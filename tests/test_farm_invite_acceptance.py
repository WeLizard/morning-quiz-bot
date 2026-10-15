"""Emitted invite -> real JS hint -> signed host login -> PostgreSQL neighbors.

Telegram networking is never invoked. Node executes the shipped parser with
minimal browser globals, HTTP runs through ASGI, and state lives in an isolated
PG schema. This is an offline integration scenario, not a native-client check.
The recipient starts without a Telegram User; signed host login provisions it.
"""
import asyncio
import json
from pathlib import Path
import subprocess
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select

from storage.models import Account, MiniAppSession, User
from tests.test_farm_platform import (
    API, environment, farm_pg_url, receipts,
)
from tests.test_mini_app import TOKEN, signed
from web.mini_app import MiniAppSettings, create_app


ORIGIN = 'https://quizzy.example'
HEADERS = {'Origin': ORIGIN, 'X-QW-Farm': '1'}
CLIENT = Path(__file__).resolve().parents[1] / 'qw_farm' / 'static' / 'telegram.js'

# Execute the shipped module without copying its invitation algorithm.
PARSER = r"""
const fs=require('node:fs'),vm=require('node:vm');
const input=JSON.parse(fs.readFileSync(0,'utf8')),memory=new Map();
const context={URL,URLSearchParams,location:{search:input.search,href:input.web_url},
 window:{Telegram:{WebApp:{initDataUnsafe:{start_param:input.start_param,user:{id:1}}}}},
 sessionStorage:{setItem:(k,v)=>memory.set(k,v),getItem:k=>memory.get(k)||null}};
vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[1],'utf8')
 .replaceAll('export async function ','async function ')
 .replaceAll('export function ','function '),context);
const parsed=vm.runInContext('incomingInvite()',context);
context.location.search='';context.window.Telegram=undefined;
const persisted=vm.runInContext('incomingInvite()',context);
process.stdout.write(JSON.stringify({parsed,persisted,keys:[...memory.keys()]}));
"""


def client_hint(invite, channel):
    start_param = parse_qs(urlsplit(invite['mini_app_url']).query)['startapp'][0]
    result = subprocess.run(
        ['node', '-e', PARSER, str(CLIENT)],
        input=json.dumps({'search': '?' + urlsplit(invite['web_url']).query
                          if channel == 'web' else '',
                          'start_param': start_param if channel == 'telegram' else '',
                          'web_url': invite['web_url']}),
        capture_output=True, text=True, check=True, timeout=10,
    )
    hint = json.loads(result.stdout)
    assert hint == {'parsed': invite['code'], 'persisted': invite['code'],
                    'keys': ['qw-farm.incoming']}
    return hint['persisted'], start_param


async def command(client, actor, kind, target, identity, key):
    return await client.post(API + '/commands', params={'identity': identity}, headers=HEADERS,
                            json={'command_id': key, 'actor': actor, 'kind': kind,
                                  'target': target, 'data': {}})


async def counts(env):
    async with env.db.transaction() as session:
        return tuple([await session.scalar(select(func.count()).select_from(model))
                      for model in (Account, MiniAppSession, env.schema['states'])])


@pytest.mark.parametrize('channel', ['web', 'telegram'])
def test_emitted_invite_requires_signed_identity_and_two_explicit_neighbor_actions(farm_pg_url, channel):
    async def run():
        async with environment(farm_pg_url) as env:
            app = create_app(database=env.db,
                             settings=MiniAppSettings(TOKEN, ORIGIN, offline=True,
                                                      bot_username='QuizzyTestBot'),
                             clock=lambda: env.now[0])
            transport = httpx.ASGITransport(app=app)
            async with (httpx.AsyncClient(transport=transport, base_url=ORIGIN) as owner,
                        httpx.AsyncClient(transport=transport, base_url=ORIGIN) as recipient):
                guest_headers = {'Origin': ORIGIN, 'X-Guest-CSRF': '1'}
                started = await owner.post('/api/guest/start', headers=guest_headers)
                assert started.status_code == 200, started.text
                opened = await owner.post(API + '/start?identity=guest', headers=HEADERS)
                assert opened.status_code == 200, opened.text
                owner_id = opened.json()['farm']['id']
                assert opened.json()['farm']['settings']['visibility'] == 'friends'
                emitted = await owner.get(API + '/invite?identity=guest')
                assert emitted.status_code == 200, emitted.text
                invite = emitted.json()
                assert invite['web_url'] == ORIGIN + '/app/farm?invite=' + owner_id
                assert invite['mini_app_url'] == 'https://t.me/QuizzyTestBot/play?startapp=farm_' + owner_id
                target, start_param = client_hint(invite, channel)
                assert target == owner_id

                before = await counts(env)
                # Opening a public hint never signs in, creates a farm, or grants a visit.
                page = await recipient.get('/app/farm', params={'invite': target})
                assert page.status_code == 200
                for path in (API + '/me', API + '/farms/' + target):
                    assert (await recipient.get(path)).status_code == 401
                assert (await recipient.post(API + '/start', headers=HEADERS)).status_code == 401
                denied = await command(recipient, target, 'request_neighbor', target,
                                       'telegram', 'unauthenticated-invite')
                assert denied.status_code == 401
                assert await counts(env) == before == (1, 0, 1)

                uid = 981020000077
                async with env.db.transaction() as session:
                    assert await session.get(User, uid) is None
                invalid = await recipient.post('/api/mini/session', json={'init_data':
                    signed(uid, date=env.now[0], start_param=start_param) + 'tampered'})
                assert invalid.status_code == 401
                assert await counts(env) == before
                login = await recipient.post('/api/mini/session', json={'init_data': signed(
                    uid, date=env.now[0], start_param=start_param, query_id=uuid4().hex)})
                assert login.status_code == 200, login.text
                assert recipient.cookies.get('mqb_mini')
                assert await counts(env) == (2, 1, 1)
                opened = await recipient.post(API + '/start?identity=telegram', headers=HEADERS)
                assert opened.status_code == 200, opened.text
                telegram_id = opened.json()['farm']['id']
                assert telegram_id != target
                async with env.db.transaction() as session:
                    account_id = str((await session.get(User, uid)).account_id)
                assert (await recipient.get(API + '/neighbors?identity=telegram')).json()['neighbors'] == []
                assert (await recipient.get(API + '/farms/' + target + '?identity=telegram')).status_code == 404

                # A browser retaining both valid cookies must choose a profile; the hint is irrelevant.
                started = await recipient.post('/api/guest/start', headers=guest_headers)
                assert started.status_code == 200
                guest_account = started.json()['account_id']
                opened = await recipient.post(API + '/start?identity=guest', headers=HEADERS)
                assert opened.status_code == 200
                guest_id = opened.json()['farm']['id']
                assert guest_id not in (telegram_id, target)
                ambiguous = await recipient.post(API + '/commands', headers=HEADERS,
                    json={'command_id': 'ambiguous-invite', 'actor': telegram_id,
                          'kind': 'request_neighbor', 'target': target, 'data': {}})
                assert ambiguous.status_code == 401 and ambiguous.json()['code'] == 'identity_required'
                assert (await recipient.get(API + '/me')).json()['code'] == 'identity_required'
                wrong_actor = await command(recipient, guest_id, 'request_neighbor', target,
                                            'telegram', 'wrong-invite-actor')
                assert wrong_actor.status_code == 409 and wrong_actor.json()['code'] == 'profile_changed'
                assert not await receipts(env, account_id, 'wrong-invite-actor')

                requested = await command(recipient, telegram_id, 'request_neighbor', target,
                                          'telegram', 'explicit-invite-request')
                assert requested.status_code == 200, requested.text
                assert len(await receipts(env, account_id, 'explicit-invite-request')) == 1
                incoming = (await owner.get(API + '/neighbors?identity=guest')).json()['neighbors']
                outgoing = (await recipient.get(API + '/neighbors?identity=telegram')).json()['neighbors']
                assert [(n['id'], n['status']) for n in incoming] == [(telegram_id, 'incoming')]
                assert [(n['id'], n['status']) for n in outgoing] == [(target, 'outgoing')]
                assert (await recipient.get(API + '/farms/' + target + '?identity=telegram')).status_code == 404
                accepted = await command(owner, target, 'accept_neighbor', telegram_id,
                                         'guest', 'explicit-invite-accept')
                assert accepted.status_code == 200, accepted.text
                visit = await recipient.get(API + '/farms/' + target + '?identity=telegram')
                assert visit.status_code == 200, visit.text
                assert visit.json()['farm']['id'] == target
                assert visit.json()['farm']['is_owner'] is False
                assert 'inventory' not in visit.json()['farm']
                assert (await recipient.get(API + '/neighbors?identity=guest')).json()['neighbors'] == []
                assert (await recipient.get(API + '/farms/' + target + '?identity=guest')).status_code == 404
                assert not await receipts(env, guest_account, 'explicit-invite-request')
                assert await counts(env) == (3, 1, 3)

    asyncio.run(run())
