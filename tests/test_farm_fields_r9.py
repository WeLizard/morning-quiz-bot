"""Farm r9 stage 15 (part A, server): fields, three machines and the three server-replayed minigames."""
import asyncio
import inspect
import json
import math
import os
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest

from qw_farm import api, catalog, economy, fields, market, progression
from qw_farm.catalog import (CROPS, FIELD_FUEL, FIELD_MACHINES, FIELD_SEED_MULT, FIELD_STEPS, FIELD_UPKEEP, HOPPER, LEVELS, Q_AUTO,
                             Q_AUTO_FULL, Q_BASE_FULL, Q_SPAN_FULL, public_catalog, validate, validate_fields)
from qw_farm.domain import FarmError, apply, new_farm, project, validate_state
from qw_farm.expansion import settle, upgrade_state
from qw_farm.service import FarmService, Principal

T0 = 1_800_000_000
DAY = 86400
FIXTURES = Path(__file__).resolve().parent / 'fixtures' / 'farm_fields'
OPS = ('cultivate', 'sow', 'harvest')
ALL_OPS = OPS + ('spray',)
TTL = catalog.FIELD_RUN_TTL


def farm(lv=30, coins=10 ** 8):
    f = upgrade_state(new_farm(str(uuid4()), 'Fld', T0))
    f.update(xp=LEVELS[lv - 1], coins=coins, starter_credit=0)
    return f


n = [0]


def cmd(f, kind, data=None, at=T0):
    n[0] += 1
    return apply(f, f, kind, data if data is not None else {}, at, f'cmd{n[0]:06d}')


def fail(f, kind, data, at=T0, code=None, status=None):
    with pytest.raises(FarmError) as error:
        cmd(f, kind, data, at)
    if code:
        assert error.value.code == code
    if status:
        assert error.value.status == status
    return error.value


def equipped(lv=44, tiers=(1, 1, 1, 1), step=0, coins=10 ** 8):
    f = farm(lv, coins)
    cmd(f, 'buy_field', dict(step=step))
    for name, tier in zip(FIELD_MACHINES, tiers):
        cmd(f, 'buy_machine', dict(machine=name))
        for _ in range(tier - 1):
            cmd(f, 'upgrade_machine', dict(machine=name))
    return f


def fld(f, index=0):
    return f['fields'][index]


def start(f, op, at, crop='', index=0):
    cmd(f, 'field_start', dict(field=fld(f, index)['id'], op=op, crop=crop, revision=fld(f, index)['revision']), at)
    return fld(f, index)['run']


def finish(f, path, at, index=0, run=None):
    return cmd(f, 'field_finish', dict(field=fld(f, index)['id'], run=run or fld(f, index)['run']['id'], path=path), at)


def drive(f, op, at, crop='', index=0):
    """Start, drive the reference route honestly (taking the time it needs) and finish. Returns (finish time, score)."""
    run = start(f, op, at, crop, index)
    path = fields.reference_path(fld(f, index), run)
    score = fields.simulate(fld(f, index), run, path)
    done = at + math.ceil(0.12 * len(path)) + 1
    finish(f, path, done, index)
    return done, score


def square(width, ha=1, rocks=(), weeds=(), op='cultivate'):
    return dict(w=8, h=8 * ha, ha=ha), dict(op=op, width=width, rocks=list(rocks), weeds=list(weeds), id='run_0')


@pytest.fixture
def spy(monkeypatch):
    calls = []
    original = progression.grant_xp

    def grant(farm_, amount, source, at, owner, seconds=None):
        calls.append(dict(amount=amount, source=source, at=at, owner=owner))
        return original(farm_, amount, source, at, owner, seconds)
    monkeypatch.setattr(progression, 'grant_xp', grant)
    return calls


# ---------------------------------------------------------------------------------------------- catalog
def test_catalog_tables_and_public_projection():
    validate()
    # 9 field crops of r9 plus the long (>= FIELD_MIN_GROW) crops that R16 added later; counted, not pinned, so a new long crop keeps the test valid
    r16_field = sum(1 for k in catalog.R16_CROP_IDS if CROPS[k]['seconds'] >= catalog.FIELD_MIN_GROW and not CROPS[k].get('orchard'))
    assert validate_fields() == dict(field_steps=5, field_machines=4, field_crops=9 + r16_field)
    assert [(s['level'], s['ha'], s['cost']) for s in FIELD_STEPS] == [(22, 1, 60000), (27, 1, 120000), (32, 2, 250000), (38, 2, 450000), (44, 3, 800000)]
    assert {k: m['costs'][1:] for k, m in FIELD_MACHINES.items()} == {k: (15000, 45000) for k in FIELD_MACHINES}
    assert {m['op'] for m in FIELD_MACHINES.values()} == set(ALL_OPS)
    assert all(c['field'] == (c['seconds'] >= catalog.FIELD_MIN_GROW and not c.get('orchard')) for c in CROPS.values())
    assert not CROPS['wheat']['field'] and CROPS['saffron']['field']
    pub = public_catalog()['fields']
    assert pub['steps'][0]['cost'] == 60000 and set(pub['machines']) == set(FIELD_MACHINES) and 'saffron' in pub['crops']
    assert pub['hopper'] == HOPPER and pub['max_path'] == 2000 and pub['upkeep'] == 1000


def test_xp_and_yield_are_not_written_outside_the_funnel(spy):
    # the global static check lives in test_farm_progression_r9; here the field XP is observed to go through grant_xp
    f = equipped()
    t = T0
    for op, crop in (('cultivate', ''), ('sow', 'saffron')):
        t, _ = drive(f, op, t, crop)
    settle(f, t + 2 * DAY)
    drive(f, 'harvest', t + 2 * DAY)
    assert [c['source'] for c in spy] == ['field']


# ---------------------------------------------------------------------------------------------- pure mechanics
@pytest.mark.parametrize('op', OPS)
@pytest.mark.parametrize('width', (1, 2, 3))
@pytest.mark.parametrize('ha', (1, 3))
def test_reference_driver_is_perfect_on_a_clear_field_and_good_around_rocks(op, width, ha):
    clear = square(width, ha, op=op)
    assert fields.simulate(*clear, fields.reference_path(*clear)) == 1000
    for k in range(6):
        rocks, weeds = fields.make_obstacles(f'seed{k}', op, 8, 8 * ha, ha)
        field, run = square(width, ha, rocks, weeds, op)
        path = fields.reference_path(field, run)
        assert len(path) <= fields.max_path(field, run)
        assert fields.simulate(field, run, path) >= 320 and fields.quality(fields.simulate(field, run, path)) <= 1100
        assert set(path) <= set('UDLRX')


@pytest.mark.parametrize('op', OPS)
def test_borders_make_the_path_invalid(op):
    for width in (1, 2, 3):
        field, run = square(width, op=op)
        assert fields.simulate(field, run, 'U') is None and fields.simulate(field, run, 'L') is None
        assert fields.simulate(field, run, 'R' * (8 - width)) is not None
        assert fields.simulate(field, run, 'R' * (9 - width)) is None
        assert fields.simulate(field, run, 'D' * 7) is not None and fields.simulate(field, run, 'D' * 8) is None
        assert fields.simulate(field, run, 'RL' * 3 + 'U') is None


@pytest.mark.parametrize('op', OPS)
def test_a_rock_blocks_the_bar_and_the_cells_behind_it_leave_the_denominator(op):
    field, run = square(1, rocks=[8], op=op)                           # rock at (0, 1)
    assert fields.simulate(field, run, 'D') is None
    field, run = square(2, rocks=[9], op=op)                           # rock at (1, 1): any bar over x=0..1 or 1..2 at row 1 is blocked
    assert fields.simulate(field, run, 'D') is None and fields.simulate(field, run, 'RD') is None
    assert fields.simulate(field, run, 'RRD') is not None
    wall = list(range(8, 16))                                          # a full rock row: only row 0 is reachable
    field, run = square(1, rocks=wall, op=op)
    assert fields.reachable_anchors(8, 8, 1, frozenset(wall)) == {(x, 0) for x in range(8)}
    assert fields.simulate(field, run, 'R' * 7) == 1000


def test_cultivation_scores_coverage_overlap_and_weeds():
    field, run = square(1)
    snake = fields.reference_path(field, run)
    assert fields.simulate(field, run, snake) == 1000
    assert fields.simulate(field, run, '') == 0 and fields.simulate(field, run, 'D' * 7) == 0           # one lane = 12.5% coverage
    half = snake[:len(snake) // 2]
    assert 0 <= fields.simulate(field, run, half) < 300
    redo = snake + 'LR' * 20                                                                              # shuffling over covered ground
    assert 0 < fields.simulate(field, run, redo) < 1000
    assert fields.simulate(field, run, snake + 'LR') > fields.simulate(field, run, redo)
    # a weed cell weighs 3: skipping a clear lane hurts less than skipping the lane full of weeds
    field, run = square(1, weeds=[7 + 8 * y for y in range(8)])
    lane = lambda start: ''.join('D' * 7 if i % 2 == 0 else 'U' * 7 for i in range(start))
    skip_clear = 'R' + 'D' * 7 + ''.join('R' + ('U' if i % 2 == 0 else 'D') * 7 for i in range(6))
    skip_weeds = 'D' * 7 + ''.join('R' + ('U' if i % 2 == 0 else 'D') * 7 for i in range(6))
    assert fields.simulate(field, run, skip_clear) > fields.simulate(field, run, skip_weeds)
    # a wider machine finishes a larger clear field in fewer steps
    wide, wrun = square(3)
    assert len(fields.reference_path(wide, wrun)) < len(snake) // 2


def test_sowing_follows_the_row_marking_and_punishes_doubles():
    field, run = square(1, op='sow')
    lanes = ''.join(('D' * 7 if i % 2 == 0 else 'U' * 7) + ('RR' if i < 3 else '') for i in range(4))
    assert fields.simulate(field, run, lanes) == 1000
    off = 'R' + 'D' * 7 + 'R' + 'U' * 7                                                                  # driving between the markings sows nothing
    assert fields.simulate(field, run, off) == 0
    assert fields.simulate(field, run, lanes + 'DDDDDDD') < 1000                                          # lane 4 sown twice
    assert fields.simulate(field, run, lanes[:-2]) < 1000                                                 # incomplete
    skip = 'D' * 7 + 'RRRR' + 'U' * 7 + 'RR' + 'D' * 7                                              # second lane missed
    assert fields.simulate(field, run, skip) < fields.simulate(field, run, lanes)
    wide, wrun = square(3, op='sow')                                                                     # lanes at x = 0 and 4 (columns 3 and 7 stay empty)
    assert fields.simulate(wide, wrun, 'D' * 7 + 'RRRR' + 'U' * 7) == 1000
    assert fields.simulate(wide, wrun, 'D' * 7 + 'RRR' + 'U' * 7) < 600                                  # the second pass is off the marking


def test_harvest_hopper_overflow_is_lost_and_unloading_is_only_at_the_top_edge():
    field, run = square(1, op='harvest')
    lanes = lambda unload: ''.join(('D' * 7 if i % 2 == 0 else 'U' * 7) + ('X' if unload and i % 2 else '') + ('R' if i < 7 else '') for i in range(8))
    assert fields.simulate(field, run, lanes(True)) == 1000
    lost = fields.simulate(field, run, lanes(False))                                                       # cap 18 of 64 cells
    assert lost == 0 and HOPPER * 1 * 1 == 18
    assert fields.simulate(field, run, 'D' + 'X') is None and fields.simulate(field, run, 'X') == fields.simulate(field, run, '')
    assert fields.simulate(field, run, 'DU' + 'X') is not None
    late = ''.join(('D' * 7 if i % 2 == 0 else 'U' * 7) + ('X' if i in (1, 3, 5) else '') + ('R' if i < 7 else '') for i in range(8))
    assert fields.simulate(field, run, late) >= 600                                                        # three lanes in the hopper, one extra pass
    never_full = ''.join(('D' * 7 if i % 2 == 0 else 'U' * 7) + ('X' if i % 2 else '') + ('R' if i < 7 else '') for i in range(8))
    assert fields.simulate(field, run, never_full) == 1000


def test_new_harvest_runs_unload_only_at_the_fixed_truck():
    for width, good, bad in ((1, 4, 6), (2, 4, 6), (3, 4, 5)):
        field, run = square(width, op='harvest')
        run['unload_zone'] = True
        assert fields._near_unload(good, width) and not fields._near_unload(bad, width)
        assert fields.simulate(field, run, 'R' * good + 'X') is not None
        assert fields.simulate(field, run, 'R' * bad + 'X') is None
    field, run = square(1, op='harvest')
    run['unload_zone'] = True
    assert fields.simulate(field, run, 'X') is None
    del run['unload_zone']
    assert fields.simulate(field, run, 'X') is not None


def test_new_runs_remember_the_fixed_unload_zone():
    f = equipped()
    cultivate_run = start(f, 'cultivate', T0)
    assert cultivate_run.get('unload_zone') is False and cultivate_run.get('rules') == 3
    g = equipped()
    fld(g).update(state='ripe', crop=dict(id='saffron', planted_at=T0, ready_at=T0, base=100, xp=1, q_sow=1000,
                                           version=catalog.VERSION))
    assert start(g, 'harvest', T0 + 1).get('unload_zone') is True
    h = equipped()
    fld(h).update(state='ripe', crop=dict(id='saffron', planted_at=T0, ready_at=T0, base=100, xp=1, q_sow=1000,
                                           version=catalog.VERSION))
    spray = start(h, 'spray', T0 + 1)
    assert spray.get('unload_zone') is True and spray.get('tank') == catalog.FIELD_TANK and spray.get('wind') in (-1, 1)


def test_reference_driver_unloads_at_the_fixed_truck():
    for width in (1, 2, 3):
        field, run = square(width, op='harvest')
        run['unload_zone'] = True
        path = fields.reference_path(field, run)
        assert 'X' in path
        for ch, x, y, _ in fields._walk(field['w'], field['h'], run['width'], frozenset(run['rocks']), path, 'X'):
            if ch == 'X':
                assert y == 0 and fields._near_unload(x, width)


def test_obstacles_are_deterministic_sparse_and_never_block_the_start():
    for op in ALL_OPS:
        for ha in (1, 2, 3):
            a = fields.make_obstacles('abc', op, 8, 8 * ha, ha)
            assert a == fields.make_obstacles('abc', op, 8, 8 * ha, ha) and a != fields.make_obstacles('abd', op, 8, 8 * ha, ha)
            rocks, weeds = a
            assert len(rocks) == fields.ROCKS_PER_HA[op] * ha and all(c >= 8 for c in rocks)
            assert len({c // 8 for c in rocks}) == len(rocks) and not set(rocks) & set(weeds)
            assert len(weeds) == (fields.WEEDS_PER_HA * ha if op == 'cultivate' else 0)


def test_fixtures_match_the_current_mechanics():
    cases = build_fixture_cases()
    if os.getenv('FARM_FIELDS_WRITE_FIXTURES'):
        FIXTURES.mkdir(parents=True, exist_ok=True)
        for op, rows in cases.items():
            (FIXTURES / f'{op}.json').write_text(json.dumps(dict(op=op, constants=fixture_constants(), cases=rows), indent=1, sort_keys=True) + '\n', encoding='utf-8')
    for op, rows in cases.items():
        saved = json.loads((FIXTURES / f'{op}.json').read_text(encoding='utf-8'))
        assert saved == json.loads(json.dumps(dict(op=op, constants=fixture_constants(), cases=rows))), f'regenerate with FARM_FIELDS_WRITE_FIXTURES=1 ({op})'
        for case in saved['cases']:
            assert fields.SIMULATE[op](case['field'], dict(case['run'], op=op), case['path']) == case['score'], case['name']
    assert sum(len(rows) for rows in cases.values()) >= 90


def fixture_constants():
    return dict(weed_weight=fields.WEED_WEIGHT, hopper=HOPPER, w=8, q_base=catalog.Q_BASE, q_span=catalog.Q_SPAN, q_auto=Q_AUTO)


def build_fixture_cases():
    out = {}
    for op in OPS:
        rows = []
        for width in (1, 2, 3):
            for ha in (1, 3):
                for rocky in (False, True):
                    rocks, weeds = fields.make_obstacles(f'fixture-{op}-{width}-{ha}', op, 8, 8 * ha, ha) if rocky else ([], [])
                    field, run = square(width, ha, rocks, weeds, op)
                    path = fields.reference_path(field, run)
                    name = f'{op} w{width} {ha}ha {"rocks" if rocky else "clear"}'
                    rows.append(dict(name=name + ' reference', field=dict(w=8, h=8 * ha), run=dict(width=width, rocks=rocks, weeds=weeds),
                                     path=path, score=fields.simulate(field, run, path)))
                    for label, bad in (('half', path[:len(path) // 2]), ('empty', ''), ('wander', path + 'LRLRUDUD'), ('wall', 'U'),
                                       ('edge', 'R' * 9), ('doubled', path + path), ('dive', 'D' * (8 * ha))):
                        rows.append(dict(name=f'{name} {label}', field=dict(w=8, h=8 * ha), run=dict(width=width, rocks=rocks, weeds=weeds),
                                         path=bad, score=fields.simulate(field, run, bad)))
        if op == 'harvest':
            field, run = square(1, op=op)
            for label, bad in (('unload off the edge', 'DX'), ('unload at the edge', 'DUX'), ('no unload', 'DDDDDDDRUUUUUUU')):
                rows.append(dict(name='harvest ' + label, field=dict(w=8, h=8), run=dict(width=1, rocks=[], weeds=[]), path=bad, score=fields.simulate(field, run, bad)))
        out[op] = rows
    return out


# ---------------------------------------------------------------------------------------------- purchases
def test_buy_field_rules():
    f = farm(21)
    fail(f, 'buy_field', dict(step=0), code='locked')
    f = farm(22, coins=59_999)
    fail(f, 'buy_field', dict(step=0), code='insufficient_coins')
    f['coins'] = 60_000
    cmd(f, 'buy_field', dict(step=0))
    assert f['coins'] == 0 and fld(f) == dict(id='field_0', step=0, ha=1, w=8, h=8, state='wild', crop=None, run=None, q_cult=Q_AUTO, seq=0, revision=0)
    fail(f, 'buy_field', dict(step=0), code='already_owned')
    fail(f, 'buy_field', dict(step=9), code='invalid_command', status=422)
    fail(f, 'buy_field', dict(step='0'), code='invalid_command')
    f = farm(44)
    for step, spec in enumerate(FIELD_STEPS):
        cmd(f, 'buy_field', dict(step=step))
    assert [x['ha'] for x in f['fields']] == [1, 1, 2, 2, 3] and [x['h'] for x in f['fields']] == [8, 8, 16, 16, 24]
    validate_state(f)


def test_machines_are_bought_and_upgraded_by_tiers():
    f = farm(22, coins=10 ** 7)
    fail(f, 'upgrade_machine', dict(machine='seeder'), code='not_owned')
    fail(f, 'buy_machine', dict(machine='tractor'), code='unknown_item')
    f['xp'] = LEVELS[20]
    fail(f, 'buy_machine', dict(machine='seeder'), code='locked')
    f['xp'] = LEVELS[21]
    before = f['coins']
    cmd(f, 'buy_machine', dict(machine='seeder'))
    assert f['field_machines']['seeder']['tier'] == 1 and f['coins'] == before - 7500
    fail(f, 'buy_machine', dict(machine='seeder'), code='already_owned')
    fail(f, 'upgrade_machine', dict(machine='seeder'), code='locked')                       # tier 2 needs L27
    f['xp'] = LEVELS[26]
    cmd(f, 'upgrade_machine', dict(machine='seeder'))
    fail(f, 'upgrade_machine', dict(machine='seeder'), code='locked')                       # tier 3 needs L38
    f['xp'] = LEVELS[37]
    f['coins'] = 44_999
    fail(f, 'upgrade_machine', dict(machine='seeder'), code='insufficient_coins')
    f['coins'] = 45_000
    cmd(f, 'upgrade_machine', dict(machine='seeder'))
    assert f['field_machines']['seeder']['tier'] == 3 and f['coins'] == 0
    fail(f, 'upgrade_machine', dict(machine='seeder'), code='max_tier')
    validate_state(f)


def test_run_width_follows_the_machine_tier():
    for tier in (1, 2, 3):
        f = equipped(tiers=(tier, 1, 1))
        assert start(f, 'cultivate', T0)['width'] == tier


# ---------------------------------------------------------------------------------------------- start
def test_start_takes_fuel_and_creates_a_deterministic_run():
    f = equipped(step=2)                                                                                       # a 2 ha field
    assert fld(f)['ha'] == 2
    coins = f['coins']
    run = start(f, 'cultivate', T0)
    assert f['coins'] == coins - FIELD_FUEL * 2 and run['id'] == 'run_0' and run['status'] == 'open'
    assert (run['started_at'], run['expires_at'], run['qrule']) == (T0, T0 + TTL, 2) and TTL == 1800 and fld(f)['seq'] == 1 and fld(f)['revision'] == 1
    twin = deepcopy(f)
    twin['fields'][0].update(run=None, revision=0, seq=0, state='wild')
    again = start(twin, 'cultivate', T0)
    assert again['seed'] == run['seed'] and again['rocks'] == run['rocks'] and again['weeds'] == run['weeds']   # same farm, field, sequence
    other = deepcopy(f)
    other['id'] = str(uuid4())
    other['fields'][0].update(run=None, revision=0, seq=0, state='wild')
    assert start(other, 'cultivate', T0)['seed'] != run['seed']
    assert 0 not in run['rocks'] and all(c >= 8 for c in run['rocks'])
    validate_state(f)


def test_start_pays_seeds_for_the_sowing():
    f = equipped()
    t, _ = drive(f, 'cultivate', T0)
    coins = f['coins']
    run = start(f, 'sow', t + 5, 'saffron')
    assert f['coins'] == coins - FIELD_FUEL - CROPS['saffron']['cost'] * FIELD_SEED_MULT and run['crop'] == 'saffron'
    assert run['sow_reach'] is True
    assert run['sow_reach'] is True and fld(f).get('run', run).get('sow_reach', True)


def test_start_validations():
    f = equipped()
    fid, rev = fld(f)['id'], fld(f)['revision']
    ok = dict(field=fid, op='cultivate', crop='', revision=rev)
    fail(f, 'field_start', {**ok, 'revision': rev + 1}, code='stale_object')
    fail(f, 'field_start', {**ok, 'revision': '0'}, code='stale_object')
    fail(f, 'field_start', {**ok, 'field': 'field_9'}, code='not_found', status=404)
    fail(f, 'field_start', {**ok, 'op': 'plough'}, code='invalid_command', status=422)
    fail(f, 'field_start', {**ok, 'crop': 'saffron'}, code='invalid_command')
    fail(f, 'field_start', {**ok, 'op': 'sow'}, code='wrong_state')                                            # the field is wild
    fail(f, 'field_start', {**ok, 'op': 'harvest'}, code='wrong_state')
    fail(f, 'field_start', dict(field=fid, op='cultivate', revision=rev), code='invalid_command', status=422)   # exact key set
    thin = deepcopy(f)
    thin['coins'] = FIELD_FUEL - 1
    fail(thin, 'field_start', ok, code='insufficient_coins')
    bare = farm(30)
    cmd(bare, 'buy_field', dict(step=0))
    fail(bare, 'field_start', dict(field=fld(bare)['id'], op='cultivate', crop='', revision=0), code='not_owned')
    cmd(f, 'field_start', ok)
    fail(f, 'field_start', {**ok, 'revision': fld(f)['revision']}, code='field_busy')
    drive_ready = equipped()
    t, _ = drive(drive_ready, 'cultivate', T0)
    for crop, code in (('wheat', 'not_field_crop'), ('moonflower', 'unknown_item'), ('', 'unknown_item')):
        fail(drive_ready, 'field_start', dict(field=fld(drive_ready)['id'], op='sow', crop=crop, revision=fld(drive_ready)['revision']), at=t, code=code)
    poor = deepcopy(drive_ready)
    poor['coins'] = FIELD_FUEL + CROPS['saffron']['cost'] * FIELD_SEED_MULT - 1
    fail(poor, 'field_start', dict(field=fld(poor)['id'], op='sow', crop='saffron', revision=fld(poor)['revision']), at=t, code='insufficient_coins')


# ---------------------------------------------------------------------------------------------- finish and anti-cheat
def test_finish_checks_path_time_and_replays_it_server_side():
    f = equipped()
    run = start(f, 'cultivate', T0)
    field = fld(f)
    path = fields.reference_path(field, run)
    n_ = len(path)
    snapshot = deepcopy(f)
    fail(f, 'field_finish', dict(field=field['id'], run=run['id'], path=path), at=T0 + math.ceil(n_ * 0.12) - 1, code='too_fast', status=422)
    assert f == snapshot                                                                                         # nothing changed, the run stays open
    for bad in ('UDLRZ', 'udlr', 'X', 'D ' + 'D', 5, 'R' * 9, 'D' * 8, ['D'], 'U'):
        err = fail(f, 'field_finish', dict(field=field['id'], run=run['id'], path=bad), at=T0 + 400)
        assert err.code == 'bad_path' and err.status == 422
    fail(f, 'field_finish', dict(field=field['id'], run=run['id'], path='D' * (fields.max_path(field, run) + 1)), at=T0 + 899, code='bad_path')
    fail(f, 'field_finish', dict(field=field['id'], run='run_77', path=path), at=T0 + 400, code='run_closed')
    # exactly 0.12 s per character is enough; extra numbers from the client are refused by the exact schema
    fail(f, 'field_finish', dict(field=field['id'], run=run['id'], path=path, score=1000), at=T0 + 400, code='invalid_command')
    exact = T0 + math.ceil(n_ * 12 / 100)
    cmd(f, 'field_finish', dict(field=field['id'], run=run['id'], path=path), exact)
    score = fields.simulate(field | dict(), run, path)
    assert fld(f)['state'] == 'ready' and fld(f)['run'] is None and fld(f)['q_cult'] == fields.quality_full(score)


def test_path_length_ceiling_is_three_times_the_tiles_per_width_and_never_above_2000():
    for width, ha, expect in ((1, 1, 192), (2, 1, 96), (3, 1, 64), (1, 3, 576), (3, 3, 192)):
        field, run = square(width, ha)
        assert fields.max_path(field, run) == expect == min(3 * 64 * ha // width, 2000)
    f = equipped(lv=44, tiers=(3, 1, 1))
    run = start(f, 'cultivate', T0)
    ceiling = fields.max_path(fld(f), run)
    ok = 'D' * 7 + 'U' * 7
    fail(f, 'field_finish', dict(field=fld(f)['id'], run=run['id'], path=ok * (ceiling // 14 + 1)), at=T0 + 899, code='bad_path')


def test_a_run_finishes_once_and_a_closed_run_is_refused():
    f = equipped()
    run = start(f, 'cultivate', T0)
    path = fields.reference_path(fld(f), run)
    finish(f, path, T0 + 60)
    xp, coins, state = f['xp'], f['coins'], deepcopy(f['fields'])
    fail(f, 'field_finish', dict(field=fld(f)['id'], run=run['id'], path=path), at=T0 + 61, code='run_closed')
    fail(f, 'field_finish', dict(field=fld(f)['id'], run=run['id'], path=None), at=T0 + 61, code='run_closed')
    assert (f['xp'], f['coins'], f['fields']) == (xp, coins, state)
    # an autopilot run cannot be finished again by hand either
    t = T0 + 100
    run = start(f, 'sow', t, 'saffron')
    finish(f, None, t + 1)
    fail(f, 'field_finish', dict(field=fld(f)['id'], run=run['id'], path='D'), at=t + 5, code='run_closed')


def test_manual_quality_is_85_to_110_and_the_autopilot_is_95():
    assert [fields.quality(s) for s in (0, 400, 1000)] == [850, 950, 1100]
    assert Q_AUTO == 950 and fields.growth_permille(950) == 1000 and fields.growth_permille(1100) == 850 and fields.growth_permille(850) == 1100
    assert fields.yield_qty(80, 1100, 1100) == 96 and fields.yield_qty(1, 850, 850) == 1


def test_autopilot_is_ready_after_90_seconds_per_hectare_over_the_width():
    for tiers, ha_step, seconds in (((1, 1, 1), 0, 90), ((2, 1, 1), 0, 45), ((3, 1, 1), 0, 30)):
        f = equipped(tiers=tiers)
        run = start(f, 'cultivate', T0)
        finish(f, None, T0 + 10)
        assert run['status'] == 'auto' and run['done_at'] == T0 + 10 + seconds and run['owner'] is True
        settle(f, T0 + 10 + seconds - 1)
        assert fld(f)['state'] == 'wild' and fld(f)['run'] is not None
        settle(f, T0 + 10 + seconds)
        assert fld(f)['state'] == 'ready' and fld(f)['run'] is None and fld(f)['q_cult'] == Q_AUTO_FULL
        validate_state(f)
    big = farm(32)
    cmd(big, 'buy_field', dict(step=2))
    cmd(big, 'buy_machine', dict(machine='cultivator'))
    assert fields.auto_seconds(2, 1) == 180 and fields.auto_seconds(3, 2) == 135 and fields.auto_seconds(1, 3) == 30
    start(big, 'cultivate', T0)
    finish(big, None, T0)
    assert fld(big)['run']['done_at'] == T0 + 180


def test_an_expired_run_is_closed_by_settle_as_the_autopilot_without_owner_bonuses(spy):
    f = equipped()
    start(f, 'cultivate', T0)
    xp = f['xp']
    settle(f, T0 + TTL - 1)
    assert fld(f)['run'] is not None and fld(f)['state'] == 'wild'
    settle(f, T0 + 5 * DAY)                                                                                      # the owner comes back much later
    assert fld(f)['state'] == 'ready' and fld(f)['run'] is None and fld(f)['q_cult'] == Q_AUTO_FULL and fld(f)['last_run_at'] == T0 + TTL
    run = start(f, 'sow', T0 + 5 * DAY, 'saffron')
    settle(f, T0 + 6 * DAY)                                                                                      # closed at its deadline: growth starts then
    assert fld(f)['state'] == 'growing' and fld(f)['crop']['planted_at'] == T0 + 5 * DAY + TTL and fld(f)['crop']['q_sow'] == 900
    assert fld(f)['crop']['ready_at'] == T0 + 5 * DAY + TTL + math.ceil(86400 * (1950 - Q_AUTO_FULL) / 1000)
    settle(f, T0 + 8 * DAY)
    assert fld(f)['state'] == 'ripe'
    start(f, 'harvest', T0 + 8 * DAY)
    settle(f, T0 + 9 * DAY)
    assert fld(f)['state'] == 'wild' and fld(f)['crop'] is None
    assert spy[-1]['owner'] is False and spy[-1]['amount'] == CROPS['saffron']['xp'] * 8 * 1 * 900 * 900 // 10 ** 6
    assert f['xp'] == xp + spy[-1]['amount'] and f['inventory']['saffron'] == fields.yield_qty(5 * 16, 900, 900)
    assert run['status'] == 'open'


def test_a_late_manual_finish_is_impossible_once_settled():
    f = equipped()
    run = start(f, 'cultivate', T0)
    path = fields.reference_path(fld(f), run)
    settle(f, T0 + TTL + 1)
    fail(f, 'field_finish', dict(field=fld(f)['id'], run=run['id'], path=path), at=T0 + TTL + 1, code='run_closed')


def test_full_manual_cycle_formulas(spy):
    f = equipped(tiers=(1, 2, 3))
    t, s_cult = drive(f, 'cultivate', T0)
    q_cult = fields.quality_full(s_cult)
    assert fld(f)['state'] == 'ready' and fld(f)['q_cult'] == q_cult
    coins = f['coins']
    t2, s_sow = drive(f, 'sow', t + 3, 'saffron')
    q_sow = fields.quality_full(s_sow)
    crop = fld(f)['crop']
    assert coins - f['coins'] == FIELD_FUEL + CROPS['saffron']['cost'] * 16
    assert crop['q_sow'] == q_sow and crop['base'] == 5 * 16 and crop['planted_at'] == t2
    assert crop['ready_at'] == t2 + math.ceil(86400 * (1950 - q_cult) / 1000) and fld(f)['state'] == 'growing'
    fail(f, 'field_start', dict(field='field_0', op='harvest', crop='', revision=fld(f)['revision']), at=t2 + 10, code='wrong_state')
    settle(f, crop['ready_at'] - 1)
    assert fld(f)['state'] == 'growing'
    settle(f, crop['ready_at'])
    assert fld(f)['state'] == 'ripe'
    inv = f['inventory'].get('saffron', 0)
    t3, s_harv = drive(f, 'harvest', crop['ready_at'] + 5)
    q_harv = fields.quality_full(s_harv)
    qty = 80 * q_sow * q_harv * 1000 // 10 ** 9
    assert f['inventory']['saffron'] == inv + qty and f['inventory']['saffron'] > 0
    assert spy[-1]['owner'] is True and spy[-1]['at'] == t3 and spy[-1]['amount'] == CROPS['saffron']['xp'] * 8 * q_sow * q_harv * 1000 // 10 ** 9
    assert fld(f)['state'] == 'wild' and fld(f)['crop'] is None and fld(f)['q_cult'] == Q_AUTO
    assert max(q_cult, q_sow, q_harv) <= Q_BASE_FULL + Q_SPAN_FULL and min(q_cult, q_sow, q_harv) >= Q_BASE_FULL
    validate_state(f)


def test_the_best_possible_cycle_yields_about_a_third_more_than_the_autopilot_one():
    q = 1100 * 1100
    assert q * 100 // (950 * 950) in range(133, 135)
    assert fields.yield_qty(80, 1100, 1100) / fields.yield_qty(80, 950, 950) == pytest.approx(1.34, abs=0.02)
    assert 1950 - 1100 == 850                                                                                    # old cultivation: -15% growth time


def test_the_full_test_economy_is_85_to_125_and_the_autopilot_is_90():
    assert [fields.quality_full(s) for s in (0, 400, 1000)] == [850, 1010, 1250]
    assert Q_AUTO_FULL == 900 and fields.growth_permille(900) == 1050 and fields.growth_permille(1250) == 700
    assert fields.yield_qty(80, 1250, 1250) == 125 and fields.yield_qty(80, 900, 900) == 64
    assert fields.yield_qty(80, 1250, 1250, 1200) == 150
    assert fields.spray_bonus_permille(850) == 1000 and fields.spray_bonus_permille(900) == 1025
    assert fields.spray_bonus_permille(1250) == 1200
    assert fields.condition_quality(1250, 90) == 1210 and fields.condition_quality(1250, 0) == 850


def test_manual_ceiling_holds_for_any_valid_path():
    for width in (1, 2, 3):
        for op in OPS:
            field, run = square(width, op=op)
            best = fields.simulate(field, run, fields.reference_path(field, run))
            assert fields.quality(best) == 1100 and fields.quality(best) <= 1100


def test_ripe_field_waits_and_harvest_needs_a_ripe_state():
    f = equipped()
    t, _ = drive(f, 'cultivate', T0)
    t, _ = drive(f, 'sow', t + 3, 'rice')
    fail(f, 'field_start', dict(field=fld(f)['id'], op='harvest', crop='', revision=fld(f)['revision']), at=t + 60, code='wrong_state')
    settle(f, t + 28800 + 1)                                                                                      # rice (8 h) grows 28800 s
    assert fld(f)['state'] == 'ripe'
    assert f['fields'][0]['crop']['ready_at'] >= t + 14400


def test_two_fields_run_independently_and_a_debt_slows_only_owner_growth():
    f = farm(30)
    for s in (0, 1):
        f['xp'] = LEVELS[29 + 10 * s]
        cmd(f, 'buy_field', dict(step=s))
    for m in FIELD_MACHINES:
        cmd(f, 'buy_machine', dict(machine=m))
    start(f, 'cultivate', T0, index=0)
    start(f, 'cultivate', T0, index=1)
    assert f['fields'][0]['run']['seed'] != f['fields'][1]['run']['seed']
    finish(f, None, T0, index=0)
    settle(f, T0 + 90)
    assert f['fields'][0]['state'] == 'ready' and f['fields'][1]['state'] == 'wild' and f['fields'][1]['run'] is not None
    economy.state(f)['debt'] = 10
    f['fields'][0]['q_cult'] = Q_AUTO
    start(f, 'sow', T0 + 100, 'saffron')
    finish(f, None, T0 + 100)
    settle(f, T0 + 190)
    assert f['fields'][0]['crop']['ready_at'] - f['fields'][0]['crop']['planted_at'] == 86400 * 6 // 5                  # owner order under debt: x1.2


# ---------------------------------------------------------------------------------------------- upkeep and old farms
def test_field_upkeep_is_1000_per_hectare_per_day():
    f = farm(44)
    base = economy.base_upkeep(f)
    for step in range(5):
        cmd(f, 'buy_field', dict(step=step))
    assert economy.base_upkeep(f) == base + FIELD_UPKEEP * 9 and FIELD_UPKEEP == 1000
    assert economy.status(f, T0)['base_upkeep'] == base + 9000
    f2 = farm(44, coins=5_000_000)
    cmd(f2, 'buy_field', dict(step=4))
    day = T0 - (T0 + market.TZ_OFFSET) % DAY + DAY
    cmd(f2, 'buy_machine', dict(machine='seeder'), at=day)             # first command of the day: bills (first liable day is free)
    before = f2['coins']
    cmd(f2, 'buy_machine', dict(machine='combine'), at=day + DAY)
    paid = before - f2['coins'] - 12500
    assert paid == economy.upkeep(f2, day + DAY) == economy.base_upkeep(f2) and paid >= 3000


def test_old_farms_without_fields_load_and_are_not_touched():
    f = farm(30)
    old = deepcopy(f)
    assert 'fields' not in f and 'field_machines' not in f and fields.fields_of(f) == [] and fields.machines_of(f) == {}
    settle(f, T0 + 100)
    upgrade_state(f)
    validate_state(f)
    assert 'fields' not in f and f['coins'] == old['coins'] and f['inventory'] == old['inventory']
    mine = project(f, f, T0)
    assert mine['fields'] == [] and mine['field_machines'] == {}
    cmd(f, 'buy_field', dict(step=0))
    assert len(f['fields']) == 1 and project(f, f, T0)['fields'][0]['id'] == 'field_0'


def test_visitors_do_not_see_fields_and_the_owner_sees_the_run():
    a, b = farm(30), farm(30)
    cmd(a, 'buy_field', dict(step=0))
    a['settings']['visibility'] = 'public'
    assert 'fields' not in project(a, b, T0) and 'field_machines' not in project(a, b, T0)
    assert project(a, a, T0)['fields'][0]['state'] == 'wild'


def test_validate_rejects_broken_field_state():
    f = equipped()
    start(f, 'cultivate', T0)
    for key, value in (('state', 'sleeping'), ('ha', 4), ('w', 9)):
        broken = deepcopy(f)
        broken['fields'][0][key] = value
        with pytest.raises(FarmError):
            validate_state(broken)
    broken = deepcopy(f)
    broken['fields'][0]['run']['width'] = 7
    with pytest.raises(FarmError):
        validate_state(broken)
    broken = deepcopy(f)
    broken['field_machines']['tractor'] = dict(tier=1)
    with pytest.raises(FarmError):
        validate_state(broken)
    validate_state(f)


# ---------------------------------------------------------------------------------------------- service, body size
class MemoryUnit:
    def __init__(self, account_id, state):
        self.account_id, self.farms, self.receipts, self.records = account_id, {state['id']: state}, {}, []

    async def lock(self, *keys): pass
    async def by_account(self, account_id): return next(iter(self.farms.values()))
    async def get(self, farm_id): return self.farms.get(farm_id)
    async def owner_account(self, farm_id): return self.account_id
    async def save(self, farm, account_id=None): self.farms[farm['id']] = farm
    async def receipt(self, account_id, key): return self.receipts.get((account_id, key))
    async def remember(self, account_id, key, fingerprint, result, now):
        self.receipts[(account_id, key)] = dict(fingerprint=fingerprint, result=result)
    async def record(self, actor, key, kind, before, after, now): self.records.append((key, kind))


def test_field_commands_through_the_service_are_idempotent_and_settle_expired_runs():
    async def run():
        state = equipped()
        unit = MemoryUnit('acc', state)
        clock = [T0]
        service = FarmService(unit, Principal('acc', 'Игрок'), clock=lambda: clock[0])
        live = lambda: unit.farms[state['id']]
        start_data = dict(field='field_0', op='cultivate', crop='', revision=live()['fields'][0]['revision'])
        first = await service.command('start-0000-0001', 'field_start', start_data)
        coins = live()['coins']
        assert await service.command('start-0000-0001', 'field_start', start_data) == first and live()['coins'] == coins
        with pytest.raises(FarmError) as error:
            await service.command('start-0000-0002', 'field_start', start_data)
        assert error.value.code in {'stale_object', 'field_busy'}
        clock[0] = T0 + 2000                                                          # the deadline passed while the owner was away
        state_view = await service.view()
        assert state_view['farm']['fields'][0]['state'] == 'ready' and state_view['farm']['fields'][0]['run'] is None
        assert unit.records                                                         # the automatic completion is a recorded change
        data = dict(field='field_0', run='run_0', path=None)
        with pytest.raises(FarmError) as closed:
            await service.command('finish-000-0001', 'field_finish', data)
        assert closed.value.code == 'run_closed'
    asyncio.run(run())


def test_the_longest_finish_body_fits_the_request_limit():
    limit = inspect.signature(api.body).parameters['maximum'].default
    body = json.dumps(dict(command_id='finish-' + 'a' * 40, kind='field_finish', target=None, actor=str(uuid4()),
                           data=dict(field='field_4', run='run_999999', path='D' * fields.FIELD_MAX_PATH)))
    assert len(body.encode()) < limit // 2 and fields.FIELD_MAX_PATH == 2000


# ---------------------------------------------------------------------------------------------- time-dependent quality (owner, 2026-10-14)
TIMED = Path(__file__).resolve().parent / 'fixtures' / 'farm_fields_timed' / 'timed.json'


def timed_cases():
    rows = []
    for ha in (1, 2, 3):
        for width in (1, 2, 3):
            a = fields.auto_seconds(ha, width)
            full, zero = a * catalog.FIELD_FULL_K // 100, a * catalog.FIELD_ZERO_K // 100
            for elapsed in sorted({0, 1, full - 1, full, full + 1, (full + zero) // 2, zero - 1, zero, zero + 1, 3600}):
                for score in (0, 399, 400, 401, 500, 800, 950, 1000):
                    rows.append(dict(ha=ha, width=width, elapsed=elapsed, score=score, q=fields.timed_quality(score, elapsed, ha, width)))
    return rows


def test_timed_quality_fixture_matches_the_formula():
    data = dict(constants=dict(q_base=catalog.Q_BASE, q_span=catalog.Q_SPAN, q_auto=Q_AUTO, auto_s=catalog.FIELD_AUTO_S,
                               run_full_k=catalog.FIELD_FULL_K, run_zero_k=catalog.FIELD_ZERO_K), cases=timed_cases())
    if os.getenv('FARM_FIELDS_WRITE_FIXTURES'):
        TIMED.parent.mkdir(parents=True, exist_ok=True)
        TIMED.write_text(json.dumps(data, indent=1, sort_keys=True) + '\n', encoding='utf-8')
    assert json.loads(TIMED.read_text(encoding='utf-8')) == json.loads(json.dumps(data)), 'regenerate with FARM_FIELDS_WRITE_FIXTURES=1'


def test_timed_quality_key_points():
    # 1 ha, width 1: A = 90 s, whole bonus up to 225 s, nothing from 540 s
    assert [fields.timed_quality(1000, t, 1, 1) for t in (0, 60, 225, 226, 380, 539, 540, 9999)] == [1100, 1100, 1100, 1099, 1026, 950, 950, 950]
    assert [fields.timed_quality(800, t, 1, 1) for t in (225, 380, 540)] == [1050, 1000, 950]
    assert fields.timed_quality(400, 9999, 1, 1) == 950 and fields.timed_quality(401, 540, 1, 1) == 950
    assert fields.timed_quality(0, 0, 1, 1) == fields.timed_quality(0, 9999, 1, 1) == 850            # clumsy driving keeps its quality, time does not worsen it
    # 1 ha, width 3: A = 30 s, whole bonus up to 75 s, nothing from 180 s
    assert [fields.timed_quality(1000, t, 1, 3) for t in (75, 76, 180)] == [1100, 1098, 950]


def test_the_slowest_bonus_fits_into_a_run():
    assert max(fields.auto_seconds(s['ha'], 1) for s in FIELD_STEPS) * catalog.FIELD_ZERO_K // 100 <= TTL


@pytest.mark.parametrize('layout, score, qualities', (
    (0, 1000, (1100, 1100, 1025, 950)),
    (89, 997, (1099, 1099, 1024, 950)),
))
def test_manual_finish_uses_the_time_of_the_run(layout, score, qualities):
    # The reference driver can revisit cells around rocks: its score is not always perfect.
    # Pin both layouts so random farm IDs cannot turn this timing check into a flaky score check.
    for wait, expect in zip((60, 225, 382, 540), qualities):
        f = equipped()
        f['id'] = f'fields-time-regression-{layout}'
        run = start(f, 'cultivate', T0)
        run['rules'] = None                                                                       # the old economy of runs opened before rules=3
        field = fld(f)
        path = fields.reference_path(field, run)
        assert fields.simulate(field, run, path) == score
        finish(f, path, T0 + wait)
        assert fld(f)['q_cult'] == expect == fields.timed_quality(score, wait, 1, 1)


def test_a_run_opened_before_the_rule_keeps_the_plain_quality_and_its_old_deadline():
    f = equipped()
    run = start(f, 'cultivate', T0)
    run['rules'] = None
    del run['qrule']
    run['expires_at'] = T0 + 900                                                              # how such a run was stored
    path = fields.reference_path(fld(f), run)
    expected = fields.quality(fields.simulate(fld(f), run, path))         # the plain quality of this exact route (the layout depends on the random farm id)
    finish(f, path, T0 + 800)                                                                   # far beyond the 225 s of a timed run
    assert fld(f)['q_cult'] == expected and expected > Q_AUTO
    g = equipped()
    old = start(g, 'cultivate', T0)
    old['rules'] = None
    del old['qrule']
    old['expires_at'] = T0 + 900
    settle(g, T0 + 900)
    assert fld(g)['state'] == 'ready' and fld(g)['q_cult'] == Q_AUTO and fld(g)['last_run_at'] == T0 + 900
    validate_state(g)


def test_the_full_economy_time_bonus_melts_from_the_900_autopilot():
    # 1 ha, width 1: A = 90 s, whole bonus up to 225 s, nothing from 540 s; 1250 - 900 = +350
    assert [fields.timed_quality_full(1000, t, 1, 1) for t in (0, 225, 226, 382, 540, 9999)] == [1250, 1250, 1248, 1075, 900, 900]
    assert fields.timed_quality_full(0, 0, 1, 1) == fields.timed_quality_full(0, 9999, 1, 1) == 850



def test_rules2_turn_and_per_cell_sow():
    field = dict(w=8, h=8)
    old = dict(op='sow', width=2, rocks=[], weeds=[])
    new = dict(old, rules=2)
    path = 'D' * 7 + 'R' * 2 + 'U' * 7 + 'R' * 3 + 'D' * 7
    assert fields.simulate(field, new, path) > fields.simulate(field, old, path)
    assert fields.simulate(field, old, 'T') is None
    assert fields.simulate(field, new, 'T') is not None
    assert fields.simulate(field, new, 'TDRR') is not None
    assert fields._oriented_bar(4, 0, 8, 2, 'v') == [4, 12]
    assert fields._near_unload(4, 2, 'v') and fields._near_unload(5, 2, 'v') and not fields._near_unload(3, 2, 'v')
    harvest = dict(op='harvest', width=2, rocks=[], weeds=[], rules=2, unload_zone=True)
    assert fields.simulate(field, harvest, 'TRRRRX') is not None
    assert fields.simulate(field, dict(harvest, rules=None), 'TRRRRX') is None


def test_rules2_reference_paths_remain_valid_on_a_clear_field():
    for op in OPS:
        for width in (1, 2, 3):
            field, run = square(width, op=op)
            run['rules'] = 2
            path = fields.reference_path(field, run)
            score = fields.simulate(field, run, path)
            assert score is not None
            if op != 'sow':
                assert score == 1000, (op, width)


def test_rules2_turn_fixture_is_current():
    data = json.loads((Path(__file__).resolve().parent / 'fixtures' / 'farm_fields_turn' / 'turn.json').read_text(encoding='utf-8'))
    assert len(data['cases']) >= 8
    for case in data['cases']:
        assert fields.simulate(case['field'], case['run'], case['path']) == case['score'], case['name']


# ---------------------------------------------------------------------------------------------- rules=3: full test economy
def test_rules3_workable_cells_include_the_vertical_pockets():
    for width in (1, 2, 3):
        rocks, _ = fields.make_obstacles(f'rules3-{width}', 'cultivate', 8, 8, 1)
        horizontal = fields._rules2_cells(8, 8, width, frozenset(rocks))
        both = fields._rules3_cells(8, 8, width, frozenset(rocks))
        assert horizontal <= both and both <= {y * 8 + x for y in range(8) for x in range(8)}


def test_rules3_bumps_damage_the_machine_and_are_validated():
    field, run = square(1)
    run['rules'] = 3
    clean = fields.simulate_full(field, run, '')
    assert clean == dict(score=0, condition=100, hits=0, repair=0)
    bumped = fields.simulate_full(field, run, 'u')
    assert bumped == dict(score=0, condition=97, hits=1, repair=15)
    assert fields.simulate_full(field, run, 'd') is None                     # a bump where the machine can move is a lie
    assert fields.simulate_full(field, run, 'u' * 34)['condition'] == 0
    assert fields.simulate_full(field, run, 'u' * 35) is None
    assert fields.simulate(field, run, 'u') == 0


def test_rules3_harvest_partial_unload_and_spray_refill():
    field, run = square(1, op='harvest')
    run.update(rules=3, unload_zone=False)
    path = 'D' * 7 + 'U' * 7
    full = fields.simulate_full(field, run, path)
    assert full['load'] == 8 and full['condition'] == 100
    assert fields.simulate_full(field, run, path + 'X')['load'] == 3        # one X = a quarter of the 18-cell hopper (ceil 5)
    assert fields.simulate_full(field, run, path + 'X' * 4)['load'] == 0
    zoned = dict(run, unload_zone=True)
    assert fields.simulate_full(field, zoned, path + 'X') is None            # the truck is not here
    spray = dict(op='spray', width=1, rocks=[], weeds=[], rules=3, tank=catalog.FIELD_TANK, wind=1, unload_zone=False)
    assert fields.simulate_spray_v3(field, spray, '')['load'] == catalog.FIELD_TANK - 3
    assert fields.simulate_spray_v3(field, spray, 'D')['load'] == catalog.FIELD_TANK - 6
    refilled = fields.simulate_spray_v3(field, spray, 'DUX')
    assert refilled['load'] == catalog.FIELD_TANK and refilled['condition'] == 100
    calm = dict(spray, wind=0)
    assert fields.simulate_spray_v3(field, calm, '')['load'] == catalog.FIELD_TANK - 2


def test_rules3_full_economy_and_damage_on_the_server():
    f = equipped(tiers=(1, 1, 1, 1))
    run = start(f, 'cultivate', T0)
    field = fld(f)
    path = 'u' + fields.reference_path(field, run)
    result = fields.simulate_full(field, run, path)
    coins = f['coins']
    finish(f, path, T0 + 60)
    expected = fields.condition_quality(fields.quality_full(result['score']), 97)
    assert fld(f)['q_cult'] == expected == fields.quality_full(result['score']) - 12
    assert fld(f)['last_hits'] == 1 and fld(f)['last_repair'] == fields.FIELD_HIT_REPAIR and fld(f)['last_condition'] == 97
    assert coins - f['coins'] == fields.FIELD_HIT_REPAIR
    assert fld(f)['state'] == 'ready'
    validate_state(f)


def test_rules3_a_broken_machine_finishes_as_the_autopilot():
    f = equipped()
    start(f, 'cultivate', T0)
    finish(f, 'u' * 34, T0 + 60)
    assert fld(f)['q_cult'] == Q_AUTO_FULL and fld(f)['last_condition'] == 0
    assert fld(f)['last_hits'] == 34 and fld(f)['last_repair'] == 34 * fields.FIELD_HIT_REPAIR
    assert fld(f)['state'] == 'ready'


def test_rules2_and_old_runs_keep_their_turn_and_old_economy_after_the_rules3_upgrade():
    f = equipped(tiers=(2, 2, 2, 2))
    run = start(f, 'cultivate', T0)
    run['rules'] = 2
    run['rocks'], run['weeds'] = [], []   # obstacles depend on the random farm id: a rock at (0, 1) would block the turn
    finish(f, 'T', T0 + 60)
    assert fld(f)['q_cult'] == fields.timed_quality(0, 60, 1, 2)
    g = equipped(tiers=(2, 2, 2, 2))
    old = start(g, 'cultivate', T0)
    old['rules'] = None
    fail(g, 'field_finish', dict(field=fld(g)['id'], run=old['id'], path='T'), at=T0 + 60, code='bad_path')


def test_rules3_spray_completes_the_crop_and_boosts_the_harvest_yield():
    f = equipped()
    fld(f).update(state='ripe', crop=dict(id='saffron', planted_at=T0, ready_at=T0, base=80, xp=1, q_sow=1250,
                                          version=catalog.VERSION))
    run = start(f, 'spray', T0 + 1)
    assert run['op'] == 'spray' and run['wind'] in (-1, 1)
    fld(f)['run']['rocks'] = []      # the straight path 'D' must not hit rocks drawn from the random farm id
    score = fields.simulate(fld(f), fld(f)['run'], 'D')
    finish(f, 'D', T0 + 60)
    assert fld(f)['state'] == 'ripe' and fld(f)['crop']['q_spray'] == fields.quality_full(score)
    assert fld(f)['crop']['q_sow'] == 1250
    fail(f, 'field_start', dict(field=fld(f)['id'], op='spray', crop='', revision=fld(f)['revision']),
         at=T0 + 61, code='already_sprayed')
    fld(f)['crop']['q_spray'] = 1250
    start(f, 'harvest', T0 + 62)
    finish(f, None, T0 + 63)
    settle(f, T0 + 63 + fields.auto_seconds(1, 1))
    qty = 80 * 1250 * Q_AUTO_FULL * fields.spray_bonus_permille(1250) // 10 ** 9
    assert f['inventory']['saffron'] == qty and qty == 108


def test_sow_reach_counts_a_lane_cell_beside_a_rock():
    rocks = frozenset([3 * 8 + 1])                                   # rock at (1, 3): its lane partner (0, 3) has no horizontal anchor
    assert 3 * 8 not in fields._rules2_sowable(8, 8, 2, rocks)
    assert fields._rules3_sowable(8, 8, 2, rocks) == fields._rules2_sowable(8, 8, 2, rocks) | {3 * 8}
    assert fields._rules3_sowable(8, 8, 2, frozenset()) == fields._rules2_sowable(8, 8, 2, frozenset())   # no rocks: nothing changes


# ---------------------------------------------------------------------------------------------- rules=3 fixture (server <-> JS)
RULES3 = Path(__file__).resolve().parent / 'fixtures' / 'farm_fields_rules3' / 'full.json'


def rules3_case(field, run, path, name):
    run = dict(run, rules=3)
    return dict(name=name, field=dict(w=field['w'], h=field['h']), run=run, path=path,
                result=fields.simulate_full(field, run, path))


def build_rules3_cases():
    rows = []
    for op in ('cultivate', 'sow'):
        for width in (1, 2, 3):
            field = dict(w=8, h=8)
            run = dict(op=op, width=width, rocks=[], weeds=[])
            paths = [('', ''), ('down', 'D' * 7), ('turn', 'T'), ('turn-down', 'T' + 'D' * 3),
                     ('bump', 'u'), ('bump3', 'u' * 3), ('bump34', 'u' * 34), ('lie', 'd'),
                     ('bump-down', 'u' + 'D' * 7 + 'U' * 7)]
            for label, path in paths:
                rows.append(rules3_case(field, run, path, f'{op} w{width} {label}'))
            rocks, weeds = fields.make_obstacles(f'r3-{op}-{width}', op, 8, 8, 1)
            rocky = dict(run, rocks=rocks, weeds=weeds)
            rows.append(rules3_case(field, rocky, fields.reference_path(field, rocky), f'{op} w{width} rocks reference'))
    for width in (2, 3):                                    # sow_reach: the turned seeder sows a lane cell beside a rock
        field = dict(w=8, h=8)
        for reach in (False, True):
            run = dict(op='sow', width=width, rocks=[3 * 8 + 1], weeds=[], sow_reach=reach)
            for label, path in (('lane', 'D' * 7), ('turn-down', 'T' + 'D' * (8 - width)), ('turn-down-up', 'T' + 'D' * (8 - width) + 'U' * (8 - width))):
                rows.append(rules3_case(field, run, path, f'sow w{width} reach{int(reach)} {label}'))
            rocks, weeds = fields.make_obstacles(f'r3-sow-reach-{width}', 'sow', 8, 8, 1)
            rocky = dict(run, rocks=rocks, weeds=weeds)
            rows.append(rules3_case(field, rocky, fields.reference_path(field, rocky), f'sow w{width} reach{int(reach)} rocks reference'))
    for width in (1, 2, 3):
        field = dict(w=8, h=8)
        for zoned in (False, True):
            run = dict(op='harvest', width=width, rocks=[], weeds=[], unload_zone=zoned)
            base = 'D' * 7 + 'U' * 7
            for label, path in (('none', ''), ('bump', 'u'), ('top', base), ('one-x', base + 'X'),
                                ('four-x', base + 'X' * 4), ('zone-x', 'R' * 4 + 'X'), ('turn', 'T' + 'D' * 3)):
                rows.append(rules3_case(field, run, path, f'harvest w{width} z{int(zoned)} {label}'))
        rocks, weeds = fields.make_obstacles(f'r3-harvest-{width}', 'harvest', 8, 8, 1)
        rocky = dict(op='harvest', width=width, rocks=rocks, weeds=weeds, unload_zone=False)
        rows.append(rules3_case(field, rocky, fields.reference_path(field, rocky), f'harvest w{width} rocks reference'))
    for width in (1, 2, 3):
        field = dict(w=8, h=8)
        for wind in (-1, 0, 1):
            for zoned in (False, True):
                run = dict(op='spray', width=width, rocks=[], weeds=[], unload_zone=zoned, tank=catalog.FIELD_TANK, wind=wind)
                base = 'D' * 7 + 'U' * 7
                for label, path in (('none', ''), ('bump', 'u'), ('down', 'D'), ('top', base),
                                    ('refill', base + 'X'), ('turn', 'T' + 'D' * 3), ('run', 'D' * 7 + 'U' * 7 + 'R' * 2 + 'D' * 7 + 'U' * 7 + 'X')):
                    rows.append(rules3_case(field, run, path, f'spray w{width} wind{wind} z{int(zoned)} {label}'))
        rocks, weeds = fields.make_obstacles(f'r3-spray-{width}', 'spray', 8, 8, 1)
        rocky = dict(op='spray', width=width, rocks=rocks, weeds=weeds, unload_zone=False, tank=catalog.FIELD_TANK, wind=1)
        rows.append(rules3_case(field, rocky, fields.reference_path(field, rocky), f'spray w{width} rocks reference'))
    return rows


def test_rules3_fixture_matches_the_mechanics():
    data = dict(constants=dict(hopper=HOPPER, tank=catalog.FIELD_TANK, tank_chunks=catalog.FIELD_TANK_CHUNKS,
                               hit_damage=catalog.FIELD_HIT_DAMAGE, hit_repair=catalog.FIELD_HIT_REPAIR,
                               cond_penalty=catalog.FIELD_COND_PENALTY),
                cases=build_rules3_cases())
    if os.getenv('FARM_FIELDS_WRITE_FIXTURES'):
        RULES3.parent.mkdir(parents=True, exist_ok=True)
        RULES3.write_text(json.dumps(data, indent=1, sort_keys=True, ensure_ascii=False) + '\n', encoding='utf-8')
    saved = json.loads(RULES3.read_text(encoding='utf-8'))
    assert saved == json.loads(json.dumps(data, sort_keys=True)), 'regenerate with FARM_FIELDS_WRITE_FIXTURES=1'
    assert len(saved['cases']) >= 60
    for case in saved['cases']:
        assert fields.simulate_full(case['field'], case['run'], case['path']) == case['result'], case['name']


def test_rules3_finish_accepts_partial_unload_and_refill_events():
    f = equipped()
    fld(f).update(state='ripe', crop=dict(id='saffron', planted_at=T0, ready_at=T0, base=80, xp=1, q_sow=1000,
                                          version=catalog.VERSION))
    start(f, 'harvest', T0 + 1)
    finish(f, 'R' * 4 + 'X', T0 + 60)
    assert fld(f)['state'] == 'wild' and fld(f)['crop'] is None
    g = equipped()
    fld(g).update(state='ripe', crop=dict(id='saffron', planted_at=T0, ready_at=T0, base=80, xp=1, q_sow=1000,
                                          version=catalog.VERSION))
    start(g, 'spray', T0 + 1)
    finish(g, 'R' * 4 + 'X', T0 + 60)
    assert fld(g)['state'] == 'ripe' and fld(g)['crop']['q_spray'] is not None


def test_the_sprayer_tank_scales_with_the_field_size():
    f = equipped()
    cmd(f, 'buy_field', dict(step=4))
    big = fld(f, 1)
    big.update(state='ripe', crop=dict(id='saffron', planted_at=T0, ready_at=T0, base=80, xp=1, q_sow=1000,
                                       version=catalog.VERSION))
    run = start(f, 'spray', T0 + 1, index=1)
    assert run['tank'] == catalog.FIELD_TANK * 3
