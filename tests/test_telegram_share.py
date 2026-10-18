import asyncio
import json

import httpx

from web.telegram_share import TelegramShare

TOKEN = '123456:' + 'A' * 35


def run(handler):
    seen = []

    def wrapped(request):
        seen.append(request)
        return handler(request)

    share = TelegramShare(TOKEN, client=httpx.AsyncClient(transport=httpx.MockTransport(wrapped)))

    async def go():
        try:
            return await share.prepare(42, result_id='farm-x', title='Приглашение', text='Привет',
                                       button_text='Открыть ферму', button_url='https://t.me/Bot/play?startapp=farm_x')
        finally:
            await share.close()
    return asyncio.run(go()), seen


def test_prepared_message_id_is_returned_and_payload_targets_one_user():
    result, seen = run(lambda r: httpx.Response(200, json={'ok': True, 'result': {'id': 'prep-1', 'expiration_date': 1}}))
    assert result == 'prep-1'
    assert seen[0].url.path.endswith('/savePreparedInlineMessage')
    body = json.loads(seen[0].content)
    assert body['user_id'] == 42 and body['allow_user_chats'] and body['allow_group_chats']
    assert body['result']['reply_markup']['inline_keyboard'][0][0]['url'].startswith('https://t.me/')


def test_api_error_and_network_error_fall_back_to_none():
    assert run(lambda r: httpx.Response(400, json={'ok': False, 'description': 'Bad Request'}))[0] is None
    assert run(lambda r: httpx.Response(502, text='bad gateway'))[0] is None

    def boom(request):
        raise httpx.ConnectError('down', request=request)
    assert run(boom)[0] is None


def share_app(prepare_share, telegram_user_id=7):
    from contextlib import asynccontextmanager
    from fastapi import FastAPI
    from qw_farm.api import create_router

    class Service:
        async def me(self):
            return {'id': '00000000-0000-4000-8000-000000000001', 'name': 'Ферма Илья'}

        async def share_link(self, rotate=False):
            return {'token': 'T' * 43, 'uses': 0, 'max_uses': 10, 'expires_at': 1.0}

        async def _invites(self, farm):
            return None

    @asynccontextmanager
    async def context(request):
        service = Service()
        service.telegram_user_id = telegram_user_id
        yield service

    app = FastAPI()
    app.include_router(create_router(context, origin='https://qw.example', bot_username='QuizzyBot',
                                     prepare_share=prepare_share))
    return app


def test_share_route_prepares_message_only_when_telegram_flag_is_sent():
    from fastapi.testclient import TestClient
    calls = []

    async def prepare(user_id, invitation):
        calls.append((user_id, invitation['mini_app_url']))
        return 'prep-9'

    client = TestClient(share_app(prepare))
    plain = client.post('/api/farm/v1/invite/share').json()
    assert plain['prepared_message_id'] is None and calls == []
    native = client.post('/api/farm/v1/invite/share', json={'telegram': True}).json()
    assert native['prepared_message_id'] == 'prep-9'
    assert calls == [(7, 'https://t.me/QuizzyBot/play?startapp=farm_' + 'T' * 43)]


def test_share_route_without_telegram_identity_keeps_the_plain_link():
    from fastapi.testclient import TestClient

    async def prepare(user_id, invitation):
        raise AssertionError('no Telegram user, no Bot API call')

    result = TestClient(share_app(prepare, telegram_user_id=None)).post('/api/farm/v1/invite/share', json={'telegram': True}).json()
    assert result['prepared_message_id'] is None and result['share_url'].startswith('https://t.me/share/url?')


def test_prepared_message_is_reused_until_it_nears_expiration():
    now = [1000.0]
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={'ok': True, 'result': {'id': f'prep-{len(calls)}', 'expiration_date': 4600}})

    share = TelegramShare(TOKEN, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), clock=lambda: now[0])

    async def prepare(user_id=42):
        return await share.prepare(user_id, result_id='x', title='t', text='m', button_text='b',
                                   button_url='https://t.me/Bot', cache_key='farm-invite:abc')

    async def go():
        try:
            first = await prepare()
            assert await prepare() == first and len(calls) == 1
            assert await prepare(43) != first and len(calls) == 2   # cached per user
            now[0] = 4600 - 60                                       # inside the safety margin
            assert await prepare() == 'prep-3'
        finally:
            await share.close()
    asyncio.run(go())
