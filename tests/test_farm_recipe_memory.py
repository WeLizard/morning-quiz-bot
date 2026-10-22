"""A workshop remembers a set of recipes (ordered, capped); the master and «repeat batches» rotate through it."""
from copy import deepcopy

from qw_farm.domain import project
from qw_farm.expansion import settle, upgrade_state

from tests.test_farm_automation_r7 import T0, add_building, cmd, err, farm, hire_and_start, obj


def queue(st, oid, recipe, at=T0):
    cmd(st, 'queue', {'object': oid, 'recipe': recipe}, at)


def bakery(**inventory):
    st = farm()
    add_building(st, 'bakery', 'b', 0, 0, level=4)   # 6 queue slots
    st['xp'] = 5000
    st['inventory'] = {'flour': 100, 'egg': 100, 'milk': 100, **inventory}
    return st


def test_manual_queue_builds_an_ordered_unique_memory_and_moves_repeats_to_the_end():
    st = bakery()
    for r in ('bread', 'bun', 'pancake'):
        queue(st, 'b', r)
    assert obj(st, 'b')['recipes_memory'] == ['bread', 'bun', 'pancake']
    queue(st, 'b', 'bread')
    assert obj(st, 'b')['recipes_memory'] == ['bun', 'pancake', 'bread'] and obj(st, 'b')['last_recipe'] == 'bread'


def test_memory_cap_is_the_queue_slot_count_and_drops_the_oldest():
    st = farm()
    add_building(st, 'mill', 'm', 0, 0)   # level 1: 3 queue slots
    st['inventory'] = {'wheat': 50, 'sunflower': 50}
    for r in ('flour', 'feed', 'oil'):
        queue(st, 'm', r)
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
    b = obj(st, 'b')
    b['jobs'].clear()
    hire_and_start(st, 'badger_artisan', 'day')
    st['helpers']['badger_artisan']['shift']['remaining'] = 3   # three restarts, nothing to collect
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
    assert 'recipes_memory' not in obj(st, 'n') and 'last_recipe' not in obj(st, 'n')   # untouched
    assert project(st, st, T0)['objects'][-1]['recipes_memory'] == []                   # the client always gets a list
    assert upgrade_state(deepcopy(st)) == st
    cmd(st, 'forget_recipe', {'object': 'm'})
    assert obj(st, 'm')['recipes_memory'] == [] and 'last_recipe' not in obj(st, 'm')


def test_cancel_keeps_the_memory_and_neighbours_see_none_of_it():
    st = bakery()
    queue(st, 'b', 'bread')
    cmd(st, 'cancel_job', {'object': 'b', 'job': obj(st, 'b')['jobs'][0]['id']}, T0 + 5)
    assert obj(st, 'b')['recipes_memory'] == ['bread']
    st['settings']['visibility'] = 'public'
    me = farm(fid='00000000-0000-0000-0000-00000000f002')
    seen = project(st, me, T0)['objects'][0]
    assert not {'recipes_memory', 'recipe_cursor', 'last_recipe'} & set(seen)
    assert project(st, st, T0)['objects'][0]['recipes_memory'] == ['bread']
