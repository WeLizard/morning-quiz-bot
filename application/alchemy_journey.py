"""Account-owned expedition commands in the caller's authenticated transaction."""
from hashlib import sha256
import re

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from domain.alchemy_journey import validate_stage
from storage.alchemy import AlchemyService, load_catalog, _resolve_now
from storage.mini_app import MiniAppError
from storage.models import AlchemyClaimCommand, AlchemyStageClaim


async def journey_projection(session, account_id):
    rows = (await session.scalars(select(AlchemyStageClaim).where(
        AlchemyStageClaim.account_id == account_id).order_by(
        AlchemyStageClaim.claimed_at, AlchemyStageClaim.stage_id))).all()
    return {'catalog_revision': load_catalog().revision,
            'claims': [row.stage_id for row in rows],
            'expedition_points': sum(row.reward['points'] for row in rows),
            'claim_receipts': [{'stage_id': row.stage_id, 'campaign_id': row.campaign_id,
                'catalog_revision': row.catalog_revision, 'reward': dict(row.reward),
                'claimed_at': row.claimed_at.isoformat()} for row in rows]}


class AlchemyJourneyService:
    def __init__(self, database, session):
        self.database, self.session = database, session

    async def claim_stage(self, *, account_id, user_id=None, command_id, stage_id,
                          catalog_revision, now=None):
        if (not isinstance(command_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,64}', command_id)
                or not isinstance(stage_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', stage_id)
                or not isinstance(catalog_revision, str) or not re.fullmatch(r'[a-f0-9]{64}', catalog_revision)):
            raise MiniAppError(422, 'Некорректная команда этапа')
        session, catalog = self.session, load_catalog()
        fingerprint = sha256((stage_id + ':' + catalog_revision).encode('ascii')).hexdigest()
        # Account progress serializes claims with crafts without global contention.
        row = await AlchemyService(self.database)._locked_account_progress(
            session, account_id, user_id=user_id)
        moment = _resolve_now(now)
        inserted = await session.scalar(insert(AlchemyClaimCommand).values(
            id=command_id, account_id=account_id, fingerprint=fingerprint, result={},
            created_at=moment).on_conflict_do_nothing().returning(AlchemyClaimCommand.id))
        if not inserted:
            receipt = await session.get(AlchemyClaimCommand, command_id)
            if receipt.account_id != account_id or receipt.fingerprint != fingerprint:
                raise MiniAppError(409, 'Идентификатор уже использован для другого этапа', code='command_reused')
            return dict(receipt.result)
        if catalog_revision != catalog.revision:
            raise MiniAppError(409, 'Каталог изменился. Обнови игру и повтори.', code='catalog_changed')
        stage = catalog.stages.get(stage_id)
        if stage is None:
            raise MiniAppError(422, 'Такого этапа нет в каталоге')
        projection = await journey_projection(session, account_id)
        awarded = 0
        existing = await session.get(AlchemyStageClaim, (account_id, stage_id))
        if existing is None:
            try:
                validate_stage(stage, claimed=projection['claims'],
                    verified_discovered=row.verified_discovered,
                    verified_crafted=row.verified_crafted, recipes=catalog.recipes)
            except ValueError as error:
                raise MiniAppError(409, str(error), code='stage_ineligible') from None
            existing = AlchemyStageClaim(account_id=account_id, stage_id=stage_id,
                campaign_id=stage.campaign_id, catalog_revision=catalog.revision,
                reward={'points': stage.points, 'seal': stage.seal}, claimed_at=moment)
            session.add(existing)
            await session.flush()
            awarded = stage.points
        result = {**await journey_projection(session, account_id), 'command_id': command_id,
                  'verified_discovered': list(row.verified_discovered),
                  'verified_crafted': list(row.verified_crafted),
                  'stage_id': stage_id, 'reward': dict(existing.reward),
                  'awarded_expedition_points': awarded}
        (await session.get(AlchemyClaimCommand, command_id)).result = result
        return result
