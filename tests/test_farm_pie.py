import json
from pathlib import Path

import pytest

from domain import farm_pie as pie

FIXTURES = json.loads((Path(__file__).parent / 'fixtures' / 'farm_pie.json').read_text(encoding='utf-8'))


def test_shared_fixtures_match_the_js_replay():
    for fixture in FIXTURES:
        assert pie.make_plan(fixture['seed']) == fixture['plan']
        assert pie.replay(fixture['plan'], fixture['log']) == dict(
            height=fixture['height'], tower=fixture['tower'], miss=fixture['miss'], taps=fixture['taps'])
        assert pie.log_valid(fixture['plan'], fixture['log'])


def test_plan_is_deterministic_and_seeded():
    assert pie.make_plan('seed') == pie.make_plan('seed')
    assert pie.make_plan('seed') != pie.make_plan('other')
    plan = pie.make_plan('seed')
    assert 0 <= plan['phase'] < plan['t0']
    assert plan['limit_ms'] == 60000 and plan['fall_ms'] == 320 and plan['min_gap_ms'] == 400 and plan['warmup_ms'] == 700


def test_crane_reaches_both_ends_and_speeds_up():
    plan = pie.make_plan('crane')
    xs = {pie.crane_x(plan, t, 0) for t in range(plan['warmup_ms'], plan['warmup_ms'] + plan['t0'])}
    assert min(xs) == plan['x0'] and max(xs) == plan['x1']
    slow = pie.crane_x(plan, 0, 0)
    fast = pie.crane_x(plan, 0, 40)
    assert fast != slow


def test_drop_cuts_the_overhang_and_misses_a_narrow_tower():
    lo, hi = pie.TOWER_CENTER - pie.BASE // 2, pie.TOWER_CENTER + pie.BASE // 2
    assert pie.drop(lo, hi, 500, pie.BASE) == (lo, hi)
    assert pie.drop(lo, hi, 860, pie.BASE) == (580, hi)
    assert pie.drop(580, 780, 140, pie.BASE) is None


def test_empty_log_keeps_the_full_tower():
    plan = pie.make_plan('empty')
    assert pie.replay(plan, []) == dict(
        height=0, tower=[pie.TOWER_CENTER - pie.BASE // 2, pie.TOWER_CENTER + pie.BASE // 2], miss=False, taps=0)


def test_limit_ignores_late_taps_and_log_validation():
    plan = pie.make_plan('limit')
    assert pie.replay(plan, [0, 60000])['taps'] == 2
    assert pie.replay(plan, [0, 60001])['taps'] == 1
    assert pie.log_valid(plan, [0, 60000])
    assert not pie.log_valid(plan, [0, 60001])
    assert pie.log_valid(plan, [])
    assert not pie.log_valid(plan, [0, 399])
    assert pie.log_valid(plan, [0, 400])
    for bad in ([True], [1.5], ['10'], [-1]):
        assert not pie.log_valid(plan, bad)
    assert not pie.log_valid(plan, [0] * (plan['max_taps'] + 1))


def test_miss_fixture_stops_the_run():
    fixture = next(f for f in FIXTURES if f['miss'])
    assert fixture['height'] == 1 and fixture['taps'] == 2
    result = pie.replay(fixture['plan'], fixture['log'])
    assert result['miss'] is True and result['height'] == 1
