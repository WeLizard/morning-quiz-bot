"""Bot API 10.1-10.4 bridge: real PTB 22.8 serialization over an in-memory transport, no network."""
import asyncio
import json
import random

import pytest
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, WebAppInfo
from telegram.constants import ParseMode
from telegram.ext import Application, Defaults, ExtBot
from telegram.request import BaseRequest

from modules import telegram_api_ext as ext
from modules import telegram_widgets as widgets

GROUP = {'id': -1001, 'type': 'supergroup', 'title': 'Room'}
RAW_TEXT_FIELDS = {'data', 'chat_data', 'public_data'}
PLAYER = {'id': 501, 'is_bot': False, 'first_name': 'Player'}


class RecordingRequest(BaseRequest):
    def __init__(self, failures=None):
        self.calls = []
        self.failures = dict(failures or {})

    @property
    def read_timeout(self):
        return 1

    async def initialize(self):
        pass

    async def shutdown(self):
        pass

    async def do_request(self, url, method, request_data=None, **kwargs):
        endpoint = url.rsplit('/', 1)[-1]
        fields = {}
        for key, value in (request_data.json_parameters if request_data else {}).items():
            if key in RAW_TEXT_FIELDS:  # widget state and answers are strings on the wire
                fields[key] = value
                continue
            try:
                fields[key] = json.loads(value)
            except json.JSONDecodeError:
                fields[key] = value
        self.calls.append((endpoint, fields))
        if endpoint in self.failures:
            return 400, json.dumps({'ok': False, 'error_code': 400, 'description': self.failures[endpoint]}).encode()
        if endpoint == 'getMe':
            result = {'id': 123456, 'is_bot': True, 'first_name': 'Local', 'username': 'local_test_bot'}
        elif endpoint == 'sendMessage':
            result = {'message_id': 0, 'date': 1700000000, 'chat': GROUP, 'text': fields['text'],
                      'ephemeral_message_id': 77, 'receiver_user': PLAYER}
        elif endpoint == 'sendWidget':
            widget = {key: fields[key] for key in ('html', 'public_data', 'chat_data', 'width', 'height') if key in fields}
            if fields.get('is_shared'):
                widget['id'] = '7770011223344556677'
            result = {'message_id': 9, 'date': 1700000000, 'chat': {'id': 501, 'type': 'private', 'first_name': 'Player'},
                      'caption': fields['caption'], 'widget': widget}
        else:
            result = True
        return 200, json.dumps({'ok': True, 'result': result}).encode()


def bot_with(request):
    # The application default is MarkdownV2, as in bot.py: helpers must send plain text unless asked.
    bot = ExtBot('123456:TEST', request=request, defaults=Defaults(parse_mode=ParseMode.MARKDOWN_V2))
    asyncio.run(bot.initialize())
    return bot


def calls(request, endpoint):
    return [fields for name, fields in request.calls if name == endpoint]


def callback_update(bot, data='role'):
    return Update.de_json({'update_id': 1, 'callback_query': {
        'id': 'cq-1', 'from': PLAYER, 'chat_instance': 'ci', 'data': data,
        'message': {'message_id': 15, 'date': 1700000000, 'chat': GROUP, 'text': 'Card'}}}, bot)


def widget_update(bot, data='farm:harvest', **extra):
    query = {'id': 'wq-1', 'from': PLAYER, 'chat': {'id': 501, 'type': 'private', 'first_name': 'Player'},
             'message_id': 9, 'chat_instance': 'ci', 'type': {'type': 'data'}, 'data': data, **extra}
    return Update.de_json({'update_id': 2, 'widget_query': query}, bot)


# ---------------------------------------------------------------- versions and updates

def test_support_and_allowed_updates_keep_ptb_types_and_add_widget_queries():
    support = ext.api_support()
    assert support['ptb_bot_api'] == '10.0' and support['target_bot_api'] == '10.4'
    updates = ext.allowed_updates()
    assert set(Update.ALL_TYPES) <= set(updates)
    assert {'widget_query', 'shared_widget_query'} <= set(updates)
    assert len(updates) == len(set(updates))


def test_update_identity_reads_widget_queries_and_regular_updates():
    request = RecordingRequest()
    bot = bot_with(request)
    assert ext.update_identity(widget_update(bot)) == (501, 501)
    forward = Update.de_json({'update_id': 3, 'shared_widget_query': {
        'id': 's', 'from': PLAYER, 'type': {'type': 'data'}, 'data': 'x', 'widget_id': 'w'}}, bot)
    assert ext.update_identity(forward) == (None, 501)
    assert ext.update_identity(callback_update(bot)) == (-1001, 501)


def test_disabled_button_and_ephemeral_command_serialize_new_fields():
    markup = InlineKeyboardMarkup([[ext.disabled_button('Уже сделано')]])
    assert markup.to_dict() == {'inline_keyboard': [[{'text': 'Уже сделано', 'disabled': {}}]]}
    assert ext.ephemeral_command('myrole', 'Моя роль').to_dict() == {
        'command': 'myrole', 'description': 'Моя роль', 'is_ephemeral': True}


# ---------------------------------------------------------------- ephemeral messages

def test_ephemeral_parameters_follow_the_api_rules():
    assert ext.ephemeral_parameters(callback_query_id='cq') == {'callback_query_id': 'cq'}
    assert ext.ephemeral_parameters(callback_query_id='cq', replace_callback_query_message=True) == {
        'callback_query_id': 'cq', 'replace_callback_query_message': True}
    assert ext.ephemeral_parameters(receiver_user_id=5) == {'receiver_user_id': 5}
    with pytest.raises(ValueError):
        ext.ephemeral_parameters()
    with pytest.raises(ValueError):
        ext.ephemeral_parameters(receiver_user_id=5, replace_callback_query_message=True)
    with pytest.raises(ValueError):
        ext.ephemeral_parameters(receiver_user_id=-100)


def test_ephemeral_markup_refuses_mini_app_and_login_buttons():
    ok = InlineKeyboardMarkup([[InlineKeyboardButton('Голос', callback_data='v')]])
    ext.check_ephemeral_markup(ok)
    with pytest.raises(ValueError):
        ext.check_ephemeral_markup(InlineKeyboardMarkup([[InlineKeyboardButton('App', web_app=WebAppInfo('https://example.org'))]]))


def test_send_ephemeral_text_is_plain_text_with_ephemeral_parameters():
    request = RecordingRequest()
    bot = bot_with(request)
    sent = asyncio.run(ext.send_ephemeral_text(bot, chat_id=-1001, text='Роль: доктор', callback_query_id='cq-1'))
    [fields] = calls(request, 'sendMessage')
    assert fields['ephemeral_message_parameters'] == {'callback_query_id': 'cq-1'}
    assert 'parse_mode' not in fields  # MarkdownV2 default is overridden
    assert sent.message_id == 0 and ext.ephemeral_message_id(sent) == 77


def test_reply_privately_sends_then_answers_the_press():
    request = RecordingRequest()
    bot = bot_with(request)
    query = callback_update(bot).callback_query
    sent = asyncio.run(ext.reply_privately(query, 'Твоя роль: доктор', replace=True))
    assert [name for name, _ in request.calls if name != 'getMe'] == ['sendMessage', 'answerCallbackQuery']
    assert calls(request, 'sendMessage')[0]['ephemeral_message_parameters'] == {
        'callback_query_id': 'cq-1', 'replace_callback_query_message': True}
    assert ext.ephemeral_message_id(sent) == 77


def test_reply_privately_falls_back_to_an_alert_for_the_presser_only():
    request = RecordingRequest(failures={'sendMessage': 'Bad Request: EPHEMERAL_NOT_SUPPORTED'})
    bot = bot_with(request)
    query = callback_update(bot).callback_query
    text = 'Секрет ' * 60
    assert asyncio.run(ext.reply_privately(query, text)) is None
    [answer] = calls(request, 'answerCallbackQuery')
    assert answer['show_alert'] is True and answer['text'] == text[:200]


def test_edit_and_delete_ephemeral_use_raw_methods_and_tolerate_not_modified():
    request = RecordingRequest(failures={'editEphemeralMessageText': 'Bad Request: message is not modified'})
    bot = bot_with(request)
    target = {'chat_id': -1001, 'receiver_user_id': 501, 'ephemeral_message_id': 77}
    assert asyncio.run(ext.edit_ephemeral_text(bot, text='Принято', **target)) is True
    assert asyncio.run(ext.delete_ephemeral(bot, **target)) is True
    assert calls(request, 'editEphemeralMessageText')[0] == {**target, 'text': 'Принято'}
    assert calls(request, 'deleteEphemeralMessage')[0] == target


# ---------------------------------------------------------------- widgets: limits and state

def test_html_limits_match_the_server_rules():
    assert widgets.check_html('<p>Привет</p>')[0] == len('<p>Привет</p>'.encode())
    with pytest.raises(ValueError):
        widgets.check_html('<p>\x00</p>')
    with pytest.raises(widgets.WidgetTooLarge):
        widgets.check_html('x' * (widgets.MAX_HTML_BYTES + 1))
    noise = random.Random(1).randbytes(6000).hex()  # incompressible: under 32 KB, over 4 KB compressed
    with pytest.raises(widgets.WidgetTooLarge):
        widgets.check_html(noise)


def test_state_is_compact_json_with_revision_and_byte_limit():
    assert widgets.pack_state({'ready': 3}, revision=4) == '{"ready":3,"r":4}'
    assert widgets.unpack('{"ready":3}') == {'ready': 3} and widgets.unpack('') is None and widgets.unpack('{') is None
    with pytest.raises(widgets.WidgetTooLarge):
        widgets.pack_state({'name': 'я' * 600})  # 1200 bytes of Cyrillic


def test_send_widget_serializes_and_exposes_the_widget():
    request = RecordingRequest()
    bot = bot_with(request)
    message = asyncio.run(widgets.send_widget(
        bot, chat_id=501, html='<h3>Ферма</h3>', caption='Ферма: 3 грядки готовы',
        chat_data=widgets.pack_state({'ready': 3}, revision=1), allow_queries=True, is_shared=True))
    [fields] = calls(request, 'sendWidget')
    assert fields == {'chat_id': 501, 'html': '<h3>Ферма</h3>', 'chat_data': '{"ready":3,"r":1}',
                      'caption': 'Ферма: 3 грядки готовы', 'allow_queries': True, 'is_shared': True}
    assert widgets.widget_of(message)['id'] == '7770011223344556677'
    with pytest.raises(ValueError):
        asyncio.run(widgets.send_widget(bot, chat_id=501, html='<p>x</p>', caption=' '))


def test_edit_widget_data_rules():
    request = RecordingRequest(failures={'editMessageWidgetData': 'Bad Request: message is not modified'})
    bot = bot_with(request)
    assert asyncio.run(widgets.edit_widget_data(bot, chat_id=501, message_id=9, chat_data='')) is True
    assert calls(request, 'editMessageWidgetData')[0] == {'chat_id': 501, 'message_id': 9, 'chat_data': ''}
    with pytest.raises(ValueError):
        asyncio.run(widgets.edit_widget_data(bot, chat_id=501, chat_data='{}'))
    with pytest.raises(ValueError):
        asyncio.run(widgets.edit_widget_data(bot, chat_id=501, message_id=9))
    asyncio.run(widgets.edit_shared_widget_data(bot, widget_id='w', public_data='{}', cache_time=99999))
    assert calls(request, 'editSharedWidgetData')[0] == {'widget_id': 'w', 'public_data': '{}', 'cache_time': 3600}
    with pytest.raises(ValueError):
        asyncio.run(widgets.edit_shared_widget_data(bot, widget_id='w', public_data='{}', cache_time=2))


def test_widget_query_parsing():
    bot = bot_with(RecordingRequest())
    query = widgets.widget_query_of(widget_update(bot, widget_id='w1'))
    assert (query.id, query.user_id, query.chat_id, query.message_id, query.prefix, query.kind) == (
        'wq-1', 501, 501, 9, 'farm', 'data')
    assert query.widget_id == 'w1' and not query.shared_forward
    assert widgets.widget_query_of(callback_update(bot)) is None
    broken = Update.de_json({'update_id': 4, 'widget_query': {'id': 'x', 'from': {}, 'data': 'a'}}, bot)
    assert widgets.widget_query_of(broken) is None


# ---------------------------------------------------------------- widgets: handler in a real Application

def run_application(request, handlers, update_factory):
    async def scenario():
        bot = ExtBot('123456:TEST', request=request, defaults=Defaults(parse_mode=ParseMode.MARKDOWN_V2))
        app = Application.builder().bot(bot).updater(None).build()
        for handler in handlers:
            app.add_handler(handler)
        await app.initialize()
        try:
            await app.process_update(update_factory(app.bot))
        finally:
            await app.shutdown()
    asyncio.run(scenario())


def test_handler_routes_by_prefix_and_answers_once():
    request = RecordingRequest()
    seen = []

    async def farm(update, context):
        seen.append(context.widget_query.data)
        await context.answer_widget({'ok': True, 'ready': 2})

    async def other(update, context):
        seen.append('other')

    run_application(request, [widgets.WidgetQueryHandler(other, prefix='mafia'),
                              widgets.WidgetQueryHandler(farm, prefix='farm')], widget_update)
    assert seen == ['farm:harvest']
    assert calls(request, 'answerWidgetQuery') == [{'widget_query_id': 'wq-1', 'data': '{"ok":true,"ready":2}'}]


def test_handler_answers_failed_when_the_game_raises_or_forgets():
    request = RecordingRequest()

    async def broken(update, context):
        raise RuntimeError('boom')

    run_application(request, [widgets.WidgetQueryHandler(broken)], widget_update)
    assert calls(request, 'answerWidgetQuery') == [{'widget_query_id': 'wq-1', 'data': '{"error":"failed"}'}]


def test_handler_ignores_wallet_queries_and_other_updates():
    request = RecordingRequest()
    seen = []

    async def any_query(update, context):
        seen.append(1)

    run_application(request, [widgets.WidgetQueryHandler(any_query)],
                    lambda bot: widget_update(bot, type={'type': 'sent_transaction', 'msg_hash': 'h'}))
    run_application(request, [widgets.WidgetQueryHandler(any_query)], callback_update)
    assert seen == [] and calls(request, 'answerWidgetQuery') == []


def test_moderation_gate_blocks_widget_queries_and_answers_unavailable(monkeypatch):
    from telegram.ext import ApplicationHandlerStop
    import handlers.moderation as moderation

    checked = []

    class Blocked:
        def __init__(self, database):
            pass

        async def allowed(self, chat_id=None, user_id=None, *, ignore_maintenance=False):
            checked.append((chat_id, user_id))
            return False

    monkeypatch.setattr(moderation, 'AdminActions', Blocked)
    request = RecordingRequest()
    bot = bot_with(request)
    gate = moderation.moderation_handler(database=None)
    with pytest.raises(ApplicationHandlerStop):
        asyncio.run(gate.callback(widget_update(bot), None))
    assert checked == [(501, 501)]
    assert calls(request, 'answerWidgetQuery') == [{'widget_query_id': 'wq-1', 'data': '{"error":"unavailable"}'}]
