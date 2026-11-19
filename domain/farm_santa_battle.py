"""Version 1 of the «Битва с Сантой» turn-based battle (docs/tasks/FARM_SANTA_BATTLE.md).

Integers only, no randomness at play time: everything the enemies do comes from the plan (``make_plan``) and the state, so
the client (qw_farm/static/santa-battle-engine.js, a line-by-line mirror) and the server replay the same battle from the
same log. The client runs the battle locally without a request per turn; the server replays the whole log at the end.

A round: every standing hero acts in order (unless chained), then every standing enemy carries out the move it announced at
the start of the round (unless frozen), then in battle 3 the reindeer sleigh sweeps the square every fourth round.
Log entry: ``[hero, action, target, press_ms]`` — target is an enemy or hero id or None, press_ms is the tap on the accuracy
bar for attacks (None = calm mode or no tap).
"""
from hashlib import sha256

VERSION = 1
TTL = 900
MAX_ROUNDS = 30
MAX_ITEMS = 3
MAX_LOG = 120
BAR_MS = 1200
ZONE_MS = 260

HEROES = ('player', 'ded_moroz', 'snegurochka')
ENEMIES = ('krampus', 'santa')
HERO_HP = {'player': 100, 'ded_moroz': 140, 'snegurochka': 90}
# power: the enemies' damage in per cent (a lone enemy hits harder); par: rounds for ★★★
BATTLES = {
    1: {'enemies': {'krampus': 160}, 'power': 260, 'par': 4, 'reindeer': False},
    2: {'enemies': {'santa': 240}, 'power': 215, 'par': 7, 'reindeer': False},
    3: {'enemies': {'krampus': 150, 'santa': 210}, 'power': 100, 'par': 11, 'reindeer': True},
}
ATTACKS = {'snowball': ('player', 12), 'staff': ('ded_moroz', 18), 'icestar': ('snegurochka', 10)}
BLIZZARD = 10
SKILLS = {'wall': ('player', 3), 'blizzard': ('ded_moroz', 2), 'freeze': ('snegurochka', 3), 'song': ('snegurochka', 3)}
SONG_HEAL = 15
ITEMS = {'pie': 50, 'pancake': 25, 'gingerbread': 20, 'tea': 10, 'honey': 0}
SWITCH, COAL, HOHOHO, CANDY, REINDEER = 24, 28, 15, 20, 12
ROAR_ROUNDS = 2


def make_plan(seed, battle):
    if battle not in BATTLES:
        raise ValueError('battle')
    digest = sha256(f'{seed}:{battle}'.encode()).digest()
    more = sha256(digest).digest()
    raw = digest + more
    zones = []
    for i in range(60):
        start = 180 + (raw[i % 64] * 256 + raw[(i + 7) % 64]) % (BAR_MS - ZONE_MS - 260)
        zones.append([start, start + ZONE_MS])
    return dict(version=VERSION, battle=battle, bar_ms=BAR_MS, zones=zones,
                targets=[b % 6 for b in raw[:40]], gifts=[1 if b % 3 == 0 else 0 for b in raw[40:60]])


def new_state(plan):
    spec = BATTLES[plan['battle']]
    enemies = [e for e in ENEMIES if e in spec['enemies']]
    hp = {h: HERO_HP[h] for h in HEROES}
    hp.update(spec['enemies'])
    state = dict(battle=plan['battle'], round=1, hp=hp, max=dict(hp), enemies=enemies,
                 cd={s: 0 for s in SKILLS}, chain=[], frozen=[], sack=False, rage=0, wall=False, honey=[],
                 items={}, n_items=0, bar=0, tk=0, gk=0, er={e: 0 for e in enemies}, intents={}, turn=0, outcome=None)
    _start_round(plan, state)
    return state


def _alive(state, ids):
    return [i for i in ids if state['hp'][i] > 0]


def _target(plan, state):
    alive = _alive(state, HEROES)
    k = plan['targets'][state['tk'] % len(plan['targets'])]
    state['tk'] += 1
    return alive[k % len(alive)]


def _intent(plan, state, enemy):
    state['er'][enemy] += 1
    r = state['er'][enemy]
    if enemy == 'krampus':
        if r % 3 == 0:
            return dict(move='chain', target=_target(plan, state))
        if r % 4 == 2 and state['rage'] == 0:
            return dict(move='roar', target=None)
        return dict(move='switch', target=_target(plan, state))
    if r % 4 == 0:
        return dict(move='sack', target=None)
    if r % 2 == 1:
        gift = plan['gifts'][state['gk'] % len(plan['gifts'])]
        state['gk'] += 1
        if gift and state['hp']['santa'] < state['max']['santa']:
            return dict(move='candy', target=None)
        return dict(move='coal', target=_target(plan, state))
    return dict(move='hohoho', target=None)


def _start_round(plan, state):
    state['intents'] = {e: _intent(plan, state, e) for e in _alive(state, state['enemies'])}
    state['turn'] = 0
    _skip_to_actor(plan, state, [])


def actor(state):
    """The hero whose move is awaited, or None when the battle is over."""
    return None if state['outcome'] else HEROES[state['turn']]


def legal(state):
    """Moves the awaited hero may make: list of [action, [targets]] (an empty target list = no target)."""
    hero = actor(state)
    if hero is None:
        return []
    enemies, heroes = _alive(state, state['enemies']), _alive(state, HEROES)
    moves = [[a, enemies] for a, (h, _) in ATTACKS.items() if h == hero]
    for skill, (h, _) in SKILLS.items():
        if h == hero and state['cd'][skill] == 0:
            moves.append([skill, enemies if skill == 'freeze' else []])
    if state['n_items'] < MAX_ITEMS:
        for item in ITEMS:
            moves.append([item, [] if item == 'gingerbread' else heroes])
    return moves


def _bar(plan, state, press):
    zone = plan['zones'][state['bar'] % len(plan['zones'])]
    state['bar'] += 1
    return press is not None and zone[0] <= press <= zone[1]


def _hit_enemy(state, enemy, amount, events, by, bonus):
    if enemy == 'santa' and state['sack']:
        state['sack'] = False
        events.append(dict(t='miss', by=by, to=enemy, why='sack'))
        return
    state['hp'][enemy] = max(0, state['hp'][enemy] - amount)
    events.append(dict(t='hit', by=by, to=enemy, amount=amount, bonus=bonus))
    if state['hp'][enemy] == 0:
        events.append(dict(t='down', who=enemy))


def _hit_hero(state, hero, amount, events, by):
    amount = amount * BATTLES[state['battle']]['power'] // 100
    if state['rage'] and by == 'krampus':
        amount = amount * 13 // 10
    if state['wall']:
        amount //= 2
    state['hp'][hero] = max(0, state['hp'][hero] - amount)
    events.append(dict(t='hit', by=by, to=hero, amount=amount, bonus=False))
    if state['hp'][hero] == 0:
        events.append(dict(t='down', who=hero))
        if hero in state['chain']:
            state['chain'].remove(hero)


def _heal(state, who, amount, events, by):
    if state['hp'][who] == 0:
        return
    got = min(amount, state['max'][who] - state['hp'][who])
    state['hp'][who] += got
    events.append(dict(t='heal', by=by, to=who, amount=got))


def _check_end(state):
    if not _alive(state, state['enemies']):
        state['outcome'] = 'win'
    elif not _alive(state, HEROES):
        state['outcome'] = 'lose'
    return state['outcome'] is not None


def act(plan, state, entry):
    """Apply one hero move; then run the enemy phase when the round's heroes are done. Returns the events."""
    if state['outcome']:
        raise ValueError('over')
    if type(entry) is not list or len(entry) != 4:
        raise ValueError('entry')
    hero, action, target, press = entry
    if hero != actor(state):
        raise ValueError('actor')
    if press is not None and (type(press) is not int or isinstance(press, bool) or not 0 <= press <= BAR_MS):
        raise ValueError('press')
    move = next((m for m in legal(state) if m[0] == action), None)
    if move is None:
        raise ValueError('action')
    if move[1]:
        if target not in move[1]:
            raise ValueError('target')
    elif target is not None:
        raise ValueError('target')
    events = []
    if action in ATTACKS or action == 'blizzard':
        bonus = _bar(plan, state, press)
        base = BLIZZARD if action == 'blizzard' else ATTACKS[action][1]
        amount = base * 3 // 2 if bonus else base
        if hero in state['honey']:
            state['honey'].remove(hero)
            amount *= 2
        for enemy in (_alive(state, state['enemies']) if action == 'blizzard' else [target]):
            _hit_enemy(state, enemy, amount, events, hero, bonus)
    elif press is not None:
        raise ValueError('press')
    elif action == 'wall':
        state['wall'] = True
        events.append(dict(t='wall', by=hero))
    elif action == 'freeze':
        if target not in state['frozen']:
            state['frozen'].append(target)
        events.append(dict(t='freeze', by=hero, to=target))
    elif action == 'song':
        for h in _alive(state, HEROES):
            _heal(state, h, SONG_HEAL, events, hero)
    else:
        state['n_items'] += 1
        state['items'][action] = state['items'].get(action, 0) + 1
        events.append(dict(t='item', by=hero, item=action, to=target))
        if action == 'gingerbread':
            for h in _alive(state, HEROES):
                _heal(state, h, ITEMS[action], events, hero)
        elif action == 'tea':
            if target in state['chain']:
                state['chain'].remove(target)
            _heal(state, target, ITEMS[action], events, hero)
        elif action == 'honey':
            if target not in state['honey']:
                state['honey'].append(target)
        else:
            _heal(state, target, ITEMS[action], events, hero)
    if action in SKILLS:
        state['cd'][action] = SKILLS[action][1]
    if _check_end(state):
        return events
    state['turn'] += 1
    _skip_to_actor(plan, state, events)
    return events


def _skip_to_actor(plan, state, events):
    """Move ``turn`` to the next hero who can act; when none is left, run the enemy phase and start the next round."""
    while not state['outcome']:
        while state['turn'] < len(HEROES):
            hero = HEROES[state['turn']]
            if state['hp'][hero] > 0 and hero not in state['chain']:
                return
            if hero in state['chain'] and state['hp'][hero] > 0:
                state['chain'].remove(hero)
                events.append(dict(t='skip', who=hero, why='chain'))
            state['turn'] += 1
        _enemy_phase(plan, state, events)
        if _check_end(state):
            return
        state['round'] += 1
        if state['round'] > MAX_ROUNDS:
            state['outcome'] = 'lose'
            events.append(dict(t='timeout'))
            return
        state['intents'] = {e: _intent(plan, state, e) for e in _alive(state, state['enemies'])}
        state['turn'] = 0
        events.append(dict(t='round', n=state['round']))


def _enemy_phase(plan, state, events):
    for enemy in _alive(state, state['enemies']):
        intent = state['intents'].get(enemy)
        if intent is None:
            continue
        if enemy in state['frozen']:
            state['frozen'].remove(enemy)
            events.append(dict(t='skip', who=enemy, why='freeze'))
            continue
        move, target = intent['move'], intent['target']
        if target is not None and state['hp'][target] == 0:
            target = _target(plan, state) if _alive(state, HEROES) else None
        events.append(dict(t='move', who=enemy, move=move, to=target))
        if move == 'switch':
            _hit_hero(state, target, SWITCH, events, enemy)
        elif move == 'chain':
            if target not in state['chain']:
                state['chain'].append(target)
        elif move == 'roar':
            state['rage'] = ROAR_ROUNDS + 1
        elif move == 'coal':
            _hit_hero(state, target, COAL, events, enemy)
        elif move == 'hohoho':
            for h in _alive(state, HEROES):
                _hit_hero(state, h, HOHOHO, events, enemy)
        elif move == 'candy':
            _heal(state, 'santa', CANDY, events, enemy)
        elif move == 'sack':
            state['sack'] = True
        if _check_end(state):
            return
    if BATTLES[state['battle']]['reindeer'] and state['round'] % 4 == 0:
        events.append(dict(t='move', who='reindeer', move='sleigh', to=None))
        for h in _alive(state, HEROES):
            _hit_hero(state, h, REINDEER, events, 'reindeer')
        if _check_end(state):
            return
    state['wall'] = False
    state['frozen'] = [e for e in state['frozen'] if state['hp'][e] > 0]
    state['rage'] = max(0, state['rage'] - 1)
    for skill in state['cd']:
        state['cd'][skill] = max(0, state['cd'][skill] - 1)


def stars(state):
    if state['outcome'] != 'win':
        return 0
    if any(state['hp'][h] == 0 for h in HEROES):
        return 1
    return 3 if state['round'] <= BATTLES[state['battle']]['par'] else 2


def replay(plan, log):
    """Replay a whole log; raises ValueError for a malformed or illegal log or one that does not finish the battle."""
    if type(log) is not list or not log or len(log) > MAX_LOG:
        raise ValueError('log')
    state = new_state(plan)
    events = []
    for entry in log:
        events.append(act(plan, state, entry))
    if state['outcome'] is None:
        raise ValueError('unfinished')
    return dict(outcome=state['outcome'], rounds=state['round'], stars=stars(state), items=state['items'],
                hp=state['hp'])
