"""Trip minigames: "Порыбачу сам" (cast, bite, strike) and "Пойду сам" (short forest gathering). See docs/tasks/FARM_TRIP_MINIGAMES.md.

A trip started WITHOUT a guide gets ``trip['game']`` (a plan generated from sha256(seed) and shipped to the client, so the client
never hashes). The autopilot is simply not playing: the trip returns the base outputs (q = 1000). A played game gives
``q = 1000 + 250 * score // 1000`` (never below the autopilot) and ``collect_trip`` multiplies every output by q (half up). The game
changes neither the trip time nor the XP. ``trip_play {trip, log}`` is the only command: the server replays ``log`` itself,
ignores every number of the client, and closes the game once.

FISHING v2 (§10 of the doc, ``plan['v'] == 2``): cast -> nibbles -> bite -> strike -> fight.  The log is
``{v: 2, bait: '' | item, casts: [[aim_ms, strike_ms | null, [toggle_ms, ...]], ...]}``.  The strike is a press; every toggle
flips hold/release afterwards.  The fight is an integer simulation on a 50 ms tick (``fight``) over the fish's pull schedule
from the plan: holding reels in and raises tension, releasing gives line.  Tension 1000 snaps, a slack line unhooks, a fish
that took the line to 1000 or fought 400 ticks is gone.  cast = (3 acc + 3 timing + 4 fight) / 10 when landed, (3 acc +
3 timing) / 20 when lost after the strike, else 0.  Landed fish go to ``farm['fish_journal']`` (rare ones are journal only,
never items).  Open v1 plans are regenerated as v2 from the same seed by ``upgrade``.

FISHING v1 (plans without ``v``).  ``plan['casts'][i] = {phase, zone, wait}``; the log is ``[[aim_ms, strike_ms | null], ...]``
(absolute ms from the game start).  The aiming mark runs a triangle wave of period ``MARK_PERIOD`` shifted by ``phase``; ``acc`` = closeness of the mark (at
``aim_ms``) to the fish zone (permille).  The float dips at ``aim_ms + wait``; a strike is valid in
``[bite + REACT, bite + REACT + window]`` (earlier = fish scared, later = fish gone) and scores best in the middle.
cast = (4 * acc + 6 * timing) // 10 if the strike is valid else 0; score = mean over casts.

FORAGING.  ``plan = {w, h, start, budget, items: {cell: item_id}, traps: [cell], gold}``; the log is a ``UDLR`` string.  Every move
costs 1 step of the budget, a trap costs 2 more (once).  score = min(1000, 1000 * collected // gold) where ``gold`` is the number of
items on a random reference walk of ``budget`` steps (so it is reachable).  Integers only.
"""
from hashlib import sha256
from .catalog import ITEMS
from .domain import need, find, inventory

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

# ---- fishing v2
FISH_V = 2
TICK = 50                      # ms per fight tick
FLY_MS = 600                   # the float flies to the aim point
LAND_PAUSE = 1000              # ms after a fight before the next cast
SCARE_PAUSE = 600              # ms after a too-early strike
TOGGLE_GAP = 40                # ms, faster hold/release changes are not human
MAX_TOGGLES = 200              # per cast
RARE_ACC = 800                 # a rare fish only comes to an accurate cast
WAIT2_MIN, WAIT2_SPAN = 1200, 2800
SEGMENTS = 24                  # pull schedule length (cyclic)
TZ = 3 * 3600                  # Moscow
FIGHT = dict(d0=600, d_max=1000, t0=450, hold_base=200, hold_k=15, rel_k=5, up=5, down=6, reel=9, drag=8, run=4,
             tire_hold=4, tire_rel=1, floor=500, snap=1000, slack=60, slack_ticks=24, ticks=400)
# segs: (pull_lo, pull_hi, ticks_lo, ticks_hi), repeated in order; g: weight in grams; par: ticks of a clean fight
SPECIES = {
    'crucian': dict(name='Карась', rare=False, g=(150, 450), par=90, segs=((8, 14, 14, 28), (36, 44, 6, 12))),
    'perch': dict(name='Окунь', rare=False, g=(120, 400), par=150, segs=((10, 16, 6, 14), (58, 66, 4, 9))),
    'pike': dict(name='Щука', rare=False, g=(900, 3200), par=200, segs=((8, 14, 16, 30), (30, 32, 6, 6), (60, 70, 14, 24))),
    'golden_crucian': dict(name='Золотой карась', rare=True, g=(500, 1100), par=160, segs=((12, 18, 12, 22), (54, 62, 8, 14))),
    'tench': dict(name='Линь', rare=True, g=(600, 1800), par=200, segs=((18, 24, 12, 20), (52, 60, 12, 18))),
    'catfish': dict(name='Сом', rare=True, g=(4000, 12000), par=260, segs=((14, 20, 16, 28), (32, 34, 8, 8), (62, 72, 18, 28))),
}
FISH_ROUTES = {
    'pond_bank': dict(casts=4, window=900, common=(('crucian', 100),), rare='golden_crucian'),
    'lake_inlet': dict(casts=4, window=800, common=(('perch', 60), ('crucian', 40)), rare='tench'),
    'river_bend': dict(casts=4, window=700, common=(('pike', 50), ('perch', 50)), rare='catfish'),
}
RARE_BASE = 25                 # permille per accurate cast
BAITS = {                      # optional extra bait, 1 item spent at trip_play; wait: % of the bite wait, rare: +permille
    'bread': dict(wait=70, rare=0, routes=None),
    'corn': dict(wait=100, rare=40, routes=('pond_bank', 'lake_inlet')),
    'crucian': dict(wait=90, rare=50, routes=('river_bend',)),
}
TOD_WAIT = {'dawn': 75, 'day': 100, 'dusk': 75, 'night': 90}
WEATHERS = ('clear', 'cloud', 'rain', 'wind')


def public_rules():
    fish2 = dict(v=FISH_V, tick=TICK, fly=FLY_MS, land_pause=LAND_PAUSE, scare_pause=SCARE_PAUSE, toggle_gap=TOGGLE_GAP,
                 max_toggles=MAX_TOGGLES, rare_acc=RARE_ACC, fight=FIGHT,
                 species={k: dict(name=v['name'], rare=v['rare'], par=v['par']) for k, v in SPECIES.items()},
                 baits={k: dict(wait=v['wait'], rare=v['rare'], routes=list(v['routes']) if v['routes'] else None) for k, v in BAITS.items()},
                 routes={k: dict(casts=v['casts'], window=v['window'], rare=v['rare'], common=[c for c, _ in v['common']])
                         for k, v in FISH_ROUTES.items()})
    return dict(ttl=GAME_TTL, bonus=BONUS, mark_period=MARK_PERIOD, dead_zone=DEAD_ZONE, acc_span=ACC_SPAN, react=REACT,
                window=WINDOW_BASE, casts=CASTS, first_aim_ms=FIRST_AIM_MS, grid=GRID, trap_cost=TRAP_COST, budget=BUDGET,
                step_cs=STEP_CS, fish2=fish2)


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
def sky(now):
    """Time of day (Moscow hour of the trip start) and the weather of that Moscow day (one for everybody)."""
    hour = (now + TZ) % 86400 // 3600
    tod = 'dawn' if 4 <= hour <= 8 else 'day' if 9 <= hour <= 17 else 'dusk' if 18 <= hour <= 21 else 'night'
    day = (now + TZ) // 86400
    return dict(tod=tod, weather=WEATHERS[sha256(f'weather:{day}'.encode()).digest()[0] % len(WEATHERS)])


def route_baits(route_id):
    return [k for k, b in BAITS.items() if b['routes'] is None or route_id in b['routes']]


def _fish(rng, species):
    sp = SPECIES[species]
    lo, hi = sp['g']
    pulls = []
    for i in range(SEGMENTS):
        p_lo, p_hi, t_lo, t_hi = sp['segs'][i % len(sp['segs'])]
        pulls.append([t_lo + next(rng) % (t_hi - t_lo + 1), p_lo + next(rng) % (p_hi - p_lo + 1)])
    return dict(id=species, g=lo + _u16(rng) % (hi - lo + 1), pulls=pulls)


def make_fish_plan(seed, route_id, started_at=0):
    """Fishing v2 plan; everything random comes from the seed, the sky from the server time of the trip start."""
    route = FISH_ROUTES.get(route_id, FISH_ROUTES['pond_bank'])
    sk = sky(int(started_at))
    period = 1250 if sk['weather'] == 'wind' else MARK_PERIOD
    rng = _stream(seed, 'fish2')
    casts = []
    for _ in range(route['casts']):
        phase, zone, wait = _u16(rng) % period, 150 + _u16(rng) % 701, WAIT2_MIN + _u16(rng) % WAIT2_SPAN
        nibbles, at = [], 150
        for _ in range(next(rng) % 3):
            at += 120 + _u16(rng) % 300
            if at <= 820:
                nibbles.append(at)
        roll, pick = _u16(rng) % 1000, next(rng) % 100
        common = route['common'][-1][0]
        for species, weight in route['common']:
            if pick < weight:
                common = species
                break
            pick -= weight
        casts.append(dict(phase=phase, zone=zone, wait=wait, nibbles=nibbles, roll=roll,
                          fish=[_fish(rng, common), _fish(rng, route['rare']) if route['rare'] else None]))
    return dict(v=FISH_V, casts=casts, window=route['window'], mark_period=period,
                wait_pct=TOD_WAIT[sk['tod']] * (80 if sk['weather'] == 'rain' else 100) // 100,
                rare_chance=RARE_BASE + 15 * (sk['weather'] == 'cloud') + 20 * (sk['tod'] == 'night'),
                sky=sk, baits=route_baits(route_id))


def make_fish_plan_v1(seed, route_id):
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
    plan = make_fish_plan(seed, route['id'], now) if kind == 'fish' else make_forage_plan(seed, route)
    return dict(kind=kind, state='open', seed=seed, expires_at=now + GAME_TTL, q=Q_AUTO, score=0, plan=plan)


# ------------------------------------------------------------------------------------------------ pure rules
def mark_position(t, phase, period=MARK_PERIOD):
    """Position of the aiming mark, permille 0..1000 (triangle wave)."""
    m = (t + phase) % period
    half = period // 2
    return m * 1000 // half if m <= half else (period - m) * 1000 // half


def accuracy(aim_ms, cast, period=MARK_PERIOD):
    d = abs(mark_position(aim_ms, cast['phase'], period) - cast['zone'])
    return max(0, 1000 - max(0, d - DEAD_ZONE) * 1000 // ACC_SPAN)


# ---- fishing v2: pure rules, mirrored 1:1 in static/trip_game.js
def bait_spec(bait):
    b = BAITS.get(bait)
    return (b['wait'], b['rare']) if b else (100, 0)


def bite_at(plan, cast, aim, acc, bait_wait):
    """Absolute ms of the real bite: the float flies, the fish comes (faster at dawn, in the rain, with bread, to a good cast)."""
    return aim + FLY_MS + cast['wait'] * plan['wait_pct'] // 100 * bait_wait // 100 + 2 * (1000 - acc)


def strike_timing(strike, bite, window):
    """0 = too early (scared) or too late; otherwise 1000 for an instant strike down to 500 at the end of the window."""
    d = strike - bite
    if d < REACT or d > REACT + window:
        return 0
    return 1000 - (d - REACT) * 500 // window


def hooked_fish(plan, cast, acc, rare_add):
    rare = cast['fish'][1]
    if rare and acc >= RARE_ACC and cast['roll'] < plan['rare_chance'] + rare_add:
        return rare
    return cast['fish'][0]


def fight_start():
    return dict(t=FIGHT['t0'], d=FIGHT['d0'], s=1000, slack=0, seg=0, left=-1, k=0, end='')


def fight_step(st, fish, hold):
    """One 50 ms tick. Mutates ``st``; sets ``st['end']`` to land | snap | slack | escape when the fight is over."""
    f, pulls = FIGHT, fish['pulls']
    if st['left'] <= 0:
        st['seg'] = (st['seg'] + (st['left'] == 0)) % len(pulls)
        st['left'] = pulls[st['seg']][0]
    pull = pulls[st['seg']][1]
    st['left'] -= 1
    eff = pull * (f['floor'] + st['s'] * (1000 - f['floor']) // 1000) // 1000
    if hold:
        target = f['hold_base'] + f['hold_k'] * eff
        st['d'] -= max(0, f['reel'] - eff // f['drag'])
        st['s'] = max(0, st['s'] - f['tire_hold'])
    else:
        target = f['rel_k'] * eff
        st['d'] += eff // f['run']
        st['s'] = max(0, st['s'] - f['tire_rel'])
    st['t'] += (target - st['t']) // (f['up'] if target > st['t'] else f['down'])
    st['k'] += 1
    st['slack'] = st['slack'] + 1 if st['t'] < f['slack'] else 0
    if st['t'] >= f['snap']:
        st['end'] = 'snap'
    elif st['slack'] >= f['slack_ticks']:
        st['end'] = 'slack'
    elif st['d'] <= 0:
        st['end'] = 'land'
    elif st['d'] >= f['d_max'] or st['k'] >= f['ticks']:
        st['end'] = 'escape'
    return st


def fight(fish, strike, toggles):
    """Replay a whole fight: holding from the strike, every toggle (absolute ms) flips hold/release. -> (end, ticks)."""
    st, hold, j = fight_start(), True, 0
    while not st['end']:
        t = strike + st['k'] * TICK
        while j < len(toggles) and toggles[j] <= t:
            hold, j = not hold, j + 1
        fight_step(st, fish, hold)
    return st['end'], st['k']


def fight_points(ticks, par):
    return 1000 - min(300, max(0, ticks - par) * 300 // par)


def eval_cast(plan, cast, aim, strike, toggles, bait):
    """Outcome of one cast: {points, end (ms), free (ms, next cast not before), result, fish|None, acc}."""
    bait_wait, rare_add = bait_spec(bait)
    acc = accuracy(aim, cast, plan['mark_period'])
    bite = bite_at(plan, cast, aim, acc, bait_wait)
    window = plan['window']
    if strike is None:
        end = bite + REACT + window
        return dict(points=0, end=end, free=end, result='missed', fish=None, acc=acc)
    timing = strike_timing(strike, bite, window)
    if not timing:
        early = strike < bite + REACT
        return dict(points=0, end=strike, free=strike + SCARE_PAUSE if early else max(strike, bite + REACT + window),
                    result='early' if early else 'missed', fish=None, acc=acc)
    fish = hooked_fish(plan, cast, acc, rare_add)
    result, ticks = fight(fish, strike, toggles)
    end = strike + ticks * TICK
    if result == 'land':
        points = (3 * acc + 3 * timing + 4 * fight_points(ticks, SPECIES[fish['id']]['par'])) // 10
    else:
        points = (3 * acc + 3 * timing) // 20
    return dict(points=points, end=end, free=end + LAND_PAUSE, result=result, fish=fish, acc=acc)


def _ms(v, lo=0):
    return type(v) is int and lo <= v <= MAX_MS


def fish_result(plan, log):
    """Server replay of a v2 log -> {score, end, casts:[...], catch:[[id, g], ...], bait} or None when it breaks the rules."""
    if not (isinstance(log, dict) and set(log) == {'v', 'bait', 'casts'} and log['v'] == FISH_V and type(log['v']) is int):
        return None
    bait, casts = log['bait'], log['casts']
    if not (isinstance(bait, str) and (bait == '' or bait in plan['baits'])):
        return None
    if not (isinstance(casts, list) and len(casts) == len(plan['casts'])):
        return None
    total, free, out, end = 0, FIRST_AIM_MS, [], 0
    for cast, entry in zip(plan['casts'], casts):
        if not (isinstance(entry, list) and len(entry) == 3):
            return None
        aim, strike, toggles = entry
        if not _ms(aim, free):
            return None
        if strike is not None and not (_ms(strike) and strike > aim):
            return None
        if not (isinstance(toggles, list) and len(toggles) <= MAX_TOGGLES and (strike is not None or not toggles)):
            return None
        prev = strike
        for t in toggles:
            if not (_ms(t) and t >= prev + TOGGLE_GAP):
                return None
            prev = t
        r = eval_cast(plan, cast, aim, strike, toggles, bait)
        total += r['points']
        free, end = r['free'], r['end']
        out.append(r)
    catch = [[r['fish']['id'], r['fish']['g']] for r in out if r['result'] == 'land']
    return dict(score=total // len(out), end=end, casts=out, catch=catch, bait=bait)


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
    """Permille score of a fishing log (v1 or v2 by the plan), or None when the log breaks the rules."""
    if plan.get('v') == FISH_V:
        r = fish_result(plan, log)
        return None if r is None else r['score']
    return fish_score_v1(plan, log)


def fish_score_v1(plan, log):
    """Permille score of a v1 fishing log, or None when the log breaks the rules."""
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
    caught = ''
    if game['kind'] == 'fish' and plan.get('v') == FISH_V:
        res = fish_result(plan, log)
        need(res is not None, 'bad_log', 'Недопустимая запись игры. Обнови страницу и сыграй ещё раз.', 422)
        need(res['end'] <= elapsed_ms + SKEW_MS, 'too_fast', 'Слишком быстро для такой игры.', 422)
        if res['bait']:
            need(farm['inventory'].get(res['bait'], 0) >= 1, 'no_bait', f'Наживка закончилась: {ITEMS[res["bait"]]["name"]}.')
            inventory(farm, {res['bait']: 1}, -1)
        score = res['score']
        game.update(catch=res['catch'], bait=res['bait'])
        caught = record_catch(farm, res['catch'])
    elif game['kind'] == 'fish':
        score = fish_score_v1(plan, log)
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
    return ('Рыбалка сыграна.' if fishing else 'Прогулка сыграна.') + caught + tail


def grams_text(g):
    """Same as trip_game.js grams(): 340 г, 2,5 кг."""
    return f'{g} г' if g < 1000 else f'{g / 1000:.1f} кг'.replace('.', ',')


def record_catch(farm, catch):
    """Landed fish -> the owner's catch journal {species: {n, g}}; returns a sentence for the event feed."""
    if not catch:
        return ' Садок пуст.'
    journal = farm.setdefault('fish_journal', {})
    fresh = []
    for species, grams in catch:
        row = journal.setdefault(species, dict(n=0, g=0))
        if not row['n']:
            fresh.append(SPECIES[species]['name'])
        row['n'] += 1
        row['g'] = max(row['g'], grams)
    names = ', '.join(f'{SPECIES[k]["name"].lower()} {grams_text(g)}' for k, g in catch)
    return f' В садке: {names}.' + (f' Новое в журнале улова: {", ".join(fresh)}!' if fresh else '')


def upgrade(farm):
    """Open v1 fishing games get a v2 plan from the same seed (played or expired games keep theirs)."""
    for trip in farm.get('trips', []):
        game = trip.get('game')
        if game and game.get('kind') == 'fish' and game.get('state') == 'open' and not game['plan'].get('v'):
            game['plan'] = make_fish_plan(game['seed'], trip['route'], trip['started_at'])


def validate(farm):
    journal = farm.get('fish_journal')
    if journal is not None:
        need(isinstance(journal, dict) and set(journal) <= set(SPECIES) and
             all(isinstance(r, dict) and set(r) == {'n', 'g'} and type(r['n']) is int and type(r['g']) is int and
                 0 <= r['n'] <= 10 ** 9 and 0 <= r['g'] <= 10 ** 6 for r in journal.values()),
             'invalid_journal', 'Некорректный журнал улова.', 500)
    for trip in farm.get('trips', []):
        game = trip.get('game')
        if game is None:
            continue
        ok = (not trip['guide'] and game.get('state') in {'open', 'done'} and game.get('kind') in {'fish', 'forage'}
              and type(game.get('q')) is int and Q_AUTO <= game['q'] <= Q_AUTO + BONUS and isinstance(game.get('plan'), dict))
        need(ok, 'invalid_trips', 'Некорректная мини-игра поездки.', 500)
