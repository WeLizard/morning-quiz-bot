"""Real A/control/T in owned schemas. No public reset or real provider calls."""
import asyncio
import copy
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import io
import importlib.util
import json
from pathlib import Path
import ssl
import unittest
from uuid import UUID,uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import select,text,update
from sqlalchemy.ext.asyncio import create_async_engine,async_sessionmaker

from application.night_case import FrozenCaseRef,NightCaseApplicationService,NightCaseRegistry,OperatorPrincipal
from application.night_case_ai import AdminPrincipal,BindingCaps,NightAIControlService
from application.night_case_ai_dispatch import AccountPrincipal,WorkerPrincipal,DispatchFlags,NightCaseAIDispatcher,ReservedPermit,DispatchResult,RENDER_TEMPLATE_HASH
from application.night_case_director import NightCaseDirectorHook
from application.night_case_orchestrator import NightCaseOrchestrator,TestOnlyIntentTransport
from config.night_case_ai import EndpointPolicy,ModelCapabilities,ProfileRegistry
from domain.night_case_format import canonical_content_hash
from infrastructure.night_ai_gateway import NightAIGateway,OperatorPolicy
from storage.database import Database,DatabaseSettings
from storage.models import Account,Base,Game,GamePlayer,GuestSession,NightGameSealed,NightIntentProposal,NightRenderJob,NightRendering,Room,RoomMembership
from storage.night_ai import KeyRing,SecretVault,ReceiptFingerprinter
from storage.night_ai_dispatch import DispatchSource
from storage.night_cases import json_hash
from storage.night_ai_models import NightAIBinding,NightAIRequest,NightAIDispatchAttempt,NightAIIntentRequest,NightAIGameControl,NightAICredential
from tests import test_night_case_application as app_base
from tests.test_night_ai_gateway_policy import FakeStream


class ModelStream(FakeStream):
    def __init__(self,backend,peer):
        super().__init__(b'',peer);self.backend=backend;self.built=False
    async def read(self,max_bytes,timeout=None):
        self.backend.entered.set()
        if self.backend.release is not None:await self.backend.release.wait()
        if not self.built:
            raw=b''.join(self.writes);headers,_,body=raw.partition(b'\r\n\r\n')
            if headers.startswith(b'POST /api/v2/oauth '):
                self.backend.oauth_calls+=1
                if self.backend.after_oauth is not None:self.backend.after_oauth()
                response=json.dumps({'access_token':'synthetic-access-'+str(self.backend.oauth_calls),
                    'expires_at':int((self.backend.now()+timedelta(minutes=30)).timestamp()*1000)}).encode()
                self.response=b'HTTP/1.1 '+str(self.backend.oauth_status).encode()+b' Synthetic\r\nContent-Length: '+str(len(response)).encode()+b'\r\n\r\n'+response
                self.built=True
                return await super().read(max_bytes,timeout)
            if b'transfer-encoding: chunked' in headers.lower():
                source=io.BytesIO(body);parts=[]
                while True:
                    size=int(source.readline().strip(),16)
                    if not size:break
                    parts.append(source.read(size));source.read(2)
                body=b''.join(parts)
            request=json.loads(body);payload=json.loads(next(m['content'] for m in request['messages'] if m['role']=='user'))
            self.backend.payloads.append(payload)
            if payload['kind']=='intent_selection':
                selected=next((x for x in payload['choices'] if x['kind']=='seen'),payload['choices'][0])
                result={'request_token':payload['request_token'],'kind':'intent_selection','selection_id':selected['selection_id']}
            else:result={'request_token':payload['request_token'],'kind':payload['kind'],'text':'Художественная связка.',
                'references':payload['references'],'catalog_ids':payload['catalog_ids'][:1] if payload['kind']=='story_offer' else []}
            response=json.dumps({'choices':[{'message':{'content':json.dumps(result,ensure_ascii=False)},'finish_reason':'stop'}],
                'usage':{'prompt_tokens':12,'completion_tokens':24}},ensure_ascii=False).encode()
            status=self.backend.inference_statuses.pop(0) if self.backend.inference_statuses else self.backend.status
            self.response=b'HTTP/1.1 '+str(status).encode()+b' Synthetic\r\nContent-Length: '+str(len(response)).encode()+b'\r\n\r\n'+response
            self.built=True
        return await super().read(max_bytes,timeout)


class ModelBackend:
    def __init__(self,db):
        self.db=db;self.payloads=[];self.calls=[];self.streams=[];self.status=200
        self.entered=asyncio.Event();self.release=None;self.contexts=0
        self.oauth_calls=0;self.oauth_status=200;self.inference_statuses=[];self.now=lambda:datetime.now(timezone.utc);self.after_oauth=None
    async def connect_tcp(self,**kwargs):
        assert self.contexts==0,'authenticated principal context survived network await'
        assert self.db.engine.pool.checkedout()==0,'SQL connection survived network await'
        self.calls.append(kwargs);stream=ModelStream(self,(kwargs['host'],kwargs['port']));self.streams.append(stream);return stream


def migration(revision):
    path=next((Path(__file__).resolve().parents[1]/'alembic/versions').glob('*_'+revision+'_*.py'))
    spec=importlib.util.spec_from_file_location('dispatch_app_migration_'+revision,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


class DispatchApplicationPostgresTests(unittest.IsolatedAsyncioTestCase):
    lobby_command=app_base.NightApplicationPostgresTests.lobby_command
    lobby=app_base.NightApplicationPostgresTests.lobby
    ready_lobby=app_base.NightApplicationPostgresTests.ready_lobby
    player_command=app_base.NightApplicationPostgresTests.player_command

    async def asyncSetUp(self):
        from tests.night_case_test_database import night_case_test_url
        url=night_case_test_url()
        self.schema='mqb_tapp_'+uuid4().hex;self.db=Database(DatabaseSettings(url))
        async with self.db.engine.begin() as c:await c.exec_driver_sql('CREATE SCHEMA '+self.schema)
        await self.db.engine.dispose()
        self.db.engine=create_async_engine(url,connect_args={'server_settings':{'search_path':self.schema}})
        self.db.session_factory=async_sessionmaker(self.db.engine,expire_on_commit=False,autoflush=False)
        self.addAsyncCleanup(self.cleanup)
        # AccountMerge registers the real host Farm tables lazily. Register
        # before schema creation, exactly as the accepted merge fixture does.
        from qw_farm.integration import register_models
        register_models()
        async with self.db.engine.begin() as c:
            await c.run_sync(lambda sync:Base.metadata.create_all(sync,tables=[t for t in Base.metadata.sorted_tables if not t.name.startswith('night_ai_')]))
            def guards(sync):
                with Operations.context(MigrationContext.configure(sync)):
                    migration('0045').install_guards();migration('0047').upgrade()
                    migration('0049').upgrade();migration('0050').upgrade()
            await c.run_sync(guards)
        self.now=datetime.now(timezone.utc);self.accounts=[uuid4() for _ in range(5)];self.owner=self.accounts[0];self.room=uuid4().hex
        self.doc=json.loads((Path(__file__).parent/'fixtures/night_city/runtime_case_v2.json').read_text(encoding='utf8'))
        self.doc['meta']['id']='tapp_'+uuid4().hex[:24]
        for i,character in enumerate(self.doc['characters']):
            for secret in character['secrets']:secret['body']['text']='PRIVATE_CANARY_'+str(i)
        self.ref=FrozenCaseRef(self.doc['meta']['id'],self.doc['meta']['version'],canonical_content_hash(self.doc))
        self.registry=NightCaseRegistry(frozenset({self.ref}),frozenset({'Europe/Berlin'}),b'night-test-cursor-secret-32-bytes!!')
        self.admin=AdminPrincipal('test-'+uuid4().hex)
        self.operator=OperatorPrincipal('synthetic',self.owner)
        self.settings={'preset':'openai','model_id':'synthetic-model'}
        self.ai_registry=ProfileRegistry.cloud({('openai','synthetic-model'):ModelCapabilities(),('gigachat','synthetic-giga'):ModelCapabilities()})
        self.vault=SecretVault(KeyRing('synthetic',{'synthetic':b'v'*32}))
        self.receipts=ReceiptFingerprinter(KeyRing('stable',{'stable':b'h'*32}))
        self.flags=DispatchFlags(True,True);self.narrate=False
        async with self.db.transaction() as s:
            s.add_all(Account(id=a,display_name='Synthetic '+str(i)) for i,a in enumerate(self.accounts));await s.flush()
            s.add(Room(id=self.room,kind='standalone',owner_account_id=self.owner));await s.flush()
            s.add_all(RoomMembership(room_id=self.room,account_id=a,role='owner' if a==self.owner else 'member') for a in self.accounts);await s.flush()
            await self.service(s).register_case(operator=OperatorPrincipal('synthetic',self.owner),content=self.doc,
                validation_report={'scope':'synthetic','publication':'not_checked'},admission='rehearsal')
        self.backend=ModelBackend(self.db)
        self.backend.now=lambda:self.now
        async def resolver(host,port):return ('8.8.8.8',)
        policies=[OperatorPolicy(self.ai_registry.policies[(name,1)],(),ssl.create_default_context()) for name in ('cloud:openai','cloud:gigachat')]
        policies.append(OperatorPolicy(EndpointPolicy('giga-oauth',1,'https://ngw.devices.sberbank.ru:9443','cloud',None),(),ssl.create_default_context()))
        gateway=NightAIGateway(policies,
            enabled=True,external_allowed=True,resolver=resolver,backend=self.backend,utcnow=lambda:self.now)
        self.dispatcher=NightCaseAIDispatcher(self.db,self.service,self.ai,gateway=gateway,flags=lambda:self.flags,clock=lambda:self.now)

    async def cleanup(self):
        async with self.db.engine.begin() as c:await c.exec_driver_sql('DROP SCHEMA '+self.schema+' CASCADE')
        await self.db.dispose()

    def service(self,s):
        hook=NightCaseDirectorHook(s,template_hash=RENDER_TEMPLATE_HASH) if self.narrate else None
        if hook is not None and getattr(self,'forge_npc',False):
            original=hook.repo.enqueue_render
            async def forge(row):
                if row.kind=='npc_reply':
                    # A malicious storage caller can rehash internally valid
                    # context. It still cannot assert the canonical NPC speaker.
                    from domain.night_case_director import _facts_for,AuthorizedSource,FrozenContext
                    d=copy.deepcopy(row.frozen_view)
                    if self.forge_npc=='reference':
                        reference=next(r for r in d['reference_map'] if r['kind']=='observation')
                        reference['source_id']='public_note'
                    else:
                        for block in d['exact_blocks']:
                            if block['kind']=='result':block['speaker_title']='FORGED_PRIVATE_SPEAKER'
                    d['narrative']['facts']=list(_facts_for(row.kind,d['action_window'],d['summarized_window'],d['exact_blocks'],d['offers']))
                    raw=copy.deepcopy(d);raw.pop('context_hash');raw['narrative'].pop('knowledge_revision')
                    d['context_hash']=d['narrative']['knowledge_revision']=json_hash(raw)
                    source=AuthorizedSource(row.kind,row.cause_id,row.audience_key,d['action_window'],None,(row.cause_id,),
                        tuple(r['source_id'] for r in d['reference_map'] if r['kind']=='observation'),
                        next(b['body'] for b in d['exact_blocks'] if b['reference']=='r01'),
                        next(b['speaker_title'] for b in d['exact_blocks'] if b['reference']=='r01'))
                    FrozenContext.from_document(d,input_hash=json_hash(d),source=source)
                    row.frozen_view,row.input_hash=d,json_hash(d)
                return await original(row)
            hook.repo.enqueue_render=forge
        return NightCaseApplicationService(s,lambda:self.now,self.registry,transition_hook=hook)

    def ai(self,s):
        return NightAIControlService(s,lambda:self.now,self.ai_registry,self.vault,self.receipts,
            environment_id='dispatch-synthetic',original_starter_resolver=self.service(s).prove_original_starter)

    async def start(self,*,byok=False):
        game,_,command=await self.ready_lobby()
        await NightCaseOrchestrator(self.db,self.service,self.ai).start_game(account_id=self.owner,game_id=game,command=command)
        async with self.db.transaction() as s:
            if byok:
                grant=await self.ai(s).stage_or_activate_byok(account_id=self.owner,game_id=game,expected_epoch=1,
                    settings={'preset':'openai','model_id':'synthetic-model','adapter':'openai_chat'},secret=b'synthetic-key',client_request_id=uuid4().hex)
                binding=UUID(grant['result']['binding_id'])
            else:
                profile=await self.ai(s).save_profile_revision(operator=self.admin,profile_id=None,expected_revision=0,
                    label='Synthetic',settings=getattr(self,'profile_settings',{'preset':'openai','model_id':'synthetic-model','adapter':'openai_chat'}),secret=b'synthetic-key',client_request_id=uuid4().hex)
                pid=UUID(profile['result']['profile_id'])
                await self.ai(s).set_profile_enabled(operator=self.admin,profile_id=pid,enabled=True,client_request_id=uuid4().hex)
                request=await s.scalar(select(NightAIRequest).where(NightAIRequest.game_id==game,NightAIRequest.status=='pending'))
                granted=await self.ai(s).decide_request(operator=self.admin,request_id=request.id,decision='approve',profile_id=pid,profile_revision=1,caps=getattr(self,'profile_caps',None),client_request_id=uuid4().hex)
                binding=UUID(granted['result']['binding_id'])
        return game,binding

    async def prepare(self,game,actor=None):
        orchestration=NightCaseOrchestrator(self.db,self.service,self.ai,TestOnlyIntentTransport(lambda payload:None))
        return await orchestration.prepare_intent(account_id=actor or self.owner,game_id=game,request_id=uuid4().hex,text='Осмотреться')

    async def play(self,game,actor,kind,params=None):
        command=await self.player_command(game,actor,kind,params)
        async with self.db.transaction() as s:
            result=await self.service(s).execute(account_id=actor,game_id=game,command=command)
        self.assertTrue(result['receipt']['accepted'],result['receipt']);return result

    async def open_route(self,game):
        for actor,action,proof in ((self.owner,'inspect_key','proof_common'),(self.accounts[1],'inspect_mechanism','proof_mechanism')):
            await self.play(game,actor,'act',{'action_id':action})
            await self.play(game,actor,'pin',{'observation_id':proof})

    async def npc_job(self,game):
        await self.open_route(game);actor=self.accounts[2]
        async with self.db.transaction() as s:
            state=(await s.get(NightGameSealed,game)).kernel
            location=next(n['location'] for n in state['npcs'] if n['character_id']=='missing_keeper')
        for place in (('platform','office') if location=='office' else ('yard',)):
            await self.play(game,actor,'move',{'location':place})
        await self.play(game,actor,'act',{'action_id':'search_office' if location=='office' else 'search_yard'})
        await self.next_window(game)
        await self.play(game,actor,'talk',{'dialogue_id':'keeper_dialogue','node_id':'keeper_entry','option_id':'keeper_question'})
        async with self.db.transaction() as s:
            job=await s.scalar(select(NightRenderJob).where(NightRenderJob.game_id==game,NightRenderJob.kind=='npc_reply',
                NightRenderJob.audience_key=='account:'+str(actor)))
            self.assertIsNotNone(job);return job

    async def test_canonical_scene_and_npc_talk_proof_exclude_private_canaries(self):
        game,_=await self.start();self.narrate=True
        npc=await self.npc_job(game)
        # The scene was emitted only by the two legally published proofs.
        async with self.db.transaction() as s:
            scene=await s.scalar(select(NightRenderJob).where(NightRenderJob.game_id==game,NightRenderJob.kind=='scene_narration'))
            self.assertIsNotNone(scene)
        # Current-window NPC uses accepted SQL talk receipt and pinned role.
        result=await self.dispatcher.dispatch(DispatchSource('render',npc.job_id),actor=WorkerPrincipal('render:test'),worker_id='render:test')
        self.assertEqual(result.result['rendering']['source'],'ai')
        self.assertNotIn('PRIVATE_CANARY_',json.dumps(self.backend.payloads,ensure_ascii=False))
        self.assertNotIn('FORGED_PRIVATE_SPEAKER',json.dumps(self.backend.payloads,ensure_ascii=False))

    async def test_scene_dispatch_comes_from_legal_published_proofs(self):
        game,_=await self.start();self.narrate=True;await self.open_route(game)
        async with self.db.transaction() as s:
            job=await s.scalar(select(NightRenderJob).where(NightRenderJob.game_id==game,NightRenderJob.kind=='scene_narration'))
            self.assertIsNotNone(job)
        result=await self.dispatcher.dispatch(DispatchSource('render',job.job_id),actor=WorkerPrincipal('render:test'),worker_id='render:test')
        self.assertEqual(result.result['rendering']['source'],'ai')
        self.assertNotIn('PRIVATE_CANARY_',json.dumps(self.backend.payloads,ensure_ascii=False))

    async def test_rehashed_forged_npc_speaker_falls_back_before_network(self):
        game,_=await self.start();self.narrate=True;self.forge_npc=True
        npc=await self.npc_job(game)
        result=await self.dispatcher.dispatch(DispatchSource('render',npc.job_id),actor=WorkerPrincipal('render:test'),worker_id='render:test')
        self.assertEqual(result.result['rendering']['source'],'authored');self.assertEqual(self.backend.calls,[])
        async with self.db.transaction() as s:
            self.assertEqual(await s.scalar(select(text('count(*)')).select_from(NightAIDispatchAttempt)),0)

    async def test_rehashed_foreign_observation_reference_cannot_assert_npc_knowledge(self):
        game,_=await self.start();self.narrate=True;self.forge_npc='reference'
        npc=await self.npc_job(game)
        result=await self.dispatcher.dispatch(DispatchSource('render',npc.job_id),actor=WorkerPrincipal('render:test'),worker_id='render:test')
        self.assertEqual(result.result['rendering']['source'],'authored');self.assertEqual(self.backend.calls,[])

    async def test_story_offer_aliases_remain_historical_after_quote_becomes_stale(self):
        game,_=await self.start();self.narrate=True;await self.next_window(game)
        async with self.db.transaction() as s:
            job=await s.scalar(select(NightRenderJob).where(NightRenderJob.game_id==game,NightRenderJob.kind=='story_offer',
                NightRenderJob.audience_key=='account:'+str(self.owner)))
            self.assertIsNotNone(job);frozen=job.frozen_view
        offer=frozen['offers'][0]
        params=json.loads(offer['params'])
        await self.play(game,self.owner,offer['kind'],params)
        result=await self.dispatcher.dispatch(DispatchSource('render',job.job_id),actor=WorkerPrincipal('render:test'),worker_id='render:test')
        self.assertEqual(result.result['rendering']['source'],'ai')
        self.assertTrue(set(result.result['rendering']['catalog_ids'])<={o['alias'] for o in frozen['offers']})
        async with self.db.transaction() as s:
            self.assertEqual((await s.get(NightRenderJob,job.job_id)).frozen_view,frozen)
            menu=await self.service(s).get_view(account_id=self.owner,game_id=game)
            self.assertNotIn(offer['selection_id'],json.dumps(menu['menu']))

    async def test_giga_cache_401_refresh_is_new_attempt_new_quota_and_one_shared_budget(self):
        self.profile_settings={'preset':'gigachat','model_id':'synthetic-giga','adapter':'gigachat_chat',
            'project_fields':{'scope':'GIGACHAT_API_PERS'}}
        game,_=await self.start();work=await self.prepare(game);source=DispatchSource('intent',work.id)
        self.backend.inference_statuses=[401,200]
        first=await self.dispatcher.dispatch(source,actor=AccountPrincipal(self.owner),worker_id='intent:test')
        self.assertEqual(first.status,'deferred');self.assertEqual(self.backend.oauth_calls,1)
        self.assertEqual(len(self.backend.calls),2)
        self.now=first.retry_after
        second=await self.dispatcher.dispatch(source,actor=AccountPrincipal(self.owner),worker_id='intent:test')
        self.assertEqual(second.result['kind'],'proposal');self.assertEqual(self.backend.oauth_calls,2)
        self.assertEqual(len(self.backend.calls),4)
        other=await self.prepare(game)
        cached=await self.dispatcher.dispatch(DispatchSource('intent',other.id),actor=AccountPrincipal(self.owner),worker_id='intent:test')
        self.assertEqual(cached.result['kind'],'proposal');self.assertEqual(self.backend.oauth_calls,2)
        self.assertEqual(len(self.backend.calls),5)
        async with self.db.transaction() as s:
            rows=list((await s.scalars(select(NightAIDispatchAttempt).where(NightAIDispatchAttempt.intent_id==work.id)
                .order_by(NightAIDispatchAttempt.attempt_no))).all())
            self.assertEqual([r.status for r in rows],['failed','succeeded'])
            self.assertEqual([r.attempt_no for r in rows],[1,2])
            self.assertTrue(all(r.network_deadline-r.reserved_at==timedelta(seconds=12) for r in rows))
            self.assertTrue(all(r.oauth_claimed_at is not None and r.sent_at is not None for r in rows))

    async def test_oauth_consumes_original_budget_and_cannot_give_inference_another_twelve_seconds(self):
        self.profile_settings={'preset':'gigachat','model_id':'synthetic-giga','adapter':'gigachat_chat',
            'project_fields':{'scope':'GIGACHAT_API_PERS'}}
        mono=[100.];self.dispatcher.monotonic=lambda:mono[0];self.dispatcher.gateway.monotonic=lambda:mono[0]
        def consume():mono[0]+=11.5;self.now+=timedelta(seconds=11.5)
        self.backend.after_oauth=consume
        game,_=await self.start();work=await self.prepare(game)
        result=await self.dispatcher.dispatch(DispatchSource('intent',work.id),actor=AccountPrincipal(self.owner),worker_id='intent:test')
        self.assertEqual(result.result['kind'],'clarification');self.assertEqual(self.backend.oauth_calls,1)
        self.assertEqual(len(self.backend.calls),1)
        async with self.db.transaction() as s:
            attempt=await s.scalar(select(NightAIDispatchAttempt))
            self.assertIsNone(attempt.sent_at);self.assertEqual(attempt.network_deadline-attempt.reserved_at,timedelta(seconds=12))

    async def test_expired_oauth_cache_and_oauth_401_never_retry_or_send_inference(self):
        self.profile_settings={'preset':'gigachat','model_id':'synthetic-giga','adapter':'gigachat_chat',
            'project_fields':{'scope':'GIGACHAT_API_PERS'}}
        game,binding=await self.start();work=await self.prepare(game)
        result=await self.dispatcher.dispatch(DispatchSource('intent',work.id),actor=AccountPrincipal(self.owner),worker_id='intent:test')
        self.assertEqual(result.result['kind'],'proposal');self.assertEqual(len(self.backend.calls),2)
        self.now+=timedelta(minutes=31);self.backend.oauth_status=401
        other=await self.prepare(game)
        failed=await self.dispatcher.dispatch(DispatchSource('intent',other.id),actor=AccountPrincipal(self.owner),worker_id='intent:test')
        self.assertEqual(failed.result['kind'],'clarification');self.assertEqual(self.backend.oauth_calls,2)
        self.assertEqual(len(self.backend.calls),3)
        async with self.db.transaction() as s:
            row=await s.scalar(select(NightAIDispatchAttempt).where(NightAIDispatchAttempt.intent_id==other.id))
            self.assertEqual(row.status,'failed');self.assertEqual(row.error_code,'auth_error')
            self.assertIsNone(row.sent_at);self.assertIsNone(row.retry_after)
            self.assertEqual((await s.get(NightAIBinding,binding)).health,'auth_error')

    async def test_actor_minute_boundary_and_game_total_quota_survive_new_sources(self):
        game,_=await self.start()
        for _ in range(4):
            work=await self.prepare(game)
            result=await self.dispatcher.dispatch(DispatchSource('intent',work.id),actor=AccountPrincipal(self.owner),worker_id='intent:test')
            self.assertEqual(result.result['kind'],'proposal')
        denied=await self.prepare(game)
        result=await self.dispatcher.dispatch(DispatchSource('intent',denied.id),actor=AccountPrincipal(self.owner),worker_id='intent:test')
        self.assertEqual(result.result['kind'],'clarification');self.assertEqual(len(self.backend.calls),4)
        self.now=self.now.replace(second=0,microsecond=0)+timedelta(minutes=1)
        work=await self.prepare(game)
        result=await self.dispatcher.dispatch(DispatchSource('intent',work.id),actor=AccountPrincipal(self.owner),worker_id='intent:test')
        self.assertEqual(result.result['kind'],'proposal');self.assertEqual(len(self.backend.calls),5)
        from storage.models import NightNarratorLimit
        from application.night_case_ai_dispatch import EPOCH
        async with self.db.transaction() as s:
            total=await s.get(NightNarratorLimit,('game:'+game+':total',EPOCH))
            self.assertEqual(total.reserved_requests,5)

    async def test_global_minute_limit_is_shared_by_independent_actor_sources(self):
        game,_=await self.start()
        for actor in [self.owner]*4+[self.accounts[1]]*4+[self.accounts[2]]*2:
            work=await self.prepare(game,actor)
            result=await self.dispatcher.dispatch(DispatchSource('intent',work.id),actor=AccountPrincipal(actor),worker_id='intent:test')
            self.assertEqual(result.result['kind'],'proposal')
        work=await self.prepare(game,self.accounts[2])
        result=await self.dispatcher.dispatch(DispatchSource('intent',work.id),actor=AccountPrincipal(self.accounts[2]),worker_id='intent:test')
        self.assertEqual(result.result['kind'],'clarification');self.assertEqual(len(self.backend.calls),10)
        async with self.db.transaction() as s:
            self.assertEqual(await s.scalar(select(text('count(*)')).select_from(NightAIDispatchAttempt)),10)

    async def test_intent_and_render_workers_share_one_union_slot_and_debit(self):
        game,binding=await self.start();self.narrate=True;await self.next_window(game)
        work=await self.prepare(game)
        async with self.db.transaction() as s:
            job=await s.scalar(select(NightRenderJob).where(NightRenderJob.kind=='window_digest',NightRenderJob.audience_key=='account:'+str(self.owner)))
        sources=[DispatchSource('intent',work.id),DispatchSource('render',job.job_id)]
        actors=[AccountPrincipal(self.owner),WorkerPrincipal('render:test')];workers=['intent:test','render:test']
        results=await asyncio.gather(*(self.dispatcher.reserve(source,actor=actor,worker_id=worker)
            for source,actor,worker in zip(sources,actors,workers)))
        self.assertCountEqual([type(r) for r in results],[ReservedPermit,DispatchResult])
        winner=next(i for i,r in enumerate(results) if type(r) is ReservedPermit)
        ticket=await self.dispatcher.authorize_inference(results[winner],actor=actors[winner],worker_id=workers[winner])
        outcome=await self.dispatcher.gateway.exchange(ticket)
        await self.dispatcher.complete(results[winner],actor=actors[winner],worker_id=workers[winner],outcome=outcome)
        async with self.db.transaction() as s:
            self.assertEqual(await s.scalar(select(text('count(*)')).select_from(NightAIDispatchAttempt)),1)
            self.assertIsNone((await s.get(NightAIBinding,binding)).inflight_permit_id)

    async def test_byok_public_and_exact_owner_private_render_only(self):
        game,_=await self.start(byok=True);self.narrate=True;await self.open_route(game)
        async with self.db.transaction() as s:
            scene=await s.scalar(select(NightRenderJob).where(NightRenderJob.game_id==game,NightRenderJob.kind=='scene_narration'))
        result=await self.dispatcher.dispatch(DispatchSource('render',scene.job_id),actor=WorkerPrincipal('render:test'),worker_id='render:test')
        self.assertEqual(result.result['rendering']['source'],'ai')
        await self.next_window(game)
        for account,expected in ((self.owner,'ai'),(self.accounts[1],'authored')):
            async with self.db.transaction() as s:
                job=await s.scalar(select(NightRenderJob).where(NightRenderJob.game_id==game,NightRenderJob.kind=='window_digest',
                    NightRenderJob.audience_key=='account:'+str(account)))
            result=await self.dispatcher.dispatch(DispatchSource('render',job.job_id),actor=WorkerPrincipal('render:test'),worker_id='render:test')
            self.assertEqual(result.result['rendering']['source'],expected)
        self.assertEqual(len(self.backend.calls),2)
        self.assertNotIn('PRIVATE_CANARY_',json.dumps(self.backend.payloads,ensure_ascii=False))

    async def test_five_committed_failures_open_circuit_and_expiry_allows_one_new_reserve(self):
        game,_=await self.start();self.backend.status=503
        for actor in [self.owner,self.owner,self.accounts[1],self.accounts[1],self.accounts[2]]:
            work=await self.prepare(game,actor)
            result=await self.dispatcher.dispatch(DispatchSource('intent',work.id),actor=AccountPrincipal(actor),worker_id='intent:test')
            self.assertEqual(result.status,'deferred')
        blocked=await self.prepare(game,self.accounts[2])
        result=await self.dispatcher.dispatch(DispatchSource('intent',blocked.id),actor=AccountPrincipal(self.accounts[2]),worker_id='intent:test')
        self.assertEqual(result.result['kind'],'clarification');self.assertEqual(len(self.backend.calls),5)
        self.now+=timedelta(minutes=5,seconds=1);self.backend.status=200
        work=await self.prepare(game)
        result=await self.dispatcher.dispatch(DispatchSource('intent',work.id),actor=AccountPrincipal(self.owner),worker_id='intent:test')
        self.assertEqual(result.result['kind'],'proposal');self.assertEqual(len(self.backend.calls),6)
        from storage.models import NightNarratorLimit
        async with self.db.transaction() as s:
            counter=await s.scalar(select(NightNarratorLimit).where(NightNarratorLimit.scope.like('nai:circuit:%')))
            self.assertEqual(counter.failures,0);self.assertIsNone(counter.circuit_open_until)

    async def test_day_boundary_rebind_does_not_reset_game_total_cap(self):
        self.now=self.now.replace(hour=23,minute=59,second=30,microsecond=0)
        self.profile_caps=BindingCaps(requests_per_day=2,total_requests=3).document()
        game,binding=await self.start()
        async def dispatch():
            work=await self.prepare(game)
            return await self.dispatcher.dispatch(DispatchSource('intent',work.id),actor=AccountPrincipal(self.owner),worker_id='intent:test')
        for _ in range(2):self.assertEqual((await dispatch()).result['kind'],'proposal')
        self.assertEqual((await dispatch()).result['kind'],'clarification');self.assertEqual(len(self.backend.calls),2)
        self.now+=timedelta(minutes=6)
        async with self.db.transaction() as s:
            old=await s.get(NightAIBinding,binding);profile_id=old.profile_id
            request=await self.ai(s).request_admin(account_id=self.owner,game_id=game,expected_epoch=1,client_request_id=uuid4().hex)
            await self.ai(s).decide_request(operator=self.admin,request_id=UUID(request['result']['request_id']),decision='approve',
                profile_id=profile_id,profile_revision=1,caps=self.profile_caps,client_request_id=uuid4().hex)
        self.assertEqual((await dispatch()).result['kind'],'proposal')
        self.assertEqual((await dispatch()).result['kind'],'clarification');self.assertEqual(len(self.backend.calls),3)

    async def test_staged_only_moderation_erases_key_without_starting_or_interrupting_lobby(self):
        from storage.admin_actions import AdminActions,AdminConflict
        game,_,_=await self.ready_lobby()
        async with self.db.transaction() as s:
            staged=await self.ai(s).stage_or_activate_byok(account_id=self.owner,game_id=game,expected_epoch=0,
                settings=self.settings,secret=b'synthetic-staged-only',client_request_id=uuid4().hex)
            ident=UUID(staged['result']['staged_credential_id'])
        admin=AdminActions(self.db)
        with self.assertRaises(AdminConflict):
            await admin.moderate_account(self.owner,operator_id='synthetic',action_id=uuid4().hex,expected_revision=12,reason='test',archived=True)
        async with self.db.transaction() as s:self.assertEqual((await s.get(NightAICredential,ident)).status,'staged')
        with self.assertRaises(AdminConflict):
            await admin.moderate_account(self.owner,operator_id='synthetic',action_id=uuid4().hex,expected_revision=0,reason='test',archived=True)
        async with self.db.transaction() as s:self.assertEqual((await s.get(NightAICredential,ident)).status,'staged')
        await admin.moderate_account(self.owner,operator_id='synthetic',action_id=uuid4().hex,expected_revision=0,reason='test',blocked=True)
        await admin.moderate_account(self.owner,operator_id='synthetic',action_id=uuid4().hex,expected_revision=1,reason='test',archived=True)
        async with self.db.transaction() as s:
            key=await s.get(NightAICredential,ident)
            self.assertEqual(key.status,'erased');self.assertIsNone(key.ciphertext)
            self.assertEqual((await s.get(NightGameSealed,game)).lifecycle,'lobby')
            self.assertIsNone((await s.get(Game,game)).started_at)

    async def late_result(self,change,*,before_prepare=None,denied=False):
        game,binding=await self.start()
        if before_prepare is not None:await before_prepare(game)
        work=await self.prepare(game)
        self.backend.release=asyncio.Event()
        task=asyncio.create_task(self.dispatcher.dispatch(DispatchSource('intent',work.id),actor=AccountPrincipal(self.owner),worker_id='intent:test'))
        try:
            await asyncio.wait_for(self.backend.entered.wait(),2)
            await change(game,binding)
            async with self.db.transaction() as s:before=(await s.get(NightGameSealed,game)).kernel
        finally:self.backend.release.set()
        if denied:
            from application.night_case import NightCaseError
            with self.assertRaises(NightCaseError):await task
        else:
            result=await task;self.assertEqual(result.result['kind'],'clarification')
        async with self.db.transaction() as s:
            self.assertEqual((await s.get(NightGameSealed,game)).kernel,before)
            self.assertEqual(await s.scalar(select(text('count(*)')).select_from(NightIntentProposal)),0)
        return game

    async def test_late_interrupted_result_cannot_create_proposal(self):
        async def change(game,binding):
            from storage.admin_actions import operation_fence
            from storage.games import GameRepository
            async with self.db.transaction() as s:
                await operation_fence(s,exclusive=True)
                await GameRepository(s).interrupt(await s.get(Game,game),event_kind='synthetic-test')
        await self.late_result(change)

    async def test_late_starter_departure_result_cannot_create_proposal(self):
        async def change(game,binding):await self.play(game,self.owner,'forfeit')
        await self.late_result(change)

    async def test_late_terminal_result_cannot_create_proposal(self):
        async def change(game,binding):
            for actor in self.accounts[:4]:await self.play(game,actor,'forfeit')
        await self.late_result(change)

    async def test_late_source_expiry_cannot_create_proposal(self):
        async def change(game,binding):self.now+=timedelta(seconds=121)
        await self.late_result(change)

    async def test_late_epoch_switch_cannot_create_proposal(self):
        async def change(game,binding):
            async with self.db.transaction() as s:
                await self.ai(s).use_authored(account_id=self.owner,game_id=game,expected_epoch=1,client_request_id=uuid4().hex)
        await self.late_result(change)

    async def test_late_window_switch_before_source_expiry_discards_body(self):
        from domain.night_case_engine import _due
        async def before(game):
            for _ in range(8):
                async with self.db.transaction() as s:
                    doc=(await s.get(NightGameSealed,game)).kernel;due=_due(doc)
                    close=datetime.fromisoformat(doc['clock']['closes_at'].replace('Z','+00:00'))
                    when=datetime.fromisoformat(due['at'].replace('Z','+00:00'))
                    if when>=close:
                        self.now=close-timedelta(seconds=1);return
                    self.now=when
                    result=await self.service(s).advance_due(game_id=game,command={'command_id':uuid4().hex,'kind':'system.tick',
                        'window_seq':doc['clock']['window_seq'],'timer_seq':doc['clock']['timer_seq'],'params':{'expected_due_at':due['at']}})
                    self.assertTrue(result['receipt']['accepted'])
            self.fail('no final window boundary')
        async def change(game,binding):await self.next_window(game)
        await self.late_result(change,before_prepare=before)
        async with self.db.transaction() as s:
            self.assertEqual((await s.scalar(select(NightAIDispatchAttempt))).status,'cancelled')

    async def test_terminal_merge_revokes_old_principal_and_drops_inflight_body(self):
        from application.account_merge import AccountMergeService
        from storage.admin_actions import operation_fence
        async def change(game,binding):
            for actor in self.accounts[:4]:await self.play(game,actor,'forfeit')
            async with self.db.transaction() as s:
                await operation_fence(s,exclusive=True)
                merge=AccountMergeService(clock=lambda:self.now.timestamp())
                await merge.lock_owned_rows_in(s,[self.owner,self.accounts[4]])
                await merge.merge_in(s,main=await s.get(Account,self.accounts[4]),secondary=await s.get(Account,self.owner),via='synthetic-test')
        game=await self.late_result(change,denied=True)
        self.now+=timedelta(seconds=31)
        self.assertEqual(await self.dispatcher.expire_due(actor=WorkerPrincipal('cleanup:test')),{'expired':1})

    async def next_window(self,game):
        from domain.night_case_engine import _due
        initial=None
        for _ in range(4):
            async with self.db.transaction() as s:
                doc=(await s.get(NightGameSealed,game)).kernel;due=_due(doc)
                if initial is None:initial=doc['clock']['window_idx']
                if doc['clock']['window_idx']>initial:return
                self.now=datetime.fromisoformat(due['at'].replace('Z','+00:00'))
                result=await self.service(s).advance_due(game_id=game,command={'command_id':uuid4().hex,'kind':'system.tick',
                    'window_seq':doc['clock']['window_seq'],'timer_seq':doc['clock']['timer_seq'],'params':{'expected_due_at':due['at']}})
                self.assertTrue(result['receipt']['accepted'])
        self.fail('window boundary not reached')

    async def test_own_digest_render_rebuild_and_reader_first_write_wins(self):
        game,_=await self.start();self.narrate=True;await self.next_window(game)
        async with self.db.transaction() as s:
            jobs=list((await s.scalars(select(NightRenderJob).where(NightRenderJob.kind=='window_digest',
                NightRenderJob.audience_key=='account:'+str(self.owner)))).all())
            self.assertTrue(jobs);job=jobs[-1];source=DispatchSource('render',job.job_id)
        worker=WorkerPrincipal('render:test')
        self.backend.release=asyncio.Event()
        task=asyncio.create_task(self.dispatcher.dispatch(source,actor=worker,worker_id=worker.worker_id))
        try:
            await asyncio.wait_for(self.backend.entered.wait(),2)
            async with self.db.transaction() as s:
                winner=await self.service(s).get_rendering(account_id=self.owner,game_id=game,job_id=source.id)
                self.assertEqual(winner['source'],'authored')
        finally:self.backend.release.set()
        result=await task
        self.assertEqual(result.result['rendering'],winner)
        async with self.db.transaction() as s:
            self.assertEqual((await s.scalar(select(NightAIDispatchAttempt))).status,'cancelled')

    async def test_moderation_rollback_then_block_unblock_revokes_without_party_effects(self):
        from storage.admin_actions import AdminActions,AdminConflict
        game,binding=await self.start(byok=True);work=await self.prepare(game)
        permit=await self.dispatcher.reserve(DispatchSource('intent',work.id),actor=AccountPrincipal(self.owner),worker_id='intent:test')
        self.assertIsInstance(permit,ReservedPermit)
        admin=AdminActions(self.db)
        async with self.db.transaction() as s:
            before=(await s.get(NightGameSealed,game)).kernel
            credential=await s.scalar(select(NightAICredential).where(NightAICredential.game_id==game))
            credential_id=credential.id;ciphertext=credential.ciphertext
        kwargs=dict(operator_id='synthetic:operator',expected_revision=0,reason='synthetic test',blocked=True)
        with self.assertRaises(AdminConflict):
            await admin.moderate_account(self.owner,action_id=uuid4().hex,**(kwargs|{'expected_revision':99}))
        async with self.db.transaction() as s:
            self.assertEqual((await s.get(NightAIBinding,binding)).status,'active')
            self.assertEqual((await s.get(NightAICredential,credential_id)).ciphertext,ciphertext)
            self.assertEqual((await s.get(NightAIDispatchAttempt,permit.id)).status,'reserved')
        action=uuid4().hex
        result=await admin.moderate_account(self.owner,action_id=action,**kwargs)
        self.assertEqual(await admin.moderate_account(self.owner,action_id=action,**kwargs),result)
        await admin.moderate_account(self.owner,action_id=uuid4().hex,operator_id='synthetic:operator',expected_revision=1,reason='synthetic undo',blocked=False)
        async with self.db.transaction() as s:
            self.assertEqual((await s.get(NightAIBinding,binding)).status,'revoked')
            self.assertEqual((await s.get(NightAICredential,credential_id)).status,'erased')
            self.assertEqual((await s.get(NightAIDispatchAttempt,permit.id)).status,'cancelled')
            self.assertEqual((await s.get(NightGameSealed,game)).kernel,before)
            self.assertEqual((await s.get(Game,game)).status,'running')

    async def test_digest_ai_completion_keeps_job_local_aliases_and_exact_blocks(self):
        game,_=await self.start();self.narrate=True;await self.next_window(game)
        async with self.db.transaction() as s:
            job=await s.scalar(select(NightRenderJob).where(NightRenderJob.kind=='window_digest',
                NightRenderJob.audience_key=='account:'+str(self.owner)))
            frozen=job.frozen_view;source=DispatchSource('render',job.job_id)
        result=await self.dispatcher.dispatch(source,actor=WorkerPrincipal('render:test'),worker_id='render:test')
        self.assertEqual(result.result['rendering']['source'],'ai')
        self.assertEqual(result.result['rendering']['text'],'Художественная связка.')
        self.assertTrue(set(result.result['rendering']['references'])<={r['alias'] for r in frozen['reference_map']})
        async with self.db.transaction() as s:
            self.assertEqual((await s.get(NightRenderJob,source.id)).frozen_view,frozen)
            self.assertEqual((await s.scalar(select(NightAIDispatchAttempt))).status,'succeeded')

    async def test_byok_other_private_and_fresh_kill_flags_do_not_dispatch(self):
        game,_=await self.start(byok=True)
        facade=NightCaseOrchestrator(self.db,self.service,self.ai,dispatcher=self.dispatcher)
        other=await facade.propose_intent(account_id=self.accounts[1],game_id=game,request_id=uuid4().hex,text='Чужой приватный текст')
        self.assertEqual(other['kind'],'clarification');self.assertEqual(self.backend.calls,[])
        work=await self.prepare(game);self.flags=DispatchFlags()
        result=await self.dispatcher.dispatch(DispatchSource('intent',work.id),actor=AccountPrincipal(self.owner),worker_id='intent:test')
        self.assertEqual(result.result['kind'],'clarification');self.assertEqual(self.backend.calls,[])
        async with self.db.transaction() as s:
            self.assertEqual(await s.scalar(select(text('count(*)')).select_from(NightAIDispatchAttempt)),0)

    async def test_fog_and_ghost_keep_own_control_and_cleanup_does_not_revoke(self):
        game,binding=await self.start(byok=True)
        for status in ('fog','ghost'):
            async with self.db.transaction() as s:
                (await s.get(GamePlayer,(game,self.owner))).status=status
            async with self.db.transaction() as s:
                ai=self.ai(s);control=await s.get(NightAIGameControl,game)
                self.assertTrue(await ai._starter_usable(control,game))
                await ai._running_starter(await ai.repo.lock_game(game),self.owner,control.epoch)
                result=await ai.cleanup_game(operator=self.admin,game_id=game,client_request_id=uuid4().hex)
                self.assertEqual(result['result']['closed_bindings'],0)
        async with self.db.transaction() as s:
            await self.ai(s).use_authored(account_id=self.owner,game_id=game,expected_epoch=2,client_request_id=uuid4().hex)
            self.assertEqual((await s.get(NightAIBinding,binding)).status,'superseded')

    async def test_intent_full_cycle_has_no_sql_across_network_and_exact_replay_after_expiry(self):
        game,binding=await self.start();work=await self.prepare(game)
        async with self.db.transaction() as s:before=(await s.get(NightGameSealed,game)).kernel
        result=await self.dispatcher.dispatch(DispatchSource('intent',work.id),actor=AccountPrincipal(self.owner),worker_id='intent:test')
        self.assertEqual(result.result['kind'],'proposal');self.assertEqual(len(self.backend.calls),1)
        async with self.db.transaction() as s:
            self.assertEqual((await s.get(NightGameSealed,game)).kernel,before)
            self.assertIsNone((await s.get(NightAIBinding,binding)).inflight_permit_id)
            attempt=await s.scalar(select(NightAIDispatchAttempt));self.assertEqual(attempt.status,'succeeded')
        self.now+=timedelta(days=2);self.flags=DispatchFlags()
        replay=await self.dispatcher.dispatch(DispatchSource('intent',work.id),actor=AccountPrincipal(self.owner),worker_id='intent:test')
        self.assertEqual(replay.result,result.result);self.assertEqual(len(self.backend.calls),1)

    async def test_two_reservers_share_one_attempt_and_only_authorize_once(self):
        game,_=await self.start();work=await self.prepare(game);source=DispatchSource('intent',work.id)
        async def reserve():return await self.dispatcher.reserve(source,actor=AccountPrincipal(self.owner),worker_id='intent:test')
        first,second=await asyncio.gather(reserve(),reserve())
        self.assertCountEqual([type(first),type(second)],[ReservedPermit,DispatchResult])
        permit=first if type(first) is ReservedPermit else second
        from infrastructure.night_ai_gateway import SendTicket
        from application.night_case_ai_dispatch import Denied
        async def authorize():return await self.dispatcher.authorize_inference(permit,actor=AccountPrincipal(self.owner),worker_id='intent:test')
        a,b=await asyncio.gather(authorize(),authorize())
        self.assertCountEqual([type(a),type(b)],[SendTicket,Denied])

    async def test_observed_transient_uses_second_quota_but_unknown_crash_never_resends(self):
        game,binding=await self.start();work=await self.prepare(game);source=DispatchSource('intent',work.id)
        self.backend.status=503
        first=await self.dispatcher.dispatch(source,actor=AccountPrincipal(self.owner),worker_id='intent:test')
        self.assertEqual(first.status,'deferred');self.assertEqual(len(self.backend.calls),1)
        self.now=first.retry_after;self.backend.status=200
        second=await self.dispatcher.dispatch(source,actor=AccountPrincipal(self.owner),worker_id='intent:test')
        self.assertEqual(second.result['kind'],'proposal');self.assertEqual(len(self.backend.calls),2)
        async with self.db.transaction() as s:
            attempts=list((await s.scalars(select(NightAIDispatchAttempt).order_by(NightAIDispatchAttempt.attempt_no))).all())
            self.assertEqual([a.status for a in attempts],['failed','succeeded'])
            self.assertEqual([a.attempt_no for a in attempts],[1,2])
            self.assertEqual(sum(a.reserved_output_tokens for a in attempts),2*attempts[0].reserved_output_tokens)
        other=await self.prepare(game);source=DispatchSource('intent',other.id)
        permit=await self.dispatcher.reserve(source,actor=AccountPrincipal(self.owner),worker_id='intent:test')
        await self.dispatcher.authorize_inference(permit,actor=AccountPrincipal(self.owner),worker_id='intent:test')
        self.now+=timedelta(seconds=31)
        self.assertEqual(await self.dispatcher.expire_due(actor=WorkerPrincipal('cleanup:test')),{'expired':1})
        replay=await self.dispatcher.dispatch(source,actor=AccountPrincipal(self.owner),worker_id='intent:test')
        self.assertEqual(replay.result['kind'],'clarification');self.assertEqual(len(self.backend.calls),2)

    async def test_orchestrator_fresh_guest_transaction_rejects_revoked_session_after_network(self):
        from application.night_case import NightCaseError
        game,_=await self.start();token='e'*64
        async with self.db.transaction() as s:
            s.add(GuestSession(token_hash=token,account_id=self.owner,account_revision=0,created_at=self.now,
                expires_at=self.now+timedelta(hours=1),revoked=False))
        @asynccontextmanager
        async def authenticated_transaction():
            async with self.db.transaction() as s:
                self.backend.contexts+=1
                try:
                    guest=await s.get(GuestSession,token,populate_existing=True)
                    if guest.revoked:raise NightCaseError('unavailable',404)
                    yield s
                finally:self.backend.contexts-=1
        facade=NightCaseOrchestrator(self.db,self.service,self.ai,dispatcher=self.dispatcher)
        self.backend.release=asyncio.Event()
        task=asyncio.create_task(facade.propose_intent(account_id=self.owner,game_id=game,request_id=uuid4().hex,
            text='Осмотреться',transaction_factory=authenticated_transaction))
        try:
            await asyncio.wait_for(self.backend.entered.wait(),2)
            self.assertEqual(self.backend.contexts,0)
            async with self.db.transaction() as s:(await s.get(GuestSession,token)).revoked=True
        finally:self.backend.release.set()
        with self.assertRaises(NightCaseError):await task
        async with self.db.transaction() as s:
            self.assertEqual(await s.scalar(select(text('count(*)')).select_from(NightIntentProposal)),0)
            self.assertEqual((await s.scalar(select(NightAIDispatchAttempt))).status,'sending')
        self.now+=timedelta(seconds=31)
        self.assertEqual(await self.dispatcher.expire_due(actor=WorkerPrincipal('cleanup:test')),{'expired':1})

    async def test_revoked_binding_during_network_drops_body_and_never_changes_party(self):
        game,binding=await self.start(byok=True);work=await self.prepare(game)
        self.backend.release=asyncio.Event()
        task=asyncio.create_task(self.dispatcher.dispatch(DispatchSource('intent',work.id),actor=AccountPrincipal(self.owner),worker_id='intent:test'))
        try:
            await asyncio.wait_for(self.backend.entered.wait(),2)
            async with self.db.transaction() as s:
                before=(await s.get(NightGameSealed,game)).kernel
                await asyncio.wait_for(self.ai(s).revoke_binding(operator=self.admin,binding_id=binding,client_request_id=uuid4().hex),2)
        finally:self.backend.release.set()
        result=await task;self.assertEqual(result.result['kind'],'clarification')
        async with self.db.transaction() as s:
            self.assertEqual((await s.get(NightGameSealed,game)).kernel,before)
            self.assertEqual(await s.scalar(select(text('count(*)')).select_from(NightIntentProposal)),0)
            row=await s.get(NightAIBinding,binding);self.assertEqual(row.status,'revoked');self.assertIsNone(row.inflight_permit_id)
            self.assertEqual((await s.scalar(select(NightAIDispatchAttempt))).status,'cancelled')
