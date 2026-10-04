"""Durable notification outbox shared by game modes and delivery adapters."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert

from .models import NotificationOutbox


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
        """Claim one pending item. Sending claims are never auto-retried blindly."""
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
            await session.flush()
            return {
                'id': row.id, 'kind': row.kind, 'game_id': row.game_id,
                'chat_id': row.chat_id, 'user_id': row.user_id,
                'payload': dict(row.payload or {}), 'attempts': row.attempts,
            }

    async def delivered(self, item_id: str, worker_id: str) -> bool:
        async with self.database.transaction() as session:
            result = await session.execute(update(NotificationOutbox).where(
                NotificationOutbox.id == item_id,
                NotificationOutbox.status == 'sending',
                NotificationOutbox.claimed_by == worker_id,
            ).values(status='delivered', delivered_at=func.now(), last_error=None))
            return result.rowcount == 1

    async def retry_after(self, item_id: str, worker_id: str, seconds: float) -> bool:
        """A Telegram 429 is an explicit rejection, so retrying later is safe."""
        due = datetime.now(timezone.utc) + timedelta(seconds=max(0.0, min(seconds, 3600.0)))
        async with self.database.transaction() as session:
            result = await session.execute(update(NotificationOutbox).where(
                NotificationOutbox.id == item_id,
                NotificationOutbox.status == 'sending',
                NotificationOutbox.claimed_by == worker_id,
            ).values(status='pending', available_at=due, claimed_by=None,
                     claimed_at=None, last_error='RetryAfter'))
            return result.rowcount == 1

    async def uncertain(self, item_id: str, worker_id: str, error_type: str) -> bool:
        """Do not resend when Telegram may already have accepted the message."""
        async with self.database.transaction() as session:
            result = await session.execute(update(NotificationOutbox).where(
                NotificationOutbox.id == item_id,
                NotificationOutbox.status == 'sending',
                NotificationOutbox.claimed_by == worker_id,
            ).values(status='uncertain', last_error=error_type[:200]))
            return result.rowcount == 1
