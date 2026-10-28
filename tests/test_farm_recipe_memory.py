"""A workshop remembers a set of recipes (ordered, capped); the master and «repeat batches» rotate through it."""
from copy import deepcopy

from qw_farm.domain import project
from qw_farm.expansion import WORKSHOP_TYPES, restartable, settle, upgrade_state
from qw_farm.catalog import ITEMS, RECIPES, level as farm_level

from tests.test_farm_automation_r7 import T0, add_building, cmd, err, farm, hire_and_start, obj


def queue(st, oid, recipe, at=T0):
    cmd(st, 'queue', {'object': oid, 'recipe': recipe}, at)


def repeat(st, oid, recipe, enabled=True, at=T0):
    return cmd(st, 'set_recipe_repeat', {'object': oid, 'recipe': recipe, 'enabled': enabled}, at)


def bakery(**inventory):
    st = farm()
    add_building(st, 'bakery', 'b', 0, 0, level=4)   # 6 queue slots
    st['xp'] = 5000
    st['inventory'] = {'flour': 100, 'egg': 100, 'milk': 100, **inventory}
    return st


def test_manual_queue_defaults_to_one_shot_and_repeat_is_explicit():
    st = bakery()
    for r in ('bread', 'bun', 'pancake'):
        queue(st, 'b', r)
    assert obj(st, 'b').get('recipes_memory', []) == []
    for r in ('bread', 'bun', 'pancake'):
        repeat(st, 'b', r)
    assert obj(st, 'b')['recipes_memory'] == ['bread', 'bun', 'pancake']
    repeat(st, 'b', 'bread')  # explicit on is idempotent
    assert obj(st, 'b')['recipes_memory'] == ['bread', 'bun', 'pancake'] and obj(st, 'b')['last_recipe'] == 'pancake'


def test_memory_cap_is_the_queue_slot_count_and_drops_the_oldest():
    st = farm()
    add_building(st, 'mill', 'm', 0, 0)   # level 1: 3 queue slots
    st['inventory'] = {'wheat': 50, 'sunflower': 50}
    for r in ('flour', 'feed', 'oil'):
        queue(st, 'm', r)
        repeat(st, 'm', r)
    assert obj(st, 'm')['recipes_memory'] == ['flour', 'feed', 'oil']
    obj(st, 'm')['jobs'].clear()
    obj(st, 'm')['recipe_cursor'] = 2
    st['xp'] = 5000
    # a fourth distinct mill recipe is not in the catalog at this level, so simulate with a repeat + forced overflow
    obj(st, 'm')['recipes_memory'] = ['flour', 'feed', 'oil']
    from qw_farm.expansion import remember_recipe
    remember_recipe(obj(st, 'm'), 'mixedfeed')
    assert obj(st, 'm')['recipes_memory'] == ['feed', 'oil', 'mixedfeed']
    assert obj(st, 'm')['recipe_cursor'] == 1 and obj(st, 'm')['recipes_memory'][1] == 'oil'   # still points at oil


def test_master_cycles_through_the_remembered_recipes():
    st = bakery()
    for r in ('bread', 'bun', 'pancake'):
        queue(st, 'b', r)
        repeat(st, 'b', r)
    b = obj(st, 'b')
    b['jobs'].clear()
    hire_and_start(st, 'badger_artisan', 'day')
    shift = st['helpers']['badger_artisan']['shift']
    shift['remaining'] = 6   # three starts plus three future collections
    shift['quota'] = 6
    settle(st, T0 + 61)
    assert [j['recipe'] for j in b['jobs']] == ['bread', 'bun', 'pancake'] and b['recipe_cursor'] == 0


def test_rotation_skips_recipes_without_ingredients_and_restart_all_follows_the_same_order():
    st = bakery(egg=0)
    queue(st, 'b', 'bread')
    b = obj(st, 'b')
    b['jobs'].clear()
    b['recipes_memory'] = ['bun', 'bread']   # bun needs an egg: skipped
    cmd(st, 'restart_all', {'area': None})
    assert [j['recipe'] for j in b['jobs']] == ['bread'] and b['recipe_cursor'] == 0
    st['inventory']['egg'] = 5
    b['jobs'].clear()
    cmd(st, 'restart_all', {'area': None})
    assert [j['recipe'] for j in b['jobs']] == ['bun']     # the cursor was after bread, so it wraps to bun
    b['jobs'].clear()
    cmd(st, 'restart_all', {'area': None})
    assert [j['recipe'] for j in b['jobs']] == ['bread']


def test_rotation_is_independent_of_settle_frequency():
    def build():
        st = bakery()
        for r in ('bread', 'bun', 'pancake'):
            queue(st, 'b', r)
            repeat(st, 'b', r)
        obj(st, 'b')['jobs'].clear()
        hire_and_start(st, 'badger_artisan', 'day')
        st['helpers']['badger_artisan']['shift']['remaining'] = 5
        return st
    one, two = build(), build()
    settle(one, T0 + 7200)
    for at in (T0 + 40, T0 + 100, T0 + 3000, T0 + 7200):
        settle(two, at)
    strip = lambda st: {k: v for k, v in st.items() if k not in {'events', 'market'}}
    assert strip(one) == strip(two)


def test_forget_one_recipe_keeps_the_others_and_validates():
    st = bakery()
    for r in ('bread', 'bun', 'pancake'):
        queue(st, 'b', r)
        repeat(st, 'b', r)
    b = obj(st, 'b')
    b['recipe_cursor'] = 2
    text = cmd(st, 'forget_recipe', {'object': 'b', 'recipe': 'bun'})
    assert b['recipes_memory'] == ['bread', 'pancake'] and b['last_recipe'] == 'pancake' and 'забыт' in text
    assert b['recipe_cursor'] == 1 and b['recipes_memory'][1] == 'pancake'   # still points at pancake
    assert err(st, 'forget_recipe', {'object': 'b', 'recipe': 'bun'}) == 'no_recipe'
    assert err(st, 'forget_recipe', {'object': 'b', 'recipe': 'flour'}) == 'wrong_recipe'   # a mill recipe
    assert err(st, 'forget_recipe', {'object': 'b', 'recipe': 5}) == 'wrong_recipe'
    cmd(st, 'forget_recipe', {'object': 'b'})   # legacy: the most recent
    assert b['recipes_memory'] == ['bread'] and b['last_recipe'] == 'bread'
    cmd(st, 'forget_recipe', {'object': 'b'})
    assert b['recipes_memory'] == [] and 'last_recipe' not in b
    assert err(st, 'forget_recipe', {'object': 'b'}) == 'no_recipe'


def test_cancel_and_forget_works_for_any_queued_job_not_only_the_latest():
    st = bakery()
    for r in ('bread', 'bun', 'pancake'):
        queue(st, 'b', r)
        repeat(st, 'b', r)
    first = obj(st, 'b')['jobs'][0]
    text = cmd(st, 'cancel_job_and_forget_recipe', {'object': 'b', 'job': first['id']}, T0 + 5)
    assert 'Рецепт забыт' in text and obj(st, 'b')['recipes_memory'] == ['bun', 'pancake']
    assert [j['recipe'] for j in obj(st, 'b')['jobs']] == ['bun', 'pancake']


def test_old_single_recipe_state_migrates_and_keeps_last_recipe():
    st = farm()
    add_building(st, 'mill', 'm', 0, 0)
    add_building(st, 'mill', 'n', 4, 0)
    obj(st, 'm')['last_recipe'] = 'flour'   # the old save: one remembered recipe, no memory fields
    for o in st['objects']:
        o.pop('recipes_memory', None)
        o.pop('recipe_cursor', None)
    upgrade_state(st)
    assert obj(st, 'm')['recipes_memory'] == ['flour'] and obj(st, 'm')['last_recipe'] == 'flour'
    assert 'recipes_memory' not in obj(st, 'n') and 'last_recipe' not in obj(st, 'n')
    assert 'recipes_memory' not in project(st, st, T0)['objects'][-1]                  # projection preserves the saved shape
    assert upgrade_state(deepcopy(st)) == st
    cmd(st, 'forget_recipe', {'object': 'm'})
    assert obj(st, 'm')['recipes_memory'] == [] and 'last_recipe' not in obj(st, 'm')


def test_cancel_keeps_the_memory_and_neighbours_see_none_of_it():
    st = bakery()
    queue(st, 'b', 'bread')
    repeat(st, 'b', 'bread')
    cmd(st, 'cancel_job', {'object': 'b', 'job': obj(st, 'b')['jobs'][0]['id']}, T0 + 5)
    assert obj(st, 'b')['recipes_memory'] == ['bread']
    st['settings']['visibility'] = 'public'
    me = farm(fid='00000000-0000-0000-0000-00000000f002')
    seen = project(st, me, T0)['objects'][0]
    assert not {'recipes_memory', 'recipe_cursor', 'last_recipe'} & set(seen)
    assert project(st, st, T0)['objects'][0]['recipes_memory'] == ['bread']


def test_queuing_new_recipes_does_not_enable_repeat_or_clear_existing_choices():
    st = bakery()
    queue(st, 'b', 'bread')
    repeat(st, 'b', 'bread')
    queue(st, 'b', 'bun')
    b = obj(st, 'b')
    assert b['recipes_memory'] == ['bread'] and all(j['manual'] for j in b['jobs'])
    b['jobs'].clear()                                   # everything finished and collected
    queue(st, 'b', 'pancake')
    assert b['recipes_memory'] == ['bread'] and b['last_recipe'] == 'bread'
    queue(st, 'b', 'bun')                               # pancake still queued: same setup
    queue(st, 'b', 'pancake')
    assert b['recipes_memory'] == ['bread']


def test_master_repeats_exactly_the_last_setup():
    st = bakery()
    queue(st, 'b', 'bread')
    b = obj(st, 'b')
    repeat(st, 'b', 'bread')
    b['jobs'].clear()
    queue(st, 'b', 'pancake')
    b['jobs'].clear()
    hire_and_start(st, 'badger_artisan', 'day')
    shift = st['helpers']['badger_artisan']['shift']
    shift['remaining'] = 4   # two starts plus two future collections
    shift['quota'] = 4
    settle(st, T0 + 61)
    assert [j['recipe'] for j in b['jobs']] == ['bread', 'bread'] and b['recipes_memory'] == ['bread']


def test_automation_jobs_neither_start_a_setup_nor_count_as_manual():
    st = bakery()
    queue(st, 'b', 'bread')
    repeat(st, 'b', 'bread')
    b = obj(st, 'b')
    b['jobs'].clear()
    hire_and_start(st, 'badger_artisan', 'day')
    # A single remaining action cannot start a job that also needs a future collection.
    limited = deepcopy(st)
    limited_shift = limited['helpers']['badger_artisan']['shift']
    limited_shift['remaining'] = 1
    limited_shift['quota'] = 1
    settle(limited, T0 + 61)
    assert not obj(limited, 'b')['jobs']

    shift = st['helpers']['badger_artisan']['shift']
    shift['remaining'] = 2
    shift['quota'] = 2
    settle(st, T0 + 61)
    assert b['jobs'] and not any(j.get('manual') for j in b['jobs'])
    assert b['recipes_memory'] == ['bread']             # the automation did not touch the repeat setting
    queue(st, 'b', 'pancake')                           # only automation jobs in the queue: a new setup
    assert b['recipes_memory'] == ['bread']


def test_old_jobs_without_the_flag_are_manual_unless_their_id_is_automatic():
    from qw_farm.expansion import has_manual_job, is_manual_job
    assert is_manual_job({'id': 'cmd-1'}) and not is_manual_job({'id': 'auto-3-1'})
    assert is_manual_job({'id': 'auto-x', 'manual': True}) and not is_manual_job({'id': 'c', 'manual': False})
    assert has_manual_job({'jobs': [{'id': 'auto-1-1'}, {'id': 'old'}]}) and not has_manual_job({'jobs': [{'id': 'auto-1-1'}]})
    st = bakery()
    queue(st, 'b', 'bread')
    b = obj(st, 'b')
    b['recipes_memory'] = ['bread', 'bun']              # old save: accumulated memory is kept as the current setup
    for j in b['jobs']:
        j.pop('manual')
    queue(st, 'b', 'pancake')                           # a new queue item does not implicitly change repeat settings
    assert b['recipes_memory'] == ['bread', 'bun']
    b['jobs'].clear()
    queue(st, 'b', 'bun')
    assert b['recipes_memory'] == ['bread', 'bun']


def test_repeat_switch_is_explicit_idempotent_and_checks_workshop_recipe_and_capacity():
    st = bakery()
    queue(st, 'b', 'bread')
    assert err(st, 'set_recipe_repeat', {'object': 'b', 'recipe': 'pie', 'enabled': True}) == 'no_job'
    assert err(st, 'set_recipe_repeat', {'object': 'b', 'recipe': 'flour', 'enabled': True}) == 'wrong_recipe'
    assert err(st, 'set_recipe_repeat', {'object': 'b', 'recipe': 'bread', 'enabled': 1}) == 'invalid_command'
    rev = obj(st, 'b')['revision']
    repeat(st, 'b', 'bread')
    assert obj(st, 'b')['recipes_memory'] == ['bread'] and obj(st, 'b')['revision'] == rev + 1
    repeat(st, 'b', 'bread')
    assert obj(st, 'b')['revision'] == rev + 1
    repeat(st, 'b', 'bread', False)
    assert obj(st, 'b')['recipes_memory'] == []
    repeat(st, 'b', 'bread', False)  # repeated explicit off is safe
    assert obj(st, 'b')['recipes_memory'] == []

    # A full repeat roster is never silently evicted when another recipe is enabled.
    bakery_obj = obj(st, 'b')
    bakery_obj.update(level=4, recipes_memory=['bread', 'bun', 'pancake', 'pie', 'oat_cookie', 'forest_pie'],
                      last_recipe='forest_pie', recipe_cursor=0,
                      jobs=[{'id': 'candidate', 'recipe': 'sponge_cake'}])
    assert err(st, 'set_recipe_repeat', {'object': 'b', 'recipe': 'sponge_cake', 'enabled': True}) == 'repeat_limit'
    assert bakery_obj['recipes_memory'] == ['bread', 'bun', 'pancake', 'pie', 'oat_cookie', 'forest_pie']


def test_recipe_repeat_command_covers_every_production_building():
    for building in WORKSHOP_TYPES:
        recipe = next((r for r in RECIPES.values()
                       if r['building'] == building and not r.get('scroll') and not r.get('teach')), None)
        assert recipe is not None, f'{building} needs a repeatable base recipe for this generic feature'
        st = farm()
        st['xp'] = 10**9
        st['inventory'] = {item: 100_000 for item in ITEMS}
        add_building(st, building, 'workshop', 0, 0, level=4)
        queue(st, 'workshop', recipe['id'])
        repeat(st, 'workshop', recipe['id'])
        obj(st, 'workshop')['jobs'].clear()
        assert restartable(st, obj(st, 'workshop'), farm_level(st['xp']))['id'] == recipe['id'], building


def test_repeat_can_be_disabled_while_a_batch_runs_and_worker_does_not_restart_it():
    st = bakery(wheat=10)
    queue(st, 'b', 'bread')
    repeat(st, 'b', 'bread')
    hire_and_start(st, 'badger_artisan', 'day')
    repeat(st, 'b', 'bread', False, T0 + 1)
    settle(st, T0 + 7200)
    assert obj(st, 'b')['jobs'] == []
    assert st['inventory']['bread'] == 1 and st['inventory']['flour'] == 98
    assert obj(st, 'b')['recipes_memory'] == []


def test_animal_autorepeat_defaults_off_for_new_purchase_but_on_for_legacy_houses():
    st = farm()
    add_building(st, 'coop', 'new-coop', 0, 0)
    st['inventory'] = {'feed': 20}
    cmd(st, 'buy_animal', {'object': 'new-coop', 'animal': 'chicken'})
    assert obj(st, 'new-coop')['animal_repeat'] is False
    hire_and_start(st, 'cat_keeper', 'day')
    settle(st, T0 + 7200)
    assert obj(st, 'new-coop')['animal_job'] is None and st['inventory'] == {'feed': 20}

    legacy = farm()
    add_building(legacy, 'coop', 'old-coop', 0, 0, animal='chicken')
    legacy['inventory'] = {'feed': 20}
    assert 'animal_repeat' not in obj(legacy, 'old-coop')
    hire_and_start(legacy, 'cat_keeper', 'day')
    settle(legacy, T0 + 7200)
    assert legacy['inventory'].get('egg', 0) > 0


def test_new_farm_starter_chickens_have_repeat_off():
    from qw_farm.domain import new_farm
    st = new_farm('00000000-0000-0000-0000-00000000f105', 'Новая', T0)
    coop = next(o for o in st['objects'] if o['type'] == 'coop')
    assert coop['animal'] == 'chicken' and coop['animal_repeat'] is False
    own_view = project(st, st, T0)
    assert next(o for o in own_view['objects'] if o['type'] == 'coop')['animal_repeat'] is False


def test_animal_autorepeat_switch_still_collects_current_job_and_manual_feed_ignores_switch():
    st = farm()
    add_building(st, 'coop', 'c', 0, 0, animal='chicken')
    st['inventory'] = {'feed': 10}
    cmd(st, 'set_animal_repeat', {'object': 'c', 'enabled': False})
    cmd(st, 'set_animal_repeat', {'object': 'c', 'enabled': False})
    assert obj(st, 'c')['animal_repeat'] is False
    cmd(st, 'feed', {'object': 'c'})  # explicit player action still starts one batch
    hire_and_start(st, 'cat_keeper', 'day')
    settle(st, T0 + 7200)
    assert obj(st, 'c')['animal_job'] is None
    assert st['inventory'].get('egg') == 2 and st['inventory'].get('feed') == 9

    cmd(st, 'feed', {'object': 'c'})
    cmd(st, 'set_animal_repeat', {'object': 'c', 'enabled': True})
    cmd(st, 'start_shift', {'worker': 'cat_keeper', 'shift': 'day'}, T0 + 7200)
    settle(st, T0 + 7500)
    assert obj(st, 'c')['animal_job'] is not None
    assert st['inventory'].get('egg') >= 4

    manual = farm()
    add_building(manual, 'coop', 'manual-coop', 0, 0, animal='chicken')
    manual['inventory'] = {'feed': 3}
    cmd(manual, 'set_animal_repeat', {'object': 'manual-coop', 'enabled': False})
    cmd(manual, 'feed_all', {'area': None})
    assert obj(manual, 'manual-coop')['animal_job'] is not None
    assert manual['inventory']['feed'] == 2


def test_animal_repeat_command_rejects_non_animal_and_invalid_boolean_and_stays_private():
    st = farm()
    add_building(st, 'coop', 'c', 0, 0, animal='chicken')
    add_building(st, 'mill', 'm', 4, 0)
    assert err(st, 'set_animal_repeat', {'object': 'm', 'enabled': True}) == 'wrong_object'
    assert err(st, 'set_animal_repeat', {'object': 'c', 'enabled': 'false'}) == 'invalid_command'
    st['settings']['visibility'] = 'public'
    other = farm(fid='00000000-0000-0000-0000-00000000f002')
    visitor_coop = next(o for o in project(st, other, T0)['objects'] if o['id'] == 'c')
    assert 'animal_repeat' not in visitor_coop
