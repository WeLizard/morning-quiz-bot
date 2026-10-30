"""Owner-specific merchant draws, secret configuration, restock and old-save compatibility."""
from collections import Counter
from copy import deepcopy
import importlib
import json
from uuid import UUID

import pytest

from qw_farm import construction, economy, merchant as M
from qw_farm.catalog import CURIOS, LEVELS, MERCHANT
from qw_farm.domain import FarmError, apply, new_farm, validate_state
from qw_farm.expansion import upgrade_state


@pytest.fixture(autouse=True)
def stable_secret(monkeypatch):
    monkeypatch.setenv('QW_FARM_MERCHANT_SECRET', 'v2-test-secret-that-is-at-least-32-characters')


DAY = next(d for d in range(M.ANCHOR + 1, M.ANCHOR + 20) if M.visit_on(d))
VISIT = M.visit_on(DAY)
OPEN = VISIT['opens_at']
SUPPLY = OPEN + M.RESTOCK


def farm(number=1):
    f = upgrade_state(new_farm(str(UUID(int=number)), 'V2', OPEN))
    f.update(xp=LEVELS[29], coins=10 ** 8, starter_credit=0, inventory={})
    f['progress'].update(day=10 ** 9, dew=10 ** 9)
    economy.state(f)['billed_day'] = 10 ** 9
    return f


def purchase(f, slot, qty=1, at=OPEN, token=None):
    token = token or M.owner_view(f, at)['visit_id']
    return apply(f, f, 'merchant_buy', dict(visit_id=token, slot=slot, qty=qty), at,
                 f'buy-{at}-{len(f["events"])}')


def ids(slots):
    return {s['id'] for s in slots}


def test_stock_is_per_farm_pure_and_stable_after_restart():
    f, other = farm(), farm(2)
    before = deepcopy(f)
    slots = M.stock(VISIT, f, OPEN)
    assert slots == M.stock(VISIT, f, OPEN + 60)
    assert f == before
    assert len(slots) == len(ids(slots)) == 6
    assert slots[0]['cheap'] and slots[0]['kind'] == 'exotic_seed'
    assert all(not e['cheap'] for e in slots[1:])
    assert ids(slots) != ids(M.stock(VISIT, other, OPEN))
    importlib.reload(M)
    assert M.stock(VISIT, f, OPEN) == slots


def test_weighted_rarity_distribution_and_one_lottery_per_visit():
    counts, fresh_counts, lotteries = Counter(), Counter(), 0
    for n in range(1, 1201):
        slots = M.stock(VISIT, farm(n), OPEN)[1:]
        counts.update(s['rarity'] for s in slots)
        fresh = M._v2_initial(M.stock_secret(), str(UUID(int=n)), DAY, [], set())[1:]
        fresh_counts.update(s['rarity'] for s in fresh if s['rarity'] != 'lot_day')
        lots = [s for s in slots if s['rarity'] == 'lot_day']
        assert len(lots) <= 1
        lotteries += bool(lots)
    assert counts['common'] > counts['uncommon'] > counts['rare'] > 0
    assert .20 < lotteries / 1200 < .30
    total = sum(fresh_counts.values())
    for rarity, weight in MERCHANT['rarity_weights'].items():
        assert abs(fresh_counts[rarity] / total - weight / 100) < .04, fresh_counts


def test_lot_day_only_offers_missing_past_series_and_is_stable_after_purchase():
    f = next(farm(n) for n in range(1, 100) if any(s['rarity'] == 'lot_day' for s in M.stock(VISIT, farm(n), OPEN)))
    lot = next(s for s in M.stock(VISIT, f, OPEN) if s['rarity'] == 'lot_day')
    assert lot['series'] != M.series_of(DAY)
    f['merchant']['curios'] = [c for c in CURIOS if CURIOS[c]['series'] != M.series_of(DAY) and c != lot['id']]
    slots = M.stock(VISIT, f, OPEN)
    lot = next(s for s in slots if s['rarity'] == 'lot_day')
    assert lot['id'] not in f['merchant']['curios']
    purchase(f, lot['slot'])
    assert M.stock(VISIT, f, OPEN) == slots
    assert lot['id'] in f['merchant']['curios']
    assert next(s for s in M.owner_view(f, OPEN)['slots'] if s['slot'] == lot['slot'])['status'] == 'owned'
    g = farm(99)
    g['merchant']['curios'] = list(CURIOS)
    assert all(s['rarity'] != 'lot_day' for s in M.stock(VISIT, g, OPEN))


def test_restock_exact_boundary_replaces_three_and_projection_does_not_mutate():
    f = farm()
    before = deepcopy(f)
    first = M.stock(VISIT, f, OPEN)
    assert first == M.stock(VISIT, f, SUPPLY - 1)
    second = M.stock(VISIT, f, SUPPLY)
    assert second[0] == first[0]
    assert sum(a['id'] != b['id'] for a, b in zip(first, second)) == 3
    assert len(ids(second)) == 6
    assert not (ids(second) - ids(first)) & ids(first)
    view = M.owner_view(f, SUPPLY - 1)
    assert view['next_restock_at'] == SUPPLY and view['visit_id'] == VISIT['visit_id'] + ':h1'
    view = M.owner_view(f, SUPPLY)
    assert view['next_restock_at'] is None and view['visit_id'] == VISIT['visit_id'] + ':h2'
    assert all(s['rarity'] in ('common', 'uncommon', 'rare', 'lot_day') for s in view['slots'])
    assert f == before


def test_stale_first_half_command_cannot_buy_replacement():
    f = farm()
    before = deepcopy(f)
    with pytest.raises(FarmError) as exc:
        purchase(f, 1, at=SUPPLY, token=VISIT['visit_id'] + ':h1')
    assert exc.value.code == 'stale_visit' and f == before


def test_unrecorded_legacy_token_cannot_buy_new_v2_assortment_at_rollout():
    f = farm()
    before = deepcopy(f)
    with pytest.raises(FarmError) as exc:
        purchase(f, 0, at=OPEN, token=VISIT['visit_id'])
    assert exc.value.code == 'stale_visit' and f == before
    purchase(f, 0, at=OPEN, token=VISIT['visit_id'] + ':h1')
    assert f['merchant']['bought'] == {'0': 1}


def test_sold_out_slots_and_bought_inventory_survive_restock_and_late_purchases():
    f = farm()
    first = M.stock(VISIT, f, OPEN)
    # Starter inventory and its visit-wide per-item counter survive the supply.
    purchase(f, 0, qty=1)
    retained_inventory = dict(f['inventory'])
    target = next(s for s in first[1:] if s['kind'] not in ('graft', 'scroll', 'curio'))
    purchase(f, target['slot'], qty=target['limit'])
    f = json.loads(json.dumps(f))
    importlib.reload(M)
    second = M.stock(VISIT, f, SUPPLY)
    assert second[target['slot']]['id'] == target['id']
    assert all(f['inventory'][k] >= v for k, v in retained_inventory.items())
    assert sum(a['id'] != b['id'] for a, b in zip(first, second)) == 3
    purchase(f, 0, at=SUPPLY)
    assert M.stock(VISIT, f, SUPPLY) == second
    before = deepcopy(f)
    with pytest.raises(FarmError) as exc:
        purchase(f, 0, at=SUPPLY)
    assert exc.value.code == 'limit_reached' and f == before
    assert f['merchant']['stock_v2']['purchased'][first[0]['id']] == 2
    validate_state(f)


def test_supply_replaces_only_remaining_places_and_respects_extra_and_unique_ownership(monkeypatch):
    from qw_farm import orchard
    monkeypatch.setattr(orchard, 'can_buy_graft', lambda *args: True)
    monkeypatch.setattr(construction, 'merchant_extra', lambda *args: 2)
    f = farm()
    first = M.stock(VISIT, f, OPEN)
    for s in first[1:5]:
        quantity = 1 if s['kind'] in ('scroll', 'curio') else s['limit'] + 2
        purchase(f, s['slot'], qty=quantity)
    second = M.stock(VISIT, f, SUPPLY)
    assert [s['id'] for s in first[:5]] == [s['id'] for s in second[:5]]
    assert first[5]['id'] != second[5]['id']
    assert f['merchant']['stock_v2']['first_full'] == [1, 2, 3, 4]
    # Completely sell the last place too: zero available replacements.
    s = first[5]
    purchase(f, 5, qty=1 if s['kind'] in ('scroll', 'curio') else s['limit'] + 2)
    assert M.stock(VISIT, f, SUPPLY) == first


def test_new_item_in_partly_bought_place_gets_its_own_limit():
    f, target, replacement = None, None, None
    for n in range(1, 100):
        candidate = farm(n)
        first, second = M.stock(VISIT, candidate, OPEN), M.stock(VISIT, candidate, SUPPLY)
        target = next((s for s in first[1:] if s['kind'] == 'dye' and s['id'] != second[s['slot']]['id']
                       and second[s['slot']]['kind'] != 'graft'), None)
        if target:
            f, replacement = candidate, second[target['slot']]
            break
    assert f is not None
    purchase(f, target['slot'])
    purchase(f, replacement['slot'], qty=replacement['limit'], at=SUPPLY)
    metadata = f['merchant']['stock_v2']
    assert metadata['purchased'][target['id']] == 1
    assert metadata['purchased'][replacement['id']] == replacement['limit']
    assert f['merchant']['bought'][str(target['slot'])] == 1 + replacement['limit']
    assert M.stock(VISIT, f, SUPPLY)[target['slot']]['id'] == replacement['id']
    validate_state(f)


def test_command_history_is_used_across_read_only_visits():
    # Pin a place the no-purchase replay would replace, so actual A differs from a hypothetical A.
    f = next(farm(n) for n in range(1, 100) if any(s['kind'] != 'graft' and s['id'] not in ids(M.stock(VISIT, farm(n), SUPPLY))
                                                for s in M.stock(VISIT, farm(n), OPEN)[1:]))
    first = M.stock(VISIT, f, OPEN)
    target = next(s for s in first[1:] if s['kind'] != 'graft' and s['id'] not in ids(M.stock(VISIT, f, SUPPLY)))
    purchase(f, target['slot'], qty=1 if target['kind'] in ('scroll', 'curio') else target['limit'])
    b = M.next_visit(OPEN)
    c = M.next_visit(b['opens_at'])
    before = deepcopy(f)
    M.owner_view(f, b['opens_at'])
    b_ids = ids(M.stock(b, f, b['opens_at'])) | ids(M.stock(b, f, b['closes_at'] - 1))
    context_c = M._stock_context(f, c)
    assert set(context_c['previous']) == b_ids
    assert not b_ids & ids(M.stock(c, f, c['opens_at']))
    assert f == before


def test_v2_fair_and_buyback_keep_existing_schedule_prices_and_counters():
    from qw_farm.catalog import ITEMS
    fair = next(M.visit_on(d) for d in range(DAY, DAY + 370) if M.visit_on(d) and M.visit_on(d)['kind'] == 'fair')
    at = fair['opens_at']
    f = farm()
    view = M.owner_view(f, at)
    assert view['fair'] and view['kind'] == 'fair' and view['base_visit_id'] == fair['visit_id']
    assert len(view['slots']) == 6
    purchase(f, 0, at=at)
    item = M.wants_for(f, fair)
    f['inventory'][item] = 1
    coins = f['coins']
    apply(f, f, 'merchant_sell', dict(visit_id=fair['visit_id'], item=item, qty=1), at + M.RESTOCK, 'v2-fair-sell')
    assert f['coins'] == coins + ITEMS[item]['price'] * 130 // 100
    assert f['merchant']['sold_value'] == ITEMS[item]['price']
    assert f['merchant']['stock_v2']['purchased']
    validate_state(f)


def test_owner_teaser_is_neutral_and_does_not_promise_goods_that_history_can_change():
    f = farm()
    nxt = M.next_visit(OPEN)
    at = nxt['opens_at'] - 1
    before = deepcopy(f)
    assert M.owner_view(f, at)['teaser'] == 'Сорока готовит новый привоз.'
    assert M.public(at)['slots'] == []
    assert M.public(at)['teaser'] == 'Сорока готовит новый привоз.'
    assert f == before


def test_partial_purchase_can_be_replaced_without_losing_history_or_goods():
    f = next(farm(n) for n in range(1, 100) if any(s['kind'] == 'dye' and s['id'] not in ids(M.stock(VISIT, farm(n), SUPPLY))
                                                for s in M.stock(VISIT, farm(n), OPEN)))
    first = M.stock(VISIT, f, OPEN)
    target = next(s for s in first if s['kind'] == 'dye' and s['id'] not in ids(M.stock(VISIT, f, SUPPLY)))
    purchase(f, target['slot'], 1)
    assert target['id'] not in ids(M.stock(VISIT, f, SUPPLY))
    assert f['inventory'][target['item']] == 1
    assert f['merchant']['stock_v2']['purchased'][target['id']] == 1
    assert f['merchant']['bought'][str(target['slot'])] == 1
    validate_state(f)


def test_previous_visit_excludes_both_halves_with_and_without_persistent_history():
    f = farm()
    all_previous = ids(M.stock(VISIT, f, OPEN)) | ids(M.stock(VISIT, f, SUPPLY))
    later = M.next_visit(OPEN)
    assert not all_previous & ids(M.stock(later, f, later['opens_at']))
    purchase(f, 0)
    all_previous = ids(M.stock(VISIT, f, OPEN)) | ids(M.stock(VISIT, f, SUPPLY))
    assert not all_previous & ids(M.stock(later, f, later['opens_at']))
    # Entering the next visit persists exactly the prior offers, not a new hypothetical draw.
    purchase(f, 0, at=later['opens_at'])
    assert set(f['merchant']['stock_v2']['previous']) == all_previous
    assert f['merchant']['bought'] == {'0': 1}
    validate_state(f)


def test_legacy_save_finishes_current_visit_without_reindexing_or_restock():
    f = farm()
    f['merchant'].update(visit_id=VISIT['visit_id'], bought={'0': 1}, sold_value=7)
    before = deepcopy(f)
    assert M.stock(VISIT, f, OPEN) == M.stock(VISIT, f, SUPPLY)
    assert ids(M.stock(VISIT, f, SUPPLY)) == ids(M.stock(VISIT))
    view = M.owner_view(f, SUPPLY)
    assert view['next_restock_at'] is None and view['visit_id'] == VISIT['visit_id']
    assert f == before
    purchase(f, 0, at=SUPPLY)
    assert f['merchant']['bought'] == {'0': 2} and f['merchant']['sold_value'] == 7
    assert 'stock_v2' not in f['merchant']
    validate_state(f)


def test_server_secret_changes_draw_and_never_enters_projection(monkeypatch):
    f = farm()
    before = M.stock(VISIT, f, OPEN)
    view = M.owner_view(f, OPEN)
    public_inputs = (f['id'], VISIT['visit_id'], VISIT['opens_at'])
    secret = 'another-server-secret-at-least-32-characters'
    monkeypatch.setenv('QW_FARM_MERCHANT_SECRET', secret)
    assert M.stock(VISIT, f, OPEN) != before
    assert public_inputs == (f['id'], VISIT['visit_id'], VISIT['opens_at'])
    assert secret not in str(view) and 'secret' not in str(view).lower()


def test_secret_is_stable_fallback_derived_and_missing_or_short_fails_closed(monkeypatch):
    for name in ('QW_FARM_MERCHANT_SECRET', 'QW_FARM_INVITE_SECRET', 'BOT_TOKEN'):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(RuntimeError, match='Configure'):
        M.stock(VISIT, farm(), OPEN)
    monkeypatch.setenv('BOT_TOKEN', 'stable-bot-token-which-is-32-characters')
    first = M.stock_secret()
    importlib.reload(M)
    assert M.stock_secret() == first
    monkeypatch.setenv('QW_FARM_INVITE_SECRET', 'a-different-stable-invite-secret-32-characters')
    assert M.stock_secret() != first
    monkeypatch.setenv('QW_FARM_MERCHANT_SECRET', 'too-short')
    with pytest.raises(RuntimeError, match='at least 32'):
        M.stock_secret()


@pytest.mark.parametrize('update', [dict(first_full=[True]), dict(purchased={'unknown': 1}), dict(owned=['unknown']), dict(previous=['unknown'])])
def test_v2_metadata_validation(update):
    f = farm()
    purchase(f, 0)
    f['merchant']['stock_v2'].update(update)
    with pytest.raises(FarmError) as exc:
        validate_state(f)
    assert exc.value.code == 'invalid_merchant'
