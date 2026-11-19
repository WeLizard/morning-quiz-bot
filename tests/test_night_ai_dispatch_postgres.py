"""0050 real PG invariants in an owned schema; never reset public/working data."""
import asyncio
from datetime import datetime, timedelta, timezone
import importlib.util
import os
from pathlib import Path
import unittest
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import insert, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from application.night_case_ai import BindingCaps
from storage.models import Account, Base, Game, Room, NightRenderJob, NightRendering, NightNarratorLimit
from storage.night_ai_models import NightAIProfile, NightAIProfileRevision, NightAIBinding, NightAIGameControl, NightAIIntentRequest, NightAIJobBinding, NightAIOperation, NightAIDispatchAttempt
from storage.night_ai_dispatch import DispatchSource, ReserveSpec, QuotaDebit, NightAIDispatchRepository, DispatchConflict
from storage.night_cases import json_hash


def migration(revision):
    path=next((Path(__file__).resolve().parents[1]/'alembic/versions').glob('20261116_'+revision+'_*.py'))
    spec=importlib.util.spec_from_file_location('dispatch_migration_'+revision,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


class DispatchPostgresTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from tests.night_case_test_database import night_case_test_url
        url=night_case_test_url()
        if os.getenv('TEST_DATABASE_URL')!=url:
            raise RuntimeError('dispatch tests require TEST_DATABASE_URL to match the guarded Night Case URL')
        self.schema='mqb_dispatch_'+uuid4().hex
        admin=create_async_engine(url)
        async with admin.begin() as conn: await conn.exec_driver_sql('CREATE SCHEMA '+self.schema)
        await admin.dispose()
        # No public fallback: create_all(checkfirst) otherwise finds public
        # parents and silently skips creating isolated copies.
        self.engine=create_async_engine(url,connect_args={'server_settings':{'search_path':self.schema}})
        self.addAsyncCleanup(self._cleanup)
        self.sessions=async_sessionmaker(self.engine,expire_on_commit=False)
        async with self.engine.begin() as conn:
            await conn.run_sync(lambda sync:Base.metadata.create_all(sync,tables=[t for t in Base.metadata.sorted_tables if not t.name.startswith('night_ai_')]))
        await self.apply('0049','upgrade')
        self.now=datetime(2026,11,16,12,tzinfo=timezone.utc)
        self.owner=uuid4();self.game=uuid4().hex;self.binding=uuid4();self.intent=uuid4();self.job=uuid4().hex
        self.config_hash='a'*64;self.caps=BindingCaps().document();self.caps_hash=json_hash(self.caps)
        async with self.sessions.begin() as s:
            s.add(Account(id=self.owner,display_name='synthetic'));await s.flush()
            s.add(Room(id=self.game,kind='standalone',owner_account_id=self.owner));await s.flush()
            s.add(Game(id=self.game,room_id=self.game,mode='night_case',status='running',phase='investigation',state={'synthetic':'retained'},started_at=self.now));await s.flush()
            profile=uuid4()
            s.add(NightAIProfile(id=profile,scope='admin',game_id=None,label='synthetic',current_revision=1,enabled=True,is_default=False,created_by_subject='admin:synthetic:operator',created_at=self.now))
            await s.flush()
            adapter='gigachat_chat' if self._testMethodName=='test_gigachat_oauth_claim_cas_is_once_per_permit' else 'openai_chat'
            s.add(NightAIProfileRevision(profile_id=profile,revision=1,config={'config_hash':self.config_hash,'preset':'gigachat' if adapter=='gigachat_chat' else 'openai','adapter':adapter,'credential_id':None},config_hash=self.config_hash,created_by_subject='admin:synthetic:operator',created_at=self.now))
            await s.flush()
            # 0049 has no inflight_permit_id yet: use its frozen SQL, not current ORM insert.
            await s.execute(text("""INSERT INTO night_ai_bindings(id,game_id,epoch,mode,profile_id,profile_revision,
                config_hash,granted_by_subject,status,valid_until,caps,health,created_at)
                VALUES(:id,:game,1,'admin',:profile,1,:hash,'admin:synthetic:operator','active',:expiry,CAST(:caps AS jsonb),'ok',:now)"""),
                {'id':self.binding,'game':self.game,'profile':profile,'hash':self.config_hash,'expiry':self.now+timedelta(days=1),'caps':__import__('json').dumps(self.caps),'now':self.now})
            s.add(NightAIGameControl(game_id=self.game,starter_account_id=self.owner,epoch=1,current_binding_id=self.binding,updated_at=self.now))
            s.add(NightAIIntentRequest(id=self.intent,game_id=self.game,requester_account_id=self.owner,client_request_id='retained-intent',fingerprint='d'*64,epoch=1,binding_id=self.binding,
                token={'config_hash':self.config_hash,'caps_hash':self.caps_hash},legal_candidates={},status='prepared',created_at=self.now,expires_at=self.now+timedelta(seconds=120)))
            s.add(NightRenderJob(job_id=self.job,game_id=self.game,cause_id='synthetic',kind='scene',audience_key='public',knowledge_revision=0,template_version='synthetic/1',frozen_view={},input_hash='b'*64,expires_at=self.now+timedelta(seconds=120),fallback='retained authored'))
            await s.flush()
            s.add(NightAIJobBinding(job_id=self.job,game_id=self.game,epoch=1,binding_id=self.binding,created_at=self.now))
            s.add(NightAIOperation(principal_subject='admin:synthetic:operator',client_request_id='retained-operation',operation='synthetic',target_id=self.game,fingerprint='e'*64,fingerprint_version='sha256:1',safe_result={'retained':True},created_at=self.now))
        self.before=await self.fingerprints()

    async def _cleanup(self):
        async with self.engine.begin() as conn: await conn.exec_driver_sql('DROP SCHEMA '+self.schema+' CASCADE')
        await self.engine.dispose()

    async def apply(self,revision,direction):
        async with self.engine.begin() as conn:
            def run(sync):
                with Operations.context(MigrationContext.configure(sync)):getattr(migration(revision),direction)()
            await conn.run_sync(run)

    async def fingerprints(self):
        async with self.engine.connect() as c:
            result={}
            for table in ('games','night_ai_operations','night_ai_bindings','night_ai_intent_requests','night_render_jobs','night_ai_job_bindings'):
                result[table]=list((await c.execute(text("SELECT md5((to_jsonb(t)-'inflight_permit_id')::text) FROM "+table+" t ORDER BY 1"))).scalars())
            return result

    def spec(self,kind='intent',**changes):
        now=changes.pop('reserved_at',self.now)
        scopes=[('nai:global:minute',now.replace(second=0,microsecond=0),10,1000000),
            ('nai:actor:'+str(self.owner)+':minute',now.replace(second=0,microsecond=0),4,1000000),
            ('game:'+self.game+':day',now.replace(hour=0,minute=0,second=0,microsecond=0),60,120000),
            ('game:'+self.game+':total',datetime(1970,1,1,tzinfo=timezone.utc),420,840000)]
        args=dict(id=uuid4(),source=DispatchSource(kind,self.intent if kind=='intent' else self.job),game_id=self.game,binding_id=self.binding,epoch=1,attempt_no=1,
            config_hash=self.config_hash,caps_hash=self.caps_hash,payload_hash='f'*64,source_expires_at=self.now+timedelta(seconds=120),worker_id='synthetic-worker',lease_nonce=uuid4(),
            reserved_at=now,lease_until=now+timedelta(seconds=30),network_deadline=now+timedelta(seconds=12),reserved_input_units=200,reserved_output_tokens=100,
            quota_debits=tuple(QuotaDebit(scope,period,1,300,req,tok) for scope,period,req,tok in scopes))
        return ReserveSpec(**(args|changes))

    async def test_upgrade_preserves_retained_rows_empty_down_and_reupgrade(self):
        await self.apply('0050','upgrade');self.assertEqual(await self.fingerprints(),self.before)
        await self.apply('0050','downgrade');self.assertEqual(await self.fingerprints(),self.before)
        await self.apply('0050','upgrade');self.assertEqual(await self.fingerprints(),self.before)

    async def test_legacy_lease_preflight_refuses_without_alter(self):
        async with self.sessions.begin() as s:
            await s.execute(text('UPDATE night_ai_bindings SET inflight_job_id=:job,inflight_lease_until=:expiry WHERE id=:id'),{'job':self.job,'expiry':self.now+timedelta(seconds=30),'id':self.binding})
        with self.assertRaisesRegex(DBAPIError,'night_ai_dispatch_drain_required'):await self.apply('0050','upgrade')
        async with self.engine.connect() as c:
            self.assertIsNone(await c.scalar(text('SELECT to_regclass(:table)'),{'table':self.schema+'.night_ai_dispatch_attempts'}))

    async def test_send_cas_terminal_immutability_and_retained_down_refusal(self):
        await self.apply('0050','upgrade');spec=self.spec()
        async with self.sessions.begin() as s:await NightAIDispatchRepository(s).reserve(spec)
        async with self.sessions.begin() as s:
            repo=NightAIDispatchRepository(s)
            self.assertFalse(await repo.authorize_send(spec.id,uuid4(),self.now))
            self.assertTrue(await repo.authorize_send(spec.id,spec.lease_nonce,self.now))
            self.assertFalse(await repo.authorize_send(spec.id,spec.lease_nonce,self.now))
            self.assertTrue(await repo.finish(spec.id,spec.lease_nonce,now=self.now+timedelta(seconds=1),status='succeeded',response_hash='c'*64,usage={'input_tokens':5,'output_tokens':7}))
        with self.assertRaisesRegex(DBAPIError,'night_ai_dispatch_transition'):
            async with self.sessions.begin() as s:await s.execute(text("UPDATE night_ai_dispatch_attempts SET status='sending',finished_at=NULL WHERE id=:id"),{'id':spec.id})
        with self.assertRaisesRegex(DBAPIError,'night_ai_dispatch_retention_required'):await self.apply('0050','downgrade')
        self.assertEqual(await self.fingerprints(),self.before)

    async def test_two_sessions_intent_render_compete_for_one_slot_and_debit(self):
        await self.apply('0050','upgrade')
        async def reserve(spec):
            try:
                async with self.sessions.begin() as s:await NightAIDispatchRepository(s).reserve(spec)
                return 'reserved'
            except DispatchConflict as error:return str(error)
        outcomes=await asyncio.gather(reserve(self.spec()),reserve(self.spec('render')))
        self.assertCountEqual(outcomes,['reserved','binding_busy'])
        async with self.sessions() as s:
            self.assertEqual(list((await s.scalars(select(NightNarratorLimit.reserved_requests))).all()),[1]*4)

    async def test_direct_render_reservation_matches_source_lease_and_cancel_before_close(self):
        await self.apply('0050','upgrade');spec=self.spec('render')
        async with self.sessions.begin() as s:await NightAIDispatchRepository(s).reserve(spec)
        async with self.sessions.begin() as s:
            job=await s.get(NightRenderJob,self.job)
            self.assertEqual((job.status,job.attempts,job.lease_owner,job.lease_until),('leased',1,spec.worker_id,spec.lease_until))
        with self.assertRaisesRegex(DBAPIError,'night_ai_dispatch_render_lease'):
            async with self.sessions.begin() as s:await s.execute(update(NightRenderJob).where(NightRenderJob.job_id==self.job).values(lease_until=None))
        with self.assertRaisesRegex(DBAPIError,'night_ai_dispatch_slot'):
            async with self.sessions.begin() as s:await s.execute(update(NightAIBinding).where(NightAIBinding.id==self.binding).values(status='revoked',closed_at=self.now))
        async with self.sessions.begin() as s:
            repo=NightAIDispatchRepository(s)
            self.assertTrue(await repo.cancel_binding(self.binding,now=self.now,error_code='stale'))
            await s.execute(update(NightAIBinding).where(NightAIBinding.id==self.binding).values(status='revoked',closed_at=self.now))
        async with self.sessions.begin() as s:
            self.assertFalse(await NightAIDispatchRepository(s).finish(spec.id,spec.lease_nonce,now=self.now,status='expired'))
            self.assertEqual((await s.get(NightRenderJob,self.job)).status,'fallback')

    async def test_gigachat_oauth_claim_cas_is_once_per_permit(self):
        await self.apply('0050','upgrade');spec=self.spec()
        async with self.sessions.begin() as s:await NightAIDispatchRepository(s).reserve(spec)
        async with self.sessions.begin() as s:
            repo=NightAIDispatchRepository(s)
            self.assertFalse(await repo.authorize_oauth(spec.id,uuid4(),self.now))
            self.assertTrue(await repo.authorize_oauth(spec.id,spec.lease_nonce,self.now))
            self.assertFalse(await repo.authorize_oauth(spec.id,spec.lease_nonce,self.now))
            self.assertTrue(await repo.authorize_send(spec.id,spec.lease_nonce,self.now+timedelta(seconds=2)))
            self.assertFalse(await repo.authorize_oauth(spec.id,spec.lease_nonce,self.now+timedelta(seconds=3)))
            self.assertTrue(await repo.finish(spec.id,spec.lease_nonce,now=self.now+timedelta(seconds=3),
                status='failed',error_code='auth_error',retry_after=self.now+timedelta(seconds=5)))
        second=self.spec(attempt_no=2,reserved_at=self.now+timedelta(seconds=5))
        async with self.sessions.begin() as s:
            await NightAIDispatchRepository(s).reserve(second)
            self.assertTrue(await NightAIDispatchRepository(s).authorize_oauth(second.id,second.lease_nonce,second.reserved_at))

    async def test_quota_exhaustion_rolls_back_all_debits_and_new_counter_retention_blocks_down(self):
        await self.apply('0050','upgrade');spec=self.spec()
        # Exhaust the last sorted row to exercise rollback after earlier debits.
        last=sorted(spec.quota_debits,key=lambda q:(q.scope,q.period_start))[-1]
        async with self.sessions.begin() as s:
            s.add(NightNarratorLimit(scope=last.scope,period_start=last.period_start,reserved_requests=last.max_requests,reserved_tokens=0))
        with self.assertRaisesRegex(DispatchConflict,'quota_exhausted'):
            async with self.sessions.begin() as s:await NightAIDispatchRepository(s).reserve(spec)
        async with self.sessions() as s:
            self.assertEqual(await s.scalar(text('SELECT count(*) FROM night_ai_dispatch_attempts')),0)
            self.assertEqual(await s.scalar(text('SELECT count(*) FROM night_narrator_limits')),1)
            self.assertIsNone((await s.get(NightAIBinding,self.binding)).inflight_permit_id)
        with self.assertRaisesRegex(DBAPIError,'night_ai_dispatch_retention_required'):await self.apply('0050','downgrade')

    async def test_wrong_source_pin_missing_slot_and_unknown_usage_fail_closed(self):
        await self.apply('0050','upgrade')
        for changed,pattern in [({'caps_hash':'1'*64},'night_ai_dispatch_binding_pin'),({'source':DispatchSource('intent',uuid4())},'night_ai_dispatch_intent_pin')]:
            with self.assertRaisesRegex(DBAPIError,pattern):
                async with self.sessions.begin() as s:await NightAIDispatchRepository(s).reserve(self.spec(**changed))
        spec=self.spec()
        async with self.sessions.begin() as s:await NightAIDispatchRepository(s).reserve(spec)
        with self.assertRaisesRegex(DBAPIError,'night_ai_dispatch_oauth'):
            async with self.sessions.begin() as s:await NightAIDispatchRepository(s).authorize_oauth(spec.id,spec.lease_nonce,self.now)
        with self.assertRaisesRegex(DBAPIError,'night_ai_dispatch_slot'):
            async with self.sessions.begin() as s:await s.execute(update(NightAIBinding).where(NightAIBinding.id==self.binding).values(inflight_permit_id=None,inflight_lease_until=None))
        with self.assertRaisesRegex(DBAPIError,'night_ai_dispatch_usage'):
            async with self.sessions.begin() as s:await s.execute(text("UPDATE night_ai_dispatch_attempts SET status='failed',finished_at=:now,usage='{}'::jsonb WHERE id=:id"),{'id':spec.id,'now':self.now})

    async def test_observed_retry_is_separate_attempt_and_old_cleanup_cannot_clear_new_slot(self):
        await self.apply('0050','upgrade');first=self.spec()
        async with self.sessions.begin() as s:await NightAIDispatchRepository(s).reserve(first)
        async with self.sessions.begin() as s:
            repo=NightAIDispatchRepository(s)
            await repo.authorize_send(first.id,first.lease_nonce,self.now)
            await repo.finish(first.id,first.lease_nonce,now=self.now+timedelta(seconds=12),status='failed',error_code='timeout',retry_after=self.now+timedelta(seconds=14))
        second=self.spec(attempt_no=2,reserved_at=self.now+timedelta(seconds=14))
        async with self.sessions.begin() as s:await NightAIDispatchRepository(s).reserve(second)
        async with self.sessions.begin() as s:
            repo=NightAIDispatchRepository(s)
            self.assertFalse(await repo.finish(first.id,first.lease_nonce,now=second.reserved_at,status='expired'))
            self.assertEqual((await s.get(NightAIBinding,self.binding)).inflight_permit_id,second.id)
            self.assertEqual(list((await s.scalars(select(NightNarratorLimit.reserved_requests))).all()),[2]*4)

    async def test_closed_or_already_rendered_source_rejected_before_any_mutation(self):
        await self.apply('0050','upgrade')
        for status,rendered in [('fallback',False),('completed',False),('rendered',False),('unknown',False),('pending',True)]:
            with self.subTest(status=status,rendered=rendered):
                async with self.sessions.begin() as s:
                    await s.execute(update(NightRenderJob).where(NightRenderJob.job_id==self.job).values(status=status))
                    if rendered:
                        import hashlib
                        s.add(NightRendering(job_id=self.job,text='already authored',source='authored',
                            content_hash=hashlib.sha256(b'already authored').hexdigest(),references=[],catalog_ids=[],created_at=self.now))
                before=await self.fingerprints()
                # Catch in the SAME transaction, then commit: rejection must
                # precede counters/slot/source mutations, not rely on rollback.
                async with self.sessions.begin() as s:
                    with self.assertRaisesRegex(DispatchConflict,'source_closed'):
                        await NightAIDispatchRepository(s).reserve(self.spec('render'))
                self.assertEqual(await self.fingerprints(),before)
                async with self.sessions() as s:
                    self.assertEqual(await s.scalar(text('SELECT count(*) FROM night_ai_dispatch_attempts')),0)
                    self.assertEqual(await s.scalar(text('SELECT count(*) FROM night_narrator_limits')),0)
                    self.assertIsNone((await s.get(NightAIBinding,self.binding)).inflight_permit_id)

    async def test_retry_requires_explicit_transient_error_in_repo_and_sql(self):
        await self.apply('0050','upgrade');first=self.spec()
        async with self.sessions.begin() as s:await NightAIDispatchRepository(s).reserve(first)
        for error in (None,'config_error','invalid_response','unknown_error','auth_error'):
            with self.subTest(error=error):
                async with self.sessions.begin() as s:
                    with self.assertRaises(ValueError):
                        await NightAIDispatchRepository(s).finish(first.id,first.lease_nonce,now=self.now,
                            status='failed',error_code=error,retry_after=self.now+timedelta(seconds=2))
                with self.assertRaises(DBAPIError):
                    async with self.sessions.begin() as s:
                        await s.execute(text("UPDATE night_ai_dispatch_attempts SET status='failed',finished_at=:now,retry_after=:retry,error_code=:error WHERE id=:id"),
                            {'now':self.now,'retry':self.now+timedelta(seconds=2),'error':error,'id':first.id})
                async with self.sessions() as s:
                    row=await NightAIDispatchRepository(s).attempt(first.id)
                    self.assertEqual(row.status,'reserved');self.assertIsNone(row.retry_after)
                    self.assertEqual((await s.get(NightAIBinding,self.binding)).inflight_permit_id,first.id)

    async def test_attempt_two_independently_rejects_a_malformed_prior_retry(self):
        await self.apply('0050','upgrade');first=self.spec()
        async with self.sessions.begin() as s:await NightAIDispatchRepository(s).reserve(first)
        # Simulate retained corruption with ONLY the CHECK absent in this owned
        # schema. Both attempt2 defenses must stand independently of that CHECK.
        async with self.engine.begin() as c:
            await c.exec_driver_sql('ALTER TABLE night_ai_dispatch_attempts DROP CONSTRAINT ck_nai_dispatch_retry')
            await c.execute(text("UPDATE night_ai_dispatch_attempts SET status='failed',finished_at=:now,retry_after=:retry,error_code=NULL WHERE id=:id"),
                {'now':self.now,'retry':self.now+timedelta(seconds=2),'id':first.id})
            await c.execute(text('UPDATE night_ai_bindings SET inflight_permit_id=NULL,inflight_lease_until=NULL WHERE id=:id'),{'id':self.binding})
        second=self.spec(attempt_no=2,reserved_at=self.now+timedelta(seconds=2))
        async with self.sessions.begin() as s:
            with self.assertRaisesRegex(DispatchConflict,'source_closed'):await NightAIDispatchRepository(s).reserve(second)
        values={k:getattr(second,k) for k in second.__dataclass_fields__ if k not in {'source','quota_debits'}}
        values.update(source_kind='intent',intent_id=self.intent,job_id=None,contract_version='night-ai-transport/1',status='reserved',quota_debits=[q.document() for q in second.quota_debits])
        with self.assertRaisesRegex(DBAPIError,'night_ai_dispatch_retry'):
            async with self.sessions.begin() as s:await s.execute(insert(NightAIDispatchAttempt).values(**values))
        async with self.sessions() as s:
            self.assertEqual(await s.scalar(text('SELECT count(*) FROM night_ai_dispatch_attempts')),1)
            self.assertEqual(list((await s.scalars(select(NightNarratorLimit.reserved_requests))).all()),[1]*4)
            self.assertIsNone((await s.get(NightAIBinding,self.binding)).inflight_permit_id)

    async def test_pending_then_retry_render_remain_eligible_with_exact_source_lease(self):
        await self.apply('0050','upgrade');first=self.spec('render')
        async with self.sessions.begin() as s:await NightAIDispatchRepository(s).reserve(first)
        async with self.sessions.begin() as s:
            repo=NightAIDispatchRepository(s)
            await repo.authorize_send(first.id,first.lease_nonce,self.now)
            await repo.finish(first.id,first.lease_nonce,now=self.now+timedelta(seconds=1),status='failed',
                error_code='rate_limited',retry_after=self.now+timedelta(seconds=3))
        second=self.spec('render',attempt_no=2,reserved_at=self.now+timedelta(seconds=3))
        async with self.sessions.begin() as s:await NightAIDispatchRepository(s).reserve(second)
        async with self.sessions() as s:
            job=await s.get(NightRenderJob,self.job)
            self.assertEqual((job.status,job.attempts,job.lease_owner,job.lease_until),('leased',2,second.worker_id,second.lease_until))
            self.assertEqual(list((await s.scalars(select(NightNarratorLimit.reserved_requests))).all()),[2]*4)
