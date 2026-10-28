"""Nightly Pumpkin Night gift, evaluated using the server's Moscow day."""

from . import economy, festivals
from .domain import inventory, need

DAY = economy.DAY
OFFSET = economy.TZ_OFFSET
SCHEMAS = {'claim_horseman_gift': set()}
BONUSES = ({'wheat': 4}, {'feed': 2}, {'oat_cookie': 1}, {'apple': 2})


def _midnight(day):
    return day * DAY - OFFSET


def _active(now):
    hour = (now + OFFSET) % DAY
    return hour >= 17 * 3600 or hour < 5 * 3600


def _festival(now):
    current = festivals.current(now)
    return current if current and current['id'] == 'pumpkin_night' else None


def _last_day(farm):
    return (farm.get('horseman_gifts') or {}).get('last_claim_day', -1)


def gift(now, festival=None):
    festival = festival or _festival(now)
    day = economy.moscow_day(now)
    first = economy.moscow_day(festival['starts_at'])
    return {'items': {'pumpkin_candy': 3, **BONUSES[(day - first) % len(BONUSES)]}}


def claim(farm, now):
    festival = _festival(now)
    need(festival is not None and _active(now), 'horseman_unavailable',
         'Призрачный всадник появится вечером во время Тыквенной ночи.')
    day = economy.moscow_day(now)
    need(_last_day(farm) < day, 'horseman_claimed', 'Сегодня подарок уже получен.')
    inventory(farm, gift(now, festival)['items'])
    farm['horseman_gifts'] = {'last_claim_day': day}
    return 'Призрачный всадник подарил угощение.'


def owner_view(farm, now):
    festival = _festival(now)
    if festival is None:
        return None
    day = economy.moscow_day(now)
    end = festival['ends_at']
    claimed = _last_day(farm) >= day
    active = _active(now)
    midnight = _midnight(day + 1)
    hour = (now + OFFSET) % DAY
    if hour < 5 * 3600:
        time_edge = _midnight(day) + 5 * 3600
    elif hour < 17 * 3600:
        time_edge = _midnight(day) + 17 * 3600
    else:
        time_edge = midnight + 5 * 3600
    next_change = min(end, midnight, time_edge)
    if active and not claimed:
        next_gift = now
    else:
        next_gift = None
        for future_day in range(day, economy.moscow_day(end - 1) + 1):
            for candidate in (_midnight(future_day), _midnight(future_day) + 17 * 3600):
                if (now < candidate < end and economy.moscow_day(candidate) > _last_day(farm)
                        and _festival(candidate) and _active(candidate)):
                    next_gift = candidate
                    break
            if next_gift is not None:
                break
    return dict(active=active, can_claim=active and not claimed, claimed_today=claimed,
                day=day, next_change_at=next_change, next_gift_at=next_gift,
                gift=gift(now, festival))


def validate(farm):
    record = farm.get('horseman_gifts')
    if record is not None:
        need(type(record) is dict and set(record) == {'last_claim_day'} and
             type(record['last_claim_day']) is int and record['last_claim_day'] >= 0,
             'invalid_horseman_gifts', 'Некорректное состояние подарков всадника.', 500)
