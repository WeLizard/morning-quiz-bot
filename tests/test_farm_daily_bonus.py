"""Shared direct-cash budget; all execution belongs to the task Docker runner."""
import asyncio
from copy import deepcopy
from uuid import uuid4, UUID
import pytest

from qw_farm import daily_bonus as bonus, minigames, oleg, economy, tavern, progression
from qw_farm.catalog import LEVELS, income_ref
from qw_farm.domain import FarmError, new_farm, project, validate_state
from qw_farm.expansion import upgrade_state
from qw_farm.persistence import Unit
from qw_farm.service import FarmService, Principal
from tests.test_farm_platform import environment, player, command, accepted, view, raw_farm, farm_pg_url
from tests.test_farm_village_construction import pg_ready
from tests.test_farm_village_games import start as ballista_start, finish as ballista_finish, solve as solve_ballista

NOW = 1800000000


def farm():
    f = upgrade_state(new_farm(str(uuid4()),'Budget',NOW))
    f.update(coins=100000,starter_credit=0,xp=0)
    return f


def test_shared_partial_zero_frozen_reference_rollover_overflow_and_merge():
    f = farm()
    cap = bonus.public(f,NOW)['cap']
    assert bonus.grant(f,'house',cap-2,NOW) == cap-2
    snapshot = bonus.public(f,NOW)
    f['xp'] = LEVELS[-1]
    from qw_farm.village_effects import dinner
    assert dinner(f,economy.moscow_day(NOW))['cap'] == bonus.public(f,NOW)['cap'] == cap
    assert bonus.grant(f,'oleg',12,NOW) == 2
    assert bonus.grant(f,'dinner',100,NOW) == 0
    assert bonus.public(f,NOW)['ref'] == snapshot['ref']
    assert bonus.public(f,NOW+86400)['ref'] == income_ref(50)
    second = farm()
    bonus.grant(second,'barn',10,NOW)
    bonus.merge(f,second,NOW)
    assert f[bonus.KEY]['cap'] == cap and f[bonus.KEY]['paid'] == cap+10
    assert bonus.quote(f,NOW,10) == 0
    full = farm();full['coins'] = 10**12
    before = deepcopy(full)
    with pytest.raises(FarmError):
        bonus.grant(full,'house',1,NOW)
    assert full == before


def test_partial_zero_results_remain_valid_and_consumed():
    f = farm()
    bonus.grant(f,'house',bonus.public(f,NOW)['cap'],NOW)
    minigames.start(f,{'game':'barn'},NOW)
    active = deepcopy(f['minigames']['barn']['active'])
    data = dict(game='barn',attempt_id=active['attempt_id'],answer=active['solution'])
    minigames.answer(f,data,NOW)
    result = f['minigames']['barn']['last_result']
    assert result['correct'] and result['reward'] == 0 and result['bonus_feed'] == 1
    assert minigames.answer(f,data,NOW)[1] is False
    oleg.start(f,{},NOW)
    run = f['oleg_game']['run']
    for index in range(3):
        oleg.answer(f,dict(run_id=run['id'],round=index,notes=oleg.expected_notes(run,index)),NOW)
    assert f['oleg_game']['last_result']['coins'] == 0
    assert f['oleg_game']['last_result']['xp'] >= 4
    validate_state(f)
    assert minigames.public(f,NOW)['barn']['next_reward']['amount'] == 0
    assert oleg.public(f,NOW)['next_reward']['coins'] == 0


def test_pukh_full_m2_fallback_consumes_nominal_entitlement_after_partial_cash():
    f = farm()
    progression.touch(f,NOW)
    f['progress']['pool'] = progression.status(f,NOW)['pool_cap']
    bonus.grant(f,'house',bonus.public(f,NOW)['cap']-2,NOW)
    run = ballista_start(f,NOW)
    ballista_finish(f,run,solve_ballista(run['plan']))
    state = f['village_games']['pukh_ballista']
    assert state['reward_kind'] == 'premium'
    assert state['last_result']['reward'] == 2
    assert state['paid'] == state['reward_base']
    run2 = ballista_start(f,NOW+120)
    ballista_finish(f,run2,solve_ballista(run2['plan']))
    assert state['last_result']['reward'] == 0
    assert bonus.public(f,NOW)['remaining'] == 0
    validate_state(f)


def test_pukh_full_wallet_keeps_zero_success_and_consumed_entitlement():
    f = farm()
    progression.touch(f,NOW)
    f['progress']['pool'] = progression.status(f,NOW)['pool_cap']
    f['coins'] = 10**12
    run = ballista_start(f,NOW)
    ballista_finish(f,run,solve_ballista(run['plan']))
    state = f['village_games']['pukh_ballista']
    assert state['last_result']['reward'] == 0 and state['paid'] == state['reward_base']
    assert f['coins'] == 10**12 and bonus.public(f,NOW)['paid'] == 0


def test_postgres_concurrent_sources_partial_zero_reopen_rollover_and_privacy(farm_pg_url):
    async def scenario():
        async with environment(farm_pg_url) as env, player(env) as actor, player(env,'telegram') as visitor:
            await pg_ready(env,actor,lv=2)
            async with env.db.transaction() as session:
                unit = Unit(session,env.schema)
                f = await unit.by_account(actor.account_id)
                f['settings']['visibility'] = 'public'
                cap = bonus.public(f,env.now[0])['cap']
                bonus.grant(f,'house',cap-5,env.now[0])
                minigames.start(f,{'game':'barn'},env.now[0])
                barn = deepcopy(f['minigames']['barn']['active'])
                oleg.start(f,{},env.now[0])
                f['oleg_game']['run']['round'] = 2
                run = deepcopy(f['oleg_game']['run'])
                f['greenhouse_bed'] = dict(cycle=1,crop=dict(id='fire_pepper',ready_at=env.now[0]+100))
                await unit.save(f)
            before = await raw_farm(env,actor)
            responses = await asyncio.gather(
                command(actor,'minigame_answer',dict(game='barn',attempt_id=barn['attempt_id'],answer=barn['solution']),key='bonus-concurrent-barn'),
                command(actor,'oleg_answer',dict(run_id=run['id'],round=2,notes=oleg.expected_notes(run,2)),key='bonus-concurrent-oleg'))
            assert [r.status_code for r in responses] == [200,200]
            after = await raw_farm(env,actor)
            assert after['coins']-before['coins'] == 5
            assert after[bonus.KEY]['paid'] == cap
            assert after['oleg_game']['last_result']['xp'] >= 4
            assert after['minigames']['barn']['last_result']['correct']
            assert (await view(actor))['daily_cash_bonus']['remaining'] == 0
            foreign = await view(visitor,actor.farm_id)
            assert not {'daily_cash_bonus','greenhouse_bed','greenhouse_pending','village_bonus','tavern'} & foreign.keys()
            env.now[0] += 86400
            async with env.db.transaction() as session:
                unit = Unit(session,env.schema)
                service = FarmService(unit,Principal(actor.account_id,'actor'),clock=lambda:env.now[0])
                await service.command('bonus-rollover-start','minigame_start',{'game':'barn'})
                current = await unit.by_account(actor.account_id)
                active = current['minigames']['barn']['active']
                await service.command('bonus-rollover-answer','minigame_answer',dict(game='barn',attempt_id=active['attempt_id'],answer=active['solution']))
            today = await raw_farm(env,actor)
            assert today[bonus.KEY]['day'] == economy.moscow_day(env.now[0])
            assert today[bonus.KEY]['paid'] == max(10,income_ref(2)//100)
            # Persist the same effect-merge hook used by AccountMergeService.
            async with env.db.transaction() as session:
                from qw_farm import construction
                unit = Unit(session,env.schema)
                await unit.lock('farm:'+actor.farm_id,'farm:'+visitor.farm_id)
                main = await unit.by_account(actor.account_id)
                secondary = await unit.by_account(visitor.account_id)
                bonus.grant(secondary,'oleg',12,env.now[0])
                main_cap = main[bonus.KEY]['cap']
                construction.merge_effect_state(main,secondary,env.now[0])
                await unit.save(main)
            merged = await raw_farm(env,actor)
            assert merged[bonus.KEY]['cap'] == main_cap
            assert merged[bonus.KEY]['paid'] == today[bonus.KEY]['paid']+12
    asyncio.run(scenario())


def test_postgres_missing_legacy_receipt_exhausts_budget_conservatively(farm_pg_url):
    async def scenario():
        async with environment(farm_pg_url) as env, player(env) as actor:
            await pg_ready(env,actor,lv=2)
            async with env.db.transaction() as session:
                unit = Unit(session,env.schema)
                f = await unit.by_account(actor.account_id)
                before = deepcopy(f)
                f['coins'] += 1
                await unit.record(actor.account_id,'legacy-missing-receipt','vgame_premium',before,f,env.now[0])
                await unit.save(f)
            result = (await view(actor))['daily_cash_bonus']
            assert result['bootstrap_incomplete'] and result['remaining'] == 0
    asyncio.run(scenario())


def test_postgres_legacy_six_receipts_recover_actual_rewards_despite_net_upkeep(farm_pg_url):
    async def scenario():
        async with environment(farm_pg_url) as env, player(env) as actor:
            await pg_ready(env,actor,lv=2)
            async with env.db.transaction() as session:
                unit = Unit(session,env.schema)
                f = await unit.by_account(actor.account_id)
                nominal = max(10,income_ref(2)//100)
                for index in range(6):
                    key,attempt = f'legacy-bonus-{index}',str(uuid4())
                    outcome = dict(attempt_id=attempt,correct=True,reward=nominal,reward_kind='coins',answered_at=env.now[0])
                    response = dict(minigames=dict(house=dict(last_result=outcome)))
                    await unit.remember(actor.account_id,key,'legacy',response,env.now[0])
                    before = deepcopy(f)
                    f['coins'] -= 1 # old net ledger hides an actual premium behind upkeep
                    await unit.record(actor.account_id,key,'minigame_answer',before,f,env.now[0])
                f['minigames']['house']['last_result'] = outcome # only the sixth result survives in farm payload
                await unit.save(f)
            state = await view(actor)
            assert state['daily_cash_bonus']['paid'] == 6*nominal
            assert state['daily_cash_bonus']['remaining'] == 0
            async with env.db.transaction() as session:
                unit = Unit(session,env.schema)
                f = await unit.by_account(actor.account_id)
                assert bonus.grant(f,'dinner',nominal,env.now[0]) == 0
                await unit.save(f)
            assert (await view(actor))['daily_cash_bonus']['paid'] == 6*nominal
    asyncio.run(scenario())


def test_postgres_legacy_vgame_run_ledger_key_deduplicates_projection_receipts(farm_pg_url):
    async def scenario():
        async with environment(farm_pg_url) as env, player(env) as actor:
            await pg_ready(env,actor,lv=2)
            run_id = str(uuid4())
            async with env.db.transaction() as session:
                unit = Unit(session,env.schema)
                f = await unit.by_account(actor.account_id)
                result = dict(run_id=run_id,score=950,stars=3,hits=5,practice=False,
                              expired=False,reward_kind='premium',reward=7)
                response = dict(village_games=dict(pukh_ballista=dict(last_result=result)))
                for key in ('legacy-vgame-finish','legacy-vgame-replay-a','legacy-vgame-replay-b'):
                    await unit.remember(actor.account_id,key,'legacy',response,env.now[0])
                before = deepcopy(f)
                f['coins'] -= 1 # premium and upkeep produced a negative net ledger delta
                await unit.record(actor.account_id,f'vgame:{run_id}:3','vgame_premium',before,f,env.now[0])
                await unit.save(f)
            current = (await view(actor))['daily_cash_bonus']
            assert current['paid'] == 7 and current['by_source'] == {'village_games':7}
            assert not current.get('bootstrap_incomplete',False)
            reopened = (await view(actor))['daily_cash_bonus']
            assert reopened == current
    asyncio.run(scenario())


def test_postgres_legacy_oleg_intermediate_terminal_and_practice_bootstrap(farm_pg_url):
    async def scenario():
        async with environment(farm_pg_url) as env, player(env) as actor:
            await pg_ready(env,actor,lv=2)
            async with env.db.transaction() as session:
                unit = Unit(session,env.schema)
                f = await unit.by_account(actor.account_id)
                for attempt in range(2):
                    oleg.start(f,{},env.now[0])
                    run = f['oleg_game']['run']
                    for round_no in range(3):
                        before = deepcopy(f)
                        oleg.answer(f,dict(run_id=run['id'],round=round_no,
                            notes=oleg.expected_notes(run,round_no)),env.now[0])
                        # Represent an installation before shared-budget activation.
                        f.pop(bonus.KEY,None)
                        if attempt == 0 and round_no == 2:
                            f['coins'] -= 13 # actual 12, net -1 after the old upkeep charge
                        key = f'legacy-oleg-{attempt}-{round_no}'
                        response = dict(oleg_game=oleg.public(f,env.now[0]))
                        await unit.remember(actor.account_id,key,'legacy',response,env.now[0])
                        await unit.record(actor.account_id,key,'oleg_answer',before,f,env.now[0])
                assert f['oleg_game']['last_result']['coins'] == 0
                await unit.save(f)
            current = (await view(actor))['daily_cash_bonus']
            assert current['paid'] == 12 and current['by_source'] == {'oleg':12}
            assert not current.get('bootstrap_incomplete',False)
            assert (await view(actor))['daily_cash_bonus'] == current
    asyncio.run(scenario())
