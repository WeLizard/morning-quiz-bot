"""Compare land-expansion curves beyond 20x20 (docs/tasks/FARM_LAND_PROGRESSION.md).

Variant A (slow beds) was approved on 2026-10-14 and now lives in qw_farm/catalog.py: run with --variant game to simulate the
real catalog. A (area beds), B and C are what-if curves applied in memory only (table prices of sizes 10..20 stay untouched)
on top of the normal balance simulator.

    python scripts/farm_land_curve_sim.py --table                 # price / level / upkeep tables only
    python scripts/farm_land_curve_sim.py --days 160 --profile active --variant game
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CEILING = 60          # technical sanity bound of the model (not a game rule)
LAST_TABLE = 20


def r_nice(v):
    """Round a price to 2-3 significant digits so the numbers look like designed prices."""
    step = 10 ** max(0, len(str(int(v))) - 3)
    return int(round(v / step) * step)


BEDS_MODE = 'area'


def beds(s):
    if BEDS_MODE == 'slow':                # land is room for buildings / decor / fields: +5 beds per step only
        return 120 + 5 * (s - LAST_TABLE) // 2
    return 3 * s * s // 10                 # 0.30 beds per cell: 20 -> 120 (as in PLOT_LIMITS)


def objects(s):
    return 200 + 2 * (s * s - 400) // 5    # +0.4 objects per new cell


# name: (description, cost(s, n), level(n), upkeep per bed(s, n))
VARIANTS = {
    'A': ('power law in size: cost = 25000*(s/20)^6, upkeep/bed = 30*(s/20)^2, level 18+5n',
          lambda s, n: r_nice(25000 * (s / 20) ** 6),
          lambda n: min(50, 18 + 5 * n),
          lambda s, n: round(30 * (s / 20) ** 2)),
    'B': ('gentle geometric: cost = 25000*1.30^n, upkeep/bed = 30+4n, level 18+4n',
          lambda s, n: r_nice(25000 * 1.30 ** n),
          lambda n: min(50, 18 + 4 * n),
          lambda s, n: 30 + 4 * n),
    'C': ('steep geometric: cost = 25000*1.70^n, upkeep/bed = 30*(s/20)^3, level 18+6n',
          lambda s, n: r_nice(25000 * 1.70 ** n),
          lambda n: min(50, 18 + 6 * n),
          lambda s, n: round(30 * (s / 20) ** 3)),
}


def table(name, rows=12):
    desc, cost, lvl, upk = VARIANTS[name]
    print(f'variant {name}: {desc}')
    print(f'{"size":>5} {"cost":>11} {"level":>6} {"beds":>5} {"objs":>5} {"upkeep/bed":>11} {"upkeep/day full":>16} {"cum cost":>12}')
    cum = 0
    for n in range(1, rows + 1):
        s = LAST_TABLE + 2 * n
        c = cost(s, n)
        cum += c
        print(f'{s:>5} {c:>11,} {lvl(n):>6} {beds(s):>5} {objects(s):>5} {upk(s, n):>11} {beds(s) * upk(s, n):>16,} {cum:>12,}')
    print()


def install(name):
    """Patch the game modules in memory: land_step / is_land_size / land_bound plus the per-size tables."""
    import qw_farm.catalog as C
    import qw_farm.domain as D
    import qw_farm.expansion as X
    _, cost, lvl, upk = VARIANTS[name]
    table_steps = {s['size']: s for s in C.LAND_STEPS}
    for s in range(LAST_TABLE + 2, CEILING + 1, 2):
        n = (s - LAST_TABLE) // 2
        table_steps[s] = dict(size=s, cost=cost(s, n), level=lvl(n))
        C.PLOT_LIMITS[s] = beds(s)
        C.OBJECT_LIMITS[s] = objects(s)
        C.PLOT_UPKEEP[s] = upk(s, n)      # the dicts are shared with economy / market by reference

    def is_land_size(v):
        return type(v) is int and C.LAND_START <= v <= CEILING and v % 2 == 0

    def land_step(size):
        return table_steps.get(size + 2) if is_land_size(size) else None

    def land_bound():
        return CEILING

    for mod in (C, D):
        mod.is_land_size = is_land_size
        mod.land_step = land_step
    for mod in (C, D, X):
        mod.land_bound = land_bound


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--table', action='store_true')
    ap.add_argument('--variant', default='game', choices=['game', *sorted(VARIANTS)])
    ap.add_argument('--days', type=int, default=160)
    ap.add_argument('--profile', default='active')
    ap.add_argument('--beds', default='area', choices=['area', 'slow'], help='bed limit beyond 20x20: 0.3 per cell or +5 per step')
    args = ap.parse_args()
    global BEDS_MODE
    BEDS_MODE = args.beds
    if args.table:
        for name in VARIANTS:
            table(name)
        return
    if args.variant != 'game':
        install(args.variant)
    import farm_balance_sim as S
    import qw_farm.catalog as C
    reached = {}
    orig = S.Sim.cmd

    def cmd(self, kind, data, now, tag):
        ok = orig(self, kind, data, now, tag)
        if ok and kind == 'expand':
            reached[self.f['size']] = (now - self.t0) / 86400
        return ok

    S.Sim.cmd = cmd
    print(f'variant {args.variant}: ' + (VARIANTS[args.variant][0] if args.variant != 'game' else 'the catalog as it is'))
    sim = S.Sim(args.profile, args.days, False, True).run()
    print(S.report(sim))
    print('LAND REACHED (day from first visit):', ', '.join(f'{s}x{s}: day {d:.1f}' for s, d in sorted(reached.items())))
    print(f'final land {sim.f["size"]}x{sim.f["size"]}, beds {sum(o["type"] == "plot" for o in sim.f["objects"])}, '
          f'level {C.level(sim.f["xp"])}, coins {sim.f["coins"]}')


if __name__ == '__main__':
    main()
