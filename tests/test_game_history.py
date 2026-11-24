import asyncio
from time import time
from uuid import UUID, uuid4

import httpx
from application.game_deadlines import GameDeadlineProcessor
from storage.models import QuestionCategory, RoomMembership
from tests.local_database import isolated_database
from tests.test_postgres_members import pg_env
from tests.test_room_photo import catalog, photo_media
from web.mini_app import MiniAppSettings, create_app


def test_guest_account_game_history_includes_browser_classic_game(pg_env):
    async def run():
        async with isolated_database(pg_env) as (database, _):
            settings = MiniAppSettings('', 'http://127.0.0.1:4185', offline=True)
            app = create_app(database=database, settings=settings, room_classic_enabled=True)
            headers = {'Origin': settings.origin, 'X-Guest-CSRF': '1', 'Idempotency-Key': str(uuid4())}
            async with database.transaction() as session:
                session.add(QuestionCategory(
                    name='История Classic', content_hash='0' * 64,
                    questions=[{'question': 'Один плюс один?', 'options': ['Два', 'Три'], 'correct_option_text': 'Два'}],
                ))
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=settings.origin) as client:
                await client.post('/api/guest/start', headers=headers)
                room_id = (await client.post(
                    '/api/guest/rooms', headers=headers,
                    json={'request_id': str(uuid4()), 'title': 'История'},
                )).json()['id']
                base = f'/api/guest/rooms/{room_id}/classic'
                started = await client.post(
                    base + '/start', headers=headers,
                    json={'count': 1, 'open_seconds': 30, 'interval_seconds': 0},
                )
                assert started.status_code == 200, started.text
                game = started.json()
                stopped = await client.post(
                    base + '/stop', headers={**headers, 'Idempotency-Key': str(uuid4())},
                    json={'game_id': game['game_id'], 'expected_revision': game['revision']},
                )
                assert stopped.status_code == 200, stopped.text

                history = await client.get('/api/account/game-history')
                assert history.status_code == 200, history.text
                item = history.json()['games'][0]
                assert item['game_id'] == game['game_id'] and item['room_id'] == room_id
                assert item['room_title'] == 'История' and item['mode'] == 'classic'
                assert item['status'] == 'stopped' and item['phase'] == 'finished'
                assert item['is_current'] is True and item['questions'] == 1
                assert item['my_answers'] == item['my_correct'] == 0 and item['my_score'] == '0.0'
                assert item['started_at'] and item['ended_at']

    asyncio.run(run())


def test_guest_account_game_history_includes_browser_photo_game(pg_env, photo_media):
    async def run():
        async with isolated_database(pg_env) as (database, _):
            await catalog(database, photo_media)
            settings = MiniAppSettings('', 'http://127.0.0.1:4185', offline=True)
            app = create_app(database=database, settings=settings, room_photo_enabled=True)
            headers = {'Origin': settings.origin, 'X-Guest-CSRF': '1', 'Idempotency-Key': str(uuid4())}
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=settings.origin) as client:
                await client.post('/api/guest/start', headers=headers)
                room_id = (await client.post(
                    '/api/guest/rooms', headers=headers,
                    json={'request_id': str(uuid4()), 'title': 'Фото история'},
                )).json()['id']
                base = f'/api/guest/rooms/{room_id}/photo'
                started = await client.post(
                    base + '/start', headers=headers,
                    json={'question_count': 1, 'open_seconds': 60, 'hints_enabled': True},
                )
                assert started.status_code == 200, started.text
                game = started.json()
                stopped = await client.post(
                    base + '/stop', headers={**headers, 'Idempotency-Key': str(uuid4())},
                    json={'game_id': game['game_id'], 'expected_revision': game['revision']},
                )
                assert stopped.status_code == 200, stopped.text

                history = await client.get('/api/account/game-history')
                assert history.status_code == 200, history.text
                item = history.json()['games'][0]
                assert item['game_id'] == game['game_id'] and item['room_id'] == room_id
                assert item['room_title'] == 'Фото история' and item['mode'] == 'photo'
                assert item['status'] == 'stopped' and item['questions'] == 1
                assert item['my_answers'] == 0 and item['my_correct'] == 0 and item['my_score'] == '0.0'

    asyncio.run(run())


def test_group_photo_history_is_private_per_account_and_excludes_outsider(pg_env, photo_media):
    async def run():
        async with isolated_database(pg_env) as (database, _):
            await catalog(database, photo_media)
            settings = MiniAppSettings('', 'http://127.0.0.1:4185', offline=True)
            now = [int(time())]
            app = create_app(database=database, settings=settings, room_photo_enabled=True, clock=lambda: now[0])
            headers = {'Origin': settings.origin, 'X-Guest-CSRF': '1'}
            async with (
                httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=settings.origin) as owner,
                httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=settings.origin) as member,
                httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=settings.origin) as outsider,
            ):
                owner_id = UUID((await owner.post('/api/guest/start', headers={**headers, 'Idempotency-Key': str(uuid4())})).json()['account_id'])
                member_id = UUID((await member.post('/api/guest/start', headers={**headers, 'Idempotency-Key': str(uuid4())})).json()['account_id'])
                await outsider.post('/api/guest/start', headers={**headers, 'Idempotency-Key': str(uuid4())})
                room_id = (await owner.post(
                    '/api/guest/rooms', headers={**headers, 'Idempotency-Key': str(uuid4())},
                    json={'request_id': str(uuid4()), 'title': 'Групповая история'},
                )).json()['id']
                async with database.transaction() as session:
                    session.add(RoomMembership(room_id=room_id, account_id=member_id, role='member', status='active'))
                base = f'/api/guest/rooms/{room_id}/photo'
                started = await owner.post(
                    base + '/start', headers={**headers, 'Idempotency-Key': str(uuid4())},
                    json={'question_count': 1, 'open_seconds': 60, 'hints_enabled': True, 'answer_policy': 'group_private_deadline'},
                )
                assert started.status_code == 200, started.text
                game = started.json()
                round_id = game['question']['round_id']
                owner_answer = await owner.post(
                    base + '/answer', headers={**headers, 'Idempotency-Key': str(uuid4())},
                    json={'game_id': game['game_id'], 'round_id': round_id, 'answer': 'Сова'},
                )
                assert owner_answer.status_code == 200, owner_answer.text
                member_answer = await member.post(
                    base + '/answer', headers={**headers, 'Idempotency-Key': str(uuid4())},
                    json={'game_id': game['game_id'], 'round_id': round_id, 'answer': 'Нет'},
                )
                assert member_answer.status_code == 200, member_answer.text

                assert (await owner.get('/api/account/game-history')).json()['games'] == []
                assert (await member.get('/api/account/game-history')).json()['games'] == []
                now[0] += 61
                await GameDeadlineProcessor(database).run_once(now=now[0])

                owner_history = (await owner.get('/api/account/game-history')).json()['games']
                member_history = (await member.get('/api/account/game-history')).json()['games']
                outsider_history = (await outsider.get('/api/account/game-history')).json()['games']
                assert len(owner_history) == len(member_history) == 1 and outsider_history == []
                assert owner_history[0]['my_answers'] == owner_history[0]['my_correct'] == 1
                assert float(owner_history[0]['my_score']) > 0
                assert member_history[0]['my_answers'] == 1 and member_history[0]['my_correct'] == 0
                assert member_history[0]['my_score'] == '0.0'

    asyncio.run(run())
