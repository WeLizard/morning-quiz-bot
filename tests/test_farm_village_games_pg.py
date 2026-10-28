"""Real row locking, receipts and M2 ledger for two village game tabs."""
import asyncio

import sqlalchemy as sa

from qw_farm.persistence import Unit
from qw_farm.service import FarmService, Principal
from tests.test_farm_oleg_pg import environment, seeded, pg_url
from tests.test_farm_village_games import solve, GAME, NOW
from domain.farm_ballista import replay


def test_two_tabs_and_receipts_pay_one_vigour_delta(pg_url):
    async def scenario():
        async with environment(pg_url) as env:
            account, farm_id = await seeded(env, NOW)
            now = [NOW]

            async def command(key, kind, data):
                async with env.db.transaction() as session:
                    unit = Unit(session,env.schema)
                    service = FarmService(unit,Principal(str(account),'Игрок'),clock=lambda:now[0])
                    return await service.command(key,kind,data)

            starts = await asyncio.gather(command('pukh-start-01','vgame_start',{'game':GAME}),
                                          command('pukh-start-02','vgame_start',{'game':GAME}))
            active = starts[0]['village_games'][GAME]['active']
            assert starts[1]['village_games'][GAME]['active']['run_id'] == active['run_id']
            assert starts[1]['village_games'][GAME]['attempts'] == 1
            log = solve(active['plan'])
            durations = replay(active['plan'],log)[2]
            now[0] += (log[-1][2]+durations[-1]+999)//1000
            data = dict(game=GAME,run_id=active['run_id'],log=log)
            await asyncio.gather(command('pukh-finish-01','vgame_finish',data),
                                 command('pukh-finish-02','vgame_finish',data))
            cached = await command('pukh-finish-01','vgame_finish',data)
            assert cached['village_games'][GAME]['active'] is None
            async with env.db.transaction() as session:
                unit = Unit(session,env.schema)
                farm = await unit.get(farm_id)
                assert farm['progress']['pool'] == 12
                ledger = env.schema['ledger']
                rows = (await unit.execute(sa.select(ledger).where(ledger.c.kind=='vgame_m2'))).mappings().all()
                assert len(rows) == 1
                assert rows[0]['vigour_delta'] == 12 and rows[0]['xp_delta'] == 0
                history = await unit.history(farm_id)
                assert any(row['vigour_delta']==12 for row in history)
    asyncio.run(scenario())
