"""Wild meadow patches: deterministic, lazy and farm-local."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from hashlib import sha256

from .domain import object_cells
from .catalog import BUILDINGS

TZ = timezone(timedelta(hours=3))
HOUR = 3600
EPOCH = 3 * HOUR

# Door sides/positions match doorX/doorY calls in static/scene_buildings.js.
# Coordinates are fractions across the corresponding building edge.
DOORS = {
    'house': ('right', .5), 'bakery': ('right', .5), 'loom': ('right', .5),
    'tailor': ('right', .5), 'confectionery': ('right', .5),
    'dairy': ('right', .5),
    'spinnery': ('right', .2), 'weavery': ('right', .35),
    'barn': ('bottom', .5), 'mill': ('bottom', .75), 'cattle_barn': ('bottom', .5),
    'rabbit_hutch': ('bottom', .5), 'coop': ('bottom', .5), 'cowshed': ('bottom', .5),
    'feedmill': ('bottom', .3), 'goatshed': ('bottom', .3),
    'pigsty': ('bottom', .3), 'oil_press': ('bottom', .2),
    'cannery': ('bottom', .8), 'smokehouse': ('bottom', .5),
    'sausage_shop': ('bottom', .8),
    'syrupery': ('bottom', .2), 'soapery': ('bottom', .2),
    'noodle_shop': ('bottom', .2), 'energy_shop': ('bottom', .2),
    'apiary': ('bottom', .5), 'goose_house': ('bottom', .5),
    'turkey_yard': ('bottom', .5),
    'creamery': ('bottom', .5), 'ostrich_farm': ('bottom', .5),
    'silk_house': ('bottom', .5), 'yak_pen': ('bottom', .5),
    'pheasantry': ('bottom', .5),
    'cellar': ('bottom', .5),
}


def season_at(at):
    month = datetime.fromtimestamp(at, TZ).month
    return 'spring' if month <= 5 and month >= 3 else 'summer' if 6 <= month <= 8 else 'autumn' if 9 <= month <= 11 else 'winter'


def _season_start(at):
    dt = datetime.fromtimestamp(at, TZ)
    return datetime(dt.year, dt.month, 1, tzinfo=TZ).timestamp()


def growth_seconds(start, end):
    """Season-weighted growth elapsed; winter intervals contribute zero."""
    start, end = start, max(start, end)
    total = 0.0
    cursor = start
    while cursor < end:
        dt = datetime.fromtimestamp(cursor, TZ)
        if dt.month == 12:
            next_month = datetime(dt.year + 1, 1, 1, tzinfo=TZ).timestamp()
            season, rate = 'winter', 0
        else:
            next_month = (datetime(dt.year + 1, 1, 1, tzinfo=TZ).timestamp() if dt.month == 12
                          else datetime(dt.year + (dt.month == 12), (dt.month % 12) + 1, 1, tzinfo=TZ).timestamp())
            season = season_at(cursor)
            rate = {'spring': 1.5, 'summer': 1.0, 'autumn': 0.75, 'winter': 0}[season]
        stop = min(end, next_month)
        total += (stop - cursor) * rate
        cursor = stop
    return total


def stage(cut_at, now):
    age = growth_seconds(cut_at, now)
    return 0 if age < 3 * HOUR else 1 if age < 8 * HOUR else 2


def next_stage_at(cut_at, now, target_stage):
    """First whole second at which a patch reaches a growth stage, including seasonal pauses."""
    thresholds = {1: 3 * HOUR, 2: 8 * HOUR}
    target = thresholds[target_stage]
    if growth_seconds(cut_at, now) >= target:
        return now
    lo, hi = int(now) + 1, int(now) + 370 * 86400
    if growth_seconds(cut_at, hi) < target:
        return None
    while lo < hi:
        mid = (lo + hi) // 2
        if growth_seconds(cut_at, mid) >= target:
            hi = mid
        else:
            lo = mid + 1
    return lo


def eligible_cells(farm):
    occupied = set()
    forbidden = set()
    for obj in farm.get('objects', []):
        cells = object_cells(obj)
        occupied |= cells
        if obj.get('type') == 'plot':
            for x, y in cells:
                forbidden.update(((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)))
        else:
            typ = obj.get('type')
            if typ in {'tree'} or (typ in BUILDINGS and BUILDINGS[typ].get('decor')):
                continue
            door = DOORS.get(typ)
            if door and cells:
                x0, y0 = int(obj.get('x', 0)), int(obj.get('y', 0))
                w, h = int(obj.get('w', 1)), int(obj.get('h', 1))
                side, fraction = door
                if side == 'right':
                    anchor = (x0 + w - 1, y0 + min(h - 1, int(h * fraction)))
                else:
                    anchor = (x0 + min(w - 1, int(w * fraction)), y0 + h - 1)
                x, y = anchor
                forbidden.update(((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)))
    return sorted((x, y) for x in range(farm['size']) for y in range(farm['size'])
                  if (x, y) not in occupied and (x, y) not in forbidden)


def patch_limit(farm):
    count = len(eligible_cells(farm))
    return min(count, max(2, min(12, count // 10)))


def _hash(farm_id, epoch):
    return int(sha256(f'{farm_id}:{epoch}:meadow'.encode()).hexdigest(), 16)


def initialize(farm, now):
    fresh = 'meadow' not in farm
    meadow = farm.setdefault('meadow', {'v': 1, 'epoch': int((now + 10800) // EPOCH), 'patches': {}})
    meadow.setdefault('v', 1)
    meadow.setdefault('patches', {})
    meadow.setdefault('epoch', int((now + 10800) // EPOCH))
    if fresh:
        # A missing record identifies a legacy save. New farms are initialized
        # with an empty record in domain.new_farm.
        cells = eligible_cells(farm)
        seed_time = _stage_one_cut_at(now)
        for x, y in cells[:min(2, patch_limit(farm))]:
            meadow['patches'][f'{x},{y}'] = seed_time
    return meadow


def _stage_one_cut_at(now):
    # Find the first second whose season-weighted age reaches stage 1. This
    # handles transitions such as March 1 (which otherwise backdate into winter).
    lo, hi = int(now - 370 * 86400), int(now)
    target = 3 * HOUR + 2
    while lo < hi:
        mid = (lo + hi) // 2
        if growth_seconds(mid, now) >= target:
            lo = mid + 1
        else:
            hi = mid
    return max(int(now - 370 * 86400), lo - 1)


def update(farm, now):
    meadow = initialize(farm, now)
    cells = eligible_cells(farm)
    valid = {f'{x},{y}' for x, y in cells}
    meadow['patches'] = {cell: cut for cell, cut in meadow['patches'].items() if cell in valid}
    limit = patch_limit(farm)
    if len(meadow['patches']) > limit:
        meadow['patches'] = dict(sorted(meadow['patches'].items())[:limit])
    epoch = int((now + 10800) // EPOCH)
    prior = meadow['epoch']
    # Process only the latest day of rolls after absence, then advance past the discarded debt.
    first = max(prior + 1, epoch - 7)
    for step in range(first, epoch + 1):
        stamp = step * EPOCH - 10800
        season = season_at(stamp)
        denominator = {'spring': 2, 'summer': 3, 'autumn': 4, 'winter': 0}[season]
        roll = _hash(farm['id'], step)
        if denominator and roll % denominator == 0 and len(meadow['patches']) < limit:
            free = [cell for cell in cells if f'{cell[0]},{cell[1]}' not in meadow['patches']]
            if free:
                x, y = free[roll % len(free)]
                meadow['patches'][f'{x},{y}'] = stamp
    meadow['epoch'] = max(prior, epoch)
    return meadow


def view(farm, now):
    meadow = farm.get('meadow') or {'patches': {}}
    return {'season': season_at(now), 'patches': [
        {'cell': cell, 'stage': stage(cut, now)} for cell, cut in sorted(meadow['patches'].items())]}


def mow(farm, cell, now, update_state=True):
    meadow = update(farm, now) if update_state else farm.setdefault('meadow', {'v': 1, 'epoch': int((now + 10800) // EPOCH), 'patches': {}})
    cut = meadow['patches'].get(cell)
    if cut is None:
        return 0
    level = stage(cut, now)
    if level == 0 or season_at(now) == 'winter':
        return 0
    from .domain import inventory
    qty = 2 if level == 2 else 1
    inventory(farm, {'grass': qty})
    meadow['patches'][cell] = now
    return qty


def seed_new_land(farm, previous_size, now):
    meadow = initialize(farm, now)
    room = max(0, patch_limit(farm) - len(meadow['patches']))
    cells = [f'{x},{y}' for x,y in eligible_cells(farm)
             if (x >= previous_size or y >= previous_size) and f'{x},{y}' not in meadow['patches']]
    for cell in cells[:min(2, room)]:
        meadow['patches'][cell] = _stage_one_cut_at(now)


def mow_ready(farm, now, tall_only=False):
    meadow = update(farm, now)
    total = 0
    for cell, cut in sorted(meadow['patches'].items()):
        level = stage(cut, now)
        if level >= (2 if tall_only else 1) and season_at(now) != 'winter':
            total += mow(farm, cell, now)
    return total
