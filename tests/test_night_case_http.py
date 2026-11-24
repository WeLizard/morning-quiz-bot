"""HTTP/auth/CSRF boundary tests. This file's service double does not prove PostgreSQL gameplay."""
import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest

from application.night_case import NightCaseError
from domain.night_case_state import PlayerActor, parse_command
from web.mini_app import MiniAppSettings, RequestLimits, create_app
from web.principal import Principal, PrincipalError

ORIGIN = 'http://127.0.0.1:4897'
ACCOUNT = UUID('70a7918e-00ad-40da-9ad8-136a4b2bbc0a')
GAME = '1ff30810-84ec-46ce-8820-5fa687cb7603'


class FakeService:
    def __init__(self):
        self.calls = []
        self.failure = None

    def __getattr__(self, method):
        async def call(**kwargs):
            self.calls.append((method, kwargs))
            assert kwargs['account_id'] == ACCOUNT
            if self.failure:
                raise self.failure
            if method == 'list_cases':
                return {'enabled': True, 'cases': [{'id': 'manor_lake_missing', 'version': 1, 'title': 'Усадьба', 'timezones': ['Europe/Berlin']}]}
            if method == 'get_view':
                return {'game_id': GAME, 'mode': 'night_case', 'public': {'clock': {'window_idx': 1, 'window_seq': 1}},
                        'self': {'actor_seq': 0}, 'menu': [], 'server_now': '2026-11-16T10:00:00Z', 'runtime_status': 'running'}
            if method == 'execute':
                parse_command(kwargs['command'], PlayerActor(str(ACCOUNT)), ruleset_version=2)
                return {'receipt': {'command_id': kwargs['command']['command_id'], 'accepted': True, 'code': 'accepted', 'actor_revision': 1}, 'caused_event_ids': [], 'caused_message_ids': []}
            if method == 'history':
                return {'items': [], 'next_cursor': None}
            return {'method': method}
        return call


def app_for(monkeypatch, *, enabled=True):
    service = FakeService()
    principals = []

    @asynccontextmanager
    async def resolve(request, **kwargs):
        identity = kwargs['identity']
        cookie = 'mqb_mini' if identity == 'telegram' else 'mqb_guest'
        if identity not in {'guest', 'telegram'} or request.cookies.get(cookie) != 's' * 43:
            raise PrincipalError('authentication', 'Требуется вход.')
        principals.append(kwargs)
        yield object(), Principal(str(ACCOUNT), 'Участник', identity)

    monkeypatch.setattr('web.principal.resolve_principal', resolve)
    app = create_app(database=SimpleNamespace(), settings=MiniAppSettings('', ORIGIN, offline=True),
                     night_case_enabled=enabled, night_case_service_factory=lambda session: service)
    return app, service, principals


def headers(identity='guest'):
    return {'Origin': ORIGIN, 'X-Mini-CSRF' if identity == 'telegram' else 'X-Guest-CSRF': '1'}


def test_stale_night_controller_cannot_write_as_new_guest_cookie(monkeypatch):
    old = UUID('70a7918e-00ad-40da-9ad8-136a4b2bbc0a')
    new = UUID('d9bd8616-2a9c-42f4-91f7-409e396da281')
    calls = []

    @asynccontextmanager
    async def resolve(request, **kwargs):
        account = {('a' * 43): old, ('b' * 43): new}.get(request.cookies.get('mqb_guest'))
        if account is None:
            raise PrincipalError('authentication', 'Требуется вход.')
        yield object(), Principal(str(account), 'Участник', 'guest')

    class Service:
        async def execute(self, **kwargs):
            parse_command(kwargs['command'], PlayerActor(str(kwargs['account_id'])), ruleset_version=2)
            calls.append(kwargs)
            return {'receipt': {'accepted': True, 'code': 'accepted', 'actor_revision': 1},
                    'caused_event_ids': [], 'caused_message_ids': []}

    monkeypatch.setattr('web.principal.resolve_principal', resolve)
    app = create_app(database=SimpleNamespace(), settings=MiniAppSettings('', ORIGIN, offline=True),
                     night_case_enabled=True, night_case_service_factory=lambda session: Service())

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN, headers={'X-Night-Expected-Viewer': str(ACCOUNT)},
                                     cookies={'mqb_guest': 'a' * 43}) as client:
            # The controller was opened by A; another tab now replaces the same cookie with B.
            client.cookies.set('mqb_guest', 'b' * 43)
            command = {'command_id': str(uuid4()), 'kind': 'seen', 'params': {},
                       'window_idx': 1, 'window_seq': 1, 'actor_seq': 0}
            response = await client.post(f'/api/night-case/games/{GAME}/commands?identity=guest',
                                         headers={**headers(), 'X-Night-Expected-Viewer': str(old)}, json=command)
            assert response.status_code == 409
            assert response.json()['code'] == 'profile_changed'
            assert calls == []

    asyncio.run(run())


@pytest.mark.parametrize('identity', ['guest', 'telegram'])
def test_viewer_bootstrap_and_fence_cover_reads_writes_and_cookie_replacement(monkeypatch, identity):
    other = UUID('d9bd8616-2a9c-42f4-91f7-409e396da281')
    cookie = 'mqb_mini' if identity == 'telegram' else 'mqb_guest'
    calls = []
    @asynccontextmanager
    async def resolve(request, **kwargs):
        account = {'a' * 43: ACCOUNT, 'b' * 43: other}.get(request.cookies.get(cookie))
        if account is None:
            raise PrincipalError('authentication', 'Требуется вход.')
        yield object(), Principal(str(account), 'Участник', identity,
                                  timezone='Asia/Tokyo' if account == ACCOUNT else None)
    class Service:
        def __getattr__(self, method):
            async def call(**kwargs):
                calls.append((method, kwargs['account_id']))
                # A historical own seat is not the canonical current viewer.
                return {'enabled': True, 'cases': [], 'self': {'account_id': str(ACCOUNT)}}
            return call
    monkeypatch.setattr('web.principal.resolve_principal', resolve)
    app = create_app(database=SimpleNamespace(), settings=MiniAppSettings('', ORIGIN, offline=True),
        night_case_enabled=True, night_case_service_factory=lambda session: Service())
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN,
            cookies={cookie: 'a' * 43}) as client:
            bootstrap = await client.get('/api/night-case/bootstrap', params={'identity': identity})
            assert bootstrap.status_code == 200 and bootstrap.json()['viewer_account_id'] == str(ACCOUNT)
            assert bootstrap.json()['account_timezone'] == 'Asia/Tokyo'
            client.cookies.set(cookie, 'b' * 43); calls.clear()
            command = {'command_id': str(uuid4()), 'kind': 'seen', 'params': {},
                'window_idx': 1, 'window_seq': 1, 'actor_seq': 0}
            for pinned in [None, str(ACCOUNT)]:
                pin = {} if pinned is None else {'X-Night-Expected-Viewer': pinned}
                for path in [f'/api/night-case/games/{GAME}/view', f'/api/night-case/games/{GAME}/history?stream=self',
                             '/api/rooms/own/night-case/current']:
                    response = await client.get(path + ('&' if '?' in path else '?') + 'identity=' + identity, headers=pin)
                    assert response.status_code == 409 and response.json()['code'] == 'profile_changed'
                response = await client.post(f'/api/night-case/games/{GAME}/commands?identity={identity}',
                    headers={**headers(identity), **pin}, json=command)
                assert response.status_code == 409 and response.json()['code'] == 'profile_changed'
            assert calls == []
            stale_bootstrap = await client.get('/api/night-case/bootstrap', params={'identity': identity},
                headers={'X-Night-Expected-Viewer': str(ACCOUNT)})
            assert stale_bootstrap.status_code == 409 and calls == []
            fresh = await client.get('/api/night-case/bootstrap', params={'identity': identity})
            assert fresh.json()['viewer_account_id'] == str(other)
            assert fresh.json()['account_timezone'] is None
            assert calls == [('list_cases', other)]
            accepted = await client.get(f'/api/night-case/games/{GAME}/view?identity={identity}',
                headers={'X-Night-Expected-Viewer': str(other)})
            assert accepted.status_code == 200 and calls[-1] == ('get_view', other)
    asyncio.run(run())


@pytest.mark.parametrize('identity', ['guest', 'telegram'])
def test_generic_room_writes_honor_optional_night_pin_before_services_and_keep_legacy_clients(monkeypatch, identity):
    other = UUID('d9bd8616-2a9c-42f4-91f7-409e396da281')
    cookie = 'mqb_mini' if identity == 'telegram' else 'mqb_guest'
    calls = []
    @asynccontextmanager
    async def resolve(request, **kwargs):
        yield object(), Principal(str(other), 'Другой тестовый игрок', identity)
    class Service:
        def __init__(self, session): calls.append(('factory', None))
        async def create(self, **kwargs): calls.append(('create', kwargs['account_id'])); return {'id': 'created'}
        async def join_by_short_code(self, **kwargs): calls.append(('join', kwargs['account_id'])); return {'id': 'joined'}
        async def create_invite(self, **kwargs):
            calls.append(('invite', kwargs['account_id'])); return {'invite_code': 'c' * 43, 'short_code': 'ABCDEF'}
    monkeypatch.setattr('web.principal.resolve_principal', resolve)
    monkeypatch.setattr('application.rooms.RoomApplicationService', Service)
    app = create_app(database=SimpleNamespace(), settings=MiniAppSettings('', ORIGIN, offline=True), night_case_enabled=False)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN, cookies={cookie: 'b' * 43}) as client:
            room_headers = {**headers(identity), 'X-Guest-CSRF': '1'}
            commands = [('/api/guest/rooms', {'request_id': str(uuid4()), 'title': 'Комната'}),
                        ('/api/guest/rooms/join', {'short_code': 'ABCDEF'}),
                        ('/api/guest/rooms/own/invites', {'expires_in_seconds': 3600, 'max_uses': 3})]
            for path, payload in commands:
                stale = await client.post(path + '?identity=' + identity, json=payload,
                    headers={**room_headers, 'X-Night-Expected-Viewer': str(ACCOUNT)})
                assert stale.status_code == 409 and stale.json()['code'] == 'profile_changed'
            assert calls == []
            for path, payload in commands:
                response = await client.post(path + '?identity=' + identity, json=payload, headers=room_headers)
                assert response.status_code == 200, response.text
            assert [entry for entry in calls if entry[0] != 'factory'] == [('create', other), ('join', other), ('invite', other)]
    asyncio.run(run())


@pytest.mark.parametrize('identity', ['guest', 'telegram'])
def test_identity_and_command_envelope_are_delegated_without_client_principal(monkeypatch, identity):
    async def run():
        app, service, principals = app_for(monkeypatch)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN, headers={'X-Night-Expected-Viewer': str(ACCOUNT)},
                                     cookies={'mqb_mini' if identity == 'telegram' else 'mqb_guest': 's' * 43}) as client:
            root = f'/api/night-case/games/{GAME}'
            bootstrap = await client.get('/api/night-case/bootstrap', params={'identity': identity})
            assert bootstrap.json()['capabilities'] == {'legacy_mafia': True, 'free_intent': False, 'ai_narrator': False}
            view = await client.get(root + '/view', params={'identity': identity})
            assert view.status_code == 200
            assert 'no-store' in view.headers['cache-control']
            assert service.calls[-1] == ('get_view', {'account_id': ACCOUNT, 'game_id': GAME})
            command = {'command_id': str(uuid4()), 'kind': 'seen', 'params': {}, 'window_idx': 1, 'window_seq': 1, 'actor_seq': 0}
            first = await client.post(root + '/commands', params={'identity': identity}, headers=headers(identity), json=command)
            second = await client.post(root + '/commands', params={'identity': identity}, headers=headers(identity), json=command)
            assert first.status_code == second.status_code == 200
            assert first.json() == second.json()
            assert principals[-1]['write'] is True
            forged = await client.post(root + '/commands', params={'identity': identity}, headers=headers(identity), json={**command, 'account_id': str(uuid4())})
            assert forged.status_code == 422
            assert 'traceback' not in forged.text.lower()
    asyncio.run(run())


@pytest.mark.parametrize('identity', ['guest', 'telegram'])
def test_new_namespaces_keep_origin_csrf_and_principal_guards(monkeypatch, identity):
    async def run():
        app, service, _ = app_for(monkeypatch)
        path = f'/api/night-case/games/{GAME}/quote?identity={identity}'
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN, headers={'X-Night-Expected-Viewer': str(ACCOUNT)}) as client:
            unauthenticated = await client.get(f'/api/night-case/games/{GAME}/view?identity={identity}')
            assert unauthenticated.status_code == 401
            client.cookies.set('mqb_mini' if identity == 'telegram' else 'mqb_guest', 's' * 43)
            for bad in [{}, {'Origin': 'https://foreign.invalid', **{k: v for k, v in headers(identity).items() if k != 'Origin'}}, {'Origin': ORIGIN}]:
                denied = await client.post(path, json={'kind': 'seen', 'params': {}}, headers=bad)
                assert denied.status_code == 403
            assert not service.calls
            accepted = await client.post(path, json={'kind': 'seen', 'params': {}}, headers=headers(identity))
            assert accepted.status_code == 200
    asyncio.run(run())


def test_feature_off_and_unwired_runtime_never_substitute_a_fake_product(monkeypatch):
    async def run():
        app, service, principals = app_for(monkeypatch, enabled=False)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN, headers={'X-Night-Expected-Viewer': str(ACCOUNT)}) as client:
            assert (await client.get('/api/night-case/bootstrap')).json() == {'enabled': False, 'cases': []}
            assert (await client.get(f'/api/night-case/games/{GAME}/view')).status_code == 404
            assert (await client.post(f'/api/night-case/games/{GAME}/commands', content='invalid')).status_code == 404
            for name in ['night-case-ui.js', 'night-case.css']:
                assert (await client.get('/app/' + name)).status_code == 200
            assert not service.calls and not principals
        unwired = create_app(database=SimpleNamespace(), settings=MiniAppSettings('', ORIGIN, offline=True), night_case_enabled=True)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=unwired), base_url=ORIGIN, headers={'X-Night-Expected-Viewer': str(ACCOUNT)}) as client:
            assert (await client.get('/api/night-case/bootstrap')).status_code == 503
    asyncio.run(run())


def test_strict_inputs_bounded_body_and_safe_errors(monkeypatch):
    async def run():
        app, service, _ = app_for(monkeypatch)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN, headers={'X-Night-Expected-Viewer': str(ACCOUNT)}, cookies={'mqb_guest': 's' * 43}) as client:
            root = f'/api/night-case/games/{GAME}'
            for raw in ['{"kind":"seen","kind":"forfeit","params":{}}', '[]']:
                denied = await client.post(root + '/quote', content=raw, headers={**headers(), 'Content-Type': 'application/json'})
                assert denied.status_code == 422
            assert (await client.post(root + '/confirm', json={'proposal_id': 'own', 'cost': 0}, headers=headers())).status_code == 422
            assert (await client.post(root + '/quote', content='x' * 16385, headers={**headers(), 'Content-Type': 'application/json'})).status_code == 413
            assert (await client.get(root + '/history?stream=self&limit=51')).status_code == 422
            service.failure = NightCaseError('SECRET_PROOF_POINTER', 404)
            error = await client.get(root + '/messages/guessed')
            assert error.status_code == 404 and 'SECRET_PROOF' not in error.text
            assert error.json()['code'] == 'night_case_unavailable'
    asyncio.run(run())


@pytest.mark.parametrize('identity', ['guest', 'telegram'])
def test_existing_per_account_rate_guard_covers_new_routes(monkeypatch, identity):
    async def run():
        app, service, _ = app_for(monkeypatch)
        monkeypatch.setattr(RequestLimits, 'allow_account', lambda *args: False)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN, headers={'X-Night-Expected-Viewer': str(ACCOUNT)},
                                     cookies={'mqb_mini' if identity == 'telegram' else 'mqb_guest': 's' * 43}) as client:
            assert (await client.get('/api/night-case/bootstrap', params={'identity': identity})).status_code == 429
            assert not service.calls
    asyncio.run(run())


def test_lobby_history_and_confirmation_pass_only_their_declared_inputs(monkeypatch):
    async def run():
        app, service, _ = app_for(monkeypatch)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN, headers={'X-Night-Expected-Viewer': str(ACCOUNT)}, cookies={'mqb_guest': 's' * 43}) as client:
            lobby = {'command_id': str(uuid4()), 'expected_lobby_revision': 0, 'params': {'case_id': 'manor_lake_missing', 'case_version': 1, 'timezone': 'Europe/Berlin'}}
            assert (await client.post('/api/rooms/own-room/night-case/lobby', headers=headers(), json=lobby)).status_code == 200
            assert service.calls[-1] == ('create_lobby', {'account_id': ACCOUNT, 'room_id': 'own-room', 'command': lobby})
            assert (await client.post(f'/api/night-case/games/{GAME}/confirm', headers=headers(), json={'proposal_id': 'own-proposal'})).status_code == 200
            assert service.calls[-1] == ('confirm_intent', {'account_id': ACCOUNT, 'game_id': GAME, 'proposal_id': 'own-proposal'})
            assert (await client.get(f'/api/night-case/games/{GAME}/history?stream=messages&cursor=signed&limit=10')).status_code == 200
            assert service.calls[-1][1]['stream'] == 'messages' and service.calls[-1][1]['limit'] == 10
    asyncio.run(run())


def test_real_api_heartbeat_is_startup_owned_cancelled_and_awaited_across_restarts(monkeypatch):
    from application.night_case_runtime import NightRuntimeHealthMonitor
    from config.night_case import NightCaseSettings

    async def run():
        async def connected():
            return None
        async def heartbeat(self, component, **kwargs):
            assert component == 'api'
            return True
        monkeypatch.setattr(NightRuntimeHealthMonitor, 'heartbeat', heartbeat)
        database = SimpleNamespace(check_connection=connected)
        runtime = NightCaseSettings(enabled=True, cursor_secret=b'http-lifecycle-cursor-secret-32bytes')
        app = create_app(database=database, settings=MiniAppSettings('', ORIGIN, offline=True), night_case_settings=runtime)
        app.state.farm_shared_rate = None  # This test owns only the Night lifecycle.
        monitor = app.state.night_case_health
        assert monitor is not None and app.state.night_case_service_factory is not None
        tasks = []
        for exceptional in [False, True]:
            try:
                async with app.router.lifespan_context(app):
                    tasks.append(monitor._api_task)
                    assert tasks[-1] is not None and not tasks[-1].done()
                    if exceptional:
                        raise RuntimeError('owned test shutdown')
            except RuntimeError as error:
                assert str(error) == 'owned test shutdown'
            assert monitor._api_task is None and tasks[-1].done()
        assert tasks[0] is not tasks[1]
    asyncio.run(run())


def test_static_world_asset_depth_does_not_publish_nested_json(monkeypatch, tmp_path):
    from web import mini_app
    art = tmp_path / 'worlds' / 'manor_lake' / 'assets'
    art.mkdir(parents=True)
    (art / 'manor_char_doctor.webp').write_bytes(b'fixture')
    (art / 'private.case.json').write_text('{"sealed":"NOT_PUBLIC"}', encoding='utf8')
    (art.parent / 'assets.json').write_text('{"schema":"nc-assets/1"}', encoding='utf8')
    monkeypatch.setattr(mini_app, 'NIGHT_DIR', tmp_path)
    allowed = mini_app._night_assets()
    assert 'worlds/manor_lake/assets/manor_char_doctor.webp' in allowed
    assert 'worlds/manor_lake/assets.json' in allowed
    assert 'worlds/manor_lake/assets/private.case.json' not in allowed


def test_content_addressed_pack_only_serves_matching_manifest_and_known_file_bytes(monkeypatch, tmp_path):
    import hashlib
    import json
    from web import mini_app
    payload = b'fixture-webp'
    document = {'schema': 'nc-assets/2', 'world': 'manor_lake', 'assets': {},
                'files': {'assets/portrait.webp': hashlib.sha256(payload).hexdigest()}}
    raw = json.dumps(document, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()
    digest = hashlib.sha256(raw).hexdigest()
    pack = tmp_path / 'packs' / digest
    (pack / 'assets').mkdir(parents=True)
    (pack / 'assets.json').write_bytes(raw)
    (pack / 'assets' / 'portrait.webp').write_bytes(payload)
    (pack / 'secret.json').write_text('PRIVATE')
    (pack / 'assets' / 'unknown.webp').write_bytes(b'UNKNOWN')
    monkeypatch.setattr(mini_app, 'NIGHT_DIR', tmp_path)
    allowed = mini_app._night_assets()
    assert f'packs/{digest}/assets.json' in allowed
    assert f'packs/{digest}/assets/portrait.webp' in allowed
    assert f'packs/{digest}/secret.json' not in allowed
    assert f'packs/{digest}/assets/unknown.webp' not in allowed
    (pack / 'assets' / 'portrait.webp').write_bytes(b'CHANGED')
    assert not any(name.startswith('packs/') for name in mini_app._night_assets())


def test_sealed_pictures_are_served_only_under_their_own_hash(monkeypatch, tmp_path):
    import hashlib
    from web import mini_app
    sealed = tmp_path / 'sealed'
    sealed.mkdir()
    payload = b'finale-webp'
    digest = hashlib.sha256(payload).hexdigest()
    (sealed / f'{digest}.webp').write_bytes(payload)
    (sealed / f'{"0" * 64}.webp').write_bytes(b'WRONG BYTES')
    (sealed / 'scene_final_variant_a.webp').write_bytes(payload)
    (sealed / f'{digest}.json').write_bytes(payload)
    (sealed / '.manor_scene_variant_a.tmp.webp').write_bytes(payload)
    monkeypatch.setattr(mini_app, 'NIGHT_DIR', tmp_path)
    assert {name for name in mini_app._night_assets() if name.startswith('sealed/')} == {f'sealed/{digest}.webp'}


@pytest.mark.parametrize('identity', ['guest', 'telegram'])
def test_new_prefixes_use_existing_room_nat_bucket_but_not_for_anonymous_calls(monkeypatch, identity):
    async def run():
        app, _, _ = app_for(monkeypatch)
        captured = []
        original = RequestLimits.allow
        def allow(self, *args, **kwargs):
            captured.append(kwargs.get('room', False))
            return original(self, *args, **kwargs)
        monkeypatch.setattr(RequestLimits, 'allow', allow)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN, headers={'X-Night-Expected-Viewer': str(ACCOUNT)}) as client:
            assert (await client.get('/api/night-case/bootstrap', params={'identity': identity})).status_code == 401
            assert captured[-1] is False
            client.cookies.set('mqb_mini' if identity == 'telegram' else 'mqb_guest', 's' * 43)
            assert (await client.get('/api/night-case/bootstrap', params={'identity': identity})).status_code == 200
            assert captured[-1] is True
            assert (await client.get('/api/rooms/own-room/night-case/current', params={'identity': identity})).status_code == 200
            assert captured[-1] is True
    asyncio.run(run())


@pytest.mark.parametrize('identity', ['guest', 'telegram'])
def test_terminal_history_selector_is_forwarded_without_changing_verified_principal(monkeypatch, identity):
    async def run():
        app, service, _ = app_for(monkeypatch)
        original = str(uuid4())
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN, headers={'X-Night-Expected-Viewer': str(ACCOUNT)}) as client:
            client.cookies.set('mqb_mini' if identity == 'telegram' else 'mqb_guest', 's' * 43)
            for suffix in ['view', 'history']:
                response = await client.get(f'/api/night-case/games/{GAME}/' + suffix,
                    params={'identity': identity, 'original_account_id': original, **({'stream': 'self'} if suffix == 'history' else {})})
                assert response.status_code == 200
                assert service.calls[-1][1]['original_account_id'] == original
                assert service.calls[-1][1]['account_id'] == ACCOUNT
            service.failure = NightCaseError('unavailable', 404)
            assert (await client.get(f'/api/night-case/games/{GAME}/view',
                params={'identity': identity, 'original_account_id': original})).status_code == 404
    asyncio.run(run())
