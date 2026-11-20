"""Handover from the old bot: chats that the old bot still serves while this one waits.

The old production bot keeps running its chats until the switch day. Players add this bot to
those chats beforehand; until the chat is released, this bot must not double the old one:

* no scheduled quizzes or wisdom in the chat (``ScheduleSource`` treats it as inactive);
* in groups, commands and messages are left to the old bot (``handlers.handover_handlers``);
* private chats keep working interactively — only the scheduled pushes wait.

The list lives in ``system_states['bot_handover']`` so it can be changed without a deploy
(``scripts/bot_handover.py``). Releasing a chat removes it from the list.
"""
from copy import deepcopy

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from .models import SystemState

KEY = 'bot_handover'


def normalize(payload):
    value = deepcopy(payload or {})
    chats = sorted({int(chat_id) for chat_id in value.get('chats', [])})
    old_bot = str(value.get('old_bot') or '').lstrip('@')
    return {'chats': chats, 'old_bot': old_bot}


async def read_in(session):
    row = await session.get(SystemState, KEY)
    return normalize(row.payload if row else {})


async def read(database):
    async with database.transaction() as session:
        return await read_in(session)


async def waiting_chats_in(session):
    return set((await read_in(session))['chats'])


async def _change(database, change):
    async with database.transaction() as session:
        await session.execute(insert(SystemState).values(key=KEY, payload={}).on_conflict_do_nothing())
        row = await session.scalar(select(SystemState).where(SystemState.key == KEY).with_for_update())
        value = normalize(row.payload)
        change(value)
        row.payload = normalize(value)
        return row.payload


async def hold(database, chat_ids, *, old_bot=None):
    """Put chats on hold (idempotent); ``old_bot`` is the username shown in the greeting."""
    def change(value):
        value['chats'] = sorted(set(value['chats']) | {int(chat_id) for chat_id in chat_ids})
        if old_bot is not None:
            value['old_bot'] = old_bot
    return await _change(database, change)


async def release(database, chat_ids=None):
    """Release the given chats, or every chat when ``chat_ids`` is None."""
    def change(value):
        value['chats'] = [] if chat_ids is None else sorted(
            set(value['chats']) - {int(chat_id) for chat_id in chat_ids})
    return await _change(database, change)


async def follow_migration(database, old_id, new_id):
    """A group that became a supergroup keeps its place in the handover list."""
    def change(value):
        if int(old_id) in value['chats']:
            value['chats'] = sorted((set(value['chats']) - {int(old_id)}) | {int(new_id)})
    return await _change(database, change)
