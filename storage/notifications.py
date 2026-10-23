"""Durable notification outbox shared by game modes and delivery adapters."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from uuid import UUID, uuid4

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert

from .models import NotificationOutbox, NotificationResolution, NotificationQuarantineReceipt


SENDERS_STOPPED_ATTESTATION = 'ALL_TELEGRAM_SENDERS_INDEPENDENTLY_CONFIRMED_STOPPED'


class NotificationResolutionConflict(ValueError):
    """The operator's action or observed notification is no longer applicable."""


class NotificationQueue:
    def __init__(self, database):
        self.database = database

    @staticmethod
    async def enqueue_in(
        session, *, kind: str, dedupe_key: str, payload: dict,
        game_id: str | None = None, chat_id: int | None = None,
        user_id: int | None = None, available_at: datetime | None = None,
    ) -> bool:
        """Insert in the caller's state-transition transaction, once per event."""
        if not kind or not dedupe_key or not isinstance(payload, dict):
            raise ValueError('Некорректное уведомление.')
        statement = insert(NotificationOutbox).values(
            id=str(uuid4()), game_id=game_id, chat_id=chat_id, user_id=user_id,
            kind=kind, payload=payload, dedupe_key=dedupe_key,
            status='pending', available_at=available_at or datetime.now(timezone.utc),
        ).on_conflict_do_nothing(
            index_elements=[NotificationOutbox.dedupe_key]
        ).returning(NotificationOutbox.id)
        return await session.scalar(statement) is not None

    async def claim(
        self,
        worker_id: str,
        *,
        kinds: set[str] | None = None,
        now: datetime | None = None,
    ):
        """Claim one pending item and return its completion-fencing version.

        Sending claims are never auto-retried blindly. The version fences DB
        callbacks only; it does not establish external transport quiescence.
        """
        if not 1 <= len(worker_id) <= 96:
            raise ValueError('Некорректный идентификатор worker.')
        if kinds is not None and not kinds:
            return None
        current = now or datetime.now(timezone.utc)
        async with self.database.transaction() as session:
            filters = [
                NotificationOutbox.status == 'pending',
                NotificationOutbox.available_at <= current,
            ]
            if kinds is not None:
                filters.append(NotificationOutbox.kind.in_(kinds))
            row = await session.scalar(
                select(NotificationOutbox).where(*filters)
                .order_by(NotificationOutbox.available_at, NotificationOutbox.id)
                .limit(1).with_for_update(skip_locked=True)
            )
            if row is None:
                return None
            row.status = 'sending'
            row.claimed_by = worker_id
            row.claimed_at = current
            row.attempts += 1
            row.version += 1
            await session.flush()
            return {
                'id': row.id, 'kind': row.kind, 'game_id': row.game_id,
                'chat_id': row.chat_id, 'user_id': row.user_id,
                'payload': dict(row.payload or {}), 'attempts': row.attempts,
                'claim_version': row.version,
            }

    async def delivered(self, item_id: str, worker_id: str, *, claim_version: int) -> bool:
        """Complete only the sending attempt represented by claim_version."""
        async with self.database.transaction() as session:
            result = await session.execute(update(NotificationOutbox).where(
                NotificationOutbox.id == item_id,
                NotificationOutbox.status == 'sending',
                NotificationOutbox.claimed_by == worker_id,
                NotificationOutbox.version == claim_version,
            ).values(status='delivered', delivered_at=func.now(), last_error=None,
                     version=NotificationOutbox.version + 1))
            return result.rowcount == 1

    async def skipped(self, item_id: str, worker_id: str, *, claim_version: int) -> bool:
        """Close an obsolete notification without counting it as a sent message."""
        async with self.database.transaction() as session:
            result = await session.execute(update(NotificationOutbox).where(
                NotificationOutbox.id == item_id,
                NotificationOutbox.status == 'sending',
                NotificationOutbox.claimed_by == worker_id,
                NotificationOutbox.version == claim_version,
            ).values(status='skipped', delivered_at=None, version=NotificationOutbox.version + 1))
            return result.rowcount == 1

    async def retry_after(
        self, item_id: str, worker_id: str, seconds: float, *, claim_version: int,
    ) -> bool:
        """A Telegram 429 is an explicit rejection, so retrying later is safe."""
        due = datetime.now(timezone.utc) + timedelta(seconds=max(0.0, min(seconds, 3600.0)))
        async with self.database.transaction() as session:
            result = await session.execute(update(NotificationOutbox).where(
                NotificationOutbox.id == item_id,
                NotificationOutbox.status == 'sending',
                NotificationOutbox.claimed_by == worker_id,
                NotificationOutbox.version == claim_version,
            ).values(status='pending', available_at=due, claimed_by=None,
                     claimed_at=None, last_error='RetryAfter',
                     version=NotificationOutbox.version + 1))
            return result.rowcount == 1

    async def uncertain(
        self, item_id: str, worker_id: str, error_type: str, *, claim_version: int,
    ) -> bool:
        """Do not resend when Telegram may already have accepted the message."""
        async with self.database.transaction() as session:
            result = await session.execute(update(NotificationOutbox).where(
                NotificationOutbox.id == item_id,
                NotificationOutbox.status == 'sending',
                NotificationOutbox.claimed_by == worker_id,
                NotificationOutbox.version == claim_version,
            ).values(status='uncertain', last_error=error_type[:200],
                     version=NotificationOutbox.version + 1))
            return result.rowcount == 1

    async def resolve(self, **request) -> dict:
        """Close uncertainty without any transport or game-state side effects."""
        async with self.database.transaction() as session:
            return await self.resolve_in(session, **request)

    async def quarantine(self, **request) -> dict:
        """Offline operator action only after independently verified sender stop."""
        async with self.database.transaction() as session:
            return await self.quarantine_in(session, **request)

    @staticmethod
    async def quarantine_in(
        session, *, item_id: str, action_id: str, operator_id: str,
        expected_version: int, expected_claimed_by: str | None,
        expected_claimed_at: datetime | None, reason: str, evidence: dict,
        senders_stopped_attestation: str,
    ) -> dict:
        """Move exactly one observed orphan sending attempt to uncertain.

        Attestation is the operator's assertion, not automated proof. Neither
        lease age nor fencing proves that an external HTTP sender has stopped.
        No delivery/retry/game operation is performed here.
        """
        if senders_stopped_attestation != SENDERS_STOPPED_ATTESTATION:
            raise ValueError('Требуется подтверждение независимой остановки всех отправителей.')
        for value, maximum in ((item_id, 64), (action_id, 96), (operator_id, 96), (reason, 2000)):
            if not isinstance(value, str) or not value.strip() or len(value) > maximum:
                raise ValueError('Некорректные данные оператора.')
        try:
            action_id = str(UUID(action_id))
        except ValueError as exc:
            raise ValueError('action_id должен быть UUID.') from exc
        if type(expected_version) is not int or expected_version < 0:
            raise ValueError('Некорректная версия уведомления.')
        if expected_claimed_by is not None and (
            not isinstance(expected_claimed_by, str) or not expected_claimed_by.strip()
            or len(expected_claimed_by) > 96
        ):
            raise ValueError('Некорректный ожидаемый отправитель.')
        if expected_claimed_at is not None:
            if (not isinstance(expected_claimed_at, datetime)
                    or expected_claimed_at.tzinfo is None
                    or expected_claimed_at.utcoffset() is None):
                raise ValueError('claimed_at требует timestamp с часовым поясом.')
            expected_claimed_at = expected_claimed_at.astimezone(timezone.utc)
        # This is recorded evidence, not verification by this service. Operators
        # must inventory all deployments and in-flight transport activity.
        if (not isinstance(evidence, dict) or not evidence
                or not isinstance(evidence.get('verification_method'), str)
                or not evidence['verification_method'].strip()
                or not isinstance(evidence.get('sender_inventory'), str)
                or not evidence['sender_inventory'].strip()):
            raise ValueError('Требуются verification_method и sender_inventory остановки.')
        request = dict(item_id=item_id, action_id=action_id, operator_id=operator_id,
                       expected_version=expected_version, expected_claimed_by=expected_claimed_by,
                       expected_claimed_at=expected_claimed_at.isoformat() if expected_claimed_at else None,
                       reason=reason, evidence=evidence,
                       senders_stopped_attestation=senders_stopped_attestation)
        try:
            encoded = json.dumps(request, sort_keys=True, separators=(',', ':'),
                                 ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError('Свидетельство должно быть JSON.') from exc
        if len(encoded.encode('utf-8')) > 8192:
            raise ValueError('Слишком большое свидетельство.')
        fingerprint = hashlib.sha256(encoded.encode('utf-8')).hexdigest()
        lock_key = int.from_bytes(hashlib.sha256(action_id.encode()).digest()[:8],
                                  'big', signed=True)
        await session.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': lock_key})
        receipt = await session.get(NotificationQuarantineReceipt, action_id)
        if await session.get(NotificationResolution, action_id) is not None:
            raise NotificationResolutionConflict('action_id уже использован для terminal resolution.')
        if receipt is not None:
            if receipt.request_fingerprint != fingerprint:
                raise NotificationResolutionConflict('action_id уже использован другим запросом.')
            return NotificationQueue._quarantine_receipt(receipt)
        row = await session.scalar(select(NotificationOutbox).where(
            NotificationOutbox.id == item_id,
        ).with_for_update().execution_options(populate_existing=True))
        if row is None:
            raise NotificationResolutionConflict('Уведомление не найдено.')
        if row.version != expected_version:
            raise NotificationResolutionConflict('Версия уведомления изменилась.')
        if row.status != 'sending':
            raise NotificationResolutionConflict('Карантин разрешён только для sending.')
        if row.claimed_by != expected_claimed_by or row.claimed_at != expected_claimed_at:
            raise NotificationResolutionConflict('Попытка отправки изменилась.')
        row.status = 'uncertain'
        row.version += 1
        row.last_error = 'OperatorQuarantine'
        receipt = NotificationQuarantineReceipt(
            action_id=action_id, item_id=item_id, request_fingerprint=fingerprint,
            operator_id=operator_id, reason=reason, evidence=json.loads(encoded)['evidence'],
            previous_version=expected_version, resulting_version=row.version,
            claimed_by=row.claimed_by, claimed_at=row.claimed_at,
            created_at=datetime.now(timezone.utc),
        )
        session.add(receipt)
        await session.flush()
        return NotificationQueue._quarantine_receipt(receipt)

    @staticmethod
    def _quarantine_receipt(receipt) -> dict:
        return {
            'action_id': receipt.action_id, 'item_id': receipt.item_id,
            'operator_id': receipt.operator_id, 'status': 'uncertain',
            'previous_version': receipt.previous_version,
            'version': receipt.resulting_version,
            'quarantined_at': receipt.created_at.isoformat(),
        }

    @staticmethod
    async def resolve_in(
        session, *, item_id: str, action_id: str, operator_id: str,
        expected_version: int, decision: str, reason: str, evidence: dict,
    ) -> dict:
        """Resolve and save a replayable receipt in the caller's transaction.

        Authorization belongs to the authenticated local operator entry point.
        A stale sending lease is never proof of failure.
        """
        for value, maximum in ((item_id, 64), (action_id, 96), (operator_id, 96), (reason, 2000)):
            if not isinstance(value, str) or not value.strip() or len(value) > maximum:
                raise ValueError('Некорректные данные оператора.')
        try:
            action_id = str(UUID(action_id))
        except ValueError as exc:
            raise ValueError('action_id должен быть UUID.') from exc
        if type(expected_version) is not int or expected_version < 0:
            raise ValueError('Некорректная версия уведомления.')
        if decision not in {'confirmed_delivered', 'closed_without_resend'}:
            raise ValueError('Некорректное решение оператора.')
        if not isinstance(evidence, dict) or not evidence:
            raise ValueError('Требуется свидетельство проверки.')
        if decision == 'confirmed_delivered':
            if (type(evidence.get('chat_id')) is not int or evidence['chat_id'] == 0
                    or type(evidence.get('message_id')) is not int or evidence['message_id'] <= 0
                    or not isinstance(evidence.get('verification_method'), str)
                    or not evidence['verification_method'].strip()):
                raise ValueError('Требуются chat_id, message_id и verification_method.')
        request = dict(item_id=item_id, action_id=action_id, operator_id=operator_id,
                       expected_version=expected_version, decision=decision,
                       reason=reason, evidence=evidence)
        try:
            encoded = json.dumps(request, sort_keys=True, separators=(',', ':'),
                                 ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError('Свидетельство должно быть JSON.') from exc
        if len(encoded.encode('utf-8')) > 8192:
            raise ValueError('Слишком большое свидетельство.')
        fingerprint = hashlib.sha256(encoded.encode('utf-8')).hexdigest()
        # Serializes global action IDs, even for requests against different rows.
        # Hash collisions only serialize unrelated actions; receipts still use
        # the full action_id primary key and full request fingerprint.
        lock_key = int.from_bytes(hashlib.sha256(action_id.encode()).digest()[:8],
                                  'big', signed=True)
        await session.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': lock_key})
        receipt = await session.get(NotificationResolution, action_id)
        if await session.get(NotificationQuarantineReceipt, action_id) is not None:
            raise NotificationResolutionConflict('action_id уже использован для карантина.')
        if receipt is not None:
            if receipt.request_fingerprint != fingerprint:
                raise NotificationResolutionConflict('action_id уже использован другим запросом.')
            return NotificationQueue._resolution_receipt(receipt)
        row = await session.scalar(select(NotificationOutbox).where(
            NotificationOutbox.id == item_id,
        ).with_for_update().execution_options(populate_existing=True))
        if row is None:
            raise NotificationResolutionConflict('Уведомление не найдено.')
        if row.version != expected_version:
            raise NotificationResolutionConflict('Версия уведомления изменилась.')
        if row.status != 'uncertain':
            raise NotificationResolutionConflict('Разрешено закрывать только uncertain.')
        if decision == 'confirmed_delivered':
            # For a direct-user message the transport recipient is user_id.
            recipient = row.chat_id if row.chat_id is not None else row.user_id
            if recipient is not None and evidence['chat_id'] != recipient:
                raise ValueError('Свидетельство относится к другому чату.')
        row.status = 'resolved'
        row.resolved_at = datetime.now(timezone.utc)
        row.version += 1
        receipt = NotificationResolution(
            action_id=action_id, item_id=item_id, request_fingerprint=fingerprint,
            operator_id=operator_id, decision=decision, reason=reason,
            evidence=json.loads(encoded)['evidence'], previous_version=expected_version,
            resulting_version=row.version, created_at=row.resolved_at,
        )
        session.add(receipt)
        await session.flush()
        return NotificationQueue._resolution_receipt(receipt)

    @staticmethod
    def _resolution_receipt(receipt) -> dict:
        return {
            'action_id': receipt.action_id, 'item_id': receipt.item_id,
            'operator_id': receipt.operator_id, 'decision': receipt.decision,
            'status': 'resolved', 'previous_version': receipt.previous_version,
            'version': receipt.resulting_version,
            'resolved_at': receipt.created_at.isoformat(),
        }
