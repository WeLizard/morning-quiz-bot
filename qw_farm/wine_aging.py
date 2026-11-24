"""Cellar batches and their fixed-price orders, evaluated at server time."""
from . import catalog
from .catalog import ITEMS, level, tick
from .domain import find, inventory, need
from .economy import DAY
from .plantations import winter_window


KEY = 'wine_aging'
LEVEL = 32
QUANTITY = 2
ORDER_COINS = 798
BASE_ITEM = 'wine_zero'
COLLECTOR_ITEM = 'wine_collectors'
STAGES = ((7, 'wine_aged'), (14, 'wine_reserve'), (30, COLLECTOR_ITEM))
SCHEMAS = {
    'wine_age_start': {'object'},
    'wine_age_collect': {'batch', 'item'},
    'wine_age_order': {'item'},
}


def _state(farm):
    return farm.get(KEY) or dict(batch=None, label_at=None)


def _has_cellar(farm):
    return any(obj['type'] == 'cellar' for obj in farm['objects'])


def _batch_quote(batch, now):
    item = BASE_ITEM
    for days, next_item in STAGES:
        next_at = batch['started_at'] + days * DAY
        if now < next_at:
            return dict(batch, item=item, next_item=next_item, next_at=next_at)
        item = next_item
    return dict(batch, item=item, next_item=None, next_at=None)


def _orders(farm, now):
    winter_start, winter_end = winter_window(now)
    if winter_start <= now < winter_end:
        yield dict(item='wine_aged', name='К ужину у камина', quantity=QUANTITY, coins=ORDER_COINS)
    if farm['inventory'].get(COLLECTOR_ITEM, 0) >= QUANTITY:
        yield dict(item=COLLECTOR_ITEM, name='Долгожитель', quantity=QUANTITY, coins=ORDER_COINS)


def public(farm, now):
    state = _state(farm)
    batch = state['batch']
    can_start = catalog.WINE_AGING_STARTS_ENABLED and level(farm['xp']) >= LEVEL and _has_cellar(farm)
    has_stock = any(farm['inventory'].get(item, 0) for _, item in STAGES)
    if not (can_start or batch or state['label_at'] is not None or has_stock):
        return None
    return dict(batch=_batch_quote(batch, now) if batch else None, label_at=state['label_at'],
                can_start=can_start, orders=list(_orders(farm, now)))


def apply(farm, kind, data, now, command_id):
    state = _state(farm)
    if kind == 'wine_age_start':
        need(catalog.WINE_AGING_STARTS_ENABLED, 'wine_aging_paused', 'Новые партии выдержки пока недоступны.')
        need(level(farm['xp']) >= LEVEL, 'locked', f'Выдержка вина открывается с уровня {LEVEL}.')
        cellar = find(farm['objects'], data['object'])
        need(cellar['type'] == 'cellar', 'wrong_building', 'Для выдержки вина нужен погребок.')
        need(state['batch'] is None, 'wine_batch_busy', 'В погребке уже выдерживается партия.')
        inventory(farm, {BASE_ITEM: QUANTITY}, -1)
        farm[KEY] = dict(state, batch=dict(id=command_id, started_at=tick(now)))
        return 'Партия поставлена на выдержку.'

    if kind == 'wine_age_collect':
        batch = state['batch']
        need(batch is not None and batch['id'] == data['batch'],
             'stale_wine_batch', 'Партия изменилась. Обнови ферму.')
        item = _batch_quote(batch, now)['item']
        need(item == data['item'], 'stale_wine_batch', 'Выдержка изменилась. Обнови ферму.')
        need(farm['inventory'].get(item, 0) + QUANTITY <= 10**9,
             'inventory_full', 'На складе нет места для вина.')
        inventory(farm, {item: QUANTITY})
        label_at = state['label_at']
        if item == COLLECTOR_ITEM and label_at is None:
            label_at = batch['started_at']
        farm[KEY] = dict(batch=None, label_at=label_at)
        return f'На склад: {ITEMS[item]["name"]} ×{QUANTITY}.'

    need(kind == 'wine_age_order', 'unknown_command', 'Неизвестное действие.', 422)
    order = next((entry for entry in _orders(farm, now) if entry['item'] == data['item']), None)
    need(order is not None, 'wine_order_unavailable', 'Этот заказ сейчас недоступен.')
    need(farm['coins'] + order['coins'] <= 10**12, 'balance_full', 'На счёте нет места для оплаты.')
    inventory(farm, {order['item']: order['quantity']}, -1)
    farm['coins'] += order['coins']
    return f'Заказ «{order["name"]}» выполнен. Получено монет: {order["coins"]}.'


def validate(farm):
    """Validate the optional aggregate field. Older farms have no batch or label."""
    if KEY not in farm:
        return
    state = farm[KEY]
    need(type(state) is dict and set(state) == {'batch', 'label_at'},
         'invalid_wine_aging', 'Некорректное состояние выдержки вина.', 500)
    batch, label_at = state['batch'], state['label_at']
    need((label_at is None or type(label_at) is int and label_at >= 0)
         and (batch is None or type(batch) is dict and set(batch) == {'id', 'started_at'}
              and type(batch['id']) is str and 0 < len(batch['id']) <= 64
              and type(batch['started_at']) is int and batch['started_at'] >= 0),
         'invalid_wine_aging', 'Некорректное состояние выдержки вина.', 500)


def merge(main, secondary, now):
    """Merge progress and return any second batch that must be added to inventory."""
    if KEY not in secondary:
        return {}
    primary, other = _state(main), _state(secondary)
    batch, overflow = primary['batch'], {}
    labels = [at for at in (primary['label_at'], other['label_at']) if at is not None]
    if other['batch'] is not None:
        if batch is None and _has_cellar(main):
            batch = dict(other['batch'])
        else:
            item = _batch_quote(other['batch'], now)['item']
            overflow[item] = QUANTITY
            if item == COLLECTOR_ITEM:
                labels.append(other['batch']['started_at'])
    main[KEY] = dict(batch=batch, label_at=min(labels, default=None))
    return overflow
