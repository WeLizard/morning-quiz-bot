"""Feeding the lake swans: a tiny owner-only daily chore (grain for a little XP).

Server-authoritative and deterministic: the cost, reward, daily limit and cooldown live here; the client only sends
``feed_swans`` with no parameters. State is ``farm['swans'] = {day, fed, next_at, total}`` where ``day`` is the Moscow day
of the last feeding and ``fed`` the feedings made on that day. An old farm without the field gets the defaults.
These swans are the decorative ones on the lake, not the «Лебединое озеро» production building.
"""
from .catalog import tick, level, FISHING_LEVEL, ITEMS
from .domain import need, inventory
from . import progression

SCHEMAS = {'feed_swans': set()}
ITEM = 'wheat'
COST = 3                 # grain per feeding
XP = 5                   # base XP per feeding (progression bonuses may add to it)
DAILY_LIMIT = 3          # feedings per Moscow day
COOLDOWN = 20 * 60       # seconds between feedings
UNLOCK_LEVEL = FISHING_LEVEL   # the lake opens with fishing


def blank():
    return dict(day=-1, fed=0, next_at=0, total=0)


def state(farm):
    return farm.setdefault('swans', blank())


def _int(value):
    return type(value) is int and 0 <= value <= 10**12 or value == -1


def validate(farm):
    s = farm.get('swans')
    if s is None:
        return
    need(isinstance(s, dict) and set(s) == {'day', 'fed', 'next_at', 'total'} and all(_int(v) for v in s.values()) and
         s['fed'] >= 0 and s['next_at'] >= 0 and s['total'] >= 0 and s['fed'] <= DAILY_LIMIT,
         'invalid_swans', 'Некорректное состояние лебедей.', 500)


def public_rules():
    return dict(item=ITEM, cost=COST, xp=XP, daily_limit=DAILY_LIMIT, cooldown=COOLDOWN, level=UNLOCK_LEVEL)


def public(farm, now):
    """Owner-only read model; never mutates the farm. ``left`` already accounts for the Moscow day roll."""
    now = tick(now)
    s = {**blank(), **(farm.get('swans') or {})}
    fed = s['fed'] if s['day'] == progression.moscow_day(now) else 0
    return dict(public_rules(), left=max(0, DAILY_LIMIT - fed), day=progression.moscow_day(now), next_at=s['next_at'], total=s['total'],
                unlocked=level(farm['xp']) >= UNLOCK_LEVEL)


def feed(farm, now):
    now = tick(now)
    need(level(farm['xp']) >= UNLOCK_LEVEL, 'locked', f'Лебеди приплывут к берегу с {UNLOCK_LEVEL} уровня.')
    s = state(farm)
    day = progression.moscow_day(now)
    if s['day'] != day:
        s['day'], s['fed'] = day, 0
    need(s['fed'] < DAILY_LIMIT, 'swans_full', 'Лебеди сегодня сыты. Приходи завтра.')
    need(now >= s['next_at'], 'swans_wait', 'Лебеди ещё доедают. Подожди немного.')
    inventory(farm, {ITEM: COST}, -1)
    s['fed'] += 1
    s['total'] += 1
    s['next_at'] = now + COOLDOWN
    got = progression.grant_xp(farm, XP, 'swans', now, True)
    return f'Лебеди съели {ITEMS[ITEM]["name"].lower()} ×{COST}. +{got} опыта.'
