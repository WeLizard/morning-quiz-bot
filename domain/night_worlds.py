"""Worlds (stories) of «Ночной город»: the ids a room may choose, and their age mark.

The list is fixed on the server on purpose. The client art lives in web/mini_client/night/worlds/<id>/ and is
deployed separately, so a missing folder must never decide which world is valid: a world whose pack is not built yet
is still accepted here (the client lists only the worlds of worlds/index.json). Keep in step with
scripts/art/night_city/worlds.json and worlds/index.json.

Age mark: 12 (classic worlds), 16 or 18 (darker ones). 12 and 16 are a mark only (a badge «16+», none for 12). An 18+
world asks the player once «Мне есть 18» when it is chosen, when an open table is taken and when an invitation is used:
the server needs ``age_ok: true`` (require_age_ok). The default world stays the pilot one and an older world is only ever
chosen explicitly.
"""

DEFAULT_WORLD = 'manor_lake'
WORLD_AGES = {
    'manor_lake': 12, 'night_express': 12, 'black_bay': 12, 'newsprint_city': 12, 'palace_masks': 12, 'polar_star': 12,
    'circus': 12, 'campus': 12, 'sand_city': 12, 'neon_city': 12, 'prohibition': 12,
    'deep_choir': 16, 'dead_air': 16,
    'velvet_circle': 18, 'eternal_hotel': 18,
}
WORLD_IDS = tuple(WORLD_AGES)
AGE_MARKS = (12, 16, 18)


def is_world(value: object) -> bool:
    return isinstance(value, str) and value in WORLD_AGES


def world_or_default(value: object) -> str:
    return value if is_world(value) else DEFAULT_WORLD


class AgeConfirmRequired(Exception):
    """An 18+ world was entered or chosen without the player's own confirmation (``age_ok: true``). Nothing is stored."""

    code = 'age_confirm_required'

    def __init__(self):
        super().__init__('В этом сюжете есть сцены для взрослых. Подтверди, что тебе есть 18.')


def require_age_ok(world: object, age_ok: object) -> None:
    """Worlds marked 18 need ``age_ok is True``; 12 and 16 never ask (the 16+ mark is a badge only)."""
    if world_age(world) >= 18 and age_ok is not True:
        raise AgeConfirmRequired()


def world_age(value: object) -> int:
    """Age mark of a world (12, 16 or 18); an unknown id counts as the default world."""
    return WORLD_AGES[world_or_default(value)]
