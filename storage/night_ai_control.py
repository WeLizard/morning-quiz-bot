"""Transaction-scoped Night AI control storage, without provider/HTTP I/O.

The service owns shared operation_fence, principal/ACL and replay ordering. This
repository never starts/commits a transaction or interprets a game-rule command.
All AI mutations share AI_CONFIG_LOCK before Game/control/profile/credential locks.
"""
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select, text, true
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import aliased

from storage.models import Game, NightGameSealed, NightIntentProposal
from storage.night_ai_models import (
    NightAIBinding, NightAICredential, NightAIGameControl, NightAIOperation,
    NightAIProfile, NightAIProfileRevision, NightAIRequest, NightAIIntentRequest,
)


AI_CONFIG_LOCK = 7319480048


@dataclass(frozen=True)
class LockedAIControl:
    game: Game
    sealed: NightGameSealed
    control: NightAIGameControl | None


class NightAIControlRepository:
    def __init__(self, session):
        self.session = session

    async def config_lock(self):
        await self.session.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': AI_CONFIG_LOCK})

    async def ensure_empty_lobby_control_locked(self, game_id, now):
        """Only initial insert under caller's Game lock; never acquires AI lock."""
        await self.session.execute(insert(NightAIGameControl).values(game_id=game_id,
            epoch=0, starter_account_id=None, current_binding_id=None, updated_at=now).on_conflict_do_nothing(index_elements=['game_id']))
        row = await self.row(NightAIGameControl, NightAIGameControl.game_id == game_id, lock=True)
        if row.epoch != 0 or row.starter_account_id is not None or row.current_binding_id is not None:
            raise ValueError('night_ai_initial_control_conflict')
        return row

    async def finalize_authored_starter_locked(self, game_id, starter, now):
        """Initial identity only, after A validation; epoch0, no grant/request/AI lock."""
        row = await self.row(NightAIGameControl, NightAIGameControl.game_id == game_id, lock=True)
        if row is None:
            return
        if row.epoch != 0:
            return  # A trusted start callback has already initialized the mode.
        if row.current_binding_id is not None or row.starter_account_id not in (None, starter):
            raise ValueError('night_ai_initial_control_conflict')
        row.starter_account_id, row.updated_at = starter, now
        await self.session.flush()

    async def intent_rows(self, game_id, actors, request_id):
        # Both namespaces must come from one READ COMMITTED statement snapshot.
        # A finalize can atomically insert the ordinary proposal and finalize the
        # prepared row between two separate SELECTs.
        ordinary_source = (select(NightIntentProposal).where(
            NightIntentProposal.game_id == game_id, NightIntentProposal.original_actor_account_id.in_(actors),
            NightIntentProposal.request_id == request_id).order_by(NightIntentProposal.proposal_id).limit(2).subquery())
        prepared_source = (select(NightAIIntentRequest).where(
            NightAIIntentRequest.game_id == game_id, NightAIIntentRequest.requester_account_id.in_(actors),
            NightAIIntentRequest.client_request_id == request_id).order_by(NightAIIntentRequest.id).limit(2).subquery())
        ordinary_row = aliased(NightIntentProposal, ordinary_source)
        prepared_row = aliased(NightAIIntentRequest, prepared_source)
        rows = (await self.session.execute(select(ordinary_row, prepared_row).select_from(
            ordinary_source.join(prepared_source, true(), full=True))
            .execution_options(populate_existing=True))).all()
        ordinary = {row.proposal_id: row for row, _ in rows if row is not None}
        prepared = {row.id: row for _, row in rows if row is not None}
        return list(ordinary.values()), list(prepared.values())

    async def intent(self, request_id, *, lock=False):
        return await self.row(NightAIIntentRequest, NightAIIntentRequest.id == request_id, lock=lock)

    async def row(self, model, *criteria, lock=False):
        query = select(model).where(*criteria).execution_options(populate_existing=True)
        if lock:
            query = query.with_for_update()
        return await self.session.scalar(query)

    async def lock_game(self, game_id) -> LockedAIControl | None:
        game = await self.row(Game, Game.id == game_id, lock=True)
        if game is None or game.mode != 'night_case':
            return None
        sealed = await self.row(NightGameSealed, NightGameSealed.game_id == game_id, lock=True)
        if sealed is None:
            return None
        control = await self.row(NightAIGameControl, NightAIGameControl.game_id == game_id, lock=True)
        return LockedAIControl(game, sealed, control)

    async def operation(self, subjects, request_id):
        return list((await self.session.scalars(select(NightAIOperation).where(
            NightAIOperation.principal_subject.in_(subjects), NightAIOperation.client_request_id == request_id,
        ).execution_options(populate_existing=True))).all())

    async def pending(self, game_id):
        return await self.row(NightAIRequest, NightAIRequest.game_id == game_id,
                              NightAIRequest.status == 'pending', lock=True)

    async def binding(self, binding_id, *, lock=True):
        return await self.row(NightAIBinding, NightAIBinding.id == binding_id, lock=lock)

    async def credential(self, credential_id, *, lock=True):
        return await self.row(NightAICredential, NightAICredential.id == credential_id, lock=lock)

    async def profile_revision(self, profile_id: UUID, revision: int, *, lock=True):
        profile = await self.row(NightAIProfile, NightAIProfile.id == profile_id, lock=lock)
        snapshot = await self.row(NightAIProfileRevision, NightAIProfileRevision.profile_id == profile_id,
                                  NightAIProfileRevision.revision == revision)
        return profile, snapshot

    async def active_profile_bindings(self, profile_id):
        return list((await self.session.scalars(select(NightAIBinding).where(
            NightAIBinding.profile_id == profile_id, NightAIBinding.status == 'active',
        ).order_by(NightAIBinding.game_id, NightAIBinding.id).execution_options(populate_existing=True))).all())

    async def requests_since(self, game_id, since: datetime):
        return list((await self.session.scalars(select(NightAIRequest).where(
            NightAIRequest.game_id == game_id, NightAIRequest.created_at >= since,
        ).order_by(NightAIRequest.created_at.desc()).execution_options(populate_existing=True))).all())

    async def record(self, **values):
        row = NightAIOperation(**values)
        self.session.add(row)
        await self.session.flush()
        return row
