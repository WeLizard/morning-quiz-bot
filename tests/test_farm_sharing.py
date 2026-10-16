"""Invitation destinations: Telegram direct Mini App, standalone and draft."""
from urllib.parse import parse_qs, urlsplit
from contextlib import asynccontextmanager
import asyncio

import httpx
import pytest
from fastapi import FastAPI

from qw_farm.sharing import invite_info, new_invite_token, invite_digest, safe_public_origin
from qw_farm.api import create_router

ID = 'aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee'


def test_telegram_invitation_share_and_personal_draft_open_registered_app():
    token = new_invite_token()
    assert len(token) == 43 and len(new_invite_token()) == 43
    assert invite_digest(token) != invite_digest('y'*43)
    info = invite_info(ID, 'Ира', token=token, origin='https://qw.example',
                       bot_username='Quizywizzy_bot', recipient='FriendlyUser')
    link = f'https://t.me/Quizywizzy_bot/play?startapp=farm_{token}'
    assert info['mini_app_url'] == link
    assert parse_qs(urlsplit(info['share_url']).query)['url'] == [link]
    assert link in info['text']
    assert link in parse_qs(urlsplit(info['direct_url']).query)['text'][0]
    assert info['web_url'] == f'https://qw.example/app/farm?invite={token}'
    assert info['code'] == ID


def test_custom_short_name_and_standalone_fallback():
    assert '/other_app?' in invite_info(ID, 'Ира', token='x'*43, bot_username='QuizzyBot',
                                      mini_app_short_name='other_app')['mini_app_url']
    info = invite_info(ID, 'Ира', token='x'*43, origin='https://qw.example')
    assert info['mini_app_url'] is None
    assert info['web_url'] in info['text']
    assert parse_qs(urlsplit(info['share_url']).query)['url'] == [info['web_url']]


@pytest.mark.parametrize('name', ['../play', 'play?bad=1', 'https://evil.test', 'ab', 'x' * 31])
def test_invalid_short_name_is_rejected(name):
    with pytest.raises(Exception) as error:
        invite_info(ID, 'Ира', token='x'*43, bot_username='QuizzyBot', mini_app_short_name=name)
    assert error.value.code == 'bot_configuration'


@pytest.mark.parametrize(('origin', 'local_only'), [
    ('https://qw.example', False), ('http://localhost:8000', True), ('https://127.0.0.1', True),
])
def test_invite_read_is_safe_and_local_only_uses_public_origin(origin, local_only):
    class Service:
        async def me(self): return {'id': ID, 'name': 'Ира'}
        async def _invites(self, farm): return {'neighbor': {'reward': 550}}

    @asynccontextmanager
    async def context(_request): yield Service()

    async def run():
        app=FastAPI()
        app.include_router(create_router(context,origin=origin))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            response=await client.get('/api/farm/v1/invite')
            assert response.status_code==200
            assert response.json()=={'code':ID,'farm_name':'Ира','rewards':{'neighbor':{'reward':550}},
                                     'local_only':local_only}
    asyncio.run(run())


def test_safe_public_origin_rejects_nonpublic_and_malformed_origins():
    assert safe_public_origin('https://qw.example')=='https://qw.example'
    for origin in ('http://qw.example','https://localhost','https://127.0.0.1','https://qw.example/path'):
        assert safe_public_origin(origin) is None
