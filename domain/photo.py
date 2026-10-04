"""Pure state machine for the shared Photo puzzle game mode.

The state contains only durable game facts.  Image bytes, Telegram messages and
HTTP responses belong to adapters; PostgreSQL stores the authoritative state.
"""

from __future__ import annotations

from copy import deepcopy
from difflib import SequenceMatcher
import random
import re
import unicodedata
from typing import Any, Sequence
from uuid import uuid4


PHOTO_STATUSES = {"active", "finished", "stopped", "interrupted"}
PHOTO_PHASES = {"question_open", "finished"}


def _timestamp(now: object = None) -> float:
    from datetime import datetime, timezone

    if now is None:
        return datetime.now(timezone.utc).timestamp()
    if isinstance(now, datetime):
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        return now.timestamp()
    if type(now) in {int, float}:
        return float(now)
    raise ValueError("Некорректное время фото-загадки.")


def normalize_answer(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Ответ должен быть текстом.")
    value = unicodedata.normalize("NFKC", value).casefold().strip()
    value = re.sub(r"\s+", " ", value)
    if not value or len(value) > 300 or "\x00" in value:
        raise ValueError("Ответ должен содержать от 1 до 300 символов.")
    return value


def answer_masks(answer: str) -> dict[str, str]:
    """Stable masks: all clients reveal exactly the same letters."""

    visible = [index for index, char in enumerate(answer) if char.isalnum()]
    first = set()
    word_start = True
    for index, char in enumerate(answer):
        if char.isalnum() and word_start:
            first.add(index)
        word_start = not char.isalnum()
    partial = set(first)
    if visible:
        amount = max(1, len(visible) // 2)
        partial.update(random.Random(answer).sample(visible, min(amount, len(visible))))

    def render(revealed: set[int]) -> str:
        return "".join(
            char if not char.isalnum() or index in revealed else "□"
            for index, char in enumerate(answer)
        )

    return {"initial": render(set()), "first_letters": render(first), "partial": render(partial)}


def _round(state: dict[str, Any], round_id: str) -> dict[str, Any]:
    item = next((item for item in state["rounds"] if item["round_id"] == round_id), None)
    if item is None:
        raise LookupError("Фото-вопрос не найден.")
    return item


def normalize_photo(value: object, *, chat_id: int | None = None) -> dict[str, Any] | None:
    if not isinstance(value, dict) or value.get("mode") != "photo":
        return None
    if type(value.get("chat_id")) is not int or (chat_id is not None and value["chat_id"] != chat_id):
        return None
    if value.get("status") not in PHOTO_STATUSES or value.get("phase") not in PHOTO_PHASES:
        return None
    if type(value.get("revision")) is not int or value["revision"] < 0:
        return None
    config, rounds = value.get("config"), value.get("rounds")
    if not isinstance(config, dict) or not isinstance(rounds, list) or not 1 <= len(rounds) <= 100:
        return None
    if (
        type(config.get("question_count")) is not int
        or config["question_count"] != len(rounds)
        or type(config.get("open_seconds")) is not int
        or not 5 <= config["open_seconds"] <= 600
        or type(config.get("hints_enabled")) is not bool
    ):
        return None
    seen: set[str] = set()
    clean_rounds = []
    for index, item in enumerate(rounds):
        if not isinstance(item, dict):
            return None
        round_id = item.get("round_id")
        media = item.get("media")
        masks = item.get("masks")
        if (
            not isinstance(round_id, str) or not round_id or len(round_id) > 64 or round_id in seen
            or item.get("index") != index or item.get("status") not in {"pending", "open", "closed"}
            or not isinstance(item.get("display_answer"), str)
            or not isinstance(item.get("normalized_answer"), str)
            or not isinstance(media, dict) or not isinstance(media.get("media_key"), str)
            or not isinstance(masks, dict)
            or any(not isinstance(masks.get(key), str) for key in ("initial", "first_letters", "partial"))
            or type(item.get("attempts")) is not int or item["attempts"] < 0
            or type(item.get("hint_level")) is not int or not 0 <= item["hint_level"] <= 2
        ):
            return None
        if item["status"] == "pending":
            if any(item.get(key) is not None for key in ("opened_at", "closes_at")):
                return None
        elif type(item.get("opened_at")) not in {int, float} or type(item.get("closes_at")) not in {int, float}:
            return None
        hints_at = item.get("hints_at")
        if not isinstance(hints_at, list) or any(type(entry) not in {int, float} for entry in hints_at):
            return None
        seen.add(round_id)
        clean_rounds.append(deepcopy(item))
    current = value.get("current_round_id")
    if current is not None and current not in seen:
        return None
    result = deepcopy(value)
    result["rounds"] = clean_rounds
    return result


def _open(state: dict[str, Any], item: dict[str, Any], now: float) -> None:
    duration = state["config"]["open_seconds"]
    hints_at = []
    if state["config"]["hints_enabled"]:
        first = max(5, int(duration * 0.4))
        second = max(first + 1, int(duration * 0.7))
        hints_at = [now + min(first, duration - 2), now + min(second, duration - 1)]
    item.update(
        status="open", opened_at=now, closes_at=now + duration,
        hints_at=hints_at, hint_level=0, attempts=0, feedback=None,
    )
    state.update(status="active", phase="question_open", current_round_id=item["round_id"])


def prepare_photo(
    *, chat_id: int, creator_id: int, questions: Sequence[dict[str, Any]],
    open_seconds: int = 60, hints_enabled: bool = True, now=None,
    round_id_factory=None,
) -> dict[str, Any]:
    if type(chat_id) is not int or chat_id == 0 or type(creator_id) is not int:
        raise ValueError("Некорректный участник фото-загадки.")
    if type(open_seconds) is not int or not 5 <= open_seconds <= 600:
        raise ValueError("Время ответа должно быть от 5 до 600 секунд.")
    if type(hints_enabled) is not bool:
        raise ValueError("Некорректная настройка подсказок.")
    if not isinstance(questions, Sequence) or isinstance(questions, (str, bytes)) or not 1 <= len(questions) <= 100:
        raise ValueError("Нужен хотя бы один фото-вопрос.")
    make_id = round_id_factory or (lambda: uuid4().hex)
    rounds, seen = [], set()
    for index, source in enumerate(questions):
        if not isinstance(source, dict):
            raise ValueError("Некорректный фото-вопрос.")
        answer = str(source.get("display_answer") or "").strip()
        normalized = normalize_answer(source.get("normalized_answer") or answer)
        media = source.get("media")
        round_id = make_id()
        if (
            not answer or len(answer) > 300 or not isinstance(media, dict)
            or not isinstance(media.get("media_key"), str) or not media["media_key"]
            or not isinstance(round_id, str) or not round_id or len(round_id) > 64 or round_id in seen
        ):
            raise ValueError("Некорректный фото-вопрос.")
        seen.add(round_id)
        rounds.append({
            "round_id": round_id, "index": index, "media": deepcopy(media),
            "display_answer": answer, "normalized_answer": normalized,
            "masks": answer_masks(answer), "status": "pending",
            "opened_at": None, "closes_at": None, "hints_at": [],
            "hint_level": 0, "attempts": 0, "feedback": None,
        })
    timestamp = _timestamp(now)
    state = {
        "mode": "photo", "status": "active", "phase": "question_open",
        "revision": 0, "chat_id": chat_id, "creator_id": creator_id,
        "config": {"question_count": len(rounds), "open_seconds": open_seconds,
                   "hints_enabled": hints_enabled},
        "rounds": rounds, "current_round_id": None, "started_at": timestamp,
        "finished_at": None, "finish_reason": None,
        "total_correct": 0, "total_score": 0.0, "last_result": None,
    }
    _open(state, rounds[0], timestamp)
    state["revision"] = 1
    return state


def classify_answer(user_answer: str, correct_answer: str) -> str:
    answer = normalize_answer(user_answer)
    correct = normalize_answer(correct_answer)
    if answer == correct:
        return "correct"
    if min(len(answer), len(correct)) >= 3 and (
        answer in correct or correct in answer or SequenceMatcher(None, answer, correct).ratio() >= 0.82
    ):
        return "almost"
    return "wrong"


def record_attempt(value: object, *, round_id: str, answer: str, now=None) -> tuple[dict[str, Any], str]:
    state = normalize_photo(value)
    if state is None:
        raise ValueError("Состояние фото-загадки повреждено.")
    item = _round(state, round_id)
    timestamp = _timestamp(now)
    if state["status"] != "active" or state["current_round_id"] != round_id or item["status"] != "open":
        raise RuntimeError("Этот фото-вопрос уже завершён.")
    if timestamp > item["closes_at"]:
        raise RuntimeError("Время ответа истекло.")
    verdict = classify_answer(answer, item["normalized_answer"])
    if verdict != "correct":
        item["attempts"] += 1
        item["feedback"] = verdict
        state["revision"] += 1
    return state, verdict


def complete_round(
    value: object, *, round_id: str, correct: bool, points: float = 0.0,
    reason: str = "answer", now=None,
) -> dict[str, Any]:
    state = normalize_photo(value)
    if state is None:
        raise ValueError("Состояние фото-загадки повреждено.")
    item = _round(state, round_id)
    if state["status"] != "active" or state["current_round_id"] != round_id or item["status"] != "open":
        raise RuntimeError("Этот фото-вопрос уже завершён.")
    timestamp = _timestamp(now)
    item.update(status="closed", feedback="correct" if correct else reason)
    state["total_correct"] += int(correct)
    state["total_score"] = float(state["total_score"]) + float(points)
    state["last_result"] = {
        "round_id": round_id, "question_number": item["index"] + 1,
        "correct": bool(correct), "reason": reason,
        "answer": item["display_answer"], "points": float(points),
    }
    if item["index"] + 1 < len(state["rounds"]):
        _open(state, state["rounds"][item["index"] + 1], timestamp)
    else:
        state.update(
            status="finished", phase="finished", current_round_id=None,
            finished_at=timestamp, finish_reason="completed",
        )
    state["revision"] += 1
    return state


def reveal_hint(value: object, *, round_id: str, level: int, now=None) -> dict[str, Any]:
    state = normalize_photo(value)
    if state is None:
        raise ValueError("Состояние фото-загадки повреждено.")
    item = _round(state, round_id)
    if (
        state["status"] != "active" or state["current_round_id"] != round_id
        or item["status"] != "open" or level not in {1, 2}
    ):
        raise RuntimeError("Подсказка больше не актуальна.")
    if level <= item["hint_level"]:
        return state
    if len(item["hints_at"]) < level or _timestamp(now) < item["hints_at"][level - 1]:
        raise RuntimeError("Подсказка ещё не готова.")
    item["hint_level"] = level
    state["revision"] += 1
    return state


def stop_photo(value: object, *, expected_revision: object, reason: str = "stopped", now=None) -> dict[str, Any]:
    state = normalize_photo(value)
    if state is None:
        raise ValueError("Состояние фото-загадки повреждено.")
    if type(expected_revision) is not int or expected_revision != state["revision"]:
        raise RuntimeError("Игра уже изменилась. Обновите экран.")
    if reason not in {"stopped", "interrupted"}:
        raise ValueError("Некорректная причина завершения.")
    if state["status"] in {"finished", "stopped", "interrupted"}:
        return state
    current = _round(state, state["current_round_id"])
    current["status"] = "closed"
    state["last_result"] = {
        "round_id": current["round_id"], "question_number": current["index"] + 1,
        "correct": False, "reason": reason, "answer": current["display_answer"], "points": 0.0,
    }
    state.update(status=reason, phase="finished", current_round_id=None,
                 finished_at=_timestamp(now), finish_reason=reason)
    state["revision"] += 1
    return state


def photo_deadlines(value: object) -> dict[str, float]:
    state = normalize_photo(value)
    if state is None or state["status"] != "active" or not state["current_round_id"]:
        return {}
    item = _round(state, state["current_round_id"])
    result = {f"close:{item['round_id']}": float(item["closes_at"])}
    for level, due in enumerate(item["hints_at"], 1):
        if level > item["hint_level"]:
            result[f"hint:{item['round_id']}:{level}"] = float(due)
    return result


def project_photo(value: object, *, image_url: str | None = None, now=None) -> dict[str, Any]:
    state = normalize_photo(value)
    if state is None:
        raise ValueError("Состояние фото-загадки повреждено.")
    question = None
    if state["current_round_id"]:
        item = _round(state, state["current_round_id"])
        key = ("initial", "first_letters", "partial")[item["hint_level"]]
        question = {
            "round_id": item["round_id"], "question_number": item["index"] + 1,
            "question_count": len(state["rounds"]),
            "ends_at": item["closes_at"], "closed": item["status"] != "open" or _timestamp(now) > item["closes_at"],
            "mask": item["masks"][key] if state["config"]["hints_enabled"] else None,
            "hint_level": item["hint_level"], "feedback": item.get("feedback"),
            "image_url": image_url,
        }
    return {
        "game_id": None, "revision": state["revision"], "status": state["status"],
        "phase": state["phase"], "question": question,
        "game": {"current": question["question_number"] if question else len(state["rounds"]),
                 "total": len(state["rounds"])},
        "score": str(state["total_score"]), "correct": state["total_correct"],
        "last_result": deepcopy(state.get("last_result")),
    }
