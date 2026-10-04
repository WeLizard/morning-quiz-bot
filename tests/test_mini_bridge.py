import asyncio
from hashlib import sha256
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from storage.mini_bridge import MiniBridge
from storage.classic_sessions import ClassicSessions
from storage.mini_app import MiniAppError
from storage.models import Game, PollAnswer, User, QuizSession
from tests.test_mini_app import environment, signed, NOW, USER, TOKEN, ORIGIN
from tests.test_postgres_members import pg_env
from web.mini_app import create_app


def test_app_text_response_never_quotes_a_nonexistent_telegram_message():
    from telegram.request import RequestData
    from telegram.request._requestparameter import RequestParameter
    from modules.telegram_test_scope import PrivateTestScope, ScopedRequest
    from unittest.mock import AsyncMock
    async def run():
        scope = PrivateTestScope(USER, 123456)
        scope.local_message_ids.append(1000000042)
        original = RequestData([RequestParameter.from_input(key, value) for key, value in {
            'chat_id': USER, 'text': 'Try again', 'reply_parameters': {'message_id': 1000000042}, 'parse_mode': 'HTML'}.items()])
        inner = SimpleNamespace(do_request=AsyncMock(return_value=(200, b'{"ok":true,"result":true}')))
        await ScopedRequest(inner, scope, TOKEN).do_request('https://api.telegram.org/bot' + TOKEN + '/sendMessage', 'POST', original)
        sent = inner.do_request.call_args.kwargs['request_data'].parameters
        assert 'reply_parameters' not in sent and sent['text'] == 'Try again' and sent['parse_mode'] == 'HTML'
    asyncio.run(run())


@pytest.mark.parametrize('action', [
    {'type': 'command', 'value': '/restore'},
    {'type': 'text', 'value': '/backup'},
    {'type': 'callback', 'value': 'qcfg_start', 'message_id': 1, 'revision': 1},
    {'type': 'vote', 'value': True, 'message_id': 1},
    {'type': 'text', 'value': 'answer', 'user_id': USER + 1},
])
def test_bridge_rejects_untrusted_actions(action):
    with pytest.raises(MiniAppError):
        MiniBridge.validate({'request_id': uuid4().hex, **action}, {'messages': []}, NOW)


def test_bridge_http_privacy_queue_idempotency_and_no_spoilers(pg_env):
    async def run():
        async with environment(pg_env) as env:
            app = create_app(database=env.db, settings=env.settings, clock=lambda: NOW, runtime_enabled=True)
            bridge = MiniBridge(env.db, sha256(TOKEN.encode()).hexdigest(), USER, clock=lambda: NOW)
            await bridge.heartbeat()
            await bridge.publish('sendPoll', {'chat_id': USER, 'open_period': 60, 'correct_option_ids': [1], 'explanation': 'SECRET_EXPLANATION'},
                {'message_id': 10, 'poll': {'id': 'same-poll', 'question': 'Question', 'options': [{'text': 'A'}, {'text': 'B'}]}})
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
                asset = await client.get('/app/play-ui.js', headers={'Sec-Fetch-Site': 'cross-site'})
                assert asset.status_code == 200 and 'script-src' in asset.headers['content-security-policy']
                assert (await client.get('/api/mini/runtime')).status_code == 401
                login = await client.post('/api/mini/session', json={'init_data': signed()})
                headers = {'Authorization': 'Bearer ' + login.json()['access_token']}
                response = await client.get('/api/mini/runtime', headers=headers)
                assert response.status_code == 200 and response.json()['connected']
                assert '_answer' not in response.text and 'SECRET_EXPLANATION' not in response.text
                action = {'request_id': uuid4().hex, 'type': 'vote', 'value': 1, 'message_id': 10}
                first = await client.post('/api/mini/runtime/actions', headers=headers, json=action)
                assert first.status_code == 200, first.text
                assert (await client.post('/api/mini/runtime/actions', headers=headers, json=action)).json() == first.json()
                assert (await client.post('/api/mini/runtime/actions', headers=headers, json={**action, 'value': 0})).status_code == 409
                claimed = await bridge.claim()
                assert claimed[0] == action and await bridge.claim() is None
                await bridge.heartbeat(restart=True)
                result = (await client.get('/api/mini/runtime', headers=headers)).json()
                assert result['requests'][-1]['status'] == 'uncertain'
                other = await client.post('/api/mini/session', json={'init_data': signed(USER + 1)})
                other_headers = {'Authorization': 'Bearer ' + other.json()['access_token']}
                assert not (await client.get('/api/mini/runtime', headers=other_headers)).json()['messages']
                assert (await client.get('/api/mini/runtime/media/10', headers=other_headers)).status_code == 404
                assert (await client.post('/api/mini/runtime/actions', headers=other_headers, json=action)).status_code == 503
    asyncio.run(run())


def test_native_game_projection_uses_own_ledger_without_bank_or_other_players(pg_env):
    from datetime import datetime, timezone
    from decimal import Decimal
    from domain.photo import prepare_photo
    async def run():
        async with environment(pg_env) as env:
            classic = await ClassicSessions(env.db).create({
                'chat_id': USER, 'session_id': 'PRIVATE_SESSION_ID',
                'num_questions_to_ask': 3, 'current_question_index': 3,
                'questions': [{'correct': 'FUTURE_SECRET'}],
                'polls': {'round-poll': {'correct': 'HIDDEN_ANSWER'}},
                'scores': {str(USER + 1): {'name': 'OTHER_PLAYER_SECRET'}},
            })
            await ClassicSessions(env.db).save(classic, status='completed')
            async with env.db.transaction() as s:
                s.add(PollAnswer(poll_id='round-poll', user_id=USER, chat_id=USER, selected_option=1, is_correct=True, points_delta=Decimal('1.250')))
                s.add(PollAnswer(poll_id='round-poll', user_id=USER + 1, chat_id=USER, selected_option=0, is_correct=False, points_delta=Decimal('-0.500')))
                photo = prepare_photo(chat_id=USER, creator_id=USER, questions=[{
                    'display_answer': 'PHOTO_SECRET', 'media': {'media_key': 'private-path'}
                }])
                photo['last_result'] = {'round_id': photo['current_round_id'], 'question_number': 1,
                                        'correct': False, 'points': 0, 'answer': 'OUTCOME_SECRET',
                                        'reason': 'timeout'}
                s.add(Game(id=str(uuid4()), chat_id=USER, mode='photo', status='active',
                           phase='question_open', revision=photo['revision'], state=photo,
                           is_current=True, started_at=datetime.now(timezone.utc)))
            bridge = MiniBridge(env.db, 'unit', USER)
            async with env.db.transaction() as s:
                data = await bridge.snapshot(s)
            classic = next(g for g in data['games'] if g['kind'] == 'classic')
            assert classic['correct'] == 1 and Decimal(classic['points']) == Decimal('1.250')
            assert classic['total'] == 3 and classic['current'] == 3 and classic['status'] == 'completed'
            assert not any(value in str(data) for value in ['PRIVATE_SESSION_ID', 'FUTURE_SECRET', 'HIDDEN_ANSWER', 'OTHER_PLAYER_SECRET', 'PHOTO_SECRET', '/private/path', 'OUTCOME_SECRET'])
            async with env.db.transaction() as s:
                assert not (await MiniBridge(env.db, 'unit', USER + 1).snapshot(s))['games']
    asyncio.run(run())


def test_app_and_telegram_share_handlers_and_one_score(pg_env, monkeypatch, tmp_path):
    from scripts import run_telegram_test as runner
    from modules import dev_runtime as offline
    from modules.mini_bridge_worker import run_worker
    from modules.telegram_test_scope import PrivateTestScope
    from tests.local_database import isolated_database
    from storage.repositories import OperationalRepository
    from storage.settings import SettingsService
    from storage.photos import PhotoCatalog
    from telegram import Update
    from tests.test_telegram_test_scope import message_update, CHAT, BOT
    import telegram.request
    monkeypatch.setenv('BOT_TOKEN', TOKEN)
    monkeypatch.setenv('STORAGE_BACKEND', 'postgres')
    monkeypatch.setenv('MINI_APP_URL', '')
    image_dir = tmp_path / 'images'
    image_dir.mkdir()
    from PIL import Image
    Image.new('RGB', (16, 16), 'green').save(image_dir / 'Сова.webp')
    monkeypatch.setenv('PHOTO_IMAGES_DIR', str(image_dir))
    monkeypatch.setattr(runner, 'WORKSPACE', tmp_path)
    monkeypatch.setattr(offline, 'CHAT', CHAT)
    monkeypatch.setattr(offline, 'USER', CHAT)
    monkeypatch.setattr(offline, 'ROOM', {'id': CHAT, 'type': 'private', 'first_name': 'Tester'})
    monkeypatch.setattr(offline, 'PLAYER', {'id': CHAT, 'first_name': 'Tester', 'is_bot': False})
    directory = tmp_path / '.local' / 'preview' / 'questions'
    directory.mkdir(parents=True)
    (directory / 'Numbers.json').write_text('[{"question":"One plus one?","options":["One","Two"],"correct":"Two"}]', encoding='utf-8')
    immutable_runtime_files = {
        path.relative_to(tmp_path): path.read_bytes()
        for path in tmp_path.rglob('*') if path.is_file()
    }

    async def run():
        async with isolated_database(pg_env) as (db, _):
            async with db.transaction() as session:
                repo = OperationalRepository(session)
                await repo.ensure_chat({'id': CHAT, 'type': 'private'})
                await repo.ensure_user({'id': CHAT, 'display_name': 'Original name'})
                await repo.ensure_member({'chat_id': CHAT, 'user_id': CHAT})
            await SettingsService(db).patch_paths(CHAT, [(('default_num_questions',), 1), (('default_announce_quiz',), False)])
            await PhotoCatalog(db).get_or_create('Сова')
            dummy = offline.DevRuntime(db)
            monkeypatch.setattr(telegram.request, 'HTTPXRequest', lambda **kwargs: offline.OfflineRequest(dummy))
            scope = PrivateTestScope(CHAT, BOT)
            bridge = MiniBridge(db, sha256(TOKEN.encode()).hexdigest(), CHAT)
            scope.mini_bridge = bridge
            app, config, quiz, photos, dm = await runner.build_application(db, scope, TOKEN, None)
            worker = None
            async def view():
                async with db.transaction() as s:
                    return await bridge.snapshot(s)
            async def action(**fields):
                value = {'request_id': uuid4().hex, **fields}
                async with db.transaction() as s:
                    await bridge.enqueue(s, value)
                for _ in range(60):
                    await asyncio.sleep(.1)
                    result = await view()
                    receipt = next(r for r in result['requests'] if r['id'] == value['request_id'])
                    if receipt['status'] not in {'pending', 'running'}:
                        assert receipt['status'] == 'done', (
                            receipt,
                            [(event.get('event'), event.get('exception'))
                             for event in scope.events
                             if event.get('exception') or event.get('event') in {
                                 'handler_error', 'mini_app_failed',
                             }],
                        )
                        return result
                pytest.fail('Mini App action did not finish')
            try:
                await app.initialize(); await app.start()
                await bridge.heartbeat()
                worker = asyncio.create_task(run_worker(bridge, app, photos, scope, asyncio.Lock()))
                menu = await action(type='command', value='/quiz')
                card = next(m for m in reversed(menu['messages']) if any(b.get('data', '').endswith('start') for row in m['buttons'] for b in row))
                start = next(b['data'] for row in card['buttons'] for b in row if b['data'].endswith('start'))
                data = await action(type='callback', value=start, message_id=card['id'], revision=card['revision'])
                poll = next(m for m in data['messages'] if m.get('poll'))
                correct = poll['poll']['options'].index('Two')
                answered = await action(type='vote', value=correct, message_id=poll['id'])
                result = next(m for m in answered['messages'] if m['id'] == poll['id'])
                assert result['feedback']['correct'] is True
                game = next(g for g in answered['games'] if g['kind'] == 'classic')
                assert game['correct'] == 1 and game['total'] == 1 and float(game['points']) > 0
                async with db.transaction() as s:
                    player = await s.get(User, CHAT)
                    score = player.global_score
                    assert score > 0 and player.display_name == 'Original name'
                # The SAME answer arriving from Telegram cannot score a second time.
                actual = next(m['poll'] for m in scope.local_runtime.messages.values() if m.get('poll'))
                update = Update.de_json({'update_id': 987, 'poll_answer': {'poll_id': actual['id'], 'user': offline.PLAYER,
                    'option_ids': [correct], 'option_persistent_ids': [actual['options'][correct]['persistent_id']]}}, app.bot)
                await runner.dispatch(app, config, scope, update)
                async with db.transaction() as s:
                    assert (await s.get(User, CHAT)).global_score == score
                await action(type='command', value='/adminsettings')
                await action(type='command', value='/start')
                photo_menu = await action(type='command', value='/photo_quiz')
                photo_card = next(m for m in reversed(photo_menu['messages']) if any(b.get('data') == 'pqcfg_start' for row in m['buttons'] for b in row))
                photo = await action(type='callback', value='pqcfg_start', message_id=photo_card['id'], revision=photo_card['revision'])
                for _ in range(30):
                    if any(g['kind'] == 'photo' for g in photo['games']): break
                    await asyncio.sleep(.1)
                    photo = await view()
                game = next(g for g in photo['games'] if g['kind'] == 'photo')
                assert game['current'] == 1 and game['phase'] == 'question_open' and game['question_started_at']
                assert any(m.get('media') for m in photo['messages'])
                assert '_media' not in str(photo) and 'normalized_answer' not in str(photo)
                await action(type='text', value='Сова')
                async with db.transaction() as s:
                    assert (await s.get(User, CHAT)).global_score > score
                await action(type='command', value='/stop_photo_quiz')
                assert not any(e['event'] in {'handler_error', 'blocked_outbound'} for e in scope.events), scope.events
            finally:
                if worker:
                    worker.cancel(); await asyncio.gather(worker, return_exceptions=True)
                await photos.shutdown()
                if app.running: await app.stop()
                await dm.flush_postgres_writes(); await app.shutdown()
    asyncio.run(run())
    assert {
        path.relative_to(tmp_path): path.read_bytes()
        for path in tmp_path.rglob('*') if path.is_file()
    } == immutable_runtime_files
    assert not list(tmp_path.rglob('*.pickle'))
