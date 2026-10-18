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
from qw_farm.sharing import invite_digest, MAX_ACTIVE_SHARE_INVITES_PER_FARM, SHARE_INVITE_MAX_USES, SHARE_INVITE_TTL
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
                assert (invite['uses'], invite['max_uses']) == (0, 10)
                again = await owner.post(API + '/invite/share', params={'identity':'guest'}, headers=HEADERS)
                assert again.json()['token'] == invite['token']
                assert (await owner.get(API + '/invite?identity=guest')).json()['link']['uses'] == 0
                async with env.db.transaction() as session:
                    assert await session.scalar(select(func.count()).select_from(env.schema['share_invites'])) == 1
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
                unknown_join = await recipient.post(API + '/invite/join?identity=telegram',headers=HEADERS,
                                                   json={'token':'U' * 43})
                assert unknown_join.status_code == 404
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
                expired_token = 'E' * 43
                from qw_farm.sharing import invite_digest
                from uuid import UUID
                async with env.db.transaction() as session:
                    await session.execute(env.schema['share_invites'].insert().values(
                        token_hash=invite_digest(expired_token), farm_id=UUID(owner_id), expires_at=env.now[0]-1))
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
                async with env.db.transaction() as session:
                    row = (await session.execute(select(env.schema['share_invites']).where(
                        env.schema['share_invites'].c.token_hash == invite_digest(target)))).mappings().one()
                    assert row['uses'] == 1
                    await session.execute(env.schema['share_invites'].update().where(
                        env.schema['share_invites'].c.token_hash == invite_digest(target)).values(max_uses=1))
                used_by_other = await recipient.post(API + '/invite/join?identity=guest', headers=HEADERS,
                                                     json={'token': target})
                assert used_by_other.status_code == 409 and used_by_other.json()['code'] == 'invite_used'
                revoke_used = await owner.post(API + '/invite/share/revoke?identity=guest',headers=HEADERS,
                                               json={'token':target})
                assert revoke_used.status_code == 200 and revoke_used.json() == {'revoked': True}
                replacement = (await owner.post(API + '/invite/share?identity=guest', headers=HEADERS)).json()
                assert replacement['token'] != target and replacement['uses'] == 0
                visit = await recipient.get(API + '/farms/' + owner_id + '?identity=telegram')
                assert visit.status_code == 200, visit.text
                assert visit.json()['farm']['id'] == owner_id
                assert visit.json()['farm']['is_owner'] is False
                assert 'inventory' not in visit.json()['farm']
                assert (await recipient.get(API + '/neighbors?identity=guest')).json()['neighbors'] == []
                assert (await recipient.get(API + '/farms/' + owner_id + '?identity=guest')).status_code == 404
                assert await counts(env) == (3, 1, 3)

    asyncio.run(run())


def test_postgres_share_invite_race_for_the_last_place_accepts_only_one_recipient(farm_pg_url):
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
                async with env.db.transaction() as session:
                    await session.execute(env.schema['share_invites'].update().where(
                        env.schema['share_invites'].c.token_hash==invite_digest(token)).values(max_uses=1))
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
                    uses=env.schema['share_invite_uses']
                    rows=(await session.execute(select(uses.c.farm_id).where(uses.c.token_hash==invite_digest(token)))).scalars().all()
                    assert [str(r) for r in rows]==[winner]
                winner_client=first if winner==first_id else second
                loser_client=second if winner==first_id else first
                assert (await winner_client.get(API+'/neighbors?identity=guest')).json()['neighbors'][0]['status']=='accepted'
                assert (await loser_client.get(API+'/neighbors?identity=guest')).json()['neighbors']==[]
                assert loser!=winner
    asyncio.run(run())


def test_demo_service_reusable_link_is_atomic_idempotent_and_capped():
    async def run():
        db=DemoDatabase(':memory:')
        owner_account,recipient_account,other_account,third_account,fourth_account=(uuid4() for _ in range(5))
        with db.engine.begin() as connection:
            for account in (owner_account,recipient_account,other_account,third_account,fourth_account):
                connection.execute(db.accounts.insert().values(id=account,name='Player',recovery_hash=uuid4().hex))
        now=[1_700_000_000]
        def service(unit,account,name='Player'):
            return FarmService(unit,Principal(str(account),name),clock=lambda:now[0])
        async def uses(unit,token):
            return (await unit.share_invite(invite_digest(token)))['uses']
        async with db.transaction() as unit:
            owner=service(unit,owner_account,'Owner')
            await owner.open()
            owner_id=(await owner.me())['id']
            assert await owner.share_link_status() is None
            link=await owner.share_link()
            token=link['token']
            assert len(token)==43 and (link['uses'],link['max_uses'])==(0,SHARE_INVITE_MAX_USES)
            assert (await owner.share_link())['token']==token   # one reusable link, not a token per tap
            assert (await unit.execute(select(func.count()).select_from(unit.t['share_invites']))).scalar_one()==1
        async with db.transaction() as unit:
            owner=service(unit,owner_account,'Owner')
            try:await owner.join_share_invite(token)
            except FarmError as error:assert error.code=='self_invite'
            else:raise AssertionError('self invite unexpectedly succeeded')
            assert await uses(unit,token)==0
        async with db.transaction() as unit:
            recipient=service(unit,recipient_account,'Recipient')
            opened=await recipient.open(token)
            recipient_id=opened['farm']['id']
            assert opened['farm']['invited_by']==owner_id
            recipient_before=(await recipient.me())['coins']
        async with db.transaction() as unit:
            owner=service(unit,owner_account,'Owner')
            owner_before=(await owner.me())['coins']
            owner_farm=await owner.me()
            owner_farm['blocked'].append(recipient_id)
            await unit.save(owner_farm)
        async with db.transaction() as unit:
            recipient=service(unit,recipient_account,'Recipient')
            try:await recipient.join_share_invite(token)
            except FarmError as error:assert error.code=='blocked'
            else:raise AssertionError('blocked invitation unexpectedly succeeded')
            assert await uses(unit,token)==0
        async with db.transaction() as unit:
            owner=service(unit,owner_account,'Owner')
            owner_farm=await owner.me()
            owner_farm['blocked'].clear()
            owner_farm['neighbors']={str(uuid4()):{'name':'Full','status':'accepted'} for _ in range(100)}
            await unit.save(owner_farm)
        async with db.transaction() as unit:
            recipient=service(unit,recipient_account,'Recipient')
            try:await recipient.join_share_invite(token)
            except FarmError as error:assert error.code=='neighbors_full'
            else:raise AssertionError('full neighbor list unexpectedly accepted invitation')
            assert await uses(unit,token)==0
        async with db.transaction() as unit:
            owner=service(unit,owner_account,'Owner')
            owner_farm=await owner.me()
            owner_farm['neighbors'].clear()
            await unit.save(owner_farm)
        async with db.transaction() as unit:
            recipient=service(unit,recipient_account,'Recipient')
            result=await recipient.join_share_invite(token)
            assert result['neighbor_reward_paid'] is True
            assert {n['id']:n['status'] for n in result['neighbors']['neighbors']}[owner_id]=='accepted'
            assert (await recipient.me())['coins']==recipient_before+result['neighbors']['reward_per_neighbor']
            assert await uses(unit,token)==1
        async with db.transaction() as unit:
            owner=service(unit,owner_account,'Owner')
            assert (await owner.me())['neighbors'][recipient_id]['status']=='accepted'
            assert (await owner.me())['coins']==owner_before+result['neighbors']['reward_per_neighbor']
            assert (await owner.share_link_status())['uses']==1
        async with db.transaction() as unit:
            recipient=service(unit,recipient_account,'Recipient')
            replay=await recipient.join_share_invite(token)
            assert replay['neighbor_reward_paid'] is False and replay['notice']=='Приглашение уже принято.'
            assert await uses(unit,token)==1   # a replay does not spend a place
        # The same link brings more neighbors; reward limits apply as for ordinary neighborhoods.
        async with db.transaction() as unit:
            other=service(unit,other_account,'Other')
            await other.open()
            try:await other.revoke_share_invite(token)
            except FarmError as error:assert error.code=='invite_unknown'
            else:raise AssertionError('foreign invitation was revoked')
            other_farm=await other.me()
            from qw_farm import economy
            other_farm['neighbor_bonus']={'day':economy.moscow_day(now[0]),'today':5,'total':5,'earned':0}
            await unit.save(other_farm)
        async with db.transaction() as unit:
            other=service(unit,other_account,'Other')
            limited=await other.join_share_invite(token)
            assert limited['neighbor_reward_paid'] is False
            assert 'лимит наград' in limited['notice'].lower()
            assert (await other.me())['neighbors'][owner_id]['status']=='accepted'
            assert await uses(unit,token)==2
        async with db.transaction() as unit:
            third=service(unit,third_account,'Third')
            await third.open()
            third_farm=await third.me()
            third_farm['neighbor_bonus']={'day':-1,'today':0,'total':40,'earned':0}
            await unit.save(third_farm)
        async with db.transaction() as unit:
            third=service(unit,third_account,'Third')
            limited_total=await third.join_share_invite(token)
            assert limited_total['neighbor_reward_paid'] is False
            assert (await third.me())['neighbors'][owner_id]['status']=='accepted'
            assert await uses(unit,token)==3
            # Full link: the next farm is refused, the owner automatically gets a new link.
            await unit.execute(unit.t['share_invites'].update().where(
                unit.t['share_invites'].c.token_hash==invite_digest(token)).values(max_uses=3))
        async with db.transaction() as unit:
            fourth=service(unit,fourth_account,'Fourth')
            await fourth.open()
            try:await fourth.join_share_invite(token)
            except FarmError as error:assert error.code=='invite_used'
            else:raise AssertionError('a full link accepted one more neighbor')
            owner=service(unit,owner_account,'Owner')
            fresh=await owner.share_link()
            assert fresh['token']!=token and fresh['uses']==0
        async with db.transaction() as unit:
            fourth=service(unit,fourth_account,'Fourth')
            assert (await fourth.join_share_invite(fresh['token']))['neighbors']['neighbors'][0]['id']==owner_id
            # An existing neighbor tapping the shared link takes no place out of its limit.
            again=await service(unit,recipient_account,'Recipient').join_share_invite(fresh['token'])
            assert again['notice']=='Вы уже соседи.' and again['neighbor_reward_paid'] is False
            assert await uses(unit,fresh['token'])==1
        # «Сменить ссылку»: the old link stops working, neighborhoods made through it stay.
        async with db.transaction() as unit:
            owner=service(unit,owner_account,'Owner')
            rotated=await owner.share_link(rotate=True)
            assert rotated['token']!=fresh['token']
            assert await owner.revoke_share_invite(rotated['token'])=={'revoked':True}
            try:await owner.revoke_share_invite(rotated['token'])
            except FarmError as error:assert error.code=='invite_expired'
            else:raise AssertionError('a revoked link was revoked twice')
            assert recipient_id in (await owner.me())['neighbors']
        async with db.transaction() as unit:
            recipient=service(unit,recipient_account,'Recipient')
            for stale in (fresh['token'],rotated['token']):
                try:await recipient.join_share_invite(stale)
                except FarmError as error:assert error.code in ('invite_expired','invite_unknown')   # replaced links are pruned
                else:raise AssertionError('a replaced link still works')
        # Expiry and pruning.
        async with db.transaction() as unit:
            expiring=(await service(unit,owner_account,'Owner').share_link())['token']
        now[0]+=SHARE_INVITE_TTL+1
        async with db.transaction() as unit:
            recipient=service(unit,recipient_account,'Recipient')
            try:await recipient.join_share_invite(expiring)
            except FarmError as error:assert error.code=='invite_expired'
            else:raise AssertionError('expired invite unexpectedly succeeded')
        async with db.transaction() as unit:
            owner=service(unit,owner_account,'Owner')
            renewed=await owner.share_link()   # also prunes all expired rows with their acceptances
            assert renewed['token'] not in (token,expiring)
            assert await unit.share_invite(invite_digest(token)) is None
            assert await unit.share_invite(invite_digest(expiring)) is None
            assert (await unit.execute(select(func.count()).select_from(unit.t['share_invite_uses']))).scalar_one()==0
            try:await service(unit,recipient_account,'Recipient').join_share_invite(token)
            except FarmError as error:assert error.code=='invite_unknown'
            else:raise AssertionError('expired invite survived its retention window')
            try:await service(unit,other_account,'Other').join_share_invite('bad-token')
            except FarmError as error:assert error.code=='invalid_invite'
            else:raise AssertionError('malformed invite unexpectedly succeeded')
        db.engine.dispose()
    asyncio.run(run())


def test_demo_link_survives_requests_changes_with_the_secret_and_legacy_rows_still_cap_issuance():
    async def run():
        db=DemoDatabase(':memory:')
        account,friend=uuid4(),uuid4()
        with db.engine.begin() as connection:
            for value in (account,friend):
                connection.execute(db.accounts.insert().values(id=value,name='Player',recovery_hash=uuid4().hex))
        now=[1_700_000_000]
        async with db.transaction() as unit:
            service=FarmService(unit,Principal(str(account),'Player'),clock=lambda:now[0])
            service.invite_secret='s'*32
            await service.open()
            farm_id=(await service.me())['id']
            first=(await service.share_link())['token']
            assert (await service.share_link())['token']==first
            service.invite_secret='t'*32   # a changed secret cannot rebuild the link: a new one replaces it
            second=(await service.share_link())['token']
            assert second!=first
            assert await unit.share_invite(invite_digest(first)) is None   # closed and pruned at once
        async with db.transaction() as unit:
            service=FarmService(unit,Principal(str(account),'Player'),clock=lambda:now[0])
            service.invite_secret='t'*32
            assert (await service.share_link())['token']==second
            # Legacy one-use rows from before 0037 still count toward the active ceiling.
            from uuid import UUID
            for index in range(MAX_ACTIVE_SHARE_INVITES_PER_FARM-1):
                await unit.execute(unit.t['share_invites'].insert().values(
                    token_hash=invite_digest(f'{index:043d}'),farm_id=UUID(farm_id),expires_at=now[0]+60))
        async with db.transaction() as unit:
            friend_service=FarmService(unit,Principal(str(friend),'Friend'),clock=lambda:now[0])
            await friend_service.open()
            assert (await friend_service.join_share_invite('0'*43))['notice'].startswith('Теперь вы соседи')
            try:await friend_service.join_share_invite('0'*43)
            except FarmError:raise AssertionError('a replay of a legacy link must be idempotent')
            assert (await unit.share_invite(invite_digest('0'*43)))['uses']==1
        db.engine.dispose()
    asyncio.run(run())
