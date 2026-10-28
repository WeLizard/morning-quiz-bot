"""Ready work is served by age across buildings; restart starts keep their old order."""
from copy import deepcopy

from qw_farm.catalog import VERSION
from qw_farm.expansion import _targets, ordered_objects, settle
from tests.test_farm_automation_r7 import T0, add_building, farm, hire_and_start, obj


def job(jid, ready_at, recipe='flour'):
    return dict(id=jid, recipe=recipe, starts_at=T0 - 1000, ready_at=ready_at,
                seconds=10, inputs={}, outputs={'flour': 1}, xp=1, version=VERSION)


def test_ready_craft_jobs_precede_newer_job_in_lower_id_workshop():
    st = farm()
    fast = add_building(st, 'feedmill', 'a-fast-feedmill', 0, 0, last_recipe='hay')
    old = add_building(st, 'mill', 'z-old-mill', 4, 0, last_recipe='flour')
    fast['jobs'] = [job('fast', T0 - 1, 'hay')]
    old['jobs'] = [job('old', T0 - 100)]
    assert [(o['id'], j['id']) for o, j in _targets(st, ordered_objects(st), 'craft', T0, None)
            if isinstance(j, dict)] == [('z-old-mill', 'old'), ('a-fast-feedmill', 'fast')]
    st['inventory'] = {}
    hire_and_start(st, 'badger_artisan', 'day')
    shift = st['helpers']['badger_artisan']['shift']
    shift['remaining'] = 1
    settle(st, T0 + 30)
    assert old['jobs'] == [] and [j['id'] for j in fast['jobs']] == ['fast']
    assert st['inventory']['flour'] == 1


def test_ready_production_and_animal_jobs_sort_by_age_then_object_and_job_id():
    st = farm()
    a = add_building(st, 'mill', 'a', 0, 0)
    z = add_building(st, 'mill', 'z', 4, 0)
    a['jobs'] = [job('b', T0 - 1), job('a', T0 - 1)]
    z['jobs'] = [job('old', T0 - 50)]
    assert [(o['id'], j['id']) for o, j in _targets(st, ordered_objects(st), 'production', T0, None)] == [
        ('z', 'old'), ('a', 'a'), ('a', 'b')]
    a['jobs'] = z['jobs'] = []
    a.update(type='coop', animal='chicken', animal_job={'ready_at': T0 - 1, 'outputs': {'egg': 1}, 'xp': 1})
    z.update(type='coop', animal='chicken', animal_job={'ready_at': T0 - 50, 'outputs': {'egg': 1}, 'xp': 1})
    assert [o['id'] for o, j in _targets(st, ordered_objects(st), 'animals', T0, None) if j] == ['z', 'a']
    a['animal_job'] = z['animal_job'] = None
    a['animal_repeat'] = z['animal_repeat'] = True
    st['inventory'] = {'feed': 10}
    assert [o['id'] for o, j in _targets(st, ordered_objects(st), 'animals', T0, None)] == ['a', 'z']


def test_two_artisans_offline_settle_matches_incremental_settle():
    st = farm()
    for oid, x in [('a', 0), ('z', 4)]:
        mill = add_building(st, 'mill', oid, x, 0, last_recipe='flour')
        mill['jobs'] = [job('ready-' + oid, T0 - (100 if oid == 'z' else 1))]
    st['inventory'] = {'wheat': 40}
    hire_and_start(st, 'badger_artisan', 'day')
    hire_and_start(st, 'beaver_artisan', 'day')
    one, two = deepcopy(st), deepcopy(st)
    settle(one, T0 + 7200)
    for at in (T0 + 30, T0 + 60, T0 + 120, T0 + 900, T0 + 7200):
        settle(two, at)
    strip = lambda value: {k: v for k, v in value.items() if k not in {'events', 'market'}}
    assert strip(one) == strip(two)
