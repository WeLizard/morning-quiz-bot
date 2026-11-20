"""Bridge from «Алхимия» to the farm: the dyer's notes.

Each note of the Alchemy expedition «Записки красильщика» (campaign ``paths_camp_dyers``)
is a riddle. When the server has recorded the seal of a stage for an account
(``alchemy_stage_claims``), the farm of the same account learns the matching dye recipe.
The check is server-side only: the client never reports a solved riddle. The farm never names
the Atlas or tells where the riddles are: the player is meant to make the connection alone.

Unlocks are monotonic: a recipe once learned stays learned (a later catalog revision or
an account merge never takes it back). Production itself — the dyeworks building, raw
materials from far trips — plugs into ``unlocked(farm)``; see docs/tasks/FARM_DYEWORKS_AND_ENDGAME.md.
"""
from copy import deepcopy
from uuid import UUID

import sqlalchemy as sa

from .domain import need

KEY = 'dyeworks'
CAMPAIGN = 'paths_camp_dyers'
# Alchemy stage -> farm recipe it unlocks. Order is the order of the notes.
NOTES = (
    ('dyers_1', 'mordant', 'Протрава', 'Записка первая. Замок для цвета'),
    ('dyers_2', 'indigo', 'Индиго', 'Записка вторая. Синий на ветру'),
    ('dyers_3', 'madder', 'Марена', 'Записка третья. Красный под землёй'),
    ('dyers_4', 'saffron', 'Шафран', 'Записка четвёртая. Нити полудня'),
)
RECIPE_OF = {stage: recipe for stage, recipe, _, _ in NOTES}


def blank():
    return dict(unlocked={})


def state(farm):
    return farm.get(KEY) or blank()


def unlocked(farm):
    """Recipe ids the farm has learned, in note order."""
    known = state(farm)['unlocked']
    return [recipe for _, recipe, _, _ in NOTES if recipe in known]


async def claimed_stages(unit, account_id):
    """Dyer's-note stages sealed by the server for this account; empty outside PostgreSQL."""
    if getattr(unit, 'dialect', None) != 'postgresql' or not getattr(unit, 'asynchronous', False):
        return set()
    try:
        account = UUID(str(account_id))
    except (ValueError, TypeError, AttributeError):
        return set()
    from storage.models import AlchemyStageClaim as claims
    rows = await unit.execute(sa.select(claims.stage_id).where(
        claims.account_id == account, claims.campaign_id == CAMPAIGN))
    return {row[0] for row in rows.all()} & set(RECIPE_OF)


def learn(farm, stages, now):
    """Record newly sealed notes. Returns the recipes learned by this call."""
    current = deepcopy(state(farm))
    fresh = [RECIPE_OF[s] for s, _, _, _ in NOTES if s in stages and RECIPE_OF[s] not in current['unlocked']]
    if not fresh:
        return []
    for recipe in fresh:
        current['unlocked'][recipe] = int(now)
    farm[KEY] = current
    return fresh


async def refresh(unit, farm, account_id, now):
    """Pull the server-verified seals into the owner's farm (called under the farm lock)."""
    return learn(farm, await claimed_stages(unit, account_id), now)


def public(farm):
    """Only what the farm has already learned: no note titles, no count of what is left."""
    known = state(farm)['unlocked']
    return dict(recipes=[dict(recipe=recipe, name=name, learned_at=known[recipe])
                         for _, recipe, name, _ in NOTES if recipe in known])


def merge(main, secondary):
    """Account merge: the union of both farms' learned recipes, earliest date wins."""
    left, right = state(main)['unlocked'], state(secondary)['unlocked']
    if not right:
        return
    merged = dict(left)
    for recipe, at in right.items():
        merged[recipe] = min(at, merged.get(recipe, at))
    main[KEY] = dict(unlocked=merged)


def validate(farm):
    value = farm.get(KEY)
    if value is None:
        return
    known = set(RECIPE_OF.values())
    need(isinstance(value, dict) and set(value) == {'unlocked'} and isinstance(value['unlocked'], dict)
         and all(k in known and type(v) is int and v >= 0 for k, v in value['unlocked'].items()),
         'invalid_state', 'Повреждено состояние красильни.', 500)
