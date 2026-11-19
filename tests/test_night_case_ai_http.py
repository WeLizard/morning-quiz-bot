"""Unmounted AI HTTP adapters: identity, body, CSRF and secret boundaries."""
import json
import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import httpx
from fastapi import FastAPI

from application.night_case_ai import NightAIControlError
from web.night_case_ai_admin import make_night_case_ai_admin_router
from web.night_case_ai_routes import register_night_case_ai_routes
from web.night_case_ai_routes import _integer


ACTOR=uuid4()
GAME='game-test'
ORIGIN='https://testserver'


class FakeAI:
    def __init__(self): self.secret=None;self.calls=[]
    async def stage_or_activate_byok(self,**kw):
        self.secret=kw['secret'];self.calls.append(('byok',kw['account_id']))
        return {'result':{'status':'ai'},'replayed':False}
    async def request_admin(self,**kw):
        self.calls.append(('request',kw['account_id']))
        return {'result':{'request_status':'pending'},'replayed':False}
    async def use_authored(self,**kw): return {'result':{'status':'authored'},'replayed':False}
    async def save_profile_revision(self,**kw):
        self.secret=kw['secret'];self.calls.append(('save',kw['operator'].subject))
        return {'result':{'revision':1},'replayed':False}
    async def decide_request(self,**kw): return {'result':{'request_status':'denied'},'replayed':False}


class FakeViews:
    async def list_presets(self,actor): return {'items':[{'id':'openai'}]}
    async def get_ai_status(self,actor,game): return {'status':'authored','model_label':None}
    async def list_admin_profiles(self,principal,**kw): return {'items':[],'has_more':False}
    async def list_admin_requests(self,principal,**kw): return {'items':[],'has_more':False}


class FakeDatabase:
    def __init__(self): self.commits=0;self.rollbacks=0
    @asynccontextmanager
    async def transaction(self):
        try: yield object()
        except BaseException:
            self.rollbacks+=1;raise
        else: self.commits+=1


class FakeAuth:
    configured=True
    def __init__(self): self.current=SimpleNamespace(csrf='valid-csrf')
    def get_session(self,request): return self.current


class AIHTTPTests(unittest.IsolatedAsyncioTestCase):
    def app(self,*,enabled=True):
        app=FastAPI();ai=FakeAI();database=FakeDatabase();auth=FakeAuth()
        app.state.admin_database=database;app.state.admin_auth=auth
        @app.middleware('http')
        async def auth_state(request,call_next):
            if request.headers.get('x-test-admin')=='1': request.state.admin_session=auth.current
            return await call_next(request)
        @asynccontextmanager
        async def principal(request,identity,*,write=False):
            yield object(),SimpleNamespace(account_id=ACTOR)
        async def body(request,*,max_bytes):
            value=await request.body()
            if len(value)>max_bytes: raise NightAIControlError('invalid_config',422)
            return value
        register_night_case_ai_routes(app,principal=principal,identity_for=lambda r,i:i or 'guest',
            read_body=body,enabled=enabled,service_factory=lambda s:ai,views_factory=lambda s:FakeViews())
        app.include_router(make_night_case_ai_admin_router(enabled=enabled,deployment_id='test',
            service_factory=lambda s:ai,views_factory=lambda s:FakeViews()))
        return app,ai,database,auth

    async def test_off_and_pinned_game_identity_csrf(self):
        app,ai,_,_=self.app(enabled=False)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url=ORIGIN) as client:
            self.assertEqual((await client.get('/api/night-case/ai/presets')).status_code,404)
            self.assertEqual((await client.get('/api/admin/night-case/ai/profiles')).status_code,404)
        app,ai,_,_=self.app()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url=ORIGIN) as client:
            self.assertEqual((await client.get('/api/night-case/ai/presets')).json()['items'],[{'id':'openai'}])
            self.assertEqual((await client.get(f'/api/night-case/games/{GAME}/ai')).json()['code'],'profile_changed')
            path=f'/api/night-case/games/{GAME}/ai/request'
            data={'expected_epoch':0,'client_request_id':'request0001'}
            self.assertEqual((await client.post(path,json=data,headers={'x-night-expected-viewer':str(ACTOR)})).status_code,403)
            self.assertEqual((await client.post(path,json=data,headers={'origin':ORIGIN,'x-guest-csrf':'1',
                'sec-fetch-site':'cross-site','x-night-expected-viewer':str(ACTOR)})).status_code,403)
            self.assertEqual((await client.post(path,json=data,headers={'origin':ORIGIN,'x-guest-csrf':'1',
                'x-night-expected-viewer':str(uuid4())})).json()['code'],'profile_changed')
            good=await client.post(path,json=data,headers={'origin':ORIGIN,'x-guest-csrf':'1',
                'x-night-expected-viewer':str(ACTOR)})
            self.assertEqual(good.status_code,200)
            self.assertEqual(ai.calls,[('request',ACTOR)])

    async def test_secret_body_duplicate_fields_and_error_never_echo(self):
        app,ai,_,_=self.app()
        path=f'/api/night-case/games/{GAME}/ai/byok'
        headers={'origin':ORIGIN,'x-guest-csrf':'1','x-night-expected-viewer':str(ACTOR),
                 'content-type':'application/json'}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url=ORIGIN) as client:
            raw=b'{"expected_epoch":0,"settings":{},"secret":"KEY_CANARY","secret":"OTHER","client_request_id":"req00001"}'
            bad=await client.post(path,content=raw,headers=headers)
            self.assertEqual(bad.status_code,422)
            self.assertNotIn('KEY_CANARY',bad.text)
            self.assertEqual((await client.post(path,content=raw,headers={
                'content-type':'application/json','x-night-expected-viewer':str(ACTOR)})).status_code,403)
            data={'expected_epoch':0,'settings':{'preset':'openai','model_id':'safe'},
                  'secret':'  KEY_CANARY  ','client_request_id':'req00001'}
            good=await client.post(path,json=data,headers=headers)
            self.assertEqual((good.status_code,ai.secret),(200,b'  KEY_CANARY  '))
            self.assertNotIn('KEY_CANARY',good.text)

    async def test_admin_requires_live_session_csrf_and_rechecks_before_commit(self):
        app,ai,database,auth=self.app()
        path='/api/admin/night-case/ai/profiles'
        headers={'origin':ORIGIN,'x-csrf-token':'valid-csrf','x-test-admin':'1'}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url=ORIGIN) as client:
            self.assertEqual((await client.get(path)).status_code,401)
            self.assertEqual((await client.get('/api/admin/night-case/ai/requests?limit=bad')).status_code,401)
            self.assertEqual((await client.post(path,json={},headers={'x-test-admin':'1'})).status_code,403)
            data={'expected_revision':0,'label':'Safe','settings':{},'client_request_id':'req00001',
                  'secret':'ADMIN_KEY_CANARY'}
            bad=await client.post(path,content=json.dumps(data).replace('"secret": "ADMIN_KEY_CANARY"',
                '"secret": "ADMIN_KEY_CANARY", "secret": "OTHER"'),headers={**headers,'content-type':'application/json'})
            self.assertEqual(bad.status_code,422)
            self.assertNotIn('ADMIN_KEY_CANARY',bad.text)
            good=await client.post(path,json=data,headers=headers)
            self.assertEqual((good.status_code,ai.secret,database.commits),(200,b'ADMIN_KEY_CANARY',1))
            self.assertNotIn('ADMIN_KEY_CANARY',good.text)
            async def logout(**kw):
                auth.current=SimpleNamespace(csrf='another')
                return {'result':{'revision':2},'replayed':False}
            ai.save_profile_revision=logout
            stale=await client.post(path,json=data,headers=headers)
            self.assertEqual((stale.status_code,database.rollbacks),(401,1))

    async def test_closed_integer_and_enum_inputs_fail_before_service(self):
        for invalid in (True,False,None,1.0,[],{},-1,2147483648,9223372036854775808):
            with self.subTest(invalid=invalid),self.assertRaises(NightAIControlError):
                _integer(invalid)
        app,ai,database,_=self.app()
        admin={'origin':ORIGIN,'x-csrf-token':'valid-csrf','x-test-admin':'1'}
        game={'origin':ORIGIN,'x-guest-csrf':'1','x-night-expected-viewer':str(ACTOR)}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app,raise_app_exceptions=False),base_url=ORIGIN) as client:
            for invalid in (True,1.2,[],{},None,2147483648):
                with self.subTest(route='game_epoch',invalid=invalid):
                    result=await client.post(f'/api/night-case/games/{GAME}/ai/request',
                        json={'expected_epoch':invalid,'client_request_id':'request0001'},headers=game)
                    self.assertEqual(result.status_code,422)
                    self.assertNotIn(str(invalid),result.text)
                with self.subTest(route='admin_revision',invalid=invalid):
                    result=await client.post('/api/admin/night-case/ai/profiles',
                        json={'expected_revision':invalid,'label':'Safe','settings':{},'client_request_id':'request0001'},headers=admin)
                    self.assertEqual(result.status_code,422)
            for invalid in ([],{},None,1,True,2147483648):
                with self.subTest(route='decision_enum',invalid=invalid):
                    result=await client.post(f'/api/admin/night-case/ai/requests/{uuid4()}/decision',
                        json={'decision':invalid,'profile_id':None,'profile_revision':None,
                              'caps':None,'client_request_id':'request0001'},headers=admin)
                    self.assertEqual(result.status_code,422)
            result=await client.get(f'/api/admin/night-case/ai/profiles/{uuid4()}/revisions/9223372036854775808',headers=admin)
            self.assertEqual(result.status_code,422)
            self.assertEqual(ai.calls,[])


if __name__=='__main__': unittest.main()
