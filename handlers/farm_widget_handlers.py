"""Farm card in the private chat with the bot (Bot API 10.4 widget), pilot W1.

``/farm`` in the private chat sends a live card of the player's own farm. Taps in the card arrive
as widget queries and run the same FarmService commands as the Mini App, in the same PostgreSQL,
with the same idempotency receipts. Nothing new is stored: every query carries the chat and the
message, which is all the bot needs to answer and to refresh the card's state.

Requests (at most 64 bytes):  farm:sync:<rev>  ·  farm:all:<rev>  ·  farm:ord:<slot>:<rev>
Answers (at most 1024 bytes): {"st": <card state>, "m": notice} or {"err": text[, "st": ...]}
"""
from contextlib import asynccontextmanager
import logging
import os
import re
import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest
from telegram.ext import CommandHandler, filters

from modules.mini_app_launch import short_name_from_env, startapp_url
from modules.telegram_widgets import MAX_ANSWER_BYTES, WidgetQueryHandler, edit_widget_data, pack_state, send_widget

logger = logging.getLogger(__name__)

QUERY = re.compile(r'farm:(sync|all|ord)(?::(\d{1,2}))?:(\d{1,12})')
UNAVAILABLE = 'Ферма сейчас недоступна. Попробуй позже.'
NO_FARM = 'Сначала открой ферму в приложении QuizzyWizzy.'
STALE = 'Ферма изменилась — проверь карточку и нажми ещё раз.'


class FarmUnavailable(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message


class _Refused(Exception):
    """The farm refused the action (FarmError); the transaction is rolled back."""


def farm_enabled():
    return os.getenv('QW_FARM_ENABLED') == '1'


def fit_answer(state, **extra):
    """Answer with the state; drop future harvest times (never counts or orders) until it fits."""
    import json
    state = dict(state, t=list(state['t']))
    while True:
        body = dict(extra, st=state)
        text = json.dumps(body, ensure_ascii=False, separators=(',', ':'))
        if len(text.encode('utf-8')) <= MAX_ANSWER_BYTES or not state['t']:
            return text
        state['t'] = state['t'][:len(state['t']) // 2]


class FarmWidgetHandlers:
    """Handlers for the farm card; ``service_scope`` is injectable for tests."""

    def __init__(self, database=None, *, service_scope=None, clock=time.time):
        self.database = database
        self.clock = clock
        self.service_scope = service_scope or self._service_scope

    def get_handlers(self):
        return [CommandHandler('farm', self.send_card, filters=filters.ChatType.PRIVATE),
                WidgetQueryHandler(self.on_query, prefix='farm')]

    @asynccontextmanager
    async def _service_scope(self, telegram_user_id):
        """One transaction with the same identity rules as the Mini App (web/principal.py)."""
        if self.database is None or not farm_enabled():
            raise FarmUnavailable(UNAVAILABLE)
        from domain.address import effective_address_form
        from qw_farm.integration import register_models
        from qw_farm.persistence import Unit
        from qw_farm.service import FarmService, Principal
        from storage.admin_actions import operation_fence
        from storage.models import User
        from storage.telegram_accounts import TelegramAccountUnavailable, telegram_account
        schema = register_models()
        async with self.database.transaction() as session:
            await operation_fence(session)
            user = await session.get(User, telegram_user_id, with_for_update=True, populate_existing=True)
            if user is None:
                raise FarmUnavailable(NO_FARM)
            try:
                account = await telegram_account(session, user, lock=True)
            except TelegramAccountUnavailable:
                raise FarmUnavailable(NO_FARM) from None
            principal = Principal(str(account.id), account.display_name, 'telegram',
                                  effective_address_form(account.address_form),
                                  bool(getattr(account, 'contrast_mode', False)))
            yield FarmService(Unit(session, schema), principal, clock=self.clock, speed=1)

    async def _state(self, telegram_user_id):
        from qw_farm.domain import FarmError
        from qw_farm.telegram_card import card_state
        async with self.service_scope(telegram_user_id) as service:
            try:
                view = await service.view()
            except FarmError as error:
                raise FarmUnavailable(NO_FARM if error.code == 'farm_not_started' else error.message) from None
            return card_state(view['farm'], self.clock())

    async def _act(self, telegram_user_id, key, action, slot, revision):
        """Run one command; a FarmError rolls the transaction back and is shown to the player."""
        from qw_farm.domain import FarmError
        from qw_farm.telegram_card import card_state
        async with self.service_scope(telegram_user_id) as service:
            try:
                view = await service.view()
                farm = view['farm']
                if action == 'ord':
                    if farm['revision'] != revision:
                        return None, STALE
                    order = next((o for o in farm.get('orders', []) if o['slot'] == slot), None)
                    if order is None:
                        return None, STALE
                    result = await service.command(key, 'order', {'order': order['id']})
                else:
                    result = await service.command(key, 'collect_all', {})
                farm = (await service.view())['farm']
                return card_state(farm, self.clock()), result.get('notice') or 'Готово.'
            except FarmError as error:
                if error.code == 'farm_not_started':
                    raise FarmUnavailable(NO_FARM) from None
                raise _Refused(error.message) from None

    async def on_query(self, update, context):
        query = context.widget_query
        match = QUERY.fullmatch(query.data)
        if match is None or query.shared_forward or query.chat_id != query.user_id:
            await context.answer_widget({'err': 'Эта карточка здесь не работает.'})
            return
        action, slot, revision = match.group(1), int(match.group(2) or 0), int(match.group(3))
        notice = None
        try:
            if action == 'sync':
                state = await self._state(query.user_id)
            else:
                try:
                    state, notice = await self._act(query.user_id, 'tgw-farm:' + query.id[-50:], action, slot, revision)
                except _Refused as refused:
                    state, notice = None, str(refused)
                if state is None:  # stale or refused: show the error over a fresh card
                    error = notice
                    state = await self._state(query.user_id)
                    await context.answer_widget(fit_answer(state, err=error))
                    await self._refresh(context, query, state, revision)
                    return
        except FarmUnavailable as unavailable:
            await context.answer_widget({'err': unavailable.message})
            return
        await context.answer_widget(fit_answer(state, **({'m': notice} if notice else {})))
        await self._refresh(context, query, state, revision)

    async def _refresh(self, context, query, state, seen_revision):
        """Keep the message's own state current, so a re-created widget draws the latest card."""
        if query.message_id is None or state['r'] == seen_revision:
            return
        try:
            await edit_widget_data(context.bot, chat_id=query.chat_id, message_id=query.message_id,
                                   chat_data=pack_state(fit_state(state)))
        except Exception:
            logger.warning('Farm card state not refreshed for message %s', query.message_id, exc_info=True)

    async def send_card(self, update, context):
        from qw_farm.telegram_card import caption, render_html
        user = update.effective_user
        message = update.effective_message
        try:
            state = await self._state(user.id)
        except FarmUnavailable as unavailable:
            await message.reply_text(unavailable.message, parse_mode=None)
            return
        try:
            link = startapp_url(context.bot.username, 'farm', short_name_from_env())
        except ValueError:
            link = None
        text = caption(state, self.clock())
        try:
            await send_widget(context.bot, chat_id=message.chat_id, html=render_html(link),
                              caption=text, chat_data=pack_state(fit_state(state)), allow_queries=True)
        except BadRequest as refused:
            # Telegram may refuse widgets for this bot or chat (e.g. Input_media_widget_not_allowed):
            # the player still gets the farm summary and a way into the Mini App.
            logger.warning('sendWidget refused for the farm card: %s', refused.message)
            markup = (InlineKeyboardMarkup([[InlineKeyboardButton('Открыть ферму', url=link)]])
                      if link else None)
            summary = text.split('\n', 1)[0] + '\nСобрать урожай и сдать заказы можно на ферме.'
            await message.reply_text(summary, parse_mode=None, reply_markup=markup)


def fit_state(state):
    """The message state has the same 1024-byte cap as an answer, without the wrapper."""
    import json
    state = dict(state, t=list(state['t']))
    while len(json.dumps(state, ensure_ascii=False, separators=(',', ':')).encode('utf-8')) > 1024 and state['t']:
        state['t'] = state['t'][:len(state['t']) // 2]
    return state
