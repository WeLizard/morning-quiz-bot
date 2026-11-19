"""Building effects: run only inside the isolated task Docker runner."""
import asyncio
from copy import deepcopy
from datetime import datetime, timezone

import pytest
import sqlalchemy as sa
from uuid import UUID

from qw_farm import construction as cn, expansion, festivals, tavern, village_effects as effects
from qw_farm.catalog import CROPS, EXOTIC_BY_FRUIT, ITEMS, LEVELS
from qw_farm.domain import FarmError, new_farm
from tests.test_farm_village_construction import World, T0, pg_ready
from tests.test_farm_platform import environment, player, accepted, command, view, raw_farm, farm_pg_url
from qw_farm.persistence import Unit
from qw_farm.service import FarmService, Principal


def farm(tier=3):
    f = expansion.upgrade_state(new_farm('00000000-0000-0000-0000-000000000001','effects',T0))
    f.update(xp=LEVELS[11],coins=100000,starter_credit=0)
    f['village_bonus'] = dict(open=['greenhouse','tavern','fairground'],tiers=dict(greenhouse=tier,tavern=tier,fairground=tier),
        month=effects.month(T0),crop='wheat')
    return f


def test_multiplier_snapshots_current_action_and_leaves_other_timers_alone():
    f = farm()
    crop = next(iter(EXOTIC_BY_FRUIT.values()))
    f['village_bonus']['crop'] = crop['id']
    obj = dict(crop=None,revision=0,type='plot')
    expansion.plant(f,obj,dict(crop,cost=0),T0,1,seed=crop['seed'])
    assert obj['crop']['ready_at'] - obj['crop']['planted_at'] == pytest.approx(crop['seconds']*.81,abs=1)
    snapshot = deepcopy(obj['crop'])
    f['village_bonus']['crop'] = 'wheat'
    assert obj['crop'] == snapshot
    assert effects.crop_multiplier(f,'wheat',T0) == .9
    assert effects.crop_multiplier(f,crop['id'],T0) == .9
    assert effects.crop_multiplier(farm(0),crop['id'],T0) == 1


def test_winner_tie_fallback_and_calendar():
    assert effects.winner({'a':'carrot','b':'wheat'}) == 'carrot'
    assert effects.winner({},'carrot') == 'carrot'
    assert effects.winner({}) == 'wheat'
    assert effects.next_month('2026-12') == '2027-01'


def test_month_snapshot_does_not_apply_to_another_month_or_closed_project():
    f = farm()
    b = f['village_bonus']
    crop = next(iter(EXOTIC_BY_FRUIT))
    b['crop'] = crop
    assert effects.crop_multiplier(f,crop,T0) == pytest.approx(.81)
    assert effects.crop_multiplier(f,crop,T0+90*86400) == .9
    b['open'] = []
    assert effects.crop_multiplier(f,crop,T0) == 1


def test_two_same_dish_slots_pay_dinner_once_and_legacy_is_consumed():
    f = farm()
    f['objects'].append(dict(type='bakery'))
    day = tavern.market.moscow_day(T0)
    before = f['coins']
    amount = effects.dinner(f,day)['amount']
    base = 0
    for slot in (0,1):
        order = tavern._offer(f,day,slot)
        f['inventory'][order['item']] = f['inventory'].get(order['item'],0)+1
        base += order['coins']
        tavern.command(f,'tavern_order',dict(day=day,item=order['item'],slot=slot),T0)
    assert f['coins']-before == base+amount
    assert f['tavern']['dinner']['paid'] == amount
    with pytest.raises(FarmError):
        tavern.command(f,'tavern_order',dict(day=day,item=order['item'],slot=1),T0)
    legacy = farm()
    legacy['tavern'] = dict(order=dict(day=day,item='bread',coins=1))
    assert effects.dinner(legacy,day)['claimed']
    assert not effects.dinner(legacy,day)['available']


def test_tavern_overflow_and_no_stock_do_not_grant_bonus():
    f = farm()
    f['objects'].append(dict(type='bakery'))
    day = tavern.market.moscow_day(T0)
    order = tavern._offer(f,day)
    f['coins'] = 10**12
    f['inventory'][order['item']] = 1
    before = deepcopy(f)
    with pytest.raises(FarmError):
        tavern.command(f,'tavern_order',dict(day=day,item=order['item']),T0)
    assert f == before


def test_fair_early_access_boundaries_price_and_shared_quota():
    at = int(datetime(2026,11,25,21,tzinfo=timezone.utc).timestamp()) # 26th Moscow midnight
    f = farm()
    assert festivals.owner_view(f,at-3601)['fair'] is None
    early = festivals.owner_view(f,at-3600)['fair']
    assert early['early'] and early['regular_starts_at'] == at
    ordinary = farm(0)
    assert festivals.owner_view(ordinary,at-1)['fair'] is None
    good = next(g for g in early['goods'] if g['level'] <= 12)
    assert good['price'] == max(1,good['base_price']*90//100)
    festivals.buy(f,dict(festival='posidelki',item=good['id']),at-1)
    with pytest.raises(FarmError,match='у тебя уже есть'):
        festivals.buy(f,dict(festival='posidelki',item=good['id']),at)
    assert not festivals.current(at-1)['phase'] == 'fair'


def test_early_new_fair_does_not_hide_current_fair_from_buy_access():
    # Maslenitsa starts directly after the flowers fair in 2027.
    at = int(datetime(2027,3,8,20,30,tzinfo=timezone.utc).timestamp())
    f = farm()
    assert festivals.fair_access(f,at)['id'] == 'maslenitsa'
    assert festivals.fair_access(f,at,'spring_flowers')['id'] == 'spring_flowers'
    assert festivals.current(at)['id'] == 'spring_flowers'


def test_merge_keeps_daily_quotas_and_growing_crops_without_second_bed():
    a,b = farm(),farm()
    a['tavern'] = dict(orders={'5:0':dict(day=5,item='bread',coins=1)})
    b['tavern'] = dict(orders={'5:1':dict(day=5,item='bread',coins=1)},dinner=dict(day=5,paid=10))
    a['greenhouse_bed'] = dict(cycle=2,crop=dict(id='fire_pepper',ready_at=T0+200))
    b['greenhouse_bed'] = dict(cycle=4,crop=dict(id='blue_corn',ready_at=T0+300))
    cn.merge_effect_state(a,b)
    assert set(a['tavern']['orders']) == {'5:0','5:1'}
    assert a['tavern']['dinner']['day'] == 5
    assert a['greenhouse_bed']['crop']['id'] == 'fire_pepper'
    assert a['greenhouse_pending'] == [b['greenhouse_bed']['crop']]
    assert a['greenhouse_bed']['cycle'] == 5


def test_month_ballot_bed_fences_and_public_honors():
    async def scenario():
        w = World()
        player = await w.player('a')
        await w.build('a')
        for pid in cn.ORDER:
            await w.force(pid,status='done',stage=2,opened_at=T0)
        async with w.db.transaction() as unit:
            for pid in cn.ORDER:
                await unit.execute(unit.t['contribs'].insert().values(project_id=pid,account_id=player.aid,
                    farm_id=UUID(player.fid),value=100000,share_bp=10000,tier=3,updated_at=T0))
        build = await w.build('a')
        assert build['honor_details']['tavern'][0]['name'] == (await w.farm('a'))['name']
        greenhouse = build['greenhouse']
        month = greenhouse['next_month']
        await w.cmd('a','greenhouse_vote',dict(month=month,crop='carrot'))
        await w.cmd('a','greenhouse_vote',dict(month=month,crop='wheat'))
        assert (await w.build('a'))['greenhouse']['vote'] == 'wheat'
        crop = next(iter(EXOTIC_BY_FRUIT.values()))
        await w.grant('a',{crop['seed']:1})
        await w.cmd('a','greenhouse_plant',dict(crop=crop['id'],cycle=0))
        with pytest.raises(FarmError,match='уже изменилась'):
            await w.cmd('a','greenhouse_plant',dict(crop=crop['id'],cycle=0))
        bed = (await w.build('a'))['greenhouse']['bed']
        w.now[0] = bed['ready_at']
        await w.cmd('a','greenhouse_harvest',dict(cycle=1))
        assert (await w.farm('a'))['inventory'][crop['id']] == crop['yield_qty']
    asyncio.run(scenario())


def test_postgres_concurrent_ballots_dinner_slots_merge_and_reopen(farm_pg_url):
    async def scenario():
        async with environment(farm_pg_url) as env, player(env) as main, player(env,'telegram') as secondary:
            for p in (main,secondary):
                await pg_ready(env,p,lv=12)
            await accepted(main,'build',dict(type='bakery',x=6,y=3))
            async with env.db.transaction() as session:
                unit = Unit(session,env.schema)
                await unit.execute(unit.t['projects'].update().values(status='done',stage=2,opened_at=env.now[0]))
                for p in (main,secondary):
                    f = await unit.by_account(p.account_id)
                    for pid in ('greenhouse','tavern'):
                        await unit.execute(unit.t['contribs'].insert().values(project_id=pid,account_id=UUID(p.account_id),
                            farm_id=UUID(f['id']),value=10000,share_bp=10000,tier=3,updated_at=env.now[0]))
            projected = (await view(main))['village_build']
            month = projected['greenhouse']['next_month']
            responses = await asyncio.gather(
                command(main,'greenhouse_vote',dict(month=month,crop='wheat'),key='effects-vote-main'),
                command(secondary,'greenhouse_vote',dict(month=month,crop='carrot'),key='effects-vote-secondary'))
            assert [r.status_code for r in responses] == [200,200]
            assert (await view(main))['village_build']['greenhouse']['vote'] == 'wheat'
            assert (await view(secondary))['village_build']['greenhouse']['vote'] == 'carrot'
            orders = projected['tavern']['orders']
            assert len(orders) == 2
            async with env.db.transaction() as session:
                unit = Unit(session,env.schema)
                f = await unit.by_account(main.account_id)
                for order in orders:
                    f['inventory'][order['item']] = 10
                await unit.save(f)
            before = await raw_farm(env,main)
            responses = await asyncio.gather(*(command(main,'tavern_order',dict(day=projected['tavern']['day'],
                slot=o['slot'],item=o['item']),key=f'effects-order-slot-{o["slot"]}') for o in orders))
            assert [r.status_code for r in responses] == [200,200]
            after = await raw_farm(env,main)
            assert after['coins']-before['coins'] == sum(o['coins'] for o in orders)+projected['tavern']['dinner']['amount']
            assert all(o['done'] for o in (await view(main))['village_build']['tavern']['orders'])
            # Exercise the real shared SQL merge hook with both votes, then secondary only.
            async with env.db.transaction() as session:
                unit = Unit(session,env.schema)
                await unit.lock('farm:'+main.farm_id,'farm:'+secondary.farm_id)
                c = unit.t['contribs']
                await unit.execute(c.update().where(c.c.project_id == 'greenhouse',c.c.account_id == UUID(main.account_id))
                    .values(tier=0,share_bp=500,updated_at=env.now[0]-100))
                await unit.execute(c.update().where(c.c.project_id == 'greenhouse',c.c.account_id == UUID(secondary.account_id))
                    .values(tier=0,share_bp=600,updated_at=env.now[0]-100))
                await unit.execute(unit.t['projects'].update().where(unit.t['projects'].c.id == 'greenhouse')
                    .values(opened_at=env.now[0]-200))
                await cn.merge_prepare(unit,main.account_id,secondary.account_id,env.now[0])
                merged = await unit.by_account(main.account_id)
                await cn.refresh_bonus(unit,merged,main.account_id)
                await cn.month_snapshot(unit,merged,env.now[0])
                exotic = next(iter(EXOTIC_BY_FRUIT))
                assert effects.crop_multiplier(merged,exotic,env.now[0]) == .9
                # The next actual manual planting uses the merged contribution;
                # previously saved crop snapshots are never rewritten.
                obj = dict(type='plot',revision=0,crop=None)
                expansion.plant(merged,obj,dict(EXOTIC_BY_FRUIT[exotic],cost=0),env.now[0],1)
                assert obj['crop']['ready_at']-env.now[0] == pytest.approx(EXOTIC_BY_FRUIT[exotic]['seconds']*.9,abs=1)
                table = unit.t['states'].metadata.tables['system_states']
                row = (await unit.execute(sa.select(table.c.payload).where(table.c.key == cn.MONTH_PREFIX+month))).scalar_one()
                assert row['votes'] == {str(main.account_id):'wheat'}
                later = effects.next_month(month)
                await cn._insert_ignore(unit,table,['key'],key=cn.MONTH_PREFIX+later,payload=dict(schema_version=1,
                    finalized=False,votes={str(secondary.account_id):'carrot'}))
            async with env.db.transaction() as session:
                unit = Unit(session,env.schema)
                await unit.lock('farm:'+main.farm_id,'farm:'+secondary.farm_id)
                await cn.merge_prepare(unit,main.account_id,secondary.account_id,env.now[0])
                table = unit.t['states'].metadata.tables['system_states']
                row = (await unit.execute(sa.select(table.c.payload).where(table.c.key == cn.MONTH_PREFIX+later))).scalar_one()
                assert row['votes'] == {str(main.account_id):'carrot'}
            # One year absent creates no chain of empty month rows and carries the winner.
            env.now[0] += 400*86400
            async with env.db.transaction() as session:
                unit = Unit(session,env.schema)
                service = FarmService(unit,Principal(main.account_id,'main'),clock=lambda:env.now[0])
                fresh = (await service.view())['farm']['village_build']['greenhouse']
            assert fresh['crop'] == 'carrot'
            async with env.db.transaction() as session:
                unit = Unit(session,env.schema)
                table = unit.t['states'].metadata.tables['system_states']
                count = (await unit.execute(sa.select(sa.func.count()).select_from(table).where(table.c.key.like(cn.MONTH_PREFIX+'%')))).scalar_one()
                assert count == 5
    asyncio.run(scenario())


def test_postgres_project_locks_precede_transition_with_two_farms(farm_pg_url):
    async def scenario():
        async with environment(farm_pg_url) as env, player(env) as a, player(env,'telegram') as b:
            async with env.db.transaction() as session:
                unit = Unit(session,env.schema)
                projects = unit.t['projects']
                await unit.execute(projects.update().where(projects.c.id == 'stalls').values(status='done',stage=2,opened_at=env.now[0]))
                await unit.execute(projects.update().where(projects.c.id == 'tavern').values(
                    status='working',stage=0,work_until=env.now[0]+10,speedup=0,fund_speed=0,version=5))
            first_locked,second_attempted = asyncio.Event(),asyncio.Event()
            order = []

            class ObservedUnit(Unit):
                def __init__(self,session,tag):
                    super().__init__(session,env.schema)
                    self.tag,self.projects_locked = tag,False

                async def execute(self,statement,parameters=None):
                    projects = self.t['projects']
                    all_projects = (getattr(statement,'is_select',False)
                        and getattr(statement,'_for_update_arg',None) is not None
                        and not statement._where_criteria
                        and projects in statement.get_final_froms())
                    if all_projects:
                        if self.tag == 'b':
                            second_attempted.set()
                        result = await super().execute(statement,parameters)
                        self.projects_locked = True
                        order.append((self.tag,'all_projects'))
                        if self.tag == 'a':
                            first_locked.set()
                            await asyncio.wait_for(second_attempted.wait(),5)
                        return result
                    if getattr(statement,'is_update',False) and statement.table is projects:
                        assert self.projects_locked, 'A shared transition ran before ordered project locks'
                        order.append((self.tag,'transition'))
                    return await super().execute(statement,parameters)

            async def visit(p,tag,at):
                if tag == 'b':
                    await first_locked.wait()
                async with env.db.transaction() as session:
                    unit = ObservedUnit(session,tag)
                    await unit.execute(sa.text("SET LOCAL lock_timeout = '3s'"))
                    await unit.lock('farm:'+p.farm_id)
                    f = await unit.by_account(p.account_id)
                    await cn.tick_account(unit,f,p.account_id,at)
                    await unit.save(f)

            await asyncio.wait_for(asyncio.gather(
                visit(a,'a',env.now[0]+20),visit(b,'b',env.now[0])),10)
            assert order.index(('a','all_projects')) < order.index(('a','transition')) < order.index(('b','all_projects'))
            async with env.db.transaction() as session:
                unit = Unit(session,env.schema)
                row = (await unit.execute(sa.select(unit.t['projects']).where(unit.t['projects'].c.id == 'tavern'))).mappings().one()
                assert row['stage'] == 1 and row['status'] == 'collecting' and row['version'] == 6
    asyncio.run(scenario())
