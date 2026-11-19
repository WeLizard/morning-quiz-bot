"""Real PostgreSQL regression for concurrent healthy runtime heartbeats."""
import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import func, select

from application.night_case_runtime import NightRuntimeHealthMonitor
from config.night_case import NightCaseSettings
from storage.database import Database, DatabaseSettings
from storage.models import NightRuntimeHealth, NightRuntimeOutage
from storage.night_cases import NightCaseRepository
from tests.night_case_test_database import night_case_test_url


class HealthConcurrencyPostgresTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = Database(DatabaseSettings(night_case_test_url()))
        self.key = 'health-race-' + uuid4().hex
        self.settings = NightCaseSettings(enabled=True, runtime_key=self.key,
            cursor_secret=b'health-concurrency-test-secret-32-bytes')
        async with self.db.transaction() as session:
            latest = await session.scalar(select(func.max(func.coalesce(
                NightRuntimeOutage.ended_at, NightRuntimeOutage.started_at))))
            self.base = max(datetime.now(timezone.utc), (latest + timedelta(days=1)) if latest else datetime.now(timezone.utc))
            session.add(NightRuntimeHealth(runtime_key=self.key, api_seen_at=self.base,
                worker_seen_at=self.base))

    async def asyncTearDown(self):
        await self.db.dispose()

    async def test_two_healthy_workers_close_one_outage_once(self):
        monitor = NightRuntimeHealthMonitor(self.db, self.settings, clock=lambda: self.base)
        self.assertFalse(await monitor.heartbeat('worker', now=self.base, probe_ready=False))
        entered = 0
        both_read = asyncio.Event()
        original = NightCaseRepository.lock_health

        async def after_cached_read(repo, runtime_key):
            nonlocal entered
            if runtime_key == self.key:
                entered += 1
                if entered == 2:
                    both_read.set()
                await asyncio.wait_for(both_read.wait(), timeout=5)
            return await original(repo, runtime_key)

        with patch.object(NightCaseRepository, 'lock_health', after_cached_read):
            results = await asyncio.gather(
                monitor.heartbeat('worker', now=self.base + timedelta(seconds=1), probe_ready=True),
                monitor.heartbeat('worker', now=self.base + timedelta(seconds=2), probe_ready=True),
                return_exceptions=True)
        self.assertEqual(results, [True, True])
        async with self.db.transaction() as session:
            health = await session.get(NightRuntimeHealth, self.key)
            self.assertIsNone(health.active_outage_id)
            outages = (await session.scalars(select(NightRuntimeOutage).where(
                NightRuntimeOutage.started_at == self.base))).all()
            self.assertEqual(len(outages), 1)
            self.assertIn(outages[0].ended_at, (self.base + timedelta(seconds=1),
                                               self.base + timedelta(seconds=2)))

    async def test_api_heartbeat_racing_healthy_worker_keeps_single_closed_outage(self):
        monitor = NightRuntimeHealthMonitor(self.db, self.settings, clock=lambda: self.base)
        self.assertFalse(await monitor.heartbeat('worker', now=self.base, probe_ready=False))
        entered = 0
        both_read = asyncio.Event()
        original = NightCaseRepository.lock_health

        async def after_cached_read(repo, runtime_key):
            nonlocal entered
            if runtime_key == self.key:
                entered += 1
                if entered == 2:
                    both_read.set()
                await asyncio.wait_for(both_read.wait(), timeout=5)
            return await original(repo, runtime_key)

        recovered_at = self.base + timedelta(seconds=1)
        with patch.object(NightCaseRepository, 'lock_health', after_cached_read):
            api, worker = await asyncio.gather(
                monitor.heartbeat('api', now=recovered_at),
                monitor.heartbeat('worker', now=recovered_at, probe_ready=True))
        self.assertIsInstance(api, bool)
        self.assertTrue(worker)
        async with self.db.transaction() as session:
            health = await session.get(NightRuntimeHealth, self.key)
            self.assertIsNone(health.active_outage_id)
            outages = (await session.scalars(select(NightRuntimeOutage).where(
                NightRuntimeOutage.started_at == self.base))).all()
            self.assertEqual(len(outages), 1)
            self.assertEqual(outages[0].ended_at, recovered_at)
