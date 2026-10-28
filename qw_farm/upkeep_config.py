"""Versioned, scheduled global settings for farm upkeep.

Rates are applied on the next Moscow billing day. Existing billed amounts and
debt are stored on each farm and are intentionally not recalculated here.
"""
from .catalog import (
    FIELD_UPKEEP,
    PLOT_UPKEEP,
    TREE_RENT_STEP,
    UPKEEP_LEVEL,
    UPKEEP_PCT,
)

MOSCOW_OFFSET_SECONDS = 3 * 60 * 60
SECONDS_PER_DAY = 24 * 60 * 60
CONFIG_VERSION = 1


def moscow_day(at):
    return int((at + MOSCOW_OFFSET_SECONDS) // SECONDS_PER_DAY)


def defaults():
    """Stable configured fields, with defaults sourced from the game catalog."""
    return {
        'upkeep_level': UPKEEP_LEVEL,
        'land_rate_pct': 100,
        'building_rate_pct': 100 // UPKEEP_PCT,
        'field_per_hectare': FIELD_UPKEEP,
        'tree_rate_per_extra_tree': TREE_RENT_STEP,
    }


def validate_values(values):
    if not isinstance(values, dict) or set(values) != set(defaults()):
        raise ValueError('Некорректный набор ставок содержания фермы.')
    bounds = {
        'upkeep_level': (1, 50),
        'land_rate_pct': (0, 500),
        'building_rate_pct': (0, 100),
        'field_per_hectare': (0, 100_000),
        'tree_rate_per_extra_tree': (0, 100_000),
    }
    normalized = {}
    for key, (low, high) in bounds.items():
        value = values[key]
        if type(value) is not int or not low <= value <= high:
            raise ValueError(f'Недопустимое значение настройки {key}.')
        normalized[key] = value
    return normalized


def settings_for(values=None):
    """Normalize an effective config; ignore transport-only revision metadata."""
    source = defaults()
    if values:
        source.update({key: value for key, value in values.items() if key in source})
    return validate_values(source)


def _payload_state(payload, at):
    if not payload:
        return {'revision': 0, 'active': defaults(), 'pending': None}
    if not isinstance(payload, dict) or payload.get('version') != CONFIG_VERSION:
        raise RuntimeError('Неизвестная версия настроек содержания фермы.')
    revision = payload.get('revision')
    if type(revision) is not int or revision < 1:
        raise RuntimeError('Некорректная версия настроек содержания фермы.')
    try:
        active = validate_values(payload['active'])
        pending_payload = payload.get('pending')
        pending = None
        if pending_payload is not None:
            if not isinstance(pending_payload, dict) or type(pending_payload.get('effective_from_moscow_day')) is not int:
                raise ValueError
            pending = {
                'values': validate_values(pending_payload['values']),
                'effective_from_moscow_day': pending_payload['effective_from_moscow_day'],
            }
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError('Некорректные сохранённые ставки содержания фермы.') from exc
    if pending and moscow_day(at) >= pending['effective_from_moscow_day']:
        active, pending = pending['values'], None
    return {'revision': revision, 'active': active, 'pending': pending}


def effective_values(payload, at):
    """Values used for this operation, plus the revision exposed to clients."""
    state = _payload_state(payload, at)
    return {**state['active'], 'revision': state['revision']}


def public_state(payload, at):
    """Admin read model. `values` follows a pending edit for convenient editing."""
    state = _payload_state(payload, at)
    return {
        'revision': state['revision'],
        'active': state['active'],
        'pending': state['pending'],
        'values': state['pending']['values'] if state['pending'] else state['active'],
    }


def updated_payload(payload, values, *, expected_revision, at):
    state = _payload_state(payload, at)
    if state['revision'] != expected_revision:
        from storage.admin_actions import AdminConflict
        raise AdminConflict('Настройки уже изменены. Обнови страницу перед сохранением.')
    values = validate_values(values)
    return {
        'version': CONFIG_VERSION,
        'revision': state['revision'] + 1,
        'active': state['active'],
        'pending': {
            'values': values,
            'effective_from_moscow_day': moscow_day(at) + 1,
        },
    }


def land_plot_rate(size, values=None):
    """Daily per-bed land bill derived from the existing land-size schedule."""
    settings = settings_for(values)
    base = PLOT_UPKEEP.get(size, 0)
    return (base * settings['land_rate_pct'] + 99) // 100
