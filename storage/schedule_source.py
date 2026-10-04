from copy import deepcopy
from dataclasses import dataclass

from sqlalchemy import select

from .models import Chat, User, SystemState
from .schedule_plan import build_schedule_plan


@dataclass
class ScheduleState:
    values: dict
    revision: int
    active: bool


class ScheduleSource:
    def __init__(self, database, config):
        self.database, self.config = database, config

    async def read(self, chat_id=None):
        statement = select(Chat.id, Chat.settings, Chat.settings_revision, Chat.is_active, Chat.bot_blocked,
                           User.bot_blocked).outerjoin(User, User.id == Chat.id)
        if chat_id is not None:
            statement = statement.where(Chat.id == int(chat_id))
        async with self.database.transaction() as session:
            rows = (await session.execute(statement)).all()
            control = await session.get(SystemState, 'maintenance_status')
            maintenance = bool(control and control.payload.get('maintenance_mode'))
        return {cid: ScheduleState(deepcopy(values or {}), revision, active and not blocked and not private_blocked and not maintenance)
                for cid, values, revision, active, blocked, private_blocked in rows}

    def plan(self, state, kind):
        if state is None or not state.active:
            return build_schedule_plan({}, kind)
        return build_schedule_plan(state.values, kind, defaults=self.config.default_chat_settings,
                                   daily_defaults=self.config.daily_quiz_defaults)

    async def is_current(self, chat_id, kind, token):
        if not token:
            return False
        state = (await self.read(chat_id)).get(int(chat_id))
        plan = self.plan(state, kind)
        return bool(plan.times) and plan.token == token
