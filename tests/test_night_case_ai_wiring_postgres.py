"""The real create_app/admin composition over an owned isolated PG schema: no fake AI services."""
import os
import tempfile
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
from fastapi import FastAPI
from sqlalchemy import select

from application.night_case import NightCaseApplicationService
from config.night_case_ai_runtime import NightAIRuntimeSettings
from storage.night_ai import KeyRing
from storage.night_ai_models import NightAICredential, NightAIRequest
from tests.test_night_case_ai_views import NOW
from web.mini_app import MiniAppSettings, create_app
from web.night_case_ai_wiring import NightAIWiring
from web.postgres_admin import make_night_ai_admin_router
from web.principal import Principal

ORIGIN = 'http://127.0.0.1:4897'


class AIWiringPostgresTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from tests.night_case_test_database import night_case_test_url
        if os.getenv('TEST_DATABASE_URL') != night_case_test_url():
            raise RuntimeError('AI wiring PG requires TEST_DATABASE_URL to match the guarded Night Case URL')
        from tests.test_night_case_ai_views import AIViewsPostgresTests
        self.db = AIViewsPostgresTests('test_lobby_acl_shape_and_no_bootstrap_write')
        await self.db.asyncSetUp()
        self.addAsyncCleanup(self.db._cleanup)
        settings = NightAIRuntimeSettings(enabled=True, external_allowed=True, environment_id='wiring-pg',
            deployment_id='test', manifest_path=Path(tempfile.gettempdir()).resolve() / 'unused.json',
            master_keys=KeyRing('k1', {'k1': b'v' * 32}), receipt_keys=KeyRing('r1', {'r1': b'h' * 32}))
        self.wiring = NightAIWiring(settings=settings, registry=self.db.registry, clock=lambda: NOW)
        sessions = self.db.sessions

        @asynccontextmanager
        async def resolve(request, **kwargs):
            account = UUID(request.headers['x-test-account'])
            async with sessions.begin() as session:
                yield session, Principal(str(account), 'Игрок', 'guest')
        import web.principal
        original, web.principal.resolve_principal = web.principal.resolve_principal, resolve
        self.addCleanup(setattr, web.principal, 'resolve_principal', original)
        game_app = create_app(database=SimpleNamespace(), settings=MiniAppSettings('', ORIGIN, offline=True),
            night_case_enabled=True, night_ai_wiring=self.wiring,
            night_case_service_factory=lambda session: NightCaseApplicationService(session, lambda: NOW, None))
        self.game = httpx.AsyncClient(transport=httpx.ASGITransport(app=game_app), base_url=ORIGIN,
                                      cookies={'mqb_guest': 's' * 43})
        self.addAsyncCleanup(self.game.aclose)

        admin = FastAPI()
        session = SimpleNamespace(csrf='csrf-test')
        admin.state.admin_auth = SimpleNamespace(configured=True, get_session=lambda request: session)

        class Database:
            @asynccontextmanager
            async def transaction(inner):
                async with sessions.begin() as sql:
                    yield sql
        admin.state.admin_database = Database()

        @admin.middleware('http')
        async def admin_state(request, call_next):
            request.state.admin_session = session
            return await call_next(request)
        admin.include_router(make_night_ai_admin_router(wiring=self.wiring))
        self.admin = httpx.AsyncClient(transport=httpx.ASGITransport(app=admin), base_url='http://127.0.0.1',
            headers={'origin': 'http://127.0.0.1', 'x-csrf-token': 'csrf-test'})
        self.addAsyncCleanup(self.admin.aclose)

    def as_player(self, index, *, write=False):
        account = str(self.db.ids[index])
        headers = {'x-test-account': account, 'x-night-expected-viewer': account}
        if write:
            headers.update({'origin': ORIGIN, 'x-guest-csrf': '1'})
        return headers

    async def test_lobby_byok_is_staged_for_host_only_with_own_reference(self):
        path = f'/api/night-case/games/{self.db.game}/ai'
        presets = await self.game.get('/api/night-case/ai/presets', headers=self.as_player(0))
        self.assertEqual((presets.status_code, presets.json()['byok_ready']), (200, True), presets.text)
        self.assertEqual([row['id'] for row in presets.json()['items']], ['openai'])
        staged = await self.game.post(path + '/byok', headers=self.as_player(0, write=True), json={
            'expected_epoch': 0, 'settings': {'preset': 'openai', 'model_id': 'safe-model'},
            'secret': 'WIRING_SECRET_CANARY', 'client_request_id': uuid4().hex})
        self.assertEqual(staged.status_code, 200, staged.text)
        self.assertNotIn('WIRING_SECRET_CANARY', staged.text)
        own = (await self.game.get(path, headers=self.as_player(0))).json()
        self.assertEqual((own['mode'], own['can_configure'], own['staged_credential_id']),
                         ('byok', True, staged.json()['result']['staged_credential_id']))
        other = (await self.game.get(path, headers=self.as_player(1))).json()
        self.assertEqual(other, {'status': 'authored', 'model_label': None})
        async with self.db.sessions() as session:
            row = (await session.scalars(select(NightAICredential))).one()
            self.assertNotIn(b'WIRING_SECRET_CANARY', row.ciphertext)

    async def test_running_request_admin_approve_then_starter_turns_it_off(self):
        await self.db.running()
        path = f'/api/night-case/games/{self.db.game}/ai'
        requested = await self.game.post(path + '/request', headers=self.as_player(0, write=True),
            json={'expected_epoch': 0, 'client_request_id': uuid4().hex})
        self.assertEqual(requested.status_code, 200, requested.text)
        catalog = (await self.admin.get('/api/admin/night-case/ai/catalog')).json()
        self.assertEqual((catalog['enabled'], catalog['vault_ready']), (True, True))
        saved = await self.admin.post('/api/admin/night-case/ai/profiles', json={
            'expected_revision': 0, 'label': 'Ведущий', 'settings': {'preset': 'openai', 'model_id': 'safe-model'},
            'secret': 'ADMIN_WIRING_CANARY', 'client_request_id': uuid4().hex})
        self.assertEqual(saved.status_code, 200, saved.text)
        profile = saved.json()['result']['profile_id']
        listed = (await self.admin.get('/api/admin/night-case/ai/profiles')).json()['items'][0]
        self.assertEqual((listed['credential_configured'], listed['masked_key']), (True, '••••'))
        self.assertNotIn('ADMIN_WIRING_CANARY', str(listed))
        enabled = await self.admin.post(f'/api/admin/night-case/ai/profiles/{profile}/enabled',
            json={'enabled': True, 'client_request_id': uuid4().hex})
        self.assertEqual(enabled.status_code, 200, enabled.text)
        inbox = (await self.admin.get('/api/admin/night-case/ai/requests')).json()['items']
        self.assertEqual((inbox[0]['status'], inbox[0]['requester_display_name']), ('pending', 'Visible 0'))
        approved = await self.admin.post(f"/api/admin/night-case/ai/requests/{inbox[0]['request_id']}/decision", json={
            'decision': 'approve', 'profile_id': profile, 'profile_revision': 1, 'caps': None,
            'client_request_id': uuid4().hex})
        self.assertEqual(approved.status_code, 200, approved.text)
        seen = (await self.game.get(path, headers=self.as_player(1))).json()
        self.assertEqual(seen, {'status': 'ai', 'model_label': 'safe-model'})
        bindings = (await self.admin.get('/api/admin/night-case/ai/bindings')).json()['items']
        self.assertEqual((bindings[0]['mode'], bindings[0]['status']), ('admin', 'active'))
        starter = (await self.game.get(path, headers=self.as_player(0))).json()
        off = await self.game.post(path + '/off', headers=self.as_player(0, write=True),
            json={'expected_epoch': starter['epoch'], 'client_request_id': uuid4().hex})
        self.assertEqual(off.status_code, 200, off.text)
        self.assertEqual((await self.game.get(path, headers=self.as_player(1))).json(),
                         {'status': 'authored', 'model_label': None})
        async with self.db.sessions() as session:
            self.assertEqual((await session.scalars(select(NightAIRequest.status))).all(), ['approved'])

    async def test_admin_revokes_binding(self):
        await self.db.running()
        path = f'/api/night-case/games/{self.db.game}/ai'
        await self.game.post(path + '/request', headers=self.as_player(0, write=True),
            json={'expected_epoch': 0, 'client_request_id': uuid4().hex})
        saved = await self.admin.post('/api/admin/night-case/ai/profiles', json={
            'expected_revision': 0, 'label': 'Ведущий', 'settings': {'preset': 'openai', 'model_id': 'safe-model'},
            'secret': 'ADMIN_WIRING_CANARY', 'client_request_id': uuid4().hex})
        profile = saved.json()['result']['profile_id']
        await self.admin.post(f'/api/admin/night-case/ai/profiles/{profile}/enabled',
            json={'enabled': True, 'client_request_id': uuid4().hex})
        request_id = (await self.admin.get('/api/admin/night-case/ai/requests')).json()['items'][0]['request_id']
        await self.admin.post(f'/api/admin/night-case/ai/requests/{request_id}/decision', json={
            'decision': 'approve', 'profile_id': profile, 'profile_revision': 1, 'caps': None,
            'client_request_id': uuid4().hex})
        binding = (await self.admin.get('/api/admin/night-case/ai/bindings')).json()['items'][0]['binding_id']
        revoked = await self.admin.post(f'/api/admin/night-case/ai/bindings/{binding}/revoke',
            json={'client_request_id': uuid4().hex})
        self.assertEqual(revoked.status_code, 200, revoked.text)
        self.assertEqual((await self.admin.get('/api/admin/night-case/ai/bindings')).json()['items'][0]['status'], 'revoked')
        self.assertNotEqual((await self.game.get(path, headers=self.as_player(1))).json()['status'], 'ai')


if __name__ == '__main__':
    unittest.main()
