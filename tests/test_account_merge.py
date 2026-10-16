"""AccountMergeService: PostgreSQL cases on a disposable schema plus the FK policy guard.

PG cases need TEST_DATABASE_URL (morning_quiz_test); they skip otherwise.
"""
import asyncio
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import func, select, update

from application.account_merge import MERGE_POLICY, AccountMergeService, policy_gaps
from qw_farm.domain import new_farm
from qw_farm.expansion import upgrade_state
from qw_farm.integration import register_models
from qw_farm.persistence import Unit
from storage.mini_app import MiniAppError
from storage.models import (Account, AccountCredential, AccountIdentity, AccountMerge, AlchemyProgress,
                            AlchemyStageClaim, ClassicAccountAnswer, Game, GamePlayer, GuestSession,
                            Room, RoomMembership, User)
from storage.database import normalize_database_url
from tests.local_database import isolated_database
from tests.test_mini_app import ORIGIN, TOKEN, signed
from web.mini_app import MiniAppSettings, create_app
from web.principal import GUEST_COOKIE, MINI_COOKIE, resolve_principal

HEADERS = {'Origin': ORIGIN, 'X-Guest-CSRF': '1'}
SERVICE = AccountMergeService(clock=time.time)
_uid = iter(range(981050000001, 981050009999))


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


# ---------------------------------------------------------------- pure guard
def test_model_constraint_and_index_names_match_migration_0031():
    """F17: names in storage.models equal the ones alembic 20261015_0031 creates."""
    from storage.models import Base
    tables = Base.metadata.tables

    def names(table):
        return ({c.name for c in table.constraints if c.name}, {i.name for i in table.indexes})
    constraints, indexes = names(tables['telegram_login_requests'])
    assert {'ck_telegram_login_requests_status', 'uq_telegram_login_requests_start',
            'uq_telegram_login_requests_browser'} <= constraints
    assert indexes == {'ix_telegram_login_requests_expires'}
    constraints, indexes = names(tables['account_merges'])
    assert 'uq_account_merges_merged' in constraints and indexes == {'ix_account_merges_main'}
    assert 'ck_accounts_not_merged_into_self' in names(tables['accounts'])[0]


def test_every_account_foreign_key_has_a_merge_policy():
    register_models()
    missing, stale = policy_gaps()
    assert not missing, f'FK on accounts.id without MERGE_POLICY entry: {missing}'
    assert not stale, f'MERGE_POLICY entries without a real FK: {stale}'
    assert set(MERGE_POLICY.values()) <= {'move', 'move_no_conflict', 'union', 'history', 'special'}


# ------------------------------------------------------------------- helpers
async def make_account(session, name, *, telegram=False, login=None, discovered=None, points=0):
    account = Account(id=uuid4(), display_name=name)
    session.add(account)
    await session.flush()
    uid = None
    if telegram:
        uid = next(_uid)
        session.add(User(id=uid, account_id=account.id, display_name=name))
        await session.flush()
        session.add(AccountIdentity(account_id=account.id, provider='telegram', provider_subject=str(uid),
                                    verified_at=datetime.now(timezone.utc)))
    if login:
        session.add(AccountIdentity(account_id=account.id, provider='password', provider_subject=login,
                                    verified_at=datetime.now(timezone.utc)))
        session.add(AccountCredential(account_id=account.id, password_hash='x'))
    if discovered is not None or points:
        await session.flush()
        session.add(AlchemyProgress(account_id=account.id, user_id=uid, discovered=list(discovered or []),
                                    verified_discovered=list(discovered or []), points_total=Decimal(points)))
    await session.flush()
    return account, uid


async def make_farm(env, session, account, *, coins=None, inventory=None, starter_credit=None):
    """Bootstrap exactly like FarmService.open; extra coins/inventory make the farm 'touched'.

    Explicit ``coins`` are earned coins (starter_credit 0) unless ``starter_credit`` says otherwise."""
    unit = Unit(session, env.schema)
    farm = upgrade_state(new_farm(str(uuid4()), 'T', 1000))
    await unit.save(farm, account.id)
    await unit.record(account.id, 'bootstrap', 'bootstrap', None, farm, 1000)
    if coins is not None or inventory is not None:
        before = dict(farm, inventory=dict(farm['inventory']))
        farm['coins'] = coins if coins is not None else farm['coins']
        if starter_credit is not None:
            farm['starter_credit'] = starter_credit
        elif coins is not None:
            farm['starter_credit'] = 0
        farm['inventory'] = dict(inventory if inventory is not None else farm['inventory'])
        farm['revision'] += 1
        await unit.save(farm)
        await unit.record(account.id, 'fixture', 'fixture', before, farm, 1001)
    return farm


async def merge(env, main_id, secondary_id, via='test'):
    async with env.db.transaction() as session:
        main, secondary = await session.get(Account, main_id), await session.get(Account, secondary_id)
        return await SERVICE.merge_in(session, main=main, secondary=secondary, via=via)


async def plan(env, current_id, telegram_id):
    async with env.db.transaction() as session:
        return await SERVICE.plan_in(session, current=await session.get(Account, current_id),
                                     telegram_account=await session.get(Account, telegram_id))


def run(coro):
    return asyncio.run(coro)


async def farm_of(env, account_id):
    async with env.db.transaction() as session:
        return await Unit(session, env.schema).by_account(account_id)


# --------------------------------------------------------------------- tests
def test_auto_merge_empty_guest_into_telegram(pg_url):
    async def case():
        async with environment(pg_url) as env:
            async with env.db.transaction() as session:
                guest, _ = await make_account(session, 'Гость')
                tg, uid = await make_account(session, 'Игрок', telegram=True, discovered=['water', 'steam'], points=7)
                await make_farm(env, session, guest)  # untouched bootstrap farm counts as empty
                token = 'g' * 64
                session.add(GuestSession(token_hash=token, account_id=guest.id, account_revision=0,
                                         created_at=datetime.now(timezone.utc),
                                         expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc)))
                gid, tid = guest.id, tg.id
            p = await plan(env, gid, tid)
            assert p['auto'] and p['main'].id == tid and p['secondary'].id == gid
            assert p['preview']['current']['empty'] and not p['preview']['telegram']['empty']
            summary = await merge(env, p['main'].id, p['secondary'].id, via='telegram_login')
            async with env.db.transaction() as session:
                sec = await session.get(Account, gid)
                assert sec.archived and sec.merged_into_id == tid and sec.merged_at
                assert (await session.get(GuestSession, 'g' * 64)).account_id == tid
                assert (await session.get(AlchemyProgress, tid)).points_total == Decimal(7)
                audit = await session.scalar(select(AccountMerge).where(AccountMerge.merged_account_id == gid))
                assert audit.main_account_id == tid and audit.initiated_via == 'telegram_login'
                assert audit.summary['secondary_account_id'] == str(gid)
            assert summary['farm'] == 'moved_to_main'
    run(case())


def test_empty_telegram_into_nonempty_guest_moves_user(pg_url):
    async def case():
        async with environment(pg_url) as env:
            async with env.db.transaction() as session:
                guest, _ = await make_account(session, 'Гость', login='alice', discovered=['water', 'steam'], points=3)
                tg, uid = await make_account(session, 'Игрок', telegram=True)
                gid, tid = guest.id, tg.id
            p = await plan(env, gid, tid)
            assert p['auto'] and p['main'].id == gid
            await merge(env, p['main'].id, p['secondary'].id, via='telegram_login')
            async with env.db.transaction() as session:
                assert (await session.get(User, uid)).account_id == gid
                ident = await session.scalar(select(AccountIdentity).where(
                    AccountIdentity.provider == 'telegram', AccountIdentity.revoked_at.is_(None)))
                assert ident.account_id == gid
                assert (await session.get(Account, gid)).display_name == 'Игрок'  # placeholder name replaced
                assert (await session.get(Account, tid)).archived
    run(case())


def test_both_nonempty_union_points_from_main_and_farms_summed(pg_url):
    async def case():
        async with environment(pg_url) as env:
            async with env.db.transaction() as session:
                a, _ = await make_account(session, 'A', login='aaa', discovered=['water', 'steam'], points=10)
                b, _ = await make_account(session, 'B', telegram=True, discovered=['fire', 'steam', 'lava'], points=99)
                session.add(AlchemyStageClaim(account_id=a.id, stage_id='s1', campaign_id='c', catalog_revision='1',
                                              reward={}, claimed_at=datetime.now(timezone.utc)))
                session.add_all([AlchemyStageClaim(account_id=b.id, stage_id=s, campaign_id='c', catalog_revision='1',
                                                   reward={}, claimed_at=datetime.now(timezone.utc))
                                 for s in ('s1', 's2')])
                await make_farm(env, session, a, coins=300, inventory={'wheat': 5})
                await make_farm(env, session, b, coins=260, inventory={'wheat': 2, 'feed': 7})
                aid, bid = a.id, b.id
            p = await plan(env, aid, bid)
            assert not p['auto'] and p['main'] is None
            assert {'current', 'telegram', 'rules', 'lost_login', 'lost_login_if_current_main',
                    'lost_login_if_telegram_main'} <= set(p['preview'])
            summary = await merge(env, aid, bid, via='mini_app')
            async with env.db.transaction() as session:
                row = await session.get(AlchemyProgress, aid)
                assert row.discovered == ['water', 'steam', 'fire', 'lava']
                assert row.points_total == Decimal(10)
                claims = (await session.scalars(select(AlchemyStageClaim.stage_id).where(
                    AlchemyStageClaim.account_id == aid))).all()
                assert sorted(claims) == ['s1', 's2']
                assert await session.scalar(select(func.count()).select_from(AlchemyStageClaim).where(
                    AlchemyStageClaim.account_id == bid)) == 1  # duplicate s1 stays behind
            farm = await farm_of(env, aid)
            assert farm['coins'] == 560 and farm['inventory']['wheat'] == 7 and farm['inventory']['feed'] == 7
            assert (await farm_of(env, bid))['coins'] == 260  # secondary farm stays untouched
            async with env.db.transaction() as session:
                ledger = env.schema['ledger']
                row = (await session.execute(select(ledger).where(
                    ledger.c.command_id == f'merge:{bid}'))).mappings().one()
                assert row['kind'] == 'account_merge' and row['xp_delta'] == 0
                assert row['coins_delta'] == 260 and row['inventory_delta'] == {'wheat': 2, 'feed': 7}
                assert row['actor_account_id'] == aid
            assert summary['lost_login'] is None
    run(case())


def test_starter_gift_coins_of_secondary_are_not_moved(pg_url):
    """F3: a farm touched by one action still holds its 250 starter coins; merging must not mint them."""
    async def case():
        async with environment(pg_url) as env:
            async with env.db.transaction() as session:
                a, _ = await make_account(session, 'A', login='aaa')
                b, _ = await make_account(session, 'B', telegram=True)
                await make_farm(env, session, a, coins=300, inventory={'wheat': 5})
                # Fresh farm of B, touched once (a seed was added); coins are still the 250-coin gift.
                await make_farm(env, session, b, inventory={'wheat': 3, 'feed': 2}, starter_credit=250)
                aid, bid = a.id, b.id
            assert (await farm_of(env, bid))['coins'] == 250 and (await farm_of(env, bid))['starter_credit'] == 250
            summary = await merge(env, aid, bid)
            farm = await farm_of(env, aid)
            assert farm['coins'] == 300 and farm['starter_credit'] == 0
            assert farm['inventory']['wheat'] == 8 and farm['inventory']['feed'] == 2  # storage moves as is
            assert summary['farm']['coins_added'] == 0 and summary['farm']['starter_credit_not_moved'] == 250
            async with env.db.transaction() as session:
                ledger = env.schema['ledger']
                row = (await session.execute(select(ledger).where(
                    ledger.c.command_id == f'merge:{bid}'))).mappings().one()
                assert row['coins_delta'] == 0
            # Partly earned: 260 coins of which 100 are the gift -> only 160 move.
            async with env.db.transaction() as session:
                c, _ = await make_account(session, 'C', login='ccc')
                d, _ = await make_account(session, 'D', telegram=True)
                await make_farm(env, session, c, coins=40, inventory={'wheat': 1})
                await make_farm(env, session, d, coins=260, inventory={'wheat': 1}, starter_credit=100)
                cid, did = c.id, d.id
            summary = await merge(env, cid, did)
            assert (await farm_of(env, cid))['coins'] == 200 and summary['farm']['coins_added'] == 160
    run(case())


def test_farm_only_on_secondary_moves_and_caps(pg_url):
    async def case():
        async with environment(pg_url) as env:
            async with env.db.transaction() as session:
                a, _ = await make_account(session, 'A', login='aaa')
                b, _ = await make_account(session, 'B', telegram=True)
                farm = await make_farm(env, session, b, coins=300, inventory={'wheat': 1})
                aid, bid = a.id, b.id
            await merge(env, aid, bid)
            moved = await farm_of(env, aid)
            assert moved['id'] == farm['id'] and await farm_of(env, bid) is None
            async with env.db.transaction() as session:
                a2, _ = await make_account(session, 'C', login='ccc')
                b2, _ = await make_account(session, 'D', telegram=True)
                await make_farm(env, session, a2, coins=10 ** 12 - 5 - 0, inventory={'wheat': 10 ** 9 - 1})
                await make_farm(env, session, b2, coins=300, inventory={'wheat': 5})
                a2id, b2id = a2.id, b2.id
            summary = await merge(env, a2id, b2id)
            capped = await farm_of(env, a2id)
            assert capped['coins'] == 10 ** 12 and capped['inventory']['wheat'] == 10 ** 9
            assert {t['what'] for t in summary['truncated']} == {'coins', 'item:wheat'}
    run(case())


def test_rooms_memberships_game_players_conflicts(pg_url):
    async def case():
        async with environment(pg_url) as env:
            async with env.db.transaction() as session:
                a, _ = await make_account(session, 'A', login='aaa')
                b, _ = await make_account(session, 'B', telegram=True)
                session.add_all([Room(id='r-own', kind='classic', owner_account_id=b.id),
                                 Room(id='r-shared', kind='classic', owner_account_id=a.id),
                                 Room(id='r-only-b', kind='classic', owner_account_id=a.id)])
                await session.flush()
                session.add_all([
                    RoomMembership(room_id='r-own', account_id=b.id, role='owner'),
                    RoomMembership(room_id='r-shared', account_id=a.id, role='member'),
                    RoomMembership(room_id='r-shared', account_id=b.id, role='owner'),
                    RoomMembership(room_id='r-only-b', account_id=b.id, role='member')])
                for game in ('g1', 'g2'):
                    session.add(Game(id=game, room_id='r-own', chat_id=None, mode=game, status='x', phase='x', state={},
                                     is_current=False))
                await session.flush()
                session.add_all([
                    GamePlayer(game_id='g1', account_id=a.id, seat='1'), GamePlayer(game_id='g1', account_id=b.id, seat='2'),
                    GamePlayer(game_id='g2', account_id=b.id, seat='1'),
                    ClassicAccountAnswer(game_id='g1', round_id='r', account_id=a.id, selected_option=0,
                                         is_correct=True, points_delta=1),
                    ClassicAccountAnswer(game_id='g1', round_id='r', account_id=b.id, selected_option=1,
                                         is_correct=False, points_delta=0),
                    ClassicAccountAnswer(game_id='g2', round_id='r', account_id=b.id, selected_option=1,
                                         is_correct=False, points_delta=0)])
                aid, bid = a.id, b.id
            await merge(env, aid, bid)
            async with env.db.transaction() as session:
                roles = {m.room_id: (m.account_id, m.role) for m in (await session.scalars(
                    select(RoomMembership).where(RoomMembership.account_id.in_([aid, bid])))).all()}
                assert roles == {'r-own': (aid, 'owner'), 'r-shared': (aid, 'owner'), 'r-only-b': (aid, 'member')}
                assert (await session.get(Room, 'r-own')).owner_account_id == aid
                players = {(p.game_id): p.account_id for p in (await session.scalars(select(GamePlayer))).all()}
                assert players['g2'] == aid
                assert (await session.scalar(select(func.count()).select_from(GamePlayer).where(
                    GamePlayer.account_id == bid))) == 1  # g1 conflict stays
                answers = {(x.game_id): x.account_id for x in (await session.scalars(select(ClassicAccountAnswer))).all()}
                assert await session.scalar(select(func.count()).select_from(ClassicAccountAnswer).where(
                    ClassicAccountAnswer.account_id == bid)) == 1
    run(case())


def test_password_on_both_sides_reports_lost_login(pg_url):
    async def case():
        async with environment(pg_url) as env:
            async with env.db.transaction() as session:
                a, _ = await make_account(session, 'A', login='keep', discovered=['water', 'x'])
                b, _ = await make_account(session, 'B', login='gone', discovered=['water', 'y'])
                aid, bid = a.id, b.id
            p = await plan(env, aid, bid)
            assert p['preview']['lost_login'] == 'gone'
            # F7: the warning exists for BOTH choices of the main profile.
            assert p['preview']['lost_login_if_current_main'] == 'gone'
            assert p['preview']['lost_login_if_telegram_main'] == 'keep'
            summary = await merge(env, aid, bid)
            assert summary['lost_login'] == 'gone'
            async with env.db.transaction() as session:
                active = (await session.scalars(select(AccountIdentity.provider_subject).where(
                    AccountIdentity.provider == 'password', AccountIdentity.revoked_at.is_(None)))).all()
                assert active == ['keep']
    run(case())


def test_lost_login_fields_are_empty_without_two_logins(pg_url):
    async def case():
        async with environment(pg_url) as env:
            async with env.db.transaction() as session:
                a, _ = await make_account(session, 'A', login='only', discovered=['water', 'x'])
                b, _ = await make_account(session, 'B', telegram=True, discovered=['water', 'y'])
                aid, bid = a.id, b.id
            preview = (await plan(env, aid, bid))['preview']
            assert preview['lost_login'] is None
            assert preview['lost_login_if_current_main'] is None and preview['lost_login_if_telegram_main'] is None
    run(case())


def test_moved_guest_sessions_lose_telegram_freshness(pg_url):
    """F6: a session born from a Telegram login on the secondary must not keep the no-password reset right."""
    async def case():
        async with environment(pg_url) as env:
            async with env.db.transaction() as session:
                a, _ = await make_account(session, 'A', login='aaa', discovered=['water', 'x'])
                b, _ = await make_account(session, 'B', telegram=True, discovered=['water', 'y'])
                now = datetime.now(timezone.utc)
                session.add(GuestSession(token_hash='f' * 64, account_id=b.id, account_revision=0,
                                         created_at=now, expires_at=now + timedelta(days=1),
                                         created_via='telegram', user_agent='Chrome · Windows'))
                aid, bid = a.id, b.id
            await merge(env, aid, bid)
            async with env.db.transaction() as session:
                row = await session.get(GuestSession, 'f' * 64)
                assert row.account_id == aid and row.created_via is None
    run(case())


def test_password_moves_when_main_has_none(pg_url):
    async def case():
        async with environment(pg_url) as env:
            async with env.db.transaction() as session:
                a, _ = await make_account(session, 'A', discovered=['water', 'x'])
                b, _ = await make_account(session, 'B', login='moves', telegram=True)
                aid, bid = a.id, b.id
            await merge(env, aid, bid)
            async with env.db.transaction() as session:
                assert (await session.get(AccountCredential, aid)) is not None
                assert (await session.scalar(select(AccountIdentity.account_id).where(
                    AccountIdentity.provider_subject == 'moves'))) == aid
    run(case())


def test_two_telegrams_repeat_and_unavailable_are_rejected(pg_url):
    async def case():
        async with environment(pg_url) as env:
            async with env.db.transaction() as session:
                a, _ = await make_account(session, 'A', telegram=True, discovered=['water', 'x'])
                b, _ = await make_account(session, 'B', telegram=True, discovered=['water', 'y'])
                c, _ = await make_account(session, 'C', discovered=['water', 'z'])
                aid, bid, cid = a.id, b.id, c.id
            with pytest.raises(MiniAppError) as error:
                await plan(env, aid, bid)
            assert error.value.status == 409 and error.value.code == 'merge_two_telegram'
            with pytest.raises(MiniAppError) as error:
                await merge(env, aid, bid)
            assert error.value.code == 'merge_two_telegram'
            await merge(env, aid, cid)
            with pytest.raises(MiniAppError) as error:  # archived secondary cannot be merged again
                await merge(env, bid, cid)
            assert error.value.code == 'merge_unavailable'
            with pytest.raises(MiniAppError) as error:
                await merge(env, cid, aid)
            assert error.value.code == 'merge_unavailable'
    run(case())


def test_rollback_leaves_both_accounts_untouched(pg_url, monkeypatch):
    async def case():
        async with environment(pg_url) as env:
            async with env.db.transaction() as session:
                a, _ = await make_account(session, 'A', login='aaa', discovered=['water', 'x'], points=1)
                b, uid = await make_account(session, 'B', telegram=True, discovered=['fire', 'y'], points=2)
                await make_farm(env, session, a, coins=300)
                await make_farm(env, session, b, coins=310)
                aid, bid = a.id, b.id

            async def boom(*args, **kwargs):
                raise RuntimeError('boom')
            monkeypatch.setattr(AccountMergeService, '_merge_farm', boom)
            with pytest.raises(RuntimeError):
                await merge(env, aid, bid)
            async with env.db.transaction() as session:
                for account_id in (aid, bid):
                    account = await session.get(Account, account_id)
                    assert not account.archived and account.merged_into_id is None
                assert (await session.get(User, uid)).account_id == bid
                assert (await session.get(AlchemyProgress, aid)).discovered == ['water', 'x']
                assert (await session.get(AlchemyProgress, bid)).discovered == ['fire', 'y']
                assert await session.scalar(select(func.count()).select_from(AccountMerge)) == 0
            assert (await farm_of(env, aid))['coins'] == 300
    run(case())


def test_sessions_and_principal_follow_main(pg_url):
    async def case():
        async with environment(pg_url) as env:
            app = create_app(database=env.db, settings=MiniAppSettings(TOKEN, ORIGIN, offline=True),
                             clock=lambda: int(time.time()))
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
                # Telegram account (non-empty) + a guest account that has a live browser session.
                async with env.db.transaction() as session:
                    tg, uid = await make_account(session, 'Игрок', telegram=True, discovered=['water', 'x'], points=4)
                    tid = tg.id
                now = int(time.time())
                response = await client.post('/api/mini/session', json={
                    'init_data': signed(uid, date=now, query_id=uuid4().hex)})
                assert response.status_code == 200, response.text
                mini_cookie = client.cookies.get(MINI_COOKIE)
                client.cookies.clear()
                response = await client.post('/api/guest/start', headers=HEADERS)
                assert response.status_code == 200, response.text
                guest_id = UUID(response.json()['account_id'])
                guest_cookie = client.cookies.get(GUEST_COOKIE)
            p = await plan(env, guest_id, tid)
            assert p['auto'] and p['main'].id == tid
            await merge(env, p['main'].id, p['secondary'].id, via='telegram_login')
            for cookies, identity in (({GUEST_COOKIE: guest_cookie}, 'guest'), ({MINI_COOKIE: mini_cookie}, 'telegram')):
                req = SimpleNamespace(cookies=cookies, query_params={})
                async with resolve_principal(req, database=env.db, guest_store=app.state.guest_store,
                                             mini_store=app.state.mini_store, identity=identity) as (_, principal):
                    assert principal.account_id == str(tid), identity
    run(case())
