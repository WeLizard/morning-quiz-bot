"""Trip minigames: "Порыбачу сам" (cast, bite, strike) and "Пойду сам" (short forest gathering). See docs/tasks/FARM_TRIP_MINIGAMES.md.

A trip started WITHOUT a guide gets ``trip['game']`` (a plan generated from sha256(seed) and shipped to the client, so the client
never hashes). The autopilot is simply not playing: the trip returns the base outputs (q = 1000). A played game gives
``q = 1000 + 250 * score // 1000`` (never below the autopilot) and ``collect_trip`` multiplies every output by q (half up). The game
changes neither the trip time nor the XP. ``trip_play {trip, log}`` is the only command: the server replays ``log`` itself,
ignores every number of the client, and closes the game once.

FISHING.  ``plan['casts'][i] = {phase, zone, wait}``; the log is ``[[aim_ms, strike_ms | null], ...]`` (absolute ms from the game
start).  The aiming mark runs a triangle wave of period ``MARK_PERIOD`` shifted by ``phase``; ``acc`` = closeness of the mark (at
``aim_ms``) to the fish zone (permille).  The float dips at ``aim_ms + wait``; a strike is valid in
``[bite + REACT, bite + REACT + window]`` (earlier = fish scared, later = fish gone) and scores best in the middle.
cast = (4 * acc + 6 * timing) // 10 if the strike is valid else 0; score = mean over casts.

FORAGING.  ``plan = {w, h, start, budget, items: {cell: item_id}, traps: [cell], gold}``; the log is a ``UDLR`` string.  Every move
costs 1 step of the budget, a trap costs 2 more (once).  score = min(1000, 1000 * collected // gold) where ``gold`` is the number of
items on a random reference walk of ``budget`` steps (so it is reachable).  Integers only.
"""
from hashlib import sha256
from .catalog import ITEMS
from .domain import need, find

SCHEMAS = {'trip_play': {'trip', 'log'}}
GAME_TTL = 900                 # seconds after the start of the trip during which the game may be played
BONUS = 250                    # permille over the autopilot at score 1000
Q_AUTO = 1000
MARK_PERIOD = 1600             # ms, full back-and-forth of the cast mark
DEAD_ZONE = 60                 # permille around the zone centre that counts as perfect
ACC_SPAN = 300                 # permille from the dead zone to accuracy 0
REACT = 150                    # ms: faster than this after the bite is impossible (counted as a miss)
WINDOW_BASE = {'pond_bank': 900, 'lake_inlet': 800, 'river_bend': 700}
CASTS = {'pond_bank': 3, 'lake_inlet': 4, 'river_bend': 5}
WAIT_MIN, WAIT_SPAN = 1500, 3500
FIRST_AIM_MS = 500
MAX_MS = 600_000
SKEW_MS = 2000                 # tolerance of the client clock against the server
STEP_CS = 20                   # minimum 0.2 s per step of the forest walk
GRID = 6
TRAP_COST = 2
BUDGET = {'timber_path': 12, 'mushroom_wood': 12, 'berry_edge': 12, 'herb_meadow': 14, 'old_grove': 16, 'night_glade': 14}
TRAPS = {'night_glade': 0}
DEFAULT_TRAPS = 3
EXTRA_ITEMS = 3
DIRS = {'U': (0, -1), 'D': (0, 1), 'L': (-1, 0), 'R': (1, 0)}


def public_rules():
    return dict(ttl=GAME_TTL, bonus=BONUS, mark_period=MARK_PERIOD, dead_zone=DEAD_ZONE, acc_span=ACC_SPAN, react=REACT,
                window=WINDOW_BASE, casts=CASTS, first_aim_ms=FIRST_AIM_MS, grid=GRID, trap_cost=TRAP_COST, budget=BUDGET,
                step_cs=STEP_CS)


def game_kind(route):
    return 'fish' if route.get('kind') == 'fishing' else 'forage'


def _stream(seed, label):
    i = 0
    while True:
        for byte in sha256(f'{seed}:{label}:{i}'.encode()).digest():
            yield byte
        i += 1


def _u16(rng):
    return next(rng) * 256 + next(rng)


# ------------------------------------------------------------------------------------------------ plans
def make_fish_plan(seed, route_id):
    rng = _stream(seed, 'fish')
    casts = [dict(phase=_u16(rng) % MARK_PERIOD, zone=150 + _u16(rng) % 701, wait=WAIT_MIN + _u16(rng) % WAIT_SPAN)
             for _ in range(CASTS.get(route_id, 3))]
    return dict(casts=casts, window=WINDOW_BASE.get(route_id, 900))


def make_forage_plan(seed, route, with_path=False):
    rng = _stream(seed, 'forage')
    budget = BUDGET.get(route['id'], 12)
    start = (GRID - 1) * GRID                       # bottom-left corner
    walk, seen, cur, moves = [], {start}, start, ''
    for _ in range(budget):
        x, y = cur % GRID, cur // GRID
        options = [(x + dx, y + dy) for dx, dy in DIRS.values() if 0 <= x + dx < GRID and 0 <= y + dy < GRID]
        fresh = [c for c in options if c[1] * GRID + c[0] not in seen]
        pick = (fresh or options)[next(rng) % len(fresh or options)]
        moves += next(ch for ch, (dx, dy) in DIRS.items() if (x + dx, y + dy) == pick)
        cur = pick[1] * GRID + pick[0]
        walk.append(cur)
        seen.add(cur)
    walk_cells = list(dict.fromkeys(walk))
    kinds = list(route['outputs'])
    items = {}
    for cell in walk_cells:
        if next(rng) % 100 < 60:
            items[cell] = kinds[next(rng) % len(kinds)]
    if not items:
        items[walk_cells[0]] = kinds[0]
    gold = len(items)
    free = [c for c in range(GRID * GRID) if c != start and c not in walk_cells]
    traps = []
    for _ in range(TRAPS.get(route['id'], DEFAULT_TRAPS)):
        if free:
            traps.append(free.pop(next(rng) % len(free)))
    for _ in range(EXTRA_ITEMS):
        if free:
            items[free.pop(next(rng) % len(free))] = kinds[next(rng) % len(kinds)]
    plan = dict(w=GRID, h=GRID, start=start, budget=budget, items={str(k): v for k, v in items.items()}, traps=sorted(traps), gold=gold)
    return (plan, moves) if with_path else plan


def make_game(farm, trip_id, route, now):
    """Plan for a trip made by the player himself (no guide); stored in ``trip['game']``."""
    seed = sha256(f'{farm["id"]}:{trip_id}:{route["id"]}'.encode()).hexdigest()[:24]
    kind = game_kind(route)
    plan = make_fish_plan(seed, route['id']) if kind == 'fish' else make_forage_plan(seed, route)
    return dict(kind=kind, state='open', seed=seed, expires_at=now + GAME_TTL, q=Q_AUTO, score=0, plan=plan)


# ------------------------------------------------------------------------------------------------ pure rules
def mark_position(t, phase):
    """Position of the aiming mark, permille 0..1000 (triangle wave)."""
    m = (t + phase) % MARK_PERIOD
    half = MARK_PERIOD // 2
    return m * 1000 // half if m <= half else (MARK_PERIOD - m) * 1000 // half


def accuracy(aim_ms, cast):
    d = abs(mark_position(aim_ms, cast['phase']) - cast['zone'])
    return max(0, 1000 - max(0, d - DEAD_ZONE) * 1000 // ACC_SPAN)


def strike_score(strike_ms, bite_ms, window):
    """Timing score 0..1000 for a strike at ``strike_ms`` (0 = scared, gone or impossibly fast)."""
    d = strike_ms - bite_ms
    if d < REACT or d > REACT + window:
        return 0
    mid = window // 2
    return 1000 - abs(d - REACT - mid) * 600 // max(1, mid)


def cast_end(aim_ms, strike_ms, cast, window):
    """When the next cast may begin: after the strike, or when the missed bite window is over."""
    return strike_ms if strike_ms is not None else aim_ms + cast['wait'] + REACT + window


def fish_score(plan, log):
    """Permille score of a fishing log, or None when the log breaks the rules."""
    casts, window = plan['casts'], plan['window']
    if not (isinstance(log, list) and len(log) == len(casts)):
        return None
    total, free_at = 0, FIRST_AIM_MS
    for cast, entry in zip(casts, log):
        if not (isinstance(entry, list) and len(entry) == 2):
            return None
        aim, strike = entry
        if type(aim) is not int or not free_at <= aim <= MAX_MS:
            return None
        if strike is not None and (type(strike) is not int or not aim < strike <= MAX_MS):
            return None
        bite = aim + cast['wait']
        timing = strike_score(strike, bite, window) if strike is not None else 0
        if timing:
            total += (4 * accuracy(aim, cast) + 6 * timing) // 10
        free_at = cast_end(aim, strike, cast, window)
    return total // len(casts)


def last_ms(plan, log):
    return max((e[1] if e[1] is not None else e[0] for e in log), default=0)


def forage_score(plan, path):
    """Permille score of a walk, or None for an illegal path (outside the grid, over the budget, unknown character)."""
    if not (isinstance(path, str) and len(path) <= plan['budget'] and set(path) <= set(DIRS)):
        return None
    w, h = plan['w'], plan['h']
    items, traps = {int(k) for k in plan['items']}, set(plan['traps'])
    cur, used, got, seen = plan['start'], 0, 0, {plan['start']}
    for ch in path:
        if used >= plan['budget']:
            return None
        dx, dy = DIRS[ch]
        x, y = cur % w + dx, cur // w + dy
        if not (0 <= x < w and 0 <= y < h):
            return None
        cur = y * w + x
        used += 1
        if cur not in seen:
            seen.add(cur)
            got += cur in items
            used += TRAP_COST * (cur in traps)
    return min(1000, 1000 * got // max(1, plan['gold']))


def quality(score):
    return Q_AUTO + BONUS * score // 1000


def scaled_outputs(outputs, q):
    """Every item multiplied by q / 1000, half up (never below the base amount)."""
    return {k: max(v, (v * q + 500) // 1000) for k, v in outputs.items()}


def final_outputs(trip):
    game = trip.get('game')
    if not game or game.get('state') != 'done':
        return dict(trip['outputs'])
    return scaled_outputs(trip['outputs'], game['q'])


# ------------------------------------------------------------------------------------------------ command
def apply_play(farm, data, now):
    trip = find(farm['trips'], data['trip'])
    game = trip.get('game')
    need(game is not None, 'no_game', 'В этой поездке нет мини-игры.')
    need(game['state'] == 'open', 'already_played', 'Эта игра уже сыграна.')
    need(now <= game['expires_at'], 'game_expired', 'Время мини-игры прошло: поездка идёт как обычно.')
    plan, log = game['plan'], data['log']
    elapsed_ms = (now - trip['started_at']) * 1000
    if game['kind'] == 'fish':
        score = fish_score(plan, log)
        need(score is not None, 'bad_log', 'Недопустимая запись игры.', 422)
        need(last_ms(plan, log) <= elapsed_ms + SKEW_MS, 'too_fast', 'Слишком быстро для такой игры.', 422)
    else:
        score = forage_score(plan, log)
        need(score is not None, 'bad_log', 'Маршрут нарушает правила игры.', 422)
        need(100 * (now - trip['started_at']) >= STEP_CS * len(log), 'too_fast', 'Слишком быстро для такой игры.', 422)
    game.update(state='done', score=score, q=quality(score))
    fishing = game['kind'] == 'fish'
    extra = {k: v - trip['outputs'][k] for k, v in final_outputs(trip).items() if v > trip['outputs'][k]}
    tail = ' Добавка к улову: ' if fishing else ' Добавка к находкам: '
    tail = tail + ', '.join(f'{ITEMS[k]["name"]} +{v}' for k, v in extra.items()) + '.' if extra else ' Сегодня как у автопилота.'
    return ('Рыбалка сыграна.' if fishing else 'Прогулка сыграна.') + tail


def validate(farm):
    for trip in farm.get('trips', []):
        game = trip.get('game')
        if game is None:
            continue
        ok = (not trip['guide'] and game.get('state') in {'open', 'done'} and game.get('kind') in {'fish', 'forage'}
              and type(game.get('q')) is int and Q_AUTO <= game['q'] <= Q_AUTO + BONUS and isinstance(game.get('plan'), dict))
        need(ok, 'invalid_trips', 'Некорректная мини-игра поездки.', 500)
