"""Durable deletion commands. Completed rows are tombstones, not absent rows."""
from datetime import datetime, timedelta, timezone
import logging
import math
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from telegram.error import BadRequest, RetryAfter

from .models import Chat, MessageCleanupItem, SystemState

logger = logging.getLogger(__name__)


class CleanupQueue:
    RETRY_KEY = "cleanup_retry_until"

    def __init__(self, database):
        self.database = database

    @staticmethod
    async def enqueue_in(session, chat_id, message_id, delete_after, *, source="bot"):
        await session.execute(insert(MessageCleanupItem).values(
            chat_id=int(chat_id), message_id=int(message_id), delete_after=delete_after,
            payload={"state": "pending", "generation": uuid4().hex, "source": source},
        ).on_conflict_do_nothing(index_elements=[MessageCleanupItem.chat_id, MessageCleanupItem.message_id]))

    async def enqueue(self, chat_id, message_id, delete_after, *, source="bot"):
        async with self.database.transaction() as session:
            await self.enqueue_in(session, chat_id, message_id, delete_after, source=source)

    async def acknowledge(self, chat_id, message_id):
        # Upsert a tombstone even when the original enqueue is still in flight.
        values = {"chat_id": int(chat_id), "message_id": int(message_id),
                  "payload": {"state": "done", "generation": uuid4().hex}}
        async with self.database.transaction() as session:
            await session.execute(insert(MessageCleanupItem).values(**values).on_conflict_do_update(
                index_elements=[MessageCleanupItem.chat_id, MessageCleanupItem.message_id],
                set_={"payload": values["payload"]},
            ))

    async def due(self, *, limit=50, now=None):
        now = now or datetime.now(timezone.utc)
        async with self.database.transaction() as session:
            cooldown = await session.get(SystemState, self.RETRY_KEY)
            if cooldown and cooldown.payload["until"] > now.timestamp():
                return []
            # Legacy imports had only a creation timestamp. Normalize once,
            # without touching existing deadlines or resurrecting completed rows.
            legacy = (await session.scalars(select(MessageCleanupItem).where(
                MessageCleanupItem.delete_after.is_(None),
                MessageCleanupItem.payload["state"].as_string().is_(None),
            ).with_for_update())).all()
            for row in legacy:
                timestamp = (row.payload or {}).get("legacy_timestamp")
                try:
                    if isinstance(timestamp, bool) or not math.isfinite(float(timestamp)):
                        raise ValueError("invalid timestamp")
                    created = datetime.fromtimestamp(float(timestamp), timezone.utc)
                except (TypeError, ValueError, OverflowError, OSError):
                    created = row.created_at
                row.delete_after = created + timedelta(seconds=120)
                row.payload = {**(row.payload or {}), "state": "pending", "generation": uuid4().hex}
            await session.flush()
            rows = (await session.scalars(select(MessageCleanupItem).where(
                MessageCleanupItem.payload["state"].as_string() == "pending",
                MessageCleanupItem.delete_after <= now,
            ).order_by(MessageCleanupItem.delete_after, MessageCleanupItem.chat_id, MessageCleanupItem.message_id)
                .limit(max(0, min(limit, 50))))).all()
            return [(r.chat_id, r.message_id, dict(r.payload)) for r in rows]

    async def defer(self, chat_id, message_id, payload, seconds):
        async with self.database.transaction() as session:
            await session.execute(update(MessageCleanupItem).where(
                MessageCleanupItem.chat_id == chat_id, MessageCleanupItem.message_id == message_id,
                MessageCleanupItem.payload["state"].as_string() == "pending",
                MessageCleanupItem.payload["generation"].as_string() == payload["generation"],
            ).values(delete_after=datetime.now(timezone.utc) + timedelta(seconds=max(1, seconds))))

    async def pause(self, seconds):
        """Persist a queue-wide cooldown so the next tick/restart also waits."""
        until = (datetime.now(timezone.utc) + timedelta(seconds=max(1, seconds))).timestamp()
        async with self.database.transaction() as session:
            await session.execute(insert(SystemState).values(key=self.RETRY_KEY, payload={"until": until})
                                  .on_conflict_do_nothing(index_elements=[SystemState.key]))
            row = await session.scalar(select(SystemState).where(SystemState.key == self.RETRY_KEY).with_for_update())
            row.payload = {"until": max(until, row.payload["until"])}

    async def process_due(self, bot, state=None, *, default_auto_delete=True):
        completed = 0
        enabled_by_chat = {}
        for chat_id, message_id, payload in await self.due():
            if chat_id not in enabled_by_chat:
                async with self.database.transaction() as session:
                    chat = await session.get(Chat, chat_id)
                    settings = chat.settings if chat else {}
                    enabled_by_chat[chat_id] = (settings or {}).get("auto_delete_bot_messages", default_auto_delete)
            if not enabled_by_chat[chat_id]:
                await self.defer(chat_id, message_id, payload, 300)
                continue
            retry_delay = 30
            try:
                await bot.delete_message(chat_id=chat_id, message_id=message_id)
            except RetryAfter as exc:
                retry_delay = exc.retry_after.total_seconds() if isinstance(exc.retry_after, timedelta) else exc.retry_after
                await self.pause(retry_delay)
                await self.defer(chat_id, message_id, payload, retry_delay)
                break
            except Exception as exc:
                terminal = isinstance(exc, BadRequest) and any(text in str(exc).lower() for text in (
                    "message to delete not found", "message can't be deleted", "message_id_invalid",
                ))
                if not terminal:
                    logger.warning("Deletion deferred for chat=%s message=%s: %s", chat_id, message_id, type(exc).__name__)
                    await self.defer(chat_id, message_id, payload, retry_delay)
                    continue
            await self.acknowledge(chat_id, message_id)
            completed += 1
            if state is not None:
                messages = state.generic_messages_to_delete.get(chat_id, {})
                messages.pop(message_id, None)
                if not messages:
                    state.generic_messages_to_delete.pop(chat_id, None)
        return completed
