"""Explicit local PTB runtime. Real handlers/jobs, synthetic Telegram transport only."""
import asyncio
from collections import deque
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
from uuid import uuid4
from urllib.parse import quote

from telegram import Update
from telegram.ext import Application, CallbackContext, Defaults, DictPersistence, PersistenceInput
from telegram.request import BaseRequest

CHAT = -900000000091
USER = 900000000091
TOKEN = '123456:LOCAL_TEST_ONLY_012345678901234567890'
BOT = {'id': 123456, 'is_bot': True, 'first_name': 'Сова · DEV', 'username': 'MorningQuizLocalDevBot'}
PLAYER = {'id': USER, 'is_bot': False, 'first_name': 'Тестовый игрок'}
ROOM = {'id': CHAT, 'type': 'supergroup', 'title': 'Тестовый чат'}


class OfflineRequest(BaseRequest):
    def __init__(self, runtime):
        self.runtime = runtime

    @property
    def read_timeout(self):
        return 10

    async def initialize(self):
        pass

    async def shutdown(self):
        pass

    async def do_request(self, url, method, request_data=None, **kwargs):
        name = url.rsplit('/', 1)[-1]
        params = request_data.parameters if request_data else {}
        chat_id = getattr(self.runtime, 'chat_id', CHAT)
        room = getattr(self.runtime, 'room', ROOM)
        player = getattr(self.runtime, 'player', PLAYER)
        self.runtime.calls += 1
        if 'chat_id' in params and str(params['chat_id']) != str(chat_id):
            return 400, json.dumps({'ok': False, 'error_code': 400, 'description': 'Offline transport: only the synthetic chat is allowed'}).encode()
        result = True
        if name == 'getMe':
            result = BOT
        elif name == 'getChat':
            result = {**room, 'accent_color_id': 0}
        elif name == 'getChatMember':
            result = {'status': 'creator', 'user': player, 'is_anonymous': False}
        elif name == 'getChatAdministrators':
            result = [{'status': 'creator', 'user': player, 'is_anonymous': False}]
        elif name == 'getChatMemberCount':
            result = 1
        elif name in {'sendMessage', 'sendPhoto', 'sendPoll', 'editMessageText', 'editMessageCaption', 'editMessageReplyMarkup'}:
            message_id = params.get('message_id') or self.runtime.next_id()
            previous = self.runtime.messages.get(message_id, {})
            result = {**previous, 'message_id': message_id, 'date': int(time.time()), 'chat': room, 'from': BOT}
            for field in ('text', 'caption', 'reply_markup'):
                if field in params:
                    result[field] = params[field]
            if name == 'sendPhoto':
                result['photo'] = [{'file_id': 'offline', 'file_unique_id': 'offline', 'width': 640, 'height': 640}]
                for upload in (request_data.multipart_data or {}).values():
                    filename = Path(str(upload[0])).name
                    if filename.endswith('.webp'):
                        result['offline_photo_url'] = '/api/images/' + quote(filename)
                        break
            if name == 'sendPoll':
                result['poll'] = {'id': 'offline-' + uuid4().hex, 'question': params['question'],
                    'options': [{'text': option if isinstance(option, str) else option['text'], 'voter_count': 0, 'persistent_id': f'offline-option-{index}'} for index, option in enumerate(params['options'])],
                    'total_voter_count': 0, 'is_closed': False, 'is_anonymous': False,
                    'type': 'quiz', 'allows_multiple_answers': False, 'members_only': False, 'allows_revoting': False,
                    'correct_option_ids': params.get('correct_option_ids', [])}
            self.runtime.messages[message_id] = result
            while len(self.runtime.messages) > 100:
                del self.runtime.messages[next(iter(self.runtime.messages))]
        elif name == 'stopPoll':
            result = dict(self.runtime.messages.get(params.get('message_id'), {}).get('poll') or {
                'id': 'offline-closed', 'question': 'Завершённый вопрос', 'options': [], 'total_voter_count': 0,
                'is_anonymous': False, 'type': 'quiz', 'allows_multiple_answers': False, 'members_only': False, 'allows_revoting': False})
            result['is_closed'] = True
            if params.get('message_id') in self.runtime.messages:
                self.runtime.messages[params['message_id']]['poll'] = result
        elif name == 'deleteMessage':
            self.runtime.messages.pop(params.get('message_id'), None)
        elif name not in {'answerCallbackQuery', 'setMyCommands', 'deleteMyCommands', 'setChatMenuButton', 'sendChatAction'}:
            return 400, json.dumps({'ok': False, 'error_code': 400, 'description': f'Offline method not implemented: {name}'}).encode()
        self.runtime.events.append({'at': datetime.now(timezone.utc).isoformat(), 'event': name})
        return 200, json.dumps({'ok': True, 'result': result}, ensure_ascii=False).encode()


class DevRuntime:
    def __init__(self, database):
        self.database = database
        self.application = None
        self.messages = {}
        self.events = deque(maxlen=100)
        self.calls = 0
        self.counter = int(time.time())
        self.started_at = None
        self.lock = asyncio.Lock()
        self.components = None
        self.game_runtime = None

    def next_id(self):
        self.counter += 1
        return self.counter

    async def start(self):
        async with self.lock:
            if self.application:
                return self.status()
            if os.getenv('MQB_DEV_RUNTIME') != 'offline' or os.getenv('BOT_TOKEN'):
                raise ValueError('Автономный бот разрешён только в специальном локальном preview без BOT_TOKEN')
            from storage.dev_backups import guard, WORKSPACE
            await asyncio.to_thread(guard, self.database)
            from app_config import AppConfig
            from state import BotState
            from data_manager import DataManager
            from storage.question_bank import PostgresQuestionBank
            from storage.runtime import PostgresRuntimeStorage
            from modules.category_manager import CategoryManager
            from modules.score_manager import ScoreManager
            from modules.photo_quiz_manager import PhotoQuizManager
            from handlers.quiz_manager import QuizManager
            from handlers.rating_handlers import RatingHandlers
            from handlers.common_handlers import CommonHandlers
            from handlers.config_handlers import ConfigHandlers
            from handlers.photo_quiz_handlers import PhotoQuizHandlers
            from handlers.mafia_handlers import MafiaHandlers
            from handlers.poll_answer_handler import CustomPollAnswerHandler
            from handlers.daily_quiz_scheduler import DailyQuizScheduler
            from handlers.wisdom_scheduler import WisdomScheduler
            from handlers.moderation import moderation_handler
            from handlers.cleanup_handler import schedule_cleanup_job
            from modules.schedule_sync import ScheduleSync
            config = AppConfig()
            config.disable_external_ai = True
            state = BotState(config)
            dm = DataManager(config, state, data_root=WORKSPACE / '.local' / 'preview')
            dm.attach_postgres_storage(PostgresRuntimeStorage(self.database))
            # The offline runtime may be pointed at a brand-new disposable database.
            # Import its explicit preview fixture once; PostgreSQL remains the only
            # source read by DataManager after this bootstrap transaction.
            await PostgresQuestionBank(self.database).seed_from_directory(
                dm.questions_dir, metadata_path=dm.global_dir / 'categories.json'
            )
            await dm.load_questions_async()
            dm.set_postgres_active_quizzes_cache(await dm.postgres_storage.load_into_state(state))
            state.data_manager = dm
            categories = CategoryManager(state, config, dm)
            dm.category_manager = categories
            scores = ScoreManager(config, state, dm)
            photos = PhotoQuizManager(dm, scores)
            app = (Application.builder().token(TOKEN).updater(None).request(OfflineRequest(self))
                   .get_updates_request(OfflineRequest(self)).defaults(Defaults(parse_mode='MarkdownV2'))
                   .persistence(DictPersistence(store_data=PersistenceInput(bot_data=False)))
                   .concurrent_updates(False).build())
            state.application = app
            app.bot_data.update(bot_state=state, app_config=config, data_manager=dm)
            quiz = QuizManager(config, state, categories, scores, dm, app)
            common = CommonHandlers(config, categories, state)
            settings = ConfigHandlers(config, dm, categories, app)
            daily = DailyQuizScheduler(config, state, dm, quiz, app)
            wisdom = WisdomScheduler(config, dm, state, app, categories)
            settings.set_daily_quiz_scheduler(daily)
            settings.set_wisdom_scheduler(wisdom)
            app.bot_data.update(daily_quiz_scheduler=daily, wisdom_scheduler=wisdom)
            app.add_handler(moderation_handler(self.database), group=-100)
            from modules.telegram_menu import navigation_guard
            app.add_handler(navigation_guard(), group=-90)
            mafia = MafiaHandlers(self.database)
            for owner in (quiz, RatingHandlers(config, scores), common, settings,
                          PhotoQuizHandlers(photos), mafia):
                app.add_handlers(owner.get_handlers())
            app.add_handler(CustomPollAnswerHandler(config, state, scores, dm, quiz).get_handler())
            async def error(update, context):
                self.events.append({'at': datetime.now(timezone.utc).isoformat(), 'event': 'handler_error',
                                    'error': type(context.error).__name__})
            app.add_error_handler(error)
            try:
                await app.initialize()
                await quiz.restore_all_active_quizzes()
                sync = ScheduleSync(self.database, config, daily, wisdom)
                dm.schedule_sync = sync
                app.bot_data['schedule_sync'] = sync
                await sync.run_once()
                sync.install(app.job_queue)
                schedule_cleanup_job(app.job_queue, state)
                mafia.install_notification_delivery(app.job_queue)
                quiz.schedule_quiz_auto_save()
                wisdom.start()
                await app.start()
            except Exception:
                await photos.shutdown()
                if wisdom.scheduler.running:
                    wisdom.scheduler.shutdown(wait=False)
                if app.running:
                    await app.stop()
                await app.shutdown()
                raise
            self.application = app
            self.components = (quiz, photos, wisdom, dm)
            self.game_runtime = mafia
            self.started_at = datetime.now(timezone.utc).isoformat()
            self.events.append({'at': self.started_at, 'event': 'offline_runtime_started'})
            return self.status()

    async def stop(self):
        async with self.lock:
            if self.application:
                app = self.application
                quiz, photos, wisdom, dm = self.components
                await photos.shutdown()
                if wisdom.scheduler.running:
                    wisdom.scheduler.shutdown(wait=False)
                await app.stop()
                await dm.flush_postgres_writes()
                await app.shutdown()
                self.application = None
                self.game_runtime = None
                self.events.append({'at': datetime.now(timezone.utc).isoformat(), 'event': 'offline_runtime_stopped'})
            return self.status()

    def status(self):
        app = self.application
        jobs = []
        if app:
            jobs = [{'name': j.name, 'next_run': str(getattr(j, 'next_t', None))} for j in app.job_queue.jobs()]
            jobs.extend({'name': j.name, 'next_run': str(j.next_run_time)} for j in self.components[2].scheduler.get_jobs())
        return {'running': bool(app and app.running), 'mode': 'offline', 'telegram_delivery': False,
                'started_at': self.started_at, 'api_calls_simulated': self.calls, 'jobs': jobs,
                'chat_id': str(CHAT), 'messages': list(self.messages.values()), 'events': list(self.events)}

    async def input(self, *, message=None, callback=None, message_id=None, poll_id=None, option=None):
        async with self.lock:
            app = self.application
            if not app or not app.running:
                raise ValueError('Сначала запустите автономного бота')
            raw = {'update_id': self.next_id()}
            if message is not None:
                if not message.strip() or len(message) > 4000:
                    raise ValueError('Введите сообщение до 4000 символов')
                raw['message'] = {'message_id': self.next_id(), 'date': int(time.time()), 'chat': ROOM, 'from': PLAYER, 'text': message}
                if message.startswith('/'):
                    command = message.split()[0]
                    if command.split('@')[0] in {'/reloadcfg', '/backup', '/restore', '/deletebackup'}:
                        raise ValueError('Файловые/эксплуатационные операции выполняются отдельно в локальной панели')
                    raw['message']['entities'] = [{'type': 'bot_command', 'offset': 0, 'length': len(command)}]
            elif callback is not None:
                source = self.messages.get(message_id)
                choices = [b.get('callback_data') for row in (source or {}).get('reply_markup', {}).get('inline_keyboard', []) for b in row]
                if callback not in choices:
                    raise ValueError('Кнопка отсутствует в текущем сообщении')
                raw['callback_query'] = {'id': uuid4().hex, 'from': PLAYER, 'chat_instance': 'offline', 'data': callback, 'message': source}
            elif poll_id is not None:
                poll = next((m['poll'] for m in self.messages.values() if m.get('poll', {}).get('id') == poll_id), None)
                if not poll or poll['is_closed'] or type(option) is not int or not 0 <= option < len(poll['options']):
                    raise ValueError('Этот вариант ответа недоступен')
                raw['poll_answer'] = {'poll_id': poll_id, 'user': PLAYER, 'option_ids': [option],
                                      'option_persistent_ids': [poll['options'][option]['persistent_id']]}
            else:
                raise ValueError('Нет действия')
            await app.process_update(Update.de_json(raw, app.bot))
            # Keep the interactive preview deterministic: transactionally queued
            # Telegram effects are delivered before the HTTP response is returned.
            if self.game_runtime is not None:
                await self.game_runtime.notification_job(CallbackContext(app))
            return self.status()
