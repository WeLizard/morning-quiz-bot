"""Cellar aging rules and safe settlement during account linking."""
from copy import deepcopy
from datetime import datetime

import pytest

from qw_farm import catalog, wine_aging
from qw_farm.domain import FarmError
from qw_farm.economy import DAY
from qw_farm.plantations import MOSCOW


def moscow(year, month, day):
    return int(datetime(year, month, day, tzinfo=MOSCOW).timestamp())


STARTED_AT = moscow(2026, 11, 1)
WINTER_START = moscow(2026, 12, 1)
WINTER_END = moscow(2027, 3, 1)
BATCH_ID = 'batch-first'


def farm(level=32, with_cellar=True, stock=4):
    objects = [{'id': 'cellar-id', 'type': 'cellar'}] if with_cellar else []
    return dict(xp=catalog.LEVELS[level - 1], objects=objects, coins=1200,
                inventory={'wine_zero': stock}, market={'rep': {'oleg': 10}})


def start(state, now=STARTED_AT, batch_id=BATCH_ID, object_id='cellar-id'):
    return wine_aging.apply(state, 'wine_age_start', {'object': object_id}, now, batch_id)


def collect(state, at, item, batch_id=BATCH_ID):
    return wine_aging.apply(state, 'wine_age_collect', {'batch': batch_id, 'item': item}, at, 'collect-key')


def fill_order(state, at, item):
    return wine_aging.apply(state, 'wine_age_order', {'item': item}, at, 'order-key')


def fails(code, action, state, *args):
    before = deepcopy(state)
    with pytest.raises(FarmError) as exc:
        action(state, *args)
    assert exc.value.code == code
    assert state == before


def test_pausing_new_batches_keeps_existing_batch_and_reserve_recipe(monkeypatch):
    state = farm()
    start(state)
    monkeypatch.setattr(catalog, 'WINE_AGING_STARTS_ENABLED', False)
    fails('wine_aging_paused', start, farm())
    at = STARTED_AT + 14 * DAY
    shelf = wine_aging.public(state, at)
    assert not shelf['can_start']
    assert shelf['batch']['item'] == 'wine_reserve'
    collect(state, at, 'wine_reserve')
    assert state['inventory']['wine_reserve'] == 2
    assert catalog.public_catalog()['recipes']['cellar_chest_reserve']['inputs']['wine_reserve'] == 1


def test_start_requires_l32_cellar_and_two_bottles_and_only_opens_one_batch():
    fails('locked', start, farm(level=31))
    fails('not_found', start, farm(with_cellar=False))
    wrong_building = farm(with_cellar=False)
    wrong_building['objects'].append(dict(id='cellar-id', type='barn'))
    fails('wrong_building', start, wrong_building)
    fails('missing_goods', start, farm(stock=1))

    state = farm()
    state['objects'].append(dict(id='other-cellar', type='cellar'))
    assert wine_aging.public(state, STARTED_AT)['batch'] is None
    assert 'wine_aging' not in state
    start(state, STARTED_AT + 0.9)
    assert state['wine_aging'] == {'batch': {'id': BATCH_ID, 'started_at': STARTED_AT}, 'label_at': None}
    assert state['inventory']['wine_zero'] == 2
    fails('wine_batch_busy', start, state, STARTED_AT, 'batch-other', 'other-cellar')
    wine_aging.validate(state)


@pytest.mark.parametrize(('elapsed', 'current', 'next_item', 'next_day'), [
    (0, 'wine_zero', 'wine_aged', 7),
    (7 * DAY - 1, 'wine_zero', 'wine_aged', 7),
    (7 * DAY, 'wine_aged', 'wine_reserve', 14),
    (14 * DAY - 1, 'wine_aged', 'wine_reserve', 14),
    (14 * DAY, 'wine_reserve', 'wine_collectors', 30),
    (30 * DAY - 1, 'wine_reserve', 'wine_collectors', 30),
    (30 * DAY, 'wine_collectors', None, None),
    (100 * DAY, 'wine_collectors', None, None),
])
def test_projection_and_collection_at_every_threshold(elapsed, current, next_item, next_day):
    state = farm(stock=2)
    before = state['coins']
    start(state)
    at = STARTED_AT + elapsed
    expected_next = None if next_day is None else STARTED_AT + next_day * DAY
    assert wine_aging.public(state, at)['batch'] == dict(
        id=BATCH_ID, started_at=STARTED_AT, item=current, next_item=next_item, next_at=expected_next)
    collect(state, at, current)
    assert state['inventory'][current] == 2
    assert state['coins'] == before
    assert state['wine_aging'] == {
        'batch': None, 'label_at': STARTED_AT if current == 'wine_collectors' else None}
    fails('stale_wine_batch', collect, state, at, current)


def test_stale_and_full_stock_fail_without_spending_and_first_label_stays():
    state = farm()
    start(state)
    at = STARTED_AT + 30 * DAY
    fails('stale_wine_batch', collect, state, at, 'wine_reserve')
    fails('stale_wine_batch', collect, state, at, 'wine_collectors', 'batch-other')
    state['inventory']['wine_collectors'] = 10**9 - 1
    fails('inventory_full', collect, state, at, 'wine_collectors')
    state['inventory']['wine_collectors'] = 0
    collect(state, at, 'wine_collectors')
    start(state, at, 'batch-second')
    collect(state, at + 30 * DAY, 'wine_collectors', 'batch-second')
    assert state['wine_aging']['label_at'] == STARTED_AT
    assert state['inventory']['wine_collectors'] == 4


def test_winter_order_uses_moscow_boundaries_and_requires_stock():
    state = farm()
    state['inventory']['wine_aged'] = 2
    expected = dict(item='wine_aged', name='К ужину у камина', quantity=2, coins=798)
    for at, offers in [(WINTER_START - 1, []), (WINTER_START, [expected]),
                       (WINTER_END - 1, [expected]), (WINTER_END, [])]:
        assert wine_aging.public(state, at)['orders'] == offers
    fails('wine_order_unavailable', fill_order, state, WINTER_END, 'wine_aged')
    fill_order(state, WINTER_END - 1, 'wine_aged')
    assert state['inventory']['wine_aged'] == 0
    assert state['coins'] == 1998
    assert state['market']['rep'] == {'oleg': 10}
    fails('missing_goods', fill_order, state, WINTER_END - 1, 'wine_aged')


def test_collectors_order_is_available_year_round_only_with_enough_stock():
    state = farm()
    state['inventory'].update(wine_collectors=1, wine_reserve=2)
    assert wine_aging.public(state, STARTED_AT)['orders'] == []
    fails('wine_order_unavailable', fill_order, state, STARTED_AT, 'wine_collectors')
    fails('wine_order_unavailable', fill_order, state, WINTER_START, 'wine_reserve')
    state['inventory']['wine_collectors'] = 2
    assert wine_aging.public(state, STARTED_AT)['orders'] == [
        dict(item='wine_collectors', name='Долгожитель', quantity=2, coins=798)]
    state['coins'] = 10**12 - 797
    fails('balance_full', fill_order, state, STARTED_AT, 'wine_collectors')
    state['coins'] = 1200
    fill_order(state, STARTED_AT, 'wine_collectors')
    assert state['inventory']['wine_collectors'] == 0
    assert state['coins'] == 1998
    assert state['market']['rep'] == {'oleg': 10}
    assert wine_aging.public(state, STARTED_AT)['orders'] == []


def test_merge_transfers_batch_and_earliest_labels_without_mutating_secondary():
    main, secondary = farm(), farm()
    start(secondary)
    main['wine_aging'] = dict(batch=None, label_at=STARTED_AT - DAY)
    secondary['wine_aging']['label_at'] = STARTED_AT - 2 * DAY
    before = deepcopy(secondary)
    assert wine_aging.merge(main, secondary, STARTED_AT + 30 * DAY) == {}
    assert main['wine_aging'] == before['wine_aging']
    assert main['wine_aging']['batch'] is not secondary['wine_aging']['batch']
    assert secondary == before


def test_merge_settles_secondary_when_primary_has_no_free_cellar():
    main, secondary = farm(), farm()
    start(main, STARTED_AT - 1, 'batch-primary')
    start(secondary)
    assert wine_aging.merge(main, secondary, STARTED_AT + 30 * DAY) == {'wine_collectors': 2}
    assert main['wine_aging'] == {
        'batch': {'id': 'batch-primary', 'started_at': STARTED_AT - 1}, 'label_at': STARTED_AT}
    assert main['coins'] == 1200
    assert main['inventory'] == {'wine_zero': 2}

    main = farm(with_cellar=False)
    assert wine_aging.merge(main, secondary, STARTED_AT + DAY) == {'wine_zero': 2}
    assert main['wine_aging'] == dict(batch=None, label_at=None)
    assert main['coins'] == 1200


@pytest.mark.parametrize('invalid', [
    None,
    {'batch': None},
    {'batch': None, 'label_at': False},
    {'batch': {'id': '', 'started_at': 10}, 'label_at': None},
    {'batch': {'id': 'batch-first', 'started_at': 10.5}, 'label_at': None},
    {'batch': {'id': 'batch-first', 'started_at': -1}, 'label_at': None},
])
def test_validates_optional_storage_shape(invalid):
    state = farm()
    wine_aging.validate(state)
    state['wine_aging'] = invalid
    fails('invalid_wine_aging', wine_aging.validate, state)
