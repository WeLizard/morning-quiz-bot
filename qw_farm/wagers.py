"""Server-side Dasha cup wagers. Secrets live only in ``farm_wager_rounds``."""
from __future__ import annotations

import secrets
from uuid import UUID, uuid4
from copy import deepcopy

from sqlalchemy import select, func

from . import economy
from .catalog import level
from .domain import FarmError, need

STAKES = (10, 20, 50)
PAYOUTS = {10: 27, 20: 54, 50: 135}
MIN_LEVEL = 3
DAILY_LIMIT = 200
ROUND_SECONDS = 600
RULES_VERSION = 1
MAX_COINS = 10**12
MOSCOW_OFFSET = 3 * 3600


def available(unit):
    return getattr(unit, 't', {}).get('wagers') is not None


def rules():
    return dict(stakes=list(STAKES), payouts={'10': 27, '20': 54, '50': 135},
                multiplier=2.7, win_probability='1/3',
                min_level=MIN_LEVEL, daily_stake_limit=DAILY_LIMIT, round_seconds=ROUND_SECONDS)


def day_bounds(now):
    day = (int(now) + MOSCOW_OFFSET) // 86400
    return day * 86400 - MOSCOW_OFFSET, (day + 1) * 86400 - MOSCOW_OFFSET


async def active(unit, account_id):
    if not available(unit):
        return None
    t = unit.t['wagers']
    row = (await unit.execute(select(t).where(t.c.account_id == UUID(str(account_id)),
                                               t.c.settled_at.is_(None)))).mappings().first()
    return dict(row) if row else None


async def expire(unit, farm, account_id, now):
    if not available(unit):
        return False
    row = await active(unit, account_id)
    if row is None or row['expires_at'] > now:
        return False
    t = unit.t['wagers']
    chosen = row['default_cup']
    won = chosen == row['winning_cup']
    due = row['payout'] if won else 0
    paid = min(due, max(0, MAX_COINS-farm['coins']))
    before = deepcopy(farm)
    pending = due-paid
    farm['coins'] += paid
    farm['revision'] += 1
    result = await unit.execute(t.update().where(t.c.id == row['id'], t.c.settled_at.is_(None)).values(
        chosen_cup=chosen, settled_at=now, won=won, pending_payout=pending))
    if result.rowcount != 1:
        raise FarmError('wager_race', 'Раунд уже завершён. Обнови ферму.', 409)
    await unit.save(farm)
    await unit.record(account_id, 'wager-expire:' + str(row['id']), 'wager_settle', before, farm, now)
    return True


async def claim_pending(unit, farm, account_id, now):
    """Pay settled winnings as wallet room becomes available; each transfer has its own ledger row."""
    if not available(unit):
        return
    t = unit.t['wagers']
    rows = (await unit.execute(select(t).where(t.c.account_id == UUID(str(account_id)),
        t.c.pending_payout > 0, t.c.settled_at.is_not(None)).order_by(t.c.settled_at, t.c.id)
        .with_for_update())).mappings().all()
    for row in rows:
        paid = min(max(0, MAX_COINS-farm['coins']), row['pending_payout'])
        if paid <= 0:
            break
        before = deepcopy(farm)
        remaining = row['pending_payout']-paid
        await unit.execute(t.update().where(t.c.id == row['id'], t.c.pending_payout == row['pending_payout'])
            .values(pending_payout=remaining))
        farm['coins'] += paid
        farm['revision'] += 1
        await unit.save(farm)
        await unit.record(account_id, f"wager-claim:{row['id']}:{row['pending_payout']}", 'wager_claim', before, farm, now)


async def projection(unit, farm, account_id, now):
    if not available(unit):
        return dict(rules=rules(), earned_balance=max(0,farm['coins']-farm['starter_credit']),
            eligible=False, reason='unavailable', daily_staked=0, remaining_stake=DAILY_LIMIT,
            pending_payout=0, active=None, last_result=None)
    t = unit.t['wagers']
    lo, hi = day_bounds(now)
    daily = int((await unit.execute(select(func.coalesce(func.sum(t.c.stake), 0)).where(
        t.c.account_id == UUID(str(account_id)), t.c.created_at >= lo, t.c.created_at < hi))).scalar_one())
    row = await active(unit, account_id)
    last = (await unit.execute(select(t).where(t.c.account_id == UUID(str(account_id)),
        t.c.settled_at.is_not(None)).order_by(t.c.settled_at.desc(), t.c.id.desc()).limit(1))).mappings().first()
    lv = level(farm['xp'])
    eligible = lv >= MIN_LEVEL
    reason = None if eligible else 'level'
    pending = int((await unit.execute(select(func.coalesce(func.sum(t.c.pending_payout), 0)).where(
        t.c.account_id == UUID(str(account_id)), t.c.settled_at.is_not(None)))).scalar_one())
    if eligible and pending:
        eligible, reason = False, 'pending_payout'
    elif eligible and row is not None:
        eligible, reason = False, 'active'
    elif eligible and DAILY_LIMIT-daily < min(STAKES):
        eligible, reason = False, 'daily_limit'
    elif eligible and farm['coins']-farm['starter_credit'] < min(STAKES):
        eligible, reason = False, 'earned_balance'
    elif eligible and farm['coins']-min(STAKES)+PAYOUTS[min(STAKES)] > MAX_COINS:
        eligible, reason = False, 'wallet_limit'
    return dict(rules=rules(), earned_balance=max(0, farm['coins']-farm['starter_credit']),
        eligible=eligible, reason=reason, daily_staked=daily, remaining_stake=max(0, DAILY_LIMIT-daily),
        pending_payout=pending,
        active=None if row is None else dict(id=str(row['id']), stake=row['stake'], payout=row['payout'],
            expires_at=row['expires_at'], rules_version=row['rules_version']),
        last_result=None if last is None else dict(id=str(last['id']), stake=last['stake'], payout=last['payout'],
            chosen_cup=last['chosen_cup'], winning_cup=last['winning_cup'], won=last['won'],
            settled_at=last['settled_at'], pending_payout=last['pending_payout']))


async def command(unit, farm, account_id, kind, data, now):
    need(available(unit), 'wager_unavailable', 'Игра временно недоступна.', 503)
    t = unit.t['wagers']
    if kind == 'wager_start':
        need(set(data) == {'stake'} and type(data.get('stake')) is int and data['stake'] in STAKES,
             'invalid_command', 'Некорректная ставка.', 422)
        stake = data['stake']
        need(level(farm['xp']) >= MIN_LEVEL, 'wager_locked', 'Игра открывается с 3 уровня.', 409)
        lo, hi = day_bounds(now)
        daily = int((await unit.execute(select(func.coalesce(func.sum(t.c.stake), 0)).where(
            t.c.account_id == UUID(str(account_id)), t.c.created_at >= lo, t.c.created_at < hi))).scalar_one())
        need(daily + stake <= DAILY_LIMIT, 'wager_daily_limit', 'На сегодня лимит ставок исчерпан.', 409)
        need(farm['coins'] - farm['starter_credit'] >= stake, 'earned_coins',
             'Для ставки нужны заработанные монеты, не стартовый подарок.')
        need(farm['coins'] - stake + PAYOUTS[stake] <= MAX_COINS, 'wager_balance_limit',
             'На балансе нет места для полной выплаты. Потрать немного монет и попробуй снова.', 409)
        pending = await unit.execute(select(t.c.id).where(t.c.account_id == UUID(str(account_id)),
            t.c.settled_at.is_not(None), t.c.pending_payout > 0).limit(1))
        need(pending.first() is None, 'wager_pending_payout',
             'Сначала освободи место на балансе для предыдущей выплаты.', 409)
        need(await active(unit, account_id) is None, 'wager_active', 'Сначала заверши текущий раунд.', 409)
        farm['coins'] -= stake
        uid = uuid4()
        await unit.execute(t.insert().values(id=uid, account_id=UUID(str(account_id)), farm_id=UUID(farm['id']),
            stake=stake, payout=PAYOUTS[stake], rules_version=RULES_VERSION, created_at=now,
            expires_at=now+ROUND_SECONDS, winning_cup=secrets.randbelow(3), default_cup=secrets.randbelow(3)))
        return 'Ставка принята. Выбери один из трёх стаканчиков.', 'wager_start'
    if kind == 'wager_choose':
        need(set(data) == {'round_id', 'cup'} and type(data.get('cup')) is int and data['cup'] in (0, 1, 2),
             'invalid_command', 'Некорректный выбор.', 422)
        try:
            rid = UUID(data['round_id']) if isinstance(data['round_id'], str) else None
        except (ValueError, TypeError, AttributeError):
            rid = None
        need(rid is not None, 'invalid_command', 'Некорректный раунд.', 422)
        row = (await unit.execute(select(t).where(t.c.id == rid, t.c.account_id == UUID(str(account_id)),
            t.c.farm_id == UUID(farm['id']), t.c.settled_at.is_(None)).with_for_update())).mappings().first()
        need(row is not None, 'wager_not_found', 'Раунд не найден или уже завершён.', 404)
        need(row['expires_at'] > now, 'wager_expired', 'Время раунда истекло. Обнови ферму.', 409)
        cup = data['cup']; won = cup == row['winning_cup']
        due = row['payout'] if won else 0
        paid = min(due, max(0, MAX_COINS-farm['coins']))
        pending = due-paid
        farm['coins'] += paid
        await unit.execute(t.update().where(t.c.id == rid, t.c.settled_at.is_(None)).values(
            chosen_cup=cup, settled_at=now, won=won, pending_payout=pending))
        notice = ('Ты выиграл(а)! Выплата уже на балансе.' if won and not pending else
                  f'Ты выиграл(а)! {paid} монет начислено, {pending} отложено до появления места на балансе.' if won else
                  'В этот раз морковка была в другом стаканчике.')
        return notice, 'wager_settle'
    raise FarmError('invalid_command', 'Неизвестная команда.', 422)
