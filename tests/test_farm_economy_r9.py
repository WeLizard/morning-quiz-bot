"""Farm r9 stage 14: upkeep, the two-part village fund (personal scale + shared counter) and paid decor."""
import asyncio
from copy import deepcopy
from uuid import uuid4

import pytest

from qw_farm import catalog, economy, market, progression
from qw_farm.catalog import (BUILDINGS, DECOR_SHOP, LEVELS, PLOT_UPKEEP, REWARD_DECOR, CROPS, income_ref, validate,
                             validate_economy)
from qw_farm.domain import FarmError, apply, new_farm, project, validate_state
from qw_farm.expansion import settle, upgrade_state
from qw_farm.service import FarmService, Principal

T0 = 1_800_000_000
DAY = 86400
W = catalog.ITEMS['wheat']['price']          # coins for one sold wheat


def day_start(day):
    return day * DAY - market.TZ_OFFSET


D1 = day_start(20_000)          # a Moscow midnight; every test works relative to it


def farm(lv=12, coins=100_000, credit=0, size=12, plots=10):
    f = upgrade_state(new_farm(str(uuid4()), 'Eco', D1 + 3600))
    f.update(xp=LEVELS[lv - 1], coins=coins, starter_credit=credit, size=size)
    f['objects'] = [o for o in f['objects'] if o['type'] != 'plot']
    for i in range(plots):
        f['objects'].append(dict(id=f'p{i}', type='plot', x=i % size, y=6 + i // size, w=1, h=1, revision=0, crop=None))
    return f


n = [0]


def cmd(f, kind, data=None, at=D1 + 3600):
    n[0] += 1
    return apply(f, f, kind, data if data is not None else {}, at, f'cmd{n[0]}')


# ---------------------------------------------------------------------------------------------- catalog
def test_catalog_economy_tables():
    validate()
    assert validate_economy() == dict(decor_shop=15, reward_decor=4)
    assert [income_ref(lv) for lv in (1, 4, 5, 10, 15, 20, 25, 30, 45, 50)] == [1100, 1100, 7000, 13000, 19000, 30000, 36000, 40000, 42000, 42000]
    assert [d['tier'] for d in DECOR_SHOP] == sorted(d['tier'] for d in DECOR_SHOP)
    assert {BUILDINGS[d['id']]['level'] for d in DECOR_SHOP} == {8, 15, 25, 35, 45}
    assert all(BUILDINGS[d['id']]['decor'] for d in DECOR_SHOP + REWARD_DECOR)
    assert sum(1 for d in DECOR_SHOP if d['tier'] == 5) == 3          # trophies of the last tier
    assert {k: v for k, v in PLOT_UPKEEP.items() if k <= 20} == {8: 0, 10: 0, 12: 2, 14: 5, 16: 10, 18: 18, 20: 30}
    assert set(PLOT_UPKEEP) == set(range(8, 61, 2))   # the tail past 20x20 is covered (docs/tasks/FARM_LAND_PROGRESSION.md)


# ---------------------------------------------------------------------------------------------- upkeep
def test_upkeep_formula_counts_beds_buildings_by_level_and_ignores_decor():
    f = farm(size=16, plots=10)
    f['objects'] += [dict(id='k', type='kitchen', x=0, y=8, w=2, h=2, revision=0, level=1, jobs=[], animal=None, animal_job=None),
                     dict(id='m2', type='mill', x=3, y=8, w=2, h=2, revision=0, level=2, jobs=[], animal=None, animal_job=None),
                     dict(id='b', type='bench', x=7, y=8, w=1, h=1, revision=0, level=1, jobs=[], animal=None, animal_job=None)]
    # beds 10 * 10 + kitchen ceil(240/100)=3 + mill (new_farm's own, level 1) 1 + level-2 mill 2 + coop 1; house, barn and decor: 0
    assert economy.base_upkeep(f) == 100 + 3 + 1 + 2 + 1
    assert economy.upkeep(f, D1) == economy.base_upkeep(f)       # no discount without the tier


def test_one_bill_per_active_moscow_day_and_a_free_first_day():
    f = farm(size=16, plots=10)                       # U = 100 + 1 + 1 = 102
    assert economy.base_upkeep(f) == 102
    coins = f['coins']
    cmd(f, 'sell', {'item': 'wheat', 'qty': 1}, D1 + 3600)
    assert f['economy']['billed_day'] == market.moscow_day(D1) and f['coins'] == coins + W   # grace day: nothing charged
    cmd(f, 'sell', {'item': 'wheat', 'qty': 1}, D1 + 7200)
    assert f['coins'] == coins + 2 * W
    cmd(f, 'sell', {'item': 'wheat', 'qty': 1}, D1 + DAY + 100)            # first command of the next day: one bill
    assert f['coins'] == coins + 3 * W - 102 and f['economy']['stats']['upkeep_paid'] == 102
    for k in range(3):                                                  # more commands the same day: no second bill
        f['inventory']['wheat'] = 1
        cmd(f, 'sell', {'item': 'wheat', 'qty': 1}, D1 + DAY + 200 + k)
    assert f['coins'] == coins + 3 * W - 102 + 3 * W and f['economy']['stats']['upkeep_paid'] == 102
    f['inventory']['wheat'] = 1
    cmd(f, 'sell', {'item': 'wheat', 'qty': 1}, D1 + 5 * DAY)               # idle days are not billed one by one
    assert f['economy']['stats']['upkeep_paid'] == 204


def test_no_bill_below_l10_and_for_rescue_pay_and_failed_commands():
    low = farm(lv=9, size=16, plots=10)
    low['economy']['billed_day'] = 5
    coins = low['coins']
    cmd(low, 'sell', {'item': 'wheat', 'qty': 1}, D1 + DAY)
    assert low['coins'] == coins + W and low['economy']['billed_day'] == 5
    f = farm(size=16, plots=10)
    f['economy']['billed_day'] = market.moscow_day(D1) - 1
    before = deepcopy(f)
    with pytest.raises(FarmError):
        cmd(f, 'sell', {'item': 'wheat', 'qty': 999}, D1)                  # a failed command is never billed
    assert f['economy'] == before['economy'] and f['coins'] == before['coins']
    poor = farm(size=16, plots=0, coins=1, credit=0)
    poor['inventory'] = {}
    poor['objects'] = []
    poor['economy']['billed_day'] = market.moscow_day(D1) - 1
    cmd(poor, 'rescue', {}, D1)
    assert poor['coins'] == 3 and poor['economy']['billed_day'] == market.moscow_day(D1) - 1     # rescue is not billed


def test_bill_never_touches_the_starter_credit_and_leaves_a_non_accumulating_debt():
    f = farm(size=16, plots=10, coins=500, credit=480)
    f['economy']['billed_day'] = market.moscow_day(D1) - 1
    cmd(f, 'sell', {'item': 'wheat', 'qty': 1}, D1)
    # earned coins were 20 (+W from the sale) -> the bill of 102 takes all of them, the rest is debt; the credit is intact
    assert f['coins'] == 480 and f['starter_credit'] == 480
    assert f['economy']['debt'] == 102 - (20 + W) and f['economy']['stats']['upkeep_billed'] == 102
    validate_state(f)
    f['economy']['billed_day'] -= 0
    f['inventory']['wheat'] = 1
    cmd(f, 'sell', {'item': 'wheat', 'qty': 1}, D1 + DAY)
    # W earned coins pay a part of the next bill; the debt is REPLACED by the new shortfall, it never piles up
    assert f['coins'] == 480 and f['economy']['debt'] == 102 - W
    validate_state(f)


@pytest.mark.parametrize('coins,credit', [(0, 0), (1, 0), (101, 100), (102, 0), (103, 0), (10 ** 6, 250)])
def test_balance_never_goes_negative_whatever_the_bill(coins, credit):
    f = farm(size=16, plots=10, coins=coins, credit=credit)
    f['economy']['billed_day'] = market.moscow_day(D1) - 1
    paid = economy.bill(f, D1)
    assert paid == min(102, max(0, coins - credit)) and f['coins'] == coins - paid and f['starter_credit'] == credit
    assert f['economy']['debt'] == 102 - paid
    validate_state(f)


def test_debt_slows_only_new_timers_by_one_fifth_and_clears_when_paid():
    f = farm(size=16, plots=10, coins=50_000)
    wheat = CROPS['wheat']
    cmd(f, 'plant', {'object': 'p0', 'crop': 'wheat', 'revision': 0}, D1 + 100)
    running = deepcopy({o['id']: o for o in f['objects']}['p0']['crop'])
    assert running['ready_at'] == D1 + 100 + wheat['seconds']
    f['economy']['debt'] = 40                                            # an open debt
    cmd(f, 'plant', {'object': 'p1', 'crop': 'wheat', 'revision': 0}, D1 + 200)
    plots = {o['id']: o for o in f['objects']}
    assert plots['p0']['crop'] == running                                # the running timer is untouched
    assert plots['p1']['crop']['ready_at'] == D1 + 200 + -(-wheat['seconds'] * 6 // 5)
    cmd(f, 'pay_upkeep', {}, D1 + 300)
    assert f['economy']['debt'] == 0
    cmd(f, 'plant', {'object': 'p2', 'crop': 'wheat', 'revision': 0}, D1 + 400)
    assert {o['id']: o for o in f['objects']}['p2']['crop']['ready_at'] == D1 + 400 + wheat['seconds']
    assert plots['p1']['crop']['ready_at'] == D1 + 200 + -(-wheat['seconds'] * 6 // 5)   # still the slow one


def test_debt_also_slows_new_recipes_animals_and_trips():
    f = farm(size=16, plots=2, coins=50_000, lv=14)
    f['economy']['debt'] = 1
    mill = next(o for o in f['objects'] if o['type'] == 'mill')
    f['inventory'].update(wheat=10, feed=5)
    cmd(f, 'queue', {'object': mill['id'], 'recipe': 'flour'}, D1 + 100)
    job = mill['jobs'][0]
    assert job['seconds'] == -(-catalog.RECIPES['flour']['seconds'] * 6 // 5)
    f['economy']['debt'] = 0
    cmd(f, 'queue', {'object': mill['id'], 'recipe': 'flour'}, D1 + 100)
    assert mill['jobs'][1]['seconds'] == catalog.RECIPES['flour']['seconds']


def test_pay_upkeep_errors_and_partial_payment():
    f = farm(size=16, plots=10, coins=300, credit=0)
    with pytest.raises(FarmError) as e:
        cmd(f, 'pay_upkeep', {})
    assert e.value.code == 'no_debt'
    f['economy']['debt'] = 500
    cmd(f, 'pay_upkeep', {})
    assert f['coins'] == 0 and f['economy']['debt'] == 200               # partial: all earned coins
    with pytest.raises(FarmError) as e:
        cmd(f, 'pay_upkeep', {})
    assert e.value.code == 'insufficient_coins'
    f['coins'], f['starter_credit'] = 100, 100
    with pytest.raises(FarmError) as e:
        cmd(f, 'pay_upkeep', {})
    assert e.value.code == 'insufficient_coins'                           # the starter credit cannot pay upkeep
    validate_state(f)


def test_items_never_disappear_when_the_bill_is_unpaid():
    f = farm(size=16, plots=10, coins=0)
    f['inventory'] = {'wheat': 7, 'flour': 3}
    f['economy']['billed_day'] = market.moscow_day(D1) - 1
    economy.bill(f, D1)
    assert f['inventory'] == {'wheat': 7, 'flour': 3} and f['economy']['debt'] == 102


# ---------------------------------------------------------------------------------------------- fund: personal scale
def test_personal_scale_tiers_rewards_and_season_aligned_record():
    f = farm(lv=12, coins=300_000)
    ref = income_ref(12)
    assert ref == 13000 and economy.thresholds(ref) == [6500, 19500, 39000, 65000, 104000]
    cmd(f, 'fund_contribute', {'coins': 6000, 'items': {}})
    rec = f['economy']['seasons'][str(economy.season_of(D1 + 3600))]
    assert rec['personal'] == 6000 and rec['tiers'] == 0 and rec['ref'] == ref and f['economy']['unlocked'] == []
    cmd(f, 'fund_contribute', {'coins': 500, 'items': {}})
    assert rec['tiers'] == 1 and f['economy']['unlocked'] == ['fd_garland']
    cmd(f, 'fund_contribute', {'coins': 13000, 'items': {}})
    # FARM_VILLAGE_CONSTRUCTION.md 4.2: tier 2 is «Покупатель Сороки» (no more 3-day feast), tier 4 is early fair access
    assert rec['tiers'] == 2 and f['economy']['feast_until'] == 0
    assert economy.perk(f, 'magpie', D1 + 3600) and not economy.perk(f, 'early', D1 + 3600)
    cmd(f, 'fund_contribute', {'coins': 19500, 'items': {}})
    assert rec['tiers'] == 3 and economy.discount_active(f, D1 + 3600)
    assert economy.upkeep(f, D1) == economy.base_upkeep(f) * 75 // 100
    assert not economy.discount_active(f, D1 + 28 * DAY * 2)                    # a later season has no discount
    cmd(f, 'fund_contribute', {'coins': 26000, 'items': {}})
    assert rec['tiers'] == 4 and 'fd_pinwheel' in f['economy']['unlocked'] and economy.perk(f, 'early', D1 + 3600)
    cmd(f, 'fund_contribute', {'coins': 39000, 'items': {}})
    assert rec['tiers'] == 5 and 'fd_cup' in f['economy']['unlocked'] and f['economy']['titles'] == ['Староста деревни']
    assert economy.perk(f, 'honor', D1 + 3600) and economy.perk(f, 'honor', D1 + 3600 + 28 * DAY)    # the season after
    assert not economy.perk(f, 'honor', D1 + 3600 + 56 * DAY)
    cmd(f, 'fund_contribute', {'coins': 10, 'items': {}})
    assert rec['tiers'] == 5 and f['economy']['stats']['fund_village'] == rec['personal'] == 104010   # tiers are paid once
    assert f['coins'] == 300_000 - 104010
    validate_state(f)


def test_the_scale_ref_is_frozen_at_the_first_contribution_of_the_season():
    f = farm(lv=12, coins=10 ** 6)
    cmd(f, 'fund_contribute', {'coins': 100, 'items': {}})
    f['xp'] = LEVELS[29]
    cmd(f, 'fund_contribute', {'coins': 100, 'items': {}})
    rec = next(iter(f['economy']['seasons'].values()))
    assert rec['ref'] == 13000 and rec['level'] == 12


def test_a_new_season_starts_a_fresh_scale_and_old_records_are_pruned():
    f = farm(lv=12, coins=10 ** 6)
    for k in range(4):
        cmd(f, 'fund_contribute', {'coins': 7000, 'items': {}}, D1 + k * 28 * DAY + 3600)
    assert len(f['economy']['seasons']) == economy.KEEP_SEASONS
    last = f['economy']['seasons'][str(economy.season_of(D1 + 3 * 28 * DAY + 3600))]
    assert last['personal'] == 7000 and last['tiers'] == 1
    assert f['economy']['unlocked'] == ['fd_garland']                           # a decor type is unlocked once
    validate_state(f)


def test_goods_count_at_price_times_1_25_and_only_earned_coins_are_accepted():
    f = farm(lv=12, coins=10_000, credit=9_500)
    f['inventory'] = {'wheat': 40, 'flour': 3}
    cmd(f, 'fund_contribute', {'coins': 0, 'items': {'wheat': 40, 'flour': 3}})
    wheat, flour = catalog.ITEMS['wheat']['price'], catalog.ITEMS['flour']['price']
    expected = wheat * 40 * 125 // 100 + flour * 3 * 125 // 100
    assert f['economy']['stats']['fund_goods'] == expected == next(iter(f['economy']['seasons'].values()))['personal']
    assert f['inventory'].get('wheat', 0) == 0 and f['coins'] == 10_000
    with pytest.raises(FarmError) as e:
        cmd(f, 'fund_contribute', {'coins': 501, 'items': {}})
    assert e.value.code == 'earned_coins'
    cmd(f, 'fund_contribute', {'coins': 500, 'items': {}})
    assert f['coins'] == 9_500 == f['starter_credit']
    validate_state(f)


def test_fund_contribution_validation():
    f = farm(lv=7, coins=10_000)
    with pytest.raises(FarmError) as e:
        cmd(f, 'fund_contribute', {'coins': 100, 'items': {}})
    assert e.value.code == 'locked'
    f = farm(lv=8, coins=10_000)
    for data, code in [({'coins': 0, 'items': {}}, 'invalid_command'), ({'coins': -5, 'items': {}}, 'invalid_command'),
                       ({'coins': 1.5, 'items': {}}, 'invalid_command'), ({'coins': 0, 'items': {'wheat': 99}}, 'missing_goods'),
                       ({'coins': 0, 'items': {'nonsense': 1}}, 'unknown_item'), ({'coins': True, 'items': {}}, 'invalid_command')]:
        before = deepcopy(f)
        with pytest.raises(FarmError) as e:
            cmd(f, 'fund_contribute', data)
        assert e.value.code == code, data
        assert f == before
    with pytest.raises(FarmError):
        cmd(f, 'fund_contribute', {'coins': 5})                                   # exact schema
    cmd(f, 'fund_contribute', {'coins': 1, 'items': {}})


def test_feast_gives_ten_percent_more_xp_to_owner_commands_only_and_is_not_stacked():
    f = farm(lv=12)
    f['economy']['feast_until'] = D1 + 7200
    xp0 = f['xp']
    got = progression.grant_xp(f, 100, 'order', D1 + 3600, True)         # 100 + 100 (morning dew) + 10% of that
    assert got == 220 and f['xp'] - xp0 == 220 and f['economy']['stats']['feast_xp'] == 20
    g = farm(lv=12)
    g['economy']['feast_until'] = D1 + 7200
    plain = progression.grant_xp(g, 100, 'order', D1 + 3600, False)               # helper replay: plain XP
    assert plain == 100
    g2 = farm(lv=12)
    g2['economy']['feast_until'] = D1 + 100
    assert progression.grant_xp(g2, 100, 'order', D1 + 3600, False) == 100          # expired
    economy._grant_feast(g2, D1 + 3600)
    economy._grant_feast(g2, D1 + 3700)
    assert g2['economy']['feast_until'] == D1 + 3700 + 3 * DAY                      # refreshed, never summed


def test_common_reward_requires_the_goal_and_the_minimum_share_and_is_paid_once():
    a, b = farm(lv=12, coins=10 ** 6), farm(lv=12, coins=10 ** 6)
    season = economy.season_of(D1 + 3600)
    cmd(a, 'fund_contribute', {'coins': 20_000, 'items': {}})
    cmd(b, 'fund_contribute', {'coins': 1_299, 'items': {}})                         # one coin below 10% of 13000
    assert economy.claimable_seasons(a) == [season] and economy.claimable_seasons(b) == []
    assert not economy.claim_village(a, season, False, D1 + 4000)                    # goal not reached
    assert not economy.claim_village(b, season, True, D1 + 4000)                     # share too small
    assert economy.claim_village(a, season, True, D1 + 4000)
    assert 'fd_banner' in a['economy']['unlocked'] and a['economy']['feast_until'] == D1 + 4000 + 3 * DAY
    assert not economy.claim_village(a, season, True, D1 + 5000) and economy.claimable_seasons(a) == []
    cmd(b, 'fund_contribute', {'coins': 1, 'items': {}})
    assert economy.claim_village(b, season, True, D1 + 4000)


def test_reward_decor_is_free_only_after_the_unlock_and_paid_decor_follows_its_level():
    f = farm(lv=12, coins=50_000, size=12)
    with pytest.raises(FarmError) as e:
        cmd(f, 'build', {'type': 'fd_garland', 'x': 0, 'y': 0})
    assert e.value.code == 'reward_locked'
    cmd(f, 'fund_contribute', {'coins': 7000, 'items': {}})
    coins = f['coins']
    cmd(f, 'build', {'type': 'fd_garland', 'x': 11, 'y': 0})
    cmd(f, 'build', {'type': 'fd_garland', 'x': 10, 'y': 0})
    assert f['coins'] == coins and f['economy']['stats']['decor'] == 0
    cmd(f, 'build', {'type': 'dc_birdbath', 'x': 0, 'y': 8})
    assert f['coins'] == coins - 1200 and f['economy']['stats']['decor'] == 1200
    with pytest.raises(FarmError) as e:
        cmd(f, 'build', {'type': 'dc_fountain', 'x': 0, 'y': 2})                  # tier II needs L15
    assert e.value.code == 'locked'
    # decor never adds upkeep
    base = economy.base_upkeep(f)
    f['xp'] = LEVELS[14]
    cmd(f, 'build', {'type': 'dc_fountain', 'x': 4, 'y': 2})
    assert economy.base_upkeep(f) == base
    validate_state(f)


def test_projection_exposes_economy_only_to_the_owner_and_old_saves_load():
    f = farm(lv=12, coins=10_000)
    me = project(f, f, D1 + 3600)
    assert me['economy_status']['thresholds'] == economy.thresholds(13000) and me['economy_status']['active']
    other = deepcopy(f)
    other['id'] = str(uuid4())
    other['settings']['visibility'] = 'public'
    seen = project(other, f, D1 + 3600)
    assert 'economy' not in seen and 'economy_status' not in seen
    old = deepcopy(f)
    del old['economy']
    old['schema_version'] = 2
    upgrade_state(old)
    assert old['economy'] == economy.blank() and old['schema_version'] == 2
    validate_state(old)


def test_economy_module_never_writes_xp():
    import re
    from pathlib import Path
    text = (Path(__file__).resolve().parents[1] / 'qw_farm' / 'economy.py').read_text(encoding='utf-8')
    assert not re.search(r"""\['xp'\]\s*[-+]?=(?!=)""", text)


# ---------------------------------------------------------------------------------------------- service: two farms, shared counter
class SharedVillage:
    """The in-memory twin of farm_village used by several units at once."""
    def __init__(self, goal=30_000):
        self.rows, self.goal = {}, goal


class SharedUnit:
    def __init__(self, account_id, state, village):
        self.account_id, self.farms, self.receipts, self.records, self.v = account_id, {state['id']: state}, {}, [], village

    async def lock(self, *keys): pass
    async def by_account(self, account_id): return next(iter(self.farms.values()))
    async def get(self, farm_id): return self.farms.get(farm_id)
    async def owner_account(self, farm_id): return self.account_id
    async def save(self, farm, account_id=None): self.farms[farm['id']] = farm
    async def receipt(self, account_id, key): return self.receipts.get((account_id, key))
    async def remember(self, account_id, key, fingerprint, result, now):
        self.receipts[(account_id, key)] = dict(fingerprint=fingerprint, result=result)
    async def record(self, actor, key, kind, before, after, now): self.records.append((key, kind))
    async def village_peek(self, season): return deepcopy(self.v.rows.get(season))
    async def village_goal(self, now): return self.v.goal
    async def village_add(self, season, value, now):
        row = self.v.rows.setdefault(season, dict(season=season, total=0, goal=self.v.goal))
        row['total'] += value
        return dict(row)


def test_two_farms_fill_the_village_and_both_receive_the_common_reward_lazily():
    async def run():
        village = SharedVillage(goal=30_000)
        units, services, clock = [], [], [D1 + 3600]
        for name in 'abc':
            state = farm(lv=12, coins=200_000)
            state['name'] = name
            unit = SharedUnit(name, state, village)
            units.append(unit)
            services.append(FarmService(unit, Principal(name, name), clock=lambda: clock[0]))
        a, b, c = services
        await a.command('fund-a-000001', 'fund_contribute', {'coins': 20_000, 'items': {}})
        assert village.rows[economy.season_of(clock[0])]['total'] == 20_000
        await b.command('fund-b-000001', 'fund_contribute', {'coins': 15_000, 'items': {}})
        assert village.rows[economy.season_of(clock[0])]['total'] == 35_000                # >= goal 30000
        await c.command('fund-c-000001', 'fund_contribute', {'coins': 100, 'items': {}})   # below the minimum share
        for unit in units[:2]:
            assert 'fd_banner' not in next(iter(unit.farms.values()))['economy']['unlocked']   # nothing is pushed: lazy
        clock[0] += 3600
        for service, unit in zip((a, b, c), units):
            result = await service.view()
            mine = next(iter(unit.farms.values()))['economy']
            if unit is units[2]:
                assert 'fd_banner' not in mine['unlocked'] and mine['feast_until'] == 0
            else:
                assert 'fd_banner' in mine['unlocked'] and mine['feast_until'] == clock[0] + 3 * DAY
                assert result['village']['total'] == 35_100 and result['village']['goal'] == 30_000
        coins = next(iter(units[0].farms.values()))['coins']
        await a.view()
        assert next(iter(units[0].farms.values()))['coins'] == coins                         # paid once
        # a retried contribution is idempotent: the shared counter is not doubled
        again = await a.command('fund-a-000001', 'fund_contribute', {'coins': 20_000, 'items': {}})
        assert village.rows[economy.season_of(D1 + 3600)]['total'] == 35_100 and again['command_id'] == 'fund-a-000001'
        # the reward also arrives in the NEXT season if the first visit after the goal was late
        late = FarmService(units[1], Principal('b', 'b'), clock=lambda: clock[0] + 30 * DAY)
        assert (await late.view())['village']['total'] == 0
    asyncio.run(run())


def test_a_failed_contribution_does_not_touch_the_counter():
    async def run():
        village = SharedVillage()
        state = farm(lv=12, coins=1_000)
        unit = SharedUnit('a', state, village)
        service = FarmService(unit, Principal('a', 'a'), clock=lambda: D1 + 3600)
        with pytest.raises(FarmError):
            await service.command('fund-a-000002', 'fund_contribute', {'coins': 5_000, 'items': {}})
        assert village.rows == {}
    asyncio.run(run())


# ---------------------------------------------------------------------------------------------- PostgreSQL
from tests.test_farm_platform import (  # noqa: E402
    API, FARM_HEADERS, accepted, environment, farm_pg_url, player, raw_farm, view)
from tests.test_mini_app import NOW  # noqa: E402
from qw_farm.persistence import Unit  # noqa: E402


async def fund_ready(env, p, coins=200_000, lv=12):
    async with env.db.transaction() as session:
        unit = Unit(session, env.schema)
        state = await unit.by_account(p.account_id)
        before = deepcopy(state)
        state.update(coins=coins, xp=LEVELS[lv - 1])
        validate_state(state)
        await unit.save(state)
        await unit.record(p.account_id, 'fixture-fund', 'fixture', before, state, env.now[0])


def test_postgres_concurrent_contributions_are_not_lost_and_both_farms_get_the_reward(farm_pg_url):
    async def run():
        async with environment(farm_pg_url) as env:
            async with player(env) as a, player(env, 'telegram', 981020000077) as b:
                await fund_ready(env, a)
                await fund_ready(env, b)
                season = economy.season_of(env.now[0])
                # 1. raw counter: many parallel transactions, each an atomic increment
                async def add(v):
                    async with env.db.transaction() as session:
                        await Unit(session, env.schema).village_add(season, v, env.now[0])
                values = list(range(1, 41))
                await asyncio.gather(*(add(v) for v in values))
                async with env.db.transaction() as session:
                    row = await Unit(session, env.schema).village_peek(season)
                assert row['total'] == sum(values) and row['goal'] >= catalog.VILLAGE_GOAL_FLOOR
                base = row['total']
                # 2. two real farms contribute at the same moment through HTTP
                first, second = await asyncio.gather(
                    accepted(a, 'fund_contribute', {'coins': 70_000, 'items': {}}),
                    accepted(b, 'fund_contribute', {'coins': 60_000, 'items': {}}))
                async with env.db.transaction() as session:
                    row = await Unit(session, env.schema).village_peek(season)
                assert row['total'] == base + 130_000 and row['total'] >= row['goal']
                # 3. the reward is not pushed; each farm gets it on its own next visit, once
                for p in (a, b):
                    stored = await raw_farm(env, p)
                    assert 'fd_banner' not in stored['economy']['unlocked']
                for p in (a, b):
                    seen = await view(p)
                    assert 'fd_banner' in seen['economy']['unlocked'] and seen['economy']['feast_until'] == env.now[0] + 3 * DAY
                    again = await view(p)
                    assert again['revision'] == seen['revision']
                response = await a.client.get(API + '/me', params={'identity': a.identity})
                assert response.json()['village']['total'] == row['total']
                assert (await raw_farm(env, a))['economy']['stats']['fund_village'] == 70_000
    asyncio.run(run())


def test_postgres_a_stranger_who_never_contributed_gets_no_common_reward(farm_pg_url):
    async def run():
        async with environment(farm_pg_url) as env:
            async with player(env) as a, player(env, 'telegram', 981020000078) as b:
                await fund_ready(env, a, coins=400_000)
                await fund_ready(env, b)
                await accepted(a, 'fund_contribute', {'coins': 130_000, 'items': {}})
                await accepted(b, 'sell', {'item': 'wheat', 'qty': 1})
                seen_b = await view(b)
                assert 'fd_banner' not in seen_b['economy']['unlocked']      # b never contributed
                seen_a = await view(a)
                assert 'fd_banner' in seen_a['economy']['unlocked']
    asyncio.run(run())


def test_postgres_upkeep_is_charged_once_per_day_through_http(farm_pg_url):
    async def run():
        async with environment(farm_pg_url) as env:
            async with player(env) as p:
                await fund_ready(env, p, coins=50_000, lv=12)
                await accepted(p, 'sell', {'item': 'wheat', 'qty': 1})       # grace day
                before = (await raw_farm(env, p))['coins']
                env.now[0] += 86400
                await accepted(p, 'sell', {'item': 'wheat', 'qty': 1})
                await accepted(p, 'sell', {'item': 'feed', 'qty': 1})
                state = await raw_farm(env, p)
                paid = state['economy']['stats']['upkeep_paid']
                assert paid == economy.base_upkeep(state) and paid > 0
                assert state['coins'] == before + W + catalog.ITEMS['feed']['price'] - paid
    asyncio.run(run())


def test_postgres_migration_creates_the_village_table_and_refuses_to_drop_data(farm_pg_url, monkeypatch):
    async def run():
        from alembic.config import Config
        from alembic.migration import MigrationContext
        from alembic.operations import Operations
        from alembic.script import ScriptDirectory
        from sqlalchemy import inspect, text
        from tests.local_database import isolated_database
        scripts = ScriptDirectory.from_config(Config('alembic.ini'))
        migration = scripts.get_revision('20261010_0027').module
        assert migration.down_revision == '20261009_0026' and scripts.get_revision('20261010_0028').down_revision == '20261010_0027'
        async with isolated_database(farm_pg_url) as (db, schema):
            async with db.engine.begin() as connection:
                def roundtrip(sync):
                    sync.execute(text('DROP TABLE farm_village'))
                    with monkeypatch.context() as patch:
                        patch.setattr(migration, 'op', Operations(MigrationContext.configure(sync)))
                        migration.upgrade()
                    columns = {c['name']: c for c in inspect(sync).get_columns('farm_village', schema=schema)}
                    assert set(columns) == {'season', 'total', 'goal', 'created_at'}
                    sync.execute(text("INSERT INTO farm_village (season, goal, created_at) VALUES (1, 100, 0)"))
                    assert sync.scalar(text('SELECT total FROM farm_village')) == 0
                    with monkeypatch.context() as patch:
                        patch.setattr(migration, 'op', Operations(MigrationContext.configure(sync)))
                        with pytest.raises(RuntimeError, match='counters exist'):
                            migration.downgrade()
                    sync.execute(text('DELETE FROM farm_village'))
                    with monkeypatch.context() as patch:
                        patch.setattr(migration, 'op', Operations(MigrationContext.configure(sync)))
                        migration.downgrade()
                        assert not inspect(sync).has_table('farm_village', schema=schema)
                        migration.upgrade()
                    assert inspect(sync).has_table('farm_village', schema=schema)
                await connection.run_sync(roundtrip)
    asyncio.run(run())
