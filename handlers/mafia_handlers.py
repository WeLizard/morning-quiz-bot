"""Telegram presentation adapter for the shared Night City application service."""

from html import escape
import logging
import math
import time

from telegram import InputPollOption, InlineKeyboardButton as Button, InlineKeyboardMarkup, Poll, Update
from telegram.error import RetryAfter, TelegramError
from telegram.ext import CallbackQueryHandler, CommandHandler

from application.mafia import MafiaApplicationService
from modules.mini_app_launch import direct_mafia_link
from modules.telegram_menu import acknowledge, card
from storage.repositories import OperationalRepository

logger = logging.getLogger(__name__)


def command_id(query):
    value = getattr(query, 'id', None)
    return f'tg:{value}' if value else None


def render_classic_result(result: dict) -> str:
    players = result.get('players') or []
    lines = [
        '🏁 <b>Викторина завершена</b>',
        f'Вопросов: {int(result.get("question_count") or 0)}',
    ]
    if not players:
        lines.extend(['', 'Пока без ответов — следующий раунд всё изменит.'])
        return '\n'.join(lines)
    lines.extend(['', '<b>Итоги</b>'])
    for place, player in enumerate(players[:10], 1):
        lines.append(
            f'{place}. {escape(str(player["name"]))} — '
            f'{escape(str(player["points"]))} баллов · '
            f'{int(player["correct"])} верных'
        )
    return '\n'.join(lines)


def render_lobby(lobby: dict | None, *, mini_url: str | None = None):
    """Return a group-safe Telegram card without per-player secrets."""
    if lobby is None:
        text = (
            '🌒 <b>Ночной город</b>\n\n'
            'Стол ещё не собран. Первый участник станет ведущим лобби.'
        )
        rows = [[Button('Сесть за стол', callback_data='mafia:join', style='primary')]]
    else:
        active = lobby['status'] != 'lobby'
        players = '\n'.join(
            f'{("◉" if player.get("alive", True) else "×") if active else ("✅" if player["ready"] else "○")} '
            f'{escape(player["name"])}'
            for player in lobby['players']
        )
        text = f'🌒 <b>Ночной город</b> · {len(lobby["players"])} из 12\n\n{players}'
        status = lobby['status']
        revision = lobby['revision']
        if status == 'night':
            text += (
                f'\n\n<b>Ночь {lobby.get("round", 1)}.</b> Город засыпает. '
                'Тайные роли делают выбор в личной карточке.'
            )
            rows = [[Button('Узнать роль и сделать ход', callback_data='mafia:role', style='primary')]]
            if lobby.get('can_advance'):
                rows.append([Button('Объявить итоги ночи', callback_data=f'mafia:advance:{revision}', style='success')])
        elif status == 'day':
            text += f'\n\n<b>День {lobby.get("round", 1)}.</b> Обсудите события и подозреваемых.'
            rows = [[Button('Моя карточка', callback_data='mafia:role')]]
            if lobby.get('can_advance'):
                rows.append([Button('Открыть голосование', callback_data=f'mafia:advance:{revision}', style='primary')])
        elif status == 'voting':
            text += (
                f'\n\n<b>Голосование.</b> Голоса: '
                f'<b>{lobby.get("votes_cast", 0)}/{lobby.get("votes_needed", 0)}</b>. '
                'Выбор делается в личной карточке.'
            )
            rows = [[Button('Открыть бюллетень', callback_data='mafia:role', style='primary')]]
            if lobby.get('can_advance'):
                rows.append([Button('Подвести итоги', callback_data=f'mafia:advance:{revision}', style='success')])
        elif status == 'finished':
            winner = ('Город победил — мафия раскрыта.' if lobby.get('winner') == 'citizens'
                      else 'Мафия подчинила Ночной город.')
            text += f'\n\n<b>Дело закрыто.</b> {winner}'
            rows = ([[Button('Собрать реванш', callback_data=f'mafia:restart:{revision}', style='primary')]]
                    if lobby.get('is_host') else [])
        else:
            ready = sum(player['ready'] for player in lobby['players'])
            text += f'\n\nГотовы: <b>{ready}/{len(lobby["players"])}</b>. Для старта нужно минимум 4.'
            rows = [
                [Button('Сесть за стол', callback_data='mafia:join')],
                [Button('Я готов', callback_data=f'mafia:ready:1:{revision}', style='success'),
                 Button('Не готов', callback_data=f'mafia:ready:0:{revision}')],
            ]
            if lobby['can_start']:
                rows.append([Button('Начать ночь', callback_data=f'mafia:start:{revision}', style='primary')])

        history = lobby.get('history') or []
        if history:
            latest = history[-1]
            if latest.get('type') == 'night_result':
                result = (f'После ночи выбыл {latest["eliminated"]}.' if latest.get('eliminated')
                          else 'Доктор спас цель мафии.' if latest.get('saved')
                          else 'Ночь прошла без потерь.')
                text += f'\n\n<i>{result}</i>'
            elif latest.get('type') == 'vote_result':
                result = (f'Город вывел из игры {latest["eliminated"]}.' if latest.get('eliminated')
                          else 'Голоса разделились — никто не выбыл.')
                text += f'\n\n<i>{result}</i>'
        rows.append([Button('Обновить стол', callback_data='mafia:refresh')])
    if mini_url:
        rows.append([Button('Открыть этот стол в Mini App', url=mini_url)])
    return text, rows


def render_private_card(role: dict, lobby: dict, *, group_chat_id: int):
    """Return a private role/action card; never render it in a group chat."""
    phase = role['phase']
    phase_title = {
        'night': f'Ночь {role.get("round", 1)}',
        'day': f'День {role.get("round", 1)}',
        'voting': 'Голосование',
        'finished': 'Дело закрыто',
    }.get(phase, phase)
    text = f'🌒 <b>{escape(phase_title)}</b>\n\nТвоя роль: <b>{escape(role["title"])}</b>'
    rows = []
    revision = lobby['revision']
    if not role.get('alive', True):
        text += '\n\nТы выбыл из дела. Наблюдай за ходом партии в общем чате.'
    elif phase == 'night':
        if role['role'] == 'citizen':
            text += '\n\nГород спит. Дождись итогов ночи.'
        elif role.get('acted'):
            text += '\n\nВыбор принят. Ведущий продолжит, когда все роли сделают ход.'
        else:
            prompt = {'mafia': 'Кого убрать этой ночью?', 'doctor': 'Кого защитить?',
                      'detective': 'Кого проверить?'}[role['role']]
            text += f'\n\n{prompt}'
            rows = [[Button(target['name'][:40], callback_data=(
                f'mafia:act:{group_chat_id}:{target["seat"]}:{revision}'
            ))] for target in role.get('targets', [])]
    elif phase == 'day':
        text += '\n\nОбсудите события в общем чате. Ведущий откроет голосование.'
    elif phase == 'voting':
        if role.get('voted'):
            text += '\n\nГолос принят. Ждём остальных игроков.'
        else:
            text += '\n\nКого город должен вывести из игры?'
            rows = [[Button(target['name'][:40], callback_data=(
                f'mafia:vote:{group_chat_id}:{target["seat"]}:{revision}'
            ))] for target in role.get('targets', [])]
    elif phase == 'finished':
        text += ('\n\nГород победил — мафия раскрыта.' if role.get('winner') == 'citizens'
                 else '\n\nМафия подчинила Ночной город.')
    investigation = role.get('investigation')
    if investigation:
        verdict = 'это мафия' if investigation['is_mafia'] else 'это не мафия'
        text += f'\n\n🔎 Последняя проверка: <b>{investigation["seat"]}</b> — {verdict}.'
    rows.append([Button('Обновить карточку', callback_data=f'mafia:private:{group_chat_id}')])
    return text, rows


class MafiaHandlers:
    """Translate Telegram updates to transport-independent Mafia commands."""

    def __init__(self, database):
        self.database = database

    @staticmethod
    def _group(update):
        chat = update.effective_chat
        return chat if chat and chat.type in {'group', 'supergroup'} else None

    @staticmethod
    async def _remember(session, chat, user):
        repository = OperationalRepository(session)
        await repository.ensure_chat({
            'id': chat.id,
            'type': chat.type,
            'title': chat.title or 'Ночной город',
            'username': chat.username,
        })
        await repository.ensure_user({'id': user.id, 'display_name': user.full_name})
        await repository.ensure_member({'chat_id': chat.id, 'user_id': user.id})

    @staticmethod
    def _mini_url(context, chat_id):
        try:
            return direct_mafia_link(getattr(context.bot, 'username', None), chat_id)
        except ValueError:
            logger.warning('Invalid Mini App launch configuration; chat game remains available')
            return None

    async def _show(self, update, context, lobby):
        text, rows = render_lobby(
            lobby, mini_url=self._mini_url(context, update.effective_chat.id)
        )
        await card(update, context, text, rows)

    @staticmethod
    async def _show_private(query, context, *, group_chat_id, role, lobby, send=False):
        text, rows = render_private_card(role, lobby, group_chat_id=group_chat_id)
        markup = InlineKeyboardMarkup(rows)
        if send:
            return await context.bot.send_message(
                query.from_user.id, text, reply_markup=markup, parse_mode='HTML'
            )
        return await context.bot.edit_message_text(
            chat_id=query.message.chat.id,
            message_id=query.message.message_id,
            text=text,
            reply_markup=markup,
            parse_mode='HTML',
        )

    async def open(self, update: Update, context):
        user, chat = update.effective_user, self._group(update)
        if not user or not update.effective_chat:
            return
        if chat is None:
            await acknowledge(
                update.callback_query,
                '«Ночной город» создаётся в группе. Добавь туда бота и отправь /mafia.',
                alert=True,
            )
            if update.effective_message and not update.callback_query:
                markup = None
                from modules.mini_app_launch import launch_button
                try:
                    mini = launch_button(update.effective_chat.type)
                    if mini:
                        markup = InlineKeyboardMarkup([[mini]])
                except ValueError:
                    pass
                await update.effective_message.reply_text(
                    '🌒 «Ночной город» — групповая игра. Добавь бота в группу и отправь /mafia.\n\n'
                    'В Mini App можно заранее посмотреть состав ролей.',
                    reply_markup=markup,
                    parse_mode=None,
                )
            return
        async with self.database.transaction() as session:
            await self._remember(session, chat, user)
            service = MafiaApplicationService(session)
            lobby = await service.lobby(chat_id=chat.id, viewer_id=user.id)
            if lobby is None:
                lobby = (await service.join(
                    chat_id=chat.id, user_id=user.id, name=user.full_name,
                    command_id=(f'tg:update:{update.update_id}'
                                if getattr(update, 'update_id', None) is not None else None),
                ))['lobby']
        await acknowledge(update.callback_query)
        await self._show(update, context, lobby)

    async def _private_callback(self, query, user, context, action, parts):
        expected_lengths = {'private': 3, 'act': 5, 'vote': 5}
        if len(parts) != expected_lengths[action]:
            await acknowledge(query, 'Личная карточка устарела.', alert=True)
            return
        try:
            group_chat_id = int(parts[2])
            async with self.database.transaction() as session:
                service = MafiaApplicationService(session)
                if action == 'act':
                    result = await service.action(
                        chat_id=group_chat_id, user_id=user.id, target_seat=parts[3],
                        expected_revision=int(parts[4]), command_id=command_id(query),
                    )
                elif action == 'vote':
                    result = await service.vote(
                        chat_id=group_chat_id, user_id=user.id, target_seat=parts[3],
                        expected_revision=int(parts[4]), command_id=command_id(query),
                    )
                else:
                    lobby = await service.lobby(chat_id=group_chat_id, viewer_id=user.id)
                    role = await service.role(chat_id=group_chat_id, user_id=user.id)
                    if lobby is None or role is None:
                        raise LookupError('Партия не найдена.')
                    result = {'lobby': lobby, 'role': role}
            await acknowledge(query, 'Выбор принят.' if action != 'private' else None)
            await self._show_private(
                query, context, group_chat_id=group_chat_id,
                role=result['role'], lobby=result['lobby'],
            )
        except (LookupError, PermissionError, RuntimeError, ValueError) as error:
            await acknowledge(query, str(error)[:180], alert=True)

    async def callback(self, update: Update, context):
        query, user, group = update.callback_query, update.effective_user, self._group(update)
        if not query or not user:
            return
        parts = query.data.split(':') if isinstance(query.data, str) else []
        if len(parts) < 2:
            await acknowledge(query, 'Кнопка устарела.', alert=True)
            return
        action = parts[1]
        if action == 'open':
            return await self.open(update, context)
        if action in {'act', 'vote', 'private'}:
            if group is not None:
                await acknowledge(query, 'Тайные действия доступны только в личной карточке.', alert=True)
                return
            await self._private_callback(query, user, context, action, parts)
            return
        if group is None:
            await acknowledge(query, 'Откройте стол в групповом чате.', alert=True)
            return

        role = None
        try:
            async with self.database.transaction() as session:
                await self._remember(session, group, user)
                service = MafiaApplicationService(session)
                if action == 'role':
                    role = await service.role(chat_id=group.id, user_id=user.id)
                    if role is None:
                        raise ValueError('Роль появится после начала ночи.')
                    lobby = await service.lobby(chat_id=group.id, viewer_id=user.id)
                elif action == 'join' and len(parts) == 2:
                    lobby = (await service.join(
                        chat_id=group.id, user_id=user.id, name=user.full_name,
                        command_id=command_id(query),
                    ))['lobby']
                elif action == 'refresh' and len(parts) == 2:
                    lobby = await service.lobby(chat_id=group.id, viewer_id=user.id)
                elif action == 'ready' and len(parts) == 4 and parts[2] in {'0', '1'}:
                    lobby = await service.ready(
                        chat_id=group.id, user_id=user.id, ready=parts[2] == '1',
                        expected_revision=int(parts[3]), command_id=command_id(query),
                    )
                elif action == 'start' and len(parts) == 3:
                    lobby = await service.start(
                        chat_id=group.id, user_id=user.id, expected_revision=int(parts[2]),
                        command_id=command_id(query),
                    )
                elif action == 'advance' and len(parts) == 3:
                    lobby = (await service.advance(
                        chat_id=group.id, user_id=user.id, expected_revision=int(parts[2]),
                        command_id=command_id(query),
                    ))['lobby']
                elif action == 'restart' and len(parts) == 3:
                    lobby = await service.restart(
                        chat_id=group.id, user_id=user.id, expected_revision=int(parts[2]),
                        command_id=command_id(query),
                    )
                else:
                    raise ValueError('Кнопка устарела. Обновите стол.')
        except (LookupError, PermissionError, RuntimeError, ValueError) as error:
            await acknowledge(query, str(error)[:180], alert=True)
            return

        if action == 'role':
            try:
                await self._show_private(
                    query, context, group_chat_id=group.id, role=role, lobby=lobby, send=True
                )
            except TelegramError:
                await acknowledge(
                    query,
                    'Не могу написать в личку. Сначала открой бота лично через /start или используй Mini App.',
                    alert=True,
                )
                return
            await acknowledge(query, 'Личная карточка отправлена.')
            return
        await acknowledge(query)
        await self._show(update, context, lobby)

    async def deadline_job(self, context):
        """Advance expired games and drain their transactionally-created outbox."""
        async with self.database.transaction() as session:
            chat_ids = await MafiaApplicationService(session).due_chat_ids()
            from application.classic import ClassicApplicationService
            classic_due = await ClassicApplicationService(
                self.database, session
            ).due()
            from application.photo import PhotoApplicationService
            photo_due = await PhotoApplicationService(self.database, session).due()
        for chat_id in chat_ids:
            try:
                async with self.database.transaction() as session:
                    await MafiaApplicationService(session).advance_due(chat_id=chat_id)
            except (LookupError, PermissionError, RuntimeError, ValueError):
                logger.info('Mafia phase already changed for chat %s', chat_id)
        for chat_id in sorted({item[0] for item in classic_due}):
            try:
                async with self.database.transaction() as session:
                    await ClassicApplicationService(
                        self.database, session
                    ).settle_due(chat_id=chat_id)
            except (LookupError, PermissionError, RuntimeError, ValueError):
                logger.info('Classic deadline already changed for chat %s', chat_id)
        for chat_id in photo_due:
            try:
                async with self.database.transaction() as session:
                    await PhotoApplicationService(self.database, session).settle_due(chat_id=chat_id)
            except (LookupError, PermissionError, RuntimeError, ValueError):
                logger.info('Photo deadline already changed for chat %s', chat_id)
        await self._deliver_notifications(context)

    async def _deliver_notifications(self, context):
        from storage.notifications import NotificationQueue
        queue = NotificationQueue(self.database)
        worker_id = 'telegram:mafia-deadlines'
        for _ in range(20):
            item = await queue.claim(
                worker_id,
                kinds={'mafia.phase', 'classic.question', 'classic.finished',
                       'photo.question', 'photo.hint', 'photo.feedback',
                       'photo.result', 'photo.finished'},
            )
            if item is None:
                return
            if not item['chat_id']:
                await queue.uncertain(item['id'], worker_id, 'MissingChatId')
                continue
            try:
                if item['kind'] == 'classic.question':
                    await self._deliver_classic_question(context, queue, worker_id, item)
                    continue
                if item['kind'] == 'classic.finished':
                    await self._deliver_classic_result(context, queue, worker_id, item)
                    continue
                if item['kind'] == 'photo.question':
                    await self._deliver_photo_question(context, item)
                elif item['kind'].startswith('photo.'):
                    await self._deliver_photo_text(context, item)
                else:
                    lobby = item['payload']['lobby']
                    text, rows = render_lobby(
                        lobby, mini_url=self._mini_url(context, item['chat_id'])
                    )
                    await context.bot.send_message(
                        item['chat_id'], text,
                        reply_markup=InlineKeyboardMarkup(rows), parse_mode='HTML',
                    )
            except RetryAfter as error:
                seconds = error.retry_after
                if hasattr(seconds, 'total_seconds'):
                    seconds = seconds.total_seconds()
                await queue.retry_after(item['id'], worker_id, float(seconds))
            except TelegramError as error:
                # Telegram has no idempotency key for sendMessage. A lost HTTP
                # response is an unknown outcome, so automatic resend could duplicate.
                await queue.uncertain(item['id'], worker_id, type(error).__name__)
            except Exception as error:
                await queue.uncertain(item['id'], worker_id, type(error).__name__)
            else:
                await queue.delivered(item['id'], worker_id)

    async def _deliver_photo_question(self, context, item):
        from application.photo import PhotoApplicationService
        async with self.database.transaction() as session:
            effect = await PhotoApplicationService(
                self.database, session
            ).question_delivery(
                game_id=item['game_id'], round_id=item['payload'].get('round_id', '')
            )
        if effect is None or effect['closes_at'] - time.time() < 5:
            return
        lines = [
            f'🖼️ <b>Фото-загадка {effect["question_number"]}/{effect["question_count"]}</b>',
            f'Время: {max(1, math.ceil(effect["closes_at"] - time.time()))} сек.',
        ]
        if effect['mask']:
            lines.append(f'Слово: <code>{escape(effect["mask"])}</code>')
        lines.extend(['', 'Напишите ответ обычным сообщением.'])
        with open(effect['image_path'], 'rb') as photo:
            await context.bot.send_photo(
                chat_id=effect['chat_id'], photo=photo,
                caption='\n'.join(lines), parse_mode='HTML',
            )

    async def _deliver_photo_text(self, context, item):
        payload = item['payload']
        if item['kind'] == 'photo.hint':
            text = f'💡 Подсказка {int(payload["level"])}: <code>{escape(str(payload["mask"]))}</code>'
        elif item['kind'] == 'photo.feedback':
            text = ('🔥 Очень близко! Соберите точное слово.' if payload.get('verdict') == 'almost'
                    else '❌ Пока мимо. Попробуйте ещё раз.')
        elif item['kind'] == 'photo.result':
            if payload.get('correct'):
                text = (f'🎉 <b>Правильно!</b> {escape(str(payload.get("answer") or ""))}\n'
                        f'+{escape(str(payload.get("points") or 0))} баллов')
            else:
                text = (f'⏰ Время вышло. Ответ: '
                        f'<b>{escape(str(payload.get("answer") or "—"))}</b>')
        else:
            reason = payload.get('reason')
            if reason == 'stopped':
                text = '🛑 Фото-викторина остановлена. Все заработанные баллы сохранены.'
            else:
                text = (f'🏁 <b>Фото-викторина завершена</b>\n'
                        f'{int(payload.get("correct") or 0)} из {int(payload.get("question_count") or 0)} · '
                        f'{escape(str(payload.get("score") or 0))} баллов')
        await context.bot.send_message(item['chat_id'], text, parse_mode='HTML')

    async def _deliver_classic_question(self, context, queue, worker_id, item):
        """Deliver one internal round once and bind Telegram's external poll id."""
        from application.classic import ClassicApplicationService
        from storage.game_deliveries import GameDeliveries
        async with self.database.transaction() as session:
            effect = await ClassicApplicationService(
                self.database, session
            ).question_delivery(
                game_id=item['game_id'], round_id=item['payload'].get('round_id', '')
            )
            if effect is None:
                delivery = None
                created = False
            else:
                created, row = await GameDeliveries(session).reserve(
                    game_id=effect['game_id'], round_id=effect['round_id'],
                    channel='telegram', kind='quiz_poll', chat_id=effect['chat_id'],
                    metadata={'revision': effect['revision']},
                )
                delivery = {'id': row.id, 'status': row.status}
        if effect is None:
            await queue.delivered(item['id'], worker_id)
            return
        if not created:
            if delivery['status'] in {'sent', 'skipped'}:
                await queue.delivered(item['id'], worker_id)
            else:
                await queue.uncertain(item['id'], worker_id, 'DeliveryAlreadyReserved')
            return
        remaining = math.ceil(effect['closes_at'] - time.time())
        if remaining < 5:
            async with self.database.transaction() as session:
                await GameDeliveries(session).skipped(
                    delivery_id=delivery['id'], reason='deadline_too_close'
                )
            await queue.delivered(item['id'], worker_id)
            return
        try:
            sent = await context.bot.send_poll(
                chat_id=effect['chat_id'],
                question=effect['question'],
                question_parse_mode=None,
                options=[InputPollOption(option, text_parse_mode=None)
                         for option in effect['options']],
                type=Poll.QUIZ,
                correct_option_ids=[effect['correct_option']],
                open_period=min(600, remaining),
                is_anonymous=False,
                allows_multiple_answers=False,
                allows_revoting=False,
                shuffle_options=False,
            )
            if sent is None or sent.poll is None:
                raise TelegramError('No poll acknowledgement')
            async with self.database.transaction() as session:
                await GameDeliveries(session).acknowledge(
                    delivery_id=delivery['id'], external_id=sent.poll.id,
                    message_id=sent.message_id,
                    metadata={
                        'option_persistent_ids': [
                            option.persistent_id for option in sent.poll.options
                        ],
                    },
                )
        except RetryAfter as error:
            async with self.database.transaction() as session:
                await GameDeliveries(session).retryable(delivery_id=delivery['id'])
            seconds = error.retry_after
            if hasattr(seconds, 'total_seconds'):
                seconds = seconds.total_seconds()
            await queue.retry_after(item['id'], worker_id, float(seconds))
        except Exception as error:
            async with self.database.transaction() as session:
                await GameDeliveries(session).uncertain(
                    delivery_id=delivery['id'], error=type(error).__name__
                )
            await queue.uncertain(item['id'], worker_id, type(error).__name__)
        else:
            await queue.delivered(item['id'], worker_id)

    async def _deliver_classic_result(self, context, queue, worker_id, item):
        """Publish one durable Classic summary without risking a blind resend."""
        from application.classic import ClassicApplicationService
        from storage.game_deliveries import GameDeliveries
        async with self.database.transaction() as session:
            result = await ClassicApplicationService(
                self.database, session
            ).result_delivery(game_id=item['game_id'])
            if result is None:
                delivery = None
                created = False
            else:
                created, row = await GameDeliveries(session).reserve(
                    game_id=result['game_id'], round_id='result',
                    channel='telegram', kind='summary', chat_id=result['chat_id'],
                    metadata={'revision': result['revision']},
                )
                delivery = {'id': row.id, 'status': row.status}
        if result is None:
            await queue.delivered(item['id'], worker_id)
            return
        if not created:
            if delivery['status'] in {'sent', 'skipped'}:
                await queue.delivered(item['id'], worker_id)
            else:
                await queue.uncertain(item['id'], worker_id, 'DeliveryAlreadyReserved')
            return
        try:
            sent = await context.bot.send_message(
                chat_id=result['chat_id'], text=render_classic_result(result),
                parse_mode='HTML',
            )
            if sent is None:
                raise TelegramError('No result acknowledgement')
            async with self.database.transaction() as session:
                await GameDeliveries(session).acknowledge(
                    delivery_id=delivery['id'],
                    external_id=f'message:{sent.message_id}',
                    message_id=sent.message_id,
                )
        except RetryAfter as error:
            async with self.database.transaction() as session:
                await GameDeliveries(session).retryable(delivery_id=delivery['id'])
            seconds = error.retry_after
            if hasattr(seconds, 'total_seconds'):
                seconds = seconds.total_seconds()
            await queue.retry_after(item['id'], worker_id, float(seconds))
        except Exception as error:
            async with self.database.transaction() as session:
                await GameDeliveries(session).uncertain(
                    delivery_id=delivery['id'], error=type(error).__name__
                )
            await queue.uncertain(item['id'], worker_id, type(error).__name__)
        else:
            await queue.delivered(item['id'], worker_id)

    def install_deadlines(self, job_queue):
        if job_queue is None:
            return None
        name = 'game_deadlines_and_notifications'
        for job in job_queue.get_jobs_by_name(name):
            job.schedule_removal()
        return job_queue.run_repeating(self.deadline_job, interval=5, first=1, name=name)

    def get_handlers(self):
        return [
            CommandHandler('mafia', self.open),
            CallbackQueryHandler(self.callback, pattern=r'^mafia:'),
        ]
