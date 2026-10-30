"""Regenerates parity.json: the catalog slice the client reads plus the server answers (qw_farm.undo) for a sweep of buildings.
Run: .venv-local/Scripts/python.exe tests/fixtures/farm_refund/make_parity.py   (from the repository root)."""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from qw_farm import catalog, undo  # noqa: E402
from qw_farm.catalog import BUILDINGS, CROPS, FIELD_FUEL, FIELD_SEED_MULT  # noqa: E402

full = dict(catalog.public_catalog(), undo=undo.public_rules())
keep = {
    'undo': full['undo'],
    'upgrades': {k: full['upgrades'][k] for k in ('max', 'levels', 'base_cost')},
    'items': {k: {'name': v['name']} for k, v in full['items'].items()},
    'buildings': {k: {'cost': v['cost'], 'decor': v.get('decor', False), 'name': v['name']} for k, v in full['buildings'].items()},
    'fields': {'fuel': full['fields']['fuel'], 'seed_mult': full['fields']['seed_mult']},
    'crops': {k: {'cost': v['cost'], 'name': v['name']} for k, v in full['crops'].items() if k in CROPS},
}
T = 1_000_000
cases = []


def add(name, obj, now):
    refund, goods, whole = undo.demolish_refund(obj, now)
    wood = 0
    spec = BUILDINGS.get(obj['type'])
    if not whole and spec and not spec.get('decor'):
        wood = 4 + catalog.effective_level(obj.get('level')) - 1
    xp = obj['build_xp'] if type(obj.get('build_xp')) is int and obj['build_xp'] > 0 else 0     # every demolition takes it back
    cases.append(dict(name=name, obj=obj, now=now, expect=dict(refund=refund, goods=goods, full=whole, wood=wood, xp=xp)))


for bid, b in BUILDINGS.items():
    for lvl in (1, 2, 3):
        add(f'{bid} L{lvl} old save (no price record), late', dict(type=bid, level=lvl), T)
        add(f'{bid} L{lvl} paid, late', dict(type=bid, level=lvl, paid=b['cost'], built_at=T - 3600), T)
    add(f'{bid} first minute', dict(type=bid, paid=b['cost'], built_at=T - 59, build_xp=5), T)
    add(f'{bid} exactly 60 s', dict(type=bid, paid=b['cost'], built_at=T - 60, build_xp=5), T)
    add(f'{bid} 61 s', dict(type=bid, paid=b['cost'], built_at=T - 61, build_xp=5), T)
for sid, typ in (('building_2', 'mill'), ('building_3', 'coop'), ('plot_4', 'plot')):
    for lvl in (1, 3):
        add(f'starter {sid} L{lvl}', dict(id=sid, type=typ, level=lvl), T)
        add(f'bought object with the id {sid} L{lvl}', dict(id=sid, type=typ, level=lvl, paid=100, built_at=T - 3600), T)
add('plot paid, first minute', dict(type='plot', paid=35, built_at=T - 5, build_xp=5), T)
add('road paid, late', dict(type='road', paid=5, built_at=T - 500, build_xp=5), T)
add('barn L3 (no purchase row)', dict(type='barn', level=3), T)
add('barn L2', dict(type='barn', level=2), T)
add('plot without record', dict(type='plot'), T)
add('house without record', dict(type='house'), T)
add('free gift building (paid 0)', dict(type='creamery', paid=0, built_at=T - 10), T)
add('unknown type', dict(type='nonexistent', level=3), T)
# the sowing refund: seeds + fuel, from the record or from the catalog
sow = []
for crop_id in list(CROPS)[:6]:
    for ha in (1, 2, 3):
        cost = CROPS[crop_id]['cost'] * FIELD_SEED_MULT * ha
        sow.append(dict(crop=crop_id, ha=ha, recorded=None, expect=cost + FIELD_FUEL * ha))
        sow.append(dict(crop=crop_id, ha=ha, recorded=dict(cost=cost - 7, fuel=FIELD_FUEL * ha - 3), expect=cost - 7 + FIELD_FUEL * ha - 3))
out = dict(catalog=keep, cases=cases, sowing=sow)
(ROOT / 'tests/fixtures/farm_refund/parity.json').write_text(json.dumps(out, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
print(len(cases), 'cases', len(sow), 'sowing cases')
