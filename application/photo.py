"""Shared Photo puzzle lifecycle used by Telegram and Mini App adapters."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import random
from typing import Any, Sequence

from sqlalchemy import select

from domain.photo import (
    complete_round, normalize_photo, photo_deadlines, prepare_photo,
    project_photo, record_attempt, reveal_hint, stop_photo,
)
from storage.admin_actions import operation_fence, require_access
from storage.games import GameRepository
from storage.members import MemberService
from storage.models import Game, GameDeadline, PhotoQuizItem, PollAnswer
from storage.notifications import NotificationQueue
from storage.photo_media import images_root, verified_image_path
from storage.photos import metadata
from storage.repositories import OperationalRepository


class PhotoGameConflict(RuntimeError):
    pass


def _moment(now=None) -> float:
    if isinstance(now, datetime):
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        return now.timestamp()
    if type(now) in {int, float}:
        return float(now)
    return datetime.now(timezone.utc).timestamp()


class PhotoApplicationService:
    """Authoritative Photo commands inside an adapter-owned transaction."""

    def __init__(self, database, session):
        self.database = database
        self.session = session
        self.games = GameRepository(session)

    async def _current(self, chat_id: int, *, lock: bool = False) -> Game | None:
        return await self.games.current(chat_id=chat_id, mode="photo", lock=lock)

    async def _select_questions(self, count: int) -> list[dict[str, Any]]:
        rows = (await self.session.scalars(
            select(PhotoQuizItem).where(PhotoQuizItem.enabled.is_(True)).order_by(PhotoQuizItem.media_key)
        )).all()
        available = []
        root = images_root()
        for row in rows:
            value = metadata(row)
            if value.get("archived"):
                continue
            path = verified_image_path(root, row.media_key, value)
            answer = str(value.get("display_answer") or value.get("correct_answer") or "").strip()
            if path is None or not answer:
                continue
            available.append({
                "display_answer": answer,
                "media": {
                    "media_key": row.media_key,
                    "storage_name": value.get("storage_name"),
                    "image_sha256": value.get("image_sha256"),
                },
            })
        if not available:
            raise LookupError("В каталоге нет доступных фото-загадок.")
        random.SystemRandom().shuffle(available)
        if count <= len(available):
            return available[:count]
        return [available[index % len(available)] for index in range(count)]

    async def _enqueue(self, game: Game, kind: str, suffix: str, payload: dict) -> None:
        await NotificationQueue.enqueue_in(
            self.session, kind=kind, dedupe_key=f"photo:{game.id}:{suffix}",
            payload=payload, game_id=game.id, chat_id=game.chat_id,
            user_id=(game.state or {}).get("creator_id"),
        )

    async def _enqueue_question(self, game: Game, state: dict[str, Any]) -> None:
        round_id = state.get("current_round_id")
        if isinstance(round_id, str):
            await self._enqueue(game, "photo.question", f"question:{round_id}",
                                {"round_id": round_id, "revision": state["revision"]})

    async def _enqueue_feedback(self, game: Game, state: dict[str, Any], verdict: str) -> None:
        item = next(item for item in state["rounds"] if item["round_id"] == state["current_round_id"])
        await self._enqueue(
            game, "photo.feedback", f"feedback:{item['round_id']}:{state['revision']}",
            {"round_id": item["round_id"], "revision": state["revision"], "verdict": verdict},
        )

    async def _enqueue_result(self, game: Game, state: dict[str, Any]) -> None:
        result = dict(state["last_result"])
        await self._enqueue(game, "photo.result", f"result:{result['round_id']}",
                            {**result, "revision": state["revision"]})

    async def _enqueue_finished(self, game: Game, state: dict[str, Any]) -> None:
        await self._enqueue(
            game, "photo.finished", "finished",
            {"revision": state["revision"], "reason": state.get("finish_reason"),
             "question_count": len(state["rounds"]), "correct": state["total_correct"],
             "score": state["total_score"]},
        )

    async def current(self, *, chat_id: int, user_id: int, now=None) -> dict[str, Any] | None:
        game = await self._current(chat_id)
        state = normalize_photo(game.state, chat_id=chat_id) if game else None
        if game is None or state is None or state.get("creator_id") != user_id:
            return None
        result = project_photo(
            state, image_url=(f"/api/mini/photo/chats/{chat_id}/current/image"
                              if state["current_round_id"] else None), now=now,
        )
        result["game_id"] = game.id
        return result

    async def start(
        self, *, chat_id: int, user_id: int, display_name: str | None,
        question_count: int = 3, open_seconds: int = 60,
        hints_enabled: bool = True, command_id: str | None = None,
        questions: Sequence[dict[str, Any]] | None = None, now=None,
    ) -> dict[str, Any]:
        await operation_fence(self.session)
        await require_access(self.session, chat_id, user_id)
        if type(question_count) is not int or not 1 <= question_count <= 10:
            raise ValueError("Количество фото-вопросов должно быть от 1 до 10.")
        operational = OperationalRepository(self.session)
        await operational.ensure_chat({"id": chat_id, "type": "unknown"})
        await operational.ensure_user({"id": user_id, "display_name": display_name or f"User {user_id}"})
        await operational.ensure_member({"chat_id": chat_id, "user_id": user_id})
        current = await self._current(chat_id, lock=True)
        payload = {"question_count": question_count, "open_seconds": open_seconds,
                   "hints_enabled": hints_enabled}
        if current is not None and current.status == "active":
            cached, result = await self.games.reserve_command(
                command_id=command_id, game_id=current.id, actor_user_id=user_id,
                kind="photo.start", expected_revision=None, payload=payload,
            )
            if cached:
                return result
            raise PhotoGameConflict("В этом чате уже идёт фото-викторина.")
        prepared = list(questions) if questions is not None else await self._select_questions(question_count)
        if len(prepared) != question_count:
            raise ValueError("Число подготовленных фото-вопросов не совпадает с настройкой.")
        state = prepare_photo(chat_id=chat_id, creator_id=user_id, questions=prepared,
                              open_seconds=open_seconds, hints_enabled=hints_enabled, now=now)
        kwargs = dict(state=state, status=state["status"], phase=state["phase"],
                      deadlines=photo_deadlines(state))
        game = (await self.games.create_current(chat_id=chat_id, mode="photo", **kwargs)
                if current is None else await self.games.replace_current(current, **kwargs))
        await self._enqueue_question(game, state)
        cached, result = await self.games.reserve_command(
            command_id=command_id, game_id=game.id, actor_user_id=user_id,
            kind="photo.start", expected_revision=None, payload=payload,
        )
        if cached:
            return result
        result = project_photo(state, image_url=f"/api/mini/photo/chats/{chat_id}/current/image", now=now)
        result["game_id"] = game.id
        await self.games.complete_command(command_id, result)
        return result

    async def answer(
        self, *, chat_id: int, user_id: int, display_name: str | None,
        round_id: str, answer: str, command_id: str | None = None, now=None,
    ) -> dict[str, Any]:
        await operation_fence(self.session)
        await require_access(self.session, chat_id, user_id)
        game = await self._current(chat_id, lock=True)
        state = normalize_photo(game.state, chat_id=chat_id) if game else None
        if game is None or game.status != "active" or state is None:
            raise LookupError("Активная фото-викторина не найдена.")
        if state["creator_id"] != user_id:
            raise PermissionError("Эта фото-серия принадлежит другому игроку.")
        payload = {"round_id": round_id, "answer": answer}
        cached, result = await self.games.reserve_command(
            command_id=command_id, game_id=game.id, actor_user_id=user_id,
            kind="photo.answer", expected_revision=None, payload=payload,
        )
        if cached:
            return result
        state, verdict = record_attempt(state, round_id=round_id, answer=answer, now=now)
        if verdict != "correct":
            await self.games.sync_state(
                game, state, event_kind="photo_attempted", actor_user_id=user_id,
                status=state["status"], phase=state["phase"], deadlines=photo_deadlines(state),
            )
            await self._enqueue_feedback(game, state, verdict)
            result = project_photo(state, image_url=f"/api/mini/photo/chats/{chat_id}/current/image", now=now)
            result.update(game_id=game.id, applied=True, verdict=verdict)
            await self.games.complete_command(command_id, result)
            return result

        item = next(item for item in state["rounds"] if item["round_id"] == round_id)
        elapsed = _moment(now) - item["opened_at"]
        fast = bool(item["hints_at"] and elapsed < item["hints_at"][0] - item["opened_at"])
        points = max(1.0, 5.0 + int(fast) - item["attempts"] * 0.5)

        async def transition(profile):
            profile["score"] = float(Decimal(str(profile.get("score", 0))) + Decimal(str(points)))
            profile["correct_answers_count"] = profile.get("correct_answers_count", 0) + 1

        score = await MemberService(self.database).apply_answer(
            chat_id=chat_id, user_id=user_id, display_name=display_name,
            answer_id=round_id, is_correct=True, transition=transition,
            transaction_session=self.session, kind="photo",
            game_id=game.id, game_round_id=round_id,
        )
        saved = await self.session.get(PollAnswer, (round_id, user_id))
        if not score.applied:
            if saved is None or saved.game_id != game.id or saved.round_id != round_id:
                raise PhotoGameConflict("Ответ уже был обработан вне текущей игры.")
            points = float(saved.points_delta)
        previous_round = state["current_round_id"]
        state = complete_round(state, round_id=round_id, correct=True, points=points,
                               reason="answer", now=now)
        await self.games.sync_state(
            game, state, event_kind="photo_answered", actor_user_id=user_id,
            status=state["status"], phase=state["phase"], deadlines=photo_deadlines(state),
        )
        await self._enqueue_result(game, state)
        if state["status"] == "finished":
            await self._enqueue_finished(game, state)
        elif state["current_round_id"] != previous_round:
            await self._enqueue_question(game, state)
        result = project_photo(
            state, image_url=(f"/api/mini/photo/chats/{chat_id}/current/image"
                              if state["current_round_id"] else None), now=now,
        )
        result.update(game_id=game.id, applied=score.applied, verdict="correct")
        await self.games.complete_command(command_id, result)
        return result

    async def stop(
        self, *, chat_id: int, user_id: int, expected_revision: int,
        command_id: str | None = None, allow_admin: bool = False, now=None,
    ) -> dict[str, Any]:
        await operation_fence(self.session)
        await require_access(self.session, chat_id, user_id)
        game = await self._current(chat_id, lock=True)
        state = normalize_photo(game.state, chat_id=chat_id) if game else None
        if game is None or state is None or game.status != "active":
            raise LookupError("Активная фото-викторина не найдена.")
        if state["creator_id"] != user_id and not allow_admin:
            raise PermissionError("Остановить фото-серию может её создатель или администратор.")
        payload = {"reason": "stopped"}
        cached, result = await self.games.reserve_command(
            command_id=command_id, game_id=game.id, actor_user_id=user_id,
            kind="photo.stop", expected_revision=expected_revision, payload=payload,
        )
        if cached:
            return result
        state = stop_photo(state, expected_revision=expected_revision, now=now)
        await self.games.sync_state(
            game, state, event_kind="photo_stopped", actor_user_id=user_id,
            status=state["status"], phase=state["phase"], deadlines={},
        )
        await self._enqueue_finished(game, state)
        result = project_photo(state, now=now)
        result["game_id"] = game.id
        await self.games.complete_command(command_id, result)
        return result

    async def settle_due(self, *, chat_id: int, user_id: int | None = None, now=None) -> dict[str, Any] | None:
        await operation_fence(self.session)
        await require_access(self.session, chat_id, user_id)
        game = await self._current(chat_id, lock=True)
        state = normalize_photo(game.state, chat_id=chat_id) if game else None
        if game is None or game.status != "active" or state is None:
            return None
        if user_id is not None and state.get("creator_id") != user_id:
            return None
        timestamp = _moment(now)
        for _ in range(4):
            due = sorted((due_at, kind) for kind, due_at in photo_deadlines(state).items()
                         if due_at <= timestamp)
            if not due:
                break
            _, kind = due[0]
            if kind.startswith("hint:"):
                _, round_id, raw_level = kind.split(":", 2)
                state = reveal_hint(state, round_id=round_id, level=int(raw_level), now=timestamp)
                await self.games.sync_state(
                    game, state, event_kind="photo_hint_revealed",
                    status=state["status"], phase=state["phase"], deadlines=photo_deadlines(state),
                )
                item = next(item for item in state["rounds"] if item["round_id"] == round_id)
                key = ("initial", "first_letters", "partial")[item["hint_level"]]
                await self._enqueue(
                    game, "photo.hint", f"hint:{round_id}:{raw_level}",
                    {"round_id": round_id, "level": int(raw_level), "mask": item["masks"][key]},
                )
                continue
            _, round_id = kind.split(":", 1)
            state = complete_round(state, round_id=round_id, correct=False, points=0,
                                   reason="timeout", now=timestamp)
            await self.games.sync_state(
                game, state, event_kind="photo_timed_out",
                status=state["status"], phase=state["phase"], deadlines=photo_deadlines(state),
            )
            await self._enqueue_result(game, state)
            if state["status"] == "finished":
                await self._enqueue_finished(game, state)
            else:
                await self._enqueue_question(game, state)
        else:
            raise RuntimeError("Превышен предел переходов фото-викторины.")
        result = project_photo(
            state, image_url=(f"/api/mini/photo/chats/{chat_id}/current/image"
                              if state["current_round_id"] else None), now=timestamp,
        )
        result["game_id"] = game.id
        return result

    async def image(self, *, chat_id: int, user_id: int):
        game = await self._current(chat_id)
        state = normalize_photo(game.state, chat_id=chat_id) if game else None
        if game is None or state is None or state.get("creator_id") != user_id or not state["current_round_id"]:
            raise LookupError("Активный фото-вопрос не найден.")
        item = next(item for item in state["rounds"] if item["round_id"] == state["current_round_id"])
        path = verified_image_path(images_root(), item["media"]["media_key"], item["media"])
        if path is None:
            raise LookupError("Изображение недоступно.")
        return path

    async def question_delivery(self, *, game_id: str, round_id: str) -> dict[str, Any] | None:
        game = await self.session.get(Game, game_id)
        state = normalize_photo(game.state, chat_id=game.chat_id) if game else None
        if game is None or not game.is_current or state is None:
            return None
        item = next((item for item in state["rounds"] if item["round_id"] == round_id), None)
        if item is None or item["status"] != "open" or state["current_round_id"] != round_id:
            return None
        path = verified_image_path(images_root(), item["media"]["media_key"], item["media"])
        if path is None:
            return None
        key = ("initial", "first_letters", "partial")[item["hint_level"]]
        return {"game_id": game.id, "round_id": round_id, "chat_id": game.chat_id,
                "image_path": path, "question_number": item["index"] + 1,
                "question_count": len(state["rounds"]), "closes_at": item["closes_at"],
                "mask": item["masks"][key] if state["config"]["hints_enabled"] else None,
                "hints_enabled": state["config"]["hints_enabled"]}

    async def due(self, *, now=None) -> list[int]:
        moment = now or datetime.now(timezone.utc)
        if type(moment) in {int, float}:
            moment = datetime.fromtimestamp(moment, timezone.utc)
        return list((await self.session.scalars(
            select(Game.chat_id).join(GameDeadline, GameDeadline.game_id == Game.id).where(
                Game.mode == "photo", Game.is_current.is_(True), Game.status == "active",
                GameDeadline.status == "pending", GameDeadline.due_at <= moment,
            ).distinct().order_by(Game.chat_id)
        )).all())
