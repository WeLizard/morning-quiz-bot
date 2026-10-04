"""Bounded private-chat UI and inbox for two interfaces of the SAME bot runtime.

No quiz rules live here. Commands and answers go to the registered bot handlers;
only a whitelisted projection of their output crosses the public API boundary.
"""
from contextlib import asynccontextmanager
from copy import deepcopy
from hashlib import sha256
import re
import time

from sqlalchemy import or_, select, text
from .models import Game, GameDelivery, SystemState, PollAnswer, QuizSession
from .mini_app import MiniAppError

COMMANDS = {'/start', '/quiz', '/photo_quiz', '/stopquiz', '/stop_photo_quiz', '/cancel',
            '/adminsettings', '/categories', '/mystats', '/top', '/globaltop', '/help',
            '/photo_quiz_help', '/chatstats', '/scheduler_status'}


class MiniBridge:
    def __init__(self, database, bot_key_id, user_id, *, clock=time.time):
        self.database, self.user_id, self.clock = database, user_id, clock
        self.key = f'mini-ui:{bot_key_id[:24]}:{user_id}'

    @asynccontextmanager
    async def locked(self, session=None):
        if session is None:
            async with self.database.transaction() as own:
                async with self.locked(own) as value:
                    yield value
            return
        lock = int.from_bytes(sha256(self.key.encode()).digest()[:8], 'big', signed=True)
        await session.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': lock})
        row = await session.get(SystemState, self.key)
        if row is None:
            row = SystemState(key=self.key, payload={})
            session.add(row)
        value = deepcopy(row.payload or {})
        value.setdefault('messages', [])
        value.setdefault('requests', [])
        value.setdefault('version', 0)
        yield value
        if value != (row.payload or {}):
            value['version'] += 1
            row.payload = value

    async def heartbeat(self, photo=None, *, restart=False):
        async with self.locked() as value:
            value['heartbeat'] = self.clock()
            value['photo_round'] = photo
            if restart:
                for item in value['requests']:
                    if item['status'] == 'running':
                        item.update(status='uncertain', error='Бот перезапустился во время действия. Проверь результат; повтор автоматически не отправлен.')

    @staticmethod
    def validate(action, value, now):
        if not isinstance(action, dict) or set(action) - {'request_id', 'type', 'value', 'message_id', 'revision', 'round'}:
            raise MiniAppError(400, 'Некорректное действие')
        if not isinstance(action.get('request_id'), str) or not re.fullmatch(r'[a-f0-9-]{32,36}', action['request_id']):
            raise MiniAppError(400, 'Некорректный идентификатор действия')
        kind, data = action.get('type'), action.get('value')
        if kind == 'command':
            if not isinstance(data, str) or data not in COMMANDS:
                raise MiniAppError(400, 'Команда недоступна в игровом приложении')
        elif kind == 'text':
            if not isinstance(data, str) or not 1 <= len(data.strip()) <= 300 or data.strip().startswith('/'):
                raise MiniAppError(400, 'Введите ответ или значение настройки, до 300 символов')
            if action.get('round') != value.get('photo_round'):
                raise MiniAppError(409, 'Этот фото-вопрос уже завершён')
        elif kind in {'callback', 'vote'}:
            if type(action.get('message_id')) is not int:
                raise MiniAppError(400, 'Некорректный идентификатор карточки')
            message = next((m for m in value['messages'] if m['id'] == action.get('message_id')), None)
            if not message:
                raise MiniAppError(409, 'Эта карточка уже закрыта')
            if kind == 'callback':
                if message['revision'] != action.get('revision') or not isinstance(data, str) or data not in {
                        b['data'] for row in message.get('buttons', []) for b in row if 'data' in b}:
                    raise MiniAppError(409, 'Настройки изменились. Нажмите кнопку в актуальной карточке.')
            else:
                poll = message.get('poll')
                if not poll or type(data) is not int or not 0 <= data < len(poll['options']):
                    raise MiniAppError(400, 'Некорректный вариант ответа')
                if poll['closed'] or now >= poll['ends_at']:
                    raise MiniAppError(409, 'Время ответа истекло')
        else:
            raise MiniAppError(400, 'Неизвестное действие')

    async def enqueue(self, session, action):
        async with self.locked(session) as value:
            previous = next((r for r in value['requests'] if r['id'] == action.get('request_id')), None)
            if previous:
                if previous['action'] != action:
                    raise MiniAppError(409, 'Идентификатор уже использован для другого действия')
                return {'id': previous['id'], 'status': previous['status']}
            if self.clock() - value.get('heartbeat', 0) > 15:
                raise MiniAppError(503, 'Игровой бот сейчас не подключён. Попробуйте позже.')
            self.validate(action, value, self.clock())
            if any(r['status'] in {'pending', 'running'} for r in value['requests']):
                raise MiniAppError(409, 'Предыдущее действие ещё выполняется')
            if sum(r['created'] > self.clock() - 60 for r in value['requests']) >= 30:
                raise MiniAppError(429, 'Слишком много действий. Подождите немного.')
            item = {'id': action['request_id'], 'action': deepcopy(action), 'status': 'pending', 'created': self.clock()}
            value['requests'] = (value['requests'] + [item])[-40:]
            return {'id': item['id'], 'status': item['status']}

    async def claim(self):
        async with self.locked() as value:
            for item in value['requests']:
                if item['status'] != 'pending':
                    continue
                try:
                    if self.clock() - item['created'] > 30:
                        raise MiniAppError(409, 'Действие устарело. Выберите его заново.')
                    self.validate(item['action'], value, self.clock())
                except MiniAppError as exc:
                    item.update(status='failed', error=exc.detail)
                    continue
                item['status'] = 'running'
                return deepcopy(item['action']), deepcopy(value)
        return None

    async def finish(self, request_id, error=None, notice=None):
        async with self.locked() as value:
            for item in value['requests']:
                if item['id'] == request_id:
                    item['status'] = 'failed' if error else 'done'
                    if error:
                        item['error'] = error
                    if notice:
                        item['notice'] = notice

    async def publish(self, method, params, result, media_name=None):
        if method not in {'sendMessage', 'sendPhoto', 'sendPoll', 'editMessageText',
                          'editMessageCaption', 'editMessageReplyMarkup', 'deleteMessage', 'deleteMessages', 'stopPoll'}:
            return
        if str(params.get('chat_id')) != str(self.user_id):
            return
        async with self.locked() as value:
            messages = value['messages']
            mid = result.get('message_id') if isinstance(result, dict) else None
            mid = mid or params.get('message_id')
            if method in {'deleteMessage', 'deleteMessages'}:
                deleted = params.get('message_ids', [mid])
                value['messages'] = [m for m in messages if m['id'] not in deleted]
                return
            if not isinstance(mid, int):
                return
            item = next((m for m in messages if m['id'] == mid), None)
            if item is None:
                item = {'id': mid, 'text': '', 'buttons': [], 'revision': 0, 'at': self.clock()}
                messages.append(item)
            item['revision'] += 1
            item['updated_at'] = self.clock()
            if isinstance(result, dict):
                if 'text' in result or 'caption' in result:
                    item['text'] = str(result.get('text', result.get('caption', '')))[:6000]
                markup = result.get('reply_markup', params.get('reply_markup'))
                if method != 'stopPoll':
                    item['buttons'] = [[{'text': str(b.get('text', ''))[:120], 'data': b['callback_data'],
                                         'style': b.get('style', '')} for b in row if isinstance(b.get('callback_data'), str)]
                                       for row in (markup or {}).get('inline_keyboard', [])[:30]]
                if method == 'sendPoll':
                    poll = result.get('poll', {})
                    item['poll'] = {'id': poll['id'], 'question': poll['question'],
                        'options': [o['text'] for o in poll['options']], 'closed': False,
                        'ends_at': params.get('close_date') or self.clock() + params.get('open_period', 30)}
                    item['_option_persistent_ids'] = [
                        option.get('persistent_id') for option in poll['options']
                    ]
                    indexes = params.get('correct_option_ids', [params.get('correct_option_id')])
                    item['_answer'] = indexes[0] if indexes else None
                    item['_explanation'] = str(params.get('explanation') or '')[:500]
            if method == 'stopPoll' and item.get('poll'):
                item['poll']['closed'] = True
            if media_name:
                item['_media'] = media_name
            value['messages'] = messages[-50:]

    async def snapshot(self, session):
        row = await session.get(SystemState, self.key)
        value = deepcopy(row.payload or {}) if row else {}
        messages = value.get('messages', [])
        poll_ids = [m['poll']['id'] for m in messages if m.get('poll')]
        deliveries = (await session.scalars(select(GameDelivery).where(
            GameDelivery.channel == 'telegram',
            GameDelivery.kind == 'quiz_poll',
            GameDelivery.external_id.in_(poll_ids),
        ))).all() if poll_ids else []
        round_ids = [delivery.round_id for delivery in deliveries]
        answer_rows = (await session.scalars(select(PollAnswer).where(
            PollAnswer.user_id == self.user_id,
            or_(
                PollAnswer.poll_id.in_(poll_ids),
                PollAnswer.round_id.in_(round_ids),
            ),
        ))).all() if poll_ids else []
        answers = {answer.poll_id: answer for answer in answer_rows}
        by_round = {
            (answer.game_id, answer.round_id): answer
            for answer in answer_rows if answer.game_id and answer.round_id
        }
        for delivery in deliveries:
            answer = by_round.get((delivery.game_id, delivery.round_id))
            if answer is not None:
                answers[delivery.external_id] = answer
        public = []
        for original in messages:
            item = {k: v for k, v in original.items() if not k.startswith('_')}
            if original.get('_media'):
                item['media'] = f'/api/mini/runtime/media/{item["id"]}'
            poll = item.get('poll')
            if poll:
                poll['closed'] = poll['closed'] or self.clock() >= poll['ends_at']
                answer = answers.get(poll['id'])
                if answer:
                    item['feedback'] = {'correct': answer.is_correct, 'selected': answer.selected_option,
                        'points': str(answer.points_delta), 'answer': original.get('_answer'),
                        'explanation': original.get('_explanation', '')}
            public.append(item)
        games = await self.game_projection(session)
        return {'connected': self.clock() - value.get('heartbeat', 0) <= 15,
                'version': value.get('version', 0), 'server_time': self.clock(), 'messages': public,
                'games': games,
                'photo_round': value.get('photo_round'),
                'requests': [{k: r[k] for k in ('id', 'status', 'error', 'notice') if k in r} for r in value.get('requests', [])[-10:]]}

    async def game_projection(self, session):
        """Player presentation data, never the question bank or other players' state."""
        rows = list((await session.scalars(select(Game).where(
            Game.chat_id == self.user_id,
            Game.mode.in_(['classic', 'photo']),
            Game.is_current.is_(True),
        ))).all())
        result = []
        for row in rows:
            state = row.state or {}
            kind = row.mode
            photo_owner = state.get('creator_id') if state.get('mode') == 'photo' else state.get('user_id')
            if kind not in {'classic', 'photo'} or (kind == 'photo' and photo_owner != self.user_id):
                continue
            v2 = state.get('mode') in {'classic', 'photo'}
            questions = state.get('rounds') if v2 else state.get('questions') or []
            count = state.get('config', {}).get('question_count') if v2 else state.get(
                'num_questions_to_ask', len(questions)
            )
            active_round = next((item for item in questions
                                 if item.get('round_id') == state.get('current_round_id')), None) if v2 else None
            current = active_round['index'] + 1 if active_round else state.get('current_question_index', 0)
            count = max(0, min(count, 1000)) if type(count) is int else 0
            current = max(0, min(current, count)) if type(current) is int else 0
            polls = ([item['round_id'] for item in questions] if v2 else
                     list((state.get('polls') or {}).keys()) if kind == 'classic' else [])
            answers = (await session.scalars(select(PollAnswer).where(
                PollAnswer.chat_id == self.user_id, PollAnswer.user_id == self.user_id,
                PollAnswer.poll_id.in_(polls)))).all() if polls else []
            item = {'kind': kind, 'status': row.status,
                'key': sha256(str(state.get('session_id', row.id)).encode()).hexdigest()[:24],
                'current': current, 'total': count, 'poll_ids': polls,
                'started_at': row.started_at.timestamp() if row.started_at else 0,
                'correct': sum(bool(a.is_correct) for a in answers) if kind == 'classic' else state.get('total_correct', state.get('total_correct_answers', 0)),
                'points': str(sum(a.points_delta for a in answers)) if kind == 'classic' else str(state.get('total_score', 0)),
                'phase': state.get('phase' if v2 or kind == 'photo' else 'storage_phase', 'ready')}
            if kind == 'photo':
                active = active_round or {}
                item['time_limit'] = state.get('config', {}).get('open_seconds', state.get('time_limit', 60))
                item['question_started_at'] = active.get('opened_at', state.get('start_time'))
                item['attempts'] = active.get('attempts', state.get('attempts', 0))
                outcome = state.get('last_result') or state.get('last_outcome') or {}
                item['outcome'] = {key: outcome[key] for key in ('index', 'correct', 'points') if key in outcome}
            result.append(item)
        return result

    async def media_name(self, session, message_id):
        row = await session.get(SystemState, self.key)
        for item in (row.payload or {}).get('messages', []) if row else []:
            if item['id'] == message_id and item.get('_media'):
                return item['_media']
        raise MiniAppError(404, 'Изображение недоступно')
