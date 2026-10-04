"""Loopback-only UI preview using synthetic data in persistent compose.dev.yml."""
import asyncio
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def seed():
    from hashlib import sha256
    from storage.database import Database, DatabaseSettings
    from storage.repositories import OperationalRepository
    from storage.photo_media import create_photo, images_root
    from storage.question_bank import PostgresQuestionBank
    from storage.settings import SettingsService
    from storage.models import Chat
    database = Database(DatabaseSettings.from_env())
    try:
        async with database.transaction() as session:
            repo = OperationalRepository(session)
            existing = await session.get(Chat, -900000000091)
            await repo.ensure_chat({"id": -900000000091, "type": "group", "title": "Тестовый чат"})
            await repo.ensure_user({"id": 900000000091, "display_name": "Тестовый игрок <без разметки>"})
            await repo.ensure_member({"chat_id": -900000000091, "user_id": 900000000091, "score": 12})
            await repo.recompute_user_totals(900000000091)
        if existing is None:
            await SettingsService(database).patch_paths(-900000000091, [
            (("default_num_questions",), 10), (("default_open_period_seconds",), 60),
            (("auto_delete_bot_messages",), True), (("daily_quiz", "enabled"), False),
            (("daily_quiz", "timezone"), "Europe/Moscow"),
            (("daily_quiz", "times_msk"), [{"hour": 9, "minute": 0}]),
            ])
        workspace = Path(__file__).resolve().parents[1]
        await PostgresQuestionBank(database).seed_from_directory(
            workspace / 'data' / 'questions',
            metadata_path=workspace / 'data' / 'global' / 'categories.json',
        )
        # Dev-only, repeatable media seed. Runtime never discovers files or
        # derives answers from filenames; this explicit import creates PG rows
        # and content-addressed immutable copies in the mounted preview volume.
        for source in sorted((workspace / 'data' / 'images').glob('*.webp')):
            raw = source.read_bytes()
            await create_photo(
                database,
                sha256(raw).hexdigest()[:32],
                raw,
                source.stem,
                True,
                root=images_root(),
            )
    finally:
        await database.dispose()


if __name__ == "__main__":
    url = urlsplit(os.getenv("DATABASE_URL", ""))
    container_dev = os.getenv('MQB_DEV_CONTAINER') == '1' and Path('/.dockerenv').is_file()
    expected_endpoint = ('postgres', 5432) if container_dev else ('127.0.0.1', 55433)
    if ((url.hostname, url.port) != expected_endpoint or url.path != "/morning_quiz_dev"
            or url.username != "mqb_dev" or os.getenv("TEST_DATABASE_URL")):
        raise SystemExit("Preview requires the dedicated local dev database, never TEST_DATABASE_URL")
    if len(os.getenv("ADMIN_ACCESS_TOKEN", "")) < 32:
        raise SystemExit("Set a separate test ADMIN_ACCESS_TOKEN of at least 32 characters")
    os.environ.update(STORAGE_BACKEND="postgres", BOT_TOKEN="", OPENROUTER_API_KEY="", SENTRY_DSN="", MODE="testing",
                      MQB_DEV_RUNTIME='offline',
                      ADMIN_ALLOWED_HOSTS="localhost,127.0.0.1,::1")
    workspace = Path(__file__).resolve().parents[1]
    preview_images = (workspace / '.local' / 'preview' / 'images').resolve()
    if not preview_images.is_relative_to(workspace) or preview_images == workspace:
        raise SystemExit('Preview images must stay inside the local workspace')
    preview_images.mkdir(parents=True, exist_ok=True)
    os.environ['PHOTO_IMAGES_DIR'] = str(preview_images)
    asyncio.run(seed())
    from web.main import app
    from fastapi.responses import JSONResponse

    @app.middleware("http")
    async def preview_readonly_files(request, call_next):
        if not request.url.path.startswith('/api/bank/') and request.method not in {"GET", "HEAD", "OPTIONS"} and any(
                fragment in request.url.path for fragment in ("/categories", "/questions", "/upload-image")):
            return JSONResponse({"detail": "В preview запись файлов отключена"}, status_code=403)
        return await call_next(request)

    import uvicorn
    bind_host = os.getenv('MQB_DEV_BIND_HOST', '127.0.0.1')
    if bind_host != '127.0.0.1' and not container_dev:
        raise SystemExit('A non-loopback preview bind is allowed only inside the local dev container')
    uvicorn.run(app, host=bind_host, port=4184, access_log=False, proxy_headers=False)
