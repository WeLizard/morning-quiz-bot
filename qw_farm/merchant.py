"""Странствующая торговка «Сорока-коробейница» (docs/tasks/FARM_VILLAGE_MINIGAMES.md section 2).

Server-authoritative and pure. Time is the fixed UTC+3 Moscow day (``economy.moscow_day``), never the device clock.

Schedule (shared by all players, no storage): in every Moscow week (Mon-Sun) two visits of 24 h on two different weekdays that are
never adjacent, chosen from ``sha256(season, week)``; plus every day the festival engine says she is at the fair (``festivals.current``
-> ``magpie``). A fair day that is also a regular day is ONE visit (a day cannot hold two). ``visit_id`` is ``v<moscow day>``.

Stock v2 (docs/tasks/FARM_MERCHANT_V2.md sections 2-4): one cheap beginner pack and five weighted places, derived with HMAC-SHA256
from a persistent server secret, farm id, visit id and half. Catalog rarity weights are common 60 / uncommon 30 / rare 10; a single
25-percent visit roll reserves one place for an unowned curio from another seasonal series (the four other series of the cyclic catalog).
No repeated ids within a set; previous-visit ids are avoided while candidates allow it. Existing catalog rows feed the pool.
At opens_at + 12 h, three non-fully-bought places 1..5 are replaced; item purchase limits span both halves. Prices retain the value law.
QW_FARM_MERCHANT_SECRET (32+ chars), otherwise a separated derivation from persistent QW_FARM_INVITE_SECRET or BOT_TOKEN, is required.
There is no process/public fallback: absent/short persistent configuration fails closed. Do not rotate keys during visits.

State: ``farm['merchant'] = {visit_id, bought{slot: n}, sold_value, curios[], scrolls[], seed_bank{}, stock_v2?}``. Schema version stays.
A new visit lazily clears counters and records initial ownership, previous offered ids, purchases by item id, and fully-bought first-half
slots in stock_v2. No prices/assortment snapshots are stored. Commands persist this metadata; projections are pure. An old current visit
without stock_v2 finishes entirely under v1 slot-index rules. Known previous command visits replay their actual two halves; no-command
visits replay deterministic draws without purchases from the launch anchor. ``seed_bank`` remains reserved (always {}).
Scrolls unlock their recipe on purchase (no scroll item); curios are bound decor placed for free from ``curios``; seed packs and dyes go to the
warehouse as bound items (``ITEMS[..]['bound']``: never gifted, listed, sold, funded or crated).

Commands (owner only; idempotent through ``command_id`` in the service, one ledger record each; undo does not apply):
  ``merchant_buy {visit_id, slot, qty}`` and ``merchant_sell {visit_id, item, qty}`` (the buy-back: +30 percent on the warehouse price, at most
  2 percent of ``income_ref`` of the player's level per visit, counted at the warehouse price).
The client sends only the visit id, the slot number and the quantity; item, price and limit are the server's. V2 owner projection uses
the opaque visit tokens ``v<day>:h1`` and ``v<day>:h2``: stale legacy/first-half buy commands are refused rather than buying another item.
The stored visit id stays ``v<day>``; sell accepts its canonical id too. Owner slots expose rarity and next_restock_at gives the next supply.
"""
from hashlib import sha256
from functools import lru_cache
import hmac
import math
import os

from .catalog import ITEMS, CURIOS, CURIO_SERIES, SCROLL_RECIPES, RECIPES, EXOTIC_CROPS, DYES, MERCHANT, ORCHARD_ROWS, ORCHARD_WIRED, TREE_VOUCHER_DISCOUNT_PCT, income_ref, level, tick
from .domain import need, inventory, pay
from . import economy, festivals, construction

DAY = 86400
TZ_OFFSET = economy.TZ_OFFSET
SLOTS = MERCHANT['slots']
SCHEMAS = {'merchant_buy': {'visit_id', 'slot', 'qty'}, 'merchant_sell': {'visit_id', 'item', 'qty'}}
ORCHARD_IDS = tuple(r[0] for r in ORCHARD_ROWS)
MAX_BOUGHT = 1000
RESTOCK = MERCHANT['restock_hours'] * 3600


def _h(*parts):
    return int(sha256(':'.join(str(p) for p in parts).encode()).hexdigest()[:16], 16)


def _ts(day):
    """Unix time of 00:00 Moscow of the day number."""
    return day * DAY - TZ_OFFSET


def weekday(day):
    """0 = Monday. Day 0 (1970-01-01) was a Thursday."""
    return (day + 3) % 7


def week_of(day):
    return (day + 3) // 7


# ----------------------------------------------------------------------------------------------------------------------
# Schedule
# ----------------------------------------------------------------------------------------------------------------------
PAIRS = tuple((a, b) for a in range(7) for b in range(a + 2, 7))        # two different weekdays, never next to each other


def _raw_pair(week):
    monday = week * 7 - 3
    return PAIRS[_h('magpie-week', economy.season_of(_ts(monday)), week) % len(PAIRS)]


def _pair(week):
    """The week's two weekdays; a Monday that would follow the previous Sunday is moved so that visits are never on consecutive days."""
    a, b = _raw_pair(week)
    if a == 0 and _raw_pair(week - 1)[1] == 6:
        a, b = 2, 4
    return a, b


def scheduled(day):
    return weekday(day) in _pair(week_of(day))


def _fair_day(day):
    cur = festivals.current(_ts(day) + DAY // 2)
    return cur if cur is not None and cur['magpie'] else None


def visit_on(day):
    """The visit lying on a Moscow day number, or None."""
    fair = _fair_day(day)
    if not scheduled(day) and fair is None:
        return None
    return dict(visit_id=f'v{day}', day=day, opens_at=_ts(day), closes_at=_ts(day + 1), kind='fair' if fair else 'regular',
                fair=fair and dict(id=fair['id'], name=fair['name'], key=fair['key']))


def visit_at(now):
    """The visit open right now, or None."""
    return visit_on(economy.moscow_day(tick(now)))


def next_visit(now, horizon=30):
    """The first visit that begins after the current moment, or None."""
    day = economy.moscow_day(tick(now))
    for ahead in range(1, horizon + 1):
        v = visit_on(day + ahead)
        if v is not None:
            return v
    return None


def _previous_day(day, horizon=21):
    for back in range(1, horizon + 1):
        if visit_on(day - back) is not None:
            return day - back
    return None


# ----------------------------------------------------------------------------------------------------------------------
# Assortment
# ----------------------------------------------------------------------------------------------------------------------
def _k_price(k, lv):
    return max(1, -(-k * income_ref(lv) // 100))


def _entries():
    rows = []
    for c in EXOTIC_CROPS.values():
        rows.append(dict(id=c['seed'], kind='exotic_seed', item=c['seed'], name=f'Заморские семена: {c["name"].lower()}', qty=MERCHANT['pack'],
                         min_level=c['level'], price=c['pack_price'], limit=MERCHANT['limits']['exotic_seed'], cheap=c['level'] <= 8,
                         note=f'Пакет на {MERCHANT["pack"]} посадки. Только на грядку, урожай семян не даёт.'))
    for d in DYES:
        rows.append(dict(id=d, kind='dye', item=d, name=ITEMS[d]['name'], qty=1, min_level=ITEMS[d]['level'], price=ITEMS[d]['price'],
                         limit=MERCHANT['limits']['dye'], cheap=False, note='Краситель для швейной мастерской.'))
    for r in SCROLL_RECIPES:
        rows.append(dict(id='scroll_' + r, kind='scroll', item=None, recipe=r, name=f'Свиток: {RECIPES[r]["name"]}', qty=1, min_level=RECIPES[r]['level'],
                         price=_k_price(MERCHANT['scroll_k'], RECIPES[r]['level']), limit=MERCHANT['limits']['scroll'], cheap=False,
                         note='Открывает рецепт навсегда.'))
    for cid, c in CURIOS.items():
        rows.append(dict(id=cid, kind='curio', item=None, name=c['name'], qty=1, min_level=c['level'], price=_k_price(c['k'], c['level']),
                         limit=MERCHANT['limits']['curio'], cheap=False, series=c['series'], series_name=c['series_name'],
                         note=f'Диковинка серии «{c["series_name"]}». Один раз на ферму.'))
    for gid, name, kind, lv, k in ORCHARD_ROWS:
        note = ('Меняет облик посаженного дерева. Урожай и место в саду прежние.' if kind == 'graft'
                else f'Скидка {TREE_VOUCHER_DISCOUNT_PCT}% на саженец. Сажается во вкладке «Сад».')
        rows.append(dict(id=gid, kind=kind, item=gid, name=name, qty=1, min_level=lv, price=_k_price(k, lv), limit=MERCHANT['limits'][kind],
                         cheap=False, wired=ORCHARD_WIRED, note=note))
    return {r['id']: r for r in rows}


ENTRIES = _entries()
for _r in ENTRIES.values():
    _r.setdefault('wired', True)


def _pool(kinds, series=None):
    return sorted((e for e in ENTRIES.values() if e['kind'] in kinds and (e['wired'] or ORCHARD_WIRED)
                   and (series is None or e.get('series') == series)), key=lambda e: e['id'])


def series_of(day):
    ids = [s[0] for s in CURIO_SERIES]
    return ids[economy.season_of(_ts(day)) % len(ids)]


def _pick(candidates, used, avoid, salt):
    free = [e for e in candidates if e['id'] not in used]
    fresh = [e for e in free if e['id'] not in avoid] or free
    return fresh[_h('magpie-slot', *salt) % len(fresh)] if fresh else None


def _picks(day, avoid):
    series = series_of(day)
    # slot 0 is the cheap seed pack of a beginner; the other seed/dye slots never take a cheap pack, so a neighbouring visit always has a fresh one
    plan = [(('exotic_seed',), True), (('exotic_seed', 'dye'), False), (('scroll',), False), (('curio',), False), (('curio',), False),
            (('exotic_seed', 'dye', 'scroll'), False)]
    if ORCHARD_WIRED and _h('magpie-orchard', day) % 2 == 0:    # every other visit the last slot carries something for the garden
        plan[5] = (('graft', 'voucher'), False)
    used, out = set(), []
    for slot, (kinds, cheap) in enumerate(plan):
        pool = [e for e in _pool(kinds, series if kinds == ('curio',) else None) if e['cheap'] == cheap]
        e = _pick(pool, used, avoid, (day, slot))
        if e is not None:
            used.add(e['id'])
            out.append(e)
    return out


ANCHOR = festivals.day_number(festivals.LAUNCH)     # the chain of «no repeats» starts at the launch of the engine
_CHAIN = {}


def _chain(day):
    """The real stock of a visit day: picks that avoid the real stock of the previous visit. Anchored at ANCHOR, so it is a pure function of the day."""
    if day < ANCHOR:
        return _picks(day, set())
    todo, d = [], day
    while d is not None and d >= ANCHOR and d not in _CHAIN:
        todo.append(d)
        d = _previous_day(d)
    prev = _CHAIN.get(d) if d is not None else None
    for x in reversed(todo):
        prev = _CHAIN[x] = _picks(x, {e['id'] for e in prev} if prev else set())
    return _CHAIN[day]


def stock_secret():
    """Stable server key only: explicit key, or a domain-separated existing persistent secret.

    A process secret or a public default would change the goods after restart or make them predictable.
    Configure QW_FARM_MERCHANT_SECRET (32+ characters) on every API worker; keep it unchanged during visits.
    """
    for name in ('QW_FARM_MERCHANT_SECRET', 'QW_FARM_INVITE_SECRET', 'BOT_TOKEN'):
        value = os.getenv(name, '')
        if value:
            if len(value) < 32:
                raise RuntimeError(f'{name} must contain at least 32 characters for merchant stock')
            return hmac.new(value.encode(), b'qw-farm:merchant-stock:v2', sha256).digest()
    raise RuntimeError('Configure QW_FARM_MERCHANT_SECRET or a persistent QW_FARM_INVITE_SECRET/BOT_TOKEN')


def _roll(key, farm_id, day, half, *purpose):
    message = ':'.join(map(str, ('merchant-v2', farm_id, f'v{day}', half, *purpose)))
    return int.from_bytes(hmac.new(key, message.encode(), sha256).digest(), 'big')


def _rarity(entry):
    return MERCHANT['rarity_by_kind'][entry['kind']]


def _weighted(candidates, used, avoid, key, farm_id, day, half, slot):
    free = [e for e in candidates if e['id'] not in used]
    free = [e for e in free if e['id'] not in avoid] or free
    groups = [(r, w, [e for e in free if _rarity(e) == r]) for r, w in MERCHANT['rarity_weights'].items()]
    groups = [(r, w, es) for r, w, es in groups if es and w > 0]
    if not groups:
        return None
    roll = _roll(key, farm_id, day, half, slot, 'rarity') % sum(w for _, w, _ in groups)
    for rarity, weight, entries in groups:
        if roll < weight:
            return dict(entries[_roll(key, farm_id, day, half, slot, 'item') % len(entries)], rarity=rarity)
        roll -= weight


def _v2_initial(key, farm_id, day, owned, avoid):
    available = [e for e in ENTRIES.values() if e['wired'] or ORCHARD_WIRED]
    cheap = [e for e in available if e['cheap']]
    first = _weighted(cheap, set(), avoid, key, farm_id, day, 1, 0)
    out, used = [first], {first['id']}
    candidates = [e for e in available if not e['cheap'] and (e['kind'] != 'curio' or e['series'] == series_of(day))]
    past = [e for e in available if e['kind'] == 'curio' and e['series'] != series_of(day) and e['id'] not in owned]
    lottery = past and _roll(key, farm_id, day, 1, 'lot-day') % 100 < MERCHANT['lot_day_chance_pct']
    # The lot is one of the five weighted places, never a seventh place or a second roll at restock.
    lot_slot = 1 + _roll(key, farm_id, day, 1, 'lot-slot') % (SLOTS - 1) if lottery else None
    for slot in range(1, SLOTS):
        e = _weighted(past if slot == lot_slot else candidates, used, avoid, key, farm_id, day, 1, slot)
        if slot == lot_slot and e:
            e['rarity'] = 'lot_day'
        if e:
            used.add(e['id'])
            out.append(e)
    return [dict(e, slot=i) for i, e in enumerate(out)]


def _v2_restock(initial, key, farm_id, day, avoid, full):
    out = [dict(e) for e in initial]
    eligible = [e['slot'] for e in initial[1:] if e['slot'] not in full]
    eligible.sort(key=lambda slot: _roll(key, farm_id, day, 2, 'replace', slot))
    used = {e['id'] for e in initial}
    candidates = [e for e in ENTRIES.values() if (e['wired'] or ORCHARD_WIRED) and not e['cheap']
                  and (e['kind'] != 'curio' or e['series'] == series_of(day))]
    for slot in eligible[:MERCHANT['restock_slots']]:
        e = _weighted(candidates, used, avoid, key, farm_id, day, 2, slot)
        if e:
            used.add(e['id'])
            out[slot] = dict(e, slot=slot)
    return out


@lru_cache(maxsize=1024)
def _v2_replay(key, farm_id, day, owned):
    """No-command visits are replayed from the launch anchor with no purchases.

    Cache contains only derived ids; secret is part of the key, so changing it cannot reuse an old draw.
    """
    days, d = [], day
    while d is not None and d >= ANCHOR:
        days.append(d)
        d = _previous_day(d)
    previous = {e['id'] for e in _chain(d)} if d is not None else set()
    for d in reversed(days):
        initial = _v2_initial(key, farm_id, d, owned, previous)
        restocked = _v2_restock(initial, key, farm_id, d, previous, ())
        previous = {e['id'] for e in initial + restocked}
    return tuple(sorted(previous))


def _legacy(farm, visit):
    m = peek(farm)
    return visit['day'] < ANCHOR or m['visit_id'] == visit['visit_id'] and 'stock_v2' not in m


def _stock_context(farm, visit):
    m = peek(farm)
    if m['visit_id'] == visit['visit_id'] and 'stock_v2' in m:
        return m['stock_v2']
    previous_day = _previous_day(visit['day'])
    previous = []
    if previous_day is not None:
        try:
            saved_day = int(m['visit_id'][1:]) if m['visit_id'] else None
        except (ValueError, TypeError):
            saved_day = None
        if saved_day is not None and saved_day <= previous_day and visit_on(saved_day):
            prior = visit_on(saved_day)
            previous = {e['id'] for e in stock(prior, farm, prior['opens_at']) + stock(prior, farm, prior['closes_at'] - 1)}
            # Replay no-command visits FROM actual persisted history, including pins from prior purchases.
            key = stock_secret()
            for day in range(saved_day + 1, previous_day + 1):
                if visit_on(day):
                    initial = _v2_initial(key, farm['id'], day, m['curios'], previous)
                    supplied = _v2_restock(initial, key, farm['id'], day, previous, ())
                    previous = {e['id'] for e in initial + supplied}
            previous = sorted(previous)
        else:
            previous = list(_v2_replay(stock_secret(), farm['id'], previous_day, tuple(sorted(m['curios']))))
    return dict(owned=list(m['curios']), previous=previous, purchased={}, first_full=[])


def stock(visit, farm=None, now=None):
    """Owner assortment, or the v1 assortment when no farm is supplied (legacy tools/tests).

    Read-only. V2 stores purchase/history metadata, never price/item snapshots; half-two purchases cannot move the slots.
    """
    if farm is None or _legacy(farm, visit):
        return [dict(e, slot=i, rarity=_rarity(e)) for i, e in enumerate(_chain(visit['day']))]
    context, key = _stock_context(farm, visit), stock_secret()
    initial = _v2_initial(key, farm['id'], visit['day'], context['owned'], set(context['previous']))
    if now is not None and tick(now) >= visit['opens_at'] + RESTOCK:
        return _v2_restock(initial, key, farm['id'], visit['day'], set(context['previous']), context['first_full'])
    return initial


def wants(visit):
    """The one «shiny» thing she wants to buy at this visit."""
    items = MERCHANT['buyback']['items']
    return items[_h('magpie-wants', visit['day']) % len(items)]


def wants_for(farm, visit):
    """The buy-back item for THIS player: the shared one, or the next shiny item whose warehouse price fits under the player's cap."""
    items = MERCHANT['buyback']['items']
    start = _h('magpie-wants', visit['day']) % len(items)
    room = cap(farm)
    for i in range(len(items)):
        item = items[(start + i) % len(items)]
        if ITEMS[item]['price'] <= room:
            return item
    return items[start]


def teaser(visit):
    """One item of the next visit for the herald: a scroll, else a curio, else the first slot."""
    slots = stock(visit)
    pick = next((s for s in slots if s['kind'] == 'curio'), None) or next((s for s in slots if s['kind'] == 'scroll'), None) or (slots[0] if slots else None)
    return pick and pick['name']


# ----------------------------------------------------------------------------------------------------------------------
# State
# ----------------------------------------------------------------------------------------------------------------------
def blank():
    return dict(visit_id=None, bought={}, sold_value=0, curios=[], scrolls=[], seed_bank={})


def state(farm):
    """Migration for old farms: an empty record, nothing else changes."""
    m = farm.setdefault('merchant', blank())
    for k, v in blank().items():
        m.setdefault(k, v)
    return m


def peek(farm):
    return {**blank(), **(farm.get('merchant') or {})}


def _enter(farm, visit):
    m = state(farm)
    if m['visit_id'] != visit['visit_id']:
        context = _stock_context(farm, visit)
        m['visit_id'], m['bought'], m['sold_value'] = visit['visit_id'], {}, 0
        m['stock_v2'] = context
    return m


def owns_curio(farm, curio_id):
    return curio_id in peek(farm)['curios']


def owns_scroll(farm, recipe_id):
    return recipe_id in peek(farm)['scrolls']


def cap(farm):
    """Most the buy-back takes per visit, in warehouse value."""
    return income_ref(level(farm['xp'])) * MERCHANT['buyback']['cap_pct'] // 100


def validate(farm):
    m = farm.get('merchant')
    if m is None:
        return
    ok = (isinstance(m, dict) and set(m) in ({'visit_id', 'bought', 'sold_value', 'curios', 'scrolls', 'seed_bank'},
                                           {'visit_id', 'bought', 'sold_value', 'curios', 'scrolls', 'seed_bank', 'stock_v2'})
          and (m['visit_id'] is None or isinstance(m['visit_id'], str) and m['visit_id'].startswith('v'))
          and isinstance(m['bought'], dict) and all(k in {str(i) for i in range(SLOTS)} and type(v) is int and 0 <= v <= MAX_BOUGHT for k, v in m['bought'].items())
          and type(m['sold_value']) is int and 0 <= m['sold_value'] <= 10 ** 9
          and isinstance(m['curios'], list) and len(set(m['curios'])) == len(m['curios']) and all(c in CURIOS for c in m['curios'])
          and isinstance(m['scrolls'], list) and len(set(m['scrolls'])) == len(m['scrolls']) and all(s in SCROLL_RECIPES for s in m['scrolls'])
          and m['seed_bank'] == {})
    need(ok, 'invalid_merchant', 'Некорректное состояние торговки.', 500)
    if 'stock_v2' in m:
        v = m['stock_v2']
        ok = (isinstance(v, dict) and set(v) == {'owned', 'previous', 'purchased', 'first_full'}
              and isinstance(v['owned'], list) and all(type(c) is str and c in CURIOS for c in v['owned'])
              and len(v['owned']) == len(set(v['owned']))
              and isinstance(v['previous'], list) and len(v['previous']) <= SLOTS * 2
              and all(type(i) is str and i in ENTRIES for i in v['previous']) and len(v['previous']) == len(set(v['previous']))
              and isinstance(v['purchased'], dict) and len(v['purchased']) <= SLOTS * 2
              and all(k in ENTRIES and type(n) is int and 0 <= n <= MAX_BOUGHT for k, n in v['purchased'].items())
              and isinstance(v['first_full'], list) and all(type(i) is int and 0 <= i < SLOTS for i in v['first_full'])
              and len(v['first_full']) == len(set(v['first_full'])))
        need(ok, 'invalid_merchant', 'Некорректное состояние торговки.', 500)


# ----------------------------------------------------------------------------------------------------------------------
# Commands
# ----------------------------------------------------------------------------------------------------------------------
def _visit_token(farm, visit, now):
    if _legacy(farm, visit):
        return visit['visit_id']
    return visit['visit_id'] + (':h2' if now >= visit['opens_at'] + RESTOCK else ':h1')


def _open_visit(farm, visit_id, now, *, buying=False):
    visit = visit_at(now)
    need(isinstance(visit_id, str), 'invalid_command', 'Некорректные параметры действия.', 422)
    need(visit is not None, 'merchant_away', 'Сорока сейчас не в деревне.')
    expected = _visit_token(farm, visit, now)
    need(visit_id == expected if buying else visit_id in (visit['visit_id'], expected),
         'stale_visit', 'Прилавок уже обновился. Обнови ферму.')
    return visit


def buy(farm, data, now):
    visit = _open_visit(farm, data['visit_id'], now, buying=True)
    slot, qty = data['slot'], data['qty']
    need(type(slot) is int and 0 <= slot < SLOTS, 'invalid_command', 'Такого места на прилавке нет.', 422)
    need(type(qty) is int and 1 <= qty <= 100, 'invalid_number', 'Недопустимое количество.', 422)
    slots = stock(visit, farm, now)
    need(slot < len(slots), 'unknown_item', 'Этот предмет не найден.', 422)
    e = slots[slot]
    m = state(farm)
    legacy = _legacy(farm, visit)
    context = None if legacy else _stock_context(farm, visit)
    bought = ((m['bought'].get(str(slot), 0) if m['visit_id'] == visit['visit_id'] else 0) if legacy
              else context['purchased'].get(e['id'], 0))
    need(level(farm['xp']) >= e['min_level'], 'locked', f'Нужен уровень {e["min_level"]}.')
    if e['kind'] == 'curio':
        need(e['id'] not in m['curios'], 'already_owned', 'Эта диковинка уже в твоей коллекции.')
    if e['kind'] == 'scroll':
        need(e['recipe'] not in m['scrolls'], 'already_owned', 'Этот рецепт ты уже знаешь.')
    need(bought + qty <= e['limit'] + construction.merchant_extra(farm, slot, now), 'limit_reached', 'На этот визит больше не продам.')
    if e['kind'] == 'graft':
        from . import orchard
        need(orchard.can_buy_graft(farm, e['item']), 'no_tree', 'Прививка нужна для посаженного дерева: сначала посади его.')
    cost = construction.merchant_price(farm, e['price'] * qty)   # «помощник» торговых рядов: −10%
    pay(farm, cost)
    _enter(farm, visit)
    m['bought'][str(slot)] = m['bought'].get(str(slot), 0) + qty
    if not legacy:
        context = m['stock_v2']
        context['purchased'][e['id']] = bought + qty
        if now < visit['opens_at'] + RESTOCK and (e['kind'] in ('curio', 'scroll') or bought + qty >= e['limit'] + construction.merchant_extra(farm, slot, now)):
            if slot not in context['first_full']:
                context['first_full'].append(slot)
    if e['kind'] in ('exotic_seed', 'dye', 'graft', 'voucher'):
        inventory(farm, {e['item']: e['qty'] * qty})
    elif e['kind'] == 'curio':
        m['curios'].append(e['id'])
    else:
        m['scrolls'].append(e['recipe'])
    what = {'curio': 'Диковинка в коллекции: можно поставить на ферму бесплатно', 'scroll': 'Рецепт открыт навсегда'}.get(e['kind'], 'Товар на складе')
    return f'Сорока-коробейница: «{e["name"]}» ×{qty} за {cost} монет. {what}.'


def sell(farm, data, now):
    visit = _open_visit(farm, data['visit_id'], now)
    item, qty = data['item'], data['qty']
    need(isinstance(item, str) and item in ITEMS, 'unknown_item', 'Этот предмет не найден.', 422)
    need(type(qty) is int and 1 <= qty <= 999, 'invalid_number', 'Недопустимое количество.', 422)
    need(item == wants_for(farm, visit), 'not_wanted', 'Это Сороке сегодня не приглянулось.')
    m = state(farm)
    base = ITEMS[item]['price'] * qty
    sold = m['sold_value'] if m['visit_id'] == visit['visit_id'] else 0
    need(sold + base <= cap(farm), 'merchant_cap', 'Больше Сорока сегодня не возьмёт: кошелёк у неё не бездонный.')
    inventory(farm, {item: qty}, -1)
    _enter(farm, visit)
    gain = base * (100 + MERCHANT['buyback']['bonus_pct']) // 100
    farm['coins'] += gain
    m['sold_value'] += base
    return f'Сорока-коробейница берёт «{ITEMS[item]["name"]}» ×{qty}: +{gain} монет.'


def apply(farm, kind, data, now):
    now = tick(now)
    return buy(farm, data, now) if kind == 'merchant_buy' else sell(farm, data, now)


# ----------------------------------------------------------------------------------------------------------------------
# Read models
# ----------------------------------------------------------------------------------------------------------------------
def public(now):
    """Shared schedule and buy-back only; an actual assortment/teaser belongs to an owner's projection."""
    now = tick(now)
    visit, nxt = visit_at(now), next_visit(now)
    out = dict(active=visit is not None, visit_id=visit and visit['visit_id'], kind=visit and visit['kind'],
               opens_at=visit and visit['opens_at'], closes_at=visit and visit['closes_at'],
               next_at=nxt and nxt['opens_at'], next_kind=nxt and nxt['kind'],
               teaser='Сорока готовит новый привоз.' if nxt and nxt['opens_at'] - now <= DAY else None,
               slots=[], wants=None, fair=None)
    if visit:
        out['wants'] = dict(item=wants(visit), bonus_pct=MERCHANT['buyback']['bonus_pct'])
        if visit['fair']:
            fair = festivals.content(visit['fair']['id'])
            out['fair'] = dict(visit['fair'], goods=[g['id'] for g in fair['goods'] if g['seller'] == 'magpie' and g['source'] == 'fair'])
    return out


def owner_view(farm, now):
    """Owner-only projection: the shared part plus this farm's counters, per-slot status and the buy-back room."""
    now = tick(now)
    view = public(now)
    m = peek(farm)
    visit = visit_at(now)
    context = None
    view['next_restock_at'] = None
    view['base_visit_id'] = visit and visit['visit_id']
    if visit:
        legacy = _legacy(farm, visit)
        context = None if legacy else _stock_context(farm, visit)
        view['slots'] = [{k: s[k] for k in ('slot', 'id', 'kind', 'name', 'qty', 'price', 'limit', 'min_level', 'note', 'wired', 'rarity')}
                         | {'series': s.get('series_name')} for s in stock(visit, farm, now)]
        view['visit_id'] = _visit_token(farm, visit, now)
        if not legacy and now < visit['opens_at'] + RESTOCK:
            view['next_restock_at'] = visit['opens_at'] + RESTOCK
    lv = level(farm['xp'])
    live = visit is not None and m['visit_id'] == visit['visit_id']
    bought = m['bought'] if live else {}
    for s in view['slots']:
        s['extra'] = construction.merchant_extra(farm, s['slot'], now)   # rows «мастер» / fund «Покупатель Сороки»
        purchased = context['purchased'].get(s['id'], 0) if context is not None else bought.get(str(s['slot']), 0)
        left = s['limit'] + s['extra'] - purchased
        s['pay'] = construction.merchant_price(farm, s['price'])
        owned = (s['kind'] == 'curio' and s['id'] in m['curios']) or (s['kind'] == 'scroll' and s['id'][7:] in m['scrolls'])
        s['left'] = max(0, left)
        from . import orchard
        s['status'] = ('soon' if not s['wired'] else 'owned' if owned else 'locked' if lv < s['min_level'] else 'sold' if left <= 0
                       else 'notree' if s['kind'] == 'graft' and not orchard.can_buy_graft(farm, s['id'])
                       else 'poor' if farm['coins'] < s['pay'] else 'ok')
    sold = m['sold_value'] if live else 0
    view.update(bought=dict(bought), sold_value=sold, cap=cap(farm), curios=list(m['curios']), scrolls=list(m['scrolls']))
    if view['wants']:
        item = wants_for(farm, visit_at(now))
        view['wants'].update(item=item, pricey=ITEMS[item]['price'] > cap(farm), unit=ITEMS[item]['price'] * (100 + view['wants']['bonus_pct']) // 100, have=farm['inventory'].get(item, 0),
                             room=max(0, (cap(farm) - sold) // ITEMS[item]['price']))
    return view
