"""Private-chat live dev runner. Never imports bot.main or reads production data."""
import argparse
import asyncio
from collections import defaultdict
import json
import logging
import os
from pathlib import Path
import sys

WORKSPACE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKSPACE))

IN_DEV_CONTAINER = os.getenv('MQB_DEV_CONTAINER') == '1' and Path('/.dockerenv').is_file()
DEV_URL = ('postgresql+asyncpg://mqb_dev:local-development-only@postgres:5432/morning_quiz_dev'
           if IN_DEV_CONTAINER else
           'postgresql+asyncpg://mqb_dev:local-development-only@127.0.0.1:55433/morning_quiz_dev')
PORT = 4186


def configure_environment(workspace, token_file):
    from dotenv import dotenv_values
    workspace = workspace.resolve()
    if not IN_DEV_CONTAINER and (str(workspace).startswith('\\\\') or workspace.drive != 'C:'):
        raise ValueError('The test runner requires the local Windows dev copy')
    if IN_DEV_CONTAINER:
        values = os.environ
    else:
        path = (workspace / token_file).resolve()
        if path.parent != workspace or path.name not in {'.env', '.env.telegram-test'}:
            raise ValueError('Use only the explicitly selected local .env or .env.telegram-test')
        values = dotenv_values(path, interpolate=False)
    dedicated = (values.get('TELEGRAM_TEST_BOT_TOKEN') or '').strip()
    regular = (values.get('BOT_TOKEN') or '').strip()
    if dedicated and regular and dedicated != regular:
        raise ValueError('Conflicting bot token variables in the selected file')
    token = dedicated or regular
    if not token:
        raise ValueError('No test bot token in the selected local file')
    proxy = (values.get('TELEGRAM_PROXY_URL') or values.get('TELEGRAM_PROXY') or '').strip() or None
    # Do not import the rest of .env. Hard-coded dev storage overrides all inherited values.
    os.environ.update(
        PYTHON_DOTENV_DISABLED='1', STORAGE_BACKEND='postgres', DATABASE_URL=DEV_URL,
        DATABASE_ECHO='0', TEST_DATABASE_URL='', BOT_TOKEN=token, MODE='testing',
        TELEGRAM_PROXY_URL=proxy or '', TELEGRAM_PROXY='',
        OPENROUTER_API_KEY='', ANTHROPIC_API_KEY='', SENTRY_DSN='', MINI_APP_URL='',
        MQB_ADMIN_AI_ENABLED='0', MQB_DEV_RUNTIME='telegram-private', PTB_TIMEDELTA='1',
        PHOTO_IMAGES_DIR=str(workspace / '.local' / 'preview' / 'images'),
    )
    return token, proxy


def install_error_logging(scope, token):
    class SafeErrors(logging.Handler):
        def emit(self, record):
            if record.levelno >= logging.WARNING:
                # Do not retain raw exceptions/URLs, user text, or HTTP request bodies.
                scope.event('runtime_log', source=record.name, level=record.levelname,
                            exception=type(record.exc_info[1]).__name__ if record.exc_info else None)
    logging.basicConfig(level=logging.WARNING, handlers=[SafeErrors()], force=True)
    logging.getLogger('httpx').setLevel(logging.CRITICAL)
    logging.getLogger('httpcore').setLevel(logging.CRITICAL)


async def build_application(database, scope, token, proxy, *, request_factory=None):
    from telegram.ext import Application, Defaults, DictPersistence, PersistenceInput
    from telegram.request import HTTPXRequest
    from app_config import AppConfig
    from state import BotState
    from data_manager import DataManager
    from storage.question_bank import PostgresQuestionBank
    from storage.runtime import PostgresRuntimeStorage
    from modules.category_manager import CategoryManager
    from modules.score_manager import ScoreManager
    from modules.photo_quiz_manager import PhotoQuizManager
    from modules.telegram_test_scope import ScopedRequest
    from handlers.quiz_manager import QuizManager
    from handlers.rating_handlers import RatingHandlers
    from handlers.common_handlers import CommonHandlers
    from handlers.config_handlers import ConfigHandlers
    from handlers.photo_quiz_handlers import PhotoQuizHandlers
    from handlers.mafia_handlers import MafiaHandlers
    from handlers.poll_answer_handler import CustomPollAnswerHandler
    from handlers.moderation import moderation_handler
    from telegram.ext import ApplicationHandlerStop, TypeHandler
    from telegram import Update

    config = AppConfig()
    config.disable_external_ai = True
    state = BotState(config)
    dm = DataManager(config, state, data_root=WORKSPACE / '.local' / 'preview')
    dm.attach_postgres_storage(PostgresRuntimeStorage(database))
    # A disposable private-test database starts empty. Seed the explicit local
    # fixture once, then serve and mutate the bank exclusively through PostgreSQL.
    await PostgresQuestionBank(database).seed_from_directory(
        dm.questions_dir, metadata_path=dm.global_dir / 'categories.json'
    )
    await dm.load_questions_async()
    active = await dm.postgres_storage.load_into_state(state)
    # No background jobs or recovery for the synthetic panel chat / other dev chats.
    state.chat_settings = {k: v for k, v in state.chat_settings.items() if k == scope.chat_id}
    state.chat_settings_revisions = {k: v for k, v in state.chat_settings_revisions.items() if k == scope.chat_id}
    state.user_scores = {k: v for k, v in state.user_scores.items() if k == scope.chat_id}
    state.generic_messages_to_delete = defaultdict(dict, {
        k: v for k, v in state.generic_messages_to_delete.items() if k == scope.chat_id})
    dm.set_postgres_active_quizzes_cache({k: v for k, v in active.items() if k == scope.chat_id})
    state.data_manager = dm
    categories = CategoryManager(state, config, dm)
    dm.category_manager = categories
    scores = ScoreManager(config, state, dm)
    photos = PhotoQuizManager(dm, scores)
    def request():
        inner = request_factory() if request_factory else HTTPXRequest(proxy=proxy, connect_timeout=10, read_timeout=30,
            httpx_kwargs={'trust_env': False, 'follow_redirects': False})
        return ScopedRequest(inner, scope, token)
    app = (Application.builder().token(token).updater(None).request(request()).get_updates_request(request())
           .defaults(Defaults(parse_mode='MarkdownV2'))
           .persistence(DictPersistence(store_data=PersistenceInput(bot_data=False)))
           .concurrent_updates(False).build())
    state.application = app
    quiz = QuizManager(config, state, categories, scores, dm, app)
    rating = RatingHandlers(config, scores)
    common = CommonHandlers(config, categories, state)
    settings = ConfigHandlers(config, dm, categories, app)
    app.bot_data.update(bot_state=state, app_config=config, data_manager=dm, telegram_private_test=True,
                        quiz_manager=quiz, rating_handlers=rating, common_handlers=common)
    async def private_gate(update, context):
        if not scope.accepts(update):
            raise ApplicationHandlerStop
    app.add_handler(TypeHandler(Update, private_gate), group=-200)
    app.add_handler(moderation_handler(database), group=-100)
    from modules.telegram_menu import navigation_guard
    app.add_handler(navigation_guard(), group=-90)
    game_runtime = MafiaHandlers(database)
    app.bot_data['game_runtime'] = game_runtime
    for owner in (quiz, rating, common, settings, PhotoQuizHandlers(photos), game_runtime):
        app.add_handlers(owner.get_handlers())
    app.add_handler(CustomPollAnswerHandler(config, state, scores, dm, quiz).get_handler())
    async def error(update, context):
        scope.event('handler_error', exception=type(context.error).__name__)
        from modules.mini_bridge_worker import active_mini_action
        intent = active_mini_action.get()
        if intent is not None:
            intent['error'] = 'Бот не смог выполнить действие. Проверьте состояние и попробуйте снова.'
    app.add_error_handler(error)
    return app, config, quiz, photos, dm


async def dispatch(app, config, scope, update):
    if not scope.accepts(update):
        scope.event('ignored_update')
        return
    if update.message:
        body = update.message.text or ''
        command = body.split(maxsplit=1)[0].split('@', 1)[0].lower() if body else ''
        if command in {'/reloadcfg', '/backup', '/restore', '/deletebackup', '/maintenance',
                       '/adddailyquiz', '/removedailyquiz', '/dailywisdom'}:
            await update.message.reply_text('В этом тестовом запуске доступны ручные игры. Системные операции — в локальной dev-панели.', parse_mode=None)
            return
    kind = 'callback' if update.callback_query else 'poll_answer' if update.poll_answer else 'message'
    scope.event('accepted_update', kind=kind)
    await app.process_update(update)
    # The private dev runner acknowledges transactionally queued effects before
    # returning control to tests/the local bridge. Periodic deadlines remain the
    # fallback for time-based transitions and process restarts.
    from telegram.ext import CallbackContext
    game_runtime = app.bot_data.get('game_runtime')
    if game_runtime is not None:
        await game_runtime.deadline_job(CallbackContext(app))


async def run(args):
    from modules.telegram_test_scope import PrivateTestScope
    scope = PrivateTestScope(args.chat_id, args.expected_bot_id)
    token, proxy = configure_environment(WORKSPACE, args.token_file)
    if args.mini_app_url:
        os.environ['MINI_APP_URL'] = args.mini_app_url
        from modules.mini_app_launch import configured_url
        configured_url()
    if token.split(':', 1)[0] != str(args.expected_bot_id):
        raise ValueError('Token does not match the explicitly expected test bot ID')
    install_error_logging(scope, token)
    from storage.database import Database, DatabaseSettings
    from storage.dev_backups import guard
    from telegram import BotCommand, BotCommandScopeChat
    from telegram.error import Conflict, NetworkError, RetryAfter
    database = Database(DatabaseSettings.from_env())
    await asyncio.to_thread(guard, database)
    await database.check_connection()
    from storage.startup import require_current_schema
    await require_current_schema(database)
    stop_path = WORKSPACE / '.local' / 'telegram-test.stop'
    status = {'running': False, 'pid': os.getpid(), 'mode': 'telegram-private',
              'chat_id': scope.chat_id, 'bot_id': scope.bot_id, 'database': 'morning_quiz_dev',
              'automatic_schedules': False, 'telegram_delivery': True}
    async def health(reader, writer):
        try:
            line = await asyncio.wait_for(reader.readline(), timeout=2)
            # Read-only loopback status endpoint; no credentials or update contents.
            if line.startswith(b'GET /health '):
                body = json.dumps({**status, 'events': list(scope.events)}, ensure_ascii=True).encode()
                writer.write(b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nCache-Control: no-store\r\nConnection: close\r\nContent-Length: ' + str(len(body)).encode() + b'\r\n\r\n' + body)
            else:
                writer.write(b'HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
            await writer.drain()
        except (OSError, asyncio.TimeoutError, ValueError):
            pass
        finally:
            writer.close()
            await writer.wait_closed()
    # Also prevents a second local polling process before any Telegram request.
    server = await asyncio.start_server(health, '0.0.0.0' if IN_DEV_CONTAINER else '127.0.0.1', PORT, limit=8192)
    if stop_path.exists():
        stop_path.unlink()
    app = photos = dm = mini_worker = None
    from hashlib import sha256
    from storage.mini_bridge import MiniBridge
    from modules.mini_bridge_worker import run_worker
    scope.mini_bridge = MiniBridge(database, sha256(token.encode()).hexdigest(), scope.chat_id)
    dispatch_lock = asyncio.Lock()
    try:
        app, config, quiz, photos, dm = await build_application(database, scope, token, proxy)
        await app.initialize()
        if app.bot.id != scope.bot_id:
            raise ValueError('Telegram returned a different bot identity')
        hook = await app.bot.get_webhook_info()
        if hook.url:
            raise ValueError('Existing webhook detected: left untouched; polling not started')
        await app.start()
        app.bot_data['game_runtime'].install_deadlines(app.job_queue)
        # Only this private chat receives a command menu; the global bot menu is untouched.
        await app.bot.set_my_commands([
            BotCommand('start', 'Главное меню'), BotCommand('quiz', 'Начать квиз'),
            BotCommand('photo_quiz', 'Фото-квиз'), BotCommand('mafia', 'Ночной город'),
            BotCommand('mystats', 'Мои результаты'),
            BotCommand('top', 'Рейтинг'), BotCommand('adminsettings', 'Настройки'),
            BotCommand('stopquiz', 'Остановить квиз'), BotCommand('cancel', 'Отменить диалог'),
        ], scope=BotCommandScopeChat(scope.chat_id))
        from telegram import MenuButtonCommands, MenuButtonWebApp, WebAppInfo
        if args.mini_app_url:
            await app.bot.set_chat_menu_button(chat_id=scope.chat_id,
                menu_button=MenuButtonWebApp('Morning Quiz', WebAppInfo(args.mini_app_url)))
        else:
            # A restart without a public URL also removes an expired test-tunnel menu.
            await app.bot.set_chat_menu_button(chat_id=scope.chat_id, menu_button=MenuButtonCommands())
        installed_menu = await app.bot.get_chat_menu_button(chat_id=scope.chat_id)
        if args.mini_app_url:
            if not isinstance(installed_menu, MenuButtonWebApp) or installed_menu.web_app.url != args.mini_app_url:
                raise RuntimeError('Telegram Mini App menu verification failed')
        elif not isinstance(installed_menu, MenuButtonCommands):
            raise RuntimeError('Telegram command menu verification failed')
        scope.event('chat_menu_verified', mini_app=bool(args.mini_app_url))
        # Classic checkpoints are already narrowed to the authorized chat.
        await quiz.restore_all_active_quizzes()
        scope.poll_ids.update(poll_id for poll_id, poll in app.bot_data['bot_state'].current_polls.items()
                              if poll.get('chat_id') == scope.chat_id)
        from telegram.ext import CallbackContext
        await photos.restore_sessions(CallbackContext(app), chat_id=scope.chat_id)
        quiz.schedule_quiz_auto_save()
        status.update(running=True, username=app.bot.username)
        print(json.dumps(status), flush=True)
        if args.show_menu:
            # Operator-requested refresh, not a fabricated incoming Telegram update.
            from datetime import datetime, timezone
            from telegram import Message, Update, User
            from modules.telegram_menu import home
            chat = await app.bot.get_chat(scope.chat_id)
            user = User(scope.chat_id, chat.first_name or 'Игрок', False, last_name=chat.last_name)
            message = Message(0, datetime.now(timezone.utc), chat, from_user=user)
            message.set_bot(app.bot)
            refresh = Update(0, message=message)
            refresh.set_bot(app.bot)
            await home(refresh, CallbackContext.from_update(refresh, app))
            scope.event('operator_menu_refresh')
        scope.event('polling_started')
        mini_worker = asyncio.create_task(run_worker(scope.mini_bridge, app, photos, scope, dispatch_lock))
        offset = None
        while not stop_path.exists():
            try:
                updates = await app.bot.get_updates(offset=offset, timeout=15, limit=100,
                    allowed_updates=['message', 'callback_query', 'poll_answer'])
                for update in updates:
                    async with dispatch_lock:
                        await dispatch(app, config, scope, update)
                    offset = update.update_id + 1
                await dm.flush_postgres_writes()
            except Conflict:
                scope.event('polling_conflict_stopping')
                raise RuntimeError('Another consumer is using the test bot; this runner is stopping') from None
            except RetryAfter as exc:
                delay = exc.retry_after.total_seconds() if hasattr(exc.retry_after, 'total_seconds') else exc.retry_after
                scope.event('telegram_rate_limit')
                for _ in range(max(1, int(delay) + 1)):
                    if stop_path.exists():
                        break
                    await asyncio.sleep(1)
            except NetworkError:
                scope.event('telegram_network_retry')
                await asyncio.sleep(3)
    finally:
        status['running'] = False
        if mini_worker:
            mini_worker.cancel()
            await asyncio.gather(mini_worker, return_exceptions=True)
        if photos:
            await photos.shutdown()
        if app:
            if app.running:
                await app.stop()
            if dm:
                await dm.flush_postgres_writes()
            await app.shutdown()
        await database.dispose()
        server.close()
        await server.wait_closed()
        print(json.dumps({'event': 'telegram_test_stopped'}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--chat-id', type=int, required=True)
    parser.add_argument('--expected-bot-id', type=int, required=True)
    parser.add_argument('--token-file', choices=['.env', '.env.telegram-test'], required=True)
    parser.add_argument('--mini-app-url', default='')
    parser.add_argument('--show-menu', action='store_true')
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        # No raw Telegram exception: URLs may embed the token.
        print(json.dumps({'event': 'telegram_test_failed', 'error_type': type(exc).__name__}), flush=True)
        sys.exit(1)
