"""Handover from the old bot: waiting chats get no scheduled pushes, waiting groups get silence."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import delete
from telegram.constants import ChatMemberStatus, ChatType
from telegram.ext import ApplicationHandlerStop

from handlers.handover_handlers import HandoverHandlers, greeting
from storage import bot_handover
from storage.models import SystemState
from tests.test_postgres_members import CHAT, OTHER_CHAT, pg_env, scenario  # noqa: F401
from tests.test_schedule_sync import job_ids, seed, workers

GROUP = -100777
PRIVATE = 777


def chat(chat_id, kind):
    return SimpleNamespace(id=chat_id, type=kind)


def message_update(chat_id, kind, **message):
    target = chat(chat_id, kind)
    return SimpleNamespace(update_id=1, effective_chat=target, my_chat_member=None, chat_member=None,
                           effective_message=SimpleNamespace(**{'chat': target, 'migrate_to_chat_id': None,
                                                                'migrate_from_chat_id': None, **message}))


def joined_update(chat_id, old=ChatMemberStatus.LEFT, new=ChatMemberStatus.MEMBER):
    target = chat(chat_id, ChatType.SUPERGROUP)
    change = SimpleNamespace(chat=target, old_chat_member=SimpleNamespace(status=old),
                             new_chat_member=SimpleNamespace(status=new))
    return SimpleNamespace(update_id=2, effective_chat=target, my_chat_member=change, chat_member=None,
                           effective_message=None)


@pytest.fixture
def handover(monkeypatch):
    """The gate over an in-memory list; ``state`` and ``reads`` are visible to the test."""
    state = {'chats': [GROUP], 'old_bot': 'OldQuizBot'}
    reads = []

    async def read(database):
        reads.append(1)
        return dict(state, chats=list(state['chats']))

    moved = []

    async def follow(database, old_id, new_id):
        moved.append((old_id, new_id))

    monkeypatch.setattr(bot_handover, 'read', read)
    monkeypatch.setattr(bot_handover, 'follow_migration', follow)
    now = [0.0]
    handlers = HandoverHandlers(object(), cache_seconds=15, clock=lambda: now[0])
    return SimpleNamespace(handlers=handlers, state=state, reads=reads, moved=moved, now=now,
                           context=SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock())))


def gate(handover, update):
    return asyncio.run(handover.handlers.gate(update, handover.context))


def test_waiting_group_leaves_commands_to_the_old_bot(handover):
    with pytest.raises(ApplicationHandlerStop):
        gate(handover, message_update(GROUP, ChatType.SUPERGROUP, text='/quiz'))


def test_other_groups_and_private_chats_are_not_gated(handover):
    gate(handover, message_update(-100888, ChatType.SUPERGROUP, text='/quiz'))
    gate(handover, message_update(GROUP, ChatType.PRIVATE, text='/start'))  # same id, but private
    gate(handover, message_update(PRIVATE, ChatType.PRIVATE, text='/start'))
    assert len(handover.reads) == 1  # private chats never read the list


def test_released_group_works_after_the_cache_expires(handover):
    with pytest.raises(ApplicationHandlerStop):
        gate(handover, message_update(GROUP, ChatType.SUPERGROUP, text='/quiz'))
    handover.state['chats'] = []
    with pytest.raises(ApplicationHandlerStop):  # still cached
        gate(handover, message_update(GROUP, ChatType.SUPERGROUP, text='/quiz'))
    handover.now[0] = 16
    gate(handover, message_update(GROUP, ChatType.SUPERGROUP, text='/quiz'))


def test_unreadable_list_suppresses_group_updates(handover, monkeypatch):
    async def broken(database):
        raise RuntimeError('database down')
    monkeypatch.setattr(bot_handover, 'read', broken)
    with pytest.raises(ApplicationHandlerStop):
        gate(handover, message_update(-100888, ChatType.SUPERGROUP, text='/quiz'))


def test_bot_added_to_a_waiting_group_greets_once_and_lets_the_event_through(handover):
    gate(handover, joined_update(GROUP))
    handover.context.bot.send_message.assert_awaited_once()
    chat_id, text = handover.context.bot.send_message.await_args.args
    assert chat_id == GROUP and '@OldQuizBot' in text
    # Promotion to admin is not a new arrival: no second greeting.
    gate(handover, joined_update(GROUP, old=ChatMemberStatus.MEMBER, new=ChatMemberStatus.ADMINISTRATOR))
    assert handover.context.bot.send_message.await_count == 1


def test_bot_added_elsewhere_or_removed_does_not_greet(handover):
    gate(handover, joined_update(-100888))
    gate(handover, joined_update(GROUP, old=ChatMemberStatus.MEMBER, new=ChatMemberStatus.LEFT))
    handover.context.bot.send_message.assert_not_awaited()


def test_group_migration_passes_and_moves_the_waiting_id(handover):
    gate(handover, message_update(GROUP, ChatType.GROUP, text=None, migrate_to_chat_id=-100999))
    assert handover.moved == [(GROUP, -100999)]


def test_greeting_names_the_old_bot_only_when_known():
    assert '@OldQuizBot' in greeting('OldQuizBot')
    assert '@' not in greeting('')


def test_handler_is_registered_before_the_menus():
    source = open('bot.py', encoding='utf-8').read()
    assert 'HandoverHandlers(data_manager.postgres_storage.database).get_handler(), group=-95' in source


# --- PostgreSQL -----------------------------------------------------------------------------------


async def _clear(db):
    async with db.transaction() as session:
        await session.execute(delete(SystemState).where(SystemState.key == bot_handover.KEY))


def test_hold_release_and_migration_keep_one_sorted_list(pg_env):
    async def run():
        async with scenario(pg_env) as db:
            await _clear(db)
            try:
                assert await bot_handover.read(db) == {'chats': [], 'old_bot': ''}
                await bot_handover.hold(db, [OTHER_CHAT, CHAT, CHAT], old_bot='@OldQuizBot')
                assert await bot_handover.read(db) == {'chats': sorted([CHAT, OTHER_CHAT]), 'old_bot': 'OldQuizBot'}
                await bot_handover.follow_migration(db, CHAT, -100123)
                await bot_handover.follow_migration(db, 42, 43)  # not waiting: nothing to move
                assert (await bot_handover.read(db))['chats'] == sorted([-100123, OTHER_CHAT])
                await bot_handover.release(db, [OTHER_CHAT])
                assert (await bot_handover.read(db))['chats'] == [-100123]
                await bot_handover.release(db)
                assert await bot_handover.read(db) == {'chats': [], 'old_bot': 'OldQuizBot'}
            finally:
                await _clear(db)
    asyncio.run(run())


def test_waiting_chat_gets_no_scheduled_quiz_or_wisdom_until_released(pg_env):
    async def run():
        async with scenario(pg_env) as db:
            await _clear(db)
            try:
                await seed(db)
                sync = workers(db)
                await sync.run_once()
                assert all(job_ids(sync))
                await bot_handover.hold(db, [CHAT])
                await sync.run_once()
                assert job_ids(sync) == ([], [])
                await bot_handover.release(db, [CHAT])
                await sync.run_once()
                assert all(job_ids(sync))
            finally:
                await _clear(db)
    asyncio.run(run())
