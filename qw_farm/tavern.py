"""Private daily visit to the village tavern, stored in the farm aggregate."""
from hashlib import sha256
import math

from . import market, textile, village_effects, daily_bonus
from .catalog import ITEMS, RECIPES, level
from .domain import inventory, need, reachable


SCHEMAS = {
    'tavern_order': {'day', 'item'},
    'tavern_serve': {'day', 'cells'},
    'tavern_toast': {'day', 'toast'},
    'tavern_favorite': {'day', 'item'},
}
TOASTS = {'harvest', 'dill', 'foam'}


def dishes(farm):
    kitchens = {obj['type'] for obj in farm['objects']} & {'bakery', 'kitchen'}
    if not kitchens:
        return []
    products = set(reachable(farm))
    lv = level(farm['xp'])
    dishes = sorted({
        item for recipe in RECIPES.values()
        if recipe['building'] in kitchens and textile.recipe_level(farm, recipe) <= lv
        and recipe['inputs'].keys() <= products
        for item in recipe['outputs'] if not ITEMS[item].get('bound')
    })
    return dishes


def _offer(farm, day, slot=0):
    choices = dishes(farm)
    if not choices:
        return None
    seed = sha256((f'{farm["id"]}:tavern:{day}' + (f':{slot}' if slot else '')).encode()).hexdigest()[:16]
    item = choices[int(seed, 16) % len(choices)]
    # The same base price as a resident's one-item order, before reputation bonuses.
    base_coins = math.ceil(ITEMS[item]['price'] * 1.45) + 6
    return dict(item=item, qty=1, coins=base_coins * 4 // 5, done=False)


def _receipt(state, day, slot):
    receipt = state.get('orders', {}).get(f'{day}:{slot}')
    if receipt is None and slot == 0:
        receipt = state.get('order')
    return receipt if receipt and receipt['day'] == day else None


def projection(farm, now):
    day = market.moscow_day(now)
    state = farm.get('tavern', {})
    orders = []
    for slot in range(2 if village_effects.perk(farm, 'tavern', 2) else 1):
        receipt = _receipt(state, day, slot)
        order = dict(item=receipt['item'], qty=1, coins=receipt['coins'], done=True) if receipt else _offer(farm, day, slot)
        if order:
            orders.append(dict(order, slot=slot, id=f'{day}:{slot}'))
    toast = state.get('toast')
    return dict(day=day, order=({k: v for k,v in orders[0].items() if k not in ('slot','id')} if orders else None), orders=orders,
                dinner=village_effects.dinner(farm, day), favorite=state.get('favorite'),
                bonus_budget=daily_bonus.public(farm,now),
                dishes=[dict(id=k,name=ITEMS[k]['name']) for k in dishes(farm)],
                can_favorite=village_effects.perk(farm, 'tavern', 3),
                puzzle=dict(done=state.get('puzzle_day') == day, stamps=state.get('stamps', 0), variant=0),
                toast=toast['key'] if toast and toast['day'] == day else None)


def _serve(cells):
    need(isinstance(cells, list) and len(cells) == 6 and cells.count(None) == 3
         and all(cells.count(dish) == 1 for dish in ('pie', 'tea', 'pancake')),
         'tavern_puzzle', 'Поставь на поднос один пирог, один чай и одни оладьи.', 422)
    pie, tea, pancake = (cells.index(dish) for dish in ('pie', 'tea', 'pancake'))
    need(pie % 3 == 1, 'tavern_puzzle', 'Пух просит поставить пирог в середину ряда.', 422)
    need(tea == pie - 1, 'tavern_puzzle', 'Соня просит поставить чай сразу слева от пирога.', 422)
    need(pancake // 3 != pie // 3, 'tavern_puzzle', 'Олег просит поставить оладьи в другой ряд.', 422)


def command(farm, kind, data, now):
    fields = SCHEMAS[kind]
    need(isinstance(data, dict) and (data.keys() == fields or kind == 'tavern_order' and data.keys() == fields | {'slot'}) and type(data['day']) is int,
         'invalid_command', 'Некорректные параметры действия.', 422)
    day = market.moscow_day(now)
    need(data['day'] == day, 'tavern_stale_day', 'В трактире уже новый день. Открой его снова.')
    state = farm.get('tavern', {})
    if kind == 'tavern_order':
        item = data['item']
        need(isinstance(item, str) and item in ITEMS, 'invalid_command', 'Выбери блюдо из заказа.', 422)
        slot = data.get('slot', 0)
        need(type(slot) is int and 0 <= slot < (2 if village_effects.perk(farm, 'tavern', 2) else 1), 'invalid_command', 'Этот заказ недоступен.', 422)
        receipt = _receipt(state, day, slot)
        need(not receipt, 'tavern_order_done', 'Заказ на сегодня уже сдан.')
        order = _offer(farm, day, slot)
        need(order and order['item'] == item, 'tavern_order_changed', 'Заказ изменился. Открой трактир снова.')
        bonus = village_effects.dinner(farm, day)
        premium = bonus['amount'] if bonus['available'] else 0
        # A legacy daily receipt consumes the dinner quota without a retrospective award.
        if state.get('order', {}).get('day') == day and 'dinner' not in state:
            premium = 0
        coins = order['coins'] + premium
        need(farm['coins'] + coins <= 10 ** 12, 'tavern_balance_full', 'На счёте нет места для оплаты заказа.')
        inventory(farm, {item: order['qty']}, -1)
        if bonus['available']:
            premium = daily_bonus.grant(farm,'dinner',premium,now)
        farm['coins'] += order['coins']
        receipt = dict(day=day, item=item, coins=order['coins'], bonus=premium)
        state['orders'] = {key:value for key,value in state.get('orders',{}).items() if value.get('day') == day}
        state['orders'][f'{day}:{slot}'] = receipt
        if slot == 0:
            state['order'] = receipt
        if bonus['available']:
            budget = daily_bonus.public(farm,now)
            state['dinner'] = dict(day=day, paid=premium, income_ref=budget['ref'], cap=budget['cap'])
        notice = f'Трактир принял заказ. +{coins} монет.'
    elif kind == 'tavern_favorite':
        need(village_effects.perk(farm, 'tavern', 3), 'locked', 'Нужна ступень «Почётный строитель».')
        need(data['item'] in dishes(farm), 'invalid_command', 'Выбери доступное блюдо.', 422)
        state['favorite'] = data['item']
        notice = 'Любимое блюдо выбрано.'
    elif kind == 'tavern_serve':
        need(state.get('puzzle_day') != day, 'tavern_puzzle_done', 'Печать на сегодня уже получена.')
        _serve(data['cells'])
        state['puzzle_day'] = day
        state['stamps'] = state.get('stamps', 0) + 1
        notice = 'Печать «Поднос пережил смену» получена!'
    else:
        toast = data['toast']
        need(isinstance(toast, str) and toast in TOASTS, 'invalid_command', 'Выбери готовый тост.', 422)
        previous = state.get('toast')
        need(not previous or previous['day'] != day, 'tavern_toast_done', 'Тост на сегодня уже выбран.')
        state['toast'] = dict(day=day, key=toast)
        notice = 'Тост принят!'
    farm['tavern'] = state
    return notice
