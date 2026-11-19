"""Source selection tests for the optional director hook; no DB or network."""
import unittest
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

from domain.night_case_engine import _initialize, step
from domain.night_case_state import rules_snapshot, event_scope, PlayerActor, SystemActor
from domain.night_case_v2_format import compile_v2, load_v2
from application.night_case_director import NightCaseDirectorHook, plan_sources, stable_job_id
from application.night_case import _director_command_summary
from storage.night_ai_models import NightAIBinding, NightAIGameControl, NightAIProfile, NightAIProfileRevision
from storage.night_cases import json_hash


NOW=datetime(2026,11,15,10,tzinfo=timezone.utc)
IDS=[f'00000000-0000-0000-0000-{i:012d}' for i in range(1,5)]
CASE=Path(__file__).parent/'fixtures'/'night_city'/'core_case_v2.json'


def initialized(variant='variant_a'):
    case=compile_v2(load_v2(CASE.read_bytes()))
    rules=rules_snapshot('Europe/Berlin')
    roster={'players':[{'account_id':aid,'display_name':f'Player {i}'} for i,aid in enumerate(IDS)],
            'npc_name_pool':[f'NPC {i}' for i in range(20)]}
    transition=_initialize(case,rules,roster,game_id='testgame',seed=42,
        composition_id='players_04',selected_variant_id=variant,now_utc=NOW)
    ctx=SimpleNamespace(case=case,rules=rules,now=NOW,actor_key=IDS[0],command_summary=None,
                        locked=SimpleNamespace(game=SimpleNamespace(id='testgame')))
    doc=transition.state.document()
    stored={e['event_id']:SimpleNamespace(game_id='testgame',event_id=e['event_id'],
        scope=event_scope(e['audience']),audience_seq=e['audience_seq'],window_idx=e['window_idx'],
        kind=e['kind'],payload=e['payload'],created_at=NOW)
        for e in doc['public']['chronicle']+doc['private_events']}
    return ctx,transition,stored


def command(state,kind,params,command_id):
    doc=state.document();player=next(p for p in doc['players'] if p['account_id']==IDS[0])
    return {'command_id':command_id,'kind':kind,'window_idx':doc['clock']['window_idx'],
            'window_seq':doc['clock']['window_seq'],'actor_seq':player['actor_seq'],'params':params}


def stored_state(transition, *, created_at=NOW):
    doc=transition.state.document()
    return {e['event_id']:SimpleNamespace(game_id='testgame',event_id=e['event_id'],
        scope=event_scope(e['audience']),audience_seq=e['audience_seq'],window_idx=e['window_idx'],
        kind=e['kind'],payload=e['payload'],created_at=created_at)
        for e in doc['public']['chronicle']+doc['private_events']}


class DirectorApplicationTests(unittest.TestCase):
    def test_ghost_cancelled_archive_does_not_abort_next_window_director(self):
        module=CASE.with_name('modules_case_v2.json')
        case=compile_v2(load_v2(module.read_bytes()))
        rules=rules_snapshot('Europe/Berlin')
        roster={'players':[{'account_id':aid,'display_name':f'Player {i}'} for i,aid in enumerate(IDS)],
                'npc_name_pool':[f'NPC {i}' for i in range(20)]}
        current=_initialize(case,rules,roster,game_id='testgame',seed=42,
            composition_id='players_04',selected_variant_id='variant_a',now_utc=NOW)
        def play(t,actor,kind,params=None):
            clock=t.state.clock
            player=next(p for p in t.state.players if p['account_id']==actor)
            now=datetime.fromisoformat((clock['opened_at'] or clock['freeze_at']).replace('Z','+00:00'))
            cmd={'command_id':'ghost'+str(len(t.state.receipts)).zfill(6),'kind':kind,
                 'window_idx':clock['window_idx'],'window_seq':clock['window_seq'],
                 'actor_seq':player['actor_seq'],'params':params or {}}
            return step(case,rules,t.state,PlayerActor(actor),cmd,now_utc=now)
        def tick(t,n):
            due=t.due;clock=t.state.clock
            cmd={'command_id':f'tick{n:04d}','kind':'system.tick','window_seq':clock['window_seq'],
                 'timer_seq':clock['timer_seq'],'params':{'expected_due_at':due['at']}}
            now=datetime.fromisoformat(due['at'].replace('Z','+00:00'))
            return step(case,rules,t.state,SystemActor(),cmd,now_utc=now)
        for n in range(2):
            for actor in IDS: current=play(current,actor,'seen')
            current=tick(current,n)
        current=play(current,IDS[1],'accuse',{'suspect':current.state.players[0]['character_id'],'citations':[]})
        hearing=current.state.hearing['id']
        for actor in IDS: current=play(current,actor,'vote',{'hearing_id':hearing,'choice':'support','citations':[]})
        current=tick(current,4)
        current=play(current,IDS[0],'archive_request',{'query_id':'register_query'})
        current=tick(current,5)
        self.assertEqual(current.state.players[0]['status'],'ghost')
        self.assertEqual(next(e['payload']['disposition'] for e in current.events if e['kind']=='archive_response'),'cancelled')
        for actor in IDS[1:]: current=play(current,actor,'seen')
        current=tick(current,6)
        ctx=SimpleNamespace(case=case,rules=rules,now=datetime.fromisoformat(current.state.clock['opened_at'].replace('Z','+00:00')),
            actor_key='system',command_summary=None,locked=SimpleNamespace(game=SimpleNamespace(id='testgame')))
        plans=plan_sources(ctx,current,stored_state(current,created_at=ctx.now))
        self.assertTrue(any(p.source.kind=='window_digest' for p in plans))
        self.assertFalse(any(p.source.audience_key=='account:'+IDS[0] for p in plans))

    def test_open_second_window_uses_previous_digest_and_current_offer(self):
        ctx,initial,_=initialized()
        due=initial.due
        raw={'command_id':'system0001','kind':'system.tick','window_seq':initial.state.clock['window_seq'],
             'timer_seq':initial.state.clock['timer_seq'],'params':{'expected_due_at':due['at']}}
        now=datetime.fromisoformat(due['at'].replace('Z','+00:00'))
        ticked=step(ctx.case,ctx.rules,initial.state,SystemActor(),raw,now_utc=now)
        ctx.now=now;ctx.actor_key='system'
        selected=plan_sources(ctx,ticked,stored_state(ticked,created_at=now))
        self.assertEqual(sum(p.source.kind=='window_digest' for p in selected),4)
        self.assertEqual(sum(p.source.kind=='story_offer' for p in selected),4)
        self.assertTrue(all((p.source.summarized_window,p.source.action_window)==(1,2) for p in selected))
        self.assertTrue(all(p.context.narrative_job(job_id='j').view.window_idx==2 for p in selected))

    def test_real_talk_receipt_selects_only_npc_current_body(self):
        ctx,initial,_=initialized()
        moved=step(ctx.case,ctx.rules,initial.state,PlayerActor(IDS[0]),
            command(initial.state,'move',{'location':'platform'},'move0001'),now_utc=NOW)
        talk=command(moved.state,'talk',{'dialogue_id':'station_talk','node_id':'opening','option_id':'ask'},'talk0001')
        result=step(ctx.case,ctx.rules,moved.state,PlayerActor(IDS[0]),talk,now_utc=NOW)
        ctx.command_summary=_director_command_summary(ctx.case,talk,result)
        plans=plan_sources(ctx,result,stored_state(result))
        npc=[p for p in plans if p.source.kind=='npc_reply']
        self.assertEqual(len(npc),1)
        self.assertEqual(npc[0].source.cause_id,result.state.receipts[-1]['result_ref']['event_id'])
        role=next(c['title'] for c in ctx.case.document()['characters'] if c['id']=='person_11')
        facts=npc[0].context.narrative_job(job_id='j').view.facts
        self.assertTrue(any(role in f for f in facts))
        self.assertNotIn('Player 0',str(facts))

    def test_command_seam_forwards_only_validated_accepted_talk_target(self):
        ctx,_,_=initialized()
        dialogue=ctx.case.document()['dialogues'][0]
        raw={'kind':'talk','params':{'dialogue_id':dialogue['id'],'text':'RAW_PRIVATE_CANARY'}}
        summary=_director_command_summary(ctx.case,raw,SimpleNamespace(receipt={'accepted':True}))
        self.assertEqual(summary,{'kind':'talk','target_character_id':dialogue['character']})
        self.assertNotIn('RAW_PRIVATE_CANARY',str(summary))
        self.assertIsNone(_director_command_summary(ctx.case,raw,SimpleNamespace(receipt={'accepted':False})))
        self.assertIsNone(_director_command_summary(ctx.case,{'kind':'act','params':raw['params']},
                                                     SimpleNamespace(receipt={'accepted':True})))

    def test_initial_sources_are_own_scoped_and_variant_invariant(self):
        plans=[]
        for variant in ('variant_a','variant_b'):
            ctx,t,stored=initialized(variant)
            selected=plan_sources(ctx,t,stored)
            self.assertEqual(sum(p.source.kind=='window_digest' for p in selected),4)
            self.assertEqual(sum(p.source.kind=='story_offer' for p in selected),4)
            for p in selected:
                self.assertEqual(p.source.action_window,1)
                self.assertEqual(p.source.summarized_window,1)
                self.assertTrue(p.source.audience_key.startswith('account:'))
                self.assertNotIn('variant_b',str(p.context.narrative_job(job_id='j').provider_payload))
            plans.append([(p.source.kind,p.source.audience_key,p.context.input_hash) for p in selected])
        self.assertEqual(plans[0],plans[1])

    def test_missing_or_changed_sql_source_is_corruption_not_optional_fallback(self):
        ctx,t,stored=initialized()
        selected=plan_sources(ctx,t,stored)
        self.assertTrue(selected)
        bad=dict(stored)
        key=next(e['event_id'] for e in t.events if e['kind']=='window_digest')
        bad.pop(key)
        with self.assertRaises(ValueError): plan_sources(ctx,t,bad)
        bad=dict(stored)
        row=bad[key]
        bad[key]=SimpleNamespace(**{**vars(row),'payload':{'window_idx':1,'event_ids':[],'observation_ids':[]}})
        with self.assertRaises(ValueError): plan_sources(ctx,t,bad)

    def test_stable_job_id_is_source_scoped_and_has_no_private_counter(self):
        h='a'*64
        one=stable_job_id('testgame','cause','window_digest','account:'+IDS[0],h)
        self.assertEqual(one,stable_job_id('testgame','cause','window_digest','account:'+IDS[0],h))
        self.assertNotEqual(one,stable_job_id('testgame','cause','window_digest','account:'+IDS[1],h))
        self.assertEqual(len(one),67)


class DirectorHookTests(unittest.IsolatedAsyncioTestCase):
    async def test_readonly_assignment_snapshot_keeps_byok_owner_scope(self):
        class Session:
            def __init__(self, rows): self.rows=rows
            async def scalar(self, query): return self.rows.get(query.column_descriptions[0]['entity'])
        ctx,_,_=initialized()
        binding_id=UUID('00000000-0000-0000-0000-000000000099')
        profile_id=UUID('00000000-0000-0000-0000-000000000098')
        credential_id=UUID('00000000-0000-0000-0000-000000000097')
        config={'credential_id':str(credential_id)}
        config_hash=hashlib.sha256(json.dumps(config,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        config['config_hash']=config_hash
        rows={NightAIGameControl:SimpleNamespace(epoch=1,current_binding_id=binding_id,
                    starter_account_id=UUID(IDS[0])),
              NightAIBinding:SimpleNamespace(id=binding_id,game_id='testgame',epoch=1,status='active',
                    health='ok',valid_until=NOW+timedelta(hours=1),mode='byok',profile_id=profile_id,
                    profile_revision=1,config_hash=config_hash),
              NightAIProfile:SimpleNamespace(id=profile_id,enabled=True,scope='game',game_id='testgame'),
              NightAIProfileRevision:SimpleNamespace(profile_id=profile_id,revision=1,config_hash=config_hash,
                    config=config,credential_id=credential_id)}
        hook=NightCaseDirectorHook(Session(rows),template_hash='b'*64)
        self.assertEqual(await hook._assignment(ctx,'account:'+IDS[0]),(1,binding_id,None))
        self.assertEqual(await hook._assignment(ctx,'public'),(1,binding_id,None))
        self.assertEqual(await hook._assignment(ctx,'account:'+IDS[1]),(1,None,'byok_audience_denied'))
        rows[NightAIProfile].enabled=False
        self.assertEqual(await hook._assignment(ctx,'public'),(1,None,'binding_unavailable'))
        rows.pop(NightAIGameControl)
        self.assertEqual(await hook._assignment(ctx,'public'),(0,None,'authored'))

    async def test_hook_enqueues_immutable_jobs_without_calling_step_or_network(self):
        class Session:
            def __init__(self): self.added=[]
            def add(self,row): self.added.append(row)
            async def flush(self): pass
            async def get(self,model,key,*,populate_existing=False): return None
        ctx,transition,stored=initialized()
        session=Session(); hook=NightCaseDirectorHook(session,template_hash='b'*64)
        hook._events=AsyncMock(return_value=stored)
        hook._count=AsyncMock(return_value=0)
        hook._assignment=AsyncMock(return_value=(0,None,'authored'))
        saved=[]
        async def save(row): saved.append(row);return row
        hook.repo.enqueue_render=save
        before=transition.state.document()
        await hook(ctx,transition)
        self.assertEqual(len(saved),8)
        self.assertEqual(len(session.added),8)
        self.assertTrue(all(row.binding_id is None and row.fallback_reason=='authored' for row in session.added))
        self.assertEqual(before,transition.state.document())
        self.assertEqual(len({row.job_id for row in saved}),8)
        self.assertTrue(all(row.input_hash==json_hash(row.frozen_view) for row in saved))
        # A retained job in the same account/window exhausts its cap on retry.
        hook._count=AsyncMock(return_value=1)
        saved.clear();session.added.clear()
        await hook(ctx,transition)
        self.assertEqual(saved,[])


if __name__=='__main__': unittest.main()
