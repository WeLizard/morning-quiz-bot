"""Trip minigames (docs/tasks/FARM_TRIP_MINIGAMES.md): server replay, bonus cap, anti-cheat, compatibility."""
from copy import deepcopy
import json
import os
from pathlib import Path

import pytest

from qw_farm import trip_games as tg
from qw_farm.catalog import LEVELS, ROUTES, HELPERS
from qw_farm.domain import FarmError, apply, new_farm, validate_state
from qw_farm.expansion import upgrade_state

T0 = 1_800_000_000
n = [0]
ids = iter(range(1, 100000))


def farm(lv=10, coins=10 ** 6):
    f = upgrade_state(new_farm('00000000-0000-4000-8000-0000000000%02d' % next(ids), 'Trip', T0))
    f.update(xp=LEVELS[lv - 1], coins=coins, starter_credit=0)
    for item in ('wheat', 'bread', 'corn', 'carrot', 'oat_cookie'):
        f['inventory'][item] = 20
    return f


def cmd(f, kind, data, at=T0):
    n[0] += 1
    return apply(f, f, kind, data, at, f'tg{n[0]:06d}')


def start(f, route, guide='', at=T0):
    cmd(f, 'start_trip', dict(route=route, guide=guide), at)
    return f['trips'][-1]


def err(code, fn, *a, **k):
    with pytest.raises(FarmError) as e:
        fn(*a, **k)
    assert e.value.code == code, e.value.code


def perfect_fish_v1(plan):
    """v1: aim when the mark crosses the zone centre, strike in the middle of the window."""
    log, free = [], tg.FIRST_AIM_MS
    for cast in plan['casts']:
        aim = next(t for t in range(free, free + 4000) if abs(tg.mark_position(t, cast['phase']) - cast['zone']) <= 5)
        strike = aim + cast['wait'] + tg.REACT + plan['window'] // 2
        log.append([aim, strike])
        free = strike
    return log


def aim_at(plan, cast, free, near=5):
    return next(t for t in range(free, free + 6000)
                if abs(tg.mark_position(t, cast['phase'], plan['mark_period']) - cast['zone']) <= near)


def fight_toggles(fish, strike, hi=760, lo=450):
    """A player who watches the tension gauge: lets go at ``hi``, pulls again at ``lo``."""
    st, hold, toggles = tg.fight_start(), True, []
    while not st['end']:
        want = False if st['t'] >= hi else True if st['t'] <= lo else hold
        if want != hold and st['k']:                                  # no toggle inside the first tick
            toggles.append(strike + st['k'] * tg.TICK)
            hold = want
        tg.fight_step(st, fish, hold)
    return toggles


def play_fish(plan, bait='', hi=760, lo=450, delay=60, near=5, skip=()):
    """A good v2 log: accurate casts, a quick strike, a gauge-watching fight. ``skip``: casts without a strike."""
    casts, free = [], tg.FIRST_AIM_MS
    bait_wait, rare_add = tg.bait_spec(bait)
    for i, cast in enumerate(plan['casts']):
        aim = aim_at(plan, cast, free, near)
        if i in skip:
            entry = [aim, None, []]
        else:
            acc = tg.accuracy(aim, cast, plan['mark_period'])
            strike = tg.bite_at(plan, cast, aim, acc, bait_wait) + tg.REACT + delay
            entry = [aim, strike, fight_toggles(tg.hooked_fish(plan, cast, acc, rare_add), strike, hi, lo)]
        casts.append(entry)
        free = tg.eval_cast(plan, cast, *entry, bait)['free']
    return dict(v=2, bait=bait, casts=casts)


def perfect_fish(plan):
    return play_fish(plan)


def end_s(plan, log):
    return tg.fish_result(plan, log)['end'] // 1000 + 1


def golden(trip):
    """The reference walk of the actual plan (the server's own generator): reaches every golden item."""
    return tg.make_forage_plan(trip['game']['seed'], ROUTES[trip['route']], with_path=True)[1]


def best_walk(plan, limit=300000):
    """DFS for a good (not necessarily optimal) path; enough for tests."""
    items, traps = {int(k) for k in plan['items']}, set(plan['traps'])
    best = ['', -1]
    stack = [(plan['start'], '', 0, frozenset([plan['start']]), 0)]
    while stack and limit:
        limit -= 1
        cur, path, used, seen, got = stack.pop()
        if got > best[1]:
            best[:] = [path, got]
        if used >= plan['budget']:
            continue
        for ch, (dx, dy) in tg.DIRS.items():
            x, y = cur % plan['w'] + dx, cur // plan['w'] + dy
            if 0 <= x < plan['w'] and 0 <= y < plan['h']:
                c = y * plan['w'] + x
                new = c not in seen
                stack.append((c, path + ch, used + 1 + tg.TRAP_COST * (new and c in traps), seen | {c}, got + (new and c in items)))
    return best[0]


# ------------------------------------------------------------------------------------------------ plans
def test_solo_trip_gets_game_guide_trip_does_not():
    f = farm()
    trip = start(f, 'pond_bank')
    assert trip['game']['kind'] == 'fish' and trip['game']['state'] == 'open' and trip['game']['q'] == 1000
    assert len(trip['game']['plan']['casts']) == 4
    guide = next(h['id'] for h in HELPERS.values() if h['role'] == 'guide')
    g = farm()
    g['helpers'][guide] = dict(hired_at=T0)
    assert 'game' not in start(g, 'timber_path', guide=guide)


@pytest.mark.parametrize('route', list(ROUTES))
def test_plans_are_deterministic_and_consistent(route):
    f = farm()
    a = tg.make_game(f, 'c1', ROUTES[route], T0)
    assert a == tg.make_game(f, 'c1', ROUTES[route], T0)
    assert a != tg.make_game(f, 'c2', ROUTES[route], T0)
    plan = a['plan']
    if a['kind'] == 'fish':
        assert plan['v'] == 2 and len(plan['casts']) == tg.FISH_ROUTES[route]['casts']
        assert all(150 <= c['zone'] <= 850 and tg.WAIT2_MIN <= c['wait'] < tg.WAIT2_MIN + tg.WAIT2_SPAN and 0 <= c['roll'] < 1000
                   and all(150 < n <= 820 for n in c['nibbles']) and c['nibbles'] == sorted(c['nibbles']) for c in plan['casts'])
        assert {c['fish'][0]['id'] for c in plan['casts']} <= set(tg.FISH_ROUTES[route]['common'][i][0] for i in range(len(tg.FISH_ROUTES[route]['common'])))
        assert all(c['fish'][1]['id'] == tg.FISH_ROUTES[route]['rare'] for c in plan['casts'])
        for c in plan['casts']:
            for fish in c['fish']:
                sp = tg.SPECIES[fish['id']]
                assert sp['g'][0] <= fish['g'] <= sp['g'][1] and len(fish['pulls']) == tg.SEGMENTS
                assert all(any(lo <= p <= hi and tl <= t <= th for lo, hi, tl, th in sp['segs']) for t, p in fish['pulls'])
    else:
        assert plan['gold'] >= 1 and len(plan['traps']) == tg.TRAPS.get(route, tg.DEFAULT_TRAPS)
        assert not set(plan['traps']) & {int(k) for k in plan['items']} and plan['start'] not in plan['traps']
        assert tg.forage_score(plan, best_walk(plan)) is not None


@pytest.mark.parametrize('route', [r for r in ROUTES if r not in tg.FISH_ROUTES])
@pytest.mark.parametrize('seed', ['a', 'b', 'c', 'd', 'e'])
def test_reference_walk_is_reachable_and_perfect(route, seed):
    plan, moves = tg.make_forage_plan(seed, ROUTES[route], with_path=True)
    assert len(moves) == plan['budget'] and tg.forage_score(plan, moves) == 1000       # the golden walk reaches every golden item


# ------------------------------------------------------------------------------------------------ fishing v2
def test_perfect_fishing_gives_cap_bonus_outputs_and_journal():
    f = farm()
    trip = start(f, 'pond_bank')
    plan = trip['game']['plan']
    log = perfect_fish(plan)
    res = tg.fish_result(plan, log)
    cmd(f, 'trip_play', dict(trip=trip['id'], log=log), T0 + end_s(plan, log))
    game = trip['game']
    assert game['state'] == 'done' and game['score'] == res['score'] >= 950 and 1237 <= game['q'] <= 1250
    assert game['catch'] == res['catch'] and len(game['catch']) == 4 and game['bait'] == ''
    journal = f['fish_journal']
    assert sum(r['n'] for r in journal.values()) == 4
    for species, grams in game['catch']:
        assert journal[species]['g'] >= grams
    validate_state(f)
    before = f['inventory'].get('crucian', 0)
    cmd(f, 'collect_trip', dict(trip=trip['id']), T0 + 700)
    assert f['inventory']['crucian'] - before == 4 and trip['outputs']['crucian'] == 3     # +25 % of 3, half up
    assert not any(k in f['inventory'] for k in ('golden_crucian', 'tench', 'catfish'))    # rare fish are never items


def test_fishing_misses_score_zero_and_never_below_autopilot():
    f = farm()
    trip = start(f, 'pond_bank')
    plan = trip['game']['plan']
    log = play_fish(plan, skip=(0, 1, 2, 3))
    cmd(f, 'trip_play', dict(trip=trip['id'], log=log), T0 + end_s(plan, log))
    assert trip['game']['score'] == 0 and trip['game']['q'] == 1000 and trip['game']['catch'] == []
    assert not f.get('fish_journal')
    before = f['inventory'].get('crucian', 0)
    cmd(f, 'collect_trip', dict(trip=trip['id']), T0 + 700)
    assert f['inventory']['crucian'] - before == 3


def test_strike_window_timing_and_accuracy():
    bite = 2800
    assert tg.strike_timing(bite + tg.REACT - 1, bite, 900) == 0                # faster than a human: scared
    assert tg.strike_timing(bite + tg.REACT, bite, 900) == 1000                 # strike at once = best
    assert tg.strike_timing(bite + tg.REACT + 900, bite, 900) == 500
    assert tg.strike_timing(bite + tg.REACT + 901, bite, 900) == 0              # gone
    mark = tg.mark_position(800, 0, 1250)
    assert tg.accuracy(800, dict(phase=0, zone=mark), 1250) == 1000
    plan = dict(wait_pct=75, rare_chance=60)
    cast = dict(wait=2000, roll=100, fish=[dict(id='crucian'), dict(id='golden_crucian')])
    assert tg.bite_at(plan, cast, 1000, 1000, 70) == 1000 + tg.FLY_MS + 2000 * 75 // 100 * 70 // 100
    assert tg.bite_at(plan, cast, 1000, 600, 100) - tg.bite_at(plan, cast, 1000, 1000, 100) == 800   # a poor cast waits longer
    assert tg.hooked_fish(plan, cast, 1000, 0)['id'] == 'crucian'                # roll 100 >= 60 (this test plan)
    assert tg.hooked_fish(plan, cast, 1000, 90)['id'] == 'golden_crucian'        # corn: 100 < 150
    assert tg.hooked_fish(plan, cast, tg.RARE_ACC - 1, 90)['id'] == 'crucian'    # only to an accurate cast


def test_fight_model_rewards_reading_the_gauge():
    """Holding all the time lands a crucian but snaps a pike; a gauge-watching player lands both."""
    plan = tg.make_fish_plan('fight', 'river_bend', T0)
    crucian = tg._fish(tg._stream('x', 'y'), 'crucian')
    assert tg.fight(crucian, 0, []) [0] == 'land'
    pikes = [tg._fish(tg._stream(f'p{i}', 'y'), 'pike') for i in range(20)]
    assert sum(tg.fight(p, 0, [])[0] == 'snap' for p in pikes) >= 15
    assert sum(tg.fight(p, 0, fight_toggles(p, 0))[0] == 'land' for p in pikes) >= 17
    # letting go for good: the line goes slack or the fish takes it
    assert tg.fight(crucian, 0, [100])[0] in {'slack', 'escape'}
    end, ticks = tg.fight(crucian, 0, [])
    assert tg.fight_points(ticks, tg.SPECIES['crucian']['par']) == 1000
    assert tg.fight_points(tg.SPECIES['crucian']['par'] * 2, tg.SPECIES['crucian']['par']) == 700
    assert plan['v'] == 2


def test_lost_fish_gives_partial_points():
    f = farm()
    trip = start(f, 'river_bend')
    plan = trip['game']['plan']
    good = play_fish(plan)
    reckless = dict(good, casts=[[a, s, []] for a, s, _ in good['casts']])      # never lets go
    res = tg.fish_result(plan, reckless)
    assert any(c['result'] == 'snap' for c in res['casts'])
    for c in res['casts']:
        if c['result'] != 'land':
            assert 0 < c['points'] <= 300
    assert res['score'] < tg.fish_result(plan, good)['score']


def test_sky_and_baits_shape_the_plan():
    seen = set()
    for day in range(40):
        now = T0 + day * 86400
        for hour, tod in ((5, 'dawn'), (12, 'day'), (19, 'dusk'), (23, 'night'), (2, 'night')):
            at = now - (now + tg.TZ) % 86400 + hour * 3600
            sk = tg.sky(at)
            assert sk['tod'] == tod
            plan = tg.make_fish_plan('s', 'lake_inlet', at)
            seen.add(sk['weather'])
            assert plan['mark_period'] == (1250 if sk['weather'] == 'wind' else 1600)
            assert plan['wait_pct'] == tg.TOD_WAIT[tod] * (80 if sk['weather'] == 'rain' else 100) // 100
            assert plan['rare_chance'] == 25 + 15 * (sk['weather'] == 'cloud') + 20 * (tod == 'night')
    assert seen == set(tg.WEATHERS)
    assert tg.make_fish_plan('s', 'pond_bank', T0)['baits'] == ['bread', 'corn']
    assert tg.make_fish_plan('s', 'river_bend', T0)['baits'] == ['bread', 'crucian']


def test_bait_is_spent_once_and_must_be_in_stock():
    f = farm()
    trip = start(f, 'river_bend')
    plan = trip['game']['plan']
    log = play_fish(plan, bait='crucian')
    err('no_bait', cmd, f, 'trip_play', dict(trip=trip['id'], log=log), T0 + end_s(plan, log))
    assert trip['game']['state'] == 'open'
    f['inventory']['crucian'] = 2
    cmd(f, 'trip_play', dict(trip=trip['id'], log=log), T0 + end_s(plan, log))
    assert f['inventory']['crucian'] == 1 and trip['game']['bait'] == 'crucian'
    bad = dict(log, bait='corn')                                                  # corn is not a river bait
    g = farm()
    t2 = start(g, 'river_bend')
    err('bad_log', cmd, g, 'trip_play', dict(trip=t2['id'], log=dict(play_fish(t2['game']['plan']), bait='corn')), T0 + 300)
    assert bad['bait'] == 'corn'


def test_rare_fish_with_corn_goes_to_the_journal_only():
    for i in range(400):
        plan = tg.make_fish_plan(f'r{i}', 'pond_bank', T0)
        if any(c['roll'] < plan['rare_chance'] + 40 for c in plan['casts']) and not any(c['roll'] < plan['rare_chance'] for c in plan['casts']):
            break
    plain, corn = tg.fish_result(plan, play_fish(plan)), tg.fish_result(plan, play_fish(plan, bait='corn'))
    assert not any(tg.SPECIES[k]['rare'] for k, _ in plain['catch'])
    assert any(k == 'golden_crucian' for k, _ in corn['catch'])
    f = farm()
    tg.record_catch(f, corn['catch'])
    assert f['fish_journal']['golden_crucian']['n'] >= 1 and 'golden_crucian' not in f['inventory']


@pytest.mark.parametrize('mutate', [
    lambda log: dict(log, casts=log['casts'][:-1]),                                   # wrong number of casts
    lambda log: dict(log, v=1),
    lambda log: dict(log, v=True),
    lambda log: dict(log, extra=1),
    lambda log: dict(log, bait='pike'),                                              # not a bait of this place
    lambda log: dict(log, bait=None),
    lambda log: dict(log, casts=[[-5, 3000, []]] + log['casts'][1:]),                # negative
    lambda log: dict(log, casts=[[1.5, 3000, []]] + log['casts'][1:]),               # float
    lambda log: dict(log, casts=[[True, 3000, []]] + log['casts'][1:]),              # bool is not an int
    lambda log: dict(log, casts=[[log['casts'][0][0], log['casts'][0][0], []]] + log['casts'][1:]),   # strike not after aim
    lambda log: dict(log, casts=[[10 ** 9, 10 ** 9 + 1, []]] + log['casts'][1:]),    # beyond MAX_MS
    lambda log: dict(log, casts=[[100, 3000, []]] + log['casts'][1:]),               # aim before the first allowed moment
    lambda log: dict(log, casts=[log['casts'][0], [log['casts'][1][0] - 30000] + log['casts'][1][1:]] + log['casts'][2:]),  # overlap
    lambda log: dict(log, casts=[[log['casts'][0][0], None, [5000]]] + log['casts'][1:]),            # toggles without strike
    lambda log: dict(log, casts=[log['casts'][0][:2] + [[log['casts'][0][1] + 10]]] + log['casts'][1:]),   # toggle < 40 ms
    lambda log: dict(log, casts=[log['casts'][0][:2] + [[log['casts'][0][1] + 100, log['casts'][0][1] + 120]]] + log['casts'][1:]),
    lambda log: dict(log, casts=[log['casts'][0][:2] + [list(range(log['casts'][0][1] + 50, log['casts'][0][1] + 50 + 50 * 201, 50))]] + log['casts'][1:]),
    lambda log: dict(log, casts=[log['casts'][0][:2] + [[1.5]]] + log['casts'][1:]),
    lambda log: [[c[0], c[1]] for c in log['casts']],                                # a v1 log against a v2 plan
    lambda log: 'UDLR',
    lambda log: dict(log, casts=[[1, 2]] + log['casts'][1:]),
])
def test_fishing_rejects_bad_logs(mutate):
    f = farm()
    trip = start(f, 'pond_bank')
    log = perfect_fish(trip['game']['plan'])
    err('bad_log', cmd, f, 'trip_play', dict(trip=trip['id'], log=mutate(deepcopy(log))), T0 + 600)
    assert trip['game']['state'] == 'open' and not f.get('fish_journal')


def test_toggles_after_the_fight_are_ignored():
    plan = tg.make_fish_plan('late', 'pond_bank', T0)
    log = play_fish(plan)
    res = tg.fish_result(plan, log)
    entry = log['casts'][0]
    tail = max([entry[1]] + entry[2]) + 40
    late = deepcopy(log)
    late['casts'][0][2] = entry[2] + [max(tail, res['casts'][0]['end'] + 10)]
    assert tg.fish_result(plan, late)['score'] == res['score']


def test_fishing_cannot_outrun_the_clock():
    f = farm()
    trip = start(f, 'pond_bank')
    plan = trip['game']['plan']
    log = perfect_fish(plan)
    err('too_fast', cmd, f, 'trip_play', dict(trip=trip['id'], log=log), T0 + 5)       # the log lasts far longer than 5 s
    cmd(f, 'trip_play', dict(trip=trip['id'], log=log), T0 + end_s(plan, log))


def test_open_v1_fishing_game_is_upgraded_and_v1_score_still_works():
    f = farm()
    trip = start(f, 'lake_inlet')
    seed = trip['game']['seed']
    old = tg.make_fish_plan_v1(seed, 'lake_inlet')
    assert tg.fish_score(old, perfect_fish_v1(old)) >= 950 and tg.fish_score(old, perfect_fish(trip['game']['plan'])) is None
    trip['game']['plan'] = deepcopy(old)
    validate_state(f)
    upgrade_state(f)
    assert trip['game']['plan'] == tg.make_fish_plan(seed, 'lake_inlet', trip['started_at'])
    assert upgrade_state(deepcopy(f)) == f
    done = start(farm(), 'pond_bank')
    done['game'].update(state='done', plan=tg.make_fish_plan_v1(done['game']['seed'], 'pond_bank'), q=1100)
    holder = dict(trips=[done])
    tg.upgrade(holder)
    assert 'v' not in done['game']['plan']                                  # played v1 games keep their plan and q


def test_v1_game_without_upgrade_scores_by_v1_rules():
    f = farm()
    trip = start(f, 'pond_bank')
    trip['game']['plan'] = tg.make_fish_plan_v1(trip['game']['seed'], 'pond_bank')
    log = perfect_fish_v1(trip['game']['plan'])
    text = tg.apply_play(f, dict(trip=trip['id'], log=log), T0 + 3 + log[-1][1] // 1000)
    assert trip['game']['score'] >= 950 and 'Рыбалка сыграна' in text


def test_journal_validation():
    f = farm()
    f['fish_journal'] = {'pike': {'n': 2, 'g': 2400}}
    validate_state(f)
    for bad in ({'shark': {'n': 1, 'g': 1}}, {'pike': {'n': -1, 'g': 1}}, {'pike': {'n': 1}}, {'pike': {'n': 1.0, 'g': 1}}, []):
        f['fish_journal'] = bad
        with pytest.raises(FarmError):
            validate_state(f)


# ------------------------------------------------------------------------------------------------ foraging
def test_forage_best_walk_bonus_and_cap():
    f = farm()
    trip = start(f, 'timber_path')
    cmd(f, 'trip_play', dict(trip=trip['id'], log=golden(trip)), T0 + 100)
    game = trip['game']
    assert game['score'] == 1000 and game['q'] == 1250
    expected = tg.scaled_outputs(trip['outputs'], game['q'])['wood']
    assert expected == 5                                                 # 4 + 25 %
    before = f['inventory'].get('wood', 0)
    cmd(f, 'collect_trip', dict(trip=trip['id']), T0 + 400)
    assert f['inventory']['wood'] - before == expected


def test_forage_rules():
    plan = dict(w=6, h=6, start=30, budget=4, items={'24': 'a', '18': 'a'}, traps=[25], gold=2)
    assert tg.forage_score(plan, '') == 0
    assert tg.forage_score(plan, 'U') == 500
    assert tg.forage_score(plan, 'UU') == 1000
    assert tg.forage_score(plan, 'UUUU') == 1000
    assert tg.forage_score(plan, 'UR') == 500                           # trap on the 2nd step: 2 + 2 = whole budget
    assert tg.forage_score(plan, 'URL') is None                         # ... so a 3rd move is illegal
    assert tg.forage_score(plan, 'D') is None                           # outside the grid
    assert tg.forage_score(plan, 'UUUUU') is None                       # longer than the budget
    assert tg.forage_score(plan, 'Z') is None
    assert tg.forage_score(plan, ['U']) is None


def test_forage_too_fast_and_bad_path():
    f = farm()
    trip = start(f, 'timber_path')
    path = golden(trip)
    err('too_fast', cmd, f, 'trip_play', dict(trip=trip['id'], log=path), T0 + 1)
    err('bad_log', cmd, f, 'trip_play', dict(trip=trip['id'], log='D' * 3), T0 + 100)
    err('bad_log', cmd, f, 'trip_play', dict(trip=trip['id'], log=['U']), T0 + 100)
    err('bad_log', cmd, f, 'trip_play', dict(trip=trip['id'], log='U' * 99), T0 + 100)


# ------------------------------------------------------------------------------------------------ lifecycle / compatibility
def test_play_once_expiry_and_schema():
    f = farm()
    trip = start(f, 'timber_path')
    path = golden(trip)
    err('game_expired', cmd, f, 'trip_play', dict(trip=trip['id'], log=path), T0 + tg.GAME_TTL + 1)
    cmd(f, 'trip_play', dict(trip=trip['id'], log=path), T0 + tg.GAME_TTL)
    err('already_played', cmd, f, 'trip_play', dict(trip=trip['id'], log=path), T0 + tg.GAME_TTL + 1)
    err('not_found', cmd, f, 'trip_play', dict(trip='nope', log=path), T0 + 100)
    err('invalid_command', cmd, f, 'trip_play', dict(trip=trip['id']), T0 + 100)
    err('invalid_command', cmd, f, 'trip_play', dict(trip=trip['id'], log=path, q=1250), T0 + 100)


def test_unplayed_game_is_autopilot():
    f = farm()
    trip = start(f, 'timber_path')
    cmd(f, 'collect_trip', dict(trip=trip['id']), T0 + 400)
    assert f['inventory']['wood'] == 4


def test_abort_uses_base_outputs():
    f = farm()
    trip = start(f, 'timber_path')
    cmd(f, 'trip_play', dict(trip=trip['id'], log=golden(trip)), T0 + 100)
    assert tg.final_outputs(trip)['wood'] == 5
    cmd(f, 'abort_trip', dict(trip=trip['id']), T0 + 150)               # 150 / 300 of the base 4 * 0.5 = 1
    assert f['inventory'].get('wood', 0) == 1 and not f['trips']


def test_old_trip_without_game_still_works():
    f = farm()
    trip = start(f, 'timber_path')
    del trip['game']
    validate_state(f)
    err('no_game', cmd, f, 'trip_play', dict(trip=trip['id'], log=''), T0 + 100)
    cmd(f, 'collect_trip', dict(trip=trip['id']), T0 + 400)
    assert f['inventory']['wood'] == 4


def test_validate_state_rejects_corrupt_game():
    f = farm()
    trip = start(f, 'timber_path')
    validate_state(f)
    trip['game']['q'] = 2000
    with pytest.raises(FarmError):
        validate_state(f)


@pytest.mark.parametrize('q,base,expected', [(1250, 3, 4), (1250, 5, 6), (1250, 4, 5), (1250, 8, 10), (1250, 2, 3), (1125, 3, 3),
                                             (1125, 8, 9), (1000, 7, 7), (1250, 1, 1)])
def test_scaled_outputs_table(q, base, expected):
    assert tg.scaled_outputs({'x': base}, q) == {'x': expected}
    assert expected <= base + -(-base // 4)                              # never above base + ceil(base / 4)


def test_public_rules_shipped_and_json_safe():
    assert json.dumps(tg.public_rules()) and tg.public_rules()['bonus'] == 250
    json.dumps(tg.make_game(farm(), 'x', ROUTES['night_glade'], T0))


# ------------------------------------------------------------------------------------------------ JS parity fixture
FIXTURE = Path(__file__).resolve().parent / 'fixtures' / 'farm_trip_games' / 'games.json'


def fixture_data():
    cases, plans = [], {}
    hours = (5 * 3600, 12 * 3600, 19 * 3600, 23 * 3600)
    for route in ('pond_bank', 'lake_inlet', 'river_bend'):
        rare = next(f'r{k}' for k in range(1000) if any(c['roll'] < 25 + 40 for c in tg.make_fish_plan(f'r{k}', route, T0)['casts']))
        for i, seed in enumerate(('s1', 's2', 's3', rare)):
            at = T0 if seed == rare else T0 - (T0 + tg.TZ) % 86400 + hours[i % 4] + 86400 * i
            plan = tg.make_fish_plan(seed, route, at)
            plans[f'{route}/{seed}'] = plan
            perfect = perfect_fish(plan)
            bait = plan['baits'][-1]
            baited = play_fish(plan, bait=bait)
            hold = dict(perfect, casts=[[a, s, []] for a, s, _ in perfect['casts']])
            sloppy = play_fish(plan, hi=900, lo=300, delay=400, near=120)
            letgo = play_fish(plan, hi=0, lo=-1)                                       # lets go at once and never pulls
            early = dict(perfect, casts=[[a, a + 300, []] for a, _, _ in perfect['casts']])
            miss = play_fish(plan, skip=tuple(range(len(plan['casts']))))
            short = dict(perfect, casts=perfect['casts'][:-1])
            fast = deepcopy(perfect)
            fast['casts'][0][2] = [fast['casts'][0][1] + 20]
            for name, log in (('perfect', perfect), ('baited', baited), ('hold', hold), ('sloppy', sloppy), ('letgo', letgo),
                              ('early', early), ('miss', miss), ('short', short), ('fast_toggle', fast),
                              ('v1', [[c[0], c[1]] for c in perfect['casts']]), ('bad_bait', dict(perfect, bait='wheat'))):
                res = tg.fish_result(plan, log)
                cases.append(dict(kind='fish', name=f'{route}/{seed}/{name}', plan_ref=f'{route}/{seed}', log=log, score=tg.fish_score(plan, log),
                                  results=None if res is None else [[c['result'], c['points'], c['end'], c['free'],
                                                                     c['fish'] and c['fish']['id']] for c in res['casts']],
                                  catch=None if res is None else res['catch']))
    for route in ('timber_path', 'mushroom_wood', 'herb_meadow', 'old_grove', 'night_glade'):
        for seed in ('s1', 's2', 's3'):
            plan, moves = tg.make_forage_plan(seed, ROUTES[route], with_path=True)
            for name, log in (('golden', moves), ('empty', ''), ('half', moves[:len(moves) // 2]), ('best', best_walk(plan, 60000)),
                              ('off', 'D' * 2), ('long', moves + 'U'), ('bad', 'UX')):
                cases.append(dict(kind='forage', name=f'{route}/{seed}/{name}', plan=plan, log=log, score=tg.forage_score(plan, log)))
    return dict(rules=tg.public_rules(), cases=cases, plans=plans,
                outputs=[dict(q=q, base={'x': b}, out=tg.scaled_outputs({'x': b}, q)) for q in (1000, 1060, 1125, 1250) for b in (1, 2, 3, 4, 5, 6, 8)])


def test_js_fixture_is_current():
    data = json.loads(json.dumps(fixture_data()))
    if os.getenv('FARM_TRIPS_WRITE_FIXTURES'):
        FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE.write_text(json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(',', ':')) + '\n', encoding='utf-8')
    assert json.loads(FIXTURE.read_text(encoding='utf-8')) == data, 'regenerate with FARM_TRIPS_WRITE_FIXTURES=1'
    assert any(c['score'] == 1000 for c in data['cases'] if c['kind'] == 'forage') and any(c['score'] is None for c in data['cases'])
