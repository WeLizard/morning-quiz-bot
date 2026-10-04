"""Single-bot reconciliation of persisted settings and in-memory schedulers."""
import asyncio
from datetime import datetime, timezone
import logging

from storage.repositories import OperationalRepository
from storage.schedule_source import ScheduleSource

logger = logging.getLogger(__name__)
SCHEDULE_SYNC_INTERVAL = 15


class ScheduleSync:
    def __init__(self, database, config, daily, wisdom):
        self.database = database
        self.source = ScheduleSource(database, config)
        self.daily, self.wisdom = daily, wisdom
        self._lock = asyncio.Lock()
        self._known_chats = set()

    async def run_once(self, context=None):
        async with self._lock:
            # A failed read must not be mistaken for an empty database.
            states = await self.source.read()
            applied, errors = {}, {}
            for chat_id in sorted(self._known_chats | states.keys()):
                state = states.get(chat_id)
                try:
                    quiz = self.source.plan(state, "quiz")
                    wisdom = self.source.plan(state, "wisdom")
                    self.daily.apply_postgres_plan(chat_id, quiz)
                    self.wisdom.apply_postgres_plan(chat_id, wisdom)
                    if state is not None:
                        applied[str(chat_id)] = state.revision
                    else:
                        self._known_chats.discard(chat_id)
                except Exception as exc:
                    logger.exception("Не удалось синхронизировать расписание чата %s", chat_id)
                    errors[str(chat_id)] = type(exc).__name__
            self._known_chats.update(states)
            result = {"checked_at": datetime.now(timezone.utc).isoformat(),
                      "applied_revisions": applied, "failed_chats": errors,
                      "interval_seconds": SCHEDULE_SYNC_INTERVAL}
            async with self.database.transaction() as session:
                await OperationalRepository(session).upsert_system_state("schedule_sync_status", result)
            return result

    async def tick(self, context=None):
        try:
            await self.run_once(context)
        except Exception:
            # JobQueue retries at the next tick; existing jobs remain intact.
            logger.exception("Синхронизация расписаний временно недоступна")

    def install(self, job_queue):
        if job_queue is None:
            raise RuntimeError("JobQueue is required for schedule synchronization")
        return job_queue.run_repeating(
            self.tick, interval=SCHEDULE_SYNC_INTERVAL, first=SCHEDULE_SYNC_INTERVAL,
            name="postgres_schedule_sync",
            job_kwargs={"id": "postgres_schedule_sync", "replace_existing": True,
                        "coalesce": True, "max_instances": 1},
        )
