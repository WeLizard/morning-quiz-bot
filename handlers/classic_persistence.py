"""PostgreSQL checkpoints and reinstallation of classic quiz jobs."""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import logging

from storage.classic_sessions import ClassicSessions
from utils import schedule_job_unique

logger = logging.getLogger(__name__)


class ClassicPersistenceMixin:
    async def _classic_send_allowed(self, quiz):
        if await self._discard_interrupted_classic(quiz.chat_id):
            return False
        return self.state.get_active_quiz(quiz.chat_id) is quiz and not quiz.is_stopping

    async def _discard_interrupted_classic(self, chat_id):
        service = self._pg_sessions
        quiz = self.state.get_active_quiz(chat_id)
        if not service or not quiz:
            return False
        from storage.admin_actions import AdminActions
        if await AdminActions(service.database).session_active(service.key(chat_id), quiz.session_id):
            return False
        quiz.is_stopping = True
        for poll_id in list(quiz.active_poll_ids_in_session):
            self.state.remove_current_poll(poll_id)
        self.state.remove_active_quiz(chat_id)
        return True

    @property
    def _pg_sessions(self):
        storage = getattr(self.data_manager, "postgres_storage", None)
        return ClassicSessions(storage.database) if storage else None

    def _classic_snapshot(self, quiz):
        for poll_id in quiz.active_poll_ids_in_session:
            poll = self.state.get_current_poll_data(poll_id)
            if poll:
                quiz.poll_history[poll_id] = deepcopy(poll)
        value = deepcopy(vars(quiz))
        value.pop("next_question_job_name", None)
        value["polls"] = value.pop("poll_history")
        value["quiz_start_time"] = quiz.quiz_start_time.isoformat()
        value["next_question_at"] = quiz.next_question_at
        value["storage_version"] = 1
        for poll in value["polls"].values():
            poll.pop("job_poll_end_name", None)
        return self.data_manager._convert_sets_to_lists(value)

    async def _checkpoint_classic(self, quiz, *, create=False, status="active"):
        service = self._pg_sessions
        if not service:
            return
        if not hasattr(self, "_checkpoint_locks"):
            self._checkpoint_locks = {}
        async with self._checkpoint_locks.setdefault(quiz.chat_id, asyncio.Lock()):
            value = self._classic_snapshot(quiz)
            saved = await service.create(value) if create else await service.save(value, status=status)
            quiz.revision = saved["revision"]

    async def _confirm_classic_poll(self, quiz, poll_id):
        poll = self.state.get_current_poll_data(poll_id)
        poll["session_id"] = quiz.session_id
        poll["end_timestamp"] = poll["open_timestamp"] + quiz.open_period_seconds
        quiz.active_poll_ids_in_session.add(poll_id)
        quiz.latest_poll_id_sent = poll_id
        quiz.progression_triggered_for_poll[poll_id] = False
        quiz.current_question_index += 1
        quiz.storage_phase = "active"
        quiz.next_question_at = None
        if quiz.interval_seconds and quiz.current_question_index < quiz.num_questions_to_ask:
            quiz.next_question_at = (datetime.now(timezone.utc) + timedelta(seconds=quiz.interval_seconds)).isoformat()
        try:
            await self._checkpoint_classic(quiz)
        except Exception:
            quiz.is_stopping = True  # Do not accept answers to an unconfirmed snapshot.
            raise

    def _valid_classic_job(self, context, chat_id):
        if not self._pg_sessions:
            return True
        quiz = self.state.get_active_quiz(chat_id)
        return bool(quiz and not quiz.is_stopping and context.job.data.get("session_id") == quiz.session_id)

    async def _queue_classic_messages(self, chat_id, message_ids):
        from storage.cleanup import CleanupQueue
        queue = CleanupQueue(self.data_manager.postgres_storage.database)
        deadline = datetime.now(timezone.utc) + timedelta(seconds=180)
        # Also used for result/solution messages created after the closing commit.
        async with queue.database.transaction() as session:
            for message_id in set(message_ids):
                await queue.enqueue_in(session, chat_id, message_id, deadline, source="classic")

    async def _restore_postgres_classic(self):
        from telegram.ext import CallbackContext
        context = CallbackContext(self.application)
        service = self._pg_sessions
        for key, _ in await service.legacy_active():
            await service.interrupt_legacy(key)
            logger.warning(
                "Legacy session %s remained outside games after cutover; marked interrupted",
                key,
            )
        for key, saved in await service.active():
            if saved.get('mode') == 'classic':
                # V2 is resumed from games/deadlines by the shared worker; it
                # must never be reconstructed into Telegram BotState.
                continue
            if saved.get("storage_version") != 1:
                await service.interrupt_legacy(key)
                logger.warning("Legacy session %s lacks poll/deadline checkpoints; marked interrupted", key)
                continue
            from storage.admin_actions import AdminActions
            if not await AdminActions(service.database).allowed(saved['chat_id']):
                await service.save(saved, status='interrupted')
                continue
            quiz = self.restore_quiz_from_saved_data(saved["chat_id"], saved)
            if quiz is None:
                raise ValueError(f"Invalid saved classic session: {key}")
            for attr in ("session_id", "revision", "storage_phase", "next_question_at"):
                setattr(quiz, attr, saved.get(attr))
            quiz.poll_history = deepcopy(saved.get("polls", {}))
            quiz.scores = await service.scores(quiz.chat_id, list(quiz.poll_history))
            if quiz.storage_phase == "sending" or quiz.is_stopping:
                quiz.is_stopping = True
                await self._checkpoint_classic(quiz, status="interrupted")
                logger.warning("Session %s interrupted: send/stop had no final acknowledgement", key)
                continue
            if not quiz.active_poll_ids_in_session.issubset(quiz.poll_history):
                raise ValueError(f"Missing durable poll data in {key}")
            self.state.add_active_quiz(quiz.chat_id, quiz)
            now = datetime.now(timezone.utc)
            for poll_id in quiz.active_poll_ids_in_session:
                poll = deepcopy(quiz.poll_history[poll_id])
                self.state.add_current_poll(poll_id, poll)
                name = f"poll_end_chat_{quiz.chat_id}_poll_{poll_id}"
                poll["job_poll_end_name"] = name
                deadline = datetime.fromtimestamp(poll["end_timestamp"], timezone.utc) + timedelta(seconds=self.app_config.job_grace_period_seconds)
                schedule_job_unique(self.application.job_queue, job_name=name, callback=self._handle_poll_end_job,
                    when=max(deadline, now + timedelta(milliseconds=100)),
                    data={"chat_id": quiz.chat_id, "ended_poll_id": poll_id, "session_id": quiz.session_id})
            if quiz.current_question_index < quiz.num_questions_to_ask and (quiz.next_question_at or not quiz.active_poll_ids_in_session):
                deadline = datetime.fromisoformat(quiz.next_question_at) if quiz.next_question_at else now
                name = f"restore_next_{quiz.session_id}_{quiz.current_question_index}"
                quiz.next_question_job_name = name
                schedule_job_unique(self.application.job_queue, job_name=name, callback=self._trigger_next_question_job_after_interval,
                    when=max(deadline, now + timedelta(milliseconds=100)),
                    data={"chat_id": quiz.chat_id, "expected_q_index_at_trigger": quiz.current_question_index,
                          "session_id": quiz.session_id})
            elif not quiz.active_poll_ids_in_session:
                await self._finalize_quiz_session(context, quiz.chat_id)
            # Notification deliberately omitted: startup must not depend on a chat send.
