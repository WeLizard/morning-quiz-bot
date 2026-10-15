"""Small house projects with physical, per-project goods escrow."""
from copy import deepcopy


HOME_PROJECTS = {
    'lake_pier': {
        'id': 'lake_pier', 'name': 'Причал у озера', 'level': 1,
        'description': 'Помоги обустроить причал для прогулок у воды.',
        'stages': [
            {'name': 'Доски и настил', 'description': 'Филиныч сделает доски/настил.',
             'needs': {'wood': 6}},
            {'name': 'Угощение для рабочих', 'description': 'Принеси еду для завершения работ.',
             'needs': {'egg': 4, 'carrot': 4}},
        ],
    },
    'tea_arbor': {
        'id': 'tea_arbor', 'name': 'Чайная беседка', 'level': 2,
        'description': 'Устрой место для встреч и чаепитий.',
        'stages': [
            {'name': 'Каркас беседки', 'description': 'Принеси древесину для стоек, лавок и крыши.',
             'needs': {'wood': 8}},
            {'name': 'Чайный стол', 'description': 'Подготовь угощение к открытию.',
             'needs': {'bread': 4, 'egg': 4}},
        ],
    },
    'flower_entry': {
        'id': 'flower_entry', 'name': 'Цветочный вход', 'level': 2,
        'description': 'Укрась вход в деревню цветами и зеленью.',
        'stages': [
            {'name': 'Ограждение и ящики', 'description': 'Принеси древесину для ограждения и цветочных ящиков.',
             'needs': {'wood': 4}},
            {'name': 'Зелень у входа', 'description': 'Посади клевер и душистые травы в подготовленные ящики.',
             'needs': {'clover': 6, 'herbs': 4}},
        ],
    },
}

# Saved farms may have already placed real goods into this escrow.
# Keep each reserved stage's original recipe until delivery or release.
LEGACY_LAKE_NEEDS = {'wheat': 6, 'flour': 2}
V2_NEEDS = {
    'lake_pier': ({'wood': 6}, {'egg': 4, 'carrot': 4}),
    'tea_arbor': ({'flour': 4, 'carrot': 4}, {'bread': 4, 'egg': 4}),
    'flower_entry': ({'wheat': 6, 'carrot': 4}, {'herbs': 4, 'bread': 2}),
}

SCHEMAS = {
    'project_select': {'project'},
    'project_reserve': {'project', 'stage', 'revision'},
    'project_release': {'project', 'stage', 'revision'},
    'project_deliver': {'project', 'stage', 'revision'},
}


def initial_state():
    return {'version': 3, 'active': None,
            'entries': {key: {'stage': 0, 'revision': 0, 'reserved': {}} for key in HOME_PROJECTS}}


def upgrade_state(farm):
    """Existing farms gain projects without changing balances or inventory."""
    if 'home_projects' not in farm:
        farm['home_projects'] = initial_state()
        return
    state = farm['home_projects']
    validate(farm)
    if state['version'] == 3:
        return
    for key, entry in state['entries'].items():
        if entry['stage'] == len(HOME_PROJECTS[key]['stages']):
            continue
        previous = effective_needs(state, key, entry)
        if entry['reserved']:
            entry['legacy_needs'] = dict(previous)
        elif previous != HOME_PROJECTS[key]['stages'][entry['stage']]['needs']:
            entry['revision'] += 1  # reject a cached command for the old recipe
    state['version'] = 3


def effective_needs(state, key, entry):
    """One recipe decision for commands, validation and owner UI state."""
    if 'legacy_needs' in entry:
        return entry['legacy_needs']
    if state['version'] == 1 and key == 'lake_pier' and entry['stage'] == 0:
        return LEGACY_LAKE_NEEDS
    if state['version'] in {1, 2}:
        return V2_NEEDS[key][entry['stage']]
    return HOME_PROJECTS[key]['stages'][entry['stage']]['needs']


def public_state(farm):
    state = farm.get('home_projects') or initial_state()
    return {'active': state['active'],
            'entries': {key: {'stage': entry['stage']} for key, entry in state['entries'].items()}}


def owner_state(farm):
    """Owner-only recipes and hints derived from actual production catalogs."""
    from .catalog import CROPS, RECIPES, ANIMALS, ROUTES, BUILDINGS, route_level

    state = deepcopy(farm.get('home_projects') or initial_state())
    materials = set()
    for key, entry in state['entries'].items():
        entry['needs'] = (dict(effective_needs(state, key, entry))
                          if entry['stage'] < len(HOME_PROJECTS[key]['stages']) else {})
        materials.update(entry['needs'])
    sources = {item: [] for item in sorted(materials)}
    for item in sources:
        if item in CROPS:
            crop = CROPS[item]
            sources[item].append(dict(kind='crop', id=item, name=crop['name'], level=crop['level']))
        for kind, catalog in (('recipe', RECIPES), ('animal', ANIMALS), ('route', ROUTES)):
            for key, spec in catalog.items():
                if item not in spec['outputs']:
                    continue
                source = dict(kind=kind, id=key, name=spec['name'],
                              level=route_level(spec) if kind == 'route' else spec['level'],
                              inputs=deepcopy(spec['inputs']))
                if 'building' in spec:
                    building = BUILDINGS[spec['building']]
                    source.update(building=spec['building'], building_name=building['name'],
                                  level=max(source['level'], building['level']))
                sources[item].append(source)
    state['material_sources'] = sources
    return state


def apply(farm, kind, data):
    from .catalog import ITEMS, level
    from .domain import inventory, need

    need(kind in SCHEMAS, 'unknown_command', 'Неизвестное действие.', 422)
    key = data['project']
    need(type(key) is str and key in HOME_PROJECTS,
         'unknown_project', 'Проект не найден.', 422)
    spec = HOME_PROJECTS[key]
    state = farm['home_projects']
    entry = state['entries'][key]
    need(level(farm['xp']) >= spec['level'], 'locked',
         f'Проект открывается с уровня {spec["level"]}.')
    if kind == 'project_select':
        need(state['active'] != key, 'already_selected', 'Этот проект уже выбран.')
        state['active'] = key
        return f'Выбран проект «{spec["name"]}».'

    stage, revision = data['stage'], data['revision']
    need(type(stage) is int and 0 <= stage < len(spec['stages']) and
         type(revision) is int and revision >= 0,
         'invalid_command', 'Некорректный этап или версия проекта.', 422)
    need(state['active'] == key, 'project_inactive', 'Сначала выбери проект в доме.')
    need(entry['stage'] < len(spec['stages']), 'project_finished', 'Проект уже завершён.')
    need(entry['stage'] == stage and entry['revision'] == revision,
         'stale_project', 'Проект изменился. Обнови ферму.')
    needs = effective_needs(state, key, entry)
    reserved = entry['reserved']
    if kind == 'project_reserve':
        additions = {item: min(qty - reserved.get(item, 0), farm['inventory'].get(item, 0))
                     for item, qty in needs.items()}
        additions = {item: qty for item, qty in additions.items() if qty > 0}
        need(additions, 'missing_goods', 'На складе пока нет нужных товаров.')
        inventory(farm, additions, -1)
        for item, qty in additions.items():
            reserved[item] = reserved.get(item, 0) + qty
        text = 'На проект передано: ' + ', '.join(f'{ITEMS[item]["name"]} ×{qty}' for item, qty in additions.items()) + '.'
    elif kind == 'project_release':
        need(reserved, 'nothing_reserved', 'Для этого этапа ничего не зарезервировано.')
        need(all(farm['inventory'].get(item, 0) + qty <= 10**9 for item, qty in reserved.items()),
             'inventory_full', 'На складе недостаточно места для возврата.')
        inventory(farm, reserved)
        entry['reserved'] = {}
        entry.pop('legacy_needs', None)
        text = 'Товары проекта возвращены на склад.'
    else:
        need(all(reserved.get(item, 0) == qty for item, qty in needs.items()),
             'project_incomplete', 'Сначала собери все товары для этапа.')
        entry['reserved'] = {}
        entry.pop('legacy_needs', None)
        entry['stage'] += 1
        text = (f'Проект «{spec["name"]}» завершён.' if entry['stage'] == len(spec['stages']) else
                f'Этап проекта «{spec["name"]}» завершён. Открыт следующий этап.')
    entry['revision'] += 1
    return text


def has_reserved(farm):
    state = farm.get('home_projects')
    return bool(state and any(entry['reserved'] for entry in state['entries'].values()))


def validate(farm):
    from .catalog import ITEMS
    from .domain import need

    state = farm.get('home_projects')
    if state is None:  # legacy farms are upgraded when opened or settled
        return
    need(type(state) is dict and set(state) == {'version', 'active', 'entries'} and
         type(state['version']) is int and state['version'] in {1, 2, 3} and
         (state['active'] is None or type(state['active']) is str and state['active'] in HOME_PROJECTS) and
         type(state['entries']) is dict and set(state['entries']) == set(HOME_PROJECTS),
         'invalid_projects', 'Некорректное состояние проектов.', 500)
    for key, entry in state['entries'].items():
        needs_legacy = False
        if type(entry) is dict and 'legacy_needs' in entry:
            stage = entry.get('stage')
            if type(stage) is int and 0 <= stage < len(HOME_PROJECTS[key]['stages']):
                known = [V2_NEEDS[key][stage], HOME_PROJECTS[key]['stages'][stage]['needs']]
                if key == 'lake_pier' and stage == 0:
                    known.append(LEGACY_LAKE_NEEDS)
                legacy = entry['legacy_needs']
                needs_legacy = (type(legacy) is dict and
                                all(type(qty) is int for qty in legacy.values()) and
                                ((state['version'] == 3 and legacy in known) or
                                 (state['version'] == 2 and key == 'lake_pier' and stage == 0 and
                                  legacy == LEGACY_LAKE_NEEDS)))
                needs_legacy = needs_legacy and type(entry.get('reserved')) is dict and bool(entry['reserved'])
        fields = {'stage', 'revision', 'reserved'} | ({'legacy_needs'} if needs_legacy else set())
        need(type(entry) is dict and set(entry) == fields and
             type(entry['stage']) is int and 0 <= entry['stage'] <= len(HOME_PROJECTS[key]['stages']) and
             type(entry['revision']) is int and entry['revision'] >= 0 and
             type(entry['reserved']) is dict,
             'invalid_projects', 'Некорректное состояние проекта.', 500)
        needs = (effective_needs(state, key, entry)
                 if entry['stage'] < len(HOME_PROJECTS[key]['stages']) else {})
        need(all(item in ITEMS and item in needs and type(qty) is int and
                 1 <= qty <= needs[item] for item, qty in entry['reserved'].items()),
             'invalid_projects', 'Некорректный резерв проекта.', 500)
