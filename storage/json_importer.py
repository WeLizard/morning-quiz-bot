"""One-shot transactional import into an empty PostgreSQL operational store."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import func, select, text

from .database import Database, DatabaseSettings, normalize_database_url
from .models import (
    AchievementGrant,
    Chat,
    ChatMember,
    DailySchedule,
    MessageCleanupItem,
    PhotoQuizItem,
    QuestionCategory,
    QuizSession,
    SystemState,
    User,
)
from .repositories import OperationalRepository


def parse_datetime(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, time.min)
    else:
        text = str(value).strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def as_decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value or 0)).quantize(Decimal("0.001"))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0.000")


def import_score(value: Any) -> Decimal:
    """Do not silently turn corrupt source scores into zero during migration."""
    if value is None or value == '':
        return Decimal('0.000')
    try:
        number = Decimal(str(value))
        if not number.is_finite() or abs(number) > Decimal('99999999999.999'):
            raise ValueError('Score outside the supported range')
        return number.quantize(Decimal('0.001'))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError('Invalid source score; import transaction was not committed') from exc


def string_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple, set)):
        return []
    return list(dict.fromkeys(str(item) for item in value if item is not None))


def read_json(path: Path, default: Any, errors: list[str]) -> Any:
    if not path.exists():
        return default
    try:
        content = path.read_text(encoding="utf-8-sig").strip()
        if not content:
            return default
        return json.loads(content)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        errors.append(f"{path}: {exc}")
        return default


OPERATIONAL_ROOT_FILES = {
    'active_quizzes.json',
    'bot_mode.json',
    'bot_status.json',
    'maintenance_status.json',
    'photo_quiz_metadata.json',
}
OPERATIONAL_GLOBAL_FILES = {
    'global/categories.json', 'global/chats_index.json', 'global/users.json'
}
OPERATIONAL_STATISTICS_FILES = {
    'statistics/categories_stats.json',
    'statistics/global_stats.json',
}
OPERATIONAL_SYSTEM_FILES = {
    'system/blacklist.json',
    'system/daily_quiz_subscriptions.json',
    'system/malformed_questions.json',
    'system/messages_to_delete.json',
}


def _source_classification(logical_path: str) -> str:
    """Describe why a JSON file is or is not part of this import transaction."""
    if logical_path in OPERATIONAL_ROOT_FILES:
        return 'operational'
    if logical_path in OPERATIONAL_GLOBAL_FILES:
        return 'operational'
    if logical_path in OPERATIONAL_STATISTICS_FILES:
        return 'operational'
    if logical_path in OPERATIONAL_SYSTEM_FILES:
        return 'operational'
    if logical_path.startswith('chats/') and logical_path.rsplit('/', 1)[-1] in {
        'categories_stats.json', 'settings.json', 'stats.json', 'users.json'
    }:
        return 'operational'
    if logical_path == 'config/maintenance_status.json':
        return 'operational'
    if logical_path.startswith('questions/'):
        return 'operational'
    if logical_path in {
        'config/admins.json',
        'config/quiz_config.json',
        'media/fake_wisdom.json',
        'system/streak_achievements.json',
    }:
        return 'static_configuration'
    if logical_path.startswith('statistics/') and '_backup_' in logical_path:
        return 'historical_backup'
    return 'unclassified'


def source_manifest(data_dir: Path, config_dir: Optional[Path] = None) -> list[dict[str, Any]]:
    data_dir = data_dir.resolve()
    config_dir = (config_dir or data_dir.parent / 'config').resolve()
    files = list(data_dir.rglob('*.json')) if data_dir.exists() else []
    manifest = []
    resolved = {item.resolve() for item in files if item.is_file()}
    for name in ('admins.json', 'maintenance_status.json', 'quiz_config.json'):
        candidate = config_dir / name
        if candidate.is_file():
            resolved.add(candidate.resolve())
    for path in sorted(resolved, key=str):
        logical = ('config/' + path.name if path.parent == config_dir
                   else str(path.relative_to(data_dir)).replace('\\', '/'))
        content = path.read_bytes()
        manifest.append({'path': logical, 'classification': _source_classification(logical),
                         'bytes': len(content),
                         'sha256': hashlib.sha256(content).hexdigest()})
    return manifest


def source_digest(data_dir: Path, config_dir: Optional[Path] = None) -> str:
    data_dir = data_dir.resolve()
    config_dir = (config_dir or data_dir.parent / 'config').resolve()
    digest = hashlib.sha256()
    for item in source_manifest(data_dir, config_dir):
        if item['classification'] != 'operational':
            continue
        path = config_dir / Path(item['path']).name if item['path'].startswith('config/') else data_dir / item['path']
        digest.update(item['path'].encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _require_object(value: Any, path: str, errors: list[str]) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    errors.append(f'{path}: expected an object')
    return {}


def _validate_member_fields(value: dict[str, Any], path: str, errors: list[str]) -> None:
    for key in ('milestones_achieved', 'streak_achievements_earned', 'answered_polls', 'daily_answered_polls'):
        if key in value and not isinstance(value[key], list):
            errors.append(f'{path}.{key}: expected an array')
    for key in ('first_answer_time', 'last_answer_time', 'last_daily_reset'):
        if value.get(key) and parse_datetime(value[key]) is None:
            errors.append(f'{path}.{key}: invalid datetime')
    for key in ('score', 'global_score'):
        if key in value:
            try:
                import_score(value[key])
            except ValueError:
                errors.append(f'{path}.{key}: invalid score')


@dataclass
class ChatSnapshot:
    chat_id: int
    metadata: dict[str, Any] = field(default_factory=dict)
    settings: dict[str, Any] = field(default_factory=dict)
    statistics: dict[str, Any] = field(default_factory=dict)
    category_statistics: dict[str, Any] = field(default_factory=dict)
    members: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass
class JsonSnapshot:
    data_dir: Path
    digest: str
    global_users: dict[str, dict[str, Any]]
    chats: list[ChatSnapshot]
    system_states: dict[str, Any]
    active_quizzes: dict[str, Any]
    photo_items: dict[str, dict[str, Any]]
    question_categories: dict[str, list[Any]]
    category_metadata: dict[str, dict[str, Any]]
    manifest: list[dict[str, Any]]
    errors: list[str]

    def manifest_summary(self) -> dict[str, int]:
        summary: dict[str, int] = {}
        for item in self.manifest:
            classification = str(item['classification'])
            summary[classification] = summary.get(classification, 0) + 1
        return dict(sorted(summary.items()))

    @classmethod
    def scan(cls, data_dir: Path) -> "JsonSnapshot":
        data_dir = data_dir.resolve()
        errors: list[str] = []
        global_users = read_json(data_dir / "global" / "users.json", {}, errors)
        chats_index = read_json(data_dir / "global" / "chats_index.json", {}, errors)
        if not isinstance(global_users, dict):
            errors.append("global/users.json: expected an object")
            global_users = {}
        for user_id, value in global_users.items():
            if not isinstance(value, dict):
                errors.append(f'global/users.json.{user_id}: expected an object')
            else:
                _validate_member_fields(value, f'global/users.json.{user_id}', errors)
        if not isinstance(chats_index, dict):
            errors.append("global/chats_index.json: expected an object")
            chats_index = {}

        chat_ids: set[int] = set()
        for raw_id in chats_index:
            try:
                chat_ids.add(int(raw_id))
            except (TypeError, ValueError):
                errors.append(f"global/chats_index.json: invalid chat id {raw_id!r}")
        chats_dir = data_dir / "chats"
        if chats_dir.exists():
            for child in chats_dir.iterdir():
                if child.is_dir():
                    try:
                        chat_ids.add(int(child.name))
                    except ValueError:
                        errors.append(f"chats/{child.name}: directory is not a Telegram chat id")

        chats: list[ChatSnapshot] = []
        for chat_id in sorted(chat_ids):
            chat_dir = chats_dir / str(chat_id)
            settings = read_json(chat_dir / "settings.json", {}, errors)
            statistics = read_json(chat_dir / "stats.json", {}, errors)
            category_statistics = read_json(chat_dir / "categories_stats.json", {}, errors)
            members = read_json(chat_dir / "users.json", {}, errors)
            metadata = chats_index.get(str(chat_id), {})
            if not isinstance(metadata, dict):
                errors.append(f'global/chats_index.json.{chat_id}: expected an object')
                metadata = {}
            settings = _require_object(settings, f'chats/{chat_id}/settings.json', errors)
            statistics = _require_object(statistics, f'chats/{chat_id}/stats.json', errors)
            category_statistics = _require_object(
                category_statistics, f'chats/{chat_id}/categories_stats.json', errors)
            members = _require_object(members, f'chats/{chat_id}/users.json', errors)
            for user_id, value in members.items():
                if not isinstance(value, dict):
                    errors.append(f'chats/{chat_id}/users.json.{user_id}: expected an object')
                else:
                    _validate_member_fields(value, f'chats/{chat_id}/users.json.{user_id}', errors)
            chats.append(
                ChatSnapshot(
                    chat_id=chat_id,
                    metadata=metadata,
                    settings=settings,
                    statistics=statistics,
                    category_statistics=category_statistics,
                    members=members,
                )
            )

        system_states: dict[str, Any] = {}
        system_dir = data_dir / "system"
        if system_dir.exists():
            for name in sorted(Path(item).name for item in OPERATIONAL_SYSTEM_FILES):
                path = system_dir / name
                if not path.exists():
                    continue
                system_states[path.stem] = read_json(path, {}, errors)
        statistics_dir = data_dir / "statistics"
        statistics_files = {
            "global_statistics": statistics_dir / "global_stats.json",
            "category_usage_stats": statistics_dir / "categories_stats.json",
        }
        for key, path in statistics_files.items():
            if path.exists():
                system_states[key] = read_json(path, {}, errors)
        for name in ("bot_mode", "bot_status", "maintenance_status"):
            path = data_dir / f"{name}.json"
            if path.exists():
                system_states[name] = read_json(path, {}, errors)
        config_maintenance = data_dir.parent / 'config' / 'maintenance_status.json'
        if config_maintenance.exists():
            if 'maintenance_status' in system_states:
                errors.append('maintenance_status.json exists in both data and config; source is ambiguous')
            system_states['maintenance_status'] = read_json(config_maintenance, {}, errors)

        active_file = read_json(data_dir / "active_quizzes.json", {}, errors)
        if not isinstance(active_file, dict):
            errors.append('active_quizzes.json: expected an object')
            active_file = {}
        active_quizzes = active_file.get("active_quizzes", {})
        if not isinstance(active_quizzes, dict):
            errors.append("active_quizzes.json: active_quizzes must be an object")
            active_quizzes = {}

        photo_items = read_json(data_dir / "photo_quiz_metadata.json", {}, errors)
        if not isinstance(photo_items, dict):
            errors.append("photo_quiz_metadata.json: expected an object")
            photo_items = {}
        for media_key, value in photo_items.items():
            if not isinstance(value, dict):
                errors.append(f'photo_quiz_metadata.json.{media_key}: expected an object')
            elif not value.get('correct_answer'):
                errors.append(f'photo_quiz_metadata.json.{media_key}.correct_answer: required')
            elif 'hints' in value and not isinstance(value['hints'], dict):
                errors.append(f'photo_quiz_metadata.json.{media_key}.hints: expected an object')

        category_metadata = read_json(data_dir / 'global' / 'categories.json', {}, errors)
        category_metadata = _require_object(
            category_metadata, 'global/categories.json', errors
        )
        for name, value in category_metadata.items():
            if not isinstance(value, dict):
                errors.append(f'global/categories.json.{name}: expected an object')
        question_categories: dict[str, list[Any]] = {}
        questions_dir = data_dir / 'questions'
        if questions_dir.exists():
            for path in sorted(questions_dir.glob('*.json')):
                values = read_json(path, [], errors)
                if not isinstance(values, list):
                    errors.append(f'questions/{path.name}: expected an array')
                    continue
                question_categories[path.stem] = values

        return cls(
            data_dir=data_dir,
            digest=source_digest(data_dir),
            global_users=global_users,
            chats=chats,
            system_states=system_states,
            active_quizzes=active_quizzes,
            photo_items=photo_items,
            question_categories=question_categories,
            category_metadata=category_metadata,
            manifest=source_manifest(data_dir),
            errors=errors,
        )

    def source_counts(self) -> dict[str, int]:
        chat_ids = {chat.chat_id for chat in self.chats}
        chat_ids.update(
            int(chat_id) for chat_id in self.active_quizzes
            if str(chat_id).lstrip('-').isdigit()
        )
        member_keys = {
            (chat.chat_id, int(user_id))
            for chat in self.chats
            for user_id in chat.members
            if str(user_id).lstrip("-").isdigit()
        }
        user_ids = {int(user_id) for user_id in self.global_users if str(user_id).isdigit()}
        user_ids.update(user_id for _, user_id in member_keys)
        blacklist = self.system_states.get('blacklist', {})
        if isinstance(blacklist, dict):
            blocked_chats = blacklist.get('chats', {})
            blocked_users = blacklist.get('users', {})
            if isinstance(blocked_chats, dict):
                chat_ids.update(
                    int(chat_id) for chat_id in blocked_chats
                    if str(chat_id).lstrip('-').isdigit() and int(chat_id) != 0
                )
            if isinstance(blocked_users, dict):
                user_ids.update(
                    int(user_id) for user_id in blocked_users
                    if str(user_id).isdigit() and int(user_id) != 0
                )
        achievement_keys = {
            (int(user_id), str(code))
            for user_id, data in self.global_users.items()
            if str(user_id).isdigit() and isinstance(data, dict)
            for code in string_list(data.get("milestones_achieved"))
        }
        achievement_keys.update(
            (int(user_id), str(code))
            for chat in self.chats
            for user_id, data in chat.members.items()
            if str(user_id).isdigit() and isinstance(data, dict)
            for code in (
                string_list(data.get("milestones_achieved"))
                + string_list(data.get("streak_achievements_earned"))
            )
        )
        schedules = sum(
            int(isinstance(chat.settings.get("daily_quiz"), dict))
            + int(isinstance(chat.settings.get("daily_wisdom"), dict))
            for chat in self.chats
        )
        cleanup_payload = self.system_states.get("messages_to_delete", {})
        cleanup_items = 0
        if isinstance(cleanup_payload, dict):
            for messages in cleanup_payload.values():
                if isinstance(messages, dict):
                    cleanup_items += len(messages)
                elif isinstance(messages, list):
                    cleanup_items += len(messages)
        return {
            "chats": len(chat_ids),
            "users": len(user_ids),
            "chat_members": len(member_keys),
            "achievement_grants": len(achievement_keys),
            "daily_schedules": schedules,
            "active_quizzes": len(self.active_quizzes),
            "photo_quiz_items": len(self.photo_items),
            "question_categories": len(self.question_categories),
            "system_states": len(self.system_states),
            "message_cleanup_items": cleanup_items,
        }


class JsonToPostgresImporter:
    def __init__(self, database: Database, snapshot: JsonSnapshot):
        self.database = database
        self.snapshot = snapshot

    async def run(self) -> dict[str, Any]:
        if self.snapshot.errors:
            raise ValueError('Snapshot contains errors; import refused before any writes')
        started_at = datetime.now(timezone.utc)
        run_id = str(uuid.uuid4())
        report: dict[str, Any] = {
            "run_id": run_id,
            "source_digest": self.snapshot.digest,
            "started_at": started_at.isoformat(),
            "source": self.snapshot.source_counts(),
            "manifest": self.snapshot.manifest,
            "manifest_summary": self.snapshot.manifest_summary(),
            "processed": {},
            "errors": list(self.snapshot.errors),
        }
        processed = report["processed"]
        from .migration_verification import MigrationVerification
        verification = MigrationVerification()

        async with self.database.transaction() as session:
            # Serialize importers. Re-running an old snapshot must never erase
            # scores/settings written by the running bot or administrator.
            await session.execute(text('SELECT pg_advisory_xact_lock(724016823001)'))
            from .admin_actions import operation_fence
            await operation_fence(session, exclusive=True)
            from .models import Base
            bind = session.get_bind()
            schemas = bind.get_execution_options().get('schema_translate_map', {})
            quote = bind.dialect.identifier_preparer.quote
            names = []
            for table in Base.metadata.sorted_tables:
                schema = schemas.get(table.schema, table.schema)
                names.append((quote(schema) + '.' if schema else '') + quote(table.name))
            # Exclude concurrent operational writers until the import commits.
            await session.execute(text('LOCK TABLE ' + ', '.join(names) + ' IN EXCLUSIVE MODE'))
            for table in Base.metadata.sorted_tables:
                if await session.scalar(select(func.count()).select_from(table)):
                    raise RuntimeError('Import requires an empty operational database; existing data was not changed')
            repository = OperationalRepository(session)
            known_users: set[int] = set()

            for raw_user_id, data in self.snapshot.global_users.items():
                if not str(raw_user_id).isdigit() or not isinstance(data, dict):
                    report["errors"].append(f"global user skipped: {raw_user_id!r}")
                    continue
                user_id = int(raw_user_id)
                known_users.add(user_id)
                metadata = {
                    key: value
                    for key, value in data.items()
                    if key
                    not in {
                        "name",
                        "global_score",
                        "total_answered",
                        "first_answer_time",
                        "last_answer_time",
                        "milestones_achieved",
                    }
                }
                user_values = {
                        "id": user_id,
                        "display_name": str(data.get("name") or "Unknown"),
                        "global_score": import_score(data.get("global_score")),
                        "total_answered": int(data.get("total_answered") or 0),
                        "first_answer_at": parse_datetime(data.get("first_answer_time")),
                        "last_answer_at": parse_datetime(data.get("last_answer_time")),
                        "metadata_json": metadata,
                    }
                await repository.upsert_user(user_values)
                verification.record('users', user_values)
                achievement_codes = string_list(data.get("milestones_achieved"))
                await repository.add_achievement_codes(user_id, achievement_codes)
                for code in achievement_codes:
                    verification.record('achievement_grants', {
                        'user_id': user_id, 'chat_id': 0, 'code': code,
                        'metadata_json': {},
                    })
            processed["global_users"] = len(known_users)

            member_count = 0
            schedule_count = 0
            for chat in self.snapshot.chats:
                metadata = chat.metadata if isinstance(chat.metadata, dict) else {}
                chat_values = {
                        "id": chat.chat_id,
                        "type": str(
                            chat.settings.get("chat_type") or metadata.get("type") or "unknown"
                        ),
                        "title": chat.settings.get("title") or metadata.get("title"),
                        "username": metadata.get("username"),
                        "settings": chat.settings,
                        "statistics": chat.statistics,
                        "category_statistics": chat.category_statistics,
                        "is_active": True,
                    }
                await repository.upsert_chat(chat_values)
                verification.record('chats', chat_values)

                for raw_user_id, data in chat.members.items():
                    if not str(raw_user_id).isdigit() or not isinstance(data, dict):
                        report["errors"].append(
                            f"chat {chat.chat_id}: member skipped: {raw_user_id!r}"
                        )
                        continue
                    user_id = int(raw_user_id)
                    if user_id not in known_users:
                        user_values = {
                            "id": user_id,
                            "display_name": str(data.get("name") or "Unknown"),
                        }
                        await repository.upsert_user(user_values)
                        verification.record('users', user_values)
                        known_users.add(user_id)
                    answered_poll_ids = string_list(data.get("answered_polls"))
                    known_fields = {
                        "name",
                        "score",
                        "answered_polls",
                        "first_answer_time",
                        "last_answer_time",
                        "milestones_achieved",
                        "consecutive_correct",
                        "max_consecutive_correct",
                        "streak_achievements_earned",
                        "daily_answered_polls",
                        "last_daily_reset",
                        "correct_answers_count",
                    }
                    member_values = {
                            "chat_id": chat.chat_id,
                            "user_id": user_id,
                            "score": import_score(data.get("score")),
                            "answered_count": len(answered_poll_ids),
                            "correct_answers_count": int(data.get("correct_answers_count") or 0),
                            "consecutive_correct": int(data.get("consecutive_correct") or 0),
                            "max_consecutive_correct": int(
                                data.get("max_consecutive_correct") or 0
                            ),
                            "first_answer_at": parse_datetime(data.get("first_answer_time")),
                            "last_answer_at": parse_datetime(data.get("last_answer_time")),
                            "last_daily_reset": parse_datetime(data.get("last_daily_reset")),
                            "answered_poll_ids": answered_poll_ids,
                            "daily_answered_poll_ids": string_list(
                                data.get("daily_answered_polls")
                            ),
                            "milestone_codes": string_list(data.get("milestones_achieved")),
                            "streak_achievement_codes": string_list(
                                data.get("streak_achievements_earned")
                            ),
                            "extra": {
                                key: value for key, value in data.items() if key not in known_fields
                            },
                        }
                    await repository.upsert_member(member_values)
                    verification.record('chat_members', member_values)
                    member_achievement_codes = (
                        string_list(data.get("milestones_achieved"))
                        + string_list(data.get("streak_achievements_earned"))
                    )
                    await repository.add_achievement_codes(user_id, member_achievement_codes)
                    for code in member_achievement_codes:
                        verification.record('achievement_grants', {
                            'user_id': user_id, 'chat_id': 0, 'code': code,
                            'metadata_json': {},
                        }, ensure=True)
                    member_count += 1

                daily_quiz = chat.settings.get("daily_quiz")
                if isinstance(daily_quiz, dict):
                    run_times = []
                    for value in daily_quiz.get("times_msk", []):
                        if isinstance(value, dict):
                            run_times.append(
                                f"{int(value.get('hour', 0)):02d}:{int(value.get('minute', 0)):02d}"
                            )
                        elif value:
                            run_times.append(str(value))
                    schedule_values = {
                            "chat_id": chat.chat_id,
                            "kind": "quiz",
                            "enabled": bool(daily_quiz.get("enabled")),
                            "timezone": str(daily_quiz.get("timezone") or "Europe/Moscow"),
                            "run_times": run_times,
                            "config": daily_quiz,
                        }
                    await repository.upsert_schedule(schedule_values)
                    verification.record('daily_schedules', schedule_values)
                    schedule_count += 1

                daily_wisdom = chat.settings.get("daily_wisdom")
                if isinstance(daily_wisdom, dict):
                    schedule_values = {
                            "chat_id": chat.chat_id,
                            "kind": "wisdom",
                            "enabled": bool(daily_wisdom.get("enabled")),
                            "timezone": str(daily_wisdom.get("timezone") or "Europe/Moscow"),
                            "run_times": [str(daily_wisdom.get("time") or "12:00")],
                            "config": daily_wisdom,
                        }
                    await repository.upsert_schedule(schedule_values)
                    verification.record('daily_schedules', schedule_values)
                    schedule_count += 1

            processed["chats"] = len(self.snapshot.chats)
            processed["users"] = len(known_users)
            processed["chat_members"] = member_count
            processed["daily_schedules"] = schedule_count

            active_count = 0
            for raw_chat_id, state in self.snapshot.active_quizzes.items():
                try:
                    chat_id = int(raw_chat_id)
                except (TypeError, ValueError):
                    report["errors"].append(f"active quiz skipped: invalid chat {raw_chat_id!r}")
                    continue
                if not any(chat.chat_id == chat_id for chat in self.snapshot.chats):
                    chat_values = {"id": chat_id, "type": "unknown"}
                    await repository.upsert_chat(chat_values)
                    verification.record('chats', chat_values, ensure=True)
                state_dict = state if isinstance(state, dict) else {"legacy_state": state}
                quiz_values = {
                        "id": f"legacy:{chat_id}",
                        "chat_id": chat_id,
                        "kind": str(state_dict.get("quiz_type") or "classic"),
                        "status": "active",
                        "state": state_dict,
                        "started_at": parse_datetime(
                            state_dict.get("start_time") or state_dict.get("started_at")
                        ),
                        "ends_at": parse_datetime(state_dict.get("ends_at")),
                    }
                await repository.upsert_quiz_session(quiz_values)
                verification.record('active_quizzes', quiz_values)
                active_count += 1
            processed["active_quizzes"] = active_count

            photo_count = 0
            for media_key, data in self.snapshot.photo_items.items():
                if not isinstance(data, dict) or not data.get("correct_answer"):
                    report["errors"].append(f"photo item skipped: {media_key!r}")
                    continue
                hints = data.get("hints") if isinstance(data.get("hints"), dict) else {}
                photo_values = {
                        "media_key": str(media_key),
                        "correct_answer": str(data["correct_answer"]),
                        "hints": hints,
                        "enabled": bool(data.get("enabled", True)),
                        "metadata_json": {
                            key: value
                            for key, value in data.items()
                            if key not in {"correct_answer", "hints", "enabled"}
                        },
                    }
                await repository.upsert_photo_item(photo_values)
                verification.record('photo_quiz_items', photo_values)
                photo_count += 1
            processed["photo_quiz_items"] = photo_count

            from .question_bank import question_content_hash, validate_category_name
            for name, questions in self.snapshot.question_categories.items():
                validate_category_name(name)
                metadata = self.snapshot.category_metadata.get(name, {})
                question_values = dict(
                    name=name,
                    revision=0,
                    content_hash=question_content_hash(questions),
                    questions=questions,
                    metadata_json=metadata if isinstance(metadata, dict) else {},
                    archived=False,
                )
                session.add(QuestionCategory(**question_values))
                verification.record('question_categories', question_values)
            # Session создаётся с autoflush=False: без flush вставки не видны
            # ни счётной сверке, ни сравнении fingerprints ниже.
            await session.flush()
            processed['question_categories'] = len(self.snapshot.question_categories)

            for key, payload in self.snapshot.system_states.items():
                await repository.upsert_system_state(key, payload)
                verification.record('system_states', {'key': key, 'payload': payload})
            from .legacy_moderation import legacy_block_records, legacy_block_statements
            legacy_payload = self.snapshot.system_states.get('blacklist', {})
            legacy_blocks = legacy_block_records(legacy_payload)
            for scope, _, values in legacy_blocks:
                verification.record_legacy_block(scope, values)
            for statement in legacy_block_statements(legacy_payload):
                await session.execute(statement)
            processed['legacy_blocks'] = len(legacy_blocks)
            processed["system_states"] = len(self.snapshot.system_states)

            cleanup_count = 0
            cleanup_payload = self.snapshot.system_states.get("messages_to_delete", {})
            if isinstance(cleanup_payload, dict):
                for raw_chat_id, messages in cleanup_payload.items():
                    try:
                        chat_id = int(raw_chat_id)
                    except (TypeError, ValueError):
                        report["errors"].append(
                            f"cleanup queue skipped: invalid chat {raw_chat_id!r}"
                        )
                        continue
                    if isinstance(messages, list):
                        normalized_messages = {str(message_id): None for message_id in messages}
                    elif isinstance(messages, dict):
                        normalized_messages = messages
                    else:
                        report["errors"].append(
                            f"cleanup queue skipped for chat {chat_id}: invalid payload"
                        )
                        continue
                    for raw_message_id, legacy_timestamp in normalized_messages.items():
                        try:
                            message_id = int(raw_message_id)
                        except (TypeError, ValueError):
                            report["errors"].append(
                                f"cleanup queue skipped: invalid message {raw_message_id!r}"
                            )
                            continue
                        cleanup_values = {
                                "chat_id": chat_id,
                                "message_id": message_id,
                                "payload": {"legacy_timestamp": legacy_timestamp},
                            }
                        await repository.upsert_cleanup_item(cleanup_values)
                        verification.record('message_cleanup_items', cleanup_values)
                        cleanup_count += 1
            processed["message_cleanup_items"] = cleanup_count

            finished_at = datetime.now(timezone.utc)
            if report['errors']:
                raise ValueError('Import validation failed; transaction rolled back: ' + '; '.join(report['errors']))
            models = self._count_models()
            report['database'] = {
                name: int(await session.scalar(select(func.count()).select_from(model)) or 0)
                for name, model in models.items()
            }
            mismatches = {
                name: {'source': expected, 'database': report['database'].get(name)}
                for name, expected in report['source'].items()
                if report['database'].get(name) != expected
            }
            if mismatches:
                raise ValueError('Import count verification failed; transaction rolled back: '
                                 + json.dumps(mismatches, sort_keys=True))
            fingerprints = await verification.compare(session)
            report['normalized_fingerprints'] = fingerprints
            fingerprint_mismatches = {
                name: value for name, value in fingerprints.items() if not value['matched']
            }
            if fingerprint_mismatches:
                raise ValueError(
                    'Import content verification failed; transaction rolled back: '
                    + json.dumps(fingerprint_mismatches, sort_keys=True)
                )
            report["finished_at"] = finished_at.isoformat()
            report["status"] = "completed"
            await repository.save_import_run(
                {
                    "id": run_id,
                    "source_digest": self.snapshot.digest,
                    "started_at": started_at,
                    "finished_at": finished_at,
                    "status": report["status"],
                    "report": report,
                }
            )

        return report

    @staticmethod
    def _count_models():
        return {
            "chats": Chat,
            "users": User,
            "chat_members": ChatMember,
            "achievement_grants": AchievementGrant,
            "daily_schedules": DailySchedule,
            "active_quizzes": QuizSession,
            "photo_quiz_items": PhotoQuizItem,
            "question_categories": QuestionCategory,
            "system_states": SystemState,
            "message_cleanup_items": MessageCleanupItem,
        }

    async def database_counts(self) -> dict[str, int]:
        models = self._count_models()
        async with self.database.transaction() as session:
            return {
                name: int(await session.scalar(select(func.count()).select_from(model)) or 0)
                for name, model in models.items()
            }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--database-url", help="Overrides DATABASE_URL")
    parser.add_argument("--dry-run", action="store_true", help="Scan JSON without connecting")
    parser.add_argument("--report", type=Path, help="Write the JSON report to this file")
    return parser


async def async_main(args: argparse.Namespace) -> dict[str, Any]:
    snapshot = JsonSnapshot.scan(args.data_dir)
    if args.dry_run:
        return {
            "status": "dry_run",
            "source_digest": snapshot.digest,
            "source": snapshot.source_counts(),
            "manifest": snapshot.manifest,
            "manifest_summary": snapshot.manifest_summary(),
            "errors": snapshot.errors,
        }

    if args.database_url:
        os.environ["DATABASE_URL"] = normalize_database_url(args.database_url)
    database = Database(DatabaseSettings.from_env())
    try:
        await database.check_connection()
        return await JsonToPostgresImporter(database, snapshot).run()
    finally:
        await database.dispose()


def main() -> int:
    args = build_parser().parse_args()
    try:
        report = asyncio.run(async_main(args))
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    output = json.dumps(report, ensure_ascii=False, indent=2)
    print(output)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(output + "\n", encoding="utf-8")
    return 0 if not report.get("errors") else 2


if __name__ == "__main__":
    sys.exit(main())
