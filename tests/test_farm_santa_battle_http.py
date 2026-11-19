"""HTTP acceptance on PostgreSQL: a whole «Битва с Сантой» battle, a lost response retried, the reward and the barn."""
import asyncio
from copy import deepcopy

from qw_farm.catalog import LEVELS
from qw_farm.domain import validate_state
from qw_farm.persistence import Unit
from tests.test_farm_platform import accepted, command, environment, farm_pg_url, ledger, player, view  # noqa: F401
from domain import farm_santa_battle as sb
from tests.test_farm_santa_battle_service import DEC21, GAME, sim


async def _seed(env, p):
    """Fixture-only level and barn; the battle itself runs through HTTP."""
    async with env.db.transaction() as session:
        unit = Unit(session, env.schema)
        farm = await unit.by_account(p.account_id)
        before = deepcopy(farm)
        farm['xp'] = LEVELS[5]
        farm['inventory']['pie'] = 1
        validate_state(farm)
        await unit.save(farm)
        await unit.record(p.account_id, 'fixture-santa', 'fixture', before, farm, env.now[0])


def test_santa_battle_survives_http_retry_and_farm_reload(farm_pg_url):
    async def run():
        async with environment(farm_pg_url) as env:
            env.now[0] = DEC21
            async with player(env) as guest:
                await _seed(env, guest)
                await accepted(guest, 'vgame_start', {'game': GAME, 'battle': 1}, key='http-santa-start')
                active = (await view(guest))['village_games'][GAME]['active']
                assert active['battle'] == 1
                plan = active['plan']
                # the farmer eats the pie from the «Корзинка» first, then the team plays it well
                log = [['player', 'pie', 'player', None]]
                state = sb.new_state(plan)
                sb.act(plan, state, log[0])
                while state['outcome'] is None:
                    entry = sim.smart(plan, state, True, False)
                    log.append(entry)
                    sb.act(plan, state, entry)
                env.now[0] = active['started_at'] + len(log) + 3
                data = {'game': GAME, 'run_id': active['run_id'], 'log': log}
                first = await accepted(guest, 'vgame_finish', data, key='http-santa-finish')
                assert 'Колокольчик Крампуса' in first['notice']
                assert await accepted(guest, 'vgame_finish', data, key='http-santa-finish') == first
                again = await accepted(guest, 'vgame_finish', data, key='http-santa-finish-2')
                assert again['notice'] == 'Результат уже учтён.'
                farm = await view(guest)
                game = farm['village_games'][GAME]
                assert game['active'] is None and game['last_result']['outcome'] == 'win'
                assert game['last_result']['items'] == {'pie': 1}
                assert farm['inventory'].get('pie', 0) == 0
                assert game['battles'][0]['reward']['got'] is True
                assert 'fest_ny_krampus_bell' in farm['festival']['collection']
                rows = [r for r in await ledger(env) if r['kind'] == 'vgame_santa']
                assert len(rows) == 1 and rows[0]['command_id'] == 'vgame:' + active['run_id']
                assert rows[0]['inventory_delta'] == {'pie': -1} and rows[0]['coins_delta'] == 0 and rows[0]['xp_delta'] == 0
                bad = await command(guest, 'vgame_start', {'game': GAME, 'battle': 3}, key='http-santa-closed')
                assert bad.status_code == 409 and bad.json()['code'] == 'battle_closed'

    asyncio.run(run())
