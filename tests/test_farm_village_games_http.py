"""HTTP acceptance for Pukh's full server-validated delivery cycle."""
import asyncio

from tests.test_farm_platform import (
    accepted, environment, farm_pg_url, ledger, player, receipts, view,
)
from tests.test_farm_village_games import GAME, NOW, solve
from domain.farm_ballista import replay


def test_pukh_five_shots_survive_http_retry_and_farm_reload(farm_pg_url):
    async def run():
        async with environment(farm_pg_url) as env, player(env) as guest:
            start_key = 'http-pukh-start'
            await accepted(guest, 'vgame_start', {'game': GAME}, key=start_key)
            started = (await view(guest))['village_games'][GAME]
            active = started['active']
            assert active is not None
            assert started['attempts'] == 1
            assert len(active['plan']['targets']) == 5

            log = solve(active['plan'])
            _, hits, durations = replay(active['plan'], log)
            assert hits == 5
            env.now[0] += (log[-1][2] + durations[-1] + 999) // 1000
            finish_data = {'game': GAME, 'run_id': active['run_id'], 'log': log}
            finish_key = 'http-pukh-finish'
            first = await accepted(guest, 'vgame_finish', finish_data, key=finish_key)

            # A lost HTTP response retried with the same idempotency key replays
            # the stored response, and a separate /me read restores final state.
            retry = await accepted(guest, 'vgame_finish', finish_data, key=finish_key)
            assert retry == first
            result = (await view(guest))['village_games'][GAME]
            assert result['active'] is None
            assert result['attempts'] == 1
            assert result['last_result']['run_id'] == active['run_id']
            assert result['last_result']['hits'] == 5
            assert result['last_result']['stars'] == 3
            assert not result['last_result']['expired']
            assert result['last_result']['reward'] > 0

            # Even a distinct command ID cannot settle this delivery twice.
            await accepted(guest, 'vgame_finish', finish_data,
                           key='http-pukh-finish-again')
            result_after_duplicate = (await view(guest))['village_games'][GAME]
            assert result_after_duplicate == result
            rows = await ledger(env)
            rewards = [row for row in rows if row['kind'] == 'vgame_m2']
            assert len(rewards) == 1
            assert rewards[0]['command_id'] == f"vgame:{active['run_id']}:3"
            assert rewards[0]['vigour_delta'] == result['last_result']['reward']
            assert len(await receipts(env, guest.account_id, finish_key)) == 1
            assert (await view(guest))['village_games'][GAME]['last_result'] == result['last_result']

    asyncio.run(run())
