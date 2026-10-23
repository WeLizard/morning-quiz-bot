"""Mini App contract and isolation. Telegram transport is always synthetic."""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
import hmac
import json
from types import SimpleNamespace
from urllib.parse import urlencode
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from starlette.requests import Request
from sqlalchemy import delete, func, select

from tests.test_postgres_members import CHAT, OTHER_CHAT, USER, pg_env, scenario
from storage.admin_actions import AdminActions
from storage.classic_sessions import ClassicSessions
from storage.games import GameRepository
from storage.mini_app import MiniAppError, MiniAppStore
from storage.models import (AchievementGrant, AlchemyProgress, Chat, ChatMember, Game, GamePlayer,
                            MiniAppSession, PollAnswer, QuizSession, User)
from storage.repositories import OperationalRepository
from storage.question_bank import BankConflict, PostgresQuestionBank
from storage.settings import SettingsService
from web.mini_auth import InvalidInitData, validate_init_data
from web.mini_app import (MiniAppSettings, RequestLimits, TelegramMembership,
                          bounded_request_body, create_app)
from web import mini_app as mini_app_module

TOKEN = '123456:LOCAL_TEST_ONLY_012345678901234567890'
ORIGIN = 'http://127.0.0.1:4185'
NOW = 1788120000


def signed(uid=USER, date=NOW, **extras):
    fields = {'auth_date': str(date), 'user': json.dumps({'id': uid, 'first_name': 'Тест & + 🦉'}, ensure_ascii=False), **extras}
    check = '\n'.join(f'{key}={value}' for key, value in sorted(fields.items()))
    key = hmac.new(b'WebAppData', TOKEN.encode(), sha256).digest()
    fields['hash'] = hmac.new(key, check.encode(), sha256).hexdigest()
    return urlencode(fields)


@asynccontextmanager
async def environment(url, *, membership=True, runtime_enabled=False):
    async with scenario(url) as db:
        now = [NOW]
        async with db.transaction() as session:
            repo = OperationalRepository(session)
            for cid, kind in [(CHAT, 'supergroup'), (OTHER_CHAT, 'supergroup'), (USER, 'private'), (USER + 1, 'private')]:
                await repo.ensure_chat({'id': cid, 'type': kind, 'title': f'Test {cid}'})
            for uid in (USER, USER + 1):
                await repo.ensure_user({'id': uid, 'display_name': f'Player {uid}'})
                user = await session.get(User, uid)
                user.global_score = Decimal('12.250')
                user.metadata_json = {'secret': 'PRIVATE_METADATA'}
            for cid, uid in [(CHAT, USER), (CHAT, USER + 1), (OTHER_CHAT, USER + 1), (USER, USER), (USER + 1, USER + 1)]:
                await repo.ensure_member({'chat_id': cid, 'user_id': uid, 'score': 12.25})
        try:
            await PostgresQuestionBank(db).create('Тестовая категория')
        except BankConflict:
            pass
        verifier = SimpleNamespace(allowed=AsyncMock(return_value=membership)) if membership is not None else None
        settings = MiniAppSettings(TOKEN, ORIGIN, offline=True)
        app = create_app(database=db, settings=settings, membership=verifier, clock=lambda: now[0],
                         runtime_enabled=runtime_enabled)
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
                yield SimpleNamespace(db=db, app=app, client=client, now=now, verifier=verifier, settings=settings)
        finally:
            async with db.transaction() as session:
                from storage.models import PhotoQuizItem, QuestionCategory, QuestionCategoryRevision
                # История ревизий тоже убирается: иначе следующий прогон падает на
                # уникальности (category_name, revision) ещё до создания категории.
                await session.execute(delete(QuestionCategoryRevision).where(
                    QuestionCategoryRevision.category_name == 'Тестовая категория'
                ))
                await session.execute(delete(QuestionCategory).where(
                    QuestionCategory.name == 'Тестовая категория'
                ))
                # Каталог фото глобальный (без chat_id), каскадом за чатом не уходит:
                # без явной уборки строка 'Сова' остаётся в общей тестовой БД и
                # ломает проверки каталога в других тестах.
                await session.execute(delete(PhotoQuizItem).where(PhotoQuizItem.media_key == 'Сова'))
                await session.execute(delete(Chat).where(Chat.id.in_([USER, USER + 1])))


async def login(env, uid=USER, **extras):
    response = await env.client.post('/api/mini/session', json={'init_data': signed(uid, **extras)})
    assert response.status_code == 200, response.text
    token = env.client.cookies.get('mqb_mini')
    assert token and response.json().get('access_token') is None
    env.client.cookies.delete('mqb_mini')
    return {'Authorization': 'Bearer ' + token}


def test_farm_main_menu_art_is_served_by_the_public_asset_route(pg_env):
    async def run():
        async with environment(pg_env) as env:
            response = await env.client.get('/app/farm-card-v2.webp')
            assert response.status_code == 200
            assert response.headers['content-type'].startswith('image/webp')
            assert response.content[:4] == b'RIFF' and response.content[8:12] == b'WEBP'
            assert "default-src 'none'" in response.headers['content-security-policy']
    asyncio.run(run())


def test_login_uses_http_only_cookie_and_cookie_writes_require_csrf(pg_env):
    async def run():
        async with environment(pg_env) as env:
            signed_in = await env.client.post('/api/mini/session', json={'init_data': signed()})
            assert signed_in.status_code == 200
            assert 'access_token' not in signed_in.json()
            cookie = signed_in.headers['set-cookie'].lower()
            cookie_attributes = {part.strip() for part in cookie.split(';')[1:]}
            assert 'mqb_mini=' in cookie and 'httponly' in cookie_attributes and 'samesite=strict' in cookie
            assert 'secure' not in cookie_attributes  # test origin is loopback HTTP; HTTPS deployments set Secure.
            assert (await env.client.get('/api/mini/me')).status_code == 200
            payload = {'discovered': [], 'crafted': [], 'attempts': 0}
            denied = await env.client.post('/api/mini/alchemy/sync', json=payload)
            assert denied.status_code == 403
            accepted = await env.client.post('/api/mini/alchemy/sync', json=payload,
                headers={'Origin': ORIGIN, 'X-Mini-CSRF': '1', 'X-Mini-User': str(USER)})
            assert accepted.status_code == 200
    asyncio.run(run())


def test_legacy_telegram_transcript_bridge_routes_are_removed(pg_env):
    async def run():
        async with environment(pg_env, runtime_enabled=True) as env:
            headers = await login(env)
            assert (await env.client.get('/api/mini/runtime', headers=headers)).status_code == 404
            assert (await env.client.post('/api/mini/runtime/actions', headers=headers, json={
                'request_id': uuid4().hex, 'type': 'command', 'value': '/quiz',
            })).status_code == 404
            assert (await env.client.get('/api/mini/runtime/media/1', headers=headers)).status_code == 404
    asyncio.run(run())


@pytest.mark.parametrize('extras', [{}, {'signature': 'signed-extra-field'}, {'start_param': 'hello_world'}, {'chat': '{"id":123}'}])
def test_hmac_accepts_decoded_unicode_and_all_signed_fields(extras):
    identity = validate_init_data(signed(**extras), TOKEN, now=NOW)
    assert identity.user_id == USER and identity.auth_date == NOW


@pytest.mark.parametrize('raw', [
    '', 'x=%ZZ', 'hash=bad', signed().replace(str(USER), str(USER + 1)),
    signed() + '&auth_date=' + str(NOW), signed() + '&hash=' + '0' * 64,
    signed(date=NOW-301), signed(date=NOW+31), signed(uid=True), signed(uid='123'),
    signed(uid=-1), signed(uid=2**52), signed(user='{"id":1,"id":2}'),
    signed(user='{"id":1,"is_bot":true}'), signed(user='null'),
    signed(user='{"id":1,"first_name":"injected"}\nquery_id=x'),
    'x=' + 'a' * 17000, signed(signature='valid').replace('signature=valid', 'signature=forged'),
])
def test_hmac_rejects_tampering_duplicates_expiry_and_invalid_identity(raw):
    with pytest.raises(InvalidInitData):
        validate_init_data(raw, TOKEN, now=NOW)


def test_wrong_bot_token_cannot_validate_init_data():
    with pytest.raises(InvalidInitData):
        validate_init_data(signed(), TOKEN + 'other', now=NOW)


def test_bounded_body_rejects_declared_size_before_reading():
    async def run():
        async def unexpected_read():
            raise AssertionError('oversized body must be rejected before streaming')
        request = Request({'type': 'http', 'headers': [(b'content-length', b'2001')]}, unexpected_read)
        with pytest.raises(MiniAppError) as error:
            await bounded_request_body(request, max_bytes=2000)
        assert error.value.status == 413
    asyncio.run(run())


def test_bounded_body_rejects_oversized_stream_without_joining_it():
    async def run():
        delivered = False
        async def receive():
            nonlocal delivered
            if delivered:
                return {'type': 'http.request', 'body': b'', 'more_body': False}
            delivered = True
            return {'type': 'http.request', 'body': b'x' * 2001, 'more_body': False}
        request = Request({'type': 'http', 'headers': []}, receive)
        with pytest.raises(MiniAppError) as error:
            await bounded_request_body(request, max_bytes=2000)
        assert error.value.status == 413
    asyncio.run(run())


@pytest.mark.parametrize(('path', 'limit'), [
    ('/api/mini/alchemy/sync', 128 * 1024),
    ('/api/mini/alchemy/craft', 512),
    (f'/api/mini/mafia/chats/{USER}/discussion', 5000),
])
def test_write_routes_reject_oversized_declared_body_before_parsing(pg_env, path, limit):
    async def run():
        async with environment(pg_env) as env:
            response = await env.client.post(
                path, content=b'x' * (limit + 1),
                headers={'Content-Type': 'application/json'},
            )
            assert response.status_code == 413
    asyncio.run(run())


def test_legacy_write_routes_reject_declared_oversize_before_reading(pg_env):
    routes = [
        ('post', '/api/mini/session', 20000),
        ('post', '/api/guest/rooms', 2000),
        ('post', '/api/guest/rooms/test-room/invites', 2000),
        ('post', '/api/guest/alchemy/sync', 128 * 1024),
        ('post', '/api/guest/rooms/test-room/mafia/lobby', 500),
        ('post', '/api/guest/rooms/test-room/mafia/lobby/join', 500),
        ('post', '/api/guest/rooms/test-room/mafia/lobby/ready', 500),
        ('post', '/api/guest/rooms/test-room/mafia/lobby/start', 500),
        ('post', '/api/guest/rooms/test-room/mafia/discussion', 5000),
        ('post', '/api/guest/rooms/test-room/mafia/action', 500),
        ('post', '/api/guest/rooms/test-room/mafia/vote', 500),
        ('post', '/api/guest/rooms/test-room/mafia/advance', 500),
        ('post', '/api/guest/rooms/test-room/mafia/restart', 500),
        ('put', f'/api/mini/chats/{USER}/classic-settings', 1000),
        ('put', f'/api/mini/chats/{USER}/preferences', 12000),
        ('post', f'/api/mini/classic/chats/{USER}/start', 300),
        ('post', f'/api/mini/classic/chats/{USER}/stop', 300),
        ('post', f'/api/mini/classic/chats/{USER}/answer', 500),
        ('post', f'/api/mini/photo/chats/{USER}/start', 500),
        ('post', f'/api/mini/photo/chats/{USER}/answer', 1000),
        ('post', f'/api/mini/photo/chats/{USER}/stop', 300),
        ('put', '/api/mini/mafia/draft', 1000),
        ('post', f'/api/mini/mafia/chats/{USER}/discussion', 5000),
        ('post', f'/api/mini/mafia/chats/{USER}/lobby/ready', 200),
        ('post', f'/api/mini/mafia/chats/{USER}/lobby/start', 160),
        ('post', f'/api/mini/mafia/chats/{USER}/action', 240),
        ('post', f'/api/mini/mafia/chats/{USER}/vote', 240),
        ('post', f'/api/mini/mafia/chats/{USER}/advance', 240),
        ('post', f'/api/mini/mafia/chats/{USER}/restart', 240),
    ]

    async def run():
        async with environment(pg_env, runtime_enabled=True) as env:
            for method, path, limit in routes:
                headers = {
                    'Content-Type': 'application/json',
                    'Origin': ORIGIN,
                    'X-Mini-CSRF': '1',
                    'X-Guest-CSRF': '1',
                }
                if path == '/api/guest/alchemy/sync':
                    started = await env.client.post(
                        '/api/guest/start', headers=headers, json={},
                    )
                    headers['X-Guest-Account'] = started.json()['account_id']
                response = await env.client.request(
                    method, path, content=b'x' * (limit + 1),
                    headers=headers,
                )
                assert response.status_code == 413, f'{method.upper()} {path}: {response.text}'
    asyncio.run(run())


@pytest.mark.parametrize('origin,offline', [('http://public.example', False), ('http://public.example', True),
    ('https://example.com/', False), ('https://user@example.com', False), ('https://example.com?x=1', False),
    ('https://*', False), ('', False)])
def test_settings_fail_closed(origin, offline):
    with pytest.raises(ValueError):
        MiniAppSettings(TOKEN, origin, offline)


def test_profile_uses_stored_values_and_session_survives_app_restart(pg_env):
    async def run():
        async with environment(pg_env) as env:
            headers = await login(env)
            profile = await env.client.get('/api/mini/me', headers=headers)
            assert profile.json() == {'user_id': str(USER), 'account_id': profile.json()['account_id'],
                                      'display_name': f'Player {USER}', 'score': '12.250', 'answered_count': 0,
                                      'address_form': 'n', 'address_form_chosen': False,
                                      'contrast_mode': False}
            assert 'PRIVATE_METADATA' not in profile.text
            assert profile.headers['cache-control'] == 'no-store'
            assert not profile.cookies and 'set-cookie' not in profile.headers
            restarted = create_app(database=env.db, settings=env.settings, clock=lambda: env.now[0])
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=restarted), base_url=ORIGIN) as client:
                assert (await client.get('/api/mini/me', headers=headers)).json() == profile.json()
            async with env.db.transaction() as session:
                row = await session.scalar(select(MiniAppSession).where(MiniAppSession.user_id == USER))
                assert row.token_hash == sha256(headers['Authorization'][7:].encode()).hexdigest()
                assert row.token_hash not in headers['Authorization']
                assert (await session.get(User, USER)).global_score == Decimal('12.250')
    asyncio.run(run())


def test_classic_v2_runs_in_mini_app_without_telegram_bridge(pg_env):
    async def run():
        async with environment(pg_env, runtime_enabled=True) as env:
            bank = PostgresQuestionBank(env.db)
            category = await bank.read('Тестовая категория')
            await bank.change(
                'Тестовая категория', category['version'],
                question={
                    'question': 'Кто ведёт Morning Quiz?',
                    'options': ['Филиныч', 'Кот'],
                    'correct': 'Филиныч',
                    'explanation': 'Конечно, Филиныч.',
                },
            )
            headers = await login(env)
            started = await env.client.post(
                f'/api/mini/classic/chats/{USER}/start', headers=headers,
                json={'command_id': str(uuid4())},
            )
            assert started.status_code == 200, started.text
            game = started.json()
            assert game['status'] == 'active'
            assert game['phase'] == 'question_open'
            assert game['question']['round_id']
            assert 'correct_option' not in game['question']

            answer_command = str(uuid4())
            payload = {
                'round_id': game['question']['round_id'],
                'selected_option': 0,
                'command_id': answer_command,
            }
            answered = await env.client.post(
                f'/api/mini/classic/chats/{USER}/answer', headers=headers,
                json=payload,
            )
            assert answered.status_code == 200, answered.text
            repeated = await env.client.post(
                f'/api/mini/classic/chats/{USER}/answer', headers=headers,
                json=payload,
            )
            assert repeated.status_code == 200
            assert repeated.json() == answered.json()

            async with env.db.transaction() as session:
                row = await session.scalar(select(Game).where(
                    Game.chat_id == USER, Game.mode == 'classic',
                    Game.is_current.is_(True),
                ))
                assert row and row.state['mode'] == 'classic'
                assert await session.get(QuizSession, f'classic:{USER}') is None
                answers = (await session.scalars(select(PollAnswer).where(
                    PollAnswer.game_id == row.id,
                    PollAnswer.round_id == payload['round_id'],
                    PollAnswer.user_id == USER,
                ))).all()
                assert len(answers) == 1

            stopped = await env.client.post(
                f'/api/mini/classic/chats/{USER}/stop', headers=headers,
                json={
                    'command_id': str(uuid4()),
                    'expected_revision': answered.json()['revision'],
                },
            )
            assert stopped.status_code == 200, stopped.text
            assert stopped.json()['status'] == 'stopped'
            assert (await env.client.post(
                f'/api/mini/classic/chats/{USER}/sync', headers=headers
            )).status_code == 404
    asyncio.run(run())


def test_replay_logout_expiry_and_token_rotation(pg_env):
    async def run():
        async with environment(pg_env) as env:
            headers = await login(env)
            assert (await env.client.post('/api/mini/session', json={'init_data': signed()})).status_code == 409
            assert (await env.client.delete('/api/mini/session', headers=headers)).status_code == 204
            assert (await env.client.get('/api/mini/me', headers=headers)).status_code == 401
            assert (await env.client.post('/api/mini/session', json={'init_data': signed()})).status_code == 409
            fresh = await login(env, query_id='another-launch')
            rotated = MiniAppStore(env.db, TOKEN + 'rotation', clock=lambda: env.now[0])
            with pytest.raises(MiniAppError) as error:
                await rotated.profile(fresh['Authorization'][7:])
            assert error.value.status == 401
            env.now[0] += 900
            assert (await env.client.get('/api/mini/me', headers=fresh)).status_code == 401
    asyncio.run(run())


def test_session_renewal_extends_the_same_token_without_new_login(pg_env):
    async def run():
        async with environment(pg_env) as env:
            headers = await login(env)
            async with env.db.transaction() as session:
                before = await session.scalar(select(MiniAppSession).where(MiniAppSession.user_id == USER))
                rows_before = await session.scalar(select(func.count()).select_from(MiniAppSession).where(
                    MiniAppSession.user_id == USER))
            env.now[0] += 700                     # 11+ минут: сессия ещё жива, но близко к границе
            assert (await env.client.get('/api/mini/me', headers=headers)).status_code == 200
            renewed = await env.client.post('/api/mini/session/renew', headers=headers)
            assert renewed.status_code == 200
            assert renewed.json()['expires_in'] == 900
            assert (await env.client.get('/api/mini/me', headers=headers)).status_code == 200
            async with env.db.transaction() as session:
                after = await session.scalar(select(MiniAppSession).where(MiniAppSession.user_id == USER))
                rows_after = await session.scalar(select(func.count()).select_from(MiniAppSession).where(
                    MiniAppSession.user_id == USER))
            assert rows_after == rows_before       # продление не создаёт новый вход
            assert after.expires_at > before.expires_at and after.created_at == before.created_at
    asyncio.run(run())


def test_session_renewal_rejects_revoked_and_expired_tokens(pg_env):
    async def run():
        async with environment(pg_env) as env:
            headers = await login(env, signature='logout-case')
            assert (await env.client.post('/api/mini/session/renew', headers=headers)).status_code == 200
            assert (await env.client.delete('/api/mini/session', headers=headers)).status_code == 204
            assert (await env.client.post('/api/mini/session/renew', headers=headers)).status_code == 401
            fresh = await login(env, signature='expiry-case')
            env.now[0] += 16 * 60
            assert (await env.client.post('/api/mini/session/renew', headers=fresh)).status_code == 401
            assert (await env.client.get('/api/mini/me', headers=fresh)).status_code == 401
    asyncio.run(run())


def test_achievements_projection_shows_earned_upcoming_and_no_foreign_data(pg_env):
    async def run():
        async with environment(pg_env) as env:
            async with env.db.transaction() as session:
                session.add(AchievementGrant(user_id=USER, chat_id=CHAT,
                                             code=f'chat_achievement_{CHAT}_{USER}_25',
                                             metadata_json={'secret': 'ADMIN-ONLY'}))
                member = await session.get(ChatMember, (CHAT, USER))
                member.milestone_codes = [f'chat_achievement_{CHAT}_{USER}_{t}'
                                          for t in (0, 10, 15, 25, 30, 50, 75, 100)]
                member.max_consecutive_correct = 4
            headers = await login(env)
            response = await env.client.get('/api/mini/achievements', headers=headers)
            assert response.status_code == 200
            data = response.json()
            summary = data['summary']
            assert summary['chat_achievements'] > 0 and 0 < summary['earned'] <= summary['available']
            chat = next(item for item in data['chats'] if item['chat_id'] == str(CHAT))
            earned = [item for item in chat['items'] if item['earned']]
            ahead = [item for item in chat['items'] if not item['earned']]
            assert len(earned) <= 6                                        # полученные показываем выборочно
            assert {'100 очков', '75 очков'} <= {item['title'] for item in earned}
            # Ближайшие впереди не должны вытесняться лимитом на полученные.
            assert '125 очков' in {item['title'] for item in ahead}
            assert all(item['kind'] != 'streak' for item in chat['items'])
            assert data['streak']['best'] == 4 and any(item['earned'] for item in data['streak']['items'])
            # Чужие данные и метаданные наград наружу не уходят.
            assert 'ADMIN-ONLY' not in response.text and 'metadata' not in response.text
            assert str(USER + 1) not in response.text
    asyncio.run(run())


def test_history_projection_covers_games_answers_and_chat_totals(pg_env):
    async def run():
        async with environment(pg_env) as env:
            moment = datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc)
            async with env.db.transaction() as session:
                await GameRepository(session).ensure_telegram_room(CHAT)
                session.add(Game(id='game-1', chat_id=CHAT, room_id=f'telegram:{CHAT}', mode='photo', status='finished', phase='finished',
                                 is_current=False, started_at=moment - timedelta(minutes=10), ended_at=moment))
                account_id = await GameRepository(session).account_for_telegram_user(USER)
                session.add(GamePlayer(
                    game_id='game-1', account_id=account_id, user_id=USER, seat='player'))
                session.add(PollAnswer(poll_id='p-1', user_id=USER, chat_id=CHAT, is_correct=True,
                                       points_delta=Decimal('1.500'), answered_at=moment,
                                       game_id='game-1', round_id='r-1'))
                session.add(PollAnswer(poll_id='p-2', user_id=USER, chat_id=CHAT, is_correct=False,
                                       points_delta=Decimal('-0.500'), answered_at=moment + timedelta(minutes=1),
                                       game_id='game-1', round_id='r-2'))
                session.add(PollAnswer(poll_id='p-3', user_id=USER + 1, chat_id=CHAT, is_correct=True,
                                       points_delta=Decimal('9.000'), answered_at=moment + timedelta(minutes=2)))
                member = await session.get(ChatMember, (CHAT, USER))
                member.answered_count, member.correct_answers_count = 7, 5
                member.first_answer_at = moment - timedelta(days=3)
                member.last_answer_at = moment + timedelta(minutes=1)
            headers = await login(env)
            response = await env.client.get('/api/mini/history', headers=headers)
            assert response.status_code == 200
            data = response.json()
            game = next(item for item in data['games'] if item['game_id'] == 'game-1')
            assert (game['mode'], game['status']) == ('photo', 'finished')
            assert (game['my_answers'], game['my_correct']) == (2, 1)
            assert [item['is_correct'] for item in data['answers']] == [False, True]   # свежие сверху
            assert data['answers'][0]['points'] == '-0.500'
            chat = next(item for item in data['chats'] if item['chat_id'] == str(CHAT))
            assert (chat['answered'], chat['correct']) == (7, 5) and chat['score'] == '12.250'
            # Чужие ответы и служебные payload-ы в проекцию не попадают.
            assert '9.000' not in response.text and str(USER + 1) not in response.text
            assert 'payload' not in response.text and 'private_state' not in response.text
    asyncio.run(run())


def test_chat_details_expose_personal_statistics_for_that_chat(pg_env):
    async def run():
        async with environment(pg_env) as env:
            async with env.db.transaction() as session:
                member = await session.get(ChatMember, (CHAT, USER))
                member.answered_count, member.correct_answers_count = 8, 6
                member.consecutive_correct, member.max_consecutive_correct = 2, 5
                session.add(AchievementGrant(user_id=USER, chat_id=CHAT,
                                             code=f'chat_achievement_{CHAT}_{USER}_25'))
                other = await session.get(ChatMember, (CHAT, USER + 1))
                other.score = Decimal('99.000')
                session.add(AchievementGrant(user_id=USER + 1, chat_id=CHAT,
                                             code=f'chat_achievement_{CHAT}_{USER + 1}_25',
                                             metadata_json={'secret': 'FOREIGN'}))
            headers = await login(env)
            details = (await env.client.get(f'/api/mini/chats/{CHAT}/details', headers=headers)).json()
            me = details['me']
            assert me['score'] == '12.250' and (me['answered'], me['correct']) == (8, 6)
            assert me['accuracy'] == 75.0
            assert (me['streak'], me['best_streak']) == (2, 5)
            assert me['rank'] == 2 and me['members'] >= 2      # впереди игрок с 99 очками
            assert me['achievements_earned'] == 1 and me['achievements_available'] > 0
            assert 'FOREIGN' not in str(details)
    asyncio.run(run())


def test_ingress_limits_keep_room_for_game_polling_and_login():
    """Раздельные ведра: игровой опрос, обычные запросы и вход не мешают друг другу."""
    moments = [1000.0]
    limits = RequestLimits(clock=lambda: moments[0])
    client = '127.0.0.1'
    # Игровой опрос: 600/мин на клиента, 601-й отклоняется.
    assert all(limits.allow(client, frequent_read=True) for _ in range(600))
    assert not limits.allow(client, frequent_read=True)
    # Обычные запросы — своё ведро 120/мин, игровой опрос его не расходует.
    assert all(limits.allow(client) for _ in range(120))
    assert not limits.allow(client)
    # Вход — отдельное узкое ведро 10/мин.
    assert all(limits.allow(client, auth=True) for _ in range(10))
    assert not limits.allow(client, auth=True)
    # Через минуту лимиты освобождаются.
    moments[0] += 61
    assert limits.allow(client, frequent_read=True) and limits.allow(client) and limits.allow(client, auth=True)


def test_settings_read_telegram_proxy_and_reject_invalid(monkeypatch):
    """Там, где Telegram доступен только через прокси, мини-апп обязан его знать."""
    monkeypatch.setenv('MINI_APP_BOT_TOKEN', TOKEN)
    monkeypatch.setenv('MINI_APP_ORIGIN', ORIGIN)
    monkeypatch.setenv('MINI_APP_OFFLINE', '1')      # http-origin допустим только в offline
    monkeypatch.setenv('TELEGRAM_PROXY_URL', 'socks5://127.0.0.1:9050')
    assert MiniAppSettings.from_env().telegram_proxy == 'socks5://127.0.0.1:9050'
    monkeypatch.setenv('TELEGRAM_PROXY_URL', 'ftp://proxy.local')
    with pytest.raises(ValueError):
        MiniAppSettings.from_env()
    monkeypatch.setenv('TELEGRAM_PROXY_URL', 'socks5://')
    with pytest.raises(ValueError):
        MiniAppSettings.from_env()
    monkeypatch.setenv('TELEGRAM_PROXY_URL', '  ')
    assert MiniAppSettings.from_env().telegram_proxy == ''


def test_membership_client_uses_proxy_only_when_configured(monkeypatch):
    captured = {}

    class FakeClient:
        def __init__(self, **kwargs):
            captured.clear()
            captured.update(kwargs)

    monkeypatch.setattr(mini_app_module.httpx, 'AsyncClient', FakeClient)
    TelegramMembership(TOKEN, proxy='socks5://127.0.0.1:9050')
    assert captured['proxy'] == 'socks5://127.0.0.1:9050'
    assert captured['trust_env'] is False          # окружение не подменяет настройку
    TelegramMembership(TOKEN)
    assert 'proxy' not in captured                 # без прокси аргумент не передаём
    injected = object()
    assert TelegramMembership(TOKEN, client=injected, proxy='socks5://127.0.0.1:9050').client is injected


def test_concurrent_login_replay_creates_one_session(pg_env):
    async def run():
        async with environment(pg_env) as env:
            responses = await asyncio.gather(*(env.client.post('/api/mini/session', json={'init_data': signed()}) for _ in range(2)))
            assert sorted(response.status_code for response in responses) == [200, 409]
            async with env.db.transaction() as session:
                assert await session.scalar(select(func.count()).select_from(MiniAppSession).where(MiniAppSession.user_id == USER)) == 1
    asyncio.run(run())


def test_mafia_lobby_draft_is_private_persisted_and_conflict_safe(pg_env):
    async def run():
        async with environment(pg_env) as env:
            headers = await login(env)
            assert (await env.client.get('/api/mini/mafia/draft')).status_code == 401
            initial = await env.client.get('/api/mini/mafia/draft', headers=headers)
            assert initial.json()['players'] == 6 and initial.json()['revision'] == 0
            saved = await env.client.put('/api/mini/mafia/draft', headers=headers,
                                         json={'players': 8, 'expected_revision': 0})
            assert saved.status_code == 200
            assert saved.json()['revision'] == 1
            assert {role['id'] for role in saved.json()['roles']} == {'mafia', 'citizen', 'detective', 'doctor'}
            stale = await env.client.put('/api/mini/mafia/draft', headers=headers,
                                         json={'players': 5, 'expected_revision': 0})
            assert stale.status_code == 409
            other = await login(env, USER + 1, query_id='mafia-other')
            assert (await env.client.get('/api/mini/mafia/draft', headers=other)).json()['players'] == 6
    asyncio.run(run())


def test_mafia_group_lobby_requires_membership_and_preserves_ready_revisions(pg_env):
    async def run():
        async with environment(pg_env) as env:
            first = await login(env)
            second = await login(env, USER + 1, query_id='mafia-group-second')
            missing = await env.client.get(f'/api/mini/mafia/chats/{CHAT}/lobby', headers=first)
            assert missing.status_code == 200 and missing.json() == {'lobby': None}
            joined = await env.client.post(f'/api/mini/mafia/chats/{CHAT}/lobby/join', headers=first)
            lobby = joined.json()['lobby']
            assert joined.status_code == 200 and lobby['is_host'] and lobby['joined'] and len(lobby['players']) == 1
            joined_again = await env.client.post(f'/api/mini/mafia/chats/{CHAT}/lobby/join', headers=second)
            second_lobby = joined_again.json()['lobby']
            assert len(second_lobby['players']) == 2 and not second_lobby['is_host']
            ready = await env.client.post(f'/api/mini/mafia/chats/{CHAT}/lobby/ready', headers=first,
                                          json={'ready': True, 'expected_revision': second_lobby['revision']})
            assert ready.status_code == 200 and ready.json()['lobby']['players'][0]['ready']
            stale = await env.client.post(f'/api/mini/mafia/chats/{CHAT}/lobby/ready', headers=second,
                                          json={'ready': True, 'expected_revision': second_lobby['revision']})
            assert stale.status_code == 409
            assert 'user_id' not in str(ready.json())
    asyncio.run(run())


def test_mafia_start_and_private_role_api_share_application_state(pg_env):
    async def run():
        from application.mafia import MafiaApplicationService
        async with environment(pg_env) as env:
            host = await login(env, query_id='mafia-host-start')
            second = await login(env, USER + 1, query_id='mafia-second-start')
            joined = await env.client.post(f'/api/mini/mafia/chats/{CHAT}/lobby/join', headers=host)
            assert joined.status_code == 200
            await env.client.post(f'/api/mini/mafia/chats/{CHAT}/lobby/join', headers=second)
            async with env.db.transaction() as session:
                repo = OperationalRepository(session)
                for uid in (USER + 2, USER + 3):
                    await repo.ensure_user({'id': uid, 'display_name': f'Telegram player {uid}'})
                    await repo.ensure_member({'chat_id': CHAT, 'user_id': uid})
                service = MafiaApplicationService(session)
                await service.join(chat_id=CHAT, user_id=USER + 2, name='Telegram player 3')
                await service.join(chat_id=CHAT, user_id=USER + 3, name='Telegram player 4')
            for uid in (USER, USER + 1, USER + 2, USER + 3):
                async with env.db.transaction() as session:
                    service = MafiaApplicationService(session)
                    current = await service.lobby(chat_id=CHAT, viewer_id=uid)
                    await service.ready(chat_id=CHAT, user_id=uid, ready=True,
                                        expected_revision=current['revision'])
            async with env.db.transaction() as session:
                revision = (await MafiaApplicationService(session).lobby(
                    chat_id=CHAT, viewer_id=USER))['revision']
            started = await env.client.post(f'/api/mini/mafia/chats/{CHAT}/lobby/start', headers=host,
                                             json={'expected_revision': revision})
            assert started.status_code == 200 and started.json()['lobby']['status'] == 'night'
            assert 'assignments' not in started.text and 'user_id' not in started.text
            own = await env.client.get(f'/api/mini/mafia/chats/{CHAT}/role', headers=host)
            other = await env.client.get(f'/api/mini/mafia/chats/{CHAT}/role', headers=second)
            assert own.status_code == other.status_code == 200, (own.text, other.text)
            assert own.json()['role'] in {'mafia', 'citizen'}
            assert other.json()['role'] in {'mafia', 'citizen'}
    asyncio.run(run())


def test_first_login_creates_profile_and_session_limit_preserves_scores(pg_env):
    async def run():
        async with environment(pg_env) as env:
            missing = await env.client.post('/api/mini/session', json={'init_data': signed(USER + 2)})
            assert missing.status_code == 200
            for index in range(5):
                await login(env, query_id=str(index))
            assert (await env.client.post('/api/mini/session', json={'init_data': signed(query_id='six')})).status_code == 429
            async with env.db.transaction() as session:
                newcomer = await session.get(User, USER + 2)
                assert newcomer.account_id is not None and newcomer.global_score == Decimal('0')
                assert (await session.get(User, USER)).global_score == Decimal('12.250')
    asyncio.run(run())


def test_block_unblock_invalidates_previous_sessions_permanently(pg_env):
    async def run():
        async with environment(pg_env) as env:
            headers = await login(env)
            actions = AdminActions(env.db)
            await actions.block('users', USER, blocked=True, expected_revision=0, reason='test', action_id=str(uuid4()))
            assert (await env.client.get('/api/mini/me', headers=headers)).status_code == 401
            assert (await env.client.post('/api/mini/session', json={'init_data': signed(query_id='blocked')})).status_code == 403
            await actions.block('users', USER, blocked=False, expected_revision=1, reason='test', action_id=str(uuid4()))
            assert (await env.client.get('/api/mini/me', headers=headers)).status_code == 401
            assert (await env.client.get('/api/mini/me', headers=await login(env, query_id='unblocked'))).status_code == 200
    asyncio.run(run())


def test_chat_scope_does_not_trust_init_data_chat_or_arbitrary_id(pg_env):
    async def run():
        async with environment(pg_env) as env:
            headers = await login(env, chat=json.dumps({'id': OTHER_CHAT}))
            chats = (await env.client.get('/api/mini/chats', headers=headers)).json()['items']
            assert {chat['chat_id'] for chat in chats} == {str(CHAT), str(USER)}
            assert next(chat for chat in chats if chat['chat_id'] == str(CHAT))['membership_verified'] is False
            for cid in (OTHER_CHAT, USER + 1, 0, 2**63, -999):
                for endpoint in ('leaderboard', 'games'):
                    assert (await env.client.get(f'/api/mini/chats/{cid}/{endpoint}', headers=headers)).status_code == 404
            env.verifier.allowed.assert_not_awaited()
            result = await env.client.get(f'/api/mini/chats/{CHAT}/leaderboard', headers=headers)
            assert result.status_code == 200
            assert [row['rank'] for row in result.json()['items']] == [1, 1]
            assert all('user_id' not in row for row in result.json()['items'])
            assert sum(row['is_me'] for row in result.json()['items']) == 1
    asyncio.run(run())


@pytest.mark.parametrize('membership,status', [(False, 403), (None, 503)])
def test_stale_membership_and_offline_mode_do_not_grant_group_access(pg_env, membership, status):
    async def run():
        async with environment(pg_env, membership=membership) as env:
            headers = await login(env)
            for endpoint in ('leaderboard', 'games'):
                assert (await env.client.get(f'/api/mini/chats/{CHAT}/{endpoint}', headers=headers)).status_code == status
            assert (await env.client.get(f'/api/mini/chats/{USER}/leaderboard', headers=headers)).status_code == 200
    asyncio.run(run())


def test_access_is_rechecked_after_membership_network_await(pg_env):
    async def run():
        async with environment(pg_env) as env:
            headers = await login(env)
            async def block_during_check(*args):
                await AdminActions(env.db).block('chats', CHAT, blocked=True, expected_revision=0,
                                                 reason='during check', action_id=str(uuid4()))
                return True
            env.verifier.allowed.side_effect = block_during_check
            assert (await env.client.get(f'/api/mini/chats/{CHAT}/leaderboard', headers=headers)).status_code == 404
    asyncio.run(run())


def test_games_never_expose_answers_or_other_players_photo_session(pg_env):
    async def run():
        from domain.photo import prepare_photo
        async with environment(pg_env) as env:
            await ClassicSessions(env.db).create({
                'chat_id': CHAT, 'session_id': 'privacy-classic',
                'storage_phase': 'active', 'current_question_index': 1,
                'num_questions_to_ask': 2,
                'questions': [{'correct_answer': 'SPOILER'}],
                'polls': {'correct_option_index': 0},
                'scores': {'someone': 10}, 'secret': 'PRIVATE_METADATA',
            })
            async with env.db.transaction() as session:
                photo = prepare_photo(chat_id=CHAT, creator_id=USER + 1, questions=[
                    {'display_answer': 'SPOILER', 'media': {'media_key': 'secret-one'}},
                    {'display_answer': 'PRIVATE_METADATA', 'media': {'media_key': 'secret-two'}},
                ])
                await GameRepository(session).ensure_telegram_room(CHAT)
                session.add(Game(id=str(uuid4()), chat_id=CHAT, room_id=f'telegram:{CHAT}', mode='photo', status='active',
                                 phase='question_open', revision=photo['revision'], state=photo,
                                 is_current=True, started_at=datetime.now(timezone.utc)))
            headers = await login(env)
            response = await env.client.get(f'/api/mini/chats/{CHAT}/games', headers=headers)
            assert response.json() == {'items': [{'kind': 'classic', 'phase': 'active', 'question_number': 1,
                                                 'question_count': 2, 'answer_in_chat': True}]}
            assert 'SPOILER' not in response.text and 'PRIVATE_METADATA' not in response.text
            second = await login(env, USER + 1)
            assert len((await env.client.get(f'/api/mini/chats/{CHAT}/games', headers=second)).json()['items']) == 2
    asyncio.run(run())


def test_classic_question_and_answer_are_shared_without_spoilers(pg_env):
    async def run():
        async with environment(pg_env, runtime_enabled=True) as env:
            deadline = datetime.now(timezone.utc).timestamp() + 120
            state = {
                'storage_version': 1, 'session_id': 'shared-session', 'revision': 1,
                'storage_phase': 'active', 'current_question_index': 1,
                'num_questions_to_ask': 1, 'latest_poll_id_sent': 'shared-poll',
                'active_poll_ids_in_session': ['shared-poll'],
                'polls': {'shared-poll': {
                    'display_question': 'Вопрос 1/1\nЧто выберешь?',
                    'question_text': 'Что выберешь?', 'options': ['Луна', 'Сова'],
                    'correct_option_index': 1, 'correct_option_text': 'Сова',
                    'explanation': 'Сова ведёт квиз.', 'question_session_index': 0,
                    'end_timestamp': deadline,
                }},
            }
            state['chat_id'] = CHAT
            state['session_id'] = 'shared-session'
            await ClassicSessions(env.db).create(state)
            headers = await login(env)
            path = f'/api/mini/classic/chats/{CHAT}'
            current = await env.client.get(path + '/current', headers=headers)
            assert current.status_code == 200
            assert current.json()['question'] == {
                'poll_id': 'shared-poll', 'question': 'Вопрос 1/1\nЧто выберешь?',
                'options': ['Луна', 'Сова'], 'question_number': 1,
                'ends_at': datetime.fromtimestamp(deadline, timezone.utc).isoformat(),
                'answered': False, 'selected_option': None, 'closed': False,
            }
            assert 'correct' not in current.text and 'Сова ведёт' not in current.text

            answer = await env.client.post(path + '/answer', headers=headers,
                json={'poll_id': 'shared-poll', 'selected_option': 1})
            assert answer.status_code == 200, answer.text
            assert answer.json()['applied'] is True
            assert answer.json()['question']['correct_option'] == 1
            assert answer.json()['question']['is_correct'] is True
            assert answer.json()['question']['explanation'] == 'Сова ведёт квиз.'

            duplicate = await env.client.post(path + '/answer', headers=headers,
                json={'poll_id': 'shared-poll', 'selected_option': 0})
            assert duplicate.status_code == 200
            assert duplicate.json()['applied'] is False
            assert duplicate.json()['question']['selected_option'] == 1
            async with env.db.transaction() as session:
                saved = await session.get(PollAnswer, ('shared-poll', USER))
                assert saved.selected_option == 1 and saved.is_correct is True
                assert (await session.get(ChatMember, (CHAT, USER))).score == Decimal('13.250')

            other = await login(env, USER + 1)
            hidden = await env.client.get(path + '/current', headers=other)
            assert hidden.json()['question']['answered'] is False
            assert 'correct_option' not in hidden.text and 'Сова ведёт' not in hidden.text
    asyncio.run(run())


def test_photo_projection_serves_current_image_without_answer_or_path(pg_env, tmp_path, monkeypatch):
    async def run():
        from domain.photo import prepare_photo
        root = tmp_path.resolve()
        image = root / 'owl.webp'
        image.write_bytes(b'RIFF-unit-test-WEBP')
        monkeypatch.setenv('PHOTO_IMAGES_DIR', str(root))
        async with environment(pg_env, runtime_enabled=True) as env:
            started = datetime.now(timezone.utc)
            state = prepare_photo(
                chat_id=CHAT, creator_id=USER, open_seconds=60, hints_enabled=True,
                questions=[{'display_answer': 'СЕКРЕТНЫЙ ОТВЕТ',
                            'media': {'media_key': 'owl', 'storage_name': 'owl'}}],
                now=started,
            )
            async with env.db.transaction() as session:
                await GameRepository(session).ensure_telegram_room(CHAT)
                session.add(Game(id=str(uuid4()), chat_id=CHAT, room_id=f'telegram:{CHAT}', mode='photo', status='active',
                                 phase='question_open', revision=state['revision'], state=state,
                                 is_current=True, started_at=started))
            headers = await login(env)
            path = f'/api/mini/photo/chats/{CHAT}/current'
            from application.photo import PhotoApplicationService
            async def forbid_settlement(self, **kwargs):
                raise AssertionError('GET current must not execute due-state transitions')
            monkeypatch.setattr(PhotoApplicationService, 'settle_due', forbid_settlement)
            current = await env.client.get(path, headers=headers)
            assert current.status_code == 200
            assert current.json()['question']['mask'] and 'СЕКРЕТНЫЙ' not in current.json()['question']['mask']
            image_url = current.json()['question']['image_url']
            assert image_url == path + '/image?round_id=' + state['current_round_id']
            assert 'СЕКРЕТНЫЙ' not in current.text and str(image) not in current.text
            loaded = await env.client.get(image_url, headers=headers)
            assert loaded.status_code == 200 and loaded.content == image.read_bytes()
            other = await login(env, USER + 1)
            assert (await env.client.get(path, headers=other)).status_code == 404
            assert (await env.client.get(image_url, headers=other)).status_code == 404
    asyncio.run(run())


def test_photo_image_url_changes_with_round_and_rejects_stale_round(pg_env, tmp_path, monkeypatch):
    async def run():
        from domain.photo import prepare_photo

        root = tmp_path.resolve()
        (root / 'owl.webp').write_bytes(b'RIFF-first-round-WEBP')
        (root / 'cat.webp').write_bytes(b'RIFF-second-round-WEBP')
        monkeypatch.setenv('PHOTO_IMAGES_DIR', str(root))
        async with environment(pg_env, runtime_enabled=True) as env:
            started = datetime.now(timezone.utc)
            state = prepare_photo(
                chat_id=CHAT, creator_id=USER, open_seconds=60, hints_enabled=True,
                questions=[
                    {'display_answer': 'СОВА', 'media': {'media_key': 'owl', 'storage_name': 'owl'}},
                    {'display_answer': 'КОТ', 'media': {'media_key': 'cat', 'storage_name': 'cat'}},
                ], now=started,
            )
            async with env.db.transaction() as session:
                await GameRepository(session).ensure_telegram_room(CHAT)
                session.add(Game(id=str(uuid4()), chat_id=CHAT, room_id=f'telegram:{CHAT}',
                                 mode='photo', status='active', phase='question_open',
                                 revision=state['revision'], state=state, is_current=True,
                                 started_at=started))
            headers = await login(env)
            base = f'/api/mini/photo/chats/{CHAT}'
            first = await env.client.get(base + '/current', headers=headers)
            assert first.status_code == 200, first.text
            first_question = first.json()['question']
            first_url = first_question['image_url']
            assert first_url.endswith('?round_id=' + first_question['round_id'])
            assert (await env.client.get(first_url, headers=headers)).content == (root / 'owl.webp').read_bytes()
            assert (await env.client.get(base + '/current/image', headers=headers)).status_code == 404

            answered = await env.client.post(base + '/answer', headers=headers, json={
                'command_id': str(uuid4()), 'round_id': first_question['round_id'], 'answer': 'сова',
            })
            assert answered.status_code == 200, answered.text
            second_question = answered.json()['question']
            second_url = second_question['image_url']
            assert second_question['round_id'] != first_question['round_id']
            assert second_url != first_url
            assert second_url.endswith('?round_id=' + second_question['round_id'])
            current = await env.client.get(base + '/current', headers=headers)
            assert current.json()['question']['image_url'] == second_url
            assert (await env.client.get(second_url, headers=headers)).content == (root / 'cat.webp').read_bytes()
            assert (await env.client.get(first_url, headers=headers)).status_code == 404
            other = await login(env, USER + 1)
            assert (await env.client.get(second_url, headers=other)).status_code == 404

    asyncio.run(run())


def test_photo_can_start_answer_and_stop_without_telegram_bridge(pg_env, tmp_path, monkeypatch):
    async def run():
        from storage.photos import PhotoCatalog
        from storage.models import GameCommand, GameEvent, NotificationOutbox

        root = tmp_path.resolve()
        (root / 'Сова.webp').write_bytes(b'RIFF-direct-photo-WEBP')
        monkeypatch.setenv('PHOTO_IMAGES_DIR', str(root))
        async with environment(pg_env, runtime_enabled=True) as env:
            await PhotoCatalog(env.db).get_or_create('Сова')
            base = f'/api/mini/photo/chats/{CHAT}'
            assert (await env.client.get(base + '/setup')).status_code == 401
            headers = await login(env)
            setup = await env.client.get(base + '/setup', headers=headers)
            assert setup.status_code == 200, setup.text
            assert setup.json() == {
                'question_count': 3, 'open_seconds': 60, 'hints_enabled': True,
                'available_questions': 1, 'can_start': True,
            }
            started = await env.client.post(base + '/start', headers=headers,
                json={'command_id': str(uuid4()), 'question_count': 1,
                      'open_seconds': 60, 'hints_enabled': True})
            assert started.status_code == 200, started.text
            question = started.json()['question']
            synced = await env.client.post(base + '/sync', headers=headers, json={})
            assert synced.status_code == 200 and synced.json()['question']['round_id'] == question['round_id']
            current = await env.client.get(base + '/current', headers=headers)
            assert current.status_code == 200 and current.json()['question']['round_id'] == question['round_id']
            assert (await env.client.get(question['image_url'], headers=headers)).content == (root / 'Сова.webp').read_bytes()
            wrong_id = str(uuid4())
            wrong = await env.client.post(base + '/answer', headers=headers,
                json={'command_id': wrong_id, 'round_id': question['round_id'], 'answer': 'ворона'})
            assert wrong.status_code == 200 and wrong.json()['verdict'] == 'wrong'
            duplicate = await env.client.post(base + '/answer', headers=headers,
                json={'command_id': wrong_id, 'round_id': question['round_id'], 'answer': 'ворона'})
            assert duplicate.json() == wrong.json()
            final_payload = {'command_id': str(uuid4()), 'round_id': question['round_id'], 'answer': 'сова'}
            won = await env.client.post(base + '/answer', headers=headers, json=final_payload)
            assert won.status_code == 200 and won.json()['status'] == 'finished'
            game_id = won.json()['game_id']

            async def snapshot():
                async with env.db.transaction() as session:
                    game = await session.get(Game, game_id)
                    return (
                        game.revision, json.loads(json.dumps(game.state)),
                        (await session.get(User, USER)).global_score,
                        (await session.get(ChatMember, (CHAT, USER))).score,
                        await session.scalar(select(func.count()).select_from(PollAnswer).where(
                            PollAnswer.game_id == game_id)),
                        await session.scalar(select(func.count()).select_from(GameEvent).where(
                            GameEvent.game_id == game_id)),
                        await session.scalar(select(func.count()).select_from(NotificationOutbox).where(
                            NotificationOutbox.game_id == game_id)),
                        await session.scalar(select(func.count()).select_from(GameCommand).where(
                            GameCommand.game_id == game_id)),
                    )

            finished_snapshot = await snapshot()
            replay = await env.client.post(base + '/answer', headers=headers, json=final_payload)
            assert replay.status_code == 200 and replay.json() == won.json()
            assert await snapshot() == finished_snapshot

            changed = await env.client.post(base + '/answer', headers=headers,
                json={**final_payload, 'answer': 'ворона'})
            assert changed.status_code == 409
            fresh_id = str(uuid4())
            fresh = await env.client.post(base + '/answer', headers=headers,
                json={**final_payload, 'command_id': fresh_id})
            assert fresh.status_code == 404
            assert await snapshot() == finished_snapshot
            async with env.db.transaction() as session:
                assert await session.get(GameCommand, fresh_id) is None

            restarted = await env.client.post(base + '/start', headers=headers,
                json={'command_id': str(uuid4()), 'question_count': 1,
                      'open_seconds': 60, 'hints_enabled': False})
            assert restarted.status_code == 200, restarted.text
            reused = await env.client.post(base + '/answer', headers=headers, json=final_payload)
            assert reused.status_code == 409
            stopped = await env.client.post(base + '/stop', headers=headers,
                json={'command_id': str(uuid4()),
                      'expected_revision': restarted.json()['revision']})
            assert stopped.status_code == 200 and stopped.json()['status'] == 'stopped'
            async with env.db.transaction() as session:
                assert await session.scalar(select(func.count()).select_from(QuizSession).where(
                    QuizSession.kind == 'photo')) == 0
    asyncio.run(run())


def test_private_classic_settings_use_shared_revisioned_service(pg_env):
    async def run():
        async with environment(pg_env, runtime_enabled=True) as env:
            headers = await login(env)
            details = (await env.client.get(f'/api/mini/chats/{USER}/details', headers=headers)).json()
            assert details['can_edit'] is True
            payload = {'questions': 7, 'seconds': 45, 'interval': 12, 'announce': True,
                       'announce_delay': 4, 'expected_revision': details['settings_revision']}
            saved = await env.client.put(f'/api/mini/chats/{USER}/classic-settings',
                headers=headers, json=payload)
            assert saved.status_code == 200, saved.text
            assert saved.json()['classic'] == {key: payload[key] for key in
                ('questions', 'seconds', 'interval', 'announce', 'announce_delay')}
            current = await SettingsService(env.db).get(USER)
            assert current.values['quiz']['num_questions'] == current.values['default_num_questions'] == 7
            stale = await env.client.put(f'/api/mini/chats/{USER}/classic-settings',
                headers=headers, json={**payload, 'questions': 8})
            assert stale.status_code == 409
            group = await env.client.put(f'/api/mini/chats/{CHAT}/classic-settings',
                headers=headers, json={**payload, 'expected_revision': 0})
            assert group.status_code == 403
    asyncio.run(run())


def test_native_preferences_save_categories_and_schedules_without_bot_bridge(pg_env):
    async def run():
        async with environment(pg_env, runtime_enabled=True) as env:
            headers = await login(env)
            categories = (await env.client.get('/api/mini/categories', headers=headers)).json()['items']
            assert categories == ['Тестовая категория']
            details = (await env.client.get(f'/api/mini/chats/{USER}/details', headers=headers)).json()
            payload = {
                'classic': {'questions': 8, 'seconds': 50, 'interval': 15, 'announce': True,
                            'announce_delay': 3, 'category_mode': 'specific',
                            'categories': [categories[0]], 'random_categories': 2},
                'daily': {'enabled': True, 'times': ['08:15', '19:30'], 'timezone': 'Europe/Istanbul',
                          'questions': 12, 'interval': 60, 'seconds': 300,
                          'category_mode': 'random', 'categories': [], 'random_categories': 4},
                'wisdom': {'enabled': True, 'time': '09:20'},
                'auto_delete': False,
                'expected_revision': details['settings_revision'],
            }
            saved = await env.client.put(f'/api/mini/chats/{USER}/preferences', headers=headers, json=payload)
            assert saved.status_code == 200, saved.text
            settings = (await SettingsService(env.db).get(USER)).values
            assert settings['quiz']['specific_categories'] == [categories[0]]
            assert settings['daily_quiz']['times_msk'] == [
                {'hour': 8, 'minute': 15}, {'hour': 19, 'minute': 30}]
            assert settings['daily_quiz']['timezone'] == 'Europe/Istanbul'
            assert settings['daily_wisdom'] == {'enabled': True, 'time': '09:20'}
            assert settings['auto_delete_bot_messages'] is False
            invalid = {**payload, 'classic': {**payload['classic'], 'categories': ['not-a-category']}}
            assert (await env.client.put(f'/api/mini/chats/{USER}/preferences', headers=headers,
                                         json=invalid)).status_code == 400
            group = await env.client.put(f'/api/mini/chats/{CHAT}/preferences', headers=headers,
                                         json={**payload, 'expected_revision': 0})
            assert group.status_code == 403
            env.verifier.status = AsyncMock(return_value={'status': 'administrator'})
            group_details = (await env.client.get(f'/api/mini/chats/{CHAT}/details', headers=headers)).json()
            assert group_details['can_edit'] is True
            saved_group = await env.client.put(f'/api/mini/chats/{CHAT}/preferences', headers=headers,
                                               json={**payload, 'expected_revision': group_details['settings_revision']})
            assert saved_group.status_code == 200, saved_group.text
            group_settings = (await SettingsService(env.db).get(CHAT)).values
            assert group_settings['quiz']['num_questions'] == 8
    asyncio.run(run())


def test_mafia_full_cycle_uses_private_actions_and_public_results(pg_env, monkeypatch):
    async def run():
        monkeypatch.setattr('domain.mafia.secrets.SystemRandom.shuffle', lambda self, values: None)
        extra_ids = [USER + 2, USER + 3]
        async with environment(pg_env, runtime_enabled=True) as env:
            async with env.db.transaction() as session:
                await session.execute(delete(User).where(User.id.in_(extra_ids)))
                repo = OperationalRepository(session)
                for uid in extra_ids:
                    await repo.ensure_user({'id': uid, 'display_name': f'Player {uid}'})
                    await repo.ensure_member({'chat_id': CHAT, 'user_id': uid})
            users = [USER, USER + 1, *extra_ids]
            headers = {uid: await login(env, uid, query_id=f'mafia-{uid}') for uid in users}
            base = f'/api/mini/mafia/chats/{CHAT}'
            for uid in users:
                assert (await env.client.post(base + '/lobby/join', headers=headers[uid])).status_code == 200
            for uid in users:
                lobby = (await env.client.get(base + '/lobby', headers=headers[uid])).json()['lobby']
                ready = await env.client.post(base + '/lobby/ready', headers=headers[uid],
                    json={'ready': True, 'expected_revision': lobby['revision']})
                assert ready.status_code == 200
            lobby = (await env.client.get(base + '/lobby', headers=headers[USER])).json()['lobby']
            assert (await env.client.post(base + '/lobby/start', headers=headers[USER],
                json={'expected_revision': lobby['revision']})).status_code == 200
            roles = {uid: (await env.client.get(base + '/role', headers=headers[uid])).json() for uid in users}
            mafia = next(uid for uid, role in roles.items() if role['role'] == 'mafia')
            candidates = [uid for uid in users if uid != mafia and uid != USER]
            victim = candidates[0] if candidates else next(uid for uid in users if uid != mafia)
            lobby = (await env.client.get(base + '/lobby', headers=headers[mafia])).json()['lobby']
            action = await env.client.post(base + '/action', headers=headers[mafia],
                json={'target': roles[victim]['seat'], 'expected_revision': lobby['phase_revision']})
            assert action.status_code == 200
            lobby = (await env.client.get(base + '/lobby', headers=headers[USER])).json()['lobby']
            assert lobby['can_advance'] is True and 'role' not in str(lobby)
            night = await env.client.post(base + '/advance', headers=headers[USER],
                json={'expected_revision': lobby['revision']})
            assert night.status_code == 200 and night.json()['lobby']['status'] == 'day'
            lobby = night.json()['lobby']
            opened = await env.client.post(base + '/advance', headers=headers[USER],
                json={'expected_revision': lobby['revision']})
            assert opened.status_code == 200 and opened.json()['lobby']['status'] == 'voting'
            living = [uid for uid in users if uid != victim]
            revision = opened.json()['lobby']['revision']
            phase_revision = opened.json()['lobby']['phase_revision']
            for uid in living:
                target = roles[mafia]['seat'] if uid != mafia else roles[next(x for x in living if x != mafia)]['seat']
                result = await env.client.post(base + '/vote', headers=headers[uid],
                    json={'target': target, 'expected_revision': phase_revision})
                assert result.status_code == 200, result.text
                revision = result.json()['lobby']['revision']
            finished = await env.client.post(base + '/advance', headers=headers[USER],
                json={'expected_revision': revision})
            assert finished.status_code == 200
            assert finished.json()['lobby']['status'] == 'finished'
            assert finished.json()['lobby']['winner'] == 'citizens'
            assert 'assignments' not in finished.text and 'user_id' not in finished.text
            replay = await env.client.post(base + '/restart', headers=headers[USER],
                json={'expected_revision': finished.json()['lobby']['revision']})
            assert replay.status_code == 200
            assert replay.json()['status'] == 'lobby'
            assert all(not player['ready'] for player in replay.json()['players'])
            async with env.db.transaction() as session:
                history = (await session.scalars(select(Game).where(
                    Game.chat_id == CHAT, Game.mode == 'mafia'
                ).order_by(Game.created_at))).all()
                assert len(history) == 2
                assert sum(game.is_current for game in history) == 1
                assert next(game for game in history if not game.is_current).status == 'finished'
                assert next(game for game in history if game.is_current).status == 'lobby'
                await session.execute(delete(Game).where(Game.chat_id == CHAT))
                await session.execute(delete(User).where(User.id.in_(extra_ids)))
    asyncio.run(run())


@pytest.mark.parametrize('path', ['/api/users', '/api/chats', '/api/bank/categories', '/api/system/status',
    '/api/mini/users/1', '/static/js/postgres-admin.js', '/docs', '/openapi.json', '/login'])
def test_admin_and_unscoped_routes_are_absent(pg_env, path):
    async def run():
        async with environment(pg_env) as env:
            assert (await env.client.get(path, headers=await login(env))).status_code == 404
    asyncio.run(run())


def test_shell_assets_are_served_to_every_game_page(pg_env):
    async def run():
        async with environment(pg_env) as env:
            for name, kind in (('qw-shell.js', 'javascript'), ('qw-tokens.css', 'text/css'), ('qw-shell.css', 'text/css'),
                               ('vendor/telegram-web-app.js', 'javascript')):
                response = await env.client.get('/app/shell/' + name)
                assert response.status_code == 200 and kind in response.headers['content-type']
                assert 'max-age' in response.headers['cache-control']
            assert (await env.client.get('/app/shell/app.js')).status_code == 404
            assert (await env.client.get('/app/shell/vendor/app.js')).status_code == 404
            assert (await env.client.get('/app/shell/..%2Fmini_app.py')).status_code == 404
    asyncio.run(run())


def test_alchemia_atlas_is_served_as_self_contained_mini_app_page(pg_env):
    async def run():
        async with environment(pg_env) as env:
            page = await env.client.get('/app/alchemy')
            assert page.status_code == 200
            assert page.headers['content-type'].startswith('text/html')
            html = page.text
            assert 'атлас маленьких чудес' in html and 'alchemia.atlas.v1' in html
            # Ресурсы автономны (Telegram SDK грузит оболочка со своего origin); сеть — только наш API.
            assert 'src="http' not in html and 'href="http' not in html and 'telegram-web-app.js' not in html
            # Общая оболочка QuizzyWizzy (docs/design/UI_RULES.md) подключается с того же origin.
            assert '/app/shell/qw-shell.js' in html and '/app/shell/qw-tokens.css' in html
            # sync.js builds endpoints from one per-identity base.
            assert "'/api/mini/alchemy/'" in html and "'/api/guest/alchemy/'" in html
            assert "API + 'sync'" in html and "API + 'craft'" in html
            assert '#t=' not in html and 'mqb-mini-token' not in html
            assert 'Authorization: `Bearer' not in html
            # Инлайн-стили и скрипты обязаны быть разрешены: со строгой политикой
            # мини-аппа страница открывается без оформления и без игры.
            csp = page.headers['content-security-policy']
            assert "script-src 'self' 'unsafe-inline' https://telegram.org;" in csp
            assert "style-src 'self' 'unsafe-inline';" in csp
            assert "connect-src 'self'" in csp and "connect-src 'none'" not in csp
            # API и остальные маршруты остаются под строгой политикой.
            assert (await env.client.get('/api/mini/config')).headers['content-security-policy'] == \
                "default-src 'none'; frame-ancestors 'none'"
            # Новый маршрут объявлен раньше обработчика ассетов и не перехватывается им.
            assert (await env.client.get('/app/alchemy.html')).status_code == 404
    asyncio.run(run())


def test_alchemy_sync_imports_without_reward_and_craft_is_server_authoritative(pg_env):
    async def run():
        async with environment(pg_env) as env:
            headers = await login(env)
            headers['X-Mini-User'] = str(USER)
            imported = await env.client.post(
                '/api/mini/alchemy/sync', headers=headers,
                json={'discovered': ['water', 'earth', 'fire', 'air', 'steam'],
                      'crafted': ['air+water'], 'attempts': 100_000},
            )
            assert imported.status_code == 200, imported.text
            assert imported.json()['awarded'] == 0
            assert imported.json()['reward_eligible'] is False
            assert imported.json()['discovered'] == ['air', 'earth', 'fire', 'steam', 'water']
            assert imported.json()['verified_discovered'] == ['air', 'earth', 'fire', 'water']
            async with env.db.transaction() as session:
                assert (await session.get(User, USER)).global_score == Decimal('12.250')

            payload = {'command_id': f'http-craft-{uuid4().hex}',
                       'ingredient_a': 'water', 'ingredient_b': 'fire'}
            crafted = await env.client.post(
                '/api/mini/alchemy/craft', headers=headers, json=payload)
            assert crafted.status_code == 200, crafted.text
            assert crafted.json()['verified'] is True
            assert crafted.json()['result'] == 'steam'
            replay = await env.client.post(
                '/api/mini/alchemy/craft', headers=headers, json=payload)
            assert replay.status_code == 200 and replay.json() == crafted.json()
            conflicting_replay = await env.client.post(
                '/api/mini/alchemy/craft', headers=headers,
                json={**payload, 'ingredient_a': 'earth'},
            )
            assert conflicting_replay.status_code == 409
            async with env.db.transaction() as session:
                user = await session.get(User, USER)
                row = await session.scalar(select(AlchemyProgress).where(
                    AlchemyProgress.user_id == USER))
                assert user.global_score == Decimal('12.250'), 'Alchemy points are a separate journal slice'
                from storage.models import ScoreTotal
                assert await session.scalar(select(ScoreTotal.total).where(
                    ScoreTotal.account_id == user.account_id, ScoreTotal.source == 'alchemy')) == Decimal(str(crafted.json()['awarded']))
                assert 'steam' in row.verified_discovered
    asyncio.run(run())


def test_cookies_query_tokens_and_unsafe_origins_cannot_authorize(pg_env):
    async def run():
        async with environment(pg_env) as env:
            headers = await login(env)
            raw = headers['Authorization'][7:]
            assert (await env.client.get('/api/mini/me?token=' + raw)).status_code == 401
            assert (await env.client.get('/api/mini/me', headers={'Cookie': 'mqb_admin_session=' + raw})).status_code == 401
            assert (await env.client.get('/api/mini/me', headers={**headers, 'Origin': 'https://evil.example'})).status_code == 403
            assert (await env.client.get('/api/mini/me', headers={**headers, 'Host': 'evil.example'})).status_code == 400
            assert (await env.client.get('/api/mini/me', headers={**headers, 'Sec-Fetch-Site': 'cross-site'})).status_code == 403
            assert (await env.client.options('/api/mini/me', headers={'Origin': 'https://evil.example'})).headers.get('access-control-allow-origin') is None
            assert (await env.client.post('/api/mini/chats/' + str(CHAT) + '/answer', headers=headers, json={'score': 99})).status_code == 404
            assert (await env.client.get('/api/mini/chats?limit=99999', headers=headers)).status_code == 422
    asyncio.run(run())


def test_login_body_limits_and_duplicate_json_keys(pg_env):
    async def run():
        async with environment(pg_env) as env:
            assert (await env.client.post('/api/mini/session', content='x', headers={'content-type': 'text/plain'})).status_code == 415
            assert (await env.client.post('/api/mini/session', content='x'*20001, headers={'content-type': 'application/json'})).status_code == 413
            for body in ('{"init_data":"x","init_data":"y"}', '{bad json}', '[]'):
                assert (await env.client.post('/api/mini/session', content=body, headers={'content-type': 'application/json'})).status_code == 401
            assert (await env.client.post('/api/mini/session', json={'init_data': signed(), 'user_id': USER + 1})).status_code == 401
    asyncio.run(run())


def test_rate_limits_are_bounded_and_expire():
    now = [0]
    limiter = RequestLimits(clock=lambda: now[0])
    assert all(limiter.allow('one', auth=True) for _ in range(10))
    assert not limiter.allow('one', auth=True)
    now[0] = 61
    assert limiter.allow('one', auth=True)
    for index in range(700):
        limiter.allow(str(index))
    assert len(limiter.clients) <= 600 and len(limiter.global_requests) == 600


@pytest.mark.parametrize('status,extra,expected', [('member', {}, True), ('left', {}, False),
    ('kicked', {}, False), ('administrator', {}, True), ('restricted', {'is_member': True}, True),
    ('restricted', {'is_member': False}, False)])
def test_membership_verifier_uses_fresh_admin_and_user_checks(status, extra, expected):
    async def run():
        calls = []
        def handler(request):
            data = json.loads(request.content)
            calls.append(data)
            uid = data['user_id']
            return httpx.Response(200, json={'ok': True, 'result': {'user': {'id': uid},
                'status': 'administrator' if uid == 123456 else status, **extra}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            verifier = TelegramMembership(TOKEN, client=client)
            assert await verifier.allowed(CHAT, USER) is expected
            assert [call['user_id'] for call in calls] == [123456, USER]
    asyncio.run(run())


@pytest.mark.parametrize('status,extra,expected', [
    ('creator', {}, True), ('administrator', {}, True), ('member', {}, False),
    ('restricted', {'is_member': True}, False), ('left', {}, False),
])
def test_membership_verifier_distinguishes_chat_admins(status, extra, expected):
    async def run():
        def handler(request):
            uid = json.loads(request.content)['user_id']
            role = 'administrator' if uid == 123456 else status
            result = {'user': {'id': uid}, 'status': role, **(extra if uid != 123456 else {})}
            return httpx.Response(200, json={'ok': True, 'result': result})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            verifier = TelegramMembership(TOKEN, client=client)
            assert await verifier.allowed(CHAT, USER, administrators_only=True) is expected
    asyncio.run(run())


# Бот-не-админ теперь даёт 409 (см. test_bot_status_in_chat_decides_between_gone_and_missing_rights).
@pytest.mark.parametrize('response', [httpx.Response(429), httpx.Response(500),
    httpx.Response(200, json={'ok': False}), httpx.Response(200, text='broken')])
def test_membership_failure_is_closed_without_leaking_bot_token(response):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: response)) as client:
            with pytest.raises(MiniAppError) as error:
                await TelegramMembership(TOKEN, client=client).allowed(CHAT, USER)
            assert error.value.status == 503 and TOKEN not in str(error.value)
    asyncio.run(run())


def test_database_failure_does_not_expose_sql_or_credentials():
    from sqlalchemy.exc import OperationalError
    async def run():
        app = create_app(database=SimpleNamespace(), settings=MiniAppSettings(TOKEN, ORIGIN, True))
        app.state.mini_store.profile = AsyncMock(side_effect=OperationalError('SECRET_SQL', {}, Exception('PASSWORD')))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
            response = await client.get('/api/mini/me', headers={'Authorization': 'Bearer ' + 'x' * 43})
            assert response.status_code == 503
            assert 'SECRET_SQL' not in response.text and 'PASSWORD' not in response.text
    asyncio.run(run())


def test_mini_bearer_is_not_an_admin_session():
    from fastapi import FastAPI
    from web.admin_auth import AdminAuth, install_admin_auth
    async def run():
        app = FastAPI()
        install_admin_auth(app, auth=AdminAuth(access_token='admin-only-test-key-' + 'x' * 32))
        @app.get('/api/users')
        async def users():
            return {'should_not_be_visible': True}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://127.0.0.1:4184') as client:
            response = await client.get('/api/users', headers={'Authorization': 'Bearer ' + 'x' * 43})
            assert response.status_code == 401
    asyncio.run(run())


# --- Устаревшие Telegram-чаты: постоянные ответы против временных -----------------------

def _telegram_gone(status, description, **parameters):
    body = {'ok': False, 'error_code': status, 'description': description}
    if parameters:
        body['parameters'] = parameters
    return httpx.Response(status, json=body)


@pytest.mark.parametrize('response,reason,migrate_to', [
    (_telegram_gone(400, 'Bad Request: chat not found'), 'gone', None),
    (_telegram_gone(403, 'Forbidden: bot was kicked from the supergroup chat'), 'gone', None),
    (_telegram_gone(403, 'Forbidden: bot is not a member of the channel chat'), 'gone', None),
    (_telegram_gone(400, 'Bad Request: group chat was upgraded to a supergroup chat',
                    migrate_to_chat_id=-1002345678901), 'migrated', -1002345678901),
])
def test_permanent_telegram_answers_are_chat_unavailable_not_503(response, reason, migrate_to):
    from web.mini_app import ChatUnavailable
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: response)) as client:
            with pytest.raises(ChatUnavailable) as error:
                await TelegramMembership(TOKEN, client=client).allowed(CHAT, USER)
            assert (error.value.status, error.value.reason, error.value.migrate_to) == (410, reason, migrate_to)
            assert error.value.deactivate is True and TOKEN not in str(error.value)
    asyncio.run(run())


@pytest.mark.parametrize('response', [
    httpx.Response(429, json={'ok': False, 'error_code': 429, 'description': 'Too Many Requests: retry after 5',
                              'parameters': {'retry_after': 5}}),
    httpx.Response(500, json={'ok': False, 'description': 'Internal Server Error'}),
    httpx.Response(502, text='<html>bad gateway</html>'),
    httpx.Response(401, json={'ok': False, 'description': 'Unauthorized'}),
    _telegram_gone(400, 'Bad Request: user not found'),
])
def test_transient_telegram_answers_stay_503_and_never_retire_a_chat(response):
    from web.mini_app import ChatUnavailable
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: response)) as client:
            with pytest.raises(MiniAppError) as error:
                await TelegramMembership(TOKEN, client=client).allowed(CHAT, USER)
            assert not isinstance(error.value, ChatUnavailable) and error.value.status == 503
    asyncio.run(run())


def test_network_failure_and_timeout_are_transient():
    async def run():
        def broken(_):
            raise httpx.ConnectTimeout('timeout')
        async with httpx.AsyncClient(transport=httpx.MockTransport(broken)) as client:
            with pytest.raises(MiniAppError) as error:
                await TelegramMembership(TOKEN, client=client).allowed(CHAT, USER)
            assert error.value.status == 503
    asyncio.run(run())


@pytest.mark.parametrize('bot_status,expected,deactivate', [('left', 410, True), ('kicked', 410, True),
                                                            ('member', 409, False)])
def test_bot_status_in_chat_decides_between_gone_and_missing_rights(bot_status, expected, deactivate):
    from web.mini_app import ChatUnavailable
    async def run():
        def handler(request):
            uid = json.loads(request.content)['user_id']
            return httpx.Response(200, json={'ok': True, 'result': {'user': {'id': uid}, 'status': bot_status}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(ChatUnavailable) as error:
                await TelegramMembership(TOKEN, client=client).allowed(CHAT, USER)
            assert (error.value.status, error.value.deactivate) == (expected, deactivate)
    asyncio.run(run())


def _reactivate(chat_id):
    from sqlalchemy import update
    return update(Chat).where(Chat.id == chat_id).values(is_active=True)


def test_permanent_error_retires_chat_and_hides_it_while_transient_does_not(pg_env):
    from web.mini_app import ChatUnavailable
    async def run():
        async with environment(pg_env) as env:
            headers = await login(env)
            try:
                env.verifier.allowed.side_effect = MiniAppError(503, 'Не удалось подтвердить членство в Telegram')
                assert (await env.client.get(f'/api/mini/chats/{CHAT}/games', headers=headers)).status_code == 503
                listed = (await env.client.get('/api/mini/chats', headers=headers)).json()['items']
                assert str(CHAT) in {item['chat_id'] for item in listed}
                async with env.db.transaction() as session:
                    assert (await session.get(Chat, CHAT)).is_active is True

                env.verifier.allowed.side_effect = ChatUnavailable('gone')
                gone = await env.client.get(f'/api/mini/chats/{CHAT}/games', headers=headers)
                assert gone.status_code == 410 and gone.json()['code'] == 'chat_unavailable'
                async with env.db.transaction() as session:
                    assert (await session.get(Chat, CHAT)).is_active is False
                listed = (await env.client.get('/api/mini/chats', headers=headers)).json()['items']
                assert str(CHAT) not in {item['chat_id'] for item in listed}
                # Telegram больше не дёргаем: чат уже скрыт.
                env.verifier.allowed.reset_mock()
                assert (await env.client.get(f'/api/mini/chats/{CHAT}/games', headers=headers)).status_code == 404
                env.verifier.allowed.assert_not_called()
            finally:
                async with env.db.transaction() as session:
                    await session.execute(_reactivate(CHAT))
    asyncio.run(run())


def test_migrated_chat_moves_settings_and_members_to_the_new_id(pg_env):
    from web.mini_app import ChatUnavailable
    new_id = -1009876543210
    async def run():
        async with environment(pg_env) as env:
            headers = await login(env)
            try:
                env.verifier.allowed.side_effect = ChatUnavailable('migrated', migrate_to=new_id)
                assert (await env.client.get(f'/api/mini/chats/{CHAT}/games', headers=headers)).status_code == 410
                async with env.db.transaction() as session:
                    assert (await session.get(Chat, CHAT)).is_active is False
                    moved = await session.get(Chat, new_id)
                    assert moved is not None and moved.is_active and moved.type == 'supergroup'
                    members = set((await session.scalars(select(ChatMember.user_id).where(
                        ChatMember.chat_id == new_id))).all())
                    assert members == {USER, USER + 1}
                from storage.chat_availability import migrate_chat
                assert await migrate_chat(env.db, CHAT, new_id) is True      # повтор безопасен
                listed = (await env.client.get('/api/mini/chats', headers=headers)).json()['items']
                assert str(new_id) in {item['chat_id'] for item in listed}
            finally:
                async with env.db.transaction() as session:
                    await session.execute(delete(Chat).where(Chat.id == new_id))
                    await session.execute(_reactivate(CHAT))
    asyncio.run(run())


def test_bot_membership_updates_toggle_chat_availability(pg_env):
    from handlers.chat_availability_handlers import ChatAvailabilityHandlers
    from telegram.constants import ChatMemberStatus
    async def run():
        async with environment(pg_env) as env:
            handlers = ChatAvailabilityHandlers(env.db)
            def event(status, kind='supergroup'):
                return SimpleNamespace(my_chat_member=SimpleNamespace(
                    chat=SimpleNamespace(id=CHAT, type=kind), new_chat_member=SimpleNamespace(status=status)))
            async def active():
                async with env.db.transaction() as session:
                    return (await session.get(Chat, CHAT)).is_active
            await handlers.my_chat_member(event(ChatMemberStatus.BANNED), None)
            assert await active() is False
            await handlers.my_chat_member(event(ChatMemberStatus.RESTRICTED), None)
            assert await active() is False
            await handlers.my_chat_member(event(ChatMemberStatus.ADMINISTRATOR), None)
            assert await active() is True
            await handlers.my_chat_member(event(ChatMemberStatus.LEFT, 'private'), None)
            assert await active() is True
    asyncio.run(run())


# --- Статика не лимитируется, API — по-прежнему --------------------------------------------

def test_static_assets_are_exempt_from_rate_limits_but_api_is_not():
    async def run():
        app = create_app(database=SimpleNamespace(), settings=MiniAppSettings(TOKEN, ORIGIN, offline=True))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
            paths = ['/app', '/app/app.js', '/app/styles.css', '/app/host-card.webp', '/app/photo.webp',
                     '/app/mafia-card.webp', '/app/farm-card-v2.webp']
            for number in range(700):          # больше глобального лимита 600/мин
                response = await client.get(paths[number % len(paths)])
                assert response.status_code == 200, (number, response.status_code)
            assert (await client.get('/app/app.js')).status_code == 200
            codes = [(await client.get('/api/mini/me')).status_code for _ in range(130)]
            assert codes[:120] == [401] * 120 and set(codes[120:]) == {429}
            # Неизвестные файлы статикой не считаются.
            assert (await client.get('/app/secret.txt')).status_code == 429
    asyncio.run(run())


def test_static_assets_have_cache_headers_and_answer_conditional_requests():
    async def run():
        app = create_app(database=SimpleNamespace(), settings=MiniAppSettings(TOKEN, ORIGIN, offline=True))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
            script = await client.get('/app/app.js')
            assert script.headers['cache-control'].startswith('public, max-age=')
            assert 'immutable' not in script.headers['cache-control']      # имена без версии
            assert 'pragma' not in script.headers and script.headers['etag']
            assert (await client.get('/app/host-card.webp')).headers['cache-control'] == 'public, max-age=3600'
            assert (await client.get('/app')).headers['cache-control'] == 'public, max-age=60, must-revalidate'
            again = await client.get('/app/app.js', headers={'If-None-Match': script.headers['etag']})
            assert again.status_code == 304 and again.content == b''
            assert again.headers['cache-control'] == script.headers['cache-control']
            assert "script-src 'self'" in again.headers['content-security-policy']
            changed = await client.get('/app/app.js', headers={'If-None-Match': '"other"'})
            assert changed.status_code == 200 and changed.content
            assert (await client.get('/api/mini/config')).headers['cache-control'] == 'no-store'
    asyncio.run(run())
