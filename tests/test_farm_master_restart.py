"""Team craft helpers reserve shift time and quota to collect every automatic restart."""
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


def test_small_quota_collects_finishing_jobs_without_leaving_uncollected_restarts():
    st = mills()
    shift = small_shift(st, 4)
    settle(st, T0 + 7200)
    assert shift['done'] == 4 and shift['remaining'] == 0
    assert obj(st, 'building_2')['jobs'] == [] and obj(st, FEED_ID)['jobs'] == []
    assert st['inventory']['rye_flour'] == 1 and st['inventory']['hay'] == 4


def test_collect_and_restart_cost_two_quota_units():
    st = mills()
    shift = small_shift(st, 2)
    settle(st, T0 + 7200)
    assert shift['done'] == 2 and shift['remaining'] == 0
    assert st['stats']['automation'] == 2
    assert obj(st, FEED_ID)['jobs'] == [] and obj(st, 'building_2')['jobs'] == []
    assert st['inventory']['hay'] == 2 and st['inventory']['clover'] == 50
    assert st['inventory']['rye_flour'] == 1


def test_quota_keeps_collect_slots_for_other_ready_workshops():
    st = mills()
    shift = small_shift(st, 3)
    settle(st, T0 + 7200)
    assert shift['done'] == 2 and shift['remaining'] == 1
    assert obj(st, FEED_ID)['jobs'] == [] and obj(st, 'building_2')['jobs'] == []
    assert st['inventory']['hay'] == 2 and st['inventory']['rye_flour'] == 1
    assert st['inventory']['clover'] == 50 and st['inventory']['rye'] == 50


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
    small_shift(st, 4)
    settle(st, T0 + 30)
    assert len(idle['jobs']) == 1 and len(soon['jobs']) == 1 and len(busy['jobs']) == 1
    assert idle['jobs'][0]['id'].startswith('auto-')  # earliest-free idle mill wins, but next collects stay reserved


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
    assert rows['building_2']['carried'] == {'rye_flour': 1} and rows['building_2']['started'] == {}
    assert rows[FEED_ID]['carried'] == {'hay': 4} and rows[FEED_ID]['started'] == {'hay': 1}
    assert rows['building_2']['type'] == 'mill' and rows['building_2']['worker'] == 'badger_artisan'
    assert 'Из кормоцеха на склад: сено ×4; поставлено: заготовить сено ×1.' in ev['text']
    assert 'Из мельницы на склад: ржаная мука ×1.' in ev['text']
    assert 'ничего' not in ev['text']
    assert set(ev) >= {'at', 'text', 'kind'}  # old fields untouched


def test_short_shift_does_not_start_oil_batch_that_cannot_be_collected():
    st = farm()
    mill = add_building(st, 'mill', 'oil-mill', 0, 0, last_recipe='oil', level=1)
    st['inventory'] = {'sunflower': 10}
    hire_and_start(st, 'badger_artisan', 'short')
    shift = st['helpers']['badger_artisan']['shift']

    settle(st, shift['until'])

    assert shift['status'] == 'finished'
    assert mill['jobs'] == []
    assert st['inventory'] == {'sunflower': 4, 'oil': 3}


def test_upkeep_debt_does_not_make_helper_preview_slower_than_its_actual_start():
    def run_with_debt(debt):
        st = farm()
        mill = add_building(st, 'mill', 'oil-mill', 0, 0, last_recipe='oil', level=1)
        st['inventory'] = {'sunflower': 10}
        st['economy']['debt'] = debt
        hire_and_start(st, 'badger_artisan', 'short')
        shift = st['helpers']['badger_artisan']['shift']
        settle(st, shift['until'])
        return shift['done'], st['inventory'], mill['jobs']

    assert run_with_debt(0) == run_with_debt(100)


def test_helper_repeats_when_batch_and_its_collect_fit_the_remaining_quota():
    st = farm()
    mill = add_building(st, 'mill', 'repeat-mill', 0, 0, last_recipe='rye_flour', level=1)
    mill['jobs'] = [ready_job('rye_flour', {'rye_flour': 1}, 'initial')]
    st['inventory'] = {'rye': 30}
    shift = small_shift(st, 6)

    settle(st, T0 + 1000)

    assert shift['done'] == 5 and shift['remaining'] == 1
    assert mill['jobs'] == []
    assert st['inventory']['rye_flour'] == 3


def test_two_remaining_actions_allow_a_batch_and_its_collect_when_they_fit():
    st = farm()
    mill = add_building(st, 'mill', 'boundary-mill', 0, 0, last_recipe='rye_flour', level=1)
    st['inventory'] = {'rye': 2}
    shift = small_shift(st, 2)

    settle(st, T0 + 240)

    assert shift['done'] == 2 and shift['remaining'] == 0
    assert mill['jobs'] == []
    assert st['inventory'] == {'rye': 0, 'rye_flour': 1}


def test_helper_skips_slow_infeasible_workshop_for_later_fast_one():
    st = farm()
    slow = add_building(st, 'bakery', 'a-slow', 0, 0, last_recipe='sponge_cake', level=1)
    fast = add_building(st, 'mill', 'b-fast', 4, 0, last_recipe='rye_flour', level=1)
    st['inventory'] = {'flour': 100, 'turkey_egg': 100, 'honey': 100, 'rye': 100}
    shift = hire_and_start(st, 'badger_artisan', 'short')['shift']
    shift['until'] = T0 + 900

    settle(st, shift['until'])

    assert shift['done'] > 0
    assert slow['jobs'] == []
    assert fast['jobs'] or st['inventory'].get('rye_flour', 0) > 0


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
