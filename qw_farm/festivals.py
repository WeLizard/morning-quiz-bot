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

from .catalog import ITEMS, ORCHARD_WIRED, income_ref, level, tick
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
KINDS = ('decor', 'decor_big', 'wall', 'roof', 'path', 'village', 'mascot', 'tree_decor', 'voucher', 'graft', 'scroll', 'curio', 'keepsake',
         'joke')


def _g(gid, name, kind, place, lvl, k, seller='agata', source='fair', limit=1, note='', wired=False, ref=''):
    """``ref`` names the catalog item an orchard lot stands for (``voucher_orchard``); an orchard lot is ``wired`` only with the orchard."""
    return dict(id=gid, name=name, kind=kind, place=place, level=lvl, k=k, seller=seller, source=source, limit=limit, note=note,
                wired=wired, bound=True, orchard=kind in ('voucher', 'graft'), ref=ref)


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
            _g('fest_posid_voucher', 'Талон сада со скидкой 25%', 'voucher', 'orchard', 10, 2, note='ждёт сад'),
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
            # the common pie-tower reward: granted lazily to every participant after the village threshold
            _g('fest_posid_tower', 'Пирог-башня', 'decor', 'farm1', 1, 60, source='tower', limit=1,
               note='награда общей башни «Пирог до небес»'),
        ],
        tower=dict(goal=40, item='fest_posid_tower')),
}
# «Новый год» (design 9.2 item 1, 9.3, 9.10): 4 tasks, the full set of decor forms (1x1, 2x2, fence, roof, path, village square,
# mascot), one decorative tree (outside the orchard limit), a graft and a voucher (orchard lots, ``wired`` only with the orchard),
# a pattern scroll, a Magpie curio and the keepsake of the year. Textile goods only where the design says (mittens, scarf, plaid).
# Not here (other systems): «Двенадцать ударов» (Oleg), cards of the Hedgehog, Kaya's contest, the winter-pepper exotic seed.
CONTENT['new_year'] = dict(
    tasks=[
        _t('table', 'Новогодний стол', 'Агата', 6, [{'pie': 2, 'pancake': 3, 'cheese': 2}, {'pancake': 4, 'bread': 4, 'cheese': 3}], 'fest_ny_cap'),
        _t('warm', 'Варежки и шарфы всей деревне', 'Соня', 7, [{'mittens': 2, 'scarf': 1}, {'yarn': 5, 'wool': 6}], 'fest_ny_mitten_garland'),
        _t('plaid', 'Пледы на скамейки у ёлки', 'Соня', 8, [{'wool_plaid': 1}, {'wool_cloth': 2, 'pillow': 1}], 'fest_ny_plaid'),
        _t('ginger', 'Пряники на ёлку', 'Агата', 7, [{'gingerbread': 3}, {'honey': 4, 'flour': 3}], 'fest_ny_sign'),
    ],
    goods=[
        _g('fest_ny_fir', 'Ёлочка в кадке', 'tree_decor', 'farm1', 8, 120, note='декор, вне лимита сада'),
        _g('fest_ny_snowman', 'Снеговик', 'decor', 'farm1', 5, 80),
        _g('fest_ny_sleigh', 'Сани с подарками', 'decor', 'farm1', 10, 150),
        _g('fest_ny_icicles', 'Гирлянда-сосульки', 'wall', 'fence', 5, 40),
        _g('fest_ny_lights', 'Фонарики вдоль дорожки', 'path', 'path', 8, 90),
        _g('fest_ny_toy', 'Именная ёлочная игрушка', 'village', 'village', 5, 60, note='ячейка площади, на большой ёлке'),
        _g('fest_ny_bullfinch', 'Снегирь', 'mascot', 'mascot', 12, 200, note='ходит за игроком по деревне'),
        _g('fest_ny_graft', 'Прививка «Яблоня в инее»', 'graft', 'orchard', 16, 10, note='облик дерева; ждёт сад', wired=ORCHARD_WIRED),
        _g('fest_ny_voucher', 'Талон сада со скидкой 25%', 'voucher', 'orchard', 16, 2, note='ждёт сад', wired=ORCHARD_WIRED,
           ref='voucher_orchard'),
        _g('fest_ny_scarf_post', 'Шарф с оленями на столбик', 'wall', 'fence', 7, 50, seller='sonya'),
        _g('fest_ny_scroll', 'Свиток «Варежки и шарф с оленями»', 'scroll', 'none', 7, 25, seller='sonya',
           note='рецепт узора; откроется в портновской, когда его подключат'),
        _g('fest_ny_ball', 'Заморский шар-диковинка', 'curio', 'farm1', 10, 250, seller='magpie',
           note='диковинка Сороки; семена «Зимний перец» — TODO, когда появятся в каталоге заморских культур'),
        # earned by tasks, not sold
        _g('fest_ny_cap', 'Снежная шапка с флажком', 'roof', 'roof', 6, 60, source='task:table'),
        _g('fest_ny_mitten_garland', 'Гирлянда из варежек', 'wall', 'fence', 7, 60, source='task:warm'),
        _g('fest_ny_plaid', 'Плед на скамейку у ёлки', 'village', 'village', 8, 60, source='task:plaid'),
        _g('fest_ny_sign', 'Снеговик с табличкой фермы', 'village', 'village', 7, 60, source='task:ginger', note='общий ряд на площади'),
        # earned by the first win of each «Битва с Сантой» battle (application/farm_santa_battle.py), not sold
        _g('fest_ny_krampus_bell', 'Колокольчик Крампуса', 'decor', 'farm1', 5, 60, source='battle:1'),
        _g('fest_ny_santa_sack', 'Мешок Санты', 'decor', 'farm1', 5, 60, source='battle:2'),
        _g('fest_ny_santa_visit', 'Санта и Крампус в гостях', 'decor_big', 'farm2', 5, 60, source='battle:3',
           note='2×2: оба пьют чай у ёлки на ферме'),
        # the memorable item of the year: every task, never sold, never returns (one per year: «Ёлочная игрушка 2027» and so on)
        _g('fest_ny_year_toy', 'Ёлочная игрушка года', 'keepsake', 'farm1', 8, 0, source='keepsake'),
    ])

# «Масленица» (9.2 item 2): the show «Проводы Зимы», the straw effigy, the slide and the village tables are scene layers (art);
# here are the fair, the tasks the design names (Pukh, the pie tower in the guise of pancakes, Kaya's judging) and the decor.
# TODO (engine): «Сто блинов на спор» is a week-long accumulation in the design; the engine has single hand-ins, so it is one hand-in.
CONTENT['maslenitsa'] = dict(
    tasks=[
        _t('hundred', 'Сто блинов на спор', 'Пух', 4, [{'pancake': 24}, {'pancake': 12, 'jam': 6}], 'fest_mas_stack'),
        _t('tower', 'Пирог до небес: блинная башня', 'Агата', 6, [{'pie': 2, 'pancake': 10}, {'pancake': 14, 'cheese': 4}], 'fest_mas_flag'),
        _t('judge', 'Лучший блин для Каи', 'Кая', 4, [{'pancake': 6, 'jam': 2}, {'pancake': 6, 'cheese': 3}], 'fest_mas_tables'),
    ],
    goods=[
        _g('fest_mas_samovar', 'Самовар с баранками', 'decor', 'farm1', 8, 150),
        _g('fest_mas_effigy', 'Чучело у грядок', 'decor', 'farm1', 5, 80),
        _g('fest_mas_ribbons', 'Ленты на забор', 'wall', 'fence', 5, 40),
        _g('fest_mas_voucher', 'Талон сада со скидкой 25%', 'voucher', 'orchard', 16, 2, note='ждёт сад', wired=ORCHARD_WIRED,
           ref='voucher_orchard'),
        _g('fest_mas_scroll', 'Свиток «Блины с вареньем»', 'scroll', 'none', 5, 25,
           note='рецепт для пекарни; откроется, когда его подключат'),
        _g('fest_mas_tea', 'Медовый чай заморский', 'curio', 'farm1', 10, 250, seller='magpie', note='диковинка Сороки'),
        _g('fest_mas_stack', 'Блинная башенка', 'decor', 'farm1', 4, 60, source='task:hundred'),
        _g('fest_mas_flag', 'Масленичный флажок', 'roof', 'roof', 6, 60, source='task:tower'),
        _g('fest_mas_tables', 'Столы с блинами', 'village', 'village', 4, 60, source='task:judge', note='ячейка площади'),
        _g('fest_mas_blin', 'Блин года', 'keepsake', 'farm1', 6, 0, source='keepsake'),
    ])

# «Весенние цветы» (9.2 item 3). Крот gives a gear to everyone: his task takes the timber for the housing («Вечная шестерёнка»).
# The Hedgehog's «Букет для соседки» is a gift in the design (not here); the bouquet is handed in for the fair item instead.
CONTENT['spring_flowers'] = dict(
    tasks=[
        _t('bouquet', 'Букет для соседки', 'Ёж', 7, [{'bouquet': 1}, {'lavender': 6}], 'fest_flw_vase'),
        _t('ribbons', 'Ленточки на грядки', 'Соня', 6, [{'linen': 2}, {'linen_thread': 8}], 'fest_flw_ribbons'),
        _t('gear', 'Вечная шестерёнка', 'Крот', 4, [{'wood': 8}, {'wood': 4, 'hay': 6}], 'fest_flw_gear'),
    ],
    goods=[
        _g('fest_flw_cart', 'Цветочная тележка-клумба', 'decor_big', 'farm2', 20, 600, note='2×2, верхние уровни'),
        _g('fest_flw_tulips', 'Тюльпаны вдоль дорожки', 'path', 'path', 8, 90),
        _g('fest_flw_pots', 'Цветочные горшки', 'decor', 'farm1', 5, 60),
        _g('fest_flw_arch', 'Цветочная арка', 'village', 'village', 5, 60, note='ячейка площади'),
        _g('fest_flw_graft', 'Прививка «Яблоня в цвету»', 'graft', 'orchard', 16, 10, note='облик дерева; ждёт сад', wired=ORCHARD_WIRED),
        _g('fest_flw_gift', 'Букет в праздничной упаковке', 'decor', 'farm1', 7, 80, seller='sonya'),
        _g('fest_flw_bulb', 'Заморская луковица «Огненный тюльпан»', 'curio', 'farm1', 10, 250, seller='magpie',
           note='диковинка Сороки; сама заморская культура — TODO, когда появится в каталоге'),
        _g('fest_flw_vase', 'Ваза на рынке', 'village', 'village', 7, 60, source='task:bouquet', note='ячейка площади'),
        _g('fest_flw_ribbons', 'Ленточки на грядки', 'wall', 'fence', 6, 60, source='task:ribbons'),
        _g('fest_flw_gear', 'Вечная шестерёнка', 'decor', 'farm1', 4, 60, source='task:gear'),
        _g('fest_flw_tulip', 'Первый тюльпан', 'keepsake', 'farm1', 7, 0, source='keepsake'),
    ])

# ---- The rest of the year (design 9.2 items 4-11, 13-17), filled 2026-11-19 in calendar order. -------------------------------
# Every festival: 3-4 tasks from ordinary goods (a cheaper fallback option each), small decor of every form it names, a Magpie curio
# and the keepsake of the year. ``seller='host'`` is the stall of the festival's host (Даша, Крот, Игорь, Кая, Лягух Шарик, Пух,
# Филиныч, Зверушка). Mechanics the design gives to other systems stay there: the hidden things of Даша, the rocket launch, the
# fishing tournament, the quiz marathon, the fern riddle of Зверушка and the Jack's gifts are not hand-ins.
# The grafts the design names (Звёздная груша, Вишня в лентах, Вишня-двойняшка, Наливная яблоня, Ночная груша) come with their
# warehouse icons and tree looks in the art turn of each festival; the yearly voucher budget (9.7: 3-4 saplings a year) holds
# one more voucher only, at the saplings festival «Весенний сев».

# «День смеха» (9.2 item 4): one day; Даша's «Честная лавка» sells jokes for a symbolic price (kind 'joke', k 1-3).
CONTENT['april_fools'] = dict(
    tasks=[
        _t('hidden', 'Найди, что я спрятала', 'Даша', 2, [{'bun': 4}, {'bread': 5}], 'fest_fool_cap'),
        _t('signs', 'Перепутанные таблички', 'Крот', 2, [{'wood': 8}, {'wood': 4, 'hay': 4}], 'fest_fool_signs'),
        _t('joke', 'Оладьи с сюрпризом для Филиныча', 'Пух', 4, [{'pancake': 3}, {'jam': 2, 'bread': 3}], 'fest_fool_geese'),
    ],
    goods=[
        _g('fest_fool_jar', 'Пустая банка из-под тишины', 'joke', 'farm1', 3, 1, seller='host', note='шутка Даши, ни на что не влияет'),
        _g('fest_fool_sock', 'Носок-невидимка', 'joke', 'fence', 3, 2, seller='host', note='шутка Даши'),
        _g('fest_fool_horseshoe', 'Подкова наоборот', 'joke', 'fence', 3, 3, seller='host', note='шутка Даши: счастье вытекает'),
        _g('fest_fool_cake', 'Торт-обманка', 'decor', 'farm1', 5, 60),
        _g('fest_fool_mirror', 'Кривое зеркало на площади', 'village', 'village', 5, 50, note='ячейка площади'),
        _g('fest_fool_stripes', 'Полосатые носки на забор', 'wall', 'fence', 5, 40, seller='sonya'),
        _g('fest_fool_whistle', 'Заморская свистулька-пищалка', 'curio', 'farm1', 10, 150, seller='magpie', note='диковинка Сороки'),
        _g('fest_fool_cap', 'Колпак на флюгере', 'roof', 'roof', 2, 60, source='task:hidden'),
        _g('fest_fool_signs', 'Табличка «Почта» на мельнице', 'village', 'village', 2, 60, source='task:signs', note='ячейка площади'),
        _g('fest_fool_geese', 'Гуси в колпаках', 'decor', 'farm1', 4, 60, source='task:joke'),
        _g('fest_fool_scarecrow', 'Пугало-шутник', 'keepsake', 'farm1', 4, 0, source='keepsake'),
    ])

# «День космонавтики» (9.2 item 13): the rocket of Крот flies when the village counter is full (a show, another system).
CONTENT['cosmonautics'] = dict(
    tasks=[
        _t('barrel', 'Бочка и заклёпки для ракеты', 'Крот', 2, [{'wood': 10}, {'wood': 5, 'hay': 5}], 'fest_cosm_flags'),
        _t('fuel', 'Энергетос для космонавта', 'Пух', 5, [{'berry_milk': 2}, {'jam': 3, 'milk': 4}], 'fest_cosm_birdhouse'),
        _t('ration', 'Бортовой паёк', 'Агата', 5, [{'rye_rusks': 6}, {'bagels': 6, 'oat_cookie': 2}], 'fest_cosm_stars'),
    ],
    goods=[
        _g('fest_cosm_rocket', 'Ракета из бочки', 'decor_big', 'farm2', 20, 600, seller='host', note='2×2, верхние уровни'),
        _g('fest_cosm_parts', 'Запчасти для ракеты', 'decor', 'farm1', 5, 60, seller='host'),
        _g('fest_cosm_path', 'Звёздочки вдоль дорожки', 'path', 'path', 8, 90),
        _g('fest_cosm_scroll', 'Свиток «Космический энергетос»', 'scroll', 'none', 11, 25,
           note='рецепт Пуха для бодрильни; откроется, когда его подключат'),
        _g('fest_cosm_meteor', 'Заморский метеорит', 'curio', 'farm1', 10, 250, seller='magpie', note='диковинка Сороки'),
        _g('fest_cosm_graft', 'Прививка «Звёздная груша»', 'graft', 'orchard', 16, 10, note='облик груши; ждёт сад', wired=ORCHARD_WIRED),
        _g('fest_cosm_flags', 'Звёздные флажки на забор', 'wall', 'fence', 2, 60, source='task:barrel'),
        _g('fest_cosm_birdhouse', 'Ракета-скворечник у сарая', 'decor', 'farm1', 5, 60, source='task:fuel'),
        _g('fest_cosm_stars', 'Карта созвездий над площадью', 'village', 'village', 5, 60, source='task:ration', note='ячейка площади'),
        _g('fest_cosm_badge', 'Значок космонавта года', 'keepsake', 'fence', 5, 0, source='keepsake'),
    ])

# «Весенний сев и субботник» (9.2 item 5): the saplings festival; Игорь's seed stall, the bridge of Крот.
CONTENT['spring_sowing'] = dict(
    tasks=[
        _t('seeds', 'Семенной обмен', 'Игорь', 2, [{'wheat': 20, 'carrot': 10}, {'oat': 20, 'beet': 8}], 'fest_sow_rakes'),
        _t('bridge', 'Древесина на мосток', 'Крот', 2, [{'wood': 12}, {'wood': 6, 'hay': 6}], 'fest_sow_bridge'),
        _t('ties', 'Подвязки для саженцев', 'Соня', 6, [{'linen_thread': 6}, {'linen': 2}], 'fest_sow_ties'),
    ],
    goods=[
        _g('fest_sow_birch', 'Берёзка', 'tree_decor', 'farm1', 8, 120, note='декор, вне лимита сада'),
        _g('fest_sow_birdhouse', 'Скворечник на столбике', 'decor', 'farm1', 5, 60, seller='host'),
        _g('fest_sow_sprouts', 'Первые всходы вдоль дорожки', 'path', 'path', 8, 90, seller='host'),
        _g('fest_sow_voucher', 'Талон сада со скидкой 25%', 'voucher', 'orchard', 16, 2, seller='host', note='ждёт сад', wired=ORCHARD_WIRED,
           ref='voucher_orchard'),
        _g('fest_sow_seeds', 'Заморская «Весенняя смесь» семян', 'curio', 'farm1', 10, 250, seller='magpie', note='диковинка Сороки'),
        _g('fest_sow_rakes', 'Грабли и тачка у сарая', 'decor', 'farm1', 2, 60, source='task:seeds'),
        _g('fest_sow_bridge', 'Починенный мосток с перилами', 'village', 'village', 2, 60, source='task:bridge', note='ячейка площади'),
        _g('fest_sow_ties', 'Льняные подвязки на заборе', 'wall', 'fence', 6, 60, source='task:ties'),
        _g('fest_sow_sprout', 'Первый росток года', 'keepsake', 'farm1', 2, 0, source='keepsake'),
    ])

# «День молока» (9.2 item 14): Кая's tasting, one day.
CONTENT['milk_day'] = dict(
    tasks=[
        _t('tasting', 'Молочная дегустация', 'Кая', 4, [{'milk': 8, 'cheese': 2}, {'goat_milk': 6, 'goat_cheese': 1}], 'fest_milk_garland'),
        _t('cheese', 'Лучший сыр', 'Кая', 6, [{'cheese': 4, 'goat_cheese': 2}, {'curd': 3, 'cheese': 2}], 'fest_milk_churn'),
        _t('kefir', 'Кефир к завтраку', 'Агата', 6, [{'kefir': 4}, {'milk': 6, 'whey': 4}], 'fest_milk_daisies'),
    ],
    goods=[
        _g('fest_milk_can', 'Бидон с ромашками', 'decor', 'farm1', 5, 80, seller='host'),
        _g('fest_milk_stall', 'Молочный прилавок на площади', 'village', 'village', 5, 60, seller='host', note='ячейка площади'),
        _g('fest_milk_path', 'Ромашки вдоль дорожки', 'path', 'path', 8, 90),
        _g('fest_milk_calf', 'Телёнок', 'mascot', 'mascot', 12, 200, seller='host', note='ходит за игроком по деревне'),
        _g('fest_milk_scroll', 'Свиток «Ягодное молоко с мятой»', 'scroll', 'none', 12, 25, seller='host',
           note='рецепт; откроется, когда его подключат'),
        _g('fest_milk_holes', 'Заморский сыр с дырками', 'curio', 'farm1', 10, 250, seller='magpie', note='диковинка Сороки'),
        _g('fest_milk_garland', 'Сырная гирлянда', 'village', 'village', 4, 60, source='task:tasting', note='ячейка площади'),
        _g('fest_milk_churn', 'Маслобойка у коровника', 'decor', 'farm1', 6, 60, source='task:cheese'),
        _g('fest_milk_daisies', 'Ромашки у забора', 'wall', 'fence', 6, 60, source='task:kefir'),
        _g('fest_milk_cow', 'Коровка года', 'keepsake', 'fence', 4, 0, source='keepsake'),
    ])

# «Ягодный праздник» (9.2 item 6).
CONTENT['berry_fest'] = dict(
    tasks=[
        _t('sweet', 'Самая сладкая ягода', 'Кая', 3, [{'strawberry': 12}, {'wildberry': 12}], 'fest_berry_garland'),
        _t('jam', 'Варенье на веранду', 'Агата', 3, [{'jam': 4}, {'berry_jam': 4}], 'fest_berry_jars'),
        _t('charge', 'Ягодный энергетос к лету', 'Пух', 11, [{'berry_charge': 2}, {'berry_milk': 3}], 'fest_berry_butterflies'),
    ],
    goods=[
        _g('fest_berry_kettle', 'Варенница на треноге', 'decor_big', 'farm2', 20, 600, note='2×2, верхние уровни'),
        _g('fest_berry_baskets', 'Корзинки у ягодных грядок', 'decor', 'farm1', 5, 60),
        _g('fest_berry_path', 'Ягодные кустики вдоль дорожки', 'path', 'path', 8, 90),
        _g('fest_berry_stall', 'Лавка варенья у рынка', 'village', 'village', 5, 60, seller='host', note='ячейка площади'),
        _g('fest_berry_blue', 'Заморская «Голубая клубника»', 'curio', 'farm1', 10, 250, seller='magpie', note='диковинка Сороки'),
        _g('fest_berry_garland', 'Ягодная гирлянда', 'village', 'village', 3, 60, source='task:sweet', note='ячейка площади'),
        _g('fest_berry_jars', 'Банки варенья на веранде', 'decor', 'farm1', 3, 60, source='task:jam'),
        _g('fest_berry_butterflies', 'Бабочки над крышей', 'roof', 'roof', 11, 60, source='task:charge'),
        _g('fest_berry_berry', 'Ягодка года', 'keepsake', 'farm1', 3, 0, source='keepsake'),
    ])

# «Иван Купала» (9.2 item 7): a night festival. The fern flower is found through the riddle of Зверушка (her game).
CONTENT['kupala'] = dict(
    tasks=[
        _t('wreath', 'Сплести венок', 'Соня', 6, [{'lavender': 8, 'linen_thread': 2}, {'herbs': 10, 'linen_thread': 3}], 'fest_kup_gate'),
        _t('fern', 'Травы для Зверушки', 'Зверушка', 3, [{'herbs': 12, 'mushroom': 4}, {'chanterelle': 6, 'wildberry': 6}], 'fest_kup_fern'),
        _t('fire', 'Дрова для костра у пруда', 'Крот', 2, [{'wood': 12}, {'wood': 6, 'hay': 6}], 'fest_kup_fire'),
    ],
    goods=[
        _g('fest_kup_flies', 'Светлячки над прудом', 'decor', 'farm1', 8, 120, note='ярче ночью'),
        _g('fest_kup_path', 'Гирлянда светлячков вдоль дорожки', 'path', 'path', 8, 90),
        _g('fest_kup_lavender', 'Венок из лаванды и льна', 'wall', 'fence', 6, 50, seller='sonya'),
        _g('fest_kup_float', 'Венки на воде', 'village', 'village', 5, 60, seller='sonya', note='ячейка площади'),
        _g('fest_kup_moon', 'Лунный камушек', 'curio', 'farm1', 10, 250, seller='magpie', note='ночная диковинка Сороки'),
        _g('fest_kup_gate', 'Венок на ворота', 'wall', 'fence', 6, 60, source='task:wreath'),
        _g('fest_kup_fern', 'Цветок папоротника в горшке', 'decor', 'farm1', 3, 60, source='task:fern', note='светится ночью'),
        _g('fest_kup_fire', 'Костёр у пруда', 'village', 'village', 2, 60, source='task:fire', note='стилизованный, ячейка площади'),
        _g('fest_kup_firefly', 'Светлячок года', 'keepsake', 'farm1', 3, 0, source='keepsake'),
    ])

# «День рыбака» (9.2 item 15): the tournament of the fishing mini-game is another system (trip_games.py); here the fair.
CONTENT['fisher_day'] = dict(
    tasks=[
        _t('catch', 'Улов на турнир', 'Лягух Шарик', 5, [{'crucian': 6}, {'perch': 4}], 'fest_fish_rods'),
        _t('ukha', 'Уха для судей', 'Агата', 5, [{'perch': 3, 'potato': 4, 'carrot': 4}, {'crucian': 4, 'potato': 4, 'herbs': 3}],
           'fest_fish_flags'),
        _t('bait', 'Прикормка', 'Игорь', 2, [{'bread': 4, 'corn': 6}, {'oat': 12, 'bread': 2}], 'fest_fish_net'),
    ],
    goods=[
        _g('fest_fish_boat', 'Лодка-клумба', 'decor_big', 'farm2', 20, 600, note='2×2, верхние уровни'),
        _g('fest_fish_tackle', 'Снасти у сарая', 'decor', 'farm1', 5, 60, seller='host'),
        _g('fest_fish_boats', 'Лодки у берега', 'village', 'village', 5, 60, seller='host', note='ячейка площади'),
        _g('fest_fish_path', 'Мостки вдоль дорожки', 'path', 'path', 8, 90),
        _g('fest_fish_lure', 'Заморская блесна', 'curio', 'farm1', 10, 250, seller='magpie', note='диковинка Сороки'),
        _g('fest_fish_rods', 'Удочки у пруда', 'decor', 'farm1', 5, 60, source='task:catch'),
        _g('fest_fish_flags', 'Флажки на причале', 'village', 'village', 5, 60, source='task:ukha', note='ячейка площади'),
        _g('fest_fish_net', 'Сеть на заборе', 'wall', 'fence', 2, 60, source='task:bait'),
        _g('fest_fish_float', 'Поплавок года', 'keepsake', 'fence', 2, 0, source='keepsake'),
    ])

# «День огурца» (9.2 item 16).
CONTENT['cucumber_day'] = dict(
    tasks=[
        _t('pickle', 'Соленья на зиму', 'Игорь', 3, [{'pickles': 4}, {'cucumber': 20}], 'fest_cuc_jars'),
        _t('crunch', 'Самый хрустящий огурец', 'Кая', 2, [{'cucumber': 12}, {'cucumber': 6, 'herbs': 4}], 'fest_cuc_vines'),
        _t('ties', 'Подвязка для огуречных плетей', 'Соня', 6, [{'linen_thread': 5}, {'linen': 2}], 'fest_cuc_arch'),
    ],
    goods=[
        _g('fest_cuc_barrel', 'Бочка с огурцами', 'decor', 'farm1', 5, 80, seller='host'),
        _g('fest_cuc_barrels', 'Бочки у дома Игоря', 'village', 'village', 5, 60, seller='host', note='ячейка площади'),
        _g('fest_cuc_path', 'Огуречные грядки вдоль дорожки', 'path', 'path', 8, 90),
        _g('fest_cuc_scroll', 'Свиток «Огурцы с мёдом»', 'scroll', 'none', 7, 25, seller='host',
           note='рецепт; откроется, когда его подключат'),
        _g('fest_cuc_bumpy', 'Заморский «Пупырчатый огурец»', 'curio', 'farm1', 10, 250, seller='magpie',
           note='диковинка Сороки; сама заморская культура — TODO, когда появится в каталоге'),
        _g('fest_cuc_jars', 'Банки солений на веранде', 'decor', 'farm1', 3, 60, source='task:pickle'),
        _g('fest_cuc_vines', 'Огуречные плети на заборе', 'wall', 'fence', 2, 60, source='task:crunch'),
        _g('fest_cuc_arch', 'Огуречная арка на рынке', 'village', 'village', 6, 60, source='task:ties', note='ячейка площади'),
        _g('fest_cuc_pickle', 'Огурчик года', 'keepsake', 'farm1', 2, 0, source='keepsake'),
    ])

# «Спасы: мёд, яблоки, орехи» (9.2 item 8): three fair days, the Magpie on all of them. Fruit of the orchard is not demanded:
# a farm without a bearing tree must be able to finish the tasks too.
CONTENT['spas'] = dict(
    tasks=[
        _t('honey', 'Мёд к Медовому Спасу', 'Пух', 7, [{'honey': 6}, {'honey': 3, 'gingerbread': 1}], 'fest_spas_hives'),
        _t('apple', 'Пироги к Яблочному Спасу', 'Агата', 6, [{'pie': 1, 'jam': 2}, {'jam': 4, 'flour': 4}], 'fest_spas_wreath'),
        _t('nuts', 'Орехи к Ореховому Спасу', 'Игорь', 2, [{'hazelnut': 15}, {'hazelnut': 8, 'wildberry': 6}], 'fest_spas_nuts'),
    ],
    goods=[
        _g('fest_spas_barrel', 'Медовый бочонок', 'decor', 'farm1', 7, 80, seller='host'),
        _g('fest_spas_apples', 'Корзины яблок у сада', 'decor', 'farm1', 5, 60),
        _g('fest_spas_stall', 'Медовая лавка Пуха', 'village', 'village', 5, 60, seller='host', note='ячейка площади'),
        _g('fest_spas_bee', 'Пчёлка', 'mascot', 'mascot', 12, 200, seller='host', note='летает за игроком по деревне'),
        _g('fest_spas_nutcracker', 'Заморский щелкунчик', 'curio', 'farm1', 10, 250, seller='magpie', note='диковинка Сороки'),
        _g('fest_spas_hives', 'Ленты на ульях', 'roof', 'roof', 7, 60, source='task:honey'),
        _g('fest_spas_wreath', 'Яблочный венок на площади', 'village', 'village', 6, 60, source='task:apple', note='ячейка площади'),
        _g('fest_spas_nuts', 'Ореховая гирлянда на забор', 'wall', 'fence', 2, 60, source='task:nuts'),
        _g('fest_spas_apple', 'Яблочко года', 'keepsake', 'farm1', 2, 0, source='keepsake'),
    ])

# «День знаний» (9.2 item 17): the quiz marathon of Филиныч is the quiz system; here the book stall and the school tasks.
CONTENT['knowledge_day'] = dict(
    tasks=[
        _t('bouquet', 'Букет учителю', 'Соня', 7, [{'bouquet': 1}, {'lavender': 6, 'herbs': 4}], 'fest_know_porch'),
        _t('satchel', 'Портфель первоклашке', 'Соня', 6, [{'wool_cloth': 1}, {'linen': 2, 'wool': 3}], 'fest_know_satchel'),
        _t('board', 'Доска для формул урожая', 'Крот', 2, [{'wood': 10}, {'wood': 5, 'hay': 5}], 'fest_know_board'),
    ],
    goods=[
        _g('fest_know_globe', 'Глобус на подставке', 'decor', 'farm1', 8, 120, seller='host'),
        _g('fest_know_abc', 'Флажки-азбука на забор', 'wall', 'fence', 5, 40),
        _g('fest_know_path', 'Классики вдоль дорожки', 'path', 'path', 8, 90),
        _g('fest_know_scroll', 'Свиток «Тыквенная каша»', 'scroll', 'none', 6, 25, seller='host',
           note='рецепт из книжной лавки Филиныча; откроется, когда его подключат'),
        _g('fest_know_spyglass', 'Заморская подзорная труба', 'curio', 'farm1', 10, 250, seller='magpie', note='диковинка Сороки'),
        _g('fest_know_porch', 'Букет на крыльце', 'decor', 'farm1', 7, 60, source='task:bouquet'),
        _g('fest_know_satchel', 'Портфель у дома', 'decor', 'farm1', 6, 60, source='task:satchel'),
        _g('fest_know_board', 'Доска с формулами урожая', 'village', 'village', 2, 60, source='task:board', note='ячейка площади'),
        _g('fest_know_bell', 'Звонок года', 'keepsake', 'farm1', 2, 0, source='keepsake'),
    ])

# «Осенняя ярмарка урожая» (9.2 item 9): the biggest fair of the year, every stall and the big decor of the upper levels.
CONTENT['harvest_fair'] = dict(
    tasks=[
        _t('pumpkin', 'Самая большая тыква', 'Кая', 6, [{'pumpkin': 10}, {'pumpkin': 6, 'potato': 10}], 'fest_harv_pumpkins'),
        _t('tower', 'Пирог до небес: тыквенная башня', 'Агата', 6, [{'pie': 3}, {'pumpkin': 8, 'flour': 6}], 'fest_harv_flag'),
        _t('convoy', 'Обоз урожая', 'Игорь', 6, [{'wool_cloth': 1, 'potato': 10}, {'linen': 2, 'cabbage': 10}], 'fest_harv_cart'),
        _t('wreath', 'Колосья на венок', 'Соня', 5, [{'wheat': 20, 'yarn': 1}, {'rye': 15, 'yarn': 1}], 'fest_harv_gate'),
    ],
    goods=[
        _g('fest_harv_monument', 'Памятник урожаю на ферме', 'decor_big', 'farm2', 25, 1000, note='2×2, для самых больших ферм'),
        _g('fest_harv_sheaf', 'Сноп с лентой', 'decor', 'farm1', 5, 80),
        _g('fest_harv_rowan', 'Рябинка', 'tree_decor', 'farm1', 8, 120, note='декор, вне лимита сада'),
        _g('fest_harv_path', 'Тыквы вдоль дорожки', 'path', 'path', 8, 90),
        _g('fest_harv_sign', 'Вывеска «Урожай!»', 'village', 'village', 5, 60, note='ячейка площади'),
        _g('fest_harv_hedgehog', 'Ёжик с яблоком', 'mascot', 'mascot', 12, 250, seller='sonya', note='ходит за игроком по деревне'),
        _g('fest_harv_scroll', 'Свиток «Пирог с тыквой и мёдом»', 'scroll', 'none', 6, 25, note='рецепт; откроется, когда его подключат'),
        _g('fest_harv_gourd', 'Заморская тыква-горлянка', 'curio', 'farm1', 10, 300, seller='magpie', note='диковинка Сороки'),
        _g('fest_harv_pumpkins', 'Тыквы у амбара', 'decor', 'farm1', 6, 60, source='task:pumpkin'),
        _g('fest_harv_flag', 'Флажок «Урожай!» на крыше', 'roof', 'roof', 6, 60, source='task:tower'),
        _g('fest_harv_cart', 'Телега обоза на площади', 'village', 'village', 6, 60, source='task:convoy', note='ячейка площади'),
        _g('fest_harv_gate', 'Колосковый венок на ворота', 'wall', 'fence', 5, 60, source='task:wreath'),
        _g('fest_harv_pumpkin', 'Тыква года', 'keepsake', 'farm1', 5, 0, source='keepsake'),
    ])

# «Тыквенная ночь» (9.2 item 10): the Jack's gifts and the scares are their own systems (horseman.py, the night layer).
CONTENT['pumpkin_night'] = dict(
    tasks=[
        _t('pie', 'Найди пропавший пирог', 'Филиныч', 6, [{'pie': 1}, {'pumpkin': 6, 'flour': 4}], 'fest_pn_web'),
        _t('lanterns', 'Фонари для ночной смены', 'Зверушка', 6, [{'pumpkin': 8}, {'pumpkin': 4, 'oil': 2}], 'fest_pn_lanterns'),
        _t('treat', 'Угощение для ряженых', 'Агата', 3, [{'oat_cookie': 4}, {'jam': 2, 'bun': 2}], 'fest_pn_scarecrow'),
    ],
    goods=[
        _g('fest_pn_lantern', 'Тыква-фонарь', 'decor', 'farm1', 5, 80),
        _g('fest_pn_glow', 'Светящиеся тыквы у пруда', 'village', 'village', 5, 60, seller='host', note='ячейка площади'),
        _g('fest_pn_bat', 'Летучая мышка', 'mascot', 'mascot', 12, 200, seller='host', note='летает за игроком по деревне'),
        _g('fest_pn_thing', 'Неведомая вещь', 'curio', 'farm1', 10, 250, seller='magpie', note='из ночной лавки Сороки и Зверушки'),
        _g('fest_pn_web', 'Паутина на заборе', 'wall', 'fence', 6, 60, source='task:pie'),
        _g('fest_pn_lanterns', 'Тыквы-фонари вдоль дорожки', 'path', 'path', 6, 60, source='task:lanterns'),
        _g('fest_pn_scarecrow', 'Ряженое пугало', 'decor', 'farm1', 3, 60, source='task:treat'),
        _g('fest_pn_owl', 'Сова года', 'keepsake', 'fence', 3, 0, source='keepsake'),
    ])

# Every festival of the calendar has its content now; a new one starts as a stub (the fair shows «скоро») until its turn.
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
            assert g['source'] in ('fair', 'keepsake', 'tower') or g['source'].startswith(('task:', 'battle:'))
            assert g['source'] == 'keepsake' or g['k'] > 0
            assert not g['ref'] or (g['orchard'] and g['ref'] in ITEMS)
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
        tower = c.get('tower')
        if tower:
            assert type(tower['goal']) is int and tower['goal'] > 0
            assert good_of(fid, tower['item'])['source'] == 'tower'
        if c['tasks']:
            assert 3 <= len(c['tasks']) <= 5
    return len(CONTENT)


validate_content()


# ----------------------------------------------------------------------------------------------------------------------
# State
# ----------------------------------------------------------------------------------------------------------------------
def blank():
    return dict(tasks={}, bought={}, rewards={}, keepsake=False, tower=False)


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


def tower_good(fid):
    """The common pie-tower reward lot of a festival, or None when the festival has no tower."""
    tower = content(fid).get('tower')
    return good_of(fid, tower['item']) if tower else None


def grant_tower(farm, key):
    """Lazy common reward: a participant gets the tower lot once, after the shared goal is reached."""
    m = KEY_RE.match(key) if isinstance(key, str) else None
    if m is None:
        return None
    g = tower_good(m.group(1))
    if g is None:
        return None
    e = entry(farm, key)
    if not e.get('tower') or owned(e, g['id']) >= g['limit']:
        return None
    e['rewards'][g['id']] = 1
    return g['name']


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
        need(isinstance(e, dict) and set(e) in ({'tasks', 'bought', 'rewards', 'keepsake'},
                                                       {'tasks', 'bought', 'rewards', 'keepsake', 'tower'})
             and type(e['keepsake']) is bool and type(e.get('tower', False)) is bool
             and isinstance(e['tasks'], dict) and isinstance(e['bought'], dict) and isinstance(e['rewards'], dict),
             'invalid_festivals', 'Некорректное состояние праздников.', 500)
        need(all(k in tasks and type(v) is int and v >= 0 for k, v in e['tasks'].items()), 'invalid_festivals',
             'Некорректное состояние праздников.', 500)
        for part, source in (('bought', ('fair',)), ('rewards', None)):
            for k, q in e[part].items():
                g = goods.get(k)
                ok = g is not None and type(q) is int and 0 < q and (
                    g['source'] in source if source else g['source'].startswith(('task:', 'battle:')) or g['source'] == 'tower')
                need(ok, 'invalid_festivals', 'Некорректное состояние праздников.', 500)
        for k in {*e['bought'], *e['rewards']}:
            need(owned(e, k) <= goods[k]['limit'], 'invalid_festivals', 'Некорректное состояние праздников.', 500)
        need(not e['keepsake'] or any(g['source'] == 'keepsake' for g in goods.values()), 'invalid_festivals',
             'Некорректное состояние праздников.', 500)


# ----------------------------------------------------------------------------------------------------------------------
# Commands
# ----------------------------------------------------------------------------------------------------------------------
def task_mode(cur, now):
    """When the tasks of the acting festival are shown and taken (owner's decision 2026-11-19, «не успели к празднику»):
    'fair' on a fair day; 'preview' in the decoration days before the first fair day (the list is shown so the goods can be
    gathered in time, nothing is taken yet); 'late' in the decoration days after it (an unfinished task is taken at the SAME
    price and still counts for the keepsake). No discount anywhere: waiting never pays, it only stops costing the keepsake."""
    if cur is None or not content(cur['id'])['tasks']:
        return None
    if cur['phase'] == 'fair':
        return 'fair'
    first = _first_fair_day(cur['key'])
    if first is None:
        return None
    return 'preview' if economy.moscow_day(tick(now)) < first else 'late'


def _day_text(day):
    d = date.fromordinal(day + EPOCH)
    return f'{d.day} {MONTHS_GEN[d.month - 1]}'


MONTHS_GEN = ('января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря')


def _open_tasks(festival, now):
    need(isinstance(festival, str) and festival in FESTIVALS, 'unknown_festival', 'Такого праздника нет.', 422)
    cur = current(now)
    mode = task_mode(cur, now) if cur is not None and cur['id'] == festival else None
    if mode == 'preview':
        need(False, 'tasks_not_open', f'Задания примут с первого дня ярмарки — {_day_text(_first_fair_day(cur["key"]))}. '
                                      'Пока можно собрать товары.')
    need(mode in ('fair', 'late'), 'fair_closed', 'Ярмарка сейчас не работает.')
    return cur


def last_completed(fid, now):
    """The most recent occurrence of ``fid`` whose last fair day is over, or None."""
    day = economy.moscow_day(now)
    done = [o for y in range(date.fromordinal(day + EPOCH).year - 1, date.fromordinal(day + EPOCH).year + 2)
            for o in occurrences(y) if o['id'] == fid and day_number(LAUNCH) <= o['fair'][0][0] and o['fair'][-1][1] < day]
    return max(done, key=lambda o: o['fair'][-1][1], default=None)


def hand_in(farm, data, now):
    now = tick(now)
    cur = _open_tasks(data['festival'], now)
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
    if g.get('orchard') and g.get('wired'):   # the orchard exists: a voucher or a graft lot gives a usable warehouse item (qw_farm/orchard.py)
        from . import orchard
        orchard.deliver_festival_good(farm, g)
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


def prep_view(farm, cur, mode, lvl):
    """The task list outside the fair days: 'preview' (shown, locked until the first fair day) or 'late' (taken, same price)."""
    c = content(cur['id'])
    e = {**blank(), **(farm.get('festivals') or {}).get(cur['key'], {})}
    first = _first_fair_day(cur['key'])
    tasks = [dict(id=t['id'], title=t['title'], host=t['host'], level=t['level'], options=t['options'], done=t['id'] in e['tasks'],
                  locked=mode == 'preview' or lvl < t['level'], preview=mode == 'preview',
                  reward=dict(id=t['reward'], name=good_of(cur['id'], t['reward'])['name']))
             for t in c['tasks']]
    keep = next((g for g in c['goods'] if g['source'] == 'keepsake'), None)
    return dict(id=cur['id'], name=cur['name'], key=cur['key'], host=cur['host'], mode=mode, opens_at=_ts(first),
                ends_at=cur['ends_at'], tasks=tasks, keepsake=keep and dict(id=keep['id'], name=keep['name'], got=e['keepsake']))


def owner_view(farm, now, tower=None):
    """Owner-only projection: calendar, the open fair (tasks, stall), the past-festivals shop and the collection."""
    now = tick(now)
    lvl = level(farm['xp'])
    s = farm.get('festivals') or {}
    cur = current(now)
    view = dict(public_calendar(farm, now), past_markup_pct=PAST_MARKUP_PCT, fair=None, prep=None, past=[], collection=collection(farm))
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
                            keepsake=keep and dict(id=keep['id'], name=keep['name'], got=e['keepsake']),
                            tower=tower)
    acting = current(now)
    mode = task_mode(acting, now) if view['fair'] is None else None
    if mode in ('preview', 'late'):
        view['prep'] = prep_view(farm, acting, mode, lvl)
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
