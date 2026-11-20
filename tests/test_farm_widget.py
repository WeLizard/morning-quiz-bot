"""Farm card widget (pilot W1): card projection, widget limits, bot handler, and real PostgreSQL commands."""
import asyncio
from contextlib import asynccontextmanager
import json

import pytest
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, Defaults, ExtBot
from telegram.request import BaseRequest

from handlers.farm_widget_handlers import (NO_FARM, STALE, FarmUnavailable, FarmWidgetHandlers, fit_answer,
                                           fit_state)
from modules.telegram_widgets import MAX_ANSWER_BYTES, check_html
from qw_farm.domain import FarmError, new_farm
from qw_farm.expansion import upgrade_state
from qw_farm.telegram_card import caption, card_state, ready_count, ready_now, render_html
from tests.test_farm_platform import environment, farm_pg_url, player, raw_farm  # noqa: F401 (PG fixture)

NOW = 1_800_000_000
PLAYER = 501
LINK = 'https://t.me/QuizzyWizzyBot/play?startapp=farm'


def farm(now=NOW):
    value = upgrade_state(new_farm('00000000-0000-0000-0000-000000000001', 'Тест', now))
    plots = [obj for obj in value['objects'] if obj['type'] == 'plot']
    plots[0]['crop']['ready_at'] = now - 5        # ready
    plots[1]['crop']['ready_at'] = now + 120      # in two minutes
    return value


# ---------------------------------------------------------------- pure card

def test_card_counts_exactly_what_collect_all_would_harvest():
    value = farm()
    state = card_state(value, NOW)
    assert state['k'] == len(ready_now(value, NOW)) == 1
    assert NOW + 120 in state['t'] and state['t'] == sorted(state['t']) and min(state['t']) > NOW
    assert ready_count(state, NOW) == 1
    assert ready_count(state, NOW + 121) == 1 + sum(at <= NOW + 121 for at in state['t'])
    assert state['r'] == value['revision'] and state['c'] == value['coins']


def test_card_orders_show_goods_reward_and_whether_they_can_be_delivered():
    value = farm()
    [first] = card_state(value, NOW)['o'][:1]
    slot, npc, text, can, coins = first
    assert slot == 0 and npc and 'Пшеница ×6' in text and can == 1 and coins > 0
    value['inventory']['wheat'] = 0
    assert card_state(value, NOW)['o'][0][3] == 0


def test_card_state_fits_in_the_message_state_and_answers():
    value = farm()
    for index, obj in enumerate(o for o in value['objects'] if o['type'] == 'plot'):
        if obj.get('crop'):
            obj['crop']['ready_at'] = NOW + 1000 + index
    state = card_state(value, NOW)
    assert len(json.dumps(fit_state(state), ensure_ascii=False, separators=(',', ':')).encode()) <= 1024
    big = dict(state, t=list(range(NOW, NOW + 400)))
    text = fit_answer(big, m='Урожай собран: 12 гряд.')
    assert len(text.encode()) <= MAX_ANSWER_BYTES and json.loads(text)['st']['k'] == state['k']


def test_widget_html_fits_telegram_limits_and_bakes_only_a_t_me_link():
    raw, compressed = check_html(render_html(LINK))
    assert raw <= 32768 and compressed <= 3000  # keep head-room under the 4096-byte cap
    html = render_html(LINK)
    assert LINK in html and '__OPEN_URL__' not in html
    assert 'innerHTML' not in html and 'fetch(' not in html
    assert 'OPEN=""' in render_html(None)
    for bad in ('https://example.org/farm', 'https://t.me/x"onload', 'javascript:alert(1)'):
        with pytest.raises(ValueError):
            render_html(bad)


def test_caption_is_useful_without_widget_support():
    state = card_state(farm(), NOW)
    assert 'готово к сбору — 1' in caption(state, NOW)
    assert 'обнови Telegram' in caption(state, NOW)


# ---------------------------------------------------------------- handler with a fake farm service

class RecordingRequest(BaseRequest):
    def __init__(self, refuse=()):
        self.calls, self.refuse = [], set(refuse)

    @property
    def read_timeout(self):
        return 1

    async def initialize(self):
        pass

    async def shutdown(self):
        pass

    async def do_request(self, url, method, request_data=None, **kwargs):
        endpoint = url.rsplit('/', 1)[-1]
        fields = dict(request_data.json_parameters) if request_data else {}
        self.calls.append((endpoint, fields))
        if endpoint in self.refuse:
            return 400, json.dumps({'ok': False, 'error_code': 400,
                                    'description': 'Bad Request: INPUT_MEDIA_WIDGET_NOT_ALLOWED'}).encode()
        if endpoint == 'getMe':
            result = {'id': 1, 'is_bot': True, 'first_name': 'Bot', 'username': 'QuizzyWizzyBot'}
        elif endpoint in {'sendWidget', 'sendMessage'}:
            result = {'message_id': 9, 'date': NOW, 'chat': {'id': PLAYER, 'type': 'private', 'first_name': 'P'}}
        else:
            result = True
        return 200, json.dumps({'ok': True, 'result': result}).encode()


class FakeService:
    def __init__(self, value, refuse=None):
        self.farm, self.commands, self.refuse = value, [], refuse

    async def view(self):
        return {'farm': self.farm}

    async def command(self, key, kind, data):
        self.commands.append((key, kind, data))
        if self.refuse:
            raise FarmError('nothing_ready', self.refuse)
        self.farm['revision'] += 1
        return {'notice': 'Урожай собран: 1 гряд.'}


def handlers_with(service=None, unavailable=None):
    @asynccontextmanager
    async def scope(user_id):
        assert user_id == PLAYER
        if unavailable:
            raise FarmUnavailable(unavailable)
        yield service
    return FarmWidgetHandlers(service_scope=scope, clock=lambda: NOW)


def widget_update(bot, data, chat_id=PLAYER):
    return Update.de_json({'update_id': 1, 'widget_query': {
        'id': '8123456789012345678', 'from': {'id': PLAYER, 'is_bot': False, 'first_name': 'P'},
        'chat': {'id': chat_id, 'type': 'private' if chat_id == PLAYER else 'group'}, 'message_id': 9,
        'chat_instance': 'ci', 'type': {'type': 'data'}, 'data': data}}, bot)


def command_update(bot):
    return Update.de_json({'update_id': 2, 'message': {
        'message_id': 3, 'date': NOW, 'chat': {'id': PLAYER, 'type': 'private', 'first_name': 'P'},
        'from': {'id': PLAYER, 'is_bot': False, 'first_name': 'P'}, 'text': '/farm',
        'entities': [{'type': 'bot_command', 'offset': 0, 'length': 5}]}}, bot)


def run(handlers, make_update, refuse=()):
    request = RecordingRequest(refuse)

    async def scenario():
        bot = ExtBot('123:TEST', request=request, defaults=Defaults(parse_mode=ParseMode.MARKDOWN_V2))
        app = Application.builder().bot(bot).updater(None).build()
        app.add_handlers(handlers.get_handlers())
        await app.initialize()
        try:
            await app.process_update(make_update(app.bot))
        finally:
            await app.shutdown()
    asyncio.run(scenario())
    return request


def answers(request):
    return [json.loads(fields['data']) for name, fields in request.calls if name == 'answerWidgetQuery']


def edits(request):
    return [fields for name, fields in request.calls if name == 'editMessageWidgetData']


def test_sync_answers_the_card_without_editing_an_unchanged_message():
    value = farm()
    request = run(handlers_with(FakeService(value)), lambda bot: widget_update(bot, f"farm:sync:{value['revision']}"))
    [answer] = answers(request)
    assert answer['st']['k'] == 1 and 'err' not in answer
    assert edits(request) == []


def test_sync_refreshes_the_message_state_when_the_farm_moved_on():
    value = farm()
    request = run(handlers_with(FakeService(value)), lambda bot: widget_update(bot, 'farm:sync:7'))
    [edit] = edits(request)
    assert edit['chat_id'] == str(PLAYER) and edit['message_id'] == '9'
    assert json.loads(edit['chat_data'])['r'] == value['revision']


def test_collect_all_runs_the_farm_command_with_an_idempotency_key():
    service = FakeService(farm())
    request = run(handlers_with(service), lambda bot: widget_update(bot, 'farm:all:0'))
    [(key, kind, data)] = service.commands  # revision 0 -> 1: the message state is refreshed
    assert kind == 'collect_all' and data == {} and key.startswith('tgw-farm:') and 8 <= len(key) <= 64
    [answer] = answers(request)
    assert answer['m'].startswith('Урожай собран') and answer['st']['r'] == service.farm['revision']
    assert len(edits(request)) == 1


def test_order_from_a_stale_card_is_refused_with_a_fresh_card():
    service = FakeService(farm())
    request = run(handlers_with(service), lambda bot: widget_update(bot, 'farm:ord:0:999'))
    assert service.commands == []
    [answer] = answers(request)
    assert answer['err'] == STALE and 'st' in answer


def test_order_delivers_the_order_in_that_slot():
    service = FakeService(farm())
    revision = service.farm['revision']
    run(handlers_with(service), lambda bot: widget_update(bot, f'farm:ord:0:{revision}'))
    [(_, kind, data)] = service.commands
    assert kind == 'order' and data == {'order': 'order_0'}


def test_farm_refusal_is_shown_over_a_fresh_card():
    service = FakeService(farm(), refuse='Пока ничего не созрело.')
    request = run(handlers_with(service), lambda bot: widget_update(bot, 'farm:all:0'))
    [answer] = answers(request)
    assert answer['err'] == 'Пока ничего не созрело.' and answer['st']['k'] == 1


def test_no_farm_and_foreign_chats_get_an_answer_not_a_timeout():
    request = run(handlers_with(unavailable=NO_FARM), lambda bot: widget_update(bot, 'farm:sync:0'))
    assert answers(request) == [{'err': NO_FARM}]
    request = run(handlers_with(FakeService(farm())), lambda bot: widget_update(bot, 'farm:sync:0', chat_id=-100))
    assert 'err' in answers(request)[0]
    request = run(handlers_with(FakeService(farm())), lambda bot: widget_update(bot, 'farm:drop:tables'))
    assert 'err' in answers(request)[0]


def test_farm_command_sends_the_widget_with_caption_state_and_queries():
    value = farm()
    request = run(handlers_with(FakeService(value)), command_update)
    [(name, fields)] = [call for call in request.calls if call[0] == 'sendWidget']
    assert fields['allow_queries'] == 'true' and LINK in fields['html']
    assert 'готово к сбору — 1' in fields['caption']
    assert json.loads(fields['chat_data'])['r'] == value['revision']


def test_farm_command_falls_back_to_a_text_card_when_telegram_refuses_the_widget():
    request = run(handlers_with(FakeService(farm())), command_update, refuse={'sendWidget'})
    [(name, fields)] = [call for call in request.calls if call[0] == 'sendMessage']
    assert 'готово к сбору — 1' in fields['text'] and 'обнови Telegram' not in fields['text']
    assert 'parse_mode' not in fields
    [[button]] = json.loads(fields['reply_markup'])['inline_keyboard']
    assert button['text'] == 'Открыть ферму' and button['url'] == LINK


def test_farm_command_without_a_farm_explains_what_to_do():
    request = run(handlers_with(unavailable=NO_FARM), command_update)
    [(name, fields)] = [call for call in request.calls if call[0] == 'sendMessage']
    assert fields['text'] == NO_FARM and 'parse_mode' not in fields


# ---------------------------------------------------------------- real FarmService in PostgreSQL (CI)

def test_widget_commands_change_the_real_farm_once(farm_pg_url):
    async def scenario():
        async with environment(farm_pg_url) as env:
            async with player(env, 'telegram', user_id=981020000077) as p:
                handlers = FarmWidgetHandlers(env.db, clock=lambda: env.now[0])
                state = await handlers._state(p.user_id)
                before = await raw_farm(env, p)
                assert state['r'] == before['revision'] and state['k'] == len(ready_now(before, env.now[0]))
                wheat = before['inventory'].get('wheat', 0)
                if state['k']:
                    after, notice = await handlers._act(p.user_id, 'tgw-farm:pg-1', 'all', 0, state['r'])
                    assert after['k'] == 0 and notice
                    harvested = (await raw_farm(env, p))['inventory'].get('wheat', 0)
                    assert harvested > wheat
                    # The same tap replayed (same key) is a receipt, not a second harvest.
                    await handlers._act(p.user_id, 'tgw-farm:pg-1', 'all', 0, after['r'])
                    assert (await raw_farm(env, p))['inventory'].get('wheat', 0) == harvested
                    state = after
                stale, message = await handlers._act(p.user_id, 'tgw-farm:pg-2', 'ord', 0, state['r'] + 50)
                assert stale is None and message == STALE
                with pytest.raises(FarmUnavailable):
                    await handlers._state(981020000099)  # a Telegram user without an account/farm

    asyncio.run(scenario())

