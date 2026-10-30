"""Лесоруб Степан, «Лесная тропа» со Степаном, вылазка «Делянка» и мини-игра «Валка» (docs/tasks/FARM_LUMBERJACK.md)."""
from copy import deepcopy
import json
import os
from pathlib import Path

import pytest

from qw_farm import trip_games as tg
from qw_farm.catalog import LEVELS, ROUTES, HELPERS, ITEMS
from qw_farm.domain import FarmError, apply, new_farm, validate_state
from qw_farm.expansion import upgrade_state

T0 = 1_800_000_000
n = [0]
ids = iter(range(1, 100000))


def farm(lv=10, coins=10 ** 6, hire=True):
    f = upgrade_state(new_farm('00000000-0000-4000-8000-0000000001%02d' % next(ids), 'Lumber', T0))
    f.update(xp=LEVELS[lv - 1], coins=coins, starter_credit=0)
    for item in ('bread', 'wheat', 'carrot'):
        f['inventory'][item] = 20
    if hire:
        cmd(f, 'hire_helper', dict(helper='lumberjack'))
    return f


def cmd(f, kind, data, at=T0):
    n[0] += 1
    return apply(f, f, kind, data, at, f'lj{n[0]:06d}')


def start(f, route, guide='', at=T0):
    cmd(f, 'start_trip', dict(route=route, guide=guide), at)
    return f['trips'][-1]


def err(code, fn, *a, **k):
    with pytest.raises(FarmError) as e:
        fn(*a, **k)
    assert e.value.code == code, e.value.code
    return e.value


def play(f, trip, log, at):
    return cmd(f, 'trip_play', dict(trip=trip['id'], log=log), at)


# ------------------------------------------------------------------------------------------------ a reference player
def mini(tree, aim, want):
    """Drive one tree: ``want(k, prog, heat, stalled, pinched)`` -> hold? Returns the toggles (a mirror of the rules, for the tests only)."""
    start_ms = aim + tg.CUT_DELAY
    toggles, hold, prog, heat, stalled = [start_ms], True, 0, 0, False
    for k in range(tg.MAX_TREE_TICKS + 1):
        pinched = tg.fell_pinched(tree, k * tg.TICK)
        if k:
            w = want(k, prog, heat, stalled, pinched)
            if w != hold:
                toggles.append(start_ms + k * tg.TICK)
                hold = w
        if not hold and prog >= tg.fell_hinge(tree):
            break
        if hold:
            if stalled:
                prog += tg.STALL_RATE
            else:
                prog += tg.CUT_RATE
                heat += tg.HEAT_UP * (tg.PINCH_MULT if pinched else 1)
                if heat >= tg.HEAT_MAX:
                    heat, stalled = tg.HEAT_MAX, True
            if prog >= tree['girth']:
                break
        elif not stalled:
            heat = max(0, heat - tg.COOL)
    return toggles


def clean(tree):
    return lambda k, prog, heat, stalled, pinched: not pinched and prog < tg.fell_hinge(tree)


def aim_for(tree, free, good=True):
    """First aim time >= free where the mark is dead centre (good) or far outside the gap (not good)."""
    for t in range(free, free + 6000):
        d = abs(tg.mark_position(t, tree['phase'], tg.FELL_PERIOD) - tree['gap_center'])
        if (good and d <= 5) or (not good and d >= tree['gap_width'] + 20):
            return t
    raise AssertionError('no aim')


def fell_log(plan, want=clean, good=True, idle=False):
    entries, free = [], tg.FIRST_AIM_MS
    for tree in plan['trees']:
        aim = aim_for(tree, free, good)
        toggles = [] if idle else mini(tree, aim, want(tree))
        entries.append([aim, toggles])
        free = tg.fell_tree(tree, aim, toggles)['free']
    return dict(v=1, trees=entries)


def elapsed_for(plan, log):
    return tg.fell_result(plan, log)['end'] // 1000 + 3


# ------------------------------------------------------------------------------------------------ hiring and the Timber path
def test_lumberjack_is_a_guide_with_its_own_bonus_and_the_others_do_not_change():
    h = HELPERS['lumberjack']
    assert (h['name'], h['role'], h['specialty'], h['cost'], h['level'], h['icon'], h['bonus']) == \
        ('Лесоруб Степан', 'guide', 'wood', 180, 5, 'helper_lumberjack', 1)
    assert 'бензопил' in h['description']
    for key in ('hedgehog', 'squirrel'):
        assert 'bonus' not in HELPERS[key] or HELPERS[key]['bonus'] == 1
    assert sum(1 for x in HELPERS.values() if x['role'] == 'guide') == 3


def test_hire_level_and_price():
    low = farm(lv=4, hire=False)
    err('locked', cmd, low, 'hire_helper', dict(helper='lumberjack'))
    f = farm(lv=5, coins=179, hire=False)
    err('insufficient_coins', cmd, f, 'hire_helper', dict(helper='lumberjack'))
    f['coins'] = 200
    cmd(f, 'hire_helper', dict(helper='lumberjack'))
    assert f['coins'] == 20 and 'lumberjack' in f['helpers']
    err('guide', cmd, f, 'start_shift', dict(worker='lumberjack', shift='short'))      # a guide has no work shift


def test_timber_path_with_stepan_is_faster_and_gives_one_more():     # +1 like every guide (owner's principle 2026-10-29: by hand is better)
    f = farm()
    base = start(farm(hire=False), 'timber_path')
    trip = start(f, 'timber_path', guide='lumberjack')
    assert base['outputs'] == {'wood': 4} and trip['outputs'] == {'wood': 5}
    assert trip['ready_at'] - trip['started_at'] == 240 and base['ready_at'] - base['started_at'] == 300
    assert 'game' not in trip and 'helper' not in trip


def test_other_guides_keep_plus_one():
    f = farm()
    for hid in ('hedgehog', 'squirrel'):
        cmd(f, 'hire_helper', dict(helper=hid))
    assert start(f, 'mushroom_wood', guide='hedgehog')['outputs'] == {'mushroom': 4, 'chanterelle': 1}
    assert start(f, 'berry_edge', guide='squirrel')['outputs'] == {'wildberry': 5, 'blackberry': 1}
    g = farm()
    cmd(g, 'hire_helper', dict(helper='hedgehog'))
    assert start(g, 'timber_path', guide='hedgehog')['outputs'] == {'wood': 4}            # not its specialty: no bonus
    assert start(g, 'timber_path', guide='lumberjack')['outputs'] == {'wood': 5}


# ------------------------------------------------------------------------------------------------ the route and the two ways to send
def test_route_definition():
    r = ROUTES['logging_plot']
    assert (r['name'], r['level'], r['seconds'], r['cost'], r['inputs'], r['outputs'], r['xp'], r['specialty'], r['icon']) == \
        ('Делянка', 6, 1200, 12, {'bread': 1}, {'wood': 10}, 18, 'wood', 'logging_plot')
    assert r['kind'] == r['category'] == 'forest' and r['helper'] == 'lumberjack'
    assert 'description' in r and 'ельник' in r['description']


def test_plot_needs_stepan_hired_level_and_free():
    err('helper_needed', start, farm(hire=False), 'logging_plot')
    err('helper_needed', start, farm(hire=False), 'logging_plot', 'lumberjack')
    err('locked', start, farm(lv=5), 'logging_plot')
    f = farm()
    cmd(f, 'hire_helper', dict(helper='hedgehog'))
    err('wrong_guide', start, f, 'logging_plot', 'hedgehog')
    start(f, 'timber_path', guide='lumberjack')                    # Stepan is away as a guide
    err('guide_busy', start, f, 'logging_plot')
    err('guide_busy', start, f, 'logging_plot', 'lumberjack')
    g = farm()
    start(g, 'logging_plot')                                       # Stepan lends the saw to the player
    err('guide_busy', start, g, 'logging_plot', 'lumberjack')
    err('guide_busy', start, g, 'timber_path', 'lumberjack')
    err('guide_busy', start, g, 'logging_plot')
    err('trip_active', start, g, 'timber_path')
    cmd(g, 'hire_helper', dict(helper='hedgehog'))
    start(g, 'mushroom_wood', guide='hedgehog')                    # the second slot still works with other guides
    err('trip_limit', start, g, 'berry_edge', 'hedgehog')


def test_plot_costs_bread_and_coins_and_collect_pays_xp():
    f = farm()
    bread, coins, xp = f['inventory']['bread'], f['coins'], f['xp']
    trip = start(f, 'logging_plot')
    assert f['inventory']['bread'] == bread - 1 and f['coins'] == coins - 12
    err('not_ready', cmd, f, 'collect_trip', dict(trip=trip['id']), T0 + 1199)
    cmd(f, 'collect_trip', dict(trip=trip['id']), T0 + 1200)
    assert f['inventory']['wood'] == 10 and f['xp'] > xp and ROUTES['logging_plot']['xp'] == trip['xp'] == 18 and not f['trips']
    validate_state(f)


def test_manual_plot_has_a_felling_game_and_stepan_is_busy_until_collected():
    f = farm()
    trip = start(f, 'logging_plot')
    assert trip['guide'] == '' and trip['helper'] == 'lumberjack' and trip['ready_at'] - T0 == 1200
    g = trip['game']
    assert g['kind'] == 'fell' and g['state'] == 'open' and g['q'] == 1000 and g['plan']['v'] == 1 and len(g['plan']['trees']) == 5
    cmd(f, 'collect_trip', dict(trip=trip['id']), T0 + 1200)
    start(f, 'timber_path', guide='lumberjack', at=T0 + 1300)     # free again


def test_sent_stepan_is_base_without_a_game_and_twenty_percent_faster():
    f = farm()
    trip = start(f, 'logging_plot', guide='lumberjack')
    assert trip['guide'] == 'lumberjack' and 'game' not in trip and 'helper' not in trip
    assert trip['outputs'] == {'wood': 10}                              # no guide bonus on the plot: the saw game pays
    assert trip['ready_at'] - T0 == 960
    err('no_game', play, f, trip, dict(v=1, trees=[]), T0 + 5)
    err('guide_busy', start, f, 'logging_plot', 'lumberjack')
    start(f, 'timber_path', at=T0 + 1)                                    # the player's own slot stays free
    cmd(f, 'collect_trip', dict(trip=trip['id']), T0 + 960)
    assert f['inventory']['wood'] == 10


# ------------------------------------------------------------------------------------------------ the plan
def test_plan_is_deterministic_and_in_range():
    a, b = tg.make_fell_plan('seed-1'), tg.make_fell_plan('seed-1')
    assert a == b and a != tg.make_fell_plan('seed-2')
    assert a['v'] == 1 and a['mark_period'] == tg.FELL_PERIOD and len(a['trees']) == 5
    json.dumps(a)
    for k in range(60):
        for t in tg.make_fell_plan(f'p{k}')['trees']:
            assert set(t) == {'gap_center', 'gap_width', 'phase', 'girth', 'pinches', 'par'}
            assert 200 <= t['gap_center'] <= 800 and 140 <= t['gap_width'] <= 220 and 0 <= t['phase'] < tg.FELL_PERIOD
            assert 800 <= t['girth'] <= 1200 and t['girth'] % 50 == 0 and 2 <= len(t['pinches']) <= 3
            assert t['pinches'] == sorted(t['pinches']) and t['pinches'][0] >= 500
            assert all(b - a >= tg.PINCH_MS + 300 for a, b in zip(t['pinches'], t['pinches'][1:]))
            assert t['par'] == tg.fell_par(t) and t['par'] > tg.PAR_SLACK


def test_game_seed_comes_from_the_trip():
    f = farm()
    a = tg.make_game(f, 'c1', ROUTES['logging_plot'], T0)
    assert a == tg.make_game(f, 'c1', ROUTES['logging_plot'], T0) and a['plan'] != tg.make_game(f, 'c2', ROUTES['logging_plot'], T0)['plan']
    assert a['kind'] == 'fell' and a['plan'] == tg.make_fell_plan(a['seed'])


def test_public_rules_describe_felling():
    r = tg.public_rules()['fell']
    assert r['tick'] == 50 and r['bonus'] == 600 and r['trees'] == 5 and r['hinge_pct'] == 80 and r['period'] == 2100


# ------------------------------------------------------------------------------------------------ the replay
def test_perfect_play_is_x16():
    f = farm()
    trip = start(f, 'logging_plot')
    plan = trip['game']['plan']
    log = fell_log(plan)
    res = tg.fell_result(plan, log)
    assert res['score'] == 1000 and all(r['result'] == 'felled' and not r['stalled'] and r['acc'] == 1000 for r in res['trees'])
    text = play(f, trip, log, T0 + elapsed_for(plan, log))
    assert 'Валка сыграна' in text and 'древесине' in text and 'Древесина +6' in text
    assert trip['game']['state'] == 'done' and trip['game']['q'] == 1600 and trip['game']['score'] == 1000
    assert [t['result'] for t in trip['game']['trees']] == ['felled'] * 5
    cmd(f, 'collect_trip', dict(trip=trip['id']), T0 + 1200)
    assert f['inventory']['wood'] == 16
    validate_state(f)


def test_not_playing_is_base_and_idle_log_scores_nothing():
    f = farm()
    trip = start(f, 'logging_plot')
    cmd(f, 'collect_trip', dict(trip=trip['id']), T0 + 1200)
    assert f['inventory']['wood'] == 10
    g = farm()
    trip = start(g, 'logging_plot')
    plan = trip['game']['plan']
    log = fell_log(plan, good=False, idle=True)
    assert tg.fell_result(plan, log)['score'] == 0
    play(g, trip, log, T0 + elapsed_for(plan, log))
    assert trip['game']['q'] == 1000
    cmd(g, 'collect_trip', dict(trip=trip['id']), T0 + 1200)
    assert g['inventory']['wood'] == 10


def test_idle_with_a_good_aim_only_pays_the_aim():
    plan = tg.make_fell_plan('idle')
    res = tg.fell_result(plan, fell_log(plan, idle=True))
    assert res['score'] == 400 and all(r['result'] == 'idle' and r['cut'] == 0 for r in res['trees'])


def test_holding_all_the_way_stalls_the_saw_and_cuts_through():
    plan = tg.make_fell_plan('stall')
    always = lambda tree: (lambda k, prog, heat, stalled, pinched: True)
    log = fell_log(plan, always)
    res = tg.fell_result(plan, log)
    for r, tree in zip(res['trees'], plan['trees']):
        assert r['stalled'] and r['result'] == 'cut_through' and r['cut'] == 0 and r['points'] == 400
        assert r['ticks'] > tree['par']
    assert res['score'] == 400


def test_stalled_but_released_at_the_hinge_is_capped_and_slow():
    tree = tg.make_fell_plan('stall2')['trees'][0]

    def want(k, prog, heat, stalled, pinched):                 # ignores the grip, lets go at the hinge
        return prog < tg.fell_hinge(tree)

    aim = aim_for(tree, 500)
    toggles = mini(tree, aim, want)
    r = tg.fell_tree(tree, aim, toggles)
    assert r['stalled'] and r['result'] == 'felled' and r['cut'] <= tg.STALL_CAP and r['acc'] == 1000
    assert r['points'] == (4000 + 6 * r['cut']) // 10
    assert r['ticks'] > tree['par']


def test_cutting_the_hinge_through_costs_accuracy_points():
    tree = tg.make_fell_plan('hinge')['trees'][1]
    aim = aim_for(tree, 500)
    good = tg.fell_tree(tree, aim, mini(tree, aim, clean(tree)))
    through = tg.fell_tree(tree, aim, mini(tree, aim, lambda k, prog, heat, stalled, pinched: not pinched))
    assert good['result'] == 'felled' and good['cut'] == 1000
    assert through['result'] == 'cut_through' and not through['stalled'] and through['cut'] <= 1000 - tg.PREMATURE_PEN
    assert through['points'] < good['points']


def test_missing_the_gap_gives_no_accuracy_but_the_cut_still_counts():
    tree = tg.make_fell_plan('miss')['trees'][2]
    aim = aim_for(tree, 500, good=False)
    r = tg.fell_tree(tree, aim, mini(tree, aim, clean(tree)))
    assert r['acc'] == 0 and r['cut'] == 1000 and r['points'] == 600


def test_accuracy_falls_linearly_to_the_edge_of_the_gap():
    tree = dict(gap_center=500, gap_width=150, phase=0, girth=1000, pinches=[], par=50)
    seen = {}
    for t in range(0, tg.FELL_PERIOD):
        seen.setdefault(abs(tg.mark_position(t, 0, tg.FELL_PERIOD) - 500), tg.fell_accuracy(t, tree))
    assert seen[0] == 1000 and seen[tg.FELL_DEAD] == 1000 and seen[150] == 0 and seen[200] == 0
    assert 0 < seen[100] < 1000 and seen[75] > seen[100] > seen[125]


def test_stopping_before_the_hinge_is_a_timeout():
    tree = tg.make_fell_plan('timeout')['trees'][0]
    aim = aim_for(tree, 500)
    start_ms = aim + tg.CUT_DELAY
    r = tg.fell_tree(tree, aim, [start_ms, start_ms + 200])
    assert r['result'] == 'timeout' and r['cut'] == 0 and r['end'] == start_ms + r['ticks'] * tg.TICK


def test_trailing_toggles_after_the_fall_are_ignored():
    plan = tg.make_fell_plan('trail')
    log = fell_log(plan)
    base = tg.fell_result(plan, log)
    entry = log['trees'][0]
    entry[1].append(entry[1][-1] + 40)                         # a finger lifted a moment later
    assert tg.fell_result(plan, log)['score'] == base['score']


@pytest.mark.parametrize('mutate', [
    lambda log: dict(log, v=2),
    lambda log: dict(log, v=True),
    lambda log: dict(log, extra=1),
    lambda log: {'v': 1},
    lambda log: [],
    lambda log: 'x',
    lambda log: dict(log, trees=log['trees'][:-1]),
    lambda log: dict(log, trees=log['trees'] + [[9000, []]]),
    lambda log: dict(log, trees=[[1, []]] + log['trees'][1:]),                         # aim before FIRST_AIM_MS
    lambda log: dict(log, trees=[[log['trees'][0][0] + 0.5, log['trees'][0][1]]] + log['trees'][1:]),
    lambda log: dict(log, trees=[[True, []]] + log['trees'][1:]),
    lambda log: dict(log, trees=[[600, [600]]] + log['trees'][1:]),                    # press sooner than CUT_DELAY after the aim
    lambda log: dict(log, trees=[[600, [850, 860]]] + log['trees'][1:]),               # toggles faster than TOGGLE_GAP
    lambda log: dict(log, trees=[[600, [850, 800]]] + log['trees'][1:]),               # not increasing
    lambda log: dict(log, trees=[[600, [850] + [900 + 50 * i for i in range(tg.MAX_FELL_TOGGLES)]]] + log['trees'][1:]),
    lambda log: dict(log, trees=[[600, [-5]]] + log['trees'][1:]),
    lambda log: dict(log, trees=[[600, ['850']]] + log['trees'][1:]),
    lambda log: dict(log, trees=[[600, 850]] + log['trees'][1:]),
    lambda log: dict(log, trees=[[600]] + log['trees'][1:]),
    lambda log: dict(log, trees=[[tg.MAX_MS + 1, []]] + log['trees'][1:]),
    lambda log: dict(log, trees=[log['trees'][1]] + [log['trees'][0]] + log['trees'][2:]),   # the second tree starts before the first one fell
    lambda log: dict(log, trees=[None] + log['trees'][1:]),
])
def test_illegal_logs_are_rejected_with_a_clear_error(mutate):
    f = farm()
    trip = start(f, 'logging_plot')
    plan = trip['game']['plan']
    log = mutate(deepcopy(fell_log(plan)))
    assert tg.fell_result(plan, log) is None
    e = err('bad_log', play, f, trip, log, T0 + 600)
    assert e.status == 422 and 'Недопустимая запись' in str(e)
    assert trip['game']['state'] == 'open'                    # a rejected log does not spend the game


def test_game_is_played_once_in_time_and_not_faster_than_the_clock():
    f = farm()
    trip = start(f, 'logging_plot')
    plan = trip['game']['plan']
    log = fell_log(plan)
    need_s = tg.fell_result(plan, log)['end'] // 1000
    err('too_fast', play, f, trip, log, T0 + need_s - 3)
    assert trip['game']['state'] == 'open'
    play(f, trip, log, T0 + need_s)
    err('already_played', play, f, trip, log, T0 + need_s + 1)
    g = farm()
    trip = start(g, 'logging_plot')
    err('game_expired', play, g, trip, fell_log(trip['game']['plan']), T0 + tg.GAME_TTL + 1)


def test_other_trips_keep_their_small_bonus_and_cap():
    assert tg.quality(1000) == 1250 and tg.quality(1000, 'fish') == 1250 and tg.quality(1000, 'forage') == 1250
    assert tg.quality(1000, 'fell') == 1600 and tg.quality(500, 'fell') == 1300 and tg.quality(0, 'fell') == 1000
    assert tg.scaled_outputs({'wood': 10}, 1600) == {'wood': 16} and tg.scaled_outputs({'wood': 10}, 1300) == {'wood': 13}


# ------------------------------------------------------------------------------------------------ saves
def test_validation_of_old_and_new_saves():
    f = farm()
    trip = start(f, 'logging_plot')
    validate_state(f)
    bad = deepcopy(f)
    bad['trips'][0]['game']['q'] = 1601
    err('invalid_trips', validate_state, bad)
    forage = farm()
    t2 = start(forage, 'timber_path')
    t2['game']['q'] = 1300                                     # only felling may go above +250
    err('invalid_trips', validate_state, forage)
    old = farm(hire=False)
    cmd(old, 'hire_helper', dict(helper='hedgehog'))
    start(old, 'pond_bank')
    start(old, 'mushroom_wood', guide='hedgehog', at=T0 + 1)                         # an ordinary save with no lumberjack at all stays valid
    validate_state(old)
    assert trip['game']['plan']['v'] == 1


def test_existing_trip_without_helper_field_still_collects():
    f = farm()
    trip = start(f, 'timber_path', guide='lumberjack')
    trip.pop('helper', None)
    cmd(f, 'collect_trip', dict(trip=trip['id']), T0 + 300)
    assert f['inventory']['wood'] == 5


# ------------------------------------------------------------------------------------------------ JS parity fixture
FIXTURE = Path(__file__).resolve().parent / 'fixtures' / 'farm_trip_games' / 'fell.json'


def fixture_data():
    cases, plans = [], {}
    for seed in ('f1', 'f2', 'f3'):
        plan = tg.make_fell_plan(seed)
        plans[seed] = plan
        t0 = plan['trees'][0]
        a0 = aim_for(t0, tg.FIRST_AIM_MS)
        logs = dict(
            perfect=fell_log(plan),
            miss=fell_log(plan, good=False),
            idle=fell_log(plan, idle=True),
            hold=fell_log(plan, lambda tree: (lambda k, prog, heat, stalled, pinched: True)),
            through=fell_log(plan, lambda tree: (lambda k, prog, heat, stalled, pinched: not pinched)),
            stalled_release=fell_log(plan, lambda tree: (lambda k, prog, heat, stalled, pinched: prog < tg.fell_hinge(tree))),
            stopped=dict(v=1, trees=[[a0, [a0 + tg.CUT_DELAY, a0 + tg.CUT_DELAY + 200]]] + fell_log(plan)['trees'][1:]),
            fast_toggle=dict(v=1, trees=[[a0, [a0 + tg.CUT_DELAY, a0 + tg.CUT_DELAY + 10]]] + fell_log(plan)['trees'][1:]),
            bad_version=dict(fell_log(plan), v=2),
        )
        for name, log in logs.items():
            res = tg.fell_result(plan, log)
            cases.append(dict(name=f'{seed}/{name}', plan_ref=seed, log=log, score=None if res is None else res['score'],
                              end=None if res is None else res['end'],
                              trees=None if res is None else [[r['acc'], r['cut'], r['points'], r['result'], r['stalled'], r['ticks'],
                                                                r['end'], r['free']] for r in res['trees']]))
    return dict(rules=tg.public_rules()['fell'], plans=plans, cases=cases)


def test_js_fixture_is_current():
    data = json.loads(json.dumps(fixture_data()))
    if os.getenv('FARM_TRIPS_WRITE_FIXTURES'):
        FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE.write_text(json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(',', ':')) + '\n', encoding='utf-8')
    assert json.loads(FIXTURE.read_text(encoding='utf-8')) == data, 'regenerate with FARM_TRIPS_WRITE_FIXTURES=1'
    scores = {c['name'].split('/')[1]: c['score'] for c in data['cases'] if c['name'].startswith('f1/')}
    assert scores['perfect'] == 1000 and scores['bad_version'] is None and scores['fast_toggle'] is None
    assert scores['idle'] < scores['miss'] or scores['idle'] <= 400
    assert 0 <= scores['hold'] < 500


def test_fell_replay_uses_the_period_of_the_plan_the_player_saw():
    """A run started before the aim was slowed (plan mark_period 1400) is replayed with 1400, not the current FELL_PERIOD."""
    plan = tg.make_fell_plan('period-check')
    old = dict(plan, mark_period=1400)
    tree = old['trees'][0]
    aim = next(t for t in range(tg.FIRST_AIM_MS, tg.FIRST_AIM_MS + 6000)
               if abs(tg.mark_position(t, tree['phase'], 1400) - tree['gap_center']) <= 5
               and abs(tg.mark_position(t, tree['phase'], tg.FELL_PERIOD) - tree['gap_center']) > tree['gap_width'])
    assert tg.fell_accuracy(aim, tree, 1400) == 1000 and tg.fell_accuracy(aim, tree) < 1000
    assert tg.fell_tree(tree, aim, [], old['mark_period'])['acc'] == 1000
