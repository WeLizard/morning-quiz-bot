"""Read-only AI views against real access and isolated PostgreSQL tables."""

import asyncio
import importlib.util
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4
import unittest

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from application.night_case import NightCaseApplicationService
from application.night_case_ai import AdminPrincipal, BindingCaps, NightAIControlError, NightAIControlService
from application.night_case_ai_views import NightCaseAIViews
from config.night_case_ai import EndpointPolicy, ModelCapabilities, ProfileRegistry, build_profile
from domain.night_case_v2_format import compile_v2, load_v2
from storage.models import (Account, Base, Game, GamePlayer, NightCase,
                            NightGameSealed, Room, RoomMembership)
from storage.night_ai_models import (NightAIBinding, NightAICredential,
                                     NightAIGameControl, NightAIProfile,
                                     NightAIProfileRevision, NightAIRequest)
from storage.admin_actions import operation_fence


NOW=datetime(2026,11,16,12,tzinfo=timezone.utc)
CASE=Path(__file__).parent/'fixtures'/'night_city'/'core_case_v2.json'


def migration(revision):
    path=next((Path(__file__).resolve().parents[1]/'alembic/versions').glob('20261116_'+revision+'_*.py'))
    spec=importlib.util.spec_from_file_location('views_migration_'+revision,path)
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


class AIViewsPostgresTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from tests.night_case_test_database import night_case_test_url
        url=night_case_test_url()
        if os.getenv('TEST_DATABASE_URL')!=url:
            raise RuntimeError('AI views PG requires TEST_DATABASE_URL to match the guarded Night Case URL')
        self.database_url=url
        self.schema='mqb_ai_views_'+uuid4().hex
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
        self.ids=[uuid4() for _ in range(3)]
        self.game='aiview_'+uuid4().hex
        self.case=compile_v2(load_v2(CASE.read_bytes()))
        self.registry=ProfileRegistry.cloud({('openai','safe-model'):ModelCapabilities()})
        case_doc=self.case.document()
        async with self.sessions.begin() as s:
            s.add_all([Account(id=aid,display_name=f'Visible {idx}') for idx,aid in enumerate(self.ids)])
            await s.flush()
            s.add(Room(id=self.game,kind='standalone',title='Safe room',owner_account_id=self.ids[0]))
            await s.flush()
            s.add_all([RoomMembership(room_id=self.game,account_id=aid,role='member',status='active') for aid in self.ids])
            s.add(NightCase(case_id=self.case.case_id,version=self.case.case_version,
                content_hash=self.case.content_hash,content=case_doc,compiler_version=self.case.compiler_version,
                engine_build='night-case-core/1',validation_report={},registered_at=NOW,
                registered_operator_id='operator:test',admission='registered'))
            await s.flush()
            s.add(Game(id=self.game,room_id=self.game,mode='night_case',status='lobby',phase='lobby',state={}))
            await s.flush()
            s.add(NightGameSealed(game_id=self.game,case_id=self.case.case_id,version=self.case.case_version,
                content_hash=self.case.content_hash,rules={},rules_hash='0'*64,
                engine_build='night-case-core/1',compiler_version=self.case.compiler_version,
                snapshot_hash='0'*64,lifecycle='lobby',lobby={},kernel=None))

    async def _cleanup(self):
        async with self.engine.begin() as conn: await conn.exec_driver_sql('DROP SCHEMA '+self.schema+' CASCADE')
        await self.engine.dispose()

    def views(self,s,**readiness):
        app=NightCaseApplicationService(s,lambda:NOW,None)
        ai=NightAIControlService(s,lambda:NOW,self.registry,None,None,environment_id='test')
        return NightCaseAIViews(s,app,ai,**readiness)

    async def running(self):
        async with self.sessions.begin() as s:
            game=await s.get(Game,self.game); game.status='running'; game.phase='investigation'
            sealed=await s.get(NightGameSealed,self.game); sealed.lifecycle='running'; sealed.lobby=None
            s.add_all([GamePlayer(game_id=self.game,account_id=self.ids[i],seat=str(i),status='active',
                public_state={},private_state={}) for i in range(2)])
            s.add(NightAIGameControl(game_id=self.game,starter_account_id=self.ids[0],epoch=0,
                current_binding_id=None,updated_at=NOW))

    async def install_local_binding(self, *, bearer=False):
        await self.running()
        policy=EndpointPolicy('local:ollama',1,'http://127.0.0.1:11434','trusted_local',None)
        self.registry=ProfileRegistry({('local:ollama',1):policy},{('ollama','local-model'):ModelCapabilities()})
        credential_id=uuid4() if bearer else None
        config=build_profile(registry=self.registry,preset='ollama',model_id='local-model',
            credential_id=credential_id,endpoint_policy=('local:ollama',1),
            auth_mode='bearer' if bearer else 'none').document()
        profile_id=uuid4();binding_id=uuid4()
        async with self.sessions.begin() as s:
            if credential_id:
                s.add(NightAICredential(id=credential_id,scope='admin',owner_subject='admin:test:operator',
                    game_id=None,preset='ollama',status='usable',key_id='local-canary',nonce=b'2'*12,
                    ciphertext=b'LOCAL_SECRET_CANARY!',aad_version=1,created_at=NOW))
            s.add(NightAIProfile(id=profile_id,scope='admin',game_id=None,label='Local',current_revision=1,
                enabled=True,is_default=False,created_by_subject='admin:test:operator',created_at=NOW))
            await s.flush()
            s.add(NightAIProfileRevision(profile_id=profile_id,revision=1,config=config,
                config_hash=config['config_hash'],credential_id=credential_id,
                created_by_subject='admin:test:operator',created_at=NOW))
            await s.flush()
            s.add(NightAIBinding(id=binding_id,game_id=self.game,epoch=1,mode='admin',
                profile_id=profile_id,profile_revision=1,config_hash=config['config_hash'],
                granted_by_subject='admin:test:operator',status='active',
                valid_until=NOW+timedelta(days=1),caps=BindingCaps().document(),health='ok',created_at=NOW))
            control=await s.get(NightAIGameControl,self.game);control.epoch=1;control.current_binding_id=binding_id

    async def test_lobby_acl_shape_and_no_bootstrap_write(self):
        async with self.sessions.begin() as s:
            s.add(NightAICredential(id=uuid4(),scope='game',owner_subject='account:'+str(self.ids[0]),
                game_id=self.game,preset='openai',status='staged',key_id='lobby-canary',nonce=b'1'*12,
                ciphertext=b'STAGED_CIPHERTEXT_CANARY',aad_version=1,created_at=NOW,
                expires_at=NOW+timedelta(hours=1)))
        sql=[]
        def capture(conn,cursor,statement,params,context,executemany): sql.append(statement.lower())
        event.listen(self.engine.sync_engine,'before_cursor_execute',capture)
        try:
            async with self.sessions() as s:
                views=self.views(s)
                owner=await views.get_ai_status(self.ids[0],self.game)
                other=await views.get_ai_status(self.ids[1],self.game)
                self.assertEqual((owner['status'],owner['can_configure'],owner['epoch'],
                                  owner['mode'],owner['credential_configured']),('authored',True,0,'byok',True))
                self.assertEqual(other,{'status':'authored','model_label':None})
                self.assertEqual([p['id'] for p in (await views.list_presets(self.ids[0]))['items']],['openai'])
                with self.assertRaises(NightAIControlError): await views.get_ai_status(self.ids[2],'missing')
                self.assertFalse(s.dirty)
        finally:
            event.remove(self.engine.sync_engine,'before_cursor_execute',capture)
        self.assertFalse(any(q.lstrip().startswith(('insert ','update ','delete ')) for q in sql))
        self.assertFalse(any('key_id' in q or 'ciphertext' in q or 'nonce' in q for q in sql))

    async def test_running_own_binding_public_shape_admin_whitelist(self):
        await self.running()
        cred=uuid4();profile=uuid4();binding=uuid4()
        config=build_profile(registry=self.registry,preset='openai',model_id='safe-model',credential_id=cred).document()
        async with self.sessions.begin() as s:
            s.add(NightAICredential(id=cred,scope='admin',owner_subject='admin:test:operator',game_id=None,
                preset='openai',status='usable',key_id='canary-key-id',nonce=b'0'*12,
                ciphertext=b'SECRET_CIPHERTEXT_CANARY',aad_version=1,created_at=NOW))
            s.add(NightAIProfile(id=profile,scope='admin',game_id=None,label='Admin profile',current_revision=1,
                enabled=True,is_default=False,created_by_subject='admin:test:operator',created_at=NOW))
            await s.flush()
            s.add(NightAIProfileRevision(profile_id=profile,revision=1,config=config,config_hash=config['config_hash'],
                credential_id=cred,created_by_subject='admin:test:operator',created_at=NOW))
            await s.flush()
            s.add(NightAIBinding(id=binding,game_id=self.game,epoch=1,mode='admin',profile_id=profile,
                profile_revision=1,config_hash=config['config_hash'],granted_by_subject='admin:test:operator',
                status='active',valid_until=NOW+timedelta(days=1),caps=BindingCaps().document(),
                health='ok',created_at=NOW))
            control=await s.get(NightAIGameControl,self.game);control.epoch=1;control.current_binding_id=binding
        sql=[]
        def capture(conn,cursor,statement,params,context,executemany): sql.append(statement.lower())
        event.listen(self.engine.sync_engine,'before_cursor_execute',capture)
        try:
            async with self.sessions() as s:
                views=self.views(s,runtime_enabled=True,external_enabled=True,vault_ready=True)
                owner=await views.get_ai_status(self.ids[0],self.game)
                other=await views.get_ai_status(self.ids[1],self.game)
                self.assertEqual((owner['status'],owner['model_label'],owner['can_configure']),('ai','safe-model',True))
                self.assertEqual(other,{'status':'ai','model_label':'safe-model'})
                self.assertEqual((await self.views(s,runtime_enabled=True,external_enabled=False,
                    vault_ready=True).get_ai_status(self.ids[1],self.game))['status'],'fallback')
                admin=AdminPrincipal('test')
                profiles=await views.list_admin_profiles(admin,limit=1)
                detail=await views.get_admin_profile_revision(admin,profile,1)
                revisions=await views.list_admin_profile_revisions(admin,profile,limit=1)
                bindings=await views.list_admin_bindings(admin,limit=1)
                self.assertEqual((profiles['items'][0]['model_id'],detail['model_id']),('safe-model','safe-model'))
                self.assertEqual(revisions,{'items':[{'revision':1,'created_at':NOW.isoformat()}],'has_more':False})
                self.assertEqual(bindings['items'][0]['binding_id'],str(binding))
                self.assertNotIn('SECRET_CIPHERTEXT_CANARY',json.dumps([owner,other,profiles,detail,bindings]))
                with self.assertRaises(NightAIControlError): await views.get_admin_profile_revision(AdminPrincipal('other'),profile,1)
                with self.assertRaises(NightAIControlError): await views.list_admin_profiles(admin,limit=True)
                self.assertFalse(s.dirty)
        finally:
            event.remove(self.engine.sync_engine,'before_cursor_execute',capture)
        self.assertFalse(any('key_id' in q or 'ciphertext' in q or 'nonce' in q for q in sql))
        self.assertFalse(any(q.lstrip().startswith(('insert ','update ','delete ')) for q in sql))

        async with self.sessions.begin() as s:
            game=await s.get(Game,self.game);game.status='interrupted'
            sealed=await s.get(NightGameSealed,self.game);sealed.lifecycle='interrupted'
        async with self.sessions() as s:
            status=await self.views(s,runtime_enabled=True,external_enabled=True,vault_ready=True).get_ai_status(self.ids[0],self.game)
            self.assertEqual((status['status'],status['can_configure']),('fallback',False))
        async with self.sessions.begin() as s:
            row=await s.get(NightAIProfile,profile); row.enabled=False
        async with self.sessions() as s:
            status=await self.views(s,runtime_enabled=True,external_enabled=True,vault_ready=True).get_ai_status(self.ids[1],self.game)
            self.assertEqual(status,{'status':'fallback','model_label':None})

    async def test_local_anonymous_is_ready_without_external_or_vault(self):
        await self.install_local_binding()
        sql=[]
        def capture(conn,cursor,statement,params,context,executemany): sql.append(statement.lower())
        event.listen(self.engine.sync_engine,'before_cursor_execute',capture)
        try:
            async with self.sessions() as s:
                status=await self.views(s,runtime_enabled=True,external_enabled=False,
                    vault_ready=False).get_ai_status(self.ids[1],self.game)
                self.assertEqual(status,{'status':'ai','model_label':'local-model'})
        finally:
            event.remove(self.engine.sync_engine,'before_cursor_execute',capture)
        self.assertFalse(any('key_id' in q or 'ciphertext' in q or 'nonce' in q for q in sql))

    async def test_local_bearer_requires_vault_but_not_external(self):
        await self.install_local_binding(bearer=True)
        async with self.sessions() as s:
            self.assertEqual((await self.views(s,runtime_enabled=True,external_enabled=False,
                vault_ready=False).get_ai_status(self.ids[1],self.game))['status'],'fallback')
            self.assertEqual((await self.views(s,runtime_enabled=True,external_enabled=False,
                vault_ready=True).get_ai_status(self.ids[1],self.game))['status'],'ai')

    async def test_admin_read_waits_for_exclusive_fence_then_denies_moderated_account(self):
        async with self.sessions.begin() as holder:
            await operation_fence(holder,exclusive=True)
            async def read():
                async with self.sessions() as s:
                    return await self.views(s).list_admin_requests(AdminPrincipal('test',self.ids[0]))
            task=asyncio.create_task(read())
            await asyncio.sleep(0.2)
            blocked=not task.done()
            account=await holder.get(Account,self.ids[0]);account.bot_blocked=True
        self.assertTrue(blocked,'read bypassed the shared platform fence')
        with self.assertRaises(NightAIControlError) as found:
            await asyncio.wait_for(task,3)
        self.assertEqual(found.exception.code,'account_unavailable')

    async def test_pending_request_inbox_and_pagination_are_bounded(self):
        await self.running()
        async with self.sessions.begin() as s:
            control=await s.get(NightAIGameControl,self.game); control.epoch=1
            s.add(NightAIRequest(id=uuid4(),game_id=self.game,epoch=1,
                requester_account_id=self.ids[0],status='pending',created_at=NOW,
                expires_at=NOW+timedelta(hours=24)))
        async with self.sessions() as s:
            views=self.views(s)
            owner=await views.get_ai_status(self.ids[0],self.game)
            other=await views.get_ai_status(self.ids[1],self.game)
            self.assertEqual((owner['status'],owner['mode'],owner['request_status']),('pending','admin','pending'))
            self.assertEqual(other,{'status':'pending','model_label':None})
            inbox=await views.list_admin_requests(AdminPrincipal('test'),limit=1)
            self.assertEqual((len(inbox['items']),inbox['has_more']), (1,False))
            self.assertEqual((inbox['items'][0]['requester_display_name'],inbox['items'][0]['room_title']),
                             ('Visible 0','Safe room'))
            with self.assertRaises(NightAIControlError): await views.list_admin_requests(AdminPrincipal('test'),offset=10001)

    async def test_starter_fog_and_ghost_can_configure_but_departed_cannot(self):
        await self.running()
        for seat_status,expected in (('fog',True),('ghost',True),('departed',False)):
            async with self.sessions.begin() as s:
                seat=await s.get(GamePlayer,(self.game,self.ids[0]));seat.status=seat_status
            async with self.sessions() as s:
                views=self.views(s)
                owner=await views.get_ai_status(self.ids[0],self.game)
                other=await views.get_ai_status(self.ids[1],self.game)
                self.assertEqual(owner['can_configure'],expected)
                self.assertEqual(other,{'status':'authored','model_label':None})


if __name__=='__main__': unittest.main()
