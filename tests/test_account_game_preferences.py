"""Validation and sparse merge rules for account-wide game preferences."""

import pytest

from domain.account_game_preferences import (
    apply_game_preferences_patch,
    merge_game_preferences,
    parse_game_preferences_patch,
)


def test_sparse_patch_updates_values_and_null_removes_an_override():
    patch = parse_game_preferences_patch({'music': False, 'music_volume': 55, 'sound_effects': None})

    assert apply_game_preferences_patch(
        {'music': True, 'sound_effects': True, 'animations': False}, patch) == {
            'music': False, 'music_volume': 55, 'animations': False}


@pytest.mark.parametrize('patch', [
    {'other': True},
    {'music': 1},
    {'animations': 'false'},
    {'sound_effects': None, 'music_volume': True},
    {'music_volume': 4},
    {'music_volume': 101},
    {'music_volume': 50.0},
    [],
    None,
])
def test_sparse_patch_rejects_unknown_or_malformed_values(patch):
    with pytest.raises(ValueError):
        parse_game_preferences_patch(patch)


def test_merge_preserves_primary_values_including_false_and_fills_missing_keys():
    assert merge_game_preferences(
        {'music': False, 'music_volume': 80},
        {'music': True, 'sound_effects': False, 'animations': False},
    ) == {'music': False, 'music_volume': 80, 'sound_effects': False, 'animations': False}
