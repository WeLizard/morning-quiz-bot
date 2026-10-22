"""Festivals engine: the yearly calendar, fair tasks and fair purchases (FARM_FESTIVALS_DESIGN.md section 9).

Everything is server-authoritative and pure. Time is the fixed UTC+3 Moscow day (``economy.moscow_day``), never the device clock.

Calendar. Every festival has a decoration window (the world is dressed) and one or more fair ranges (stalls and tasks work).
A fair always lies inside its decoration window. At most one festival acts on a day (``_resolved``): among the festivals whose
decoration covers the day, the one with a fair that day wins; then ``priority``; then the earlier start. Movable feasts
(Масленица, День рыбака) come from the ``MOVING`` table, checked against the Easter arithmetic in the tests; the table must
reach at least a year past today (``TABLE_END``). The personal «День рождения фермы» is not in the calendar: ``birthday``.

State. ``farm['festivals']['<id>-<year>'] = {tasks, bought, rewards, keepsake}`` (``setdefault`` only, ``schema_version`` is not
raised). ``<year>`` is the year in which the decoration window ENDS (New Year 20.12.2026 - 14.01.2027 is ``new_year-2027``).
The entries ARE the player's festival collection (bound items: never gifted, listed or sold), so they are never pruned.

Commands (owner only, idempotent by ``command_id`` in the service):
  ``festival_task {festival, task, option}`` hands in goods for a fair task. The reward is a festival item, never coins or XP.
  ``festival_buy {festival, item}`` buys a fair item for coins during the fair; outside it, the same command buys a item of
  a finished festival in the «Лавка прошлых праздников» (x1.5). The memorable item of a year («Носки года») is given for
  finishing every task of the fair and is never sold.

Decor, saplings and graftings here are COLLECTION/DECOR-ONLY placeholders: ``wired`` is False, ``place`` names the drawing slot
the designer will fill (farm cell, fence, roof, path, village square, mascot). The orchard does not exist yet: a voucher or a
graft is only recorded here and flagged ``orchard`` so it can be wired to ``farm['orchard']`` later.
"""
from datetime import date, timedelta
from functools import lru_cache
import re

from .catalog import ITEMS, income_ref, level, tick
from .domain import need, inventory, pay
from . import economy

DAY = 86400
TZ_OFFSET = economy.TZ_OFFSET
EPOCH = date(1970, 1, 1).toordinal()
SCHEMAS = {'festival_task': {'festival', 'task', 'option'}, 'festival_buy': {'festival', 'item'}}
PAST_MARKUP_PCT = 150          # «Лавка прошлых праздников»: price x1.5
TABLE_END = date(2030, 12, 31)  # last day the MOVING table covers
LAUNCH = date(2026, 10, 22)   # engine start: earlier occurrences of a festival never happened in the game (no past shop for them)
SOON_DAYS = 14                 # the client shows «скоро» for a festival that starts within this many days
KEY_RE = re.compile(r'^([a-z_]+)-(\d{4})$')

# Fund-fair boost (section 9.4): one table, wired later (needs the village row of the previous season).
BOOST = dict(extra_agata_lots=2, extra_magpie_slots=1, contributor_discount_pct=15, extra_task_reward=1, tower_threshold_cut_pct=25)


def day_number(d):
    return d.toordinal() - EPOCH


def moscow_date(at):
    return date.fromordinal(economy.moscow_day(at) + EPOCH)


def _md(m, d, year):
    return day_number(date(year, m, d))


# ----------------------------------------------------------------------------------------------------------------------
# Calendar data.  deco/fair are (month, day) pairs; ``fair`` is a list of ranges.  ``windows`` of a movable feast come from MOVING.
# ----------------------------------------------------------------------------------------------------------------------
def _f(fid, name, kind, deco, fair, host='Агата', priority=0, magpie='first', theme=''):
    return dict(id=fid, name=name, kind=kind, deco=deco, fair=fair, host=host, priority=priority, magpie=magpie, theme=theme)


FESTIVALS = {f['id']: f for f in [
    _f('new_year', 'Новый год', 'fixed', ((12, 20), (1, 14)), [((12, 30), (1, 8))], theme='Снег, ёлка на площади, гирлянды.'),
    _f('maslenitsa', 'Масленица', 'moving', None, None, priority=2, theme='Блины, чучело Зимы, шоу «Проводы Зимы».'),
    _f('spring_flowers', 'Весенние цветы', 'fixed', ((3, 1), (3, 9)), [((3, 6), (3, 8))], priority=3, theme='Тюльпаны, мимоза, первый букет.'),
    _f('april_fools', 'День смеха', 'fixed', ((3, 31), (4, 2)), [((4, 1), (4, 1))], host='Даша', theme='Таблички перепутаны, пугало в чужой шляпе.'),
    _f('cosmonautics', 'День космонавтики', 'fixed', ((4, 10), (4, 13)), [((4, 12), (4, 12))], host='Крот', theme='Ракета из бочки.'),
    _f('spring_sowing', 'Весенний сев и субботник', 'fixed', ((4, 25), (5, 5)), [((5, 1), (5, 5))], host='Игорь', theme='Скворечники, первые всходы.'),
    _f('milk_day', 'День молока', 'fixed', ((5, 31), (6, 2)), [((6, 1), (6, 1))], host='Кая', theme='Бидоны и ромашки.'),
    _f('berry_fest', 'Ягодный праздник', 'fixed', ((6, 10), (6, 20)), [((6, 14), (6, 16))], host='Кая', theme='Варенье на верандах.'),
    _f('kupala', 'Иван Купала', 'fixed', ((7, 5), (7, 8)), [((7, 6), (7, 7))], host='Соня', theme='Венки, костёр у пруда, светлячки (ночной).'),
    _f('fisher_day', 'День рыбака', 'moving', None, None, host='Лягух Шарик', theme='Рыболовный турнир на озере.'),
    _f('cucumber_day', 'День огурца', 'fixed', ((7, 26), (7, 28)), [((7, 27), (7, 27))], host='Игорь', theme='Огуречная ярмарка.'),
    _f('spas', 'Спасы: мёд, яблоки, орехи', 'fixed', ((8, 14), (8, 29)), [((8, 14), (8, 14)), ((8, 19), (8, 19)), ((8, 29), (8, 29))],
       host='Пух', magpie='all', theme='Три волны украшений: мёд, яблоки, орехи.'),
    _f('knowledge_day', 'День знаний', 'fixed', ((8, 31), (9, 2)), [((9, 1), (9, 1))], host='Филиныч', theme='Школа Филиныча, викторинный марафон.'),
    _f('harvest_fair', 'Осенняя ярмарка урожая', 'fixed', ((9, 20), (10, 5)), [((10, 1), (10, 5))], theme='Тыквы, снопы, самая большая ярмарка года.'),
    _f('pumpkin_night', 'Тыквенная ночь', 'fixed', ((10, 26), (11, 2)), [((10, 31), (10, 31))], host='Зверушка', theme='Тыквы-фонари, туман, страшилки по-деревенски.'),
    _f('posidelki', 'Посиделки', 'fixed', ((11, 20), (11, 30)), [((11, 26), (11, 30))], host='Соня', theme='Печки, пряжа, пледы на скамейках.'),
]}

# Movable feasts: year -> (deco start, deco end); the fair is the whole window (Масленица) or its last day (День рыбака).
MOVING = {
    'maslenitsa': {2026: ((2, 16), (2, 22)), 2027: ((3, 8), (3, 14)), 2028: ((2, 21), (2, 27)), 2029: ((2, 12), (2, 18)), 2030: ((3, 4), (3, 10))},
    'fisher_day': {2026: ((7, 10), (7, 12)), 2027: ((7, 9), (7, 11)), 2028: ((7, 7), (7, 9)), 2029: ((7, 6), (7, 8)), 2030: ((7, 12), (7, 14))},
}
MOVING_FAIR_LAST_DAY_ONLY = {'fisher_day'}


@lru_cache(maxsize=64)
def occurrences(year):
    """Every occurrence of every festival whose decoration window ENDS in ``year``: list of dicts of integer Moscow days."""
    result = []
    for fid, f in FESTIVALS.items():
        if f['kind'] == 'moving':
            row = MOVING[fid].get(year)
            if row is None:
                continue
            (m1, d1), (m2, d2) = row
            start, end = _md(m1, d1, year), _md(m2, d2, year)
            fair = [(end, end)] if fid in MOVING_FAIR_LAST_DAY_ONLY else [(start, end)]
        else:
            (m1, d1), (m2, d2) = f['deco']
            start = _md(m1, d1, year - 1 if m1 > m2 else year)
            end = _md(m2, d2, year)
            fair = [(_md(a, b, year - 1 if a > m2 and m1 > m2 else year), _md(c, e, year)) for (a, b), (c, e) in f['fair']]
        result.append(dict(id=fid, year=year, key=f'{fid}-{year}', deco=(start, end), fair=fair, priority=f['priority']))
    return result


def _around(day):
    year = date.fromordinal(day + EPOCH).year
    return [o for y in (year, year + 1) for o in occurrences(y)]


@lru_cache(maxsize=2048)
def _resolved(day):
    """The one occurrence acting on ``day`` (a Moscow day number) and its phase, or None. Cached: the calendar is constant all day."""
    best = None
    for o in _around(day):
        if o['deco'][0] <= day <= o['deco'][1]:
            fair = any(a <= day <= b for a, b in o['fair'])
            rank = (fair, o['priority'], -o['deco'][0])
            if best is None or rank > best[0]:
                best = (rank, o, 'fair' if fair else 'decor')
    return None if best is None else (best[1]['key'], best[1]['id'], best[1]['year'], best[2])


def _ts(day):
    """Unix time of 00:00 Moscow of the day number."""
    return day * DAY - TZ_OFFSET


def _span(day, key):
    """First and last day of the unbroken run of ``key`` around ``day`` (the visible, overlap-resolved window)."""
    lo = hi = day
    while (_resolved(lo - 1) or (None,))[0] == key and day - lo < 60:
        lo -= 1
    while (_resolved(hi + 1) or (None,))[0] == key and hi - day < 60:
        hi += 1
    return lo, hi


@lru_cache(maxsize=256)
def _first_fair_day(key):
    """The first fair day on which the occurrence ``key`` actually acts (a fair day lost to a higher-ranked festival does not count)."""
    m = KEY_RE.match(key)
    occ = next(o for o in occurrences(int(m.group(2))) if o['id'] == m.group(1))
    for a, b in occ['fair']:
        for day in range(a, b + 1):
            row = _resolved(day)
            if row is not None and row[0] == key and row[3] == 'fair':
                return day
    return None


def current(now):
    """What acts in the world right now (Moscow day): dict(id, name, key, year, phase 'decor'|'fair', host, ...) or None."""
    now = tick(now)
    day = economy.moscow_day(now)
    row = _resolved(day)
    if row is None:
        return None
    key, fid, year, phase = row
    f = FESTIVALS[fid]
    lo, hi = _span(day, key)
    occ = next(o for o in occurrences(year) if o['id'] == fid)
    fair_today = [r for r in occ['fair'] if r[0] <= day <= r[1]]
    first_fair_day = phase == 'fair' and day == _first_fair_day(key)
    magpie = phase == 'fair' and (f['magpie'] == 'all' or first_fair_day)
    return dict(id=fid, name=f['name'], key=key, year=year, phase=phase, host=f['host'], theme=f['theme'],
                starts_at=_ts(lo), ends_at=_ts(hi + 1), fair_ends_at=_ts(fair_today[0][1] + 1) if fair_today else None,
                magpie=magpie, content=bool(CONTENT.get(fid)))


def upcoming(now, horizon=400):
    """The next festival that begins after today: dict(id, name, starts_at, days, soon) or None."""
    now = tick(now)
    day = economy.moscow_day(now)
    here = (_resolved(day) or (None,))[0]
    for ahead in range(1, horizon + 1):
        row = _resolved(day + ahead)
        if row is not None and row[0] != here:
            f = FESTIVALS[row[1]]
            return dict(id=row[1], name=f['name'], key=row[0], starts_at=_ts(day + ahead), days=ahead, soon=ahead <= SOON_DAYS)
    return None


def birthday(farm, now):
    """Personal «День рождения фермы» (section 3, decision 3): only a farm with a real ``created_at``; years since creation, >= 1."""
    made = farm.get('created_at')
    if type(made) not in (int, float) or made <= 0:
        return None
    born, today = moscow_date(made), moscow_date(now)
    if today.year <= born.year:
        return None
    try:
        mark = born.replace(year=today.year)
    except ValueError:      # 29 February in a common year -> 28 February
        mark = date(today.year, 2, 28)
    return dict(years=today.year - born.year) if mark == today else None


# ----------------------------------------------------------------------------------------------------------------------
# Content.  price = ceil(k * income_ref(level) / 100)   (FARM_VILLAGE_MINIGAMES 2.4 value law; k = percent of a day's income).
# ----------------------------------------------------------------------------------------------------------------------
PLACES = ('farm1', 'farm2', 'fence', 'roof', 'path', 'village', 'mascot', 'tree', 'orchard', 'none')
KINDS = ('decor', 'decor_big', 'wall', 'roof', 'path', 'village', 'mascot', 'tree_decor', 'voucher', 'graft', 'scroll', 'curio', 'keepsake')


def _g(gid, name, kind, place, lvl, k, seller='agata', source='fair', limit=1, note=''):
    return dict(id=gid, name=name, kind=kind, place=place, level=lvl, k=k, seller=seller, source=source, limit=limit, note=note,
                wired=False, bound=True, orchard=kind in ('voucher', 'graft'))


def _t(tid, title, host, lvl, options, reward):
    return dict(id=tid, title=title, host=host, level=lvl, options=options, reward=reward)


CONTENT = {
    # Pilot, 20.11.2026: the first festival that exercises the whole engine.
    'posidelki': dict(
        tasks=[
            _t('yarn', 'Пряжа для общего клубка', 'Соня', 5, [{'yarn': 4}, {'wool': 6}], 'fest_posid_basket'),
            _t('warm', 'Тёплое всей деревне', 'Соня', 5, [{'mittens': 2}, {'yarn': 5}], 'fest_posid_bunting'),
            _t('pillows', 'Подушки на лавочки', 'Соня', 5, [{'pillow': 2}, {'wool': 8}], 'fest_posid_plaid'),
            _t('tea', 'Пироги к чаю', 'Агата', 3, [{'pie': 3}, {'bread': 4}], 'fest_posid_smoke'),
        ],
        goods=[
            _g('fest_posid_quilt', 'Лоскутное одеяло на веранде', 'decor_big', 'farm2', 20, 600, note='2×2, верхние уровни'),
            _g('fest_posid_lights', 'Тёплые огоньки вдоль дорожки', 'path', 'path', 8, 90),
            _g('fest_posid_wreath', 'Венок из пряжи на калитку', 'wall', 'fence', 5, 40),
            _g('fest_posid_window', 'Свет в окнах деревни', 'village', 'village', 5, 60, note='ячейка площади'),
            _g('fest_posid_rowan', 'Рябинка в вязаном чехле', 'tree_decor', 'farm1', 10, 150, note='декор, вне лимита сада'),
            _g('fest_posid_graft', 'Прививка «Яблоня в уютном чехле»', 'graft', 'orchard', 10, 10, note='облик дерева; ждёт сад'),
            _g('fest_posid_voucher', 'Талон сада со скидкой 25%', 'voucher', 'orchard', 10, 10, note='ждёт сад'),
            _g('fest_posid_snowman', 'Снеговик в шарфе', 'mascot', 'mascot', 12, 200, seller='sonya'),
            _g('fest_posid_lantern', 'Заморский фонарик-клубок', 'curio', 'farm1', 10, 250, seller='magpie',
               note='диковинка Сороки; красители dye_* — TODO, когда они появятся в каталоге'),
            # earned by tasks (source 'task:<id>'), not sold
            _g('fest_posid_basket', 'Корзинка с пряжей', 'decor', 'farm1', 5, 60, source='task:yarn'),
            _g('fest_posid_bunting', 'Гирлянда из носочков', 'wall', 'fence', 5, 60, source='task:warm'),
            _g('fest_posid_plaid', 'Плед на скамейку', 'village', 'village', 5, 60, source='task:pillows'),
            _g('fest_posid_smoke', 'Дымок над трубой', 'roof', 'roof', 3, 60, source='task:tea'),
            # the memorable item of the year: finishing every task, never sold, never returns
            _g('fest_posid_socks', 'Носки года', 'keepsake', 'fence', 5, 0, source='keepsake', limit=1),
        ]),
}
# Every other festival is defined in the calendar (windows, host, theme) and handled by the engine;
# its tasks/goods are a TODO stub until its content turn (design 9.8).
for _fid in FESTIVALS:
    CONTENT.setdefault(_fid, None)


def content(fid):
    return CONTENT.get(fid) or dict(tasks=[], goods=[])


def good_of(fid, item):
    return next((g for g in content(fid)['goods'] if g['id'] == item), None)


def price(g):
    return max(1, -(-g['k'] * income_ref(g['level']) // 100)) if g['k'] else 0


def past_price(g):
    return -(-price(g) * PAST_MARKUP_PCT // 100)


def validate_content():
    """Import-time/test-time contract of the data (raises AssertionError)."""
    for fid, f in FESTIVALS.items():
        assert f['kind'] in ('fixed', 'moving') and (f['kind'] == 'moving') == (fid in MOVING)
        assert (f['deco'] is None) == (f['kind'] == 'moving')
    for fid in FESTIVALS:
        c = content(fid)
        ids = [g['id'] for g in c['goods']]
        assert len(ids) == len(set(ids))
        for g in c['goods']:
            assert g['kind'] in KINDS and g['place'] in PLACES and g['limit'] >= 1 and g['seller'] in ('agata', 'sonya', 'magpie', 'host')
            assert g['source'] in ('fair', 'keepsake') or g['source'].startswith('task:')
            assert g['source'] == 'keepsake' or g['k'] > 0
        tids = [t['id'] for t in c['tasks']]
        assert len(tids) == len(set(tids)) and len(tids) <= 5
        for t in c['tasks']:
            assert t['options'] and all(o and all(k in ITEMS and type(q) is int and q > 0 for k, q in o.items()) for o in t['options'])
            g = good_of(fid, t['reward'])
            assert g is not None and g['source'] == f'task:{t["id"]}'
        for g in c['goods']:
            if g['source'].startswith('task:'):
                assert g['source'][5:] in tids
        assert sum(g['source'] == 'keepsake' for g in c['goods']) <= 1
        if c['tasks']:
            assert 3 <= len(c['tasks']) <= 5
    return len(CONTENT)


validate_content()


# ----------------------------------------------------------------------------------------------------------------------
# State
# ----------------------------------------------------------------------------------------------------------------------
def blank():
    return dict(tasks={}, bought={}, rewards={}, keepsake=False)


def state(farm):
    """Migration for old farms: an empty mapping, nothing else changes."""
    return farm.setdefault('festivals', {})


def entry(farm, key):
    e = state(farm).setdefault(key, blank())
    for k, v in blank().items():
        e.setdefault(k, v)
    return e


def peek(farm, key):
    """Read-only view of an entry (nothing is created)."""
    return {**blank(), **(farm.get('festivals') or {}).get(key, {})}


def owned(e, item):
    return e['bought'].get(item, 0) + e['rewards'].get(item, 0)


def validate(farm):
    s = farm.get('festivals')
    if s is None:
        return
    need(isinstance(s, dict) and len(s) <= 200, 'invalid_festivals', 'Некорректное состояние праздников.', 500)
    for key, e in s.items():
        m = KEY_RE.match(key) if isinstance(key, str) else None
        need(m is not None and m.group(1) in FESTIVALS and 2000 <= int(m.group(2)) <= 2100, 'invalid_festivals',
             'Некорректное состояние праздников.', 500)
        c = content(m.group(1))
        tasks = {t['id'] for t in c['tasks']}
        goods = {g['id']: g for g in c['goods']}
        need(isinstance(e, dict) and set(e) == {'tasks', 'bought', 'rewards', 'keepsake'} and type(e['keepsake']) is bool
             and isinstance(e['tasks'], dict) and isinstance(e['bought'], dict) and isinstance(e['rewards'], dict),
             'invalid_festivals', 'Некорректное состояние праздников.', 500)
        need(all(k in tasks and type(v) is int and v >= 0 for k, v in e['tasks'].items()), 'invalid_festivals',
             'Некорректное состояние праздников.', 500)
        for part, source in (('bought', ('fair',)), ('rewards', None)):
            for k, q in e[part].items():
                g = goods.get(k)
                ok = g is not None and type(q) is int and 0 < q and (g['source'] in source if source else g['source'].startswith('task:'))
                need(ok, 'invalid_festivals', 'Некорректное состояние праздников.', 500)
        for k in {*e['bought'], *e['rewards']}:
            need(owned(e, k) <= goods[k]['limit'], 'invalid_festivals', 'Некорректное состояние праздников.', 500)
        need(not e['keepsake'] or any(g['source'] == 'keepsake' for g in goods.values()), 'invalid_festivals',
             'Некорректное состояние праздников.', 500)


# ----------------------------------------------------------------------------------------------------------------------
# Commands
# ----------------------------------------------------------------------------------------------------------------------
def _open_fair(festival, now):
    cur = current(now)
    need(isinstance(festival, str) and festival in FESTIVALS, 'unknown_festival', 'Такого праздника нет.', 422)
    need(cur is not None and cur['id'] == festival and cur['phase'] == 'fair', 'fair_closed', 'Ярмарка сейчас не работает.')
    return cur


def last_completed(fid, now):
    """The most recent occurrence of ``fid`` whose last fair day is over, or None."""
    day = economy.moscow_day(now)
    done = [o for y in range(date.fromordinal(day + EPOCH).year - 1, date.fromordinal(day + EPOCH).year + 2)
            for o in occurrences(y) if o['id'] == fid and day_number(LAUNCH) <= o['fair'][0][0] and o['fair'][-1][1] < day]
    return max(done, key=lambda o: o['fair'][-1][1], default=None)


def hand_in(farm, data, now):
    now = tick(now)
    cur = _open_fair(data['festival'], now)
    fid = cur['id']
    task = next((t for t in content(fid)['tasks'] if t['id'] == data['task']), None)
    need(task is not None, 'unknown_task', 'Такого задания нет.', 422)
    opt = data['option']
    need(type(opt) is int and 0 <= opt < len(task['options']), 'invalid_option', 'Некорректный вариант задания.', 422)
    need(level(farm['xp']) >= task['level'], 'locked', f'Задание откроется с {task["level"]} уровня.')
    need(task['id'] not in peek(farm, cur['key'])['tasks'], 'already_claimed', 'Это задание уже выполнено.')
    inventory(farm, task['options'][opt], -1)
    e = entry(farm, cur['key'])
    e['tasks'][task['id']] = economy.moscow_day(now)
    e['rewards'][task['reward']] = e['rewards'].get(task['reward'], 0) + 1
    reward = good_of(fid, task['reward'])['name']
    text = f'«{task["title"]}» готово. В награду: {reward}.'
    keep = next((g for g in content(fid)['goods'] if g['source'] == 'keepsake'), None)
    if keep and all(t['id'] in e['tasks'] for t in content(fid)['tasks']) and not e['keepsake']:
        e['keepsake'] = True
        text += f' Все задания праздника выполнены: «{keep["name"]}» навсегда в коллекции.'
    return text


def buy(farm, data, now):
    now = tick(now)
    fid, item = data['festival'], data['item']
    need(isinstance(fid, str) and fid in FESTIVALS, 'unknown_festival', 'Такого праздника нет.', 422)
    g = good_of(fid, item) if isinstance(item, str) else None
    need(g is not None and g['source'] == 'fair', 'unknown_item', 'Этого нет в продаже.', 422)
    cur = current(now)
    fair = cur is not None and cur['id'] == fid and cur['phase'] == 'fair'
    if fair:
        need(g['seller'] != 'magpie' or cur['magpie'], 'seller_away', 'Сорока уже уехала. Её товары — в «Лавке прошлых праздников».')
        key, cost = cur['key'], price(g)
    else:
        last = last_completed(fid, now)
        need(last is not None, 'festival_not_past', 'Этот праздник ещё не проходил.')
        key, cost = last['key'], past_price(g)
    need(level(farm['xp']) >= g['level'], 'locked', f'Нужен уровень {g["level"]}.')
    need(owned(peek(farm, key), item) < g['limit'], 'limit_reached', 'Этот предмет у тебя уже есть за этот праздник.')
    pay(farm, cost)
    e = entry(farm, key)
    e['bought'][item] = e['bought'].get(item, 0) + 1
    where = 'на ярмарке' if fair else 'в «Лавке прошлых праздников»'
    return f'{g["name"]}: куплено {where} за {cost} монет.'


def apply(farm, kind, data, now):
    need(isinstance(data.get('festival'), str), 'invalid_command', 'Некорректные параметры действия.', 422)
    return hand_in(farm, data, now) if kind == 'festival_task' else buy(farm, data, now)


# ----------------------------------------------------------------------------------------------------------------------
# Read models
# ----------------------------------------------------------------------------------------------------------------------
def public_calendar(farm, now):
    """What any visitor may see of a farm's festival: the shared world calendar and the farm's own birthday. No economy."""
    now = tick(now)
    cur = current(now)
    return dict(current=cur and {k: cur[k] for k in ('id', 'name', 'key', 'phase', 'host', 'starts_at', 'ends_at')},
                upcoming=upcoming(now), birthday=birthday(farm, now))


def _good_view(g, e, lvl, cost, extra=None):
    left = g['limit'] - owned(e, g['id'])
    row = dict(id=g['id'], name=g['name'], kind=g['kind'], place=g['place'], seller=g['seller'], level=g['level'], price=cost,
               limit=g['limit'], owned=owned(e, g['id']), wired=g['wired'], orchard=g['orchard'], note=g['note'],
               status='owned' if left <= 0 else 'locked' if lvl < g['level'] else 'ok')
    row.update(extra or {})
    return row


def owner_view(farm, now):
    """Owner-only projection: calendar, the open fair (tasks, stall), the past-festivals shop and the collection."""
    now = tick(now)
    lvl = level(farm['xp'])
    s = farm.get('festivals') or {}
    cur = current(now)
    view = dict(public_calendar(farm, now), past_markup_pct=PAST_MARKUP_PCT, fair=None, past=[], collection=collection(farm))
    if cur is not None and cur['phase'] == 'fair':
        c = content(cur['id'])
        e = {**blank(), **s.get(cur['key'], {})}
        tasks = [dict(id=t['id'], title=t['title'], host=t['host'], level=t['level'], options=t['options'], done=t['id'] in e['tasks'],
                      locked=lvl < t['level'], reward=dict(id=t['reward'], name=good_of(cur['id'], t['reward'])['name']))
                 for t in c['tasks']]
        keep = next((g for g in c['goods'] if g['source'] == 'keepsake'), None)
        goods = [_good_view(g, e, lvl, price(g), dict(away=g['seller'] == 'magpie' and not cur['magpie']))
                 for g in c['goods'] if g['source'] == 'fair']
        view['fair'] = dict(id=cur['id'], name=cur['name'], key=cur['key'], host=cur['host'], magpie=cur['magpie'],
                            ends_at=cur['fair_ends_at'], tasks=tasks, goods=goods, todo=not c['tasks'] and not c['goods'],
                            keepsake=keep and dict(id=keep['id'], name=keep['name'], got=e['keepsake']))
    for fid in FESTIVALS:
        if cur is not None and cur['id'] == fid and cur['phase'] == 'fair':
            continue    # this fair is open: the stall sells at the fair price, so last year's lots (x1.5) are not listed next to it
        last = last_completed(fid, now)
        c = content(fid)
        if last is None or not c['goods']:
            continue
        e = {**blank(), **s.get(last['key'], {})}
        view['past'].append(dict(id=fid, name=FESTIVALS[fid]['name'], key=last['key'], year=last['year'],
                                 goods=[_good_view(g, e, lvl, past_price(g)) for g in c['goods'] if g['source'] == 'fair'],
                                 live=False))
    return view


def collection(farm):
    """Everything the farm owns from festivals: item -> dict(name, kind, place, wired, count, years)."""
    result = {}
    for key, e in sorted((farm.get('festivals') or {}).items()):
        m = KEY_RE.match(key)
        if not m:
            continue
        for part in ('bought', 'rewards'):
            for item, q in e.get(part, {}).items():
                g = good_of(m.group(1), item)
                if g:
                    row = result.setdefault(item, dict(name=g['name'], kind=g['kind'], place=g['place'], wired=g['wired'], count=0, years=[]))
                    row['count'] += q
                    row['years'].append(int(m.group(2)))
        if e.get('keepsake'):
            g = next((g for g in content(m.group(1))['goods'] if g['source'] == 'keepsake'), None)
            if g:
                row = result.setdefault(g['id'], dict(name=g['name'], kind=g['kind'], place=g['place'], wired=g['wired'], count=0, years=[]))
                row['count'] += 1
                row['years'].append(int(m.group(2)))
    return result
