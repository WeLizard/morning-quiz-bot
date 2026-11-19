"""Raw loopback readiness must work with public HTTPS settings and stay narrow."""
import asyncio
import hashlib
import hmac
import socket
import unittest
from types import SimpleNamespace

import httpx
import uvicorn

from application.night_case_runtime import NightCaseDeadlineWorker
from config.night_case import NightCaseSettings
from infrastructure.night_case_readiness import readiness_probe
from web.mini_app import MiniAppSettings, create_app


SECRET = b'fixed-readiness-boundary-test-secret-32-bytes'
TOKEN = hmac.new(SECRET, b'night-case-readiness/1', hashlib.sha256).hexdigest()


class ReadinessBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(('127.0.0.1', 0))
        sock.listen(128)
        self.port = sock.getsockname()[1]
        self.url = f'http://127.0.0.1:{self.port}/healthz'
        self.night = NightCaseSettings(enabled=True, cursor_secret=SECRET,
                                       readiness_url=self.url)

        async def check_connection():
            return None

        self.database = SimpleNamespace(check_connection=check_connection)
        self.app = create_app(database=self.database,
            settings=MiniAppSettings('', 'https://quiz.example.test', offline=False),
            night_case_settings=self.night, night_case_service_factory=lambda session: None)
        server = uvicorn.Server(uvicorn.Config(self.app, host='127.0.0.1', port=self.port,
            access_log=False, lifespan='off', log_level='error'))
        self.server = server
        self.task = asyncio.create_task(server.serve(sockets=[sock]))
        for _ in range(100):
            if server.started:
                break
            await asyncio.sleep(.01)
        self.assertTrue(server.started)
        self.client = httpx.AsyncClient(trust_env=False, timeout=3)

    async def asyncTearDown(self):
        await self.client.aclose()
        self.server.should_exit = True
        await asyncio.wait_for(self.task, 5)

    async def test_default_worker_probe_reaches_real_api_under_public_https_settings(self):
        self.assertEqual((await self.client.get(self.url)).status_code, 400)
        worker = NightCaseDeadlineWorker(None, self.night, service_factory=lambda session: None)
        self.assertTrue(await worker.probe(self.url))

    async def test_token_and_boundary_are_exact_and_rate_bypass_is_narrow(self):
        token = TOKEN
        good = {'X-Night-Readiness': token}
        self.assertEqual((await self.client.get(self.url, headers=good)).status_code, 200)
        for headers in ({'X-Night-Readiness': '0' * 64}, {'X-Night-Readiness': 'G' * 64},
                        {'X-Night-Readiness': token.upper()}, {}):
            self.assertEqual((await self.client.get(self.url, headers=headers)).status_code, 400)
        duplicate = [('X-Night-Readiness', token), ('X-Night-Readiness', token)]
        self.assertEqual((await self.client.get(self.url, headers=duplicate)).status_code, 400)
        for header in ('Forwarded', 'X-Forwarded-For', 'X-Forwarded-Proto',
                       'X-Forwarded-Host', 'X-Real-IP'):
            self.assertEqual((await self.client.get(self.url, headers={**good, header: '127.0.0.1'})).status_code, 400)
        for path in ('/healthz/', '/healthz?x=1', '/healthz%2F'):
            self.assertEqual((await self.client.get(f'http://127.0.0.1:{self.port}{path}', headers=good)).status_code, 400)
        self.assertEqual((await self.client.post(self.url, headers=good)).status_code, 400)
        self.assertEqual((await self.client.get(self.url, headers={**good, 'Host': 'localhost'})).status_code, 400)
        self.assertEqual((await self.client.get(self.url, headers={**good, 'Host': '127.0.0.1:9999'})).status_code, 400)
        self.assertEqual((await self.client.get(self.url, headers={**good, 'Origin': 'https://evil.example'})).status_code, 403)
        self.assertEqual((await self.client.get(self.url, headers={**good, 'Sec-Fetch-Site': 'cross-site'})).status_code, 403)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app, client=('198.51.100.5', 1234)),
                                     base_url=f'http://127.0.0.1:{self.port}') as remote:
            self.assertEqual((await remote.get('/healthz', headers=good)).status_code, 400)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app, client=('127.0.0.1', 1234)),
                                     base_url=f'https://127.0.0.1:{self.port}') as wrong_scheme:
            self.assertEqual((await wrong_scheme.get('/healthz', headers=good)).status_code, 400)
        for enabled, configured in ((False, True), (True, False)):
            night = NightCaseSettings(enabled=configured, cursor_secret=SECRET, readiness_url=self.url)
            disabled = create_app(database=self.database,
                settings=MiniAppSettings('', 'https://quiz.example.test', offline=False),
                night_case_enabled=enabled, night_case_settings=night,
                night_case_service_factory=lambda session: None)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=disabled, client=('127.0.0.1', 1234)),
                                         base_url=f'http://127.0.0.1:{self.port}') as client:
                self.assertEqual((await client.get('/healthz', headers=good)).status_code, 400)
        for bad in ('G' * 64, token.upper(), 'a' * 63, 'a' * 65):
            with self.assertRaises(ValueError):
                await readiness_probe(self.url, token=bad)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app, client=('127.0.0.1', 1234)),
                                     base_url='https://quiz.example.test') as public:
            statuses = [(await public.get('/api/mini/config')).status_code for _ in range(121)]
            self.assertEqual(statuses[0], 200)
            self.assertEqual(statuses[-1], 429)
            self.assertEqual((await self.client.get(self.url, headers=good)).status_code, 200)
            self.assertEqual((await public.get('/api/mini/config')).status_code, 429)
