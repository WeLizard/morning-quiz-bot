"""Explicit loopback synthetic preview. Never used by the public Mini App factory."""
import asyncio
from hashlib import sha256
import os
from pathlib import Path
import time
from urllib.parse import urlsplit
from uuid import uuid4

from web.mini_app import MiniAppSettings, create_app
from web.mini_auth import TelegramIdentity

DEMO_USER = 900000000091
DEMO_CHAT = -900000000091
SYNTHETIC_TOKEN = '123456:LOCAL_TEST_ONLY_012345678901234567890'


class DemoMembership:
    async def allowed(self, chat_id, user_id):
        return chat_id == DEMO_CHAT and user_id == DEMO_USER


def create_dev_app():
    parsed = urlsplit(os.getenv('MINI_APP_DATABASE_URL', ''))
    settings = MiniAppSettings.from_env()
    container_dev = os.getenv('MQB_DEV_CONTAINER') == '1' and Path('/.dockerenv').is_file()
    expected_endpoint = ('postgres', 5432) if container_dev else ('127.0.0.1', 55433)
    if ((parsed.hostname, parsed.port) != expected_endpoint or parsed.path != '/morning_quiz_dev'
            or parsed.username != 'mqb_dev' or not settings.offline or settings.origin != 'http://127.0.0.1:4185'
            or settings.bot_token != SYNTHETIC_TOKEN):
        raise RuntimeError('Synthetic preview requires the dedicated loopback dev database and synthetic key')
    player_id = int(os.getenv('MINI_APP_DEV_USER_ID') or DEMO_USER)
    if player_id <= 0:
        raise RuntimeError('A positive dev player ID is required')
    # Separate opt-ins: disabling new Classic starts must never revoke guests'
    # access to their already-running rooms. Real Telegram private tests remain closed.
    guests_enabled = player_id == DEMO_USER and os.getenv('MQB_DEV_GUEST_ENABLED', '') == '1'
    room_classic_enabled = guests_enabled and os.getenv('MQB_ROOM_CLASSIC_ENABLED', '') == '1'
    room_photo_enabled = guests_enabled and os.getenv('MQB_ROOM_PHOTO_ENABLED', '') == '1'
    app = create_app(settings=settings, membership=DemoMembership(),
                     allowed_user_ids={player_id}, dev_guest_access=guests_enabled,
                     runtime_enabled=player_id == DEMO_USER, room_classic_enabled=room_classic_enabled,
                     room_photo_enabled=room_photo_enabled)
    if player_id == DEMO_USER:
        from contextlib import asynccontextmanager
        original_lifespan = app.router.lifespan_context
        @asynccontextmanager
        async def with_synthetic_chat(application):
            async with original_lifespan(application):
                database = app.state.mini_store.database
                from storage.dev_backups import guard
                from storage.repositories import OperationalRepository
                await asyncio.to_thread(guard, database)
                async with database.transaction() as session:
                    repo = OperationalRepository(session)
                    await repo.ensure_chat({'id': player_id, 'type': 'private', 'title': 'Моя тестовая игра'})
                    await repo.ensure_member({'chat_id': player_id, 'user_id': player_id})
                yield
        app.router.lifespan_context = with_synthetic_chat

    @app.get('/api/dev/info')
    async def info():
        return {'demo': True, 'identity': 'Синтетический dev-игрок' if player_id == DEMO_USER else 'Твой профиль в локальной dev-БД',
                'synthetic_player': player_id == DEMO_USER, 'telegram_delivery': False}

    @app.post('/api/dev/session')
    async def login():
        identity = TelegramIdentity(player_id, int(time.time()), sha256(uuid4().bytes).hexdigest())
        # Loopback preview tabs are disposable and can be reopened frequently.
        # The public Telegram path keeps the default cap of five active sessions.
        payload = await app.state.mini_store.create_session(identity, session_limit=100)
        return app.state.mini_session_response(payload)

    return app
