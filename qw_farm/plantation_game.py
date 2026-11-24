"""Server replay for the versioned manual plantation games."""
from hashlib import sha256

from .domain import need

VERSION = 1
SIZE = 8
CAPACITY = 8
TTL = 15 * 60
LIMITS = {'harvest': 384, 'prune': 40}
TARGET_COUNTS = {'harvest': 24, 'prune': 8}
MOVES = {'U': (0, -1), 'D': (0, 1), 'L': (-1, 0), 'R': (1, 0)}


def _target_key(seed, cell):
    return sha256(f'{seed}:{cell}'.encode()).digest()


def targets(seed, op):
    if op == 'harvest':
        candidates = range(1, SIZE * SIZE)
    else:
        # Two adjacent rows let the player reach every marked shoot within 40 actions.
        first_row = 2 * (int.from_bytes(_target_key(seed, 0)[:2], 'big') % (SIZE // 2))
        candidates = range(max(1, first_row * SIZE), (first_row + 2) * SIZE)
    return sorted(sorted(candidates, key=lambda cell: _target_key(seed, cell))[:TARGET_COUNTS[op]])


def new_run(farm_id, hectare, op, command_id, now):
    # The cycle identity survives expiry and opening a fresh run with a new command ID.
    seed = f'{VERSION}:{farm_id}:{hectare["id"]}:{hectare["crop"]}:{hectare["cycle"]["started_at"]}:{op}'
    return dict(v=VERSION, id=command_id, op=op, revision=hectare['revision'] + 1,
                expires_at=now + TTL, targets=targets(seed, op))


def public(run):
    op = run['op']
    return dict(id=run['id'], op=op, targets=list(run['targets']), expires_at=run['expires_at'],
                limit=LIMITS[op], capacity=CAPACITY if op == 'harvest' else 0)


def replay(run, path):
    """Replay movement, first actions on cells, and loads delivered at the start."""
    op = run['op']
    need(type(path) is str and 0 < len(path) <= LIMITS[op], 'invalid_plantation_path',
         'Некорректный журнал плантации.', 422)

    def valid(condition):
        need(condition, 'invalid_plantation_path', 'Некорректное действие на плантации.', 422)

    x = y = cuts = misses = carried = delivered = 0
    acted = set()
    goals = set(run['targets'])
    for action in path:
        cell = y * SIZE + x
        if action in MOVES:
            dx, dy = MOVES[action]
            x, y = x + dx, y + dy
            valid(0 <= x < SIZE and 0 <= y < SIZE)
        elif action == 'C':
            valid(cell != 0 and cell not in acted and (op == 'prune' or carried < CAPACITY))
            acted.add(cell)
            if cell not in goals:
                misses += 1
            elif op == 'prune':
                cuts += 1
            else:
                carried += 1
        else:
            valid(op == 'harvest' and action == 'X' and cell == 0 and carried > 0)
            delivered += carried
            carried = 0
    if op == 'prune':
        return dict(success=max(0, cuts - misses) * 4 >= len(goals) * 3)
    need(delivered > 0, 'empty_plantation_harvest', 'Доставь хотя бы один собранный куст к повозке.')
    need(carried == 0, 'undelivered_plantation_harvest', 'Выгрузи корзину у повозки перед завершением.')
    return dict(quality=max(85, min(125, 85 + 40 * delivered // len(goals) - 4 * misses)),
                penalty=min(20, 5 * misses))


def valid_run(run, revision):
    if (type(run) is not dict or set(run) != {'v', 'id', 'op', 'revision', 'expires_at', 'targets'}
            or type(run['op']) is not str or run['op'] not in LIMITS):
        return False
    cells = run['targets']
    return (type(run['v']) is int and run['v'] == VERSION
            and type(run['id']) is str and 0 < len(run['id']) <= 64
            and type(run['revision']) is int and run['revision'] == revision
            and type(run['expires_at']) is int and run['expires_at'] > 0
            and type(cells) is list and len(cells) == TARGET_COUNTS[run['op']]
            and all(type(cell) is int and 0 < cell < SIZE * SIZE for cell in cells)
            and len(set(cells)) == len(cells))
