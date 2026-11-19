"""Pure building perks; shared monthly decisions are loaded by construction."""
from datetime import datetime, timezone, timedelta
from .catalog import CROPS, EXOTIC_BY_FRUIT, income_ref, level


def perk(farm, building, tier=1):
    b = farm.get('village_bonus') or {}
    return building in b.get('open', ()) and b.get('tiers', {}).get(building, 0) >= tier


def month(now):
    return datetime.fromtimestamp(now, timezone(timedelta(hours=3))).strftime('%Y-%m')


def next_month(key):
    year, m = map(int, key.split('-'))
    return f'{year + (m == 12):04d}-{m % 12 + 1:02d}'


def crop_choices():
    return {**{k: c for k, c in CROPS.items() if not c.get('orchard')}, **EXOTIC_BY_FRUIT}


def winner(votes, previous='wheat'):
    counts = {}
    for crop in votes.values():
        if crop in crop_choices():
            counts[crop] = counts.get(crop, 0) + 1
    return min(counts, key=lambda c: (-counts[c], c)) if counts else previous


def crop_multiplier(farm, crop, at):
    b = farm.get('village_bonus') or {}
    value = 1
    if 'greenhouse' in b.get('open', ()):
        if b.get('month') == month(at) and b.get('crop') == crop:
            value *= .9
        if crop in EXOTIC_BY_FRUIT and perk(farm, 'greenhouse'):
            value *= .9
    return value


def dinner(farm, day):
    from . import daily_bonus, economy
    ref = income_ref(level(farm['xp']))
    receipt = (farm.get('tavern') or {}).get('dinner') or {}
    done = receipt.get('day') == day or (farm.get('tavern') or {}).get('order', {}).get('day') == day
    nominal = max(10, ref // 100)
    amount = daily_bonus.quote(farm,day*86400-economy.TZ_OFFSET,nominal)
    return dict(day=day, amount=amount, nominal_amount=nominal,paid=receipt.get('paid',0) if receipt.get('day')==day else 0,
                claimed=done, available=perk(farm, 'tavern') and not done,
                income_ref=ref, cap=daily_bonus.snapshot(farm,day*86400-economy.TZ_OFFSET)['cap'])
