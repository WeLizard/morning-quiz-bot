"""Server rules for the first workshop goals on the order board."""
import asyncio
from copy import deepcopy
from tempfile import NamedTemporaryFile
from uuid import uuid4

import pytest

from qw_farm.catalog import level, public_catalog
from qw_farm.domain import FarmError, apply, new_farm, project, validate_state
from qw_farm.expansion import upgrade_state
from qw_farm.persistence import DemoDatabase
from qw_farm.service import FarmService, Principal


NOW = 1_700_000_000


def farm(xp=0):
    state = upgrade_state(new_farm(str(uuid4()), 'Workshop', NOW), NOW)
    state.update(xp=xp, coins=500)
    return state


def command(state, kind, data, other=None):
    return apply(state, state if other is None else other, kind, data, NOW, str(uuid4()))


def build(state, building):
    command(state, 'build', {'type': building, 'x': 0, 'y': 6})


def rejected(state, quest, code, other=None):
    before = deepcopy(state)
    with pytest.raises(FarmError) as failure:
        command(state, 'quest', {'quest': quest}, other)
    assert failure.value.code == code
    assert state == before


def test_catalog_exposes_workshop_goals_separately_from_stat_quests():
    catalog = public_catalog()
    goals = catalog.get('workshop_goals', [])
    assert [(g['id'], g['name'], g['text'], g['level'], g['building'], g['needs'], g['coins'], g['xp'])
            for g in goals] == [
        ('workshop_bread', 'Первая выпечка',
         'Сдай две буханки хлеба со склада. Для цели нужна пекарня на твоей ферме.',
         2, 'bakery', {'bread': 2}, 91, 11),
        ('workshop_cheese', 'Первый сыр',
         'Сдай сыр со склада. Для цели нужна сыроварня на твоей ферме.',
         4, 'dairy', {'cheese': 1}, 83, 10),
        ('workshop_butter', 'Первое масло',
         'Сдай сливочное масло со склада. Для цели нужна маслобойня на твоей ферме.',
         10, 'oil_press', {'butter': 1}, 89, 11),
        ('workshop_juice', 'Первый сок',
         'Сдай виноградный сок со склада. Для цели нужна соковарня на твоей ферме.',
         13, 'juicery', {'grape_juice': 1}, 138, 18),
        ('workshop_ajvar', 'Первая заготовка',
         'Сдай баклажанную икру со склада. Для цели нужен консервный цех на твоей ферме.',
         14, 'cannery', {'ajvar': 1}, 231, 31),
        ('workshop_smoked_cheese', 'Первое копчение',
         'Сдай копчёный сыр со склада. Для цели нужна коптильня на твоей ферме.',
         15, 'smokehouse', {'smoked_cheese': 1}, 144, 19),
    ]
    assert {g['id'] for g in goals}.isdisjoint(q['id'] for q in catalog['quests'])


def test_workshop_goal_requires_level_even_with_building_and_goods():
    state = farm(xp=20)
    build(state, 'bakery')
    state['xp'] = 19
    state['inventory']['bread'] = 2

    rejected(state, 'workshop_bread', 'locked')


def test_workshop_goal_requires_workshop_on_own_farm():
    state = farm(xp=20)
    neighbor = farm(xp=20)
    build(neighbor, 'bakery')
    state['inventory']['bread'] = 2

    rejected(state, 'workshop_bread', 'building_required')
    rejected(state, 'workshop_bread', 'not_owner', other=neighbor)


def test_workshop_goal_checks_inventory_before_claim():
    state = farm(xp=20)
    build(state, 'bakery')
    state['inventory']['bread'] = 1

    rejected(state, 'workshop_bread', 'missing_goods')


@pytest.mark.parametrize(('quest', 'building', 'product', 'qty', 'xp', 'coins_reward', 'xp_reward'), [
    ('workshop_bread', 'bakery', 'bread', 2, 20, 91, 22),
    ('workshop_cheese', 'dairy', 'cheese', 1, 135, 83, 20),
])
def test_workshop_goal_accepts_existing_stock_and_building_once_after_reload(
        quest, building, product, qty, xp, coins_reward, xp_reward):
    account = uuid4()
    state = farm(xp=xp)
    build(state, building)
    state['inventory'][product] = qty * 2
    state['claimed_quests'].append('q1')
    validate_state(state)

    async def claim(db, key):
        async with db.transaction() as unit:
            service = FarmService(unit, Principal(str(account), 'Workshop'), clock=lambda: NOW)
            return await service.command(key, 'quest', {'quest': quest})

    async def scenario(db_path):
        db = DemoDatabase(db_path)
        try:
            async with db.transaction() as unit:
                await unit.execute(db.accounts.insert().values(
                    id=account, name='Workshop', recovery_hash=uuid4().hex))
                await unit.save(state, account)
            first = await claim(db, 'workshop-first')
        finally:
            db.engine.dispose()

        restarted = DemoDatabase(db_path)
        try:
            assert await claim(restarted, 'workshop-first') == first
            with pytest.raises(FarmError) as failure:
                await claim(restarted, 'workshop-second')
            assert failure.value.code == 'already_claimed'
            async with restarted.transaction() as unit:
                saved = await unit.by_account(account)
        finally:
            restarted.engine.dispose()
        assert saved['claimed_quests'] == ['q1', quest]
        assert saved['inventory'][product] == qty
        assert saved['coins'] == state['coins'] + coins_reward
        assert saved['xp'] == state['xp'] + xp_reward  # base XP doubled by the ordinary dew bonus
        assert saved['orders'] == state['orders']
        assert saved['stats'] == state['stats']
        assert saved['market']['rep'] == state['market']['rep']
        assert saved['market']['contracts'] == state['market']['contracts']

    with NamedTemporaryFile(suffix='.sqlite3', delete_on_close=False) as db_file:
        db_file.close()
        asyncio.run(scenario(db_file.name))


def test_unclaimed_workshop_goals_do_not_block_orders_or_stat_quest_level_up():
    state = farm(xp=100)
    order = state['orders'][0]
    state['inventory'].update(order['needs'])
    command(state, 'order', {'order': order['id']})
    assert state['stats']['orders'] == 1
    assert state['orders'][0]['id'] != order['id']

    rejected(state, 'q1', 'quest_incomplete')
    state['xp'] = 134
    state['stats']['harvests'] = 4
    coins = state['coins']
    goods = state['inventory'].copy()
    command(state, 'quest', {'quest': 'q1'})

    assert state['claimed_quests'] == ['q1']
    assert state['coins'] == coins + 45
    assert state['inventory'] == goods
    assert level(state['xp']) == 4


def test_visitors_do_not_see_goal_claims_or_inventory():
    state = farm(xp=20)
    state['settings']['visibility'] = 'public'
    state['claimed_quests'].append('workshop_bread')
    state['inventory']['bread'] = 2

    visitor_view = project(state, farm(), NOW)

    assert not visitor_view['is_owner']
    assert 'claimed_quests' not in visitor_view
    assert 'inventory' not in visitor_view
