"""Standalone Night Case health, availability and bounded deadline processing.

Health transitions commit before claims. Each candidate owns a separate transaction;
Game locks precede the deadline generation recheck. No network is performed there.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import partial
from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.exc import OperationalError, InterfaceError, DBAPIError

from application.night_case import AvailabilityDecision, CompletedOutage, NightCaseApplicationService, NightCaseError
from config.night_case import NightCaseSettings
from infrastructure.night_case_readiness import readiness_probe, readiness_token
from storage.admin_actions import operation_fence
from storage.models import Game, GameDeadline, NightRuntimeHealth, NightRuntimeOutage
from storage.night_cases import NightCaseRepository, json_hash
from domain.night_case_engine import _due

logger = logging.getLogger(__name__)
BACKOFF_SECONDS = (5, 30, 120)


def utc_now(): return datetime.now(timezone.utc)


def _utc(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError('runtime_clock_invalid')
    return value


def _stamp(value): return _utc(value).isoformat().replace('+00:00', 'Z')


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def fresh(seen, now, stale_seconds=120):
    return seen is not None and timedelta(0) <= now - _utc(seen) <= timedelta(seconds=stale_seconds)


@dataclass(frozen=True)
class HealthPlan:
    start_at: datetime | None
    close: bool


def health_plan(api_seen, worker_seen, active, now, *, component, probe_ready=None, stale_seconds=120, last_ended=None):
    """Compute the conservative interval before overwriting a stale heartbeat."""
    _utc(now)
    if component not in {'api', 'worker'}: raise ValueError('invalid runtime component')
    for seen in (api_seen, worker_seen):
        if seen is not None and _utc(seen) > now: raise ValueError('runtime_clock_invalid')
    stale = [s for s in (api_seen, worker_seen) if s is not None and not fresh(s, now, stale_seconds)]
    missing = api_seen is None or worker_seen is None
    start = None
    if not active and (stale or missing or probe_ready is False):
        candidates = stale or ([api_seen] if probe_ready is False and api_seen else [])
        start = min(candidates) if candidates else now
        if last_ended is not None: start = max(start, _utc(last_ended))
        if start > now: raise ValueError('runtime_clock_invalid')
    after_api = now if component == 'api' else api_seen
    after_worker = now if component == 'worker' else worker_seen
    close = (component == 'worker' and probe_ready is True
             and fresh(after_api, now, stale_seconds) and fresh(after_worker, now, stale_seconds))
    return HealthPlan(start, close)


class NightRuntimeHealthMonitor:
    def __init__(self, database, settings: NightCaseSettings, *, clock=utc_now):
        self.database, self.settings, self.clock = database, settings, clock
        self._api_task = None

    async def heartbeat(self, component, *, now=None, probe_ready=None):
        if not self.settings.enabled: return False
        now = _utc(now or self.clock())
        async with self.database.transaction() as session:
            # Read first; ordinary 5s polling does not lock the shared health row.
            row = await session.get(NightRuntimeHealth, self.settings.runtime_key)
            previous = getattr(row, component + '_seen_at', None) if row else None
            due = previous is None or now - previous >= timedelta(seconds=self.settings.heartbeat_seconds)
            unhealthy = row is None or not fresh(row.api_seen_at, now) or not fresh(row.worker_seen_at, now)
            if not due and not unhealthy and not row.active_outage_id and probe_ready is not False: return True
            repo = NightCaseRepository(session)
            row = await repo.lock_health(self.settings.runtime_key)
            # A concurrent heartbeat may have committed after our polling sample.
            # Re-read time and the locked row before deriving or writing anything.
            now = max(now, _utc(self.clock()))
            previous = getattr(row, component + '_seen_at')
            due = previous is None or now - previous >= timedelta(seconds=self.settings.heartbeat_seconds)
            last_ended = await session.scalar(select(NightRuntimeOutage.ended_at).where(NightRuntimeOutage.ended_at.is_not(None)).order_by(NightRuntimeOutage.ended_at.desc()).limit(1))
            plan = health_plan(row.api_seen_at, row.worker_seen_at, row.active_outage_id, now, component=component, probe_ready=probe_ready, stale_seconds=self.settings.stale_seconds, last_ended=last_ended)
            if previous is None or due: setattr(row, component + '_seen_at', now)
            if plan.start_at is not None:
                oid = 'outage_' + _hash([self.settings.runtime_key, _stamp(plan.start_at)])[:48]
                await repo.open_outage(NightRuntimeOutage(outage_id=oid, started_at=plan.start_at, ended_at=None, detected_by=component))
                row.active_outage_id = oid
            if row.active_outage_id and plan.close:
                outage = await session.get(NightRuntimeOutage, row.active_outage_id)
                if now > outage.started_at:
                    await repo.close_outage(outage.outage_id, now)
                    row.active_outage_id = None
            await session.flush()
            return row.active_outage_id is None and fresh(row.api_seen_at, now) and fresh(row.worker_seen_at, now)

    @asynccontextmanager
    async def api_lifecycle(self):
        """API owns one heartbeat task; cancellation and exceptional shutdown are awaited."""
        if not self.settings.enabled:
            yield self
            return
        if self._api_task is not None: raise RuntimeError('heartbeat_lifecycle_already_running')
        await self.heartbeat('api')
        if self._api_task is not None: raise RuntimeError('heartbeat_lifecycle_already_running')
        async def loop():
            while True:
                await asyncio.sleep(self.settings.heartbeat_seconds)
                try: await self.heartbeat('api')
                except Exception: logger.warning('Night API heartbeat failed: runtime_unavailable')
        task = asyncio.create_task(loop(), name='night-case-api-heartbeat')
        self._api_task = task
        try: yield self
        finally:
            task.cancel()
            try: await asyncio.wait_for(task, timeout=5)
            except asyncio.CancelledError: pass
            finally: self._api_task = None


async def availability_snapshot(session, settings, context):
    """Read-only under Game lock: no health lock, network, independent session or commit."""
    now = _utc(context.now)
    if not settings.enabled: return AvailabilityDecision(True)
    row = await session.get(NightRuntimeHealth, settings.runtime_key, populate_existing=True)
    if row is None or row.active_outage_id or not fresh(row.api_seen_at, now) or not fresh(row.worker_seen_at, now):
        return AvailabilityDecision(True)
    if context.locked.sealed.lifecycle == 'lobby' and not settings.starts_enabled:
        return AvailabilityDecision(True)
    deadline = await session.get(GameDeadline, 'night:' + context.locked.game.id + ':phase', populate_existing=True)
    if deadline is not None and deadline.quarantined_at is not None: raise NightCaseError('game_quarantined', 503)
    started = context.locked.game.started_at
    if started is None: return AvailabilityDecision(False)
    outages = list((await session.scalars(select(NightRuntimeOutage).where(NightRuntimeOutage.ended_at.is_not(None), NightRuntimeOutage.ended_at > started).order_by(NightRuntimeOutage.started_at))).all())
    from application.night_case_recovery import recovery_coverage, coverage_status
    coverage = await recovery_coverage(session, context.locked.game.id)
    completed = []
    kernel = getattr(context.locked.sealed, 'kernel', None)
    applied = {r['outage_id']: r['payload_hash'] for r in kernel['clock']['resume_receipts']} if kernel else {}
    for outage in outages:
        if not outage.started_at < outage.ended_at <= now: raise NightCaseError('runtime_delayed', 503)
        begin = max(started, outage.started_at)
        params = {'outage_id': outage.outage_id, 'unavailable_from': _stamp(begin), 'resumed_at': _stamp(outage.ended_at)}
        coverage.verify_source(params)
        if outage.outage_id in applied and applied[outage.outage_id] != json_hash(params):
            raise NightCaseError('game_quarantined', 503)
        if coverage_status(begin, outage.ended_at, coverage) == 'covered':
            continue
        completed.append(CompletedOutage(outage.outage_id, begin, outage.ended_at))
    return AvailabilityDecision(False, tuple(completed))


class NightCaseServiceFactory:
    """Callable(session) accepted by create_app; registry and cursor secret remain pinned."""
    def __init__(self, settings, *, registry=None, clock=utc_now, transition_hook=None):
        self.settings, self.registry, self.clock = settings, registry or settings.registry(), clock
        self.transition_hook = transition_hook

    def __call__(self, session):
        async def availability(context): return await availability_snapshot(session, self.settings, context)
        return NightCaseApplicationService(session, self.clock, self.registry, transition_hook=self.transition_hook, availability_hook=availability, starts_enabled=self.settings.starts_enabled)


@dataclass(frozen=True)
class DeadlineClaim:
    deadline_id: str
    game_id: str
    revision: int
    due_at: datetime
    owner: str


def tick_command(game_id, clock, due_at):
    at = _stamp(due_at)
    return {'command_id': 'tick_' + _hash([game_id, clock['window_seq'], clock['timer_seq'], at])[:56],
        'kind': 'system.tick', 'window_seq': clock['window_seq'], 'timer_seq': clock['timer_seq'], 'params': {'expected_due_at': at}}


def same_generation(row, claim):
    return row is not None and row.revision == claim.revision and row.due_at == claim.due_at and row.claimed_by == claim.owner and row.status == 'claimed'


class NightCaseDeadlineWorker:
    def __init__(self, database, settings, *, service_factory=None, clock=utc_now, probe=readiness_probe, owner=None):
        self.database, self.settings, self.clock = database, settings, clock
        self.probe = (partial(readiness_probe, token=readiness_token(settings.cursor_secret))
                      if probe is readiness_probe and settings.enabled else probe)
        self.owner = owner or 'night-worker-' + uuid4().hex
        self.monitor = NightRuntimeHealthMonitor(database, settings, clock=clock)
        self.service_factory = service_factory or (NightCaseServiceFactory(settings, clock=clock) if settings.enabled else None)

    async def claim_due(self, now):
        async with self.database.transaction() as session:
            rows = list((await session.scalars(select(GameDeadline).join(Game, Game.id == GameDeadline.game_id).where(
                Game.mode == 'night_case', GameDeadline.kind == 'night.phase', GameDeadline.quarantined_at.is_(None),
                GameDeadline.due_at <= now, or_(GameDeadline.retry_at.is_(None), GameDeadline.retry_at <= now),
                or_(GameDeadline.status == 'pending', (GameDeadline.status == 'claimed') & (GameDeadline.claimed_at <= now - timedelta(seconds=self.settings.lease_seconds))))
                .order_by(GameDeadline.due_at, GameDeadline.id).limit(self.settings.batch_size)
                .with_for_update(of=GameDeadline, skip_locked=True))).all())
            claims = []
            for row in rows:
                row.status, row.claimed_by, row.claimed_at = 'claimed', self.owner, now
                claims.append(DeadlineClaim(row.id, row.game_id, row.revision, row.due_at, self.owner))
            await session.flush()
            return claims

    async def apply_claim(self, claim, now):
        async with self.database.transaction() as session:
            await operation_fence(session)
            locked = await NightCaseRepository(session).lock_game(claim.game_id)
            row = (await session.execute(select(GameDeadline).where(GameDeadline.id == claim.deadline_id).with_for_update())).scalar_one_or_none()
            if not same_generation(row, claim): return False
            if locked is None or locked.sealed.lifecycle != 'running':
                row.status, row.claimed_by, row.claimed_at = 'cancelled', None, None
                return False
            clock = locked.sealed.kernel['clock']
            kernel_due = _due(locked.sealed.kernel)
            if clock['timer_seq'] != claim.revision or kernel_due is None or datetime.fromisoformat(kernel_due['at'].replace('Z', '+00:00')) != claim.due_at:
                raise ValueError('deadline_generation_invalid')
            if claim.due_at > now:
                row.status, row.claimed_by, row.claimed_at = 'pending', None, None
                return False
            result = await self.service_factory(session).advance_due(game_id=claim.game_id, command=tick_command(claim.game_id, clock, claim.due_at))
            await session.refresh(row)
            if same_generation(row, claim): row.status, row.claimed_by, row.claimed_at = 'pending', None, None
            return bool(result['receipt']['accepted'])

    async def record_failure(self, claim, now, code):
        async with self.database.transaction() as session:
            await operation_fence(session)
            # Match transition lock order before audit's Game FK/key-share access.
            locked = await NightCaseRepository(session).lock_game(claim.game_id)
            row = (await session.execute(select(GameDeadline).where(GameDeadline.id == claim.deadline_id).with_for_update())).scalar_one_or_none()
            if locked is None or not same_generation(row, claim): return False
            row.attempts += 1
            row.last_error_code = code
            row.retry_at = now + timedelta(seconds=BACKOFF_SECONDS[min(row.attempts, 3) - 1])
            row.claimed_by = row.claimed_at = None
            row.status = 'quarantined' if row.attempts >= 3 else 'pending'
            if row.attempts >= 3:
                row.quarantined_at = now
                payload = {'deadline_id': row.id, 'timer_seq': row.revision, 'due_at': _stamp(row.due_at), 'code': code}
                await NightCaseRepository(session).put_command_receipt(game_id=claim.game_id, actor_key='system', actor_account_id=None,
                    client_command_id='quarantine_' + _hash(payload)[:48], kind='night.quarantine', payload=payload,
                    result={'status': 'game_quarantined'}, status='quarantined', now=now)
            await session.flush()
            return True

    async def run_once(self, *, now=None):
        if not self.settings.enabled: return 0
        now = _utc(now or self.clock())
        await self.monitor.heartbeat('worker', now=now)
        ready = await self.probe(self.settings.readiness_url)
        if not await self.monitor.heartbeat('worker', now=now, probe_ready=ready): return 0
        claims = await self.claim_due(now)
        settled = 0
        for claim in claims:
            try:
                settled += await self.apply_claim(claim, now)
            except asyncio.CancelledError: raise
            except (OperationalError, InterfaceError, OSError, TimeoutError):
                logger.warning('Night deadline deferred: database_unavailable')
            except DBAPIError as exc:
                if exc.connection_invalidated:
                    logger.warning('Night deadline deferred: database_unavailable')
                else:
                    try: await self.record_failure(claim, now, 'transition_failed')
                    except Exception: logger.warning('Night deadline failure not persisted: database_unavailable')
            except NightCaseError as exc:
                if exc.code == 'runtime_delayed':
                    # Health changed after probe; do not count operational downtime as a game fault.
                    continue
                code = 'snapshot_invalid' if exc.code == 'game_quarantined' else 'transition_failed'
                try: await self.record_failure(claim, now, code)
                except Exception: logger.warning('Night deadline failure not persisted: database_unavailable')
            except Exception:
                try: await self.record_failure(claim, now, 'transition_failed')
                except Exception: logger.warning('Night deadline failure not persisted: database_unavailable')
        return settled
