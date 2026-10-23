"""«Контрастный режим»: one Account setting for the hub and every game (docs/design/UI_RULES.md §16).

Pure checks run anywhere; storage and HTTP checks need the disposable PostgreSQL (TEST_DATABASE_URL).
"""
import asyncio
import re
from pathlib import Path

import httpx
import sqlalchemy as sa

from storage.models import Account, User
from tests.local_database import isolated_database
from tests.test_account_merge import environment as merge_environment, make_account, merge, pg_url  # noqa: F401
from tests.test_guest_accounts import HEADERS, ORIGIN, guest_pg_url  # noqa: F401
from tests.test_farm_platform import farm_pg_url  # noqa: F401
from tests.test_mini_app import TOKEN, signed
from web.mini_app import MiniAppSettings, create_app

ROOT = Path(__file__).resolve().parent.parent
URL = '/api/account/contrast-mode'


def test_model_column_is_an_additive_boolean_with_a_false_default():
    column = Account.__table__.c.contrast_mode
    assert isinstance(column.type, sa.Boolean) and not column.nullable
    assert str(column.server_default.arg) == 'false'
    migration = (ROOT / 'alembic' / 'versions' / '20261023_0040_account_contrast_mode.py').read_text(encoding='utf-8')
    assert "down_revision = \"20261023_village_build\"" in migration
    assert 'server_default="false"' in migration and 'drop_column("accounts", "contrast_mode")' in migration


def test_guest_switch_is_stored_projected_and_validated(guest_pg_url):  # noqa: F811
    async def run():
        async with isolated_database(guest_pg_url) as (db, _):
            app = create_app(database=db, settings=MiniAppSettings('', ORIGIN, offline=True))
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
                started = await client.post('/api/guest/start', headers=HEADERS)
                assert started.json()['contrast_mode'] is False
                url = URL + '?identity=guest'
                # Cookie-authenticated write without the CSRF header is refused.
                assert (await client.post(url, json={'enabled': True}, headers={'Origin': ORIGIN})).status_code == 403
                for bad in ({'enabled': 'yes'}, {'enabled': 1}, {}, {'enabled': True, 'extra': 1}):
                    assert (await client.post(url, json=bad, headers=HEADERS)).status_code in {400, 422}
                saved = await client.post(url, json={'enabled': True}, headers=HEADERS)
                assert saved.status_code == 200, saved.text
                assert saved.json() == {'contrast_mode': True}
                assert (await client.get('/api/guest/me')).json()['contrast_mode'] is True
                off = await client.post(url, json={'enabled': False}, headers=HEADERS)
                assert off.json() == {'contrast_mode': False}
                assert (await client.get('/api/guest/me')).json()['contrast_mode'] is False
    asyncio.run(run())


def test_telegram_switch_is_the_same_account_setting(guest_pg_url):  # noqa: F811
    async def run():
        user_id = 981020000881
        async with isolated_database(guest_pg_url) as (db, _):
            now = 1788120000
            app = create_app(database=db, settings=MiniAppSettings(TOKEN, ORIGIN, offline=True), clock=lambda: now)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
                login = await client.post('/api/mini/session', json={'init_data': signed(user_id, date=now)})
                assert login.status_code == 200, login.text
                assert (await client.get('/api/mini/me')).json()['contrast_mode'] is False
                saved = await client.post(URL + '?identity=telegram', json={'enabled': True}, headers=HEADERS)
                assert saved.status_code == 200, saved.text
                assert (await client.get('/api/mini/me')).json()['contrast_mode'] is True
            async with db.transaction() as session:
                account = await session.get(Account, (await session.get(User, user_id)).account_id)
                assert account.contrast_mode is True
    asyncio.run(run())


def test_merge_keeps_the_mode_when_either_account_asked_for_it(pg_url):  # noqa: F811
    async def case():
        async with merge_environment(pg_url) as env:
            async with env.db.transaction() as session:
                guest, _ = await make_account(session, 'Гость')
                guest.contrast_mode = True
                main, _ = await make_account(session, 'Игрок', telegram=True, discovered=['water', 'steam'], points=3)
                gid, mid = guest.id, main.id
            await merge(env, mid, gid)
            async with env.db.transaction() as session:
                assert (await session.get(Account, mid)).contrast_mode is True
    asyncio.run(case())


def test_farm_echoes_the_account_mode_only_when_it_is_known():
    """/api/farm/v1/start and /me carry `contrast_mode` from the Account so a farm opened directly applies it;
    the demo stand has no Account setting and sends no field (the shell then keeps the device cache)."""
    from uuid import uuid4
    from qw_farm.persistence import DemoDatabase
    from qw_farm.service import FarmService, Principal

    async def run():
        db = DemoDatabase(':memory:')
        account = uuid4()
        with db.engine.begin() as connection:
            connection.execute(db.accounts.insert().values(id=account, name='Игрок', recovery_hash=uuid4().hex))
        async with db.transaction() as unit:
            unknown = FarmService(unit, Principal(str(account), 'Игрок'))
            assert 'contrast_mode' not in await unknown.open()
            assert 'contrast_mode' not in await unknown.view()
        for value in (True, False):
            async with db.transaction() as unit:
                known = FarmService(unit, Principal(str(account), 'Игрок', 'guest', 'n', value))
                assert (await known.open())['contrast_mode'] is value
                assert (await known.view())['contrast_mode'] is value
    asyncio.run(run())


def test_farm_projection_follows_the_switch(farm_pg_url):  # noqa: F811
    from tests.test_farm_platform import API, FARM_HEADERS, GUEST_HEADERS, environment as farm_environment, player

    async def run():
        async with farm_environment(farm_pg_url) as env:
            async with player(env, 'guest') as p:
                start = (await p.client.post(API + '/start', params={'identity': 'guest'}, headers=FARM_HEADERS)).json()
                assert start['contrast_mode'] is False
                saved = await p.client.post(URL + '?identity=guest', json={'enabled': True}, headers=GUEST_HEADERS)
                assert saved.status_code == 200, saved.text
                me = (await p.client.get(API + '/me', params={'identity': 'guest'})).json()
                assert me['contrast_mode'] is True
    asyncio.run(run())


def test_farm_client_applies_the_mode_and_draws_it():
    static = ROOT / 'qw_farm' / 'static'
    app = (static / 'app.js').read_text(encoding='utf-8')
    scene = (static / 'scene.js').read_text(encoding='utf-8')
    style = (static / 'style.css').read_text(encoding='utf-8')
    # Server value from /start and /me wins over the device cache; the farm never writes the attribute itself.
    assert 'QW?.prefs?.applyAccount?.(data)' in app and 'QW?.prefs?.applyAccount?.(me)' in app
    assert not re.search(r"setAttribute\(\s*['\"]data-qw-contrast|dataset\.qwContrast\s*=", app)
    # The scene reads the flag and --qw-night-dim, and re-reads them on qw:contrast.
    assert "getAttribute?.('data-qw-contrast')==='1'" in scene and "'--qw-night-dim'" in scene
    assert "addEventListener?.('qw:contrast'" in scene
    # Default style stays as it was: every contrast rule is scoped to the attribute.
    block = style[style.index('/* ==== «Контрастный режим»'):]
    rules = [r.strip() for r in block.split('}') if '{' in r and not r.strip().startswith(('@media', '/*'))]
    assert rules and all(r.lstrip('/* ').startswith(':root[data-qw-contrast="1"]') or ':root[data-qw-contrast="1"]' in r.split('{')[0] for r in rules)
    assert 'filter:var(--qw-scene-filter' in block and 'opacity:var(--qw-night-dim' in block
