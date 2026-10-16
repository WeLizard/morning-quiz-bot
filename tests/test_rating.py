"""Ranking core and /api/rating: slices, periods, games, privacy, guests.

PG cases need TEST_DATABASE_URL (morning_quiz_test) and run in a private schema.
"""
import asyncio
import json
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from application.rating import RatingError, rank
from qw_farm.integration import register_models
from storage.database import normalize_database_url
from storage.models import Account, Room, RoomMembership, User
from storage.score_ledger import RewardLedger
from tests.local_database import isolated_database
from tests.test_mini_app import ORIGIN, TOKEN, signed
from web.mini_app import MiniAppSettings, create_app
from web.principal import GUEST_COOKIE, MINI_COOKIE

D = Decimal
HEADERS = {'Origin': ORIGIN, 'X-Guest-CSRF': '1'}
_uid = iter(range(981080000001, 981080009999))
NOW = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def pg_url(monkeypatch):
    raw = os.getenv('TEST_DATABASE_URL')
    if not raw:
        pytest.skip('TEST_DATABASE_URL is not configured')
    monkeypatch.setenv('QW_FARM_ENABLED', '1')
    return normalize_database_url(raw)


@asynccontextmanager
async def environment(url):
    schema = register_models()
    async with isolated_database(url) as (db, _):
        yield SimpleNamespace(db=db, schema=schema)


def run(coro):
    return asyncio.run(coro)


async def player(session, name, *, telegram=False, **flags):
    account = Account(id=uuid4(), display_name=name, **flags)
    session.add(account)
    await session.flush()
    uid = None
    if telegram:
        uid = next(_uid)
        session.add(User(id=uid, account_id=account.id, display_name=name))
        await session.flush()
    return account.id, uid


async def points(session, account, amount, key, *, source='classic', days_ago=0, **where):
    await RewardLedger.award(session, account_id=account, source=source, amount=amount, key=key,
                             at=NOW - timedelta(days=days_ago), **where)


def names(result):
    return [(row['rank'], row['display_name'], row['score']) for row in result['items']]


def test_global_period_and_game_slices(pg_url):
    async def case():
        async with environment(pg_url) as env:
            async with env.db.transaction() as session:
                a, _ = await player(session, 'Аня')
                b, _ = await player(session, 'Боря')
                c, _ = await player(session, 'Вера')
                await points(session, a, 10, 'poll:1', days_ago=40)           # old classic
                await points(session, a, 2, 'poll:2', days_ago=3)
                await points(session, b, 5, 'photo:1', source='photo', days_ago=20)
                await points(session, b, 4, 'poll:3', days_ago=1)
                await points(session, c, 100, 'craft:abcdefgh', source='alchemy', days_ago=1)   # own slice
                await points(session, c, 1, 'legacy:chat:1', source='legacy_import', days_ago=0)
            async with env.db.transaction() as session:
                allt = await rank(session, viewer=a, now=NOW)
                assert names(allt) == [(1, 'Аня', '12'), (2, 'Боря', '9'), (3, 'Вера', '1')]
                assert [r['is_me'] for r in allt['items']] == [True, False, False]
                assert allt['me'] == {'rank': 1, 'score': '12', 'listed': True, 'hidden': False, 'needs_nickname': False}
                week = await rank(session, viewer=a, period='week', now=NOW)
                assert names(week) == [(1, 'Боря', '4'), (2, 'Аня', '2'), (3, 'Вера', '1')]
                month = await rank(session, viewer=a, period='month', now=NOW)
                assert names(month) == [(1, 'Боря', '9'), (2, 'Аня', '2'), (3, 'Вера', '1')]
                photo = await rank(session, viewer=a, game='photo', now=NOW)
                assert names(photo) == [(1, 'Боря', '5')]
                assert photo['me']['rank'] is None, 'no points in this game'
                alchemy = await rank(session, viewer=a, scope='alchemy', now=NOW)
                assert names(alchemy) == [(1, 'Вера', '100')]
                with pytest.raises(RatingError):
                    await rank(session, viewer=a, scope='alchemy', game='photo')
                with pytest.raises(RatingError):
                    await rank(session, viewer=a, scope='nope')
    run(case())


def test_ties_share_a_rank_and_paging_is_stable(pg_url):
    async def case():
        async with environment(pg_url) as env:
            async with env.db.transaction() as session:
                ids = [(await player(session, n))[0] for n in ('А', 'Б', 'В', 'Г')]
                for i, acc in enumerate(ids):
                    await points(session, acc, 5 if i < 2 else 3, f'poll:{i}')
            async with env.db.transaction() as session:
                first = await rank(session, viewer=None, limit=3, now=NOW)
                second = await rank(session, viewer=None, limit=3, offset=3, now=NOW)
                assert [r['rank'] for r in first['items']] == [1, 1, 3] and first['has_more']
                assert [r['rank'] for r in second['items']] == [3] and not second['has_more']
                assert first['me'] is None
    run(case())


def test_who_is_listed(pg_url):
    async def case():
        async with environment(pg_url) as env:
            async with env.db.transaction() as session:
                shown, _ = await player(session, 'Видимая')
                hidden, _ = await player(session, 'Скрытая', rating_hidden=True)
                guest, _ = await player(session, 'Гость')
                blocked, _ = await player(session, 'Заблокированный', bot_blocked=True)
                archived, _ = await player(session, 'Архивная', archived=True)
                main, _ = await player(session, 'Основная')
                merged, _ = await player(session, 'Слитая')
                for i, acc in enumerate((shown, hidden, guest, blocked, archived, merged), 1):
                    await points(session, acc, 10 - i, f'poll:{i}')
                (await session.get(Account, merged)).merged_into_id = main
            async with env.db.transaction() as session:
                result = await rank(session, viewer=guest, now=NOW)
                assert [r['display_name'] for r in result['items']] == ['Видимая', 'Заблокированный'], \
                    'hidden, unnamed guest, archived and merged accounts are not listed; bot_blocked stay'
                # The guest without a nickname sees only their own place, not a row.
                assert result['me'] == {'rank': 2, 'score': '7', 'listed': False, 'hidden': False, 'needs_nickname': True}
                assert not any(r['is_me'] for r in result['items'])
                own = await rank(session, viewer=hidden, now=NOW)
                assert own['me']['hidden'] and own['me']['rank'] == 2 and not own['me']['listed']
                # Private groups (room scope) do not require a nickname.
                room = Room(id='r1', kind='classic', title='Комната')
                session.add(room)
                await session.flush()
                for acc in (shown, guest):
                    session.add(RoomMembership(room_id='r1', account_id=acc, role='member', status='active'))
                await session.flush()
                await points(session, shown, 2, 'room:g:r1', room_id='r1')
                await points(session, guest, 6, 'room:g:r2', room_id='r1')
                in_room = await rank(session, viewer=guest, scope='room', room_id='r1', now=NOW)
                assert names(in_room) == [(1, 'Гость', '6'), (2, 'Видимая', '2')]
    run(case())


def test_friends_are_room_mates_and_farm_neighbours(pg_url):
    async def case():
        async with environment(pg_url) as env:
            async with env.db.transaction() as session:
                me, _ = await player(session, 'Я')
                mate, _ = await player(session, 'Сокомнатник')
                stranger, _ = await player(session, 'Чужой')
                session.add(Room(id='r2', kind='classic', title='t'))
                await session.flush()
                for acc in (me, mate):
                    session.add(RoomMembership(room_id='r2', account_id=acc, role='member', status='active'))
                await session.flush()
                for i, acc in enumerate((me, mate, stranger)):
                    await points(session, acc, 3 + i, f'poll:{i}')
            async with env.db.transaction() as session:
                result = await rank(session, viewer=me, scope='friends', now=NOW)
                assert names(result) == [(1, 'Сокомнатник', '4'), (2, 'Я', '3')]
                assert result['me']['rank'] == 2
                with pytest.raises(RatingError):
                    await rank(session, viewer=None, scope='friends')
    run(case())


def test_farm_slice_uses_xp_and_respects_private_farms(pg_url):
    from qw_farm.domain import new_farm
    from qw_farm.expansion import upgrade_state
    from qw_farm.persistence import Unit

    async def case():
        async with environment(pg_url) as env:
            async with env.db.transaction() as session:
                a, _ = await player(session, 'Фермер')
                b, _ = await player(session, 'Скромник')
                unit = Unit(session, env.schema)
                for acc, xp, visibility in ((a, 500, 'public'), (b, 900, 'private')):
                    farm = upgrade_state(new_farm(str(uuid4()), 'Ферма', 1000))
                    farm['xp'] = xp
                    farm['settings']['visibility'] = visibility
                    await unit.save(farm, acc)
                    await unit.record(acc, 'k', 'bootstrap', None, farm, time.time())
            async with env.db.transaction() as session:
                result = await rank(session, viewer=b, scope='farm', now=NOW)
                assert names(result) == [(1, 'Фермер', '500')], 'private farms are not listed'
                assert result['me']['rank'] == 1 and result['me']['score'] == '900', 'but the owner sees the own place'
                week = await rank(session, viewer=a, scope='farm', period='week', now=datetime.now(timezone.utc))
                assert week['items'], 'ledger xp of the last days counts'
    run(case())


# ------------------------------------------------------------------------ HTTP
async def web(env):
    app = create_app(database=env.db, settings=MiniAppSettings(TOKEN, ORIGIN, offline=True),
                     clock=lambda: int(time.time()))
    return app, httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN)


def test_api_rating_hides_identifiers_and_works_for_guest_and_telegram(pg_url):
    async def case():
        async with environment(pg_url) as env:
            app, client = await web(env)
            async with client:
                async with env.db.transaction() as session:
                    other, other_uid = await player(session, 'Телеграмщик', telegram=True)
                    await points(session, other, 8, 'poll:x', days_ago=0)
                # Guest without a nickname: sees the rating and only their own place.
                response = await client.post('/api/guest/start', headers=HEADERS)
                assert response.status_code == 200, response.text
                guest_account = response.json()['account_id']
                async with env.db.transaction() as session:
                    await points(session, __import__('uuid').UUID(guest_account), 5, 'poll:g')
                body = await client.get('/api/rating')
                assert body.status_code == 200, body.text
                data = body.json()
                assert [r['display_name'] for r in data['items']] == ['Телеграмщик']
                assert data['me']['rank'] == 2 and data['me']['listed'] is False and data['me']['needs_nickname']
                text = body.text
                assert guest_account not in text and str(other_uid) not in text
                for row in data['items']:
                    assert set(row) == {'rank', 'display_name', 'score', 'is_me'}
                assert 'options' in data and set(data['options']) == {'rooms', 'chats', 'telegram'}
                # Choosing a nickname lists the guest; hiding removes them again.
                assert (await client.post('/api/guest/profile', headers=HEADERS, json={'display_name': 'Ник'})).status_code == 200
                data = (await client.get('/api/rating')).json()
                assert [(r['display_name'], r['is_me']) for r in data['items']] == [('Телеграмщик', False), ('Ник', True)]
                hide = await client.post('/api/account/rating-visibility', headers=HEADERS, json={'hidden': True})
                assert hide.status_code == 200 and hide.json() == {'hidden': True}
                data = (await client.get('/api/rating')).json()
                assert [r['display_name'] for r in data['items']] == ['Телеграмщик']
                assert data['me']['hidden'] and data['me']['rank'] == 2
                bad = await client.post('/api/account/rating-visibility', headers=HEADERS, json={'hidden': 'yes'})
                assert bad.status_code == 400
                assert (await client.get('/api/rating?scope=bogus')).status_code == 422
                assert (await client.get('/api/rating?scope=room&room_id=nope')).status_code == 404
    run(case())


def test_api_rating_for_a_telegram_session_and_no_session(pg_url):
    async def case():
        async with environment(pg_url) as env:
            app, client = await web(env)
            async with client:
                assert (await client.get('/api/rating')).status_code == 401
                async with env.db.transaction() as session:
                    tg, uid = await player(session, 'Игрок', telegram=True)
                    await points(session, tg, 4, 'poll:t')
                response = await client.post('/api/mini/session', json={
                    'init_data': signed(uid, date=int(time.time()), query_id=uuid4().hex)})
                assert response.status_code == 200, response.text
                data = (await client.get('/api/rating')).json()
                assert data['items'][0]['is_me'] and data['me']['rank'] == 1 and data['options']['telegram']
                assert json.dumps(data).count(str(uid)) == 0
    run(case())
