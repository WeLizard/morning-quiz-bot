"""HTML widgets (Bot API 10.4) over python-telegram-bot 22.8.

A widget is fixed HTML plus small state that only the bot writes; it talks to the bot only through
64-byte requests that arrive as ``widget_query`` updates. Production Telegram currently allows widgets
only in the private chat with the bot (groups, inline mode and forwards: test server only), and sent
widgets are protected from forwarding there.

Rules kept here, not in every game:
* size limits are checked before the request (32 KB of HTML, 4 KB after zlib level 9, 1 KB of state);
* state is compact JSON with a revision ``r`` so a widget can drop an older state;
* every query is answered within 15 s, also on errors, or the widget shows TIMEOUT;
* the query never carries the widget's state: games check ``data`` against their server state.
Guide: https://core.telegram.org/bots/widgets
"""
import json
import logging
import zlib
from dataclasses import dataclass
from typing import Optional

from telegram import Message
from telegram.error import BadRequest
from telegram.ext import BaseHandler

from modules.telegram_api_ext import call, extra, not_modified

logger = logging.getLogger(__name__)

MAX_HTML_BYTES = 32768
MAX_COMPRESSED_BYTES = 4096
MAX_STATE_BYTES = 1024
MAX_QUERY_BYTES = 64
MAX_ANSWER_BYTES = 1024
ANSWER_DEADLINE_SECONDS = 15
CACHE_TIME_RANGE = (5, 3600)


class WidgetTooLarge(ValueError):
    pass


def html_size(html):
    """(UTF-8 bytes, bytes after zlib level 9): Python's zlib counts exactly as Telegram does."""
    raw = html.encode('utf-8')
    return len(raw), len(zlib.compress(raw, 9))


def check_html(html):
    if not isinstance(html, str) or not html:
        raise ValueError('Widget HTML must be a non-empty string')
    if '\x00' in html:
        raise ValueError('Widget HTML must not contain NUL')
    raw, compressed = html_size(html)
    if raw > MAX_HTML_BYTES or compressed > MAX_COMPRESSED_BYTES:
        raise WidgetTooLarge(f'Widget HTML is {raw} B ({compressed} B compressed); '
                             f'limits {MAX_HTML_BYTES} B / {MAX_COMPRESSED_BYTES} B')
    return raw, compressed


def check_text(value, limit, what):
    if value is None:
        return None
    if not isinstance(value, str) or '\x00' in value:
        raise ValueError(f'{what} must be text without NUL')
    if len(value.encode('utf-8')) > limit:
        raise WidgetTooLarge(f'{what} is over {limit} bytes')
    return value


def pack_state(state, *, revision=None):
    """Compact JSON for chat_data / public_data; ``revision`` goes in as ``r``. None clears nothing."""
    if state is None:
        return None
    if revision is not None:
        if not isinstance(state, dict):
            raise ValueError('A revision needs a dict state')
        state = {**state, 'r': revision}
    text = json.dumps(state, ensure_ascii=False, separators=(',', ':'))
    return check_text(text, MAX_STATE_BYTES, 'Widget state')


def unpack(text):
    if not text:
        return None
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return None


def widget_of(message):
    """``Message.widget`` as a dict (id, html, width, height, public_data, chat_data), or None."""
    value = extra(message, 'widget')
    return value if isinstance(value, dict) else None


def _size(value, what):
    if value is None:
        return None
    if type(value) is not int or value < 0:
        raise ValueError(f'{what} must be a non-negative integer')
    return value


async def send_widget(bot, *, chat_id, html, caption, public_data=None, chat_data=None, allow_queries=False,
                      is_shared=False, width=None, height=None, reply_markup=None, parse_mode=None,
                      disable_notification=None, protect_content=None, message_thread_id=None):
    """``sendWidget``. A caption is required here: it is what chat lists, search and old apps show."""
    check_html(html)
    if not isinstance(caption, str) or not caption.strip():
        raise ValueError('A widget needs a caption for chat lists and unsupported apps')
    return await call(bot, 'sendWidget', {
        'chat_id': chat_id, 'message_thread_id': message_thread_id, 'html': html,
        'width': _size(width, 'width'), 'height': _size(height, 'height'),
        'public_data': check_text(public_data, MAX_STATE_BYTES, 'public_data'),
        'chat_data': check_text(chat_data, MAX_STATE_BYTES, 'chat_data'),
        'caption': caption, 'parse_mode': parse_mode,
        'allow_queries': True if allow_queries else None, 'is_shared': True if is_shared else None,
        'disable_notification': disable_notification, 'protect_content': protect_content,
        'reply_markup': reply_markup}, return_type=Message)


async def send_shared_widget(bot, *, chat_id, widget_id, caption, chat_data=None, reply_markup=None,
                             parse_mode=None, disable_notification=None, message_thread_id=None):
    if not isinstance(widget_id, str) or not widget_id:
        raise ValueError('widget_id is required')
    return await call(bot, 'sendSharedWidget', {
        'chat_id': chat_id, 'message_thread_id': message_thread_id, 'widget_id': widget_id,
        'chat_data': check_text(chat_data, MAX_STATE_BYTES, 'chat_data'), 'caption': caption,
        'parse_mode': parse_mode, 'disable_notification': disable_notification,
        'reply_markup': reply_markup}, return_type=Message)


async def edit_widget_data(bot, *, chat_id=None, message_id=None, inline_message_id=None,
                           chat_data=None, public_data=None):
    """``editMessageWidgetData``; ``''`` clears a state, ``None`` keeps it. "Not modified" counts as done.

    Each call counts as a sent message against the bot's limits: coalesce bursts on the caller's side.
    """
    if inline_message_id is None and (chat_id is None or message_id is None):
        raise ValueError('Pass chat_id and message_id, or inline_message_id')
    if chat_data is None and public_data is None:
        raise ValueError('Nothing to change')
    try:
        return await call(bot, 'editMessageWidgetData', {
            'chat_id': chat_id, 'message_id': message_id, 'inline_message_id': inline_message_id,
            'chat_data': check_text(chat_data, MAX_STATE_BYTES, 'chat_data'),
            'public_data': check_text(public_data, MAX_STATE_BYTES, 'public_data')})
    except BadRequest as error:
        if not_modified(error):
            return True
        raise


async def edit_shared_widget_data(bot, *, widget_id, public_data, cache_time=None):
    """``editSharedWidgetData``: at most one edit per second per shared widget."""
    if cache_time is not None and not (type(cache_time) is int and cache_time >= CACHE_TIME_RANGE[0]):
        raise ValueError('cache_time must be an integer of at least 5 seconds')
    try:
        return await call(bot, 'editSharedWidgetData', {
            'widget_id': widget_id, 'public_data': check_text(public_data, MAX_STATE_BYTES, 'public_data') or '',
            'cache_time': min(cache_time, CACHE_TIME_RANGE[1]) if cache_time is not None else None})
    except BadRequest as error:
        if not_modified(error):
            return True
        raise


async def answer_widget_query(bot, query_id, data=None):
    """``answerWidgetQuery``; ``data`` (str, or a JSON-able value) reaches only the asking widget."""
    if data is not None and not isinstance(data, str):
        data = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
    return await call(bot, 'answerWidgetQuery', {
        'widget_query_id': query_id, 'data': check_text(data, MAX_ANSWER_BYTES, 'Widget answer')})


@dataclass(frozen=True)
class WidgetQuery:
    """A ``widget_query`` (from an original) or ``shared_widget_query`` (from a forward)."""
    id: str
    user_id: int
    data: str
    kind: str  # 'data', 'sign_data' or 'sent_transaction'
    shared_forward: bool
    chat_id: Optional[int] = None
    chat_type: Optional[str] = None
    message_id: Optional[int] = None
    inline_message_id: Optional[str] = None
    widget_id: Optional[str] = None
    raw: Optional[dict] = None

    @property
    def prefix(self):
        """The part before the first ':' — games route on it (``farm:harvest`` → ``farm``)."""
        return self.data.split(':', 1)[0]


def widget_query_of(update):
    """Parse the widget query of an Update, or return None for every other update."""
    raw, forward = extra(update, 'widget_query'), False
    if raw is None:
        raw, forward = extra(update, 'shared_widget_query'), True
    if not isinstance(raw, dict):
        return None
    sender = raw.get('from') or {}
    chat = raw.get('chat') or {}
    kind = (raw.get('type') or {}).get('type', 'data') if isinstance(raw.get('type'), dict) else 'data'
    if not isinstance(raw.get('id'), str) or type(sender.get('id')) is not int or not isinstance(raw.get('data'), str):
        logger.warning('Malformed widget query ignored: %r', sorted(raw))
        return None
    return WidgetQuery(
        id=raw['id'], user_id=sender['id'], data=raw['data'], kind=kind, shared_forward=forward,
        chat_id=chat.get('id'), chat_type=chat.get('type') or raw.get('chat_type'),
        message_id=raw.get('message_id'), inline_message_id=raw.get('inline_message_id'),
        widget_id=raw.get('widget_id'), raw=raw)


class WidgetQueryHandler(BaseHandler):
    """PTB handler for widget queries; ``prefix`` routes ``<prefix>:<payload>`` data to one game.

    The callback gets ``(update, context)`` with ``context.widget_query`` set. If it raises or returns
    without answering, the handler answers ``{"error":"failed"}`` so the widget never waits 15 s.
    """

    def __init__(self, callback, prefix=None, block=True):
        super().__init__(callback, block=block)
        self.prefix = prefix

    def check_update(self, update):
        query = widget_query_of(update)
        if query is None or query.kind != 'data':
            return None
        if self.prefix is not None and query.prefix != self.prefix:
            return None
        return query

    def collect_additional_context(self, context, update, application, check_result):
        context.widget_query = check_result

    async def handle_update(self, update, application, check_result, context):
        query: WidgetQuery = check_result  # type: ignore[assignment]
        answered = {'done': False}
        bot = context.bot

        async def answer(data=None):
            answered['done'] = True
            return await answer_widget_query(bot, query.id, data)

        context.answer_widget = answer
        try:
            return await super().handle_update(update, application, check_result, context)
        finally:
            if not answered['done']:
                try:
                    await answer_widget_query(bot, query.id, {'error': 'failed'})
                except Exception:
                    logger.warning('Widget query %s left unanswered', query.id, exc_info=True)
