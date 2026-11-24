"""Coffee and cotton catalogue, seasonal cycles, and real processing chains."""
import asyncio
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from qw_farm import catalog, market, plantations
from qw_farm.domain import reachable, validate_state
from qw_farm.economy import DAY
from qw_farm.persistence import Unit
from tests.test_farm_plantations import cmd, error, farm, moscow, T0
from tests.test_farm_platform import accepted, environment, farm_pg_url, player, raw_farm, view


CHAINS = {
    'coffee_beans': ('coffee_roastery', 38, {'coffee_cherry': 4}, {'coffee_beans': 2}, 20, 183),
    'espresso': ('teahouse', 38, {'coffee_beans': 1}, {'espresso': 1}, 10, 246),
    'latte': ('teahouse', 38, {'coffee_beans': 1, 'milk': 2}, {'latte': 1}, 15, 314),
    'cotton_yarn': ('spinnery', 41, {'cotton': 4}, {'cotton_yarn': 2}, 12, 110),
    'chintz': ('weavery', 41, {'cotton_yarn': 2}, {'chintz': 1}, 25, 385),
    'shirt': ('tailor', 41, {'chintz': 1}, {'shirt': 1}, 30, 583),
    'sundress_chintz': ('tailor', 41, {'chintz': 1, 'cotton_yarn': 1}, {'sundress': 1}, 38, 746),
}


def test_catalogue_keeps_old_cloth_prices_and_registers_the_complete_new_chains():
    public = catalog.public_catalog()
    assert public['items']['coffee_cherry']['price'] == 60
    assert public['items']['cotton']['price'] == 35
    assert public['items']['madder_linen']['price'] == 325
    roastery = public['buildings']['coffee_roastery']
    assert (roastery['level'], roastery['cost'], roastery['w'], roastery['h']) == (38, 18_000, 2, 2)
    for key, (building, level, inputs, outputs, minutes, price) in CHAINS.items():
        recipe = public['recipes'][key]
        assert recipe['building'] == building
        assert recipe['level'] == level and recipe['seconds'] == minutes * 60
        assert recipe['inputs'] == inputs and recipe['outputs'] == outputs
        output, = outputs
        prices = public['items']
        assert prices[output]['price'] == price
        av = (minutes * (25 + level) + 9) // 10
        cost = sum(prices[item]['price'] * qty for item, qty in inputs.items())
        assert 0 <= price * outputs[output] - (cost + av) < outputs[output]
    original = public['recipes']['sundress']
    assert original['inputs'] == {'dyed_linen': 2, 'yarn': 1} and original['level'] == 19
    assert original['outputs'] == {'sundress': 1} and original['seconds'] == 2100
    assert public['upgrades']['kinds']['coffee_roastery'] == 'workshop'
    assert {'coffee_beans', 'espresso'} <= set(public['market']['tastes']['Филиныч'])
    assert 'latte' in public['market']['tastes']['Кошка Кая']
    assert {'cotton_yarn', 'chintz', 'shirt', 'sundress'} <= set(public['market']['tastes']['Кошка Соня'])
    catalog.validate()


@pytest.mark.parametrize(('crop', 'level', 'cost', 'juvenile', 'days', 'qty', 'xp', 'winter'), [
    ('coffee_grove', 38, 60_000, 4, 3, 135, 120, False),
    ('cotton_field', 41, 25_000, 1, 2, 155, 80, True),
])
def test_crop_unlocks_and_calendar(crop, level, cost, juvenile, days, qty, xp, winter):
    spec = catalog.public_catalog()['plantations']['cultures'][crop]
    assert (spec['level'], spec['cost'], spec['juvenile'], spec['seconds'], spec['yield_qty'],
            spec['xp'], spec['winter_pause']) == (level, cost, juvenile, days * DAY, qty, xp, winter)
    state = farm(lv=level - 1)
    started = moscow(2026, 12, 1) - DAY
    cmd(state, 'buy_plantation', {'step': 1}, started)
    error('locked', cmd, state, 'plant_plantation', {'plantation': 1, 'revision': 0, 'crop': crop}, started)
    state['xp'] = catalog.LEVELS[level - 1]
    before = state['coins']
    cmd(state, 'plant_plantation', {'plantation': 1, 'revision': 0, 'crop': crop}, started)
    assert state['coins'] == before - cost
    cycle = state['plantations'][0]['cycle']
    assert cycle['active_seconds'] == (juvenile + 1) * days * DAY
    assert cycle['ready_at'] == (moscow(2027, 3, 4) if winter else started + 15 * DAY)
    assert plantations.owner_view(state, started + DAY)[0]['state'] == ('winter' if winter else 'young')


def test_public_art_contains_the_new_items_and_seasonal_scenes():
    static = Path(__file__).resolve().parents[1] / 'qw_farm' / 'static'
    item_icons = {node.get('id') for node in ET.parse(static / 'icons.svg').iter()}
    assert {'coffee_cherry', 'coffee_beans', 'espresso', 'latte', 'cotton', 'cotton_yarn', 'chintz', 'shirt'} <= item_icons
    scenes = {node.get('id') for node in ET.parse(static / 'plantations-art.svg').iter()}
    assert {f'{crop}-{stage}' for crop in ('coffee_grove', 'cotton_field') for stage in ('young', 'adult', 'ripe')} <= scenes
    assert 'cotton_field-winter' in scenes


def test_postgres_both_plantations_supply_their_workshop_chains_and_jobs_survive_flag(farm_pg_url, monkeypatch):
    async def scenario():
        async with environment(farm_pg_url) as env:
            env.now[0] = T0
            async with player(env) as actor:
                async with env.db.transaction() as session:
                    unit = Unit(session, env.schema)
                    state = await unit.by_account(actor.account_id)
                    state.update(coins=1_000_000, xp=catalog.LEVELS[40], size=14)
                    state['inventory']['milk'] = 2
                    validate_state(state)
                    await unit.save(state)
                workshop_ids = {}
                for index, building in enumerate(('coffee_roastery', 'teahouse', 'spinnery', 'weavery', 'tailor',
                                                   'cowshed', 'feedmill')):
                    key = 'expansion-build-' + building
                    await accepted(actor, 'build', {'type': building, 'x': 6 + 2 * (index % 3), 'y': 6 + 2 * (index // 3)}, key=key)
                    workshop_ids[building] = key
                await accepted(actor, 'buy_animal', {'object': workshop_ids['cowshed'], 'animal': 'cow'})
                before = await raw_farm(env, actor)
                assert not {'coffee_beans', 'espresso', 'latte', 'cotton_yarn', 'chintz', 'shirt'} & set(reachable(before))
                for index, crop in enumerate(('coffee_grove', 'cotton_field'), 1):
                    await accepted(actor, 'buy_plantation', {'step': index})
                    await accepted(actor, 'plant_plantation', {'plantation': index, 'revision': 0, 'crop': crop})
                planted = (await view(actor))['plantations']
                env.now[0] = max(hectare['ready_at'] for hectare in planted)
                for index in (1, 2):
                    await accepted(actor, 'plantation_auto', {'plantation': index, 'revision': 1})
                harvested = await raw_farm(env, actor)
                assert harvested['inventory']['coffee_cherry'] == 73 and harvested['inventory']['cotton'] == 84
                possible = set(market.reachable_items(harvested))
                assert possible == set(reachable(harvested))
                assert {'coffee_beans', 'espresso', 'latte', 'cotton_yarn', 'chintz', 'shirt', 'sundress'} <= possible

                async def queue(recipe):
                    building = CHAINS[recipe][0]
                    object_id = workshop_ids[building]
                    await accepted(actor, 'queue', {'object': object_id, 'recipe': recipe})
                    state = await raw_farm(env, actor)
                    job, = next(obj['jobs'] for obj in state['objects'] if obj['id'] == object_id)
                    return object_id, job

                async def collect(object_id, job):
                    env.now[0] = max(env.now[0], job['ready_at'])
                    await accepted(actor, 'collect', {'object': object_id, 'job': job['id']})

                started = await queue('coffee_beans')
                with monkeypatch.context() as flag:
                    flag.setattr(catalog, 'PLANTATIONS_WIRED', False)
                    assert 'plantations' not in (await view(actor))
                    assert 'coffee_beans' in catalog.public_catalog()['recipes']
                    await collect(*started)
                    assert (await raw_farm(env, actor))['inventory']['coffee_beans'] == 2
                for recipe in ('espresso', 'latte', 'cotton_yarn', 'chintz', 'shirt',
                               'cotton_yarn', 'chintz', 'cotton_yarn', 'sundress_chintz'):
                    await collect(*await queue(recipe))
                final = await raw_farm(env, actor)
                assert all(final['inventory'][item] == 1 for item in ('espresso', 'latte', 'shirt', 'sundress'))
                validate_state(final)

    asyncio.run(scenario())
