"""r9 progression: the single XP funnel and the dynamic catch-up mechanisms (stage 12).

Every XP award in qw_farm goes through :func:`grant_xp`; nothing else may write ``farm['xp']``.
State lives in ``farm['progress']`` (added with ``setdefault``; ``schema_version`` is not raised, old farms get a
blank record and nothing is granted retroactively). Days are Moscow days (``market.moscow_day``).

Mechanisms (only for ``owner=True``, i.e. XP from the owner's own commands):

* M1 "Morning dew": per Moscow day the first ``0.15 * PACE(lv)`` XP are doubled.
* M2 "Vigour": every full Moscow day without owner commands adds ``0.5 * PACE(lv)`` to a pool (cap
  ``1.5 * PACE(lv)``); while the pool is not empty, XP is doubled and the pool pays for the extra.
* M3 "Fatigue": XP from crops shorter than 1800 s (the whole fast class) and recipes shorter than 120 s, beyond
  ``0.1 * PACE(lv)`` per day, is multiplied by 0.25; M1/M2 do not apply to that reduced part. Helpers (``owner=False``)
  are tired too (owner decision 2026-10-11): their short-source XP shares the same daily allowance.

M1 and M2 both look at the base XP of a grant (after M3), so they may stack. Helper shifts replayed in ``settle``
(``owner=False``) add plain XP: no bonuses, no pool spending, no "last activity" shift; only M3 fatigue applies to them.
"""
from .catalog import level, FEAST_PCT

LEVEL_MAX = 50
# Reference XP per Moscow day by level (index = level, [0] unused): the active player's pace.
PACE = [400] + [400] * 4 + [2300] * 5 + [3900] * 5 + [7000] * 5 + [10000] * 11 + [10000 + 150 * (lv - 30) for lv in range(31, 51)]
assert len(PACE) == LEVEL_MAX + 1

DEW_PCT = 15          # M1: share of PACE doubled per day
POOL_GAIN_PCT = 50    # M2: pool gain per idle day
POOL_CAP_PCT = 150    # M2: pool cap
TIRED_PCT = 10        # M3: daily full-rate allowance of short-source XP
TIRED_NUM, TIRED_DEN = 1, 4  # M3: multiplier of the excess
SHORT_SECONDS = {'harvest': 1800, 'craft': 120}   # source -> "shorter than" threshold (catalog seconds)
SOURCES = ('harvest', 'craft', 'animal', 'build', 'expand', 'order', 'quest', 'caravan', 'contract', 'trip', 'secret', 'field')


def pace(lv):
    return PACE[max(1, min(LEVEL_MAX, lv))]


def blank():
    return dict(day=-1, dew=0, short=0, pool=0, last=-1, carry=0,
                total=dict(m1=0, m2=0, m3=0))   # cumulative extra XP from M1/M2 and XP lost to M3


def moscow_day(at):
    from . import market   # market imports domain, which imports this module
    return market.moscow_day(at)


def progress(farm):
    p = farm.setdefault('progress', blank())
    for key, value in blank().items():
        p.setdefault(key, value)
    for key in ('m1', 'm2', 'm3'):
        p['total'].setdefault(key, 0)
    return p


def _pool_cap(lv):
    return pace(lv) * POOL_CAP_PCT // 100


def touch(farm, at):
    """Register an owner command at ``at``: roll the Moscow day and credit M2 for full idle days. Idempotent."""
    p = progress(farm)
    day = moscow_day(at)
    if day > p['day']:
        p['day'] = day
        p['dew'] = 0
        p['short'] = 0
    if p['last'] >= 0 and day > p['last']:
        idle = day - p['last'] - 1
        if idle > 0:
            lv = level(farm['xp'])
            p['pool'] = min(_pool_cap(lv), p['pool'] + idle * (pace(lv) * POOL_GAIN_PCT // 100))
    if day > p['last']:
        p['last'] = day
    return p


def grant_xp(farm, amount, source, at, owner, seconds=None):
    """The only place that adds XP. Returns the XP actually credited (base + bonuses - fatigue loss)."""
    if amount <= 0:
        return 0
    if not owner:
        got = amount
        limit = SHORT_SECONDS.get(source)
        if limit is not None and seconds is not None and seconds < limit:
            p = progress(farm)
            day = moscow_day(at)
            if day > p['day']:                      # roll the Moscow day only; no vigour credit, no activity shift
                p['day'], p['dew'], p['short'] = day, 0, 0
            room = max(0, pace(level(farm['xp'])) * TIRED_PCT // 100 - p['short'])
            base = min(amount, room)
            p['short'] += amount
            excess = amount - base
            reduced = 0
            if excess:
                carry = p['carry'] + excess * TIRED_NUM
                reduced, p['carry'] = carry // TIRED_DEN, carry % TIRED_DEN
                p['total']['m3'] += excess - reduced
            got = base + reduced
        farm['xp'] += got
        return got
    p = touch(farm, at)
    pc = pace(level(farm['xp']))
    base, reduced = amount, 0
    limit = SHORT_SECONDS.get(source)
    if limit is not None and seconds is not None and seconds < limit:
        room = max(0, pc * TIRED_PCT // 100 - p['short'])
        base = min(amount, room)
        p['short'] += amount
        excess = amount - base
        if excess:
            carry = p['carry'] + excess * TIRED_NUM      # exact quarters: no XP is lost to rounding
            reduced, p['carry'] = carry // TIRED_DEN, carry % TIRED_DEN
            p['total']['m3'] += excess - reduced
    e1 = min(base, max(0, pc * DEW_PCT // 100 - p['dew']))
    p['dew'] += e1
    e2 = min(base, p['pool'])
    p['pool'] -= e2
    p['total']['m1'] += e1
    p['total']['m2'] += e2
    got = base + e1 + e2 + reduced
    eco = farm.get('economy')
    if eco and eco.get('feast_until', 0) > at:      # stage 14: the fund's "Праздник" (+10% XP), owner commands only
        extra = got * FEAST_PCT // 100
        got += extra
        eco['stats']['feast_xp'] = eco['stats'].get('feast_xp', 0) + extra
    farm['xp'] += got
    return got


def status(farm, at):
    """Read-only view for the client: what is left of today's dew and the vigour pool (including idle days not yet credited)."""
    p = {**blank(), **(farm.get('progress') or {})}   # never mutates the farm
    day = moscow_day(at)
    lv = level(farm['xp'])
    dew_used = p['dew'] if day <= p['day'] else 0
    pool = p['pool']
    if p['last'] >= 0 and day > p['last']:
        pool = min(_pool_cap(lv), pool + max(0, day - p['last'] - 1) * (pace(lv) * POOL_GAIN_PCT // 100))
    return dict(dew_left=max(0, pace(lv) * DEW_PCT // 100 - dew_used), dew_cap=pace(lv) * DEW_PCT // 100,
                pool=pool, pool_cap=_pool_cap(lv))


def validate(farm):
    from .domain import need
    p = farm.get('progress')
    if p is None:
        return
    need(isinstance(p, dict) and all(type(p.get(k)) is int for k in ('day', 'dew', 'short', 'pool', 'last', 'carry'))
         and p['dew'] >= 0 and p['short'] >= 0 and 0 <= p['pool'] <= _pool_cap(LEVEL_MAX) and 0 <= p['carry'] < TIRED_DEN,
         'invalid_state', 'Некорректное состояние прогресса.', 500)
