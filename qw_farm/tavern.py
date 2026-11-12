"""Private daily visit to the village tavern, stored in the farm aggregate."""
from hashlib import sha256
import math

from . import market, textile
from .catalog import ITEMS, RECIPES, level
from .domain import inventory, need, reachable


SCHEMAS = {
    'tavern_order': {'day', 'item'},
    'tavern_serve': {'day', 'cells'},
    'tavern_toast': {'day', 'toast'},
}
TOASTS = {'harvest', 'dill', 'foam'}


def _offer(farm, day):
    kitchens = {obj['type'] for obj in farm['objects']} & {'bakery', 'kitchen'}
    if not kitchens:
        return None
    products = set(reachable(farm))
    lv = level(farm['xp'])
    dishes = sorted({
        item for recipe in RECIPES.values()
        if recipe['building'] in kitchens and textile.recipe_level(farm, recipe) <= lv
        and recipe['inputs'].keys() <= products
        for item in recipe['outputs'] if not ITEMS[item].get('bound')
    })
    if not dishes:
        return None
    seed = sha256(f'{farm["id"]}:tavern:{day}'.encode()).hexdigest()[:16]
    item = dishes[int(seed, 16) % len(dishes)]
    # The same base price as a resident's one-item order, before reputation bonuses.
    base_coins = math.ceil(ITEMS[item]['price'] * 1.45) + 6
    return dict(item=item, qty=1, coins=base_coins * 4 // 5, done=False)


def projection(farm, now):
    day = market.moscow_day(now)
    state = farm.get('tavern', {})
    receipt = state.get('order')
    order = (dict(item=receipt['item'], qty=1, coins=receipt['coins'], done=True)
             if receipt and receipt['day'] == day else _offer(farm, day))
    toast = state.get('toast')
    return dict(day=day, order=order,
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
    need(isinstance(data, dict) and data.keys() == SCHEMAS[kind] and type(data['day']) is int,
         'invalid_command', 'Некорректные параметры действия.', 422)
    day = market.moscow_day(now)
    need(data['day'] == day, 'tavern_stale_day', 'В трактире уже новый день. Открой его снова.')
    state = farm.get('tavern', {})
    if kind == 'tavern_order':
        item = data['item']
        need(isinstance(item, str) and item in ITEMS, 'invalid_command', 'Выбери блюдо из заказа.', 422)
        receipt = state.get('order')
        need(not receipt or receipt['day'] != day, 'tavern_order_done', 'Заказ на сегодня уже сдан.')
        order = _offer(farm, day)
        need(order and order['item'] == item, 'tavern_order_changed', 'Заказ изменился. Открой трактир снова.')
        coins = order['coins']
        need(farm['coins'] + coins <= 10 ** 12, 'tavern_balance_full', 'На счёте нет места для оплаты заказа.')
        inventory(farm, {item: order['qty']}, -1)
        farm['coins'] += coins
        state['order'] = dict(day=day, item=item, coins=coins)
        notice = f'Трактир принял заказ. +{coins} монет.'
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
