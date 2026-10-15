"""Personal, creator-only Photo series in standalone rooms.

The room owner controls the series. Other members receive only occupancy;
group Photo rules remain an owner decision, not an implicit new game mode.
"""
from datetime import datetime, timezone
from urllib.parse import quote

from sqlalchemy import select, text

from application.photo import (DEFAULT_PHOTO_HINTS_ENABLED, DEFAULT_PHOTO_OPEN_SECONDS,
                               DEFAULT_PHOTO_QUESTION_COUNT, _moment)
from application.photo_selection import available_photo_questions, select_photo_questions
from application.room_classic import RoomClassicApplicationService
from domain.photo import (complete_round, normalize_photo, photo_deadlines, photo_points,
                          prepare_photo, project_photo, record_attempt, reveal_hint, stop_photo)
from storage.admin_actions import operation_fence
from storage.games import GameRepository
from storage.models import Game, GameCommand, GameDeadline
from storage.photo_media import images_root, verified_image_path


class RoomPhotoApplicationService:
    def __init__(self, session):
        self.session = session
        self.games = GameRepository(session)

    async def access(self, *, room_id, account_id, owner=False):
        room = await RoomClassicApplicationService(self.session).access(
            room_id=room_id, account_id=account_id)
        if owner and room['role'] != 'owner':
            raise PermissionError('Только владелец комнаты может управлять своей фото-серией.')
        return room

    @staticmethod
    def _state(game):
        state = normalize_photo(game.state, room_id=game.room_id)
        if state is None or game.chat_id is not None:
            raise ValueError('Состояние фото-серии повреждено.')
        return state

    def _projection(self, game, *, now=None):
        state = self._state(game)
        url = None
        if state['current_round_id']:
            url = (f'/api/guest/rooms/{quote(game.room_id, safe="")}/photo/current/image'
                   f'?game_id={quote(game.id, safe="")}&round_id={quote(state["current_round_id"], safe="")}')
        result = project_photo(state, image_url=url, now=now)
        result['game_id'] = game.id
        return result

    async def setup(self, *, room_id, account_id):
        await self.access(room_id=room_id, account_id=account_id)
        try:
            available = await available_photo_questions(self.session)
        except LookupError:
            available = []
        return {'question_count': DEFAULT_PHOTO_QUESTION_COUNT,
                'open_seconds': DEFAULT_PHOTO_OPEN_SECONDS,
                'hints_enabled': DEFAULT_PHOTO_HINTS_ENABLED,
                'available_questions': len(available), 'can_start': bool(available)}

    async def _settle(self, game, *, now=None):
        state = self._state(game)
        timestamp = _moment(now)
        # At most two hints and one close; a newly opened round starts now.
        for _ in range(3):
            due = sorted((at, kind) for kind, at in photo_deadlines(state).items() if at <= timestamp)
            if not due:
                break
            _, kind = due[0]
            if kind.startswith('hint:'):
                _, round_id, level = kind.split(':', 2)
                state = reveal_hint(state, round_id=round_id, level=int(level), now=timestamp)
                event = 'photo_hint_revealed'
            else:
                _, round_id = kind.split(':', 1)
                state = complete_round(state, round_id=round_id, correct=False,
                                       reason='timeout', now=timestamp)
                event = 'photo_timed_out'
            await self.games.sync_state(game, state, event_kind=event, deadlines=photo_deadlines(state))

    async def current(self, *, room_id, account_id, now=None):
        await self.access(room_id=room_id, account_id=account_id)
        game = await self.games.current_in_room(room_id=room_id, mode='photo', lock=True)
        if game is None:
            return None
        state = self._state(game)
        if state['creator_account_id'] != str(account_id):
            return {'occupied': game.status == 'active'}
        await self._settle(game, now=now)
        return self._projection(game, now=now)

    async def start(self, **kwargs):
        async with self.session.begin_nested():
            return await self._start(**kwargs)

    async def _start(self, *, room_id, account_id, command_id,
                     question_count=DEFAULT_PHOTO_QUESTION_COUNT,
                     open_seconds=DEFAULT_PHOTO_OPEN_SECONDS,
                     hints_enabled=DEFAULT_PHOTO_HINTS_ENABLED, now=None, enabled=True):
        await self.access(room_id=room_id, account_id=account_id, owner=True)
        if type(question_count) is not int or not 1 <= question_count <= 10:
            raise ValueError('Количество фото-вопросов должно быть от 1 до 10.')
        if type(open_seconds) is not int or not 5 <= open_seconds <= 600:
            raise ValueError('Время ответа должно быть от 5 до 600 секунд.')
        if type(hints_enabled) is not bool:
            raise ValueError('Некорректная настройка подсказок.')
        payload = {'room_id': room_id, 'question_count': question_count,
                   'open_seconds': open_seconds, 'hints_enabled': hints_enabled}
        current = await self.games.current_in_room(room_id=room_id, mode='photo', lock=True)
        await self.session.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))'),
                                   {'key': f'command:{command_id}'})
        receipt = await self.session.get(GameCommand, command_id)
        if receipt is not None:
            cached, result = await self.games.reserve_command(command_id=command_id,
                game_id=receipt.game_id, actor_account_id=account_id, kind='room_photo.start',
                expected_revision=None, payload=payload)
            if cached:
                return result
        if not enabled:
            raise PermissionError('Новые фото-серии в комнатах сейчас отключены.')
        if current and current.status == 'active':
            # An owner change never grants control over another creator's series.
            if self._state(current)['creator_account_id'] != str(account_id):
                raise RuntimeError('Фото-серия занята другим игроком.')
            await self._settle(current, now=now)
            if current.status == 'active':
                raise RuntimeError('В комнате уже идёт твоя фото-серия.')
        questions = await select_photo_questions(self.session, question_count)
        state = prepare_photo(room_id=room_id, creator_account_id=str(account_id),
            questions=questions, open_seconds=open_seconds, hints_enabled=hints_enabled, now=now)
        game = await self.games.replace_current(current, state=state, deadlines=photo_deadlines(state)) if current else await self.games.create_room_current(
            room_id=room_id, mode='photo', state=state, deadlines=photo_deadlines(state), actor_account_id=account_id)
        await self.games.reserve_command(command_id=command_id, game_id=game.id,
            actor_account_id=account_id, kind='room_photo.start', expected_revision=None, payload=payload)
        result = self._projection(game, now=now)
        await self.games.complete_command(command_id, result)
        return result

    async def command(self, **kwargs):
        async with self.session.begin_nested():
            return await self._command(**kwargs)

    async def _command(self, *, room_id, account_id, game_id, command_id, kind,
                       round_id=None, answer=None, expected_revision=None, now=None):
        await self.access(room_id=room_id, account_id=account_id, owner=kind == 'stop')
        current = await self.games.current_in_room(room_id=room_id, mode='photo', lock=True)
        game = await self.session.get(Game, game_id)
        if game is None or game.room_id != room_id or game.mode != 'photo' or game.chat_id is not None:
            raise LookupError('Фото-серия не найдена.')
        state = self._state(game)
        if state['creator_account_id'] != str(account_id):
            raise PermissionError('Эта фото-серия принадлежит другому игроку.')
        if kind not in {'answer', 'stop'}:
            raise ValueError('Неизвестная команда.')
        payload = {'room_id': room_id, 'round_id': round_id, 'answer': answer}
        cached, result = await self.games.reserve_command(command_id=command_id,
            game_id=game.id, actor_account_id=account_id, kind=f'room_photo.{kind}',
            expected_revision=expected_revision, payload=payload)
        if cached:
            return result
        if current is None or current.id != game.id or game.status != 'active':
            raise RuntimeError('Эта фото-серия уже завершена.')
        if kind == 'answer':
            state, verdict = record_attempt(state, round_id=round_id, answer=answer, now=now)
            if verdict == 'correct':
                item = next(item for item in state['rounds'] if item['round_id'] == round_id)
                state = complete_round(state, round_id=round_id, correct=True,
                    points=photo_points(item, now=now), reason='answer', now=now)
            event = 'photo_answered' if verdict == 'correct' else 'photo_attempted'
        else:
            state = stop_photo(state, expected_revision=expected_revision, now=now)
            event = 'photo_stopped'
        await self.games.sync_state(game, state, actor_account_id=account_id,
                                   event_kind=event, deadlines=photo_deadlines(state))
        result = self._projection(game, now=now)
        if kind == 'answer':
            result.update(applied=True, verdict=verdict)
        await self.games.complete_command(command_id, result)
        return result

    async def image(self, *, room_id, account_id, game_id, round_id, now=None):
        await self.access(room_id=room_id, account_id=account_id)
        game = await self.games.current_in_room(room_id=room_id, mode='photo', lock=True)
        if game is None or game.id != game_id or game.status != 'active':
            raise LookupError('Активный фото-вопрос не найден.')
        state = self._state(game)
        if state['creator_account_id'] != str(account_id) or round_id != state['current_round_id']:
            raise LookupError('Активный фото-вопрос не найден.')
        item = next(item for item in state['rounds'] if item['round_id'] == round_id)
        if item['status'] != 'open' or _moment(now) > item['closes_at']:
            raise LookupError('Активный фото-вопрос не найден.')
        path = verified_image_path(images_root(), item['media']['media_key'], item['media'])
        if path is None:
            raise LookupError('Изображение недоступно.')
        return path

    async def settle_due_game(self, *, game_id, now=None):
        await operation_fence(self.session)
        candidate = await self.session.get(Game, game_id)
        if candidate is None or candidate.mode != 'photo' or candidate.chat_id is not None:
            return None
        game = await self.games.current_in_room(room_id=candidate.room_id, mode='photo', lock=True)
        if game is None or game.id != game_id or game.status != 'active':
            return None
        await self._settle(game, now=now)
        return {'game_id': game.id, 'status': game.status}

    async def due_game_ids(self, *, now=None):
        moment = datetime.fromtimestamp(_moment(now), timezone.utc)
        return list((await self.session.scalars(select(Game.id).join(GameDeadline, GameDeadline.game_id == Game.id).where(
            Game.mode == 'photo', Game.chat_id.is_(None), Game.is_current.is_(True), Game.status == 'active',
            GameDeadline.status == 'pending', GameDeadline.due_at <= moment).distinct())).all())
