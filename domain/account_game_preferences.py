"""Shared optional sound and motion preferences for account-owned game settings."""

GAME_PREFERENCE_KEYS = frozenset({'sound_effects', 'music', 'music_volume', 'animations'})


def parse_game_preferences_patch(value):
    """Validate a sparse patch. A null value removes that account override."""
    if not isinstance(value, dict) or not set(value) <= GAME_PREFERENCE_KEYS:
        raise ValueError('game_preferences')
    result = {}
    for key, item in value.items():
        if item is None:
            result[key] = None
        elif key in {'sound_effects', 'music', 'animations'}:
            if not isinstance(item, bool):
                raise ValueError('game_preferences')
            result[key] = item
        elif key == 'music_volume':
            if type(item) is not int or not 5 <= item <= 100:
                raise ValueError('game_preferences')
            result[key] = item
    return result


def apply_game_preferences_patch(current, patch):
    """Return the whole sparse profile object after applying a validated patch."""
    result = dict(current or {})
    for key, value in patch.items():
        if value is None:
            result.pop(key, None)
        else:
            result[key] = value
    return result


def merge_game_preferences(primary, secondary):
    """Preserve explicit primary values and fill only absent keys from secondary."""
    result = dict(secondary or {})
    result.update(primary or {})
    return result
