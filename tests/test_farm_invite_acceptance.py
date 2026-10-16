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
from qw_farm.persistence import DemoDatabase, Unit
from qw_farm.service import FarmService, Principal
from qw_farm.domain import FarmError
from qw_farm.sharing import invite_digest, MAX_ACTIVE_SHARE_INVITES_PER_FARM
from sqlalchemy import func, select
from tests.test_farm_platform import (
    API, environment, farm_pg_url, receipts,
)
from tests.test_mini_app import TOKEN, signed
from web.mini_app import MiniAppSettings, create_app


ORIGIN = 'https://quizzy.example'
HEADERS = {'Origin': ORIGIN, 'X-QW-Farm': '1'}
CLIENT = Path(__file__).resolve().parents[1] / 'qw_farm' / 'static' / 'invite.js'

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
    assert hint == {'parsed': invite['token'], 'persisted': invite['token'],
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
                read = await owner.get(API + '/invite?identity=guest')
                assert read.status_code == 200 and 'token' not in read.json()
                async with env.db.transaction() as session:
                    assert await session.scalar(select(func.count()).select_from(env.schema['share_invites'])) == 0
                emitted = await owner.post(API + '/invite/share?identity=guest', headers=HEADERS)
                assert emitted.status_code == 200, emitted.text
                invite = emitted.json()
                assert invite['code'] == owner_id
                assert len(invite['token']) == 43
                assert invite['web_url'] == ORIGIN + '/app/farm?invite=' + invite['token']
                assert invite['mini_app_url'] == 'https://t.me/QuizzyTestBot/play?startapp=farm_' + invite['token']
                cancelled = await owner.post(API + '/invite/share', params={'identity':'guest'}, headers=HEADERS)
                cancelled_token = cancelled.json()['token']
                revoked = await owner.post(API + '/invite/share/revoke?identity=guest', headers=HEADERS,
                                           json={'token':cancelled_token})
                assert revoked.status_code == 200 and revoked.json() == {'revoked':True}
                target, start_param = client_hint(invite, channel)
                assert target == invite['token']

                before = await counts(env)
                # Opening a public hint never signs in, creates a farm, or grants a visit.
                page = await recipient.get('/app/farm', params={'invite': target})
                assert page.status_code == 200
                for path in (API + '/me', API + '/farms/' + owner_id):
                    assert (await recipient.get(path)).status_code == 401
                assert (await recipient.post(API + '/start', headers=HEADERS)).status_code == 401
                denied = await command(recipient, owner_id, 'request_neighbor', owner_id,
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
                opened = await recipient.post(API + '/start?identity=telegram', headers=HEADERS,
                                              json={'invite': target})
                assert opened.status_code == 200, opened.text
                telegram_id = opened.json()['farm']['id']
                assert telegram_id != owner_id
                assert opened.json()['farm']['invited_by'] == owner_id
                foreign_revoke = await recipient.post(API + '/invite/share/revoke?identity=telegram',
                                                      headers=HEADERS,json={'token':target})
                assert foreign_revoke.status_code == 404
                cancelled_join = await recipient.post(API + '/invite/join?identity=telegram',headers=HEADERS,
                                                     json={'token':cancelled_token})
                assert cancelled_join.status_code == 404
                async with env.db.transaction() as session:
                    account_id = str((await session.get(User, uid)).account_id)
                assert (await recipient.get(API + '/neighbors?identity=telegram')).json()['neighbors'] == []
                assert (await recipient.get(API + '/farms/' + owner_id + '?identity=telegram')).status_code == 404

                # A browser retaining both valid cookies must choose a profile; the hint is irrelevant.
                started = await recipient.post('/api/guest/start', headers=guest_headers)
                assert started.status_code == 200
                opened = await recipient.post(API + '/start?identity=guest', headers=HEADERS,
                                              json={'invite': owner_id})
                assert opened.status_code == 200
                guest_id = opened.json()['farm']['id']
                assert guest_id not in (telegram_id, owner_id)
                assert opened.json()['farm']['invited_by'] == owner_id
                ambiguous = await recipient.post(API + '/commands', headers=HEADERS,
                    json={'command_id': 'ambiguous-invite', 'actor': telegram_id,
                          'kind': 'request_neighbor', 'target': owner_id, 'data': {}})
                assert ambiguous.status_code == 401 and ambiguous.json()['code'] == 'identity_required'
                assert (await recipient.get(API + '/me')).json()['code'] == 'identity_required'
                wrong_actor = await command(recipient, guest_id, 'request_neighbor', owner_id,
                                            'telegram', 'wrong-invite-actor')
                assert wrong_actor.status_code == 409 and wrong_actor.json()['code'] == 'profile_changed'
                assert not await receipts(env, account_id, 'wrong-invite-actor')

                malformed = await recipient.post(API + '/invite/join?identity=telegram', headers=HEADERS,
                                                 json={'token': 'not-a-token'})
                assert malformed.status_code == 422
                before_owner = (await owner.get(API + '/me?identity=guest')).json()['farm']['coins']
                before_recipient = (await recipient.get(API + '/me?identity=telegram')).json()['farm']['coins']
                expired_link = await owner.post(API + '/invite/share?identity=guest', headers=HEADERS)
                expired_token = expired_link.json()['token']
                from qw_farm.sharing import invite_digest
                async with env.db.transaction() as session:
                    await session.execute(env.schema['share_invites'].update().where(
                        env.schema['share_invites'].c.token_hash == invite_digest(expired_token)
                    ).values(expires_at=env.now[0]-1))
                expired = await recipient.post(API + '/invite/join?identity=telegram', headers=HEADERS,
                                               json={'token': expired_token})
                assert expired.status_code == 410
                joined = await recipient.post(API + '/invite/join?identity=telegram', headers=HEADERS,
                                              json={'token': target})
                assert joined.status_code == 200, joined.text
                assert joined.json()['neighbor_reward_paid'] is True
                reward = joined.json()['neighbors']['reward_per_neighbor']
                assert (await owner.get(API + '/me?identity=guest')).json()['farm']['coins'] == before_owner + reward
                assert (await recipient.get(API + '/me?identity=telegram')).json()['farm']['coins'] == before_recipient + reward
                incoming = (await owner.get(API + '/neighbors?identity=guest')).json()['neighbors']
                outgoing = (await recipient.get(API + '/neighbors?identity=telegram')).json()['neighbors']
                assert [(n['id'], n['status']) for n in incoming] == [(telegram_id, 'accepted')]
                assert [(n['id'], n['status']) for n in outgoing] == [(owner_id, 'accepted')]
                assert (await recipient.get(API + '/farms/' + owner_id + '?identity=telegram')).status_code == 200
                replay = await recipient.post(API + '/invite/join?identity=telegram', headers=HEADERS,
                                              json={'token': target})
                assert replay.status_code == 200 and replay.json()['neighbor_reward_paid'] is False
                used_by_other = await recipient.post(API + '/invite/join?identity=guest', headers=HEADERS,
                                                     json={'token': target})
                assert used_by_other.status_code == 409 and used_by_other.json()['code'] == 'invite_used'
                revoke_used = await owner.post(API + '/invite/share/revoke?identity=guest',headers=HEADERS,
                                               json={'token':target})
                assert revoke_used.status_code == 409 and revoke_used.json()['code'] == 'invite_used'
                visit = await recipient.get(API + '/farms/' + owner_id + '?identity=telegram')
                assert visit.status_code == 200, visit.text
                assert visit.json()['farm']['id'] == owner_id
                assert visit.json()['farm']['is_owner'] is False
                assert 'inventory' not in visit.json()['farm']
                assert (await recipient.get(API + '/neighbors?identity=guest')).json()['neighbors'] == []
                assert (await recipient.get(API + '/farms/' + owner_id + '?identity=guest')).status_code == 404
                assert await counts(env) == (3, 1, 3)

    asyncio.run(run())


def test_postgres_share_invite_race_accepts_only_one_recipient(farm_pg_url):
    async def run():
        async with environment(farm_pg_url) as env:
            app=create_app(database=env.db,settings=MiniAppSettings(TOKEN,ORIGIN,offline=True,
                                                                   bot_username='QuizzyTestBot'),
                            clock=lambda:env.now[0])
            transport=httpx.ASGITransport(app=app)
            async with (httpx.AsyncClient(transport=transport,base_url=ORIGIN) as owner,
                        httpx.AsyncClient(transport=transport,base_url=ORIGIN) as first,
                        httpx.AsyncClient(transport=transport,base_url=ORIGIN) as second):
                async def start_guest(client,name):
                    result=await client.post('/api/guest/start',headers={'Origin':ORIGIN,'X-Guest-CSRF':'1'})
                    assert result.status_code==200,result.text
                    opened=await client.post(API+'/start?identity=guest',headers=HEADERS)
                    assert opened.status_code==200,opened.text
                    return opened.json()['farm']['id']
                await start_guest(owner,'owner')
                first_id,second_id=await asyncio.gather(start_guest(first,'first'),start_guest(second,'second'))
                emitted=await owner.post(API+'/invite/share?identity=guest',headers=HEADERS)
                assert emitted.status_code==200,emitted.text
                token=emitted.json()['token']
                async def join(client):
                    return await client.post(API+'/invite/join?identity=guest',headers=HEADERS,json={'token':token})
                responses=await asyncio.gather(join(first),join(second))
                assert sorted(response.status_code for response in responses)==[200,409]
                winner=first_id if responses[0].status_code==200 else second_id
                loser=second_id if winner==first_id else first_id
                rejected=responses[1] if responses[0].status_code==200 else responses[0]
                assert rejected.json()['code']=='invite_used'
                neighbors=(await owner.get(API+'/neighbors?identity=guest')).json()['neighbors']
                assert [(row['id'],row['status']) for row in neighbors]==[(winner,'accepted')]
                async with env.db.transaction() as session:
                    row=await session.execute(select(env.schema['share_invites'].c.accepted_by_farm_id).where(
                        env.schema['share_invites'].c.token_hash==invite_digest(token)))
                    assert str(row.scalar_one())==winner
                winner_client=first if winner==first_id else second
                loser_client=second if winner==first_id else first
                assert (await winner_client.get(API+'/neighbors?identity=guest')).json()['neighbors'][0]['status']=='accepted'
                assert (await loser_client.get(API+'/neighbors?identity=guest')).json()['neighbors']==[]
                assert loser!=winner
    asyncio.run(run())


def test_demo_service_invite_join_is_atomic_idempotent_and_single_use():
    async def run():
        db=DemoDatabase(':memory:')
        owner_account,recipient_account,other_account,third_account=(uuid4(),uuid4(),uuid4(),uuid4())
        with db.engine.begin() as connection:
            for account in (owner_account,recipient_account,other_account,third_account):
                connection.execute(db.accounts.insert().values(id=account,name='Player',recovery_hash=uuid4().hex))
        now=[1_700_000_000]
        async with db.transaction() as unit:
            owner=FarmService(unit,Principal(str(owner_account),'Owner'),clock=lambda:now[0])
            await owner.open()
            owner_id=(await owner.me())['id']
            token=await owner.create_share_invite()
            self_token=await owner.create_share_invite()
        assert len(token)==43
        async with db.transaction() as unit:
            owner=FarmService(unit,Principal(str(owner_account),'Owner'),clock=lambda:now[0])
            try:await owner.join_share_invite(self_token)
            except FarmError as error:assert error.code=='self_invite'
            else:raise AssertionError('self invite unexpectedly succeeded')
            self_digest=invite_digest(self_token)
            assert (await unit.share_invite(self_digest))['accepted_by_farm_id'] is None
        async with db.transaction() as unit:
            recipient=FarmService(unit,Principal(str(recipient_account),'Recipient'),clock=lambda:now[0])
            opened=await recipient.open(token)
            recipient_id=opened['farm']['id']
            assert opened['farm']['invited_by']==owner_id
            recipient_before=(await recipient.me())['coins']
        async with db.transaction() as unit:
            owner=FarmService(unit,Principal(str(owner_account),'Owner'),clock=lambda:now[0])
            owner_before=(await owner.me())['coins']
            owner_farm=await owner.me()
            owner_farm['blocked'].append(recipient_id)
            await unit.save(owner_farm)
        async with db.transaction() as unit:
            recipient=FarmService(unit,Principal(str(recipient_account),'Recipient'),clock=lambda:now[0])
            try:await recipient.join_share_invite(token)
            except FarmError as error:assert error.code=='blocked'
            else:raise AssertionError('blocked invitation unexpectedly succeeded')
            assert (await unit.share_invite(invite_digest(token)))['accepted_by_farm_id'] is None
        async with db.transaction() as unit:
            owner=FarmService(unit,Principal(str(owner_account),'Owner'),clock=lambda:now[0])
            owner_farm=await owner.me()
            owner_farm['blocked'].clear()
            owner_farm['neighbors']={str(uuid4()):{'name':'Full','status':'accepted'} for _ in range(100)}
            await unit.save(owner_farm)
        async with db.transaction() as unit:
            recipient=FarmService(unit,Principal(str(recipient_account),'Recipient'),clock=lambda:now[0])
            try:await recipient.join_share_invite(token)
            except FarmError as error:assert error.code=='neighbors_full'
            else:raise AssertionError('full neighbor list unexpectedly accepted invitation')
            assert (await unit.share_invite(invite_digest(token)))['accepted_by_farm_id'] is None
        async with db.transaction() as unit:
            owner=FarmService(unit,Principal(str(owner_account),'Owner'),clock=lambda:now[0])
            owner_farm=await owner.me()
            owner_farm['neighbors'].clear()
            await unit.save(owner_farm)
        async with db.transaction() as unit:
            recipient=FarmService(unit,Principal(str(recipient_account),'Recipient'),clock=lambda:now[0])
            result=await recipient.join_share_invite(token)
            assert result['neighbor_reward_paid'] is True
            assert {n['id']:n['status'] for n in result['neighbors']['neighbors']}[owner_id]=='accepted'
            assert (await recipient.me())['coins']==recipient_before+result['neighbors']['reward_per_neighbor']
        async with db.transaction() as unit:
            owner=FarmService(unit,Principal(str(owner_account),'Owner'),clock=lambda:now[0])
            assert (await owner.me())['neighbors'][recipient_id]['status']=='accepted'
            assert (await owner.me())['coins']==owner_before+result['neighbors']['reward_per_neighbor']
        async with db.transaction() as unit:
            recipient=FarmService(unit,Principal(str(recipient_account),'Recipient'),clock=lambda:now[0])
            replay=await recipient.join_share_invite(token)
            assert replay['neighbor_reward_paid'] is False
        async with db.transaction() as unit:
            owner=FarmService(unit,Principal(str(owner_account),'Owner'),clock=lambda:now[0])
            try:await owner.revoke_share_invite(token)
            except FarmError as error:assert error.code=='invite_used'
            else:raise AssertionError('accepted invitation was revoked')
        async with db.transaction() as unit:
            other=FarmService(unit,Principal(str(other_account),'Other'),clock=lambda:now[0])
            await other.open()
            try:await other.revoke_share_invite(self_token)
            except FarmError as error:assert error.code=='invite_unknown'
            else:raise AssertionError('foreign invitation was revoked')
            try:await other.join_share_invite(token)
            except FarmError as error:assert error.code=='invite_used'
            else:raise AssertionError('second recipient unexpectedly consumed the invite')
        async with db.transaction() as unit:
            owner=FarmService(unit,Principal(str(owner_account),'Owner'),clock=lambda:now[0])
            owner_farm=await owner.me()
            owner_farm['neighbors'].clear()
            await unit.save(owner_farm)
            other=FarmService(unit,Principal(str(other_account),'Other'),clock=lambda:now[0])
            other_farm=await other.me()
            from qw_farm import economy
            other_farm['neighbor_bonus']={'day':economy.moscow_day(now[0]),'today':5,'total':5,'earned':0}
            await unit.save(other_farm)
            quota_token=await owner.create_share_invite()
        async with db.transaction() as unit:
            other=FarmService(unit,Principal(str(other_account),'Other'),clock=lambda:now[0])
            limited=await other.join_share_invite(quota_token)
            assert limited['neighbor_reward_paid'] is False
            assert 'лимит наград' in limited['notice'].lower()
            assert (await other.me())['neighbors'][owner_id]['status']=='accepted'
            assert (await unit.share_invite(invite_digest(quota_token)))['accepted_by_farm_id'] is not None
        async with db.transaction() as unit:
            owner=FarmService(unit,Principal(str(owner_account),'Owner'),clock=lambda:now[0])
            third=FarmService(unit,Principal(str(third_account),'Third'),clock=lambda:now[0])
            await third.open()
            third_farm=await third.me()
            third_farm['neighbor_bonus']={'day':-1,'today':0,'total':40,'earned':0}
            await unit.save(third_farm)
            total_limit_token=await owner.create_share_invite()
        async with db.transaction() as unit:
            third=FarmService(unit,Principal(str(third_account),'Third'),clock=lambda:now[0])
            limited_total=await third.join_share_invite(total_limit_token)
            assert limited_total['neighbor_reward_paid'] is False
            assert (await third.me())['neighbors'][owner_id]['status']=='accepted'
        async with db.transaction() as unit:
            recipient=FarmService(unit,Principal(str(recipient_account),'Recipient'),clock=lambda:now[0])
            expired_token=await FarmService(unit,Principal(str(owner_account),'Owner'),clock=lambda:now[0]).create_share_invite()
        now[0]+=7*24*60*60+1
        async with db.transaction() as unit:
            recipient=FarmService(unit,Principal(str(recipient_account),'Recipient'),clock=lambda:now[0])
            try:await recipient.join_share_invite(expired_token)
            except FarmError as error:assert error.code=='invite_expired'
            else:raise AssertionError('expired invite unexpectedly succeeded')
            assert (await unit.share_invite(invite_digest(expired_token)))['accepted_by_farm_id'] is None
        async with db.transaction() as unit:
            owner=FarmService(unit,Principal(str(owner_account),'Owner'),clock=lambda:now[0])
            await owner.create_share_invite()  # globally prune all expired rows
            assert await unit.share_invite(invite_digest(token)) is None
            assert await unit.share_invite(invite_digest(expired_token)) is None
            try:await FarmService(unit,Principal(str(recipient_account),'Recipient'),clock=lambda:now[0]).join_share_invite(token)
            except FarmError as error:assert error.code=='invite_unknown'
            else:raise AssertionError('expired invite survived its retention window')
            other=FarmService(unit,Principal(str(other_account),'Other'),clock=lambda:now[0])
            try:await other.join_share_invite('bad-token')
            except FarmError as error:assert error.code=='invalid_invite'
            else:raise AssertionError('malformed invite unexpectedly succeeded')
        db.engine.dispose()
    asyncio.run(run())


def test_demo_share_invite_issuance_is_capped_and_expired_rows_are_pruned():
    async def run():
        db=DemoDatabase(':memory:')
        account=uuid4()
        with db.engine.begin() as connection:
            connection.execute(db.accounts.insert().values(id=account,name='Player',recovery_hash=uuid4().hex))
        now=[1_700_000_000]
        async with db.transaction() as unit:
            service=FarmService(unit,Principal(str(account),'Player'),clock=lambda:now[0])
            await service.open()
            tokens=[await service.create_share_invite() for _ in range(MAX_ACTIVE_SHARE_INVITES_PER_FARM)]
            try:await service.create_share_invite()
            except FarmError as error:assert error.code=='share_invite_limit' and error.status==429
            else:raise AssertionError('invite issuance exceeded its active-window quota')
            count=await unit.execute(select(func.count()).select_from(unit.t['share_invites']))
            assert count.scalar_one()==MAX_ACTIVE_SHARE_INVITES_PER_FARM
            assert await service.revoke_share_invite(tokens[0])=={'revoked':True}
            replacement_for_revoked=await service.create_share_invite()
            assert len(replacement_for_revoked)==43
            count=await unit.execute(select(func.count()).select_from(unit.t['share_invites']))
            assert count.scalar_one()==MAX_ACTIVE_SHARE_INVITES_PER_FARM
        now[0]+=7*24*60*60+1
        async with db.transaction() as unit:
            service=FarmService(unit,Principal(str(account),'Player'),clock=lambda:now[0])
            replacement=await service.create_share_invite()
            assert len(replacement)==43
            assert await unit.share_invite(invite_digest(tokens[0])) is None
            assert (await unit.execute(select(func.count()).select_from(unit.t['share_invites']))).scalar_one()==1
        db.engine.dispose()
    asyncio.run(run())
