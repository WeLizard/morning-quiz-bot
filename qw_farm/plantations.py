"""Perennial plantations. Each purchased hectare has its own cycle and revision."""
from datetime import datetime, timedelta, timezone

from . import market, progression
from .catalog import ITEMS, PLANTATION_UPKEEP, PLANTATION_WINTER_UPKEEP, level
from .domain import duration, find, inventory, named, need, number, pay
from .economy import DAY, TZ_OFFSET


STEPS = {
    1: dict(level=32, ha=1, cost=150_000),
    2: dict(level=36, ha=1, cost=280_000),
    3: dict(level=41, ha=2, cost=520_000),
    4: dict(level=46, ha=2, cost=900_000),
}
STEP_ENDS = tuple(sum(STEPS[n]['ha'] for n in STEPS if n <= step) for step in STEPS)
MAX_HECTARES = STEP_ENDS[-1]
CULTURES = {
    'vineyard': dict(name='Виноград', level=32, cost=40_000, juvenile=3, seconds=2 * DAY,
                     yield_qty=98, item='grape', xp=80, winter_pause=True),
    'tea_garden': dict(name='Чайный куст', level=32, cost=30_000, juvenile=2, seconds=DAY,
                       yield_qty=95, item='tea_leaf', xp=40, winter_pause=False),
}
YOUNG_HARVESTS = 3
YOUNG_PCT = 60
AUTO_QUALITY = 90
XP_MULTIPLIER = 8
MOSCOW = timezone(timedelta(seconds=TZ_OFFSET))

SCHEMAS = {
    'buy_plantation': {'step'},
    'plant_plantation': {'plantation', 'revision', 'crop'},
    'uproot_plantation': {'plantation', 'revision'},
    'plantation_auto': {'plantation', 'revision'},
}


def winter_window(at):
    """The current or next Moscow winter as a half-open interval."""
    local = datetime.fromtimestamp(at, MOSCOW)
    year = local.year - (local.month < 3)
    return (int(datetime(year, 12, 1, tzinfo=MOSCOW).timestamp()),
            int(datetime(year + 1, 3, 1, tzinfo=MOSCOW).timestamp()))


def upkeep_per_hectare(crop, at=None):
    if crop == 'vineyard' and at is not None:
        start, end = winter_window(at)
        if start <= at < end:
            return PLANTATION_WINTER_UPKEEP
    return PLANTATION_UPKEEP


def cycle_deadline(spec, at, active_seconds):
    """Count growth seconds only outside dormancy, keeping exact boundary deadlines."""
    if not spec['winter_pause']:
        return at + active_seconds
    while active_seconds:
        start, end = winter_window(at)
        available = max(0, start - at)
        if active_seconds <= available:
            return at + active_seconds
        active_seconds -= available
        at = end
    return at


def new_cycle(spec, at, harvests, speed=1, farm=None):
    juvenile = spec['juvenile'] if harvests == 0 else 0
    seconds = duration(spec['seconds'] * (juvenile + 1), speed, farm)
    young_seconds = duration(spec['seconds'] * juvenile, speed, farm) if juvenile else 0
    maturity = YOUNG_PCT if harvests < YOUNG_HARVESTS else 100
    return dict(started_at=at, active_seconds=seconds, ready_at=cycle_deadline(spec, at, seconds),
                young_until=cycle_deadline(spec, at, young_seconds),
                season_seconds=spec['seconds'], winter_pause=spec['winter_pause'],
                yield_qty=spec['yield_qty'], base_xp=spec['xp'] * XP_MULTIPLIER, maturity_pct=maturity)


def cycle_reward(cycle, quality=AUTO_QUALITY):
    """Quantity (half up) and base XP for the frozen cycle, before XP bonuses."""
    qty = (cycle['yield_qty'] * cycle['maturity_pct'] * quality + 5_000) // 10_000
    xp = cycle['base_xp'] * quality // 100
    return qty, xp


def public_catalog():
    return dict(steps=STEPS, cultures=CULTURES, upkeep=PLANTATION_UPKEEP, auto_quality=AUTO_QUALITY,
                vineyard_winter_upkeep=PLANTATION_WINTER_UPKEEP,
                young_harvests=YOUNG_HARVESTS, young_pct=YOUNG_PCT, xp_multiplier=XP_MULTIPLIER)


def products_in_reach(farm):
    stock = farm['inventory']
    available = {spec['item'] for spec in CULTURES.values() if stock.get(spec['item'], 0) > 0}
    return available | {CULTURES[hectare['crop']]['item'] for hectare in farm.get('plantations', [])
                        if hectare['harvests'] > 0}


def owner_view(farm, now):
    result = []
    for hectare in farm.get('plantations', []):
        crop, cycle = hectare['crop'], hectare['cycle']
        state = 'empty'
        if cycle is not None:
            if now >= cycle['ready_at']:
                state = 'ready'
            elif cycle['winter_pause'] and winter_window(now)[0] <= now:
                state = 'winter'
            elif now < cycle.get('young_until', cycle['started_at']):
                state = 'young'
            else:
                state = 'growing'
        result.append(dict(id=hectare['id'], revision=hectare['revision'], crop=crop,
                           harvests=hectare['harvests'], state=state,
                           ready_at=cycle['ready_at'] if cycle is not None else None))
    return result


def apply(farm, kind, data, now, speed):
    if kind == 'buy_plantation':
        step = number(data['step'], high=len(STEPS))
        spec = STEPS[step]
        owned = len(farm.get('plantations', []))
        previous = STEP_ENDS[step - 2] if step > 1 else 0
        need(owned <= previous, 'already_owned', 'Эта земля уже куплена.')
        need(owned == previous, 'plantation_step', 'Сначала купи предыдущий участок плантации.')
        need(level(farm['xp']) >= spec['level'], 'locked', f'Нужен уровень {spec["level"]}.')
        pay(farm, spec['cost'])
        farm.setdefault('plantations', []).extend(
            dict(id=n, revision=0, crop=None, harvests=0, cycle=None)
            for n in range(owned + 1, owned + spec['ha'] + 1)
        )
        return f'Куплена земля для плантации: {spec["ha"]} га.'

    hectare = find(farm.get('plantations', []), number(data['plantation'], high=MAX_HECTARES))
    need(type(data['revision']) is int and hectare['revision'] == data['revision'],
         'stale_object', 'Плантация изменилась. Обнови ферму.')
    if kind == 'plant_plantation':
        need(hectare['crop'] is None, 'plantation_occupied', 'Сначала выкорчуй старую посадку.')
        crop = data['crop']
        spec = named(CULTURES, crop)
        need(level(farm['xp']) >= spec['level'], 'locked', f'Нужен уровень {spec["level"]}.')
        cycle = new_cycle(spec, now, 0, speed, farm)
        pay(farm, spec['cost'])
        hectare.update(crop=crop, cycle=cycle)
        text = f'Посадка завершена. Культура: {spec["name"]}.'
    elif kind == 'uproot_plantation':
        need(hectare['crop'] is not None, 'plantation_empty', 'На гектаре пока ничего не посажено.')
        hectare.update(crop=None, cycle=None, harvests=0)
        text = 'Посадка выкорчевана. Можно посадить новую культуру.'
    else:
        need(hectare['cycle'] is not None and hectare['cycle']['ready_at'] <= now,
             'not_ready', 'На плантации пока нет спелого урожая.')
        spec, ripe_cycle = CULTURES[hectare['crop']], hectare['cycle']
        harvests = hectare['harvests']
        qty, xp = cycle_reward(ripe_cycle)
        cycle = new_cycle(spec, now, harvests + 1, speed, farm)
        inventory(farm, {spec['item']: qty})
        progression.grant_xp(farm, xp, 'harvest', now, True, ripe_cycle['season_seconds'])
        market.count(farm, 'h:' + spec['item'], qty)
        hectare.update(harvests=harvests + 1, cycle=cycle)
        text = f'Бригада собрала урожай: {ITEMS[spec["item"]]["name"]} ×{qty}, качество {AUTO_QUALITY}%.'
    hectare['revision'] += 1
    return text


def validate(farm):
    def valid(condition):
        need(condition, 'invalid_plantations', 'Некорректное состояние плантаций.', 500)

    hectares = farm.get('plantations', [])
    valid(type(hectares) is list and len(hectares) in (0, *STEP_ENDS))
    for n, hectare in enumerate(hectares, 1):
        valid(type(hectare) is dict and {'id', 'revision', 'crop', 'harvests', 'cycle'} <= set(hectare))
        valid(type(hectare['id']) is int and hectare['id'] == n and
              type(hectare['revision']) is int and hectare['revision'] >= 0 and
              type(hectare['harvests']) is int and 0 <= hectare['harvests'] <= hectare['revision'])
        crop, cycle = hectare['crop'], hectare['cycle']
        if crop is None:
            valid(cycle is None and hectare['harvests'] == 0)
            continue
        valid(type(crop) is str and crop in CULTURES and type(cycle) is dict and
              type(cycle.get('winter_pause')) is bool and
              all(type(cycle.get(k)) is int for k in ('started_at', 'ready_at', 'active_seconds')))
        valid(0 < cycle['active_seconds'] <= cycle['ready_at'] - cycle['started_at'] and
              all(type(cycle.get(k)) is int and cycle[k] > 0 for k in ('yield_qty', 'base_xp', 'season_seconds')) and
              type(cycle.get('maturity_pct')) is int and 0 < cycle['maturity_pct'] <= 100)
        young_until = cycle.get('young_until', cycle['started_at'])
        valid(type(young_until) is int and cycle['started_at'] <= young_until <= cycle['ready_at'])
