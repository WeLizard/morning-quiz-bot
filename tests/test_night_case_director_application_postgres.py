"""Director enqueue against real PostgreSQL in one owned, disposable schema."""
import asyncio
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from uuid import UUID, uuid4
from datetime import datetime, timedelta, timezone

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from application.night_case_director import NightCaseDirectorHook
from application.night_case import _director_command_summary
from domain.night_case_engine import _initialize, step
from domain.night_case_state import PlayerActor, SystemActor, event_scope, rules_snapshot
from domain.night_case_v2_format import compile_v2, load_v2
from storage.models import Account, Base, Game, Room, NightEvent, NightRenderJob, NightRendering
from storage.night_ai_models import (NightAICredential, NightAIBinding, NightAIGameControl,
                                     NightAIJobBinding, NightAIProfile, NightAIProfileRevision)
from storage.night_cases import NightCaseRepository, canonical_json
from storage.night_ai_control import AI_CONFIG_LOCK


NOW=datetime(2026,11,16,12,tzinfo=timezone.utc)
CASE=Path(__file__).parent/'fixtures'/'night_city'/'core_case_v2.json'


def migration(revision):
    path=next((Path(__file__).resolve().parents[1]/'alembic/versions').glob('20261116_'+revision+'_*.py'))
    spec=importlib.util.spec_from_file_location('director_migration_'+revision,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


class DirectorPostgresTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from tests.night_case_test_database import night_case_test_url
        url=night_case_test_url()
        if os.getenv('TEST_DATABASE_URL')!=url:
            raise RuntimeError('director PG requires TEST_DATABASE_URL to match the guarded Night Case URL')
        self.schema='mqb_director_'+uuid4().hex
        admin=create_async_engine(url)
        async with admin.begin() as conn: await conn.exec_driver_sql('CREATE SCHEMA '+self.schema)
        await admin.dispose()
        self.engine=create_async_engine(url,connect_args={'server_settings':{'search_path':self.schema}})
        self.addAsyncCleanup(self._cleanup)
        self.sessions=async_sessionmaker(self.engine,expire_on_commit=False)
        async with self.engine.begin() as conn:
            await conn.run_sync(lambda sync:Base.metadata.create_all(sync,tables=[t for t in Base.metadata.sorted_tables if not t.name.startswith('night_ai_')]))
        for revision in ('0049','0050'):
            async with self.engine.begin() as conn:
                def run(sync):
                    with Operations.context(MigrationContext.configure(sync)): migration(revision).upgrade()
                await conn.run_sync(run)
        self.case=compile_v2(load_v2(CASE.read_bytes()))
        self.rules=rules_snapshot('Europe/Berlin')
        self.ids=[uuid4() for _ in range(4)]
        self.game=uuid4().hex
        roster={'players':[{'account_id':str(aid),'display_name':f'Player {i}'} for i,aid in enumerate(self.ids)],
                'npc_name_pool':[f'NPC {i}' for i in range(20)]}
        self.transition=_initialize(self.case,self.rules,roster,game_id=self.game,seed=42,
            composition_id='players_04',selected_variant_id='variant_a',now_utc=NOW)
        async with self.sessions.begin() as s:
            s.add_all([Account(id=aid,display_name=f'Player {i}') for i,aid in enumerate(self.ids)])
            await s.flush()
            s.add(Room(id=self.game,kind='standalone',owner_account_id=self.ids[0]));await s.flush()
            s.add(Game(id=self.game,room_id=self.game,mode='night_case',status='running',phase='investigation',
                       state={'synthetic':'isolated'},started_at=NOW))

    async def _cleanup(self):
        async with self.engine.begin() as conn: await conn.exec_driver_sql('DROP SCHEMA '+self.schema+' CASCADE')
        await self.engine.dispose()

    def context(self,transition,now=NOW,actor_key=None):
        return SimpleNamespace(case=self.case,rules=self.rules,now=now,
            actor_key=actor_key or str(self.ids[0]),command_summary=None,
            locked=SimpleNamespace(game=SimpleNamespace(id=self.game)))

    async def insert_events(self,s,transition,*,now=NOW,omit=None):
        for event in transition.events:
            if event['event_id']==omit: continue
            s.add(NightEvent(game_id=self.game,event_id=event['event_id'],scope=event_scope(event['audience']),
                audience_seq=event['audience_seq'],window_idx=event['window_idx'],kind=event['kind'],
                payload=event['payload'],created_at=now))
        await s.flush()

    async def test_real_sql_enqueue_replay_and_first_write(self):
        async with self.sessions.begin() as s:
            await self.insert_events(s,self.transition)
            await NightCaseDirectorHook(s,template_hash='a'*64)(self.context(self.transition),self.transition)
        async with self.sessions() as s:
            jobs=list((await s.scalars(select(NightRenderJob).where(NightRenderJob.game_id==self.game))).all())
            assignments=list((await s.scalars(select(NightAIJobBinding).where(NightAIJobBinding.game_id==self.game))).all())
            self.assertEqual((len(jobs),len(assignments)),(8,8))
            self.assertTrue(all(a.binding_id is None and a.fallback_reason=='authored' for a in assignments))
            self.assertTrue(all(j.knowledge_revision>0 and hashlib.sha256(canonical_json(j.frozen_view)).hexdigest()==j.input_hash for j in jobs))
            first=jobs[0]
        async with self.sessions.begin() as s:
            await NightCaseRepository(s).commit_rendering(NightRendering(job_id=first.job_id,text='Первый авторский текст',
                source='authored',content_hash=hashlib.sha256('Первый авторский текст'.encode()).hexdigest(),
                references=[],catalog_ids=[],created_at=NOW))
            profile=uuid4();binding=uuid4()
            config={'preset':'openai','credential_id':None}
            digest=hashlib.sha256(canonical_json(config)).hexdigest();config['config_hash']=digest
            s.add(NightAIProfile(id=profile,scope='admin',game_id=None,label='synthetic later approval',
                current_revision=1,enabled=True,is_default=False,created_by_subject='admin:synthetic:operator',created_at=NOW))
            s.add(NightAIProfileRevision(profile_id=profile,revision=1,config=config,config_hash=digest,
                credential_id=None,created_by_subject='admin:synthetic:operator',created_at=NOW))
            await s.flush()
            s.add(NightAIBinding(id=binding,game_id=self.game,epoch=1,mode='admin',profile_id=profile,
                profile_revision=1,config_hash=digest,granted_by_subject='admin:synthetic:operator',
                status='active',valid_until=NOW+timedelta(days=1),caps={},health='ok',created_at=NOW))
            await s.flush()
            s.add(NightAIGameControl(game_id=self.game,starter_account_id=self.ids[0],epoch=1,
                current_binding_id=binding,updated_at=NOW))
            await s.flush()
            await NightCaseDirectorHook(s,template_hash='a'*64)(self.context(self.transition),self.transition)
        async with self.sessions() as s:
            self.assertEqual(await s.scalar(select(text('count(*)')).select_from(NightRenderJob)),8)
            self.assertEqual((await s.get(NightRendering,first.job_id)).text,'Первый авторский текст')
            self.assertEqual(await s.scalar(select(text('count(*)')).select_from(NightAIJobBinding)
                .where(NightAIJobBinding.binding_id==binding)),0)

    async def test_missing_sql_source_fails_without_jobs(self):
        omitted=next(e['event_id'] for e in self.transition.events if e['kind']=='window_digest')
        with self.assertRaisesRegex(ValueError,'director_source_corrupt'):
            async with self.sessions.begin() as s:
                await self.insert_events(s,self.transition,omit=omitted)
                await NightCaseDirectorHook(s,template_hash='a'*64)(self.context(self.transition),self.transition)
        async with self.sessions() as s:
            self.assertEqual(await s.scalar(select(text('count(*)')).select_from(NightRenderJob)),0)

    async def test_foreign_sql_scope_fails_and_stale_source_creates_no_job(self):
        foreign=next(e for e in self.transition.events if e['kind']=='window_digest')
        with self.assertRaisesRegex(ValueError,'director_source_corrupt'):
            async with self.sessions.begin() as s:
                await self.insert_events(s,self.transition,omit=foreign['event_id'])
                s.add(NightEvent(game_id=self.game,event_id=foreign['event_id'],
                    scope='account:'+str(uuid4()),audience_seq=foreign['audience_seq'],
                    window_idx=foreign['window_idx'],kind=foreign['kind'],payload=foreign['payload'],created_at=NOW))
                await s.flush()
                await NightCaseDirectorHook(s,template_hash='a'*64)(self.context(self.transition),self.transition)
        async with self.sessions.begin() as s:
            await self.insert_events(s,self.transition,now=NOW-timedelta(minutes=10))
            await NightCaseDirectorHook(s,template_hash='a'*64)(self.context(self.transition),self.transition)
        async with self.sessions() as s:
            self.assertEqual(await s.scalar(select(text('count(*)')).select_from(NightRenderJob)),0)

    async def test_real_window_two_digest_expiry_and_cap_use_emission_window(self):
        async with self.sessions.begin() as s:
            await self.insert_events(s,self.transition)
            await NightCaseDirectorHook(s,template_hash='a'*64)(self.context(self.transition),self.transition)
        due=self.transition.due
        tick_at=datetime.fromisoformat(due['at'].replace('Z','+00:00'))
        raw={'command_id':'system0001','kind':'system.tick',
            'window_seq':self.transition.state.clock['window_seq'],
            'timer_seq':self.transition.state.clock['timer_seq'],
            'params':{'expected_due_at':due['at']}}
        second=step(self.case,self.rules,self.transition.state,SystemActor(),raw,now_utc=tick_at)
        async with self.sessions.begin() as s:
            await self.insert_events(s,second,now=tick_at)
            hook=NightCaseDirectorHook(s,template_hash='a'*64)
            await hook(self.context(second,now=tick_at,actor_key='system'),second)
        async with self.sessions() as s:
            jobs=list((await s.scalars(select(NightRenderJob).where(NightRenderJob.game_id==self.game))).all())
            self.assertEqual(len(jobs),16)
            emitted=[job for job in jobs if job.frozen_view['action_window']==2]
            self.assertEqual(len(emitted),8)
            self.assertTrue(all(job.frozen_view['summarized_window']==1 for job in emitted))
            self.assertTrue(all(job.expires_at==tick_at+timedelta(minutes=5) for job in emitted))
        async with self.sessions.begin() as s:
            await NightCaseDirectorHook(s,template_hash='a'*64)(self.context(second,now=tick_at,actor_key='system'),second)
        async with self.sessions() as s:
            self.assertEqual(await s.scalar(select(text('count(*)')).select_from(NightRenderJob)),16)

    async def test_board_pinned_observation_is_linked_in_next_digest(self):
        def command(state, actor, kind, params, command_id):
            player=next(p for p in state.players if p['account_id']==actor)
            return {'command_id':command_id,'kind':kind,'window_idx':state.clock['window_idx'],
                'window_seq':state.clock['window_seq'],'actor_seq':player['actor_seq'],'params':params}
        actor=str(self.ids[0]); current=self.transition
        inspect=step(self.case,self.rules,current.state,PlayerActor(actor),
            command(current.state,actor,'act',{'action_id':'inspect_desk'},'inspect01'),now_utc=NOW)
        proof=next(k['observation_id'] for k in inspect.state.knowledge
            if k['account_id']==actor and k['observation_id'].startswith('proof'))
        def tick(t,command_id):
            due=t.due
            at=datetime.fromisoformat(due['at'].replace('Z','+00:00'))
            raw={'command_id':command_id,'kind':'system.tick','window_seq':t.state.clock['window_seq'],
                 'timer_seq':t.state.clock['timer_seq'],'params':{'expected_due_at':due['at']}}
            return step(self.case,self.rules,t.state,SystemActor(),raw,now_utc=at),at
        opened2,at2=tick(inspect,'tick0002')
        pin=step(self.case,self.rules,opened2.state,PlayerActor(actor),
            command(opened2.state,actor,'pin',{'observation_id':proof},'pin00002'),now_utc=at2)
        opened3,at3=tick(pin,'tick0003')
        digest=next(e for e in opened3.events if e['kind']=='window_digest' and e['audience']['ids']==[actor])
        self.assertIn(proof,digest['payload']['observation_ids'])
        async with self.sessions.begin() as s:
            for t,when in ((current,NOW),(inspect,NOW),(opened2,at2),(pin,at2),(opened3,at3)):
                await self.insert_events(s,t,now=when)
            await NightCaseDirectorHook(s,template_hash='a'*64)(self.context(opened3,now=at3,actor_key='system'),opened3)
        async with self.sessions() as s:
            self.assertGreater(await s.scalar(select(text('count(*)')).select_from(NightRenderJob)),0)

    async def test_npc_reply_replay_keeps_original_assignment(self):
        def command(state, kind, params, command_id):
            player=next(p for p in state.players if p['account_id']==str(self.ids[0]))
            return {'command_id':command_id,'kind':kind,'window_idx':state.clock['window_idx'],
                'window_seq':state.clock['window_seq'],'actor_seq':player['actor_seq'],'params':params}
        moved=step(self.case,self.rules,self.transition.state,PlayerActor(str(self.ids[0])),
            command(self.transition.state,'move',{'location':'platform'},'move0001'),now_utc=NOW)
        talk_command=command(moved.state,'talk',{'dialogue_id':'station_talk','node_id':'opening','option_id':'ask'},'talk0001')
        talked=step(self.case,self.rules,moved.state,PlayerActor(str(self.ids[0])),talk_command,now_utc=NOW)
        ctx=self.context(talked)
        ctx.command_summary=_director_command_summary(self.case,talk_command,talked)
        async with self.sessions.begin() as s:
            for t in (self.transition,moved,talked): await self.insert_events(s,t)
            hook=NightCaseDirectorHook(s,template_hash='a'*64)
            await hook(ctx,talked)
        async with self.sessions.begin() as s:
            hook=NightCaseDirectorHook(s,template_hash='a'*64)
            await hook(ctx,talked)
        async with self.sessions() as s:
            jobs=list((await s.scalars(select(NightRenderJob).where(NightRenderJob.game_id==self.game,
                NightRenderJob.kind=='npc_reply'))).all())
            self.assertEqual(len(jobs),1)
            assignments=list((await s.scalars(select(NightAIJobBinding).where(NightAIJobBinding.job_id==jobs[0].job_id))).all())
            self.assertEqual(len(assignments),1)
            self.assertEqual(assignments[0].fallback_reason,'authored')

    async def test_hook_does_not_take_ai_config_advisory_after_game_lock(self):
        async with self.sessions.begin() as holder:
            await holder.execute(text('SELECT pg_advisory_xact_lock(:key)'),{'key':AI_CONFIG_LOCK})
            async def enqueue_while_held():
                async with self.sessions.begin() as s:
                    await self.insert_events(s,self.transition)
                    await NightCaseDirectorHook(s,template_hash='a'*64)(self.context(self.transition),self.transition)
            await asyncio.wait_for(enqueue_while_held(),timeout=3)
        async with self.sessions() as s:
            self.assertEqual(await s.scalar(select(text('count(*)')).select_from(NightRenderJob)),8)

    async def test_byok_assignment_is_owner_private_only(self):
        credential=uuid4();profile=uuid4();binding=uuid4()
        config={'preset':'openrouter','credential_id':str(credential)}
        digest=hashlib.sha256(canonical_json(config)).hexdigest();config['config_hash']=digest
        async with self.sessions.begin() as s:
            s.add(NightAICredential(id=credential,scope='game',owner_subject='account:'+str(self.ids[0]),
                game_id=self.game,preset='openrouter',status='usable',key_id='synthetic',nonce=b'0'*12,
                ciphertext=b'not-a-real-secret!!',aad_version=1,created_at=NOW,
                expires_at=NOW+timedelta(days=1)))
            await s.flush()
            s.add(NightAIProfile(id=profile,scope='game',game_id=self.game,label='synthetic',current_revision=1,
                enabled=True,is_default=False,created_by_subject='account:'+str(self.ids[0]),created_at=NOW))
            s.add(NightAIProfileRevision(profile_id=profile,revision=1,config=config,config_hash=digest,
                credential_id=credential,created_by_subject='account:'+str(self.ids[0]),created_at=NOW))
            await s.flush()
            s.add(NightAIBinding(id=binding,game_id=self.game,epoch=1,mode='byok',profile_id=profile,
                profile_revision=1,config_hash=digest,granted_by_subject='account:'+str(self.ids[0]),
                status='active',valid_until=NOW+timedelta(days=1),caps={},health='ok',created_at=NOW))
            await s.flush()
            s.add(NightAIGameControl(game_id=self.game,starter_account_id=self.ids[0],epoch=1,
                current_binding_id=binding,updated_at=NOW))
            await self.insert_events(s,self.transition)
            hook=NightCaseDirectorHook(s,template_hash='a'*64)
            self.assertEqual(await hook._assignment(self.context(self.transition),'public'),(1,binding,None))
            await hook(self.context(self.transition),self.transition)
        async with self.sessions() as s:
            rows=list((await s.scalars(select(NightAIJobBinding).where(NightAIJobBinding.game_id==self.game))).all())
            jobs={j.job_id:j for j in (await s.scalars(select(NightRenderJob).where(NightRenderJob.game_id==self.game))).all()}
            self.assertEqual(len(rows),8)
            self.assertEqual(sum(a.binding_id==binding for a in rows),2)
            self.assertTrue(all(a.binding_id is None or jobs[a.job_id].audience_key=='account:'+str(self.ids[0]) for a in rows))
        due=self.transition.due
        tick_at=datetime.fromisoformat(due['at'].replace('Z','+00:00'))
        raw={'command_id':'system0001','kind':'system.tick',
            'window_seq':self.transition.state.clock['window_seq'],
            'timer_seq':self.transition.state.clock['timer_seq'],
            'params':{'expected_due_at':due['at']}}
        second=step(self.case,self.rules,self.transition.state,SystemActor(),raw,now_utc=tick_at)
        async with self.sessions.begin() as s:
            profile_row=await s.get(NightAIProfile,profile);profile_row.enabled=False
            await s.flush()
            await self.insert_events(s,second,now=tick_at)
            await NightCaseDirectorHook(s,template_hash='a'*64)(self.context(second,now=tick_at,actor_key='system'),second)
        async with self.sessions() as s:
            rows=list((await s.scalars(select(NightAIJobBinding).where(NightAIJobBinding.game_id==self.game))).all())
            jobs={j.job_id:j for j in (await s.scalars(select(NightRenderJob).where(NightRenderJob.game_id==self.game))).all()}
            self.assertEqual(len(rows),16)
            self.assertEqual(sum(a.binding_id==binding for a in rows),2)
            self.assertTrue(all(a.binding_id is None for a in rows
                if jobs[a.job_id].frozen_view['action_window']==2))
            self.assertTrue(all(a.fallback_reason=='binding_unavailable' for a in rows
                if jobs[a.job_id].frozen_view['action_window']==2
                and jobs[a.job_id].audience_key=='account:'+str(self.ids[0])))


if __name__=='__main__': unittest.main()
