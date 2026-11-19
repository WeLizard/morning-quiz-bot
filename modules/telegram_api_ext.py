"""Bot API 10.1-10.4 features on top of python-telegram-bot 22.8 (Bot API 10.0).

PTB 22.8 is the newest release on PyPI and natively knows Bot API 10.0. Newer methods and
fields are reached through the library's own escape hatches, so nothing is monkey-patched:

* unknown request parameters go in ``api_kwargs`` of a regular PTB method;
* unknown methods go through ``Bot.do_api_request``;
* unknown response fields land in ``TelegramObject.api_kwargs`` (read them with ``extra``).

When PTB gains native support, swap the helpers' bodies; callers keep the same signatures.
Ephemeral replies: https://core.telegram.org/bots/api#ephemeral-messages-and-commands
"""
import logging

import telegram
from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest

logger = logging.getLogger(__name__)

TARGET_BOT_API = '10.4'
# Update fields added after Bot API 10.0 that the bot wants to receive. getUpdates delivers
# only listed types once allowed_updates is passed, so new ones must be named explicitly.
WIDGET_UPDATE_TYPES = ('widget_query', 'shared_widget_query')


def api_support():
    """Versions for the startup log and diagnostics."""
    return {'ptb': telegram.__version__, 'ptb_bot_api': telegram.__bot_api_version__,
            'target_bot_api': TARGET_BOT_API}


def allowed_updates():
    """Every type PTB knows plus the widget queries, in a stable order without duplicates."""
    return list(dict.fromkeys([*Update.ALL_TYPES, *WIDGET_UPDATE_TYPES]))


def extra(obj, key, default=None):
    """A response field PTB does not model yet (it keeps those in ``api_kwargs``)."""
    if obj is None:
        return default
    return (getattr(obj, 'api_kwargs', None) or {}).get(key, default)


def without_none(params):
    return {key: value for key, value in params.items() if value is not None}


def _keep_empty_strings(params):
    """PTB 22.8 ``ExtBot`` with ``Defaults`` turns an empty-string parameter into ``[]``: its
    InputPollOption branch runs ``all()`` over the (empty) string. ``''`` is meaningful here (it clears
    widget state), so wrap it in ``DefaultValue``, which both Bot and ExtBot unwrap to the plain value."""
    from telegram._utils.defaultvalue import DefaultValue
    return {key: DefaultValue('') if isinstance(value, str) and not value else value for key, value in params.items()}


async def call(bot, method, params, *, return_type=None):
    """A Bot API method PTB 22.8 lacks; ``None`` parameters are dropped, objects serialised by PTB."""
    return await bot.do_api_request(method, api_kwargs=_keep_empty_strings(without_none(params)),
                                    return_type=return_type)


def not_modified(error):
    return isinstance(error, BadRequest) and 'not modified' in str(error).lower()


# ---------------------------------------------------------------- buttons and commands

def disabled_button(text):
    """An inline button that does nothing (Bot API 10.3), e.g. a used or locked action."""
    return InlineKeyboardButton(text, api_kwargs={'disabled': {}})


def ephemeral_command(command, description):
    """A command only the sender and the bot see in a group (Bot API 10.2)."""
    return BotCommand(command, description, api_kwargs={'is_ephemeral': True})


# ---------------------------------------------------------------- ephemeral messages

def ephemeral_parameters(*, callback_query_id=None, receiver_user_id=None, replace_callback_query_message=False):
    """``EphemeralMessageParameters`` (Bot API 10.3/10.4).

    * ``callback_query_id`` alone: a reply only the user who pressed the button sees, on the client
      they pressed it in, within 15 seconds of the press. Any chat except channel DM chats.
    * ``receiver_user_id``: an initiative message to a group member; the bot must be an admin.
    * ``replace_callback_query_message``: show the reply in place of the pressed card, for that user only.
      Not for buttons on an ephemeral card: edit those with ``edit_ephemeral_text`` instead.
    Delivery is never guaranteed: keep the source of truth on the server and allow re-opening.
    """
    if callback_query_id is None and receiver_user_id is None:
        raise ValueError('An ephemeral message needs callback_query_id or receiver_user_id')
    if replace_callback_query_message and callback_query_id is None:
        raise ValueError('replace_callback_query_message needs callback_query_id')
    if receiver_user_id is not None and (type(receiver_user_id) is not int or receiver_user_id <= 0):
        raise ValueError('receiver_user_id must be a user id')
    params = without_none({'callback_query_id': callback_query_id, 'receiver_user_id': receiver_user_id})
    if replace_callback_query_message:
        params['replace_callback_query_message'] = True
    return params


def check_ephemeral_markup(reply_markup):
    """Telegram refuses web_app and login_url buttons on ephemeral messages; fail before the request."""
    if reply_markup is None:
        return
    if not isinstance(reply_markup, InlineKeyboardMarkup):
        raise ValueError('Ephemeral messages take only an inline keyboard')
    for row in reply_markup.inline_keyboard:
        for button in row:
            if button.web_app is not None or button.login_url is not None:
                raise ValueError('web_app and login_url buttons are not supported in ephemeral messages')


def ephemeral_message_id(message):
    """``Message.ephemeral_message_id``: ephemeral messages have ``message_id == 0``."""
    value = extra(message, 'ephemeral_message_id')
    return value if type(value) is int else None


async def send_ephemeral_text(bot, *, chat_id, text, callback_query_id=None, receiver_user_id=None,
                              replace_callback_query_message=False, reply_markup=None, parse_mode=None):
    """``sendMessage`` with ``ephemeral_message_parameters``; returns the Message (``message_id`` 0).

    ``parse_mode=None`` sends plain text and overrides the application's MarkdownV2 default.
    """
    check_ephemeral_markup(reply_markup)
    params = ephemeral_parameters(callback_query_id=callback_query_id, receiver_user_id=receiver_user_id,
                                  replace_callback_query_message=replace_callback_query_message)
    return await bot.send_message(chat_id=chat_id, text=text, parse_mode=parse_mode, reply_markup=reply_markup,
                                  api_kwargs={'ephemeral_message_parameters': params})


async def reply_privately(query, text, *, reply_markup=None, replace=False, parse_mode=None,
                          fallback_alert=True, answer_text=None):
    """Answer a callback query with a card only the presser sees, then acknowledge the press.

    Returns the ephemeral Message, or ``None`` when Telegram refused it; then, with ``fallback_alert``,
    the presser gets the first 200 characters as an alert instead (no secret ever goes to the chat).
    The callback query is always answered, as the API requires.
    """
    message = query.message
    chat_id = message.chat.id if message is not None else query.from_user.id
    try:
        sent = await send_ephemeral_text(query.get_bot(), chat_id=chat_id, text=text, callback_query_id=query.id,
                                         replace_callback_query_message=replace, reply_markup=reply_markup,
                                         parse_mode=parse_mode)
    except BadRequest:
        logger.warning('Ephemeral reply refused for callback in chat %s', chat_id, exc_info=True)
        if fallback_alert:
            await query.answer(text[:200], show_alert=True)
        else:
            await query.answer(answer_text)
        return None
    await query.answer(answer_text)
    return sent


async def edit_ephemeral_text(bot, *, chat_id, receiver_user_id, ephemeral_message_id, text,
                              reply_markup=None, parse_mode=None):
    check_ephemeral_markup(reply_markup)
    try:
        return await call(bot, 'editEphemeralMessageText', {
            'chat_id': chat_id, 'receiver_user_id': receiver_user_id,
            'ephemeral_message_id': ephemeral_message_id, 'text': text,
            'parse_mode': parse_mode, 'reply_markup': reply_markup})
    except BadRequest as error:
        if not_modified(error):
            return True
        raise


async def edit_ephemeral_reply_markup(bot, *, chat_id, receiver_user_id, ephemeral_message_id, reply_markup=None):
    check_ephemeral_markup(reply_markup)
    try:
        return await call(bot, 'editEphemeralMessageReplyMarkup', {
            'chat_id': chat_id, 'receiver_user_id': receiver_user_id,
            'ephemeral_message_id': ephemeral_message_id, 'reply_markup': reply_markup})
    except BadRequest as error:
        if not_modified(error):
            return True
        raise


async def delete_ephemeral(bot, *, chat_id, receiver_user_id, ephemeral_message_id):
    return await call(bot, 'deleteEphemeralMessage', {
        'chat_id': chat_id, 'receiver_user_id': receiver_user_id, 'ephemeral_message_id': ephemeral_message_id})


# ---------------------------------------------------------------- update identity

def update_identity(update):
    """(chat_id, user_id) of any update, including widget queries PTB does not model yet."""
    chat = update.effective_chat
    user = update.effective_user
    if chat is None and user is None:
        query = extra(update, 'widget_query') or extra(update, 'shared_widget_query')
        if isinstance(query, dict):
            sender = query.get('from') or {}
            source = query.get('chat') or {}
            return source.get('id'), sender.get('id')
    return (chat.id if chat else None), (user.id if user else None)
