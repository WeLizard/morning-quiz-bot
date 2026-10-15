"""Form of address (он / она / не указывать): one Account setting for every game and channel.

Pure checks run anywhere; storage, HTTP and Farm checks need the disposable PostgreSQL
(TEST_DATABASE_URL), like the neighbouring guest/farm acceptance tests.
"""
import asyncio
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import text

from domain.address import (ADDRESS_FORMS, DEFAULT_ADDRESS_FORM, effective_address_form, g,
                            parse_address_form)
from storage.address_form import set_telegram_address_form, telegram_address_form
from storage.guest_accounts import GuestAccounts
from storage.mini_app import MiniAppError
from storage.models import Account, Base, User
from tests.local_database import isolated_database
from tests.test_farm_platform import API, FARM_HEADERS, GUEST_HEADERS, environment as farm_environment, farm_pg_url, player  # noqa: F401
from tests.test_guest_accounts import HEADERS, ORIGIN, guest_pg_url  # noqa: F401
from tests.test_mini_app import TOKEN, signed
from web.mini_app import MiniAppSettings, create_app

ROOT = Path(__file__).resolve().parent.parent
FORM_URL = '/api/account/address-form'


def test_g_picks_each_form_and_unknown_values_read_as_neutral():
    assert g('m', 'собрал', 'собрала', 'собрано') == 'собрал'
    assert g('f', 'собрал', 'собрала', 'собрано') == 'собрала'
    assert g('n', 'собрал', 'собрала', 'собрано') == 'собрано'
    for unknown in (None, '', 'x', 'M', 'he'):
        assert g(unknown, 'собрал', 'собрала', 'собрано') == 'собрано'
        assert effective_address_form(unknown) == DEFAULT_ADDRESS_FORM == 'n'


def test_parse_accepts_only_the_three_codes():
    assert [parse_address_form(code) for code in ADDRESS_FORMS] == ['m', 'f', 'n']
    for bad in (None, '', 'x', 'он', 'mm', 1, True, ['m']):
        with pytest.raises(ValueError):
            parse_address_form(bad)


def test_javascript_copies_are_identical_and_agree_with_python():
    web, farm = ROOT / 'web/mini_client/address.js', ROOT / 'qw_farm/static/address.js'
    assert web.read_bytes() == farm.read_bytes(), 'Farm copy of address.js drifted from the Mini App source'
    node = shutil.which('node')
    if node is None:
        pytest.skip('node is not installed')
    script = ("require('vm').runInNewContext(require('fs').readFileSync(process.argv[1], 'utf8'), {globalThis: globalThis});"
              "const a = globalThis.QWAddress; console.log(JSON.stringify(['m','f','n',undefined,null,'x'].map(f => a.g(f, 'M', 'F', 'N'))));")
    out = subprocess.run([node, '-e', script, str(web)], capture_output=True, text=True, check=True).stdout
    assert out.strip() == '["M","F","N","N","N","N"]'
    assert [g(f, 'M', 'F', 'N') for f in ('m', 'f', 'n', None, None, 'x')] == ['M', 'F', 'N', 'N', 'N', 'N']


def test_migration_is_additive_nullable_and_checked(guest_pg_url, monkeypatch):  # noqa: F811
    async def run():
        from alembic.config import Config
        from alembic.migration import MigrationContext
        from alembic.operations import Operations
        from alembic.script import ScriptDirectory
        script = ScriptDirectory.from_config(Config('alembic.ini'))
        migration = script.get_revision('20261015_0030').module
        assert migration.down_revision == '20261011_0029'
        async with isolated_database(guest_pg_url) as (db, _):
            async with db.engine.begin() as connection:
                await connection.run_sync(Base.metadata.drop_all)
                await connection.exec_driver_sql(
                    "CREATE TABLE accounts (id UUID PRIMARY KEY, display_name VARCHAR(255) NOT NULL)")
                await connection.exec_driver_sql(
                    "INSERT INTO accounts VALUES ('00000000-0000-4000-8000-000000000001', 'Ира')")

                def roundtrip(sync):
                    with monkeypatch.context() as patch:
                        patch.setattr(migration, 'op', Operations(MigrationContext.configure(sync)))
                        migration.upgrade()
                        row = sync.execute(text('SELECT display_name, address_form FROM accounts')).one()
                        assert tuple(row) == ('Ира', None)  # existing accounts are untouched: "not asked yet"
                        sync.execute(text("UPDATE accounts SET address_form = 'f'"))
                        with pytest.raises(Exception):
                            sync.execute(text("UPDATE accounts SET address_form = 'x'"))
                await connection.run_sync(roundtrip)
    asyncio.run(run())


def test_guest_default_choice_projection_and_persistence(guest_pg_url):  # noqa: F811
    async def run():
        async with isolated_database(guest_pg_url) as (db, _):
            store = GuestAccounts(db, clock=lambda: 1788120000)
            profile, raw = await store.start()
            assert (profile['address_form'], profile['address_form_chosen']) == ('n', False)
            changed = await store.update_address_form(raw, 'f')
            assert (changed['address_form'], changed['address_form_chosen']) == ('f', True)
            # A new store object (a restart) reads the stored value back.
            again = await GuestAccounts(db, clock=lambda: 1788120000).profile(raw)
            assert (again['address_form'], again['address_form_chosen']) == ('f', True)
            # "Не указывать" is an explicit answer: chosen, but still neutral wording.
            neutral = await store.update_address_form(raw, 'n')
            assert (neutral['address_form'], neutral['address_form_chosen']) == ('n', True)
            for bad in ('x', None, '', 'он'):
                with pytest.raises(MiniAppError) as error:
                    await store.update_address_form(raw, bad)
                assert error.value.status == 400
            assert (await store.profile(raw))['address_form'] == 'n'
    asyncio.run(run())


def test_guest_http_choice_registration_and_csrf(guest_pg_url):  # noqa: F811
    async def run():
        async with isolated_database(guest_pg_url) as (db, _):
            app = create_app(database=db, settings=MiniAppSettings('', ORIGIN, offline=True))
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
                started = await client.post('/api/guest/start', headers=HEADERS)
                assert started.json()['address_form'] == 'n' and started.json()['address_form_chosen'] is False
                url = FORM_URL + '?identity=guest'
                assert (await client.post(url, json={'address_form': 'f'}, headers={'Origin': ORIGIN})).status_code == 403
                for bad in ({'address_form': 'x'}, {'address_form': 1}, {}, {'address_form': 'm', 'extra': 1}):
                    assert (await client.post(url, json=bad, headers=HEADERS)).status_code in {400, 422}
                saved = await client.post(url, json={'address_form': 'f'}, headers=HEADERS)
                assert saved.status_code == 200, saved.text
                assert saved.json()['address_form'] == 'f'
                me = (await client.get('/api/guest/me')).json()
                assert (me['address_form'], me['address_form_chosen']) == ('f', True)
                # A password account created from this guest keeps the chosen form.
                registered = await client.post('/api/account/register', headers=HEADERS,
                                               json={'login': 'ira_form', 'password': 'correct horse battery'})
                assert registered.status_code == 200, registered.text
                assert registered.json()['address_form'] == 'f'
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as fresh:
                created = await fresh.post('/api/account/register', headers=HEADERS, json={
                    'login': 'new_form', 'password': 'correct horse battery', 'address_form': 'm'})
                assert created.status_code == 200, created.text
                assert (created.json()['address_form'], created.json()['address_form_chosen']) == ('m', True)
                bad = await fresh.post('/api/account/register', headers=HEADERS, json={
                    'login': 'bad_form', 'password': 'correct horse battery', 'address_form': 'zzz'})
                assert bad.status_code == 400
                login = await fresh.post('/api/account/login', headers=HEADERS,
                                         json={'login': 'new_form', 'password': 'correct horse battery'})
                assert login.json()['address_form'] == 'm'
    asyncio.run(run())


def test_telegram_account_shares_the_setting_between_bot_mini_app_and_endpoint(guest_pg_url):  # noqa: F811
    async def run():
        user_id = 981020000777
        async with isolated_database(guest_pg_url) as (db, _):
            now = 1788120000
            app = create_app(database=db, settings=MiniAppSettings(TOKEN, ORIGIN, offline=True), clock=lambda: now)
            # Bot side: nothing chosen yet, then a choice provisions the Account like a first Mini App login.
            assert await telegram_address_form(db, user_id) == ('n', False)
            assert await set_telegram_address_form(db, user_id, 'f') == 'f'
            assert await telegram_address_form(db, user_id) == ('f', True)
            with pytest.raises(ValueError):
                await set_telegram_address_form(db, user_id, 'x')
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
                login = await client.post('/api/mini/session', json={'init_data': signed(user_id, date=now)})
                assert login.status_code == 200, login.text
                me = (await client.get('/api/mini/me')).json()
                assert (me['address_form'], me['address_form_chosen']) == ('f', True)
                changed = await client.post(FORM_URL + '?identity=telegram', json={'address_form': 'm'}, headers=HEADERS)
                assert changed.status_code == 200, changed.text
                assert (await client.get('/api/mini/me')).json()['address_form'] == 'm'
            assert await telegram_address_form(db, user_id) == ('m', True)
            async with db.transaction() as session:
                account = await session.get(Account, (await session.get(User, user_id)).account_id)
                assert account.address_form == 'm'
    asyncio.run(run())


def test_farm_projection_carries_the_account_form_for_both_channels(farm_pg_url):  # noqa: F811
    async def run():
        async with farm_environment(farm_pg_url) as env:
            async with player(env, 'guest') as p:
                start = (await p.client.post(API + '/start', params={'identity': 'guest'}, headers=FARM_HEADERS)).json()
                assert start['address_form'] == 'n'
                saved = await p.client.post(FORM_URL + '?identity=guest', json={'address_form': 'f'}, headers=GUEST_HEADERS)
                assert saved.status_code == 200, saved.text
                me = (await p.client.get(API + '/me', params={'identity': 'guest'})).json()
                assert me['address_form'] == 'f'
                again = (await p.client.post(API + '/start', params={'identity': 'guest'}, headers=FARM_HEADERS)).json()
                assert again['address_form'] == 'f'
            async with player(env, 'telegram') as t:
                assert (await t.client.get(API + '/me', params={'identity': 'telegram'})).json()['address_form'] == 'n'
                assert await set_telegram_address_form(env.db, t.user_id, 'm') == 'm'
                assert (await t.client.get(API + '/me', params={'identity': 'telegram'})).json()['address_form'] == 'm'
    asyncio.run(run())


def test_bot_menu_card_shows_and_saves_the_choice(guest_pg_url, monkeypatch):  # noqa: F811
    from modules import telegram_menu

    async def run():
        async with isolated_database(guest_pg_url) as (db, _):
            shown = []

            async def card(update, context, text, rows, **kwargs):
                shown.append((text, [[(b.text, b.callback_data) for b in row] for row in rows]))

            monkeypatch.setattr(telegram_menu, 'card', card)
            context = SimpleNamespace(bot_data={'data_manager': SimpleNamespace(
                postgres_storage=SimpleNamespace(database=db))})
            update = SimpleNamespace(effective_user=SimpleNamespace(id=981020000888))
            await telegram_menu.address_card(update, context, 'nav:address')
            text, rows = shown[-1]
            assert 'пока не выбрано' in text
            assert [b[1] for b in rows[0]] == ['addr:m', 'addr:f', 'addr:n']
            await telegram_menu.address_card(update, context, 'addr:f')
            text, rows = shown[-1]
            assert 'Сейчас: <b>она</b>' in text and rows[0][1][0].startswith('✅')
            assert await telegram_address_form(db, 981020000888) == ('f', True)
            await telegram_menu.address_card(update, context, 'addr:n')
            assert 'Сейчас: <b>не указывать</b>' in shown[-1][0]
    asyncio.run(run())


def _fresh_trip(route):
    from tests.test_farm_automation_r7 import T0
    from tests.test_farm_fishing import act, fishing_farm
    state = fishing_farm(route)
    act(state, 'start_trip', {'route': route, 'guide': ''}, key='trip-' + route)
    return state, T0


@pytest.mark.parametrize('route, fragment', [
    ('pond_bank', {'m': 'ты вернулся раньше срока без улова', 'f': 'ты вернулась раньше срока без улова',
                   'n': 'возвращение раньше срока, улова нет'}),
    ('timber_path', {'m': 'ты вернулся раньше срока и ничего не успел собрать',
                     'f': 'ты вернулась раньше срока и ничего не успела собрать',
                     'n': 'возвращение раньше срока: собрать ничего не удалось'}),
])
def test_farm_early_return_text_follows_the_players_form(route, fragment):
    from qw_farm.domain import apply
    for form, expected in fragment.items():
        state, t0 = _fresh_trip(route)
        text = apply(state, state, 'abort_trip', {'trip': 'trip-' + route}, t0 + 61, 'abort-' + form, form=form)
        assert expected in text and text.endswith('Опыта нет, взятое не возвращается.')
        assert '(а)' not in text


def test_farm_busy_error_follows_the_players_form():
    from qw_farm.domain import FarmError, apply
    seen = {}
    for form in ('m', 'f', 'n'):
        state, t0 = _fresh_trip('pond_bank')
        with pytest.raises(FarmError) as error:
            apply(state, state, 'start_trip', {'route': 'pond_bank', 'guide': ''}, t0, 'second-' + form, form=form)
        seen[form] = error.value.message
    assert seen['m'].startswith('Ты уже занят вылазкой или рыбалкой.')
    assert seen['f'].startswith('Ты уже занята вылазкой или рыбалкой.')
    assert seen['n'].startswith('Твоё место для вылазок и рыбалки уже занято.')
    assert all(text.endswith('Во вторую можно отправить проводника.') for text in seen.values())
