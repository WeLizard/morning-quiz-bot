"""Separate Mini App ASGI service. Never import or mount web.main/admin routes."""
import asyncio
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
import ipaddress
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Query, Request, Response
from fastapi.responses import JSONResponse, FileResponse
import httpx
from sqlalchemy.exc import SQLAlchemyError

from storage.database import Database, DatabaseSettings, normalize_database_url
from storage.mini_app import MiniAppError, MiniAppStore
from web.mini_auth import InvalidInitData, unique_object, validate_init_data


@dataclass(frozen=True)
class MiniAppSettings:
    bot_token: str = field(repr=False)
    origin: str
    offline: bool = False
    bot_username: str = ''

    def __post_init__(self):
        if self.bot_username and not re.fullmatch(r'[A-Za-z0-9_]{5,32}', self.bot_username):
            raise ValueError('Invalid Telegram bot username')
        if not re.fullmatch(r'[0-9]+:[A-Za-z0-9_-]{30,}', self.bot_token):
            raise ValueError('Set a dedicated MINI_APP_BOT_TOKEN for the same Telegram bot')
        parsed = urlsplit(self.origin)
        if (parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path
                or not parsed.hostname or parsed.hostname == '*'):
            raise ValueError('MINI_APP_ORIGIN must be an exact origin without a path')
        if parsed.scheme != 'https' and not (self.offline and parsed.scheme == 'http'
                and parsed.hostname in {'127.0.0.1', 'localhost', '::1'}):
            raise ValueError('Mini App requires HTTPS; HTTP is allowed only for offline loopback tests')

    @classmethod
    def from_env(cls):
        # No .env loading and no reuse of ADMIN_ACCESS_TOKEN/BOT_TOKEN.
        return cls(
            os.getenv('MINI_APP_BOT_TOKEN', ''),
            os.getenv('MINI_APP_ORIGIN', ''),
            os.getenv('MINI_APP_OFFLINE', '') == '1',
            os.getenv('MINI_APP_BOT_USERNAME', ''),
        )


class TelegramMembership:
    def __init__(self, token, *, client=None):
        self._token = token
        self.bot_id = int(token.split(':', 1)[0])
        self.client = client or httpx.AsyncClient(timeout=5, follow_redirects=False, trust_env=False)

    async def close(self):
        await self.client.aclose()

    async def allowed(self, chat_id, user_id):
        async def member(uid):
            response = await self.client.post(f'https://api.telegram.org/bot{self._token}/getChatMember',
                                              json={'chat_id': chat_id, 'user_id': uid})
            response.raise_for_status()
            body = response.json()
            result = body.get('result', {})
            if body.get('ok') is not True or result.get('user', {}).get('id') != uid:
                raise ValueError()
            return result
        try:
            async with asyncio.timeout(8):
                # Telegram only guarantees querying other members for bot admins.
                if (await member(self.bot_id)).get('status') not in {'creator', 'administrator'}:
                    raise ValueError()
                result = await member(user_id)
                return result.get('status') in {'creator', 'administrator', 'member'} or (
                    result.get('status') == 'restricted' and result.get('is_member') is True)
        except (httpx.HTTPError, ValueError, TypeError, AttributeError, TimeoutError):
            # Never log exception strings containing the secret-bearing Telegram URL.
            raise MiniAppError(503, 'Не удалось подтвердить членство в Telegram') from None


class RequestLimits:
    """Bounded, single-process ingress limits; edge limits still required at deployment."""
    def __init__(self, clock=time.monotonic):
        self.clock, self.global_requests, self.frequent_reads, self.clients = clock, deque(), deque(), {}

    def allow(self, client, auth=False, frequent_read=False):
        now = self.clock()
        global_bucket = self.frequent_reads if frequent_read else self.global_requests
        global_limit = 5000 if frequent_read else 600
        while global_bucket and global_bucket[0] <= now - 60:
            global_bucket.popleft()
        if len(global_bucket) >= global_limit:
            return False
        global_bucket.append(now)
        self.clients = {key: values for key, values in self.clients.items() if values[-1] > now - 60}
        # A frequent, read-only game refresh must not consume the much smaller
        # bucket for login or write operations from the same Telegram client.
        key = (client, auth, frequent_read)
        recent = [value for value in self.clients.get(key, ()) if value > now - 60]
        per_client_limit = 10 if auth else 600 if frequent_read else 120
        if len(recent) >= per_client_limit:
            return False
        self.clients[key] = recent + [now]
        return True


def create_app(*, database=None, settings=None, membership=None, clock=time.time, allowed_user_ids=None,
               runtime_enabled=False, scoring_rules=None):
    settings = settings or MiniAppSettings.from_env()
    owned_db = database is None
    database = database or Database(DatabaseSettings(url=normalize_database_url(os.getenv('MINI_APP_DATABASE_URL', ''))))
    # Offline is fail-closed for groups; it never substitutes a permissive verifier.
    verifier = membership if membership is not None else (None if settings.offline else TelegramMembership(settings.bot_token))
    limits = RequestLimits()
    config_path = Path(__file__).resolve().parents[1] / 'config' / 'quiz_config.json'
    try:
        quiz_config = json.loads(config_path.read_text(encoding='utf-8'))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        quiz_config = {}
    streak_path = Path(__file__).resolve().parents[1] / 'data' / 'system' / 'streak_achievements.json'
    try:
        streak_raw = json.loads(streak_path.read_text(encoding='utf-8')).get('streak_achievements') or {} \
            if streak_path.is_file() else {}
    except (OSError, ValueError, TypeError, json.JSONDecodeError, AttributeError):
        streak_raw = {}
    # Каталоги достижений для экрана мини-аппа: порог -> текст поздравления.
    chat_achievements: dict = {}
    for key, message in ((quiz_config.get('global_settings') or {}).get('chat_achievements') or {}).items():
        try:
            chat_achievements[int(key)] = str(message)
        except (TypeError, ValueError):
            continue
    streak_achievements: dict = {}
    for key, messages in streak_raw.items():
        try:
            threshold = int(key)
        except (TypeError, ValueError):
            continue
        if isinstance(messages, list) and messages:
            streak_achievements[threshold] = [str(item) for item in messages]
    if scoring_rules is None:
        from domain.scoring import ClassicScoringRules
        scoring_rules = ClassicScoringRules.from_settings(
            quiz_config.get('global_settings'), streak_milestones=tuple(sorted(streak_achievements)))
    store = MiniAppStore(database, settings.bot_token, clock=clock, allowed_user_ids=allowed_user_ids,
                         chat_achievements=chat_achievements, streak_achievements=streak_achievements)

    @asynccontextmanager
    async def lifespan(app):
        try:
            await database.check_connection()
            if owned_db:
                from storage.startup import require_current_schema
                await require_current_schema(database)
            yield
        finally:
            if membership is None and verifier is not None:
                await verifier.close()
            if owned_db:
                await database.dispose()

    app = FastAPI(title='Morning Quiz Mini App API', docs_url=None, redoc_url=None,
                  openapi_url=None, lifespan=lifespan, redirect_slashes=False)
    app.state.mini_store = store
    app.state.mini_runtime_enabled = runtime_enabled

    @app.exception_handler(MiniAppError)
    async def expected_error(request, error):
        return JSONResponse({'detail': error.detail}, error.status,
                            headers={'Retry-After': '60'} if error.status == 429 else None)

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request, error):
        return JSONResponse({'detail': 'Хранилище временно недоступно'}, 503)

    @app.middleware('http')
    async def boundary(request, call_next):
        public_page = request.method in {'GET', 'HEAD'} and request.url.path in {'/app', '/app/app.js', '/app/telegram-ui.js', '/app/game-ui.js', '/app/play-ui.js', '/app/styles.css', '/app/host.webp', '/app/photo.webp', '/app/mafia.webp'}
        origin = f'{request.url.scheme}://{request.url.netloc}'
        allowed = origin == settings.origin
        if request.url.scheme != 'https':
            try:
                loopback = ipaddress.ip_address(request.client.host).is_loopback
            except (ValueError, AttributeError):
                loopback = False
            container_proxy = (os.getenv('MQB_DEV_CONTAINER') == '1' and Path('/.dockerenv').is_file()
                               and request.url.hostname in {'127.0.0.1', 'localhost', '::1'})
            allowed = allowed and settings.offline and (loopback or container_proxy)
        if not allowed:
            response = JSONResponse({'detail': 'Недопустимый адрес сервиса'}, 400)
        elif (request.headers.get('origin') not in (None, settings.origin)
              or (request.headers.get('sec-fetch-site') == 'cross-site' and not public_page)):
            response = JSONResponse({'detail': 'Межсайтовый запрос запрещён'}, 403)
        # Login needs a deliberately tight bucket.  A game setup may legitimately
        # contain several callbacks, and the read-only runtime endpoint is polled
        # while a round is open; both still remain bounded per client and globally.
        elif not (settings.offline and request.url.path == '/api/dev/session') and not limits.allow(
                request.client.host if request.client else '', request.url.path == '/api/mini/session',
                request.url.path == '/api/mini/runtime'):
            response = JSONResponse({'detail': 'Слишком много запросов'}, 429, headers={'Retry-After': '60'})
        else:
            response = await call_next(request)
        response.headers.update({'Cache-Control': 'no-store', 'Pragma': 'no-cache',
            'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer',
            'Content-Security-Policy': "default-src 'none'; frame-ancestors 'none'"})
        if public_page:
            response.headers['Content-Security-Policy'] = "default-src 'none'; script-src 'self' https://telegram.org; style-src 'self'; img-src 'self' blob:; connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors https://web.telegram.org https://*.telegram.org"
        return response

    def credential(request):
        header = request.headers.get('authorization', '')
        if not header.startswith('Bearer '):
            raise MiniAppError(401, 'Требуется вход через Telegram')
        return header[7:]

    async def chat_access(request, chat_id):
        token = credential(request)
        uid = await store.chat_identity(token, chat_id)
        if chat_id != uid:
            if verifier is None:
                raise MiniAppError(503, 'Проверка Telegram отключена в локальном offline-режиме')
            if not await verifier.allowed(chat_id, uid):
                raise MiniAppError(403, 'Членство в чате не подтверждено')
        return token  # Projection rechecks session/chat after the external await.

    @app.get('/')
    async def index():
        return {'service': 'morning-quiz-mini-api', 'api_version': 1,
                'authentication': 'telegram-init-data', 'offline': settings.offline,
                'game_writes_enabled': runtime_enabled}

    @app.get('/healthz')
    async def health():
        await database.check_connection()
        return {'status': 'ok'}

    @app.get('/api/mini/config')
    async def client_config():
        return {'bot_username': settings.bot_username, 'game_location': 'shared-bot-and-app' if runtime_enabled else 'telegram-chat', 'offline': settings.offline,
                'runtime_enabled': runtime_enabled,
                'private_test': allowed_user_ids is not None}

    @app.get('/app')
    async def frontend():
        return FileResponse(Path(__file__).parent / 'mini_client' / 'index.html')

    @app.get('/app/{asset}')
    async def frontend_asset(asset: str):
        if asset == 'host.webp':
            return FileResponse(Path(__file__).parent / 'prototypes' / 'mini-app' / 'assets' / 'host-daily.webp')
        if asset == 'photo.webp':
            return FileResponse(Path(__file__).parent / 'prototypes' / 'mini-app' / 'assets' / 'host-photo-table-v3.webp')
        if asset == 'mafia.webp':
            return FileResponse(Path(__file__).parent / 'prototypes' / 'mini-app' / 'assets' / 'host-mafia.webp')
        if asset not in {'app.js', 'telegram-ui.js', 'game-ui.js', 'play-ui.js', 'styles.css'}:
            raise MiniAppError(404, 'Файл не найден')
        return FileResponse(Path(__file__).parent / 'mini_client' / asset)

    @app.post('/api/mini/session')
    async def login(request: Request):
        if request.headers.get('content-type', '').split(';')[0].strip() != 'application/json':
            raise MiniAppError(415, 'Ожидается JSON')
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 20000:
                raise MiniAppError(413, 'Запрос слишком большой')
        try:
            value = json.loads(body, object_pairs_hook=unique_object)
            if not isinstance(value, dict) or set(value) != {'init_data'}:
                raise ValueError()
            identity = validate_init_data(value['init_data'], settings.bot_token, now=clock())
        except (ValueError, TypeError, UnicodeError, InvalidInitData, RecursionError):
            raise MiniAppError(401, 'Недействительные или просроченные данные Telegram') from None
        return await store.create_session(identity)

    @app.post('/api/mini/session/renew')
    async def renew(request: Request):
        # Продление тем же токеном: активная сессия не упирается в лимит входов.
        return await store.renew_session(credential(request))

    @app.delete('/api/mini/session')
    async def logout(request: Request):
        await store.logout(credential(request))
        return Response(status_code=204)

    @app.get('/api/mini/me')
    async def profile(request: Request):
        return await store.profile(credential(request))

    @app.get('/api/mini/chats')
    async def chats(request: Request, limit: int = Query(20, ge=1, le=50), offset: int = Query(0, ge=0, le=10000)):
        return await store.chats(credential(request), limit=limit, offset=offset)

    @app.get('/api/mini/progress')
    async def progress(request: Request):
        return await store.progress(credential(request))

    @app.get('/api/mini/achievements')
    async def achievements(request: Request):
        # Экран достижений: свои полученные и ближайшие впереди, без чужих данных.
        return await store.achievements(credential(request))

    @app.get('/api/mini/leaderboard')
    async def global_leaderboard(request: Request, limit: int = Query(20, ge=1, le=50), offset: int = Query(0, ge=0, le=10000)):
        return await store.global_leaderboard(credential(request), limit=limit, offset=offset)

    @app.get('/api/mini/chats/{chat_id}/details')
    async def chat_details(request: Request, chat_id: int):
        if not -(2**52) < chat_id < 2**52 or chat_id == 0:
            raise MiniAppError(404, 'Чат недоступен')
        return await store.chat_details(await chat_access(request, chat_id), chat_id)

    @app.get('/api/mini/chats/{chat_id}/leaderboard')
    async def leaderboard(request: Request, chat_id: int, limit: int = Query(20, ge=1, le=50), offset: int = Query(0, ge=0, le=10000)):
        if not -(2**52) < chat_id < 2**52 or chat_id == 0:
            raise MiniAppError(404, 'Чат недоступен')
        return await store.leaderboard(await chat_access(request, chat_id), chat_id, limit=limit, offset=offset)

    @app.get('/api/mini/chats/{chat_id}/games')
    async def games(request: Request, chat_id: int):
        if not -(2**52) < chat_id < 2**52 or chat_id == 0:
            raise MiniAppError(404, 'Чат недоступен')
        return await store.games(await chat_access(request, chat_id), chat_id)

    @app.put('/api/mini/chats/{chat_id}/classic-settings')
    async def classic_settings(request: Request, chat_id: int):
        from storage.settings import SettingsConflict, SettingsService
        if not runtime_enabled:
            raise MiniAppError(409, 'Редактирование настроек сейчас отключено')
        if request.headers.get('content-type', '').split(';')[0].strip() != 'application/json':
            raise MiniAppError(415, 'Ожидается JSON')
        raw = await request.body()
        if len(raw) > 1000:
            raise MiniAppError(413, 'Настройки слишком большие')
        try:
            value = json.loads(raw, object_pairs_hook=unique_object)
            expected = {'questions', 'seconds', 'interval', 'announce', 'announce_delay', 'expected_revision'}
            if not isinstance(value, dict) or set(value) != expected:
                raise ValueError()
            if (type(value['questions']) is not int or not 1 <= value['questions'] <= 50
                    or type(value['seconds']) is not int or not 5 <= value['seconds'] <= 600
                    or type(value['interval']) is not int or not 0 <= value['interval'] <= 600
                    or type(value['announce']) is not bool
                    or type(value['announce_delay']) is not int or not 0 <= value['announce_delay'] <= 300
                    or type(value['expected_revision']) is not int or value['expected_revision'] < 0):
                raise ValueError()
        except (ValueError, UnicodeError, RecursionError):
            raise MiniAppError(400, 'Некорректные параметры викторины') from None
        token = await chat_access(request, chat_id)
        async with store.authorized(token) as (session, user):
            await store.require_chat(session, user.id, chat_id)
            if chat_id != user.id:
                raise MiniAppError(403, 'Групповые настройки меняет администратор в Telegram')
            user_id = user.id
        try:
            saved = await SettingsService(database).patch_paths(chat_id, [
                (('quiz', 'num_questions'), value['questions']),
                (('quiz', 'open_period_seconds'), value['seconds']),
                (('quiz', 'interval_seconds'), value['interval']),
                (('quiz', 'announce'), value['announce']),
                (('quiz', 'announce_delay_seconds'), value['announce_delay']),
            ], defaults=quiz_config.get('default_chat_settings') or {},
               expected_revision=value['expected_revision'], actor_user_id=user_id)
        except SettingsConflict as error:
            raise MiniAppError(409, str(error)) from None
        return {'revision': saved.revision, 'classic': {
            'questions': saved.values.get('quiz', {}).get('num_questions'),
            'seconds': saved.values.get('quiz', {}).get('open_period_seconds'),
            'interval': saved.values.get('quiz', {}).get('interval_seconds'),
            'announce': bool(saved.values.get('quiz', {}).get('announce')),
            'announce_delay': saved.values.get('quiz', {}).get('announce_delay_seconds'),
        }}

    async def available_categories():
        from storage.question_bank import PostgresQuestionBank
        return [item['name'] for item in await PostgresQuestionBank(database).categories()]

    @app.get('/api/mini/categories')
    async def mini_categories(request: Request):
        async with store.authorized(credential(request)):
            return {'items': await available_categories()}

    @app.put('/api/mini/chats/{chat_id}/preferences')
    async def save_mini_preferences(request: Request, chat_id: int):
        """Save the complete personal game/schedule form through shared settings."""
        from storage.settings import SettingsConflict, SettingsService
        import pytz
        if not runtime_enabled:
            raise MiniAppError(409, 'Изменение настроек сейчас отключено')
        if request.headers.get('content-type', '').split(';')[0].strip() != 'application/json':
            raise MiniAppError(415, 'Ожидается JSON')
        raw = await request.body()
        if len(raw) > 12000:
            raise MiniAppError(413, 'Настройки слишком большие')
        try:
            value = json.loads(raw, object_pairs_hook=unique_object)
            if not isinstance(value, dict) or set(value) != {'classic', 'daily', 'wisdom', 'auto_delete', 'expected_revision'}:
                raise ValueError()
            classic, daily, wisdom = value['classic'], value['daily'], value['wisdom']
            if (not isinstance(classic, dict) or set(classic) != {
                    'questions', 'seconds', 'interval', 'announce', 'announce_delay',
                    'category_mode', 'categories', 'random_categories'}
                    or not isinstance(daily, dict) or set(daily) != {
                    'enabled', 'times', 'timezone', 'questions', 'interval', 'seconds',
                    'category_mode', 'categories', 'random_categories'}
                    or not isinstance(wisdom, dict) or set(wisdom) != {'enabled', 'time'}
                    or type(value['auto_delete']) is not bool
                    or type(value['expected_revision']) is not int or value['expected_revision'] < 0):
                raise ValueError()
            modes = {'all', 'specific', 'exclude', 'random'}
            known = set(await available_categories())
            def category_values(item):
                categories = item['categories']
                if (item['category_mode'] not in modes or not isinstance(categories, list)
                        or len(categories) > len(known) or any(not isinstance(name, str) or name not in known for name in categories)
                        or len(categories) != len(set(categories))
                        or type(item['random_categories']) is not int or not 1 <= item['random_categories'] <= 10
                        or (item['category_mode'] == 'specific' and not categories)):
                    raise ValueError()
                return categories
            classic_categories = category_values(classic)
            daily_categories = category_values(daily)
            if (type(classic['questions']) is not int or not 1 <= classic['questions'] <= 50
                    or type(classic['seconds']) is not int or not 5 <= classic['seconds'] <= 600
                    or type(classic['interval']) is not int or not 0 <= classic['interval'] <= 600
                    or type(classic['announce']) is not bool
                    or type(classic['announce_delay']) is not int or not 0 <= classic['announce_delay'] <= 300
                    or type(daily['enabled']) is not bool or not isinstance(daily['times'], list)
                    or not 0 <= len(daily['times']) <= 5
                    or not isinstance(daily['timezone'], str) or daily['timezone'] not in pytz.all_timezones_set
                    or type(daily['questions']) is not int or not 1 <= daily['questions'] <= 50
                    or type(daily['interval']) is not int or not 10 <= daily['interval'] <= 3600
                    or type(daily['seconds']) is not int or not 30 <= daily['seconds'] <= 7200
                    or type(wisdom['enabled']) is not bool or not isinstance(wisdom['time'], str)
                    or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', wisdom['time'])):
                raise ValueError()
            times = []
            for item in daily['times']:
                if not isinstance(item, str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', item):
                    raise ValueError()
                hour, minute = map(int, item.split(':'))
                times.append({'hour': hour, 'minute': minute})
            if len(daily['times']) != len(set(daily['times'])) or (daily['enabled'] and not times):
                raise ValueError()
        except (ValueError, UnicodeError, RecursionError):
            raise MiniAppError(400, 'Некорректные настройки') from None
        token = await chat_access(request, chat_id)
        async with store.authorized(token) as (session, user):
            await store.require_chat(session, user.id, chat_id)
            if chat_id != user.id:
                raise MiniAppError(403, 'Групповые настройки меняет администратор в Telegram')
            actor = user.id
        changes = [
            (('quiz', 'num_questions'), classic['questions']),
            (('quiz', 'open_period_seconds'), classic['seconds']),
            (('quiz', 'interval_seconds'), classic['interval']),
            (('quiz', 'announce'), classic['announce']),
            (('quiz', 'announce_delay_seconds'), classic['announce_delay']),
            (('quiz', 'categories_mode'), classic['category_mode']),
            (('quiz', 'specific_categories'), classic_categories),
            (('quiz', 'num_random_categories'), classic['random_categories']),
            (('daily_quiz', 'enabled'), daily['enabled']),
            (('daily_quiz', 'times_msk'), times),
            (('daily_quiz', 'timezone'), daily['timezone']),
            (('daily_quiz', 'num_questions'), daily['questions']),
            (('daily_quiz', 'interval_seconds'), daily['interval']),
            (('daily_quiz', 'poll_open_seconds'), daily['seconds']),
            (('daily_quiz', 'categories_mode'), daily['category_mode']),
            (('daily_quiz', 'specific_categories'), daily_categories),
            (('daily_quiz', 'num_random_categories'), daily['random_categories']),
            (('daily_wisdom', 'enabled'), wisdom['enabled']),
            (('daily_wisdom', 'time'), wisdom['time']),
            (('auto_delete_bot_messages',), value['auto_delete']),
        ]
        try:
            saved = await SettingsService(database).patch_paths(
                chat_id, changes, defaults=quiz_config.get('default_chat_settings') or {},
                expected_revision=value['expected_revision'], actor_user_id=actor,
            )
        except SettingsConflict as error:
            raise MiniAppError(409, str(error)) from None
        except ValueError as error:
            raise MiniAppError(400, str(error)) from None
        return {'revision': saved.revision}

    @app.get('/api/mini/classic/chats/{chat_id}/current')
    async def classic_current(request: Request, chat_id: int):
        from application.classic import ClassicApplicationService
        if not -(2**52) < chat_id < 2**52 or chat_id == 0:
            raise MiniAppError(404, 'Чат недоступен')
        token = await chat_access(request, chat_id)
        async with store.authorized(token) as (session, user):
            await store.require_chat(session, user.id, chat_id)
            current = await ClassicApplicationService(
                database, session, rules=scoring_rules).current(chat_id=chat_id, user_id=user.id)
            if current is None:
                raise MiniAppError(404, 'Активная викторина не найдена')
            return current

    @app.post('/api/mini/classic/chats/{chat_id}/start')
    async def classic_start(request: Request, chat_id: int):
        from application.classic import ClassicApplicationService
        from application.classic_selection import select_classic_questions
        from storage.classic_sessions import ClassicSessionConflict
        if not runtime_enabled:
            raise MiniAppError(409, 'Запуск игр в Mini App сейчас отключён')
        if request.headers.get('content-type', '').split(';')[0].strip() != 'application/json':
            raise MiniAppError(415, 'Ожидается JSON')
        raw = await request.body()
        if len(raw) > 300:
            raise MiniAppError(413, 'Команда слишком большая')
        try:
            value = json.loads(raw, object_pairs_hook=unique_object)
            if (not isinstance(value, dict) or set(value) != {'command_id'}
                    or not isinstance(value['command_id'], str)
                    or not 8 <= len(value['command_id']) <= 64):
                raise ValueError()
        except (ValueError, UnicodeError, RecursionError):
            raise MiniAppError(400, 'Некорректная команда') from None
        token = await chat_access(request, chat_id)
        async with store.authorized(token, write=True) as (session, user):
            chat, _ = await store.require_chat(session, user.id, chat_id)
            defaults = quiz_config.get('default_chat_settings') or {}
            settings_value = {**defaults, **(chat.settings or {})}
            classic = settings_value.get('quiz') or {}
            count = classic.get('num_questions', settings_value.get('default_num_questions', 5))
            seconds = classic.get('open_period_seconds', settings_value.get('default_open_period_seconds', 30))
            interval = classic.get('interval_seconds', settings_value.get('default_interval_seconds', 0))
            try:
                questions = await select_classic_questions(
                    session, chat_id=chat_id, count=count, defaults=defaults
                )
                if not questions:
                    raise ValueError('Не удалось подобрать вопросы. Проверьте настройки категорий.')
                return await ClassicApplicationService(
                    database, session, rules=scoring_rules
                ).start(
                    chat_id=chat_id, user_id=user.id,
                    display_name=user.display_name, questions=questions,
                    quiz_type='single' if len(questions) == 1 else 'session',
                    open_seconds=seconds, interval_seconds=interval,
                    command_id=value['command_id'],
                )
            except ClassicSessionConflict as error:
                raise MiniAppError(409, str(error)) from None
            except ValueError as error:
                raise MiniAppError(400, str(error)) from None

    @app.post('/api/mini/classic/chats/{chat_id}/sync')
    async def classic_sync(request: Request, chat_id: int):
        from application.classic import ClassicApplicationService
        if not runtime_enabled:
            raise MiniAppError(409, 'Игры в Mini App сейчас отключены')
        token = await chat_access(request, chat_id)
        async with store.authorized(token, write=True) as (session, user):
            await store.require_chat(session, user.id, chat_id)
            service = ClassicApplicationService(database, session, rules=scoring_rules)
            current = await service.settle_due(chat_id=chat_id, user_id=user.id)
            if current is None:
                current = await service.current(chat_id=chat_id, user_id=user.id)
            if current is None:
                raise MiniAppError(404, 'Активная викторина не найдена')
            return current

    @app.post('/api/mini/classic/chats/{chat_id}/stop')
    async def classic_stop(request: Request, chat_id: int):
        from application.classic import ClassicApplicationService
        if not runtime_enabled:
            raise MiniAppError(409, 'Игры в Mini App сейчас отключены')
        if request.headers.get('content-type', '').split(';')[0].strip() != 'application/json':
            raise MiniAppError(415, 'Ожидается JSON')
        raw = await request.body()
        if len(raw) > 300:
            raise MiniAppError(413, 'Команда слишком большая')
        try:
            value = json.loads(raw, object_pairs_hook=unique_object)
            if (not isinstance(value, dict)
                    or set(value) != {'command_id', 'expected_revision'}
                    or not isinstance(value['command_id'], str)
                    or not 8 <= len(value['command_id']) <= 64
                    or type(value['expected_revision']) is not int):
                raise ValueError()
        except (ValueError, UnicodeError, RecursionError):
            raise MiniAppError(400, 'Некорректная команда') from None
        token = await chat_access(request, chat_id)
        async with store.authorized(token, write=True) as (session, user):
            await store.require_chat(session, user.id, chat_id)
            try:
                return await ClassicApplicationService(
                    database, session, rules=scoring_rules
                ).stop(
                    chat_id=chat_id, user_id=user.id,
                    expected_revision=value['expected_revision'],
                    command_id=value['command_id'],
                )
            except LookupError as error:
                raise MiniAppError(404, str(error)) from None
            except PermissionError as error:
                raise MiniAppError(403, str(error)) from None
            except RuntimeError as error:
                raise MiniAppError(409, str(error)) from None
            except ValueError as error:
                raise MiniAppError(400, str(error)) from None

    @app.post('/api/mini/classic/chats/{chat_id}/answer')
    async def classic_answer(request: Request, chat_id: int):
        from application.classic import ClassicApplicationService
        from storage.classic_sessions import ClassicSessionConflict
        if not runtime_enabled:
            raise MiniAppError(409, 'Ответы в Mini App сейчас отключены')
        if request.headers.get('content-type', '').split(';')[0].strip() != 'application/json':
            raise MiniAppError(415, 'Ожидается JSON')
        raw = await request.body()
        if len(raw) > 500:
            raise MiniAppError(413, 'Ответ слишком большой')
        try:
            value = json.loads(raw, object_pairs_hook=unique_object)
            keys = set(value) if isinstance(value, dict) else set()
            id_keys = keys & {'poll_id', 'round_id'}
            if (not isinstance(value, dict)
                    or keys - {'poll_id', 'round_id', 'selected_option', 'command_id'}
                    or id_keys not in ({'poll_id'}, {'round_id'})
                    or 'selected_option' not in value
                    or not isinstance(value[next(iter(id_keys))], str)
                    or not 1 <= len(value[next(iter(id_keys))]) <= 255
                    or ('command_id' in value and (
                        not isinstance(value['command_id'], str)
                        or not 8 <= len(value['command_id']) <= 64
                    ))
                    or type(value['selected_option']) is not int):
                raise ValueError()
        except (ValueError, UnicodeError, RecursionError):
            raise MiniAppError(400, 'Некорректный ответ') from None
        token = await chat_access(request, chat_id)
        async with store.authorized(token, write=True) as (session, user):
            await store.require_chat(session, user.id, chat_id)
            try:
                return await ClassicApplicationService(database, session, rules=scoring_rules).answer(
                    chat_id=chat_id, user_id=user.id, display_name=user.display_name,
                    poll_id=value.get('poll_id'), round_id=value.get('round_id'),
                    selected_option=value['selected_option'],
                    command_id=value.get('command_id'))
            except LookupError as error:
                raise MiniAppError(404, str(error)) from None
            except ClassicSessionConflict as error:
                raise MiniAppError(409, str(error)) from None
            except ValueError as error:
                raise MiniAppError(400, str(error)) from None

    @app.post('/api/mini/photo/chats/{chat_id}/start')
    async def photo_start(request: Request, chat_id: int):
        from application.photo import PhotoApplicationService, PhotoGameConflict
        if not runtime_enabled:
            raise MiniAppError(409, 'Запуск игр в Mini App сейчас отключён')
        if request.headers.get('content-type', '').split(';')[0].strip() != 'application/json':
            raise MiniAppError(415, 'Ожидается JSON')
        raw = await request.body()
        if len(raw) > 500:
            raise MiniAppError(413, 'Команда слишком большая')
        try:
            value = json.loads(raw, object_pairs_hook=unique_object)
            if (not isinstance(value, dict) or set(value) - {
                    'command_id', 'question_count', 'open_seconds', 'hints_enabled'}
                    or set(value) < {'command_id'}
                    or not isinstance(value['command_id'], str)
                    or not 8 <= len(value['command_id']) <= 64
                    or type(value.get('question_count', 3)) is not int
                    or type(value.get('open_seconds', 60)) is not int
                    or type(value.get('hints_enabled', True)) is not bool):
                raise ValueError()
        except (ValueError, UnicodeError, RecursionError):
            raise MiniAppError(400, 'Некорректные параметры фото-игры') from None
        token = await chat_access(request, chat_id)
        async with store.authorized(token, write=True) as (session, user):
            await store.require_chat(session, user.id, chat_id)
            try:
                return await PhotoApplicationService(database, session).start(
                    chat_id=chat_id, user_id=user.id, display_name=user.display_name,
                    question_count=value.get('question_count', 3),
                    open_seconds=value.get('open_seconds', 60),
                    hints_enabled=value.get('hints_enabled', True),
                    command_id=value['command_id'],
                )
            except PhotoGameConflict as error:
                raise MiniAppError(409, str(error)) from None
            except LookupError as error:
                raise MiniAppError(409, str(error)) from None
            except ValueError as error:
                raise MiniAppError(400, str(error)) from None

    @app.get('/api/mini/photo/chats/{chat_id}/current')
    async def photo_current(request: Request, chat_id: int):
        from application.photo import PhotoApplicationService
        if not -(2**52) < chat_id < 2**52 or chat_id == 0:
            raise MiniAppError(404, 'Чат недоступен')
        token = await chat_access(request, chat_id)
        async with store.authorized(token, write=True) as (session, user):
            await store.require_chat(session, user.id, chat_id)
            service = PhotoApplicationService(database, session)
            current = await service.settle_due(chat_id=chat_id, user_id=user.id)
            if current is None:
                current = await service.current(chat_id=chat_id, user_id=user.id)
            if current is None:
                raise MiniAppError(404, 'Активная фото-викторина не найдена')
            return current

    @app.post('/api/mini/photo/chats/{chat_id}/answer')
    async def photo_answer(request: Request, chat_id: int):
        from application.photo import PhotoApplicationService, PhotoGameConflict
        if not runtime_enabled:
            raise MiniAppError(409, 'Ответы в Mini App сейчас отключены')
        if request.headers.get('content-type', '').split(';')[0].strip() != 'application/json':
            raise MiniAppError(415, 'Ожидается JSON')
        raw = await request.body()
        if len(raw) > 1000:
            raise MiniAppError(413, 'Ответ слишком большой')
        try:
            value = json.loads(raw, object_pairs_hook=unique_object)
            if (not isinstance(value, dict)
                    or set(value) != {'round_id', 'answer', 'command_id'}
                    or not isinstance(value['round_id'], str)
                    or not 1 <= len(value['round_id']) <= 64
                    or not isinstance(value['answer'], str)
                    or not 1 <= len(value['answer'].strip()) <= 300
                    or not isinstance(value['command_id'], str)
                    or not 8 <= len(value['command_id']) <= 64):
                raise ValueError()
        except (ValueError, UnicodeError, RecursionError):
            raise MiniAppError(400, 'Некорректный ответ') from None
        token = await chat_access(request, chat_id)
        async with store.authorized(token, write=True) as (session, user):
            await store.require_chat(session, user.id, chat_id)
            try:
                return await PhotoApplicationService(database, session).answer(
                    chat_id=chat_id, user_id=user.id, display_name=user.display_name,
                    round_id=value['round_id'], answer=value['answer'],
                    command_id=value['command_id'],
                )
            except LookupError as error:
                raise MiniAppError(404, str(error)) from None
            except PermissionError as error:
                raise MiniAppError(403, str(error)) from None
            except PhotoGameConflict as error:
                raise MiniAppError(409, str(error)) from None
            except RuntimeError as error:
                raise MiniAppError(409, str(error)) from None
            except ValueError as error:
                raise MiniAppError(400, str(error)) from None

    @app.post('/api/mini/photo/chats/{chat_id}/stop')
    async def photo_stop(request: Request, chat_id: int):
        from application.photo import PhotoApplicationService
        if not runtime_enabled:
            raise MiniAppError(409, 'Игры в Mini App сейчас отключены')
        if request.headers.get('content-type', '').split(';')[0].strip() != 'application/json':
            raise MiniAppError(415, 'Ожидается JSON')
        raw = await request.body()
        if len(raw) > 300:
            raise MiniAppError(413, 'Команда слишком большая')
        try:
            value = json.loads(raw, object_pairs_hook=unique_object)
            if (not isinstance(value, dict) or set(value) != {'command_id', 'expected_revision'}
                    or not isinstance(value['command_id'], str)
                    or not 8 <= len(value['command_id']) <= 64
                    or type(value['expected_revision']) is not int):
                raise ValueError()
        except (ValueError, UnicodeError, RecursionError):
            raise MiniAppError(400, 'Некорректная команда') from None
        token = await chat_access(request, chat_id)
        async with store.authorized(token, write=True) as (session, user):
            await store.require_chat(session, user.id, chat_id)
            try:
                return await PhotoApplicationService(database, session).stop(
                    chat_id=chat_id, user_id=user.id,
                    expected_revision=value['expected_revision'],
                    command_id=value['command_id'],
                )
            except LookupError as error:
                raise MiniAppError(404, str(error)) from None
            except PermissionError as error:
                raise MiniAppError(403, str(error)) from None
            except RuntimeError as error:
                raise MiniAppError(409, str(error)) from None
            except ValueError as error:
                raise MiniAppError(400, str(error)) from None

    @app.get('/api/mini/photo/chats/{chat_id}/current/image')
    async def photo_current_image(request: Request, chat_id: int):
        from application.photo import PhotoApplicationService
        if not -(2**52) < chat_id < 2**52 or chat_id == 0:
            raise MiniAppError(404, 'Чат недоступен')
        token = await chat_access(request, chat_id)
        async with store.authorized(token) as (session, user):
            await store.require_chat(session, user.id, chat_id)
            try:
                path = await PhotoApplicationService(database, session).image(chat_id=chat_id, user_id=user.id)
            except LookupError as error:
                raise MiniAppError(404, str(error)) from None
        return FileResponse(path, media_type='image/webp')

    mafia_prefix = 'mini_mafia_lobby:'

    def mafia_command_id(request: Request):
        value = request.headers.get('idempotency-key')
        if value is None:
            return None  # Compatibility for clients deployed before game_commands.
        if not re.fullmatch(r'[A-Za-z0-9._:-]{8,64}', value):
            raise MiniAppError(400, 'Некорректный идентификатор команды')
        return 'mini:' + value if len(value) <= 59 else value

    @app.get('/api/mini/mafia/draft')
    async def mafia_draft(request: Request):
        from domain.mafia import normalized_draft
        from storage.models import SystemState
        async with store.authorized(credential(request)) as (session, user):
            row = await session.get(SystemState, mafia_prefix + str(user.id))
            return normalized_draft(row.payload if row else None)

    @app.put('/api/mini/mafia/draft')
    async def save_mafia_draft(request: Request):
        from domain.mafia import update_draft
        from storage.models import SystemState
        if request.headers.get('content-type', '').split(';')[0].strip() != 'application/json':
            raise MiniAppError(415, 'Ожидается JSON')
        raw = await request.body()
        if len(raw) > 1000:
            raise MiniAppError(413, 'Черновик слишком большой')
        try:
            value = json.loads(raw, object_pairs_hook=unique_object)
            if not isinstance(value, dict) or set(value) != {'players', 'expected_revision'}:
                raise ValueError()
        except (ValueError, UnicodeError, RecursionError):
            raise MiniAppError(400, 'Некорректные параметры стола') from None
        async with store.authorized(credential(request), write=True) as (session, user):
            key = mafia_prefix + str(user.id)
            row = await session.get(SystemState, key, with_for_update=True)
            try:
                draft = update_draft(row.payload if row else None, players=value['players'],
                                     expected_revision=value['expected_revision'])
            except RuntimeError as error:
                raise MiniAppError(409, str(error)) from None
            except ValueError as error:
                raise MiniAppError(400, str(error)) from None
            if row is None:
                session.add(SystemState(key=key, payload=draft))
            else:
                row.payload = draft
            return draft

    async def mafia_chat_token(request: Request, chat_id: int):
        if not -(2**52) < chat_id < 0:
            raise MiniAppError(404, 'Для мафии нужен групповой чат.')
        return await chat_access(request, chat_id)

    @app.get('/api/mini/mafia/chats/{chat_id}/lobby')
    async def mafia_lobby(request: Request, chat_id: int):
        from application.mafia import MafiaApplicationService
        token = await mafia_chat_token(request, chat_id)
        async with store.authorized(token) as (session, user):
            return {'lobby': await MafiaApplicationService(session).lobby(
                chat_id=chat_id, viewer_id=user.id)}

    @app.post('/api/mini/mafia/chats/{chat_id}/lobby/join')
    async def join_mafia_lobby(request: Request, chat_id: int):
        from application.mafia import MafiaApplicationService
        token = await mafia_chat_token(request, chat_id)
        async with store.authorized(token, write=True) as (session, user):
            try:
                return await MafiaApplicationService(session).join(
                    chat_id=chat_id, user_id=user.id, name=user.display_name,
                    command_id=mafia_command_id(request))
            except ValueError as error:
                raise MiniAppError(409, str(error)) from None

    @app.post('/api/mini/mafia/chats/{chat_id}/lobby/ready')
    async def set_mafia_ready(request: Request, chat_id: int):
        from application.mafia import MafiaApplicationService
        if request.headers.get('content-type', '').split(';')[0].strip() != 'application/json':
            raise MiniAppError(415, 'Ожидается JSON')
        raw = await request.body()
        if len(raw) > 200:
            raise MiniAppError(413, 'Действие слишком большое')
        try:
            value = json.loads(raw, object_pairs_hook=unique_object)
            if not isinstance(value, dict) or set(value) != {'ready', 'expected_revision'}:
                raise ValueError()
        except (ValueError, UnicodeError, RecursionError):
            raise MiniAppError(400, 'Некорректная готовность') from None
        token = await mafia_chat_token(request, chat_id)
        async with store.authorized(token, write=True) as (session, user):
            try:
                lobby = await MafiaApplicationService(session).ready(
                    chat_id=chat_id, user_id=user.id, ready=value['ready'],
                    expected_revision=value['expected_revision'],
                    command_id=mafia_command_id(request))
            except LookupError as error:
                raise MiniAppError(404, str(error)) from None
            except PermissionError as error:
                raise MiniAppError(403, str(error)) from None
            except RuntimeError as error:
                raise MiniAppError(409, str(error)) from None
            except ValueError as error:
                raise MiniAppError(400, str(error)) from None
            return {'lobby': lobby}

    @app.post('/api/mini/mafia/chats/{chat_id}/lobby/start')
    async def start_mafia_lobby(request: Request, chat_id: int):
        from application.mafia import MafiaApplicationService
        if request.headers.get('content-type', '').split(';')[0].strip() != 'application/json':
            raise MiniAppError(415, 'Ожидается JSON')
        raw = await request.body()
        if len(raw) > 160:
            raise MiniAppError(413, 'Действие слишком большое')
        try:
            value = json.loads(raw, object_pairs_hook=unique_object)
            if not isinstance(value, dict) or set(value) != {'expected_revision'}:
                raise ValueError()
        except (ValueError, UnicodeError, RecursionError):
            raise MiniAppError(400, 'Некорректный запуск партии') from None
        token = await mafia_chat_token(request, chat_id)
        async with store.authorized(token, write=True) as (session, user):
            try:
                lobby = await MafiaApplicationService(session).start(
                    chat_id=chat_id, user_id=user.id,
                    expected_revision=value['expected_revision'],
                    command_id=mafia_command_id(request))
            except LookupError as error:
                raise MiniAppError(404, str(error)) from None
            except PermissionError as error:
                raise MiniAppError(403, str(error)) from None
            except RuntimeError as error:
                raise MiniAppError(409, str(error)) from None
            except ValueError as error:
                raise MiniAppError(400, str(error)) from None
            return {'lobby': lobby}

    @app.get('/api/mini/mafia/chats/{chat_id}/role')
    async def mafia_role(request: Request, chat_id: int):
        from application.mafia import MafiaApplicationService
        token = await mafia_chat_token(request, chat_id)
        async with store.authorized(token) as (session, user):
            try:
                role = await MafiaApplicationService(session).role(
                    chat_id=chat_id, user_id=user.id)
            except PermissionError as error:
                raise MiniAppError(403, str(error)) from None
            if role is None:
                raise MiniAppError(409, 'Роль появится после начала ночи.')
            return role

    async def mafia_game_body(request, *, target=False):
        if request.headers.get('content-type', '').split(';')[0].strip() != 'application/json':
            raise MiniAppError(415, 'Ожидается JSON')
        raw = await request.body()
        if len(raw) > 240:
            raise MiniAppError(413, 'Действие слишком большое')
        try:
            value = json.loads(raw, object_pairs_hook=unique_object)
            keys = {'expected_revision', 'target'} if target else {'expected_revision'}
            if (not isinstance(value, dict) or set(value) != keys
                    or type(value['expected_revision']) is not int or value['expected_revision'] < 0
                    or (target and (not isinstance(value['target'], str)
                                    or not re.fullmatch(r'p(?:[1-9]|1[0-2])', value['target'])))):
                raise ValueError()
            return value
        except (ValueError, UnicodeError, RecursionError):
            raise MiniAppError(400, 'Некорректное действие партии') from None

    async def mafia_game_command(request, chat_id, method, *, target=False):
        from application.mafia import MafiaApplicationService
        value = await mafia_game_body(request, target=target)
        token = await mafia_chat_token(request, chat_id)
        async with store.authorized(token, write=True) as (session, user):
            try:
                arguments = dict(chat_id=chat_id, user_id=user.id,
                                 expected_revision=value['expected_revision'],
                                 command_id=mafia_command_id(request))
                if target:
                    arguments['target_seat'] = value['target']
                return await getattr(MafiaApplicationService(session), method)(**arguments)
            except LookupError as error:
                raise MiniAppError(404, str(error)) from None
            except PermissionError as error:
                raise MiniAppError(403, str(error)) from None
            except RuntimeError as error:
                raise MiniAppError(409, str(error)) from None
            except ValueError as error:
                raise MiniAppError(400, str(error)) from None

    @app.post('/api/mini/mafia/chats/{chat_id}/action')
    async def mafia_action(request: Request, chat_id: int):
        return await mafia_game_command(request, chat_id, 'action', target=True)

    @app.post('/api/mini/mafia/chats/{chat_id}/vote')
    async def mafia_vote(request: Request, chat_id: int):
        return await mafia_game_command(request, chat_id, 'vote', target=True)

    @app.post('/api/mini/mafia/chats/{chat_id}/advance')
    async def mafia_advance(request: Request, chat_id: int):
        return await mafia_game_command(request, chat_id, 'advance')

    @app.post('/api/mini/mafia/chats/{chat_id}/restart')
    async def mafia_restart(request: Request, chat_id: int):
        return await mafia_game_command(request, chat_id, 'restart')

    if runtime_enabled:
        from storage.mini_bridge import MiniBridge

        @app.get('/api/mini/runtime')
        async def runtime_view(request: Request):
            async with store.authorized(credential(request)) as (session, user):
                return await MiniBridge(database, store.bot_key_id, user.id, clock=clock).snapshot(session)

        @app.post('/api/mini/runtime/actions')
        async def runtime_action(request: Request):
            if request.headers.get('content-type', '').split(';')[0].strip() != 'application/json':
                raise MiniAppError(415, 'Ожидается JSON')
            raw = bytearray()
            async for chunk in request.stream():
                raw.extend(chunk)
                if len(raw) > 4000:
                    raise MiniAppError(413, 'Действие слишком большое')
            try:
                action = json.loads(raw, object_pairs_hook=unique_object)
                if not isinstance(action, dict):
                    raise ValueError()
            except (ValueError, UnicodeError, RecursionError):
                raise MiniAppError(400, 'Некорректное действие') from None
            async with store.authorized(credential(request), write=True) as (session, user):
                from storage.admin_actions import access_allowed_in
                if not await access_allowed_in(session, user.id, user.id):
                    raise MiniAppError(403, 'Игры сейчас недоступны')
                return await MiniBridge(database, store.bot_key_id, user.id, clock=clock).enqueue(session, action)

        @app.get('/api/mini/runtime/media/{message_id}')
        async def runtime_media(request: Request, message_id: int):
            from storage.photo_media import images_root
            async with store.authorized(credential(request)) as (session, user):
                name = await MiniBridge(database, store.bot_key_id, user.id, clock=clock).media_name(session, message_id)
                root = images_root()
                path = (root / name).resolve()
                if path.parent != root or path.suffix.lower() not in {'.webp', '.jpg', '.jpeg', '.png'} or not path.is_file():
                    raise MiniAppError(404, 'Изображение недоступно')
                return FileResponse(path)

    return app
