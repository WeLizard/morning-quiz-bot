"""r8 market rules: residents' reputation, the caravan (big order) and daily contracts.

Pure state transitions, additive to the farm aggregate (``farm['market']``). No timers, IO or client time:
every deadline and day boundary is evaluated from the trusted ``now`` passed by the service (``settle``).
Old farms get an empty market on first load; nothing is granted retroactively.
"""
from hashlib import sha256
import math
from .catalog import (CROPS, ITEMS, RECIPES, NPCS, REP_NAMES, REP_POINTS, REP_BONUS, REP_SPECIAL_LEVEL, NPC_TASTES,
                      MARKET, PLOT_LIMITS, level, income_ref, OLD_ORCHARD_PRICES)
from .domain import need, find, inventory, event, unbound
from . import progression, textile

SCHEMAS = {
    'caravan_fill': {'crate'},
    'contract_claim': {'contract'},
}
CARAVAN = MARKET['caravan']
CONTRACTS = MARKET['contracts']
TZ_OFFSET = CONTRACTS['tz_offset']      # Europe/Moscow has no DST: a fixed UTC+3
MAX_REP_LEVEL = len(REP_POINTS) - 1


def moscow_day(now):
    return int((now + TZ_OFFSET) // 86400)


def blank():
    return dict(rep={}, counts={}, caravan=None, caravan_next_at=0, caravan_seq=0, caravans_done=0, caravans_failed=0, last_caravan=None,
                contracts=dict(day=-1, items=[]), streak=dict(last_day=-1, count=0), decor_credits=[])


def upgrade_market(farm):
    m = farm.setdefault('market', blank())
    for key, value in blank().items():
        m.setdefault(key, value)
    car = m.get('caravan')
    if car and any('unit_price' not in c for c in car['crates']):
        # Old saves recorded the aggregate value, but no per-crate prices. Recognise the old orchard
        # catalog by that exact total; otherwise use today's prices. Existing snapshots always win.
        old_value = sum(OLD_ORCHARD_PRICES.get(c['item'], ITEMS[c['item']]['price']) * c['qty'] for c in car['crates'])
        old_catalog = old_value == car['value']
        for c in car['crates']:
            price = OLD_ORCHARD_PRICES.get(c['item'], ITEMS[c['item']]['price']) if old_catalog else ITEMS[c['item']]['price']
            c.setdefault('unit_price', price)
    return m


def _rng(*parts):
    return int(sha256(':'.join(str(p) for p in parts).encode()).hexdigest()[:16], 16)


# --- reputation ------------------------------------------------------------------------------------------
def rep_level(points):
    return max(i for i, need_points in enumerate(REP_POINTS) if points >= need_points)


def rep_state(farm, npc):
    points = farm.get('market', {}).get('rep', {}).get(npc, 0)
    lv = rep_level(points)
    return dict(points=points, level=lv, name=REP_NAMES[lv], bonus=lv * REP_BONUS,
                next_at=REP_POINTS[lv + 1] if lv < MAX_REP_LEVEL else None)


def add_rep(farm, npc, points):
    m = upgrade_market(farm)
    m['rep'][npc] = min(10 ** 6, m['rep'].get(npc, 0) + points)


def boost(farm, npc, amount):
    return amount * (100 + rep_state(farm, npc)['bonus']) // 100


def order_reward(farm, order):
    return boost(farm, order['npc'], order['coins']), boost(farm, order['npc'], order['xp'])


def after_order(farm, order, now):
    """Called by the order command once goods are taken: reputation grows, contracts see the delivery."""
    before = rep_state(farm, order['npc'])['level']
    add_rep(farm, order['npc'], 2 if order.get('special') else 1)
    count(farm, 'orders', 1)
    after = rep_state(farm, order['npc'])
    if after['level'] > before:
        event(farm, now, f'{order["npc"]}: теперь «{after["name"]}». Награды за его заказы выше на {after["bonus"]}%.', 'reputation')


def special_needs(farm, rng, npc, products):
    """A resident of sufficient reputation sometimes asks for a favourite good (deterministic, reachable only)."""
    if rep_state(farm, npc)['level'] < REP_SPECIAL_LEVEL or (rng // 7) % 4 != 0:
        return None
    wish = [i for i in NPC_TASTES[npc] if i in products]
    if not wish:
        return None
    item = wish[(rng // 13) % len(wish)]
    qty = 1 + (rng // 11) % 3
    if ITEMS[item]['price'] * qty > 1500:
        qty = 1
    return {item: qty}


# --- counters feeding the contracts -----------------------------------------------------------------------
def count(farm, key, qty):
    m = farm.get('market')
    if m is None:
        m = upgrade_market(farm)
    m['counts'][key] = min(10 ** 9, m['counts'].get(key, 0) + qty)


def count_outputs(farm, outputs):
    for item, qty in outputs.items():
        count(farm, 'p:' + item, qty)


# --- balance model ------------------------------------------------------------------------------------------
LAND_AT_LEVEL = ((1, 8), (3, 12), (6, 14), (9, 16), (13, 18), (18, 20))


def typical_size(lv):
    return [size for l, size in LAND_AT_LEVEL if l <= lv][-1]


def reference_daily_income(lv):
    """Lower bound of an active player's daily coins: crops only (no workshops/animals), 70% of the plot limit,
    the best available crop, at most 3 harvests per plot per day and half of the crop's theoretical cycles, halved again."""
    plots = int(PLOT_LIMITS[typical_size(lv)] * 0.7)
    best = 0
    for c in CROPS.values():
        if c['level'] <= lv:
            profit = c['yield_qty'] * ITEMS[c['id']]['price'] - c['cost']
            best = max(best, profit * min(3, 86400 / c['seconds'] * 0.5))
    return round(0.5 * plots * best)


def _crop_prices(lv):
    return sorted(ITEMS[c['id']]['price'] for c in CROPS.values() if c['level'] <= lv)


# --- caravan ---------------------------------------------------------------------------------------------
def caravan_target(lv):
    return max(150, round(income_ref(lv) * CARAVAN['value_share'] / 100))


def crate_count(lv):
    return 3 + min(3, max(0, lv - CARAVAN['level']) // 5)


def reachable_items(farm):
    from .domain import reachable
    return reachable(farm)


def make_caravan(farm, now):
    m = upgrade_market(farm)
    seq = m['caravan_seq']
    m['caravan_seq'] += 1
    rng = _rng(farm['id'], 'caravan', seq)
    lv = level(farm['xp'])
    n = crate_count(lv)
    each = caravan_target(lv) / n
    products = reachable_items(farm)
    pool = sorted(i for i in products if each / 10 <= ITEMS[i]['price'] <= each * 1.5 and ITEMS[i]['price'] >= 8)
    if len(pool) < n:
        pool = sorted(i for i in products if ITEMS[i]['price'] >= 8) or sorted(products)
    chosen = sorted(pool, key=lambda i: _rng(rng, i))[:n]
    crates = [dict(item=i, qty=max(1, min(12, round(each / ITEMS[i]['price']))), done=False, unit_price=ITEMS[i]['price']) for i in chosen]
    value = sum(ITEMS[c['item']]['price'] * c['qty'] for c in crates)
    npc = NPCS[(rng // 5) % len(NPCS)][0]
    hours = CARAVAN['min_hours'] + (rng // 29) % (CARAVAN['max_hours'] - CARAVAN['min_hours'] + 1)
    decor = CARAVAN['decor'][(rng // 101) % len(CARAVAN['decor'])] if (rng // 53) % 100 < CARAVAN['decor_chance'] else None
    m['caravan'] = dict(id=f'caravan_{seq}', npc=npc, started_at=now, deadline=now + hours * 3600, crates=crates,
                        value=value, coins=math.ceil(value * (100 + CARAVAN['premium']) / 100),
                        xp=max(5, value // CARAVAN['xp_div']), decor=decor)
    event(farm, now, f'К ферме подъехал обоз: {npc} просит {len(crates)} ящиков до {hours} ч. Загляни на доску заказов.', 'caravan')


def caravan_payout(farm, car):
    return boost(farm, car['npc'], car['coins']), boost(farm, car['npc'], car['xp'])


def settle_caravan(farm, now):
    m = upgrade_market(farm)
    car = m['caravan']
    if car and now >= car['deadline']:
        # Refund the shop value recorded on arrival, even if the catalog changed while the caravan waited.
        refund = sum(c['unit_price'] * c['qty'] for c in car['crates'] if c['done'])
        farm['coins'] += refund
        m['caravans_failed'] += 1
        m['last_caravan'] = dict(ok=False, npc=car['npc'], refund=refund, at=car['deadline'])
        m['caravan'] = None
        m['caravan_next_at'] = car['deadline'] + CARAVAN['cooldown_hours'] * 3600
        event(farm, now, 'Обоз уехал: время вышло.' + (f' За привезённые ящики вернули {refund} монет.' if refund else ''), 'caravan')
        car = None
    if car is None and level(farm['xp']) >= CARAVAN['level'] and now >= m['caravan_next_at']:
        make_caravan(farm, now)


# --- contracts ---------------------------------------------------------------------------------------------
def counter_key(kind, item):
    return 'orders' if kind == 'orders' else ('h:' if kind == 'harvest' else 'p:') + item


def contract_key(c):
    return counter_key(c['kind'], c['item'])


def contract_progress(farm, c):
    return max(0, farm['market']['counts'].get(contract_key(c), 0) - c['base'])


def make_contracts(farm, day):
    m = farm['market']
    lv = level(farm['xp'])
    rng = _rng(farm['id'], 'contracts', day)
    crops = sorted(c['id'] for c in CROPS.values() if c['level'] <= lv and c['seconds'] <= 14400 and not c.get('orchard'))   # orchard fruit grows on trees
    types = {o['type'] for o in farm['objects']}
    recipes = sorted(r['id'] for r in RECIPES.values() if textile.recipe_level(farm, r) <= lv and r['building'] in types and not r.get('exclusive')
                     and sum(ITEMS[k]['price'] for k in r['outputs']) >= 8)
    items = []

    def add(kind, item, goal, value, coins_min, share, xp):
        key = counter_key(kind, item)
        items.append(dict(id=f'contract_{day}_{len(items)}', kind=kind, item=item, goal=goal,
                          base=m['counts'].get(key, 0), coins=max(coins_min, round(value * share)), xp=xp, claimed=False))
    plots = 4 + min(10, lv // 2)
    crop = crops[rng % len(crops)]
    add('harvest', crop, CROPS[crop]['yield_qty'] * plots, CROPS[crop]['yield_qty'] * plots * ITEMS[crop]['price'], 5 + lv, 0.15, 2 + lv // 4)
    if recipes:
        rid = recipes[(rng // 11) % len(recipes)]
        out = next(iter(RECIPES[rid]['outputs']))
        goal = max(2, min(12, round((140 + 8 * lv) / ITEMS[out]['price'])))
        add('craft', out, goal, goal * ITEMS[out]['price'], 6 + lv, 0.2, 3 + lv // 3)
    else:
        other = [c for c in crops if c != crop] or crops
        crop2 = other[(rng // 11) % len(other)]
        add('harvest', crop2, CROPS[crop2]['yield_qty'] * (plots - 1), CROPS[crop2]['yield_qty'] * (plots - 1) * ITEMS[crop2]['price'], 5 + lv, 0.15, 2 + lv // 4)
    add('orders', None, 2 + lv // 10, 0, 6 + 2 * lv, 0, 4 + lv // 2)
    m['contracts'] = dict(day=day, items=items)


def streak_bonus(farm, day):
    s = farm['market']['streak']
    if s['last_day'] in (day, day - 1):
        return min(CONTRACTS['streak_max'], s['count']) * CONTRACTS['streak_step']
    return 0


def settle(farm, now):
    """Server-authoritative market clock: caravan arrival/expiry and the Moscow-day contract reset."""
    m = upgrade_market(farm)
    settle_caravan(farm, now)
    day = moscow_day(now)
    if m['contracts']['day'] != day:  # generated at every level, so a level-up never changes a settled farm
        make_contracts(farm, day)


# --- commands ----------------------------------------------------------------------------------------------
def apply_market(farm, kind, data, now, command_id):
    settle(farm, now)
    m = farm['market']
    if kind == 'caravan_fill':
        car = m['caravan']
        need(car is not None, 'no_caravan', 'Обоза сейчас нет.')
        crate = data['crate']
        need(type(crate) is int and 0 <= crate < len(car['crates']), 'invalid_crate', 'Такого ящика нет.', 422)
        c = car['crates'][crate]
        need(not c['done'], 'crate_done', 'Этот ящик уже погружен.')
        unbound([c['item']])
        inventory(farm, {c['item']: c['qty']}, -1)
        c['done'] = True
        text = f'Ящик погружен: {ITEMS[c["item"]]["name"]} ×{c["qty"]}.'
        if all(x['done'] for x in car['crates']):
            coins, xp = caravan_payout(farm, car)
            farm['coins'] += coins
            xp = progression.grant_xp(farm, xp, 'caravan', now, True)
            add_rep(farm, car['npc'], CARAVAN['rep_points'])
            m['caravans_done'] += 1
            m['last_caravan'] = dict(ok=True, npc=car['npc'], coins=coins, xp=xp, at=now)
            m['caravan'] = None
            m['caravan_next_at'] = now + CARAVAN['cooldown_hours'] * 3600
            text = f'Обоз собран! {car["npc"]} благодарит: +{coins} монет, +{xp} XP.'
            if car.get('decor') and len(m['decor_credits']) < 5:
                m['decor_credits'].append(car['decor'])
                text += ' В подарок — бесплатный декор (в стройке).'
        return text
    if kind == 'contract_claim':
        need(level(farm['xp']) >= CONTRACTS['level'], 'locked', f'Контракты откроются с {CONTRACTS["level"]} уровня.')
        c = find(m['contracts']['items'], data['contract'])
        need(not c['claimed'], 'already_claimed', 'Награда уже получена.')
        need(contract_progress(farm, c) >= c['goal'], 'contract_incomplete', 'Контракт ещё не выполнен.')
        day = m['contracts']['day']
        bonus = streak_bonus(farm, day)
        coins, xp = c['coins'] * (100 + bonus) // 100, c['xp'] * (100 + bonus) // 100
        c['claimed'] = True
        farm['coins'] += coins
        xp = progression.grant_xp(farm, xp, 'contract', now, True)
        if all(x['claimed'] for x in m['contracts']['items']):
            s = m['streak']
            if s['last_day'] != day:
                s['count'] = s['count'] + 1 if s['last_day'] == day - 1 else 1
                s['last_day'] = day
        return f'Контракт выполнен: +{coins} монет, +{xp} XP' + (f' (серия +{bonus}%).' if bonus else '.')
    raise AssertionError('Unknown market command')


def free_decor(farm, typ):
    return typ in farm.get('market', {}).get('decor_credits', [])


def take_decor(farm, typ):
    farm['market']['decor_credits'].remove(typ)


def validate_market(farm):
    m = farm.get('market')
    if m is None:
        return
    need(isinstance(m, dict) and all(k in m for k in blank()), 'invalid_market', 'Некорректное состояние рынка.', 500)
    need(all(k in {n for n, _ in NPCS} and type(v) is int and 0 <= v <= 10 ** 6 for k, v in m['rep'].items()),
         'invalid_market', 'Некорректная репутация.', 500)
    car = m['caravan']
    if car:
        need(3 <= len(car['crates']) <= 6 and all(c['item'] in ITEMS and type(c['qty']) is int and 1 <= c['qty'] <= 12
                                                    and ('unit_price' not in c or (type(c['unit_price']) is int and c['unit_price'] >= 0))
                                                    for c in car['crates']), 'invalid_market', 'Некорректный обоз.', 500)
    need(len(m['contracts']['items']) <= 3 and len(m['decor_credits']) <= 5, 'invalid_market', 'Некорректные контракты.', 500)


# --- balance table (documentation and tests) --------------------------------------------------------------
def max_extra_daily(lv, orders_per_day=6):
    """Upper bound of what the r8 systems add per day for an active player (coins + XP, 1 XP counted as 1 coin).

    The caravan counts every 24 h cooldown (one per cooldown, at most one a day); contracts include the full streak bonus; reputation counts
    the maximum +25% on ``orders_per_day`` average orders plus the +20% favourite-goods premium on a quarter of them.
    """
    out = {}
    if lv >= CARAVAN['level']:
        value = caravan_target(lv)
        coins = math.ceil(value * (100 + CARAVAN['premium']) / 100) * (100 + REP_BONUS * MAX_REP_LEVEL) // 100
        xp = max(5, value // CARAVAN['xp_div']) * (100 + REP_BONUS * MAX_REP_LEVEL) // 100
        out['caravan'] = round((coins - value + xp) * 24 / CARAVAN['cooldown_hours'])
    plots = 4 + min(10, lv // 2)
    wheatish = [c for c in CROPS.values() if c['level'] <= lv and c['seconds'] <= 14400]
    dearest = max(c['yield_qty'] * plots * ITEMS[c['id']]['price'] for c in wheatish)
    contracts = max(5 + lv, round(dearest * 0.15)) + max(6 + lv, round((140 + 8 * lv) * 0.2)) + 6 + 2 * lv
    xps = 2 + lv // 4 + 3 + lv // 3 + 4 + lv // 2
    mult = 100 + CONTRACTS['streak_step'] * CONTRACTS['streak_max']
    out['contracts'] = (contracts + xps) * mult // 100 if lv >= CONTRACTS['level'] else 0
    prices = _crop_prices(lv)
    top = prices[-max(1, len(prices) // 3):]
    avg_order = 1.45 * (sum(top) / len(top)) * 2 + 6
    out['reputation'] = round(orders_per_day * avg_order * (REP_BONUS * MAX_REP_LEVEL / 100 + 0.25 * 0.20))
    out['total'] = sum(out.values())
    # The caravan and its share use the same late-game reference; retain the original pre-caravan model.
    out['reference'] = income_ref(lv) if lv >= CARAVAN['level'] else reference_daily_income(lv)
    out['share'] = round(out['total'] / max(1, out['reference']), 3)
    return out
