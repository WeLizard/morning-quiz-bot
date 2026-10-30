"""The pie tower through FarmService: the shared row, the threshold and the lazy common reward."""
import asyncio
from copy import deepcopy

from qw_farm import festivals
from qw_farm.service import FarmService, Principal
from tests.test_farm_economy_r9 import SharedUnit, SharedVillage, farm
from tests.test_farm_pie_service import FAIR, solve


class TowerUnit(SharedUnit):
    def __init__(self, account_id, state, village):
        super().__init__(account_id, state, village)
        self.towers = {}

    async def tower_peek(self, key):
        return deepcopy(self.towers.get(key))

    async def tower_add(self, key, value, player_delta, goal, now):
        row = self.towers.setdefault(key, dict(key=key, total=0, goal=goal, players=0, reached_at=None))
        row['total'] += value
        row['players'] += player_delta
        if row['reached_at'] is None and row['total'] >= row['goal']:
            row['reached_at'] = now
        return dict(row)


def test_finish_crosses_the_goal_and_grants_the_lot_once():
    async def run():
        village = SharedVillage(goal=10**9)
        state = farm(lv=12)
        state['name'] = 'a'
        unit = TowerUnit('a', state, village)
        unit.towers['posidelki-2026'] = dict(key='posidelki-2026', total=39, goal=40, players=5, reached_at=None)
        now = [FAIR]
        service = FarmService(unit, Principal('a', 'a'), clock=lambda: now[0])
        started = await service.command('pie-start-0001', 'vgame_start', {'game': 'agata_pie'})
        active = started['village_games']['agata_pie']['active']
        log = solve(active['plan'])
        now[0] = active['started_at'] + log[-1] // 1000 + 2
        finished = await service.command('pie-finish-0001', 'vgame_finish',
                                         {'game': 'agata_pie', 'run_id': active['run_id'], 'log': log})
        f = next(iter(unit.farms.values()))
        row = unit.towers['posidelki-2026']
        assert row['total'] == 39 + len(log) and row['players'] == 6 and row['reached_at'] == now[0]
        assert f['festivals']['posidelki-2026']['rewards']['fest_posid_tower'] == 1
        assert 'Пирог-башня' in finished['notice']
        view = await service.view()
        tower = view['farm']['festival']['fair']['tower']
        assert tower['total'] == 39 + len(log) and tower['reached'] is True
        assert 'fest_posid_tower' in view['farm']['festival']['collection']
    asyncio.run(run())


def test_an_earlier_participant_gets_the_lot_lazily_on_view():
    async def run():
        village = SharedVillage(goal=10**9)
        state = farm(lv=12)
        state['name'] = 'b'
        state['festivals'] = {'posidelki-2026': {**festivals.blank(), 'tower': True}}
        unit = TowerUnit('b', state, village)
        unit.towers['posidelki-2026'] = dict(key='posidelki-2026', total=40, goal=40, players=6, reached_at=FAIR - 60)
        service = FarmService(unit, Principal('b', 'b'), clock=lambda: FAIR)
        view = await service.view()
        f = next(iter(unit.farms.values()))
        assert f['festivals']['posidelki-2026']['rewards']['fest_posid_tower'] == 1
        assert 'fest_posid_tower' in view['farm']['festival']['collection']
        before = f['festivals']['posidelki-2026']['rewards']['fest_posid_tower']
        await service.view()
        assert next(iter(unit.farms.values()))['festivals']['posidelki-2026']['rewards']['fest_posid_tower'] == before
    asyncio.run(run())
