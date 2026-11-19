"""Night Case repository contracts; isolated PostgreSQL only, no shared fixtures."""
import unittest


class NightStorageCodecTests(unittest.TestCase):
    def test_bounded_canonical_json_rejects_bool_number_alias_and_nonfinite(self):
        from storage.night_cases import canonical_json, json_hash
        self.assertNotEqual(json_hash({'v': True}), json_hash({'v': 1}))
        with self.assertRaises(ValueError):
            canonical_json({'bad': float('nan')})
        with self.assertRaises(ValueError):
            canonical_json({'x': 'x' * 100}, max_bytes=20)

    def test_command_identity_is_actor_local(self):
        from storage.night_cases import command_key
        self.assertEqual(len(command_key('g', 'a', 'c')), 64)
        self.assertNotEqual(command_key('g', 'a', 'c'), command_key('g', 'b', 'c'))

    def test_public_envelope_rejects_extra_fields(self):
        from storage.night_cases import public_envelope
        with self.assertRaises(ValueError):
            public_envelope({'id': 'x', 'version': 1, 'hash': 'a'*64, 'kernel': {}}, 'running', {})


import asyncio
import hashlib
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select, text, update, func
from sqlalchemy.exc import DBAPIError
from storage.database import Database, DatabaseSettings
from storage.models import (Account, Room, Game, GamePlayer, GameEvent, GameCommand,
    NightCase, NightGameSealed, NightEvent, NightMessage, NightRenderJob,
    NightRendering, NightRewardClaim, NightRuntimeOutage, NightNarratorLimit)
from storage.night_cases import NightCaseRepository, NightStorageConflict, json_hash, public_envelope, QuotaReservation


def isolated_url():
    from tests.night_case_test_database import night_case_test_url
    return night_case_test_url()


class NightStoragePostgresTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = Database(DatabaseSettings(url=isolated_url()))
        self.now = datetime.now(timezone.utc).replace(microsecond=0)
        self.actor, self.stranger = uuid4(), uuid4()
        self.room = uuid4().hex
        self.game = uuid4().hex
        self.case = uuid4().hex
        self.content = {'case': self.case}
        self.hash = json_hash(self.content)
        async with self.db.transaction() as session:
            session.add_all([Account(id=self.actor), Account(id=self.stranger)])
            await session.flush()
            session.add(Room(id=self.room, kind='standalone', owner_account_id=self.actor))
            await session.flush()
            session.add(Game(id=self.game, room_id=self.room, mode='night_case', status='running', phase='day',
                state=public_envelope({'id':self.case,'version':1,'hash':self.hash},'running',{'window':0})))
            await session.flush()
            repo = NightCaseRepository(session)
            await repo.register_case(NightCase(case_id=self.case, version=1, content=self.content,
                content_hash=self.hash, compiler_version='1', engine_build='test', validation_report={},
                registered_at=self.now, registered_by=self.actor, admission='rehearsal'))
            await repo.create_sealed(NightGameSealed(game_id=self.game, case_id=self.case, version=1,
                content_hash=self.hash, rules={}, rules_hash=json_hash({}), engine_build='test',
                compiler_version='1', storage_version=1, kernel={'secret':'canary'}, lobby=None,
                snapshot_hash=json_hash({'secret':'canary'}), storage_revision=0, lifecycle='running', interruption=None))

    async def asyncTearDown(self):
        await self.db.dispose()

    def event(self, event_id='e', scope='public', seq=0):
        return NightEvent(game_id=self.game, event_id=event_id, scope=scope, audience_seq=seq,
            window_idx=0, kind='observed', payload={'value':'canary'}, created_at=self.now)

    def message_row(self, text_value='private canary'):
        return NightMessage(game_id=self.game, id='m', command_id='cmd', thread_key='thread',
            channel='whisper', sender_account_id=self.actor, recipients=[str(self.actor)],
            window_idx=0, text=text_value, text_hash=hashlib.sha256(text_value.encode()).hexdigest(), created_at=self.now)

    async def render_job(self, job_id=None):
        job_id = job_id or uuid4().hex
        async with self.db.transaction() as session:
            await NightCaseRepository(session).enqueue_render(NightRenderJob(job_id=job_id,
                game_id=self.game, cause_id=job_id, kind='scene', audience_key=f'account:{self.actor}',
                knowledge_revision=0, template_version='1', frozen_view={}, input_hash=json_hash({}),
                expires_at=self.now+timedelta(minutes=5), fallback='authored', status='pending',
                attempts=0, lease_owner=None, lease_until=None, retry_at=None, sanitized_error=None))
        return job_id

    async def test_atomic_snapshot_receipt_event_message_rollback(self):
        with self.assertRaises(RuntimeError):
            async with self.db.transaction() as session:
                repo = NightCaseRepository(session)
                locked = await repo.lock_game(self.game)
                await repo.write_snapshot(locked, expected_storage_revision=0, kernel={'new':1}, lobby=None,
                    snapshot_hash=json_hash({'new':1}), lifecycle='running')
                await repo.put_command_receipt(game_id=self.game, actor_key=str(self.actor), actor_account_id=self.actor,
                    client_command_id='c', kind='message', payload={'text':'x'}, result={'ok':True}, status='applied', now=self.now)
                await repo.append_events([self.event()])
                await repo.append_messages([self.message_row()])
                raise RuntimeError('crash before commit')
        async with self.db.transaction() as session:
            sealed = await session.get(NightGameSealed,self.game)
            self.assertEqual(sealed.kernel, {'secret':'canary'})
            for model in (GameCommand,NightEvent,NightMessage):
                self.assertEqual(await session.scalar(select(func.count()).select_from(model).where(model.game_id==self.game)),0)

    async def test_two_sessions_same_command_one_effect(self):
        async def command():
            async with self.db.transaction() as session:
                repo = NightCaseRepository(session)
                locked = await repo.lock_game(self.game)
                old = await repo.command_receipt(self.game,str(self.actor),'c',json_hash({'x':1}))
                if old:
                    return old.result
                await repo.write_snapshot(locked, expected_storage_revision=0,kernel={'ap':0},lobby=None,
                    snapshot_hash=json_hash({'ap':0}), lifecycle='running')
                await repo.append_events([self.event()])
                return (await repo.put_command_receipt(game_id=self.game,actor_key=str(self.actor),actor_account_id=self.actor,
                    client_command_id='c',kind='action',payload={'x':1},result={'ok':True},status='applied',now=self.now)).result
        self.assertEqual(await asyncio.gather(command(),command()),[{'ok':True},{'ok':True}])
        async with self.db.transaction() as session:
            self.assertEqual((await session.get(NightGameSealed,self.game)).storage_revision,1)
            with self.assertRaises(NightStorageConflict):
                await NightCaseRepository(session).command_receipt(self.game,str(self.actor),'c',json_hash({'x':True}))

    async def test_private_changes_leave_generic_projection_and_stream_unchanged(self):
        async with self.db.transaction() as session:
            before = await session.get(Game,self.game)
            old = (before.revision,before.updated_at,before.state)
        async with self.db.transaction() as session:
            repo = NightCaseRepository(session)
            locked = await repo.lock_game(self.game)
            await repo.write_snapshot(locked,expected_storage_revision=0,kernel={'private':1},lobby=None,
                snapshot_hash=json_hash({'private':1}),lifecycle='running')
            await repo.append_events([self.event('a',f'account:{self.actor}',0),self.event('b',f'account:{self.stranger}',0)])
            self.assertFalse(await repo.sync_public(locked,projection={'window':0},phase='day',public_revision=0))
            self.assertEqual(await repo.events(self.game,scope='public'),[])
            self.assertEqual([e.event_id for e in await repo.events(self.game,scope=f'account:{self.actor}')],['a'])
        async with self.db.transaction() as session:
            after = await session.get(Game,self.game)
            self.assertEqual((after.revision,after.updated_at,after.state),old)

    async def test_message_recipient_filter_and_immutable_exact_replay(self):
        async with self.db.transaction() as session:
            repo = NightCaseRepository(session)
            await repo.append_messages([self.message_row()])
            await repo.append_messages([self.message_row()])
            self.assertIsNone(await repo.message(self.game,'m',authorized_aliases=[self.stranger]))
            self.assertEqual((await repo.message(self.game,'m',authorized_aliases=[self.actor])).text,'private canary')
            with self.assertRaises(NightStorageConflict):
                await repo.append_messages([self.message_row('changed')])
        with self.assertRaises(DBAPIError):
            async with self.db.transaction() as session:
                await session.execute(update(NightMessage).where(NightMessage.game_id==self.game).values(text='tamper'))

    async def test_first_write_rendering_two_sessions_and_reopen(self):
        job = await self.render_job()
        async def render(value,source):
            async with self.db.transaction() as session:
                row = await NightCaseRepository(session).commit_rendering(NightRendering(job_id=job,text=value,source=source,
                    content_hash=hashlib.sha256(value.encode()).hexdigest(),references=[],catalog_ids=[],created_at=self.now,first_shown_at=None))
                return row.text
        winners = await asyncio.gather(render('fallback','authored'),render('AI prose','ai'))
        self.assertEqual(winners[0],winners[1])
        async with self.db.transaction() as session:
            repo=NightCaseRepository(session)
            self.assertIsNone(await repo.rendering(job,authorized_audiences=[f'account:{self.stranger}']))
            self.assertEqual((await repo.rendering(job,authorized_audiences=[f'account:{self.actor}'])).text,winners[0])
            await repo.mark_rendering_shown(job,self.now)
        with self.assertRaises(DBAPIError):
            async with self.db.transaction() as session:
                await session.execute(update(NightRendering).where(NightRendering.job_id==job).values(text='tamper'))

    async def test_cross_mode_index_interrupted_night_blocks_mafia(self):
        async with self.db.transaction() as session:
            await session.execute(update(Game).where(Game.id==self.game).values(status='interrupted'))
        with self.assertRaises(DBAPIError):
            async with self.db.transaction() as session:
                session.add(Game(id=uuid4().hex,room_id=self.room,mode='mafia',status='running',phase='night',state={}))
                await session.flush()
        async with self.db.transaction() as session:
            await session.execute(update(Game).where(Game.id==self.game).values(status='stopped'))
            session.add(Game(id=uuid4().hex,room_id=self.room,mode='mafia',status='interrupted',phase='interrupted',state={}))
            await session.flush()
            # Legacy Mafia interrupted remains terminal; new current night game is possible.
            await session.execute(update(Game).where(Game.id==self.game).values(is_current=False))
            session.add(Game(id=uuid4().hex,room_id=self.room,mode='night_case',status='lobby',phase='lobby',
                state=public_envelope({'id':self.case,'version':1,'hash':self.hash},'lobby',{})))
            await session.flush()

    async def test_db_guards_public_kernel_and_generic_private_copies(self):
        bad_operations = [
            lambda s:s.execute(update(Game).where(Game.id==self.game).values(state={'kernel':{'secret':1}})),
            lambda s:s.execute(update(NightCase).where(NightCase.case_id==self.case).values(content={'changed':1})),
            lambda s:s.execute(update(NightGameSealed).where(NightGameSealed.game_id==self.game).values(rules={'changed':1})),
        ]
        for operation in bad_operations:
            with self.assertRaises(DBAPIError):
                async with self.db.transaction() as session:
                    await operation(session)
        with self.assertRaises(DBAPIError):
            async with self.db.transaction() as session:
                session.add(GamePlayer(game_id=self.game,account_id=self.actor,seat='1',private_state={'secret':1}))
                await session.flush()
        with self.assertRaises(DBAPIError):
            async with self.db.transaction() as session:
                session.add(GameEvent(game_id=self.game,event_index=0,kind='private',payload={'secret':1}))
                await session.flush()

    async def test_two_workers_claim_once_and_late_owner_cannot_finish(self):
        job = await self.render_job()
        async def claim(owner):
            async with self.db.transaction() as session:
                rows = await NightCaseRepository(session).claim_render_jobs(now=self.now,owner=owner,
                    lease_until=self.now+timedelta(seconds=30),max_attempts=2,limit=100)
                return [r.job_id for r in rows]
        claims = await asyncio.gather(claim('worker1'),claim('worker2'))
        self.assertEqual(sum(job in ids for ids in claims),1)
        async with self.db.transaction() as session:
            self.assertFalse(await NightCaseRepository(session).finish_render_job(job,owner='wrong',now=self.now,status='completed'))

    async def test_quotas_no_partial_reservation_and_concurrent_limit(self):
        scope = 'game:'+self.game
        async def reserve():
            async with self.db.transaction() as session:
                return await NightCaseRepository(session).reserve_quotas([
                    QuotaReservation(scope,self.now,1,10,1,10)])
        self.assertEqual(sorted(await asyncio.gather(reserve(),reserve())),[False,True])
        async with self.db.transaction() as session:
            self.assertFalse(await NightCaseRepository(session).reserve_quotas([
                QuotaReservation('account:'+str(self.actor),self.now,1,1,4,100),
                QuotaReservation(scope,self.now,1,1,1,10)]))
        async with self.db.transaction() as session:
            row=await session.get(NightNarratorLimit,('account:'+str(self.actor),self.now))
            self.assertEqual(row.reserved_requests,0)

    async def test_outages_cannot_overlap_or_rewrite_completed(self):
        start=self.now+timedelta(days=10000)
        # Each test gets disjoint future interval keyed by UUID to avoid other tests' history.
        start += timedelta(seconds=int(self.game[:8],16)*10)
        oid=uuid4().hex
        async with self.db.transaction() as session:
            repo=NightCaseRepository(session)
            await repo.open_outage(NightRuntimeOutage(outage_id=oid,started_at=start,ended_at=start+timedelta(seconds=5),detected_by='worker'))
        with self.assertRaises(DBAPIError):
            async with self.db.transaction() as session:
                await NightCaseRepository(session).open_outage(NightRuntimeOutage(outage_id=uuid4().hex,
                    started_at=start+timedelta(seconds=1),ended_at=start+timedelta(seconds=7),detected_by='api'))
        with self.assertRaises(DBAPIError):
            async with self.db.transaction() as session:
                await session.execute(update(NightRuntimeOutage).where(NightRuntimeOutage.outage_id==oid).values(ended_at=start+timedelta(seconds=9)))

    async def test_profile2_kernel_budget_and_message_bounds(self):
        large={'x':'a'*(2*1024*1024+1)}
        async with self.db.transaction() as session:
            repo=NightCaseRepository(session)
            locked=await repo.lock_game(self.game)
            await repo.write_snapshot(locked,expected_storage_revision=0,kernel=large,lobby=None,
                snapshot_hash=hashlib.sha256(b'codec-hash').hexdigest(),lifecycle='running')
            with self.assertRaises(ValueError):
                await repo.append_messages([self.message_row('a'*1001)])
        with self.assertRaises(DBAPIError):
            async with self.db.transaction() as session:
                session.add(self.message_row('a'*1001))
                await session.flush()

    async def test_deadline_projection_uses_timer_fence_and_preserves_retry_on_replay(self):
        from storage.models import GameDeadline
        async with self.db.transaction() as session:
            repo=NightCaseRepository(session)
            await repo.project_deadline(game_id=self.game,due_at=self.now,timer_seq=3)
            await session.execute(update(GameDeadline).where(GameDeadline.game_id==self.game).values(attempts=2,last_error_code='retry'))
            await repo.project_deadline(game_id=self.game,due_at=self.now,timer_seq=3)
        async with self.db.transaction() as session:
            row=await session.get(GameDeadline,f'night:{self.game}:phase')
            self.assertEqual((row.attempts,row.last_error_code),(2,'retry'))
            await NightCaseRepository(session).project_deadline(game_id=self.game,due_at=self.now+timedelta(hours=1),timer_seq=4)
        async with self.db.transaction() as session:
            row=await session.get(GameDeadline,f'night:{self.game}:phase')
            self.assertEqual((row.revision,row.attempts,row.last_error_code),(4,0,None))


class NightMigrationTests(unittest.TestCase):
    """Explicit destructive opt-in for the owned test container, never default PG."""
    def test_old_new_down_up_preflight_and_preserved_legacy_rows(self):
        if os.getenv('NIGHT_CASE_MIGRATION_RESET') != '1':
            self.skipTest('NIGHT_CASE_MIGRATION_RESET=1 required for owned schema reset')
        url = isolated_url()
        import subprocess
        import sys
        from pathlib import Path
        from storage.models import GameDeadline
        root = Path(__file__).resolve().parents[1]
        from alembic.config import Config
        from alembic.script import ScriptDirectory
        expected_head = ScriptDirectory.from_config(Config(str(root / 'alembic.ini'))).get_current_head()
        environment = dict(os.environ, DATABASE_URL=url, PYTHONDONTWRITEBYTECODE='1')
        def migrate(*args, expect_success=True, expected_error='night_family_conflict'):
            done = subprocess.run([sys.executable,'-B','-m','alembic',*args], cwd=root,
                env=environment,capture_output=True,text=True,timeout=120)
            if expect_success:
                self.assertEqual(done.returncode,0,done.stdout+done.stderr)
            else:
                self.assertNotEqual(done.returncode,0)
                self.assertIn(expected_error,done.stdout+done.stderr)
            return done
        async def database_action(callback):
            db=Database(DatabaseSettings(url=url))
            try:
                async with db.transaction() as session:
                    return await callback(session)
            finally:
                await db.dispose()
        async def reset(session):
            await session.execute(text('DROP SCHEMA public CASCADE'))
            await session.execute(text('CREATE SCHEMA public'))
        asyncio.run(database_action(reset))
        migrate('upgrade','20261030_0044')
        actor=uuid4(); room=uuid4().hex; game=uuid4().hex; conflict=uuid4().hex
        now=datetime.now(timezone.utc).replace(microsecond=0)
        async def seed(session):
            session.add(Account(id=actor)); await session.flush()
            session.add(Room(id=room,kind='standalone',owner_account_id=actor)); await session.flush()
            session.add_all([Game(id=game,room_id=room,mode='mafia',status='running',phase='night',state={'legacy':'keep'}),
                Game(id=conflict,room_id=room,mode='night_case',status='interrupted',phase='interrupted',state={})])
            await session.flush()
            session.add(GamePlayer(game_id=game,account_id=actor,seat='1',private_state={'role':'old'}))
            # Use SQL: deadline ORM now has columns absent from the old schema.
            await session.execute(text("INSERT INTO game_deadlines(id,game_id,kind,due_at,status,revision) VALUES (:i,:g,'mafia.phase',:d,'pending',3)"),{'i':'legacy-due','g':game,'d':now})
        asyncio.run(database_action(seed))
        migrate('upgrade','head',expect_success=False)
        async def remove_conflict(session):
            self.assertEqual(await session.scalar(text('SELECT version_num FROM alembic_version')),'20261030_0044')
            self.assertEqual(await session.scalar(text("SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_name='night_cases'")),0)
            await session.execute(text('DELETE FROM games WHERE id=:i'),{'i':conflict})
        asyncio.run(database_action(remove_conflict))
        migrate('upgrade','head')
        async def preserved(session):
            self.assertEqual((await session.get(Game,game)).state,{'legacy':'keep'})
            self.assertEqual((await session.get(GamePlayer,(game,actor))).private_state,{'role':'old'})
            deadline=await session.get(GameDeadline,'legacy-due')
            self.assertEqual((deadline.due_at,deadline.revision,deadline.status,deadline.attempts),(now,3,'pending',0))
            self.assertEqual(await session.scalar(text('SELECT version_num FROM alembic_version')),expected_head)
        asyncio.run(database_action(preserved))
        migrate('downgrade','20261030_0044')
        migrate('upgrade','head')
        asyncio.run(database_action(preserved))
        async def retained_history(session):
            session.add(NightRuntimeOutage(outage_id='migration-retention-proof',
                started_at=now-timedelta(days=10),ended_at=now-timedelta(days=9),detected_by='operator'))
        asyncio.run(database_action(retained_history))
        migrate('downgrade','20261030_0044',expect_success=False,expected_error='night_history_retained')
        asyncio.run(database_action(preserved))


if __name__ == '__main__':
    unittest.main()
