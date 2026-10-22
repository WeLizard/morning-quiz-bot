"""Taking back a started action with a small penalty (owner decision, 2026-10-11). Pure state transitions.

* Digging up a planting: the seed price is refunded in full during the first ``UNDO_WINDOW`` seconds after planting
  (protection from a mis-tap), and by ``LATE_REFUND_PCT`` percent later. No XP, no harvest; the bed is free at once.
* Cancelling a workshop batch (same canon as digging up). A ready batch cannot be cancelled (collect it). A batch still waiting in
  the queue (``starts_at > now``) is returned in full at any time. A running batch is returned in full during the first
  ``UNDO_WINDOW`` seconds after ``starts_at`` (the window counts from the start, not from queueing), later ``LATE_REFUND_PCT`` percent
  of every ingredient (floor, zero positions are not returned); no XP and no products. Following batches restart from ``now``.
  The remembered ``recipes_memory`` (artisans, «repeat batches») is untouched; ``forget_recipe`` edits it.
* Returning from a woodland trip or fishing early: during the first ``UNDO_WINDOW`` seconds the trip is cancelled and everything taken
  (coins for the route, goods taken along) is returned in full; later the player comes back early with
  ``floor(output * elapsed_share * LATE_LOOT_PCT / 100)`` of every item, no XP, no secret, and what was taken is not returned.

The starter gift is restored together with the refund (``gift`` is the part of the price that was paid from it), so digging up
never turns the one-time gift into freely spendable coins.
"""
from domain.address import g as address_g
from .catalog import CROPS, ROUTES, ITEMS, RECIPES, trip_kind
from .domain import need, inventory, event

UNDO_WINDOW = 60
LATE_REFUND_PCT = 50
LATE_LOOT_PCT = 50

# Seed prices of r8 (before the r9 rebalance), for plantings that carry no ``cost``: the effective price of an old
# planting is ``min(current price, LEGACY_SEED_COST[crop])``, or just the current price.
LEGACY_SEED_COST = {'wheat': 2, 'carrot': 4, 'corn': 7, 'clover': 5, 'strawberry': 12, 'potato': 16, 'sunflower': 22, 'pumpkin': 32, 'lavender': 25, 'tomato': 18, 'oat': 5, 'beet': 9, 'cucumber': 12, 'cabbage': 15, 'peas': 16, 'rye': 14, 'raspberry': 20, 'basil': 14, 'blueberry': 26, 'flax': 26, 'rice': 30, 'watermelon': 45, 'pepper': 50, 'eggplant': 58, 'buckwheat': 40, 'mint': 60, 'grape': 64, 'chamomile': 62, 'hops': 78, 'garlic': 72, 'poppy': 84, 'melon': 100, 'cranberry': 100, 'saffron': 96}


def crop_cost(crop):
    """What a planting cost: the recorded price, or (older plantings) the cheaper of the current and the legacy price."""
    if type(crop.get('cost')) is int:
        return crop['cost']
    spec = CROPS.get(crop['id'])
    current = spec['cost'] if spec else 0
    return min(current, LEGACY_SEED_COST.get(crop['id'], current))


def crop_refund(crop, now):
    """(coins refunded, full?) for digging up this planting right now."""
    cost = crop_cost(crop)
    if now - crop['planted_at'] <= UNDO_WINDOW:
        return cost, True
    return cost * LATE_REFUND_PCT // 100, False


def restore_gift(farm, gift, amount):
    farm['starter_credit'] = min(farm['coins'], farm['starter_credit'] + min(max(0, gift), amount))


def dig_up(farm, obj, now):
    crop = obj.get('crop')
    need(obj['type'] == 'plot', 'wrong_object', 'Выкопать можно только посадку на грядке.')
    need(crop is not None, 'empty_plot', 'Грядка уже свободна.')
    need(crop['ready_at'] > now, 'ripe', 'Урожай уже созрел — лучше собрать его.')
    refund, full = crop_refund(crop, now)
    farm['coins'] += refund
    restore_gift(farm, crop.get('gift', 0), refund)
    obj['crop'] = None
    obj['revision'] += 1
    name = CROPS[crop['id']]['name'] if crop['id'] in CROPS else crop['id']
    if full:
        return f'{name}: посадка отменена, семена возвращены полностью: +{refund} монет.'
    return f'{name}: выкопано. Вернулась половина цены семян: +{refund} монет, опыта нет.'


def job_refund(job, now):
    """(ingredients refunded, full?) for cancelling this batch right now (it must not be ready)."""
    inputs = job['inputs']
    if job['starts_at'] > now or now - job['starts_at'] <= UNDO_WINDOW:
        return dict(inputs), True
    return {k: q * LATE_REFUND_PCT // 100 for k, q in inputs.items() if q * LATE_REFUND_PCT // 100 > 0}, False


def cancel_job(farm, obj, job, now):
    need(job['ready_at'] > now, 'job_done', 'Партия уже готова — забери её.')
    refund, full = job_refund(job, now)
    inventory(farm, refund)
    obj['jobs'].remove(job)
    end = now
    for j in obj['jobs']:  # the queue is sequential: what follows starts no earlier than now
        if j['starts_at'] > now:
            j['starts_at'] = max(now, end)
            j['ready_at'] = j['starts_at'] + j['seconds']
        end = j['ready_at']
    obj['revision'] += 1
    recipe = RECIPES.get(job.get('recipe'))
    name = recipe['name'] if recipe else 'Партия'
    if full:
        return f'{name}: партия отменена, ингредиенты возвращены полностью.'
    if not refund:
        return f'{name}: остановлено. Ничего не вернулось, опыта нет.'
    back = ', '.join(f'{ITEMS[k]["name"] if k in ITEMS else k} ×{q}' for k, q in refund.items())
    return f'{name}: остановлено. Вернулась половина ингредиентов: {back}, опыта нет.'


def trip_taken(trip):
    """What starting the trip took from the farm (recorded on new trips, derived from the route for older ones)."""
    if trip.get('taken'):
        return trip['taken']
    route = ROUTES.get(trip['route'])
    return dict(coins=route['cost'] if route else 0, gift=0, items=dict(route['inputs']) if route else {})


def trip_loot(trip, now):
    """Early-return loot: floor(output * elapsed share * 0.5) of every item (integer arithmetic, exact)."""
    elapsed = max(0, now - trip['started_at'])
    total = max(1, trip['ready_at'] - trip['started_at'])
    return {k: q * elapsed * LATE_LOOT_PCT // (total * 100) for k, q in trip['outputs'].items()}


def abort_trip(farm, trip, now, form='n'):
    fishing = trip_kind(trip) == 'fishing'
    need(trip['ready_at'] > now, 'trip_done', 'Рыбалка уже завершена — забери улов.' if fishing else 'Поход уже завершён — разбери корзину.')
    route = ROUTES.get(trip['route'])
    name = route['name'] if route else ('рыбалка' if fishing else 'вылазка')
    if now - trip['started_at'] <= UNDO_WINDOW:
        taken = trip_taken(trip)
        farm['coins'] += taken['coins']
        restore_gift(farm, taken.get('gift', 0), taken['coins'])
        inventory(farm, taken['items'])
        farm['trips'].remove(trip)
        back = [f'{taken["coins"]} монет'] if taken['coins'] else []
        back += [f'{ITEMS[k]["name"]} ×{q}' for k, q in taken['items'].items()]
        activity = 'рыбалка' if fishing else 'вылазка'
        return f'«{name}»: {activity} отменена, всё взятое вернулось' + (': ' + ', '.join(back) if back else '') + '.'
    loot = {k: q for k, q in trip_loot(trip, now).items() if q > 0}
    inventory(farm, loot)
    farm['trips'].remove(trip)
    if not loot:
        if fishing:
            return f'«{name}»: ' + address_g(form, 'ты вернулся раньше срока без улова', 'ты вернулась раньше срока без улова',
                                           'возвращение раньше срока, улова нет') + '. Опыта нет, взятое не возвращается.'
        return f'«{name}»: ' + address_g(form, 'ты вернулся раньше срока и ничего не успел собрать',
                                       'ты вернулась раньше срока и ничего не успела собрать',
                                       'возвращение раньше срока: собрать ничего не удалось') + '. Опыта нет, взятое не возвращается.'
    return (f'«{name}»: возвращение раньше срока. Принесено: ' + ', '.join(f'{ITEMS[k]["name"]} ×{q}' for k, q in loot.items())
            + '. Опыта нет, взятое не возвращается.')


def public_rules():
    """Constants for the client (catalog block ``undo``); the amounts are computed there from the planting's own ``cost``/``taken``."""
    return dict(window=UNDO_WINDOW, late_refund_pct=LATE_REFUND_PCT, late_loot_pct=LATE_LOOT_PCT)
