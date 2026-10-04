"""Telegram helpers with bounded, delivery-aware retries."""
import logging
from functools import wraps
from typing import Optional, Union

from telegram import Bot, Message
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden

from modules.telegram_transport import telegram_request

logger = logging.getLogger(__name__)


class TelegramMessageError(Exception):
    """Base failure; the original Telegram exception is retained as __cause__."""


class MessageTooLongError(TelegramMessageError):
    pass


class UserBlockedError(TelegramMessageError):
    pass


class ChatNotFoundError(TelegramMessageError):
    pass


class PartialDeliveryError(TelegramMessageError):
    """Some chunks were acknowledged. Never replay the whole batch."""
    def __init__(self, messages):
        super().__init__('Message was only partly delivered; batch replay suppressed')
        self.messages = tuple(messages)


def is_formatting_error(error):
    """A plain-text fallback is safe only after an explicit content rejection."""
    if isinstance(error, PartialDeliveryError):
        return False
    if isinstance(error, MessageTooLongError):
        return True
    cause = error.__cause__ if isinstance(error, TelegramMessageError) else error
    return isinstance(cause, BadRequest) and any(fragment in str(cause).lower() for fragment in (
        "can't parse entities", "can't find end of", 'unsupported start tag',
        'message is too long', 'message_too_long',
    ))


def safe_telegram_call(max_retries=1, base_delay=0.1, max_delay=0.5,
                       exponential_base=1.5, *, idempotent=False):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                return await telegram_request(lambda: func(*args, **kwargs),
                    idempotent=idempotent, max_retries=max_retries,
                    base_delay=base_delay, max_delay=max_delay, exponential_base=exponential_base)
            except Forbidden as exc:
                raise UserBlockedError(str(exc)) from exc
            except BadRequest as exc:
                message = str(exc).lower()
                if 'chat not found' in message:
                    raise ChatNotFoundError(str(exc)) from exc
                if 'message is too long' in message or 'message_too_long' in message:
                    raise MessageTooLongError(str(exc)) from exc
                raise TelegramMessageError(str(exc)) from exc
            except TelegramMessageError:
                raise
            except Exception as exc:
                raise TelegramMessageError(str(exc)) from exc
        return wrapper
    return decorator


@safe_telegram_call(max_retries=2)
async def _send_message_part(bot, **kwargs):
    return await bot.send_message(**kwargs)


async def safe_send_message(
    bot: Bot, chat_id: Union[int, str], text: str,
    parse_mode: Optional[ParseMode] = None, **kwargs,
) -> Message:
    """Plain text splits losslessly; each chunk owns its retry budget.

    Rich text cannot safely split arbitrary entities: reject it before sending.
    Return the first message for legacy callers. PartialDeliveryError carries
    all acknowledged messages so callers can register cleanup without replay.
    """
    if len(text) > 4096 and parse_mode:
        raise MessageTooLongError('Rich text must be formatted into messages of at most 4096 characters')
    parts = [text[index:index + 4096] for index in range(0, len(text), 4096)] or [text]
    messages = []
    for part in parts:
        try:
            messages.append(await _send_message_part(
                bot, chat_id=chat_id, text=part, parse_mode=parse_mode, **kwargs))
        except Exception as exc:
            if messages:
                raise PartialDeliveryError(messages) from exc
            raise
    return messages[0]


@safe_telegram_call(max_retries=1, idempotent=True)
async def safe_edit_message(
    bot: Bot, chat_id: Union[int, str], message_id: int, text: str,
    parse_mode: Optional[ParseMode] = None, **kwargs,
) -> Message:
    return await bot.edit_message_text(
        chat_id=chat_id, message_id=message_id, text=text, parse_mode=parse_mode, **kwargs)


@safe_telegram_call(max_retries=1, idempotent=True)
async def safe_delete_message(bot: Bot, chat_id: Union[int, str], message_id: int) -> bool:
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
        return True
    except BadRequest as exc:
        if 'message to delete not found' in str(exc).lower():
            return False
        raise


def format_error_message(error, context=''):
    if isinstance(error, UserBlockedError):
        return 'Пользователь заблокировал бота или боту недоступен чат'
    if isinstance(error, ChatNotFoundError):
        return 'Чат не найден'
    if isinstance(error, MessageTooLongError):
        return 'Сообщение слишком длинное'
    if isinstance(error, TelegramMessageError):
        return f'Ошибка Telegram: {error}'
    return f'Произошла ошибка: {error}'


__all__ = [
    'safe_telegram_call', 'safe_send_message', 'safe_edit_message', 'safe_delete_message',
    'format_error_message', 'is_formatting_error', 'TelegramMessageError',
    'MessageTooLongError', 'UserBlockedError', 'ChatNotFoundError', 'PartialDeliveryError',
]
