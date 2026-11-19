"""r9 stage 15: fields (hectares outside the bed grid), three machines and three top-down minigames.

OPERATION CYCLE (one run at a time per field):  wild --cultivate--> ready --sow--> growing --(timer)--> ripe --harvest--> wild.
Machines: cultivator (cultivate), seeder (sow), combine (harvest); tier = swath width 1 -> 2 -> 3 (``farm['field_machines']``).

STATE.  ``farm['fields']`` (a list; ``economy.base_upkeep`` sums ``ha`` over it) and ``farm['field_machines']`` are created
lazily with ``setdefault`` by the first field command; old farms simply do not have them and ``schema_version`` is not raised.

PROTOCOL.  ``buy_field {step}``, ``buy_machine {machine}``, ``upgrade_machine {machine}``,
``field_start {field, op, crop, revision}`` (crop is '' except for sowing; takes fuel and seeds, creates the run with its
obstacles) and ``field_finish {field, run, path}`` (``path`` is a string over ``UDLR`` (+ ``X`` for the combine) or null =
autopilot).  The server replays the path itself and ignores every number of the client.

THE PURE MECHANICS (the client repeats them 1:1; integers only - scores are permille 0..1000, no floats, no sha256).
Grid: ``W = field['w'] = 8`` columns, ``H = field['h'] = 8 * ha`` rows, cell index ``y * W + x``.  The machine is a horizontal
bar of ``width = run['width']`` cells; its anchor ``(x, y)`` is the left end, ``0 <= x <= W - width``, ``0 <= y < H``; it starts
at ``(0, 0)``.  ``U/D/L/R`` move the anchor by one cell (y - 1 / y + 1 / x - 1 / x + 1).  A move that leaves the grid or puts the
bar over a rock (``run['rocks']``: list of cell indexes, never in row 0) makes the whole path INVALID (``None`` -> HTTP 422).
The server derives rocks/weeds from sha256(seed) at ``field_start`` and ships them in the run, so a client never hashes.
"Reachable anchors" = anchors reachable from (0, 0) by valid moves; "reachable cells" = the union of their bars.

* simulate_cultivate - every position's bar cuts the cells it covers.  Weighted coverage (a weed cell weighs 3, others 1)
  over the reachable cells = ``cov``; ``again`` counts cell visits whose cell was last covered before the previous step
  (a straight sweep does not count itself; coming back later does); ``ov = again / covered cells``.
  score = clamp((cov - 600) * 1000 // 380, 0, 1000) - 300 * max(0, ov - 250) // 1000, floored at 0.
* simulate_sow - seeds drop only while the bar stands exactly on a row marking: anchors with ``x % (width + 1) == 0``
  (lanes ``width`` wide, one gap column between them).  Arriving at such an anchor (the start counts) sows its cells; a cell
  sown again is a "double".  ``rec`` = sown cells / sowable cells (cells of the reachable lane anchors); ``dbl = doubles /
  sowable``.  score = clamp((rec - 600) * 1000 // 380, 0, 1000) - 2 * max(0, dbl - 30), clamped to 0..1000.
* simulate_harvest - the cells are taken the first time the bar covers them and go to the hopper of capacity
  ``18 * width * ha``; a cell that does not fit is LOST.  ``X`` unloads the hopper and is only valid with y == 0 (the truck at
  the top edge).  ``cov`` = taken cells that were not lost / reachable cells; overlap as in cultivation; same score formula.

QUALITY.  Manual quality ``q = 850 + 250 * score // 1000`` (0.85 .. 1.10, permille); the autopilot is 950.  For runs with
``qrule == 2`` (all runs opened since the owner's 2026-10-14 decision) the bonus over 950 is whole while the run lasts at most
2.5 x the autopilot time and melts linearly to 0 at 6 x (``timed_quality``); older open runs keep the plain quality and their 900 s
deadline.  Cultivation only moves time: growth lasts ``base * (1950 - q_cult) / 1000`` (autopilot 1.0, best manual 0.85).

RULES VERSIONS.  A run without ``run['rules']`` is the legacy one above.  ``rules == 2`` adds ``T`` (the implement turns in place)
and per-cell sowing at the lane anchors under the same economy.  ``rules >= FIELD_RULES`` (= 3) is the full test economy: both
orientations are workable (sow runs with ``sow_reach`` count every reachable lane cell as sowable), a lowercase ``u/d/l/r`` is a bump against a rock or the field edge (-3 condition, 15 coins of repair
per hit, 4 permille of quality per missing condition point), the fourth operation ``spray`` fills the tank at the tanker and drifts
with the wind, and ``X`` transfers a quarter of the hopper/tank at a time.  Its manual quality is
``850 + 400 * score // 1000`` (0.85 .. 1.25) with the autopilot 900, the same timed melt (``timed_quality_full``) and condition 0
closing the run as the autopilot.  Growth after cultivation is 1950 - q_cult (950 -> 1.0, 900 -> 1.05, 1250 -> 0.70, 850 -> 1.10);
spray adds 0 .. +20 % (``spray_bonus_permille``).

Yield = ``yield_qty * 16 * ha * q_sow * q_harvest * q_spray // 10**9``; XP = ``crop.xp * 8 * ha * q_sow * q_harvest * q_spray //
10**9`` through ``progression.grant_xp`` (the only XP funnel); rules < 3 use q_spray = 1000.
"""
from hashlib import sha256
import heapq
import math
from .catalog import (CROPS, ITEMS, level, FIELD_STEPS, FIELD_MACHINES, FIELD_OPS, FIELD_FUEL, FIELD_YIELD_MULT, FIELD_SEED_MULT,
                      FIELD_XP_MULT, FIELD_MIN_GROW, FIELD_RUN_TTL, FIELD_STEP_CS, FIELD_MAX_PATH, FIELD_AUTO_S, FIELD_W,
                      FIELD_MIN_LEVEL, FIELD_UPKEEP, FIELD_FULL_K, FIELD_ZERO_K, Q_AUTO, Q_BASE, Q_SPAN, Q_AUTO_FULL, Q_BASE_FULL,
                      Q_SPAN_FULL, HOPPER, FIELD_UNLOAD_CENTER, FIELD_UNLOAD_HALF, FIELD_RULES, FIELD_TANK, FIELD_TANK_CHUNKS,
                      FIELD_HIT_DAMAGE, FIELD_HIT_REPAIR, FIELD_COND_PENALTY, FIELD_SPRAY_BONUS_BASE, FIELD_SPRAY_BONUS_SPAN,
                      FIELD_SPRAY_BONUS_MAX, VERSION)
from .domain import need, named, find, pay, inventory, event, duration
from . import progression, market
from .upkeep_config import settings_for

SCHEMAS = {
    'buy_field': {'step'},
    'buy_machine': {'machine'},
    'upgrade_machine': {'machine'},
    'field_start': {'field', 'op', 'crop', 'revision'},
    'field_finish': {'field', 'run', 'path'},
    'field_cancel': {'field', 'revision'},      # E27 F4: take back a mistaken sowing during the first UNDO_WINDOW seconds
}
DIRS = {'U': (0, -1), 'D': (0, 1), 'L': (-1, 0), 'R': (1, 0)}
BUMP_DIRS = {'u': (0, -1), 'd': (0, 1), 'l': (-1, 0), 'r': (1, 0)}   # a damaging bump against a rock/wall (rules=3)
WEED_WEIGHT = 3
ROCKS_PER_HA = {'cultivate': 3, 'sow': 2, 'harvest': 2, 'spray': 2}
WEEDS_PER_HA = 10


# ------------------------------------------------------------------------------------------------ pure geometry
def _geometry(field, run):
    return field['w'], field['h'], run['width'], frozenset(run.get('rocks') or ())


def _free(x, y, W, width, rocks):
    base = y * W + x
    return not any(base + i in rocks for i in range(width))


def _bar(x, y, W, width):
    base = y * W + x
    return [base + i for i in range(width)]


def _near_unload(x, width, orient='h'):
    """True when the machine centre stands at the fixed grain truck (hundredths of a cell)."""
    center2 = 2 * x + (width if orient == 'h' else 1)
    return abs(center2 * 50 - FIELD_UNLOAD_CENTER) <= FIELD_UNLOAD_HALF


def _step(x, y, ch, W, H, width, rocks):
    """The anchor after one move, or None when the move is illegal (outside the grid or over a rock)."""
    dx, dy = DIRS[ch]
    nx, ny = x + dx, y + dy
    if 0 <= nx <= W - width and 0 <= ny < H and _free(nx, ny, W, width, rocks):
        return nx, ny
    return None


def reachable_anchors(W, H, width, rocks):
    seen = {(0, 0)}
    todo = [(0, 0)]
    while todo:
        x, y = todo.pop()
        for ch in 'UDLR':
            nxt = _step(x, y, ch, W, H, width, rocks)
            if nxt is not None and nxt not in seen:
                seen.add(nxt)
                todo.append(nxt)
    return seen


def _cells_of(anchors, W, width):
    cells = set()
    for x, y in anchors:
        cells.update(_bar(x, y, W, width))
    return cells


def max_path(field, run):
    return min(3 * field['w'] * field['h'] // run['width'], FIELD_MAX_PATH)


def _walk(W, H, width, rocks, path, events=''):
    """Yield ``(char, x, y, t)`` for the start (char '') and every character; None at the first illegal character.
    ``t`` counts successful moves.  Characters in ``events`` ('X') are non-moving events and must satisfy the caller."""
    x = y = t = 0
    yield '', x, y, t
    for ch in path:
        if ch in events:
            yield ch, x, y, t
            continue
        nxt = _step(x, y, ch, W, H, width, rocks) if ch in DIRS else None
        if nxt is None:
            yield None
            return
        x, y = nxt
        t += 1
        yield ch, x, y, t


def _oriented_bar(x, y, W, width, orient):
    base = y * W + x
    if orient == 'h':
        return [base + i for i in range(width)]
    return [base + i * W for i in range(width)]


def _orient_ok(x, y, W, H, width, rocks, orient):
    if orient == 'h':
        if x < 0 or x + width > W or y < 0 or y >= H:
            return False
    elif x < 0 or x >= W or y < 0 or y + width > H:
        return False
    return not any(c in rocks for c in _oriented_bar(x, y, W, width, orient))


def _walk_v2(W, H, width, rocks, path, events=''):
    """Rules=2 walk: T toggles the implement in place and does not consume a cell visit."""
    x = y = t = 0
    orient = 'h'
    yield '', x, y, orient, t
    for ch in path:
        if ch in events:
            yield ch, x, y, orient, t
            continue
        if ch == 'T':
            if width < 2:
                yield None
                return
            no = 'v' if orient == 'h' else 'h'
            if not _orient_ok(x, y, W, H, width, rocks, no):
                yield None
                return
            orient = no
            continue
        d = DIRS.get(ch)
        if d is None:
            yield None
            return
        nx, ny = x + d[0], y + d[1]
        if not _orient_ok(nx, ny, W, H, width, rocks, orient):
            yield None
            return
        x, y = nx, ny
        t += 1
        yield ch, x, y, orient, t


def _grade(cov, ov):
    score = min(1000, max(0, cov - 600) * 1000 // 380)
    return max(0, score - 300 * max(0, ov - 250) // 1000)


def simulate_cultivate(field, run, path):
    W, H, width, rocks = _geometry(field, run)
    weeds = frozenset(run.get('weeds') or ())
    cells = _cells_of(reachable_anchors(W, H, width, rocks), W, width)
    total = sum(WEED_WEIGHT if c in weeds else 1 for c in cells)
    last, got, again = {}, 0, 0
    for item in _walk(W, H, width, rocks, path):
        if item is None:
            return None
        _, x, y, t = item
        for c in _bar(x, y, W, width):
            if c not in last:
                got += WEED_WEIGHT if c in weeds else 1
            elif last[c] < t - 1:
                again += 1
            last[c] = t
    return _grade(got * 1000 // total, again * 1000 // len(last))


def simulate_sow(field, run, path):
    W, H, width, rocks = _geometry(field, run)
    lanes = [a for a in reachable_anchors(W, H, width, rocks) if a[0] % (width + 1) == 0]
    sowable = _cells_of(lanes, W, width)
    sown, doubles = set(), 0
    for item in _walk(W, H, width, rocks, path):
        if item is None:
            return None
        ch, x, y, t = item
        if x % (width + 1) == 0:
            for c in _bar(x, y, W, width):
                if c in sown:
                    doubles += 1
                else:
                    sown.add(c)
    rec, dbl = len(sown) * 1000 // len(sowable), doubles * 1000 // len(sowable)
    return max(0, min(1000, max(0, rec - 600) * 1000 // 380) - 2 * max(0, dbl - 30))


def simulate_harvest(field, run, path):
    W, H, width, rocks = _geometry(field, run)
    cells = _cells_of(reachable_anchors(W, H, width, rocks), W, width)
    cap = HOPPER * width * (H // W)
    last, load, kept = {}, 0, 0
    again = 0
    for item in _walk(W, H, width, rocks, path, 'X'):
        if item is None:
            return None
        ch, x, y, t = item
        if ch == 'X':
            if y != 0 or (run.get('unload_zone') and not _near_unload(x, width)):
                return None
            load = 0
            continue
        for c in _bar(x, y, W, width):
            if c not in last:
                if load < cap:
                    load += 1
                    kept += 1
            elif last[c] < t - 1:
                again += 1
            last[c] = t
    return _grade(kept * 1000 // len(cells), again * 1000 // len(last))


def _rules2_cells(W, H, width, rocks):
    return _cells_of(reachable_anchors(W, H, width, rocks), W, width)


def _rules2_sowable(W, H, width, rocks):
    lanes = [a for a in reachable_anchors(W, H, width, rocks) if a[0] % (width + 1) == 0]
    return _cells_of(lanes, W, width)


def simulate_cultivate_v2(field, run, path):
    W, H, width, rocks = _geometry(field, run)
    weeds = frozenset(run.get('weeds') or ())
    cells = _rules2_cells(W, H, width, rocks)
    total = sum(WEED_WEIGHT if c in weeds else 1 for c in cells)
    last, got, again = {}, 0, 0
    for item in _walk_v2(W, H, width, rocks, path):
        if item is None:
            return None
        _, x, y, orient, t = item
        for c in _oriented_bar(x, y, W, width, orient):
            if c not in cells:
                continue
            if c not in last:
                got += WEED_WEIGHT if c in weeds else 1
            elif last[c] < t - 1:
                again += 1
            last[c] = t
    return _grade(got * 1000 // total, again * 1000 // max(1, len(last)))


def simulate_sow_v2(field, run, path):
    W, H, width, rocks = _geometry(field, run)
    sowable = _rules2_sowable(W, H, width, rocks)
    sown, doubles = set(), 0
    for item in _walk_v2(W, H, width, rocks, path):
        if item is None:
            return None
        _, x, y, orient, _ = item
        for c in _oriented_bar(x, y, W, width, orient):
            if c not in sowable:
                continue
            if c in sown:
                doubles += 1
            else:
                sown.add(c)
    rec, dbl = len(sown) * 1000 // len(sowable), doubles * 1000 // len(sowable)
    return max(0, min(1000, max(0, rec - 600) * 1000 // 380) - 2 * max(0, dbl - 30))


def simulate_harvest_v2(field, run, path):
    W, H, width, rocks = _geometry(field, run)
    cells = _rules2_cells(W, H, width, rocks)
    cap = HOPPER * width * (H // W)
    last, load, kept, again = {}, 0, 0, 0
    for item in _walk_v2(W, H, width, rocks, path, 'X'):
        if item is None:
            return None
        ch, x, y, orient, t = item
        if ch == 'X':
            if y != 0 or (run.get('unload_zone') and not _near_unload(x, width, orient)):
                return None
            load = 0
            continue
        for c in _oriented_bar(x, y, W, width, orient):
            if c not in cells:
                continue
            if c not in last:
                if load < cap:
                    load += 1
                    kept += 1
            elif last[c] < t - 1:
                again += 1
            last[c] = t
    return _grade(kept * 1000 // max(1, len(cells)), again * 1000 // max(1, len(last)))


def _rules3_cells(W, H, width, rocks):
    """Cells reachable with both implement orientations (T included): the turn opens pockets that a horizontal bar cannot enter."""
    seen = {(0, 0, 'h')}
    todo = [(0, 0, 'h')]
    cells = set()
    while todo:
        x, y, orient = todo.pop()
        cells.update(_oriented_bar(x, y, W, width, orient))
        for ch in 'UDLR':
            dx, dy = DIRS[ch]
            nx, ny = x + dx, y + dy
            if not _orient_ok(nx, ny, W, H, width, rocks, orient):
                continue
            state = (nx, ny, orient)
            if state not in seen:
                seen.add(state)
                todo.append(state)
        other = 'v' if orient == 'h' else 'h'
        if _orient_ok(x, y, W, H, width, rocks, other) and (x, y, other) not in seen:
            seen.add((x, y, other))
            todo.append((x, y, other))
    cells.difference_update(rocks)
    return cells


def _walk_v3(W, H, width, rocks, path, events=''):
    """Rules=3 walk: T toggles the implement, a lowercase direction is a damaging bump against a rock/wall, events (X) do not move.
    Every item is ``(char, x, y, orient, t, condition)``; ``None`` marks the first illegal character."""
    x = y = t = 0
    orient = 'h'
    condition = 100
    yield '', x, y, orient, t, condition
    for ch in path:
        if ch in events:
            yield ch, x, y, orient, t, condition
            continue
        if ch == 'T':
            if width < 2:
                yield None
                return
            other = 'v' if orient == 'h' else 'h'
            if not _orient_ok(x, y, W, H, width, rocks, other):
                yield None
                return
            orient = other
            continue
        if ch in BUMP_DIRS:
            dx, dy = BUMP_DIRS[ch]
            if condition <= 0 or _orient_ok(x + dx, y + dy, W, H, width, rocks, orient):
                yield None                          # a bump is legal only where the move is really blocked
                return
            condition = max(0, condition - FIELD_HIT_DAMAGE)
            yield ch, x, y, orient, t, condition
            continue
        d = DIRS.get(ch)
        if d is None:
            yield None
            return
        nx, ny = x + d[0], y + d[1]
        if not _orient_ok(nx, ny, W, H, width, rocks, orient):
            yield None
            return
        x, y = nx, ny
        t += 1
        yield ch, x, y, orient, t, condition


def _v3_result(score, condition, hits, load=None):
    result = dict(score=score, condition=condition, hits=hits, repair=hits * FIELD_HIT_REPAIR)
    if load is not None:
        result['load'] = load
    return result


def simulate_cultivate_v3(field, run, path):
    W, H, width, rocks = _geometry(field, run)
    weeds = frozenset(run.get('weeds') or ())
    cells = _rules3_cells(W, H, width, rocks)
    total = sum(WEED_WEIGHT if c in weeds else 1 for c in cells)
    last, got, again, condition, hits = {}, 0, 0, 100, 0
    for item in _walk_v3(W, H, width, rocks, path):
        if item is None:
            return None
        ch, x, y, orient, t, condition = item
        if ch in BUMP_DIRS:
            hits += 1
            continue
        for c in _oriented_bar(x, y, W, width, orient):
            if c not in cells:
                continue
            if c not in last:
                got += WEED_WEIGHT if c in weeds else 1
            elif last[c] < t - 1:
                again += 1
            last[c] = t
    score = _grade(got * 1000 // total, again * 1000 // max(1, len(last)))
    return _v3_result(score, condition, hits)


def _rules3_sowable(W, H, width, rocks):
    """Runs with ``sow_reach``: every reachable lane cell (both orientations), so a lane cell beside a rock that only the turned
    implement can enter counts and gets sown.  Older runs keep the lane anchors of the horizontal bar (``_rules2_sowable``)."""
    return {c for c in _rules3_cells(W, H, width, rocks) if (c % W) % (width + 1) < width}


def simulate_sow_v3(field, run, path):
    W, H, width, rocks = _geometry(field, run)
    sowable = _rules3_sowable(W, H, width, rocks) if run.get('sow_reach') else _rules2_sowable(W, H, width, rocks)
    sown, doubles, condition, hits = set(), 0, 100, 0
    for item in _walk_v3(W, H, width, rocks, path):
        if item is None:
            return None
        ch, x, y, orient, _, condition = item
        if ch in BUMP_DIRS:
            hits += 1
            continue
        for c in _oriented_bar(x, y, W, width, orient):
            if c not in sowable:
                continue
            if c in sown:
                doubles += 1
            else:
                sown.add(c)
    rec, dbl = len(sown) * 1000 // len(sowable), doubles * 1000 // len(sowable)
    score = max(0, min(1000, max(0, rec - 600) * 1000 // 380) - 2 * max(0, dbl - 30))
    return _v3_result(score, condition, hits)


def simulate_harvest_v3(field, run, path):
    W, H, width, rocks = _geometry(field, run)
    cells = _rules3_cells(W, H, width, rocks)
    cap = HOPPER * width * (H // W)
    chunk = max(1, math.ceil(cap / FIELD_TANK_CHUNKS))
    last, load, kept, again, condition, hits = {}, 0, 0, 0, 100, 0
    for item in _walk_v3(W, H, width, rocks, path, 'X'):
        if item is None:
            return None
        ch, x, y, orient, t, condition = item
        if ch == 'X':
            if y != 0 or (run.get('unload_zone') and not _near_unload(x, width, orient)):
                return None
            load = max(0, load - chunk)
            continue
        if ch in BUMP_DIRS:
            hits += 1
            continue
        for c in _oriented_bar(x, y, W, width, orient):
            if c not in cells:
                continue
            if c not in last:
                if load < cap:
                    load += 1
                    kept += 1
            elif last[c] < t - 1:
                again += 1
            last[c] = t
    score = _grade(kept * 1000 // max(1, len(cells)), again * 1000 // max(1, len(last)))
    return _v3_result(score, condition, hits, load=load)


def simulate_spray_v3(field, run, path):
    W, H, width, rocks = _geometry(field, run)
    cells = _rules3_cells(W, H, width, rocks)
    tank = int(run.get('tank') or FIELD_TANK)
    chunk = max(1, tank // FIELD_TANK_CHUNKS)
    wind = -1 if int(run.get('wind') or 0) < 0 else 1 if int(run.get('wind') or 0) > 0 else 0
    load, sprayed, doubles, condition, hits = tank, set(), 0, 100, 0
    for item in _walk_v3(W, H, width, rocks, path, 'X'):
        if item is None:
            return None
        ch, x, y, orient, _, condition = item
        if ch == 'X':
            if y != 0 or (run.get('unload_zone') and not _near_unload(x, width, orient)):
                return None
            load = min(tank, load + chunk)
            continue
        if ch in BUMP_DIRS:
            hits += 1
            continue
        for c in _oriented_bar(x, y, W, width, orient):
            if c not in cells:
                continue
            if c in sprayed:
                doubles += 1
                if load > 0:
                    load -= 1
                continue
            if load < 2:
                continue
            sprayed.add(c)
            load -= 2
            if wind and load > 0:
                cx = c % W
                wx = cx + wind
                if 0 <= wx < W:
                    wk = c - cx + wx
                    if wk in cells and wk not in sprayed and load > 0:
                        sprayed.add(wk)
                        load -= 1
    rec = len(sprayed) * 1000 // max(1, len(cells))
    dbl = doubles * 1000 // max(1, len(cells))
    score = _grade(rec, dbl)
    return _v3_result(score, condition, hits, load=load)


SIMULATE = {'cultivate': simulate_cultivate, 'sow': simulate_sow, 'harvest': simulate_harvest}
SIMULATE_V2 = {'cultivate': simulate_cultivate_v2, 'sow': simulate_sow_v2, 'harvest': simulate_harvest_v2}
SIMULATE_V3 = {'cultivate': simulate_cultivate_v3, 'sow': simulate_sow_v3, 'harvest': simulate_harvest_v3, 'spray': simulate_spray_v3}


def simulate_full(field, run, path):
    """Full result of a path: ``dict(score, condition, hits, repair)`` or None; old and rules=2 runs report a clean machine."""
    rules = run.get('rules')
    if rules is not None and rules >= FIELD_RULES:
        return SIMULATE_V3[run['op']](field, run, path)
    table = SIMULATE_V2 if rules == 2 else SIMULATE
    score = table[run['op']](field, run, path)
    return None if score is None else _v3_result(score, 100, 0)


def simulate(field, run, path):
    result = simulate_full(field, run, path)
    return None if result is None else result['score']


def quality(score):
    """Manual quality in permille from a score in permille (old economy, open runs)."""
    return Q_BASE + Q_SPAN * score // 1000


def quality_full(score):
    """Manual quality of the full test economy: 0.85 at a bad run, 1.25 at a perfect one."""
    return Q_BASE_FULL + Q_SPAN_FULL * score // 1000


QRULE_TIMED = 2                    # run['qrule']: the bonus over the autopilot melts with the time of the run (runs without it: plain quality)


def _timed(score, elapsed, ha, width, base, span, q_auto):
    q = base + span * score // 1000
    bonus = q - q_auto
    if bonus <= 0:
        return q
    a = auto_seconds(ha, width)
    full, zero = a * FIELD_FULL_K // 100, a * FIELD_ZERO_K // 100
    keep = 1000 if elapsed <= full else 0 if elapsed >= zero else (zero - elapsed) * 1000 // (zero - full)
    return q_auto + bonus * keep // 1000


def timed_quality(score, elapsed, ha, width):
    """Manual quality when the run took ``elapsed`` seconds: the bonus over the autopilot is whole within FIELD_FULL_K % of the
    autopilot time A (in real seconds, no world speed), falls linearly to 0 at FIELD_ZERO_K %; a worse-than-autopilot drive keeps its quality."""
    return _timed(score, elapsed, ha, width, Q_BASE, Q_SPAN, Q_AUTO)


def timed_quality_full(score, elapsed, ha, width):
    """The same time rule for the full economy: the bonus over the 900 autopilot melts with time."""
    return _timed(score, elapsed, ha, width, Q_BASE_FULL, Q_SPAN_FULL, Q_AUTO_FULL)


def damage_penalty(condition):
    return max(0, 100 - condition) * FIELD_COND_PENALTY


def condition_quality(q, condition):
    """Full-economy quality after machine damage: every missing condition point costs 4 permille, clamped to 0.85 .. 1.25."""
    return max(Q_BASE_FULL, min(Q_BASE_FULL + Q_SPAN_FULL, q - damage_penalty(condition)))


def growth_permille(q_cult):
    """Growth-time multiplier (permille) after cultivation of quality ``q_cult``: 950 -> 1000, best 1250 -> 700."""
    return 1950 - q_cult


def spray_bonus_permille(q_spray):
    """Yield multiplier of a sprayed crop: 1.00 at 850 quality, up to 1.20 at 1250 (the approved test economy)."""
    if not q_spray:
        return 1000
    bonus = max(0, q_spray - FIELD_SPRAY_BONUS_BASE) * 1000 // FIELD_SPRAY_BONUS_SPAN
    return min(FIELD_SPRAY_BONUS_MAX, 1000 + bonus)


def yield_qty(base, q_sow, q_harvest, q_spray=1000):
    return max(1, base * q_sow * q_harvest * q_spray // 10 ** 9)


def auto_seconds(ha, width, speed=1):
    return max(1, math.ceil(FIELD_AUTO_S * ha / width / speed))


# ------------------------------------------------------------------------------------------------ reference driver
def reference_path(field, run):
    """An honest planner (what a good player does): sweeps in snakes, detours around rocks, unloads the combine at the top edge.
    Used by tests, the fixtures and the balance simulator's ``skilled`` profile; it only ever emits valid paths."""
    W, H, width, rocks = _geometry(field, run)
    op = run['op']
    reach = reachable_anchors(W, H, width, rocks)
    weeds = frozenset(run.get('weeds') or ())
    cap = HOPPER * width * (H // W)
    pos = (0, 0)
    path = []
    done, load = set(), 0           # covered cells (cultivate/harvest) or sown cells (sow)
    sow_lane = lambda a: a[0] % (width + 1) == 0

    def arrive(a, event=False):
        nonlocal load
        cells = _bar(a[0], a[1], W, width)
        if op == 'sow':
            if sow_lane(a):
                done.update(cells)
            return
        for c in cells:
            if c not in done:
                done.add(c)
                if op == 'harvest' and load < cap:
                    load += 1

    def want(a):
        cells = _bar(a[0], a[1], W, width)
        if op == 'sow':
            return sow_lane(a) and any(c not in done for c in cells)
        return any(c not in done for c in cells)

    def route(goal):
        """Cheapest anchor route (Dijkstra; stepping onto finished ground costs more) to the nearest anchor satisfying ``goal``."""
        heap, best, prev = [(0, pos[1], pos[0], pos)], {pos: 0}, {}
        while heap:
            cost, _, _, cur = heapq.heappop(heap)
            if cost > best[cur]:
                continue
            if cur != pos and goal(cur):
                steps = []
                while cur != pos:
                    steps.append(cur)
                    cur = prev[cur]
                return steps[::-1]
            for ch in 'DRLU':
                nxt = _step(cur[0], cur[1], ch, W, H, width, rocks)
                if nxt is None:
                    continue
                price = 1 + (0 if want(nxt) else (30 if op == 'sow' and sow_lane(nxt) else 2))
                if cost + price < best.get(nxt, 10 ** 9):
                    best[nxt] = cost + price
                    prev[nxt] = cur
                    heapq.heappush(heap, (cost + price, nxt[1], nxt[0], nxt))
        return None

    def go(steps):
        nonlocal pos
        for a in steps:
            dx, dy = a[0] - pos[0], a[1] - pos[1]
            path.append({(0, -1): 'U', (0, 1): 'D', (-1, 0): 'L', (1, 0): 'R'}[(dx, dy)])
            pos = a
            arrive(a)

    arrive(pos)
    lane = H * width

    def unload(force=False):
        """Unload at the top edge when the next lane would not fit (``force``: whenever something is loaded)."""
        nonlocal load
        if op != 'harvest' or load == 0 or not (force or load + lane > cap):
            return True
        if pos[1] != 0 or (run.get('unload_zone') and not _near_unload(pos[0], width)):
            home = route(lambda a: a[1] == 0 and (not run.get('unload_zone') or _near_unload(a[0], width)))
            if home is None:
                return False
            go(home)
        path.append('X')
        load = 0
        return True

    # 1. the snake: lane after lane, alternating direction; blocked rows are bypassed by the cheapest route
    pitch = width + 1 if op == 'sow' else width
    lanes = sorted({min(k * pitch, W - width) for k in range(-(-W // pitch))})
    for x in lanes:
        rows = range(H) if pos[1] <= (H - 1) // 2 else range(H - 1, -1, -1)      # sweep away from where we stand
        unload()
        for y in rows:
            target = (x, y)
            if target in reach and target != pos and want(target):
                go(route(lambda a: a == target) or [])
        unload()
    # 2. clean-up of whatever the snake left behind (ground around rocks), nearest first
    while True:
        steps = route(want)
        if steps is None:
            break
        if op == 'harvest' and load > 0 and load + width * len(steps) > cap:     # would overflow: unload at the top edge first
            if not unload(force=True):
                break
            continue
        go(steps)
    return ''.join(path)


# ------------------------------------------------------------------------------------------------ run creation
def _stream(seed, label):
    i = 0
    while True:
        for byte in sha256(f'{seed}:{label}:{i}'.encode()).digest():
            yield byte
        i += 1


def make_obstacles(seed, op, W, H, ha):
    """Deterministic rocks (never in row 0, at most one per row) and cultivation weeds from sha256(seed)."""
    rng = _stream(seed, op)
    rocks, rows = [], set()
    for _ in range(ROCKS_PER_HA[op] * ha * 8):
        if len(rocks) >= ROCKS_PER_HA[op] * ha:
            break
        row, col = 1 + next(rng) % (H - 1), next(rng) % W
        if row not in rows:
            rows.add(row)
            rocks.append(row * W + col)
    weeds = []
    if op == 'cultivate':
        for _ in range(WEEDS_PER_HA * ha * 8):
            if len(weeds) >= WEEDS_PER_HA * ha:
                break
            c = (next(rng) * 256 + next(rng)) % (W * H)
            if c not in weeds and c not in rocks:
                weeds.append(c)
    return sorted(rocks), sorted(weeds)


# ------------------------------------------------------------------------------------------------ state
def fields_of(farm):
    return farm.get('fields') or []


def machines_of(farm):
    return farm.get('field_machines') or {}


def find_field(farm, field_id):
    need(isinstance(field_id, str), 'invalid_command', 'Некорректное поле.', 422)
    return find(fields_of(farm), field_id)


def new_field(spec):
    return dict(id=f'field_{spec["step"]}', step=spec['step'], ha=spec['ha'], w=FIELD_W, h=FIELD_W * spec['ha'], state='wild',
                crop=None, run=None, q_cult=Q_AUTO, seq=0, revision=0)


STATE_TEXT = {'wild': 'Дикое поле', 'ready': 'Подготовлено', 'growing': 'Растёт', 'ripe': 'Созрело'}


def apply_field(farm, kind, data, now, command_id, speed, upkeep_config=None):
    lv = level(farm['xp'])
    if kind == 'buy_field':
        step = data['step']
        need(type(step) is int and 0 <= step < len(FIELD_STEPS), 'invalid_command', 'Неизвестный участок.', 422)
        spec = FIELD_STEPS[step]
        need(lv >= spec['level'], 'locked', f'Это поле открывается с {spec["level"]} уровня.')
        need(all(f['step'] != step for f in fields_of(farm)), 'already_owned', 'Это поле уже куплено.')
        pay(farm, spec['cost'])
        farm.setdefault('fields', []).append(new_field(spec))
        per_hectare = settings_for(upkeep_config)['field_per_hectare']
        return f'Поле {spec["ha"]} га куплено. Содержание — {per_hectare * spec["ha"]} монет в сутки.'
    if kind in {'buy_machine', 'upgrade_machine'}:
        spec = named(FIELD_MACHINES, data['machine'])
        owned = farm.setdefault('field_machines', {})
        if kind == 'buy_machine':
            need(spec['id'] not in owned, 'already_owned', 'Эта машина уже есть.')
            tier = 0
        else:
            need(spec['id'] in owned, 'not_owned', 'Сначала купи машину.')
            tier = owned[spec['id']]['tier']
            need(tier < len(spec['costs']), 'max_tier', 'Машина уже самой большой ширины.')
        need(lv >= spec['levels'][tier], 'locked', f'Нужен уровень {spec["levels"][tier]}.')
        pay(farm, spec['costs'][tier])
        owned.setdefault(spec['id'], dict(tier=0, acquired_at=now))['tier'] = tier + 1
        return f'{spec["name"]}: ширина {tier + 1}.'
    if kind == 'field_start':
        return _start(farm, data, now, speed, lv)
    if kind == 'field_cancel':
        return _cancel_sowing(farm, data, now)
    return _finish(farm, data, now, speed)


def _start(farm, data, now, speed, lv):
    f = find_field(farm, data['field'])
    need(type(data['revision']) is int and data['revision'] == f['revision'], 'stale_object', 'Поле изменилось. Обнови ферму.')
    op = data['op']
    need(isinstance(op, str) and op in FIELD_OPS, 'invalid_command', 'Неизвестная операция.', 422)
    spec = FIELD_OPS[op]
    need(f.get('run') is None, 'field_busy', 'На поле уже идёт работа.')
    need(f['state'] == spec['src'], 'wrong_state', 'Эта операция сейчас невозможна на этом поле.')
    machine = machines_of(farm).get(spec['machine'])
    need(machine is not None, 'not_owned', f'Нужна машина: {FIELD_MACHINES[spec["machine"]]["name"]}.')
    seeds = 0
    crop_id = ''
    if op == 'sow':
        crop = named(CROPS, data['crop'])
        need(crop['field'], *(('orchard_crop', 'Плодовые деревья теперь растут в саду: посади саженец во вкладке «Сад».') if crop.get('orchard') else ('not_field_crop', 'Эта культура не растёт на полях.')))
        need(lv >= crop['level'], 'locked', 'Эта культура пока не открыта.')
        crop_id, seeds = crop['id'], crop['cost'] * FIELD_SEED_MULT * f['ha']
    else:
        need(data['crop'] == '', 'invalid_command', 'Культура указывается только при посеве.', 422)
    if op == 'spray':
        need(isinstance(f.get('crop'), dict) and not f['crop'].get('q_spray'), 'already_sprayed', 'Это поле уже обработано.')
    fuel = FIELD_FUEL * f['ha']
    need(farm['coins'] >= fuel + seeds, 'insufficient_coins', 'Не хватает монет на топливо и семена.')
    gift = pay(farm, fuel + seeds)
    seed = sha256(f'{farm["id"]}:{f["id"]}:{f["seq"]}:{op}'.encode()).hexdigest()[:24]
    rocks, weeds = make_obstacles(seed, op, f['w'], f['h'], f['ha'])
    f['run'] = dict(id=f'run_{f["seq"]}', op=op, status='open', crop=crop_id, started_at=now, expires_at=now + FIELD_RUN_TTL,
                    width=machine['tier'], seed=seed, rocks=rocks, weeds=weeds, speed=speed, qrule=QRULE_TIMED,
                    rules=FIELD_RULES, unload_zone=(op in {'harvest', 'spray'}), sow_reach=(op == 'sow'),
                    tank=(FIELD_TANK * f['ha'] if op == 'spray' else 0), wind=(1 if int(seed[-1], 16) % 2 else -1) if op == 'spray' else 0)
    if op == 'sow':      # E27 F4: what the sowing took, so that undoing it gives exactly this back
        f['run'].update(cost=seeds, fuel=fuel, gift=gift)
    f['seq'] += 1
    f['revision'] += 1
    return f'{FIELD_MACHINES[spec["machine"]]["name"]} выехал в поле (ширина {machine["tier"]}).'


def _cancel_sowing(farm, data, now):
    """E27 F4: take back a mistaken sowing in the first ``undo.UNDO_WINDOW`` seconds (the same canon as digging up a bed): the seeds and the
    fuel come back in full (and the starter-gift part is restored), nothing was harvested, the field stays cultivated.  It works on an
    unfinished sowing run (open or autopilot) and on the crop that this run has just planted.  Repair of bumps is not returned."""
    from . import undo
    f = find_field(farm, data['field'])
    need(type(data['revision']) is int and data['revision'] == f['revision'], 'stale_object', 'Поле изменилось. Обнови ферму.')
    run, crop = f.get('run'), f.get('crop')
    if run is not None and run['op'] == 'sow' and run['status'] in {'open', 'auto'}:
        need(now - run['started_at'] <= undo.UNDO_WINDOW, 'undo_expired', 'Отменить посев можно только в первую минуту.')
        seeds = run['cost'] if type(run.get('cost')) is int else CROPS[run['crop']]['cost'] * FIELD_SEED_MULT * f['ha']
        fuel = run['fuel'] if type(run.get('fuel')) is int else FIELD_FUEL * f['ha']
        gift, name = run.get('gift', 0), CROPS[run['crop']]['name']
        f['run'] = None
    else:
        need(f['state'] == 'growing' and isinstance(crop, dict), 'nothing_to_cancel', 'Сейчас на поле нечего отменять.')
        need(now - crop['planted_at'] <= undo.UNDO_WINDOW, 'undo_expired', 'Отменить посев можно только в первую минуту.')
        seeds = crop['cost'] if type(crop.get('cost')) is int else CROPS[crop['id']]['cost'] * FIELD_SEED_MULT * f['ha']
        fuel = crop['fuel'] if type(crop.get('fuel')) is int else FIELD_FUEL * f['ha']
        gift, name = crop.get('gift', 0), CROPS[crop['id']]['name']
        f['state'], f['crop'] = 'ready', None
    refund = seeds + fuel
    farm['coins'] += refund
    undo.restore_gift(farm, gift, refund)
    f['revision'] += 1
    return f'{FIELD_MACHINES["seeder"]["name"]}: посев отменён ({name}), семена и топливо вернулись полностью: +{refund} монет.'


def _finish(farm, data, now, speed):
    f = find_field(farm, data['field'])
    run = f.get('run')
    need(run is not None and isinstance(data['run'], str) and run['id'] == data['run'] and run['status'] == 'open',
         'run_closed', 'Эта работа уже закончена или закрыта.')
    path = data['path']
    if path is None:                                   # autopilot: ready after 90 s * ha / width, the owner ordered it
        run['status'] = 'auto'
        run['owner'] = True
        run['done_at'] = now + auto_seconds(f['ha'], run['width'], run['speed'])
        f['revision'] += 1
        return 'Автопилот взялся за работу.'
    rules = run.get('rules')
    allowed = set('UDLRT') | ({'X'} if run['op'] in {'harvest', 'spray'} else set())
    if rules is None or rules < 2:
        allowed.discard('T')
    if rules is not None and rules >= FIELD_RULES:
        allowed.update(BUMP_DIRS)
    need(isinstance(path, str) and len(path) <= max_path(f, run) and set(path) <= allowed,
         'bad_path', 'Недопустимый маршрут.', 422)
    need(100 * (now - run['started_at']) >= FIELD_STEP_CS * len(path), 'too_fast', 'Слишком быстро для такой работы.', 422)
    result = simulate_full(f, run, path)
    need(result is not None, 'bad_path', 'Маршрут нарушает правила поля.', 422)
    if rules is not None and rules >= FIELD_RULES:
        condition, hits = result['condition'], result['hits']
        if condition <= 0:
            q = Q_AUTO_FULL
        else:
            q = condition_quality(quality_full(result['score']), condition)
            if run.get('qrule') == QRULE_TIMED:
                a = auto_seconds(f['ha'], run['width'])
                full, zero = a * FIELD_FULL_K // 100, a * FIELD_ZERO_K // 100
                elapsed = now - run['started_at']
                keep = 1000 if elapsed <= full else 0 if elapsed >= zero else (zero - elapsed) * 1000 // (zero - full)
                bonus = q - Q_AUTO_FULL
                if bonus > 0:
                    q = Q_AUTO_FULL + bonus * keep // 1000
        return complete(farm, f, run, q, now, True, condition=condition, hits=hits)
    q = timed_quality(result['score'], now - run['started_at'], f['ha'], run['width']) if run.get('qrule') == QRULE_TIMED else quality(result['score'])
    return complete(farm, f, run, q, now, True)


def complete(farm, f, run, q, at, owner, condition=100, hits=0):
    """Close the run of ``f`` with quality ``q`` (permille) at time ``at``; returns the notice."""
    op = run['op']
    f['run'] = None
    f['revision'] += 1
    name = FIELD_MACHINES[FIELD_OPS[op]['machine']]['name']
    pct = f'{q / 10:.1f}%'.replace('.', ',')
    repair = hits * FIELD_HIT_REPAIR
    if op == 'cultivate':
        f['state'], f['q_cult'] = 'ready', q
        text = f'{name}: поле подготовлено, качество {pct}.'
    elif op == 'sow':
        crop = CROPS[run['crop']]
        seconds = max(crop['seconds'], FIELD_MIN_GROW) * growth_permille(f['q_cult']) / 1000
        f['state'] = 'growing'
        f['crop'] = dict(id=crop['id'], planted_at=at, ready_at=at + duration(seconds, run['speed'], farm if owner else None),
                         base=crop['yield_qty'] * FIELD_YIELD_MULT * f['ha'], xp=crop['xp'], q_sow=q, version=VERSION)
        for key in ('cost', 'fuel', 'gift'):          # E27 F4: the price of the sowing, kept for the first minute (runs opened before it have none)
            if type(run.get(key)) is int:
                f['crop'][key] = run[key]
        text = f'{name}: {crop["name"]} посеяна, качество {pct}.'
    elif op == 'spray':
        c = f['crop']
        c['q_spray'], c['sprayed_at'] = q, at
        bonus = spray_bonus_permille(q)
        text = f'{name}: поле обработано, качество {pct}, прибавка к урожаю +{(bonus - 1000) / 10:.1f}%.'.replace('.', ',')
    else:
        c = f['crop']
        spray = spray_bonus_permille(c.get('q_spray'))
        qty = yield_qty(c['base'], c['q_sow'], q, spray)
        inventory(farm, {c['id']: qty})
        gain = max(1, c['xp'] * FIELD_XP_MULT * f['ha'] * c['q_sow'] * q * spray // 10 ** 9)
        progression.grant_xp(farm, gain, 'field', at, owner)
        market.count(farm, 'h:' + c['id'], qty)
        f['state'], f['crop'], f['q_cult'] = 'wild', None, Q_AUTO
        text = f'{name}: убрано {ITEMS[c["id"]]["name"]} ×{qty}, качество {pct}.'
    if repair:
        farm['coins'] -= min(repair, farm['coins'])
        text += f' Ремонт {repair} монет.'
    f['last_run_at'], f['last_q'] = at, q                  # the client reads the exact quality of the run it just finished
    if run.get('rules') is not None and run['rules'] >= FIELD_RULES:
        f['last_hits'], f['last_repair'], f['last_condition'] = hits, repair, condition
    event(farm, at, text, 'field')
    return text


def settle(farm, now):
    """Materialise finished autopilot runs, expired runs (closed as the autopilot, owner=False, at their deadline) and ripening."""
    for f in sorted(fields_of(farm), key=lambda x: x['id']):
        run = f.get('run')
        full = run is not None and run.get('rules') is not None and run['rules'] >= FIELD_RULES
        auto_q = Q_AUTO_FULL if full else Q_AUTO
        if run and run['status'] == 'auto' and run['done_at'] <= now:
            complete(farm, f, run, auto_q, run['done_at'], run.get('owner', False))
        elif run and run['status'] == 'open' and run['expires_at'] <= now:
            complete(farm, f, run, auto_q, run['expires_at'], False)
        if f['state'] == 'growing' and f['crop']['ready_at'] <= now:
            f['state'] = 'ripe'
            f['revision'] += 1


def validate(farm):
    seen = set()
    for f in farm.get('fields') or []:
        run = f.get('run')
        need(isinstance(f, dict) and f.get('id') not in seen and type(f.get('step')) is int and 0 <= f['step'] < len(FIELD_STEPS)
             and f.get('ha') == FIELD_STEPS[f['step']]['ha'] and f.get('w') == FIELD_W and f.get('h') == FIELD_W * f['ha']
             and f.get('state') in STATE_TEXT and all(type(f.get(k)) is int and f[k] >= 0 for k in ('seq', 'revision', 'q_cult'))
             and (f['state'] in {'growing', 'ripe'}) == isinstance(f.get('crop'), dict),
             'invalid_field', 'Некорректное состояние поля.', 500)
        seen.add(f['id'])
        if f['crop'] is not None:
            need(f['crop'].get('id') in CROPS and type(f['crop'].get('ready_at')) is int and type(f['crop'].get('base')) is int
                 and f['crop']['base'] > 0 and type(f['crop'].get('q_sow')) is int, 'invalid_field', 'Некорректная посадка на поле.', 500)
        if run is not None:
            need(run.get('op') in FIELD_OPS and run.get('status') in {'open', 'auto'} and type(run.get('width')) is int
                 and 1 <= run['width'] <= 3 and FIELD_OPS[run['op']]['src'] == f['state']
                 and isinstance(run.get('rocks'), list) and isinstance(run.get('weeds'), list)
                 and run.get('rules') in (None, 2, 3)
                 and (run.get('unload_zone') is None or type(run['unload_zone']) is bool)
                 and (run.get('sow_reach') is None or type(run['sow_reach']) is bool)
                 and (run['op'] != 'spray' or (type(run.get('tank')) is int and run['tank'] > 0 and run.get('wind') in (-1, 1)))
                 and (run['status'] != 'auto' or type(run.get('done_at')) is int), 'invalid_field', 'Некорректная работа на поле.', 500)
        for key, lo, hi in (('last_hits', 0, 10 ** 6), ('last_repair', 0, 10 ** 9), ('last_condition', 0, 100)):
            if key in f:
                need(type(f[key]) is int and lo <= f[key] <= hi, 'invalid_field', 'Некорректное состояние машины.', 500)
    machines = farm.get('field_machines') or {}
    need(set(machines) <= set(FIELD_MACHINES) and all(isinstance(m, dict) and m.get('tier') in (1, 2, 3) for m in machines.values()),
         'invalid_field', 'Некорректный парк машин.', 500)
