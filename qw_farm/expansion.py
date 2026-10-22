"""r2 game rules: equipment, finite work shifts, woodland trips and Easter eggs.

Pure state transitions. No timers/IO/Telegram. A paid shift has both a time bound
and a work quota; catch-up evaluates historical work in chronological order.
Old farm JSON is upgraded additively, without changing its balances or crops.
"""
from copy import deepcopy
import math
from domain.address import g as address_g
from .catalog import (tick, VERSION, CROPS, ITEMS, RECIPES, ANIMALS, EQUIPMENT, HELPERS, SHIFTS, ROUTES, SECRETS,
                      level, animal_batch, animal_xp, ANIMAL_XP_LEGACY, queue_slots, effective_level, RECIPE_SPEED, land_bound, GROUPS,
                      MAX_SHIFT_ACTIONS, SHIFT_INTERVAL, route_level, trip_kind)
from .domain import need, named, find, number, duration, inventory, pay, event
from . import market, progression, economy, fields, projects, trip_games

GRAINS = frozenset({'wheat', 'corn', 'oat', 'rye', 'rice', 'buckwheat'})
ROOTS = frozenset({'carrot', 'beet', 'potato'})
SCHEMAS = {
    'buy_equipment': {'equipment'},
    'hire_helper': {'helper'},
    'machine_run': {'machine', 'crop', 'plots', 'replant'},
    'start_shift': {'worker', 'shift'},
    'stop_shift': {'worker'},
    'start_trip': {'route', 'guide'},
    'collect_trip': {'trip'},
    'abort_trip': {'trip'},
    'night_delivery': set(),
    # r7: zones and one-tap versions of what helpers do. ``area`` is null (whole farm) or {x, y, w, h}.
    'set_zone': {'worker', 'zone'},
    'collect_group': {'group', 'area'},
    'collect_building': {'object'},
    'feed_all': {'area'},
    'restart_all': {'area'},
    'plant_many': {'crop', 'area'},
}
SCHEMAS.update(market.SCHEMAS)  # r8: caravan_fill, contract_claim
SCHEMAS.update(fields.SCHEMAS)  # r9 stage 15: buy_field, buy_machine, upgrade_machine, field_start, field_finish
SCHEMAS.update(projects.SCHEMAS)
SCHEMAS.update(trip_games.SCHEMAS)  # trip minigames: trip_play


def upgrade_state(farm):
    """Safe in-transaction r1 -> r2; no currency, loot or job duplication."""
    farm.setdefault('schema_version', 1)
    need(farm['schema_version'] <= 2, 'newer_save',
         'Сохранение создано более новой версией игры.', 503)
    farm.setdefault('equipment', {})
    farm.setdefault('helpers', {})
    farm.setdefault('trips', [])
    farm.setdefault('trip_seq', 0)
    farm.setdefault('secrets', [])
    farm.setdefault('harvested_crops', [])
    progression.progress(farm)  # r9: setdefault only, schema_version stays 2
    economy.state(farm)         # r9 stage 14: same
    projects.upgrade_state(farm)
    from . import minigames
    minigames.upgrade(farm)
    for key in ('automation', 'forages', 'fishing_trips', 'machine_runs', 'secrets'):
        farm['stats'].setdefault(key, 0)
    market.upgrade_market(farm)
    from . import village_quests
    village_quests.state(farm)
    for obj in farm.get('objects', []):
        if obj['type'] in WORKSHOP_TYPES and (obj.get('last_recipe') or 'recipes_memory' in obj):
            _own_memory(obj)
            _sync_memory(obj)
    farm['schema_version'] = 2
    farm['catalog'] = VERSION
    return farm


def discover(farm, key, now):
    if key not in farm['secrets']:
        farm['secrets'].append(key)
        farm['stats']['secrets'] += 1
        event(farm, now, f'Находка: «{SECRETS[key]["name"]}». В строительстве появился особый декор.', 'secret')


def observe_harvest(farm, crop_id):
    if crop_id not in farm['harvested_crops']:
        farm['harvested_crops'].append(crop_id)


def detect_secrets(farm, now):
    if len(farm['harvested_crops']) >= 4:
        discover(farm, 'elements', now)


def harvest(farm, obj, at, owner=True):
    crop = obj['crop']
    inventory(farm, {crop['id']: crop['yield_qty']})
    progression.grant_xp(farm, crop['xp'], 'harvest', at, owner, CROPS[crop['id']]['seconds'] if crop['id'] in CROPS else None)
    farm['stats']['harvests'] += 1
    observe_harvest(farm, crop['id'])
    market.count(farm, 'h:' + crop['id'], crop['yield_qty'])
    obj['last_crop'] = crop['id']
    obj['crop'] = None
    obj['revision'] += 1


def plant(farm, obj, crop, at, speed):
    gift = pay(farm, crop['cost'])
    obj['crop'] = dict(id=crop['id'], planted_at=at,
                       ready_at=at + duration(crop['seconds'], speed, farm),
                       yield_qty=crop['yield_qty'], xp=crop['xp'], helped=False,
                       watered=False, version=VERSION, cost=crop['cost'], gift=gift)
    obj['revision'] += 1


def owned_worker(farm, worker_id):
    if worker_id == 'robot':
        need(worker_id in farm['equipment'], 'not_owned', 'Сначала купи робота-сборщика.')
        return farm['equipment'][worker_id], EQUIPMENT[worker_id]
    spec = named(HELPERS, worker_id)
    need(worker_id in farm['helpers'], 'not_hired', 'Сначала пригласи помощника в команду.')
    return farm['helpers'][worker_id], spec


WORKSHOP_TYPES = frozenset(r['building'] for r in RECIPES.values())


def rect(value, code='invalid_zone'):
    """Validate an optional {x,y,w,h} rectangle (0-based cells) -> (x0, y0, x1, y1) inclusive, or None = whole farm."""
    if value is None:
        return None
    need(isinstance(value, dict) and set(value) == {'x', 'y', 'w', 'h'} and all(type(v) is int for v in value.values()),
         code, 'Неверная область: нужны x, y, w, h.', 422)
    x, y, w, h = value['x'], value['y'], value['w'], value['h']
    top = land_bound()
    need(0 <= x < top and 0 <= y < top and 1 <= w <= top and 1 <= h <= top
         and x + w <= top and y + h <= top, code, 'Область выходит за пределы участка.', 422)
    return (x, y, x + w - 1, y + h - 1)


def in_zone(obj, box):
    """True if any cell of the object lies inside the zone."""
    return (box is None or (obj['x'] <= box[2] and obj['x'] + obj['w'] - 1 >= box[0]
                            and obj['y'] <= box[3] and obj['y'] + obj['h'] - 1 >= box[1]))


def ordered_objects(farm):
    return sorted(farm['objects'], key=lambda x: x['id'])


def make_job(obj, recipe, at, speed, job_id, farm=None):
    """The one place that builds a queued recipe, used by the manual command and by the artisans."""
    start = max([at] + [j['ready_at'] for j in obj['jobs']])
    seconds = duration(recipe['seconds'] * RECIPE_SPEED[effective_level(obj.get('level'))], speed, farm)
    return dict(id=job_id, recipe=recipe['id'], starts_at=start, ready_at=start + seconds, seconds=seconds,
                inputs=deepcopy(recipe['inputs']), outputs=deepcopy(recipe['outputs']), xp=recipe['xp'], version=VERSION)


def memory_cap(obj):
    """How many distinct recipes a workshop remembers: as many as it has queue slots."""
    return max(1, queue_slots(obj.get('level')))


def recipe_memory(obj):
    """Ordered unique recipe ids the player queued by hand (oldest first); read-only, so a refused command mutates nothing.
    Migrates the single legacy ``last_recipe`` on the fly."""
    mem = obj.get('recipes_memory')
    if isinstance(mem, list):
        return mem
    return [obj['last_recipe']] if obj.get('last_recipe') else []


def _own_memory(obj):
    """The stored list (created from the legacy field when missing) for writers."""
    if not isinstance(obj.get('recipes_memory'), list):
        obj['recipes_memory'] = recipe_memory(obj)
    return obj['recipes_memory']


def _sync_memory(obj):
    """Keep the legacy ``last_recipe`` mirror (= newest remembered) and the rotation cursor in range."""
    mem = obj['recipes_memory']
    if mem:
        obj['last_recipe'] = mem[-1]
    else:
        obj.pop('last_recipe', None)
    obj['recipe_cursor'] = obj.get('recipe_cursor', 0) % len(mem) if mem else 0


def _drop_at(obj, index):
    mem = obj['recipes_memory']
    mem.pop(index)
    if index < obj.get('recipe_cursor', 0):
        obj['recipe_cursor'] -= 1   # the cursor keeps pointing at the same recipe


def remember_recipe(obj, recipe_id):
    """A manual enqueue: append (or move to the end), drop the oldest beyond the cap."""
    mem = _own_memory(obj)
    if recipe_id in mem:
        _drop_at(obj, mem.index(recipe_id))
    mem.append(recipe_id)
    while len(mem) > memory_cap(obj):
        _drop_at(obj, 0)
    _sync_memory(obj)


def forget_recipe_id(obj, recipe_id=None):
    """Forget one remembered recipe (default: the most recent). Returns its id, or None if there is nothing to forget."""
    mem = _own_memory(obj)
    if recipe_id is None:
        recipe_id = mem[-1] if mem else None
    if recipe_id not in mem:
        return None
    _drop_at(obj, mem.index(recipe_id))
    _sync_memory(obj)
    return recipe_id


def mark_started(obj, recipe_id):
    """An automatic restart happened: the rotation continues after this recipe."""
    mem = _own_memory(obj)
    if recipe_id in mem:
        obj['recipe_cursor'] = (mem.index(recipe_id) + 1) % len(mem)


def restartable(farm, obj, lv):
    """The next remembered recipe of a workshop (rotation order) that can be queued right now, else None."""
    if obj['type'] not in WORKSHOP_TYPES or len(obj['jobs']) >= queue_slots(obj.get('level')):
        return None
    mem = recipe_memory(obj)
    for step in range(len(mem)):
        recipe = RECIPES.get(mem[(obj.get('recipe_cursor', 0) + step) % len(mem)])
        if (recipe and recipe['building'] == obj['type'] and recipe['level'] <= lv
                and all(farm['inventory'].get(k, 0) >= q for k, q in recipe['inputs'].items())):
            return recipe
    return None


def can_feed(farm, obj):
    if not obj.get('animal') or obj.get('animal_job'):
        return False
    inputs = animal_batch(ANIMALS[obj['animal']], obj.get('level'))[0]
    return all(farm['inventory'].get(k, 0) >= q for k, q in inputs.items())


def start_feed(farm, obj, at, speed, player=True):
    inputs, outputs, seconds = animal_batch(ANIMALS[obj['animal']], obj.get('level'))
    inventory(farm, inputs, -1)
    obj['animal_job'] = dict(ready_at=at + duration(seconds, speed, farm if player else None), outputs=outputs, xp=animal_xp(ANIMALS[obj['animal']], obj.get('level')),
                          version=VERSION)
    obj['revision'] += 1


def take_animal(farm, obj, at, owner=True):
    job = obj['animal_job']
    inventory(farm, job['outputs'])
    market.count_outputs(farm, job['outputs'])
    progression.grant_xp(farm, job.get('xp', ANIMAL_XP_LEGACY), 'animal', at, owner)
    farm['stats']['crafts'] += 1
    obj['animal_job'] = None
    obj['revision'] += 1


def take_job(farm, obj, job, at, owner=True):
    inventory(farm, job['outputs'])
    market.count_outputs(farm, job['outputs'])
    recipe = RECIPES.get(job.get('recipe'))
    progression.grant_xp(farm, job['xp'], 'craft', at, owner, recipe['seconds'] if recipe else None)
    farm['stats']['crafts'] += 1
    obj['jobs'].remove(job)
    obj['revision'] += 1


def _targets(farm, ordered, role, at, box):
    """Yield (object, payload) eligible at this instant, in deterministic order (by object id)."""
    if role == 'craft':
        # Collect first (the master then restarts the same workshop right away if quota allows), then restart idle workshops:
        # the one that frees up earliest goes first (empty queue = earliest), ties by object id.
        for obj in ordered:
            if obj['type'] in WORKSHOP_TYPES and in_zone(obj, box):
                for job in obj['jobs']:
                    if job['ready_at'] <= at:
                        yield obj, job
        lv = level(farm['xp'])
        frees = lambda o: (max((j['ready_at'] for j in o.get('jobs', [])), default=float('-inf')), o['id'])
        for obj in sorted(ordered, key=frees):
            if obj['type'] in WORKSHOP_TYPES and in_zone(obj, box):
                recipe = restartable(farm, obj, lv)
                if recipe:
                    yield obj, recipe['id']
        return
    for obj in ordered:
        if not in_zone(obj, box):
            continue
        crop = obj.get('crop')
        if role in {'harvest', 'roots'} and crop and crop['ready_at'] <= at:
            if role != 'roots' or crop['id'] in ROOTS:
                yield obj, None
        elif role == 'water' and crop and crop['planted_at'] <= at < crop['ready_at'] and not crop.get('watered'):
            yield obj, None
        elif role == 'production':
            for job in obj.get('jobs', []):
                if job['ready_at'] <= at:
                    yield obj, job
        elif role == 'animals' and obj.get('animal'):
            job = obj.get('animal_job')
            if job and job['ready_at'] <= at:
                yield obj, job
            elif not job and can_feed(farm, obj):
                yield obj, None


def _next_possible(farm, ordered, role, at, box):
    """Jump straight to the next relevant timestamp instead of replaying empty ticks."""
    moments = []
    for obj in ordered:
        if not in_zone(obj, box):
            continue
        crop = obj.get('crop')
        if role in {'harvest', 'roots'} and crop and (role != 'roots' or crop['id'] in ROOTS):
            if crop['ready_at'] > at:
                moments.append(crop['ready_at'])
        elif role in {'production', 'craft'}:
            moments += [j['ready_at'] for j in obj.get('jobs', []) if j['ready_at'] > at]
        elif role == 'animals' and obj.get('animal_job'):
            if obj['animal_job']['ready_at'] > at:
                moments.append(obj['animal_job']['ready_at'])
    return min(moments) if moments else None


def _craft_row(log, worker, obj):
    """Per (worker, workshop) account of one settle: what went to the warehouse, what was put back in."""
    return log.setdefault((worker, obj['id']), dict(worker=worker, object=obj['id'], type=obj['type'], carried={}, started={}))


def _start_craft(farm, obj, recipe, at, speed, job_id, log, worker):
    inventory(farm, recipe['inputs'], -1)
    obj['jobs'].append(make_job(obj, recipe, at, speed, job_id))
    mark_started(obj, recipe['id'])
    obj['revision'] += 1
    if log is not None:
        row = _craft_row(log, worker, obj)
        row['started'][recipe['id']] = row['started'].get(recipe['id'], 0) + 1


def _work_once(farm, ordered, role, at, shift, box, log=None, worker=None):
    """Do one unit of work; returns the quota units it cost (0 = nothing to do).

    A craft collect costs 1 and the immediate restart of the same workshop another 1 (2 in all); with a single unit
    left the master only collects."""
    target = next(_targets(farm, ordered, role, at, box), None)
    if target is None:
        return 0
    units = 1
    obj, payload = target
    speed = shift['speed']
    if role in {'harvest', 'roots'}:
        harvest(farm, obj, at, False)
    elif role == 'water':
        crop = obj['crop']
        crop['ready_at'] = max(at, crop['ready_at'] - (crop['ready_at'] - crop['planted_at']) * .15)
        crop['watered'] = True
        obj['revision'] += 1
    elif role in {'production', 'craft'} and isinstance(payload, dict):
        outputs = payload['outputs']
        take_job(farm, obj, payload, at, False)
        if log is not None and role == 'craft':
            row = _craft_row(log, worker, obj)
            for item, qty in outputs.items():
                row['carried'][item] = row['carried'].get(item, 0) + qty
        if role == 'craft':
            # The master puts the next remembered recipe straight back: collect (1 unit) + start (1 unit).
            again = restartable(farm, obj, level(farm['xp'])) if shift['remaining'] >= 2 else None
            if again:
                _start_craft(farm, obj, again, at, speed, f'auto-{shift["id"]}-{shift["done"] + 1}', log, worker)
                units = 2
    elif role == 'craft':
        _start_craft(farm, obj, RECIPES[payload], at, speed, f'auto-{shift["id"]}-{shift["done"]}', log, worker)
    elif role == 'animals':
        if payload:
            take_animal(farm, obj, at, False)
        else:
            start_feed(farm, obj, at, speed, False)   # helpers are never slowed by the owner's upkeep debt
    farm['stats']['automation'] += units
    return units


GENITIVE = dict(
    mill='мельницы', feedmill='кормоцеха', bakery='пекарни', kitchen='летней кухни', dairy='сыроварни', loom='мастерской',
    energy_shop='бодрильни', cannery='консервного цеха', confectionery='кондитерской', creamery='молокозавода',
    juicery='соковарни', noodle_shop='макаронной мастерской', oil_press='маслобойни', sausage_shop='колбасного цеха',
    smokehouse='коптильни', soapery='мыловарни', syrupery='сироповарни', tailor='швейной мастерской',
    teahouse='чайной беседки')


def craft_text(rows):
    """Shift journal lines, e.g. «Из мельницы на склад: ржаная мука ×3; поставлено: ржаная мука ×3.»
    (only a restart: «Мельница — поставлено: …»; only a collect: no «поставлено» clause)."""
    def items(values, names):
        return ', '.join(f'{names[k]["name"].lower()} ×{n}' for k, n in values.items())
    parts = []
    for r in rows:
        carried, started = items(r['carried'], ITEMS), items(r['started'], RECIPES)
        if carried:
            source = f'Из {GENITIVE[r["type"]]}' if r['type'] in GENITIVE else f'Из постройки «{named_building(r["type"])}»'
            parts.append(f'{source} на склад: {carried}' + (f'; поставлено: {started}.' if started else '.'))
        elif started:
            parts.append(f'{named_building(r["type"])} — поставлено: {started}.')
    return ' ' + ' '.join(parts) if parts else ''


def named_building(kind):
    from .catalog import BUILDINGS
    return BUILDINGS[kind]['name'] if kind in BUILDINGS else kind


def settle(farm, now):
    """Materialize finite paid work, as if checked at the original server times.

    Only the service invokes this, under aggregate locks in its transaction.
    No rewards derive from client time. Shifts do not renew or debit coins by
    themselves, and no work is performed after their paid deadline. A helper
    works only inside its zone (the whole farm when none is set); a zone change
    is a command, and every command settles first, so history is never rewritten.
    """
    now = tick(now)
    upgrade_state(farm)
    market.settle(farm, now)  # caravan arrival/expiry and the Moscow-day contract reset, even with no workers
    fields.settle(farm, now)  # r9 stage 15: autopilot/expired field runs and ripening, even with no workers
    workers = [(key, val, EQUIPMENT[key] if key in EQUIPMENT else HELPERS[key])
               for source in (farm['equipment'], farm['helpers']) for key, val in source.items()
               if val.get('shift') and val['shift']['status'] == 'working']
    if not workers:
        return
    ordered = ordered_objects(farm)
    boxes = {key: rect(val.get('zone')) for key, val, spec in workers}
    counts = {}
    craft_log = {}
    ended = []
    # Every pass advances one worker by at least one interval, so this bound is never reached by honest data.
    # Saved shifts may still carry fractional deadlines (older clocks were float time.time), so the floor division may yield a float.
    budget = int(sum(max(0, (min(now, v['shift']['until']) - v['shift']['next_at']) // v['shift']['interval']) + 2
                     for _, v, _ in workers)) + 10
    need(budget <= 400000, 'automation_budget', 'Превышен безопасный предел расчёта смены.', 503)
    for _ in range(budget):
        due = [(v['shift']['next_at'], k, v, spec) for k, v, spec in workers
               if v['shift']['status'] == 'working'
               and v['shift']['next_at'] <= min(now, v['shift']['until'])
               and v['shift']['remaining'] > 0]
        if not due:
            break
        at, key, val, spec = min(due, key=lambda x: (x[0], x[1]))
        shift = val['shift']
        role = shift.get('role', spec['role'])
        units = _work_once(farm, ordered, role, at, shift, boxes[key], craft_log, key)
        if units:
            shift['remaining'] -= units
            shift['done'] += units
            counts[key] = counts.get(key, 0) + units
            shift['next_at'] = at + shift['interval']
        else:
            # With several workers, one may produce feed or shorten a crop
            # deadline for another. Do not skip their chronological check slots.
            future = _next_possible(farm, ordered, role, at, boxes[key])
            if len(workers) > 1:
                shift['next_at'] = at + shift['interval']
            elif future is None:
                shift['next_at'] = at + max(1, math.floor((now - at) / shift['interval']) + 1) * shift['interval']
            else:
                steps = max(1, math.ceil((future - at) / shift['interval']))
                shift['next_at'] = at + steps * shift['interval']
        if shift['remaining'] == 0:
            shift['status'] = 'finished'
            shift['ended_at'] = at
            ended.append(key)
    else:
        need(False, 'automation_budget', 'Превышен безопасный предел расчёта смены.', 503)
    for key, val, spec in workers:
        shift = val['shift']
        if shift['status'] == 'working' and now >= shift['until']:
            shift['status'] = 'finished'
            shift['ended_at'] = shift['until']
            ended.append(key)
    if counts:
        names = '; '.join(f'{(EQUIPMENT.get(k) or HELPERS[k])["name"]}: {n}' for k, n in counts.items())
        rows = list(craft_log.values())
        event(farm, now, f'Работа команды — {names}. Выполненные действия сохранены.{craft_text(rows)}', 'automation')
        if rows:
            farm['events'][0]['details'] = rows   # additive: old clients show only ``text``
    for key in sorted(set(ended)):
        spec = EQUIPMENT.get(key) or HELPERS[key]
        event(farm, now, f'{spec["name"]}: смена завершена. Новая начнётся только по твоему решению.', 'shift')
    detect_secrets(farm, now)


def _bulk(farm, kind, data, now, speed, command_id):
    """Owner's one-tap versions of what helpers do: same transitions, deterministic order, partial when short."""
    box = rect(data['area'], 'invalid_area')
    ordered = ordered_objects(farm)
    lv = level(farm['xp'])
    if kind == 'collect_group':
        group = data['group']
        need(isinstance(group, str) and group in GROUPS, 'invalid_command', 'Неизвестная категория.', 422)
        done = 0
        for obj in ordered:
            if not in_zone(obj, box):
                continue
            if group == 'plots' and obj['type'] == 'plot' and obj.get('crop') and obj['crop']['ready_at'] <= now:
                harvest(farm, obj, now)
                done += 1
            elif group == 'animals' and obj.get('animal_job') and obj['animal_job']['ready_at'] <= now:
                take_animal(farm, obj, now)
                done += 1
            elif group == 'workshops':
                for job in [j for j in obj.get('jobs', []) if j['ready_at'] <= now]:
                    take_job(farm, obj, job, now)
                    done += 1
        need(done > 0, 'nothing_ready', 'Пока ничего не готово.')
        label = {'plots': 'грядок', 'animals': 'домиков с продукцией', 'workshops': 'готовых партий'}[group]
        return f'Собрано: {done} {label}.'
    if kind == 'feed_all':
        waiting = [o for o in ordered if in_zone(o, box) and o.get('animal') and not o.get('animal_job')]
        done = 0
        for obj in waiting:
            if can_feed(farm, obj):  # earlier houses may have used the shared feed
                start_feed(farm, obj, now, speed)
                done += 1
        need(done > 0, 'nothing_to_do', 'Некого кормить: нет свободных домиков или не хватает корма.')
        rest = len(waiting) - done
        return f'Накормлено домиков: {done}.' + (f' Остальным ({rest}) не хватило корма.' if rest else '')
    if kind == 'restart_all':
        done = 0
        for obj in ordered:
            if obj['type'] in WORKSHOP_TYPES and in_zone(obj, box):
                recipe = restartable(farm, obj, lv)
                if recipe:
                    inventory(farm, recipe['inputs'], -1)
                    obj['jobs'].append(make_job(obj, recipe, now, speed, f'bulk-{command_id}-{done}', farm))
                    mark_started(obj, recipe['id'])
                    obj['revision'] += 1
                    done += 1
        need(done > 0, 'nothing_to_do', 'Нечего повторять: нет запомненных рецептов, места в очереди или сырья.')
        return f'Повторены рецепты в мастерских: {done}.'
    # plant_many
    crop = named(CROPS, data['crop'])
    need(lv >= crop['level'], 'locked', 'Эта культура пока не открыта.')
    empty = sorted((o for o in ordered if o['type'] == 'plot' and not o.get('crop') and in_zone(o, box)),
                   key=lambda o: (o['y'], o['x'], o['id']))
    need(bool(empty), 'no_empty_plots', 'В этой области нет свободных грядок.')
    count = min(len(empty), farm['coins'] // crop['cost'])
    need(count > 0, 'insufficient_coins', 'Не хватает монет даже на одну грядку.')
    for obj in empty[:count]:
        plant(farm, obj, crop, now, speed)
    text = f'{crop["name"]}: посажено {count} из {len(empty)} свободных грядок.'
    return text + (' Монет хватило не на все — остальные ждут.' if count < len(empty) else '')


def apply_extension(farm, kind, data, now, command_id, speed, form='n'):
    lv = level(farm['xp'])
    if kind in projects.SCHEMAS:
        text = projects.apply(farm, kind, data)
        event(farm, now, text, kind)
        return text
    if kind in market.SCHEMAS:
        text = market.apply_market(farm, kind, data, now, command_id)
        event(farm, now, text, kind)
        return text
    if kind in fields.SCHEMAS:
        text = fields.apply_field(farm, kind, data, now, command_id, speed)
        event(farm, now, text, kind)
        return text
    if kind in {'buy_equipment', 'hire_helper'}:
        is_machine = kind == 'buy_equipment'
        spec = named(EQUIPMENT if is_machine else HELPERS, data['equipment' if is_machine else 'helper'])
        source = farm['equipment'] if is_machine else farm['helpers']
        need(spec['id'] not in source, 'already_owned', 'Уже в твоём хозяйстве.')
        need(lv >= spec['level'], 'locked', f'Нужен уровень {spec["level"]}.')
        pay(farm, spec['cost'])
        source[spec['id']] = dict(acquired_at=now, shift=None, total_runs=0)
        text = f'{spec["name"]}: в твоей команде!'
    elif kind == 'machine_run':
        spec = named(EQUIPMENT, data['machine'])
        need(spec['id'] in farm['equipment'], 'not_owned', 'Сначала приобрети технику.')
        need(spec['role'] in {'sow', 'reap'}, 'wrong_machine', 'Робот работает по сменам.')
        need(type(data['replant']) is bool and isinstance(data['plots'], list)
             and 1 <= len(data['plots']) <= 24, 'invalid_command', 'Выбери от 1 до 24 грядок.', 422)
        need(all(isinstance(p, dict) and set(p) == {'id', 'revision'} and isinstance(p['id'], str)
                 for p in data['plots']), 'invalid_command', 'Неверный список грядок.', 422)
        need(len({p['id'] for p in data['plots']}) == len(data['plots']), 'duplicate_plot', 'Грядка указана дважды.', 422)
        selected = []
        for entry in data['plots']:
            obj = find(farm['objects'], entry['id'])
            need(obj['type'] == 'plot' and type(entry['revision']) is int and obj['revision'] == entry['revision'],
                 'stale_object', 'Одна из грядок изменилась. Обнови план рейса.')
            selected.append(obj)
        if spec['role'] == 'sow':
            crop = named(CROPS, data['crop'])
            need(not data['replant'], 'invalid_command', 'Трактор засевает только свободные грядки.', 422)
            need(lv >= crop['level'], 'locked', 'Эта культура пока не открыта.')
            need(all(p['crop'] is None for p in selected), 'busy_plot', 'В плане есть занятая грядка.')
            need(farm['coins'] >= crop['cost'] * len(selected), 'insufficient_coins', 'Не хватает монет на весь посев.')
            for obj in selected:
                plant(farm, obj, crop, now, speed)
            text = f'Трактор засеял {len(selected)} грядок: {crop["name"]}.'
        else:
            need(data['crop'] == '', 'invalid_command', 'Комбайн сохраняет культуру каждой грядки.', 422)
            need(all(p['crop'] and p['crop']['id'] in GRAINS and p['crop']['ready_at'] <= now for p in selected),
                 'not_ready', 'Комбайн убирает только готовые зерновые.')
            seed_cost = sum(CROPS[p['crop']['id']]['cost'] for p in selected) if data['replant'] else 0
            need(farm['coins'] >= seed_cost, 'insufficient_coins', 'Не хватает монет на повторный посев.')
            for obj in selected:
                crop = CROPS[obj['crop']['id']]
                harvest(farm, obj, now)
                if data['replant']:
                    plant(farm, obj, crop, now, speed)
            text = f'Комбайн убрал {len(selected)} грядок' + (' и повторил посев.' if data['replant'] else '.')
        farm['equipment'][spec['id']]['last_run_at'] = now
        farm['equipment'][spec['id']]['total_runs'] += 1
        farm['stats']['machine_runs'] += 1
    elif kind == 'start_shift':
        val, spec = owned_worker(farm, data['worker'])
        need(spec['role'] != 'guide', 'guide', 'Проводника выбирают при отправке в лес.')
        plan = named(SHIFTS, data['shift'])
        need(lv >= plan.get('level', 1), 'locked', f'Такая смена открывается с {plan.get("level", 1)} уровня фермы.')
        need(not val.get('shift') or val['shift']['status'] != 'working', 'shift_active', 'Смена уже идёт.')
        pay(farm, plan['cost'])
        val['shift'] = dict(id=command_id, status='working', plan=plan['id'],
                            starts_at=now, until=now + duration(plan['seconds'], speed), next_at=now,
                            interval=duration(SHIFT_INTERVAL, speed), remaining=plan['actions'], done=0,
                            speed=speed, role=spec['role'], quota=plan['actions'], version=VERSION)
        text = f'{spec["name"]}: смена началась, до {plan["actions"]} полезных действий. Автопродления нет.'
    elif kind == 'stop_shift':
        val, spec = owned_worker(farm, data['worker'])
        need(val.get('shift') and val['shift']['status'] == 'working', 'no_shift', 'Активной смены нет.')
        val['shift']['status'] = 'stopped'
        val['shift']['ended_at'] = now
        text = f'{spec["name"]}: работа остановлена. Оплаченная смена не возвращается.'
    elif kind == 'set_zone':
        val, spec = owned_worker(farm, data['worker'])
        need(spec['role'] != 'guide', 'guide', 'У проводника нет рабочей зоны.')
        box = rect(data['zone'])
        if box is None:
            val.pop('zone', None)
            text = f'{spec["name"]}: работает на всей ферме.'
        else:
            val['zone'] = dict(data['zone'])
            text = f'{spec["name"]}: зона {data["zone"]["w"]}×{data["zone"]["h"]} с клетки {box[0] + 1}, {box[1] + 1}.'
    elif kind == 'collect_building':
        obj = find(farm['objects'], data['object'])
        need(any(r['building'] == obj['type'] for r in RECIPES.values()),
             'wrong_building', 'Здесь нет производственной очереди.')
        ready = sorted((j for j in obj.get('jobs', []) if j['ready_at'] <= now),
                       key=lambda j: (j['ready_at'], j['id']))
        need(ready, 'nothing_ready', 'В этом здании пока нет готовой продукции.')
        for job in ready:
            take_job(farm, obj, job, now)
        text = f'На склад отправлено готовых партий: {len(ready)}.'
    elif kind in {'collect_group', 'feed_all', 'restart_all', 'plant_many'}:
        text = _bulk(farm, kind, data, now, speed, command_id)
    elif kind == 'start_trip':
        route = named(ROUTES, data['route'])
        fishing = route.get('kind') == 'fishing'
        unlock = route_level(route)
        need(lv >= unlock, 'locked', f'{"Рыбалка" if fishing else "Тропа"} открывается с уровня {unlock}.')
        need(isinstance(data['guide'], str), 'invalid_command', 'Неверный проводник.', 422)
        need(len(farm['trips']) < 2, 'trip_limit', 'Заняты оба места для лесных вылазок и рыбалки. Сначала забери одну корзину или улов.')
        guide = named(HELPERS, data['guide']) if data['guide'] else None
        if guide:
            need(guide['role'] == 'guide' and guide['id'] in farm['helpers'], 'not_hired', 'Этот проводник ещё не нанят.')
            need(not any(t['guide'] == guide['id'] for t in farm['trips']), 'guide_busy', 'Проводник ещё не вернулся.')
        else:
            need(not any(not t['guide'] for t in farm['trips']), 'trip_active', address_g(form, 'Ты уже занят вылазкой или рыбалкой.', 'Ты уже занята вылазкой или рыбалкой.',
                                                            'Твоё место для вылазок и рыбалки уже занято.') + ' Во вторую можно отправить проводника.')
        inventory(farm, route['inputs'], -1)
        gift = pay(farm, route['cost'])
        outputs = deepcopy(route['outputs'])
        matched = bool(guide and guide['specialty'] == route['specialty'])
        if matched:
            first = next(iter(outputs))
            outputs[first] += 1
        seconds = duration(route['seconds'] * (.8 if guide else 1), speed, farm)
        trip = dict(id=command_id, route=route['id'], kind=route.get('kind', 'forest'), guide=data['guide'], started_at=now,
                    ready_at=now + seconds, outputs=outputs, xp=route['xp'],
                    secret=route.get('secret'), version=VERSION,
                    taken=dict(coins=route['cost'], gift=gift, items=deepcopy(route['inputs'])))
        if not data['guide']:                              # the player goes himself: an optional minigame for a bonus on top
            trip['game'] = trip_games.make_game(farm, command_id, route, now)
        farm['trips'].append(trip)
        farm['trip_seq'] += 1
        text = (f'Рыбалка «{route["name"]}» началась. Можно закрыть игру; улов не пропадёт.' if fishing else
                f'Вылазка «{route["name"]}» началась. Можно закрыть игру; корзина не пропадёт.')
    elif kind == 'collect_trip':
        trip = find(farm['trips'], data['trip'])
        fishing = trip_kind(trip) == 'fishing'
        need(trip['ready_at'] <= now, 'not_ready', 'Рыбалка ещё не завершена.' if fishing else 'Поход ещё не завершён.')
        outputs = trip_games.final_outputs(trip)
        inventory(farm, outputs)
        progression.grant_xp(farm, trip['xp'], 'trip', now, True)
        farm['stats']['fishing_trips' if fishing else 'forages'] += 1
        if trip.get('secret'):
            discover(farm, trip['secret'], now)
        farm['trips'].remove(trip)
        text = ('Улов отправлен на склад: ' if fishing else 'Лесная корзина разобрана: ') + ', '.join(f'{ITEMS[k]["name"]} ×{q}' for k, q in outputs.items()) + '.'
    elif kind == 'trip_play':
        text = trip_games.apply_play(farm, data, now)
    elif kind == 'abort_trip':
        from . import undo
        text = undo.abort_trip(farm, find(farm['trips'], data['trip']), now, form)
    elif kind == 'night_delivery':
        need(farm['stats']['orders'] >= 3, 'locked', 'Сначала выполни три обычных заказа.')
        need('detective' not in farm['secrets'], 'already_claimed', 'Дело о булочке уже закрыто.')
        inventory(farm, {'bread': 2, 'egg': 2}, -1)
        progression.grant_xp(farm, 15, 'secret', now, True)
        discover(farm, 'detective', now)
        text = 'Ночной завтрак доставлен. Пугало-детектив раскрывает дело и остаётся работать декором.'
    else:
        raise AssertionError('Unknown expansion command')
    detect_secrets(farm, now)
    event(farm, now, text, kind)
    return text


def validate_expansion(farm):
    market.validate_market(farm)
    fields.validate(farm)
    trip_games.validate(farm)
    projects.validate(farm)
    need(set(farm.get('equipment', {})) <= set(EQUIPMENT) and set(farm.get('helpers', {})) <= set(HELPERS),
         'invalid_team', 'Некорректный состав команды.', 500)
    for source in (farm.get('equipment', {}), farm.get('helpers', {})):
        for val in source.values():
            shift = val.get('shift')
            if shift:
                need(shift['status'] in {'working', 'finished', 'stopped'} and
                     type(shift['remaining']) is int and 0 <= shift['remaining'] <= MAX_SHIFT_ACTIONS and
                     type(shift['done']) is int and 0 <= shift['done'] <= MAX_SHIFT_ACTIONS and
                     shift['done'] + shift['remaining'] == shift.get('quota', SHIFTS[shift['plan']]['actions']),
                     'invalid_shift', 'Некорректное состояние смены.', 500)
            rect(val.get('zone'), 'invalid_zone')
    trips = farm.get('trips', [])
    need(len(trips) <= 2 and len({t['id'] for t in trips}) == len(trips), 'invalid_trips', 'Некорректные вылазки.', 500)
    need(set(farm.get('secrets', [])) <= set(SECRETS), 'invalid_secrets', 'Некорректная коллекция.', 500)
