"""Version 1 of the fair pie-tower replay. Integers only; mirrored by qw_farm/static/pie-physics.js."""
from hashlib import sha256

VERSION = 1
TTL = 65
LIMIT_MS = 60000
FALL_MS = 320
MIN_GAP_MS = 400
WARMUP_MS = 700
MAX_TAPS = 160
BASE = 560
X0, X1 = 140, 860
T0, STEP, TMIN = 4200, 100, 1800
WIDTH, HEIGHT = 1000, 600
TOWER_CENTER = 500


def make_plan(seed):
    digest = sha256(str(seed).encode()).digest()
    return dict(version=VERSION, width=WIDTH, height=HEIGHT,
                base=BASE, x0=X0, x1=X1, t0=T0, step=STEP, tmin=TMIN,
                phase=int.from_bytes(digest[:4], 'big') % T0,
                fall_ms=FALL_MS, min_gap_ms=MIN_GAP_MS, warmup_ms=WARMUP_MS, limit_ms=LIMIT_MS,
                max_taps=MAX_TAPS)


def crane_x(plan, t, height):
    """Crane centre at ``t`` ms when the tower already has ``height`` layers."""
    period = max(plan['tmin'], plan['t0'] - plan['step'] * height)
    p = (max(0, t - plan['warmup_ms']) + plan['phase']) % period
    u = p * 2000 // period
    q = u if u <= 1000 else 2000 - u
    return plan['x0'] + (plan['x1'] - plan['x0']) * q // 1000


def drop(tower_lo, tower_hi, x, base):
    """The tower interval after a layer centred at ``x``; None when nothing overlaps."""
    lo = max(tower_lo, x - base // 2)
    hi = min(tower_hi, x + base // 2)
    return (lo, hi) if hi > lo else None


def log_valid(plan, log):
    if type(log) is not list or len(log) > plan['max_taps']:
        return False
    previous = None
    for t in log:
        if type(t) is not int or isinstance(t, bool) or t < 0 or t > plan['limit_ms']:
            return False
        if previous is not None and t - previous < plan['min_gap_ms']:
            return False
        previous = t
    return True


def replay(plan, log):
    """Height, final tower and the reason the run ended; a tap past the limit is ignored."""
    tower_lo = TOWER_CENTER - plan['base'] // 2
    tower_hi = TOWER_CENTER + plan['base'] // 2
    height = 0
    miss = False
    taps = 0
    for t in log:
        if t > plan['limit_ms']:
            break
        taps += 1
        x = crane_x(plan, t, height)
        landed = drop(tower_lo, tower_hi, x, plan['base'])
        if landed is None:
            miss = True
            break
        tower_lo, tower_hi = landed
        height += 1
    return dict(height=height, tower=[tower_lo, tower_hi], miss=miss, taps=taps)
