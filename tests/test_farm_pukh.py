"""Медведь Пух and the «Бодрильня» (docs/tasks/FARM_PUKH_ENERGY.md): catalog, order hook, old/new saves, upgrades, assets."""
import re
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest

from qw_farm import market
from qw_farm.catalog import (BUILDINGS, ITEMS, LEVELS, MARKET, NPC_SIGNATURE, NPC_TASTES, NPCS, RECIPES, SIGNATURE_PCT, UPGRADES,
                             public_catalog, upgrade_cost, upgrade_kind, validate)
from qw_farm.domain import FarmError, apply, make_order, new_farm, reachable, validate_state
from qw_farm.expansion import upgrade_state

STATIC = Path(__file__).resolve().parents[1] / 'qw_farm' / 'static'
PUKH = 'Медведь Пух'
CHARGES = {'berry_charge': (11, 600, {'raspberry': 4, 'honey': 1}, 85),
           'forest_charge': (12, 600, {'wildberry': 4, 'blackberry': 1, 'herbs': 2}, 79),
           'honey_charge': (13, 900, {'honey': 2, 'mint': 1}, 108)}


def farm_with_shop(xp=LEVELS[29], shop=True):
    state = upgrade_state(new_farm(str(uuid4()), 'Pukh', 1000))
    state.update(xp=xp, coins=10 ** 7, starter_credit=0, size=20)
    state['objects'] = []
    if shop:
        state['objects'].append(dict(id='shop', type='energy_shop', x=0, y=0, w=2, h=2, revision=0, level=1, jobs=[], animal=None, animal_job=None))
    state['objects'].append(dict(id='apiary', type='apiary', x=4, y=0, w=2, h=2, revision=0, level=1, jobs=[], animal='bees', animal_job=None))
    return state


def test_catalog_validates_and_pukh_is_appended_last():
    validate()
    assert NPCS[-1] == (PUKH, 'Для бодрости перед работой')
    assert [n for n, _ in NPCS][:8] == ['Филиныч', 'Агата', 'Почтальон Ёж', 'Механик Крот', 'Кошка Кая', 'Кошка Соня', 'Суслик Игорь', 'Неведома Зверушка']
    assert NPC_TASTES[PUKH] == ('berry_charge', 'honey_charge', 'forest_charge', 'honey', 'gingerbread')
    assert set(NPC_SIGNATURE[PUKH]) == set(CHARGES) and SIGNATURE_PCT == 70
    assert public_catalog()['market']['tastes'][PUKH] == list(NPC_TASTES[PUKH]) and MARKET['tastes'][PUKH]


def test_building_and_recipes_follow_the_neighbours_price_law():
    b = BUILDINGS['energy_shop']
    assert (b['name'], b['cost'], b['level'], b['w'], b['h'], b['decor']) == ('Бодрильня', 1800, 11, 2, 2, False)
    assert BUILDINGS['oil_press']['cost'] < b['cost'] < BUILDINGS['juicery']['cost']
    assert BUILDINGS['oil_press']['level'] < b['level'] < BUILDINGS['juicery']['level']
    for rid, (lvl, secs, inputs, price) in CHARGES.items():
        r = RECIPES[rid]
        assert (r['building'], r['level'], r['seconds'], r['inputs'], r['outputs']) == ('energy_shop', lvl, secs, inputs, {rid: 2})
        assert ITEMS[rid]['price'] == price and ITEMS[rid]['kind'] == 'product'
        assert all(i in ITEMS for i in inputs)
        cost_in = sum(ITEMS[k]['price'] * q for k, q in inputs.items())
        expected = cost_in + secs / 60 * (2.5 + 0.1 * lvl)
        assert abs(2 * price - expected) <= 2, (rid, 2 * price, expected)     # tolerance of the neighbours (rounding of unit prices)
        assert r['xp'] == max(6, secs // 80)
    assert sum(1 for r in RECIPES.values() if 'berry_charge' in r['outputs']) == 1


def test_upgrades_of_the_new_workshop():
    assert upgrade_kind('energy_shop') == 'workshop'
    assert upgrade_cost('energy_shop', 2)['coins'] == 900 and upgrade_cost('energy_shop', 3)['coins'] == 1800
    state = farm_with_shop()
    state['inventory'].update({k: 50 for l in (2, 3) for k in UPGRADES[l]['items']})
    obj = state['objects'][0]
    for _ in range(2):
        apply(state, state, 'upgrade', dict(object=obj['id'], revision=obj['revision']), 2000, str(uuid4()))
    assert obj['level'] == 3
    validate_state(state)


def test_can_build_and_craft_after_level_11():
    state = farm_with_shop(xp=LEVELS[10], shop=False)
    apply(state, state, 'build', dict(type='energy_shop', x=0, y=8), 2000, str(uuid4()))
    shop = next(o for o in state['objects'] if o['type'] == 'energy_shop')
    state['inventory'].update(raspberry=4, honey=1)
    apply(state, state, 'queue', dict(object=shop['id'], recipe='berry_charge'), 2000, str(uuid4()))
    low = farm_with_shop(xp=LEVELS[9], shop=False)
    with pytest.raises(FarmError):
        apply(low, low, 'build', dict(type='energy_shop', x=0, y=8), 2000, str(uuid4()))


def _orders(state, n):
    return [make_order(state, 0, 5000) for _ in range(n)]


def test_pukh_asks_for_energy_drinks_about_seventy_percent_and_deterministically():
    state = farm_with_shop()
    assert set(CHARGES) <= set(reachable(state))
    orders = _orders(deepcopy(state), 3000)
    assert orders == _orders(deepcopy(state), 3000)                     # same seed, same orders
    mine = [o for o in orders if o['npc'] == PUKH]
    assert 250 < len(mine) < 420                                         # about 1/9 of 3000
    share = sum(1 for o in mine if set(o['needs']) & set(CHARGES)) / len(mine)
    assert 0.62 <= share <= 0.80, share
    for o in mine:
        assert all(i in ITEMS for i in o['needs']) and o['coins'] > 0


def test_without_the_shop_the_hook_stays_silent_and_training_orders_are_untouched():
    state = farm_with_shop(shop=False)
    assert not set(CHARGES) & set(reachable(state))
    assert all(not (set(o['needs']) & set(CHARGES)) for o in _orders(state, 600))
    fresh = farm_with_shop()
    fresh['order_seq'] = 0
    first = [make_order(fresh, 0, 5000) for _ in range(3)]
    assert first[0]['needs'] == {'wheat': 6} and first[1]['needs'] == {'carrot': 3} and first[2]['needs'] == {'flour': 1, 'egg': 2}


def test_old_save_without_pukh_and_new_save_with_pukh_are_valid():
    old = farm_with_shop(shop=False)
    assert PUKH not in old['market']['rep']
    validate_state(old)
    new = farm_with_shop()
    market.add_rep(new, PUKH, 3)
    assert new['market']['rep'][PUKH] == 3
    validate_state(new)
    new['market']['rep']['Выдуманный'] = 1
    with pytest.raises(FarmError):
        validate_state(new)


def test_pukh_special_requests_work_before_the_shop_exists():
    state = farm_with_shop(shop=False)
    market.add_rep(state, PUKH, 5)
    products = reachable(state)
    found = [market.special_needs(state, r, PUKH, products) for r in range(0, 2000, 7)]
    items = {i for f in found if f for i in f}
    assert items and items <= {'honey', 'gingerbread'}


def test_a_delivered_order_raises_pukh_reputation():
    state = farm_with_shop()
    state['orders'][0] = dict(id='order_x', slot=0, npc=PUKH, title='Для бодрости перед работой', needs={'honey': 1}, coins=100, xp=10, skip_at=0)
    state['inventory']['honey'] = 1
    apply(state, state, 'order', dict(order='order_x'), 2000, str(uuid4()))
    assert state['market']['rep'][PUKH] == 1


@pytest.mark.xfail(reason='art is drawn by another task: avatar_bear, three item icons, energy_shop drawer', strict=False)
def test_frontend_assets_exist():
    icons = set(re.findall(r'<symbol id="([a-z_0-9]+)"', (STATIC / 'icons.svg').read_text(encoding='utf-8')))
    assert {'avatar_bear', 'berry_charge', 'honey_charge', 'forest_charge'} <= icons
    buildings = (STATIC / 'scene_buildings.js').read_text(encoding='utf-8')
    types = re.search(r'const TYPES=\{([^}]*)\}', buildings).group(1)
    assert 'energy_shop' in {m.split(':')[0].strip() for m in types.split(',')}


def test_client_constants_cover_pukh():
    app = (STATIC / 'app.js').read_text(encoding='utf-8')
    for const in ('VILLAGE_VOICES', 'VILLAGE_SPOTS', 'VILLAGE_LIFE', 'AVATARS'):
        i = app.index('const ' + const + '=')
        assert PUKH in app[i:i + 6000].split('\nconst ')[0], const
    assert "'avatar_bear'" in app
