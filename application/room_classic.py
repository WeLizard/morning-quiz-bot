"""Account Classic commands using the shared rules, without Telegram effects."""
import json
from datetime import datetime, timezone
from pathlib import Path
from decimal import Decimal

from sqlalchemy import select, text

from domain.classic import (classic_deadlines, finish_classic, normalize_classic,
                            on_answer_applied, prepare_classic, project_classic,
                            settle_classic, start_classic, validate_classic_answer)
from domain.scoring import ClassicScoringRules, classic_points
from application.classic_selection import list_classic_categories, select_classic_questions
from application.rooms import RoomApplicationService
from storage.admin_actions import operation_fence
from storage.games import GameRepository
from storage.models import Account, ClassicAccountAnswer, Game, GameCommand, GameDeadline, GamePlayer


def _telegram_defaults():
    """Room Classic defaults mirror the Telegram chat defaults in config/quiz_config.json."""
    try:
        with open(Path(__file__).resolve().parent.parent / 'config' / 'quiz_config.json', encoding='utf-8') as handle:
            chat = json.load(handle)['default_chat_settings']
        values = (int(chat['default_num_questions']), int(chat['default_open_period_seconds']),
                  int(chat['default_interval_seconds']))
        if 1 <= values[0] <= 50 and 5 <= values[1] <= 600 and 0 <= values[2] <= 600:
            return values
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return 10, 30, 30


DEFAULT_COUNT, DEFAULT_OPEN_SECONDS, DEFAULT_INTERVAL = _telegram_defaults()
DEFAULT_RANDOM_CATEGORIES = 3
CATEGORY_MODES = {'all', 'random', 'specific', 'exclude'}


class RoomClassicApplicationService:
    def __init__(self, session, *, rules=None):
        self.session = session
        self.games = GameRepository(session)
        self.rules = rules or ClassicScoringRules()

    async def access(self, *, room_id, account_id, owner=False):
        await operation_fence(self.session)
        account = await self.session.scalar(select(Account).where(Account.id == account_id)
            .execution_options(populate_existing=True))
        if account is None or account.archived or account.bot_blocked:
            raise PermissionError('Игровой аккаунт недоступен.')
        room = await RoomApplicationService(self.session).get_mine(room_id=room_id, account_id=account_id)
        if owner and room['role'] != 'owner':
            raise PermissionError('Только владелец комнаты может управлять викториной.')
        return room

    async def _projection(self, game, account_id, *, now=None, answered_round_id=None):
        rows = (await self.session.scalars(select(ClassicAccountAnswer).where(
            ClassicAccountAnswer.game_id == game.id,
            ClassicAccountAnswer.account_id == account_id,
        ))).all()
        result = project_classic(game.state, selected_options={r.round_id: r.selected_option for r in rows},
                                 answered_round_id=answered_round_id, now=now)
        result['game_id'] = game.id
        for row in rows:
            if result['question'] and result['question']['round_id'] == row.round_id:
                result['question']['points'] = str(row.points_delta)
            if result.get('accepted_answer') and result['accepted_answer']['round_id'] == row.round_id:
                result['accepted_answer']['points'] = str(row.points_delta)
        players = (await self.session.execute(select(GamePlayer, Account.display_name).join(
            Account, Account.id == GamePlayer.account_id,
        ).where(GamePlayer.game_id == game.id))).all()
        result['scores'] = sorted([{'account_id': str(p.account_id), 'name': name,
                                  'score': p.public_state.get('score', '0')}
                                 for p, name in players], key=lambda p: (-Decimal(p['score']), p['account_id']))
        return result

    async def _settle(self, game, *, now=None):
        state = normalize_classic(game.state, room_id=game.room_id)
        if state is None or game.chat_id is not None:
            raise ValueError('Состояние комнаты повреждено.')
        after = settle_classic(state, now=now)
        if after != state:
            await self.games.sync_state(game, after, event_kind='classic_deadline_advanced',
                                        deadlines=classic_deadlines(after))

    async def current(self, *, room_id, account_id, now=None):
        await self.access(room_id=room_id, account_id=account_id)
        game = await self.games.current_in_room(room_id=room_id, mode='classic', lock=True)
        if game is None:
            return None
        await self._settle(game, now=now)
        return await self._projection(game, account_id, now=now)

    async def start(self, **kwargs):
        async with self.session.begin_nested():
            return await self._start(**kwargs)

    async def setup(self, *, room_id, account_id):
        """Defaults, limits and selectable themes: the same options the Telegram setup offers."""
        await self.access(room_id=room_id, account_id=account_id)
        return {'questions': DEFAULT_COUNT, 'seconds': DEFAULT_OPEN_SECONDS, 'interval': DEFAULT_INTERVAL,
                'category_mode': 'all', 'categories': [], 'random_categories': DEFAULT_RANDOM_CATEGORIES,
                'available_categories': await list_classic_categories(self.session),
                'limits': {'questions': [1, 50], 'seconds': [5, 600], 'interval': [0, 600],
                           'random_categories': [1, 10]}}

    async def _start(self, *, room_id, account_id, command_id, count=DEFAULT_COUNT,
                    open_seconds=DEFAULT_OPEN_SECONDS, interval_seconds=DEFAULT_INTERVAL, now=None, enabled=True,
                    category_mode='all', categories=(), random_categories=DEFAULT_RANDOM_CATEGORIES):
        await self.access(room_id=room_id, account_id=account_id, owner=True)
        if type(count) is not int or not 1 <= count <= 50:
            raise ValueError('Количество вопросов должно быть от 1 до 50.')
        if type(open_seconds) is not int or not 5 <= open_seconds <= 600:
            raise ValueError('Время ответа должно быть от 5 до 600 секунд.')
        if type(interval_seconds) is not int or not 0 <= interval_seconds <= 600:
            raise ValueError('Интервал должен быть от 0 до 600 секунд.')
        if category_mode not in CATEGORY_MODES:
            raise ValueError('Неизвестный способ выбора тем.')
        if (not isinstance(categories, (list, tuple)) or len(categories) != len(set(categories))
                or any(type(name) is not str for name in categories)):
            raise ValueError('Список тем некорректен.')
        categories = list(categories)
        if type(random_categories) is not int or not 1 <= random_categories <= 10:
            raise ValueError('Количество случайных тем должно быть от 1 до 10.')
        if category_mode in {'specific', 'exclude'} and not categories:
            raise ValueError('Выбери хотя бы одну тему.')
        if category_mode in {'all', 'random'} and categories:
            raise ValueError('Список тем нужен только для режимов «выбранные» и «кроме выбранных».')
        known = None
        if categories:
            known = set(await list_classic_categories(self.session))
            if any(name not in known for name in categories):
                raise ValueError('Выбрана неизвестная или недоступная тема.')
        payload = {'room_id': room_id, 'count': count, 'open_seconds': open_seconds, 'interval_seconds': interval_seconds}
        if category_mode != 'all' or random_categories != DEFAULT_RANDOM_CATEGORIES:
            payload.update(category_mode=category_mode, categories=categories, random_categories=random_categories)
        # Serialize even when no current game exists, and inspect the receipt
        # before random selection or replacing a finished current game.
        current = await self.games.current_in_room(room_id=room_id, mode='classic', lock=True)
        await self.session.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))'), {'key': f'command:{command_id}'})
        receipt = await self.session.get(GameCommand, command_id)
        if receipt is not None:
            cached, result = await self.games.reserve_command(command_id=command_id, game_id=receipt.game_id,
                actor_account_id=account_id, kind='room_classic.start', expected_revision=None, payload=payload)
            if cached:
                return result
        if not enabled:
            raise PermissionError('Новые викторины в комнатах сейчас отключены.')
        if current and current.status == 'active':
            await self._settle(current, now=now)
            if current.status == 'active':
                raise RuntimeError('В комнате уже идёт викторина.')
        if category_mode == 'specific':
            # Every chosen theme takes part; there is no per-chat usage rotation to apply.
            questions = await select_classic_questions(self.session, chat_id=None, count=count,
                                                       category_names=categories, random_categories=False)
        else:
            questions = await select_classic_questions(self.session, chat_id=None, count=count, defaults={'quiz': {
                'categories_mode': category_mode, 'specific_categories': categories,
                'num_random_categories': random_categories}})
        if len(questions) != count:
            raise ValueError('В выбранных темах недостаточно вопросов.' if category_mode != 'all' else 'В каталоге недостаточно вопросов.')
        state = start_classic(prepare_classic(room_id=room_id, creator_account_id=str(account_id),
            questions=questions, open_seconds=open_seconds, interval_seconds=interval_seconds), expected_revision=0, now=now)
        game = await self.games.replace_current(current, state=state, deadlines=classic_deadlines(state)) if current else await self.games.create_room_current(
            room_id=room_id, mode='classic', state=state, deadlines=classic_deadlines(state), actor_account_id=account_id)
        await self.games.reserve_command(command_id=command_id, game_id=game.id, actor_account_id=account_id,
            kind='room_classic.start', expected_revision=None, payload=payload)
        result = await self._projection(game, account_id, now=now)
        await self.games.complete_command(command_id, result)
        return result

    async def command(self, **kwargs):
        async with self.session.begin_nested():
            return await self._command(**kwargs)

    async def _command(self, *, room_id, account_id, game_id, command_id, kind,
                      round_id=None, selected_option=None, expected_revision=None, now=None):
        await self.access(room_id=room_id, account_id=account_id, owner=kind == 'stop')
        current = await self.games.current_in_room(room_id=room_id, mode='classic', lock=True)
        game = await self.session.get(Game, game_id)
        if game is None or game.room_id != room_id or game.mode != 'classic' or game.chat_id is not None:
            raise LookupError('Викторина не найдена.')
        payload = {'round_id': round_id, 'selected_option': selected_option}
        cached, result = await self.games.reserve_command(command_id=command_id, game_id=game.id,
            actor_account_id=account_id, kind=f'room_classic.{kind}', expected_revision=expected_revision, payload=payload)
        if cached:
            return result
        if current is None or current.id != game.id:
            raise RuntimeError('Эта викторина уже завершена.')
        if kind == 'answer':
            row = await self.session.get(ClassicAccountAnswer, (game.id, round_id, account_id))
            if row is None:
                # Validate server time before deadline settlement: no client clock
                # or shared revision can reject another player's independent answer.
                item = validate_classic_answer(game.state, round_id=round_id, selected_option=selected_option, now=now)
                player = await self.session.get(GamePlayer, (game.id, account_id))
                if player is None:
                    player = GamePlayer(game_id=game.id, account_id=account_id, seat=account_id.hex, public_state={})
                    self.session.add(player)
                public = dict(player.public_state or {})
                correct = selected_option == item['correct_option_index']
                streak, points = classic_points(streak=int(public.get('streak', 0)), is_correct=correct, rules=self.rules)
                public.update(score=str(Decimal(public.get('score', '0')) + points), streak=streak)
                player.public_state = public
                self.session.add(ClassicAccountAnswer(game_id=game.id, round_id=round_id, account_id=account_id,
                    selected_option=selected_option, is_correct=correct, points_delta=points,
                    answered_at=datetime.fromtimestamp(float(now), timezone.utc) if type(now) in {int, float} else now or datetime.now(timezone.utc)))
                after = on_answer_applied(game.state, round_id=round_id, now=now)
                await self.games.sync_state(game, after, actor_account_id=account_id,
                    event_kind='classic_answered', deadlines=classic_deadlines(after))
            elif row.selected_option != selected_option:
                raise RuntimeError('Ответ уже принят и не может быть изменён.')
        elif kind == 'stop':
            after = finish_classic(game.state, reason='stopped', expected_revision=expected_revision, now=now)
            await self.games.sync_state(game, after, actor_account_id=account_id, event_kind='classic_stopped', deadlines={})
        else:
            raise ValueError('Неизвестная команда.')
        result = await self._projection(game, account_id, now=now, answered_round_id=round_id if kind == 'answer' else None)
        await self.games.complete_command(command_id, result)
        return result

    async def settle_due_game(self, *, game_id, now=None):
        await operation_fence(self.session)
        candidate = await self.session.get(Game, game_id)
        if candidate is None or candidate.chat_id is not None:
            return None
        game = await self.games.current_in_room(room_id=candidate.room_id, mode='classic', lock=True)
        if game is None or game.id != game_id or game.status != 'active':
            return None
        await self._settle(game, now=now)
        return {'game_id': game.id, 'status': game.status}

    async def due_game_ids(self, *, now=None):
        moment = datetime.fromtimestamp(float(now), timezone.utc) if type(now) in {int, float} else now or datetime.now(timezone.utc)
        return list((await self.session.scalars(select(Game.id).join(GameDeadline, GameDeadline.game_id == Game.id).where(
            Game.mode == 'classic', Game.chat_id.is_(None), Game.is_current.is_(True), Game.status == 'active',
            GameDeadline.status == 'pending', GameDeadline.due_at <= moment).distinct())).all())
