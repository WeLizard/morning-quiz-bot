import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from telegram import Update
from telegram.error import Forbidden

from modules.telegram_test_scope import PrivateTestScope, ScopedRequest, menu_command

CHAT = 900000000091
BOT = 123456
TOKEN = '123456:LOCAL_TEST_ONLY_012345678901234567890'


def message_update(chat=CHAT, user=CHAT, kind='private', command='/start', bot=None):
    return Update.de_json({'update_id': 1, 'message': {'message_id': 10, 'date': 1700000000,
        'from': {'id': user, 'is_bot': False, 'first_name': 'Tester'},
        'chat': {'id': chat, 'type': kind}, 'text': command,
        'entities': [{'type': 'bot_command', 'offset': 0, 'length': len(command.split()[0])}]}}, bot)


@pytest.mark.parametrize('chat,user,kind,expected', [
    (CHAT, CHAT, 'private', True), (CHAT + 1, CHAT, 'private', False),
    (CHAT, CHAT + 1, 'private', False), (-CHAT, CHAT, 'group', False),
])
def test_inbound_identity_and_chat(chat, user, kind, expected):
    assert PrivateTestScope(CHAT, BOT).accepts(message_update(chat, user, kind)) is expected


@pytest.mark.parametrize('method', ['getChatMenuButton', 'setChatMenuButton'])
def test_menu_configuration_and_readback_are_private_chat_only(method):
    scope = PrivateTestScope(CHAT, BOT)
    assert scope.permits(method, {'chat_id': CHAT})
    assert not scope.permits(method, {})
    assert not scope.permits(method, {'chat_id': CHAT + 1})
    assert not scope.permits(method, {'chat_id': -CHAT})


@pytest.mark.parametrize('method,params', [
    ('sendMessage', {'chat_id': CHAT + 1}), ('sendPhoto', {'chat_id': '@someone'}),
    ('editMessageText', {'inline_message_id': 'outside'}),
    ('sendMessage', {'chat_id': CHAT, 'business_connection_id': 'outside'}),
    ('deleteWebhook', {}), ('setWebhook', {}), ('setMyCommands', {}),
    ('setMyCommands', {'scope': {'type': 'chat', 'chat_id': CHAT + 1}}),
    ('forwardMessage', {'chat_id': CHAT, 'from_chat_id': 5}),
    ('answerCallbackQuery', {'callback_query_id': 'unknown'}),
    ('newUnreviewedMethod', {'chat_id': CHAT}),
])
def test_denied_before_any_network_call(method, params):
    async def run():
        inner = SimpleNamespace(do_request=AsyncMock())
        request = ScopedRequest(inner, PrivateTestScope(CHAT, BOT), TOKEN)
        with pytest.raises(Forbidden):
            await request.do_request('https://api.telegram.org/bot' + TOKEN + '/' + method,
                                     'POST', SimpleNamespace(parameters=params))
        inner.do_request.assert_not_called()
    asyncio.run(run())


def test_unexpected_url_blocked_and_own_poll_registered():
    async def run():
        scope = PrivateTestScope(CHAT, BOT)
        inner = SimpleNamespace(do_request=AsyncMock(return_value=(200, b'{"ok":true,"result":{"poll":{"id":"own"}}}')))
        request = ScopedRequest(inner, scope, TOKEN)
        with pytest.raises(Forbidden):
            await request.do_request('https://elsewhere.invalid/getMe', 'POST')
        inner.do_request.assert_not_called()
        await request.do_request('https://api.telegram.org/bot' + TOKEN + '/sendPoll', 'POST',
                                 SimpleNamespace(parameters={'chat_id': CHAT}))
        assert scope.poll_ids == {'own'}
        for user, poll, expected in [(CHAT, 'own', True), (CHAT, 'other', False), (CHAT + 1, 'own', False)]:
            update = Update.de_json({'update_id': 2, 'poll_answer': {'poll_id': poll,
                'user': {'id': user, 'is_bot': False, 'first_name': 'Tester'}, 'option_ids': [0],
                'option_persistent_ids': ['option-0']}}, None)
            assert scope.accepts(update) is expected
    asyncio.run(run())


def test_opted_in_mini_game_delivery_never_calls_telegram():
    async def run():
        scope = PrivateTestScope(CHAT, BOT)
        scope.enable_local_delivery()
        inner = SimpleNamespace(do_request=AsyncMock())
        request = ScopedRequest(inner, scope, TOKEN)
        payload = SimpleNamespace(parameters={'chat_id': CHAT, 'question': 'Local?', 'options': ['Yes', 'No']}, multipart_data={})
        status, raw = await request.do_request('https://api.telegram.org/bot' + TOKEN + '/sendPoll', 'POST', payload)
        assert status == 200 and b'"ok": true' in raw
        inner.do_request.assert_not_called()
        assert any(event['event'] == 'mini_local_delivery' and event['method'] == 'sendPoll' for event in scope.events)
        assert not any(event['event'] == 'telegram_call' for event in scope.events)
    asyncio.run(run())


def test_start_settings_routes_to_real_settings_command():
    scope = PrivateTestScope(CHAT, BOT)
    commands = SimpleNamespace(quiz='quiz', mystats='mystats', global_top='globaltop',
                               admin_settings='adminsettings', help='help', categories='categories')
    raw = message_update().message.to_dict()
    raw['from'] = {'id': BOT, 'first_name': 'Bot', 'is_bot': True}
    update = Update.de_json({'update_id': 3, 'callback_query': {'id': 'valid', 'chat_instance': 'test',
        'from': {'id': CHAT, 'is_bot': False, 'first_name': 'Tester'},
        'message': raw, 'data': 'start_settings'}}, None)
    assert scope.accepts(update)
    assert scope.permits('answerCallbackQuery', {'callback_query_id': 'valid'})
    mapped = menu_command(update, commands, None)
    assert mapped.message.text == '/adminsettings'
    assert mapped.effective_user.id == CHAT
    assert mapped.message.entities[0].type == 'bot_command'


def test_private_runner_real_handlers_menu_quiz_and_score(pg_env, monkeypatch, tmp_path):
    from scripts import run_telegram_test as runner
    from modules import dev_runtime as offline
    from tests.local_database import isolated_database
    from storage.repositories import OperationalRepository
    from storage.settings import SettingsService
    from storage.question_bank import QuestionBank
    from storage.models import User
    from uuid import uuid4
    import telegram.request
    monkeypatch.setenv('BOT_TOKEN', TOKEN)
    monkeypatch.setenv('STORAGE_BACKEND', 'postgres')
    monkeypatch.setenv('MINI_APP_URL', '')
    monkeypatch.setattr(runner, 'WORKSPACE', tmp_path)
    monkeypatch.setattr(offline, 'CHAT', CHAT)
    monkeypatch.setattr(offline, 'USER', CHAT)
    monkeypatch.setattr(offline, 'ROOM', {'id': CHAT, 'type': 'private', 'first_name': 'Tester'})
    monkeypatch.setattr(offline, 'PLAYER', {'id': CHAT, 'first_name': 'Tester', 'is_bot': False})
    directory = tmp_path / '.local' / 'preview' / 'questions'
    directory.mkdir(parents=True)
    (directory / 'Numbers.json').write_text(
        '[{"question":"One plus one?","options":["One","Two"],"correct":"Two"}]', encoding='utf-8')
    async def run():
        async with isolated_database(pg_env) as (db, _):
            async with db.transaction() as session:
                repo = OperationalRepository(session)
                await repo.ensure_chat({'id': CHAT, 'type': 'private'})
                await repo.ensure_user({'id': CHAT, 'display_name': 'Tester'})
                await repo.ensure_member({'chat_id': CHAT, 'user_id': CHAT})
            await SettingsService(db).patch_paths(CHAT, [(('default_num_questions',), 1), (('default_announce_quiz',), False)])
            dummy = offline.DevRuntime(db)
            monkeypatch.setattr(telegram.request, 'HTTPXRequest', lambda **kwargs: offline.OfflineRequest(dummy))
            scope = PrivateTestScope(CHAT, BOT)
            app, config, quiz, photos, dm = await runner.build_application(db, scope, TOKEN, None)
            try:
                await app.initialize()
                await app.start()
                await runner.dispatch(app, config, scope, message_update(bot=app.bot))
                menu = next(m for m in dummy.messages.values() if m.get('reply_markup'))
                async def click(source, data):
                    raw = {'update_id': dummy.next_id(), 'callback_query': {'id': uuid4().hex,
                        'from': offline.PLAYER, 'chat_instance': 'test', 'message': source, 'data': data}}
                    await runner.dispatch(app, config, scope, Update.de_json(raw, app.bot))
                await click(menu, 'start_settings')
                assert any('admin_' in str(m.get('reply_markup', '')) or 'cfg_' in str(m.get('reply_markup', '')) for m in dummy.messages.values())
                await runner.dispatch(app, config, scope, message_update(command='/cancel', bot=app.bot))
                await click(menu, 'start_quiz')
                choices = [(m, b['callback_data']) for m in dummy.messages.values()
                           for row in m.get('reply_markup', {}).get('inline_keyboard', []) for b in row
                           if b.get('callback_data', '').endswith('start')]
                assert choices
                await click(*choices[-1])
                poll = next(m['poll'] for m in dummy.messages.values() if m.get('poll'))
                assert poll['id'] in scope.poll_ids
                correct = next(i for i, o in enumerate(poll['options']) if o['text'] == 'Two')
                answer = Update.de_json({'update_id': dummy.next_id(), 'poll_answer': {
                    'poll_id': poll['id'], 'user': offline.PLAYER, 'option_ids': [correct],
                    'option_persistent_ids': [poll['options'][correct]['persistent_id']]}}, app.bot)
                await runner.dispatch(app, config, scope, answer)
                async with db.transaction() as session:
                    score = (await session.get(User, CHAT)).global_score
                    assert score > 0
                await runner.dispatch(app, config, scope, answer)
                async with db.transaction() as session:
                    assert (await session.get(User, CHAT)).global_score == score
                assert not any(e['event'] in {'handler_error', 'blocked_outbound'} for e in scope.events), scope.events
            finally:
                await photos.shutdown()
                if app.running:
                    await app.stop()
                await dm.flush_postgres_writes()
                await app.shutdown()
    asyncio.run(run())


# Shared disposable-database fixture, never the persistent dev database.
from tests.test_postgres_members import pg_env
