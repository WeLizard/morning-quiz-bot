import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from telegram.error import BadRequest, TimedOut
from telegram.ext import ApplicationHandlerStop

from modules.telegram_menu import card, navigation_guard
from tests.test_mini_app import environment, signed, TOKEN, NOW, USER
from tests.test_postgres_members import pg_env
from web.mini_app import create_app, MiniAppSettings


@pytest.mark.parametrize('error,should_send', [
    (BadRequest('Message is not modified'), False),
    (BadRequest('Message to edit not found'), True),
    (BadRequest("Can't parse entities"), False),
    (TimedOut(), False),
])
def test_menu_edit_fallback_only_for_definite_missing_message(error, should_send):
    async def run():
        bot = SimpleNamespace(edit_message_text=AsyncMock(side_effect=error), send_message=AsyncMock())
        update = SimpleNamespace(callback_query=None, effective_chat=SimpleNamespace(id=123))
        context = SimpleNamespace(bot=bot)
        if isinstance(error, TimedOut) or "Can't parse" in str(error):
            with pytest.raises(type(error)):
                await card(update, context, 'Hello', [], message_id=5)
        else:
            await card(update, context, 'Hello', [], message_id=5)
        assert bot.send_message.called is should_send
    asyncio.run(run())


@pytest.mark.parametrize('callback,key', [('qcfg_num_menu', '_quiz_cfg_msg_id'), ('pqcfg_start', '_photo_quiz_cfg_msg_id')])
def test_stale_setup_button_stops_before_game_mutation(callback, key):
    async def run():
        query = SimpleNamespace(data=callback, message=SimpleNamespace(message_id=1), answer=AsyncMock())
        update = SimpleNamespace(callback_query=query)
        context = SimpleNamespace(chat_data={key: 2})
        with pytest.raises(ApplicationHandlerStop):
            await navigation_guard().callback(update, context)
        query.answer.assert_awaited_once()
    asyncio.run(run())


def test_private_mini_app_signed_owner_only_and_client_contract(pg_env):
    async def run():
        async with environment(pg_env) as env:
            origin = 'https://test-quiz.example.com'
            app = create_app(database=env.db, settings=MiniAppSettings(TOKEN, origin, bot_username='TestQuizBot'),
                             membership=env.verifier, clock=lambda: NOW, allowed_user_ids={USER})
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
                config = (await client.get('/api/mini/config')).json()
                assert config['bot_username'] == 'TestQuizBot' and config['private_test'] is True
                assert TOKEN not in str(config)
                assert [item['id'] for item in config['game_modes']] == ['classic', 'photo', 'night', 'atlas', 'farm']
                assert next(item for item in config['game_modes'] if item['id'] == 'farm')['status'] == 'coming_soon'
                assert (await client.get('/app/telegram-ui.js')).status_code == 200
                assert (await client.post('/api/dev/session')).status_code == 404
                assert (await client.get('/api/mini/me')).status_code == 401
                denied = await client.post('/api/mini/session', json={'init_data': signed(USER + 1)})
                assert denied.status_code == 403
                signed_in = await client.post('/api/mini/session', json={'init_data': signed(USER)})
                assert signed_in.status_code == 200
                headers = {'Cookie': f"mqb_mini={client.cookies.get('mqb_mini')}", 'Origin': origin}
                profile = await client.get('/api/mini/me', headers=headers)
                assert profile.status_code == 200 and profile.json()['user_id'] == str(USER)
                # A later restriction invalidates an otherwise still-valid session.
                app.state.mini_store.allowed_user_ids = frozenset()
                assert (await client.get('/api/mini/me', headers=headers)).status_code == 403
    asyncio.run(run())
