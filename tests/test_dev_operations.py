import asyncio
from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy import select

from storage.broadcasts import Broadcasts, OfflineDelivery
from storage.admin_actions import AdminActions, AdminConflict
from storage.models import SystemState
from storage.repositories import OperationalRepository
from tests.local_database import isolated_database
from tests.test_postgres_members import pg_env, CHAT, OTHER_CHAT


def test_broadcast_frozen_preview_rechecks_blocks_and_no_duplicate(pg_env):
    async def run():
        async with isolated_database(pg_env) as (db, _):
            async with db.transaction() as session:
                for cid in (CHAT, OTHER_CHAT):
                    await OperationalRepository(session).ensure_chat({'id': cid, 'title': 'Тест'})
            delivery = OfflineDelivery({OTHER_CHAT: 'simulated_unknown'})
            delivery.deliver = Mock(wraps=delivery.deliver)
            service = Broadcasts(db, delivery)
            key = str(uuid4())
            args = dict(draft_id=key, chat_ids=[CHAT, OTHER_CHAT, CHAT], message='Hello <script>')
            draft = await service.preview(**args)
            assert len(draft['targets']) == 2 and draft['telegram_delivery'] is False
            assert await service.preview(**args) == draft
            with pytest.raises(AdminConflict):
                await service.preview(**{**args, 'message': 'changed'})
            with pytest.raises(ValueError):
                await service.simulate(key, confirmation='send to all')
            await AdminActions(db).block('chats', CHAT, blocked=True, reason='Test', expected_revision=0, action_id=str(uuid4()))
            report = await service.simulate(key, confirmation=draft['confirmation'])
            assert {r['status'] for r in report['results']} == {'skipped_blocked', 'simulated_unknown'}
            assert await service.simulate(key, confirmation=draft['confirmation']) == report
            delivery.deliver.assert_called_once_with(OTHER_CHAT, 'Hello <script>')
            assert (await Broadcasts(db).history())[0]['report'] == report
    asyncio.run(run())


def test_offline_runtime_real_start_quiz_buttons_and_stop(pg_env, monkeypatch, tmp_path):
    from modules.dev_runtime import DevRuntime, CHAT as DEMO_CHAT, USER as DEMO_USER
    from storage import dev_backups
    from storage.settings import SettingsService
    from storage.question_bank import QuestionBank
    monkeypatch.setenv('MQB_DEV_RUNTIME', 'offline')
    monkeypatch.setenv('BOT_TOKEN', '')
    monkeypatch.setenv('STORAGE_BACKEND', 'postgres')
    monkeypatch.setattr(dev_backups, 'guard', lambda db: None)
    monkeypatch.setattr(dev_backups, 'WORKSPACE', tmp_path)
    monkeypatch.setenv('PHOTO_IMAGES_DIR', str(tmp_path / 'images'))
    bank = QuestionBank(tmp_path / '.local' / 'preview' / 'questions')
    # Existing validated bank fixture format; the real reader is still used.
    directory = tmp_path / '.local' / 'preview' / 'questions'
    directory.mkdir(parents=True)
    (directory / 'Demo.json').write_text('[{"question":"One plus one?","options":["Two","Three"],"correct":"Two"}]', encoding='utf-8')
    async def run():
        async with isolated_database(pg_env) as (db, _):
            async with db.transaction() as session:
                repo = OperationalRepository(session)
                await repo.ensure_chat({'id': DEMO_CHAT, 'title': 'Тестовый чат'})
                await repo.ensure_user({'id': DEMO_USER, 'display_name': 'Dev'})
                await repo.ensure_member({'chat_id': DEMO_CHAT, 'user_id': DEMO_USER})
            await SettingsService(db).patch_paths(DEMO_CHAT, [(('default_num_questions',), 1), (('default_announce_quiz',), False)])
            runtime = DevRuntime(db)
            try:
                status = await runtime.start()
                assert status['running'] and status['telegram_delivery'] is False
                assert any(j['name'] == 'postgres_cleanup' for j in status['jobs'])
                result = await runtime.input(message='/start')
                assert result['messages']
                result = await runtime.input(message='/quiz')
                assert not any(e['event'] == 'handler_error' for e in result['events']), result['events']
                buttons = [(m['message_id'], b) for m in result['messages'] for row in m.get('reply_markup', {}).get('inline_keyboard', []) for b in row]
                assert buttons
                start = next((mid, b) for mid, b in buttons if b.get('callback_data', '').endswith('start'))
                result = await runtime.input(message_id=start[0], callback=start[1]['callback_data'])
                assert not any(e['event'] == 'handler_error' for e in result['events']), result['events']
                assert any(m.get('poll') for m in result['messages']), result['messages']
                from storage.models import User
                poll = next(m['poll'] for m in result['messages'] if m.get('poll'))
                correct = next(i for i, choice in enumerate(poll['options']) if choice['text'] == 'Two')
                await runtime.input(poll_id=poll['id'], option=correct)
                async with db.transaction() as session:
                    before = (await session.get(User, DEMO_USER)).global_score
                    assert before > 0
                await runtime.input(poll_id=poll['id'], option=correct)
                async with db.transaction() as session:
                    assert (await session.get(User, DEMO_USER)).global_score == before
                await runtime.input(message='/stopquiz')
                from storage.photo_media import create_photo
                from io import BytesIO
                from PIL import Image
                picture = BytesIO()
                Image.new('RGB', (20, 20), 'blue').save(picture, format='PNG')
                await create_photo(db, uuid4().hex, picture.getvalue(), 'сова', True, root=tmp_path / 'images')
                result = await runtime.input(message='/photo_quiz')
                start = next((m['message_id'], b) for m in result['messages'] for row in m.get('reply_markup', {}).get('inline_keyboard', []) for b in row if b.get('callback_data') == 'pqcfg_start')
                result = await runtime.input(message_id=start[0], callback=start[1]['callback_data'])
                assert any(m.get('photo') for m in result['messages']), result['messages']
                await runtime.input(message='сова')
                async with db.transaction() as session:
                    total = (await session.get(User, DEMO_USER)).global_score
                    assert total > before
                from storage.mini_app import MiniAppStore
                from web.mini_auth import TelegramIdentity
                import time
                from hashlib import sha256
                store = MiniAppStore(db, '123456:LOCAL_TEST_ONLY_012345678901234567890')
                auth = await store.create_session(TelegramIdentity(DEMO_USER, int(time.time()), sha256(uuid4().bytes).hexdigest()))
                assert (await store.profile(auth['access_token']))['score'] == str(total)
                assert (await store.progress(auth['access_token']))['correct_including_photo'] >= 2
                assert not any(e['event'] == 'handler_error' for e in runtime.events), runtime.events
            finally:
                status = await runtime.stop()
                assert not status['running']
    asyncio.run(run())
