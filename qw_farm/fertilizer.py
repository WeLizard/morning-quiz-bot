"""Fertilizing beds and trees (docs/tasks/FARM_FERTILIZERS.md, section 4).

A planting (``crop``) or a tree cycle (``fruit``) is marked ``fert = 1`` when one fertilizer unit (humate first, then compost) was spent on it.
``fert_item`` remembers which one, so that a return gives back exactly what was spent. The effect appears only at harvest: +25% of the
quantity, with the fractional part kept in ``farm['fert_carry'][item]`` (whole permille 0..999) and paid out as whole units. Experience,
the golden-fruit chance and prices are not touched. Flags ``farm['fert_beds']`` / ``farm['fert_trees']`` (absent means false) switch the
automatic spending on planting and on a new adult-tree cycle. All fields are optional: an old save without them is valid and unfertilized.
"""
from .catalog import ITEMS
from .domain import need, inventory

SPEND_ORDER = ('humate', 'compost')    # humate goes first
BONUS_PERMILLE = 250
TARGETS = {'beds': 'fert_beds', 'trees': 'fert_trees'}


def take(farm):
    """Spend one fertilizer unit if the warehouse has one; return its item id or None."""
    for item in SPEND_ORDER:
        if farm['inventory'].get(item, 0) >= 1:
            inventory(farm, {item: 1}, -1)
            return item
    return None


def mark(farm, holder, flag, *, force=False):
    """Fertilize a fresh planting / tree cycle when the switch ``flag`` is on (or ``force``: a manual action). True if a unit was spent."""
    if not force and not farm.get(flag):
        return False
    item = take(farm)
    if item is None:
        return False
    holder['fert'] = 1
    holder['fert_item'] = item
    return True


def bonus(farm, key, qty, holder):
    """Extra whole units for harvesting ``qty`` of ``key`` from a fertilized holder; the fraction is carried on the farm."""
    if holder.get('fert') != 1:
        return 0
    carry = farm.setdefault('fert_carry', {})
    extra, rest = divmod(carry.get(key, 0) + qty * BONUS_PERMILLE, 1000)
    if rest:
        carry[key] = rest
    else:
        carry.pop(key, None)
    return extra


def give_back(farm, holder):
    """Return the unit spent on an unripe planting / cycle that is being removed (the mark is cleared)."""
    if holder.get('fert') != 1:
        return False
    inventory(farm, {holder.get('fert_item', 'compost'): 1})
    holder.pop('fert', None)
    holder.pop('fert_item', None)
    return True


def toggle(farm, data):
    target, enabled = data['target'], data['enabled']
    need(isinstance(target, str) and target in TARGETS and type(enabled) is bool,
         'invalid_command', 'Некорректные параметры действия.', 422)
    farm[TARGETS[target]] = enabled
    name = 'грядок' if target == 'beds' else 'сада'
    return f'Подкормка {name} ' + ('включена.' if enabled else 'выключена.')


def validate_holder(holder, what):
    ok = isinstance(holder, dict) and holder.get('fert', 0) in (0, 1) and type(holder.get('fert', 0)) is int
    ok = ok and (holder.get('fert_item') is None or holder['fert_item'] in SPEND_ORDER)
    ok = ok and not (holder.get('fert_item') and holder.get('fert') != 1)
    need(ok, 'invalid_fertilizer', f'Некорректная подкормка: {what}.', 500)


def validate(farm):
    for flag in TARGETS.values():
        need(type(farm.get(flag, False)) is bool, 'invalid_fertilizer', 'Некорректный переключатель подкормки.', 500)
    carry = farm.get('fert_carry', {})
    need(isinstance(carry, dict) and all(k in ITEMS and type(v) is int and 0 <= v <= 999 for k, v in carry.items()),
         'invalid_fertilizer', 'Некорректный счётчик подкормки.', 500)
    for obj in farm.get('objects', []):
        if obj.get('type') == 'plot' and obj.get('crop'):
            validate_holder(obj['crop'], 'грядка')
        elif obj.get('type') == 'tree' and obj.get('fruit'):
            validate_holder(obj['fruit'], 'дерево')
