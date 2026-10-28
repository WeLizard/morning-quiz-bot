"""Global farm upkeep settings stored in PostgreSQL and audited per edit."""
from copy import deepcopy
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from qw_farm.upkeep_config import public_state, updated_payload

from .admin_actions import AdminActions, AdminConflict
from .models import AdminAction, SystemState

KEY = 'farm_upkeep_config'


class FarmUpkeepSettings:
    def __init__(self, database):
        self.database = database

    async def read(self, *, at):
        async with self.database.transaction() as session:
            row = await session.get(SystemState, KEY)
            return public_state(row.payload if row else None, at)

    async def update(self, *, values, expected_revision, action_id):
        """Save one complete desired config; it starts on the next Moscow day."""
        actions = AdminActions(self.database)
        request = {
            'values': deepcopy(values),
            'expected_revision': expected_revision,
        }
        async with self.database.transaction() as session:
            previous = await actions._retry(
                session, action_id, 'system', 0, 'farm_upkeep', request,
            )
            if previous:
                return previous
            await session.execute(
                insert(SystemState).values(key=KEY, payload={}).on_conflict_do_nothing()
            )
            row = await session.scalar(
                select(SystemState).where(SystemState.key == KEY).with_for_update()
            )
            # The first lookup is a fast path; recheck after the state lock so
            # concurrent retries with one action_id receive the committed receipt.
            previous = await actions._retry(
                session, action_id, 'system', 0, 'farm_upkeep', request,
            )
            if previous:
                return previous
            # Calculate the effective day only after the row lock, so a request
            # waiting across Moscow midnight cannot schedule an already-started day.
            at = datetime.now(timezone.utc).timestamp()
            before = public_state(row.payload, at)
            if before['revision'] != expected_revision:
                raise AdminConflict('Ставки содержания уже изменены. Обнови страницу перед сохранением.')
            payload = updated_payload(
                row.payload, values, expected_revision=expected_revision, at=at,
            )
            row.payload = payload
            after = public_state(payload, at)
            return await actions._record(
                session, action_id, 'system', 0, 'farm_upkeep', request, before, after,
            )
