import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from sqlalchemy import func, select

from application.mafia import MafiaApplicationService
from handlers.mafia_handlers import MafiaHandlers, render_lobby, render_private_card
from modules.mini_app_launch import direct_mafia_link
from storage.models import (
    Chat,
    Game,
    GameCommand,
    GameDeadline,
    GameEvent,
    GamePlayer,
    NotificationOutbox,
    SystemState,
    User,
)
from storage.repositories import OperationalRepository
from tests.local_database import isolated_database
from tests.test_postgres_members import pg_env


CHAT = -880000000044


def test_application_service_owns_state_and_public_projection_hides_roles(pg_env):
    async def run():
        async with isolated_database(pg_env) as (database, _):
            async with database.transaction() as session:
                repository = OperationalRepository(session)
                await repository.ensure_chat({'id': CHAT, 'type': 'supergroup', 'title': 'Night City'})
                for user_id in range(1, 5):
                    await repository.ensure_user({'id': user_id, 'display_name': f'Player {user_id}'})
                    await repository.ensure_member({'chat_id': CHAT, 'user_id': user_id})
            for user_id in range(1, 5):
                async with database.transaction() as session:
                    result = await MafiaApplicationService(session).join(
                        chat_id=CHAT, user_id=user_id, name=f'Player {user_id}')
                    assert result['lobby']['joined']
            for user_id in range(1, 5):
                async with database.transaction() as session:
                    service = MafiaApplicationService(session)
                    current = await service.lobby(chat_id=CHAT, viewer_id=user_id)
                    await service.ready(chat_id=CHAT, user_id=user_id, ready=True,
                                        expected_revision=current['revision'])
            async with database.transaction() as session:
                service = MafiaApplicationService(session)
                current = await service.lobby(chat_id=CHAT, viewer_id=1)
                public = await service.start(chat_id=CHAT, user_id=1,
                                             expected_revision=current['revision'])
                assert public['status'] == 'night'
                assert 'assignments' not in public and 'user_id' not in str(public)
                night_deadline = public['ends_at']
            async with database.transaction() as session:
                service = MafiaApplicationService(session)
                roles = [await service.role(chat_id=CHAT, user_id=user_id) for user_id in range(1, 5)]
                stored = await session.scalar(select(Game).where(
                    Game.chat_id == CHAT, Game.mode == 'mafia', Game.is_current.is_(True)
                ))
                assert sorted(role['role'] for role in roles) == ['citizen', 'citizen', 'citizen', 'mafia']
                assert 'assignments' in stored.state
                assert await session.scalar(select(SystemState).where(
                    SystemState.key == f'mafia_lobby:{CHAT}')) is None
                assert len((await session.scalars(select(GamePlayer).where(
                    GamePlayer.game_id == stored.id))).all()) == 4
                assert await session.scalar(select(GameDeadline).where(
                    GameDeadline.game_id == stored.id, GameDeadline.status == 'pending'))
                assert len((await session.scalars(select(GameEvent).where(
                    GameEvent.game_id == stored.id))).all()) >= 9
            async with database.transaction() as session:
                service = MafiaApplicationService(session)
                assert CHAT in await service.due_chat_ids(now=night_deadline)
            async def advance():
                async with database.transaction() as session:
                    return await MafiaApplicationService(session).advance_due(
                        chat_id=CHAT, now=night_deadline
                    )
            results = await asyncio.gather(advance(), advance())
            advanced = next(result for result in results if result is not None)
            assert sum(result is not None for result in results) == 1
            assert advanced['status'] == 'day' and advanced['ends_at'] > night_deadline
            async with database.transaction() as session:
                notifications = (await session.scalars(select(NotificationOutbox))).all()
                assert len(notifications) == 1
                assert notifications[0].kind == 'mafia.phase'
                assert notifications[0].status == 'pending'
                payload = notifications[0].payload
                assert payload['lobby']['status'] == 'day'
                assert 'assignments' not in str(payload) and 'user_id' not in str(payload)
    asyncio.run(run())


def test_mafia_commands_require_current_chat_membership(pg_env):
    async def run():
        async with isolated_database(pg_env) as (database, _):
            async with database.transaction() as session:
                repository = OperationalRepository(session)
                await repository.ensure_chat({'id': CHAT, 'type': 'supergroup'})
                await repository.ensure_user({'id': 91, 'display_name': 'Former member'})
                try:
                    await MafiaApplicationService(session).join(
                        chat_id=CHAT, user_id=91, name='Former member'
                    )
                except PermissionError as error:
                    assert 'не состоит' in str(error)
                else:
                    raise AssertionError('Non-member joined a Mafia game')
    asyncio.run(run())


def test_mafia_command_id_is_shared_idempotency_receipt(pg_env):
    async def run():
        async with isolated_database(pg_env) as (database, _):
            async with database.transaction() as session:
                repository = OperationalRepository(session)
                await repository.ensure_chat({'id': CHAT, 'type': 'supergroup'})
                await repository.ensure_user({'id': 92, 'display_name': 'One'})
                await repository.ensure_member({'chat_id': CHAT, 'user_id': 92})
            first_id = 'cross-client-command-0001'
            async with database.transaction() as session:
                first = await MafiaApplicationService(session).join(
                    chat_id=CHAT, user_id=92, name='One', command_id=first_id
                )
            async with database.transaction() as session:
                replay = await MafiaApplicationService(session).join(
                    chat_id=CHAT, user_id=92, name='One', command_id=first_id
                )
                assert replay == first and replay['changed'] is True
                assert await session.scalar(select(func.count()).select_from(GameCommand)) == 1
                game = await session.scalar(select(Game).where(Game.is_current.is_(True)))
                assert await session.scalar(select(func.count()).select_from(GameEvent).where(
                    GameEvent.game_id == game.id
                )) == 1
            async with database.transaction() as session:
                try:
                    await MafiaApplicationService(session).join(
                        chat_id=CHAT, user_id=92, name='Different', command_id=first_id
                    )
                except RuntimeError as error:
                    assert 'другой команды' in str(error)
                else:
                    raise AssertionError('Reused command id accepted different input')
    asyncio.run(run())


def test_telegram_card_is_group_safe_and_uses_supported_direct_link(monkeypatch):
    monkeypatch.setenv('MINI_APP_URL', 'https://quiz.example.com/app')
    link = direct_mafia_link('MorningQuizTestBot', CHAT)
    assert link == f'https://t.me/MorningQuizTestBot?startapp=mafia_n{abs(CHAT)}'
    lobby = {
        'status': 'night', 'revision': 9, 'players': [
            {'name': '<Player>', 'ready': True, 'is_me': True},
            {'name': 'Second', 'ready': True, 'is_me': False},
        ],
        'can_start': False,
    }
    text, rows = render_lobby(lobby, mini_url=link)
    assert '&lt;Player&gt;' in text
    assert 'assignments' not in text and 'Мафия' not in text
    assert any(button.callback_data == 'mafia:role' for row in rows for button in row)
    assert any(button.url == link for row in rows for button in row)


def test_private_card_contains_actions_but_group_card_does_not():
    lobby = {'status': 'night', 'revision': 12, 'players': [
        {'name': 'One', 'ready': True, 'alive': True},
        {'name': 'Two', 'ready': True, 'alive': True},
    ], 'can_start': False, 'round': 2}
    role = {'phase': 'night', 'round': 2, 'role': 'detective', 'title': 'Детектив',
            'alive': True, 'targets': [{'seat': 'p2', 'name': 'Two'}]}
    private_text, private_rows = render_private_card(role, lobby, group_chat_id=CHAT)
    group_text, group_rows = render_lobby(lobby)
    private_callbacks = [button.callback_data for row in private_rows for button in row]
    group_callbacks = [button.callback_data for row in group_rows for button in row]
    assert 'Детектив' in private_text and any(value.startswith('mafia:act:') for value in private_callbacks)
    assert 'Детектив' not in group_text and not any(value.startswith('mafia:act:') for value in group_callbacks)


def test_telegram_adapter_translates_updates_to_shared_commands(pg_env, monkeypatch):
    monkeypatch.delenv('MINI_APP_URL', raising=False)

    async def run():
        async with isolated_database(pg_env) as (database, _):
            chat = SimpleNamespace(id=CHAT, type='supergroup', title='Night City', username=None)
            user = SimpleNamespace(id=77, full_name='Telegram Player')
            message = SimpleNamespace(chat=chat, message_id=10)
            bot = SimpleNamespace(username='MorningQuizTestBot', send_message=AsyncMock(),
                                  edit_message_text=AsyncMock())
            context = SimpleNamespace(bot=bot)
            handler = MafiaHandlers(database)
            command = SimpleNamespace(callback_query=None, effective_user=user,
                                      effective_chat=chat, effective_message=message)
            await handler.open(command, context)
            bot.send_message.assert_awaited_once()
            async with database.transaction() as session:
                lobby = await MafiaApplicationService(session).lobby(chat_id=CHAT, viewer_id=user.id)
                assert lobby['joined'] and lobby['revision'] == 0
            query = SimpleNamespace(data='mafia:ready:1:0', message=message, answer=AsyncMock())
            callback = SimpleNamespace(callback_query=query, effective_user=user,
                                       effective_chat=chat, effective_message=message)
            await handler.callback(callback, context)
            query.answer.assert_awaited_once()
            bot.edit_message_text.assert_awaited_once()
            async with database.transaction() as session:
                lobby = await MafiaApplicationService(session).lobby(chat_id=CHAT, viewer_id=user.id)
                assert lobby['players'][0]['ready'] is True and lobby['revision'] == 1
    asyncio.run(run())
