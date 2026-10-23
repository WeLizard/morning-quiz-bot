"""Village construction (shared stages) and the market rows: docs/tasks/FARM_VILLAGE_CONSTRUCTION.md.

Logic tests run on the local SQLite harness (``DemoDatabase``); the shared-SQL races and the migration run on PostgreSQL
(``TEST_DATABASE_URL``, skipped without it).
"""
import asyncio
from copy import deepcopy
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from qw_farm import construction as cn, economy, merchant, progression
from qw_farm.catalog import ITEMS, LEVELS, income_ref
from qw_farm.domain import FarmError, new_farm, validate_state
from qw_farm.expansion import upgrade_state
from qw_farm.persistence import DemoDatabase
from qw_farm.service import FarmService, Principal

DAY = 86400
T0 = 20_000 * DAY - economy.TZ_OFFSET + 3600           # a Moscow morning
N = [0]


def key():
    N[0] += 1
    return f'cmd-construction-{N[0]:06d}'


class World:
    """Several players on one local database and one clock."""

    def __init__(self):
        self.db = DemoDatabase(':memory:')
        self.now = [T0]
        self.players = {}

    async def player(self, name, lv=12, coins=200_000, items=None, credit=0):
        aid = uuid4()
        async with self.db.transaction() as unit:
            await unit.execute(self.db.accounts.insert().values(id=aid, name=name, recovery_hash=uuid4().hex * 2))
            farm = upgrade_state(new_farm(str(uuid4()), name, self.now[0]))
            farm.update(xp=LEVELS[lv - 1], coins=coins, starter_credit=credit)
            farm['inventory'].update(items or {})
            progression.touch(farm, self.now[0])
            validate_state(farm)
            await unit.save(farm, aid)
            self.players[name] = SimpleNamespace(aid=aid, fid=farm['id'])
        return self.players[name]

    async def run(self, name, fn):
        p = self.players[name]
        async with self.db.transaction() as unit:
            service = FarmService(unit, Principal(str(p.aid), name), clock=lambda: self.now[0])
            return await fn(service, unit)

    async def cmd(self, name, kind, data, target=None, command_id=None):
        return await self.run(name, lambda s, u: s.command(command_id or key(), kind, data, target))

    async def view(self, name):
        return await self.run(name, lambda s, u: s.view())

    async def build(self, name):
        return (await self.view(name))['farm']['village_build']

    async def farm(self, name):
        return await self.run(name, lambda s, u: u.by_account(self.players[name].aid))

    async def project(self, pid):
        async with self.db.transaction() as unit:
            t = unit.t['projects']
            row = (await unit.execute(sa.select(t).where(t.c.id == pid))).mappings().first()
            return dict(row)

    async def force(self, pid, **values):
        async with self.db.transaction() as unit:
            t = unit.t['projects']
            await unit.execute(t.update().where(t.c.id == pid).values(**values))

    async def grant(self, name, items=None, coins=0):
        async with self.db.transaction() as unit:
            farm = await unit.by_account(self.players[name].aid)
            for k, q in (items or {}).items():
                farm['inventory'][k] = farm['inventory'].get(k, 0) + q
            farm['coins'] += coins
            await unit.save(farm)


def run(coro):
    return asyncio.run(coro)


def active_project(build):
    return next(p for p in build['projects'] if p['status'] in ('collecting', 'working'))


async def full_load(world, name):
    """Give the player everything the current stage needs, and one stage more."""
    build = await world.build(name)
    proj = active_project(build)
    await world.grant(name, {k: v + 5 for k, v in proj['need'].items() if k != 'coins'}, coins=proj['need'].get('coins', 0))
    return proj


async def fund_stage(world, name, pid=None):
    """Contribute exactly the current need of the active project in one command."""
    proj = await full_load(world, name)
    items = {k: v - proj['got'].get(k, 0) for k, v in proj['need'].items() if k != 'coins' and v > proj['got'].get(k, 0)}
    coins = proj['need']['coins'] - proj['got'].get('coins', 0)
    return await world.cmd(name, 'build_contribute', {'project': proj['id'], 'items': items, 'coins': coins})


# ----------------------------------------------------------------------------------------------------------- rules
def test_stage_need_is_a_share_of_the_active_income_with_the_fund_floor():
    ref = 40_000
    pit = cn.stage_need('stalls', 0, ref)
    assert pit['coins'] == 1600 and pit['wood'] == 2400 // cn.unit_credit('wood') == 240       # 10% of 40000: 60% goods, 40% coins
    assert cn.stage_need('stalls', 1, ref)['coins'] == 3200 and set(cn.stage_need('stalls', 1, ref)) == {'wood', 'linen', 'coins'}
    assert cn.stage_need('tavern', 2, ref).keys() == {'bread', 'pie', 'pancake', 'linen', 'coins'}
    assert cn.REF_FLOOR == 40_000
    for pid, stages in cn.GOODS.items():
        assert len(stages) == 3 and all(k in ITEMS and not ITEMS[k].get('bound') for ks in stages for k in ks)
    assert [cn.tier_of(x) for x in (0, 999, 1000, 3999, 4000, 9999, 10000)] == [0, 0, 1, 1, 2, 2, 3]


def test_effective_end_energy_cap_fund_and_floor():
    row = dict(work_until=1_000_000, stage=1, speedup=0, fund_speed=0)
    assert cn.effective_end(row) == 1_000_000
    assert cn.effective_end({**row, 'speedup': 10 * DAY}) == 1_000_000 - DAY              # at most one day from the energy drinks
    assert cn.effective_end({**row, 'speedup': DAY, 'fund_speed': DAY}) == 1_000_000 - 2 * DAY + cn.MIN_WORK   # both cuts hit the floor of a 2-day stage
    assert cn.effective_end({**row, 'speedup': DAY // 2, 'fund_speed': DAY // 4}) == 1_000_000 - 3 * DAY // 4
    assert cn.effective_end({**row, 'stage': 0, 'speedup': DAY, 'fund_speed': DAY}) == 1_000_000 - DAY + cn.MIN_WORK   # never instant


def test_fund_tiers_perks_are_derived_from_the_personal_scale():
    f = upgrade_state(new_farm(str(uuid4()), 'x', T0))
    assert not economy.perk(f, 'magpie', T0)
    rec = economy.record(f, economy.season_of(T0), 12)
    rec['tiers'] = 2
    assert economy.perk(f, 'magpie', T0) and not economy.perk(f, 'early', T0)
    assert economy.TIER_REWARD[2] == 'magpie' and economy.TIER_REWARD[4] == 'early'


# ----------------------------------------------------------------------------------------------------------- lifecycle
def test_first_stage_starts_lazily_and_a_repeated_read_changes_nothing():
    async def scenario():
        w = World()
        await w.player('a')
        build = await w.build('a')
        first = build['projects'][0]
        assert first['id'] == 'stalls' and first['status'] == 'collecting' and first['stage'] == 0
        assert [p['status'] for p in build['projects']] == ['collecting', 'soon', 'soon', 'soon']
        before = await w.project('stalls')
        await w.build('a')
        assert await w.project('stalls') == before                                           # idempotent read
        assert build['rows'] == {'open': False}
    run(scenario())


def test_contribution_is_clipped_closes_the_stage_and_later_players_keep_their_goods():
    async def scenario():
        w = World()
        await w.player('a', items={'wood': 10_000})
        await w.player('b', items={'wood': 10_000})
        need_ = (await w.build('a'))['projects'][0]['need']
        a0 = await w.farm('a')
        res = await w.cmd('a', 'build_contribute', {'project': 'stalls', 'items': {'wood': 9000}, 'coins': 50_000})
        a1 = await w.farm('a')
        assert a0['inventory']['wood'] - a1['inventory']['wood'] == need_['wood']             # only the missing part is taken
        assert a0['coins'] - a1['coins'] == need_['coins']
        assert 'Лишнее' in res['notice']
        row = await w.project('stalls')
        assert row['status'] == 'working' and row['work_until'] == T0 + DAY and row['got'] == need_
        b0 = await w.farm('b')
        with pytest.raises(FarmError) as error:
            await w.cmd('b', 'build_contribute', {'project': 'stalls', 'items': {'wood': 50}, 'coins': 10})
        assert error.value.code == 'stage_closed'
        assert (await w.farm('b'))['inventory'] == b0['inventory'] and (await w.farm('b'))['coins'] == b0['coins']
    run(scenario())


def test_validation_level_bound_items_starter_credit_and_unknown_things():
    async def scenario():
        w = World()
        await w.player('low', lv=7)
        await w.player('rich', coins=300, credit=300, items={'wood': 5, 'magpie_seed_pack': 1} if 'magpie_seed_pack' in ITEMS else {'wood': 5})
        for name, data, code in [
                ('low', {'project': 'stalls', 'items': {}, 'coins': 10}, 'locked'),
                ('rich', {'project': 'stalls', 'items': {}, 'coins': 10}, 'earned_coins'),
                ('rich', {'project': 'stalls', 'items': {'bread': 1}, 'coins': 0}, 'not_needed'),
                ('rich', {'project': 'nope', 'items': {}, 'coins': 1}, 'unknown_project'),
                ('rich', {'project': 'tavern', 'items': {'wood': 1}, 'coins': 0}, 'stage_closed'),
                ('rich', {'project': 'stalls', 'items': {}, 'coins': 0}, 'nothing_needed'),
                ('rich', {'project': 'stalls', 'items': {'wood': 0}, 'coins': 1}, 'invalid_command')]:
            with pytest.raises(FarmError) as error:
                await w.cmd(name, 'build_contribute', data)
            assert error.value.code == code, (data, error.value.code)
        bound = [k for k, v in ITEMS.items() if v.get('bound')]
        assert bound
        with pytest.raises(FarmError) as error:
            await w.cmd('rich', 'build_contribute', {'project': 'stalls', 'items': {bound[0]: 1}, 'coins': 0})
        assert error.value.code == 'bound_item'
    run(scenario())


def test_full_lifecycle_stages_work_times_open_and_next_project():
    async def scenario():
        w = World()
        await w.player('a', coins=2_000_000)
        durations = (DAY, 2 * DAY, 2 * DAY)
        for stage in range(3):
            await fund_stage(w, 'a')
            row = await w.project('stalls')
            assert row['status'] == 'working' and row['stage'] == stage and row['work_until'] == w.now[0] + durations[stage]
            w.now[0] += durations[stage] - 1
            assert (await w.build('a'))['projects'][0]['status'] == 'working'                  # one second early
            w.now[0] += 1
            build = await w.build('a')
            if stage < 2:
                assert build['projects'][0]['status'] == 'collecting' and build['projects'][0]['stage'] == stage + 1
        projects = {p['id']: p for p in build['projects']}
        assert projects['stalls']['status'] == 'done' and projects['stalls']['opened_at'] == w.now[0]
        assert projects['tavern']['status'] == 'collecting' and projects['tavern']['stage'] == 0   # the next one gets the blueprint
        assert build['rows']['open'] is True
        version = (await w.project('tavern'))['version']
        await w.build('a')
        assert (await w.project('tavern'))['version'] == version
        farm = await w.farm('a')
        assert farm['village_bonus']['open'] == ['stalls'] and farm['village_bonus']['tiers']['stalls'] == 3
    run(scenario())


def test_ledger_has_one_record_per_transition_and_one_per_tier():
    async def scenario():
        w = World()
        await w.player('a', coins=2_000_000)
        await fund_stage(w, 'a')
        w.now[0] += DAY
        await w.build('a')
        await w.build('a')
        async with w.db.transaction() as unit:
            t = unit.t['ledger']
            rows = (await unit.execute(sa.select(t.c.command_id, t.c.kind))).all()
        keys = [r[0] for r in rows if r[0].startswith('v:')]
        assert sorted(keys) == sorted(set(keys))
        assert 'v:stalls:start' in keys and 'v:stalls:0:funded' in keys and 'v:stalls:0:end' in keys and 'v:stalls:tier1' in keys
    run(scenario())


def test_pukh_energy_shortens_work_by_two_hours_each_up_to_one_day():
    async def scenario():
        w = World()
        await w.player('a', coins=2_000_000, items={'berry_charge': 40, 'honey_charge': 40})
        await fund_stage(w, 'a')
        # stage 0 lasts one day: energy cannot make it instant
        await w.cmd('a', 'build_speedup', {'project': 'stalls', 'item': 'berry_charge', 'qty': 3})
        row = await w.project('stalls')
        assert row['speedup'] == 3 * 7200
        await w.cmd('a', 'build_speedup', {'project': 'stalls', 'item': 'honey_charge', 'qty': 40})
        row = await w.project('stalls')
        assert row['speedup'] == DAY                                                          # 12 drinks, not more
        farm = await w.farm('a')
        assert farm['inventory']['berry_charge'] + farm['inventory']['honey_charge'] == 80 - 12
        with pytest.raises(FarmError) as error:
            await w.cmd('a', 'build_speedup', {'project': 'stalls', 'item': 'berry_charge', 'qty': 1})
        assert error.value.code == 'pukh_tired'
        w.now[0] += cn.MIN_WORK
        assert (await w.build('a'))['projects'][0]['status'] == 'collecting'                  # the minimum work time passed
        with pytest.raises(FarmError) as error:
            await w.cmd('a', 'build_speedup', {'project': 'stalls', 'item': 'berry_charge', 'qty': 1})
        assert error.value.code == 'not_working'
        with pytest.raises(FarmError):
            await w.cmd('a', 'build_speedup', {'project': 'stalls', 'item': 'wood', 'qty': 1})
    run(scenario())


def test_a_fulfilled_fund_goal_speeds_the_current_stage_up_by_a_day_once():
    async def scenario():
        w = World()
        await w.player('a', coins=2_000_000)
        await fund_stage(w, 'a')
        w.now[0] += DAY
        await w.build('a')
        await fund_stage(w, 'a')                                                              # the two-day frame
        start = w.now[0]
        w.now[0] += DAY // 2
        async with w.db.transaction() as unit:                                               # the village reached the season goal
            await unit.village_add(economy.season_of(w.now[0]), 10 ** 9, w.now[0])
        build = await w.build('a')
        row = await w.project('stalls')
        assert row['fund_speed'] == DAY and build['projects'][0]['work_until'] == start + DAY
        await w.build('a')
        assert (await w.project('stalls'))['fund_speed'] == DAY                              # applied once
        w.now[0] = start + DAY
        assert (await w.build('a'))['projects'][0]['stage'] == 2                             # a day earlier than 2 days
    run(scenario())


def test_tiers_use_the_players_own_income_and_unlock_perks_when_the_building_is_open():
    async def scenario():
        w = World()
        await w.player('small', lv=8, coins=200_000, items={'wood': 5_000})
        await w.player('big', lv=12, coins=2_000_000)
        ref = income_ref(8)
        # 10% of own income -> helper
        need_ = (await w.build('small'))['projects'][0]['need']
        coins = min(need_['coins'], ref // 10)
        await w.cmd('small', 'build_contribute', {'project': 'stalls', 'items': {}, 'coins': coins})
        mine = (await w.build('small'))['projects'][0]['mine']
        assert mine['tier'] == 1 and mine['value'] == coins and mine['share_bp'] == coins * 10000 // ref
        # finishing all stages by the big player; the small one keeps helper
        for _ in range(3):
            await fund_stage(w, 'big')
            w.now[0] += 2 * DAY
            await w.build('big')
        farm = await w.farm('small')
        await w.view('small')
        farm = await w.farm('small')
        assert farm['village_bonus']['open'] == ['stalls'] and farm['village_bonus']['tiers']['stalls'] == 1
        assert cn.perk(farm, 'stalls', 1) and not cn.perk(farm, 'stalls', 2)
        assert cn.merchant_price(farm, 100) == 90 and cn.merchant_extra(farm, 0, w.now[0]) == 0
        big = await w.farm('big')
        assert cn.merchant_extra(big, 3, w.now[0]) == 1 and cn.merchant_price(big, 100) == 90   # tier 3 includes the lower ones
        build = await w.build('big')
        assert build['honor']['stalls'] == [big['name']]
    run(scenario())


def test_magpie_discount_and_extra_limit_follow_the_perks():
    f = upgrade_state(new_farm(str(uuid4()), 'x', T0))
    f['village_bonus'] = dict(tiers={'stalls': 2}, open=['stalls'])
    assert cn.merchant_price(f, 200) == 180 and cn.merchant_extra(f, 2, T0) == 1
    rec = economy.record(f, economy.season_of(T0), 12)
    rec['tiers'] = 2
    assert cn.merchant_extra(f, 0, T0) == 2 and cn.merchant_extra(f, 1, T0) == 1
    f['village_bonus'] = dict(tiers={'stalls': 3}, open=[])
    assert cn.merchant_price(f, 200) == 200                                                  # the building is not open


def test_replayed_command_id_is_not_applied_twice():
    async def scenario():
        w = World()
        await w.player('a', items={'wood': 500})
        data = {'project': 'stalls', 'items': {'wood': 10}, 'coins': 100}
        await w.cmd('a', 'build_contribute', data, command_id='contribute-replay-1')
        first = await w.farm('a')
        again = await w.cmd('a', 'build_contribute', data, command_id='contribute-replay-1')
        assert again['command_id'] == 'contribute-replay-1' and (await w.farm('a'))['coins'] == first['coins']
        assert (await w.project('stalls'))['got']['wood'] == 10
        with pytest.raises(FarmError) as error:
            await w.cmd('a', 'build_contribute', {**data, 'coins': 99}, command_id='contribute-replay-1')
        assert error.value.code == 'key_reused'
    run(scenario())


# ----------------------------------------------------------------------------------------------------------- stalls
async def open_rows(w):
    await w.cmd('a', 'sell', {'item': 'wheat', 'qty': 1})
    await w.force('stalls', status='done', stage=2, opened_at=w.now[0])
    await w.view('a')


def test_own_stall_listing_rules_buy_commission_and_daily_limit():
    async def scenario():
        w = World()
        await w.player('a', items={'bread': 100, 'egg': 100})
        await w.player('b', coins=100_000)
        await open_rows(w)
        await w.view('b')
        bread = ITEMS['bread']['price']
        with pytest.raises(FarmError) as e:
            await w.cmd('a', 'stall_list', {'item': 'bread', 'qty': 2, 'unit_price': bread - 1})
        assert e.value.code == 'invalid_price'
        with pytest.raises(FarmError) as e:
            await w.cmd('a', 'stall_list', {'item': 'bread', 'qty': 2, 'unit_price': bread * 3 // 2 + 1})
        assert e.value.code == 'invalid_price'
        coins0 = (await w.farm('a'))['coins']
        for i in range(3):
            await w.cmd('a', 'stall_list', {'item': 'bread', 'qty': 2, 'unit_price': bread * 3 // 2})
        a = await w.farm('a')
        assert coins0 - a['coins'] == cn.rent_for(a) and a['inventory']['bread'] == 94     # rent once, three lots
        with pytest.raises(FarmError) as e:
            await w.cmd('a', 'stall_list', {'item': 'bread', 'qty': 1, 'unit_price': bread})
        assert e.value.code == 'stall_full'
        rows = (await w.build('b'))['rows']
        assert len(rows['lots']) == 3 and rows['own'] == [] and rows['lots'][0]['seller'] == a['name']
        lots = rows['lots']
        coins_b = (await w.farm('b'))['coins']
        await w.cmd('b', 'stall_buy', {'lot': lots[0]['id']}, target=w.players['a'].fid)
        cost = 2 * (bread * 3 // 2)
        fee = max(1, -(-cost * 5 // 100))
        assert coins_b - (await w.farm('b'))['coins'] == cost and (await w.farm('a'))['coins'] == a['coins'] + cost - fee
        assert (await w.farm('b'))['inventory']['bread'] >= 2
        with pytest.raises(FarmError) as e:
            await w.cmd('b', 'stall_buy', {'lot': lots[0]['id']}, target=w.players['a'].fid)
        assert e.value.code == 'lot_gone'
        with pytest.raises(FarmError) as e:
            await w.cmd('a', 'stall_buy', {'lot': lots[1]['id']}, target=w.players['a'].fid)
        assert e.value.code == 'own_farm'
        # a lot listed under another farm's name is stale
        with pytest.raises(FarmError) as e:
            await w.cmd('b', 'stall_buy', {'lot': lots[1]['id']}, target=w.players['b'].fid)
        assert e.value.code in {'own_farm', 'stale_lot'}
        # three purchases per buyer and seller per day
        await w.cmd('a', 'stall_list', {'item': 'bread', 'qty': 1, 'unit_price': bread})
        for lot in (await w.build('b'))['rows']['lots'][:2]:
            await w.cmd('b', 'stall_buy', {'lot': lot['id']}, target=w.players['a'].fid)
        left = (await w.build('b'))['rows']['lots']
        assert left and left[0]['buys_today'] == 3
        with pytest.raises(FarmError) as e:
            await w.cmd('b', 'stall_buy', {'lot': left[0]['id']}, target=w.players['a'].fid)
        assert e.value.code == 'buy_limit'
        w.now[0] += DAY
        await w.cmd('b', 'stall_buy', {'lot': left[0]['id']}, target=w.players['a'].fid)
    run(scenario())


def test_stall_access_bound_items_cancel_and_starter_credit():
    async def scenario():
        w = World()
        await w.player('a', lv=9, items={'bread': 10})
        await w.player('b', lv=12, coins=300, credit=300)
        await w.cmd('a', 'sell', {'item': 'wheat', 'qty': 1})
        with pytest.raises(FarmError) as e:
            await w.cmd('a', 'stall_list', {'item': 'bread', 'qty': 1, 'unit_price': 29})
        assert e.value.code == 'rows_closed'
        await w.force('stalls', status='done', stage=2, opened_at=w.now[0])
        await w.view('a')
        with pytest.raises(FarmError) as e:
            await w.cmd('a', 'stall_list', {'item': 'bread', 'qty': 1, 'unit_price': 29})
        assert e.value.code == 'stall_locked'                                                # level 9, no «мастер»
        await w.view('b')
        bound = next(k for k, v in ITEMS.items() if v.get('bound'))
        await w.grant('b', {bound: 1, 'bread': 5})
        with pytest.raises(FarmError) as e:
            await w.cmd('b', 'stall_list', {'item': bound, 'qty': 1, 'unit_price': ITEMS[bound]['price']})
        assert e.value.code == 'bound_item'
        with pytest.raises(FarmError) as e:
            await w.cmd('b', 'stall_list', {'item': 'bread', 'qty': 1, 'unit_price': 29})
        assert e.value.code == 'earned_coins'                                                # the rent is paid from earned coins only
        await w.grant('b', coins=1000)
        await w.cmd('b', 'stall_list', {'item': 'bread', 'qty': 5, 'unit_price': 29})
        lot = (await w.build('b'))['rows']['own'][0]
        before = (await w.farm('b'))['inventory']['bread']
        await w.cmd('b', 'stall_cancel', {'lot': lot['id']})
        assert (await w.farm('b'))['inventory']['bread'] == before + 5
        with pytest.raises(FarmError) as e:
            await w.cmd('b', 'stall_cancel', {'lot': lot['id']})
        assert e.value.code == 'lot_gone'
    run(scenario())


def test_rent_renews_only_after_a_sale_otherwise_the_stall_closes_and_goods_return():
    async def scenario():
        w = World()
        await w.player('a', items={'bread': 20})
        await w.player('b', coins=100_000)
        await open_rows(w)
        await w.view('b')
        await w.cmd('a', 'stall_list', {'item': 'bread', 'qty': 4, 'unit_price': 29})
        await w.cmd('a', 'stall_list', {'item': 'bread', 'qty': 4, 'unit_price': 29})
        lot = (await w.build('b'))['rows']['lots'][0]
        await w.cmd('b', 'stall_buy', {'lot': lot['id']}, target=w.players['a'].fid)
        w.now[0] += cn.RENT_PERIOD + 10
        coins = (await w.farm('a'))['coins']
        left = (await w.build('b'))['rows']['lots']
        assert left == []                                                                    # expired: hidden for buyers, nobody locks the seller
        rows = (await w.build('a'))['rows']                                                  # the seller's own visit renews the rent
        a = await w.farm('a')
        assert a['coins'] == coins - cn.rent_for(a) and len(rows['own']) == 1
        w.now[0] += cn.RENT_PERIOD + 10                                                      # a week with no sales
        bread = a['inventory']['bread']
        rows = (await w.build('a'))['rows']
        a = await w.farm('a')
        assert rows['own'] == [] and a['inventory']['bread'] == bread + 4
        assert (await w.build('b'))['rows']['lots'] == []
    run(scenario())


def test_account_merge_adds_contributions_and_closes_open_lots():
    async def scenario():
        w = World()
        await w.player('a', items={'bread': 20})
        await w.player('s', items={'bread': 20, 'wood': 1000})
        await w.cmd('a', 'build_contribute', {'project': 'stalls', 'items': {}, 'coins': 100})
        await w.cmd('s', 'build_contribute', {'project': 'stalls', 'items': {'wood': 10}, 'coins': 200})
        await w.force('stalls', status='done', stage=2, opened_at=w.now[0])
        await w.view('s')
        await w.cmd('s', 'stall_list', {'item': 'bread', 'qty': 3, 'unit_price': 29})
        mine, theirs = w.players['a'], w.players['s']
        async with w.db.transaction() as unit:
            c = unit.t['contribs']
            rows = {r['account_id']: r for r in (await unit.execute(sa.select(c))).mappings().all()}
            await cn.merge_prepare(unit, mine.aid, theirs.aid, w.now[0])
            rows2 = (await unit.execute(sa.select(c))).mappings().all()
            assert len(rows2) == 1 and rows2[0]['account_id'] == mine.aid
            assert rows2[0]['value'] == rows[mine.aid]['value'] + rows[theirs.aid]['value']
            assert rows2[0]['share_bp'] == rows[mine.aid]['share_bp'] + rows[theirs.aid]['share_bp']
            lots = unit.t['lots']
            assert (await unit.execute(sa.select(sa.func.count()).select_from(lots).where(lots.c.status == 'open'))).scalar_one() == 0
            assert (await unit.by_account(theirs.aid))['inventory']['bread'] == 20          # returned to the secondary farm
    run(scenario())


def test_old_fake_units_without_the_tables_are_left_alone():
    async def scenario():
        class Bare:
            pass
        assert not cn.available(Bare())
        assert await cn.projection(Bare(), {}, 'x', T0) is None
        await cn.tick_account(Bare(), {}, 'x', T0)
    run(scenario())


def test_metadata_is_idempotent_and_merge_policy_has_no_gaps():
    from application.account_merge import policy_gaps
    from qw_farm.integration import register_models
    register_models()
    register_models()
    missing, extra = policy_gaps()
    assert not [m for m in missing if m[0].startswith('farm_village')]
    assert ('farm_village_contribs', 'account_id') not in extra and ('farm_village_stall_lots', 'seller_account') not in extra


# ----------------------------------------------------------------------------------------------------------- PostgreSQL
from tests.test_farm_platform import (  # noqa: E402
    FARM_HEADERS, accepted, command, environment, farm_pg_url, player, raw_farm, view)
from qw_farm.persistence import Unit  # noqa: E402


async def pg_ready(env, p, *, coins=500_000, lv=12, items=None):
    async with env.db.transaction() as session:
        unit = Unit(session, env.schema)
        state = await unit.by_account(p.account_id)
        before = deepcopy(state)
        state.update(coins=coins, xp=LEVELS[lv - 1])
        state['inventory'].update(items or {})
        progression.touch(state, env.now[0])
        validate_state(state)
        await unit.save(state)
        await unit.record(p.account_id, 'fixture-build', 'fixture', before, state, env.now[0])


async def pg_project(env, pid):
    async with env.db.transaction() as session:
        unit = Unit(session, env.schema)
        t = unit.t['projects']
        return dict((await unit.execute(sa.select(t).where(t.c.id == pid))).mappings().first())


def test_postgres_two_players_close_the_same_stage_at_once(farm_pg_url):
    async def run_():
        async with environment(farm_pg_url) as env:
            async with player(env) as a, player(env, 'telegram', 981020000091) as b:
                for p in (a, b):
                    await pg_ready(env, p, items={'wood': 5000})
                await view(a)
                need_ = (await pg_project(env, 'stalls'))['need']
                data = {'project': 'stalls', 'items': {'wood': need_['wood']}, 'coins': need_['coins']}
                first, second = await asyncio.gather(command(a, 'build_contribute', data), command(b, 'build_contribute', data))
                codes = sorted(r.status_code for r in (first, second))
                assert codes == [200, 409], [r.text for r in (first, second)]
                loser, lost = (a, first) if first.status_code == 409 else (b, second)
                assert lost.json()['code'] == 'stage_closed'
                stored = await raw_farm(env, loser)
                assert stored['inventory']['wood'] >= 5000 and stored['coins'] == 500_000               # nothing was taken
                row = await pg_project(env, 'stalls')
                assert row['status'] == 'working' and row['got'] == need_ and row['version'] == 2      # one start + one funding
                async with env.db.transaction() as session:
                    t = Unit(session, env.schema).t['contribs']
                    assert (await session.execute(sa.select(sa.func.count()).select_from(t))).scalar_one() == 1
    asyncio.run(run_())


def test_postgres_partial_contributions_in_parallel_are_never_lost_or_over_accepted(farm_pg_url):
    async def run_():
        async with environment(farm_pg_url) as env:
            async with player(env) as a, player(env, 'telegram', 981020000092) as b:
                for p in (a, b):
                    await pg_ready(env, p, items={'wood': 5000})
                await view(a)
                need_ = (await pg_project(env, 'stalls'))['need']
                half = {'project': 'stalls', 'items': {'wood': need_['wood'] * 3 // 4}, 'coins': 0}
                results = await asyncio.gather(command(a, 'build_contribute', half), command(b, 'build_contribute', half))
                assert [r.status_code for r in results] == [200, 200]
                row = await pg_project(env, 'stalls')
                assert row['got']['wood'] == need_['wood']                                              # clipped, never above the need
                taken = 0
                for p in (a, b):
                    taken += 5000 - (await raw_farm(env, p))['inventory']['wood']
                assert taken == need_['wood']
    asyncio.run(run_())


def test_postgres_replay_lazy_transition_and_two_buyers_for_one_lot(farm_pg_url):
    async def run_():
        async with environment(farm_pg_url) as env:
            async with player(env) as a, player(env, 'telegram', 981020000093) as b, player(env, 'telegram', 981020000094) as c:
                for p in (a, b, c):
                    await pg_ready(env, p, items={'bread': 50, 'wood': 5000})
                await view(a)
                need_ = (await pg_project(env, 'stalls'))['need']
                key_ = str(uuid4())
                data = {'project': 'stalls', 'items': {'wood': need_['wood']}, 'coins': need_['coins']}
                r1 = await accepted(a, 'build_contribute', data, key=key_)
                r2 = await accepted(a, 'build_contribute', data, key=key_)                              # replay
                assert r1['command_id'] == r2['command_id']
                assert (await raw_farm(env, a))['inventory']['wood'] == 5000 - need_['wood']
                async with env.db.transaction() as session:                                              # the residents finish now
                    unit = Unit(session, env.schema)
                    t = unit.t['projects']
                    await unit.execute(t.update().where(t.c.id == 'stalls').values(work_until=env.now[0] - 1))
                await view(a)
                assert (await pg_project(env, 'stalls'))['stage'] == 1
                version = (await pg_project(env, 'stalls'))['version']
                await view(b)
                await view(a)
                assert (await pg_project(env, 'stalls'))['version'] == version                          # lazy and idempotent
                async with env.db.transaction() as session:                                              # open the rows
                    unit = Unit(session, env.schema)
                    t = unit.t['projects']
                    await unit.execute(t.update().where(t.c.id == 'stalls').values(status='done', stage=2, opened_at=env.now[0]))
                await view(a)
                await view(b)
                await accepted(a, 'stall_list', {'item': 'bread', 'qty': 2, 'unit_price': 29})
                lots = (await view(b))['village_build']['rows']['lots']
                assert len(lots) == 1
                buy = {'lot': lots[0]['id']}
                one, two = await asyncio.gather(command(b, 'stall_buy', buy, target=a.farm_id), command(c, 'stall_buy', buy, target=a.farm_id))
                assert sorted(r.status_code for r in (one, two)) == [200, 404], [r.text for r in (one, two)]
                bread = [(await raw_farm(env, p))['inventory']['bread'] for p in (b, c)]
                assert sorted(bread) == [50, 52]
    asyncio.run(run_())


def test_postgres_migration_matches_metadata_and_refuses_to_drop_history(farm_pg_url, monkeypatch):
    async def run_():
        from sqlalchemy import inspect
        from tests.local_database import isolated_database
        from qw_farm.integration import register_models
        schema = register_models()
        async with isolated_database(farm_pg_url) as (db, _):
            async with db.engine.begin() as connection:
                def roundtrip(sync):
                    tables = ('farm_village_stall_lots', 'farm_village_contribs', 'farm_village_projects')
                    metadata_columns = {n: {c.name for c in sa.Table(n, sa.MetaData(), autoload_with=sync).c} for n in tables}
                    for n in tables:
                        sync.execute(sa.text(f'DROP TABLE {n}'))
                    import importlib.util
                    from pathlib import Path
                    from alembic.migration import MigrationContext
                    from alembic.operations import Operations
                    path = Path(__file__).resolve().parents[1] / 'alembic' / 'versions' / '20261023_village_build.py'
                    spec = importlib.util.spec_from_file_location('village_build_migration', path)
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    assert module.down_revision == '20261023_0039'
                    with Operations.context(MigrationContext.configure(sync)):
                        module.upgrade()
                    for n in tables:
                        assert {c['name'] for c in inspect(sync).get_columns(n)} == metadata_columns[n], n
                    sync.execute(sa.text("INSERT INTO farm_village_projects (id,status,stage,need,got) VALUES ('x','soon',0,'{}','{}')"))
                await connection.run_sync(roundtrip)
    asyncio.run(run_())
