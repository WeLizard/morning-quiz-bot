"""Pure classic-quiz contracts shared by every delivery adapter."""

from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Callable, Sequence
import random
from uuid import uuid4


@dataclass(frozen=True)
class ClassicQuestion:
    """A question prepared once for Telegram, Mini App and persistence."""

    text: str
    options: tuple[str, ...]
    correct_option_index: int
    correct_option_text: str
    explanation: str | None

    def delivery(self, *, prefix: str = "", category: str | None = None) -> dict[str, Any]:
        return {
            "question": question_with_header(self.text, prefix, category),
            "options": list(self.options),
            "correct_option_index": self.correct_option_index,
        }

    def checkpoint(self, *, prefix: str = "", category: str | None = None) -> dict[str, Any]:
        return {
            "question_text": self.text,
            "display_question": question_with_header(self.text, prefix, category),
            "options": list(self.options),
            "correct_option_index": self.correct_option_index,
            "correct_option_text": self.correct_option_text,
            "explanation": self.explanation,
        }


def prepare_question(
    source: dict[str, Any],
    *,
    shuffle: Callable[[list[tuple[int, str]]], None] | None = None,
) -> ClassicQuestion:
    """Validate and freeze option order without changing the question bank."""

    text = source["question"].strip()
    options = [option.strip() for option in source["options"]]
    correct = source["correct_option_text"].strip()
    if not 1 <= len(text) <= 300:
        raise ValueError("Question must contain 1–300 characters; truncation is unsafe")
    if not 2 <= len(options) <= 10 or any(not 1 <= len(option) <= 100 for option in options):
        raise ValueError("Classic quiz requires 2–10 options of 1–100 characters")
    if len(set(options)) != len(options) or correct not in options:
        raise ValueError("Options must be distinct and contain the correct answer")
    indexed = list(enumerate(options))
    (shuffle or random.shuffle)(indexed)
    original_correct = options.index(correct)
    correct_index = next(index for index, (original, _) in enumerate(indexed) if original == original_correct)
    raw_explanation = source.get("solution") or source.get("explanation")
    explanation = str(raw_explanation).strip() if raw_explanation else None
    return ClassicQuestion(
        text=text,
        options=tuple(option for _, option in indexed),
        correct_option_index=correct_index,
        correct_option_text=correct,
        explanation=explanation,
    )


def question_with_header(question: str, prefix: str = "", category: str | None = None) -> str:
    """Drop optional decoration before ever losing part of a question."""

    headers = [prefix.strip()] if prefix.strip() else []
    if category:
        headers.append(f"Категория: {category.strip()}")
    while headers:
        candidate = "\n".join([*headers, question])
        if len(candidate) <= 300:
            return candidate
        headers.pop()
    return question


def public_question(
    poll_id: str,
    poll: dict[str, Any],
    *,
    selected_option: int | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return a spoiler-safe projection of one persisted poll."""

    options = poll.get("options")
    text = poll.get("display_question") or poll.get("question_text")
    if not isinstance(text, str) or not isinstance(options, Sequence) or isinstance(options, (str, bytes)):
        raise ValueError("This session predates the shared question contract")
    if not options or any(not isinstance(option, str) for option in options):
        raise ValueError("Invalid persisted question")
    deadline = poll.get("end_timestamp")
    timestamp = (now or datetime.now(timezone.utc)).timestamp()
    ended = isinstance(deadline, (int, float)) and timestamp > deadline
    answered = type(selected_option) is int and 0 <= selected_option < len(options)
    revealed = answered or ended
    result = {
        "poll_id": poll_id,
        "question": text,
        "options": list(options),
        "question_number": poll.get("question_session_index", 0) + 1,
        "ends_at": datetime.fromtimestamp(deadline, timezone.utc).isoformat()
        if isinstance(deadline, (int, float))
        else None,
        "answered": answered,
        "selected_option": selected_option if answered else None,
        "closed": ended,
    }
    if revealed:
        correct = poll.get("correct_option_index")
        if type(correct) is int and 0 <= correct < len(options):
            result["correct_option"] = correct
            result["is_correct"] = selected_option == correct if answered else None
        result["explanation"] = poll.get("explanation")
    return result


CLASSIC_STATUSES = {
    "prepared", "active", "finished", "stopped", "interrupted",
}
CLASSIC_PHASES = {
    "waiting_start", "question_open", "between", "finished",
}


def _timestamp(now: datetime | int | float | None = None) -> float:
    if now is None:
        return datetime.now(timezone.utc).timestamp()
    if isinstance(now, datetime):
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        return now.timestamp()
    if type(now) in {int, float}:
        return float(now)
    raise ValueError("Invalid classic game time")


def _expect_revision(state: dict[str, Any], expected_revision: object) -> None:
    if type(expected_revision) is not int or expected_revision != state["revision"]:
        raise RuntimeError("Викторина уже изменилась. Обновите экран и повторите действие.")


def _round(state: dict[str, Any], round_id: str) -> dict[str, Any]:
    value = next((item for item in state["rounds"] if item["round_id"] == round_id), None)
    if value is None:
        raise LookupError("Вопрос не найден.")
    return value


def normalize_classic(value: object, *, chat_id: int | None = None) -> dict[str, Any] | None:
    """Validate the durable v2 envelope without repairing ambiguous state."""

    if not isinstance(value, dict) or value.get("mode") != "classic":
        return None
    if type(value.get("chat_id")) is not int or (
        chat_id is not None and value["chat_id"] != chat_id
    ):
        return None
    if value.get("status") not in CLASSIC_STATUSES or value.get("phase") not in CLASSIC_PHASES:
        return None
    revision = value.get("revision")
    config = value.get("config")
    rounds = value.get("rounds")
    if type(revision) is not int or revision < 0 or not isinstance(config, dict) or not isinstance(rounds, list):
        return None
    if not 1 <= len(rounds) <= 1000:
        return None
    count = config.get("question_count")
    open_seconds = config.get("open_seconds")
    interval_seconds = config.get("interval_seconds")
    if (
        type(count) is not int or count != len(rounds)
        or type(open_seconds) is not int or not 1 <= open_seconds <= 600
        or type(interval_seconds) is not int or not 0 <= interval_seconds <= 3600
    ):
        return None
    clean_rounds: list[dict[str, Any]] = []
    seen: set[str] = set()
    allowed_round_statuses = {"pending", "open", "closed"}
    for index, item in enumerate(rounds):
        if not isinstance(item, dict):
            return None
        round_id = item.get("round_id")
        options = item.get("options")
        correct = item.get("correct_option_index")
        if (
            not isinstance(round_id, str) or not round_id or len(round_id) > 64 or round_id in seen
            or item.get("index") != index or item.get("status") not in allowed_round_statuses
            or not isinstance(item.get("question_text"), str)
            or not isinstance(item.get("display_question"), str)
            or not isinstance(options, list) or not 2 <= len(options) <= 10
            or any(not isinstance(option, str) for option in options)
            or type(correct) is not int or not 0 <= correct < len(options)
        ):
            return None
        seen.add(round_id)
        opened_at = item.get("opened_at")
        closes_at = item.get("closes_at")
        advance_at = item.get("advance_at")
        if item["status"] == "pending":
            if opened_at is not None or closes_at is not None:
                return None
        elif type(opened_at) not in {int, float} or type(closes_at) not in {int, float}:
            return None
        if advance_at is not None and type(advance_at) not in {int, float}:
            return None
        clean_rounds.append(deepcopy(item))
    current = value.get("current_round_id")
    if current is not None and current not in seen:
        return None
    result = deepcopy(value)
    result["rounds"] = clean_rounds
    if result.get('start_at') is not None and type(result['start_at']) not in {int, float}:
        return None
    return result


def prepare_classic(
    *,
    chat_id: int,
    creator_id: int | None,
    questions: Sequence[dict[str, Any]],
    quiz_type: str = "session",
    open_seconds: int = 30,
    interval_seconds: int = 0,
    round_id_factory: Callable[[], str] | None = None,
    shuffle: Callable[[list[tuple[int, str]]], None] | None = None,
) -> dict[str, Any]:
    """Validate and freeze every round before any client delivery occurs."""

    if type(chat_id) is not int or chat_id == 0:
        raise ValueError("Некорректный чат.")
    if creator_id is not None and type(creator_id) is not int:
        raise ValueError("Некорректный создатель викторины.")
    if not isinstance(quiz_type, str) or not 1 <= len(quiz_type) <= 32:
        raise ValueError("Некорректный тип викторины.")
    if type(open_seconds) is not int or not 1 <= open_seconds <= 600:
        raise ValueError("Время ответа должно быть от 1 до 600 секунд.")
    if type(interval_seconds) is not int or not 0 <= interval_seconds <= 3600:
        raise ValueError("Интервал должен быть от 0 до 3600 секунд.")
    if not isinstance(questions, Sequence) or isinstance(questions, (str, bytes)) or not 1 <= len(questions) <= 1000:
        raise ValueError("Нужен хотя бы один вопрос.")
    make_id = round_id_factory or (lambda: uuid4().hex)
    rounds = []
    ids = set()
    for index, source in enumerate(questions):
        if not isinstance(source, dict):
            raise ValueError("Некорректный вопрос.")
        prepared = prepare_question(source, shuffle=shuffle)
        round_id = make_id()
        if not isinstance(round_id, str) or not round_id or len(round_id) > 64 or round_id in ids:
            raise ValueError("Некорректный или повторяющийся идентификатор вопроса.")
        ids.add(round_id)
        category = source.get("current_category_name_for_quiz", source.get("original_category"))
        prefix = "Вопрос" if quiz_type == "single" else f"Вопрос {index + 1}/{len(questions)}"
        if quiz_type == "daily":
            prefix = f"Ежедневный вопрос {index + 1}/{len(questions)}"
        rounds.append({
            "round_id": round_id,
            "index": index,
            "category": str(category)[:100] if category else None,
            **prepared.checkpoint(prefix=prefix, category=str(category) if category else None),
            "status": "pending",
            "opened_at": None,
            "closes_at": None,
            "advance_at": None,
            "advance_triggered": False,
        })
    return {
        "mode": "classic",
        "status": "prepared",
        "phase": "waiting_start",
        "revision": 0,
        "chat_id": chat_id,
        "creator_id": creator_id,
        "quiz_type": quiz_type,
        "config": {
            "question_count": len(rounds),
            "open_seconds": open_seconds,
            "interval_seconds": interval_seconds,
        },
        "rounds": rounds,
        "current_round_id": None,
        "started_at": None,
        "start_at": None,
        "finished_at": None,
        "finish_reason": None,
    }


def _open_round(state: dict[str, Any], item: dict[str, Any], now: float) -> None:
    item.update(status="open", opened_at=now,
                closes_at=now + state["config"]["open_seconds"])
    state.update(status="active", phase="question_open", current_round_id=item["round_id"])


def start_classic(value: object, *, expected_revision: object, now=None) -> dict[str, Any]:
    state = normalize_classic(value)
    if state is None:
        raise ValueError("Состояние викторины повреждено.")
    _expect_revision(state, expected_revision)
    if state["status"] != "prepared" or state["phase"] != "waiting_start":
        raise ValueError("Викторина уже запущена.")
    timestamp = _timestamp(now)
    if state.get('start_at') is not None and timestamp < state['start_at']:
        raise RuntimeError('Время старта ещё не наступило.')
    _open_round(state, state["rounds"][0], timestamp)
    state["started_at"] = timestamp
    state["revision"] += 1
    return state


def schedule_classic(
    value: object, *, expected_revision: object, start_at: object,
) -> dict[str, Any]:
    state = normalize_classic(value)
    if state is None:
        raise ValueError('Состояние викторины повреждено.')
    _expect_revision(state, expected_revision)
    if state['status'] != 'prepared' or state['phase'] != 'waiting_start':
        raise ValueError('Викторина уже запущена.')
    timestamp = _timestamp(start_at)
    state['start_at'] = timestamp
    state['revision'] += 1
    return state


def validate_classic_answer(
    value: object, *, round_id: str, selected_option: object, now=None,
) -> dict[str, Any]:
    """Return the answered round; scoring/persistence remains an application concern."""

    state = normalize_classic(value)
    if state is None:
        raise ValueError("Состояние викторины повреждено.")
    if state["status"] != "active":
        raise ValueError("Викторина не активна.")
    item = _round(state, round_id)
    if item["status"] != "open" or _timestamp(now) > item["closes_at"]:
        raise RuntimeError("Время ответа истекло.")
    if type(selected_option) is not int or not 0 <= selected_option < len(item["options"]):
        raise ValueError("Некорректный вариант ответа.")
    return item


def on_answer_applied(value: object, *, round_id: str, now=None) -> dict[str, Any]:
    """Schedule one advance for the newest round after the first accepted answer."""

    state = normalize_classic(value)
    if state is None:
        raise ValueError("Состояние викторины повреждено.")
    item = _round(state, round_id)
    if state["status"] != "active" or item["status"] != "open":
        raise ValueError("Вопрос уже завершён.")
    if state["current_round_id"] != round_id or item["advance_triggered"]:
        return state
    if item["index"] + 1 < len(state["rounds"]):
        item["advance_triggered"] = True
        item["advance_at"] = _timestamp(now) + state["config"]["interval_seconds"]
        state["revision"] += 1
    return state


def close_round(value: object, *, round_id: str, now=None) -> dict[str, Any]:
    state = normalize_classic(value)
    if state is None:
        raise ValueError("Состояние викторины повреждено.")
    item = _round(state, round_id)
    if item["status"] != "open":
        return state
    if _timestamp(now) < item["closes_at"]:
        raise RuntimeError("Вопрос ещё открыт.")
    item["status"] = "closed"
    item["advance_at"] = None
    state["revision"] += 1
    if state["current_round_id"] == round_id:
        if item["index"] + 1 == len(state["rounds"]):
            state.update(status="finished", phase="finished", finished_at=_timestamp(now),
                         finish_reason="completed")
        else:
            state["phase"] = "between"
    return state


def advance_classic(
    value: object,
    *,
    round_id: str,
    cause: str,
    expected_revision: object,
    now=None,
) -> dict[str, Any]:
    """Open the next round once; old open rounds may overlap until their own deadline."""

    state = normalize_classic(value)
    if state is None:
        raise ValueError("Состояние викторины повреждено.")
    _expect_revision(state, expected_revision)
    if state["status"] != "active" or state["current_round_id"] != round_id:
        raise ValueError("Этот вопрос уже не является текущим.")
    item = _round(state, round_id)
    timestamp = _timestamp(now)
    if item["index"] + 1 >= len(state["rounds"]):
        raise ValueError("Следующего вопроса нет.")
    if cause == "answer":
        if not item["advance_triggered"] or item["advance_at"] is None or timestamp < item["advance_at"]:
            raise RuntimeError("Переход ещё не готов.")
    elif cause == "deadline":
        if timestamp < item["closes_at"]:
            raise RuntimeError("Вопрос ещё открыт.")
        item["status"] = "closed"
    else:
        raise ValueError("Некорректная причина перехода.")
    item["advance_at"] = None
    _open_round(state, state["rounds"][item["index"] + 1], timestamp)
    state["revision"] += 1
    return state


def finish_classic(
    value: object, *, reason: str, expected_revision: object, now=None,
) -> dict[str, Any]:
    state = normalize_classic(value)
    if state is None:
        raise ValueError("Состояние викторины повреждено.")
    _expect_revision(state, expected_revision)
    if state["status"] in {"finished", "stopped", "interrupted"}:
        return state
    if reason not in {"completed", "stopped", "interrupted"}:
        raise ValueError("Некорректная причина завершения.")
    state.update(
        status="finished" if reason == "completed" else reason,
        phase="finished",
        finished_at=_timestamp(now),
        finish_reason=reason,
    )
    state["revision"] += 1
    return state


def classic_deadlines(value: object) -> dict[str, float]:
    """Return every pending server deadline; overlapping Telegram polls are preserved."""

    state = normalize_classic(value)
    if state is None:
        return {}
    if state['status'] == 'prepared' and type(state.get('start_at')) in {int, float}:
        return {'start': float(state['start_at'])}
    if state["status"] != "active":
        return {}
    result = {}
    for item in state["rounds"]:
        if item["status"] == "open":
            result[f'close:{item["round_id"]}'] = float(item["closes_at"])
        if item["advance_at"] is not None:
            result[f'advance:{item["round_id"]}'] = float(item["advance_at"])
    return result


def project_classic(
    value: object,
    *,
    selected_options: dict[str, int] | None = None,
    now=None,
) -> dict[str, Any]:
    """Spoiler-safe game projection shared by Telegram-facing and HTTP clients."""

    state = normalize_classic(value)
    if state is None:
        raise ValueError("Состояние викторины повреждено.")
    selected_options = selected_options or {}
    current = _round(state, state["current_round_id"]) if state["current_round_id"] else None
    question = None
    if current is not None:
        question = public_question(
            current["round_id"],
            {
                **current,
                "question_session_index": current["index"],
                "end_timestamp": current["closes_at"],
            },
            selected_option=selected_options.get(current["round_id"]),
            now=datetime.fromtimestamp(_timestamp(now), timezone.utc),
        )
        question["round_id"] = question.pop("poll_id")
    return {
        "game_id": None,
        "revision": state["revision"],
        "status": state["status"],
        "phase": state["phase"],
        "question": question,
        "game": {
            "current": current["index"] + 1 if current else 0,
            "total": len(state["rounds"]),
        },
    }
