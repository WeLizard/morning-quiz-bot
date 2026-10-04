"""End-to-end local milestone: real PostgreSQL, synthetic data, no Telegram IO."""
import asyncio
from decimal import Decimal
import json
import os
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select

from tests.local_database import isolated_database
from tests.test_admin_auth import TOKEN, login
from tests.test_json_importer import write_json
from tests.test_postgres_members import CHAT, OTHER_CHAT, USER, pg_env, scorer, answer
from tests.test_classic_recovery import game, manager
from tests.test_postgres_photos import payload
from tests.test_schedule_sync import workers, job_ids
from storage.json_importer import JsonSnapshot, JsonToPostgresImporter, source_digest
from storage.classic_sessions import ClassicSessions, ClassicSessionConflict
from storage.photos import PhotoSessions
from storage.models import Base, Chat, ChatMember, User, SystemState, DailySchedule, AchievementGrant, QuizSession
from storage.settings import SettingsService
from web.admin_auth import AdminAuth, install_admin_auth
from web.postgres_admin import make_router


def snapshot(root):
    write_json(root / 'global' / 'users.json', {str(USER): {'name': 'Локальный игрок', 'global_score': 12.25, 'total_answered': 2}})
    chat = root / 'chats' / str(CHAT)
    write_json(chat / 'users.json', {str(USER): {'name': 'Локальный игрок', 'score': 12.25,
        'answered_polls': ['imported-1', 'imported-2'], 'correct_answers_count': 2,
        'consecutive_correct': 2, 'max_consecutive_correct': 4, 'milestones_achieved': ['old-achievement'],
        'streak_achievements_earned': ['old-streak'], 'first_answer_time': '2026-01-01T10:00:00+00:00',
        'last_answer_time': '2026-08-29T10:00:00+00:00', 'custom_from_legacy': 'preserved'}})
    write_json(chat / 'settings.json', {'title': 'Локальный чат', 'auto_delete_bot_messages': True,
        'daily_quiz': {'enabled': False, 'times_msk': [{'hour': 9, 'minute': 0}], 'timezone': 'Europe/Moscow'},
        'daily_wisdom': {'enabled': False, 'time': '12:00'}})
    write_json(chat / 'stats.json', {'total_quizzes': 7})
    write_json(chat / 'categories_stats.json', {'Лес': {'chat_usage': 7}})
    write_json(root / 'statistics' / 'categories_stats.json', {'Лес': {'global_usage': 7, 'chat_usage': {str(CHAT): 7}}})
    write_json(root / 'photo_quiz_metadata.json', {'Сова': {'correct_answer': 'Сова', 'enabled': True, 'hints': {'first_letter': 'С'}}})
    return JsonSnapshot.scan(root)


def test_import_bot_admin_restart_and_photo_share_one_database(pg_env, tmp_path):
    async def run():
        source = snapshot(tmp_path)
        digest = source_digest(tmp_path)
        async with isolated_database(pg_env) as (db, _):
            report = await JsonToPostgresImporter(db, source).run()
            assert report['status'] == 'completed' and not report['errors']
            assert report['source'] == report['database']
            assert report['normalized_fingerprints']
            assert all(item['matched'] for item in report['normalized_fingerprints'].values())
            async with db.transaction() as session:
                member = await session.get(ChatMember, (CHAT, USER))
                assert member.score == Decimal('12.250')
                assert member.answered_poll_ids == ['imported-1', 'imported-2']
                assert (member.consecutive_correct, member.max_consecutive_correct) == (2, 4)
                assert member.extra['custom_from_legacy'] == 'preserved'
                assert member.first_answer_at.isoformat() == '2026-01-01T10:00:00+00:00'
                assert await session.scalar(select(func.count()).select_from(AchievementGrant)) == 2
                assert await session.scalar(select(func.count()).select_from(DailySchedule)) == 2
            live, quiz = await game(db)
            quiz.questions = [{'question': 'Кто?', 'original_category': 'Лес'}]
            await live._checkpoint_classic(quiz)
            score_manager = scorer(db)
            await answer(score_manager, 'durable-poll')
            await answer(score_manager, 'durable-poll')  # Redelivery is a no-op.

            app = FastAPI(); app.state.admin_database = db; app.include_router(make_router())
            install_admin_auth(app, auth=AdminAuth(TOKEN))
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://127.0.0.1') as client:
                client.headers['X-CSRF-Token'] = await login(client)
                users = (await client.get('/api/users')).json()['users']
                assert users[0]['total_score'] == 13.25 and users[0]['total_answered'] == 3
                response = await client.put(f'/api/users/{USER}/score', params={'chat_id': CHAT, 'new_score': '20.5', 'expected_score': '13.25'})
                assert response.status_code == 200
                revision = (await client.get(f'/api/chats/{CHAT}/settings')).headers['X-Settings-Revision']
                url = f'/api/chats/{CHAT}/settings?expected_revision={revision}'
                assert (await client.put(url, json={'daily_quiz': {'enabled': True, 'times_msk': [{'hour': 10, 'minute': 15}]}})).status_code == 200
                assert (await client.put(url, json={'daily_quiz': {'enabled': False}})).status_code == 409

                # New pool + new manager: no cached poll, score or schedule state.
                await db.engine.dispose()
                restored = manager(db); await restored.restore_all_active_quizzes()
                assert restored.state.get_active_quiz(CHAT).session_id == quiz.session_id
                restored.application.bot.send_message.assert_not_awaited()
                sync = workers(db); await sync.run_once()
                assert job_ids(sync)[0]
                await restored._checkpoint_classic(restored.state.get_active_quiz(CHAT), status='completed')
                overview = (await client.get('/api/analytics/overview')).json()
                assert overview['categories'][0]['usage'] == 8
                assert overview['answers'] == 3 and overview['activity'][0]['answers'] == 1

                photo = await PhotoSessions(db).create(payload())
                result = await PhotoSessions(db).complete_question(photo, correct=True, points=5.5)
                assert await PhotoSessions(db).complete_question(photo, correct=True, points=5.5) == result
                await PhotoSessions(db).save(result, status='completed')
                users = (await client.get('/api/users')).json()['users']
                assert users[0]['total_score'] == 26
                with pytest.raises(RuntimeError, match='empty operational'):
                    await JsonToPostgresImporter(db, source).run()
                assert (await client.get('/api/users')).json()['users'][0]['total_score'] == 26
                assert (await SettingsService(db).get(CHAT)).values['daily_quiz']['times_msk'] == [{'hour': 10, 'minute': 15}]
            assert source_digest(tmp_path) == digest
    asyncio.run(run())


def test_import_rolls_back_when_normalized_content_fingerprint_differs(pg_env, tmp_path, monkeypatch):
    async def mismatch(self, session):
        return {'users': {
            'source': 'source-digest', 'database': 'different-digest',
            'rows': 1, 'matched': False,
        }}

    async def run():
        from storage.migration_verification import MigrationVerification
        monkeypatch.setattr(MigrationVerification, 'compare', mismatch)
        source = snapshot(tmp_path)
        async with isolated_database(pg_env) as (db, _):
            with pytest.raises(ValueError, match='content verification failed'):
                await JsonToPostgresImporter(db, source).run()
            assert all(
                count == 0
                for count in (await JsonToPostgresImporter(db, source).database_counts()).values()
            )

    asyncio.run(run())


def test_parallel_completion_keeps_counters_and_duplicate_close_cannot_increment(pg_env):
    async def run():
        async with isolated_database(pg_env) as (db, _):
            one, first = await game(db); two, second = await game(db, OTHER_CHAT)
            for owner, state in ((one, first), (two, second)):
                state.questions = [{'original_category': 'Лес'}, {'original_category': 'Лес'}]
                await owner._checkpoint_classic(state)
            old = one._classic_snapshot(first)
            await asyncio.gather(one._checkpoint_classic(first, status='completed'), two._checkpoint_classic(second, status='completed'))
            with pytest.raises(ClassicSessionConflict):
                await ClassicSessions(db).save(old, status='completed')
            async with db.transaction() as session:
                stats = (await session.get(SystemState, 'category_usage_stats')).payload['Лес']
                assert stats['global_usage'] == 2
                assert stats['chat_usage'] == {str(CHAT): 1, str(OTHER_CHAT): 1}
                assert (await session.get(Chat, CHAT)).statistics['total_quizzes'] == 1
    asyncio.run(run())


def test_import_failure_rolls_back_all_rows_and_parallel_import_is_refused(pg_env, tmp_path):
    async def run():
        source = snapshot(tmp_path)
        async with isolated_database(pg_env) as (db, _):
            source.global_users['invalid-id'] = {'name': 'invalid'}
            with pytest.raises(ValueError, match='rolled back'):
                await JsonToPostgresImporter(db, source).run()
            assert all(count == 0 for count in (await JsonToPostgresImporter(db, source).database_counts()).values())
            del source.global_users['invalid-id']
            results = await asyncio.gather(*(JsonToPostgresImporter(db, source).run() for _ in range(2)), return_exceptions=True)
            assert sum(isinstance(result, RuntimeError) for result in results) == 1
            assert sum(isinstance(result, dict) for result in results) == 1
    asyncio.run(run())


def test_local_pg_dump_restores_synthetic_schema_exactly(pg_env, tmp_path):
    if os.getenv('MQB_TEST_DUMP_RESTORE') != '1':
        pytest.skip('Enable only with the shared local PostgreSQL container')
    async def run():
        async with isolated_database(pg_env) as (db, schema):
            await JsonToPostgresImporter(db, snapshot(tmp_path)).run()
            from storage.mini_app import MiniAppStore
            from web.mini_auth import TelegramIdentity
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc).timestamp()
            await MiniAppStore(db, 'synthetic-dump-key', clock=lambda: now).create_session(
                TelegramIdentity(USER, int(now), 'a' * 64))
            from storage.admin_actions import AdminActions
            from uuid import uuid4
            action = await AdminActions(db).block('users', USER, blocked=True, reason='Dump/restore fixture',
                                                  expected_revision=0, action_id=str(uuid4()))
            async def rows():
                async with db.transaction() as session:
                    return {table.name: sorted(json.dumps(dict(row), sort_keys=True, default=str)
                                              for row in (await session.execute(select(table))).mappings())
                            for table in Base.metadata.sorted_tables}
            original = await rows()
            if os.getenv('MQB_DEV_CONTAINER') == '1' and Path('/.dockerenv').is_file():
                parsed = urlsplit(pg_env)
                command = ['pg_dump', '-h', parsed.hostname, '-p', str(parsed.port)]
                restore_command = ['pg_restore', '-h', parsed.hostname, '-p', str(parsed.port)]
                pg_environment = os.environ.copy()
                pg_environment['PGPASSWORD'] = parsed.password or ''
            else:
                command = ['docker', 'exec', '-i', 'mqb-local-dev-postgres-1']
                restore_command = command
                pg_environment = None
            backup = subprocess.run(command + ['pg_dump', '-U', 'mqb_dev', '-d', 'morning_quiz_test', '-Fc', '-n', schema]
                                    if command[0] == 'docker' else command + ['-U', 'mqb_dev', '-d', 'morning_quiz_test', '-Fc', '-n', schema],
                                    capture_output=True, check=True, env=pg_environment).stdout
            assert backup.startswith(b'PGDMP')
            await SettingsService(db).patch_paths(CHAT, [(('title',), 'changed after backup')])
            await db.engine.dispose()
            restore_args = ['pg_restore', '-U', 'mqb_dev', '-d', 'morning_quiz_test', '--clean', '--if-exists', '--exit-on-error']
            if restore_command[0] != 'docker':
                restore_args = ['-U', 'mqb_dev', '-d', 'morning_quiz_test', '--clean', '--if-exists', '--exit-on-error']
            subprocess.run(restore_command + restore_args, input=backup, capture_output=True, check=True, env=pg_environment)
            assert await rows() == original
            assert not await AdminActions(db).allowed(user_id=USER)
            assert (await AdminActions(db).read_receipt(action['id'])) == action
            assert (await SettingsService(db).get(CHAT)).values['title'] == 'Локальный чат'
            async with db.transaction() as session:
                assert (await session.get(ChatMember, (CHAT, USER))).score == Decimal('12.250')
                assert (await session.get(User, USER)).global_score == Decimal('12.250')
                assert await session.scalar(select(func.count()).select_from(AchievementGrant)) == 2
    asyncio.run(run())


@pytest.mark.parametrize('value', ['bad-score', 'NaN', 'Infinity', True])
def test_import_never_converts_corrupt_score_to_zero(pg_env, tmp_path, value):
    async def run():
        source = snapshot(tmp_path)
        source.global_users[str(USER)]['global_score'] = value
        async with isolated_database(pg_env) as (db, _):
            with pytest.raises(ValueError, match='source score'):
                await JsonToPostgresImporter(db, source).run()
            assert all(n == 0 for n in (await JsonToPostgresImporter(db, source).database_counts()).values())
    asyncio.run(run())


def test_import_promotes_blacklist_keeps_source_scores_and_new_unban_decision(pg_env, tmp_path):
    async def run():
        from storage.admin_actions import AdminActions
        from storage.legacy_moderation import legacy_block_statements
        from uuid import uuid4
        source = snapshot(tmp_path)
        source.system_states['blacklist'] = {'users': {str(USER): {'name': 'Старое имя', 'reason': 'legacy reason'}},
                                              'chats': {str(OTHER_CHAT): {'title': 'Архивный чат'}}}
        async with isolated_database(pg_env) as (db, _):
            report = await JsonToPostgresImporter(db, source).run()
            assert report['processed']['legacy_blocks'] == 2
            service = AdminActions(db)
            assert not await service.allowed(user_id=USER)
            assert not await service.allowed(chat_id=OTHER_CHAT)
            async with db.transaction() as session:
                assert (await session.get(SystemState, 'blacklist')).payload == source.system_states['blacklist']
                user = await session.get(User, USER)
                assert user.global_score == Decimal('12.250') and user.display_name == 'Локальный игрок'
            await service.block('users', USER, blocked=False, reason='New admin decision', expected_revision=1, action_id=str(uuid4()))
            async with db.transaction() as session:
                for statement in legacy_block_statements(source.system_states['blacklist']):
                    await session.execute(statement)
            assert await service.allowed(user_id=USER)
    asyncio.run(run())


def test_invalid_legacy_blacklist_aborts_import_without_partial_data(pg_env, tmp_path):
    async def run():
        source = snapshot(tmp_path)
        source.system_states['blacklist'] = {'users': {'bad-id': {'reason': 'bad'}}}
        async with isolated_database(pg_env) as (db, _):
            with pytest.raises(ValueError, match='blacklist ID'):
                await JsonToPostgresImporter(db, source).run()
            assert all(n == 0 for n in (await JsonToPostgresImporter(db, source).database_counts()).values())
    asyncio.run(run())


def test_upgrade_promotes_previously_archived_blacklist_without_erasing_profiles(pg_env, tmp_path, monkeypatch):
    async def run():
        from alembic.config import Config
        from alembic.script import ScriptDirectory
        from storage.admin_actions import AdminActions
        source = snapshot(tmp_path)
        async with isolated_database(pg_env) as (db, _):
            await JsonToPostgresImporter(db, source).run()
            async with db.transaction() as session:
                session.add(SystemState(key='blacklist', payload={'users': {str(USER): {'reason': 'Old ban'}}}))
            migration = ScriptDirectory.from_config(Config('alembic.ini')).get_revision('20260830_0005').module
            async with db.engine.begin() as connection:
                def upgrade(sync):
                    with monkeypatch.context() as context:
                        context.setattr(migration.op, 'get_bind', lambda: sync)
                        migration.upgrade()
                await connection.run_sync(upgrade)
            assert not await AdminActions(db).allowed(user_id=USER)
            async with db.transaction() as session:
                assert (await session.get(User, USER)).global_score == Decimal('12.250')
                assert (await session.get(ChatMember, (CHAT, USER))).answered_poll_ids == ['imported-1', 'imported-2']
    asyncio.run(run())


def test_mini_session_migration_preserves_all_existing_operational_rows(pg_env, tmp_path, monkeypatch):
    async def run():
        from alembic.config import Config
        from alembic.migration import MigrationContext
        from alembic.operations import Operations
        from alembic.script import ScriptDirectory
        from storage.models import MiniAppSession
        async with isolated_database(pg_env) as (db, _):
            await JsonToPostgresImporter(db, snapshot(tmp_path)).run()
            async def existing_rows():
                async with db.transaction() as session:
                    return {table.name: sorted(json.dumps(dict(row), sort_keys=True, default=str)
                        for row in (await session.execute(select(table))).mappings())
                        for table in Base.metadata.sorted_tables if table.name != 'mini_app_sessions'}
            before = await existing_rows()
            migration = ScriptDirectory.from_config(Config('alembic.ini')).get_revision('20260830_0006').module
            async with db.engine.begin() as connection:
                def upgrade(sync):
                    MiniAppSession.__table__.drop(sync)
                    with monkeypatch.context() as patch:
                        patch.setattr(migration, 'op', Operations(MigrationContext.configure(sync)))
                        migration.upgrade()
                await connection.run_sync(upgrade)
            assert await existing_rows() == before
            async with db.transaction() as session:
                assert await session.scalar(select(func.count()).select_from(MiniAppSession)) == 0
    asyncio.run(run())


def test_archive_migration_preserves_every_existing_row(pg_env, tmp_path, monkeypatch):
    async def run():
        from alembic.config import Config
        from alembic.migration import MigrationContext
        from alembic.operations import Operations
        from alembic.script import ScriptDirectory
        async with isolated_database(pg_env) as (db, _):
            await JsonToPostgresImporter(db, snapshot(tmp_path)).run()
            async def rows():
                async with db.transaction() as session:
                    return {table.name: sorted(json.dumps(dict(row), sort_keys=True, default=str)
                        for row in (await session.execute(select(table))).mappings()) for table in Base.metadata.sorted_tables}
            before = await rows()
            migration = ScriptDirectory.from_config(Config('alembic.ini')).get_revision('20260831_0007').module
            async with db.engine.begin() as connection:
                def upgrade(sync):
                    operations = Operations(MigrationContext.configure(sync))
                    operations.drop_column('users', 'archived')
                    operations.drop_column('chats', 'archived')
                    with monkeypatch.context() as patch:
                        patch.setattr(migration, 'op', operations)
                        migration.upgrade()
                await connection.run_sync(upgrade)
            assert await rows() == before
    asyncio.run(run())
