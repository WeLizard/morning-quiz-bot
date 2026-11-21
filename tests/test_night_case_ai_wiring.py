"""Night AI narrator access is mounted in both HTTP processes, default-off and env-composed."""
import asyncio
import base64
import json
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI

from web.mini_app import MiniAppSettings, create_app
from web.night_case_ai_wiring import NightAIWiring, load_night_ai_wiring
from web.postgres_admin import make_night_ai_admin_router
from web.principal import Principal, PrincipalError

ORIGIN = 'http://127.0.0.1:4897'
ACCOUNT = UUID('70a7918e-00ad-40da-9ad8-136a4b2bbc0a')
GAME = '1ff30810-84ec-46ce-8820-5fa687cb7603'
KEY = base64.b64encode(b'k' * 32).decode()
HMAC = base64.b64encode(b'h' * 32).decode()


def manifest(path: Path, *, environment='wiring-env'):
    path.write_text(json.dumps({'manifest_version': 1, 'environment_id': environment, 'policies': [
        {'policy_id': 'cloud:openai', 'policy_version': 1, 'base_url': 'https://api.openai.com/v1',
         'network_class': 'cloud', 'allowed_cidrs': [], 'ca_ref': None, 'label': 'OpenAI',
         'presets': ['openai'], 'inventory_route': 'openai_models', 'local_model_allowlist': []},
        {'policy_id': 'local:ollama', 'policy_version': 1, 'base_url': 'http://127.0.0.1:11434/v1',
         'network_class': 'trusted_local', 'allowed_cidrs': ['127.0.0.1/32'], 'ca_ref': None,
         'label': 'Worker Ollama', 'presets': ['ollama'], 'inventory_route': 'ollama_tags',
         'local_model_allowlist': ['owned-local']}], 'ca_bundles': {}}), encoding='utf-8')
    return path


def env_for(path, **extra):
    return {'NIGHT_NARRATOR_ENABLED': 'true', 'NIGHT_NARRATOR_EXTERNAL_ALLOWED': 'true',
            'NIGHT_AI_ENVIRONMENT_ID': 'wiring-env', 'NIGHT_AI_DEPLOYMENT_ID': 'local-dev',
            'NIGHT_AI_MANIFEST_PATH': str(path.resolve()),
            'NIGHT_AI_MASTER_KEYS': json.dumps({'k1': KEY}), 'NIGHT_AI_MASTER_ACTIVE_KEY_ID': 'k1',
            'NIGHT_AI_RECEIPT_HMAC_KEY': json.dumps({'r1': HMAC}), 'NIGHT_AI_RECEIPT_HMAC_ACTIVE_KEY_ID': 'r1',
            'NIGHT_AI_MANUAL_PRESETS': 'openai,ollama', **extra}


def test_wiring_is_default_off_and_fails_closed(tmp_path):
    assert load_night_ai_wiring({}) is None
    assert load_night_ai_wiring({'NIGHT_NARRATOR_ENABLED': 'false'}) is None
    # Enabled without manifest/environment, a wrong environment, a bad preset: authored, not a crash.
    assert load_night_ai_wiring({'NIGHT_NARRATOR_ENABLED': 'true'}) is None
    path = manifest(tmp_path / 'm.json', environment='other-env')
    assert load_night_ai_wiring(env_for(path)) is None
    path = manifest(tmp_path / 'm.json')
    assert load_night_ai_wiring(env_for(path, NIGHT_AI_MANUAL_PRESETS='unknown')) is None
    assert load_night_ai_wiring(env_for(tmp_path / 'missing.json')) is None


def test_wiring_builds_registry_vault_and_safe_catalog(tmp_path):
    wiring = load_night_ai_wiring(env_for(manifest(tmp_path / 'm.json')))
    assert isinstance(wiring, NightAIWiring) and wiring.vault_ready and wiring.deployment_id == 'local-dev'
    catalog = wiring.admin_catalog()
    text = json.dumps(catalog)
    for leak in ('api.openai.com', '127.0.0.1', '11434', KEY, HMAC):
        assert leak not in text
    assert [row['id'] for row in catalog['presets']] == ['ollama', 'openai']
    assert next(row for row in catalog['presets'] if row['id'] == 'ollama')['local'] is True
    assert catalog['external_allowed'] is True and catalog['vault_ready'] is True
    assert 'k1' not in repr(wiring) and KEY not in repr(wiring)
    no_keys = {k: v for k, v in env_for(manifest(tmp_path / 'm.json')).items() if 'MASTER' not in k}
    assert load_night_ai_wiring(no_keys).vault_ready is False


class FakeAI:
    def __init__(self):
        self.calls = []

    def __getattr__(self, method):
        async def call(*args, **kwargs):
            self.calls.append((method, args, kwargs))
            if method == 'list_presets':
                return {'items': [{'id': 'openai'}], 'byok_ready': True, 'reason': None}
            if method == 'get_ai_status':
                return {'status': 'pending', 'model_label': None}
            return {'result': {'epoch': kwargs.get('expected_epoch'), 'request_status': 'pending'}}
        return call


class FakeWiring:
    def __init__(self):
        self.ai = FakeAI()

    def __bool__(self): return True
    def control(self, session, **kwargs): return self.ai
    def views(self, session, app): return self.ai


def mini_app(monkeypatch, wiring):
    @asynccontextmanager
    async def resolve(request, **kwargs):
        if request.cookies.get('mqb_guest') != 's' * 43:
            raise PrincipalError('authentication', 'Требуется вход.')
        yield object(), Principal(str(ACCOUNT), 'Участник', 'guest')

    class Service:
        async def list_cases(self, **kwargs): return {'enabled': True, 'cases': []}
        async def prove_original_starter(self, locked): return ACCOUNT

    monkeypatch.setattr('web.principal.resolve_principal', resolve)
    return create_app(database=SimpleNamespace(), settings=MiniAppSettings('', ORIGIN, offline=True),
                      night_case_enabled=True, night_case_service_factory=lambda session: Service(),
                      night_ai_wiring=wiring)


def client_for(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN,
                             cookies={'mqb_guest': 's' * 43},
                             headers={'X-Night-Expected-Viewer': str(ACCOUNT)})


def test_mini_app_keeps_ai_routes_closed_when_off(monkeypatch):
    async def run():
        async with client_for(mini_app(monkeypatch, False)) as client:
            boot = await client.get('/api/night-case/bootstrap')
            assert boot.json()['capabilities'] == {'legacy_mafia': True, 'free_intent': False, 'ai_narrator': False}
            assert (await client.get('/api/night-case/ai/presets')).status_code == 404
            assert (await client.get(f'/api/night-case/games/{GAME}/ai')).status_code == 404
    asyncio.run(run())


def test_mini_app_mounts_ai_routes_behind_room_principal_and_csrf(monkeypatch):
    async def run():
        wiring = FakeWiring()
        app = mini_app(monkeypatch, wiring)
        async with client_for(app) as client:
            boot = await client.get('/api/night-case/bootstrap')
            # A bare orchestrator carries start options only; free text stays off.
            assert boot.json()['capabilities'] == {'legacy_mafia': True, 'free_intent': False, 'ai_narrator': True}
            presets = await client.get('/api/night-case/ai/presets')
            assert presets.status_code == 200 and presets.json()['items'] == [{'id': 'openai'}]
            status = await client.get(f'/api/night-case/games/{GAME}/ai')
            assert status.json() == {'status': 'pending', 'model_label': None}
            body = {'expected_epoch': 0, 'client_request_id': uuid4().hex}
            forged = await client.post(f'/api/night-case/games/{GAME}/ai/request', json=body)
            assert forged.status_code == 403
            sent = await client.post(f'/api/night-case/games/{GAME}/ai/request', json=body,
                                     headers={'Origin': ORIGIN, 'X-Guest-CSRF': '1'})
            assert sent.status_code == 200, sent.text
            assert wiring.ai.calls[-1][0] == 'request_admin'
            assert wiring.ai.calls[-1][2]['account_id'] == ACCOUNT
        anonymous = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN)
        async with anonymous:
            assert (await anonymous.get('/api/night-case/ai/presets')).status_code == 401
    asyncio.run(run())


def admin_app(router):
    session = SimpleNamespace(csrf='csrf-test')
    auth = SimpleNamespace(configured=True, get_session=lambda request: session)
    app = FastAPI()
    app.state.admin_auth = auth

    @app.middleware('http')
    async def admin_state(request, call_next):
        request.state.admin_session = session
        return await call_next(request)
    app.include_router(router)
    return app


def test_admin_section_says_off_and_hides_routes_without_narrator():
    async def run():
        app = admin_app(make_night_ai_admin_router(env={}))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://127.0.0.1') as client:
            catalog = await client.get('/api/admin/night-case/ai/catalog')
            assert catalog.status_code == 200 and catalog.json() == {'enabled': False}
            for path in ('profiles', 'requests', 'bindings'):
                assert (await client.get('/api/admin/night-case/ai/' + path)).status_code == 404
    asyncio.run(run())


def test_admin_catalog_comes_from_operator_manifest(tmp_path):
    async def run():
        wiring = load_night_ai_wiring(env_for(manifest(tmp_path / 'm.json')))
        app = admin_app(make_night_ai_admin_router(wiring=wiring))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://127.0.0.1') as client:
            catalog = (await client.get('/api/admin/night-case/ai/catalog')).json()
            assert catalog['enabled'] is True
            assert [row['policy_id'] for row in catalog['policies']] == ['cloud:openai', 'local:ollama']
            assert 'api.openai.com' not in json.dumps(catalog)
    asyncio.run(run())


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-q']))
