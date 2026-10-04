"""Photo metadata and durable series; never fall back to operational JSON."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
import json

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from .members import MemberService
from .games import GameRepository
from .models import Game, PhotoQuizItem
from .repositories import OperationalRepository
from .admin_actions import operation_fence, require_access


class PhotoSessionConflict(RuntimeError):
    pass


class PhotoMetadataConflict(RuntimeError):
    pass


def metadata_version(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def metadata(item):
    return {**deepcopy(item.metadata_json or {}), "correct_answer": item.correct_answer,
            "hints": deepcopy(item.hints or {}), "enabled": item.enabled}


class PhotoCatalog:
    def __init__(self, database):
        self.database = database

    async def load(self):
        async with self.database.transaction() as session:
            items = (await session.scalars(select(PhotoQuizItem))).all()
            return {item.media_key: metadata(item) for item in items}

    async def get_or_create(self, key):
        async with self.database.transaction() as session:
            await session.execute(insert(PhotoQuizItem).values(
                media_key=key, correct_answer=key, metadata_json={"display_answer": key},
                enabled=True, hints={},
            ).on_conflict_do_nothing(index_elements=[PhotoQuizItem.media_key]))
            return metadata(await session.get(PhotoQuizItem, key))

    async def patch(self, key, changes, *, expected_version):
        if not changes or set(changes) - {"correct_answer", "display_answer", "hints", "enabled"}:
            raise ValueError("Unsupported photo metadata fields")
        async with self.database.transaction() as session:
            item = await session.scalar(select(PhotoQuizItem).where(PhotoQuizItem.media_key == key).with_for_update())
            if item is None:
                raise LookupError("Фото-вопрос не найден")
            if metadata_version(metadata(item)) != expected_version:
                raise PhotoMetadataConflict("Фото-вопрос уже изменён. Загрузите актуальную версию.")
            if (item.metadata_json or {}).get('archived'):
                raise PhotoMetadataConflict('Сначала восстановите фото-вопрос из корзины.')
            if "correct_answer" in changes:
                item.correct_answer = changes["correct_answer"]
                # The game prefers display_answer, so keep it in sync by default.
                item.metadata_json = {**(item.metadata_json or {}),
                                      "display_answer": changes.get("display_answer", changes["correct_answer"])}
            elif "display_answer" in changes:
                item.metadata_json = {**(item.metadata_json or {}), "display_answer": changes["display_answer"]}
            if "hints" in changes:
                item.hints = deepcopy(changes["hints"])
            if "enabled" in changes:
                item.enabled = changes["enabled"]
            return metadata(item)

    async def archive(self, key, *, archived, expected_version):
        async with self.database.transaction() as session:
            item = await session.scalar(select(PhotoQuizItem).where(PhotoQuizItem.media_key == key).with_for_update())
            if item is None:
                raise LookupError('Фото-вопрос не найден')
            if metadata_version(metadata(item)) != expected_version:
                raise PhotoMetadataConflict('Фото-вопрос изменился. Обновите каталог.')
            value = deepcopy(item.metadata_json or {})
            if archived and not value.get('archived'):
                value.update(archived=True, archived_at=datetime.now(timezone.utc).isoformat(), enabled_before_archive=item.enabled)
                item.enabled = False
            elif not archived and value.get('archived'):
                item.enabled = bool(value.pop('enabled_before_archive', False))
                value.update(archived=False)
            item.metadata_json = value
            return metadata(item)


class PhotoSessions:
    """Legacy Telegram snapshot adapter backed only by the games substrate.

    New clients use :class:`application.photo.PhotoApplicationService`.  This
    adapter keeps an already isolated manager functional during the cutover,
    without retaining ``quiz_sessions`` as a second runtime store.
    """
    def __init__(self, database):
        self.database = database

    @staticmethod
    def key(chat_id):
        return f"photo:{chat_id}"

    async def _locked(self, session, state):
        row = await GameRepository(session).current(
            chat_id=state["chat_id"], mode="photo", lock=True,
        )
        if row is None or row.state.get("session_id") != state["session_id"]:
            raise PhotoSessionConflict("Фото-серия уже заменена или удалена")
        return row

    @staticmethod
    def _check_revision(row, state):
        if row.status != "active" or row.state.get("revision", 0) != state.get("revision", 0):
            raise PhotoSessionConflict("Состояние фото-серии уже изменилось")

    @staticmethod
    def _write(row, state, status="active"):
        value = deepcopy(state)
        value["revision"] = row.state.get("revision", 0) + 1
        return deepcopy(value)

    @staticmethod
    def _deadlines(value, status="active"):
        if status != "active" or value.get("phase") != "active" or not value.get("is_active"):
            return {}
        started = value.get("start_time")
        if not isinstance(started, str):
            return {}
        return {"legacy-close": datetime.fromisoformat(started) + timedelta(seconds=value["time_limit"])}

    async def create(self, state):
        async with self.database.transaction() as session:
            await operation_fence(session)
            await require_access(session, state['chat_id'], state['user_id'])
            await OperationalRepository(session).ensure_chat({"id": state["chat_id"], "type": "unknown"})
            repository = GameRepository(session)
            row = await repository.current(chat_id=state["chat_id"], mode="photo", lock=True)
            if row is not None and row.status == "active":
                raise PhotoSessionConflict("Фото-викторина уже идёт")
            value = deepcopy(state)
            value["revision"] = 1
            kwargs = dict(
                state=value, status="active", phase=value.get("phase") or "ready",
                deadlines=self._deadlines(value),
            )
            if row is None:
                await repository.create_current(chat_id=state["chat_id"], mode="photo", **kwargs)
            else:
                await repository.replace_current(row, **kwargs)
            result = deepcopy(value)
        return result

    async def save(self, state, *, status="active"):
        async with self.database.transaction() as session:
            await operation_fence(session)
            row = await self._locked(session, state)
            self._check_revision(row, state)
            result = self._write(row, state, status)
            game_status = "finished" if status == "completed" else status
            await GameRepository(session).sync_state(
                row, result, event_kind="legacy_photo_checkpoint" if status == "active" else f"legacy_photo_{status}",
                status=game_status, phase="finished" if game_status != "active" else (result.get("phase") or status),
                deadlines=self._deadlines(result, status),
            )
            if status != "active":
                from .cleanup import CleanupQueue
                deadline = datetime.now(timezone.utc) + timedelta(seconds=180)
                for message_id in result.get("message_ids_to_delete", []):
                    await CleanupQueue.enqueue_in(session, result["chat_id"], message_id, deadline, source="photo")
        return result

    async def active(self):
        async with self.database.transaction() as session:
            rows = (await session.scalars(select(Game).where(
                Game.mode == "photo", Game.status == "active", Game.is_current.is_(True)
            ).order_by(Game.chat_id))).all()
            return [deepcopy(row.state) for row in rows]

    async def complete_question(self, state, *, correct, points):
        """Ledger, profile and series totals commit together; retry returns saved outcome."""
        index = state["current_question_index"] - 1
        async with self.database.transaction() as session:
            await operation_fence(session)
            row = await self._locked(session, state)
            previous = row.state.get("last_outcome")
            if previous and previous["index"] == index:
                return deepcopy(row.state)
            self._check_revision(row, state)
            if row.state.get("phase") != "active" or not 0 <= index < len(row.state["questions"]):
                raise PhotoSessionConflict("Этот фото-вопрос не принимает ответы")
            value = deepcopy(row.state)
            if correct:
                async def transition(profile):
                    profile["score"] = float(Decimal(str(profile.get("score", 0))) + Decimal(str(points)))
                    profile["correct_answers_count"] = profile.get("correct_answers_count", 0) + 1
                result = await MemberService(self.database).apply_answer(
                    chat_id=value["chat_id"], user_id=value["user_id"], display_name=None,
                    answer_id=f"photo:{value['session_id']}:{index}", is_correct=True,
                    transition=transition, kind="photo", transaction_session=session,
                )
                if not result.applied:
                    raise PhotoSessionConflict("Ответ уже начислен вне состояния серии")
                value["total_correct_answers"] += 1
                value["total_score"] += points
            value.update(phase="between", is_active=False,
                         last_outcome={"index": index, "correct": correct, "points": points})
            result = self._write(row, value)
            await GameRepository(session).sync_state(
                row, result, event_kind="legacy_photo_answered",
                status="active", phase="between", deadlines={},
            )
        return result
