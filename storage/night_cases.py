"""Transaction-scoped primitives for Night Case, never a game-rules engine.

The application must acquire operation_fence and verify a usable principal and ACL
BEFORE calling ANY read/replay method. It owns Database.transaction(), ordering
room/mode locks before lock_game(). This repository never commits, opens another
session, calls a provider, or publishes an ORM row through a generic serializer.
JSON payloads are opaque codec-validated values; byte bounds remain enforced here.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Sequence, TypeVar
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from storage.models import (
    Game, GameCommand, NightCase, NightGameSealed, NightLobbyCommand,
    NightEvent, NightMessage, NightRenderJob, NightRendering,
    NightIntentProposal, NightEpisodeDraft, NightRewardClaim, NightRuntimeHealth, NightRuntimeOutage,
)

MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_RECORD_BYTES = 64 * 1024
MAX_KERNEL_BYTES = 16 * 1024 * 1024
_LIFECYCLES = {'lobby', 'running', 'finished', 'interrupted', 'stopped'}
T = TypeVar('T')


class NightStorageConflict(ValueError):
    """Same immutable key was supplied with different exact contents."""


class NightStorageCorruption(ValueError):
    """Stored state cannot be interpreted safely by this caller."""


def canonical_json(value: Any, *, max_bytes: int = MAX_JSON_BYTES) -> bytes:
    """Strict JSON, deterministic hashes, including distinction of bool and int."""
    def validate(item: Any, depth: int = 0) -> None:
        if depth > 80:
            raise ValueError('night_json_depth')
        if item is None or type(item) in (str, bool, int, float):
            return
        if type(item) is list:
            for part in item:
                validate(part, depth + 1)
            return
        if type(item) is dict and all(type(k) is str for k in item):
            for part in item.values():
                validate(part, depth + 1)
            return
        raise ValueError('night_json_type')
    validate(value)
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
    if len(encoded) > max_bytes:
        raise ValueError('night_json_size')
    return encoded


def json_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def command_key(game_id: str, actor_key: str, client_command_id: str) -> str:
    if not all(type(v) is str and v for v in (game_id, actor_key, client_command_id)):
        raise ValueError('night_command_key')
    return json_hash(['night-case-command/1', game_id, actor_key, client_command_id])


def public_envelope(case_ref: dict[str, Any], lifecycle: str, projection: dict[str, Any]) -> dict[str, Any]:
    if set(case_ref) != {'id', 'version', 'hash'} or lifecycle not in _LIFECYCLES:
        raise ValueError('night_public_envelope')
    if type(case_ref['id']) is not str or type(case_ref['version']) is not int or case_ref['version'] < 1:
        raise ValueError('night_case_ref')
    if type(case_ref['hash']) is not str or len(case_ref['hash']) != 64:
        raise ValueError('night_case_hash')
    # Projection schema itself belongs to the typed domain/application codec.
    if type(projection) is not dict:
        raise ValueError('night_public_projection')
    value = {'storage_version': 1, 'case_ref': case_ref, 'lifecycle': lifecycle, 'public_projection': projection}
    return json.loads(canonical_json(value, max_bytes=MAX_RECORD_BYTES))


def _record_values(row: Any) -> dict[str, Any]:
    values = {col.key: getattr(row, col.key) for col in row.__table__.columns
              if col.key in row.__dict__ or (col.default is None and col.server_default is None)}
    for key, val in values.items():
        if isinstance(val, (dict, list)):
            canonical_json(val, max_bytes=MAX_KERNEL_BYTES if key == 'kernel' else (MAX_JSON_BYTES if key == 'content' else MAX_RECORD_BYTES))
    return values


def _exact(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    return value


@dataclass(frozen=True)
class CommandReceipt:
    id: str
    payload_hash: str
    result: dict[str, Any]
    status: str


@dataclass(frozen=True)
class SealedGame:
    game: Game
    sealed: NightGameSealed
    shared: bool = False  # read without FOR UPDATE: writes through it are refused


class NightCaseRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def _insert_exact(self, row: T) -> T:
        values = _record_values(row)
        model = type(row)
        table = row.__table__
        keys = {col.key: values[col.key] for col in table.primary_key.columns}
        stmt = insert(model).values(**values).on_conflict_do_nothing(index_elements=list(keys)).returning(model)
        inserted = (await self.session.execute(stmt)).scalar_one_or_none()
        if inserted is not None:
            return inserted
        existing = (await self.session.execute(select(model).filter_by(**keys).execution_options(populate_existing=True))).scalar_one()
        old = {key: getattr(existing, key) for key in values}
        if canonical_json({k: _exact(v) for k, v in old.items()}, max_bytes=MAX_KERNEL_BYTES + MAX_JSON_BYTES) != canonical_json({k: _exact(v) for k, v in values.items()}, max_bytes=MAX_KERNEL_BYTES + MAX_JSON_BYTES):
            raise NightStorageConflict(f'{table.name}_immutable_conflict')
        return existing

    async def register_case(self, row: NightCase) -> NightCase:
        if json_hash(row.content) != row.content_hash:
            raise ValueError('night_content_hash')
        return await self._insert_exact(row)

    async def get_case(self, case_id: str, version: int) -> NightCase | None:
        return await self.session.get(NightCase, (case_id, version))

    async def case_pin(self, case_id: str, version: int):
        """``(content_hash, validation_report)`` of a registered case without its content.

        Plain columns, not an entity, so no partially loaded NightCase enters the
        identity map. Content of a row is immutable (``night_history_immutable``).
        """
        return (await self.session.execute(select(NightCase.content_hash, NightCase.validation_report).where(
            NightCase.case_id == case_id, NightCase.version == version))).one_or_none()

    async def lock_game(self, game_id: str, *, shared: bool = False, snapshot: bool = False) -> SealedGame | None:
        """Read the Game and sealed rows, locking them until the end of the transaction.

        Default ``FOR UPDATE`` is for writers. ``shared=True`` takes ``FOR SHARE``:
        it still excludes every writer for the whole transaction, but readers of
        one game no longer queue behind each other. ``snapshot=True`` takes no row
        lock at all; only for callers whose result is a function of the sealed row
        plus immutable or append-only rows (see ``get_view``). Shared and snapshot
        results refuse every write through them.
        """
        def statement(model, column):
            query = select(model).where(column == game_id)
            if not snapshot:
                query = query.with_for_update(read=shared)
            return query.execution_options(populate_existing=True)
        game = (await self.session.execute(statement(Game, Game.id))).scalar_one_or_none()
        if game is None or game.mode != 'night_case':
            return None
        sealed = (await self.session.execute(statement(NightGameSealed, NightGameSealed.game_id))).scalar_one_or_none()
        if sealed is None:
            raise NightStorageCorruption('night_sealed_missing')
        return SealedGame(game, sealed, shared or snapshot)

    async def create_sealed(self, row: NightGameSealed) -> NightGameSealed:
        if json_hash(row.rules) != row.rules_hash:
            raise ValueError('night_rules_hash')
        return await self._insert_exact(row)

    async def write_snapshot(self, locked: SealedGame, *, expected_storage_revision: int,
                             kernel: dict[str, Any] | None, lobby: dict[str, Any] | None,
                             snapshot_hash: str, lifecycle: str,
                             interruption: dict[str, Any] | None = None) -> int:
        if lifecycle not in _LIFECYCLES:
            raise ValueError('night_lifecycle')
        canonical_json(kernel, max_bytes=MAX_KERNEL_BYTES)
        canonical_json(lobby, max_bytes=MAX_RECORD_BYTES)
        canonical_json(interruption, max_bytes=MAX_RECORD_BYTES)
        if locked.shared:
            raise NightStorageCorruption('night_shared_lock_write')
        if locked.sealed.storage_revision != expected_storage_revision:
            raise NightStorageConflict('night_storage_revision')
        if len(snapshot_hash) != 64:
            raise ValueError('night_snapshot_hash')
        row = locked.sealed
        row.kernel, row.lobby = kernel, lobby
        row.snapshot_hash, row.lifecycle, row.interruption = snapshot_hash, lifecycle, interruption
        row.storage_revision += 1
        await self.session.flush()
        return row.storage_revision

    async def sync_public(self, locked: SealedGame, *, projection: dict[str, Any],
                          phase: str, public_revision: int) -> bool:
        if locked.shared:
            raise NightStorageCorruption('night_shared_lock_write')
        row, sealed = locked.game, locked.sealed
        envelope = public_envelope({'id': sealed.case_id, 'version': sealed.version, 'hash': sealed.content_hash}, sealed.lifecycle, projection)
        changed = canonical_json(row.state) != canonical_json(envelope)
        if changed:
            row.state, row.status, row.phase, row.revision = envelope, sealed.lifecycle, phase, public_revision
            await self.session.flush()
        return changed

    async def lobby_receipt(self, room_id: str, actor_id: UUID, command_id: str,
                            fingerprint: str) -> NightLobbyCommand | None:
        row = await self.session.get(NightLobbyCommand, (room_id, actor_id, command_id))
        if row is not None and row.fingerprint != fingerprint:
            raise NightStorageConflict('night_lobby_command_conflict')
        return row

    async def put_lobby_receipt(self, row: NightLobbyCommand) -> NightLobbyCommand:
        return await self._insert_exact(row)

    async def command_receipt(self, game_id: str, actor_key: str, client_command_id: str,
                              payload_hash: str) -> CommandReceipt | None:
        row = await self.session.get(GameCommand, command_key(game_id, actor_key, client_command_id))
        if row is None:
            return None
        if row.payload.get('payload_hash') != payload_hash:
            raise NightStorageConflict('night_command_conflict')
        return CommandReceipt(row.id, payload_hash, row.result, row.status)

    async def put_command_receipt(self, *, game_id: str, actor_key: str,
                                  actor_account_id: UUID | None, client_command_id: str,
                                  kind: str, payload: dict[str, Any], result: dict[str, Any],
                                  status: str, now: datetime) -> CommandReceipt:
        fingerprint = json_hash(payload)
        canonical_json(result, max_bytes=MAX_RECORD_BYTES)
        row = GameCommand(id=command_key(game_id, actor_key, client_command_id), game_id=game_id,
                          actor_user_id=None, actor_account_id=actor_account_id, kind=kind,
                          expected_revision=None, payload={'client_command_id': client_command_id,
                          'actor_key': actor_key, 'command': payload, 'payload_hash': fingerprint},
                          result=result, status=status, error=None, created_at=now, processed_at=now)
        row = await self._insert_exact(row)
        return CommandReceipt(row.id, fingerprint, row.result, row.status)

    async def append_events(self, rows: Sequence[NightEvent]) -> None:
        for row in rows:
            await self._insert_exact(row)

    async def append_messages(self, rows: Sequence[NightMessage]) -> None:
        for row in rows:
            import unicodedata
            if not (1 <= len(row.text) <= 1000) or len(row.text.encode('utf-8')) > 4096 or not row.text.strip() or unicodedata.normalize('NFC', row.text) != row.text or any(unicodedata.category(c) == 'Cc' and c != '\n' for c in row.text):
                raise ValueError('night_message_text')
            if hashlib.sha256(row.text.encode('utf-8')).hexdigest() != row.text_hash:
                raise ValueError('night_message_hash')
            await self._insert_exact(row)

    async def events(self, game_id: str, *, scope: str, after_seq: int = -1,
                     limit: int = 100) -> list[NightEvent]:
        # One authorized audience per call; private streams never share a cursor.
        return list((await self.session.scalars(select(NightEvent).where(
            NightEvent.game_id == game_id, NightEvent.scope == scope,
            NightEvent.audience_seq > after_seq).order_by(NightEvent.audience_seq).limit(min(max(limit, 1), 100)))).all())

    async def message(self, game_id: str, message_id: str, *, authorized_aliases: Sequence[UUID]) -> NightMessage | None:
        # SQL checks immutable recipients before selecting the body. Aliases must
        # have already been proven from canonical AccountMerge ancestry by caller.
        from sqlalchemy import or_
        if not authorized_aliases:
            return None
        clauses = [NightMessage.recipients.contains([str(actor)]) for actor in authorized_aliases]
        return (await self.session.execute(select(NightMessage).where(
            NightMessage.game_id == game_id, NightMessage.id == message_id, or_(*clauses)))).scalar_one_or_none()

    async def enqueue_render(self, row: NightRenderJob) -> NightRenderJob:
        return await self._insert_exact(row)

    async def commit_rendering(self, row: NightRendering) -> NightRendering:
        """First writer wins; callers publish only this returned committed winner."""
        if hashlib.sha256(row.text.encode('utf-8')).hexdigest() != row.content_hash:
            raise ValueError('night_rendering_hash')
        values = _record_values(row)
        await self.session.execute(insert(NightRendering).values(**values).on_conflict_do_nothing(index_elements=['job_id']))
        return (await self.session.execute(select(NightRendering).where(NightRendering.job_id == row.job_id).execution_options(populate_existing=True))).scalar_one()

    async def mark_rendering_shown(self, job_id: str, now: datetime) -> None:
        await self.session.execute(update(NightRendering).where(NightRendering.job_id == job_id,
            NightRendering.first_shown_at.is_(None)).values(first_shown_at=now))

    async def put_proposal(self, row: NightIntentProposal) -> NightIntentProposal:
        return await self._insert_exact(row)

    async def put_draft(self, row: NightEpisodeDraft) -> NightEpisodeDraft:
        return await self._insert_exact(row)

    async def put_reward(self, row: NightRewardClaim) -> NightRewardClaim:
        return await self._insert_exact(row)

    async def rendering(self, job_id: str, *, authorized_audiences: Sequence[str]) -> NightRendering | None:
        if not authorized_audiences:
            return None
        return (await self.session.execute(select(NightRendering).join(NightRenderJob).where(
            NightRendering.job_id == job_id,
            NightRenderJob.audience_key.in_(authorized_audiences)))).scalar_one_or_none()

    async def proposal(self, proposal_id: str, *, authorized_aliases: Sequence[UUID]) -> NightIntentProposal | None:
        return (await self.session.execute(select(NightIntentProposal).where(
            NightIntentProposal.proposal_id == proposal_id,
            NightIntentProposal.original_actor_account_id.in_(authorized_aliases))
            .with_for_update())).scalar_one_or_none()

    async def confirm_proposal(self, proposal: NightIntentProposal, command_id: str) -> None:
        if proposal.confirmed_command_id not in (None, command_id):
            raise NightStorageConflict('night_proposal_confirmed')
        proposal.confirmed_command_id = command_id
        await self.session.flush()

    async def claim_render_jobs(self, *, now: datetime, owner: str, lease_until: datetime,
                                max_attempts: int, limit: int = 1) -> list[NightRenderJob]:
        from sqlalchemy import or_
        rows = list((await self.session.scalars(select(NightRenderJob).where(
            NightRenderJob.status.in_(['pending', 'retry', 'leased']),
            NightRenderJob.expires_at > now, NightRenderJob.attempts < max_attempts,
            or_(NightRenderJob.retry_at.is_(None), NightRenderJob.retry_at <= now),
            or_(NightRenderJob.lease_until.is_(None), NightRenderJob.lease_until <= now))
            .order_by(NightRenderJob.job_id).limit(min(max(limit, 1), 100))
            .with_for_update(skip_locked=True))).all())
        for row in rows:
            row.status, row.lease_owner, row.lease_until = 'leased', owner, lease_until
            row.attempts += 1
        await self.session.flush()
        return rows

    async def finish_render_job(self, job_id: str, *, owner: str, now: datetime,
                                status: str, retry_at: datetime | None = None,
                                error_code: str | None = None) -> bool:
        if status not in {'completed', 'retry', 'fallback', 'failed'}:
            raise ValueError('night_job_status')
        result = await self.session.execute(update(NightRenderJob).where(
            NightRenderJob.job_id == job_id, NightRenderJob.status == 'leased',
            NightRenderJob.lease_owner == owner, NightRenderJob.lease_until > now)
            .values(status=status, lease_owner=None, lease_until=None,
                    retry_at=retry_at, sanitized_error=error_code))
        return result.rowcount == 1

    async def project_deadline(self, *, game_id: str, due_at: datetime | None,
                               timer_seq: int) -> None:
        from storage.models import GameDeadline
        deadline_id = f'night:{game_id}:phase'
        if due_at is None:
            await self.session.execute(update(GameDeadline).where(
                GameDeadline.game_id == game_id, GameDeadline.kind == 'night.phase')
                .values(status='cancelled', claimed_by=None, claimed_at=None))
            return
        values = dict(id=deadline_id, game_id=game_id, kind='night.phase', due_at=due_at,
                      status='pending', revision=timer_seq, attempts=0,
                      claimed_by=None, claimed_at=None, completed_at=None,
                      last_error_code=None, retry_at=None, quarantined_at=None)
        stmt = insert(GameDeadline).values(**values)
        await self.session.execute(stmt.on_conflict_do_update(
            constraint='uq_game_deadline_kind', set_={k: v for k, v in values.items() if k not in {'id','game_id','kind'}},
            where=GameDeadline.revision < timer_seq))

    async def put_notification(self, *, notification_id: str, game_id: str, scope: str,
                               cause_id: str, kind: str, dedupe_key: str, now: datetime) -> None:
        from storage.models import NotificationOutbox
        if not kind.startswith('night.'):
            raise ValueError('night_notification_kind')
        row = NotificationOutbox(id=notification_id, game_id=game_id, chat_id=None,
            user_id=None, kind=kind, payload={'game_id': game_id, 'scope': scope,
            'cause_id': cause_id, 'kind': kind}, dedupe_key=dedupe_key, status='pending',
            available_at=now, attempts=0, claimed_by=None, claimed_at=None,
            delivered_at=None, last_error=None, version=0, resolved_at=None)
        await self._insert_exact(row)

    async def lock_health(self, runtime_key: str) -> NightRuntimeHealth:
        from storage.models import NightRuntimeHealth
        await self.session.execute(insert(NightRuntimeHealth).values(runtime_key=runtime_key).on_conflict_do_nothing())
        return (await self.session.execute(select(NightRuntimeHealth).where(
            NightRuntimeHealth.runtime_key == runtime_key).with_for_update()
            .execution_options(populate_existing=True))).scalar_one()

    async def open_outage(self, row: NightRuntimeOutage) -> NightRuntimeOutage:
        from storage.models import NightRuntimeOutage
        if not isinstance(row, NightRuntimeOutage):
            raise TypeError('night_outage_type')
        return await self._insert_exact(row)

    async def close_outage(self, outage_id: str, ended_at: datetime) -> None:
        from storage.models import NightRuntimeOutage
        row = (await self.session.execute(select(NightRuntimeOutage).where(
            NightRuntimeOutage.outage_id == outage_id).with_for_update())).scalar_one()
        if row.ended_at is not None and row.ended_at != ended_at:
            raise NightStorageConflict('night_outage_closed')
        row.ended_at = ended_at
        await self.session.flush()

    async def outages_since(self, since: datetime) -> list[NightRuntimeOutage]:
        from sqlalchemy import or_
        from storage.models import NightRuntimeOutage
        return list((await self.session.scalars(select(NightRuntimeOutage).where(
            or_(NightRuntimeOutage.ended_at.is_(None), NightRuntimeOutage.ended_at > since))
            .order_by(NightRuntimeOutage.started_at))).all())

    async def reserve_quotas(self, reservations: Sequence['QuotaReservation']) -> bool:
        """Lock every scope in sorted order; denial never increments any counter."""
        from storage.models import NightNarratorLimit
        ordered = sorted(reservations, key=lambda q: (q.scope, q.period_start))
        if len({(q.scope, q.period_start) for q in ordered}) != len(ordered):
            raise ValueError('night_duplicate_quota_scope')
        rows = []
        for q in ordered:
            if min(q.requests, q.tokens, q.max_requests, q.max_tokens) < 0:
                raise ValueError('night_negative_quota')
            await self.session.execute(insert(NightNarratorLimit).values(
                scope=q.scope, period_start=q.period_start).on_conflict_do_nothing())
            row = (await self.session.execute(select(NightNarratorLimit).where(
                NightNarratorLimit.scope == q.scope,
                NightNarratorLimit.period_start == q.period_start).with_for_update())).scalar_one()
            rows.append((q, row))
        if any(row.reserved_requests + q.requests > q.max_requests or
               row.reserved_tokens + q.tokens > q.max_tokens for q, row in rows):
            return False
        for q, row in rows:
            row.reserved_requests += q.requests
            row.reserved_tokens += q.tokens
        await self.session.flush()
        return True


@dataclass(frozen=True)
class QuotaReservation:
    scope: str
    period_start: datetime
    requests: int
    tokens: int
    max_requests: int
    max_tokens: int
