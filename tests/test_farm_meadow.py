from copy import deepcopy
from datetime import datetime, timezone, timedelta

import pytest

from qw_farm import domain, meadow
from qw_farm.expansion import can_feed, start_feed, upgrade_state, _work_once, ordered_objects, settle as settle_workers
from qw_farm.catalog import ITEMS, RECIPES
from qw_farm.service import FarmService, Principal

MOSCOW = timezone(timedelta(hours=3))


def at(month, day=15, hour=12):
    return int(datetime(2026, month, day, hour, tzinfo=MOSCOW).timestamp())


def moscow_timestamp(year, month, day=1):
    local = datetime(year, month, day)
    return int((local - datetime(1970, 1, 1)).total_seconds()) - 3 * 3600


def farm(now=at(6)):
    result = domain.new_farm('meadow-test', 'Farm', now)
    upgrade_state(result, now)
    meadow.update(result, now)
    return result


def test_catalog_item_recipe_and_grass_is_not_reachable():
    assert ITEMS['grass']['name'] == 'Луговая трава'
    assert ITEMS['grass']['price'] == 1
    assert RECIPES['meadow_hay']['inputs'] == {'grass': 4}
    assert 'grass' not in domain.reachable(farm())


def test_migration_seeds_two_stage_one_patches_and_accepts_legacy_inventory():
    state = farm()
    state.pop('meadow')
    state['created_at'] = at(1)
    state['inventory']['grass'] = 3
    upgrade_state(state, at(6))
    meadow.update(state, at(6))
    assert len(state['meadow']['patches']) == 2
    assert all(meadow.stage(cut, at(6)) == 1 for cut in state['meadow']['patches'].values())
    domain.validate_state(state)


def test_new_farm_starts_empty_but_old_farm_gets_stage_one_in_autumn_and_winter():
    for now in (at(10), at(1)):
        state = domain.new_farm(f'legacy-{now}', 'Farm', at(1) - 120 * 86400)
        state.pop('meadow')
        upgrade_state(state, now)
        meadow.update(state, now)
        assert len(state['meadow']['patches']) == 2
        assert all(meadow.stage(cut, now) == 1 for cut in state['meadow']['patches'].values())
    now = at(6)
    state = farm(now)
    assert state['meadow']['patches'] == {}


@pytest.mark.parametrize('now', [at(3, 1, 0), at(12, 1, 0)])
def test_migration_seed_age_is_stage_one_across_season_boundaries(now):
    state = domain.new_farm(f'legacy-boundary-{now}', 'Farm', now - 180 * 86400)
    state.pop('meadow')
    meadow.update(state, now)
    assert len(state['meadow']['patches']) == 2
    assert all(meadow.stage(cut, now) == 1 for cut in state['meadow']['patches'].values())


@pytest.mark.parametrize('now', [at(6), at(10), at(1), at(3, 1, 0)])
def test_new_land_seeds_two_stage_one_patches_across_seasons(now):
    state = domain.new_farm(f'expanded-{now}', 'Farm', now)
    previous_size = state['size']
    state['size'] = previous_size + 4

    meadow.seed_new_land(state, previous_size, now)

    patches = state['meadow']['patches']
    assert len(patches) == 2
    assert all(meadow.stage(cut, now) == 1 for cut in patches.values())
    assert all(int(cell.split(',')[0]) >= previous_size or
               int(cell.split(',')[1]) >= previous_size for cell in patches)


def test_eligible_cells_skip_objects_and_cardinal_neighbors_of_plots_and_buildings():
    state = farm()
    cells = set(meadow.eligible_cells(state))
    assert (3, 4) not in cells  # bed
    assert (2, 4) not in cells  # adjacent to bed
    assert (2, 2) in cells      # diagonal to house, not a door path


def test_eligibility_excludes_door_neighbors_but_not_other_building_sides_or_decor():
    state = farm()
    state['objects'] = [
        {'id':'h','type':'house','x':3,'y':3,'w':2,'h':2},
        {'id':'road','type':'road','x':5,'y':7,'w':1,'h':1},
        {'id':'bench','type':'bench','x':6,'y':6,'w':1,'h':1},
    ]
    cells = set(meadow.eligible_cells(state))
    # House door is on the right edge; neighbors of other walls remain usable.
    assert (5, 4) not in cells and (5, 3) in cells and (2, 3) in cells
    # Road/decor footprints are occupied, but do not reserve neighboring cells.
    assert (4, 7) in cells and (6, 7) in cells and (6, 5) in cells


@pytest.mark.parametrize(('typ', 'side', 'fraction'), [
    ('barn', 'bottom', .5), ('mill', 'bottom', .75),
    ('rabbit_hutch', 'bottom', .5), ('dairy', 'right', .5),
    ('spinnery', 'right', .2), ('weavery', 'right', .35),
    ('coop', 'bottom', .5), ('cowshed', 'bottom', .5),
    ('cannery', 'bottom', .8), ('sausage_shop', 'bottom', .8),
    ('smokehouse', 'bottom', .5), ('cattle_barn', 'bottom', .5),
    ('syrupery', 'bottom', .2), ('soapery', 'bottom', .2),
    ('noodle_shop', 'bottom', .2),
    ('ostrich_farm', 'bottom', .5), ('silk_house', 'bottom', .5),
    ('yak_pen', 'bottom', .5), ('pheasantry', 'bottom', .5),
])
def test_scene_door_families_block_only_the_door_neighbor(typ, side, fraction):
    state = farm()
    x0, y0, w, h = 2, 2, 2, 2
    state['objects'] = [dict(id='door-building', type=typ, x=x0, y=y0, w=w, h=h)]
    cells = set(meadow.eligible_cells(state))
    if side == 'right':
        anchor = (x0 + w - 1, y0 + int(h * fraction))
        blocked = (anchor[0] + 1, anchor[1])
        open_cell = (anchor[0] + 1, anchor[1] - 1)
    else:
        anchor = (x0 + int(w * fraction), y0 + h - 1)
        blocked = (anchor[0], anchor[1] + 1)
        open_cell = (anchor[0] + 1, anchor[1] + 1)
    assert blocked not in cells
    assert open_cell in cells


@pytest.mark.parametrize('typ', ['spinnery', 'weavery'])
def test_upper_right_door_keeps_lower_right_neighbor_open(typ):
    state = farm()
    state['objects'] = [dict(id='door-building', type=typ, x=2, y=2, w=2, h=2)]
    cells = set(meadow.eligible_cells(state))
    assert (4, 2) not in cells
    assert (4, 3) in cells


def test_spawn_rolls_are_deterministic_and_bounded_to_eight_epochs_and_cap():
    now = at(6)
    a, b = farm(now), farm(now)
    for state in (a, b):
        state['size'] = 24
        state['meadow'] = {'v': 1, 'epoch': int((now + 10800) // meadow.EPOCH) - 20, 'patches': {}}
        meadow.update(state, now)
    assert a['meadow'] == b['meadow']
    assert len(a['meadow']['patches']) <= meadow.patch_limit(a) <= 12
    target = int((now + 10800) // meadow.EPOCH)
    assert a['meadow']['epoch'] == target
    assert all(cut >= (target - 7) * meadow.EPOCH - 10800
               for cut in a['meadow']['patches'].values())
    meadow.update(a, now)
    meadow.update(a, now)
    assert a['meadow']['epoch'] == target


def test_spawn_cell_uses_full_hash_modulo_free_cell_count():
    now = at(6)
    state = farm(now)
    state['size'] = 24
    target = int((now + 10800) // meadow.EPOCH)
    # Set cursor one epoch behind and select a deterministic epoch that spawns.
    while meadow._hash(state['id'], target) % 3:
        target += 1
    now = target * meadow.EPOCH - 10800
    state['meadow'] = {'v':1,'epoch':target-1,'patches':{}}
    free = meadow.eligible_cells(state)
    expected = free[meadow._hash(state['id'], target) % len(free)]
    meadow.update(state, now)
    assert list(state['meadow']['patches']) == [f'{expected[0]},{expected[1]}']


def test_update_discards_spawn_debt_after_long_absence_and_advances_cursor():
    start = int(datetime(2026, 11, 1, 12, tzinfo=MOSCOW).timestamp())
    now = int(datetime(2027, 1, 15, 12, tzinfo=MOSCOW).timestamp())
    state = farm(start)
    old_epoch = int((start + 10800) // meadow.EPOCH)
    current_epoch = int((now + 10800) // meadow.EPOCH)
    state['meadow'] = {'v': 1, 'epoch': old_epoch, 'patches': {}}

    meadow.update(state, now)

    assert current_epoch - old_epoch > 8
    assert state['meadow']['epoch'] == current_epoch
    assert state['meadow']['patches'] == {}


def test_settle_discards_spawn_debt_after_long_absence():
    start = int(datetime(2026, 11, 1, 12, tzinfo=MOSCOW).timestamp())
    now = int(datetime(2027, 1, 15, 12, tzinfo=MOSCOW).timestamp())
    state = farm(start)
    old_epoch = int((start + 10800) // meadow.EPOCH)
    current_epoch = int((now + 10800) // meadow.EPOCH)
    state['meadow'] = {'v': 1, 'epoch': old_epoch, 'patches': {}}

    settle_workers(state, now)

    assert state['meadow']['epoch'] == current_epoch
    assert state['meadow']['patches'] == {}


def test_stage_thresholds_season_multipliers_and_winter_pause():
    summer = at(6)
    assert meadow.stage(summer - 3 * 3600, summer) == 1
    assert meadow.stage(summer - 8 * 3600, summer) == 2
    spring = at(4)
    assert meadow.stage(spring - 2 * 3600, spring) == 1
    autumn = at(10)
    assert meadow.stage(autumn - 4 * 3600, autumn) == 1
    winter = at(1)
    assert meadow.season_at(winter) == 'winter'
    assert meadow.stage(winter - 10 * 86400, winter) == 0


def test_small_and_negative_timestamps_use_moscow_calendar_and_day_boundaries():
    assert meadow.season_at(-1) == 'winter'  # 1970-01-01 02:59:59 Moscow
    assert meadow.season_at(0) == 'winter'   # 1970-01-01 03:00 Moscow
    assert meadow.season_at(1000) == 'winter'
    assert meadow.season_at(-86400) == 'winter'  # 1969-12-31 03:00 Moscow
    moscow_new_year = -3 * 3600
    assert meadow._season_start(moscow_new_year - 1) == moscow_timestamp(1969, 12)
    assert meadow._season_start(moscow_new_year) == moscow_timestamp(1970, 1)
    assert meadow.growth_seconds(moscow_new_year - 1, moscow_new_year + 86400) == 0


def test_pre_epoch_season_boundary_and_next_stage_crossing():
    spring = moscow_timestamp(1969, 3)
    assert meadow.season_at(spring - 1) == 'winter'
    assert meadow.season_at(spring) == 'spring'
    assert meadow.growth_seconds(spring - 2 * 3600, spring) == 0
    assert meadow.growth_seconds(spring, spring + 2 * 3600) == 3 * 3600
    assert meadow.next_stage_at(spring, spring, 1) == spring + 2 * 3600


def test_winter_pause_preserves_growth_across_winter():
    cut = int(datetime(2026, 11, 30, 23, 59, tzinfo=MOSCOW).timestamp())
    after = int(datetime(2027, 3, 1, 0, 1, tzinfo=MOSCOW).timestamp())
    assert meadow.stage(cut, after) == 0


def test_mow_and_mow_all_yield_stage_amounts_without_xp_and_regrow_in_place():
    now = at(6)
    state = farm(now)
    cells = [f'{x},{y}' for x,y in meadow.eligible_cells(state)[:2]]
    state['meadow'] = {'v': 1, 'epoch': int((now + 10800) // meadow.EPOCH),
                       'patches': {cells[0]: now - 8 * 3600, cells[1]: now - 4 * 3600}}
    before_xp = state['xp']
    text = domain.apply(state, state, 'mow', {'cell': cells[0]}, now, 'mow-1')
    assert '×2' in text and state['inventory']['grass'] == 2
    assert state['meadow']['patches'][cells[0]] == now
    assert state['xp'] == before_xp
    with pytest.raises(domain.FarmError):
        domain.apply(state, state, 'mow', {'cell': cells[0]}, now, 'mow-2')
    state['meadow']['patches'][cells[1]] = now - 4 * 3600
    domain.apply(state, state, 'mow_all', {}, now, 'mow-all')
    assert state['inventory']['grass'] == 3
    assert state['meadow']['patches'][cells[1]] == now


def test_winter_mow_and_guest_mow_are_rejected_and_projection_is_private():
    now = at(1)
    owner = farm(now)
    owner['settings']['visibility'] = 'public'
    owner['meadow'] = {'v': 1, 'epoch': int((now + 10800) // meadow.EPOCH), 'patches': {'2,2': now - 30 * 86400}}
    with pytest.raises(domain.FarmError):
        domain.apply(owner, owner, 'mow', {'cell': '2,2'}, now, 'winter-mow')
    guest = domain.new_farm('guest', 'Guest', now)
    public = domain.project(owner, guest, now)
    assert 'meadow' not in public and 'meadow_view' not in public
    before = deepcopy(owner)
    assert domain.project(owner, owner, now)['meadow_view']['season'] == 'winter'
    assert owner == before
    with pytest.raises(domain.FarmError):
        domain.apply(guest, owner, 'mow', {'cell': '2,2'}, now, 'guest-mow')


def test_poultry_grass_substitution_flag_and_animal_helper_feed_path():
    state = farm()
    coop = next(obj for obj in state['objects'] if obj['type'] == 'coop')
    assert coop.get('grass_feed', True) is True
    state['inventory']['feed'] = 0
    state['inventory']['grass'] = 2
    assert can_feed(state, coop)
    start_feed(state, coop, at(6), 1, player=False)
    assert state['inventory']['grass'] == 0
    assert state['inventory']['feed'] == 0
    state['inventory']['grass'] = 2
    domain.apply(state, state, 'grass_feed', {'object': coop['id'], 'enabled': False}, at(6), 'toggle')
    assert not can_feed(state, coop)


@pytest.mark.parametrize(('feed', 'grass', 'expected_feed', 'expected_grass'), [
    (0, 2, 0, 0),  # grass alone fully replaces the chicken's feed input
    (2, 2, 2, 0),  # use the available grass first; keep the feed in inventory
])
def test_manual_feed_uses_grass_substitution_atomically(feed, grass, expected_feed, expected_grass):
    now = at(6)
    state = farm(now)
    coop = next(obj for obj in state['objects'] if obj['type'] == 'coop')
    state['inventory']['feed'] = feed
    state['inventory']['grass'] = grass

    domain.apply(state, state, 'feed', {'object': coop['id']}, now, f'manual-feed-{feed}-{grass}')

    assert state['inventory']['feed'] == expected_feed
    assert state['inventory']['grass'] == expected_grass
    assert coop['animal_job']['ready_at'] > now
    assert coop['revision'] == 1


def test_manual_feed_shortage_leaves_inventory_and_animal_unchanged():
    now = at(6)
    state = farm(now)
    coop = next(obj for obj in state['objects'] if obj['type'] == 'coop')
    state['inventory']['feed'] = 0
    state['inventory']['grass'] = 1
    before = deepcopy(state)

    with pytest.raises(domain.FarmError) as error:
        domain.apply(state, state, 'feed', {'object': coop['id']}, now, 'manual-feed-short')

    assert error.value.code == 'missing_goods'
    assert state == before


def test_harvester_collects_beds_then_only_tall_meadow_without_meadow_xp():
    now = at(6)
    state = farm(now)
    for obj in state['objects']:
        if obj['type'] == 'plot':
            obj['crop'] = None
    plot = next(obj for obj in state['objects'] if obj['type'] == 'plot')
    plot['crop'] = dict(id='wheat', planted_at=now-30, ready_at=now, yield_qty=3,
                        xp=1, helped=False, version='test', cost=0, gift=0)
    cells = [f'{x},{y}' for x,y in meadow.eligible_cells(state)[:2]]
    state['meadow'] = {'v':1,'epoch':int((now+10800)//meadow.EPOCH),
                       'patches':{cells[0]:now-8*3600,cells[1]:now-4*3600}}
    worker = dict(id='worker-1', speed=1, remaining=4, done=0)
    ordered = ordered_objects(state)
    assert _work_once(state, ordered, 'harvest', now, worker, None) == 1
    assert plot['crop'] is None
    xp_after_bed = state['xp']
    grass_before = state['inventory'].get('grass',0)
    assert _work_once(state, ordered, 'harvest', now, worker, None) == 1
    assert state['inventory']['grass'] == grass_before+2
    assert state['xp'] == xp_after_bed
    assert state['meadow']['patches'][cells[0]] == now
    assert state['meadow']['patches'][cells[1]] == now-4*3600


def test_harvester_mows_meadow_as_it_reaches_stage_two_during_shift():
    now = at(6)
    state = farm(now)
    for obj in state['objects']:
        if obj['type'] == 'plot':
            obj['crop'] = None
    cell = f'{meadow.eligible_cells(state)[0][0]},{meadow.eligible_cells(state)[0][1]}'
    state['meadow'] = {'v': 1, 'epoch': int((now + 10800) // meadow.EPOCH),
                       'patches': {cell: now - 7 * 3600}}
    state['helpers']['fox_picker'] = dict(acquired_at=now, total_runs=0, shift=dict(
        id='meadow-shift', status='working', plan='day', starts_at=now, until=now + 2 * 3600,
        next_at=now, interval=30, remaining=36, done=0, speed=1, role='harvest', quota=36))
    before = state['inventory'].get('grass', 0)

    settle_workers(state, now + 2 * 3600)

    shift = state['helpers']['fox_picker']['shift']
    assert shift['done'] == 1
    assert shift['status'] == 'finished'
    assert state['inventory']['grass'] == before + 2
    assert state['meadow']['patches'][cell] == now + 3600


def test_meadow_state_validation_rejects_invalid_coordinates():
    state = farm()
    state['meadow']['patches'] = {'99,99': at(6)}
    with pytest.raises(domain.FarmError):
        domain.validate_state(state)


def test_mow_command_receipt_replay_is_idempotent():
    class Unit:
        def __init__(self, state):
            self.state = state
            self.receipts = {}
            self.records = []
        async def lock(self, *keys): pass
        async def by_account(self, account): return self.state
        async def get(self, farm_id): return self.state if farm_id == self.state['id'] else None
        async def owner_account(self, farm_id): return 'owner'
        async def save(self, state, account_id=None): self.state = state
        async def receipt(self, account, key): return self.receipts.get((account,key))
        async def remember(self, account, key, fingerprint, result, now):
            self.receipts[(account,key)] = dict(fingerprint=fingerprint,result=result)
        async def record(self, *row): self.records.append(row)

    async def run():
        now = at(6)
        state = farm(now)
        state['id'] = '00000000-0000-4000-8000-000000000001'
        cell = next(f'{x},{y}' for x,y in meadow.eligible_cells(state))
        state['meadow']['patches'] = {cell: now - 8 * 3600}
        unit = Unit(state)
        service = FarmService(unit, Principal('owner','Owner'), clock=lambda: now)
        first = await service.command('meadow-mow-01','mow',{'cell':cell})
        grass = unit.state['inventory']['grass']
        replay = await service.command('meadow-mow-01','mow',{'cell':cell})
        assert replay == first
        assert unit.state['inventory']['grass'] == grass
        assert len(unit.records) == 1
    import asyncio
    asyncio.run(run())
