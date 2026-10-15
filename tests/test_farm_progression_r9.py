"""Farm r9 stage 12: level curve to L50, the single XP funnel and the M1-M3 mechanisms."""
from copy import deepcopy
from pathlib import Path
import re
from uuid import uuid4

import pytest

from qw_farm import catalog, market, progression
from qw_farm.catalog import LEVELS, level, validate
from qw_farm.domain import FarmError, apply, new_farm, project, validate_state
from qw_farm.expansion import harvest, upgrade_state

T0 = 1_800_000_000
DAY = 86400
OLD_LEVELS = [0, 20, 65, 135, 240, 400, 650, 1000, 1500, 2200, 3100, 4300, 5800, 7800, 10300,
              13500, 17200, 21600, 26600, 32400, 39000, 46500, 55000, 64500, 75000, 86600, 99400, 113500, 129000, 146000]


def old_level(xp):
    return max(i + 1 for i, x in enumerate(OLD_LEVELS) if xp >= x)


def farm(xp=0, coins=10 ** 6):
    state = upgrade_state(new_farm(str(uuid4()), 'Prog', T0))
    state.update(xp=xp, coins=coins, starter_credit=0)
    return state


def day_start(day):
    """First instant of the given Moscow day number."""
    return day * DAY - market.TZ_OFFSET


def test_level_curve_keeps_l1_l30_and_reaches_l50():
    validate()
    assert len(LEVELS) == 50 and LEVELS[:30] == OLD_LEVELS and LEVELS == sorted(set(LEVELS))
    assert LEVELS[30] == 165_600 and LEVELS[34] == 277_900 and LEVELS[49] == 990_100
    for xp in sorted({*range(0, 400), *range(0, 146_000, 37), *(t + d for t in OLD_LEVELS for d in (-1, 0, 1))}):
        if 0 <= xp < 146_000:
            assert level(xp) == old_level(xp), xp
    assert level(146_000) == 30 and level(165_599) == 30 and level(165_600) == 31
    assert level(990_099) == 49 and level(990_100) == 50 and level(10 ** 9) == 50


def test_pace_table():
    assert [progression.pace(lv) for lv in (1, 4, 5, 9, 10, 14, 15, 19, 20, 30, 31, 50)] == [
        400, 400, 2300, 2300, 3900, 3900, 7000, 7000, 10000, 10000, 10150, 13000]


def test_every_xp_award_goes_through_the_funnel():
    root = Path(__file__).resolve().parents[1] / 'qw_farm'
    pattern = re.compile(r"""(\[['"]xp['"]\]\s*[-+]?=(?!=)|(?<![\w.])xp\s*[-+]=)""")
    offenders = [f'{p.name}:{n}' for p in sorted(root.glob('*.py')) if p.name != 'progression.py'
                 for n, line in enumerate(p.read_text(encoding='utf-8').splitlines(), 1) if pattern.search(line)]
    assert offenders == []


def test_m1_morning_dew_doubles_first_share_of_the_day_and_resets_at_moscow_midnight():
    f = farm()                                   # L1: PACE 400 -> 60 XP of dew
    assert progression.grant_xp(f, 50, 'quest', T0, True) == 100
    assert progression.grant_xp(f, 30, 'quest', T0 + 10, True) == 40      # only 10 XP of dew left
    assert progression.grant_xp(f, 30, 'quest', T0 + 20, True) == 30
    assert f['xp'] == 170 and f['progress']['total']['m1'] == 60
    midnight = day_start(market.moscow_day(T0) + 1)
    assert progression.grant_xp(f, 10, 'quest', midnight - 1, True) == 10
    assert progression.grant_xp(f, 10, 'quest', midnight, True) == 20     # a new Moscow day: dew is back
    assert progression.status(f, midnight)['dew_left'] == 60 - 10


def test_m2_vigour_pool_grows_per_full_idle_day_is_capped_and_doubles_xp_until_empty():
    f = farm(xp=LEVELS[9])                       # L10: PACE 3900, dew 585, pool +1950/day, cap 5850
    progression.touch(f, T0)
    day0 = market.moscow_day(T0)
    t = day_start(day0 + 2) + 100                # day0 + 1 passed without commands
    assert progression.status(f, t)['pool'] == 1950
    progression.touch(f, t)
    assert f['progress']['pool'] == 1950
    t2 = day_start(day0 + 10) + 100              # many idle days: the cap holds
    progression.touch(f, t2)
    assert f['progress']['pool'] == 5850
    before = f['xp']
    assert progression.grant_xp(f, 500, 'quest', t2, True) == 500 * 3     # base + dew + vigour
    assert f['progress']['pool'] == 5350
    f['progress']['pool'] = 100
    assert progression.grant_xp(f, 1000, 'quest', t2 + 5, True) == 1000 + 85 + 100   # dew has 85 left
    assert f['progress']['pool'] == 0 and f['progress']['total']['m2'] == 600
    assert f['xp'] == before + 1500 + 1185


def test_m2_gives_nothing_for_consecutive_days_or_retroactively():
    f = farm(xp=LEVELS[9])
    day0 = market.moscow_day(T0)
    progression.touch(f, T0)
    progression.touch(f, day_start(day0 + 1) + 50)   # the very next day: no idle day in between
    assert f['progress']['pool'] == 0
    old = farm(xp=LEVELS[9])
    old['progress']['last'] = -1                     # never seen: no retroactive pool
    progression.touch(old, T0 + 30 * DAY)
    assert old['progress']['pool'] == 0 and old['progress']['last'] == market.moscow_day(T0 + 30 * DAY)


def test_m3_fatigue_reduces_short_sources_beyond_the_daily_allowance_and_skips_m1_m2():
    f = farm(xp=LEVELS[19])                      # L20: PACE 10000 -> allowance 1000, dew 1500
    progression.touch(f, T0)
    f['progress']['dew'] = 10 ** 6               # take M1 out of the picture
    assert progression.grant_xp(f, 1000, 'harvest', T0, True, 30) == 1000
    assert progression.grant_xp(f, 8, 'harvest', T0, True, 30) == 2       # x0.25
    assert progression.grant_xp(f, 8, 'harvest', T0, True, 599) == 2
    assert progression.grant_xp(f, 3, 'harvest', T0, True, 30) == 0       # remainder is carried, never lost...
    assert progression.grant_xp(f, 1, 'harvest', T0, True, 30) == 1       # ...3 + 1 quarters make a whole XP
    assert f['progress']['total']['m3'] == 20 - 5
    assert progression.grant_xp(f, 500, 'harvest', T0, True, 1800) == 500         # 1800 s is the medium class: not short
    assert progression.grant_xp(f, 500, 'craft', T0, True, 120) == 500
    assert progression.grant_xp(f, 40, 'craft', T0, True, 119) == 10
    assert progression.grant_xp(f, 40, 'order', T0, True, 1) == 40        # only crops and recipes are fatigue sources
    f['progress']['dew'] = 0
    f['progress']['pool'] = 10 ** 4
    assert progression.grant_xp(f, 100, 'harvest', T0, True, 30) == 25    # M1/M2 do not touch the reduced XP
    assert f['progress']['pool'] == 10 ** 4 and f['progress']['dew'] == 0


def test_m3_allowance_is_per_moscow_day():
    f = farm(xp=LEVELS[19])
    progression.touch(f, T0)
    f['progress']['dew'] = 10 ** 6
    progression.grant_xp(f, 1000, 'harvest', T0, True, 30)
    assert progression.grant_xp(f, 4, 'harvest', T0, True, 30) == 1
    later = day_start(market.moscow_day(T0) + 1) + 5          # the next day: no idle day, so no vigour
    assert progression.grant_xp(f, 4, 'harvest', later, True, 30) == 8     # new day: full rate, and the dew is back


def test_helpers_get_plain_xp_without_spending_pool_dew_or_activity():
    f = farm(xp=LEVELS[9])
    progression.touch(f, T0)
    f['progress']['pool'] = 1000
    snapshot = {k: f['progress'][k] for k in ('pool', 'dew', 'last')}
    calm = lambda: {k: f['progress'][k] for k in snapshot}
    later = T0 + 5 * DAY
    assert progression.grant_xp(f, 40, 'harvest', later, False, 30) == 40  # inside the daily allowance: plain XP
    assert calm() == snapshot                                              # no pool, no dew, no activity shift
    crop = dict(id='wheat', planted_at=T0, ready_at=T0 + 30, yield_qty=3, xp=1, helped=False, version=catalog.VERSION)
    plot = dict(id='p', type='plot', x=0, y=0, w=1, h=1, revision=0, crop=dict(crop))
    f['objects'] = [plot]
    xp = f['xp']
    harvest(f, plot, later, False)
    assert f['xp'] == xp + 1 and calm() == snapshot
    plot['crop'] = dict(crop)
    harvest(f, plot, later)                                                # the owner's own harvest is activity
    assert f['progress']['last'] == market.moscow_day(later) and f['progress']['pool'] == 5850 - 1   # idle days credited (cap), then 1 XP doubled from the pool


def test_owner_commands_use_the_funnel_and_failed_commands_leave_progress_alone():
    f = farm()
    crop = dict(id='clover', planted_at=T0 - 1000, ready_at=T0 - 1, yield_qty=3, xp=4, helped=False, version=catalog.VERSION)
    f['objects'] = [dict(id='p', type='plot', x=0, y=0, w=1, h=1, revision=0, crop=crop)]
    apply(f, f, 'harvest', dict(object='p', revision=0), T0, 'h1')
    assert f['xp'] == 8 and f['progress']['total']['m1'] == 4              # 4 XP, doubled by the dew
    before = deepcopy(f)
    with pytest.raises(FarmError):
        apply(f, f, 'harvest', dict(object='p', revision=1), T0 + 5 * DAY, 'h2')
    assert f == before
    validate_state(f)


def test_old_farms_without_progress_load_and_keep_schema_version():
    f = new_farm(str(uuid4()), 'Old', T0)
    f.pop('progress', None)
    f['schema_version'] = 2
    f['xp'] = 5000
    upgrade_state(f)
    assert f['schema_version'] == 2 and f['progress'] == progression.blank()
    validate_state(f)
    f['inventory']['wheat'] = 1
    apply(f, f, 'sell', dict(item='wheat', qty=1), T0 + 7 * DAY, 's1')
    assert f['progress']['pool'] == 0 and f['progress']['last'] == market.moscow_day(T0 + 7 * DAY)   # nothing retroactive
    assert project(f, f, T0 + 7 * DAY)['xp_bonus']['dew_left'] > 0
    bare = new_farm(str(uuid4()), 'Bare', T0)
    bare.pop('progress', None)
    assert project(bare, bare, T0)['xp_bonus']['pool'] == 0 and 'progress' not in bare   # the read path never mutates


def test_status_is_exposed_only_to_the_owner_and_does_not_mutate():
    owner, other = farm(xp=LEVELS[9]), farm()
    owner['progress']['last'] = market.moscow_day(T0) - 3
    snapshot = deepcopy(owner)
    view = project(owner, owner, T0)
    assert view['xp_bonus'] == dict(dew_left=585, dew_cap=585, pool=3900, pool_cap=5850)
    assert owner == snapshot
    owner['neighbors'][other['id']] = dict(status='accepted')
    other['neighbors'][owner['id']] = dict(status='accepted')
    seen = project(owner, other, T0)
    assert 'xp_bonus' not in seen and 'progress' not in seen


def test_m3_fatigue_applies_to_helpers_too_and_shares_the_owners_allowance():
    f = farm(xp=LEVELS[19])                      # L20: allowance 1000 per Moscow day
    progression.touch(f, T0)
    f['progress']['pool'] = 777
    assert progression.grant_xp(f, 1000, 'harvest', T0, False, 30) == 1000
    assert progression.grant_xp(f, 8, 'harvest', T0, False, 30) == 2         # x0.25 beyond the allowance
    assert progression.grant_xp(f, 8, 'harvest', T0, False, 1800) == 8       # medium class: not short
    assert progression.grant_xp(f, 8, 'order', T0, False, None) == 8
    assert progression.grant_xp(f, 8, 'harvest', T0, True, 30) == 2          # the owner draws from the same daily allowance
    assert f['progress']['pool'] == 777
