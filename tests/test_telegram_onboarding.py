"""Signed first login and mapping invariants in isolated real PostgreSQL."""
import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from storage.games import GameRepository
from storage.admin_actions import operation_fence
from storage import mini_app as mini_storage
from storage.mini_app import MiniAppError, MiniAppStore
from storage.models import (Account, AccountIdentity, AlchemyProgress, Chat,
                            MiniAppSession, Room, User)
from tests.test_farm_platform import API, FARM_HEADERS, GUEST_HEADERS, environment, farm_pg_url
from tests.test_mini_app import NOW, ORIGIN, TOKEN, signed
from web.mini_auth import validate_init_data

UID = 981020000099
STAMP = datetime.fromtimestamp(NOW, timezone.utc)


async def counts(db):
    async with db.transaction() as session:
        return tuple([await session.scalar(select(func.count()).select_from(model))
            for model in (User, Account, AccountIdentity, MiniAppSession, Chat, Room)])


def test_signed_resume_requires_existing_mapping_and_never_provisions(farm_pg_url):
    async def run():
        async with environment(farm_pg_url) as env:
            missing = await env.client.post('/api/mini/session/resume',
                                            json={'init_data': signed(UID, query_id='first')})
            assert missing.status_code == 404
            assert await counts(env.db) == (0, 0, 0, 0, 0, 0)
            created = await env.client.post('/api/mini/session',
                                            json={'init_data': signed(UID, query_id='created')})
            assert created.status_code == 200, created.text
            env.client.cookies.delete('mqb_mini')
            resumed = await env.client.post('/api/mini/session/resume',
                                            json={'init_data': signed(UID, query_id='returned')})
            assert resumed.status_code == 200, resumed.text
            account_id = (await env.client.get('/api/mini/me')).json()['account_id']
            async with env.db.transaction() as session:
                assert str((await session.get(User, UID)).account_id) == account_id
            assert await counts(env.db) == (1, 1, 1, 2, 1, 0)
    asyncio.run(run())


def test_first_logins_serialize_mapping_and_replays(farm_pg_url):
    async def run():
        async with environment(farm_pg_url) as env:
            store = env.app.state.mini_store
            identities = [validate_init_data(signed(UID, query_id=str(i)), TOKEN, now=NOW)
                          for i in range(8)]
            await asyncio.gather(*(store.create_session(identity, session_limit=None)
                                   for identity in identities))
            assert await counts(env.db) == (1, 1, 1, 8, 1, 0)
            with pytest.raises(MiniAppError) as replay:
                await store.create_session(identities[0], session_limit=None)
            assert replay.value.status == 409
            async with env.db.transaction() as session:
                user = await session.get(User, UID)
                link = await session.scalar(select(AccountIdentity))
                assert link.account_id == user.account_id
                assert link.verified_at == STAMP and link.revoked_at is None
                assert user.global_score == 0 and user.metadata_json == {}
                assert await GameRepository(session).existing_account_for_telegram_user(UID) == user.account_id
    asyncio.run(run())


def test_concurrent_same_init_data_creates_only_one_session(farm_pg_url):
    async def run():
        async with environment(farm_pg_url) as env:
            store = env.app.state.mini_store
            identity = validate_init_data(signed(UID), TOKEN, now=NOW)
            outcomes = await asyncio.gather(*(store.create_session(identity) for _ in range(4)),
                                            return_exceptions=True)
            assert sum(isinstance(item, dict) for item in outcomes) == 1
            assert [item.status for item in outcomes if isinstance(item, MiniAppError)] == [409] * 3
            assert await counts(env.db) == (1, 1, 1, 1, 1, 0)
    asyncio.run(run())


def test_denied_or_rolled_back_first_login_leaves_no_profile(farm_pg_url):
    async def run():
        async with environment(farm_pg_url, allowed_user_ids={UID + 1}) as env:
            invalid = await env.client.post('/api/mini/session', json={'init_data': signed(UID) + 'bad'})
            assert invalid.status_code == 401
            denied = await env.client.post('/api/mini/session', json={'init_data': signed(UID)})
            assert denied.status_code == 403
            assert await counts(env.db) == (0, 0, 0, 0, 0, 0)
            store = MiniAppStore(env.db, TOKEN, clock=lambda: NOW)
            with pytest.raises(MiniAppError) as quota:
                await store.create_session(validate_init_data(signed(UID), TOKEN, now=NOW), session_limit=0)
            assert quota.value.status == 429
            assert await counts(env.db) == (0, 0, 0, 0, 0, 0)
    asyncio.run(run())


def test_login_preserves_existing_account_profile_and_progress(farm_pg_url):
    async def run():
        async with environment(farm_pg_url) as env:
            account_id = uuid4()
            async with env.db.transaction() as session:
                session.add(Account(id=account_id, display_name='Original account'))
                await session.flush()
                session.add(User(id=UID, account_id=account_id, display_name='Original user',
                                 global_score=Decimal('42.250'), metadata_json={'kept': True}))
                await session.flush()
                session.add(AlchemyProgress(account_id=account_id, user_id=UID,
                                            attempts=15, discovered=['fire'], points_total=Decimal('7.500')))
            for index in range(2):
                response = await env.client.post('/api/mini/session', json={'init_data': signed(UID, query_id=str(index))})
                assert response.status_code == 200, response.text
            async with env.db.transaction() as session:
                user = await session.get(User, UID)
                account = await session.get(Account, account_id)
                progress = await session.get(AlchemyProgress, account_id)
                assert user.account_id == account_id and user.display_name == 'Original user'
                assert user.global_score == Decimal('42.250') and user.metadata_json == {'kept': True}
                assert account.display_name == 'Original account'
                assert (progress.attempts, progress.discovered, progress.points_total) == (15, ['fire'], Decimal('7.500'))
            assert await counts(env.db) == (1, 1, 1, 2, 1, 0)
    asyncio.run(run())


def test_first_login_keeps_the_current_guest_account_separate(farm_pg_url):
    async def run():
        async with environment(farm_pg_url) as env:
            guest = await env.client.post('/api/guest/start', headers=GUEST_HEADERS)
            assert guest.status_code == 200
            guest_id = guest.json()['account_id']
            guest_cookie = env.client.cookies.get('mqb_guest')
            response = await env.client.post('/api/mini/session', json={'init_data': signed(UID)})
            assert response.status_code == 200
            assert env.client.cookies.get('mqb_guest') == guest_cookie
            async with env.db.transaction() as session:
                user = await session.get(User, UID)
                link = await session.scalar(select(AccountIdentity))
                assert str(user.account_id) != guest_id and link.account_id == user.account_id
            assert await counts(env.db) == (1, 2, 1, 1, 1, 0)
    asyncio.run(run())


@pytest.mark.parametrize('state', ['user_blocked', 'user_archived', 'account_blocked',
    'account_archived', 'revoked', 'unverified', 'mismatch', 'missing_mapping', 'missing_user'])
def test_login_fails_closed_for_unavailable_or_conflicting_mapping(farm_pg_url, state):
    async def run():
        async with environment(farm_pg_url) as env:
            account_id = uuid4()
            async with env.db.transaction() as session:
                session.add(Account(id=account_id, display_name='Existing',
                    bot_blocked=state == 'account_blocked', archived=state == 'account_archived'))
                await session.flush()
                if state == 'mismatch':
                    other = Account()
                    session.add(other)
                    await session.flush()
                if state != 'missing_user':
                    session.add(User(id=UID, account_id=None if state == 'missing_mapping' else account_id,
                        bot_blocked=state == 'user_blocked', archived=state == 'user_archived'))
                session.add(AccountIdentity(account_id=other.id if state == 'mismatch' else account_id,
                    provider='telegram', provider_subject=str(UID),
                    verified_at=None if state == 'unverified' else STAMP,
                    revoked_at=STAMP if state == 'revoked' else None))
            before = await counts(env.db)
            response = await env.client.post('/api/mini/session', json={'init_data': signed(UID)})
            assert response.status_code == 403, response.text
            assert await counts(env.db) == before
    asyncio.run(run())


@pytest.mark.parametrize('state', ['revoked', 'unverified', 'mismatch', 'user_archived', 'account_archived', 'account_blocked'])
def test_mapping_changes_revoke_mini_and_farm_access_without_writes(farm_pg_url, state):
    async def run():
        async with environment(farm_pg_url) as env:
            response = await env.client.post('/api/mini/session', json={'init_data': signed(UID)})
            assert response.status_code == 200
            opened = await env.client.post(API + '/start?identity=telegram', headers=FARM_HEADERS)
            assert opened.status_code == 200, opened.text
            async with env.db.transaction() as session:
                user = await session.get(User, UID)
                account = await session.get(Account, user.account_id)
                link = await session.scalar(select(AccountIdentity))
                if state == 'revoked':
                    link.revoked_at = STAMP
                elif state == 'unverified':
                    link.verified_at = None
                elif state == 'mismatch':
                    other = Account()
                    session.add(other)
                    await session.flush()
                    link.account_id = other.id
                elif state == 'user_archived':
                    user.archived = True
                elif state == 'account_archived':
                    account.archived = True
                else:
                    account.bot_blocked = True
            before = await counts(env.db)
            assert (await env.client.get('/api/mini/me')).status_code == 401
            assert (await env.client.post('/api/mini/session/renew', headers={
                'Origin': ORIGIN, 'X-Mini-CSRF': '1'})).status_code == 401
            assert (await env.client.get(API + '/me?identity=telegram')).status_code == 401
            assert (await env.client.post(API + '/start?identity=telegram', headers=FARM_HEADERS)).status_code == 401
            assert await counts(env.db) == before
    asyncio.run(run())


def test_waiting_first_login_obeys_moderation_fence(farm_pg_url, monkeypatch):
    async def run():
        async with environment(farm_pg_url) as env:
            waiting = asyncio.Event()
            async def fenced(session):
                waiting.set()
                await operation_fence(session)
            monkeypatch.setattr(mini_storage, 'operation_fence', fenced)
            async with env.db.transaction() as session:
                await operation_fence(session, exclusive=True)
                pending = asyncio.create_task(env.app.state.mini_store.create_session(
                    validate_init_data(signed(UID), TOKEN, now=NOW)))
                await asyncio.wait_for(waiting.wait(), 5)
                session.add(User(id=UID, bot_blocked=True))
            with pytest.raises(MiniAppError) as denied:
                await asyncio.wait_for(pending, 5)
            assert denied.value.status == 403
            assert await counts(env.db) == (1, 0, 0, 0, 0, 0)
    asyncio.run(run())


def test_login_and_game_provision_the_same_legacy_mapping(farm_pg_url):
    async def run():
        async with environment(farm_pg_url) as env:
            async with env.db.transaction() as session:
                session.add(User(id=UID, display_name='Legacy'))
            async def game_mapping():
                async with env.db.transaction() as session:
                    await operation_fence(session)
                    return await GameRepository(session).account_for_telegram_user(UID)
            game_account, _ = await asyncio.gather(game_mapping(), env.app.state.mini_store.create_session(
                validate_init_data(signed(UID), TOKEN, now=NOW)))
            assert await counts(env.db) == (1, 1, 1, 1, 1, 0)
            async with env.db.transaction() as session:
                assert (await session.get(User, UID)).account_id == game_account
    asyncio.run(run())
