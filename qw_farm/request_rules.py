"""Pure shared request/gift state, eligibility and Moscow-day counters."""
from . import economy
from .domain import need

def upgrade(farm, now=None):
    farm['settings'].setdefault('allow_requests', True)
    farm['settings'].setdefault('notify_requests', True)
    if now is not None:
        for edge in farm['neighbors'].values():
            if edge.get('status') == 'accepted':
                edge.setdefault('accepted_at', now)
    state = farm.setdefault('friend_request_state', dict(hidden=[], good_deeds=0, telegram={}))
    state.setdefault('seen', [])
    return state


def gift_daily(farm, target, now):
    """The existing gift keys use Moscow days for gifts and request deliveries alike."""
    day = economy.moscow_day(now)
    rec = farm.setdefault('gift_daily', dict(day=day, counts={}))
    # Preserve already spent legacy UTC-day quota during the one-time rollout.
    if 'migrated' not in rec:
        if farm.get('daily', {}).get('day') == int(now // 86400):
            rec['counts'] = {k: v for k, v in farm['daily']['counts'].items() if k == 'gift_total' or k.startswith('gift:')}
        rec['migrated'] = True
    if rec['day'] != day:
        rec.update(day=day, counts={})
    counts = rec['counts']
    need(counts.get('gift:' + target, 0) < 3 and counts.get('gift_total', 0) < 5,
         'daily_limit', 'На сегодня лимит подарков и посылок исчерпан.', 429)
    for key in ('gift:' + target, 'gift_total'):
        counts[key] = counts.get(key, 0) + 1
    # Keep the well-known counters visible to existing clients and reports.
    legacy = farm.setdefault('daily', dict(day=int(now // 86400), counts={}))
    if legacy['day'] != int(now // 86400):
        legacy.update(day=int(now // 86400), counts={})
    for key in ('gift:' + target, 'gift_total'):
        legacy['counts'][key] = counts[key]


def mutual(a, b):
    return bool(a and b and a['id'] != b['id'] and b['id'] not in a['blocked'] and a['id'] not in b['blocked'] and
        a['neighbors'].get(b['id'], {}).get('status') == 'accepted' and
        b['neighbors'].get(a['id'], {}).get('status') == 'accepted')


def unlocked(farm, coins=False):
    need(farm['stats']['orders'] >= (3 if coins else 1) and farm['stats']['harvests'] >= 4,
         'request_locked', 'Просьбы открываются после первого заказа и четырёх сборов; монеты — после трёх заказов.')


