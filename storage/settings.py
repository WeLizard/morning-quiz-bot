"""Versioned settings commands; settings and schedules commit together."""
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, select

from .database import Database
from .models import Chat, DailySchedule
from .repositories import OperationalRepository
from .runtime import schedule_values
from .schedule_plan import validate_schedule_settings
from .admin_actions import operation_fence, require_access


class SettingsConflict(RuntimeError):
    pass


@dataclass
class SettingsSnapshot:
    values: dict[str, Any]
    revision: int


class SettingsService:
    def __init__(self, database: Database):
        self.database = database

    async def rename_chat(self, chat_id, title, *, expected_revision):
        title = title.strip()
        if not 1 <= len(title) <= 255 or '\x00' in title:
            raise ValueError('Название должно содержать от 1 до 255 символов.')
        async with self.database.transaction() as session:
            chat = await session.scalar(select(Chat).where(Chat.id == chat_id).with_for_update())
            if chat is None:
                raise LookupError('Чат не найден.')
            if chat.settings_revision != expected_revision:
                raise SettingsConflict('Настройки чата уже изменились. Загрузите актуальную версию.')
            # Rename is local metadata, not a Telegram API call or schedule rewrite.
            if chat.title != title or (chat.settings or {}).get('title') != title:
                chat.title = title
                chat.settings = {**(chat.settings or {}), 'title': title}
                chat.settings_revision += 1
            return SettingsSnapshot(deepcopy(chat.settings), chat.settings_revision)

    async def get(self, chat_id: int) -> SettingsSnapshot:
        async with self.database.transaction() as session:
            chat = await session.get(Chat, chat_id)
            return SettingsSnapshot(deepcopy(chat.settings or {}), chat.settings_revision) if chat else SettingsSnapshot({}, 0)

    async def patch_paths(self, chat_id: int, changes, *, defaults=None, expected_revision=None,
                          actor_user_id=None):
        changes = [(tuple(path), deepcopy(value)) for path, value in changes]
        if not changes or any(not path or any(not isinstance(k, str) or not k for k in path) for path, _ in changes):
            raise ValueError("A nonempty settings path is required")

        # All admin and chat editors feed the same canonical quiz.* settings.
        # Keep legacy aliases for quick-start commands and imported clients.
        aliases = {'default_num_questions': 'num_questions', 'default_open_period_seconds': 'open_period_seconds',
                   'default_interval_seconds': 'interval_seconds', 'default_announce_quiz': 'announce',
                   'default_announce_delay_seconds': 'announce_delay_seconds',
                   'quiz_categories_mode': 'categories_mode', 'quiz_categories_pool': 'specific_categories',
                   'num_categories_per_quiz': 'num_random_categories'}
        expanded = dict(changes)
        for path, value in changes:
            for legacy, field in aliases.items():
                counterpart = ('quiz', field) if path == (legacy,) else ((legacy,) if path == ('quiz', field) else None)
                if counterpart:
                    if counterpart in expanded and expanded[counterpart] != value:
                        raise ValueError('Противоречащие друг другу настройки викторины')
                    expanded[counterpart] = deepcopy(value)
        changes = list(expanded.items())

        def modify(values):
            for path, value in changes:
                node = values
                for key in path[:-1]:
                    if key not in node:
                        node[key] = {}
                    if not isinstance(node[key], dict):
                        raise ValueError(f"Setting {key} is not an object")
                    node = node[key]
                node[path[-1]] = value
            return values

        return await self._change(chat_id, modify, defaults or {}, expected_revision,
                                  validate_schedule=any(p[0] in {"daily_quiz", "daily_wisdom"} for p, _ in changes),
                                  actor_user_id=actor_user_id)

    async def reset(self, chat_id: int, defaults: dict, *, expected_revision: int):
        def modify(values):
            fresh = deepcopy(defaults)
            for key in ("title", "chat_type"):
                if key in values:
                    fresh[key] = values[key]
            return fresh
        return await self._change(chat_id, modify, defaults, expected_revision, validate_schedule=True)

    async def _change(self, chat_id, modify, defaults, expected_revision, validate_schedule=False,
                      actor_user_id=None):
        async with self.database.transaction() as session:
            await operation_fence(session)
            if actor_user_id is not None:
                await require_access(session, chat_id, actor_user_id)
            repo = OperationalRepository(session)
            await repo.ensure_chat({"id": chat_id, "type": "unknown", "settings": deepcopy(defaults)})
            chat = await session.scalar(select(Chat).where(Chat.id == chat_id).with_for_update())
            if expected_revision is not None and chat.settings_revision != expected_revision:
                raise SettingsConflict("Настройки уже изменились. Откройте меню заново и повторите действие.")
            values = modify(deepcopy(chat.settings or {}))
            if validate_schedule:
                validate_schedule_settings(values)
            if values == chat.settings and chat.settings_revision > 0:
                return SettingsSnapshot(values, chat.settings_revision)
            revision = chat.settings_revision + 1
            columns = {"id": chat_id, "settings": values, "settings_revision": revision}
            if "title" in values:
                columns["title"] = values["title"]
            if values.get("chat_type"):
                columns["type"] = values["chat_type"]
            await repo.upsert_chat(columns)
            for key, kind in (("daily_quiz", "quiz"), ("daily_wisdom", "wisdom")):
                config = values.get(key)
                if isinstance(config, dict):
                    schedule_config = deepcopy(config)
                    if kind == "wisdom":
                        schedule_config["timezone"] = (values.get("daily_quiz") or {}).get("timezone", "Europe/Moscow")
                    await repo.upsert_schedule(schedule_values(chat_id, kind, schedule_config))
                else:
                    await session.execute(delete(DailySchedule).where(DailySchedule.chat_id == chat_id, DailySchedule.kind == kind))
            snapshot = SettingsSnapshot(values, revision)
        return snapshot
