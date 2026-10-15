"""Standalone personal Photo acceptance in disposable PostgreSQL schemas."""
import asyncio
from hashlib import sha256
from io import BytesIO
from uuid import UUID, uuid4

import httpx
from PIL import Image
import pytest
from sqlalchemy import func, select

from application.game_deadlines import GameDeadlineProcessor
from application.photo import PhotoApplicationService
from application.room_classic import RoomClassicApplicationService
from application.room_photo import RoomPhotoApplicationService
from domain.photo import normalize_photo, prepare_photo
from storage.admin_actions import operation_fence
from storage.models import (Account, Chat, Game, GameCommand, GameDeadline, GameEvent,
                            NotificationOutbox, PhotoQuizItem, PollAnswer,
                            RoomMembership, User)
from tests.local_database import isolated_database
from tests.test_postgres_members import pg_env
from tests.test_room_classic import seed
from web.mini_app import MiniAppSettings, create_app


@pytest.mark.parametrize('guest_flag,photo_flag,guests,photo', [
    ('0', '1', False, False), ('1', '0', True, False), ('1', '1', True, True),
])
def test_dev_room_photo_start_gate_is_separate_from_guest_access(monkeypatch, guest_flag, photo_flag, guests, photo):
    from fastapi import FastAPI
    from web import dev_mini_app
    captured = {}
    def factory(**kwargs):
        captured.update(kwargs)
        return FastAPI()
    monkeypatch.setattr(dev_mini_app, 'create_app', factory)
    for key, value in {
        'MINI_APP_DEV_USER_ID': str(dev_mini_app.DEMO_USER), 'MQB_DEV_GUEST_ENABLED': guest_flag,
        'MQB_ROOM_PHOTO_ENABLED': photo_flag, 'MQB_ROOM_CLASSIC_ENABLED': '0', 'MQB_DEV_CONTAINER': '0',
        'MINI_APP_DATABASE_URL': 'postgresql+asyncpg://mqb_dev:local-development-only@127.0.0.1:55433/morning_quiz_dev',
        'MINI_APP_BOT_TOKEN': dev_mini_app.SYNTHETIC_TOKEN, 'MINI_APP_ORIGIN': 'http://127.0.0.1:4185',
        'MINI_APP_OFFLINE': '1',
    }.items():
        monkeypatch.setenv(key, value)
    dev_mini_app.create_dev_app()
    assert captured['dev_guest_access'] == guests and captured['room_photo_enabled'] == photo
    assert captured['room_classic_enabled'] is False
    assert captured['allowed_user_ids'] == {dev_mini_app.DEMO_USER}


@pytest.fixture
def photo_media(tmp_path, monkeypatch):
    root = tmp_path / 'photo-images'
    root.mkdir()
    image = BytesIO()
    Image.new('RGB', (3, 3), (125, 45, 200)).save(image, format='WEBP', lossless=True)
    content = image.getvalue()
    (root / 'owl.webp').write_bytes(content)
    monkeypatch.setenv('PHOTO_IMAGES_DIR', str(root))
    return content


async def catalog(database, content):
    async with database.transaction() as session:
        session.add(PhotoQuizItem(media_key='owl', correct_answer='Сова', enabled=True, hints={},
            metadata_json={'storage_name': 'owl', 'image_sha256': sha256(content).hexdigest()}))
        # Unavailable and disabled entries are never candidates.
        session.add(PhotoQuizItem(media_key='missing', correct_answer='Нет', enabled=True, hints={}, metadata_json={}))
        session.add(PhotoQuizItem(media_key='disabled', correct_answer='Нет', enabled=False, hints={}, metadata_json={}))


def test_room_photo_domain_scope_preserves_telegram_rules():
    question = {'display_answer': 'Сова', 'media': {'media_key': 'owl'}}
    room = prepare_photo(room_id='room', creator_account_id=str(uuid4()), questions=[question], now=100)
    assert room['chat_id'] is None and room['creator_id'] is None
    assert normalize_photo(room, room_id='room') is not None
    assert normalize_photo(room, room_id='other') is None and normalize_photo(room, chat_id=1) is None
    telegram = prepare_photo(chat_id=1, creator_id=2, questions=[question], now=100)
    assert normalize_photo(telegram, chat_id=1) is not None
    assert normalize_photo(telegram, room_id='room') is None
    assert normalize_photo({**room, 'creator_id': 123}) is None
    with pytest.raises(ValueError):
        prepare_photo(room_id='room', creator_account_id='account', chat_id=1, creator_id=2, questions=[question])


def test_room_photo_receipts_privacy_hints_scoring_restart_and_stop(pg_env, photo_media, monkeypatch):
    async def run():
        async with isolated_database(pg_env) as (db, _):
            room, owner, member, outsider = await seed(db)
            await catalog(db, photo_media)
            start_id = str(uuid4())
            body = dict(room_id=room, account_id=owner, command_id=start_id,
                        question_count=2, open_seconds=5, now=100)
            async with db.transaction() as session:
                service = RoomPhotoApplicationService(session)
                assert (await service.setup(room_id=room, account_id=owner))['available_questions'] == 1
                started = await service.start(**body)
                assert 'rounds' not in started and 'normalized_answer' not in str(started)
                assert 'Сова' not in str(started)
                game = await session.get(Game, started['game_id'])
                assert game.chat_id is None and game.state['creator_account_id'] == str(owner)
            for actor, exception in ((member, PermissionError), (outsider, LookupError)):
                with pytest.raises(exception):
                    async with db.transaction() as session:
                        await RoomPhotoApplicationService(session).start(**{**body, 'account_id': actor, 'command_id': str(uuid4())})
            async with db.transaction() as session:
                service = RoomPhotoApplicationService(session)
                assert await service.current(room_id=room, account_id=member, now=100) == {'occupied': True}
                rejected = str(uuid4())
                with pytest.raises(PermissionError):
                    await service.command(room_id=room, account_id=member, game_id=started['game_id'], command_id=rejected,
                        kind='answer', round_id=started['question']['round_id'], answer='Сова', now=101)
                assert await session.get(GameCommand, rejected) is None
            answer = dict(room_id=room, account_id=owner, game_id=started['game_id'],
                          command_id=str(uuid4()), kind='answer', round_id=started['question']['round_id'], answer='Нет', now=101)
            async def command(values):
                async with db.transaction() as session:
                    return await RoomPhotoApplicationService(session).command(**values)
            wrong, duplicate = await asyncio.gather(command(answer), command(answer))
            assert wrong == duplicate and wrong['verdict'] == 'wrong'
            correct = await command({**answer, 'command_id': str(uuid4()), 'answer': 'Сова', 'now': 102})
            assert correct['last_result']['points'] == 5.5 and correct['correct'] == 1
            assert correct['question']['round_id'] != answer['round_id']
            # New worker instances race, reveal exactly two hints and close once.
            await asyncio.gather(GameDeadlineProcessor(db).run_once(now=107), GameDeadlineProcessor(db).run_once(now=107))
            async with db.transaction() as session:
                finished = await RoomPhotoApplicationService(session).current(room_id=room, account_id=owner, now=107)
                assert finished['status'] == 'finished' and finished['score'] == '5.5'
                assert await PhotoApplicationService(db, session).due(now=107) == []
                assert await RoomPhotoApplicationService(session).due_game_ids(now=107) == []
                assert await session.scalar(select(func.count()).select_from(GameEvent).where(GameEvent.kind == 'photo_timed_out')) == 1
                assert await session.scalar(select(func.count()).select_from(GameDeadline).where(GameDeadline.status == 'pending')) == 0
                for model in (User, Chat, NotificationOutbox, PollAnswer):
                    assert await session.scalar(select(func.count()).select_from(model)) == 0
                second = await RoomPhotoApplicationService(session).start(**{**body, 'command_id': str(uuid4()), 'now': 110})
                # Receipt lookup precedes selection/replacement, even with starts disabled.
                async def forbidden(*args):
                    raise AssertionError('Replay selected a new random catalog')
                monkeypatch.setattr('application.room_photo.select_photo_questions', forbidden)
                assert await RoomPhotoApplicationService(session).start(**{**body, 'now': 110, 'enabled': False}) == started
                assert await session.scalar(select(func.count()).select_from(Game)) == 2
            with pytest.raises(RuntimeError):
                await command({**answer, 'command_id': str(uuid4()), 'answer': 'Сова', 'now': 110})
            stop = dict(room_id=room, account_id=owner, game_id=second['game_id'], command_id=str(uuid4()),
                        kind='stop', expected_revision=second['revision'], now=111)
            stopped = await command(stop)
            assert stopped['status'] == 'stopped' and await command(stop) == stopped
            with pytest.raises(RuntimeError):
                async with db.transaction() as session:
                    await RoomPhotoApplicationService(session).start(**{**body, 'question_count': 3})
    asyncio.run(run())


def test_room_photo_answer_worker_race_has_one_round_result_and_failed_savepoint(pg_env, photo_media):
    async def run():
        async with isolated_database(pg_env) as (db, _):
            room, owner, _, _ = await seed(db)
            await catalog(db, photo_media)
            async with db.transaction() as session:
                started = await RoomPhotoApplicationService(session).start(room_id=room, account_id=owner,
                    command_id=str(uuid4()), question_count=1, open_seconds=5, now=100)
            async def answer():
                async with db.transaction() as session:
                    try:
                        return await RoomPhotoApplicationService(session).command(room_id=room, account_id=owner,
                            game_id=started['game_id'], command_id=str(uuid4()), kind='answer',
                            round_id=started['question']['round_id'], answer='Сова', now=105)
                    except RuntimeError:
                        return None
            await asyncio.gather(answer(), GameDeadlineProcessor(db).run_once(now=105), GameDeadlineProcessor(db).run_once(now=105))
            async with db.transaction() as session:
                game = await session.get(Game, started['game_id'])
                assert game.status == 'finished'
                assert game.state['total_correct'] in {0, 1}
                assert game.state['total_score'] in {0.0, 5.0}
                assert await session.scalar(select(func.count()).select_from(GameEvent).where(
                    GameEvent.game_id == game.id, GameEvent.kind.in_(['photo_answered', 'photo_timed_out']))) == 1
                rejected = str(uuid4())
                with pytest.raises(RuntimeError):
                    await RoomPhotoApplicationService(session).command(room_id=room, account_id=owner,
                        game_id=game.id, command_id=rejected, kind='answer', round_id=started['question']['round_id'], answer='Сова', now=106)
                assert await session.get(GameCommand, rejected) is None
    asyncio.run(run())


def test_guest_room_photo_http_privacy_media_flags_csrf_and_receipt_scope(pg_env, photo_media):
    async def run():
        async with isolated_database(pg_env) as (db, _):
            await catalog(db, photo_media)
            settings = MiniAppSettings('', 'http://127.0.0.1:4185', offline=True)
            app = create_app(database=db, settings=settings, room_photo_enabled=True)
            off = create_app(database=db, settings=settings)
            headers = {'Origin': settings.origin, 'X-Guest-CSRF': '1', 'Idempotency-Key': str(uuid4())}
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=settings.origin) as owner, httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=settings.origin) as member:
                assert (await owner.post('/api/guest/start', headers=headers)).status_code == 200
                account_id = UUID((await member.post('/api/guest/start', headers=headers)).json()['account_id'])
                room = (await owner.post('/api/guest/rooms', headers=headers, json={'request_id': str(uuid4()), 'title': 'Фото'})).json()['id']
                base = f'/api/guest/rooms/{room}/photo'
                assert (await member.get(base+'/current')).status_code == 404
                async with db.transaction() as session:
                    session.add(RoomMembership(room_id=room, account_id=account_id, role='member', status='active'))
                payload = {'question_count': 2, 'open_seconds': 60, 'hints_enabled': True}
                assert (await owner.post(base+'/start', json=payload)).status_code == 403
                assert (await member.post(base+'/start', headers=headers, json=payload)).status_code == 403
                started = await owner.post(base+'/start', headers=headers, json=payload)
                assert started.status_code == 200, started.text
                assert (await owner.post(base+'/start', headers=headers, json=payload)).json() == started.json()
                game = started.json()
                image_url = game['question']['image_url']
                image = await owner.get(image_url)
                assert image.status_code == 200 and image.content == photo_media
                assert image.headers['cache-control'] == 'no-store'
                assert image.headers['content-disposition'] == 'inline; filename="photo.webp"'
                assert (await member.get(base+'/current')).json() == {'current': None, 'occupied': True}
                assert (await member.get(image_url)).status_code == 404
                assert (await owner.get(image_url.replace(game['game_id'], str(uuid4())))).status_code == 404
                assert (await owner.get(base+'/current/image')).status_code == 404
                async with db.transaction() as session:
                    row = await session.get(Game, game['game_id'])
                    assert await PhotoApplicationService(db, session).question_delivery(
                        game_id=row.id, round_id=game['question']['round_id']) is None
                answer = {'game_id': game['game_id'], 'round_id': game['question']['round_id'], 'answer': 'Сова'}
                assert (await member.post(base+'/answer', headers={**headers, 'Idempotency-Key': str(uuid4())}, json=answer)).status_code == 403
                assert (await owner.post(base+'/answer', headers=headers, json={**answer, 'account_id': str(account_id)})).status_code == 400
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=off), base_url=settings.origin, cookies=owner.cookies) as disabled:
                    accepted = await disabled.post(base+'/answer', headers={**headers, 'Idempotency-Key': str(uuid4())}, json=answer)
                    assert accepted.status_code == 200, accepted.text
                    current = accepted.json()
                    assert current['last_result']['points'] == 6.0
                    assert (await disabled.get(image_url)).status_code == 404
                    assert (await disabled.get(current['question']['image_url'])).status_code == 200
                    stopped = await disabled.post(base+'/stop', headers={**headers, 'Idempotency-Key': str(uuid4())}, json={'game_id': current['game_id'], 'expected_revision': current['revision']})
                    assert stopped.status_code == 200, stopped.text
                    assert (await disabled.get(current['question']['image_url'])).status_code == 404
                    assert (await disabled.post(base+'/start', headers={**headers, 'Idempotency-Key': str(uuid4())}, json=payload)).status_code == 403
                    # The original start may be replayed but cannot replace stopped state.
                    assert (await disabled.post(base+'/start', headers=headers, json=payload)).json() == game
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=settings.origin) as anonymous:
                    assert (await anonymous.get(image_url)).status_code == 401
                async with db.transaction() as session:
                    assert await session.scalar(select(func.count()).select_from(Game)) == 1
                    assert await session.scalar(select(func.count()).select_from(GameCommand)) == 3
    asyncio.run(run())


@pytest.mark.parametrize('mode', ['classic', 'photo', 'mafia'])
def test_admin_fence_precedes_guest_auth_and_stale_guest_is_rejected(pg_env, mode):
    async def run():
        async with isolated_database(pg_env) as (db, _):
            settings = MiniAppSettings('', 'http://127.0.0.1:4185', offline=True)
            app = create_app(database=db, settings=settings, room_photo_enabled=True, room_classic_enabled=True)
            headers = {'Origin': settings.origin, 'X-Guest-CSRF': '1', 'Idempotency-Key': str(uuid4())}
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=settings.origin) as client:
                account_id = UUID((await client.post('/api/guest/start', headers=headers)).json()['account_id'])
                room = (await client.post('/api/guest/rooms', headers=headers, json={'request_id': str(uuid4()), 'title': 'Fence'})).json()['id']
                if mode == 'classic':
                    path, body = f'/api/guest/rooms/{room}/classic/start', {'count': 1, 'open_seconds': 30, 'interval_seconds': 0}
                elif mode == 'photo':
                    path, body = f'/api/guest/rooms/{room}/photo/start', {'question_count': 1, 'open_seconds': 60, 'hints_enabled': True}
                else:
                    path, body = f'/api/guest/rooms/{room}/mafia/lobby', {}
                async with db.transaction() as admin:
                    await operation_fence(admin, exclusive=True)
                    # Guest must wait for this fence without taking Account first.
                    pending = asyncio.create_task(client.post(path, headers=headers, json=body))
                    await asyncio.sleep(0.05)
                    account = await asyncio.wait_for(admin.scalar(select(Account).where(Account.id == account_id).with_for_update()), timeout=3)
                    account.bot_blocked = True
                    account.moderation_revision += 1
                    assert not pending.done()
                response = await asyncio.wait_for(pending, timeout=3)
                assert response.status_code == 401, response.text
                async with db.transaction() as session:
                    assert await session.scalar(select(func.count()).select_from(GameCommand)) == 0
                    assert await session.scalar(select(func.count()).select_from(Game)) == 0
                # Reverse order: a valid guest holding shared fence and Account
                # completes before an admin may acquire the exclusive fence.
                async with db.transaction() as session:
                    account = await session.get(Account, account_id)
                    account.bot_blocked = False
                    account.moderation_revision -= 1
                from storage.guest_accounts import GuestAccounts
                token = client.cookies.get('mqb_guest')
                if token is None:
                    token = next(value for name, value in client.cookies.items() if 'guest' in name)
                async with GuestAccounts(db).authorized(token, lock=True) as (_, _, _):
                    async def moderate():
                        async with db.transaction() as session:
                            await operation_fence(session, exclusive=True)
                            account = await session.scalar(select(Account).where(Account.id == account_id).with_for_update())
                            account.bot_blocked = True
                    admin_pending = asyncio.create_task(moderate())
                    await asyncio.sleep(0.05)
                    assert not admin_pending.done()
                await asyncio.wait_for(admin_pending, timeout=3)
    asyncio.run(run())


def test_direct_room_services_revalidate_moderated_account_after_fence(pg_env):
    async def run():
        async with isolated_database(pg_env) as (db, _):
            room, owner, _, _ = await seed(db)
            async with db.transaction() as session:
                cached = await session.get(Account, owner)  # deliberately cache pre-moderation account
                async with db.transaction() as admin:
                    account = await admin.get(Account, owner)
                    account.bot_blocked = True
                assert cached.bot_blocked is False
                for service in (RoomClassicApplicationService(session), RoomPhotoApplicationService(session)):
                    with pytest.raises(PermissionError):
                        await service.current(room_id=room, account_id=owner)
    asyncio.run(run())
