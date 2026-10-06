"""Functional parity checks run on disposable fixtures, never the persistent dev DB."""
import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from modules.category_manager import CategoryManager
from modules.quiz_preferences import category_preferences
from storage.models import Chat, DailySchedule
from storage.settings import SettingsService
from tests.test_admin_auth import TOKEN, login
from tests.test_postgres_members import CHAT, pg_env, scenario
from tests.test_postgres_reads_settings import data_manager
from web.admin_auth import AdminAuth, install_admin_auth
from web.postgres_admin import install_postgres_admin


def test_bank_bulk_validates_before_writing_and_exports_every_category(tmp_path):
    from storage.question_bank import QuestionBank, BankConflict
    from tests.test_question_bank import QUESTION
    bank = QuestionBank(tmp_path)
    a = bank.create('A')
    bank.create('Untouched')
    with pytest.raises(ValueError):
        bank.import_all({'A': [QUESTION], 'B': [{'bad': True}]}, {'A': a['version'], 'B': None})
    assert bank.read('A')['count'] == 0 and not (tmp_path / 'B.json').exists()
    result = bank.import_all({'A': [QUESTION], 'B': [QUESTION]}, {'A': a['version'], 'B': None})
    assert result['completed'] == ['A', 'B'] and result['failed'] is None
    assert set(bank.export_all()['categories']) == {'A', 'B', 'Untouched'}
    with pytest.raises(BankConflict):
        bank.import_all({'A': [QUESTION]}, {'A': a['version']})
    assert bank.read('A')['count'] == 1


def test_report_scope_history_and_csv_formula_guard(pg_env):
    from storage.admin_analytics import report
    from storage.repositories import OperationalRepository
    from tests.test_postgres_members import USER, OTHER_CHAT
    from web.admin_analytics import csv_cell
    assert csv_cell('=HYPERLINK("bad")').startswith("'")
    assert csv_cell('  @SUM(1)').startswith("'")
    async def run():
        async with scenario(pg_env) as db:
            async with db.transaction() as session:
                repo = OperationalRepository(session)
                for cid in (CHAT, OTHER_CHAT):
                    await repo.ensure_chat({'id': cid})
                await repo.ensure_user({'id': USER, 'display_name': '=Formula', 'global_score': 17, 'total_answered': 5})
                await repo.ensure_member({'chat_id': CHAT, 'user_id': USER, 'score': 12, 'answered_count': 3})
                await repo.ensure_member({'chat_id': OTHER_CHAT, 'user_id': USER, 'score': 5, 'answered_count': 2})
            all_data = await report(db, days=7)
            local = await report(db, chat_id=CHAT, days=7)
            assert all_data['totals']['score'] == '17.000'
            assert local['totals']['score'] == '12.000'
            assert local['totals']['classic_answers'] == 3
            assert len(local['activity']) == 7 and not any(a['answers'] for a in local['activity'])
            assert sum(b['users'] for b in local['distribution']) == 1
            with pytest.raises(LookupError):
                await report(db, chat_id=42)
    asyncio.run(run())


def test_photo_replace_archive_restore_keeps_old_pixels(pg_env, tmp_path):
    from io import BytesIO
    from PIL import Image
    from uuid import uuid4
    from sqlalchemy import delete
    from storage.models import PhotoQuizItem
    from storage.photo_media import create_photo, UploadConflict, verified_image_path
    from storage.photos import PhotoCatalog, metadata_version, PhotoMetadataConflict
    image = BytesIO(); Image.new('RGB', (20, 20), 'blue').save(image, format='PNG')
    async def run():
        async with scenario(pg_env) as db:
            keys = []
            try:
                first, value, _ = await create_photo(db, uuid4().hex, image.getvalue(), 'Сова', True, root=tmp_path)
                keys.append(first)
                original_path = verified_image_path(tmp_path, first, value)
                original = original_path.read_bytes()
                replacement_id = uuid4().hex
                second, result, created = await create_photo(db, replacement_id, image.getvalue(), 'Новая сова', True,
                    root=tmp_path, replace_key=first, expected_version=metadata_version(value))
                keys.append(second)
                assert created and result['replaces'] == first
                _, _, repeated = await create_photo(db, replacement_id, image.getvalue(), 'Новая сова', True,
                    root=tmp_path, replace_key=first, expected_version=metadata_version(value))
                assert repeated is False
                catalog = PhotoCatalog(db)
                old = (await catalog.load())[first]
                assert old['archived'] and not old['enabled']
                assert verified_image_path(tmp_path, first, old).read_bytes() == original
                with pytest.raises(PhotoMetadataConflict):
                    await catalog.patch(first, {'enabled': True}, expected_version=metadata_version(old))
                restored = await catalog.archive(first, archived=False, expected_version=metadata_version(old))
                assert restored['enabled'] and not restored['archived']
                assert (await catalog.load())[second]['enabled']
            finally:
                async with db.transaction() as session:
                    await session.execute(delete(PhotoQuizItem).where(PhotoQuizItem.media_key.in_(keys)))
    asyncio.run(run())


def test_full_settings_flow_and_reset(pg_env):
    async def run():
        async with scenario(pg_env) as db:
            service = SettingsService(db)
            initial = await service.patch_paths(CHAT, [(('title',), 'Keep title'), (('daily_wisdom', 'enabled'), False)])
            app = FastAPI()
            install_postgres_admin(app)
            install_admin_auth(app, auth=AdminAuth(TOKEN))
            async with app.router.lifespan_context(app):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://127.0.0.1') as client:
                    client.headers['X-CSRF-Token'] = await login(client)
                    settings = dict(default_interval_seconds=0, default_announce_quiz=True,
                        default_announce_delay_seconds=45, quiz_categories_mode='exclude',
                        quiz_categories_pool=['Космос'], num_categories_per_quiz=5,
                        daily_quiz={'timezone': 'Europe/Istanbul'}, daily_wisdom={'time': '13:25', 'enabled': True})
                    url = f'/api/chats/{CHAT}/settings?expected_revision={initial.revision}'
                    changed = await client.put(url, json=settings)
                    assert changed.status_code == 200, changed.text
                    assert (await client.put(url, json=settings)).status_code == 409
                    dm = data_manager(db)
                    snapshot = await dm.get_chat_settings_async(CHAT)
                    assert dm.get_quiz_setting(CHAT, 'interval_seconds') == 0
                    assert dm.get_quiz_setting(CHAT, 'announce') is True
                    assert dm.get_quiz_setting(CHAT, 'announce_delay_seconds') == 45
                    assert category_preferences(snapshot) == ('exclude', ['Космос'], 5)
                    async with db.transaction() as session:
                        schedule = await session.scalar(select(DailySchedule).where(DailySchedule.chat_id == CHAT, DailySchedule.kind == 'wisdom'))
                        assert schedule.timezone == 'Europe/Istanbul' and schedule.enabled
                    revision = changed.json()['revision']
                    for bad in ({'default_interval_seconds': -1}, {'default_interval_seconds': True}, {'quiz_categories_pool': ['']}, {'quiz_categories_mode': 'bad'}):
                        assert (await client.put(f'/api/chats/{CHAT}/settings?expected_revision={revision}', json=bad)).status_code == 422
                    body = {'expected_revision': revision, 'confirmation': 'wrong'}
                    assert (await client.post(f'/api/chats/{CHAT}/reset-settings', json=body)).status_code == 422
                    body['confirmation'] = str(CHAT)
                    reset = await client.post(f'/api/chats/{CHAT}/reset-settings', json=body)
                    assert reset.status_code == 200, reset.text
                    assert reset.json()['settings']['title'] == 'Keep title'
                    assert reset.json()['settings']['default_announce_quiz'] is False
                    assert (await client.post(f'/api/chats/{CHAT}/reset-settings', json=body)).status_code == 409
    asyncio.run(run())


@pytest.mark.parametrize('mode,pool,expected', [('exclude', ['A'], {'B'}), ('specific', ['A'], {'A'}), ('specific', [], set()), ('random', [], {'A', 'B'})])
def test_category_pool_is_used_by_real_selector(mode, pool, expected):
    manager = CategoryManager.__new__(CategoryManager)
    manager.state = SimpleNamespace(quiz_data={'A': [{'question': 'A'}], 'B': [{'question': 'B'}]})
    manager.data_manager = SimpleNamespace(get_chat_settings=lambda _: {'quiz': {'categories_mode': mode, 'specific_categories': pool, 'num_random_categories': 2}})
    manager._get_weighted_random_categories = Mock(side_effect=lambda names, count, chat: names)
    questions = manager.get_questions(10, chat_id=CHAT)
    assert {q['current_category_name_for_quiz'] for q in questions} == expected


def test_setting_alias_conflicts_are_rejected_before_writes(pg_env):
    async def run():
        async with scenario(pg_env) as db:
            with pytest.raises(ValueError, match='Противоречащие'):
                await SettingsService(db).patch_paths(CHAT, [(('default_interval_seconds',), 5), (('quiz', 'interval_seconds'), 9)])
            async with db.transaction() as session:
                assert await session.get(Chat, CHAT) is None
    asyncio.run(run())


def test_mini_client_new_projections_and_no_public_demo_bypass(pg_env):
    from tests.test_mini_app import environment, login as mini_login
    from tests.test_postgres_members import USER, OTHER_CHAT
    async def run():
        async with environment(pg_env) as env:
            response = await env.client.get('/app', headers={'Sec-Fetch-Site': 'cross-site'})
            assert response.status_code == 200
            assert 'telegram.org' in response.headers['content-security-policy']
            assert '/app/app.js' in response.text and 'maximum-scale' not in response.text
            assert (await env.client.get('/app/app.js')).status_code == 200
            assert (await env.client.get('/app/host.webp')).status_code == 200
            assert (await env.client.get('/app/photo.webp')).status_code == 200\n            assert (await env.client.get('/app/host-card.svg')).status_code == 200\n            assert (await env.client.get('/app/mafia-card.svg')).status_code == 200
            assert (await env.client.post('/api/dev/session')).status_code == 404
            assert (await env.client.get('/api/mini/progress')).status_code == 401
            headers = await mini_login(env)
            progress = await env.client.get('/api/mini/progress', headers=headers)
            assert progress.status_code == 200 and 'PRIVATE_METADATA' not in progress.text
            ranking = await env.client.get('/api/mini/leaderboard', headers=headers)
            assert len(ranking.json()['items']) == 2 and 'user_id' not in ranking.text
            details = await env.client.get(f'/api/mini/chats/{CHAT}/details', headers=headers)
            assert details.status_code == 200 and details.json()['classic']['questions'] == 10
            assert (await env.client.get(f'/api/mini/chats/{OTHER_CHAT}/details', headers=headers)).status_code == 404
    asyncio.run(run())


def test_dev_mini_factory_rejects_nondev_database(monkeypatch):
    from web.dev_mini_app import create_dev_app, SYNTHETIC_TOKEN
    monkeypatch.setenv('MINI_APP_BOT_TOKEN', SYNTHETIC_TOKEN)
    monkeypatch.setenv('MINI_APP_ORIGIN', 'http://127.0.0.1:4185')
    monkeypatch.setenv('MINI_APP_OFFLINE', '1')
    monkeypatch.setenv('MINI_APP_DATABASE_URL', 'postgresql+asyncpg://mqb_dev:local-development-only@127.0.0.1:55433/morning_quiz_test')
    with pytest.raises(RuntimeError, match='dedicated loopback dev'):
        create_dev_app()


def test_maintenance_interrupts_games_and_survives_new_service(pg_env):
    from uuid import uuid4
    from storage.admin_actions import AdminActions, AdminConflict
    from storage.models import QuizSession
    from storage.repositories import OperationalRepository
    from storage.system_control import SystemControl
    from tests.local_database import isolated_database
    async def run():
        async with isolated_database(pg_env) as (db, _):
            async with db.transaction() as session:
                await OperationalRepository(session).ensure_chat({'id': CHAT})
                session.add(QuizSession(id=f'classic:{CHAT}', chat_id=CHAT, state={'polls': {'p': {'message_id': 8}}}, status='active'))
            control = SystemControl(db)
            aid = str(uuid4())
            result = await control.set_maintenance(enabled=True, reason='Dev test', expected_revision=0, action_id=aid)
            assert result['after']['interrupted_sessions'] == [f'classic:{CHAT}']
            assert not await AdminActions(db).allowed(CHAT)
            assert await AdminActions(db).allowed(CHAT, ignore_maintenance=True)
            assert (await SystemControl(db).read())['maintenance_mode']
            assert (await control.set_maintenance(enabled=True, reason='Dev test', expected_revision=0, action_id=aid))['id'] == aid
            with pytest.raises(AdminConflict):
                await control.set_maintenance(enabled=False, reason='stale', expected_revision=0, action_id=str(uuid4()))
            await control.set_maintenance(enabled=False, reason='Ready', expected_revision=1, action_id=str(uuid4()))
            assert await AdminActions(db).allowed(CHAT)
            async with db.transaction() as session:
                assert (await session.get(QuizSession, f'classic:{CHAT}')).status == 'interrupted'
    asyncio.run(run())


def test_category_reset_preserves_other_chat_and_records_receipt(pg_env):
    from uuid import uuid4
    from storage.category_statistics import CategoryStatistics
    from storage.models import SystemState
    from storage.repositories import OperationalRepository
    from tests.local_database import isolated_database
    from tests.test_postgres_members import OTHER_CHAT
    async def run():
        async with isolated_database(pg_env) as (db, _):
            async with db.transaction() as session:
                repo = OperationalRepository(session)
                await repo.ensure_chat({'id': CHAT, 'category_statistics': {'A': {'chat_usage': 3}}})
                await repo.ensure_chat({'id': OTHER_CHAT, 'category_statistics': {'A': {'chat_usage': 5}}})
                session.add(SystemState(key='category_usage_stats', payload={'A': {'global_usage': 8, 'chat_usage': {str(CHAT): 3, str(OTHER_CHAT): 5}}}))
            service = CategoryStatistics(db)
            before = await service.preview(CHAT)
            args = dict(expected_version=before['version'], confirmation=str(CHAT), action_id=str(uuid4()))
            receipt = await service.reset_chat(CHAT, **args)
            assert receipt['after']['local'] == {}
            assert (await service.reset_chat(CHAT, **args))['id'] == receipt['id']
            async with db.transaction() as session:
                assert (await session.get(Chat, OTHER_CHAT)).category_statistics['A']['chat_usage'] == 5
                assert (await session.get(SystemState, 'category_usage_stats')).payload['A']['global_usage'] == 5
    asyncio.run(run())


def test_maintenance_notice_is_throttled_persisted_and_never_sent_to_banned(pg_env):
    from datetime import datetime, timedelta, timezone
    from uuid import uuid4
    from storage.admin_actions import AdminActions
    from storage.system_control import SystemControl
    from storage.models import MessageCleanupItem
    from storage.repositories import OperationalRepository
    from tests.local_database import isolated_database
    async def run():
        async with isolated_database(pg_env) as (db, _):
            async with db.transaction() as session:
                await OperationalRepository(session).ensure_chat({'id': CHAT})
            service = SystemControl(db)
            await service.set_maintenance(enabled=True, reason='Test', expected_revision=0, action_id=str(uuid4()))
            now = datetime.now(timezone.utc)
            notice = await service.claim_notification(CHAT, None, now=now)
            assert notice['revision'] == 1
            assert await SystemControl(db).claim_notification(CHAT, None, now=now + timedelta(seconds=30)) is None
            await service.notification_sent(CHAT, 12, 1)
            assert str(CHAT) in (await service.read())['chats_notified']
            async with db.transaction() as session:
                assert await session.scalar(select(MessageCleanupItem).where(MessageCleanupItem.chat_id == CHAT, MessageCleanupItem.message_id == 12))
            assert await service.claim_notification(CHAT, None, now=now + timedelta(seconds=61))
            await AdminActions(db).block('chats', CHAT, blocked=True, reason='test', expected_revision=0, action_id=str(uuid4()))
            assert await service.claim_notification(CHAT, None, now=now + timedelta(minutes=3)) is None
    asyncio.run(run())
