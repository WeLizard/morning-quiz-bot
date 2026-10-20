"""Small, owner-only village errands and Dasha's bounded presence prank."""
from .catalog import tick, VILLAGE_QUESTS
from .domain import need, inventory, pay, event
from . import progression

QUESTS = VILLAGE_QUESTS
LEGACY_NPC_NAMES = {'Петух Гриша': 'Петух Олег'}
GRACE = 45
LEASE = 25
COOLDOWN = 86400


def state(farm):
    s = farm.setdefault('village_errands', dict(quests={}, presence=None, theft_next_at=0, theft_total=0))
    quests = s['quests']
    if 'Петух Гриша' in quests:
        old = quests['Петух Гриша']
        has_current = 'Петух Олег' in quests
        current = quests.get('Петух Олег')
        for q in ((old, current) if has_current else (old,)):
            need(type(q) is dict and type(q.get('day')) is int and
                 q.get('phase') in {'available', 'active', 'done'},
                 'invalid_village', 'Некорректное состояние деревни.', 500)
        if not has_current:
            quests['Петух Олег'] = old
        else:
            # A completed day outranks an active duplicate on that day. An
            # active quest from a later day remains deliverable after a rename.
            quests['Петух Олег'] = max((old, current),
                                      key=lambda q: (q['phase'] != 'available', q['day'], q['phase'] == 'done'))
        del quests['Петух Гриша']
    return s


def public(farm, now):
    s = state(farm)
    day = int((tick(now) + 10800) // 86400)
    return dict(quests={npc:(q['phase'] if q['day'] == day or q['phase'] == 'active' else 'available')
                        for npc, q in s['quests'].items()}, theft_next_at=s['theft_next_at'],
                theft_total=s['theft_total'])


def validate(farm):
    s = state(farm)
    need(set(s) == {'quests', 'presence', 'theft_next_at', 'theft_total'} and
         type(s['theft_next_at']) is int and s['theft_next_at'] >= 0 and
         type(s['theft_total']) is int and s['theft_total'] >= 0 and
         set(s['quests']) <= set(QUESTS) and
         all(type(q.get('day')) is int and q.get('phase') in {'available', 'active', 'done'}
             for q in s['quests'].values()), 'invalid_village', 'Некорректное состояние деревни.', 500)
    p = s['presence']
    if p is not None:
        need(set(p) == {'session', 'entered_at', 'last_at', 'talked'} and
             isinstance(p['session'], str) and len(p['session']) == 36 and
             type(p['entered_at']) is int and type(p['last_at']) is int and
             p['entered_at'] <= p['last_at'] and type(p['talked']) is bool,
             'invalid_village', 'Некорректное присутствие в деревне.', 500)


def quest(farm, npc, now):
    need(isinstance(npc,str), 'unknown_resident', 'Житель не найден.', 422)
    npc = LEGACY_NPC_NAMES.get(npc, npc)
    need(npc in QUESTS, 'unknown_resident', 'Житель не найден.', 422)
    day = int((tick(now) + 10800) // 86400)
    return state(farm)['quests'].setdefault(npc, dict(day=day, phase='available'))


def act(farm, npc, action, now):
    need(isinstance(npc,str), 'unknown_resident', 'Житель не найден.', 422)
    npc = LEGACY_NPC_NAMES.get(npc, npc)
    q = quest(farm, npc, now)
    day = int((tick(now) + 10800) // 86400)
    if q['day'] != day and q['phase'] != 'active':
        q.update(day=day, phase='available')
    if action == 'take':
        need(q['phase'] == 'available', 'quest_phase', 'Задание уже взято или выполнено.')
        q['phase'] = 'active'
        if npc == 'Лиса Даша' and state(farm)['presence']:
            state(farm)['presence']['talked'] = True
        return f'{npc}: задание принято.'
    need(action == 'deliver', 'invalid_command', 'Неизвестное действие.', 422)
    need(q['phase'] == 'active', 'quest_phase', 'Сначала возьми задание у жителя.')
    spec = QUESTS[npc]
    inventory(farm, {spec['item']: spec['qty']}, -1)
    farm['coins'] += spec['coins']
    progression.grant_xp(farm, spec['xp'], 'order', now, True)
    q['day'] = day
    q['phase'] = 'done'
    if npc == 'Лиса Даша' and state(farm)['presence']:
        state(farm)['presence']['talked'] = True
    return f'{npc} благодарит! +{spec["coins"]} монет.'


def presence(farm, action, session, now):
    """Only a live, uninterrupted server-observed visit can trigger one theft."""
    now = tick(now)
    s = state(farm)
    p = s['presence']
    if action == 'enter':
        s['presence'] = dict(session=session, entered_at=now, last_at=now, talked=False)
        return 0
    need(isinstance(action,str) and action in {'pulse', 'talk', 'leave'}, 'invalid_command', 'Неизвестное действие.', 422)
    if not p or p['session'] != session:
        return 0
    if action == 'leave':
        s['presence'] = None
        return 0
    if now - p['last_at'] > LEASE:
        p.update(entered_at=now, last_at=now)
    else:
        p['last_at'] = now
    if action == 'talk':
        p['talked'] = True
        return 0
    if p['talked'] or now - p['entered_at'] < GRACE or now < s['theft_next_at']:
        return 0
    amount = min(2, farm['coins'])
    if amount:
        pay(farm, amount)
        s['theft_total'] += amount
        event(farm, now, f'Лиса Даша стащила {amount} мон. из кармана.', 'village_theft')
    s['theft_next_at'] = now + COOLDOWN
    p['talked'] = True
    return amount
