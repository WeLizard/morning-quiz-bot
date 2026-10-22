"""Team-helper craft role: collect (1 quota unit) + restart (1 unit); restarts go to the workshop that frees up first."""
from qw_farm.catalog import VERSION
from qw_farm.expansion import settle

from tests.test_farm_automation_r7 import T0, add_building, add_plots, cmd, farm, hire_and_start, obj

FEED_ID = '3ce4037f-aaaa'   # uuid-like id: sorts before 'building_2'


def ready_job(recipe, outputs, jid):
    return dict(id=jid, recipe=recipe, starts_at=T0 - 60, ready_at=T0 - 1, seconds=60,
                inputs={}, outputs=outputs, xp=2, version=VERSION)


def mills(extra=None):
    st = farm()
    feed = add_building(st, 'feedmill', FEED_ID, 0, 0, last_recipe='hay', level=3)
    mill = add_building(st, 'mill', 'building_2', 4, 0, last_recipe='rye_flour', level=3)
    feed['jobs'] = [ready_job('hay', {'hay': 2}, 'jf')]
    mill['jobs'] = [ready_job('rye_flour', {'rye_flour': 1}, 'jm')]
    st['inventory'] = {'clover': 50, 'rye': 50, **(extra or {})}
    return st


def small_shift(st, quota):
    hire_and_start(st, 'badger_artisan', 'day')
    shift = st['helpers']['badger_artisan']['shift']
    shift['remaining'] = quota
    return shift


def test_late_id_workshop_is_not_starved_by_a_small_quota():
    st = mills()
    small_shift(st, 4)
    settle(st, T0 + 7200)
    assert [j['recipe'] for j in obj(st, 'building_2')['jobs']] == ['rye_flour']
    assert [j['recipe'] for j in obj(st, FEED_ID)['jobs']] == ['hay']
    assert st['inventory']['rye_flour'] == 1 and st['inventory']['hay'] == 2


def test_collect_and_restart_cost_two_quota_units():
    st = mills()
    shift = small_shift(st, 2)
    settle(st, T0 + 7200)
    assert shift['done'] == 2 and shift['remaining'] == 0
    assert st['stats']['automation'] == 2
    feed = obj(st, FEED_ID)
    assert st['inventory']['hay'] == 2 and st['inventory']['clover'] == 48  # carried out and the same recipe put back
    assert [j['recipe'] for j in feed['jobs']] == ['hay'] and feed['jobs'][0]['id'].startswith('auto-')
    assert obj(st, 'building_2')['jobs'][0]['id'] == 'jm'  # untouched, second in line


def test_with_one_unit_left_the_master_only_collects():
    st = mills()
    shift = small_shift(st, 3)
    settle(st, T0 + 7200)
    assert shift['done'] == 3 and shift['remaining'] == 0
    assert obj(st, FEED_ID)['jobs'][0]['id'].startswith('auto-')   # collect + restart (2 units)
    assert obj(st, 'building_2')['jobs'] == []                      # last unit: collect only
    assert st['inventory']['rye_flour'] == 1 and st['inventory']['rye'] == 50


def test_collect_without_inputs_just_collects():
    st = mills()
    st['inventory'] = {}
    shift = small_shift(st, 5)
    settle(st, T0 + 7200)
    assert shift['done'] == 2
    assert obj(st, FEED_ID)['jobs'] == [] and obj(st, 'building_2')['jobs'] == []
    assert st['inventory'] == {'hay': 2, 'rye_flour': 1}


def test_restart_without_collect_serves_the_workshop_that_frees_up_first():
    st = farm()
    busy = add_building(st, 'mill', 'a-busy', 0, 0, last_recipe='flour')
    soon = add_building(st, 'mill', 'b-soon', 4, 0, last_recipe='flour')
    idle = add_building(st, 'mill', 'z-idle', 8, 0, last_recipe='flour')
    busy['jobs'] = [dict(ready_job('flour', {'flour': 1}, 'jb'), ready_at=T0 + 900)]
    soon['jobs'] = [dict(ready_job('flour', {'flour': 1}, 'js'), ready_at=T0 + 300)]
    st['inventory'] = {'wheat': 100}
    small_shift(st, 2)
    settle(st, T0 + 61)
    assert len(idle['jobs']) == 2 and len(soon['jobs']) == 1 and len(busy['jobs']) == 1  # idle first, ties by id


def test_ordering_is_deterministic_and_independent_of_settle_frequency():
    one, two = mills(), mills()
    small_shift(one, 4)
    small_shift(two, 4)
    settle(one, T0 + 7200)
    for at in (T0 + 40, T0 + 100, T0 + 3000, T0 + 7200):
        settle(two, at)
    strip = lambda st: {k: v for k, v in st.items() if k not in {'events', 'market'}}
    assert strip(one) == strip(two)


def test_shift_event_reports_what_went_where_per_building():
    st = mills()
    small_shift(st, 4)
    settle(st, T0 + 7200)
    ev = next(e for e in st['events'] if e['kind'] == 'automation')
    assert 'Работа команды' in ev['text'] and 'на склад' in ev['text'] and 'поставлено' in ev['text']
    rows = {r['object']: r for r in ev['details']}
    assert rows['building_2']['carried'] == {'rye_flour': 1} and rows['building_2']['started'] == {'rye_flour': 1}
    assert rows[FEED_ID]['carried'] == {'hay': 2} and rows[FEED_ID]['started'] == {'hay': 1}
    assert rows['building_2']['type'] == 'mill' and rows['building_2']['worker'] == 'badger_artisan'
    assert 'Из кормоцеха на склад: сено ×2; поставлено: заготовить сено ×1.' in ev['text']
    assert 'Из мельницы на склад: ржаная мука ×1; поставлено: смолоть ржаную муку ×1.' in ev['text']
    assert 'ничего' not in ev['text']
    assert set(ev) >= {'at', 'text', 'kind'}  # old fields untouched


def test_non_craft_events_stay_plain():
    st = farm()
    add_plots(st, 2)
    hire_and_start(st, 'fox_picker', 'day')
    settle(st, T0 + 60)
    assert st['stats']['automation'] == 2
    assert all('details' not in e for e in st['events'])


def test_journal_grammar_for_restart_only_collect_only_and_unknown_types():
    from qw_farm.catalog import RECIPES
    from qw_farm.expansion import GENITIVE, craft_text
    assert craft_text([dict(type='mill', carried={}, started={'flour': 1})]) == ' Мельница — поставлено: смолоть муку ×1.'
    assert craft_text([dict(type='bakery', carried={'bread': 2}, started={})]) == ' Из пекарни на склад: хлеб ×2.'
    assert craft_text([dict(type='mystery', carried={'bread': 1}, started={})]) == ' Из постройки «mystery» на склад: хлеб ×1.'
    assert {r['building'] for r in RECIPES.values()} <= set(GENITIVE)   # every workshop type has its genitive
    assert craft_text([]) == ''
