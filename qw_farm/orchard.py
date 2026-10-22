"""Fruit orchard: perennial trees (docs/tasks/FARM_ORCHARD.md). Pure rules; time and identity come from the trusted layer.

A tree is a 1x1 object ``{id, type:'tree', species, planted_at, harvests, fruit, pruned_until, prune_at, look, cost, gift, paid_with}``.
It bears fruit in cycles of ``TREE_CYCLE`` ("garden year", 20 h) like an animal house: ``fruit`` is the current cycle, frozen when it
starts (``ready_at``, ``qty``, ``xp``, ``pest``, ``golden``), so a rebalance needs no migration. The first harvest comes after
``juvenile + 1`` cycles. A ripe harvest waits on the tree; the next cycle starts when the fruit is taken (like a bed). Nothing dies or
spoils: care only adds or removes a bonus. Trees use ``TREE_LIMITS`` (not beds) and pay ``plot_upkeep`` like a bed.

Commands (owner only, strict schemas; the fruit itself is taken with the ordinary ``harvest`` / ``collect_all`` / ``collect_group``):
  ``plant_tree {species, x, y, voucher}``  voucher: null | 'free' (a free sapling of ``farm['orchard']['vouchers']``) | the id of a discount
                                           voucher in the warehouse (the merchant's / a festival's, -25%)
  ``tree_care {object, action, item}``     action 'spray' (one «Садовый настой»), 'prune' (free), 'graft' (item = a graft from the warehouse)

State ``farm['orchard'] = {vouchers:{species:n}, granted:[species], seen:[species]}`` (``setdefault`` only, the schema is not raised).
``seen`` is the migration marker: the compensation sapling for a fruit once grown on a bed is decided exactly once per species, at the
first upgrade after the species exists (a tree harvest also writes ``harvested_crops``, so the marker is what keeps it from repeating).
"""
from hashlib import sha256
import math

from .catalog import (CROPS, ITEMS, TREES, TREE_BY_FRUIT, GRAFTS, TREE_CYCLE, TREE_YOUNG_HARVESTS, TREE_ADULT_HARVESTS, TREE_CENTURY_HARVESTS,
                      TREE_PEST_PCT, TREE_GOLD_PERMILLE, TREE_PRUNE_EVERY, TREE_PRUNE_WOOD, TREE_WATER_CUT, TREE_HELP_PCT, TREE_BIRDHOUSE_RADIUS,
                      TREE_VOUCHER_DISCOUNT_PCT, TREE_REFUND_WOOD, TREE_PESTS, VERSION, level, tick, tree_limit, object_limit)
from .domain import need, named, find, duration, inventory, pay, place, event
from . import progression, market

SCHEMAS = {'plant_tree': {'species', 'x', 'y', 'voucher'}, 'tree_care': {'object', 'action', 'item'}}
PESTS = dict(TREE_PESTS)
INFUSION = 'garden_infusion'
GOLDEN = 'rejuvenating_apple'
FRUIT_OF_BED = {c['id']: c['orchard'] for c in CROPS.values() if c.get('orchard')}      # fruit id -> species (the closed bed crops)
GEN = dict(apple='грядочной яблони', cherry='грядочной вишни', pear='грядочной груши', plum='грядочной сливы', apricot='грядочного абрикоса',
           peach='грядочного персика', pomegranate='грядочного граната')
BED_MESSAGE = 'Плодовые деревья теперь растут в саду: посади саженец во вкладке «Сад».'


def _h(*parts):
    return int(sha256(':'.join(str(p) for p in parts).encode()).hexdigest()[:16], 16)


# ----------------------------------------------------------------------------------------------------------------------
# Tree maths
# ----------------------------------------------------------------------------------------------------------------------
def is_tree(obj):
    return obj.get('type') == 'tree'


def trees(farm):
    return [o for o in farm['objects'] if is_tree(o)]


def yield_of(spec, n):
    """Fruit of the n-th harvest (1-based): Y while young (up to 5), Y+1 while adult (up to 20), Y+2 later."""
    return spec['yield_qty'] + (0 if n <= TREE_YOUNG_HARVESTS else 1 if n <= TREE_ADULT_HARVESTS else 2)


def stage(obj):
    """sapling (no harvest yet) | young | adult | elder | century. By the harvest that is next in line."""
    n = obj['harvests'] + 1
    if obj['harvests'] == 0:
        return 'sapling'
    return 'young' if n <= TREE_YOUNG_HARVESTS else 'adult' if n <= TREE_ADULT_HARVESTS else 'century' if n >= TREE_CENTURY_HARVESTS else 'elder'


def gold_chance(n):
    """Permille of a golden fruit at the n-th harvest: none while young, 2% adult and older, 4% from the 100th."""
    return 0 if n <= TREE_YOUNG_HARVESTS else TREE_GOLD_PERMILLE[1 if n >= TREE_CENTURY_HARVESTS else 0]


def near_birdhouse(farm, obj):
    r = TREE_BIRDHOUSE_RADIUS
    return any(o['type'] == 'birdhouse' and max(abs(o['x'] - obj['x']), abs(o['y'] - obj['y'])) <= r for o in farm['objects'])


def spas_bonus(species, at):
    """«Яблочный Спас»: on the fair days of the festival «Спасы» an apple tree gives one more apple. The festival engine owns the calendar."""
    if species != 'apple':
        return False
    from . import festivals
    cur = festivals.current(at)
    return bool(cur and cur['id'] == 'spas' and cur['phase'] == 'fair')


def new_cycle(farm, obj, at, speed=1, player=True):
    """The fruit of the next cycle: parameters are frozen now. The first one waits ``juvenile + 1`` cycles."""
    spec = TREES[obj['species']]
    n = obj['harvests'] + 1
    cycles = spec['juvenile'] + 1 if obj['harvests'] == 0 else 1
    qty = yield_of(spec, n) + (1 if obj['harvests'] < obj.get('pruned_until', 0) else 0)
    pest = None
    if _h(farm['id'], obj['id'], obj['harvests'], 'pest') % 100 < TREE_PEST_PCT:
        pest = TREE_PESTS[_h(farm['id'], obj['id'], obj['harvests'], 'kind') % len(TREE_PESTS)][0]
    gold = _h(farm['id'], obj['id'], obj['harvests'], 'gold') % 1000 < gold_chance(n)
    return dict(started_at=at, ready_at=at + duration(TREE_CYCLE * cycles, speed, farm if player else None), qty=qty, xp=spec['xp'],
                pest=pest, golden=gold and pest is None, gold_hidden=gold and pest is not None, helped=False, watered=False, version=VERSION)


def ripe(obj, at):
    return is_tree(obj) and bool(obj.get('fruit')) and obj['fruit']['ready_at'] <= at


def pest_active(farm, obj):
    f = obj.get('fruit')
    return bool(f and f.get('pest')) and not near_birdhouse(farm, obj)


def dry(obj):
    """Dry branches are waiting for the pruner (nothing is lost if they are left)."""
    return obj['harvests'] >= obj.get('prune_at', TREE_PRUNE_EVERY)


def _observe(farm, fruit):
    if fruit in CROPS and fruit not in farm['harvested_crops']:
        farm['harvested_crops'].append(fruit)


def harvest(farm, obj, at, owner=True, speed=1):
    """Take the ripe fruit and start the next cycle. Used by the owner, by the bulk commands and by the harvest helpers."""
    f = obj.get('fruit')
    need(is_tree(obj) and f is not None and f['ready_at'] <= at, 'not_ready', 'Урожай ещё растёт.')
    spec = TREES[obj['species']]
    qty, golden = f['qty'], f['golden']
    if f.get('pest') and near_birdhouse(farm, obj):      # the birdhouse treats the pest by itself
        qty += 1
        golden = golden or f.get('gold_hidden', False)
    if spas_bonus(obj['species'], at):
        qty += 1
    got = {spec['fruit']: qty}
    if golden:
        got[GOLDEN] = 1
    inventory(farm, got)
    progression.grant_xp(farm, f['xp'], 'harvest', at, owner, TREE_CYCLE)
    farm['stats']['harvests'] += 1
    _observe(farm, spec['fruit'])
    market.count(farm, 'h:' + spec['fruit'], qty)
    obj['harvests'] += 1
    obj['fruit'] = new_cycle(farm, obj, at, speed, owner)
    obj['revision'] += 1
    return got


def waterable(obj, at):
    f = obj.get('fruit')
    return is_tree(obj) and obj['harvests'] == 0 and bool(f) and not f.get('watered') and f['started_at'] <= at < f['ready_at']


def water(obj, at):
    """A helper (Заяц Поливай) waters a sapling: the sapling phase gets 15% shorter. Once per tree."""
    f = obj['fruit']
    f['ready_at'] = max(at, f['ready_at'] - (f['ready_at'] - f['started_at']) * TREE_WATER_CUT // 1000)
    f['watered'] = True
    obj['revision'] += 1


def check_help(obj, now):
    f = obj.get('fruit')
    need(f is not None and f['ready_at'] > now and not f['helped'], 'cannot_help', 'Это дерево уже плодоносит или ему уже помогли.')
    return f


def help_tree(obj, now):
    """A neighbour's help: -20% of the time left in the current cycle, once per cycle."""
    f = check_help(obj, now)
    f['ready_at'] = max(now, f['ready_at'] - max(1, math.ceil((f['ready_at'] - now) * TREE_HELP_PCT / 100)))
    f['helped'] = True
    obj['revision'] += 1


# ----------------------------------------------------------------------------------------------------------------------
# State
# ----------------------------------------------------------------------------------------------------------------------
def blank():
    return dict(vouchers={}, granted=[], seen=[])


def state(farm):
    o = farm.setdefault('orchard', blank())
    for k, v in blank().items():
        o.setdefault(k, v)
    return o


def peek(farm):
    return {**blank(), **(farm.get('orchard') or {})}


def _grew_on_beds(farm, fruit):
    """The player has grown (or is growing) this fruit the old way: a harvest on record, a bed or a field with it, or a sowing run."""
    if fruit in farm.get('harvested_crops', []):
        return True
    if any((o.get('crop') or {}).get('id') == fruit for o in farm['objects'] if o['type'] == 'plot'):
        return True
    for f in farm.get('fields', []):
        if isinstance(f, dict) and ((f.get('crop') or {}).get('id') == fruit or (f.get('run') or {}).get('crop') == fruit):
            return True
    return False


def upgrade(farm, now=None):
    """Create the record and give every fruit grown on beds one free sapling, exactly once per species (``seen``). Idempotent."""
    o = state(farm)
    at = now if now is not None else (farm['events'][0]['at'] if farm.get('events') else farm.get('created_at', 0))
    for sp, spec in TREES.items():
        if sp in o['seen']:
            continue
        o['seen'].append(sp)
        if _grew_on_beds(farm, spec['fruit']):
            o['vouchers'][sp] = o['vouchers'].get(sp, 0) + 1
            o['granted'].append(sp)
            event(farm, at, f'Филиныч привёз саженец взамен {GEN[sp]}: «На грядке было тесно».', 'orchard')
    return o


def add_voucher(farm, species, n=1):
    """A free sapling of a species (festivals and other sources call this; the tree limit is checked when it is planted)."""
    need(species in TREES, 'unknown_item', 'Такого дерева нет.', 422)
    o = state(farm)
    o['vouchers'][species] = o['vouchers'].get(species, 0) + n


def validate(farm):
    o = farm.get('orchard')
    if o is not None:
        need(isinstance(o, dict) and set(o) == {'vouchers', 'granted', 'seen'} and isinstance(o['vouchers'], dict)
             and all(k in TREES and type(v) is int and 0 <= v <= 1000 for k, v in o['vouchers'].items())
             and isinstance(o['granted'], list) and isinstance(o['seen'], list) and set(o['granted']) <= set(o['seen']) <= set(TREES)
             and len(set(o['granted'])) == len(o['granted']) and len(set(o['seen'])) == len(o['seen']),
             'invalid_orchard', 'Некорректное состояние сада.', 500)
    for obj in trees(farm):
        f = obj.get('fruit')
        need(obj.get('species') in TREES and type(obj.get('harvests')) is int and obj['harvests'] >= 0 and type(obj.get('planted_at')) is int
             and (obj.get('look') is None or isinstance(obj['look'], str))
             and type(obj.get('cost')) is int and obj['cost'] >= 0 and (f is None or (isinstance(f, dict) and type(f.get('ready_at')) is int
                                                                                   and type(f.get('qty')) is int and f['qty'] >= 0)),
             'invalid_tree', 'Некорректное дерево в саду.', 500)


# ----------------------------------------------------------------------------------------------------------------------
# Reachability for orders (a fruit is askable only if the player can grow it)
# ----------------------------------------------------------------------------------------------------------------------
def fruits_in_reach(farm):
    """Fruit that is reachable by growing: a bearing tree (one harvest done) or an old planting of it still on a bed or a field."""
    out = {TREES[o['species']]['fruit'] for o in trees(farm) if o['harvests'] >= 1}
    out |= {o['crop']['id'] for o in farm['objects'] if o['type'] == 'plot' and o.get('crop') and o['crop']['id'] in FRUIT_OF_BED}
    for f in farm.get('fields', []):
        if isinstance(f, dict) and f.get('crop') and f['crop'].get('id') in FRUIT_OF_BED:
            out.add(f['crop']['id'])
    return out


def closed(crop_id):
    """The message when a new bed or field planting of an orchard fruit is attempted, else None."""
    return BED_MESSAGE if crop_id in FRUIT_OF_BED else None


# ----------------------------------------------------------------------------------------------------------------------
# Commands
# ----------------------------------------------------------------------------------------------------------------------
def discount_voucher(item_id):
    spec = ITEMS.get(item_id)
    return bool(spec and spec.get('kind') == 'voucher' and spec.get('orchard'))


def sapling_price(species, voucher):
    cost = TREES[species]['cost']
    return cost * (100 - TREE_VOUCHER_DISCOUNT_PCT) // 100 if voucher not in (None, 'free') else (0 if voucher == 'free' else cost)


def plant(farm, data, now, command_id, speed):
    sp = data['species']
    need(isinstance(sp, str) and sp in TREES, 'unknown_item', 'Такого дерева нет.', 422)
    spec = TREES[sp]
    voucher = data['voucher']
    need(voucher is None or isinstance(voucher, str), 'invalid_command', 'Некорректный талон.', 422)
    need(level(farm['xp']) >= spec['level'], 'locked', f'{spec["name"]} открывается с {spec["level"]} уровня.')
    count, limit = len(trees(farm)), tree_limit(farm['size'])
    need(count < limit, 'tree_limit', f'На таком участке доступно деревьев: {limit}. Расширь землю.' if limit else 'Сад начинается с участка 16 × 16: сначала расширь землю.')
    need(len(farm['objects']) < object_limit(farm['size']), 'object_limit', 'Достигнут лимит объектов для этого участка.')
    place(farm, data['x'], data['y'], 1, 1)
    o = state(farm)
    if voucher == 'free':
        need(o['vouchers'].get(sp, 0) > 0, 'no_voucher', 'Бесплатного саженца этого вида нет.')
    elif voucher is not None:
        need(discount_voucher(voucher), 'no_voucher', 'Это не талон сада.', 422)
        need(farm['inventory'].get(voucher, 0) >= 1, 'no_voucher', 'Такого талона нет на складе.')
    price = sapling_price(sp, voucher)
    gift = pay(farm, price) if price else 0
    if voucher == 'free':
        o['vouchers'][sp] -= 1
        if not o['vouchers'][sp]:
            del o['vouchers'][sp]
    elif voucher is not None:
        inventory(farm, {voucher: 1}, -1)
    obj = dict(id=command_id, type='tree', x=data['x'], y=data['y'], w=1, h=1, revision=0, level=1, jobs=[], animal=None, animal_job=None,
               species=sp, planted_at=now, harvests=0, fruit=None, pruned_until=0, prune_at=TREE_PRUNE_EVERY, look=None, cost=price, gift=gift,
               paid_with=voucher, version=VERSION)
    obj['fruit'] = new_cycle(farm, obj, now, speed)
    farm['objects'].append(obj)
    farm['stats']['builds'] += 1
    return f'{spec["name"]}: саженец посажен, первый урожай через {spec["juvenile"] + 1} садовых года.'


def graft_spec(item_id):
    g = GRAFTS.get(item_id)
    if g:
        return g
    spec = ITEMS.get(item_id) or {}
    if spec.get('kind') == 'graft' and spec.get('orchard') and spec.get('species') in TREES and spec.get('look'):
        return dict(species=spec['species'], look=spec['look'], name=spec['name'])
    return None


def deliver_festival_good(farm, good):
    """A festival lot of the orchard kind was bought (festivals.buy): a voucher lands in the warehouse as its catalog item (``ref``, the
    merchant's discount voucher by default), a graft as the graft item of the same id. Returns the item id, or None for any other lot."""
    if good.get('kind') == 'voucher':
        item = good.get('ref') or 'voucher_orchard'
    elif good.get('kind') == 'graft' and graft_spec(good['id']):
        item = good['id']
    else:
        return None
    need(item in ITEMS, 'unknown_item', 'Этот предмет не найден.', 422)
    inventory(farm, {item: 1})
    return item


def can_buy_graft(farm, item_id):
    g = graft_spec(item_id)
    return bool(g and any(o['species'] == g['species'] for o in trees(farm)))


def care(farm, data, now):
    obj = find(farm['objects'], data['object'])
    need(is_tree(obj), 'wrong_object', 'Это не дерево.', 422)
    action, item = data['action'], data['item']
    need(isinstance(action, str) and action in {'spray', 'prune', 'graft'}, 'invalid_command', 'Неизвестный уход.', 422)
    spec = TREES[obj['species']]
    if action == 'spray':
        need(item is None, 'invalid_command', 'Некорректные параметры действия.', 422)
        f = obj['fruit']
        need(f is not None and f.get('pest'), 'no_pest', 'Вредителей на дереве нет.')
        need(not near_birdhouse(farm, obj), 'bird_watch', 'За этим деревом уже присматривает скворечник.')
        inventory(farm, {INFUSION: 1}, -1)
        f['qty'] += 1
        f['golden'] = f['golden'] or f.get('gold_hidden', False)
        f['gold_hidden'] = False
        f['pest'] = None
        obj['revision'] += 1
        return f'{spec["name"]}: вредитель ушёл, плодов в этом году будет больше.'
    if action == 'prune':
        need(item is None, 'invalid_command', 'Некорректные параметры действия.', 422)
        need(dry(obj), 'no_dry_branches', 'Сухих веток пока нет.')
        inventory(farm, {'wood': TREE_PRUNE_WOOD})
        if obj['fruit'] is not None:
            obj['fruit']['qty'] += 1
        obj['pruned_until'] = obj['harvests'] + TREE_PRUNE_EVERY
        obj['prune_at'] = obj['harvests'] + TREE_PRUNE_EVERY
        obj['revision'] += 1
        return f'{spec["name"]}: ветки подрезаны, древесина ×{TREE_PRUNE_WOOD}, плодов станет больше на ближайшие урожаи.'
    need(isinstance(item, str), 'invalid_command', 'Выбери прививку со склада.', 422)
    g = graft_spec(item)
    need(g is not None, 'unknown_item', 'Это не прививка.', 422)
    need(g['species'] == obj['species'], 'wrong_species', f'Эта прививка для другого дерева: {TREES[g["species"]]["name"].lower()}.')
    need(obj.get('look') != g['look'], 'same_look', 'Дерево уже выглядит так.')
    inventory(farm, {item: 1}, -1)
    obj['look'] = g['look']
    obj['revision'] += 1
    return f'{spec["name"]}: прививка сделана, теперь это «{g["name"]}». Урожай и место в саду прежние.'


def apply(farm, kind, data, now, command_id, speed):
    now = tick(now)
    return plant(farm, data, now, command_id, speed) if kind == 'plant_tree' else care(farm, data, now)


def uproot(farm, obj, now, speed=1):
    """Remove a tree. A ripe harvest is taken first. In the undo window the whole sapling price comes back (and a spent voucher);
    later only wood x2 does, and the client asks for confirmation first."""
    from . import undo
    taken = ''
    if ripe(obj, now):
        harvest(farm, obj, now, True, speed)
        taken = ' Созревший урожай собран.'
    spec = TREES[obj['species']]
    if now - obj['planted_at'] <= undo.UNDO_WINDOW:
        farm['coins'] += obj['cost']
        undo.restore_gift(farm, obj.get('gift', 0), obj['cost'])
        paid = obj.get('paid_with')
        if paid == 'free':
            add_voucher(farm, obj['species'])
        elif paid:
            inventory(farm, {paid: 1})
        text = f'{spec["name"]}: посадка отменена, саженец возвращён.' + (f' Монет: +{obj["cost"]}.' if obj['cost'] else '')
    else:
        inventory(farm, {'wood': TREE_REFUND_WOOD})
        text = f'{spec["name"]}: дерево выкорчевано, древесина ×{TREE_REFUND_WOOD}.'
    farm['objects'].remove(obj)
    return text + taken


# ----------------------------------------------------------------------------------------------------------------------
# Read model
# ----------------------------------------------------------------------------------------------------------------------
def tree_view(farm, obj, now):
    f = obj.get('fruit') or {}
    n = obj['harvests'] + 1
    return dict(stage=stage(obj), age=max(0, (now - obj['planted_at']) // TREE_CYCLE), ripe=ripe(obj, now), pest=f.get('pest'),
                pest_active=pest_active(farm, obj), dry=dry(obj), qty=f.get('qty', 0), golden_permille=gold_chance(n),
                next_yield=yield_of(TREES[obj['species']], n), bird=near_birdhouse(farm, obj))


def owner_view(farm, now):
    o = peek(farm)
    mine = trees(farm)
    return dict(vouchers=dict(o['vouchers']), count=len(mine), limit=tree_limit(farm['size']), infusion=farm['inventory'].get(INFUSION, 0),
                discounts={k: q for k, q in farm['inventory'].items() if q and discount_voucher(k)},
                grafts={k: q for k, q in farm['inventory'].items() if q and graft_spec(k)},
                trees={t['id']: tree_view(farm, t, now) for t in mine})
