import asyncio
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import text

from storage.models import Account, Game, GameCommand, GameEvent, GamePlayer, User
from storage.repositories import OperationalRepository
from tests.local_database import isolated_database
from tests.test_postgres_members import pg_env


def test_0018_backfills_platform_identities_and_game_actors(pg_env, monkeypatch):
    async def run():
        migration = ScriptDirectory.from_config(Config('alembic.ini')).get_revision(
            '20261008_0018').module
        async with isolated_database(pg_env) as (database, _):
            linked_account, placeholder_one, placeholder_two = uuid4(), uuid4(), uuid4()
            first_user, second_user = 981000000101, 981000000102
            async with database.transaction() as session:
                session.add_all([
                    Account(id=linked_account, display_name='Existing account'),
                    Account(id=placeholder_one, display_name='Old player slot'),
                    Account(id=placeholder_two, display_name='Old player slot 2'),
                ])
                await session.flush()
                session.add_all([
                    User(id=first_user, account_id=linked_account, display_name='Linked'),
                    User(id=second_user, account_id=None, display_name='Needs account'),
                ])
                await session.flush()
                await OperationalRepository(session).ensure_chat({
                    'id': -981000000101, 'type': 'group', 'title': 'Migration test'})
                from storage.games import GameRepository
                await GameRepository(session).ensure_telegram_room(-981000000101)
                session.add(Game(
                    id='account-identity-game', chat_id=-981000000101,
                    room_id='telegram:-981000000101',
                    mode='mafia', status='lobby', phase='lobby', revision=1,
                    state={'players': []}, is_current=True,
                ))
                session.add_all([
                    GamePlayer(game_id='account-identity-game', user_id=first_user,
                               account_id=placeholder_one, seat='p1'),
                    GamePlayer(game_id='account-identity-game', user_id=second_user,
                               account_id=placeholder_two, seat='p2'),
                    GameCommand(id='actor-command-001', game_id='account-identity-game',
                                actor_user_id=second_user, kind='test', payload={}),
                    GameEvent(game_id='account-identity-game', event_index=1,
                              kind='test', actor_user_id=first_user, payload={}),
                ])

            async with database.engine.begin() as connection:
                def roundtrip(sync):
                    operations = Operations(MigrationContext.configure(sync))
                    with monkeypatch.context() as patch:
                        patch.setattr(migration, 'op', operations)
                        patch.setattr(migration.context, 'is_offline_mode', lambda: False)
                        # Present a real pre-0018 schema while retaining populated legacy rows.
                        for table, column in (
                            ('game_players', 'account_id'),
                            ('game_commands', 'actor_account_id'),
                            ('game_events', 'actor_account_id'),
                        ):
                            constraints = sync.execute(text("""
                                SELECT conname FROM pg_constraint
                                WHERE conrelid = to_regclass(:table_name) AND contype = 'f'
                                  AND pg_get_constraintdef(oid) ILIKE :column_pattern
                            """), {
                                'table_name': table,
                                'column_pattern': f'%({column})%',
                            }).scalars().all()
                            for name in constraints:
                                operations.drop_constraint(name, table, type_='foreignkey')
                        operations.drop_index('ix_game_players_account_id', table_name='game_players')
                        # Recreate the pre-0018 participant key before removing
                        # account_id from this latest-schema acceptance fixture.
                        operations.drop_constraint('game_players_pkey', 'game_players', type_='primary')
                        operations.create_primary_key(
                            'game_players_pkey', 'game_players', ['game_id', 'user_id'])
                        operations.drop_index('ix_game_commands_actor_account_id', table_name='game_commands')
                        operations.drop_index('ix_game_events_actor_account_id', table_name='game_events')
                        operations.drop_column('game_players', 'account_id')
                        operations.drop_column('game_commands', 'actor_account_id')
                        operations.drop_column('game_events', 'actor_account_id')
                        operations.drop_table('account_identities')

                        migration.upgrade()
                        rows = sync.execute(text("""
                            SELECT gp.user_id, gp.account_id, u.account_id AS user_account
                            FROM game_players gp JOIN users u ON u.id = gp.user_id
                            WHERE gp.game_id = 'account-identity-game' ORDER BY gp.seat
                        """)).mappings().all()
                        assert len(rows) == 2
                        assert all(row['account_id'] == row['user_account'] for row in rows)
                        assert rows[0]['account_id'] == linked_account
                        assert rows[1]['account_id'] != placeholder_two
                        assert sync.execute(text("""
                            SELECT count(*) FROM account_identities
                            WHERE provider = 'telegram' AND revoked_at IS NULL
                        """)).scalar_one() == 2
                        assert sync.execute(text("""
                            SELECT actor_account_id FROM game_commands
                            WHERE id = 'actor-command-001'
                        """)).scalar_one() == rows[1]['account_id']
                        assert sync.execute(text("""
                            SELECT actor_account_id FROM game_events
                            WHERE game_id = 'account-identity-game'
                        """)).scalar_one() == linked_account

                        # Clean downgrade keeps all legacy rows and user-account mappings.
                        migration.downgrade()
                        assert sync.execute(text(
                            "SELECT count(*) FROM game_players WHERE game_id = 'account-identity-game'"
                        )).scalar_one() == 2
                        assert sync.execute(text(
                            "SELECT account_id FROM users WHERE id = :id"
                        ), {'id': second_user}).scalar_one() is not None

                        migration.upgrade()
                        sync.execute(text("""
                            UPDATE account_identities SET revoked_at = now()
                            WHERE provider = 'telegram' AND provider_subject = :subject
                        """), {'subject': str(first_user)})
                        with pytest.raises(RuntimeError, match='account identity or game actor data has changed'):
                            migration.downgrade()
                await connection.run_sync(roundtrip)
    asyncio.run(run())
