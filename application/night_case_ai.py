"""Night AI control plane; caller owns the database transaction.

No transport, model calls, game-rule transitions or dispatch quota reservations.
On failure the caller must roll back its transaction. No method commits. A future
orchestrator must replay the FULL start before acquire_start_config, then acquire
the Game lock and call start_in_locked_game before A's first domain persistence.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from functools import wraps
from uuid import UUID, uuid4

from sqlalchemy import inspect, select

from application.night_case import historical_aliases
from config.night_case_ai import ProfileRevision, build_profile
from storage.admin_actions import operation_fence
from storage.models import Account, Game, GamePlayer, Room, RoomMembership, NightRenderJob
from storage.night_ai import CredentialContext, Fingerprint, SealedSecret, VaultUnavailable, canonical, subject
from storage.night_ai_control import LockedAIControl, NightAIControlRepository
from storage.night_ai_dispatch import NightAIDispatchRepository, ACTIVE
from storage.night_ai_models import (
    NightAIBinding, NightAICredential, NightAIGameControl, NightAIProfile,
    NightAIProfileRevision, NightAIRequest, NightAIDispatchAttempt, NightAIIntentRequest,
)
from storage.notifications import NotificationQueue


class NightAIControlError(ValueError):
    def __init__(self, code, status=409, retry_after_seconds=None):
        self.code, self.status, self.retry_after_seconds = code, status, retry_after_seconds
        super().__init__(code)


# Ownership/lifetime of an AI grant follows participation, not gameplay action
# eligibility. Domain available_actions/step continue to decide allowed actions.
AI_PARTICIPATING_STATUSES=frozenset({'active','fog','ghost'})


@dataclass(frozen=True)
class AdminPrincipal:
    """Trusted adapter constructs this AFTER existing admin auth and CSRF checks."""
    deployment_id: str
    account_id: UUID | None = None

    def __post_init__(self):
        subject('admin:' + self.deployment_id + ':operator')
        if self.account_id is not None and not isinstance(self.account_id, UUID):
            raise ValueError('night_ai_subject_invalid')

    @property
    def subject(self):
        return 'admin:' + self.deployment_id + ':operator'


@dataclass(frozen=True)
class BindingCaps:
    requests_per_day: int = 60
    reserved_tokens_per_day: int = 120000
    total_requests: int = 420
    total_reserved_tokens: int = 840000
    max_output_tokens: int = 800

    def __post_init__(self):
        maxima = (60, 120000, 420, 840000, 800)
        if any(type(v) is not int or not 1 <= v <= maximum for v, maximum in zip(asdict(self).values(), maxima)):
            raise NightAIControlError('invalid_config', 422)

    def document(self):
        return {'schema': 'night-ai-caps/1', **asdict(self)}

    @classmethod
    def decode(cls, value):
        if type(value) is not dict or set(value) != set(cls().document()) or value.get('schema') != 'night-ai-caps/1':
            raise NightAIControlError('invalid_config', 422)
        return cls(**{k: v for k, v in value.items() if k != 'schema'})


_POINTERS = {'night_ai_approval_requested': ('admin:night_ai', 'night-ai-request:'),
             'night_ai_cleanup': ('system:night_ai_cleanup', 'night-ai-cleanup:')}


@dataclass(frozen=True)
class ControlPointer:
    game_id: str
    scope: str
    cause_id: UUID
    kind: str

    def __post_init__(self):
        if (type(self.game_id) is not str or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,64}', self.game_id)
                or not isinstance(self.cause_id, UUID) or self.kind not in _POINTERS
                or self.scope != _POINTERS[self.kind][0]):
            raise NightAIControlError('invalid_pointer', 422)

    def document(self):
        return {'game_id': self.game_id, 'scope': self.scope, 'cause_id': str(self.cause_id), 'kind': self.kind}

    @classmethod
    def decode(cls, payload, *, row_kind, row_game_id):
        try:
            if type(payload) is not dict or set(payload) != {'game_id', 'scope', 'cause_id', 'kind'}:
                raise ValueError
            if payload['kind'] != row_kind or payload['game_id'] != row_game_id or str(UUID(payload['cause_id'])) != payload['cause_id']:
                raise ValueError
            return cls(payload['game_id'], payload['scope'], UUID(payload['cause_id']), payload['kind'])
        except (ValueError, TypeError, KeyError, AttributeError):
            raise NightAIControlError('invalid_pointer', 422) from None


def byok_audience_allowed(owner: UUID, audience_key: str, private_context_accounts: frozenset[UUID]) -> bool:
    """Trusted context classifier supplies ALL private accounts, never client input."""
    if not isinstance(owner, UUID) or type(private_context_accounts) is not frozenset or any(not isinstance(x, UUID) for x in private_context_accounts):
        return False
    return ((audience_key == 'public' and not private_context_accounts)
            or (audience_key == 'account:' + str(owner) and private_context_accounts <= {owner}))


def _fenced(method):
    @wraps(method)
    async def call(self, *args, **kwargs):
        await operation_fence(self.session)
        async with self.session.begin_nested():
            return await method(self, *args, **kwargs)
    return call


def _uuid(value):
    if not isinstance(value, UUID):
        raise NightAIControlError('invalid_config', 422)
    return value


def _epoch(value):
    if type(value) is not int or value < 0:
        raise NightAIControlError('invalid_config', 422)
    return value


def _secret(value):
    if type(value) is not bytes or not 1 <= len(value) <= 8192 or any(c in value for c in (b'\r', b'\n', b'\0')):
        raise NightAIControlError('invalid_config', 422)
    return base64.b64encode(value).decode('ascii')


class NightAIControlService:
    def __init__(self, session, clock, registry, vault, receipts, *, environment_id, original_starter_resolver=None):
        self.session, self.clock, self.registry = session, clock, registry
        self.vault, self.receipts, self.environment_id = vault, receipts, environment_id
        self.repo = NightAIControlRepository(session)
        self._start_guard = None
        self.original_starter_resolver = original_starter_resolver

    def _now(self):
        value = self.clock()
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise NightAIControlError('clock_unavailable', 503)
        return value

    async def _account(self, account_id):
        if not isinstance(account_id, UUID):
            raise NightAIControlError('account_unavailable', 403)
        row = await self.session.get(Account, account_id, populate_existing=True)
        if row is None or row.archived or row.bot_blocked or row.merged_into_id is not None:
            raise NightAIControlError('account_unavailable', 403)
        return row

    async def _admin(self, principal):
        if type(principal) is not AdminPrincipal:
            raise NightAIControlError('operator_required', 403)
        if principal.account_id is not None:
            await self._account(principal.account_id)
        return principal.subject

    async def _account_scope(self, account_id, game_id):
        await self._account(account_id)
        aliases = await historical_aliases(self.session, account_id)
        game = await self.repo.row(Game, Game.id == game_id)
        if game is None or game.mode != 'night_case':
            raise NightAIControlError('not_found', 404)
        seat = await self.session.scalar(select(GamePlayer.game_id).where(
            GamePlayer.game_id == game_id, GamePlayer.account_id.in_(aliases)).limit(1))
        if seat is None:
            room = await self.repo.row(Room, Room.id == game.room_id)
            member = await self.repo.row(RoomMembership, RoomMembership.room_id == game.room_id,
                                         RoomMembership.account_id == account_id, RoomMembership.status == 'active')
            if game.status != 'lobby' or room is None or room.owner_account_id != account_id or member is None:
                raise NightAIControlError('not_found', 404)
        return ('account:' + str(account_id),) + tuple('account:' + str(a) for a in sorted(aliases - {account_id}, key=str))

    async def _replay(self, subjects, request_id, operation, target, body, key_bearing):
        rows = await self.repo.operation(subjects, request_id)
        for row in rows:
            if (row.operation == operation and row.target_id == target and self.receipts.verify(
                    body, Fingerprint(row.fingerprint, row.fingerprint_version), key_bearing=key_bearing)):
                return {'replayed': True, 'result': copy.deepcopy(row.safe_result)}
        if rows:
            raise NightAIControlError('idempotency_conflict')
        return None

    async def _begin(self, subjects, request_id, operation, target, payload, *, key_bearing=False):
        if type(request_id) is not str or not 8 <= len(request_id) <= 96 or any(ord(c) < 33 or ord(c) > 126 for c in request_id):
            raise NightAIControlError('invalid_config', 422)
        body = {'operation': operation, 'target': target, 'payload': payload}
        canonical(body)
        replay = await self._replay(subjects, request_id, operation, target, body, key_bearing)
        if replay is not None:
            return replay, None
        await self.repo.config_lock()
        replay = await self._replay(subjects, request_id, operation, target, body, key_bearing)
        if replay is not None:
            return replay, None
        try:
            fingerprint = self.receipts.create(body, key_bearing=key_bearing)
        except VaultUnavailable:
            raise NightAIControlError('ai_unavailable', 503) from None
        return None, (subjects[0], request_id, operation, target, fingerprint)

    async def _finish(self, operation, result, now):
        canonical(result, limit=8192)
        principal, request_id, kind, target, fingerprint = operation
        await self.repo.record(principal_subject=principal, client_request_id=request_id, operation=kind,
                               target_id=target, fingerprint=fingerprint.digest, fingerprint_version=fingerprint.version,
                               safe_result=copy.deepcopy(result), created_at=now)
        return {'replayed': False, 'result': result}

    async def _locked(self, game_id):
        locked = await self.repo.lock_game(game_id)
        if locked is None:
            raise NightAIControlError('not_found', 404)
        return locked

    async def _running_starter(self, locked, account_id, expected_epoch):
        control = locked.control
        if control is None and expected_epoch==0:
            if self.original_starter_resolver is None or locked.sealed.lifecycle!='running':
                raise NightAIControlError('starter_unproven')
            try:
                starter=await self.original_starter_resolver(locked)
            except ValueError:
                raise NightAIControlError('starter_unproven') from None
            if starter!=account_id: raise NightAIControlError('not_found',404)
            control=NightAIGameControl(game_id=locked.game.id,starter_account_id=starter,
                epoch=0,current_binding_id=None,updated_at=self._now())
            self.session.add(control)
            await self.session.flush()
        if control is None or control.starter_account_id != account_id:
            raise NightAIControlError('not_found', 404)
        if control.epoch != _epoch(expected_epoch):
            raise NightAIControlError('stale_epoch')
        if locked.sealed.lifecycle != 'running' or locked.game.status != 'running':
            raise NightAIControlError('game_not_running')
        await self._account(account_id)
        seat = await self.repo.row(GamePlayer, GamePlayer.game_id == locked.game.id,
                                   GamePlayer.account_id == account_id)
        if seat is None or seat.status not in AI_PARTICIPATING_STATUSES:
            raise NightAIControlError('not_found', 404)
        return control

    async def _lobby_owner(self, locked, account_id):
        if locked.sealed.lifecycle != 'lobby' or locked.game.status != 'lobby':
            raise NightAIControlError('game_not_lobby')
        room = await self.repo.row(Room, Room.id == locked.game.room_id)
        member = await self.repo.row(RoomMembership, RoomMembership.room_id == locked.game.room_id,
                                     RoomMembership.account_id == account_id, RoomMembership.status == 'active')
        if room is None or room.owner_account_id != account_id or member is None:
            raise NightAIControlError('not_found', 404)

    async def _ensure_control(self, locked, now):
        if locked.control is not None:
            return locked.control
        row = NightAIGameControl(game_id=locked.game.id, epoch=0, current_binding_id=None,
                                 starter_account_id=None, updated_at=now)
        self.session.add(row)
        await self.session.flush()
        return row

    async def _notify(self, game_id, cause_id, kind, now):
        pointer = ControlPointer(game_id, _POINTERS[kind][0], cause_id, kind)
        payload = pointer.document()
        ControlPointer.decode(payload, row_kind=kind, row_game_id=game_id)
        await NotificationQueue.enqueue_in(self.session, kind=kind, game_id=game_id, payload=payload,
            dedupe_key=_POINTERS[kind][1] + str(cause_id), available_at=now)

    async def _erase(self, credential, now):
        if credential is not None and credential.scope == 'game' and credential.status != 'erased':
            credential.status, credential.erased_at = 'erased', now
            credential.key_id = credential.nonce = credential.ciphertext = credential.aad_version = None

    async def _close_binding(self, binding, status, now):
        if binding is None or binding.status != 'active':
            return
        credential=None
        if binding.mode == 'byok':
            _, revision = await self.repo.profile_revision(binding.profile_id, binding.profile_revision)
            if revision is None:
                raise NightAIControlError('config_unavailable', 503)
            credential=await self.repo.credential(revision.credential_id)
        # Source before attempt, and cancellation/slot flush BEFORE terminal
        # binding:0050 forbids any later mutation of that terminal binding.
        attempt=await self.session.scalar(select(NightAIDispatchAttempt).where(
            NightAIDispatchAttempt.binding_id==binding.id,NightAIDispatchAttempt.status.in_(ACTIVE)))
        source=None
        if attempt is not None:
            model=NightAIIntentRequest if attempt.source_kind=='intent' else NightRenderJob
            source=await self.session.scalar(select(model).where(
                (model.id==attempt.intent_id) if attempt.source_kind=='intent' else (model.job_id==attempt.job_id)).with_for_update())
        await NightAIDispatchRepository(self.session).cancel_binding(binding.id,now=now,error_code='stale')
        if isinstance(source,NightAIIntentRequest) and source.status=='prepared':
            source.status,source.finalized_at,source.safe_result='cancelled',now,{'kind':'clarification','code':'choose_available_action'}
        binding.status, binding.closed_at = status, now
        binding.inflight_job_id = binding.inflight_lease_until = binding.inflight_permit_id = None
        await self._erase(credential,now)
        await self._notify(binding.game_id, binding.id, 'night_ai_cleanup', now)
        await self.session.flush()

    async def _switch(self, control, now):
        if control.current_binding_id is not None:
            await self._close_binding(await self.repo.binding(control.current_binding_id), 'superseded', now)
        pending = await self.repo.pending(control.game_id)
        if pending is not None:
            pending.status, pending.reason, pending.decided_at = 'cancelled', 'superseded', now
        control.current_binding_id = None
        control.epoch += 1
        control.updated_at = now
        await self.session.flush()

    async def _rate_request(self, game_id, now):
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        requests = await self.repo.requests_since(game_id, midnight - timedelta(minutes=5))
        if sum(row.created_at >= midnight for row in requests) >= 3:
            raise NightAIControlError('request_limit', 429, int((midnight + timedelta(days=1) - now).total_seconds()))
        if requests and requests[0].created_at + timedelta(minutes=5) > now:
            raise NightAIControlError('request_cooldown', 429, max(1, int((requests[0].created_at + timedelta(minutes=5) - now).total_seconds())))

    async def _new_request(self, control, account_id, now):
        request = NightAIRequest(id=uuid4(), game_id=control.game_id, epoch=control.epoch,
            requester_account_id=account_id, status='pending', created_at=now, expires_at=now + timedelta(hours=24))
        self.session.add(request)
        await self.session.flush()
        await self._notify(control.game_id, request.id, 'night_ai_approval_requested', now)
        return {'epoch': control.epoch, 'request_id': str(request.id), 'request_status': 'pending',
                'expires_at': request.expires_at.isoformat()}

    async def _new_credential(self, *, scope, owner, game_id, preset, secret, status, expires_at, now):
        credential_id = uuid4()
        context = CredentialContext(self.environment_id, credential_id, scope, owner, game_id, preset)
        try:
            sealed = self.vault.encrypt(secret, context)
        except VaultUnavailable:
            raise NightAIControlError('ai_unavailable', 503) from None
        credential = NightAICredential(id=credential_id, scope=scope, owner_subject=owner, game_id=game_id,
            preset=preset, status=status, key_id=sealed.key_id, nonce=sealed.nonce, ciphertext=sealed.ciphertext,
            aad_version=sealed.aad_version, created_at=now, expires_at=expires_at)
        self.session.add(credential)
        await self.session.flush()
        return credential

    def _build(self, settings, credential_id, *, byok=False):
        allowed = {'preset', 'model_id', 'adapter', 'auth_mode', 'project_fields', 'routing',
                   'temperature', 'max_output_tokens', 'json_output', 'endpoint_policy'}
        if type(settings) is not dict or set(settings) - allowed or not {'preset', 'model_id'} <= set(settings):
            raise NightAIControlError('invalid_config', 422)
        options = copy.deepcopy(settings)
        if 'endpoint_policy' in options:
            if type(options['endpoint_policy']) is not list or len(options['endpoint_policy']) != 2:
                raise NightAIControlError('invalid_config', 422)
            options['endpoint_policy'] = tuple(options['endpoint_policy'])
        try:
            # Driver UUID subclasses are normalized at this owning boundary;
            # the accepted immutable config codec keeps its strict DTO types.
            canonical_credential_id = UUID(str(credential_id)) if credential_id is not None else None
            return build_profile(registry=self.registry, credential_id=canonical_credential_id, byok=byok, **options)
        except (ValueError, TypeError):
            raise NightAIControlError('invalid_config', 422) from None

    async def _grant(self, control, profile, revision, *, mode, granted_by, caps, now):
        try:
            decoded = ProfileRevision.decode(revision.config, self.registry, byok=mode == 'byok')
        except ValueError:
            raise NightAIControlError('config_unavailable', 503) from None
        if not profile.enabled or decoded.config_hash != revision.config_hash:
            raise NightAIControlError('profile_disabled')
        credential = await self.repo.credential(revision.credential_id) if revision.credential_id else None
        if revision.credential_id and (credential is None or credential.status != 'usable'
                or (credential.expires_at is not None and credential.expires_at <= now)):
            raise NightAIControlError('credential_unavailable')
        if (decoded.document()['credential_id'] != (str(revision.credential_id) if revision.credential_id else None)
                or (credential is not None and (credential.preset != decoded.document()['preset']
                    or credential.scope != profile.scope or credential.game_id != profile.game_id))):
            raise NightAIControlError('config_unavailable', 503)
        if mode == 'byok' and (profile.scope != 'game' or profile.game_id != control.game_id or credential is None
                or credential.scope != 'game' or credential.game_id != control.game_id
                or credential.owner_subject != 'account:' + str(control.starter_account_id)):
            raise NightAIControlError('not_found', 404)
        if mode == 'admin' and profile.scope != 'admin':
            raise NightAIControlError('not_found', 404)
        valid_until = min(now + timedelta(days=30), credential.expires_at) if credential and credential.expires_at else now + timedelta(days=30)
        binding = NightAIBinding(id=uuid4(), game_id=control.game_id, epoch=control.epoch, mode=mode,
            profile_id=profile.id, profile_revision=revision.revision, config_hash=revision.config_hash,
            granted_by_subject=granted_by, status='active', valid_until=valid_until,
            caps=caps.document(), health='ok', created_at=now)
        self.session.add(binding)
        await self.session.flush()
        control.current_binding_id, control.updated_at = binding.id, now
        return binding

    @_fenced
    async def ensure_lobby_control(self, *, account_id, game_id):
        await self._account_scope(account_id, game_id)
        await self.repo.config_lock()
        locked = await self._locked(game_id)
        await self._lobby_owner(locked, account_id)
        row = await self._ensure_control(locked, self._now())
        return {'epoch': row.epoch}

    @_fenced
    async def request_admin(self, *, account_id, game_id, expected_epoch, client_request_id):
        subjects = await self._account_scope(account_id, game_id)
        replay, operation = await self._begin(subjects, client_request_id, 'request_admin', game_id,
                                              {'expected_epoch': _epoch(expected_epoch)})
        if replay:
            return replay
        locked = await self._locked(game_id)
        control = await self._running_starter(locked, account_id, expected_epoch)
        now = self._now()
        await self._rate_request(game_id, now)
        await self._switch(control, now)
        return await self._finish(operation, await self._new_request(control, account_id, now), now)

    @_fenced
    async def use_authored(self, *, account_id, game_id, expected_epoch, client_request_id):
        subjects = await self._account_scope(account_id, game_id)
        replay, operation = await self._begin(subjects, client_request_id, 'use_authored', game_id,
                                              {'expected_epoch': _epoch(expected_epoch)})
        if replay:
            return replay
        locked = await self._locked(game_id)
        control = await self._running_starter(locked, account_id, expected_epoch)
        now = self._now()
        await self._switch(control, now)
        return await self._finish(operation, {'epoch': control.epoch, 'status': 'authored'}, now)

    @_fenced
    async def save_profile_revision(self, *, operator, profile_id, expected_revision, label,
                                    settings, client_request_id, secret=None):
        principal = await self._admin(operator)
        if (type(label) is not str or not label.strip() or len(label) > 80
                or type(expected_revision) is not int or expected_revision < 0
                or (profile_id is not None and not isinstance(profile_id, UUID))
                or type(settings) is not dict):
            raise NightAIControlError('invalid_config', 422)
        payload = {'expected_revision': expected_revision, 'label': label, 'settings': settings,
                   'secret': _secret(secret) if secret is not None else None}
        replay, operation = await self._begin((principal,), client_request_id, 'save_profile_revision',
                                              str(profile_id) if profile_id else 'new', payload,
                                              key_bearing=secret is not None)
        if replay:
            return replay
        now = self._now()
        previous_credential = None
        if profile_id is None:
            if expected_revision != 0:
                raise NightAIControlError('stale_revision')
            profile = NightAIProfile(id=uuid4(), scope='admin', game_id=None, label=label,
                current_revision=1, enabled=False, is_default=False, created_by_subject=principal, created_at=now)
            self.session.add(profile)
            await self.session.flush()
        else:
            profile, previous = await self.repo.profile_revision(profile_id, expected_revision)
            if profile is None or profile.scope != 'admin' or profile.created_by_subject != principal:
                raise NightAIControlError('not_found', 404)
            if profile.current_revision != expected_revision or previous is None:
                raise NightAIControlError('stale_revision')
            if previous.credential_id:
                previous_credential = await self.repo.credential(previous.credential_id)
                if previous_credential is None or previous_credential.status != 'usable':
                    raise NightAIControlError('credential_unavailable')
            profile.current_revision += 1
            profile.label = label
        credential_id = previous_credential.id if previous_credential else None
        if secret is not None:
            if type(settings) is not dict or type(settings.get('preset')) is not str:
                raise NightAIControlError('invalid_config', 422)
            credential = await self._new_credential(scope='admin', owner=principal, game_id=None,
                preset=settings['preset'], secret=secret, status='usable', expires_at=None, now=now)
            credential_id = credential.id
        elif settings.get('auth_mode') == 'none':
            credential_id = None
        if previous_credential and secret is None and credential_id and previous_credential.preset != settings.get('preset'):
            raise NightAIControlError('invalid_config', 422)
        snapshot = self._build(settings, credential_id)
        revision = NightAIProfileRevision(profile_id=profile.id, revision=profile.current_revision,
            config=snapshot.document(), config_hash=snapshot.config_hash, credential_id=credential_id,
            created_by_subject=principal, created_at=now)
        self.session.add(revision)
        return await self._finish(operation, {'profile_id': str(profile.id), 'revision': revision.revision,
            'config_hash': revision.config_hash, 'credential_configured': credential_id is not None}, now)

    @_fenced
    async def set_profile_enabled(self, *, operator, profile_id, enabled, client_request_id):
        principal = await self._admin(operator)
        _uuid(profile_id)
        if type(enabled) is not bool:
            raise NightAIControlError('invalid_config', 422)
        replay, operation = await self._begin((principal,), client_request_id, 'set_profile_enabled', str(profile_id), {'enabled': enabled})
        if replay:
            return replay
        bindings = await self.repo.active_profile_bindings(profile_id) if not enabled else []
        for game_id in sorted({b.game_id for b in bindings}):
            await self._locked(game_id)
        profile = await self.repo.row(NightAIProfile, NightAIProfile.id == profile_id, lock=True)
        if profile is None or profile.scope != 'admin' or profile.created_by_subject != principal:
            raise NightAIControlError('not_found', 404)
        profile.enabled = enabled
        if not enabled:
            profile.is_default = False
        await self.session.flush()
        now = self._now()
        for binding in bindings:
            await self._close_binding(await self.repo.binding(binding.id), 'revoked', now)
        return await self._finish(operation, {'profile_id': str(profile_id), 'enabled': enabled,
                                             'revoked_bindings': len(bindings)}, now)

    @_fenced
    async def set_default_profile(self, *, operator, profile_id, client_request_id):
        principal = await self._admin(operator)
        if profile_id is not None:
            _uuid(profile_id)
        replay, operation = await self._begin((principal,), client_request_id, 'set_default_profile',
                                              str(profile_id) if profile_id else 'none', {})
        if replay:
            return replay
        profile = await self.repo.row(NightAIProfile, NightAIProfile.id == profile_id, lock=True) if profile_id else None
        if profile_id and (profile is None or profile.scope != 'admin' or profile.created_by_subject != principal):
            raise NightAIControlError('not_found', 404)
        if profile is not None and not profile.enabled:
            raise NightAIControlError('profile_disabled')
        current = await self.repo.row(NightAIProfile, NightAIProfile.is_default.is_(True), lock=True)
        if current is not None:
            current.is_default = False
            await self.session.flush()
        if profile is not None:
            profile.is_default = True
        return await self._finish(operation, {'profile_id': str(profile_id) if profile_id else None}, self._now())

    @_fenced
    async def stage_or_activate_byok(self, *, account_id, game_id, expected_epoch, settings, secret, client_request_id):
        subjects = await self._account_scope(account_id, game_id)
        payload = {'expected_epoch': _epoch(expected_epoch), 'settings': settings, 'secret': _secret(secret)}
        replay, operation = await self._begin(subjects, client_request_id, 'stage_or_activate_byok', game_id,
                                              payload, key_bearing=True)
        if replay:
            return replay
        locked = await self._locked(game_id)
        now = self._now()
        lobby = locked.sealed.lifecycle == 'lobby'
        if lobby:
            await self._lobby_owner(locked, account_id)
            control = await self._ensure_control(locked, now)
            if control.epoch != expected_epoch:
                raise NightAIControlError('stale_epoch')
        else:
            control = await self._running_starter(locked, account_id, expected_epoch)
        if type(settings) is not dict or type(settings.get('preset')) is not str:
            raise NightAIControlError('invalid_config', 422)
        credential = await self._new_credential(scope='game', owner='account:' + str(account_id), game_id=game_id,
            preset=settings['preset'], secret=secret, status='staged' if lobby else 'usable',
            expires_at=now + (timedelta(hours=1) if lobby else timedelta(days=30)), now=now)
        snapshot = self._build(settings, credential.id, byok=True)
        profile = NightAIProfile(id=uuid4(), scope='game', game_id=game_id, label='BYOK', current_revision=1,
            enabled=True, is_default=False, created_by_subject='account:' + str(account_id), created_at=now)
        self.session.add(profile)
        await self.session.flush()
        revision = NightAIProfileRevision(profile_id=profile.id, revision=1, config=snapshot.document(),
            config_hash=snapshot.config_hash, credential_id=credential.id, created_by_subject='account:' + str(account_id), created_at=now)
        self.session.add(revision)
        await self.session.flush()
        if lobby:
            result = {'epoch': control.epoch, 'staged_credential_id': str(credential.id), 'expires_at': credential.expires_at.isoformat()}
        else:
            await self._switch(control, now)
            binding = await self._grant(control, profile, revision, mode='byok', granted_by='account:' + str(account_id), caps=BindingCaps(), now=now)
            result = {'epoch': control.epoch, 'binding_id': str(binding.id), 'status': 'ai', 'expires_at': binding.valid_until.isoformat()}
        return await self._finish(operation, result, now)

    @_fenced
    async def decide_request(self, *, operator, request_id, decision, profile_id, profile_revision,
                             caps, client_request_id):
        principal = await self._admin(operator)
        _uuid(request_id)
        if decision not in {'approve', 'deny'}:
            raise NightAIControlError('invalid_config', 422)
        if decision == 'approve':
            _uuid(profile_id)
            if type(profile_revision) is not int or profile_revision < 1:
                raise NightAIControlError('invalid_config', 422)
            limits = BindingCaps.decode(caps) if caps is not None else BindingCaps()
        else:
            if any(x is not None for x in (profile_id, profile_revision, caps)):
                raise NightAIControlError('invalid_config', 422)
            limits = None
        payload = {'decision': decision, 'profile_id': str(profile_id) if profile_id else None,
                   'profile_revision': profile_revision, 'caps': limits.document() if limits else None}
        replay, operation = await self._begin((principal,), client_request_id, 'decide_request', str(request_id), payload)
        if replay:
            return replay
        request = await self.repo.row(NightAIRequest, NightAIRequest.id == request_id)
        if request is None:
            raise NightAIControlError('not_found', 404)
        locked = await self._locked(request.game_id)
        request = await self.repo.row(NightAIRequest, NightAIRequest.id == request_id, lock=True)
        now = self._now()
        if request.status != 'pending' or request.expires_at <= now or locked.control is None or locked.control.epoch != request.epoch:
            raise NightAIControlError('request_stale')
        await self._running_starter(locked, request.requester_account_id, request.epoch)
        if decision == 'approve':
            profile, revision = await self.repo.profile_revision(profile_id, profile_revision)
            if profile is None or revision is None or profile.created_by_subject != principal:
                raise NightAIControlError('not_found', 404)
            binding = await self._grant(locked.control, profile, revision, mode='admin', granted_by=principal, caps=limits, now=now)
            request.status, request.binding_id = 'approved', binding.id
        else:
            request.status, request.reason = 'denied', 'operator_denied'
        request.decided_by_subject, request.decided_at = principal, now
        return await self._finish(operation, {'request_id': str(request_id), 'request_status': request.status,
            'binding_id': str(request.binding_id) if request.binding_id else None, 'epoch': request.epoch}, now)

    @_fenced
    async def revoke_binding(self, *, operator, binding_id, client_request_id):
        principal = await self._admin(operator)
        _uuid(binding_id)
        replay, operation = await self._begin((principal,), client_request_id, 'revoke_binding', str(binding_id), {})
        if replay:
            return replay
        binding = await self.repo.binding(binding_id, lock=False)
        if binding is None:
            raise NightAIControlError('not_found', 404)
        await self._locked(binding.game_id)
        binding = await self.repo.binding(binding_id)
        now = self._now()
        await self._close_binding(binding, 'revoked', now)
        return await self._finish(operation, {'binding_id': str(binding_id), 'status': binding.status}, now)

    @_fenced
    async def rebind_admin(self, *, operator, binding_id, expected_epoch, profile_id, profile_revision, caps, client_request_id):
        principal = await self._admin(operator)
        _uuid(binding_id)
        _uuid(profile_id)
        if type(profile_revision) is not int or profile_revision < 1:
            raise NightAIControlError('invalid_config', 422)
        limits = BindingCaps.decode(caps) if caps is not None else BindingCaps()
        payload = {'expected_epoch': _epoch(expected_epoch), 'profile_id': str(profile_id),
                   'profile_revision': profile_revision, 'caps': limits.document()}
        replay, operation = await self._begin((principal,), client_request_id, 'rebind_admin', str(binding_id), payload)
        if replay:
            return replay
        old = await self.repo.binding(binding_id, lock=False)
        if old is None:
            raise NightAIControlError('not_found', 404)
        locked = await self._locked(old.game_id)
        old = await self.repo.binding(binding_id)
        if old.status != 'active' or old.mode != 'admin' or locked.control is None or locked.control.current_binding_id != binding_id:
            raise NightAIControlError('request_stale')
        await self._running_starter(locked, locked.control.starter_account_id, expected_epoch)
        profile, revision = await self.repo.profile_revision(profile_id, profile_revision)
        if profile is None or revision is None or profile.created_by_subject != principal:
            raise NightAIControlError('not_found', 404)
        now = self._now()
        await self._switch(locked.control, now)
        binding = await self._grant(locked.control, profile, revision, mode='admin', granted_by=principal, caps=limits, now=now)
        return await self._finish(operation, {'binding_id': str(binding.id), 'epoch': binding.epoch, 'status': 'ai'}, now)

    @_fenced
    async def acquire_start_config(self, *, account_id):
        """Orchestrator calls AFTER full-start replay, BEFORE acquiring Game lock."""
        await self._account(account_id)
        await self.repo.config_lock()
        self._start_guard = (self.session.get_transaction(), account_id)

    @_fenced
    async def start_in_locked_game(self, *, account_id, locked, expected_epoch, now,
                                   mode='admin', staged_credential_id=None):
        """Trusted callback; not an independently exposed player command.

        A owns the complete start receipt/options fingerprint and must invoke
        this before its first _persist, in this SAME outer transaction. Its
        Game.started_at must already equal the trusted start timestamp. There is
        no second AI player receipt and no provider call in this callback.
        """
        if self._start_guard != (self.session.get_transaction(), account_id):
            raise NightAIControlError('start_lock_order', 503)
        if (inspect(locked.game).session is not self.session.sync_session
                or inspect(locked.sealed).session is not self.session.sync_session
                or locked.game.started_at != now or not isinstance(now, datetime)
                or now.tzinfo is None or now.utcoffset() != timedelta(0)):
            raise NightAIControlError('start_context_invalid', 503)
        if mode not in {'admin', 'authored', 'byok'} or (mode == 'byok') != (staged_credential_id is not None):
            raise NightAIControlError('invalid_config', 422)
        await self._account(account_id)
        await self._lobby_owner(locked, account_id)
        control = await self.repo.row(NightAIGameControl, NightAIGameControl.game_id == locked.game.id, lock=True)
        if control is None:
            control = await self._ensure_control(LockedAIControl(locked.game, locked.sealed, None), now)
        if control.epoch != _epoch(expected_epoch):
            raise NightAIControlError('stale_epoch')
        if control.starter_account_id is not None:
            raise NightAIControlError('already_started')
        if mode == 'admin':
            await self._rate_request(control.game_id, now)
        control.starter_account_id = account_id
        await self._switch(control, now)
        if mode == 'admin':
            return await self._new_request(control, account_id, now)
        if mode == 'authored':
            return {'epoch': control.epoch, 'status': 'authored'}
        _uuid(staged_credential_id)
        # Profile lock precedes credential lock. Staged expiry is immutable;
        # activation creates a fresh usable credential rather than extending it.
        old_revision = await self.repo.row(NightAIProfileRevision, NightAIProfileRevision.credential_id == staged_credential_id)
        if old_revision is None:
            raise NightAIControlError('not_found', 404)
        old_profile, old_revision = await self.repo.profile_revision(old_revision.profile_id, old_revision.revision)
        staged = await self.repo.credential(staged_credential_id)
        if (staged is None or staged.scope != 'game' or staged.game_id != control.game_id
                or staged.owner_subject != 'account:' + str(account_id) or staged.status != 'staged'
                or staged.expires_at <= now or old_profile.scope != 'game' or old_profile.game_id != control.game_id):
            raise NightAIControlError('not_found', 404)
        try:
            decoded = ProfileRevision.decode(old_revision.config, self.registry, byok=True)
            plaintext = self.vault.decrypt(SealedSecret(staged.key_id, staged.nonce, staged.ciphertext, staged.aad_version),
                CredentialContext(self.environment_id, UUID(str(staged.id)), staged.scope, staged.owner_subject, staged.game_id, staged.preset))
        except (ValueError, VaultUnavailable):
            raise NightAIControlError('ai_unavailable', 503) from None
        usable = await self._new_credential(scope='game', owner=staged.owner_subject, game_id=staged.game_id,
            preset=staged.preset, secret=plaintext, status='usable', expires_at=now + timedelta(days=30), now=now)
        del plaintext
        document = decoded.document()
        document['credential_id'] = str(usable.id)
        document['config_hash'] = hashlib.sha256(canonical({k: v for k, v in document.items() if k != 'config_hash'})).hexdigest()
        new_snapshot = ProfileRevision.decode(document, self.registry, byok=True)
        old_profile.current_revision += 1
        revision = NightAIProfileRevision(profile_id=old_profile.id, revision=old_profile.current_revision,
            config=new_snapshot.document(), config_hash=new_snapshot.config_hash, credential_id=usable.id,
            created_by_subject='account:' + str(account_id), created_at=now)
        self.session.add(revision)
        await self._erase(staged, now)
        await self.session.flush()
        binding = await self._grant(control, old_profile, revision, mode='byok', granted_by='account:' + str(account_id), caps=BindingCaps(), now=now)
        return {'epoch': control.epoch, 'binding_id': str(binding.id), 'status': 'ai', 'expires_at': binding.valid_until.isoformat()}

    @_fenced
    async def cleanup_game(self, *, operator, game_id, client_request_id):
        """Internal/operator maintenance recomputes eligibility, never trusts a reason.

        A future periodic worker enumerates candidates then calls this operation.
        Stale cleanup pointers must call cleanup_binding for their exact binding.
        """
        principal = await self._admin(operator)
        replay, operation = await self._begin((principal,), client_request_id, 'cleanup_game', game_id, {})
        if replay:
            return replay
        locked = await self._locked(game_id)
        now = self._now()
        starter_usable = await self._starter_usable(locked.control, game_id)
        bindings = list((await self.session.scalars(select(NightAIBinding).where(
            NightAIBinding.game_id == game_id, NightAIBinding.status == 'active').order_by(NightAIBinding.id))).all())
        closed = 0
        for candidate in bindings:
            binding = await self.repo.binding(candidate.id)
            reason = self._cleanup_reason(locked, binding, starter_usable, now)
            if reason:
                await self._close_binding(binding, 'expired' if reason == 'expired' else 'closed', now)
                closed += 1
        credentials = list((await self.session.scalars(select(NightAICredential).where(
            NightAICredential.game_id == game_id, NightAICredential.status.in_(['staged', 'usable', 'revoked'])))).all())
        erased = 0
        for candidate in credentials:
            # No profile changes here. Canonical lifecycle/expiry decides erase.
            credential = await self.repo.credential(candidate.id)
            unusable_owner = False
            if credential.status == 'staged':
                owner = await self.session.get(Account, UUID(credential.owner_subject[8:]), populate_existing=True)
                unusable_owner = owner is None or owner.archived or owner.bot_blocked or owner.merged_into_id is not None
            if (locked.sealed.lifecycle not in {'lobby', 'running'} or credential.expires_at <= now
                    or credential.status == 'revoked' or unusable_owner
                    or (credential.status != 'staged' and not starter_usable)):
                await self._erase(credential, now)
                erased += 1
        pending = await self.repo.pending(game_id)
        if pending is not None and (pending.expires_at <= now or locked.sealed.lifecycle != 'running' or not starter_usable):
            expired = pending.expires_at <= now
            pending.status, pending.decided_at = ('expired' if expired else 'cancelled'), now
            pending.reason = 'expired' if expired else 'starter_unusable' if not starter_usable else 'terminal'
        return await self._finish(operation, {'closed_bindings': closed, 'erased_credentials': erased}, now)

    async def _starter_usable(self, control, game_id):
        if control is None or control.starter_account_id is None:
            return False
        account = await self.session.get(Account, control.starter_account_id, populate_existing=True)
        seat = await self.repo.row(GamePlayer, GamePlayer.game_id == game_id, GamePlayer.account_id == control.starter_account_id)
        return account is not None and not account.archived and not account.bot_blocked and account.merged_into_id is None and seat is not None and seat.status in AI_PARTICIPATING_STATUSES

    @staticmethod
    def _cleanup_reason(locked, binding, starter_usable, now):
        if binding.status != 'active':
            return None
        if locked.sealed.lifecycle == 'interrupted':
            return 'interrupted'
        if locked.sealed.lifecycle != 'running':
            return 'terminal'
        if not starter_usable:
            return 'starter_unusable'
        if binding.valid_until <= now:
            return 'expired'
        return None

    @_fenced
    async def cleanup_binding(self, *, operator, pointer, client_request_id):
        """Dedicated consumer passes a decoded exact system pointer; no broadcasts."""
        principal = await self._admin(operator)
        if type(pointer) is not ControlPointer or pointer.kind != 'night_ai_cleanup':
            raise NightAIControlError('invalid_pointer', 422)
        replay, operation = await self._begin((principal,), client_request_id, 'cleanup_binding', str(pointer.cause_id), pointer.document())
        if replay:
            return replay
        locked = await self._locked(pointer.game_id)
        binding = await self.repo.binding(pointer.cause_id)
        if binding is None or binding.game_id != pointer.game_id:
            raise NightAIControlError('not_found', 404)
        now = self._now()
        reason = self._cleanup_reason(locked, binding, await self._starter_usable(locked.control, pointer.game_id), now)
        if reason:
            await self._close_binding(binding, 'expired' if reason == 'expired' else 'closed', now)
        return await self._finish(operation, {'binding_id': str(binding.id), 'closed': reason is not None}, now)
