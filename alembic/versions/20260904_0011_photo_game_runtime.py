"""Move Photo runtime envelopes to the shared games substrate.

Revision ID: 20260904_0011
Revises: 20260904_0010
"""

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from alembic import op
import sqlalchemy as sa


revision = "20260904_0011"
down_revision = "20260904_0010"
branch_labels = None
depends_on = None


def _timestamp(value, fallback):
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.timestamp()
        except ValueError:
            pass
    if isinstance(value, datetime):
        return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).timestamp()
    return fallback.timestamp()


def _media(question, catalog):
    stem = Path(str(question.get("image_path") or "")).stem
    answer = str(question.get("display_answer") or question.get("correct_answer") or "").strip()
    selected = next((item for item in catalog if (item["metadata_json"] or {}).get("storage_name") == stem), None)
    selected = selected or next((item for item in catalog if item["media_key"] == stem), None)
    selected = selected or next((item for item in catalog if (
        str((item["metadata_json"] or {}).get("display_answer") or item["correct_answer"]).strip() == answer
    )), None)
    if selected:
        meta = selected["metadata_json"] or {}
        return {"media_key": selected["media_key"], "storage_name": meta.get("storage_name"),
                "image_sha256": meta.get("image_sha256")}
    # Preserve the address even when an operator must repair the catalog later.
    return {"media_key": stem or answer, "storage_name": stem or None, "image_sha256": None}


def _convert(row, catalog):
    legacy = deepcopy(row["state"])
    questions = legacy.get("questions")
    if not isinstance(questions, list) or not questions:
        raise RuntimeError(f'Cannot migrate malformed photo session {row["id"]}')
    now = row["updated_at"] or datetime.now(timezone.utc)
    duration = int(legacy.get("time_limit") or 60)
    duration = min(600, max(5, duration))
    active_index = int(legacy.get("current_question_index") or 0) - 1
    active_index = min(max(active_index, 0), len(questions) - 1)
    raw_status = str(row["status"] or "interrupted")
    raw_phase = str(legacy.get("phase") or "ready")
    if raw_status == "active" and raw_phase == "sending":
        raw_status = "interrupted"  # Telegram send acknowledgement was unknown.
    playable = raw_status == "active"
    if playable and raw_phase == "between":
        active_index = min(active_index + 1, len(questions) - 1)
    opened_at = _timestamp(legacy.get("start_time"), now)
    if playable and raw_phase == "between":
        opened_at = now.timestamp()
    hint_offsets = legacy.get("hint_schedule") or [max(5, int(duration * .4)), max(6, int(duration * .7))]
    hint_offsets = [min(duration - 1, max(1, int(value))) for value in hint_offsets[:2]]
    rounds = []
    for index, question in enumerate(questions):
        answer = str(question.get("display_answer") or question.get("correct_answer") or "").strip()
        normalized = str(question.get("normalized_answer") or answer).strip().casefold()
        masks = question.get("masks") if isinstance(question.get("masks"), dict) else {}
        masks = {key: str(masks.get(key) or "□" * max(1, len(answer)))
                 for key in ("initial", "first_letters", "partial")}
        status = "closed" if index < active_index or not playable else "pending"
        opened = closes = None
        hints_at = []
        hint_level = 0
        attempts = 0
        feedback = None
        if playable and index == active_index:
            status, opened, closes = "open", opened_at, opened_at + duration
            hints_at = [opened_at + offset for offset in hint_offsets] if legacy.get("hints_enabled", True) else []
            hint_level = min(2, max(0, int(legacy.get("current_hint_level") or 0)))
            attempts = max(0, int(legacy.get("attempts") or 0))
        round_id = str(uuid5(NAMESPACE_URL, f'morning-quiz:photo-round:{row["id"]}:{index}'))
        rounds.append({"round_id": round_id, "index": index, "media": _media(question, catalog),
                       "display_answer": answer, "normalized_answer": normalized, "masks": masks,
                       "status": status, "opened_at": opened, "closes_at": closes,
                       "hints_at": hints_at, "hint_level": hint_level, "attempts": attempts,
                       "feedback": feedback})
    status = ({"completed": "finished", "stopped": "stopped", "interrupted": "interrupted"}
              .get(raw_status, "active" if playable else "interrupted"))
    phase = "question_open" if playable else "finished"
    last = legacy.get("last_outcome") if isinstance(legacy.get("last_outcome"), dict) else None
    last_result = None
    if last and type(last.get("index")) is int and 0 <= last["index"] < len(rounds):
        item = rounds[last["index"]]
        last_result = {"round_id": item["round_id"], "question_number": item["index"] + 1,
                       "correct": bool(last.get("correct")), "reason": "answer" if last.get("correct") else "timeout",
                       "answer": item["display_answer"], "points": float(last.get("points") or 0)}
    state = {"mode": "photo", "status": status, "phase": phase,
             "revision": max(1, int(legacy.get("revision") or 0)), "chat_id": row["chat_id"],
             "creator_id": int(legacy.get("user_id")),
             "config": {"question_count": len(rounds), "open_seconds": duration,
                        "hints_enabled": bool(legacy.get("hints_enabled", True))},
             "rounds": rounds, "current_round_id": rounds[active_index]["round_id"] if playable else None,
             "started_at": _timestamp(row["started_at"], now),
             "finished_at": None if playable else now.timestamp(),
             "finish_reason": None if playable else status,
             "total_correct": int(legacy.get("total_correct_answers") or 0),
             "total_score": float(legacy.get("total_score") or 0), "last_result": last_result}
    return state


def upgrade():
    bind = op.get_bind()
    meta = sa.MetaData()
    sessions = sa.Table("quiz_sessions", meta, autoload_with=bind)
    games = sa.Table("games", meta, autoload_with=bind)
    events = sa.Table("game_events", meta, autoload_with=bind)
    deadlines = sa.Table("game_deadlines", meta, autoload_with=bind)
    photos = sa.Table("photo_quiz_items", meta, autoload_with=bind)
    catalog = bind.execute(sa.select(photos)).mappings().all()
    rows = bind.execute(sa.select(sessions).where(sessions.c.kind == "photo")
                        .order_by(sessions.c.chat_id, sessions.c.updated_at.desc())).mappings().all()
    current_by_chat = set()
    for row in rows:
        state = _convert(row, catalog)
        game_id = str(uuid5(NAMESPACE_URL, f'morning-quiz:photo:{row["chat_id"]}:{row["id"]}:{row["created_at"]}'))
        is_current = row["chat_id"] not in current_by_chat
        current_by_chat.add(row["chat_id"])
        bind.execute(games.insert().values(
            id=game_id, chat_id=row["chat_id"], mode="photo", status=state["status"],
            phase=state["phase"], revision=state["revision"], state=state,
            is_current=is_current, started_at=row["started_at"],
            ended_at=None if state["status"] == "active" else row["updated_at"],
            created_at=row["created_at"], updated_at=row["updated_at"],
        ))
        bind.execute(events.insert().values(
            game_id=game_id, event_index=1, kind="legacy_photo_migrated", visibility="private",
            actor_user_id=state["creator_id"], payload={"legacy_session_id": row["id"],
                                                        "revision": state["revision"]},
            created_at=row["updated_at"],
        ))
        if is_current and state["status"] == "active":
            item = next(item for item in state["rounds"] if item["round_id"] == state["current_round_id"])
            entries = {f"close:{item['round_id']}": item["closes_at"]}
            for level, due in enumerate(item["hints_at"], 1):
                if level > item["hint_level"]:
                    entries[f"hint:{item['round_id']}:{level}"] = due
            for kind, due in entries.items():
                bind.execute(deadlines.insert().values(
                    id=f"{game_id}:{kind}"[:96], game_id=game_id, kind=kind,
                    due_at=datetime.fromtimestamp(due, timezone.utc), status="pending",
                    revision=state["revision"],
                ))
        bind.execute(sessions.delete().where(sessions.c.id == row["id"]))


def downgrade():
    bind = op.get_bind()
    count = bind.scalar(sa.text("SELECT count(*) FROM games WHERE mode = 'photo'"))
    current = bind.scalar(sa.text("SELECT count(*) FROM games WHERE mode = 'photo' AND is_current"))
    if count != current:
        raise RuntimeError("Refusing downgrade: photo game history cannot fit in addressed quiz_sessions")
    bind.execute(sa.text("""
        INSERT INTO quiz_sessions
            (id, chat_id, kind, status, state, started_at, ends_at, created_at, updated_at)
        SELECT 'photo:' || chat_id::text, chat_id, 'photo', status, state,
               started_at, ended_at, created_at, updated_at
        FROM games WHERE mode = 'photo' AND is_current
        ON CONFLICT (id) DO UPDATE SET status = EXCLUDED.status, state = EXCLUDED.state,
            started_at = EXCLUDED.started_at, ends_at = EXCLUDED.ends_at,
            updated_at = EXCLUDED.updated_at
    """))
    bind.execute(sa.text("DELETE FROM games WHERE mode = 'photo'"))
