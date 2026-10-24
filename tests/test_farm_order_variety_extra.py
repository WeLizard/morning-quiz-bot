"""Signature share, empty-candidate fallback and order_recent validation for farm orders."""
from __future__ import annotations

import pytest

from qw_farm import domain
from qw_farm.catalog import NPC_SIGNATURE, NPCS
from qw_farm.domain import FarmError, make_order, new_farm, validate_state

NOW = 1_800_000_000
POOL = ['wheat', 'carrot', 'flour', 'egg', 'corn', 'honey', 'berry_charge', 'honey_charge', 'forest_charge',
        'pillow', 'scarf', 'mittens', 'wool_plaid', 'quilt', 'sunflower', 'pumpkin', 'oat_cookie', 'porridge']


def _run(monkeypatch, npc, total):
    from qw_farm.catalog import ITEMS
    pool = [i for i in POOL if i in ITEMS]
    monkeypatch.setattr(domain, 'reachable', lambda farm: list(pool))
    farm = new_farm('share-farm', 'T', NOW)
    hits = seen = 0
    sig = set(NPC_SIGNATURE[npc])
    for n in range(total):
        slot = n % 3
        order = make_order(farm, slot, NOW)
        farm['orders'][slot] = order
        if order['id'] != f'order_{farm["order_seq"] - 1}':
            raise AssertionError('order id mismatch')
        if order['npc'] == npc and int(order['id'].split('_')[1]) > 2 and not order.get('special'):
            seen += 1
            hits += set(order['needs']) <= sig
        names = [o['npc'] for o in farm['orders']]
        items = [i for o in farm['orders'] for i in o['needs']]
        assert len(items) == len(set(items)), 'duplicate item among active orders'
        assert all(names.count(x) <= 2 for x in names)
    return hits, seen


def test_pukh_signature_share_holds_despite_cooldown(monkeypatch):
    hits, seen = _run(monkeypatch, 'Медведь Пух', 7000)
    assert seen >= 400
    assert 0.65 <= hits / seen <= 0.75, (hits, seen)


def test_sonya_signature_share_uses_its_own_percentage(monkeypatch):
    hits, seen = _run(monkeypatch, 'Кошка Соня', 7000)
    assert seen >= 400
    assert 0.45 <= hits / seen <= 0.55, (hits, seen)


def test_tiny_farm_every_item_taken_never_crashes(monkeypatch):
    monkeypatch.setattr(domain, 'reachable', lambda farm: ['wheat', 'carrot'])
    farm = new_farm('tiny', 'T', NOW)
    for n in range(300):
        slot = n % 3
        farm['orders'][slot] = make_order(farm, slot, NOW)
        assert farm['orders'][slot]['needs']


def test_real_demolished_level_one_farm(monkeypatch):
    farm = new_farm('demolished', 'T', NOW)
    farm['objects'] = [o for o in farm['objects'] if o['type'] == 'plot'][:1]
    for n in range(200):
        slot = n % 3
        farm['orders'][slot] = make_order(farm, slot, NOW)
    validate_state(farm)


def test_no_goods_at_all_is_a_clean_error(monkeypatch):
    base = new_farm('none', 'T', NOW)
    monkeypatch.setattr(domain, 'reachable', lambda farm: [])
    with pytest.raises(FarmError):
        make_order(base, 0, NOW)


@pytest.mark.parametrize('bad', [[], 'x', {'Медведь Пух': 'x'}, {'Медведь Пух': [['nope']]}, {'Медведь Пух': [['wheat']] * 5}, {1: []}, {'Медведь Пух': [[1]]}])
def test_validate_rejects_bad_order_recent(bad):
    farm = new_farm('v', 'T', NOW)
    farm['order_recent'] = bad
    with pytest.raises(FarmError):
        validate_state(farm)


def test_validate_accepts_good_order_recent():
    farm = new_farm('v2', 'T', NOW)
    validate_state(farm)
