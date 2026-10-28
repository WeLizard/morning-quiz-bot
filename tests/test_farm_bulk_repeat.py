"""One-shot bulk repeat and queue fill share a read-only plan and a locked apply path."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from qw_farm.catalog import queue_slots
from qw_farm.expansion import plan_repeats
from tests.test_farm_automation_r7 import T0, add_building, cmd, err, farm, obj


CASES = json.loads((Path(__file__).parent / 'fixtures' / 'farm_bulk_repeat.json').read_text(encoding='utf-8'))['cases']


@pytest.mark.parametrize('case', CASES, ids=lambda case: case['name'])
def test_shared_parity_fixture_plan_and_apply(case):
    st = farm()
    st.update(deepcopy(case['farm']))
    for building in st['objects']:
        building.setdefault('revision', 0)
        building.setdefault('last_recipe', building['recipes_memory'][-1])
    before = deepcopy(st)
    plan = plan_repeats(st, case['area'], case['mode'])
    assert st == before
    assert plan['starts'] == case['starts']
    notice = cmd(st, case['mode'], {'area': case['area']})
    assert f'Поставлено партий: {len(case["starts"])}.' in notice
    bulk_event = next(event for event in st['events'] if event['kind'] == case['mode'])
    assert [(item['object'], item['recipe']) for item in bulk_event['details']] == [
        (item['object'], item['recipe']) for item in case['starts']]
    assert len({item['job'] for item in bulk_event['details']}) == len(case['starts'])
    assert all(job.get('manual') is True for building in st['objects'] for job in building['jobs'])
    assert len({job['id'] for building in st['objects'] for job in building['jobs']}) == len(case['starts'])


def test_once_never_repeats_a_recipe_and_keeps_memory_with_legacy_last_recipe():
    st = farm()
    mill = add_building(st, 'mill', 'm', 0, 0, last_recipe='flour')
    mill.pop('recipes_memory')
    mill.pop('recipe_cursor')
    st['inventory'] = {'wheat': 100}
    assert plan_repeats(st, None, 'repeat_once')['starts'] == [dict(object='m', recipe='flour')]
    cmd(st, 'repeat_once', {'area': None})
    assert [job['recipe'] for job in mill['jobs']] == ['flour']
    assert mill['recipes_memory'] == ['flour'] and mill['last_recipe'] == 'flour'


def test_once_partial_slots_locked_recipes_and_failure_leave_state_intact():
    st = farm(xp=0)
    mill = add_building(st, 'mill', 'm', 0, 0)
    mill.update(recipes_memory=['flour', 'oil', 'rye_flour'], recipe_cursor=0, last_recipe='rye_flour')
    st['inventory'] = {'wheat': 2, 'sunflower': 2, 'rye': 2}
    plan = plan_repeats(st, None, 'repeat_once')
    assert plan['starts'] == [dict(object='m', recipe='flour')]
    assert 'locked_recipe' in plan['reasons']
    notice = cmd(st, 'repeat_once', {'area': None})
    assert 'недоступна' in notice and mill['recipes_memory'] == ['flour', 'oil', 'rye_flour']
    st['inventory'] = {}
    assert err(st, 'repeat_once', {'area': None}) == 'nothing_to_do'
    assert err(st, 'fill_queues', {'area': {'x': -1, 'y': 0, 'w': 1, 'h': 1}}) == 'invalid_area'


def test_fill_is_finite_and_never_exceeds_slots_or_shared_stock():
    st = farm()
    for oid, x in [('a', 0), ('b', 4)]:
        item = add_building(st, 'mill', oid, x, 0)
        item.update(recipes_memory=['flour', 'feed'], recipe_cursor=0, last_recipe='feed')
    st['inventory'] = {'wheat': 100}
    cmd(st, 'fill_queues', {'area': None})
    assert all(len(item['jobs']) == queue_slots(item['level']) for item in st['objects'])
    assert st['inventory']['wheat'] == 100 - 2 * sum(len(item['jobs']) for item in st['objects'])
    assert err(st, 'fill_queues', {'area': None}) == 'nothing_to_do'
