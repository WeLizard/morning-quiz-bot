import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from application.mafia import MafiaApplicationService
from application.game_deadlines import GameDeadlineProcessor
from handlers.mafia_handlers import MafiaHandlers, render_lobby, render_private_card
from modules.mini_app_launch import direct_mafia_link
from storage.models import (
    AccountIdentity,
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
from storage.games import GameRepository
from storage.repositories import OperationalRepository
from tests.local_database import isolated_database
from tests.test_postgres_members import pg_env


CHAT = -880000000044


def test_read_only_telegram_account_resolution_requires_verified_identity(pg_env):
    async def run():
        async with isolated_database(pg_env) as (database, _):
            async with database.transaction() as session:
                await OperationalRepository(session).ensure_user({'id': 808, 'display_name': 'Игрок'})
            async with database.transaction() as session:
                games = GameRepository(session)
                assert await games.existing_account_for_telegram_user(808) is None
                created = await games.account_for_telegram_user(808)
                assert str(await games.existing_account_for_telegram_user(808)) == str(created)
    asyncio.run(run())


def test_mafia_projection_refuses_a_revoked_telegram_identity(pg_env):
    async def run():
        async with isolated_database(pg_env) as (database, _):
            async with database.transaction() as session:
                repository = OperationalRepository(session)
                await repository.ensure_chat({'id': CHAT, 'type': 'supergroup'})
                for user_id in range(809, 813):
                    await repository.ensure_user({'id': user_id, 'display_name': f'Игрок {user_id}'})
                    await repository.ensure_member({'chat_id': CHAT, 'user_id': user_id})
            async with database.transaction() as session:
                service = MafiaApplicationService(session)
                for user_id in range(809, 813):
                    joined = await service.join(
                        chat_id=CHAT, user_id=user_id, name=f'Игрок {user_id}')
                    lobby = joined['lobby']
                for user_id in range(809, 813):
                    lobby = await service.ready(
                        chat_id=CHAT, user_id=user_id, ready=True,
                        expected_revision=lobby['revision'])
                await service.start(
                    chat_id=CHAT, user_id=809, expected_revision=lobby['revision'])
            async with database.transaction() as session:
                identity = await session.scalar(select(AccountIdentity).where(
                    AccountIdentity.provider == 'telegram',
                    AccountIdentity.provider_subject == '809',
                ))
                assert identity is not None
                identity.revoked_at = datetime.now(timezone.utc)
            async with database.transaction() as session:
                with pytest.raises(RuntimeError, match='revoked'):
                    await GameRepository(session).account_for_telegram_user(809)
            async with database.transaction() as session:
                identities = list((await session.scalars(select(AccountIdentity).where(
                    AccountIdentity.provider == 'telegram',
                    AccountIdentity.provider_subject == '809',
                ))).all())
                assert len(identities) == 1 and identities[0].revoked_at is not None
            async with database.transaction() as session:
                with pytest.raises(PermissionError):
                    await MafiaApplicationService(session).role(chat_id=CHAT, user_id=809)
            async with database.transaction() as session:
                repository = GameRepository(session)
                game = await repository.current(chat_id=CHAT, mode='mafia')
                assert game is not None
                due_state = dict(game.state)
                due_state['phase_deadline'] = 1
                await repository.sync_state(game, due_state, event_kind='projection_check')
                revoked_player = await session.scalar(select(GamePlayer).where(
                    GamePlayer.game_id == game.id,
                    GamePlayer.account_id == due_state['players'][0]['account_id'],
                ))
                assert revoked_player is not None and revoked_player.user_id is None
            result = await GameDeadlineProcessor(database).run_once(now=2_000_000_000)
            assert result['mafia'] == 1
            async with database.transaction() as session:
                game = await GameRepository(session).current(chat_id=CHAT, mode='mafia')
                assert game.state['status'] == 'day'
    asyncio.run(run())


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
                assert stored.room_id == f'telegram:{CHAT}'
                assert sorted(role['role'] for role in roles) == ['citizen', 'citizen', 'citizen', 'mafia']
                assert 'assignments' in stored.state
                assert await session.scalar(select(SystemState).where(
                    SystemState.key == f'mafia_lobby:{CHAT}')) is None
                projected_players = (await session.scalars(select(GamePlayer).where(
                    GamePlayer.game_id == stored.id))).all()
                assert len(projected_players) == 4
                assert {player.user_id for player in projected_players} == set(range(1, 5))
                assert all('user_id' not in player for player in stored.state['players'])
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


def test_mafia_discussion_is_player_only_public_and_idempotent(pg_env):
    async def run():
        async with isolated_database(pg_env) as (database, _):
            async with database.transaction() as session:
                repository = OperationalRepository(session)
                await repository.ensure_chat({'id': CHAT, 'type': 'supergroup'})
                for user_id in (101, 102):
                    await repository.ensure_user({'id': user_id, 'display_name': f'Player {user_id}'})
                    await repository.ensure_member({'chat_id': CHAT, 'user_id': user_id})
            async with database.transaction() as session:
                await MafiaApplicationService(session).join(chat_id=CHAT, user_id=101, name='First')
            command_id = 'mafia-discussion-command-0001'
            async with database.transaction() as session:
                result = await MafiaApplicationService(session).post_discussion(
                    chat_id=CHAT, user_id=101, message=' <подозреваю> мафию ', command_id=command_id)
                assert result['accepted']
            async with database.transaction() as session:
                service = MafiaApplicationService(session)
                replay = await service.post_discussion(
                    chat_id=CHAT, user_id=101, message='<подозреваю> мафию', command_id=command_id)
                assert replay == result
                messages = await service.discussion(chat_id=CHAT, viewer_id=101)
                assert messages['enabled'] is True
                assert len(messages['items']) == 1
                assert messages['items'][0]['message'] == '<подозреваю> мафию'
                assert messages['items'][0]['author'] == 'First'
                assert messages['items'][0]['is_me'] is True
                assert await session.scalar(select(func.count()).select_from(GameEvent).where(
                    GameEvent.kind == 'discussion_message')) == 1
            async with database.transaction() as session:
                try:
                    await MafiaApplicationService(session).discussion(chat_id=CHAT, viewer_id=102)
                except PermissionError as error:
                    assert 'участникам стола' in str(error)
                else:
                    raise AssertionError('A chat member outside the game read the discussion')
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


def test_failed_mafia_command_rolls_back_unfinished_receipt_before_outer_commit(pg_env):
    async def run():
        async with isolated_database(pg_env) as (database, _):
            async with database.transaction() as session:
                repository = OperationalRepository(session)
                await repository.ensure_chat({'id': CHAT, 'type': 'supergroup'})
                await repository.ensure_user({'id': 94, 'display_name': 'One'})
                await repository.ensure_member({'chat_id': CHAT, 'user_id': 94})
            async with database.transaction() as session:
                await MafiaApplicationService(session).join(
                    chat_id=CHAT, user_id=94, name='One')

            command_id = 'failed-ready-command-0001'
            async with database.transaction() as session:
                try:
                    await MafiaApplicationService(session).ready(
                        chat_id=CHAT, user_id=94, ready=True,
                        expected_revision=99, command_id=command_id,
                    )
                except RuntimeError as error:
                    assert 'уже изменилось' in str(error)
                else:
                    raise AssertionError('Stale Mafia command unexpectedly succeeded')
                # The adapter may catch the exception and commit its outer
                # transaction; the service savepoint must still discard receipt.

            async with database.transaction() as session:
                assert await session.get(GameCommand, command_id) is None
                game = await session.scalar(select(Game).where(
                    Game.chat_id == CHAT, Game.mode == 'mafia', Game.is_current.is_(True)
                ))
                assert game.state['revision'] == 0
                result = await MafiaApplicationService(session).ready(
                    chat_id=CHAT, user_id=94, ready=True,
                    expected_revision=0, command_id=command_id,
                )
                assert result['players'][0]['ready'] is True
            async with database.transaction() as session:
                receipt = await session.get(GameCommand, command_id)
                assert receipt is not None and receipt.status == 'completed'
    asyncio.run(run())


def test_mafia_command_id_cannot_replay_a_receipt_across_games(pg_env):
    async def run():
        second_chat = CHAT - 1
        command_id = 'same-command-id-cross-game-0001'
        async with isolated_database(pg_env) as (database, _):
            async with database.transaction() as session:
                repository = OperationalRepository(session)
                await repository.ensure_chat({'id': CHAT, 'type': 'supergroup'})
                await repository.ensure_chat({'id': second_chat, 'type': 'supergroup'})
                await repository.ensure_user({'id': 93, 'display_name': 'One'})
                await repository.ensure_member({'chat_id': CHAT, 'user_id': 93})
                await repository.ensure_member({'chat_id': second_chat, 'user_id': 93})
            async with database.transaction() as session:
                await MafiaApplicationService(session).join(
                    chat_id=CHAT, user_id=93, name='One', command_id=command_id,
                )
            try:
                async with database.transaction() as session:
                    await MafiaApplicationService(session).join(
                        chat_id=second_chat, user_id=93, name='One', command_id=command_id,
                    )
            except RuntimeError as error:
                assert 'другой команды или игры' in str(error)
            else:
                raise AssertionError('Cross-game command ID replay was accepted')
            async with database.transaction() as session:
                assert await session.scalar(select(Game).where(
                    Game.chat_id == second_chat, Game.mode == 'mafia', Game.is_current.is_(True)
                )) is None
                assert await session.scalar(select(func.count()).select_from(GameCommand)) == 1
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
