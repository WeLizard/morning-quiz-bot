"""Shared daily cash-premium budget. Called under the existing farm lock.

Sales, paid orders, wagers, refunds, capital and XP are outside this budget.
"""
from copy import deepcopy
from uuid import UUID
import sqlalchemy as sa

from .catalog import income_ref, level
from . import economy
from .domain import need

KEY = 'daily_cash_bonus'
SOURCES = ('house','barn','oleg','village_games','dinner')
MAX_COINS = 10**12


def blank(farm, now):
    ref = income_ref(level(farm['xp']))
    return dict(day=economy.moscow_day(now),ref=ref,cap=ref*3//100,paid=0,by_source={})


def snapshot(farm, now):
    value = farm.get(KEY)
    return deepcopy(value) if value and value['day'] == economy.moscow_day(now) else blank(farm,now)


def public(farm, now):
    value = snapshot(farm,now)
    return dict(value,remaining=max(0,value['cap']-value['paid']),pct=3)


def quote(farm, now, requested):
    value = snapshot(farm,now)
    return min(requested,max(0,value['cap']-value['paid']))


def grant(farm, source, requested, now):
    need(source in SOURCES and type(requested) is int and requested >= 0,
         'invalid_bonus','Некорректная премия.',500)
    value = snapshot(farm,now)
    actual = min(requested,max(0,value['cap']-value['paid']))
    need(farm['coins'] + actual <= MAX_COINS,'balance_full','На счёте нет места для премии.')
    value['paid'] += actual
    value['by_source'][source] = value['by_source'].get(source,0)+actual
    farm[KEY] = value
    farm['coins'] += actual
    return actual


def merge(main, secondary, now):
    day = economy.moscow_day(now)
    if main.get(KEY,{}).get('day') != day and secondary.get(KEY,{}).get('day') != day:
        return
    left,right = snapshot(main,now),snapshot(secondary,now)
    left['paid'] += right['paid']
    for source,amount in right['by_source'].items():
        left['by_source'][source] = left['by_source'].get(source,0)+amount
    if left.get('bootstrap_incomplete') or right.get('bootstrap_incomplete'):
        left['paid'] = max(left['paid'],left['cap'])
        left['bootstrap_incomplete'] = True
    main[KEY] = left


def validate(farm):
    value = farm.get(KEY)
    if value is None:
        return
    need(type(value) is dict and {'day','ref','cap','paid','by_source'} <= value.keys()
         and set(value) <= {'day','ref','cap','paid','by_source','bootstrap_incomplete'}
         and all(type(value[k]) is int and value[k] >= 0 for k in ('day','ref','cap','paid'))
         and value['cap'] == value['ref']*3//100 and type(value['by_source']) is dict
         and all(k in SOURCES and type(v) is int and v >= 0 for k,v in value['by_source'].items())
         and sum(value['by_source'].values()) <= value['paid']
         and type(value.get('bootstrap_incomplete',False)) is bool,
         'invalid_bonus','Некорректное состояние ежедневных премий.',500)


async def bootstrap(unit, farm, now):
    """Account for today's legacy premiums before activating the shared budget."""
    if farm.get(KEY,{}).get('day') == economy.moscow_day(now):
        return
    # Pure/domain harnesses have no ledger; service Units always do.
    table = getattr(unit,'t',{}).get('ledger')
    if table is None:
        return
    start = economy.moscow_day(now)*86400-economy.TZ_OFFSET
    rows = (await unit.execute(sa.select(table).where(table.c.farm_id == UUID(farm['id']),
        table.c.created_at >= start,table.c.created_at < start+86400,
        table.c.kind.in_(('minigame_answer','oleg_answer','vgame_premium'))))).mappings().all()
    receipts = unit.t['receipts']
    responses = (await unit.execute(sa.select(receipts.c.command_id,receipts.c.result).where(
        receipts.c.account_id == UUID(str(await unit.owner_account(farm['id']))),
        receipts.c.created_at >= start,receipts.c.created_at < start+86400))).all() if rows else []
    by_command = dict(responses)
    value, seen, incomplete = blank(farm,now),set(),False
    for row in rows:
        response = by_command.get(row['command_id']) or {}
        candidates = []
        if row['kind'] == 'minigame_answer':
            for game,state in response.get('minigames',{}).items():
                result = state.get('last_result') or {}
                if result.get('answered_at') == int(row['created_at']) and 'attempt_id' in result:
                    amount = result['reward'] if result.get('reward_kind','coins' if game=='house' else 'feed') == 'coins' else 0
                    candidates.append((game,result['attempt_id'],amount))
        elif row['kind'] == 'oleg_answer':
            state = response.get('oleg_game') or {}
            result = state.get('last_result') or {}
            if result.get('at') == int(row['created_at']) and 'run_id' in result:
                candidates.append(('oleg',result['run_id'],result['coins']))
            elif state.get('active') is not None:
                continue # A successfully repeated intermediate round pays nothing.
        else:
            run_id = row['command_id'].split(':')[1] if row['command_id'].startswith('vgame:') else None
            matches = []
            for _,candidate in responses:
                for state in candidate.get('village_games',{}).values():
                    result = state.get('last_result') or {}
                    if run_id and result.get('run_id') == run_id and result.get('reward_kind') == 'premium':
                        matches.append(result.get('reward'))
            if matches and len(set(matches)) == 1:
                candidates.append(('village_games',run_id,matches[0]))
        if not candidates:
            incomplete = True
        for source,identity,amount in candidates:
            key = (source,identity)
            if key in seen:
                continue
            if type(amount) is not int or amount < 0:
                incomplete = True
                continue
            seen.add(key)
            value['paid'] += amount
            value['by_source'][source] = value['by_source'].get(source,0)+amount
    dinner = (farm.get('tavern') or {}).get('dinner') or {}
    if dinner.get('day') == value['day']:
        amount = dinner.get('paid',0)
        value['paid'] += amount
        value['by_source']['dinner'] = amount
    if incomplete:
        value['paid'] = max(value['paid'],value['cap'])
        value['bootstrap_incomplete'] = True
    if value['paid']:
        farm[KEY] = value
