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

* Demolishing an empty building, decor, road or bed (E27 D1, owner decision 2026-10-29): in the first ``UNDO_WINDOW`` seconds after it was
  built everything comes back (the coins paid and the goods of its upgrades, no wood); later ``LATE_REFUND_PCT`` percent of the coins
  (the price recorded in ``paid``, the catalog price for older objects without a record, 0 for a caravan gift and for the starter
  objects of ``new_farm``, plus the coin price of the upgrades) and of the upgrade goods (rounded down), and the wood.  The 5 build XP and
  the build counter are taken back on EVERY demolition of an object that recorded them (``build_xp``; never below the level start), so a
  build-and-clear cycle costs coins and gives no XP.
* Uprooting a tree after the window (E27 D2): ``LATE_REFUND_PCT`` percent of the sapling price (and the wood) instead of wood only.

The starter gift is restored together with the refund (``gift`` is the part of the price that was paid from it), so digging up
never turns the one-time gift into freely spendable coins.
"""
from domain.address import g as address_g
from .catalog import CROPS, ROUTES, ITEMS, RECIPES, BUILDINGS, UPGRADES, trip_kind, upgrade_coins, effective_level
from . import progression
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
    from . import fertilizer
    crop = obj.get('crop')
    need(obj['type'] == 'plot', 'wrong_object', 'Выкопать можно только посадку на грядке.')
    need(crop is not None, 'empty_plot', 'Грядка уже свободна.')
    need(crop['ready_at'] > now, 'ripe', 'Урожай уже созрел — лучше собрать его.')
    fertilizer.give_back(farm, crop)   # an unripe fertilized bed returns the unit at any moment, even after the undo window
    if crop.get('seed'):     # a foreign crop: no coins were paid; inside the undo window the seed unit comes back, later it is lost
        back = now - crop['planted_at'] <= UNDO_WINDOW
        if back:
            inventory(farm, {crop['seed']: 1})
        obj['crop'] = None
        obj['revision'] += 1
        name = ITEMS[crop['id']]['name']
        return f'{name}: посадка отменена, семена вернулись на склад.' if back else f'{name}: выкопано. Семена не вернулись.'
    refund, full = crop_refund(crop, now)
    farm['coins'] += refund
    restore_gift(farm, crop.get('gift', 0), refund)
    obj['crop'] = None
    obj['revision'] += 1
    name = CROPS[crop['id']]['name'] if crop['id'] in CROPS else crop['id']
    if full:
        return f'{name}: посадка отменена, семена возвращены полностью: +{refund} монет.'
    return f'{name}: выкопано. Вернулась половина цены семян: +{refund} монет, опыта нет.'


STARTER_IDS = frozenset([*(f'building_{i}' for i in range(4)), *(f'plot_{i}' for i in range(6))])   # what ``domain.new_farm`` hands out


def is_starter(obj):
    """An object that came with the farm: ``new_farm`` gives it an id ``building_N`` / ``plot_N`` and no record of a price (bought ones
    carry ``paid`` since E27, and earlier ones got a command id, never ``building_N`` / ``plot_N``)."""
    return obj.get('id') in STARTER_IDS and 'paid' not in obj


def building_invested(obj):
    """Coins put into a placed object: what was paid for it (recorded on buildings bought since E27; a building bought earlier
    has no record and counts at the current catalog price; a bed costs 35) plus the coin price of its upgrades. Decor (roads included)
    and beds are refunded like buildings; a starter object counts only its upgrades, a caravan gift (``paid == 0``) nothing."""
    spec = BUILDINGS.get(obj['type'])
    if obj['type'] != 'plot' and not spec:
        return 0
    if is_starter(obj):
        base = 0
    elif type(obj.get('paid')) is int and obj['paid'] >= 0:
        base = obj['paid']
    else:
        base = 35 if obj['type'] == 'plot' else spec['cost']
    upgrades = 0
    if spec and not spec.get('decor'):
        upgrades = sum(upgrade_coins(obj['type'], to) for to in range(2, effective_level(obj.get('level')) + 1))
    return base + upgrades


def upgrade_materials(obj):
    """Goods spent on the upgrades of this object up to its level (the sum of ``UPGRADES[n]['items']``)."""
    spec = BUILDINGS.get(obj['type'])
    out = {}
    if (spec and not spec.get('decor')) or obj['type'] == 'barn':
        for to in range(2, effective_level(obj.get('level')) + 1):
            for item, qty in UPGRADES[to]['items'].items():
                out[item] = out.get(item, 0) + qty
    return out


def demolish_refund(obj, now):
    """(coins, goods, full?) given back for demolishing this empty object now: everything inside the first ``UNDO_WINDOW`` seconds after it
    was built (a mis-tap), later ``LATE_REFUND_PCT`` percent of the coins and of the upgrade goods (rounded down)."""
    coins, goods = building_invested(obj), upgrade_materials(obj)
    if type(obj.get('built_at')) is int and now - obj['built_at'] <= UNDO_WINDOW:
        return coins, goods, True
    return (coins * LATE_REFUND_PCT // 100,
            {k: q * LATE_REFUND_PCT // 100 for k, q in goods.items() if q * LATE_REFUND_PCT // 100 > 0}, False)


def demolish(farm, obj, now):
    """Remove an empty building, decor or bed (the caller has checked that nothing is growing, cooking or living in it)."""
    building = BUILDINGS.get(obj['type'])
    name = building['name'] if building else 'Объект'
    refund, goods, full = demolish_refund(obj, now)
    farm['coins'] += refund
    restore_gift(farm, obj.get('gift', 0), refund)
    if goods:
        inventory(farm, goods)
    xp = obj.get('build_xp')
    if type(xp) is int:        # always, in the window and after it: the 5 XP of building must not be farmed (never below the level start)
        if xp > 0:
            progression.revoke_xp(farm, xp)
        if farm['stats'].get('builds', 0) > 0:
            farm['stats']['builds'] -= 1
    wood = 0
    if not full and building and not building.get('decor'):
        wood = 4 + effective_level(obj.get('level')) - 1
        inventory(farm, {'wood': wood})
    farm['objects'].remove(obj)
    back = []
    if refund:
        back.append(f'+{refund} монет')
    back += [f'{ITEMS[k]["name"] if k in ITEMS else k} ×{q}' for k, q in goods.items()]
    if wood:
        back.append(f'древесина ×{wood}')
    if full:
        return f'{name}: убрано в первую минуту, вложенное вернулось полностью' + (': ' + ', '.join(back) if back else '') + '.'
    return f'{name}: разобрано. Вернулась половина вложенного' + (': ' + ', '.join(back) if back else ', ничего не вернулось') + '.'


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
