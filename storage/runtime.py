"""Compatibility adapter between PostgreSQL and the existing in-memory BotState."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, Optional, TYPE_CHECKING

from sqlalchemy import delete, select

from .database import Database
from .json_importer import as_decimal, parse_datetime, string_list
from .models import Chat, ChatMember, MessageCleanupItem, QuizSession, SystemState, User
from .repositories import OperationalRepository

if TYPE_CHECKING:
    from state import BotState


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


def _date_iso(value: Optional[datetime]) -> Optional[str]:
    return value.date().isoformat() if value else None


def member_data(member: ChatMember, user: User) -> Dict[str, Any]:
    """Build a detached compatibility view; it must never be bulk-saved back."""
    data = dict(member.extra or {})
    data.update({
        "name": user.display_name,
        "score": float(member.score),
        "answered_polls": set(member.answered_poll_ids or []),
        "correct_answers_count": member.correct_answers_count,
        "daily_answered_polls": set(member.daily_answered_poll_ids or []),
        "first_answer_time": _iso(member.first_answer_at),
        "last_answer_time": _iso(member.last_answer_at),
        "last_daily_reset": _date_iso(member.last_daily_reset),
        "milestones_achieved": set(member.milestone_codes or []),
        "consecutive_correct": member.consecutive_correct,
        "max_consecutive_correct": member.max_consecutive_correct,
        "streak_achievements_earned": set(member.streak_achievement_codes or []),
    })
    return data


def member_values(chat_id: int, user_id: int, data: Dict[str, Any]) -> Dict[str, Any]:
    known = {
        "name",
        "score",
        "answered_polls",
        "correct_answers_count",
        "daily_answered_polls",
        "first_answer_time",
        "last_answer_time",
        "last_daily_reset",
        "milestones_achieved",
        "consecutive_correct",
        "max_consecutive_correct",
        "streak_achievements_earned",
    }
    answered = string_list(data.get("answered_polls"))
    return {
        "chat_id": chat_id,
        "user_id": user_id,
        "score": as_decimal(data.get("score")),
        "answered_count": len(answered),
        "correct_answers_count": int(data.get("correct_answers_count") or 0),
        "consecutive_correct": int(data.get("consecutive_correct") or 0),
        "max_consecutive_correct": int(data.get("max_consecutive_correct") or 0),
        "first_answer_at": parse_datetime(data.get("first_answer_time")),
        "last_answer_at": parse_datetime(data.get("last_answer_time")),
        "last_daily_reset": parse_datetime(data.get("last_daily_reset")),
        "answered_poll_ids": answered,
        "daily_answered_poll_ids": string_list(data.get("daily_answered_polls")),
        "milestone_codes": string_list(data.get("milestones_achieved")),
        "streak_achievement_codes": string_list(data.get("streak_achievements_earned")),
        "extra": {key: value for key, value in data.items() if key not in known},
    }


def schedule_values(chat_id: int, kind: str, config: Dict[str, Any]) -> Dict[str, Any]:
    if kind == "quiz":
        run_times = []
        for value in config.get("times_msk", []):
            if isinstance(value, dict):
                run_times.append(
                    f"{int(value.get('hour', 0)):02d}:{int(value.get('minute', 0)):02d}"
                )
            elif value:
                run_times.append(str(value))
    else:
        run_times = [str(config.get("time") or "12:00")]
    return {
        "chat_id": chat_id,
        "kind": kind,
        "enabled": bool(config.get("enabled")),
        "timezone": str(config.get("timezone") or "Europe/Moscow"),
        "run_times": run_times,
        "config": config,
    }


class PostgresRuntimeStorage:
    def __init__(self, database: Database):
        self.database = database

    async def load_into_state(self, state: "BotState") -> Dict[int, Dict[str, Any]]:
        async with self.database.transaction() as session:
            chats = list((await session.scalars(select(Chat).order_by(Chat.id))).all())
            member_rows = list(
                (
                    await session.execute(
                        select(ChatMember, User)
                        .join(User, User.id == ChatMember.user_id)
                        .order_by(ChatMember.chat_id, ChatMember.user_id)
                    )
                ).all()
            )
            cleanup_items = list((await session.scalars(select(MessageCleanupItem))).all())
            quiz_sessions = list(
                (
                    await session.scalars(
                        select(QuizSession).where(QuizSession.status == "active", QuizSession.kind != "photo")
                    )
                ).all()
            )
            system_states = {
                item.key: item.payload
                for item in (await session.scalars(select(SystemState))).all()
            }

        state.chat_settings = {chat.id: dict(chat.settings or {}) for chat in chats}
        state.chat_settings_revisions = {chat.id: chat.settings_revision for chat in chats}
        loaded_scores: Dict[int, Dict[str, Any]] = {chat.id: {} for chat in chats}
        for member, user in member_rows:
            loaded_scores.setdefault(member.chat_id, {})[str(member.user_id)] = member_data(member, user)
        state.user_scores = loaded_scores
        state.global_settings["category_usage_stats"] = dict(
            system_states.get("category_usage_stats") or {}
        )
        state.global_settings["global_statistics"] = dict(
            system_states.get("global_statistics") or {}
        )

        state.generic_messages_to_delete = defaultdict(dict)
        for item in cleanup_items:
            if (item.payload or {}).get("state") == "done":
                continue
            legacy_timestamp = (item.payload or {}).get("legacy_timestamp")
            if not isinstance(legacy_timestamp, (int, float)):
                legacy_timestamp = item.delete_after.timestamp() - 120 if item.delete_after else datetime.now(timezone.utc).timestamp()
            state.generic_messages_to_delete[item.chat_id][item.message_id] = legacy_timestamp

        active: Dict[int, Dict[str, Any]] = {}
        priorities: Dict[int, int] = {}
        now = datetime.now(timezone.utc)
        for quiz in quiz_sessions:
            payload = dict(quiz.state or {})
            started = parse_datetime(payload.get("quiz_start_time")) or quiz.started_at
            if payload.get("storage_version") != 1 and started and (now - started.astimezone(timezone.utc)).total_seconds() > 7200:
                continue
            priority = 3 if quiz.id.startswith("classic:") else 2 if quiz.id.startswith("runtime:") else 1
            if priority >= priorities.get(quiz.chat_id, 0):
                active[quiz.chat_id] = payload
                priorities[quiz.chat_id] = priority
        return active

    async def sync_member_state(
        self,
        chat_id: int,
        user_id: int,
        display_name: str,
        data: Dict[str, Any],
        *,
        recompute_global: bool = False,
    ) -> None:
        """Seed a new membership only. Existing state requires a domain transaction."""
        async with self.database.transaction() as session:
            from .admin_actions import operation_fence, require_access
            await operation_fence(session)
            await require_access(session, chat_id, user_id)
            repository = OperationalRepository(session)
            await repository.ensure_chat({"id": chat_id, "type": "unknown"})
            await repository.ensure_user({"id": user_id, "display_name": display_name})
            await session.scalar(select(User).where(User.id == user_id).with_for_update())
            if await session.get(ChatMember, (chat_id, user_id)) is not None:
                raise RuntimeError("Refusing to overwrite an existing member from cached state")
            await repository.upsert_user(
                {
                    "id": user_id,
                    "display_name": display_name,
                    "first_answer_at": parse_datetime(data.get("first_answer_time")),
                    "last_answer_at": parse_datetime(data.get("last_answer_time")),
                }
            )
            await repository.upsert_member(member_values(chat_id, user_id, data))
            await repository.add_achievement_codes(
                user_id, string_list(data.get("milestones_achieved"))
            )
            await repository.add_achievement_codes(
                user_id, string_list(data.get("streak_achievements_earned"))
            )
            if recompute_global:
                await repository.recompute_user_totals(user_id)

    async def save_chat_users(self, chat_id: int, users: Dict[str, Dict[str, Any]]) -> None:
        raise RuntimeError("PostgreSQL profiles must be changed through MemberService, not snapshots")

    async def save_chat_settings(self, chat_id: int, settings: Dict[str, Any]) -> None:
        """Compatibility seed only. All subsequent changes use SettingsService."""
        async with self.database.transaction() as session:
            repository = OperationalRepository(session)
            await repository.ensure_chat({"id": chat_id, "type": "unknown"})
            chat = await session.scalar(select(Chat).where(Chat.id == chat_id).with_for_update())
            if chat.settings_revision or chat.settings:
                raise RuntimeError("Refusing to overwrite existing settings from a snapshot")
            await repository.upsert_chat(
                {
                    "id": chat_id,
                    "type": str(settings.get("chat_type") or "unknown"),
                    "title": settings.get("title"),
                    "settings": settings,
                    "settings_revision": 1,
                }
            )
            daily_quiz = settings.get("daily_quiz")
            if isinstance(daily_quiz, dict):
                await repository.upsert_schedule(schedule_values(chat_id, "quiz", daily_quiz))
            daily_wisdom = settings.get("daily_wisdom")
            if isinstance(daily_wisdom, dict):
                await repository.upsert_schedule(
                    schedule_values(chat_id, "wisdom", daily_wisdom)
                )

    async def save_category_statistics(self, statistics: Dict[str, Dict[str, Any]]) -> None:
        raise RuntimeError("Category snapshots are disabled; counters belong to session completion")

    async def replace_cleanup_queue(self, queue: Dict[int, Dict[int, float]]) -> None:
        raise RuntimeError("Cleanup snapshots are disabled; use CleanupQueue commands")

    async def replace_active_quizzes(self, quizzes: Dict[int, Dict[str, Any]]) -> None:
        raise RuntimeError("Session snapshots are disabled; use ClassicSessions commands")

    async def delete_active_quizzes(self) -> None:
        await self.replace_active_quizzes({})
