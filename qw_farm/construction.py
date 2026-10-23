"""Village construction (shared stages) and the market rows (docs/tasks/FARM_VILLAGE_CONSTRUCTION.md).

Shared state lives in SQL (``farm_village_projects``, ``farm_village_contribs``, ``farm_village_stall_lots``), never in a farm.
One project at a time, in the fixed ``ORDER``. A stage is ``collecting`` (goods 60% at price x1.25, earned coins 40%) -> ``working``
(residents, 1/2/2 days) -> next stage or ``done``. Every transition is a conditional UPDATE (status, stage, version) and happens lazily
on a read (``sync``); only the call whose UPDATE touched a row writes the ledger record.

Lock order: farm advisory locks (taken by the service) first, then SQL row locks (project / lot) -- never the reverse. A reader never
locks someone else's farm: expired lots of other sellers are only filtered out; rent and closing run on the seller's own visit.

The farm keeps only a small mirror ``farm['village_bonus'] = {tiers, open}`` so that pure modules (merchant) can read perks without SQL.
"""
from __future__ import annotations

from copy import deepcopy
from uuid import UUID, uuid4
import math
import sqlalchemy as sa

from . import economy
from .catalog import ITEMS, FUND_LEVEL, FUND_MARKUP, VILLAGE_GOAL_FLOOR, LEVELS, income_ref, level
from .domain import FarmError, need, inventory, unbound, event, named

DAY = 86400
COMMANDS = {'build_contribute', 'build_speedup', 'stall_list', 'stall_buy', 'stall_cancel'}
ORDER = ('stalls', 'tavern', 'greenhouse', 'fairground')
NAMES = dict(stalls='Торговые ряды', tavern='Трактир', greenhouse='Оранжерея', fairground='Ярмарочное поле')
STAGE_NAMES = ('Котлован', 'Каркас', 'Отделка')
STAGE_SHARE = (10, 20, 20)                  # percent of the sum of income_ref of the active farms
STAGE_WORK = (DAY, 2 * DAY, 2 * DAY)
GOODS_PCT = 60                               # the rest (40%) is earned coins
ACTIVE_DAYS = 7
REF_FLOOR = VILLAGE_GOAL_FLOOR // 3          # the fund floor expressed as a sum of income_ref (goal = 3 x sum)
MIN_WORK = 3600
ENERGY = ('berry_charge', 'honey_charge', 'forest_charge')
ENERGY_SECONDS, ENERGY_CAP, FUND_SPEED = 7200, DAY, DAY
TIER_BP = (1000, 4000, 10000)                # 10% / 40% / 100% of the player's own income_ref, in basis points
TIER_NAMES = ('', 'Помощник', 'Мастер', 'Почётный строитель')
# Goods of each stage (coins are always part of the need). Substitutes for items that the catalog does not have yet:
# festive flags / ribbons -> dyed linen cloths, "seedlings" -> lavender, "glass" -> coins.
GOODS = {
    'stalls': (('wood',), ('wood', 'linen'), ('dyed_linen', 'madder_linen')),
    'tavern': (('wood',), ('wood',), ('bread', 'pie', 'pancake', 'linen')),
    'greenhouse': (('wood',), ('wood',), ('raspberry', 'lavender')),
    'fairground': (('wood',), ('wool_cloth',), ('madder_linen', 'indigo_linen')),
}
BONUS_TEXT = {
    'stalls': ('−10% у Сороки в рядах', '+1 к лимиту каждого слота Сороки и своя лавка на рядах', 'Именная табличка на лавке'),
    'tavern': ('«Ужин дня» (скоро)', '+1 заказ трактира в сутки (скоро)', 'Скамья с гербом фермы (скоро)'),
    'greenhouse': ('Заморские семена растут быстрее (скоро)', 'Оранжерейная грядка (скоро)', 'Голос за культуру месяца (скоро)'),
    'fairground': ('−10% на ярмарках (скоро)', 'Ранний час на ярмарке (скоро)', 'Флаг фермы над сценой (скоро)'),
}
# own stall (docs section 5.3)
STALL_LOTS, PRICE_MAX_PCT, COMMISSION_PCT, RENT_PCT, RENT_PERIOD = 3, 150, 5, 1, 7 * DAY
STALL_LEVEL, BUYS_PER_DAY, LOT_QTY_MAX, HELPER_DISCOUNT_PCT = 10, 3, 20, 10
MAX_COINS = 10 ** 12


def tables(metadata: sa.MetaData):
    if 'farm_village_projects' in metadata.tables:
        return {'projects': metadata.tables['farm_village_projects'], 'contribs': metadata.tables['farm_village_contribs'],
                'lots': metadata.tables['farm_village_stall_lots']}
    projects = sa.Table('farm_village_projects', metadata,
        sa.Column('id', sa.String(16), primary_key=True),
        sa.Column('status', sa.String(12), nullable=False), sa.Column('stage', sa.SmallInteger, nullable=False),
        sa.Column('need', sa.JSON, nullable=False), sa.Column('got', sa.JSON, nullable=False),
        sa.Column('work_until', sa.BigInteger), sa.Column('speedup', sa.Integer, nullable=False, server_default='0'),
        sa.Column('fund_speed', sa.Integer, nullable=False, server_default='0'),
        sa.Column('opened_at', sa.BigInteger), sa.Column('version', sa.Integer, nullable=False, server_default='0'),
        sa.CheckConstraint("status IN ('soon','collecting','working','done')", name='ck_village_project_status'),
        sa.CheckConstraint('stage BETWEEN 0 AND 2 AND speedup >= 0 AND fund_speed >= 0', name='ck_village_project_stage'))
    contribs = sa.Table('farm_village_contribs', metadata,
        sa.Column('project_id', sa.String(16), sa.ForeignKey('farm_village_projects.id', ondelete='RESTRICT'), primary_key=True),
        sa.Column('account_id', sa.Uuid, sa.ForeignKey('accounts.id', ondelete='RESTRICT'), primary_key=True),
        sa.Column('farm_id', sa.Uuid, sa.ForeignKey('farm_states.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('value', sa.BigInteger, nullable=False),
        sa.Column('share_bp', sa.BigInteger, nullable=False),     # sum of shares of income_ref in basis points (0.01%)
        sa.Column('tier', sa.SmallInteger, nullable=False), sa.Column('updated_at', sa.BigInteger, nullable=False),
        sa.CheckConstraint('value >= 0 AND share_bp >= 0 AND tier BETWEEN 0 AND 3', name='ck_village_contrib'))
    lots = sa.Table('farm_village_stall_lots', metadata,
        sa.Column('id', sa.Uuid, primary_key=True),
        sa.Column('seller_farm', sa.Uuid, sa.ForeignKey('farm_states.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('seller_account', sa.Uuid, sa.ForeignKey('accounts.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('item', sa.String(40), nullable=False), sa.Column('qty', sa.Integer, nullable=False),
        sa.Column('unit_price', sa.Integer, nullable=False), sa.Column('created_at', sa.BigInteger, nullable=False),
        sa.Column('rent_paid_until', sa.BigInteger, nullable=False), sa.Column('status', sa.String(8), nullable=False),
        sa.Column('sold_at', sa.BigInteger), sa.Column('buyer_farm', sa.Uuid, sa.ForeignKey('farm_states.id', ondelete='RESTRICT')),
        sa.Column('closed_at', sa.BigInteger),
        sa.CheckConstraint("status IN ('open','sold','closed')", name='ck_village_lot_status'),
        sa.CheckConstraint('qty BETWEEN 1 AND 20 AND unit_price > 0', name='ck_village_lot_amount'))
    sa.Index('ix_village_lots_open', lots.c.status, lots.c.rent_paid_until)
    sa.Index('ix_village_lots_seller', lots.c.seller_account, lots.c.status)
    sa.Index('ix_village_lots_buyer_day', lots.c.buyer_farm, lots.c.seller_farm, lots.c.sold_at)
    return {'projects': projects, 'contribs': contribs, 'lots': lots}


def available(unit):
    t = getattr(unit, 't', None)
    return isinstance(t, dict) and t.get('projects') is not None


# ------------------------------------------------------------------------------------------------------------ pure rules
def tier_of(share_bp):
    return sum(share_bp >= b for b in TIER_BP)


def unit_credit(item):
    return ITEMS[item].get('fund_price', ITEMS[item]['price']) * FUND_MARKUP // 100


def stage_need(pid, stage, total_ref):
    """Frozen at the start of a stage: goods 60% / earned coins 40% of ``share x sum(income_ref of active farms)``."""
    target = total_ref * STAGE_SHARE[stage] // 100
    goods = target * GOODS_PCT // 100
    keys = GOODS[pid][stage]
    each = goods // len(keys)
    out = {k: max(1, -(-each // unit_credit(k))) for k in keys}
    out['coins'] = target - goods
    return out


def complete(need_, got):
    return all(got.get(k, 0) >= v for k, v in need_.items())


def effective_end(row):
    if row['work_until'] is None:
        return None
    cut = min(row['speedup'], ENERGY_CAP) + row['fund_speed']
    return max(row['work_until'] - STAGE_WORK[row['stage']] + MIN_WORK, row['work_until'] - cut)


def bonus_state(farm):
    b = farm.setdefault('village_bonus', {})
    b.setdefault('tiers', {})
    b.setdefault('open', [])
    return b


def perk(farm, pid, tier=1):
    """True when the building is open and the farm holds at least ``tier`` there (pure: reads the farm mirror)."""
    b = farm.get('village_bonus') or {}
    return pid in b.get('open', ()) and b.get('tiers', {}).get(pid, 0) >= tier


def rows_open(farm):
    return 'stalls' in (farm.get('village_bonus') or {}).get('open', ())


def merchant_extra(farm, slot, now):
    """Extra purchases per visit for a Magpie slot: «мастер» of the rows (+1 each slot) and the fund's «Покупатель Сороки» (+1 on slot 0)."""
    return int(perk(farm, 'stalls', 2)) + int(slot == 0 and economy.perk(farm, 'magpie', now))


def merchant_price(farm, cost):
    return max(1, cost * (100 - HELPER_DISCOUNT_PCT) // 100) if perk(farm, 'stalls', 1) else cost


def stall_access(farm):
    return level(farm['xp']) >= STALL_LEVEL or perk(farm, 'stalls', 2)


def rent_for(farm):
    return max(1, income_ref(level(farm['xp'])) * RENT_PCT // 100)


# ------------------------------------------------------------------------------------------------------------ SQL helpers
async def _insert_ignore(unit, table, keys, **values):
    if unit.dialect == 'postgresql':
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    return await unit.execute(insert(table).values(**values).on_conflict_do_nothing(index_elements=keys))


async def _load(unit):
    t = unit.t['projects']
    rows = (await unit.execute(sa.select(t))).mappings().all()
    return {r['id']: {**dict(r), 'need': dict(r['need'] or {}), 'got': dict(r['got'] or {})} for r in rows}


async def _lock_row(unit, pid):
    t = unit.t['projects']
    row = (await unit.execute(sa.select(t).where(t.c.id == pid).with_for_update())).mappings().first()
    need(row is not None, 'not_found', 'Такой стройки нет.', 404)
    return {**dict(row), 'need': dict(row['need'] or {}), 'got': dict(row['got'] or {})}


async def _note(unit, farm, account_id, key, kind, now):
    """A ledger record without a balance change (a transition of the shared project)."""
    await unit.record(account_id, key[:64], kind, farm, farm, now)


async def active_ref(unit, now):
    t = unit.t['states']
    since = economy.moscow_day(now) - ACTIVE_DAYS
    rows = (await unit.execute(sa.select(t.c.xp).where(t.c.xp >= LEVELS[FUND_LEVEL - 1],
            t.c.payload['progress']['last'].as_integer() >= since).limit(20000))).all()
    return max(REF_FLOOR, sum(income_ref(level(r[0])) for r in rows))


async def _fund_reached(unit, now):
    if not hasattr(unit, 'village_peek'):
        return False
    row = await unit.village_peek(economy.season_of(now))
    return bool(row and row['total'] >= row['goal'])


async def _advance(unit, farm, account_id, row, now):
    t = unit.t['projects']
    if row['stage'] >= 2:
        values = dict(status='done', opened_at=int(now), work_until=None)
    else:
        stage = row['stage'] + 1
        values = dict(status='collecting', stage=stage, need=stage_need(row['id'], stage, await active_ref(unit, now)),
                      got={}, work_until=None, speedup=0, fund_speed=0)
    res = await unit.execute(t.update().where(t.c.id == row['id'], t.c.status == 'working', t.c.stage == row['stage'],
                                              t.c.version == row['version']).values(version=row['version'] + 1, **values))
    if res.rowcount == 1:
        await _note(unit, farm, account_id, f"v:{row['id']}:{row['stage']}:end", 'village_stage', now)
        return True
    return False


async def sync(unit, farm, account_id, now):
    """Lazy transitions. Idempotent: a repeated call changes nothing (every UPDATE is conditional on status/stage/version)."""
    if not available(unit):
        return
    t = unit.t['projects']
    rows = await _load(unit)
    if len(rows) < len(ORDER):
        for pid in ORDER:
            if pid not in rows:
                await _insert_ignore(unit, t, ['id'], id=pid, status='soon', stage=0, need={}, got={}, speedup=0, fund_speed=0, version=0)
        rows = await _load(unit)
    changed, reached = False, None
    for pid in ORDER:
        row = rows.get(pid)
        if not row or row['status'] != 'working':
            continue
        if reached is None:
            reached = await _fund_reached(unit, now)
        if reached and row['fund_speed'] == 0:
            res = await unit.execute(t.update().where(t.c.id == pid, t.c.status == 'working', t.c.stage == row['stage'],
                                                      t.c.fund_speed == 0).values(fund_speed=FUND_SPEED))
            row['fund_speed'] = FUND_SPEED
            changed = changed or res.rowcount == 1
        if now >= effective_end(row):
            changed = await _advance(unit, farm, account_id, row, now) or changed
    if changed:
        rows = await _load(unit)
    if not any(r['status'] in ('collecting', 'working') for r in rows.values()):
        for i, pid in enumerate(ORDER):
            if rows[pid]['status'] == 'soon' and all(rows[p]['status'] == 'done' for p in ORDER[:i]):
                need_ = stage_need(pid, 0, await active_ref(unit, now))
                res = await unit.execute(t.update().where(t.c.id == pid, t.c.status == 'soon').values(
                    status='collecting', stage=0, need=need_, got={}, version=rows[pid]['version'] + 1))
                if res.rowcount == 1:
                    await _note(unit, farm, account_id, f'v:{pid}:start', 'village_stage', now)
                break


async def refresh_bonus(unit, farm, account_id):
    """Mirror of the player's tiers and of the open buildings in the farm (a quiet key: no automation ledger record)."""
    if not available(unit):
        return
    rows = await _load(unit)
    c = unit.t['contribs']
    tiers = {r[0]: r[1] for r in (await unit.execute(sa.select(c.c.project_id, c.c.tier).where(
        c.c.account_id == UUID(str(account_id)), c.c.tier > 0))).all()}
    opened = [p for p in ORDER if rows.get(p, {}).get('status') == 'done']
    b = bonus_state(farm)
    if b['tiers'] != tiers or b['open'] != opened:
        b['tiers'], b['open'] = tiers, opened


async def tick_account(unit, farm, account_id, now):
    """Everything the service runs on the owner's own visit: transitions, mirror and the rent of the own stall."""
    if not available(unit):
        return
    await sync(unit, farm, account_id, now)
    await refresh_bonus(unit, farm, account_id)
    await stall_rent(unit, farm, account_id, now)


# ------------------------------------------------------------------------------------------------------------ commands
def _check_project(data):
    pid = data.get('project')
    need(isinstance(pid, str) and pid in ORDER, 'unknown_project', 'Такой стройки нет.', 422)
    return pid


async def contribute(unit, farm, account_id, data, now):
    need(set(data) == {'project', 'items', 'coins'}, 'invalid_command', 'Некорректные параметры действия.', 422)
    pid = _check_project(data)
    coins, items = data['coins'], data['items']
    need(type(coins) is int and coins >= 0 and isinstance(items, dict) and len(items) <= 12
         and all(isinstance(k, str) and type(q) is int and q > 0 for k, q in items.items()),
         'invalid_command', 'Некорректный вклад.', 422)
    lv = level(farm['xp'])
    need(lv >= FUND_LEVEL, 'locked', f'Стройка открывается с {FUND_LEVEL} уровня.')
    unbound(list(items))
    for k in items:
        named(ITEMS, k)
    row = await _lock_row(unit, pid)
    need(row['status'] == 'collecting', 'stage_closed',
         'Этап уже собран.' if row['status'] in ('working', 'done') else 'Эта стройка ещё не началась.')
    need_, got = row['need'], row['got']
    need(all(k in need_ and k != 'coins' for k in items), 'not_needed', 'Это на стройку сейчас не нужно.', 422)
    accepted = {}
    for k, q in items.items():
        take = min(q, need_[k] - got.get(k, 0))
        if take > 0:
            accepted[k] = take
    coins_ok = min(coins, need_.get('coins', 0) - got.get('coins', 0))
    need(accepted or coins_ok > 0, 'nothing_needed', 'Этого уже хватает: лишнее не принимается.')
    need(coins_ok <= max(0, farm['coins'] - farm['starter_credit']), 'earned_coins',
         'В стройку идут только заработанные монеты, не стартовый подарок.')
    if accepted:
        inventory(farm, accepted, -1)
    farm['coins'] -= coins_ok
    value = coins_ok + economy.goods_value(accepted)
    new_got = dict(got)
    for k, q in accepted.items():
        new_got[k] = new_got.get(k, 0) + q
    if coins_ok:
        new_got['coins'] = new_got.get('coins', 0) + coins_ok
    full = complete(need_, new_got)
    t = unit.t['projects']
    values = dict(got=new_got, version=row['version'] + 1)
    if full:
        values.update(status='working', work_until=int(now) + STAGE_WORK[row['stage']])
    res = await unit.execute(t.update().where(t.c.id == pid, t.c.status == 'collecting', t.c.stage == row['stage'],
                                              t.c.version == row['version']).values(**values))
    need(res.rowcount == 1, 'stage_closed', 'Этап уже собран.')
    old_tier, new_tier = await _bump_contrib(unit, pid, account_id, farm, value, now)
    text = f'{NAMES[pid]}: внесено {value}.'
    if full:
        text += f' Этап «{STAGE_NAMES[row["stage"]].lower()}» собран, жители взялись за работу!'
        await _note(unit, farm, account_id, f"v:{pid}:{row['stage']}:funded", 'village_stage', now)
    if new_tier > old_tier:
        text += f' Ступень: «{TIER_NAMES[new_tier]}»!'
        await _note(unit, farm, account_id, f'v:{pid}:tier{new_tier}', 'village_tier', now)
    await refresh_bonus(unit, farm, account_id)
    skipped = sum(items.values()) - sum(accepted.values()) + coins - coins_ok
    if skipped > 0:
        text += ' Лишнее осталось у тебя.'
    return text


async def _bump_contrib(unit, pid, account_id, farm, value, now):
    c = unit.t['contribs']
    aid = UUID(str(account_id))
    row = (await unit.execute(sa.select(c).where(c.c.project_id == pid, c.c.account_id == aid).with_for_update())).mappings().first()
    bp = value * 10000 // income_ref(level(farm['xp']))
    if row is None:
        tier = tier_of(bp)
        await unit.execute(c.insert().values(project_id=pid, account_id=aid, farm_id=UUID(farm['id']), value=value, share_bp=bp,
                                             tier=tier, updated_at=int(now)))
        return 0, tier
    share = row['share_bp'] + bp
    tier = max(row['tier'], tier_of(share))
    await unit.execute(c.update().where(c.c.project_id == pid, c.c.account_id == aid).values(
        value=row['value'] + value, share_bp=share, tier=tier, updated_at=int(now)))
    return row['tier'], tier


async def speedup(unit, farm, account_id, data, now):
    need(set(data) == {'project', 'item', 'qty'}, 'invalid_command', 'Некорректные параметры действия.', 422)
    pid = _check_project(data)
    item, qty = data['item'], data['qty']
    need(isinstance(item, str) and item in ENERGY and type(qty) is int and 1 <= qty <= 50, 'invalid_command',
         'Пуху нужен энергетос.', 422)
    need(level(farm['xp']) >= FUND_LEVEL, 'locked', f'Стройка открывается с {FUND_LEVEL} уровня.')
    row = await _lock_row(unit, pid)
    need(row['status'] == 'working', 'not_working', 'Сейчас жители не работают: бодрить некого.')
    room = (ENERGY_CAP - row['speedup']) // ENERGY_SECONDS
    take = min(qty, room)
    need(take > 0, 'pukh_tired', 'Пух уже выложился на этом этапе: больше суток не сэкономить.')
    inventory(farm, {item: take}, -1)
    t = unit.t['projects']
    res = await unit.execute(t.update().where(t.c.id == pid, t.c.status == 'working', t.c.stage == row['stage'],
        t.c.speedup == row['speedup']).values(speedup=row['speedup'] + take * ENERGY_SECONDS, version=row['version'] + 1))
    need(res.rowcount == 1, 'stage_closed', 'Этап уже изменился. Обнови ферму.')
    return f'Пух работает за троих: этап ускорен на {take * 2} ч.'


# ------------------------------------------------------------------------------------------------------------ stalls
def _lot_dict(r):
    return dict(id=str(r['id']), item=r['item'], qty=r['qty'], unit_price=r['unit_price'], seller_farm=str(r['seller_farm']),
                paid_until=r['rent_paid_until'])


async def _open_lots(unit, account_id, now=None, live=True):
    t = unit.t['lots']
    q = sa.select(t).where(t.c.seller_account == UUID(str(account_id)), t.c.status == 'open')
    if live and now is not None:
        q = q.where(t.c.rent_paid_until > now)
    return (await unit.execute(q.order_by(t.c.created_at, t.c.id))).mappings().all()


async def _close_lot(unit, farm, row, now):
    t = unit.t['lots']
    res = await unit.execute(t.update().where(t.c.id == row['id'], t.c.status == 'open').values(status='closed', closed_at=int(now)))
    if res.rowcount == 1:
        inventory(farm, {row['item']: row['qty']})
        return True
    return False


async def stall_rent(unit, farm, account_id, now):
    """Lazy rent on the seller's own visit: renew when something sold in the week and the rent is paid, otherwise close and return the goods."""
    due = [r for r in await _open_lots(unit, account_id, live=False) if r['rent_paid_until'] <= now]
    if not due:
        return
    t = unit.t['lots']
    paid_until = due[0]['rent_paid_until']
    sold = (await unit.execute(sa.select(sa.func.count()).select_from(t).where(
        t.c.seller_account == UUID(str(account_id)), t.c.status == 'sold', t.c.sold_at >= paid_until - RENT_PERIOD))).scalar_one()
    periods = min(4, 1 + int((now - paid_until) // RENT_PERIOD))
    rent = rent_for(farm) * periods
    if sold and rent <= max(0, farm['coins'] - farm['starter_credit']):
        farm['coins'] -= rent
        for r in due:
            await unit.execute(t.update().where(t.c.id == r['id'], t.c.status == 'open').values(
                rent_paid_until=paid_until + periods * RENT_PERIOD))
        event(farm, now, f'Аренда лавки на площади: −{rent} монет.', 'trade')
        return
    for r in due:
        await _close_lot(unit, farm, r, now)
    event(farm, now, 'Лавка на площади закрылась: за неделю ничего не продано или нечем платить за место. Товар вернулся на склад.', 'trade')


async def stall_list(unit, farm, account_id, data, now):
    need(set(data) == {'item', 'qty', 'unit_price'}, 'invalid_command', 'Некорректные параметры действия.', 422)
    need(rows_open(farm), 'rows_closed', 'Торговые ряды ещё не построены.')
    need(stall_access(farm), 'stall_locked', 'Своя лавка: со ступени «Мастер» торговых рядов или с 10 уровня.')
    item = named(ITEMS, data['item'])
    unbound([item['id']])
    qty, price = data['qty'], data['unit_price']
    need(type(qty) is int and 1 <= qty <= LOT_QTY_MAX, 'invalid_number', 'Недопустимое количество.', 422)
    need(type(price) is int and item['price'] <= price <= item['price'] * PRICE_MAX_PCT // 100, 'invalid_price',
         'Цена в лавке на площади — от 1 до 1,5 цены товара.', 422)
    mine = await _open_lots(unit, account_id, now)
    need(len(mine) < STALL_LOTS, 'stall_full', 'В лавке три места. Продай или убери один лот.')
    if mine:
        paid_until = mine[0]['rent_paid_until']
    else:
        rent = rent_for(farm)
        need(rent <= max(0, farm['coins'] - farm['starter_credit']), 'earned_coins', f'Аренда места — {rent} заработанных монет.')
        farm['coins'] -= rent
        paid_until = int(now) + RENT_PERIOD
    inventory(farm, {item['id']: qty}, -1)
    await unit.execute(unit.t['lots'].insert().values(id=uuid4(), seller_farm=UUID(farm['id']), seller_account=UUID(str(account_id)),
        item=item['id'], qty=qty, unit_price=price, created_at=int(now), rent_paid_until=paid_until, status='open'))
    return 'Товар выставлен в лавке на площади.'


async def stall_cancel(unit, farm, account_id, data, now):
    need(set(data) == {'lot'}, 'invalid_command', 'Некорректные параметры действия.', 422)
    lot = _uuid(data['lot'])
    t = unit.t['lots']
    row = (await unit.execute(sa.select(t).where(t.c.id == lot, t.c.seller_account == UUID(str(account_id))).with_for_update())).mappings().first()
    need(row is not None and row['status'] == 'open', 'lot_gone', 'Лот уже продан или снят.', 404)
    need(await _close_lot(unit, farm, row, now), 'lot_gone', 'Лот уже продан или снят.', 404)
    return 'Товар возвращён на склад.'


def _uuid(value):
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        raise FarmError('invalid_command', 'Некорректный лот.', 422)


async def stall_buy(unit, me, other, account_id, data, now):
    need(set(data) == {'lot'}, 'invalid_command', 'Некорректные параметры действия.', 422)
    need(rows_open(me), 'rows_closed', 'Торговые ряды ещё не построены.')
    need(me['id'] != other['id'], 'own_farm', 'Свой лот не покупают.', 422)
    lot = _uuid(data['lot'])
    t = unit.t['lots']
    row = (await unit.execute(sa.select(t).where(t.c.id == lot).with_for_update())).mappings().first()
    need(row is not None and row['status'] == 'open' and row['rent_paid_until'] > now, 'lot_gone', 'Лот уже продан или снят.', 404)
    need(str(row['seller_farm']) == other['id'], 'stale_lot', 'Лот уже изменился. Обнови ряды.')
    day0 = (economy.moscow_day(now)) * DAY - economy.TZ_OFFSET
    bought = (await unit.execute(sa.select(sa.func.count()).select_from(t).where(
        t.c.buyer_farm == UUID(me['id']), t.c.seller_farm == UUID(other['id']), t.c.status == 'sold', t.c.sold_at >= day0))).scalar_one()
    need(bought < BUYS_PER_DAY, 'buy_limit', 'У одного продавца — не больше трёх покупок в сутки.', 429)
    cost = row['qty'] * row['unit_price']
    pay = cost          # the helper discount is only for the Magpie (a system sink): between players it would mint coins
    need(me['coins'] - me['starter_credit'] >= pay, 'earned_coins', 'На рынке используются только заработанные монеты, не стартовый подарок.')
    fee = max(1, math.ceil(pay * COMMISSION_PCT / 100))
    need(other['coins'] + pay - fee <= MAX_COINS, 'seller_full', 'У продавца переполнен кошелёк.')
    res = await unit.execute(t.update().where(t.c.id == lot, t.c.status == 'open', t.c.rent_paid_until > now).values(
        status='sold', sold_at=int(now), buyer_farm=UUID(me['id'])))
    need(res.rowcount == 1, 'lot_gone', 'Лот уже продан или снят.', 404)
    me['coins'] -= pay
    other['coins'] += pay - fee
    inventory(me, {row['item']: row['qty']})
    event(other, now, f'{me["name"]} покупает в твоей лавке на площади: +{pay - fee} монет (комиссия {fee}).', 'trade')
    return f'Покупка получена за {pay} монет.'


# ------------------------------------------------------------------------------------------------------------ dispatch
async def command(unit, farm, other, account_id, kind, data, now):
    """Returns (notice, ledger kind). ``other`` is the second locked farm (only stall_buy uses it)."""
    need(available(unit), 'village_build_unavailable', 'Стройка временно недоступна.', 503)
    if kind != 'stall_buy':
        need(other is farm, 'not_owner', 'Это не твоя ферма.', 403)
    if kind == 'build_contribute':
        return await contribute(unit, farm, account_id, data, now), kind
    if kind == 'build_speedup':
        return await speedup(unit, farm, account_id, data, now), kind
    if kind == 'stall_list':
        return await stall_list(unit, farm, account_id, data, now), kind
    if kind == 'stall_cancel':
        return await stall_cancel(unit, farm, account_id, data, now), kind
    if kind == 'stall_buy':
        return await stall_buy(unit, farm, other, account_id, data, now), kind
    raise FarmError('invalid_command', 'Неизвестная команда.', 422)


# ------------------------------------------------------------------------------------------------------------ projection
async def projection(unit, farm, account_id, now):
    if not available(unit):
        return None
    rows = await _load(unit)
    c, accounts = unit.t['contribs'], unit.t['states'].metadata.tables['accounts']
    mine = {r['project_id']: r for r in (await unit.execute(sa.select(c).where(c.c.account_id == UUID(str(account_id))))).mappings().all()}
    projects, active = [], None
    for i, pid in enumerate(ORDER):
        r = rows.get(pid) or dict(status='soon', stage=0, need={}, got={}, work_until=None, speedup=0, fund_speed=0, opened_at=None)
        if r['status'] in ('collecting', 'working'):
            active = pid
        total = sum(v for v in r['need'].values()) or 0
        pct = None
        if r['status'] == 'collecting' and r['need']:
            pct = int(100 * sum(min(r['got'].get(k, 0), v) for k, v in r['need'].items()) / max(1, total))
        mc = mine.get(pid)
        projects.append(dict(id=pid, name=NAMES[pid], order=i, status=r['status'], stage=r['stage'], stage_name=STAGE_NAMES[r['stage']],
            need=r['need'], got=r['got'], pct=pct, work_until=effective_end(r) if r['status'] == 'working' else None,
            work_total=STAGE_WORK[r['stage']], speedup=r['speedup'], fund_speed=r['fund_speed'],
            speedup_room=max(0, ENERGY_CAP - r['speedup']), opened_at=r['opened_at'],
            mine=dict(value=mc['value'], share_bp=mc['share_bp'], tier=mc['tier']) if mc else dict(value=0, share_bp=0, tier=0),
            bonus=BONUS_TEXT[pid]))
    honor = {}
    done = [p for p in ORDER if rows.get(p, {}).get('status') == 'done']
    if done:
        s = unit.t['states']
        q = sa.select(c.c.project_id, s.c.name).join(s, s.c.id == c.c.farm_id).where(c.c.tier == 3, c.c.project_id.in_(done))
        if 'rating_hidden' in accounts.c:
            q = q.join(accounts, accounts.c.id == c.c.account_id).where(accounts.c.rating_hidden.is_(False))
        for pid, name in (await unit.execute(q.order_by(c.c.updated_at).limit(60))).all():
            honor.setdefault(pid, []).append(name)
    return dict(level_ok=level(farm['xp']) >= FUND_LEVEL, level=FUND_LEVEL, active=active, projects=projects, honor=honor,
                tier_bp=list(TIER_BP), tier_names=list(TIER_NAMES), energy=list(ENERGY),
                rows=await rows_projection(unit, farm, account_id, now) if 'stalls' in done else dict(open=False),
                stub=dict(effects=['tavern', 'greenhouse', 'fairground'], magpie_third_visit=True))


async def rows_projection(unit, farm, account_id, now):
    t = unit.t['lots']
    s = unit.t['states']
    q = (sa.select(t, s.c.name).join(s, s.c.id == t.c.seller_farm)
         .where(t.c.status == 'open', t.c.rent_paid_until > now).order_by(t.c.created_at.desc(), t.c.id).limit(60))
    lots = (await unit.execute(q)).mappings().all()
    c = unit.t['contribs']
    sellers = {r['seller_account'] for r in lots}
    honored = set()
    if sellers:
        honored = {r[0] for r in (await unit.execute(sa.select(c.c.account_id).where(
            c.c.project_id == 'stalls', c.c.tier == 3, c.c.account_id.in_(sellers)))).all()}
    me = UUID(str(account_id))
    day0 = economy.moscow_day(now) * DAY - economy.TZ_OFFSET
    bought = {str(r[0]): r[1] for r in (await unit.execute(sa.select(t.c.seller_farm, sa.func.count()).where(
        t.c.buyer_farm == UUID(farm['id']), t.c.status == 'sold', t.c.sold_at >= day0).group_by(t.c.seller_farm))).all()}
    out = []
    for r in lots:
        out.append(dict(id=str(r['id']), item=r['item'], qty=r['qty'], unit_price=r['unit_price'], seller=r['name'],
                        seller_farm=str(r['seller_farm']), mine=r['seller_account'] == me, honor=r['seller_account'] in honored,
                        buys_today=bought.get(str(r['seller_farm']), 0)))
    own = [o for o in out if o['mine']]
    return dict(open=True, lots=[o for o in out if not o['mine']], own=own, access=stall_access(farm), rent=rent_for(farm),
                rent_period=RENT_PERIOD, paid_until=min((r['rent_paid_until'] for r in lots if r['seller_account'] == me), default=None),
                max_lots=STALL_LOTS, price_min_pct=100, price_max_pct=PRICE_MAX_PCT, commission_pct=COMMISSION_PCT,
                buys_per_day=BUYS_PER_DAY, level=STALL_LEVEL)


# ------------------------------------------------------------------------------------------------------------ account merge
async def merge_prepare(unit, main_id, secondary_id, now):
    """Before the farms are merged: close the secondary's open lots (goods return to the secondary farm) and add up the contributions."""
    if not available(unit):
        return
    sec_farm = await unit.by_account(secondary_id)
    main_farm = await unit.by_account(main_id)
    if sec_farm is not None:
        lots = await _open_lots(unit, secondary_id, live=False)
        if lots:
            before = deepcopy(sec_farm)
            for r in lots:
                await _close_lot(unit, sec_farm, r, now)
            sec_farm['revision'] += 1
            await unit.save(sec_farm)
            await unit.record(main_id, f'merge-lots:{secondary_id}'[:64], 'village_lots', before, sec_farm, now)
    c = unit.t['contribs']
    for r in (await unit.execute(sa.select(c).where(c.c.account_id == UUID(str(secondary_id))))).mappings().all():
        keep = (await unit.execute(sa.select(c).where(c.c.project_id == r['project_id'], c.c.account_id == UUID(str(main_id))))).mappings().first()
        farm_id = UUID(main_farm['id']) if main_farm else r['farm_id']
        if keep is None:
            await unit.execute(c.update().where(c.c.project_id == r['project_id'], c.c.account_id == UUID(str(secondary_id))).values(
                account_id=UUID(str(main_id)), farm_id=farm_id))
        else:
            share = keep['share_bp'] + r['share_bp']
            await unit.execute(c.update().where(c.c.project_id == r['project_id'], c.c.account_id == UUID(str(main_id))).values(
                value=keep['value'] + r['value'], share_bp=share, tier=max(keep['tier'], r['tier'], tier_of(share)), farm_id=farm_id))
            await unit.execute(c.delete().where(c.c.project_id == r['project_id'], c.c.account_id == UUID(str(secondary_id))))
