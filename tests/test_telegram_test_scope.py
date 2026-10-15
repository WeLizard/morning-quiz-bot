import asyncio
from hashlib import sha256
import hmac
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import urlencode

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
    from storage.models import ChatMember, Game, GameCommand, PollAnswer
    from sqlalchemy import select
    import httpx
    from telegram.ext import CallbackContext
    from web.mini_app import MiniAppSettings, create_app
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
                from modules import telegram_menu
                monkeypatch.setattr(
                    telegram_menu, 'as_command',
                    lambda *_args, **_kwargs: pytest.fail('Classic menu entry must keep the real callback Update'),
                )
                await click(menu, 'nav:quiz')
                assert menu['message_id'] in dummy.messages
                assert any(
                    button.get('callback_data', '').startswith('qcfg_')
                    for row in dummy.messages[menu['message_id']]['reply_markup']['inline_keyboard']
                    for button in row
                )
                cancel_data = next(
                    button['callback_data']
                    for row in dummy.messages[menu['message_id']]['reply_markup']['inline_keyboard']
                    for button in row if button.get('text') == 'Отмена'
                )
                await click(dummy.messages[menu['message_id']], cancel_data)
                assert any(
                    button.get('callback_data') == 'nav:quiz'
                    for row in dummy.messages[menu['message_id']]['reply_markup']['inline_keyboard']
                    for button in row
                )
                await click(dummy.messages[menu['message_id']], 'nav:quiz')
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
                    game = await session.scalar(select(Game).where(
                        Game.chat_id == CHAT, Game.mode == 'classic', Game.is_current.is_(True),
                    ))
                    assert game is not None
                    rows = (await session.scalars(select(PollAnswer).where(
                        PollAnswer.game_id == game.id, PollAnswer.user_id == CHAT,
                    ))).all()
                    assert len(rows) == 1 and rows[0].is_correct
                    round_id = rows[0].round_id

                # A Telegram vote and a Mini App answer use the same durable game
                # and answer ledger. Only the Telegram boundary receives an Update.
                origin = 'http://127.0.0.1:4185'
                mini = create_app(
                    database=db, settings=MiniAppSettings(TOKEN, origin, offline=True),
                    membership=SimpleNamespace(allowed=AsyncMock(return_value=True)),
                    clock=lambda: int(time.time()), runtime_enabled=True,
                )
                fields = {
                    'auth_date': str(int(time.time())),
                    'user': json.dumps({'id': CHAT, 'first_name': 'Tester'}),
                }
                check = '\n'.join(f'{key}={value}' for key, value in sorted(fields.items()))
                key = hmac.new(b'WebAppData', TOKEN.encode(), sha256).digest()
                fields['hash'] = hmac.new(key, check.encode(), sha256).hexdigest()
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=mini), base_url=origin,
                ) as client:
                    login = await client.post('/api/mini/session', json={'init_data': urlencode(fields)})
                    assert login.status_code == 200, login.text
                    current = await client.get(f'/api/mini/classic/chats/{CHAT}/current')
                    assert current.status_code == 200, current.text
                    question = current.json()['question']
                    assert question['round_id'] == round_id
                    assert question['answered'] is True
                    assert question['selected_option'] == correct
                    first_duplicate_payload = {
                        'round_id': round_id, 'selected_option': 1 - correct,
                        'command_id': uuid4().hex,
                    }
                    duplicate = await client.post(
                        f'/api/mini/classic/chats/{CHAT}/answer',
                        json=first_duplicate_payload,
                        headers={'Origin': origin, 'X-Mini-CSRF': '1'},
                    )
                    assert duplicate.status_code == 200, duplicate.text
                    assert duplicate.json()['applied'] is False
                    assert duplicate.json()['question']['selected_option'] == correct
                    replay = await client.post(
                        f'/api/mini/classic/chats/{CHAT}/answer',
                        json=first_duplicate_payload,
                        headers={'Origin': origin, 'X-Mini-CSRF': '1'},
                    )
                    assert replay.status_code == 200 and replay.json() == duplicate.json()
                    await runner.dispatch(app, config, scope, answer)
                    async with db.transaction() as session:
                        assert (await session.get(User, CHAT)).global_score == score
                        rows = (await session.scalars(select(PollAnswer).where(
                            PollAnswer.game_id == game.id, PollAnswer.user_id == CHAT,
                        ))).all()
                        assert len(rows) == 1

                    stopped = await client.post(
                        f'/api/mini/classic/chats/{CHAT}/stop',
                        json={'command_id': uuid4().hex,
                              'expected_revision': duplicate.json()['revision']},
                        headers={'Origin': origin, 'X-Mini-CSRF': '1'},
                    )
                    assert stopped.status_code == 200, stopped.text
                    started = await client.post(
                        f'/api/mini/classic/chats/{CHAT}/start',
                        json={'command_id': uuid4().hex},
                        headers={'Origin': origin, 'X-Mini-CSRF': '1'},
                    )
                    assert started.status_code == 200, started.text
                    new_game = started.json()
                    assert new_game['question']['round_id'] != round_id
                    old_poll_ids = {m['poll']['id'] for m in dummy.messages.values() if m.get('poll')}
                    await app.bot_data['game_runtime'].notification_job(CallbackContext(app))
                    delivered = [m['poll'] for m in dummy.messages.values()
                                 if m.get('poll') and m['poll']['id'] not in old_poll_ids]
                    assert len(delivered) == 1
                    new_poll = delivered[0]
                    assert new_poll['id'] in scope.poll_ids
                    new_correct = next(i for i, option in enumerate(new_poll['options'])
                                       if option['text'] == 'Two')
                    async with db.transaction() as session:
                        before_member = await session.get(ChatMember, (CHAT, CHAT))
                        before_member_score = before_member.score
                        before_member_answers = before_member.answered_count
                    http_command_id = uuid4().hex
                    new_payload = {
                        'round_id': new_game['question']['round_id'],
                        'selected_option': new_correct,
                        'command_id': http_command_id,
                    }
                    mini_answer = await client.post(
                        f'/api/mini/classic/chats/{CHAT}/answer', json=new_payload,
                        headers={'Origin': origin, 'X-Mini-CSRF': '1'},
                    )
                    assert mini_answer.status_code == 200, mini_answer.text
                    assert mini_answer.json()['applied'] is True
                    async with db.transaction() as session:
                        awarded_score = (await session.get(User, CHAT)).global_score
                        awarded_member = await session.get(ChatMember, (CHAT, CHAT))
                        awarded_member_score = awarded_member.score
                        awarded_member_answers = awarded_member.answered_count
                        assert awarded_score > score
                        assert awarded_member_score > before_member_score
                        assert awarded_member_answers == before_member_answers + 1
                    mini_replay = await client.post(
                        f'/api/mini/classic/chats/{CHAT}/answer', json=new_payload,
                        headers={'Origin': origin, 'X-Mini-CSRF': '1'},
                    )
                    assert mini_replay.status_code == 200
                    assert mini_replay.json() == mini_answer.json()
                    async with db.transaction() as session:
                        assert (await session.get(User, CHAT)).global_score == awarded_score
                        member = await session.get(ChatMember, (CHAT, CHAT))
                        assert member.score == awarded_member_score
                        assert member.answered_count == awarded_member_answers
                    new_answer = Update.de_json({'update_id': dummy.next_id(), 'poll_answer': {
                        'poll_id': new_poll['id'], 'user': offline.PLAYER,
                        'option_ids': [new_correct],
                        'option_persistent_ids': [new_poll['options'][new_correct]['persistent_id']],
                    }}, app.bot)
                    await runner.dispatch(app, config, scope, new_answer)
                    after = await client.get(f'/api/mini/classic/chats/{CHAT}/current')
                    assert after.status_code == 200, after.text
                    assert after.json()['question']['answered'] is True
                    assert after.json()['question']['selected_option'] == new_correct
                    async with db.transaction() as session:
                        assert (await session.get(User, CHAT)).global_score == awarded_score
                        member = await session.get(ChatMember, (CHAT, CHAT))
                        assert member.score == awarded_member_score
                        assert member.answered_count == awarded_member_answers
                        second = (await session.scalars(select(PollAnswer).where(
                            PollAnswer.game_id == new_game['game_id'], PollAnswer.user_id == CHAT,
                        ))).all()
                        assert len(second) == 1 and second[0].selected_option == new_correct
                        tg_command_id = 'tg-answer:' + sha256(
                            f"{new_poll['id']}:{CHAT}".encode(),
                        ).hexdigest()[:48]
                        commands = (await session.scalars(select(GameCommand).where(
                            GameCommand.game_id == new_game['game_id'],
                            GameCommand.kind == 'classic.answer',
                        ))).all()
                        assert {item.id for item in commands} == {http_command_id, tg_command_id}
                        assert all(item.status == 'completed' for item in commands)
                        assert (await session.get(GameCommand, http_command_id)).result == mini_answer.json()
                        assert (await session.get(GameCommand, tg_command_id)).result['applied'] is False
                    await runner.dispatch(app, config, scope, new_answer)
                    async with db.transaction() as session:
                        assert (await session.get(User, CHAT)).global_score == awarded_score
                        member = await session.get(ChatMember, (CHAT, CHAT))
                        assert member.score == awarded_member_score
                        assert member.answered_count == awarded_member_answers
                        second = (await session.scalars(select(PollAnswer).where(
                            PollAnswer.game_id == new_game['game_id'], PollAnswer.user_id == CHAT,
                        ))).all()
                        assert len(second) == 1
                        commands = (await session.scalars(select(GameCommand).where(
                            GameCommand.game_id == new_game['game_id'],
                            GameCommand.kind == 'classic.answer',
                        ))).all()
                        assert {item.id for item in commands} == {http_command_id, tg_command_id}
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
