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


def perfect_fish(plan):
    """Aim when the mark crosses the zone centre, strike in the middle of the window."""
    log, free = [], tg.FIRST_AIM_MS
    for cast in plan['casts']:
        aim = next(t for t in range(free, free + 4000) if abs(tg.mark_position(t, cast['phase']) - cast['zone']) <= 5)
        strike = aim + cast['wait'] + tg.REACT + plan['window'] // 2
        log.append([aim, strike])
        free = strike
    return log


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
    assert len(trip['game']['plan']['casts']) == 3
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
        assert len(plan['casts']) == tg.CASTS[route]
        assert all(150 <= c['zone'] <= 850 and tg.WAIT_MIN <= c['wait'] < tg.WAIT_MIN + tg.WAIT_SPAN for c in plan['casts'])
    else:
        assert plan['gold'] >= 1 and len(plan['traps']) == tg.TRAPS.get(route, tg.DEFAULT_TRAPS)
        assert not set(plan['traps']) & {int(k) for k in plan['items']} and plan['start'] not in plan['traps']
        assert tg.forage_score(plan, best_walk(plan)) is not None


@pytest.mark.parametrize('route', [r for r in ROUTES if r not in tg.CASTS])
@pytest.mark.parametrize('seed', ['a', 'b', 'c', 'd', 'e'])
def test_reference_walk_is_reachable_and_perfect(route, seed):
    plan, moves = tg.make_forage_plan(seed, ROUTES[route], with_path=True)
    assert len(moves) == plan['budget'] and tg.forage_score(plan, moves) == 1000       # the golden walk reaches every golden item


# ------------------------------------------------------------------------------------------------ fishing
def test_perfect_fishing_gives_cap_and_bonus_outputs():
    f = farm()
    trip = start(f, 'pond_bank')
    cmd(f, 'trip_play', dict(trip=trip['id'], log=perfect_fish(trip['game']['plan'])), T0 + 90)
    assert trip['game']['state'] == 'done' and trip['game']['score'] >= 950
    assert 1237 <= trip['game']['q'] <= 1250
    before = f['inventory'].get('crucian', 0)
    cmd(f, 'collect_trip', dict(trip=trip['id']), T0 + 700)
    assert f['inventory']['crucian'] - before == 4 and trip['outputs']['crucian'] == 3     # +25 % of 3, half up


def test_fishing_misses_score_zero_and_never_below_autopilot():
    f = farm()
    trip = start(f, 'pond_bank')
    log = [[tg.FIRST_AIM_MS + i * 20000, None] for i in range(3)]
    cmd(f, 'trip_play', dict(trip=trip['id'], log=log), T0 + 120)
    assert trip['game']['score'] == 0 and trip['game']['q'] == 1000
    before = f['inventory'].get('crucian', 0)
    cmd(f, 'collect_trip', dict(trip=trip['id']), T0 + 700)
    assert f['inventory']['crucian'] - before == 3


def test_strike_and_aim_rules():
    bite = 2800
    assert tg.strike_score(bite, bite, 900) == 0                       # at the bite: faster than a human
    assert tg.strike_score(bite + tg.REACT - 1, bite, 900) == 0
    assert tg.strike_score(bite + tg.REACT + 901, bite, 900) == 0      # too late
    assert tg.strike_score(bite + tg.REACT + 450, bite, 900) == 1000
    assert 0 < tg.strike_score(bite + tg.REACT, bite, 900) < 1000
    mark = tg.mark_position(800, 0)
    assert tg.accuracy(800, dict(phase=0, zone=mark, wait=2000)) == 1000
    far = 0 if mark > 500 else 1000
    assert tg.accuracy(800, dict(phase=0, zone=far, wait=2000)) < 1000


@pytest.mark.parametrize('mutate', [
    lambda log: log[:-1],                                              # wrong number of casts
    lambda log: [[-5, 3000]] + log[1:],                                # negative
    lambda log: [[1.5, 3000]] + log[1:],                               # float
    lambda log: [[True, 3000]] + log[1:],                              # bool is not an int
    lambda log: [[log[0][0], log[0][0]]] + log[1:],                    # strike not after the aim
    lambda log: [[10 ** 9, 10 ** 9 + 1]] + log[1:],                    # beyond MAX_MS
    lambda log: [[100, log[0][1]]] + log[1:],                          # aim before the first allowed moment
    lambda log: 'UDLR',
    lambda log: [log[0], [log[1][0] - 100000, log[1][1]]] + log[2:],   # next cast overlaps the previous one
    lambda log: [[1, 2, 3]] + log[1:],
])
def test_fishing_rejects_bad_logs(mutate):
    f = farm()
    trip = start(f, 'pond_bank')
    log = perfect_fish(trip['game']['plan'])
    err('bad_log', cmd, f, 'trip_play', dict(trip=trip['id'], log=mutate(deepcopy(log))), T0 + 600)
    assert trip['game']['state'] == 'open'


def test_fishing_cannot_outrun_the_clock():
    f = farm()
    trip = start(f, 'pond_bank')
    log = perfect_fish(trip['game']['plan'])
    err('too_fast', cmd, f, 'trip_play', dict(trip=trip['id'], log=log), T0 + 5)       # the log lasts far longer than 5 s
    cmd(f, 'trip_play', dict(trip=trip['id'], log=log), T0 + 3 + log[-1][1] // 1000)


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
    cases = []
    for route in ('pond_bank', 'lake_inlet', 'river_bend'):
        for seed in ('s1', 's2'):
            plan = tg.make_fish_plan(seed, route)
            perfect = perfect_fish(plan)
            late = [[a, a + c['wait'] + tg.REACT + plan['window'] + 5] for (a, _), c in zip(perfect, plan['casts'])]
            early = [[a, a + 300] for a, _ in perfect]
            edge = [[a, a + c['wait'] + tg.REACT] for (a, _), c in zip(perfect, plan['casts'])]
            miss = [[a, None] for a, _ in perfect]
            for name, log in (('perfect', perfect), ('late', late), ('early', early), ('edge', edge), ('miss', miss),
                              ('short', perfect[:-1]), ('float', [[1.5, 3000]] + perfect[1:]), ('aim_early', [[10, 4000]] + perfect[1:])):
                cases.append(dict(kind='fish', name=f'{route}/{seed}/{name}', plan=plan, log=log, score=tg.fish_score(plan, log)))
    for route in ('timber_path', 'mushroom_wood', 'herb_meadow', 'old_grove', 'night_glade'):
        for seed in ('s1', 's2', 's3'):
            plan, moves = tg.make_forage_plan(seed, ROUTES[route], with_path=True)
            for name, log in (('golden', moves), ('empty', ''), ('half', moves[:len(moves) // 2]), ('best', best_walk(plan, 60000)),
                              ('off', 'D' * 2), ('long', moves + 'U'), ('bad', 'UX')):
                cases.append(dict(kind='forage', name=f'{route}/{seed}/{name}', plan=plan, log=log, score=tg.forage_score(plan, log)))
    return dict(rules=tg.public_rules(), cases=cases,
                outputs=[dict(q=q, base={'x': b}, out=tg.scaled_outputs({'x': b}, q)) for q in (1000, 1060, 1125, 1250) for b in (1, 2, 3, 4, 5, 6, 8)])


def test_js_fixture_is_current():
    data = json.loads(json.dumps(fixture_data()))
    if os.getenv('FARM_TRIPS_WRITE_FIXTURES'):
        FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE.write_text(json.dumps(data, indent=1, sort_keys=True) + '\n', encoding='utf-8')
    assert json.loads(FIXTURE.read_text(encoding='utf-8')) == data, 'regenerate with FARM_TRIPS_WRITE_FIXTURES=1'
    assert any(c['score'] == 1000 for c in data['cases'] if c['kind'] == 'forage') and any(c['score'] is None for c in data['cases'])
