"""Regression coverage for farm order rotation and old-save history migration."""
from __future__ import annotations

from copy import deepcopy

import pytest

from qw_farm.catalog import NPC_SIGNATURE, NPC_TASTES, NPCS, REP_POINTS
from qw_farm.domain import make_order, new_farm, reachable
from qw_farm.expansion import upgrade_state
from qw_farm.persistence import unpack


def _legacy_row():
    """A synthetic old-format farm row."""
    state = new_farm("00000000-0000-4000-8000-0000000000aa", "Test", 1_800_000_000)
    return {
        "id": state["id"],
        "name": state["name"],
        "coins": state["coins"],
        "xp": state["xp"],
        "revision": state["revision"],
        "payload": {k: deepcopy(v) for k, v in state.items() if k not in {"id", "name", "coins", "xp", "revision"}},
    }


def _item_ids(order):
    return set(order.get("needs", {}))


def _expected_history(row):
    expected = {}
    orders = sorted(
        row["payload"].get("orders", []),
        key=lambda item: int(item["id"].rsplit("_", 1)[-1]),
    )
    for order in orders:
        expected.setdefault(order["npc"], []).append(list(order.get("needs", {})))
    return {npc: entries[-4:] for npc, entries in expected.items()}


def _sequence(row):
    original = deepcopy(row)
    state = unpack(row)
    assert row == original, "unpack modified its input row"
    return state


@pytest.fixture
def legacy_order_row():
    """Small old-format row, deliberately unsorted to catch lexicographic order sorting."""
    return {
        "id": "00000000-0000-0000-0000-000000000010",
        "name": "Legacy fixture",
        "coins": 0,
        "xp": 0,
        "revision": 0,
        "payload": {
            "orders": [
                {"id": "order_10", "npc": "resident_a", "needs": {"item_c": 1}},
                {"id": "order_8", "npc": "resident_a", "needs": {"item_a": 1}},
                {"id": "order_9", "npc": "resident_a", "needs": {"item_b": 1}},
            ]
        },
    }


def test_old_save_without_history_migrates_orders_in_numeric_id_order(legacy_order_row):
    state = unpack(legacy_order_row)

    assert state.get("order_recent") == {
        "resident_a": [["item_a"], ["item_b"], ["item_c"]]
    }
    assert "order_recent" not in legacy_order_row["payload"]


def test_thirty_future_order_replacements_preserve_variety_invariants():
    row = _legacy_row()
    state = _sequence(row)
    state = upgrade_state(state, 1_800_000_000)
    state["market"]["rep"] = {npc: REP_POINTS[-1] for npc, _ in NPCS}
    if len(state.get("orders", [])) != 3:
        state["orders"] = [make_order(state, slot, 1_800_000_000) for slot in range(3)]

    seen_special = 0
    for index in range(30):
        slot = index % 3
        history_before = deepcopy(state.get("order_recent", {}))
        new = make_order(state, slot, 1_800_000_000 + index)
        state["orders"][slot] = new

        active = state["orders"]
        assert sum(bool(order.get("special")) for order in active) <= 1
        assert max((sum(order["npc"] == npc for order in active) for npc, _ in NPCS), default=0) <= 2
        for left in range(len(active)):
            for right in range(left + 1, len(active)):
                assert not (_item_ids(active[left]) & _item_ids(active[right]))

        npc_history = history_before.get(new["npc"], [])
        recent_items = {item for needs in npc_history[-4:] for item in needs}
        # Signature items are exempt from the per-resident cooldown (they keep their designed share).
        assert not ((_item_ids(new) - set(NPC_SIGNATURE.get(new["npc"], ()))) & recent_items)

        if new.get("special"):
            seen_special += 1
            assert _item_ids(new) <= set(NPC_TASTES[new["npc"]])

    assert seen_special > 0


def test_sonya_sometimes_gets_a_signature_item():
    state = upgrade_state(_sequence(_legacy_row()), 1_800_000_000)
    state["market"]["rep"] = {npc: REP_POINTS[-1] for npc, _ in NPCS}
    sonya_signature = set(NPC_SIGNATURE["Кошка Соня"]) & set(reachable(state))
    if not sonya_signature:
        pytest.skip("The available farm progression cannot reach the resident's signature items")
    if len(state.get("orders", [])) != 3:
        state["orders"] = [make_order(state, slot, 1_800_000_000) for slot in range(3)]

    found = False
    # A longer deterministic sequence accommodates the resident's share and signature cooldown.
    for index in range(120):
        slot = index % 3
        order = make_order(state, slot, 1_800_000_000 + index)
        state["orders"][slot] = order
        if order["npc"] == "Кошка Соня" and (_item_ids(order) & sonya_signature):
            found = True
            break

    assert found


def test_conditional_fallback_for_demolished_level_one_farm_with_saturated_history():
    state = new_farm("00000000-0000-0000-0000-000000000111", "Test", 1_800_000_000)
    state["objects"] = [obj for obj in state["objects"] if obj["type"] in {"house", "barn", "plot"}]
    products = set(reachable(state))
    active_orders = deepcopy(state["orders"][:2])
    occupied = {item for order in active_orders for item in order["needs"]}
    cooling_goods = sorted(products - occupied)
    assert len(cooling_goods) <= 8
    one_resident_history = [cooling_goods[index:index + 2] for index in range(0, len(cooling_goods), 2)]
    one_resident_history.extend([[]] * (4 - len(one_resident_history)))
    state["orders"] = active_orders
    state["order_recent"] = {npc: deepcopy(one_resident_history) for npc, _ in NPCS}

    # Four plausible historical orders cover every reachable good outside the two active slots.
    assert len(state["orders"]) == 2
    assert all(len(entries) == 4 and all(len(order_items) <= 2 for order_items in entries)
               for entries in state["order_recent"].values())
    assert all(set(cooling_goods) <= {item for order_items in entries for item in order_items}
               for entries in state["order_recent"].values())

    history_before = deepcopy(state["order_recent"])
    new = make_order(state, 2, 1_800_000_100)
    state["orders"].append(new)
    active = state["orders"]

    new_items = _item_ids(new)
    assert new_items <= products
    assert not (new_items & occupied)
    assert new_items & {
        item for order_items in history_before[new["npc"]][-4:] for item in order_items
    }
    assert sum(bool(order.get("special")) for order in active) <= 1
    assert max(sum(order["npc"] == npc for order in active) for npc, _ in NPCS) <= 2


def test_order_sequence_is_deterministic_from_the_same_legacy_state():
    state = upgrade_state(_sequence(_legacy_row()), 1_800_000_000)
    clone = deepcopy(state)
    first = []
    second = []
    for index in range(30):
        slot = index % 3
        first_order = make_order(state, slot, 1_800_000_000 + index)
        second_order = make_order(clone, slot, 1_800_000_000 + index)
        state["orders"][slot] = first_order
        clone["orders"][slot] = second_order
        first.append(first_order)
        second.append(second_order)
    assert first == second
