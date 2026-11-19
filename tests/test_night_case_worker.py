"""Bounded Night Case worker/health tests; PG acceptance is explicitly isolated."""
import asyncio
import unittest
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
from unittest.mock import patch

from application.night_case import NightCaseError
from application.night_case_runtime import (
    NightCaseDeadlineWorker, NightRuntimeHealthMonitor, DeadlineClaim,
    availability_snapshot, health_plan, fresh, same_generation, tick_command,
)
from config.night_case import NightCaseSettings
from infrastructure.night_case_readiness import readiness_probe, validate_readiness_url

NOW = datetime(2026, 11, 16, 10, tzinfo=timezone.utc)


def settings(**kwargs):
    return NightCaseSettings(enabled=True, cursor_secret=b'worker-test-cursor-secret-32-bytes!!', **kwargs)


class RuntimePureTests(unittest.TestCase):
    def test_active_probe_outage_requires_explicit_successful_worker_probe(self):
        for component,probe in (('api',None),('worker',None),('api',True),('api',False),('worker',False)):
            self.assertFalse(health_plan(NOW,NOW,'failed-probe-outage',NOW,component=component,probe_ready=probe).close)
        self.assertTrue(health_plan(NOW,NOW,'failed-probe-outage',NOW,component='worker',probe_ready=True).close)
        self.assertFalse(health_plan(NOW-timedelta(seconds=121),NOW,'failed-probe-outage',NOW,component='worker',probe_ready=True).close)

    def test_default_off_stable_secret_and_fixed_probe_configuration(self):
        self.assertFalse(NightCaseSettings.from_env({}).enabled)
        with self.assertRaises(ValueError): NightCaseSettings.from_env({'MQB_NIGHT_CASE_ENABLED': 'true'})
        for url in ('https://127.0.0.1/healthz', 'http://example.com/healthz', 'http://127.0.0.1/path', 'http://u:p@localhost/healthz', 'http://localhost/healthz?x=1'):
            with self.assertRaises(ValueError): validate_readiness_url(url)
        self.assertEqual(settings().poll_seconds, 5)
        self.assertFalse(settings().starts_enabled)

    def test_tick_ids_bind_exact_generation_and_due_not_worker_identity(self):
        clock = {'window_seq': 5, 'timer_seq': 8}
        raw = tick_command('game1', clock, NOW)
        self.assertEqual(raw, tick_command('game1', dict(clock), NOW))
        self.assertNotEqual(raw['command_id'], tick_command('game1', {**clock, 'timer_seq': 9}, NOW)['command_id'])
        self.assertNotEqual(raw['command_id'], tick_command('game1', clock, NOW + timedelta(microseconds=1))['command_id'])
        self.assertEqual(raw['params'], {'expected_due_at': '2026-11-16T10:00:00Z'})

    def test_long_outage_starts_at_last_heartbeat_and_closes_after_both_recover(self):
        old = NOW - timedelta(hours=30)
        plan = health_plan(NOW, old, None, NOW, component='worker', probe_ready=True)
        self.assertEqual(plan.start_at, old)
        self.assertTrue(plan.close)
        plan = health_plan(old, NOW, 'persisted-outage', NOW, component='worker', probe_ready=True)
        self.assertIsNone(plan.start_at)
        self.assertFalse(plan.close)
        recovered = health_plan(old, NOW, 'persisted-outage', NOW, component='api')
        self.assertFalse(recovered.close)
        self.assertTrue(health_plan(NOW,NOW,'persisted-outage',NOW,component='worker',probe_ready=True).close)
        self.assertTrue(fresh(NOW - timedelta(seconds=120), NOW))
        self.assertFalse(fresh(NOW - timedelta(seconds=121), NOW))

    def test_probe_failure_clamps_to_previous_interval_and_clock_does_not_rewind(self):
        last = NOW - timedelta(seconds=10)
        plan = health_plan(NOW - timedelta(seconds=30), NOW, None, NOW, component='worker', probe_ready=False, last_ended=last)
        self.assertEqual(plan.start_at, last)
        self.assertFalse(plan.close)
        with self.assertRaisesRegex(ValueError, 'clock'):
            health_plan(NOW + timedelta(seconds=1), NOW, None, NOW, component='worker')


class _Scalar:
    def __init__(self, value): self.value = value
    def scalar_one_or_none(self): return self.value
    def all(self): return self.value


class _Database:
    def __init__(self, session): self.session, self.transactions, self.active = session, 0, 0
    @asynccontextmanager
    async def transaction(self):
        self.transactions += 1; self.active += 1
        try: yield self.session
        finally: self.active -= 1


class RuntimeAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_read_only_availability_returns_all_intervals_and_blocks_stale_starts(self):
        from storage.models import NightRuntimeHealth, GameDeadline
        health = NS(api_seen_at=NOW, worker_seen_at=NOW, active_outage_id=None)
        intervals = [NS(outage_id='outage-1', started_at=NOW - timedelta(hours=35), ended_at=NOW - timedelta(hours=30)), NS(outage_id='outage-2', started_at=NOW - timedelta(hours=2), ended_at=NOW - timedelta(hours=1))]
        class Session:
            async def get(self, model, key, **kwargs): return health if model is NightRuntimeHealth else None
            async def scalars(self, statement):
                self_outer.assertNotIn('FOR UPDATE', str(statement))
                from storage.models import GameCommand
                if statement.column_descriptions[0]['entity'] is GameCommand:
                    return _Scalar([])
                return _Scalar(intervals)
        self_outer = self
        context = NS(now=NOW, locked=NS(game=NS(id='game', started_at=NOW - timedelta(hours=34)), sealed=NS(lifecycle='running')))
        decision = await availability_snapshot(Session(), settings(), context)
        self.assertEqual(len(decision.completed_outages), 2)
        self.assertEqual(decision.completed_outages[0].unavailable_from, context.locked.game.started_at)
        health.worker_seen_at = NOW - timedelta(seconds=121)
        self.assertTrue((await availability_snapshot(Session(), settings(), context)).delayed)
        health.worker_seen_at = NOW
        context.locked.sealed.lifecycle = 'lobby'; context.locked.game.started_at = None
        self.assertTrue((await availability_snapshot(Session(), settings(), context)).delayed)
        self.assertFalse((await availability_snapshot(Session(), settings(starts_enabled=True), context)).delayed)

    async def test_probe_and_health_precede_game_loops_and_one_bad_game_isolated(self):
        calls = []
        async def probe(url): calls.append('probe'); return True
        class Monitor:
            async def heartbeat(self, component, **kwargs):
                calls.append('health-commit' if 'probe_ready' in kwargs else 'heartbeat-commit'); return True
        class Worker(NightCaseDeadlineWorker):
            async def claim_due(self, now): calls.append('claim-commit'); return ['bad', 'good']
            async def apply_claim(self, claim, now):
                calls.append('game-' + claim)
                if claim == 'bad': raise NightCaseError('game_quarantined', 503)
                return True
            async def record_failure(self, claim, now, code): calls.append('failure-' + code)
        worker = Worker(None, settings(), service_factory=lambda session: None, probe=probe)
        worker.monitor = Monitor()
        self.assertEqual(await worker.run_once(now=NOW), 1)
        self.assertEqual(calls, ['heartbeat-commit', 'probe', 'health-commit', 'claim-commit', 'game-bad', 'failure-snapshot_invalid', 'game-good'])

    async def test_retry_backoff_quarantine_and_old_generation_cannot_overwrite_new(self):
        row = NS(id='night:game:phase', game_id='game', revision=2, due_at=NOW, claimed_by='owner', status='claimed', attempts=0, claimed_at=NOW, quarantined_at=None)
        class Session:
            async def execute(self, statement, *args): return _Scalar(row)
            async def flush(self): pass
        audits = []
        class Repo:
            def __init__(self, session): pass
            async def lock_game(self, game_id): return NS(game=NS(id=game_id))
            async def put_command_receipt(self, **kwargs): audits.append(kwargs)
        db = _Database(Session())
        worker = NightCaseDeadlineWorker(db, settings(), service_factory=lambda session: None)
        claim = DeadlineClaim(row.id, 'game', 2, NOW, 'owner')
        with patch('application.night_case_runtime.NightCaseRepository', Repo):
            for attempt, delay in enumerate((5, 30, 120), 1):
                row.claimed_by, row.status = 'owner', 'claimed'
                self.assertTrue(await worker.record_failure(claim, NOW, 'snapshot_invalid'))
                self.assertEqual(row.attempts, attempt)
                self.assertEqual(row.retry_at, NOW + timedelta(seconds=delay))
        self.assertEqual(row.status, 'quarantined')
        self.assertEqual(row.quarantined_at, NOW)
        self.assertEqual(len(audits), 1)
        self.assertEqual(audits[0]['result'], {'status': 'game_quarantined'})
        row.revision, row.claimed_by, row.status = 3, 'owner', 'claimed'
        with patch('application.night_case_runtime.NightCaseRepository', Repo):
            self.assertFalse(await worker.record_failure(claim, NOW, 'snapshot_invalid'))
        self.assertEqual(row.attempts, 3)
        self.assertEqual(db.active, 0)

    async def test_api_heartbeat_lifecycle_repeated_exit_and_failure_leave_no_tasks(self):
        monitor = NightRuntimeHealthMonitor(None, settings())
        calls = []
        async def beat(*args, **kwargs): calls.append('heartbeat')
        monitor.heartbeat = beat
        baseline = {t for t in asyncio.all_tasks() if t.get_name() == 'night-case-api-heartbeat'}
        for i in range(10):
            try:
                async with monitor.api_lifecycle():
                    await asyncio.sleep(0)
                    if i % 2: raise RuntimeError('body failed')
            except RuntimeError: pass
        await asyncio.sleep(0)
        self.assertEqual({t for t in asyncio.all_tasks() if t.get_name() == 'night-case-api-heartbeat'}, baseline)
        self.assertEqual(len(calls), 10)

    async def test_probe_closes_connections_and_rejects_redirects_without_following(self):
        active, requests, redirect = 0, 0, False
        async def handler(reader, writer):
            nonlocal active, requests
            active += 1
            requests += 1
            try:
                await reader.readuntil(b'\r\n\r\n')
                if redirect: writer.write(b'HTTP/1.1 302 Found\r\nLocation: /healthz\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
                else: writer.write(b'HTTP/1.1 200 OK\r\nContent-Length: 15\r\nConnection: close\r\n\r\n{"status":"ok"}')
                await writer.drain()
            finally:
                writer.close(); await writer.wait_closed(); active -= 1
        server = await asyncio.start_server(handler, '127.0.0.1', 0)
        try:
            url = 'http://127.0.0.1:' + str(server.sockets[0].getsockname()[1]) + '/healthz'
            for _ in range(10): self.assertTrue(await readiness_probe(url))
            redirect = True
            self.assertFalse(await readiness_probe(url))
            await asyncio.sleep(0)
            self.assertEqual(requests, 11)
            self.assertEqual(active, 0)
        finally:
            server.close(); await server.wait_closed()

# Reuse the existing isolated account/lobby helpers without inheriting its tests.
import tests.test_night_case_application as _application_tests


class NightWorkerPostgresTests(unittest.IsolatedAsyncioTestCase):
    service = _application_tests.NightApplicationPostgresTests.service
    lobby_command = _application_tests.NightApplicationPostgresTests.lobby_command
    lobby = _application_tests.NightApplicationPostgresTests.lobby
    ready_lobby = _application_tests.NightApplicationPostgresTests.ready_lobby
    running = _application_tests.NightApplicationPostgresTests.running
    player_command = _application_tests.NightApplicationPostgresTests.player_command

    async def asyncSetUp(self):
        from sqlalchemy import select
        from storage.models import NightRuntimeOutage
        from uuid import uuid4
        await _application_tests.NightApplicationPostgresTests.asyncSetUp(self)
        # Immutable history is retained. Each test starts after prior intervals,
        # uses its own health key, and never deletes an outage to clean up.
        async with self.db.transaction() as session:
            rows = list((await session.scalars(select(NightRuntimeOutage))).all())
            if rows:
                latest = max(r.ended_at or r.started_at for r in rows)
                self.now = max(self.now, latest + timedelta(days=2))
            # The worker claims every due Night Case deadline in the database, as it must.
            # Other test modules share this database and leave running games behind;
            # cancel their open deadlines so claim counts here see only this test's games.
            from sqlalchemy import update
            from storage.models import GameDeadline
            await session.execute(update(GameDeadline).where(
                GameDeadline.kind == 'night.phase', GameDeadline.status.in_(('pending', 'claimed'))
            ).values(status='cancelled', claimed_by=None, claimed_at=None))
        self.settings = settings(starts_enabled=True, runtime_key='worker-test-' + uuid4().hex)
        from application.night_case_runtime import NightCaseServiceFactory
        self.factory = NightCaseServiceFactory(self.settings, registry=self.registry, clock=lambda: self.now)
        async def probe(url): return True
        self.worker = NightCaseDeadlineWorker(self.db, self.settings, service_factory=self.factory, clock=lambda: self.now, probe=probe)

    async def asyncTearDown(self):
        if hasattr(self, 'db'):
            from sqlalchemy import select, update
            from storage.models import GameDeadline, NightGameSealed
            # Stop only deadlines belonging to this test's unique registered case.
            # Append-only game/outage history is retained for inspection.
            async with self.db.transaction() as session:
                own_games = select(NightGameSealed.game_id).where(NightGameSealed.case_id == self.ref.case_id)
                await session.execute(update(GameDeadline).where(GameDeadline.game_id.in_(own_games)).values(status='cancelled', claimed_by=None, claimed_at=None))
            await self.db.dispose()

    async def healthy(self):
        from sqlalchemy.dialects.postgresql import insert
        from storage.models import NightRuntimeHealth
        async with self.db.transaction() as session:
            statement = insert(NightRuntimeHealth).values(runtime_key=self.settings.runtime_key, api_seen_at=self.now, worker_seen_at=self.now)
            await session.execute(statement.on_conflict_do_update(index_elements=['runtime_key'], set_={'api_seen_at': self.now, 'worker_seen_at': self.now}))

    async def deadline(self, game):
        from storage.models import GameDeadline
        async with self.db.transaction() as session:
            row = await session.get(GameDeadline, 'night:' + game + ':phase')
            return NS(**{key: getattr(row, key) for key in ('id', 'game_id', 'revision', 'due_at', 'status', 'attempts', 'claimed_by', 'quarantined_at', 'retry_at')})

    async def kernel(self, game):
        from storage.models import NightGameSealed
        async with self.db.transaction() as session: return (await session.get(NightGameSealed, game)).kernel

    async def test_two_workers_claim_once_and_restart_reclaims_expired_lease(self):
        from sqlalchemy import select
        from storage.models import GameCommand
        game, _, _, _ = await self.running()
        due = await self.deadline(game); self.now = due.due_at
        await self.healthy()
        other = NightCaseDeadlineWorker(self.db, self.settings, service_factory=self.factory, clock=lambda: self.now, probe=self.worker.probe)
        results = await asyncio.gather(self.worker.run_once(now=self.now), other.run_once(now=self.now))
        self.assertEqual(sum(results), 1)
        kernel = await self.kernel(game)
        self.assertEqual(kernel['clock']['window_idx'], 2)
        async with self.db.transaction() as session:
            receipts = list((await session.scalars(select(GameCommand).where(GameCommand.game_id == game, GameCommand.kind == 'system.tick'))).all())
            self.assertEqual(len(receipts), 1)
        due = await self.deadline(game); self.now = due.due_at
        await self.healthy()
        claims = await self.worker.claim_due(self.now)
        self.assertEqual(len(claims), 1)
        self.assertEqual(await other.claim_due(self.now), [])
        self.now += timedelta(seconds=61)
        await self.healthy()
        reclaimed = await other.claim_due(self.now)
        self.assertEqual(len(reclaimed), 1)
        self.assertFalse(await self.worker.apply_claim(claims[0], self.now))
        self.assertTrue(await other.apply_claim(reclaimed[0], self.now))
        self.assertEqual((await self.kernel(game))['clock']['window_idx'], 3)

    async def test_thirty_hour_outage_resumes_old_due_without_backlog_or_afk(self):
        from sqlalchemy import select
        from storage.models import GameCommand
        game, _, _, _ = await self.running()
        command = await self.player_command(game, self.owner, 'move', {'location': 'yard'})
        async with self.db.transaction() as session: await self.service(session).execute(account_id=self.owner, game_id=game, command=command)
        original = await self.kernel(game)
        await self.healthy()
        self.now += timedelta(hours=30)
        self.assertFalse(await self.worker.monitor.heartbeat('worker', now=self.now))
        self.assertEqual(await self.worker.run_once(now=self.now), 0)
        self.now += timedelta(seconds=1)
        self.assertFalse(await self.worker.monitor.heartbeat('api', now=self.now))
        old_due = await self.deadline(game)
        self.assertEqual(await self.worker.run_once(now=self.now), 0)  # resume invalidates the old tick generation
        after = await self.kernel(game)
        self.assertEqual(after['clock']['window_idx'], 1)
        self.assertEqual([p['ap'] for p in after['players']], [p['ap'] for p in original['players']])
        self.assertEqual([p['missed_windows'] for p in after['players']], [0] * 4)
        self.assertEqual(len(after['clock']['resume_receipts']), 1)
        deadline = await self.deadline(game)
        self.assertGreater(deadline.revision, old_due.revision)
        self.assertGreater(deadline.due_at, self.now)
        self.assertEqual(deadline.status, 'pending')
        async with self.db.transaction() as session:
            resumes = list((await session.scalars(select(GameCommand).where(GameCommand.game_id == game, GameCommand.kind == 'system.resume'))).all())
            self.assertEqual(len(resumes), 1)
        self.now += timedelta(seconds=5)
        self.assertEqual(await self.worker.run_once(now=self.now), 0)
        self.assertEqual((await self.kernel(game))['clock'], after['clock'])

    async def test_delayed_sequential_outages_clamp_start_and_keep_actual_audit_time(self):
        from sqlalchemy import select
        from storage.models import GameCommand, NightRuntimeOutage
        from uuid import uuid4

        game, _, _, _ = await self.running()
        move = await self.player_command(game, self.owner, 'move', {'location': 'yard'})
        async with self.db.transaction() as session:
            await self.service(session).execute(account_id=self.owner, game_id=game, command=move)
        original = await self.kernel(game)
        started = self.now
        first_end = started + timedelta(hours=30)
        second_end = first_end + timedelta(hours=30)
        intervals = [
            NightRuntimeOutage(outage_id='delayed-' + uuid4().hex,
                started_at=started - timedelta(hours=1), ended_at=first_end, detected_by='worker'),
            NightRuntimeOutage(outage_id='delayed-' + uuid4().hex,
                started_at=first_end + timedelta(hours=2), ended_at=second_end, detected_by='worker'),
        ]
        async with self.db.transaction() as session:
            session.add_all(intervals)
        self.now = second_end + timedelta(hours=1)
        await self.healthy()
        command = await self.player_command(game, self.owner, 'seen')
        async with self.db.transaction() as session:
            result = await self.factory(session).execute(account_id=self.owner, game_id=game, command=command)
        self.assertTrue(result['receipt']['accepted'])
        after = await self.kernel(game)
        self.assertEqual(after['clock']['window_idx'], 1)
        self.assertEqual([p['ap'] for p in after['players']], [p['ap'] for p in original['players']])
        self.assertEqual([p['missed_windows'] for p in after['players']], [0] * 4)
        self.assertEqual(len(after['clock']['resume_receipts']), 2)
        self.assertGreater((await self.deadline(game)).due_at, self.now)
        async with self.db.transaction() as session:
            rows = list((await session.scalars(select(GameCommand).where(
                GameCommand.game_id == game, GameCommand.kind == 'system.resume'))).all())
        rows.sort(key=lambda row: row.payload['command']['params']['resumed_at'])
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].payload['command']['params']['unavailable_from'], started.isoformat().replace('+00:00', 'Z'))
        self.assertEqual([row.payload['command']['params']['resumed_at'] for row in rows],
            [end.isoformat().replace('+00:00', 'Z') for end in (first_end, second_end)])
        self.assertTrue(all(row.created_at == self.now and row.processed_at == self.now for row in rows))
        self.now += timedelta(minutes=1)
        async with self.db.transaction() as session:
            self.assertEqual(await self.factory(session).execute(account_id=self.owner, game_id=game, command=command), result)
        self.assertEqual((await self.kernel(game))['clock'], after['clock'])

    async def test_corrupt_generation_quarantines_after_three_failures_other_game_advances(self):
        from sqlalchemy import update
        from storage.models import NightGameSealed, Room, RoomMembership
        from uuid import uuid4
        bad, _, _, _ = await self.running()
        self.room = uuid4().hex
        async with self.db.transaction() as session:
            session.add(Room(id=self.room, kind='standalone', owner_account_id=self.owner)); await session.flush()
            session.add_all([RoomMembership(room_id=self.room, account_id=a, role='owner' if a == self.owner else 'member') for a in self.accounts])
        good, _, _, _ = await self.running()
        async with self.db.transaction() as session: await session.execute(update(NightGameSealed).where(NightGameSealed.game_id == bad).values(snapshot_hash='0' * 64))
        self.now = (await self.deadline(bad)).due_at
        await self.healthy()
        self.assertEqual(await self.worker.run_once(now=self.now), 1)
        self.assertEqual((await self.deadline(bad)).attempts, 1)
        self.assertEqual((await self.kernel(good))['clock']['window_idx'], 2)
        self.now += timedelta(seconds=5)
        await self.worker.run_once(now=self.now)
        self.assertEqual((await self.deadline(bad)).attempts, 2)
        self.now += timedelta(seconds=30)
        await self.worker.run_once(now=self.now)
        bad_deadline = await self.deadline(bad)
        self.assertEqual(bad_deadline.status, 'quarantined')
        self.assertEqual(bad_deadline.attempts, 3)
        self.assertIsNotNone(bad_deadline.quarantined_at)
        self.assertEqual(await self.worker.claim_due(self.now + timedelta(hours=1)), [])


    async def test_outage_guard_close_reclose_and_draft_review_immutability(self):
        from sqlalchemy import update
        from sqlalchemy.exc import DBAPIError
        from storage.models import NightRuntimeOutage, NightEpisodeDraft, NightCase
        from storage.night_cases import NightCaseRepository, NightStorageConflict
        from uuid import uuid4
        oid = 'guard-' + uuid4().hex
        draft_id = 'guard-' + uuid4().hex
        async with self.db.transaction() as session:
            await NightCaseRepository(session).open_outage(NightRuntimeOutage(outage_id=oid, started_at=self.now, ended_at=None, detected_by='operator'))
            session.add(NightEpisodeDraft(draft_id=draft_id, candidate={'text':'original'}, content_hash='1' * 64, world_id='test', contract_version='1', owner_review='draft'))
        async with self.db.transaction() as session:
            await NightCaseRepository(session).close_outage(oid, self.now + timedelta(seconds=1))
        async with self.db.transaction() as session:
            await NightCaseRepository(session).close_outage(oid, self.now + timedelta(seconds=1))
            await session.execute(update(NightEpisodeDraft).where(NightEpisodeDraft.draft_id == draft_id).values(candidate={'text':'reviewed'}, owner_review='approved', reviewed_by=self.owner, reviewed_at=self.now))
        async with self.db.transaction() as session:
            with self.assertRaises(NightStorageConflict):
                await NightCaseRepository(session).close_outage(oid, self.now + timedelta(seconds=2))
        for model, predicate, values, code in (
            (NightRuntimeOutage, NightRuntimeOutage.outage_id == oid, {'ended_at': self.now + timedelta(seconds=2)}, 'night_completed_outage_immutable'),
            (NightEpisodeDraft, NightEpisodeDraft.draft_id == draft_id, {'candidate': {'text':'changed'}}, 'night_history_immutable'),
            (NightCase, NightCase.case_id == self.ref.case_id, {'content_hash': '0' * 64}, 'night_history_immutable')):
            with self.assertRaisesRegex(DBAPIError, code):
                async with self.db.transaction() as session: await session.execute(update(model).where(predicate).values(**values))

    async def test_stale_runtime_blocks_new_command_but_owned_retry_and_history_survive(self):
        from sqlalchemy import update
        from storage.models import NightRuntimeHealth
        game, _, _, _ = await self.running()
        await self.healthy()
        command = await self.player_command(game, self.owner, 'seen')
        async with self.db.transaction() as session:
            first = await self.factory(session).execute(account_id=self.owner, game_id=game, command=command)
        async with self.db.transaction() as session:
            await session.execute(update(NightRuntimeHealth).where(NightRuntimeHealth.runtime_key == self.settings.runtime_key).values(api_seen_at=self.now - timedelta(seconds=121)))
        async with self.db.transaction() as session:
            retry = await self.factory(session).execute(account_id=self.owner, game_id=game, command=command)
            self.assertEqual(retry, first)
            view = await self.factory(session).get_view(account_id=self.owner, game_id=game)
            self.assertEqual(view['public']['clock']['window_idx'], 1)
        new_command = await self.player_command(game, self.owner, 'seen')
        with self.assertRaisesRegex(NightCaseError, 'runtime_delayed'):
            async with self.db.transaction() as session:
                await self.factory(session).execute(account_id=self.owner, game_id=game, command=new_command)

    async def test_failed_probe_outage_is_not_closed_by_api_or_unprobed_worker_heartbeat(self):
        from storage.models import NightRuntimeHealth,NightRuntimeOutage
        await self.healthy()
        self.assertFalse(await self.worker.monitor.heartbeat('worker',now=self.now,probe_ready=False))
        async with self.db.transaction() as session:
            health=await session.get(NightRuntimeHealth,self.settings.runtime_key)
            outage_id=health.active_outage_id
            self.assertIsNotNone(outage_id)
        self.now+=timedelta(seconds=1)
        for component in ('api','worker'):
            self.assertFalse(await self.worker.monitor.heartbeat(component,now=self.now))
            async with self.db.transaction() as session:
                self.assertEqual((await session.get(NightRuntimeHealth,self.settings.runtime_key)).active_outage_id,outage_id)
                self.assertIsNone((await session.get(NightRuntimeOutage,outage_id)).ended_at)
        self.assertTrue(await self.worker.monitor.heartbeat('worker',now=self.now,probe_ready=True))
        async with self.db.transaction() as session:
            self.assertIsNone((await session.get(NightRuntimeHealth,self.settings.runtime_key)).active_outage_id)
            self.assertEqual((await session.get(NightRuntimeOutage,outage_id)).ended_at,self.now)
