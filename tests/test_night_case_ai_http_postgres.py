"""Actual AI HTTP/service/database flow in an owned isolated PG schema."""
import os
import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
from fastapi import FastAPI
from sqlalchemy import select

from application.night_case import NightCaseApplicationService
from application.night_case_ai import NightAIControlService
from application.night_case_ai_views import NightCaseAIViews
from storage.night_ai import KeyRing, ReceiptFingerprinter, SecretVault
from storage.night_ai_models import NightAICredential, NightAIRequest
from tests.test_night_case_ai_views import NOW
from web.night_case_ai_admin import make_night_case_ai_admin_router
from web.night_case_ai_routes import register_night_case_ai_routes


class AIHTTPPostgresTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from tests.night_case_test_database import night_case_test_url
        url=night_case_test_url()
        if os.getenv('TEST_DATABASE_URL')!=url:
            raise RuntimeError('AI HTTP PG requires TEST_DATABASE_URL to match the guarded Night Case URL')
        # Reuse the already proven isolated-schema fixture; no public schema fallback.
        from tests.test_night_case_ai_views import AIViewsPostgresTests
        self.db=AIViewsPostgresTests('test_lobby_acl_shape_and_no_bootstrap_write')
        await self.db.asyncSetUp()
        self.addAsyncCleanup(self.db._cleanup)
        self.vault=SecretVault(KeyRing('test',{'test':b'v'*32}))
        self.receipts=ReceiptFingerprinter(KeyRing('test',{'test':b'h'*32}))
        self.auth=SimpleNamespace(configured=True,current=SimpleNamespace(csrf='csrf-test'))
        self.auth.get_session=lambda request:self.auth.current
        app=FastAPI()
        app.state.admin_auth=self.auth
        class Database:
            @asynccontextmanager
            async def transaction(inner):
                async with self.db.sessions.begin() as session: yield session
        app.state.admin_database=Database()
        @app.middleware('http')
        async def test_admin_state(request,call_next):
            if request.headers.get('x-test-admin')=='1': request.state.admin_session=self.auth.current
            return await call_next(request)
        @asynccontextmanager
        async def principal(request,identity,*,write=False):
            try: actor=UUID(request.headers.get('x-test-account',''))
            except ValueError: actor=self.db.ids[0]
            async with self.db.sessions.begin() as session:
                yield session,SimpleNamespace(account_id=actor)
        async def read_body(request,*,max_bytes):
            body=await request.body()
            if len(body)>max_bytes: raise ValueError('oversize')
            return body
        def ai(session):
            return NightAIControlService(session,lambda:NOW,self.db.registry,self.vault,self.receipts,
                environment_id='http-pg-test')
        def views(session):
            app_service=NightCaseApplicationService(session,lambda:NOW,None)
            return NightCaseAIViews(session,app_service,ai(session),runtime_enabled=True,
                external_enabled=True,vault_ready=True)
        register_night_case_ai_routes(app,principal=principal,identity_for=lambda r,i:i or 'guest',
            read_body=read_body,enabled=True,service_factory=ai,views_factory=views)
        app.include_router(make_night_case_ai_admin_router(service_factory=ai,views_factory=views,
            deployment_id='test',enabled=True))
        self.client=httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='https://testserver')
        self.addAsyncCleanup(self.client.aclose)

    def game_headers(self,actor):
        return {'x-test-account':str(actor),'x-night-expected-viewer':str(actor),
            'origin':'https://testserver','x-guest-csrf':'1'}

    def admin_headers(self):
        return {'x-test-admin':'1','origin':'https://testserver','x-csrf-token':'csrf-test'}

    async def test_lobby_byok_secret_is_owner_scoped_and_game_status_minimal(self):
        path=f'/api/night-case/games/{self.db.game}/ai'
        data={'expected_epoch':0,'settings':{'preset':'openai','model_id':'safe-model'},
              'secret':'PG_SECRET_CANARY','client_request_id':uuid4().hex}
        owner=self.db.ids[0];other=self.db.ids[1]
        staged=await self.client.post(path+'/byok',json=data,headers=self.game_headers(owner))
        self.assertEqual(staged.status_code,200,staged.text)
        self.assertNotIn('PG_SECRET_CANARY',staged.text)
        own=await self.client.get(path,headers=self.game_headers(owner))
        foreign=await self.client.get(path,headers=self.game_headers(other))
        self.assertEqual((own.status_code,own.json()['mode'],own.json()['credential_configured']), (200,'byok',True))
        self.assertEqual(foreign.json(),{'status':'authored','model_label':None})
        denied=await self.client.post(path+'/byok',json=data,headers=self.game_headers(other))
        self.assertEqual(denied.status_code,404)
        self.assertNotIn('PG_SECRET_CANARY',denied.text)
        async with self.db.sessions() as session:
            rows=(await session.scalars(select(NightAICredential))).all()
            self.assertEqual(len(rows),1)
            self.assertEqual(rows[0].owner_subject,'account:'+str(owner))

    async def test_request_admin_profile_approval_and_exact_replay(self):
        await self.db.running()
        path=f'/api/night-case/games/{self.db.game}/ai'
        owner=self.db.ids[0]
        request_id=uuid4().hex
        request=await self.client.post(path+'/request',json={'expected_epoch':0,'client_request_id':request_id},
            headers=self.game_headers(owner))
        self.assertEqual(request.status_code,200,request.text)
        self.assertEqual(request.json()['result']['request_status'],'pending')
        duplicate=await self.client.post(path+'/request',json={'expected_epoch':0,'client_request_id':request_id},
            headers=self.game_headers(owner))
        self.assertEqual(duplicate.json()['result'],request.json()['result'])
        profile_data={'expected_revision':0,'label':'Admin model',
            'settings':{'preset':'openai','model_id':'safe-model'},
            'secret':'ADMIN_PG_KEY_CANARY','client_request_id':uuid4().hex}
        saved=await self.client.post('/api/admin/night-case/ai/profiles',json=profile_data,
            headers=self.admin_headers())
        self.assertEqual(saved.status_code,200,saved.text)
        profile_id=saved.json()['result']['profile_id']
        overflow=await self.client.get(f'/api/admin/night-case/ai/profiles/{profile_id}/revisions/9223372036854775808',
            headers=self.admin_headers())
        self.assertEqual((overflow.status_code,overflow.json()['code']),(422,'invalid_config'))
        bad_decision=await self.client.post('/api/admin/night-case/ai/requests/'+request.json()['result']['request_id']+'/decision',
            json={'decision':[],'profile_id':None,'profile_revision':None,'caps':None,
                  'client_request_id':uuid4().hex},headers=self.admin_headers())
        self.assertEqual((bad_decision.status_code,bad_decision.json()['code']),(422,'invalid_config'))
        stale_revision=await self.client.post(f'/api/admin/night-case/ai/profiles/{profile_id}/revisions',
            json={'expected_revision':2,'label':'Admin model','settings':profile_data['settings'],
                  'client_request_id':uuid4().hex},headers=self.admin_headers())
        self.assertEqual((stale_revision.status_code,stale_revision.json()['code']),(409,'stale_revision'))
        enabled=await self.client.post(f'/api/admin/night-case/ai/profiles/{profile_id}/enabled',
            json={'enabled':True,'client_request_id':uuid4().hex},headers=self.admin_headers())
        self.assertEqual(enabled.status_code,200,enabled.text)
        default=await self.client.post('/api/admin/night-case/ai/profiles/default',
            json={'profile_id':profile_id,'client_request_id':uuid4().hex},headers=self.admin_headers())
        self.assertEqual(default.status_code,200,default.text)
        still_pending=await self.client.get(path,headers=self.game_headers(self.db.ids[1]))
        self.assertEqual(still_pending.json(),{'status':'pending','model_label':None})
        self.assertNotIn('ADMIN_PG_KEY_CANARY',saved.text+enabled.text)
        inbox=await self.client.get('/api/admin/night-case/ai/requests',headers=self.admin_headers())
        self.assertEqual(inbox.json()['items'][0]['status'],'pending')
        decision={'decision':'approve','profile_id':profile_id,'profile_revision':1,'caps':None,
                  'client_request_id':uuid4().hex}
        approved=await self.client.post('/api/admin/night-case/ai/requests/'+request.json()['result']['request_id']+'/decision',
            json=decision,headers=self.admin_headers())
        self.assertEqual(approved.status_code,200,approved.text)
        status=await self.client.get(path,headers=self.game_headers(self.db.ids[1]))
        self.assertEqual(status.json(),{'status':'ai','model_label':'safe-model'})
        async with self.db.sessions() as session:
            rows=(await session.scalars(select(NightAIRequest))).all()
            self.assertEqual(len(rows),1)
            self.assertEqual(rows[0].status,'approved')

    async def test_denial_replay_and_stale_decision(self):
        await self.db.running()
        path=f'/api/night-case/games/{self.db.game}/ai'
        requested=await self.client.post(path+'/request',
            json={'expected_epoch':0,'client_request_id':uuid4().hex},headers=self.game_headers(self.db.ids[0]))
        self.assertEqual(requested.status_code,200,requested.text)
        decision_path='/api/admin/night-case/ai/requests/'+requested.json()['result']['request_id']+'/decision'
        body={'decision':'deny','profile_id':None,'profile_revision':None,'caps':None,
              'client_request_id':uuid4().hex}
        denied=await self.client.post(decision_path,json=body,headers=self.admin_headers())
        self.assertEqual(denied.status_code,200,denied.text)
        self.assertEqual(denied.json()['result']['request_status'],'denied')
        replay=await self.client.post(decision_path,json=body,headers=self.admin_headers())
        self.assertEqual(replay.json()['result'],denied.json()['result'])
        stale=await self.client.post(decision_path,json={**body,'client_request_id':uuid4().hex},
            headers=self.admin_headers())
        self.assertEqual((stale.status_code,stale.json()['code']),(409,'request_stale'))
        game=await self.client.get(path,headers=self.game_headers(self.db.ids[1]))
        self.assertEqual(game.json(),{'status':'authored','model_label':None})


if __name__=='__main__': unittest.main()
