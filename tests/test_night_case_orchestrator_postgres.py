"""Real orchestration transactions; synthetic transport only, owned PG55434."""
import asyncio
import copy
import os
import unittest
from contextlib import asynccontextmanager
from datetime import timedelta
from uuid import UUID, uuid4
from unittest.mock import patch

from sqlalchemy import func, select, text

from application.night_case import NightCaseApplicationService, NightCaseError
from application.night_case_ai import NightAIControlService, NightAIControlError
from application.night_case_orchestrator import NightCaseOrchestrator, PreparedIntent, TestOnlyIntentTransport
from storage.night_ai import SecretVault
from storage.night_ai_control import AI_CONFIG_LOCK, NightAIControlRepository
from storage.night_ai_models import NightAIIntentRequest, NightAIGameControl, NightAIRequest
from storage.models import Game, GamePlayer, NightGameSealed, NightIntentProposal, NotificationOutbox, Room
from tests import test_night_ai_control_postgres as base


@unittest.skipUnless(os.getenv('NIGHT_AI_ORCHESTRATION_TESTS') == '1', 'NIGHT_AI_ORCHESTRATION_TESTS=1 required')
class NightCaseOrchestratorPostgresTests(unittest.IsolatedAsyncioTestCase):
    service=base.NightAIControlPostgresTests.service
    lobby_command=base.NightAIControlPostgresTests.lobby_command
    lobby=base.NightAIControlPostgresTests.lobby
    ready_lobby=base.NightAIControlPostgresTests.ready_lobby
    player_command=base.NightAIControlPostgresTests.player_command
    asyncSetUp=base.NightAIControlPostgresTests.asyncSetUp
    asyncTearDown=base.NightAIControlPostgresTests.asyncTearDown

    def ai(self,session):
        return NightAIControlService(session,lambda:self.now,self.ai_registry,self.vault,self.receipts,
            environment_id='synthetic-test',original_starter_resolver=self.service(session).prove_original_starter)

    def orchestration(self,transport=None,factory=None):
        return NightCaseOrchestrator(self.db,factory or self.service,self.ai,transport)

    async def start(self, *, direct=False, legacy=False, options=None, factory=None):
        if legacy:
            async def old_no_control(*args,**kwargs): return None
            with patch.object(NightAIControlRepository,'ensure_empty_lobby_control_locked',old_no_control):
                game,_,command=await self.ready_lobby()
        else: game,_,command=await self.ready_lobby()
        if options is not None: command={**command,'params':{'ai':options}}
        if direct:
            async with self.db.transaction() as session:
                result=await self.service(session).start_game(account_id=self.owner,game_id=game,command=command)
        else:
            result=await self.orchestration(factory=factory).start_game(account_id=self.owner,game_id=game,command=command)
        return game,command,result

    async def bind(self,game,epoch=1):
        async with self.db.transaction() as session:
            return await self.ai(session).stage_or_activate_byok(account_id=self.owner,game_id=game,expected_epoch=epoch,
                settings=self.settings,secret=b'synthetic-orchestration',client_request_id=uuid4().hex)

    async def selection(self,game):
        async with self.db.transaction() as session:
            view=await self.service(session).get_view(account_id=self.owner,game_id=game)
        return next(item['quote']['selection_id'] for item in view['menu'] if item.get('quote',{}).get('kind')=='seen')

    async def direct_button(self,game,request,selection):
        async with self.db.transaction() as session:
            return await self.service(session).propose_intent(account_id=self.owner,game_id=game,request_id=request,selection_id=selection)

    def response(self,work):
        selected=next(x for x in work.legal['items'] if x['kind']=='seen')
        return {'request_token':work.token['request_token'],'kind':'intent_selection','selection_id':selected['selection_id']}

    def fake(self,callback=None):
        async def choose(payload):
            selected=next(x for x in payload['choices'] if x['kind']=='seen')
            return {'request_token':payload['request_token'],'kind':'intent_selection','selection_id':selected['selection_id']}
        return TestOnlyIntentTransport(callback or choose)

    async def test_direct_authored_initial_identity_and_old_start_replay_never_request_ai(self):
        game,command,old=await self.start(direct=True)
        async with self.db.transaction() as session:
            control=await session.get(NightAIGameControl,game)
            self.assertEqual((control.starter_account_id,control.epoch,control.current_binding_id),(self.owner,0,None))
            self.assertEqual(await session.scalar(select(func.count()).select_from(NightAIRequest).where(NightAIRequest.game_id==game)),0)
            self.assertEqual(await session.scalar(select(func.count()).select_from(NotificationOutbox).where(NotificationOutbox.game_id==game)),0)
        self.vault=SecretVault(None)
        self.now+=timedelta(days=30)
        self.assertEqual(await self.orchestration().start_game(account_id=self.owner,game_id=game,command=command),old)
        explicit={**command,'params':{'ai':{'mode':'admin','expected_epoch':0,'staged_credential_id':None}}}
        with self.assertRaises(NightCaseError) as caught:
            await self.orchestration().start_game(account_id=self.owner,game_id=game,command=explicit)
        self.assertEqual(caught.exception.code,'command_conflict')
        async with self.db.transaction() as session:
            pending=await self.ai(session).request_admin(account_id=self.owner,game_id=game,expected_epoch=0,client_request_id=uuid4().hex)
            self.assertEqual(pending['result']['epoch'],1)

    async def test_legacy_game_no_control_proves_original_starter_without_current_owner(self):
        game,command,original=await self.start(direct=True,legacy=True)
        async with self.db.transaction() as session:
            self.assertIsNone(await session.get(NightAIGameControl,game))
            (await session.get(Room,self.room)).owner_account_id=self.accounts[1]
        self.assertEqual(await self.orchestration().start_game(account_id=self.owner,game_id=game,command=command),original)
        async with self.db.transaction() as session:
            self.assertIsNone(await session.get(NightAIGameControl,game))
            result=await self.ai(session).request_admin(account_id=self.owner,game_id=game,expected_epoch=0,client_request_id=uuid4().hex)
            self.assertEqual(result['result']['epoch'],1)
            self.assertEqual((await session.get(NightAIGameControl,game)).starter_account_id,self.owner)

    async def test_orchestrated_start_sets_control_and_started_at_before_director_and_rolls_back_all(self):
        observed=[]
        async def fail(context,transition):
            observed.append((context.locked.game.started_at,context.now))
            raise RuntimeError('synthetic-director-failure')
        def factory(session):
            async def hook(context,transition):
                row=await session.get(NightAIGameControl,context.locked.game.id)
                self.assertEqual((row.starter_account_id,row.epoch),(self.owner,1))
                await fail(context,transition)
            return NightCaseApplicationService(session,lambda:self.now,self.registry,transition_hook=hook)
        game,_,command=await self.ready_lobby()
        with self.assertRaisesRegex(RuntimeError,'synthetic-director'):
            await self.orchestration(factory=factory).start_game(account_id=self.owner,game_id=game,command=command)
        self.assertEqual(observed,[(self.now,self.now)])
        async with self.db.transaction() as session:
            self.assertIsNone((await session.get(Game,game)).started_at)
            self.assertEqual((await session.get(NightGameSealed,game)).lifecycle,'lobby')
            self.assertEqual((await session.get(NightAIGameControl,game)).epoch,0)
            self.assertEqual(await session.scalar(select(func.count()).select_from(GamePlayer).where(GamePlayer.game_id==game)),0)
            self.assertEqual(await session.scalar(select(func.count()).select_from(NightAIRequest).where(NightAIRequest.game_id==game)),0)
            self.assertEqual(await session.scalar(select(func.count()).select_from(NotificationOutbox).where(NotificationOutbox.game_id==game)),0)
        self.vault=SecretVault(None)
        await self.orchestration().start_game(account_id=self.owner,game_id=game,command=command)

    async def test_cross_path_identity_and_button_128_new_prepare_96_boundary(self):
        game,_,_=await self.start()
        selection=await self.selection(game)
        orchestrator=self.orchestration()
        request=uuid4().hex
        first=await orchestrator.propose_intent(account_id=self.owner,game_id=game,request_id=request,text='look')
        self.assertEqual(first['kind'],'clarification')
        with self.assertRaises(NightCaseError): await self.direct_button(game,request,selection)
        button=uuid4().hex
        await self.direct_button(game,button,selection)
        with self.assertRaises(NightCaseError):
            await orchestrator.propose_intent(account_id=self.owner,game_id=game,request_id=button,text='look')
        for size in (96,97,128): await self.direct_button(game,'b'*size,selection)
        await orchestrator.prepare_intent(account_id=self.owner,game_id=game,request_id='t'*96,text='look')
        for size in (97,128):
            with self.assertRaises(NightCaseError) as caught:
                await orchestrator.prepare_intent(account_id=self.owner,game_id=game,request_id='t'*size,text='look')
            self.assertEqual(caught.exception.status,422)
        racing=uuid4().hex
        results=await asyncio.gather(self.direct_button(game,racing,selection),orchestrator.propose_intent(
            account_id=self.owner,game_id=game,request_id=racing,text='look'),return_exceptions=True)
        self.assertEqual(sum(isinstance(x,dict) for x in results),1)
        self.assertEqual(next(x.code for x in results if isinstance(x,NightCaseError)),'command_conflict')
        async with self.db.transaction() as session:
            self.assertIsNone(await session.scalar(select(NightAIIntentRequest).where(NightAIIntentRequest.client_request_id=='t'*97)))

    async def test_prepare_commits_no_ap_http_has_no_locks_and_proposal_keeps_prepare_deadline(self):
        game,_,_=await self.start()
        await self.bind(game)
        request=uuid4().hex
        orchestrator=self.orchestration(self.fake())
        async with self.db.transaction() as session:
            kernel=copy.deepcopy((await session.get(NightGameSealed,game)).kernel)
        work=await orchestrator.prepare_intent(account_id=self.owner,game_id=game,request_id=request,text='look')
        self.assertIsInstance(work,PreparedIntent)
        async with self.db.transaction() as session:
            self.assertEqual((await session.get(NightGameSealed,game)).kernel,kernel)
            self.assertEqual(await session.scalar(select(func.count()).select_from(NightIntentProposal).where(NightIntentProposal.game_id==game)),0)
            self.assertTrue(await session.scalar(text('SELECT pg_try_advisory_xact_lock(:key)'),{'key':AI_CONFIG_LOCK}))
            await session.execute(select(Game).where(Game.id==game).with_for_update(nowait=True))
        self.now+=timedelta(seconds=35)
        response=self.response(work)
        response['selection_id']=next(x['selection_id'] for x in work.legal['items'] if x['kind']=='move')
        proposal=await orchestrator.finalize_intent(account_id=self.owner,game_id=game,request_id=request,transport_result=response)
        self.assertEqual(proposal['kind'],'proposal')
        self.assertEqual(proposal['proposal']['created_at'],work.token['prepared_at'])
        self.assertEqual(proposal['proposal']['expires_at'],work.token['expires_at'])
        async with self.db.transaction() as session:
            before=next(p for p in (await session.get(NightGameSealed,game)).kernel['players'] if p['account_id']==str(self.owner))['ap']
            confirmed=await self.service(session).confirm_intent(account_id=self.owner,game_id=game,proposal_id=proposal['proposal']['proposal_id'])
            self.assertTrue(confirmed['receipt']['accepted'])
            after=next(p for p in (await session.get(NightGameSealed,game)).kernel['players'] if p['account_id']==str(self.owner))['ap']
            self.assertEqual(after,before-1)
        self.now+=timedelta(seconds=120)
        self.assertEqual(await orchestrator.prepare_intent(account_id=self.owner,game_id=game,request_id=request,text='look'),proposal)

    async def test_finalize_stale_epoch_expiry_and_wrong_actor_are_safe(self):
        game,_,_=await self.start()
        await self.bind(game)
        orchestrator=self.orchestration(self.fake())
        request=uuid4().hex
        work=await orchestrator.prepare_intent(account_id=self.owner,game_id=game,request_id=request,text='look')
        with self.assertRaises(NightCaseError) as caught:
            await orchestrator.finalize_intent(account_id=self.accounts[1],game_id=game,request_id=request,transport_result=self.response(work))
        self.assertEqual(caught.exception.status,404)
        async with self.db.transaction() as session:
            await self.ai(session).use_authored(account_id=self.owner,game_id=game,expected_epoch=2,client_request_id=uuid4().hex)
        result=await orchestrator.finalize_intent(account_id=self.owner,game_id=game,request_id=request,transport_result=self.response(work))
        self.assertEqual(result['kind'],'clarification')
        await self.bind(game,epoch=3)
        request2=uuid4().hex
        work2=await orchestrator.prepare_intent(account_id=self.owner,game_id=game,request_id=request2,text='look')
        self.now+=timedelta(seconds=121)
        self.assertEqual((await orchestrator.finalize_intent(account_id=self.owner,game_id=game,request_id=request2,transport_result=self.response(work2)))['kind'],'clarification')
        async with self.db.transaction() as session:
            self.assertEqual(await session.scalar(select(func.count()).select_from(NightIntentProposal).where(NightIntentProposal.game_id==game)),0)

    async def test_real_http_principal_transactions_close_around_transport_and_reauthenticate(self):
        import hashlib
        import secrets
        import httpx
        from storage.models import GuestSession
        from web.mini_app import MiniAppSettings, create_app
        game,_,_=await self.start()
        await self.bind(game)
        cookie=secrets.token_urlsafe(32)
        token_hash=hashlib.sha256(cookie.encode('ascii')).hexdigest()
        async with self.db.transaction() as session:
            session.add(GuestSession(token_hash=token_hash,account_id=self.owner,account_revision=0,
                created_at=self.now,expires_at=self.now+timedelta(days=1),revoked=False,created_via='guest'))
        class TrackingDatabase:
            active=0
            sessions=[]
            def __getattr__(inner,name): return getattr(self.db,name)
            @asynccontextmanager
            async def transaction(inner):
                inner.active+=1
                try:
                    async with self.db.transaction() as session:
                        inner.sessions.append(session)
                        yield session
                finally: inner.active-=1
        tracked=TrackingDatabase()
        calls=[]
        revoke=False
        async def model(payload):
            self.assertEqual(tracked.active,0)  # includes REAL resolve_principal's outer transaction
            self.assertTrue(all(not s.in_transaction() for s in tracked.sessions))
            self.assertEqual(set(payload),{'request_token','kind','text','choices'})
            self.assertNotIn(str(self.owner),str(payload))
            async with self.db.transaction() as session:
                self.assertTrue(await session.scalar(text('SELECT pg_try_advisory_xact_lock(:key)'),{'key':AI_CONFIG_LOCK}))
                await session.execute(select(Game).where(Game.id==game).with_for_update(nowait=True))
                if revoke: (await session.get(GuestSession,token_hash)).revoked=True
            if not revoke:
                command=await self.player_command(game,self.accounts[1],'seen')
                async with self.db.transaction() as session:
                    await self.service(session).execute(account_id=self.accounts[1],game_id=game,command=command)
            calls.append(payload['request_token'])
            chosen=next(x for x in payload['choices'] if x['kind']=='seen')
            return {'request_token':payload['request_token'],'kind':'intent_selection','selection_id':chosen['selection_id']}
        orchestrator=NightCaseOrchestrator(tracked,self.service,self.ai,self.fake(model))
        origin='http://127.0.0.1:4897'
        app=create_app(database=tracked,settings=MiniAppSettings('',origin,offline=True),clock=lambda:self.now.timestamp(),
            night_case_enabled=True,night_case_service_factory=self.service,night_case_orchestrator=orchestrator)
        headers={'Origin':origin,'X-Guest-CSRF':'1','X-Night-Expected-Viewer':str(self.owner)}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url=origin,cookies={'mqb_guest':cookie}) as client:
            response=await client.post(f'/api/night-case/games/{game}/intent?identity=guest',headers=headers,
                json={'request_id':uuid4().hex,'selection_id':None,'text':'look'})
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(response.json()['kind'],'proposal')
            revoke=True
            other_request=uuid4().hex
            response=await client.post(f'/api/night-case/games/{game}/intent?identity=guest',headers=headers,
                json={'request_id':other_request,'selection_id':None,'text':'look again'})
            self.assertEqual(response.status_code,401,response.text)
        self.assertEqual(len(calls),2)
        async with self.db.transaction() as session:
            self.assertIsNone(await session.scalar(select(NightIntentProposal).where(NightIntentProposal.game_id==game,
                NightIntentProposal.request_id==other_request)))

    async def test_selected_byok_missing_master_rolls_back_real_orchestrated_start(self):
        game,_,command=await self.ready_lobby()
        async with self.db.transaction() as session:
            staged=await self.ai(session).stage_or_activate_byok(account_id=self.owner,game_id=game,expected_epoch=0,
                settings=self.settings,secret=b'synthetic-orchestrated-stage',client_request_id=uuid4().hex)
        staged_id=staged['result']['staged_credential_id']
        byok={**command,'params':{'ai':{'mode':'byok','expected_epoch':0,'staged_credential_id':staged_id}}}
        self.vault=SecretVault(None)
        with self.assertRaises(NightAIControlError) as caught:
            await self.orchestration().start_game(account_id=self.owner,game_id=game,command=byok)
        self.assertEqual(caught.exception.code,'ai_unavailable')
        async with self.db.transaction() as session:
            self.assertIsNone((await session.get(Game,game)).started_at)
            self.assertEqual((await session.get(NightAIGameControl,game)).epoch,0)
        authored={**command,'command_id':uuid4().hex,'params':{'ai':{'mode':'authored','expected_epoch':0,'staged_credential_id':None}}}
        await self.orchestration().start_game(account_id=self.owner,game_id=game,command=authored)

    async def test_two_sessions_prepare_finalize_and_departed_exact_replay(self):
        game,_,_=await self.start()
        await self.bind(game)
        calls=[]
        async def no_call(payload):
            calls.append(payload)
            return None
        orchestrator=self.orchestration(self.fake(no_call))
        request=uuid4().hex
        first,second=await asyncio.gather(*[orchestrator.prepare_intent(account_id=self.owner,game_id=game,
            request_id=request,text='look') for _ in range(2)])
        self.assertEqual((first.id,first.token),(second.id,second.token))
        self.assertEqual(sorted([first.replayed,second.replayed]),[False,True])
        pending=await orchestrator.propose_intent(account_id=self.owner,game_id=game,request_id=request,text='look')
        self.assertEqual(pending['code'],'intent_pending')
        self.assertEqual(calls,[])
        results=await asyncio.gather(*[orchestrator.finalize_intent(account_id=self.owner,game_id=game,
            request_id=request,transport_result=self.response(first)) for _ in range(2)])
        self.assertEqual(results[0],results[1])
        async with self.db.transaction() as session:
            self.assertEqual(await session.scalar(select(func.count()).select_from(NightIntentProposal).where(
                NightIntentProposal.game_id==game,NightIntentProposal.request_id==request)),1)
        command=await self.player_command(game,self.owner,'forfeit')
        async with self.db.transaction() as session:
            await self.service(session).execute(account_id=self.owner,game_id=game,command=command)
        self.now+=timedelta(minutes=5)
        self.assertEqual(await orchestrator.prepare_intent(account_id=self.owner,game_id=game,request_id=request,text='look'),results[0])

    async def test_replay_lookup_never_mixes_pre_and_post_finalize_snapshots(self):
        from sqlalchemy.ext.asyncio import AsyncSession
        game,_,_=await self.start()
        await self.bind(game)
        orchestrator=self.orchestration(self.fake())
        request=uuid4().hex
        work=await orchestrator.prepare_intent(account_id=self.owner,game_id=game,request_id=request,text='look')
        ordinary_read=asyncio.Event()
        release=asyncio.Event()
        original=AsyncSession.scalars
        replay_task=None

        async def pause_after_ordinary_select(session,statement,*args,**kwargs):
            result=await original(session,statement,*args,**kwargs)
            if (asyncio.current_task() is replay_task and statement.column_descriptions[0].get('entity') is NightIntentProposal):
                ordinary_read.set()
                await asyncio.wait_for(release.wait(),5)
            return result

        with patch.object(AsyncSession,'scalars',pause_after_ordinary_select):
            replay_task=asyncio.create_task(orchestrator.prepare_intent(
                account_id=self.owner,game_id=game,request_id=request,text='look'))
            waiter=asyncio.create_task(ordinary_read.wait())
            try:
                done,_=await asyncio.wait({replay_task,waiter},timeout=5,return_when=asyncio.FIRST_COMPLETED)
                self.assertTrue(done)
                finalized=await orchestrator.finalize_intent(account_id=self.owner,game_id=game,
                    request_id=request,transport_result=self.response(work))
            finally:
                release.set()
                waiter.cancel()
            replayed=await replay_task
        self.assertIn(type(replayed),(PreparedIntent,dict))
        if type(replayed) is dict:
            self.assertEqual(replayed,finalized)
        statements=[]
        from sqlalchemy import event
        def observe(conn,cursor,statement,parameters,context,executemany):
            if 'night_intent_proposals' in statement or 'night_ai_intent_requests' in statement:
                statements.append(statement)
        event.listen(self.db.engine.sync_engine,'before_cursor_execute',observe)
        async with self.db.transaction() as session:
            try:
                ordinary,prepared=await NightAIControlRepository(session).intent_rows(game,[self.owner],request)
            finally:
                event.remove(self.db.engine.sync_engine,'before_cursor_execute',observe)
        self.assertEqual((len(ordinary),len(prepared)),(1,1))
        self.assertEqual(prepared[0].safe_result,finalized)
        self.assertEqual(len(statements),1)
        self.assertIn('night_intent_proposals',statements[0])
        self.assertIn('night_ai_intent_requests',statements[0])

    async def test_ambiguous_legacy_starter_evidence_cannot_bootstrap_control(self):
        game,command,old=await self.start(direct=True,legacy=True)
        async with self.db.transaction() as session:
            await self.service(session).repo.lock_game(game)
            await self.service(session).repo.put_command_receipt(game_id=game,actor_key=str(self.accounts[1]),
                actor_account_id=self.accounts[1],client_command_id=uuid4().hex,kind='start_game',
                payload={'kind':'start_game','expected_lobby_revision':command['expected_lobby_revision'],'params':{}},
                result=old,status='applied',now=self.now)
        with self.assertRaises(NightAIControlError) as caught:
            async with self.db.transaction() as session:
                await self.ai(session).request_admin(account_id=self.owner,game_id=game,expected_epoch=0,client_request_id=uuid4().hex)
        self.assertEqual(caught.exception.code,'starter_unproven')
        async with self.db.transaction() as session:
            self.assertIsNone(await session.get(NightAIGameControl,game))

    async def test_byok_other_private_and_unreviewed_transport_never_infer(self):
        game,_,_=await self.start()
        await self.bind(game)
        calls=[]
        async def forbidden(payload):
            calls.append(payload)
            raise AssertionError('must not infer')
        other=self.orchestration(self.fake(forbidden))
        private_text='OWN-OTHER-PRIVATE-CANARY'
        result=await other.propose_intent(account_id=self.accounts[1],game_id=game,request_id=uuid4().hex,text=private_text)
        self.assertEqual(result,{'kind':'clarification','code':'choose_available_action'})
        class UnreviewedProvider:
            async def infer(self,payload): return await forbidden(payload)
        result=await self.orchestration(UnreviewedProvider()).propose_intent(account_id=self.owner,game_id=game,
            request_id=uuid4().hex,text='look')
        self.assertEqual(result['kind'],'clarification')
        self.assertEqual(calls,[])
        self.assertNotIn(private_text,str(result))

    async def test_nul_text_is_closed_validation_before_insert(self):
        game,_,_=await self.start()
        request=uuid4().hex
        with self.assertRaises(NightCaseError) as caught:
            await self.orchestration().prepare_intent(account_id=self.owner,game_id=game,request_id=request,text='bad\x00text')
        self.assertEqual(caught.exception.code,'invalid_command')
        async with self.db.transaction() as session:
            self.assertIsNone(await session.scalar(select(NightAIIntentRequest).where(
                NightAIIntentRequest.game_id==game,NightAIIntentRequest.client_request_id==request)))
