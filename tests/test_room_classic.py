"""Standalone Classic acceptance on real, isolated disposable PostgreSQL."""
import asyncio
import importlib.util
from pathlib import Path
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select

from application.game_deadlines import GameDeadlineProcessor
from application.room_classic import RoomClassicApplicationService
from application.rooms import RoomApplicationService
from storage.models import (Account, Chat, ClassicAccountAnswer, Game, GameCommand,
                            GamePlayer, NotificationOutbox, QuestionCategory, RoomMembership, User)
from tests.local_database import isolated_database
from tests.test_postgres_members import pg_env
from web.mini_app import MiniAppSettings, create_app


@pytest.mark.parametrize('player,guest_flag,classic_flag,guests,classic', [
    (900000000091, '0', '1', False, False),
    (900000000091, '1', '0', True, False),
    (900000000091, '1', '1', True, True),
    (123, '1', '1', False, False),
])
def test_dev_guest_opt_in_preserves_telegram_whitelist(monkeypatch, player, guest_flag, classic_flag, guests, classic):
    from fastapi import FastAPI
    from web import dev_mini_app
    captured = {}
    def factory(**kwargs):
        captured.update(kwargs)
        return FastAPI()
    monkeypatch.setattr(dev_mini_app, 'create_app', factory)
    monkeypatch.setenv('MINI_APP_DEV_USER_ID', str(player))
    monkeypatch.setenv('MQB_DEV_GUEST_ENABLED', guest_flag)
    monkeypatch.setenv('MQB_ROOM_CLASSIC_ENABLED', classic_flag)
    monkeypatch.setenv('MQB_DEV_CONTAINER', '0')
    monkeypatch.setenv('MINI_APP_DATABASE_URL', 'postgresql+asyncpg://mqb_dev:local-development-only@127.0.0.1:55433/morning_quiz_dev')
    monkeypatch.setenv('MINI_APP_BOT_TOKEN', dev_mini_app.SYNTHETIC_TOKEN)
    monkeypatch.setenv('MINI_APP_ORIGIN', 'http://127.0.0.1:4185')
    monkeypatch.setenv('MINI_APP_OFFLINE', '1')
    dev_mini_app.create_dev_app()
    assert captured['allowed_user_ids'] == {player}
    assert captured['dev_guest_access'] == guests and captured['room_classic_enabled'] == classic
    monkeypatch.setenv('MINI_APP_DATABASE_URL', 'postgresql+asyncpg://mqb_dev:local-development-only@remote:55433/morning_quiz_dev')
    with pytest.raises(RuntimeError, match='dedicated loopback'):
        dev_mini_app.create_dev_app()


def test_opted_in_guests_do_not_open_synthetic_telegram_login(pg_env):
    from tests.test_mini_app import TOKEN, NOW, signed, USER, ORIGIN
    async def run():
        async with isolated_database(pg_env) as (database, _):
            app = create_app(database=database, settings=MiniAppSettings(TOKEN, ORIGIN, offline=True),
                             clock=lambda: NOW, allowed_user_ids={900000000091},
                             dev_guest_access=True, room_classic_enabled=True)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
                assert (await client.post('/api/guest/start', headers={'Origin': ORIGIN, 'X-Guest-CSRF': '1'})).status_code == 200
                # This signature is cryptographically valid under the documented
                # synthetic token; only the server whitelist prevents imported ID access.
                rejected = await client.post('/api/mini/session', headers={'Origin': ORIGIN, 'X-Mini-CSRF': '1'}, json={'init_data': signed(USER)})
                assert rejected.status_code == 403, rejected.text
                config = (await client.get('/api/mini/config')).json()
                assert config['guest_enabled'] is True and config['private_test'] is True
    asyncio.run(run())


async def seed(database):
    owner, member, outsider = uuid4(), uuid4(), uuid4()
    room = str(uuid4())
    async with database.transaction() as session:
        session.add_all([Account(id=owner, display_name='Ведущий'), Account(id=member, display_name='Друг'), Account(id=outsider, display_name='Чужой')])
        session.add(QuestionCategory(name='Тест Classic', content_hash='0' * 64, questions=[{
            'question': f'Сколько будет {i}+1?', 'options': [str(i+1), '999'],
            'correct_option_text': str(i+1), 'solution': 'Прибавь один.'} for i in range(5)]))
    async with database.transaction() as session:
        await RoomApplicationService(session).create(account_id=owner, request_id=room, title='Квиз друзей')
        session.add(RoomMembership(room_id=room, account_id=member, role='member', status='active'))
    return room, owner, member, outsider


def test_answer_receipt_projects_submitted_round_after_another_player_advanced(pg_env):
    async def run():
        async with isolated_database(pg_env) as (database, _):
            room, owner, member, _ = await seed(database)
            async with database.transaction() as session:
                started = await RoomClassicApplicationService(session).start(room_id=room, account_id=owner,
                    command_id=str(uuid4()), count=2, open_seconds=5, interval_seconds=0, now=100)
                game = await session.get(Game, started['game_id'])
                first_round = game.state['rounds'][0]
                correct = first_round['correct_option_index']
            async with database.transaction() as session:
                await RoomClassicApplicationService(session).command(room_id=room, account_id=owner,
                    game_id=started['game_id'], command_id=str(uuid4()), kind='answer',
                    round_id=first_round['round_id'], selected_option=correct, now=101)
            await GameDeadlineProcessor(database).run_once(now=101)
            receipt_id = str(uuid4())
            body = dict(room_id=room, account_id=member, game_id=started['game_id'], command_id=receipt_id,
                        kind='answer', round_id=first_round['round_id'], selected_option=correct, now=102)
            async with database.transaction() as session:
                result = await RoomClassicApplicationService(session).command(**body)
                assert result['question']['round_id'] != first_round['round_id']
                assert result['question']['answered'] is False and 'correct_option' not in result['question']
                accepted = result['accepted_answer']
                assert accepted['round_id'] == first_round['round_id'] and accepted['is_correct'] is True
                assert Decimal(accepted['points']) == 1 and accepted['explanation'] == first_round['explanation']
            async with database.transaction() as session:
                assert await RoomClassicApplicationService(session).command(**body) == result
                other = await RoomClassicApplicationService(session).current(room_id=room, account_id=owner, now=102)
                assert 'accepted_answer' not in other and 'correct_option' not in other['question']
    asyncio.run(run())


def test_room_classic_multi_actor_repeat_worker_restart_and_no_telegram(pg_env):
    async def run():
        async with isolated_database(pg_env) as (database, _):
            room, owner, member, outsider = await seed(database)
            start_id = str(uuid4())
            async with database.transaction() as session:
                service = RoomClassicApplicationService(session)
                started = await service.start(room_id=room, account_id=owner, command_id=start_id, count=2, open_seconds=5, interval_seconds=0, now=100)
                game = await session.get(Game, started['game_id'])
                assert game.chat_id is None and game.state['chat_id'] is None
                correct = game.state['rounds'][0]['correct_option_index']
                assert 'correct_option' not in started['question'] and 'rounds' not in started
            for actor, exception in ((outsider, LookupError), (member, PermissionError)):
                with pytest.raises(exception):
                    async with database.transaction() as session:
                        await RoomClassicApplicationService(session).start(room_id=room, account_id=actor, command_id=str(uuid4()), count=2, open_seconds=5, interval_seconds=0, now=100)
            async with database.transaction() as session:
                rejected_id = str(uuid4())
                with pytest.raises(ValueError):
                    await RoomClassicApplicationService(session).command(room_id=room, account_id=owner,
                        game_id=started['game_id'], command_id=rejected_id, kind='answer',
                        round_id=started['question']['round_id'], selected_option=999, now=100)
                assert await session.get(GameCommand, rejected_id) is None
                assert await session.scalar(select(func.count()).select_from(ClassicAccountAnswer)) == 0
            answer_body = dict(room_id=room, game_id=started['game_id'], round_id=started['question']['round_id'], selected_option=correct, now=101, kind='answer')
            one_id, two_id = str(uuid4()), str(uuid4())
            async def answer(actor, command_id):
                async with database.transaction() as session:
                    return await RoomClassicApplicationService(session).command(account_id=actor, command_id=command_id, **answer_body)
            first, second = await asyncio.gather(answer(owner, one_id), answer(member, two_id))
            assert first['question']['is_correct'] and second['question']['is_correct']
            assert await answer(owner, one_id) == first
            await answer(owner, str(uuid4()))
            with pytest.raises(RuntimeError):
                await answer(owner, two_id)
            with pytest.raises(RuntimeError):
                async with database.transaction() as session:
                    await RoomClassicApplicationService(session).command(account_id=owner, command_id=str(uuid4()), **{**answer_body, 'selected_option': 1-correct})
            # New processor/service instances recover persisted deadlines while
            # Telegram adapters are absent, with two independent workers racing.
            await asyncio.gather(GameDeadlineProcessor(database).run_once(now=101), GameDeadlineProcessor(database).run_once(now=101))
            async with database.transaction() as session:
                current = await RoomClassicApplicationService(session).current(room_id=room, account_id=member, now=102)
                assert current['game']['current'] == 2
                assert 'correct_option' not in current['question']
            assert (await GameDeadlineProcessor(database).run_once(now=107))['classic'] == 1
            with pytest.raises(ValueError):
                async with database.transaction() as session:
                    await RoomClassicApplicationService(session).command(room_id=room, account_id=member,
                        game_id=started['game_id'], command_id=str(uuid4()), kind='answer',
                        round_id=current['question']['round_id'], selected_option=0, now=107)
            async with database.transaction() as session:
                current = await RoomClassicApplicationService(session).current(room_id=room, account_id=member, now=107)
                assert current['status'] == 'finished'
                assert len(current['scores']) == 2 and all(p['score'] == '1' for p in current['scores'])
                assert await session.scalar(select(func.count()).select_from(ClassicAccountAnswer)) == 2
                for model in (User, Chat, NotificationOutbox):
                    assert await session.scalar(select(func.count()).select_from(model)) == 0
                newer = await RoomClassicApplicationService(session).start(room_id=room, account_id=owner, command_id=str(uuid4()), count=1, open_seconds=5, interval_seconds=0, now=110)
                replay = await RoomClassicApplicationService(session).start(room_id=room, account_id=owner, command_id=start_id, count=2, open_seconds=5, interval_seconds=0, now=110, enabled=False)
                assert replay == started and newer['game_id'] != replay['game_id']
                assert await session.scalar(select(func.count()).select_from(Game)) == 2
            with pytest.raises(RuntimeError):
                async with database.transaction() as session:
                    await RoomClassicApplicationService(session).start(room_id=room, account_id=owner, command_id=start_id, count=3, open_seconds=5, interval_seconds=0, now=110)
    asyncio.run(run())


def test_classic_account_migration_preserves_populated_game_and_refuses_destructive_downgrade(pg_env):
    async def run():
        async with isolated_database(pg_env) as (database, _):
            room, owner, _, _ = await seed(database)
            async with database.transaction() as session:
                started = await RoomClassicApplicationService(session).start(room_id=room, account_id=owner, command_id=str(uuid4()), count=1, open_seconds=5, interval_seconds=0, now=100)
                before = dict((await session.get(Game, started['game_id'])).state)
            path = Path(__file__).resolve().parents[1] / 'alembic/versions/20261009_0024_classic_account_answers.py'
            spec = importlib.util.spec_from_file_location('classic_accounts_migration', path)
            migration = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(migration)
            assert migration.down_revision == '20261009_0023'
            async with database.engine.begin() as connection:
                # The fixture creates today's metadata. Rename its empty ledger
                # in this disposable schema to reproduce the pre-migration state.
                await connection.exec_driver_sql('ALTER TABLE classic_account_answers RENAME TO fixture_empty_answers')
                def apply(sync_connection):
                    from alembic.migration import MigrationContext
                    from alembic.operations import Operations
                    with Operations.context(MigrationContext.configure(sync_connection)):
                        migration.upgrade()
                await connection.run_sync(apply)
            async with database.transaction() as session:
                assert (await session.get(Game, started['game_id'])).state == before
                answer = await RoomClassicApplicationService(session).command(room_id=room, account_id=owner, game_id=started['game_id'],
                    command_id=str(uuid4()), kind='answer', round_id=started['question']['round_id'], selected_option=0, now=101)
                assert answer['question']['answered']
            with pytest.raises(RuntimeError, match='archival'):
                migration.downgrade()
    asyncio.run(run())


def test_guest_classic_http_auth_csrf_flag_rights_stop_and_recovery(pg_env):
    async def run():
        async with isolated_database(pg_env) as (database, _):
            settings = MiniAppSettings('', 'http://127.0.0.1:4185', offline=True)
            enabled = create_app(database=database, settings=settings, room_classic_enabled=True)
            disabled = create_app(database=database, settings=settings)
            private = create_app(database=database, settings=settings, allowed_user_ids={123}, room_classic_enabled=True)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=enabled), base_url=settings.origin) as owner, httpx.AsyncClient(transport=httpx.ASGITransport(app=enabled), base_url=settings.origin) as outsider:
                headers = {'Origin': settings.origin, 'X-Guest-CSRF': '1', 'Idempotency-Key': str(uuid4())}
                assert (await owner.post('/api/guest/start', headers=headers)).status_code == 200
                created = await owner.post('/api/guest/rooms', headers=headers, json={'request_id': str(uuid4()), 'title': 'HTTP комната'})
                assert created.status_code == 200, created.text
                room_id = created.json()['id']
                base = f'/api/guest/rooms/{room_id}/classic'
                assert (await outsider.get(base+'/current')).status_code == 401
                assert (await outsider.post('/api/guest/start', headers=headers)).status_code == 200
                assert (await outsider.get(base+'/current')).status_code == 404
                async with database.transaction() as session:
                    session.add(QuestionCategory(name='HTTP Classic', content_hash='0' * 64, questions=[{'question': 'Один плюс один?', 'options': ['Два', 'Три'], 'correct_option_text': 'Два'}]))
                body = {'count': 1, 'open_seconds': 30, 'interval_seconds': 0}
                assert (await owner.post(base+'/start', json=body)).status_code == 403
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=disabled), base_url=settings.origin, cookies=owner.cookies) as off:
                    assert (await off.post(base+'/start', headers=headers, json=body)).status_code == 403
                started = await owner.post(base+'/start', headers=headers, json=body)
                assert started.status_code == 200, started.text
                assert (await owner.post(base+'/start', headers=headers, json=body)).json() == started.json()
                game = started.json()
                answer = {'game_id': game['game_id'], 'round_id': game['question']['round_id'], 'selected_option': 0}
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=disabled), base_url=settings.origin, cookies=owner.cookies) as off:
                    assert (await off.get(base+'/current')).json()['current']['game_id'] == game['game_id']
                    accepted = await off.post(base+'/answer', headers={**headers, 'Idempotency-Key': str(uuid4())}, json=answer)
                    assert accepted.status_code == 200, accepted.text
                    stop = await off.post(base+'/stop', headers={**headers, 'Idempotency-Key': str(uuid4())}, json={'game_id': game['game_id'], 'expected_revision': accepted.json()['revision']})
                    assert stop.status_code == 200 and stop.json()['status'] == 'stopped'
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=private), base_url=settings.origin, cookies=owner.cookies) as restricted:
                    assert (await restricted.get(base+'/current')).status_code == 403
                async with database.transaction() as session:
                    assert await session.scalar(select(func.count()).select_from(GameCommand)) == 3
                    assert await session.scalar(select(func.count()).select_from(ClassicAccountAnswer)) == 1
                    assert await session.scalar(select(func.count()).select_from(GamePlayer)) == 1
    asyncio.run(run())


def test_room_classic_setup_and_start_with_categories(pg_env):
    async def run():
        async with isolated_database(pg_env) as (database, _):
            room, owner, member, outsider = await seed(database)
            async with database.transaction() as session:
                session.add_all([
                    QuestionCategory(name='Космос Classic', content_hash='1' * 64, questions=[{
                        'question': f'Планета {i}?', 'options': ['да', 'нет'], 'correct_option_text': 'да'} for i in range(3)]),
                    QuestionCategory(name='Архив Classic', content_hash='2' * 64, archived=True, questions=[{
                        'question': 'Старое?', 'options': ['да', 'нет'], 'correct_option_text': 'да'}]),
                ])
            async with database.transaction() as session:
                service = RoomClassicApplicationService(session)
                setup = await service.setup(room_id=room, account_id=member)
                assert set(setup['available_categories']) == {'Тест Classic', 'Космос Classic'}
                assert setup['category_mode'] == 'all' and setup['limits']['questions'] == [1, 50]
                with pytest.raises(LookupError):
                    await service.setup(room_id=room, account_id=outsider)
                chosen = await service.start(room_id=room, account_id=owner, command_id=str(uuid4()), count=3, open_seconds=5, interval_seconds=0,
                                             category_mode='specific', categories=['Космос Classic'], now=100)
                game = await session.get(Game, chosen['game_id'])
                assert {r['category'] for r in game.state['rounds']} == {'Космос Classic'}
                await service.command(room_id=room, account_id=owner, game_id=chosen['game_id'], command_id=str(uuid4()),
                                      kind='stop', expected_revision=chosen['revision'], now=101)
                for bad in (dict(category_mode='specific', categories=[]), dict(category_mode='specific', categories=['Нет такой']),
                            dict(category_mode='specific', categories=['Архив Classic']), dict(category_mode='bogus'),
                            dict(category_mode='all', categories=['Космос Classic']), dict(category_mode='random', random_categories=11),
                            dict(category_mode='specific', categories=['Космос Classic', 'Космос Classic'])):
                    with pytest.raises(ValueError):
                        await service.start(room_id=room, account_id=owner, command_id=str(uuid4()), count=1, open_seconds=5, interval_seconds=0, now=102, **bad)
                with pytest.raises(ValueError, match='недостаточно'):
                    await service.start(room_id=room, account_id=owner, command_id=str(uuid4()), count=4, open_seconds=5, interval_seconds=0, now=102,
                                        category_mode='specific', categories=['Космос Classic'])
                excluded = await service.start(room_id=room, account_id=owner, command_id=str(uuid4()), count=3, open_seconds=5, interval_seconds=0, now=103,
                                               category_mode='exclude', categories=['Космос Classic'])
                game = await session.get(Game, excluded['game_id'])
                assert {r['category'] for r in game.state['rounds']} == {'Тест Classic'}
    asyncio.run(run())


def test_guest_classic_http_setup_and_categories(pg_env):
    async def run():
        async with isolated_database(pg_env) as (database, _):
            settings = MiniAppSettings('', 'http://127.0.0.1:4185', offline=True)
            app = create_app(database=database, settings=settings, room_classic_enabled=True)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=settings.origin) as owner:
                headers = {'Origin': settings.origin, 'X-Guest-CSRF': '1', 'Idempotency-Key': str(uuid4())}
                assert (await owner.post('/api/guest/start', headers=headers)).status_code == 200
                room_id = (await owner.post('/api/guest/rooms', headers=headers, json={'request_id': str(uuid4()), 'title': 'Темы'})).json()['id']
                base = f'/api/guest/rooms/{room_id}/classic'
                async with database.transaction() as session:
                    session.add_all([QuestionCategory(name=name, content_hash=str(i) * 64, questions=[{
                        'question': f'{name}?', 'options': ['Да', 'Нет'], 'correct_option_text': 'Да'}]) for i, name in enumerate(['Кино', 'Музыка'], 1)])
                setup = await owner.get(base + '/setup')
                assert setup.status_code == 200, setup.text
                assert setup.json()['available_categories'] == ['Кино', 'Музыка']
                data = setup.json()
                assert (data['questions'], data['seconds'], data['interval']) == (10, 30, 30) and data['limits']['seconds'] == [5, 600]
                body = {'count': 1, 'open_seconds': 30, 'interval_seconds': 0, 'category_mode': 'specific', 'categories': ['Музыка'], 'random_categories': 3}
                bad = await owner.post(base + '/start', headers={**headers, 'Idempotency-Key': str(uuid4())}, json={**body, 'categories': ['Нет']})
                assert bad.status_code == 400
                unknown = await owner.post(base + '/start', headers={**headers, 'Idempotency-Key': str(uuid4())}, json={**body, 'extra': 1})
                assert unknown.status_code == 400
                started = await owner.post(base + '/start', headers=headers, json=body)
                assert started.status_code == 200, started.text
                assert started.json()['question']['question'].endswith('Музыка?') or 'Музыка' in started.json()['question']['question']
    asyncio.run(run())
