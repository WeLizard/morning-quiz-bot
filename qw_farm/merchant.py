"""Странствующая торговка «Сорока-коробейница» (docs/tasks/FARM_VILLAGE_MINIGAMES.md section 2).

Server-authoritative and pure. Time is the fixed UTC+3 Moscow day (``economy.moscow_day``), never the device clock.

Schedule (shared by all players, no storage): in every Moscow week (Mon-Sun) two visits of 24 h on two different weekdays that are
never adjacent, chosen from ``sha256(season, week)``; plus every day the festival engine says she is at the fair (``festivals.current``
-> ``magpie``). A fair day that is also a regular day is ONE visit (a day cannot hold two). ``visit_id`` is ``v<moscow day>``.

Stock (``stock``): six slots computed from the visit day alone (no database): the cheap slot, a seed pack or dye, a recipe scroll, two curios
of the season's series, one more seed/dye/scroll. Nothing repeats from the previous visit while the pool allows it. Prices follow
``ceil(k * income_ref(item level) / 100)`` (dyes: the workshop value law, a fixed price). Orchard hooks (grafts, vouchers) are defined in the
catalog but ``ORCHARD_WIRED`` is False, so they are never offered.

State: ``farm['merchant'] = {visit_id, bought{slot: n}, sold_value, curios[], scrolls[], seed_bank{}}`` (``setdefault`` only, the schema
version is not raised). A new ``visit_id`` zeroes ``bought`` and ``sold_value`` lazily. ``seed_bank`` is reserved for Суслик Игорь (always {}).
Scrolls unlock their recipe on purchase (no scroll item); curios are bound decor placed for free from ``curios``; seed packs and dyes go to the
warehouse as bound items (``ITEMS[..]['bound']``: never gifted, listed, sold, funded or crated).

Commands (owner only; idempotent through ``command_id`` in the service, one ledger record each; undo does not apply):
  ``merchant_buy {visit_id, slot, qty}`` and ``merchant_sell {visit_id, item, qty}`` (the buy-back: +30 percent on the warehouse price, at most
  2 percent of ``income_ref`` of the player's level per visit, counted at the warehouse price).
The client sends only the visit id, the slot number and the quantity; item, price and limit are the server's.
"""
from hashlib import sha256
import math

from .catalog import ITEMS, CURIOS, CURIO_SERIES, SCROLL_RECIPES, RECIPES, EXOTIC_CROPS, DYES, MERCHANT, ORCHARD_ROWS, ORCHARD_WIRED, TREE_VOUCHER_DISCOUNT_PCT, income_ref, level, tick
from .domain import need, inventory, pay
from . import economy, festivals

DAY = 86400
TZ_OFFSET = economy.TZ_OFFSET
SLOTS = MERCHANT['slots']
SCHEMAS = {'merchant_buy': {'visit_id', 'slot', 'qty'}, 'merchant_sell': {'visit_id', 'item', 'qty'}}
ORCHARD_IDS = tuple(r[0] for r in ORCHARD_ROWS)
MAX_BOUGHT = 1000


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


def stock(visit):
    """Six slots of a visit: list of dicts (slot, id, kind, item, name, qty, price, limit, min_level, note, ...). Same for every player."""
    return [dict(e, slot=i) for i, e in enumerate(_chain(visit['day']))]


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
        m['visit_id'], m['bought'], m['sold_value'] = visit['visit_id'], {}, 0
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
    ok = (isinstance(m, dict) and set(m) == {'visit_id', 'bought', 'sold_value', 'curios', 'scrolls', 'seed_bank'}
          and (m['visit_id'] is None or isinstance(m['visit_id'], str) and m['visit_id'].startswith('v'))
          and isinstance(m['bought'], dict) and all(k in {str(i) for i in range(SLOTS)} and type(v) is int and 0 <= v <= MAX_BOUGHT for k, v in m['bought'].items())
          and type(m['sold_value']) is int and 0 <= m['sold_value'] <= 10 ** 9
          and isinstance(m['curios'], list) and len(set(m['curios'])) == len(m['curios']) and all(c in CURIOS for c in m['curios'])
          and isinstance(m['scrolls'], list) and len(set(m['scrolls'])) == len(m['scrolls']) and all(s in SCROLL_RECIPES for s in m['scrolls'])
          and m['seed_bank'] == {})
    need(ok, 'invalid_merchant', 'Некорректное состояние торговки.', 500)


# ----------------------------------------------------------------------------------------------------------------------
# Commands
# ----------------------------------------------------------------------------------------------------------------------
def _open_visit(farm, visit_id, now):
    visit = visit_at(now)
    need(isinstance(visit_id, str), 'invalid_command', 'Некорректные параметры действия.', 422)
    need(visit is not None, 'merchant_away', 'Сорока сейчас не в деревне.')
    need(visit['visit_id'] == visit_id, 'stale_visit', 'Это уже другой визит. Обнови ферму.')
    return visit


def buy(farm, data, now):
    visit = _open_visit(farm, data['visit_id'], now)
    slot, qty = data['slot'], data['qty']
    need(type(slot) is int and 0 <= slot < SLOTS, 'invalid_command', 'Такого места на прилавке нет.', 422)
    need(type(qty) is int and 1 <= qty <= 100, 'invalid_number', 'Недопустимое количество.', 422)
    slots = stock(visit)
    need(slot < len(slots), 'unknown_item', 'Этот предмет не найден.', 422)
    e = slots[slot]
    m = state(farm)
    bought = m['bought'].get(str(slot), 0) if m['visit_id'] == visit['visit_id'] else 0
    need(level(farm['xp']) >= e['min_level'], 'locked', f'Нужен уровень {e["min_level"]}.')
    if e['kind'] == 'curio':
        need(e['id'] not in m['curios'], 'already_owned', 'Эта диковинка уже в твоей коллекции.')
    if e['kind'] == 'scroll':
        need(e['recipe'] not in m['scrolls'], 'already_owned', 'Этот рецепт ты уже знаешь.')
    need(bought + qty <= e['limit'], 'limit_reached', 'На этот визит больше не продам.')
    if e['kind'] == 'graft':
        from . import orchard
        need(orchard.can_buy_graft(farm, e['item']), 'no_tree', 'Прививка нужна для посаженного дерева: сначала посади его.')
    cost = e['price'] * qty
    pay(farm, cost)
    _enter(farm, visit)
    m['bought'][str(slot)] = bought + qty
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
    """Shared part, identical for every player: presence, times, the herald's teaser, slots with prices and limits, the wanted item."""
    now = tick(now)
    visit, nxt = visit_at(now), next_visit(now)
    out = dict(active=visit is not None, visit_id=visit and visit['visit_id'], kind=visit and visit['kind'],
               opens_at=visit and visit['opens_at'], closes_at=visit and visit['closes_at'],
               next_at=nxt and nxt['opens_at'], next_kind=nxt and nxt['kind'],
               teaser=nxt and nxt['opens_at'] - now <= DAY and teaser(nxt) or None, slots=[], wants=None, fair=None)
    if visit:
        out['slots'] = [{k: s[k] for k in ('slot', 'id', 'kind', 'name', 'qty', 'price', 'limit', 'min_level', 'note', 'wired')} | {'series': s.get('series_name')}
                        for s in stock(visit)]
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
    lv = level(farm['xp'])
    live = view['visit_id'] is not None and m['visit_id'] == view['visit_id']
    bought = m['bought'] if live else {}
    for s in view['slots']:
        left = s['limit'] - bought.get(str(s['slot']), 0)
        owned = (s['kind'] == 'curio' and s['id'] in m['curios']) or (s['kind'] == 'scroll' and s['id'][7:] in m['scrolls'])
        s['left'] = max(0, left)
        from . import orchard
        s['status'] = ('soon' if not s['wired'] else 'owned' if owned else 'locked' if lv < s['min_level'] else 'sold' if left <= 0
                       else 'notree' if s['kind'] == 'graft' and not orchard.can_buy_graft(farm, s['id'])
                       else 'poor' if farm['coins'] < s['price'] else 'ok')
    sold = m['sold_value'] if live else 0
    view.update(bought=dict(bought), sold_value=sold, cap=cap(farm), curios=list(m['curios']), scrolls=list(m['scrolls']))
    if view['wants']:
        item = wants_for(farm, visit_at(now))
        view['wants'].update(item=item, pricey=ITEMS[item]['price'] > cap(farm), unit=ITEMS[item]['price'] * (100 + view['wants']['bonus_pct']) // 100, have=farm['inventory'].get(item, 0),
                             room=max(0, (cap(farm) - sold) // ITEMS[item]['price']))
    return view
