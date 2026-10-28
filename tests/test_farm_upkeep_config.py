"""Configurable farm upkeep keeps old rules until the next Moscow billing day."""
import pytest

from qw_farm import catalog, economy, fields
from qw_farm.upkeep_config import (
    defaults, effective_values, land_plot_rate, moscow_day, public_state,
    settings_for, updated_payload, validate_values,
)


def test_defaults_match_existing_catalog_and_rates_are_independently_applied():
    config = defaults()
    assert config == {
        'upkeep_level': catalog.UPKEEP_LEVEL,
        'land_rate_pct': 100,
        'building_rate_pct': 1,
        'field_per_hectare': catalog.FIELD_UPKEEP,
        'tree_rate_per_extra_tree': catalog.TREE_RENT_STEP,
    }

    farm = {
        'size': 16,
        'objects': [
            {'id': 'p', 'type': 'plot'},
            {'id': 'kitchen', 'type': 'kitchen', 'level': 1},
            *({'id': f'tree-{index}', 'type': 'tree', 'planted_at': index}
              for index in range(13)),
        ],
        'fields': [{'ha': 2}],
    }
    assert economy.base_upkeep(farm) == economy.base_upkeep(farm, config)

    changed = {**config, 'land_rate_pct': 200, 'building_rate_pct': 3,
               'field_per_hectare': 25, 'tree_rate_per_extra_tree': 7}
    assert land_plot_rate(16, changed) == 20
    expected = 20 + 13 * 20 + sum(range(1, 11)) * 7 + 8 + 50  # bed, orchard tiers, kitchen, 2 ha
    assert economy.base_upkeep(farm, changed) == expected


def test_pending_rate_change_does_not_recalculate_existing_debt_or_todays_bill():
    farm = {
        'size': 8, 'xp': catalog.LEVELS[9], 'coins': 0, 'starter_credit': 0,
        'objects': [], 'fields': [],
        'economy': {'billed_day': 20_000, 'debt': 73},
    }
    changed = {**defaults(), 'field_per_hectare': 0}
    assert economy.bill(farm, 20_000 * 86400 - 10800 + 20, changed) == 0
    assert farm['economy']['debt'] == 73


def test_scheduled_update_activates_at_next_moscow_day_and_keeps_revision():
    at = 1_800_000_000
    prior = defaults()
    changed = {**prior, 'land_rate_pct': 125, 'upkeep_level': 12}
    payload = updated_payload(None, changed, expected_revision=0, at=at)
    assert payload['revision'] == 1
    state = public_state(payload, at)
    assert state['active'] == prior
    assert state['values'] == changed
    assert effective_values(payload, at) == {**prior, 'revision': 1}

    after = (moscow_day(at) + 1) * 86400 - 10800
    assert effective_values(payload, after) == {**changed, 'revision': 1}
    assert public_state(payload, after)['pending'] is None

    replacement = {**changed, 'land_rate_pct': 150}
    next_payload = updated_payload(payload, replacement, expected_revision=1, at=at)
    assert next_payload['revision'] == 2
    assert next_payload['pending']['values'] == replacement


def test_config_validation_rejects_bool_fraction_unknown_and_out_of_range_values():
    config = defaults()
    for invalid in (
        {**config, 'land_rate_pct': True},
        {**config, 'building_rate_pct': 1.5},
        {**config, 'upkeep_level': 51},
        {**config, 'tree_rate_per_extra_tree': -1},
        {**config, 'other': 3},
    ):
        with pytest.raises(ValueError):
            validate_values(invalid)


def test_catalog_exposes_effective_building_rate_and_revision():
    config = {**defaults(), 'building_rate_pct': 4, 'revision': 7}
    economy_data = catalog.public_catalog(config)['economy']
    assert economy_data['building_rate_pct'] == 4
    assert economy_data['upkeep_revision'] == 7
    assert economy_data['land_rate_pct'] == 100
    assert economy_data['plot_upkeep'][16] == catalog.PLOT_UPKEEP[16]


def test_custom_field_rate_is_exposed_and_used_in_purchase_notice():
    config = {**defaults(), 'field_per_hectare': 2100}
    assert catalog.public_catalog(config)['fields']['upkeep'] == 2100
    farm = {
        'xp': catalog.LEVELS[21], 'coins': 60_000, 'starter_credit': 0,
        'fields': [],
    }
    notice = fields.apply_field(
        farm, 'buy_field', {'step': 0}, 1_800_000_000, 'field-buy-test', 1,
        upkeep_config=config,
    )
    assert notice == 'Поле 1 га куплено. Содержание — 2100 монет в сутки.'
