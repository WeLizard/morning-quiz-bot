import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory

from application.rooms import RoomApplicationService, normalize_room_title
from application.game_deadlines import GameDeadlineProcessor
from application.mafia import MafiaApplicationService
from storage.games import GameRepository
from storage.models import (Account, Base, Chat, Game, GameCommand, GameEvent,
                            GamePlayer, Room, RoomInvite, RoomMembership,
                            RoomTransport, User)
from storage.repositories import OperationalRepository
from tests.local_database import isolated_database
from tests.test_postgres_members import pg_env


def test_room_title_is_bounded_plain_text():
    assert normalize_room_title('  Вечерняя   компания\n друзей ') == 'Вечерняя компания друзей'
    with pytest.raises(ValueError):
        normalize_room_title(' ')
    with pytest.raises(ValueError):
        normalize_room_title('x' * 81)
    with pytest.raises(ValueError):
        normalize_room_title('плохо\x00')


def test_guest_room_creation_is_idempotent_and_private(pg_env):
    async def run():
        async with isolated_database(pg_env) as (database, _):
            first_account, second_account = uuid4(), uuid4()
            request_id = str(uuid4())
            async with database.transaction() as session:
                session.add_all([
                    Account(id=first_account, display_name='First'),
                    Account(id=second_account, display_name='Second'),
                ])
            async with database.transaction() as session:
                first = await RoomApplicationService(session).create(
                    account_id=first_account, request_id=request_id, title='Дело друзей')
            async with database.transaction() as session:
                replay = await RoomApplicationService(session).create(
                    account_id=first_account, request_id=request_id, title='Дело друзей')
                assert replay == first
                room = await session.get(Room, request_id)
                assert room.owner_account_id == first_account
                assert await session.scalar(select(func.count()).select_from(RoomMembership)) == 1
                assert await session.scalar(select(func.count()).select_from(Chat)) == 0
                assert await session.scalar(select(func.count()).select_from(User)) == 0
                assert await RoomApplicationService(session).list_mine(account_id=second_account) == []
                with pytest.raises(LookupError):
                    await RoomApplicationService(session).get_mine(
                        account_id=second_account, room_id=request_id)
            async with database.transaction() as session:
                with pytest.raises(RuntimeError):
                    await RoomApplicationService(session).create(
                        account_id=second_account, request_id=request_id, title='Дело друзей')
    asyncio.run(run())


def test_room_game_and_account_player_need_no_telegram_identity(pg_env, monkeypatch):
    async def run():
        async with isolated_database(pg_env) as (database, _):
            room_id, account_id = 'standalone-mafia-room', uuid4()
            second_account_id = uuid4()
            telegram_room_id = 'telegram:-870000000045'
            async with database.transaction() as session:
                session.add_all([
                    Account(id=account_id, display_name='Гость'),
                    Account(id=second_account_id, display_name='Другой игрок'),
                ])
                session.add(Room(
                    id=room_id, kind='standalone', title='Ночная партия',
                    owner_account_id=account_id, state={},
                ))
                session.add(Room(
                    id=telegram_room_id, kind='telegram', title='Telegram', state={},
                ))
            async with database.transaction() as session:
                games = GameRepository(session)
                state = {
                    'mode': 'mafia_lobby', 'state_version': 2, 'room_id': room_id,
                    'host_account_id': str(account_id),
                    'status': 'lobby', 'phase': 'lobby', 'revision': 0,
                    'players': [{
                        'account_id': str(account_id), 'name': 'Гость', 'ready': False,
                    }],
                }
                game = await games.create_room_current(
                    room_id=room_id, mode='mafia', state=state)
                player = await session.scalar(select(GamePlayer).where(
                    GamePlayer.game_id == game.id,
                    GamePlayer.account_id == account_id,
                ))
                assert player is not None and player.user_id is None
                assert player.public_state == {'name': 'Гость', 'ready': False}
                cached, result = await games.reserve_command(
                    command_id='standalone-room-join-1', game_id=game.id,
                    actor_account_id=account_id, kind='mafia.join',
                    expected_revision=0, payload={},
                )
                assert cached is False and result is None
                await games.complete_command('standalone-room-join-1', {'joined': True})
                cached, result = await games.reserve_command(
                    command_id='standalone-room-join-1', game_id=game.id,
                    actor_account_id=account_id, kind='mafia.join',
                    expected_revision=0, payload={},
                )
                assert cached is True and result == {'joined': True}
                with pytest.raises(RuntimeError, match='другой команды или игры'):
                    await games.reserve_command(
                        command_id='standalone-room-join-1', game_id=game.id,
                        actor_account_id=second_account_id, kind='mafia.join',
                        expected_revision=0, payload={},
                    )
                with pytest.raises(RuntimeError, match='другой команды или игры'):
                    await games.reserve_command(
                        command_id='standalone-room-join-1', game_id=game.id,
                        actor_account_id=account_id, kind='mafia.join',
                        expected_revision=0, payload={'changed': True},
                    )
                event = await games.append_event(
                    game, kind='lobby_joined', actor_user_id=None,
                    actor_account_id=account_id, visibility='public', payload={},
                )
                assert event.actor_user_id is None
                assert event.actor_account_id == account_id
            migration = ScriptDirectory.from_config(Config('alembic.ini')).get_revision(
                '20261008_0020').module
            async with database.engine.begin() as connection:
                def refuse_loss(sync):
                    operations = Operations(MigrationContext.configure(sync))
                    with monkeypatch.context() as patch:
                        patch.setattr(migration, 'op', operations)
                        patch.setattr(migration.context, 'is_offline_mode', lambda: False)
                        with pytest.raises(RuntimeError, match='standalone room game data'):
                            migration.downgrade()
                await connection.run_sync(refuse_loss)
            async with database.transaction() as session:
                with pytest.raises(ValueError, match='уже есть текущая игра'):
                    await GameRepository(session).create_room_current(
                        room_id=room_id, mode='mafia',
                        state={'status': 'lobby', 'phase': 'lobby', 'revision': 0})
                with pytest.raises(LookupError, match='не найдена'):
                    await GameRepository(session).create_room_current(
                        room_id=telegram_room_id, mode='mafia',
                        state={'status': 'lobby', 'phase': 'lobby', 'revision': 0})
            async with database.transaction() as session:
                game = await GameRepository(session).current_in_room(
                    room_id=room_id, mode='mafia')
                assert game is not None and game.chat_id is None
                assert await session.scalar(select(func.count()).select_from(Chat)) == 0
                assert await session.scalar(select(func.count()).select_from(User)) == 0
                player = await session.scalar(select(GamePlayer).where(
                    GamePlayer.game_id == game.id,
                    GamePlayer.account_id == account_id,
                ))
                assert player is not None and player.user_id is None
                command = await session.get(GameCommand, 'standalone-room-join-1')
                assert command is not None and command.actor_user_id is None
                assert command.actor_account_id == account_id and command.result == {'joined': True}
                event = await session.scalar(select(GameEvent).where(
                    GameEvent.game_id == game.id,
                    GameEvent.kind == 'lobby_joined',
                ))
                assert event is not None and event.actor_user_id is None
                assert event.actor_account_id == account_id
            async with database.transaction() as session:
                repository = GameRepository(session)
                current = await repository.current_in_room(room_id=room_id, mode='mafia')
                replacement = await repository.replace_current(
                    current, state={
                        'mode': 'mafia_lobby', 'state_version': 2, 'room_id': room_id,
                        'host_account_id': str(account_id),
                        'status': 'lobby', 'phase': 'lobby', 'revision': 0,
                        'players': [{'account_id': str(account_id), 'name': 'Гость', 'ready': False}],
                    })
                assert replacement.room_id == room_id and replacement.chat_id is None
                assert await session.scalar(select(func.count()).select_from(GamePlayer).where(
                    GamePlayer.game_id == replacement.id)) == 1
    asyncio.run(run())


def test_standalone_mafia_uses_account_membership_and_shared_deadline_worker(pg_env, monkeypatch):
    async def run():
        async with isolated_database(pg_env) as (database, _):
            room_id = str(uuid4())
            accounts = [uuid4() for _ in range(4)]
            monkeypatch.setattr('domain.mafia.secrets.SystemRandom.shuffle', lambda self, values: None)
            async with database.transaction() as session:
                session.add_all([
                    Account(id=account_id, display_name=f'Игрок {index}')
                    for index, account_id in enumerate(accounts, 1)
                ])
                session.add(Room(
                    id=room_id, kind='standalone', title='Ночной город',
                    owner_account_id=accounts[0], state={},
                ))
                session.add_all([
                    RoomMembership(
                        room_id=room_id, account_id=account_id,
                        role='owner' if index == 0 else 'member', status='active',
                    ) for index, account_id in enumerate(accounts)
                ])
            async with database.transaction() as session:
                lobby = await MafiaApplicationService(session).create_room_lobby(
                    room_id=room_id, account_id=accounts[0], name='Игрок 1',
                    command_id='room-mafia-create-0001',
                )
                assert lobby['is_host'] and lobby['joined']
                assert 'assignments' not in lobby
            async with database.transaction() as session:
                service = MafiaApplicationService(session)
                for index, account_id in enumerate(accounts[1:], 2):
                    lobby = await service.room_join(
                        room_id=room_id, account_id=account_id, name=f'Игрок {index}',
                        command_id=f'room-mafia-join-{index:04d}',
                    )
                for account_id in accounts:
                    lobby = await service.room_ready(
                        room_id=room_id, account_id=account_id, ready=True,
                        expected_revision=lobby['revision'],
                        command_id=f'ready-{str(account_id)[:12]}',
                    )
                lobby = await service.room_start(
                    room_id=room_id, account_id=accounts[0],
                    expected_revision=lobby['revision'],
                    command_id='room-mafia-start-0001',
                )
                assert lobby['status'] == 'night' and lobby['ends_at'] is not None
                own_role = await service.room_role(
                    room_id=room_id, account_id=accounts[0],
                )
                assert own_role is not None and own_role['role'] == 'mafia'
                with pytest.raises(LookupError, match='не найдена'):
                    await service.room_lobby(room_id=room_id, account_id=uuid4())
                game_id = await session.scalar(select(Game.id).where(
                    Game.room_id == room_id, Game.is_current.is_(True),
                ))
                assert await session.scalar(select(func.count()).select_from(Chat)) == 0
                assert await session.scalar(select(func.count()).select_from(User)) == 0
            deadline = datetime.fromtimestamp(lobby['ends_at'], tz=timezone.utc)
            async with database.transaction() as session:
                assert await MafiaApplicationService(session).due_game_ids(now=deadline) == [game_id]
            result = await GameDeadlineProcessor(database).run_once(now=deadline)
            assert result['mafia'] == 1
            async with database.transaction() as session:
                state = await MafiaApplicationService(session).room_lobby(
                    room_id=room_id, account_id=accounts[0],
                )
                assert state['status'] == 'day'
                game = await session.get(Game, game_id)
                assert game.chat_id is None and game.state['status'] == 'day'
                players = (await session.scalars(select(GamePlayer).where(
                    GamePlayer.game_id == game_id,
                ))).all()
                assert len(players) == 4 and all(player.user_id is None for player in players)
    asyncio.run(run())


def test_mafia_projection_rejects_duplicate_account_actors(pg_env):
    async def run():
        async with isolated_database(pg_env) as (database, _):
            account_id = uuid4()
            async with database.transaction() as session:
                session.add(Account(id=account_id, display_name='Один аккаунт'))
                session.add(Room(
                    id='duplicate-mafia-room', kind='standalone', title='Дубликат',
                    owner_account_id=account_id, state={},
                ))
            async with database.transaction() as session:
                duplicate_state = {
                    'mode': 'mafia_lobby', 'state_version': 2,
                    'room_id': 'duplicate-mafia-room',
                    'host_account_id': str(account_id),
                    'status': 'lobby', 'phase': 'lobby', 'revision': 0,
                    'players': [
                        {'account_id': str(account_id), 'name': 'Первый'},
                        {'account_id': str(account_id), 'name': 'Второй'},
                    ],
                }
                with pytest.raises(ValueError, match='Duplicate player identity|Duplicate account identity'):
                    await GameRepository(session).create_room_current(
                        room_id='duplicate-mafia-room', mode='mafia', state=duplicate_state)
            async with database.transaction() as session:
                assert await session.scalar(select(func.count()).select_from(Game)) == 0
                assert await session.scalar(select(func.count()).select_from(GamePlayer)) == 0
    asyncio.run(run())


def test_room_game_schema_migration_roundtrips_legacy_telegram_rows(pg_env, monkeypatch):
    async def run():
        migration = ScriptDirectory.from_config(Config('alembic.ini')).get_revision(
            '20261008_0020').module
        async with isolated_database(pg_env) as (database, _):
            account_id, chat_id, user_id = uuid4(), -870000000046, 870000000046
            async with database.transaction() as session:
                session.add_all([
                    Account(id=account_id, display_name='Legacy Telegram player'),
                    Chat(id=chat_id, type='supergroup', title='Legacy table'),
                    User(id=user_id, account_id=account_id, display_name='Legacy player'),
                    Room(id=f'telegram:{chat_id}', kind='telegram', title='Legacy table', state={}),
                ])
                await session.flush()
                game = Game(
                    id='legacy-room-game', chat_id=chat_id, room_id=f'telegram:{chat_id}',
                    mode='mafia', status='lobby', phase='lobby', revision=0,
                    state={'players': []}, is_current=True,
                )
                session.add(game)
                await session.flush()
                session.add(GamePlayer(
                    game_id=game.id, account_id=account_id, user_id=user_id,
                    seat='p1', public_state={}, private_state={},
                ))

            async with database.engine.begin() as connection:
                def roundtrip(sync):
                    operations = Operations(MigrationContext.configure(sync))
                    with monkeypatch.context() as patch:
                        patch.setattr(migration, 'op', operations)
                        patch.setattr(migration.context, 'is_offline_mode', lambda: False)
                        migration.downgrade()
                        columns = {row['column_name']: row['is_nullable'] for row in sync.execute(text(
                            "SELECT column_name, is_nullable FROM information_schema.columns "
                            "WHERE table_schema = current_schema() "
                            "AND table_name IN ('games', 'game_players')"
                        )).mappings()}
                        assert columns['chat_id'] == 'NO'
                        assert columns['user_id'] == 'NO'
                        migration.upgrade()
                        columns = {row['column_name']: row['is_nullable'] for row in sync.execute(text(
                            "SELECT column_name, is_nullable FROM information_schema.columns "
                            "WHERE table_schema = current_schema() "
                            "AND table_name IN ('games', 'game_players')"
                        )).mappings()}
                        assert columns['chat_id'] == 'YES'
                        assert columns['user_id'] == 'YES'
                        assert sync.execute(text(
                            "SELECT count(*) FROM games WHERE id = 'legacy-room-game' "
                            "AND room_id = :room_id AND chat_id = :chat_id"
                        ), {'room_id': f'telegram:{chat_id}', 'chat_id': chat_id}).scalar_one() == 1
                        assert sync.execute(text(
                            "SELECT count(*) FROM game_players WHERE game_id = 'legacy-room-game' "
                            "AND account_id = :account_id AND user_id = :user_id"
                        ), {'account_id': account_id, 'user_id': user_id}).scalar_one() == 1
                await connection.run_sync(roundtrip)
    asyncio.run(run())


def test_room_invites_are_private_hashed_bounded_and_revocable(pg_env):
    async def run():
        async with isolated_database(pg_env) as (database, _):
            owner_id, member_id, outsider_id = uuid4(), uuid4(), uuid4()
            async with database.transaction() as session:
                session.add_all([
                    Account(id=owner_id, display_name='Owner'),
                    Account(id=member_id, display_name='Member'),
                    Account(id=outsider_id, display_name='Outsider'),
                ])
            room_id = str(uuid4())
            async with database.transaction() as session:
                room = await RoomApplicationService(session).create(
                    account_id=owner_id, request_id=room_id, title='Invite room')
            async with database.transaction() as session:
                service = RoomApplicationService(session)
                invite = await service.create_invite(
                    account_id=owner_id, room_id=room_id,
                    expires_in_seconds=3600, max_uses=2)
                invite_id, invite_code = invite['id'], invite['invite_code']
                assert len(invite_code) == 43
                stored = await session.get(RoomInvite, invite_id)
                from hashlib import sha256
                assert stored.token_hash == sha256(invite_code.encode()).hexdigest()
                assert stored.token_hash != invite_code

            async with database.transaction() as session:
                result = await RoomApplicationService(session).join_by_invite(
                    account_id=member_id, invite_code=invite_code)
                assert result['id'] == room['id'] and result['role'] == 'member'
                assert result['joined'] is True
            async with database.transaction() as session:
                retry = await RoomApplicationService(session).join_by_invite(
                    account_id=member_id, invite_code=invite_code)
                assert retry['joined'] is False
                invite_row = await session.get(RoomInvite, invite_id)
                assert invite_row.uses == 1
                items = await RoomApplicationService(session).list_invites(
                    account_id=owner_id, room_id=room_id)
                assert items == [{
                    'id': invite_id, 'expires_at': invite_row.expires_at.isoformat(),
                    'max_uses': 2, 'uses': 1, 'revoked': False,
                }]
                with pytest.raises(LookupError):
                    await RoomApplicationService(session).list_invites(
                        account_id=outsider_id, room_id=room_id)

            async with database.transaction() as session:
                result = await RoomApplicationService(session).join_by_invite(
                    account_id=outsider_id, invite_code=invite_code)
                assert result['joined'] is True
            async with database.transaction() as session:
                with pytest.raises(LookupError, match='недействительно'):
                    await RoomApplicationService(session).join_by_invite(
                        account_id=uuid4(), invite_code=invite_code)
                await RoomApplicationService(session).revoke_invite(
                    account_id=owner_id, room_id=room_id, invite_id=invite_id)
            async with database.transaction() as session:
                with pytest.raises(LookupError, match='недействительно'):
                    await RoomApplicationService(session).join_by_invite(
                        account_id=uuid4(), invite_code=invite_code)
                with pytest.raises(ValueError):
                    await RoomApplicationService(session).create_invite(
                        account_id=owner_id, room_id=room_id,
                        expires_in_seconds=True, max_uses=0)
    asyncio.run(run())


def test_room_invite_usage_limit_is_serialized_across_accounts(pg_env):
    async def run():
        async with isolated_database(pg_env) as (database, _):
            owner_id, first_id, second_id = uuid4(), uuid4(), uuid4()
            async with database.transaction() as session:
                session.add_all([
                    Account(id=owner_id, display_name='Owner'),
                    Account(id=first_id, display_name='First'),
                    Account(id=second_id, display_name='Second'),
                ])
            room_id = str(uuid4())
            async with database.transaction() as session:
                await RoomApplicationService(session).create(
                    account_id=owner_id, request_id=room_id, title='One seat')
                invite = await RoomApplicationService(session).create_invite(
                    account_id=owner_id, room_id=room_id,
                    expires_in_seconds=3600, max_uses=1)
                code = invite['invite_code']

            async def join(account_id):
                try:
                    async with database.transaction() as session:
                        result = await RoomApplicationService(session).join_by_invite(
                            account_id=account_id, invite_code=code)
                        return result['joined']
                except LookupError:
                    return False

            assert sorted(await asyncio.gather(join(first_id), join(second_id))) == [False, True]
            async with database.transaction() as session:
                persisted = await session.get(RoomInvite, invite['id'])
                assert persisted.uses == 1
                members = await session.scalar(select(func.count()).select_from(RoomMembership).where(
                    RoomMembership.room_id == room_id))
                assert members == 2
    asyncio.run(run())


def test_room_invite_migration_refuses_downgrade_with_live_invites(pg_env, monkeypatch):
    async def run():
        migration = ScriptDirectory.from_config(Config('alembic.ini')).get_revision(
            '20261008_0019').module
        async with isolated_database(pg_env) as (database, _):
            owner_id, room_id = uuid4(), str(uuid4())
            async with database.transaction() as session:
                session.add(Account(id=owner_id, display_name='Invite owner'))
                session.add(Room(
                    id=room_id, kind='standalone', title='Migration room',
                    owner_account_id=owner_id, state={},
                ))
                session.add(RoomMembership(
                    room_id=room_id, account_id=owner_id, role='owner', status='active',
                ))
                session.add(RoomInvite(
                    id=str(uuid4()), room_id=room_id, created_by_account_id=owner_id,
                    token_hash='a' * 64,
                    expires_at=datetime.now(timezone.utc) + timedelta(hours=1), max_uses=1,
                ))

            async with database.engine.begin() as connection:
                def verify(sync):
                    operations = Operations(MigrationContext.configure(sync))
                    with monkeypatch.context() as patch:
                        patch.setattr(migration, 'op', operations)
                        patch.setattr(migration.context, 'is_offline_mode', lambda: False)
                        with pytest.raises(RuntimeError, match='invitation records exist'):
                                migration.downgrade()
                await connection.run_sync(verify)
    asyncio.run(run())


def test_room_migration_backfills_games_and_guards_downgrade(pg_env, monkeypatch):
    async def run():
        migration = ScriptDirectory.from_config(Config('alembic.ini')).get_revision(
            '20261008_0017').module
        async with isolated_database(pg_env) as (database, _):
            chat_id = -870000000044
            legacy_state = {'status': 'lobby', 'revision': 4, 'players': [{'user_id': 901}]}
            async with database.transaction() as session:
                await OperationalRepository(session).ensure_chat({
                    'id': chat_id, 'type': 'supergroup', 'title': 'Legacy room',
                    'username': 'legacy_room',
                })
                session.add(Room(
                    id=f'telegram:{chat_id}', kind='telegram', title='Legacy room', state={}
                ))
                await session.flush()
                session.add(Game(
                    id='legacy-mafia-game', chat_id=chat_id, room_id=f'telegram:{chat_id}',
                    mode='mafia', status='lobby', phase='lobby', revision=4,
                    state=legacy_state, is_current=True,
                ))

            async with database.engine.begin() as connection:
                def roundtrip(sync):
                    operations = Operations(MigrationContext.configure(sync))
                    with monkeypatch.context() as patch:
                        patch.setattr(migration, 'op', operations)
                        patch.setattr(migration.context, 'is_offline_mode', lambda: False)
                        # Recreate the schema immediately before 0017 while keeping
                        # one real chat/game row to verify the data backfill.
                        operations.drop_index('ix_games_room_id', table_name='games')
                        room_fk = sync.execute(text("""
                            SELECT conname FROM pg_constraint
                            WHERE conrelid = to_regclass('games') AND contype = 'f'
                              AND pg_get_constraintdef(oid) ILIKE '%(room_id)%'
                        """)).scalar_one()
                        operations.drop_constraint(
                            room_fk, 'games', type_='foreignkey')
                        operations.drop_column('games', 'room_id')
                        operations.drop_table('room_transports')
                        operations.drop_table('room_memberships')
                        operations.drop_table('room_invites')
                        operations.drop_table('rooms')

                        migration.upgrade()
                        game = sync.execute(text(
                            'SELECT room_id, state FROM games WHERE id = :id'),
                            {'id': 'legacy-mafia-game'},
                        ).mappings().one()
                        assert game['room_id'] == f'telegram:{chat_id}'
                        assert game['state'] == legacy_state
                        room = sync.execute(text(
                            'SELECT kind, title, owner_account_id, state FROM rooms WHERE id = :id'),
                            {'id': f'telegram:{chat_id}'},
                        ).mappings().one()
                        assert room['kind'] == 'telegram'
                        assert room['title'] == 'Legacy room'
                        assert room['owner_account_id'] is None and room['state'] == {}
                        transport = sync.execute(text(
                            'SELECT kind, external_id, metadata_json FROM room_transports'),
                        ).mappings().one()
                        assert transport['kind'] == 'telegram'
                        assert transport['external_id'] == str(chat_id)
                        assert transport['metadata_json'] == {
                            'chat_type': 'supergroup', 'username': 'legacy_room'}

                        # A clean downgrade is safe and leaves the legacy game intact.
                        migration.downgrade()
                        assert sync.execute(text(
                            'SELECT state FROM games WHERE id = :id'),
                            {'id': 'legacy-mafia-game'},
                        ).scalar_one() == legacy_state
                        assert sync.execute(text(
                            "SELECT to_regclass(current_schema() || '.rooms')"
                        )).scalar_one() is None

                        migration.upgrade()
                        sync.execute(text(
                            'UPDATE rooms SET state = CAST(:state AS json) WHERE id = :id'),
                            {'state': '{"changed": true}', 'id': f'telegram:{chat_id}'},
                        )
                        with pytest.raises(RuntimeError, match='Cannot downgrade'):
                            migration.downgrade()
                        assert sync.execute(text(
                            'SELECT room_id FROM games WHERE id = :id'),
                            {'id': 'legacy-mafia-game'},
                        ).scalar_one() == f'telegram:{chat_id}'
                await connection.run_sync(roundtrip)
    asyncio.run(run())
