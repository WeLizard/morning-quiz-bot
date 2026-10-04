"""Shared Telegram navigation: compact cards and real conversation entry points."""
from html import escape
import logging

from telegram import Update, CallbackQuery, InlineKeyboardButton as Button, InlineKeyboardMarkup
from telegram.error import BadRequest, TelegramError
from telegram.ext import CallbackQueryHandler, CommandHandler, ConversationHandler, TypeHandler, ApplicationHandlerStop

logger = logging.getLogger(__name__)


async def acknowledge(query, text=None, *, alert=False):
    if query:
        try:
            await query.answer(text, show_alert=alert, read_timeout=5, write_timeout=5)
        except TelegramError:
            # A late callback must not prevent a fresh screen from being displayed.
            logger.info('Callback acknowledgement unavailable')


def as_command(update, command):
    query = update.callback_query
    if not query or not query.message:
        return update
    text = '/' + command
    return Update.de_json({'update_id': update.update_id, 'message': {
        'message_id': query.message.message_id, 'date': int(query.message.date.timestamp()),
        'chat': query.message.chat.to_dict(), 'from': query.from_user.to_dict(), 'text': text,
        'entities': [{'type': 'bot_command', 'offset': 0, 'length': len(text.split()[0])}],
    }}, update.get_bot())


def conversation_entry(callback, command):
    async def enter(update, context):
        await acknowledge(update.callback_query)
        context.args = []
        if update.callback_query and update.callback_query.message:
            context.chat_data['_menu_entry_message_id'] = update.callback_query.message.message_id
        try:
            return await callback(as_command(update, command), context)
        finally:
            context.chat_data.pop('_menu_entry_message_id', None)
    return enter


def home_fallbacks():
    return [CallbackQueryHandler(home, pattern=r'^nav:home$'), CommandHandler('start', home)]


async def card(update, context, text, rows, *, parse_mode='HTML', message_id=None):
    query = update if isinstance(update, CallbackQuery) else update.callback_query
    chat = query.message.chat if query and query.message else update.effective_chat
    if not chat:
        return None
    target = message_id or (query.message.message_id if query and query.message else None)
    markup = InlineKeyboardMarkup(rows)
    if target:
        try:
            return await context.bot.edit_message_text(chat_id=chat.id, message_id=target,
                text=text, reply_markup=markup, parse_mode=parse_mode)
        except BadRequest as exc:
            reason = str(exc).lower()
            if 'message is not modified' in reason:
                return None
            if 'message to edit not found' not in reason and "message can't be edited" not in reason:
                raise
        # Ambiguous network errors propagate; never blindly send a duplicate card.
    return await context.bot.send_message(chat.id, text, reply_markup=markup, parse_mode=parse_mode)


async def home(update, context):
    if not update.effective_user or not update.effective_chat:
        return ConversationHandler.END
    await acknowledge(update.callback_query)
    config = context.bot_data['app_config']
    dm = context.bot_data.get('data_manager')
    if dm and dm.postgres_storage:
        from storage.repositories import OperationalRepository
        chat, user = update.effective_chat, update.effective_user
        async with dm.postgres_storage.database.transaction() as session:
            repository = OperationalRepository(session)
            await repository.ensure_chat({'id': chat.id, 'type': chat.type, 'title': chat.title or user.first_name})
            await repository.ensure_user({'id': user.id, 'display_name': user.full_name})
            await repository.ensure_member({'chat_id': chat.id, 'user_id': user.id})
    from modules.mini_app_launch import launch_button
    from utils import is_user_admin_in_update
    rows = [[Button('🎮 Классический квиз', callback_data='nav:quiz', style='primary')],
            [Button('🖼 Фото-квиз', callback_data='nav:photo')],
            [Button('🌒 Ночной город', callback_data='mafia:open')],
            [Button('📊 Мой прогресс', callback_data='nav:profile'), Button('🏆 Рейтинг', callback_data='nav:rating')],
            [Button('📚 Категории', callback_data='nav:categories'), Button('❔ Как играть', callback_data='nav:help')]]
    try:
        mini = launch_button(update.effective_chat.type)
        if mini:
            rows.insert(0, [mini])
    except ValueError:
        logger.warning('Invalid Mini App URL; keeping chat navigation')
    if await is_user_admin_in_update(update, context):
        rows.append([Button('⚙️ Настройки', callback_data='nav:settings')])
    name = escape(update.effective_user.first_name[:80])
    text = f'🦉 <b>Morning Quiz</b>\n\nПривет, {name}!\nВыбери игру — Филиныч уже приготовил вопросы.\n\n<i>Классика и фото — в чате. Прогресс и рейтинги — всегда под рукой.</i>'
    if context.bot_data.get('telegram_private_test'):
        text += '\n\n<code>DEV · личный тест · расписания выключены</code>'
    await card(update, context, text, rows)
    return ConversationHandler.END


async def navigate(update, context):
    query = update.callback_query
    if not query:
        return
    await acknowledge(query)
    action = {'start_mystats': 'nav:profile', 'start_global_top': 'nav:rating',
              'start_help': 'nav:help', 'start_categories': 'nav:categories'}.get(query.data, query.data)
    back = [Button('‹ Главное меню', callback_data='nav:home')]
    config = context.bot_data['app_config']
    dm = context.bot_data.get('data_manager')
    if action == 'nav:home':
        return await home(update, context)
    if action == 'nav:help':
        text = ('❔ <b>Два способа играть</b>\n\n'
                '<b>Классический квиз</b>\nВыбери количество вопросов, время и темы. Отвечай кнопками в опросе.\n\n'
                '<b>Фото-квиз</b>\nУгадывай изображение и пиши ответ в чат. Подсказки можно включить перед стартом.\n\n'
                '<b>Ночной город</b>\nСоздай групповое лобби командой /mafia. Стол и роли общие с Mini App.\n\n'
                '<b>Управление</b>\n/start — главное меню\n/cancel — выйти из настройки\n'
                '/stopquiz — остановить классический квиз\n/stop_photo_quiz — остановить фото-квиз\n\n'
                '<i>Очки и правила классики не изменены. Mini App не заменяет игру в чате.</i>')
    elif action == 'nav:categories':
        categories = dm.category_manager.get_all_category_names(chat_id=update.effective_chat.id) if dm else []
        names = sorted(str(name) for name in categories)
        text = '📚 <b>Темы квиза</b>\n\n' + ('\n'.join('• ' + escape(name[:70]) for name in names[:30]) if names else 'Открой /categories, чтобы посмотреть доступные темы и статистику.')
        if len(names) > 30:
            text += f'\n\nЕщё {len(names) - 30} тем — /categories'
        back = [Button('🎮 Выбрать темы и играть', callback_data='nav:quiz', style='primary')], back
        await card(update, context, text, list(back))
        return
    elif action in {'nav:profile', 'nav:rating', 'nav:chat_rating'}:
        from modules.score_manager import ScoreManager
        scores = ScoreManager(config, context.bot_data['bot_state'], dm)
        try:
            if action == 'nav:profile':
                uid = str(update.effective_user.id)
                profile = (await scores.get_session_profiles(update.effective_chat.id, [uid])).get(uid, {})
                local, total = profile.get('chat') or {}, profile.get('global') or {}
                text = (f'📊 <b>{escape(update.effective_user.first_name[:80])} · мой прогресс</b>\n\n'
                        f'В этом чате: <b>{local.get("score", 0)}</b> баллов\n'
                        f'Ответов в чате: <b>{local.get("answered_polls_count", 0)}</b>\n\n'
                        f'Всего: <b>{total.get("total_score", 0)}</b> баллов\n'
                        f'Ответов всего: <b>{total.get("answered_polls", 0)}</b>\n\n<i>Данные из того же хранилища, что и у квиза.</i>')
            else:
                local = action == 'nav:chat_rating'
                rating = await scores.get_chat_rating(update.effective_chat.id, top_n=10) if local else await scores.get_global_rating(top_n=10)
                title = '🏆 Рейтинг чата' if local else '🌍 Общий рейтинг'
                text = title + '\n\n' + ('Результатов пока нет. Сыграем?' if not rating else '')
                for index, item in enumerate(rating, 1):
                    text += f'{index}. {escape(str(item.get("name", "Игрок"))[:60])} — <b>{item.get("score", 0)}</b>\n'
                await card(update, context, text, [[Button('Общий', callback_data='nav:rating'), Button('Этот чат', callback_data='nav:chat_rating')], back])
                return
        except Exception:
            logger.exception('Navigation statistics unavailable')
            text = '📊 <b>Не удалось обновить данные</b>\n\nПопробуй ещё раз. Твои результаты сохранены.'
    else:
        text = 'Эта кнопка устарела. Открой главное меню и выбери действие заново.'
    await card(update, context, text, [back])


def navigation_guard():
    async def guard(update, context):
        query = update.callback_query
        if not query or not isinstance(query.data, str):
            return
        key = ('_quiz_cfg_msg_id' if query.data.startswith('qcfg_') else
               'admin_cfg_msg_id' if query.data.startswith('admcfg_') else
               '_photo_quiz_cfg_msg_id' if query.data.startswith('pqcfg_') else None)
        if key is None:
            return
        if key == 'admin_cfg_msg_id':
            from utils import is_user_admin_in_update
            if not await is_user_admin_in_update(update, context):
                await acknowledge(query, 'Настройки доступны администратору чата.', alert=True)
                raise ApplicationHandlerStop
        current = context.chat_data.get(key)
        if not current or not query.message or query.message.message_id != current:
            await acknowledge(query, 'Это старое меню. Открой /start и выбери действие заново.', alert=True)
            raise ApplicationHandlerStop
    return TypeHandler(Update, guard)
