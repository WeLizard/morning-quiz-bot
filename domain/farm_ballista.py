"""Version one of Pukh's replay physics. Integers only; mirrored by the JS client."""
from hashlib import sha256
from math import isqrt
from functools import lru_cache

VERSION = 1
SHOTS = 5
STEP_MS = 40
TTL = 180
WINDOWS = ((270,330),(430,250),(600,200),(760,300),(900,400))


@lru_cache(maxsize=64)
def _reachable(x, y, wind, with_roof):
    roof = dict(left=420,right=560,y=360) if with_roof else None
    return any((px-x)**2+(py-y)**2 <= 36**2
               for angle in range(15000,75001,2000) for power in range(200,1001,20)
               for px,py in trajectory(angle,power,wind,roof))


def trajectory(angle, power, wind, roof=None):
    x, y = 60, 500
    vx = power * (90000 - angle) // 1800000
    vy = -(power * angle // 900000)
    points = [[x, y]]
    bounced = False
    for step in range(1, 151):
        old_y = y
        x += vx
        y += vy
        vy += 2
        if step % 4 == 0:
            vx += wind
        if (roof and not bounced and vy > 0 and old_y < roof['y'] <= y
                and roof['left'] <= x <= roof['right']):
            y = roof['y']
            vy = -(vy * 7 // 10)
            bounced = True
        points.append([x, y])
        if y > 600 or x > 1100 or x < -100:
            break
    return points


def make_plan(seed):
    digest = sha256(str(seed).encode()).digest()
    targets = []
    for i in range(SHOTS):
        x,y = WINDOWS[(i+digest[31]) % SHOTS]
        wind = digest[i] % 5 - 2
        roof = dict(left=420, right=560, y=360)
        if not _reachable(x,y,wind,bool(roof)):
            wind = 0
        assert _reachable(x,y,wind,bool(roof))
        targets.append(dict(x=x, y=y, radius=36, wind=wind, roof=roof))
    return dict(version=VERSION, width=1000, height=600, step_ms=STEP_MS, targets=targets)


def replay(plan, log):
    """Return (score, hits, durations); raises ValueError for malformed/fast logs."""
    if type(log) is not list or len(log) != SHOTS:
        raise ValueError('five_shots')
    total = hits = 0
    durations = []
    previous_end = 0
    for target, shot in zip(plan['targets'], log):
        if (type(shot) is not list or len(shot) != 3
                or any(type(n) is not int for n in shot)):
            raise ValueError('invalid_shot')
        angle, power, release = shot
        if not 15000 <= angle <= 75000 or not 200 <= power <= 1000:
            raise ValueError('invalid_shot')
        if release < previous_end + 250 or release > TTL * 1000:
            raise ValueError('too_fast')
        path = trajectory(angle, power, target['wind'], target['roof'])
        distances = [(x-target['x'])**2 + (y-target['y'])**2 for x, y in path]
        distance = isqrt(min(distances))
        hit = min(distances) <= target['radius']**2
        # A hit ends flight at its closest point; a miss must reach the boundary.
        steps = distances.index(min(distances)) if hit else len(path)-1
        duration = steps * STEP_MS
        durations.append(duration)
        previous_end = release + duration
        if hit:
            hits += 1
            total += 800 + 200 * max(0, target['radius']-distance) // target['radius']
    return total // SHOTS, hits, durations
