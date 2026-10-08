"""Guest auth acceptance: isolated disposable PG schemas and HTTP boundaries."""
import asyncio
import os
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import func, select, text

from storage.database import normalize_database_url
from storage.guest_accounts import GuestAccounts, credential_hash, SESSION_SECONDS
from storage.mini_app import MiniAppError
from storage.models import (Account, Base, Game, GameEvent, GamePlayer, GuestSession,
                            Room, RoomMembership, User)
from tests.local_database import isolated_database
from web.mini_app import MiniAppSettings, create_app
from application.game_deadlines import GameDeadlineProcessor

ORIGIN = 'http://127.0.0.1:4185'
HEADERS = {'Origin': ORIGIN, 'X-Guest-CSRF': '1'}


@pytest.fixture
def guest_pg_url():
    url = os.getenv('TEST_DATABASE_URL')
    if not url:
        pytest.skip('TEST_DATABASE_URL is not configured; no production fallback')
    return normalize_database_url(url)


def test_guest_lifecycle_and_moderation(guest_pg_url):
    async def run():
        async with isolated_database(guest_pg_url) as (db, _):
            now = [1788120000]
            store = GuestAccounts(db, clock=lambda: now[0])
            profile, raw = await store.start()
            repeat, token = await store.start(raw)
            assert repeat == profile and token is None
            async with db.transaction() as session:
                assert await session.scalar(select(func.count()).select_from(Account)) == 1
                assert await session.scalar(select(func.count()).select_from(User)) == 0
                row = await session.get(GuestSession, credential_hash(raw))
                assert row.token_hash != raw and row.account_id is not None
            rotated, new_raw = await store.resume(raw)
            assert rotated['account_id'] == profile['account_id'] and new_raw == raw
            assert (await store.profile(raw))['account_id'] == profile['account_id']
            await store.logout(new_raw)
            with pytest.raises(MiniAppError):
                await store.profile(new_raw)
            _, raw = await store.start()
            now[0] += SESSION_SECONDS
            with pytest.raises(MiniAppError):
                await store.profile(raw)
            for flag in ('archived', 'bot_blocked', 'moderation_revision'):
                profile, raw = await store.start()
                async with db.transaction() as session:
                    row = await session.get(GuestSession, credential_hash(raw))
                    account = await session.get(Account, row.account_id)
                    setattr(account, flag, 1 if flag == 'moderation_revision' else True)
                with pytest.raises(MiniAppError):
                    await store.resume(raw)
    asyncio.run(run())


def test_concurrent_renewal_and_lost_response_are_retryable(guest_pg_url):
    async def run():
        async with isolated_database(guest_pg_url) as (db, _):
            store = GuestAccounts(db)
            _, raw = await store.start()
            outcomes = await asyncio.gather(store.resume(raw), store.resume(raw), return_exceptions=True)
            assert all(isinstance(item, tuple) and item[1] == raw for item in outcomes)
            assert (await store.resume(raw))[1] == raw
    asyncio.run(run())


def test_guest_http_cookie_restart_and_telegram_separation(guest_pg_url):
    async def run():
        async with isolated_database(guest_pg_url) as (db, _):
            settings = MiniAppSettings('', ORIGIN, offline=True)
            app = create_app(database=db, settings=settings)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
                response = await client.post('/api/guest/start', headers=HEADERS)
                assert response.status_code == 200
                cookie = response.headers['set-cookie']
                assert 'HttpOnly' in cookie and 'SameSite=strict' in cookie and 'Path=/' in cookie
                assert 'Secure' not in cookie
                aid = response.json()['account_id']
                assert (await client.post('/api/guest/start', headers=HEADERS)).json()['account_id'] == aid
                assert (await client.get('/api/mini/me')).status_code == 401
                assert (await client.post('/api/mini/session', json={})).status_code == 503
                app2 = create_app(database=db, settings=settings)
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app2), base_url=ORIGIN,
                                            cookies=client.cookies) as restarted:
                    assert (await restarted.get('/api/guest/me')).json()['account_id'] == aid
                    assert (await restarted.post('/api/guest/resume', headers=HEADERS)).status_code == 200
                    assert (await client.get('/api/guest/me')).status_code == 200
                    assert (await restarted.post('/api/guest/logout', headers=HEADERS)).status_code == 204
                    assert (await restarted.get('/api/guest/me')).status_code == 401
    asyncio.run(run())


def test_guest_boundaries_and_secure_cookie():
    async def run():
        for origin, offline in [(ORIGIN, True), ('https://quiz.example', False)]:
            app = create_app(database=SimpleNamespace(), settings=MiniAppSettings('', origin, offline=offline))
            app.state.guest_store.start = AsyncMock(return_value=({'account_id': 'test'}, 'a' * 43))
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
                for headers in ({}, {'Origin': origin}, {'Origin': 'https://evil.example', 'X-Guest-CSRF': '1'},
                                {'Origin': origin, 'X-Guest-CSRF': '1', 'Sec-Fetch-Site': 'cross-site'}):
                    assert (await client.post('/api/guest/start', headers=headers)).status_code == 403
                headers = {'Origin': origin, 'X-Guest-CSRF': '1'}
                response = await client.post('/api/guest/start', headers=headers)
                assert response.status_code == 200
                assert ('Secure' in response.headers['set-cookie']) is (not offline)
                for _ in range(9):
                    assert (await client.post('/api/guest/start', headers=headers)).status_code == 200
                assert (await client.post('/api/guest/start', headers=headers)).status_code == 429
        restricted = create_app(database=SimpleNamespace(), settings=MiniAppSettings('', ORIGIN, offline=True), allowed_user_ids={1})
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=restricted), base_url=ORIGIN) as client:
            assert (await client.post('/api/guest/start', headers=HEADERS)).status_code == 403
    asyncio.run(run())


def test_guest_room_invitation_http_flow_and_one_way_storage(guest_pg_url):
    async def run():
        async with isolated_database(guest_pg_url) as (db, _):
            app = create_app(database=db, settings=MiniAppSettings('', ORIGIN, offline=True))
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url=ORIGIN,
            ) as owner, httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url=ORIGIN,
            ) as invitee:
                owner_id = (await owner.post('/api/guest/start', headers=HEADERS)).json()['account_id']
                invitee_id = (await invitee.post('/api/guest/start', headers=HEADERS)).json()['account_id']
                created = await owner.post('/api/guest/rooms', headers=HEADERS, json={
                    'request_id': '08f0b432-9c9f-4ae7-9f1e-b1fdc937d199',
                    'title': 'Friends',
                })
                assert created.status_code == 200
                room_id = created.json()['id']
                issued = await owner.post(
                    f'/api/guest/rooms/{room_id}/invites', headers=HEADERS,
                    json={'expires_in_seconds': 3600, 'max_uses': 1},
                )
                assert issued.status_code == 200
                code = issued.json()['invite_code']
                listed = await owner.get(f'/api/guest/rooms/{room_id}/invites')
                assert listed.status_code == 200
                assert code not in listed.text

                joined = await invitee.post('/api/guest/rooms/join', headers=HEADERS,
                                            json={'invite_code': code})
                assert joined.status_code == 200
                assert joined.json()['id'] == room_id and joined.json()['joined'] is True
                replay = await invitee.post('/api/guest/rooms/join', headers=HEADERS,
                                            json={'invite_code': code})
                assert replay.status_code == 200 and replay.json()['joined'] is False
                own_rooms = await invitee.get('/api/guest/rooms')
                assert [item['id'] for item in own_rooms.json()['items']] == [room_id]
                assert invitee_id != owner_id

                revocation = await owner.delete(
                    f"/api/guest/rooms/{room_id}/invites/{issued.json()['id']}",
                    headers=HEADERS,
                )
                assert revocation.status_code == 204
                assert (await owner.get(f'/api/guest/rooms/{room_id}/invites')).json()['items'][0]['revoked']

                missing_csrf = await owner.post(
                    f'/api/guest/rooms/{room_id}/invites',
                    headers={'Origin': ORIGIN, 'Content-Type': 'application/json'},
                    json={'expires_in_seconds': 3600, 'max_uses': 2},
                )
                assert missing_csrf.status_code == 403
    asyncio.run(run())


def test_guest_standalone_mafia_http_lifecycle_is_account_scoped(guest_pg_url, monkeypatch):
    async def run():
        async with isolated_database(guest_pg_url) as (db, _):
            monkeypatch.setattr('domain.mafia.secrets.SystemRandom.shuffle', lambda self, values: None)
            app = create_app(database=db, settings=MiniAppSettings('', ORIGIN, offline=True))
            clients = [httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url=ORIGIN,
            ) for _ in range(5)]
            async with clients[0] as owner, clients[1] as p2, clients[2] as p3, clients[3] as p4, clients[4] as outsider:
                players = [owner, p2, p3, p4]
                account_ids = []
                for client in [*players, outsider]:
                    profile = await client.post('/api/guest/start', headers=HEADERS)
                    assert profile.status_code == 200
                    account_ids.append(profile.json()['account_id'])

                room_response = await owner.post('/api/guest/rooms', headers=HEADERS, json={
                    'request_id': 'ea045217-f0eb-489a-a109-e981ce4b7932',
                    'title': 'Ночной город',
                })
                assert room_response.status_code == 200
                room_id = room_response.json()['id']
                invitation = await owner.post(
                    f'/api/guest/rooms/{room_id}/invites', headers=HEADERS,
                    json={'expires_in_seconds': 3600, 'max_uses': 3},
                )
                assert invitation.status_code == 200
                code = invitation.json()['invite_code']
                for client in players[1:]:
                    joined = await client.post(
                        '/api/guest/rooms/join', headers=HEADERS,
                        json={'invite_code': code},
                    )
                    assert joined.status_code == 200

                base = f'/api/guest/rooms/{room_id}/mafia'
                created = await owner.post(
                    f'{base}/lobby', headers={**HEADERS, 'Idempotency-Key': 'mafia-create-001'},
                    json={},
                )
                assert created.status_code == 200
                lobby = created.json()['lobby']
                assert lobby['is_host'] and lobby['joined'] and len(lobby['players']) == 1
                for index, client in enumerate(players[1:], 2):
                    response = await client.post(
                        f'{base}/lobby/join',
                        headers={**HEADERS, 'Idempotency-Key': f'mafia-join-{index:03}'},
                        json={},
                    )
                    assert response.status_code == 200
                    lobby = response.json()['lobby']
                for index, client in enumerate(players):
                    response = await client.post(
                        f'{base}/lobby/ready',
                        headers={**HEADERS, 'Idempotency-Key': f'mafia-ready-{index:03}'},
                        json={'ready': True, 'expected_revision': lobby['revision']},
                    )
                    assert response.status_code == 200
                    lobby = response.json()['lobby']
                started = await owner.post(
                    f'{base}/lobby/start',
                    headers={**HEADERS, 'Idempotency-Key': 'mafia-start-001'},
                    json={'expected_revision': lobby['revision']},
                )
                assert started.status_code == 200
                lobby = started.json()['lobby']
                assert lobby['status'] == 'night' and lobby['ends_at']
                assert 'assignments' not in started.text
                assert all(account_id not in started.text for account_id in account_ids)
                roles = []
                for client in players:
                    response = await client.get(f'{base}/role')
                    assert response.status_code == 200
                    roles.append(response.json()['role'])
                assert sorted(roles) == ['citizen', 'citizen', 'citizen', 'mafia']
                outsider_lobby = await outsider.get(f'{base}/lobby')
                outsider_role = await outsider.get(f'{base}/role')
                assert outsider_lobby.status_code == 404 and outsider_role.status_code == 404
                replay = await owner.post(
                    f'{base}/lobby/start',
                    headers={**HEADERS, 'Idempotency-Key': 'mafia-start-001'},
                    json={'expected_revision': lobby['revision'] - 1},
                )
                assert replay.status_code == 200 and replay.json()['lobby'] == lobby
                action = await owner.post(
                    f'{base}/action', headers={**HEADERS, 'Idempotency-Key': 'mafia-action-001'},
                    json={'expected_revision': lobby['phase_revision'], 'target': 'p2'},
                )
                assert action.status_code == 200 and action.json()['role']['role'] == 'mafia'
                assert all(account_id not in action.text for account_id in account_ids)
                due_time = datetime.fromtimestamp(action.json()['lobby']['ends_at'], tz=timezone.utc)
                assert (await GameDeadlineProcessor(db).run_once(now=due_time))['mafia'] == 1
                lobby = (await owner.get(f'{base}/lobby')).json()['lobby']
                assert lobby['status'] == 'day'

                opened = await owner.post(
                    f'{base}/advance',
                    headers={**HEADERS, 'Idempotency-Key': 'mafia-advance-day'},
                    json={'expected_revision': lobby['revision']},
                )
                assert opened.status_code == 200 and opened.json()['lobby']['status'] == 'voting'
                lobby = opened.json()['lobby']
                voters = [(p3, 'p1'), (p4, 'p1'), (owner, 'p3')]
                for index, (client, target) in enumerate(voters):
                    response = await client.post(
                        f'{base}/vote',
                        headers={**HEADERS, 'Idempotency-Key': f'mafia-vote-{index:03}'},
                        json={'expected_revision': lobby['phase_revision'], 'target': target},
                    )
                    assert response.status_code == 200
                    lobby = response.json()['lobby']
                assert lobby['can_advance']
                finished = await owner.post(
                    f'{base}/advance',
                    headers={**HEADERS, 'Idempotency-Key': 'mafia-advance-vote'},
                    json={'expected_revision': lobby['revision']},
                )
                assert finished.status_code == 200
                lobby = finished.json()['lobby']
                assert lobby['status'] == 'finished' and lobby['winner'] == 'citizens'
                restarted = await owner.post(
                    f'{base}/restart',
                    headers={**HEADERS, 'Idempotency-Key': 'mafia-restart-001'},
                    json={'expected_revision': lobby['revision']},
                )
                assert restarted.status_code == 200
                assert restarted.json()['lobby']['status'] == 'lobby'
                assert all(not player['ready'] for player in restarted.json()['lobby']['players'])

            async with db.transaction() as session:
                assert await session.scalar(select(func.count()).select_from(User)) == 0
                assert await session.scalar(select(func.count()).select_from(Room).where(
                    Room.id == room_id)) == 1
                game = await session.scalar(select(Game).where(
                    Game.room_id == room_id, Game.is_current.is_(True)))
                assert game is not None and game.chat_id is None
                assert await session.scalar(select(func.count()).select_from(GamePlayer).where(
                    GamePlayer.game_id == game.id)) == 4
                assert await session.scalar(select(func.count()).select_from(GameEvent).where(
                    GameEvent.game_id == game.id, GameEvent.visibility == 'private')) == 0
    asyncio.run(run())


def test_alchemy_html_scopes_guest_before_game_boot_and_telegram_mode_is_explicit():
    async def run():
        app = create_app(database=SimpleNamespace(), settings=MiniAppSettings('', ORIGIN, offline=True))
        guest_id = '11111111-1111-4111-8111-111111111111'
        async def scoped_profile(credential):
            if not credential:
                raise MiniAppError(401, 'Гостевая сессия завершена')
            return {'account_id': guest_id}
        app.state.guest_store.profile = AsyncMock(side_effect=scoped_profile)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
            client.cookies.set('mqb_guest', 'a' * 43)
            page = await client.get('/app/alchemy?mode=guest')
            assert page.status_code == 200
            assert page.headers['cache-control'] == 'no-store'
            source = page.text
            scope_at = source.index('window.MQB_ALCHEMY_GUEST_ID=')
            game_at = source.index('const GUEST_ID=')
            assert scope_at < game_at
            assert guest_id in source
            assert 'alchemia.atlas.guest.' in source
            telegram = await client.get('/app/alchemy?mode=telegram')
            assert telegram.status_code == 200
            assert 'window.MQB_ALCHEMY_GUEST_ID=null;' in telegram.text
            client.cookies.clear()
            assert (await client.get('/app/alchemy?mode=guest')).status_code == 401
    asyncio.run(run())


def test_migration_backfills_unique_accounts_and_preserves_users(guest_pg_url, monkeypatch):
    async def run():
        from alembic.config import Config
        from alembic.migration import MigrationContext
        from alembic.operations import Operations
        from alembic.script import ScriptDirectory
        migration = ScriptDirectory.from_config(Config('alembic.ini')).get_revision('20261007_0014').module
        async with isolated_database(guest_pg_url) as (db, _):
            # Exercise the historic pre-0014 table shape. The shared helper creates
            # current metadata, whose later account FKs would invalidate this test.
            async with db.engine.begin() as connection:
                await connection.run_sync(Base.metadata.drop_all)
                await connection.exec_driver_sql("""
                    CREATE TABLE users (
                        id BIGINT PRIMARY KEY,
                        display_name VARCHAR(255) NOT NULL,
                        archived BOOLEAN NOT NULL DEFAULT FALSE,
                        bot_blocked BOOLEAN NOT NULL DEFAULT FALSE,
                        moderation_revision INTEGER NOT NULL DEFAULT 0,
                        moderation_reason TEXT NOT NULL DEFAULT '',
                        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                    )
                """)
                await connection.exec_driver_sql("""
                    INSERT INTO users (id, display_name, bot_blocked, moderation_revision, moderation_reason)
                    VALUES (901, 'Alice', TRUE, 3, 'blocked'), (902, 'Bob', FALSE, 0, '')
                """)
            async with db.engine.begin() as connection:
                def roundtrip(sync):
                    operations = Operations(MigrationContext.configure(sync))
                    before = list(sync.execute(text('SELECT * FROM users ORDER BY id')).mappings())
                    with monkeypatch.context() as patch:
                        patch.setattr(migration, 'op', operations)
                        migration.upgrade()
                        after = list(sync.execute(text('SELECT * FROM users ORDER BY id')).mappings())
                        assert [{k: v for k, v in row.items() if k != 'account_id'} for row in after] == [dict(row) for row in before]
                        assert len({row['account_id'] for row in after}) == 2
                        assert all(row['account_id'] is not None for row in after)
                        accounts = list(sync.execute(text('SELECT * FROM accounts')).mappings())
                        alice = next(row for row in accounts if row['display_name'] == 'Alice')
                        assert alice['bot_blocked'] and alice['moderation_revision'] == 3
                        migration.downgrade()
                        assert list(sync.execute(text('SELECT * FROM users ORDER BY id')).mappings()) == before
                        migration.upgrade()
                await connection.run_sync(roundtrip)
    asyncio.run(run())
