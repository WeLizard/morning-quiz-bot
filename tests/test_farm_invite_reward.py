"""Invitation rewards: invitee bonus on a fresh farm, inviter coins once per invited farm at L3, limits, no self-invite."""
import asyncio
from copy import deepcopy
from uuid import uuid4

import pytest

from qw_farm.catalog import INVITE, LEVELS, level, income_ref
from qw_farm.domain import FarmError
from qw_farm.service import FarmService, Principal
from tests.test_farm_platform import farm_pg_url  # noqa: F401  (fixture)

T0 = 1_791_600_000
DAY = 86400


class World:
    """In-memory twin of farm_states + farm_invites for several accounts."""
    def __init__(self):
        self.farms, self.accounts, self.links, self.records = {}, {}, {}, []


class Unit:
    def __init__(self, world, account):
        self.w, self.account = world, account

    async def lock(self, *keys): pass

    async def by_account(self, account_id):
        fid = self.w.accounts.get(account_id)
        return deepcopy(self.w.farms[fid]) if fid else None

    async def get(self, farm_id): return deepcopy(self.w.farms.get(farm_id))

    async def owner_account(self, farm_id): return next(a for a, f in self.w.accounts.items() if f == farm_id)

    async def save(self, farm, account_id=None):
        self.w.farms[farm['id']] = deepcopy(farm)
        if account_id:
            self.w.accounts[account_id] = farm['id']

    async def receipt(self, account_id, key): return None

    async def remember(self, *a): pass

    async def record(self, actor, key, kind, before, after, now):
        self.w.records.append((actor, key, kind, after['coins'] - (before or {'coins': 0})['coins']))

    async def public_farms(self): return []

    async def invite_add(self, invitee, inviter, now):
        if invitee in self.w.links:
            return False
        self.w.links[invitee] = dict(inviter=inviter, rewarded_at=None)
        return True

    async def invite_list(self, inviter):
        return [dict(id=i, rewarded_at=l['rewarded_at'], name=self.w.farms[i]['name'], xp=self.w.farms[i]['xp'])
                for i, l in self.w.links.items() if l['inviter'] == inviter]

    async def invite_mark(self, invitee, now):
        if self.w.links[invitee]['rewarded_at'] is not None:
            return False
        self.w.links[invitee]['rewarded_at'] = now
        return True


def player(world, name, clock):
    return FarmService(Unit(world, name), Principal(name, name), clock=lambda: clock[0])


def grow(world, service, xp):
    world.farms[world.accounts[service.p.account_id]]['xp'] = xp


def run(coro): return asyncio.run(coro)


def test_bonus_for_invited_and_reward_once_at_level_three_in_any_channel():
    async def go():
        world, clock = World(), [T0]
        host = player(world, 'host', clock)
        hid = (await host.open())['farm']['id']
        base = world.farms[hid]['coins']
        newbie = player(world, 'newbie', clock)
        opened = await newbie.open(hid)   # the same call serves Telegram startapp, web ?invite= and a typed code
        assert opened['farm']['coins'] == 250 + INVITE['bonus'] and opened['farm']['invited_by'] == hid
        assert opened['invites']['bonus'] == INVITE['bonus']
        again = await newbie.open(hid)    # reopening never pays twice
        assert again['farm']['coins'] == 250 + INVITE['bonus']
        view = await host.view()          # level 1: waiting
        assert view['farm']['coins'] == base and view['invites']['invited'][0]['status'] == 'growing'
        grow(world, newbie, LEVELS[INVITE['level'] - 1])
        assert level(world.farms[world.accounts['newbie']]['xp']) == INVITE['level']
        paid = await host.view()
        assert paid['farm']['coins'] == base + INVITE['reward']
        assert paid['invites']['invited'][0]['status'] == 'rewarded' and paid['invites']['total'] == 1
        assert (await host.view())['farm']['coins'] == base + INVITE['reward']   # one reward per invited farm
        assert any(r[2] == 'invite_reward' and r[3] == INVITE['reward'] for r in world.records)
    run(go())


def test_typed_code_is_the_same_as_a_link_and_only_for_fresh_farms():
    async def go():
        world, clock = World(), [T0]
        host = player(world, 'host', clock)
        hid = (await host.open())['farm']['id']
        newbie = player(world, 'newbie', clock)
        await newbie.open()
        done = await newbie.accept_invite(hid)
        assert done['coins'] == 250 + INVITE['bonus']
        old = player(world, 'old', clock)
        await old.open()
        clock[0] += 2 * DAY
        with pytest.raises(FarmError) as e:
            await old.accept_invite(hid)
        assert e.value.code == 'invite_late'
        veteran = player(world, 'xp', clock)
        await veteran.open()
        grow(world, veteran, 25)
        with pytest.raises(FarmError):
            await veteran.accept_invite(hid)
    run(go())


def test_no_self_invite_and_one_inviter_per_farm():
    async def go():
        world, clock = World(), [T0]
        a, b = player(world, 'a', clock), player(world, 'b', clock)
        aid = (await a.open())['farm']['id']
        with pytest.raises(FarmError) as e:
            await a.accept_invite(aid)
        assert e.value.code == 'self_invite'
        assert (await a.open(aid))['farm']['coins'] == 250   # silently ignored on open
        bid = (await b.open())['farm']['id']
        c = player(world, 'c', clock)
        await c.open(aid)
        with pytest.raises(FarmError):
            await c.accept_invite(bid)                       # already invited by a
        assert world.links[world.accounts['c']]['inviter'] == aid
        with pytest.raises(FarmError) as e:
            await b.accept_invite(str(uuid4()))
        assert e.value.code == 'invite_unknown'
        with pytest.raises(FarmError) as e:
            await b.accept_invite('not-a-code')
        assert e.value.code == 'invalid_invite'
    run(go())


def test_daily_and_total_limits_defer_but_never_lose_rewards():
    async def go():
        world, clock = World(), [T0 + 3600]
        host = player(world, 'host', clock)
        hid = (await host.open())['farm']['id']
        base = world.farms[hid]['coins']
        for i in range(INVITE['per_day'] + 2):
            g = player(world, f'g{i}', clock)
            await g.open(hid)
            grow(world, g, LEVELS[INVITE['level'] - 1])
        result = await host.view()
        assert result['farm']['coins'] == base + INVITE['per_day'] * INVITE['reward']
        assert result['invites']['today_left'] == 0
        assert sum(1 for i in result['invites']['invited'] if i['status'] == 'ready') == 2   # waiting, not lost
        clock[0] += DAY
        result = await host.view()
        assert result['farm']['coins'] == base + (INVITE['per_day'] + 2) * INVITE['reward']
        world.farms[hid]['referral']['total'] = INVITE['total']   # the lifetime cap
        late = player(world, 'late', clock)
        await late.open(hid)
        grow(world, late, LEVELS[INVITE['level'] - 1])
        before = world.farms[hid]['coins']
        assert (await host.view())['farm']['coins'] == before
    run(go())


def test_reward_numbers_are_in_the_early_economy_range():
    assert income_ref(1) <= INVITE['reward'] <= 2 * income_ref(1)   # 1-2 days of early income
    assert 0 < INVITE['bonus'] < INVITE['reward']
    assert INVITE['level'] >= 3 and INVITE['per_day'] * INVITE['reward'] <= 4 * income_ref(1)


# ------------------------------------------------------------------ PostgreSQL + HTTP: real table, real SQL
def test_postgres_http_invite_bonus_link_and_single_reward(farm_pg_url):
    from sqlalchemy import select, func, update
    from uuid import UUID
    from tests.test_farm_platform import environment, player as http_player, raw_farm, view, API, FARM_HEADERS

    async def go():
        async with environment(farm_pg_url) as env:
            async with http_player(env) as host:
                base = (await raw_farm(env, host))['coins']
                # the web channel: the invite travels in the /start body; a bad / self code never blocks the farm
                async with http_player(env, invite=host.farm_id) as guest:
                    mine = await raw_farm(env, guest)
                    assert mine['coins'] == 250 + INVITE['bonus'] and mine['invited_by'] == host.farm_id
                    bad = await guest.client.post(API + '/start', params={'identity': 'guest'}, headers=FARM_HEADERS,
                                                  json={'invite': 'garbage', 'x': 1})
                    assert bad.status_code == 422
                    table = env.schema['invites']
                    async with env.db.transaction() as session:
                        assert await session.scalar(select(func.count()).select_from(table)) == 1
                    page = await guest.client.get(API + '/invite', params={'identity': 'guest'})
                    assert page.status_code == 200 and page.json()['rewards']['bonus'] == INVITE['bonus']
                    assert (await view(host, None))['coins'] == base                          # level 1: no reward yet
                    async with env.db.transaction() as session:
                        states = env.schema['states']
                        await session.execute(update(states).where(states.c.id == UUID(guest.farm_id)).values(xp=LEVELS[INVITE['level'] - 1]))
                    assert (await view(host, None))['coins'] == base + INVITE['reward']
                    assert (await view(host, None))['coins'] == base + INVITE['reward']      # paid once
                    # a typed code is refused on a farm that already has an inviter
                    again = await guest.client.post(API + '/invite/accept', params={'identity': 'guest'}, headers=FARM_HEADERS,
                                                    json={'code': host.farm_id})
                    assert again.status_code in {409, 422}
                async with http_player(env, invite=host.farm_id) as other:                   # self-invite impossible
                    own = await other.client.post(API + '/invite/accept', params={'identity': 'guest'}, headers=FARM_HEADERS,
                                                  json={'code': other.farm_id})
                    assert own.status_code == 422 and own.json()['code'] == 'self_invite'
    asyncio.run(go())


def test_postgres_migration_0028_is_additive_and_refuses_to_drop_data(farm_pg_url, monkeypatch):
    async def run():
        from alembic.config import Config
        from alembic.migration import MigrationContext
        from alembic.operations import Operations
        from alembic.script import ScriptDirectory
        from sqlalchemy import inspect, text
        from tests.local_database import isolated_database
        scripts = ScriptDirectory.from_config(Config('alembic.ini'))
        migration = scripts.get_revision('20261010_0028').module
        assert migration.down_revision == '20261010_0027'
        async with isolated_database(farm_pg_url) as (db, schema):
            async with db.engine.begin() as connection:
                def roundtrip(sync):
                    sync.execute(text('DROP TABLE farm_invites'))
                    with monkeypatch.context() as patch:
                        patch.setattr(migration, 'op', Operations(MigrationContext.configure(sync)))
                        migration.upgrade()
                    columns = {c['name'] for c in inspect(sync).get_columns('farm_invites', schema=schema)}
                    assert columns == {'invitee_farm_id', 'inviter_farm_id', 'created_at', 'rewarded_at'}
                    with monkeypatch.context() as patch:
                        patch.setattr(migration, 'op', Operations(MigrationContext.configure(sync)))
                        migration.downgrade()
                        assert 'farm_invites' not in inspect(sync).get_table_names(schema=schema)
                        migration.upgrade()
                    assert 'farm_invites' in inspect(sync).get_table_names(schema=schema)
                await connection.run_sync(roundtrip)
    asyncio.run(run())
