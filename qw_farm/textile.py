"""Textile chain rules that live in farm state: the lessons of «Кошка Соня».

Farm state: ``farm['lessons'] = {track: number of delivered steps}`` (absent in older saves; ``upgrade`` adds ``{}``).
A delivered step opens recipes that carry ``teach`` (see ``catalog.LESSONS``) ``early`` levels sooner than their own level;
the plain level always opens them too. ``recipe_level`` is the one place that says from which player level a farm may use a recipe,
so ``reachable()``, the queue command, helpers' restarts and contracts all agree (docs/tasks/FARM_VILLAGE_MINIGAMES.md 3.3).
"""
from .catalog import LESSONS, ITEMS, level
from .domain import need, named, inventory

SCHEMAS = {'lesson_deliver': {'track'}}


def upgrade(farm):
    """Additive, idempotent: older saves just get an empty ledger."""
    farm.setdefault('lessons', {})
    return farm


def recipe_level(farm, recipe):
    """Player level from which this farm may use ``recipe`` (its own level, or earlier when a lesson opened it)."""
    if recipe.get('scroll') and recipe['scroll'] not in (farm.get('merchant') or {}).get('scrolls', ()):
        return 10 ** 6          # a merchant's scroll recipe: never opened by level, only by the scroll itself
    teach = recipe.get('teach')
    if teach and (farm.get('lessons') or {}).get(teach['track'], 0) >= teach['step']:
        return max(1, recipe['level'] - teach['early'])
    return recipe['level']


def next_step(farm, track):
    steps = LESSONS[track]['steps']
    done = (farm.get('lessons') or {}).get(track, 0)
    return steps[done] if done < len(steps) else None


def deliver(farm, track_id):
    track = named(LESSONS, track_id)
    step = next_step(farm, track['id'])
    need(step is not None, 'lesson_done', 'Все уроки этого курса уже пройдены.', 422)
    need(level(farm['xp']) >= step['level'], 'locked', f'Этот урок открывается с {step["level"]} уровня.')
    inventory(farm, step['items'], -1)
    inventory(farm, step['reward'], 1)
    upgrade(farm)['lessons'][track['id']] = step['step']
    gift = ', '.join(f'{ITEMS[k]["name"].lower()} ×{q}' for k, q in step['reward'].items())
    return f'{track["npc"]} принимает работу: «{step["text"]}». Урок пройден, в подарок: {gift}.'


def apply(farm, kind, data):
    assert kind == 'lesson_deliver'
    return deliver(farm, data['track'])


def validate(farm):
    lessons = farm.get('lessons', {})
    need(isinstance(lessons, dict) and all(k in LESSONS and type(v) is int and 0 <= v <= len(LESSONS[k]['steps'])
                                           for k, v in lessons.items()), 'invalid_lessons', 'Некорректные уроки.', 500)
