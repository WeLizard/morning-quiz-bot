"""Local-only admin routes backed by the same database as the Telegram bot.

The migration is incremental. Unported API routes fail closed in PostgreSQL
mode; they must never silently read or write the obsolete JSON projections.
This module does not expose an authenticated public Mini App API.
"""

from __future__ import annotations

import os
import json
from collections import defaultdict
from contextlib import asynccontextmanager
from decimal import Decimal
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr, StrictInt, field_validator
from sqlalchemy import select, text, func
from starlette.routing import Match

from storage.database import Database, DatabaseSettings
from storage.members import MemberNotFound, MemberService, ScoreConflict
from storage.models import Chat, ChatMember, SystemState, User, PollAnswer, QuizSession, ImportRun
from storage.runtime import member_data
from storage.settings import SettingsConflict, SettingsService
from storage.photos import PhotoCatalog, PhotoMetadataConflict, metadata_version


Score = Annotated[Decimal, Query(
    ge=Decimal("-99999999999.999"), le=Decimal("99999999999.999"), decimal_places=3,
)]


class DailyTime(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hour: int = Field(ge=0, le=23, strict=True)
    minute: int = Field(ge=0, le=59, strict=True)


class DailyQuizPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: StrictBool | None = None
    times_msk: list[DailyTime] | None = Field(default=None, max_length=24)
    timezone: str | None = None
    num_questions: int | None = Field(default=None, ge=1, le=100)
    poll_open_seconds: int | None = Field(default=None, ge=5, le=600)
    interval_seconds: int | None = Field(default=None, ge=0, le=86400)
    categories_mode: Literal["random", "specific", "all_enabled"] | None = None
    num_random_categories: int | None = Field(default=None, ge=1, le=100)
    specific_categories: list[str] | None = None


class DailyWisdomPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: StrictBool | None = None
    time: str | None = Field(default=None, pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")


class QuizSettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    auto_delete_bot_messages: StrictBool | None = None
    default_num_questions: int | None = Field(default=None, ge=1, le=100)
    default_open_period_seconds: int | None = Field(default=None, ge=5, le=600)
    default_interval_seconds: int | None = Field(default=None, ge=0, le=86400, strict=True)
    default_announce_quiz: StrictBool | None = None
    default_announce_delay_seconds: int | None = Field(default=None, ge=0, le=300, strict=True)
    quiz_categories_mode: Literal['all', 'random', 'specific', 'exclude'] | None = None
    quiz_categories_pool: list[str] | None = Field(default=None, max_length=200)
    num_categories_per_quiz: int | None = Field(default=None, ge=1, le=100, strict=True)
    enabled_categories: list[str] | None = None
    disabled_categories: list[str] | None = None
    daily_quiz: DailyQuizPatch | None = None
    daily_wisdom: DailyWisdomPatch | None = None

    @field_validator('enabled_categories', 'disabled_categories', 'quiz_categories_pool')
    @classmethod
    def category_names(cls, value):
        if value is not None:
            if len(value) > 200 or any(not name.strip() or len(name) > 100 or '\x00' in name for name in value):
                raise ValueError('Укажите не более 200 непустых названий категорий длиной до 100 символов')
            return list(dict.fromkeys(name.strip() for name in value))
        return value


class ResetSettingsRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_revision: StrictInt = Field(ge=0)
    confirmation: str = Field(max_length=20)


def default_settings():
    # Read only the static quiz defaults; do not instantiate AppConfig/load .env.
    path = Path(__file__).resolve().parents[1] / 'config' / 'quiz_config.json'
    return json.loads(path.read_text(encoding='utf-8'))['default_chat_settings']


class PhotoMetadataPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    correct_answer: str | None = Field(default=None, min_length=1, max_length=300)
    display_answer: str | None = Field(default=None, min_length=1, max_length=300)
    enabled: StrictBool | None = None
    hints: dict[str, StrictStr | StrictInt] | None = Field(default=None, max_length=32)

    @field_validator("hints")
    @classmethod
    def validate_hints(cls, value):
        if value and any(len(key) > 64 or len(str(item)) > 1000 for key, item in value.items()):
            raise ValueError("Подсказки слишком длинные")
        return value


class PhotoArchiveRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    archived: StrictBool
    expected_version: str = Field(pattern=r'^[a-f0-9]{64}$')


def image_path(name):
    from storage.photo_media import images_root
    root = images_root()
    if not name or any(char in name for char in ("/", "\\", ":", "\x00")) or Path(name).name != name:
        raise HTTPException(422, "Недопустимое имя изображения")
    result = (root / name).resolve()
    if not result.is_relative_to(root) or result.suffix.lower() != ".webp":
        raise HTTPException(422, "Недопустимый путь изображения")
    return result


def _iso(value):
    return value.isoformat() if value else None


async def _snapshot(database: Database):
    async with database.transaction() as session:
        await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        chats = list((await session.scalars(select(Chat).order_by(Chat.id))).all())
        users = list((await session.scalars(select(User).order_by(User.id))).all())
        members = list((await session.scalars(select(ChatMember).order_by(
            ChatMember.chat_id, ChatMember.user_id,
        ))).all())
    return chats, users, members


def _chat_details(chat, members, users):
    # Historical quiz/category counters are retained. Live score and answer
    # totals come from memberships, not the imported statistics snapshot.
    stats = dict(chat.statistics or {})
    stats.update({
        "total_score": float(sum((m.score for m in members), Decimal(0))),
        "total_answers": sum(m.answered_count for m in members),
        "correct_answers": sum(m.correct_answers_count for m in members),
        "total_users": len(members),
        "user_activity": {str(m.user_id): {
            "name": users[m.user_id].display_name, "score": float(m.score),
            "answered_count": m.answered_count,
            "correct_answers_count": m.correct_answers_count,
            "consecutive_correct": m.consecutive_correct,
            "max_consecutive_correct": m.max_consecutive_correct,
            "first_answer": _iso(m.first_answer_at), "last_answer": _iso(m.last_answer_at),
            "streak_achievements_count": len(m.streak_achievement_codes or []),
        } for m in members},
    })
    return {
        "chat_id": str(chat.id), "settings": chat.settings or {}, "stats": stats,
        "daily_quiz_enabled": (chat.settings or {}).get("daily_quiz", {}).get("enabled", False),
        "users": {str(m.user_id): member_data(m, users[m.user_id]) for m in members},
        "user_count": len(members), "categories_stats": chat.category_statistics or {},
    }


def make_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/storage/status")
    async def pg_storage_status(request: Request):
        database = request.app.state.admin_database
        async with database.transaction() as session:
            revision = (await session.execute(text('SELECT version_num FROM alembic_version'))).scalars().first()
            completed_imports = int(await session.scalar(
                select(func.count()).select_from(ImportRun).where(ImportRun.status == 'completed')) or 0)
        return {
            "backend": "postgres", "schema_revision": revision, "completed_imports": completed_imports,
            "notice": "Изменяемые данные и банк вопросов хранит PostgreSQL; media-файлы неизменяемы.",
            "capabilities": ["chats", "users", "scores", "settings", "schedules", "photo_metadata", "photo_upload", "question_bank", "analytics", "profiles", "profile_exports", "chat_titles"],
            "unavailable": ["production_control", "live_broadcast"],
            "administration": ["moderation", "reset_preview", "safe_reset", "action_receipts", "profile_archive",
                "maintenance", "dev_backups", "offline_runtime", "offline_broadcast", "admin_ai", "bank_repair"],
        }

    @router.get("/api/photo-quiz")
    async def pg_photos(request: Request):
        catalog = await PhotoCatalog(request.app.state.admin_database).load()
        photos = []
        for key, value in sorted(catalog.items()):
            from storage.photo_media import images_root, verified_image_path
            has_image = verified_image_path(images_root(), key, value) is not None
            from urllib.parse import quote
            photos.append({**value, "name": key, "version": metadata_version(value), "has_image": has_image,
                           "image_url": f"/api/images/{quote(key, safe='')}.webp" if has_image else None})
        return {"photos": photos, "total": len(photos)}

    @router.get('/api/analytics/overview')
    async def pg_overview(request: Request):
        database = request.app.state.admin_database
        async with database.transaction() as session:
            await session.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
            totals = (await session.execute(select(
                func.count(ChatMember.user_id), func.coalesce(func.sum(ChatMember.score), 0),
                func.coalesce(func.sum(ChatMember.answered_count), 0),
                func.coalesce(func.sum(ChatMember.correct_answers_count), 0)))).one()
            chats = (await session.scalars(select(Chat).order_by(Chat.id))).all()
            user_count = await session.scalar(select(func.count()).select_from(User))
            category_state = await session.get(SystemState, 'category_usage_stats')
            categories = category_state.payload if category_state else {}
            # Only new ledger entries have reliable timestamps; imported answers
            # are aggregate counters. Do not invent a historical activity graph.
            activity = (await session.execute(select(func.date(PollAnswer.answered_at), func.count())
                .group_by(func.date(PollAnswer.answered_at)).order_by(func.date(PollAnswer.answered_at).desc()).limit(30))).all()
            active = await session.scalar(select(func.count()).select_from(QuizSession).where(QuizSession.status == 'active'))
            leaders = (await session.scalars(select(User).order_by(User.global_score.desc(), User.id).limit(20))).all()
            return {
                'chats': len(chats), 'users': user_count, 'memberships': totals[0],
                'score': float(totals[1]), 'answers': totals[2], 'correct': totals[3],
                'active_sessions': active,
                'categories': [{'name': key, 'usage': value.get('global_usage', value.get('total_usage', 0)),
                                'chats': len(value.get('chat_usage', {}))} for key, value in sorted(categories.items())],
                'activity': [{'date': str(day), 'answers': count} for day, count in activity],
                'activity_scope': 'Только ответы, записанные после миграции. Старые ответы учтены в итогах, но не в графике по дням.',
                'leaderboard': [{'name': u.display_name, 'id': str(u.id), 'score': float(u.global_score)} for u in leaders],
            }

    @router.put("/api/photo-quiz/{name}")
    async def pg_patch_photo(name: str, data: PhotoMetadataPatch, request: Request,
                             expected_version: Annotated[str | None, Query(pattern=r"^[a-f0-9]{64}$")] = None):
        if expected_version is None:
            raise HTTPException(428, "Передайте expected_version из списка фото-вопросов")
        try:
            value = await PhotoCatalog(request.app.state.admin_database).patch(name,
                data.model_dump(exclude_unset=True, exclude_none=True), expected_version=expected_version)
        except PhotoMetadataConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"success": True, "photo": {**value, "name": name, "version": metadata_version(value)}}

    @router.get("/api/images/{filename}")
    async def pg_image(filename: str, request: Request):
        if not filename.endswith('.webp'):
            raise HTTPException(404, "Изображение не найдено")
        key = filename[:-5]
        catalog = await PhotoCatalog(request.app.state.admin_database).load()
        value = catalog.get(key)
        if value is None:
            raise HTTPException(404, "Изображение не найдено")
        from storage.photo_media import images_root, verified_image_path
        path = verified_image_path(images_root(), key, value)
        if path is None:
            raise HTTPException(404, "Изображение не найдено")
        return FileResponse(path, media_type="image/webp")

    @router.post('/api/photo-quiz/{name}/archive')
    async def pg_archive_photo(name: str, data: PhotoArchiveRequest, request: Request):
        try:
            result = await PhotoCatalog(request.app.state.admin_database).archive(name, **data.model_dump())
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except PhotoMetadataConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        return {'name': name, **result, 'version': metadata_version(result), 'recoverable': True}

    @router.get("/api/schedules/status")
    async def pg_schedule_status(request: Request):
        async with request.app.state.admin_database.transaction() as session:
            status = await session.get(SystemState, "schedule_sync_status")
            payload = status.payload if status else {}
        try:
            checked = datetime.fromisoformat(payload["checked_at"])
            age = (datetime.now(timezone.utc) - checked).total_seconds()
            fresh = 0 <= age <= 45
        except (KeyError, ValueError, TypeError):
            fresh = False
        return {"fresh": fresh, "worker_status": payload}

    @router.get("/api/chats")
    async def pg_chats(request: Request, use_telegram_api: bool = False, include_archived: bool = False):
        # No Telegram requests or JSON writes, even when the legacy UI passes true.
        chats, _, members = await _snapshot(request.app.state.admin_database)
        grouped = defaultdict(list)
        for member in members:
            grouped[member.chat_id].append(member)
        return [{
            "id": chat.id, "title": chat.title or (chat.settings or {}).get("title") or f"Чат {chat.id}",
            "daily_quiz_enabled": (chat.settings or {}).get("daily_quiz", {}).get("enabled", False),
            "daily_quiz_times": (chat.settings or {}).get("daily_quiz", {}).get("times_msk", []),
            "users_count": len(grouped[chat.id]),
            "total_quizzes": (chat.statistics or {}).get("total_quizzes", 0),
            "enabled_categories": (chat.settings or {}).get("enabled_categories", []),
            "disabled_categories": (chat.settings or {}).get("disabled_categories", []),
            "chat_type": chat.type, 'archived': chat.archived,
        } for chat in chats if include_archived or not chat.archived]

    @router.get("/api/chats/{chat_id}/settings")
    async def pg_chat_settings(chat_id: int, request: Request, response: Response):
        async with request.app.state.admin_database.transaction() as session:
            chat = await session.get(Chat, chat_id)
            if chat is None:
                raise HTTPException(404, "Чат не найден")
            response.headers["ETag"] = f'"{chat.settings_revision}"'
            response.headers["X-Settings-Revision"] = str(chat.settings_revision)
            return chat.settings or {}

    @router.get('/api/settings/defaults')
    async def pg_settings_defaults():
        return default_settings()

    @router.post('/api/chats/{chat_id}/reset-settings')
    async def pg_reset_settings(chat_id: int, data: ResetSettingsRequest, request: Request):
        if data.confirmation != str(chat_id):
            raise HTTPException(422, 'Введите ID чата для подтверждения сброса настроек')
        database = request.app.state.admin_database
        async with database.transaction() as session:
            if await session.get(Chat, chat_id) is None:
                raise HTTPException(404, 'Чат не найден')
        try:
            snapshot = await SettingsService(database).reset(chat_id, default_settings(), expected_revision=data.expected_revision)
        except SettingsConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        return {'settings': snapshot.values, 'revision': snapshot.revision, 'schedule_sync': 'pending'}

    @router.put("/api/chats/{chat_id}/settings")
    async def pg_patch_settings(
        chat_id: int, settings_update: QuizSettingsPatch, request: Request, response: Response,
        expected_revision: Annotated[int | None, Query(ge=0)] = None,
    ):
        if expected_revision is None:
            raise HTTPException(428, "Передайте expected_revision из X-Settings-Revision ответа GET настроек.")
        changes = settings_update.model_dump(exclude_unset=True, exclude_none=True)
        if not changes:
            raise HTTPException(422, "Не указаны изменяемые настройки")
        async with request.app.state.admin_database.transaction() as session:
            if await session.get(Chat, chat_id) is None:
                raise HTTPException(404, "Чат не найден")
        paths = []
        for key, value in changes.items():
            if key in {"daily_quiz", "daily_wisdom"}:
                paths.extend(([key, field], item) for field, item in value.items())
            else:
                paths.append(([key], value))
        if not paths:
            raise HTTPException(422, "Не указаны изменяемые настройки")
        for legacy, field in (("default_num_questions", "num_questions"), ("default_open_period_seconds", "open_period_seconds")):
            if legacy in changes:
                paths.append((["quiz", field], changes[legacy]))
        try:
            snapshot = await SettingsService(request.app.state.admin_database).patch_paths(
                chat_id, paths, expected_revision=expected_revision,
            )
        except SettingsConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        response.headers["X-Settings-Revision"] = str(snapshot.revision)
        response.headers["ETag"] = f'"{snapshot.revision}"'
        result = {"message": "Настройки обновлены", "settings": snapshot.values, "revision": snapshot.revision}
        if {"daily_quiz", "daily_wisdom"} & changes.keys():
            result["schedule_sync"] = "pending"
        return result

    @router.get("/api/analytics/chats")
    async def pg_chats_analytics(request: Request):
        chats, users, members = await _snapshot(request.app.state.admin_database)
        user_map = {u.id: u for u in users}
        grouped = defaultdict(list)
        for member in members:
            grouped[member.chat_id].append(member)
        result = [_chat_details(c, grouped[c.id], user_map) for c in chats]
        return {"chats": result, "total": len(result)}

    @router.get("/api/analytics/chats/{chat_id}")
    async def pg_chat_analytics(chat_id: int, request: Request):
        chats, users, members = await _snapshot(request.app.state.admin_database)
        chat = next((c for c in chats if c.id == chat_id), None)
        if chat is None:
            raise HTTPException(404, "Чат не найден")
        return _chat_details(chat, [m for m in members if m.chat_id == chat_id], {u.id: u for u in users})

    @router.get("/api/users")
    async def pg_users(request: Request, include_archived: bool = False):
        chats, users, members = await _snapshot(request.app.state.admin_database)
        titles = {c.id: c.title or (c.settings or {}).get("title") or f"Чат {c.id}" for c in chats}
        grouped = defaultdict(list)
        for member in members:
            grouped[member.user_id].append(member)
        result = []
        for user in users:
            if user.archived and not include_archived:
                continue
            memberships = grouped[user.id]
            activity = [{
                "chat_id": str(m.chat_id), "chat_title": titles[m.chat_id],
                "score": float(m.score), "answered_count": m.answered_count,
                "consecutive_correct": m.consecutive_correct,
                "max_consecutive_correct": m.max_consecutive_correct,
                "first_answer": _iso(m.first_answer_at), "last_answer": _iso(m.last_answer_at),
                "streak_achievements_count": len(m.streak_achievement_codes or []),
            } for m in memberships]
            result.append({
                "user_id": str(user.id), "name": user.display_name, 'archived': user.archived,
                "total_score": float(user.global_score), "total_answered": user.total_answered,
                "max_streak": max((m.max_consecutive_correct for m in memberships), default=0),
                "streak_achievements": sum(len(m.streak_achievement_codes or []) for m in memberships),
                "first_activity": _iso(user.first_answer_at), "last_activity": _iso(user.last_answer_at),
                "chats_activity": activity, "chats_count": len(activity),
            })
        result.sort(key=lambda u: (-u["total_score"], int(u["user_id"])))
        for rank, user in enumerate(result, 1):
            user["rank"] = rank
        return {"users": result, "total": len(result)}

    @router.put("/api/users/{user_id}/score")
    async def pg_set_score(
        user_id: int, chat_id: int, new_score: Score, request: Request,
        expected_score: Annotated[Decimal | None, Query(allow_inf_nan=False)] = None,
    ):
        try:
            old = await MemberService(request.app.state.admin_database).set_score(
                chat_id, user_id, new_score, expected_score,
            )
        except MemberNotFound as exc:
            raise HTTPException(404, str(exc)) from exc
        except ScoreConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {
            "success": True, "message": f"Баллы изменены: {old} → {new_score}",
            "old_score": float(old), "new_score": float(new_score),
        }

    return router


# No legacy API handler is allowed to mutate a file-backed question/media catalog.
STATIC_HANDLER_NAMES = frozenset()  # PG bank uses versioned /api/bank; no legacy writes.


def install_postgres_admin(app: FastAPI) -> None:
    backend = os.getenv("STORAGE_BACKEND", "postgres").strip().lower()
    if backend != "postgres":
        @asynccontextmanager
        async def reject_legacy_runtime(application):
            raise RuntimeError(
                "Admin runtime requires STORAGE_BACKEND=postgres; "
                "JSON is supported only as an explicit migration input."
            )
            yield application

        app.router.lifespan_context = reject_legacy_runtime
        return

    previous_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application):
        # Legacy routes are declared later in web.main. Do not let their
        # schemas hide the versioned PG contracts in /docs and /openapi.json.
        for route in application.routes:
            if (getattr(route, "path", "").startswith("/api/")
                    and getattr(route, "endpoint", None) not in pg_endpoints
                    and route.name not in STATIC_HANDLER_NAMES):
                route.include_in_schema = False
        application.openapi_schema = None
        database = Database(DatabaseSettings.from_env())
        application.state.admin_database = database
        try:
            await database.check_connection()
            from storage.startup import require_current_schema
            await require_current_schema(database)
            async with previous_lifespan(application) as state:
                yield state
        finally:
            if getattr(application.state, 'dev_runtime', None):
                await application.state.dev_runtime.stop()
            await database.dispose()

    app.router.lifespan_context = lifespan
    router = make_router()
    from web.question_bank_admin import make_bank_router
    router.include_router(make_bank_router())
    from web.photo_upload import make_photo_upload_router
    router.include_router(make_photo_upload_router())
    from web.admin_profiles import make_profiles_router
    router.include_router(make_profiles_router())
    from web.admin_actions import make_actions_router
    router.include_router(make_actions_router())
    from web.admin_analytics import make_analytics_router
    router.include_router(make_analytics_router())
    from web.system_control import make_system_router
    router.include_router(make_system_router())
    from web.dev_backups import make_backups_router
    router.include_router(make_backups_router())
    from web.broadcasts import make_broadcast_router
    router.include_router(make_broadcast_router())
    from web.dev_runtime import make_dev_runtime_router
    router.include_router(make_dev_runtime_router())
    from web.admin_ai import make_ai_router
    router.include_router(make_ai_router())
    app.include_router(router)
    pg_endpoints = {route.endpoint for route in router.routes}

    @app.middleware("http")
    async def prevent_json_fallback(request: Request, call_next):
        if request.url.path.startswith("/api/"):
            for route in app.routes:
                match, _ = route.matches(request.scope)
                if match is Match.FULL:
                    if getattr(route, "endpoint", None) in pg_endpoints or route.name in STATIC_HANDLER_NAMES:
                        return await call_next(request)
                    break
            return JSONResponse(status_code=501, content={
                "detail": "Эта операция ещё не перенесена на PostgreSQL. JSON fallback отключён.",
                "storage_backend": "postgres",
            })
        return await call_next(request)
