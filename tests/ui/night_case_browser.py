"""Owned PG + real HTTP/browser acceptance. Never points at dev, production or CI DBs.

Set NIGHT_BROWSER_DATABASE_URL explicitly; --setup only creates/migrates this fixture DB.
No clock-control HTTP endpoint exists. Exercise owns the ASGI/worker tasks it starts.
"""
from __future__ import annotations
import argparse
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
import time
from urllib.parse import urlsplit
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
DB_NAME = 'morning_quiz_night_browser'
CASE_PATH = ROOT / 'content/night_city/manor_lake.case.json'
ART_HASH = '701d7ecb7ab415b04dc05b095391a8f644ccfc6560d2c17c49956db5d9c1facd'


class FixtureClock:
    """Accelerated UTC anchors with real monotonic elapsed time between jumps.

    A transient failed readiness probe must have a positive outage duration on
    recovery, just as it does with production UTC. No game transition is applied here.
    """
    def __init__(self, at, monotonic=time.monotonic):
        self.monotonic = monotonic
        self.anchor, self.anchor_tick = at, monotonic()

    @property
    def now(self):
        return self.anchor + timedelta(seconds=max(0, self.monotonic() - self.anchor_tick))

    def advance_to(self, at):
        self.anchor, self.anchor_tick = max(at, self.now), self.monotonic()


async def wait_for_window(read_view, before_seq, *, timeout_seconds=15, poll_seconds=.1):
    """Observe one real transition regardless of which worker claimed the deadline."""
    end = time.monotonic() + timeout_seconds
    last = None
    while True:
        remaining = end - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('Window transition not observed: ' + json.dumps({'before_seq': before_seq, 'last_clock': last}))
        view = await asyncio.wait_for(read_view(), remaining)
        if view is not None:
            last = view['public']['clock']
            seq = last['window_seq']
            if seq > before_seq + 1:
                raise AssertionError('More than one window advanced')
            if seq == before_seq + 1 or view['public'].get('final') is not None:
                return view
        await asyncio.sleep(min(poll_seconds, max(0, end - time.monotonic())))


async def post_with_runtime_retry(send, serialized_payload, *, timeout_seconds=15, poll_seconds=.25, observations=None):
    """Only runtime_delayed/503 retries; bytes, UUID and all fences stay identical."""
    end = time.monotonic() + timeout_seconds
    while True:
        remaining = end - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('runtime_delayed command retry budget exhausted')
        response = await asyncio.wait_for(send(serialized_payload), remaining)
        code = None
        if response.status == 503:
            try:
                value = await asyncio.wait_for(response.json(), max(.000001, end - time.monotonic()))
                code = value.get('code') if isinstance(value, dict) else None
            except ValueError:
                pass
        if observations is not None:
            observations.append({'status': response.status, 'code': code})
        if response.status != 503 or code != 'runtime_delayed':
            return response
        await asyncio.sleep(min(poll_seconds, max(0, end - time.monotonic())))


def guarded_url():
    raw = os.environ.get('NIGHT_BROWSER_DATABASE_URL', '')
    parsed = urlsplit(raw)
    if (parsed.scheme != 'postgresql+asyncpg' or parsed.hostname not in {'127.0.0.1', 'localhost'}
            or parsed.port != 55434 or parsed.path != '/' + DB_NAME
            or parsed.username != 'mqb_dev' or parsed.password != 'local-development-only'
            or parsed.query or parsed.fragment):
        raise RuntimeError('Browser fixture requires exact owned loopback PG55434/morning_quiz_night_browser URL')
    return raw


async def setup():
    import asyncpg
    raw = guarded_url()
    parsed = urlsplit(raw)
    connection = await asyncpg.connect(host=parsed.hostname, port=parsed.port, user=parsed.username,
                                      password=parsed.password, database='postgres')
    try:
        exists = await connection.fetchval('SELECT 1 FROM pg_database WHERE datname=$1', DB_NAME)
        if not exists:
            await connection.execute('CREATE DATABASE morning_quiz_night_browser')
    finally:
        await connection.close()
    env = {**os.environ, 'DATABASE_URL': raw, 'TEMP': r'F:\Temp', 'TMP': r'F:\Temp'}
    process = await asyncio.create_subprocess_exec(sys.executable, '-B', '-m', 'alembic', 'upgrade', 'head', cwd=ROOT, env=env)
    if await process.wait():
        raise RuntimeError('Browser database migration failed')
    from application.night_case import OperatorPrincipal
    from application.night_case_runtime import NightCaseServiceFactory
    from config.night_case import NightCaseSettings
    from storage.database import Database, DatabaseSettings
    runtime = NightCaseSettings(enabled=True, starts_enabled=True, cursor_secret=b'owned-browser-fixture-cursor-secret-01a1dfba')
    factory = NightCaseServiceFactory(runtime)
    document = json.loads(CASE_PATH.read_text(encoding='utf8'))
    # Reports of the pinned case hash; a re-pinned case brings its own pair (NIGHT_BROWSER_REPORT_TAG).
    tag = os.environ.get('NIGHT_BROWSER_REPORT_TAG', '20261116')
    reports = [json.loads(Path(r'F:\Temp', 'mqb-manor-pinned-' + scope + '-' + tag + '.json').read_text(encoding='utf8')) for scope in ['witness', 'smoke']]
    if not all(r['case_hash'] in runtime.allowed_hashes and r['scope_passed'] for r in reports):
        raise RuntimeError('Pinned validation reports are missing or do not match the registered case')
    database = Database(DatabaseSettings(url=raw))
    try:
        async with database.transaction() as session:
            from storage.models import NightCase
            from domain.night_case_v2_format import compile_v2, load_v2
            compiled = compile_v2(load_v2(CASE_PATH.read_bytes()))
            from application.night_art import binding_for_case
            art = binding_for_case(document['meta'], compiled.content_hash)  # what registration itself finds
            if art is None or art['manifest_sha256'] != ART_HASH:
                raise RuntimeError(f'built pack for the case is {art and art["manifest_sha256"]}, expected {ART_HASH}')
            report = {'scope': 'owned-browser-fixture', 'art': art, 'pure_reports': reports,
                      'browser': 'not_checked', 'production': 'not_authorized'}
            existing = await session.get(NightCase, (compiled.case_id, compiled.case_version))
            if existing:
                if existing.content_hash != compiled.content_hash or existing.content != document or existing.validation_report.get('art') != art:
                    raise RuntimeError('Existing immutable browser registration differs from exact source/art pin')
                report = existing.validation_report
            ref = await factory(session).register_case(operator=OperatorPrincipal('owned-browser-fixture', None),
                content=document, admission='rehearsal', validation_report=report)
            print('REGISTERED', ref.case_id, ref.content_hash, flush=True)
    finally:
        await database.dispose()


class Harness:
    @property
    def now(self):
        return self._fixture_clock.now

    @now.setter
    def now(self, at):
        if hasattr(self, '_fixture_clock'):
            self._fixture_clock.advance_to(at)
        else:
            self._fixture_clock = FixtureClock(at)

    def __init__(self, port, *, farm_only=False):
        from application.night_case_runtime import NightCaseDeadlineWorker
        from config.night_case import NightCaseSettings
        from storage.database import Database, DatabaseSettings
        from web.mini_app import MiniAppSettings, create_app
        self.database = Database(DatabaseSettings(url=guarded_url()))
        self.now = datetime(2026, 11, 16, 10, tzinfo=timezone.utc)
        self.origin = f'http://127.0.0.1:{port}'
        self.settings = NightCaseSettings(enabled=not farm_only, starts_enabled=not farm_only,
            cursor_secret=b'owned-browser-fixture-cursor-secret-01a1dfba', readiness_url=self.origin + '/healthz')
        import time
        self.app = create_app(database=self.database, clock=time.time if farm_only else lambda: self.now.timestamp(),
            settings=MiniAppSettings('', self.origin, offline=True),
            night_case_settings=self.settings)
        self.factory = self.app.state.night_case_service_factory
        self.worker = None if farm_only else NightCaseDeadlineWorker(self.database, self.settings, service_factory=self.factory, clock=lambda: self.now)
        self.worker_runs, self.probe_observations = [], []
        if self.worker:
            original_probe = self.worker.probe
            async def observed_probe(url):
                began = time.monotonic()
                ready = await original_probe(url)
                observation = {'at': self.now.isoformat(), 'ready': ready, 'elapsed_s': round(time.monotonic() - began, 4)}
                if not ready:
                    import httpx
                    try:
                        async with httpx.AsyncClient(timeout=3) as client:
                            response = await client.get(url)
                            observation['diagnostic_http_status'] = response.status_code
                    except Exception as error:
                        observation['diagnostic_error_type'] = type(error).__name__
                self.probe_observations.append(observation)
                self.probe_observations[:] = self.probe_observations[-40:]
                return ready
            self.worker.probe = observed_probe
        self.server = self.server_task = None
        self.clock_initialized = False
        original = self.app.router.lifespan_context

        @asynccontextmanager
        async def lifetime(app):
            async with original(app):
                if self.worker is None:
                    yield
                    return
                async def loop():
                    while True:
                        await self.run_worker()
                        await asyncio.sleep(self.settings.poll_seconds)
                task = asyncio.create_task(loop(), name='owned-night-browser-worker')
                try:
                    yield
                finally:
                    task.cancel()
                    try:
                        await asyncio.wait_for(task, 5)
                    except asyncio.CancelledError:
                        pass
        self.app.router.lifespan_context = lifetime

    async def start(self):
        import uvicorn
        from storage.startup import require_current_schema
        await require_current_schema(self.database)
        if not self.clock_initialized:
            from storage.models import NightRuntimeHealth
            async with self.database.transaction() as session:
                health = await session.get(NightRuntimeHealth, self.settings.runtime_key)
                seen = [stamp for stamp in (health.api_seen_at, health.worker_seen_at) if stamp is not None] if health else []
            if seen and max(seen) >= self.now:
                latest = max(seen)
                self.now = latest.replace(hour=10, minute=0, second=0, microsecond=0)
                if self.now <= latest:
                    self.now += timedelta(days=1)
            self.clock_initialized = True
        config = uvicorn.Config(self.app, host='127.0.0.1', port=urlsplit(self.origin).port,
                                log_level='warning', access_log=False, lifespan='on')
        self.server = uvicorn.Server(config)
        self.server_task = asyncio.create_task(self.server.serve(), name='owned-night-browser-http')
        for _ in range(200):
            if self.server.started:
                self.now += timedelta(seconds=1)
                if self.worker:
                    await self.run_worker()
                return
            if self.server_task.done():
                await self.server_task
                raise RuntimeError('Own HTTP server failed to start')
            await asyncio.sleep(.05)
        raise RuntimeError('Own HTTP startup timed out')

    async def stop(self):
        if self.server_task:
            self.server.should_exit = True
            await asyncio.wait_for(self.server_task, 10)
            self.server = self.server_task = None

    async def jump(self, now):
        """Trusted fixture-only virtual clock. No kernel/deadline/game writes occur here.

        Processes remain healthy while virtual time moves: seed their heartbeat observation
        consistently, as W's PG clock fixtures do, then let the real worker claim/apply due.
        """
        from sqlalchemy import update
        from storage.models import NightRuntimeHealth
        self.now = now
        now = self.now
        async with self.database.transaction() as session:
            await session.execute(update(NightRuntimeHealth).where(NightRuntimeHealth.runtime_key == self.settings.runtime_key)
                                  .values(api_seen_at=now, worker_seen_at=now))
        return await self.run_worker(now=now)

    async def run_worker(self, *, now=None):
        captured = now or self.now
        observation = {'captured_at': captured.isoformat()}
        try:
            result = await self.worker.run_once(now=captured)
            observation['settled'] = result
            return result
        except Exception as error:
            observation['error_type'] = type(error).__name__
            raise
        finally:
            observation['completed_at'] = self.now.isoformat()
            self.worker_runs.append(observation)
            self.worker_runs[:] = self.worker_runs[-40:]

    async def safe_metadata(self, game_id):
        """Read clock/claim/health metadata only; never select private kernel content."""
        from sqlalchemy import select
        from storage.models import Game, GameDeadline, NightGameSealed, NightRuntimeHealth, NightRuntimeOutage
        async with self.database.transaction() as session:
            row = (await session.execute(select(Game.status, Game.phase, NightGameSealed.lifecycle, NightGameSealed.kernel['clock'])
                .join(NightGameSealed, NightGameSealed.game_id == Game.id).where(Game.id == game_id))).one()
            clock = {key: row[3].get(key) for key in ['phase', 'window_idx', 'window_seq', 'timer_seq', 'opened_at', 'closes_at']}
            deadline = await session.get(GameDeadline, 'night:' + game_id + ':phase')
            health = await session.get(NightRuntimeHealth, self.settings.runtime_key)
            outage = await session.get(NightRuntimeOutage, health.active_outage_id) if health and health.active_outage_id else None
            def fields(value, names):
                return None if value is None else {key: (item.isoformat() if isinstance(item, datetime) else item) for key in names for item in [getattr(value, key)]}
            return {'fixture_now': self.now.isoformat(), 'status': row[0], 'phase': row[1], 'lifecycle': row[2], 'clock': clock,
                'deadline': fields(deadline, ['status', 'revision', 'due_at', 'claimed_by', 'claimed_at', 'retry_at', 'attempts', 'last_error_code', 'quarantined_at']),
                'health': fields(health, ['api_seen_at', 'worker_seen_at', 'active_outage_id']),
                'outage': fields(outage, ['started_at', 'ended_at', 'detected_by']),
                'worker_runs': list(self.worker_runs), 'probes': list(self.probe_observations)}

    async def advance(self, game):
        from storage.models import GameDeadline
        async with self.database.transaction() as session:
            row = await session.get(GameDeadline, 'night:' + game + ':phase')
            if row is None:
                raise RuntimeError('No current deadline')
            due = row.due_at
        return await self.jump(due)


async def capture_farm(context, harness, output, report):
    farm = await context.new_page()
    farm_writes, farm_errors, farm_network_failures = [], [], []
    report['farm_network_failures'] = farm_network_failures
    farm.on('response', lambda response: farm_network_failures.append({'path': urlsplit(response.url).path, 'status': response.status}) if response.status >=400 else None)
    farm.on('request', lambda request: farm_writes.append(request.url) if request.method == 'POST' and '/api/farm/v1/commands' in request.url else None)
    farm.on('pageerror', lambda error: farm_errors.append(str(error)))
    await farm.bring_to_front()
    await farm.goto(harness.origin + '/app/farm?identity=guest')
    try:
        await farm.locator('#harvest-all').wait_for(state='visible', timeout=30000)
    except Exception:
        await farm.screenshot(path=str(output / 'farm-open-failure.png'), full_page=True)
        (output / 'farm-open-failure.txt').write_text(await farm.locator('body').inner_text(), encoding='utf8')
        raise
    for width, height in [(360, 780), (384, 832)]:
        await farm.set_viewport_size({'width': width, 'height': height})
        for lighting in ['day', 'night']:
            for _ in range(3):
                if await farm.locator('#lighting-toggle').get_attribute('data-mode') == lighting:
                    break
                await farm.locator('#lighting-toggle').click()
            assert await farm.locator('#lighting-toggle').get_attribute('data-mode') == lighting
            for selector in ['#harvest-all', '#farm-menu-button', '#catalog-button']:
                await farm.locator(selector).wait_for(state='visible', timeout=30000)
            await farm.evaluate('document.documentElement.style.setProperty("--qw-safe-top", "48px")')
            await farm.wait_for_function('(lighting) => document.documentElement.dataset.farmTheme === lighting', arg=lighting)
            await farm.evaluate('document.fonts.ready')
            await farm.wait_for_function('''() => { const canvas = document.getElementById("farm-canvas"); if (!canvas?.width || !canvas.height) return false; const ctx = canvas.getContext("2d"), colors = new Set(); for (let x=0; x<canvas.width; x+=Math.max(1,Math.floor(canvas.width/15))) for (let y=0; y<canvas.height; y+=Math.max(1,Math.floor(canvas.height/15))) { const p=ctx.getImageData(x,y,1,1).data; if(p[3]) colors.add([...p].join()); } return colors.size>8; }''', timeout=20000)
            # Lighting has a real animated transition after the chrome changes.
            # Observe the rendered sky rather than assuming a delay painted it.
            await farm.wait_for_function('''(lighting) => { const canvas=document.getElementById('farm-canvas'), pixel=canvas.getContext('2d').getImageData(Math.floor(canvas.width/2),1,1,1).data; const brightness=(pixel[0]+pixel[1]+pixel[2])/3; return pixel[3]>0 && (lighting==='day' ? brightness>180 : brightness<80); }''', arg=lighting, timeout=20000)
            report.setdefault('farm_canvas_probes', []).append({'width': width, 'lighting': lighting,
                'sky_rgba': await farm.evaluate('''() => {const c=document.getElementById('farm-canvas');return [...c.getContext('2d').getImageData(Math.floor(c.width/2),1,1,1).data]}''')})
            stem = f'farm-{lighting}-{width}x{height}'
            for state in ['home', 'menu', 'catalog-all']:
                if state == 'menu':
                    await farm.locator('#farm-menu-button').click()
                    await farm.locator('#rail').wait_for(state='visible')
                elif state == 'catalog-all':
                    await farm.keyboard.press('Escape')
                    await farm.locator('#catalog-button').click()
                    await farm.locator('#panel').wait_for(state='visible')
                filename = f'{stem}-{state}.png'
                await farm.screenshot(path=str(output / filename), full_page=False, animations='disabled')
                report['screenshots'].append(filename)
            await farm.keyboard.press('Escape')
    report['farm_network_failures'] = farm_network_failures
    await farm.wait_for_function('''() => !document.getElementById("retry")?.checkVisibility() && !/Не удалось|Нет связи|Связь прервалась/.test(document.getElementById("connection")?.textContent || '')''', timeout=15000)
    assert not farm_writes, farm_writes
    assert not farm_errors, farm_errors
    report['steps'].append('farm_predeploy_360_384_top48_day_night_home_menu_catalog_no_commands')


async def exercise(port, output, *, with_farm=False, identity_only=False, identity_focused=False):
    from playwright.async_api import async_playwright
    from tests.ui.ui_check import SCANNER, ZONE_SCANNER
    output.mkdir(parents=True, exist_ok=True)
    harness = Harness(port)
    contexts = []
    browser = None
    report = {'scope': 'night_case_browser', 'production': 'not_authorized', 'steps': [], 'screenshots': [], 'gaps': [],
              'browser_http_errors': [], 'failed_browser_requests': [], 'public_resource_statuses': [], 'audio_requests': []}
    try:
        await harness.start()
        async with async_playwright() as playwright:
            for args in [{}, {'channel': 'msedge'}, {'channel': 'chrome'}]:
                try:
                    browser = await playwright.chromium.launch(**args)
                    break
                except Exception:
                    continue
            if browser is None:
                raise RuntimeError('No Chromium-family browser available')
            for _ in range(4):
                context = await browser.new_context(viewport={'width': 390, 'height': 844})
                contexts.append(context)
                def observed_response(response):
                    path = urlsplit(response.url).path
                    entry = {'path': path, 'status': response.status, 'resource_type': response.request.resource_type}
                    if response.status >= 400:
                        report['browser_http_errors'].append(entry)
                    if path.startswith('/app/'):
                        report['public_resource_statuses'].append(entry)
                def observed_request(request):
                    path = urlsplit(request.url).path
                    if request.resource_type == 'media' or Path(path).suffix.lower() in {'.m4a', '.mp3', '.wav', '.ogg', '.aac', '.flac'}:
                        report['audio_requests'].append({'path': path, 'resource_type': request.resource_type})
                context.on('response', observed_response)
                context.on('request', observed_request)
                context.on('requestfailed', lambda request: report['failed_browser_requests'].append({
                    'path': urlsplit(request.url).path, 'resource_type': request.resource_type, 'failure': request.failure}))
                response = await context.request.post(harness.origin + '/api/guest/start', headers={'Origin': harness.origin, 'X-Guest-CSRF': '1'})
                assert response.ok, await response.text()
            pages = [await context.new_page() for context in contexts]
            account_ids = []
            viewer_pins = [None] * 4
            async def req(index, suffix, payload=None):
                request = contexts[index].request
                url = harness.origin + suffix + ('&' if '?' in suffix else '?') + 'identity=guest'
                pin = {} if viewer_pins[index] is None else {'X-Night-Expected-Viewer': viewer_pins[index]}
                if payload is None:
                    response = await request.get(url, headers=pin)
                else:
                    serialized = json.dumps(payload).encode('utf8')
                    frozen_headers = {'Origin': harness.origin, 'X-Guest-CSRF': '1', 'Content-Type': 'application/json', **pin}
                    async def post(data): return await request.post(url, data=data, headers=frozen_headers)
                    if suffix.startswith('/api/night-case/games/') and suffix.endswith('/commands'):
                        attempts = []
                        try:
                            response = await post_with_runtime_retry(post, serialized, observations=attempts)
                        finally:
                            if len(attempts) > 1 or attempts and attempts[-1]['status'] == 503:
                                report.setdefault('runtime_command_retries', []).append({'command_id': payload['command_id'], 'attempts': attempts})
                    else:
                        response = await post(serialized)
                assert response.ok, (suffix, response.status, await response.text())
                return await response.json()
            for i in range(4):
                account_ids.append((await req(i, '/api/guest/me'))['account_id'])
                bootstrap = await req(i, '/api/night-case/bootstrap')
                assert bootstrap['viewer_account_id'] == account_ids[i]
                viewer_pins[i] = bootstrap['viewer_account_id']
            room = await req(0, '/api/guest/rooms', {'request_id': str(uuid4()), 'title': 'Браузерная усадьба ' + uuid4().hex[:6]})
            invite = await req(0, '/api/guest/rooms/' + room['id'] + '/invites', {'expires_in_seconds': 3600, 'max_uses': 3})
            for i in range(1, 4):
                await req(i, '/api/guest/rooms/join', {'short_code': invite['short_code']})
            source_meta = json.loads(CASE_PATH.read_text(encoding='utf8'))['meta']
            created = await req(0, '/api/rooms/' + room['id'] + '/night-case/lobby', {'command_id': str(uuid4()), 'expected_lobby_revision': 0,
                'params': {'case_id': source_meta['id'], 'case_version': source_meta['version'], 'timezone': 'Europe/Berlin'}})
            game = created['view']['game_id']
            base = f'/api/night-case/games/{game}/'
            async def reopen(page):
                dossier = page.get_by_role('button', name='Досье', exact=True)
                room_button = page.get_by_role('button', name=room['title'], exact=True)
                launch = page.get_by_role('button', name='Открыть дело', exact=True)
                try:
                    await dossier.or_(room_button).or_(launch).first.wait_for(timeout=15000)
                    if await dossier.is_visible():
                        return
                    if await launch.is_visible():
                        await launch.click()
                    await dossier.or_(room_button).first.wait_for(timeout=15000)
                    if not await dossier.is_visible():
                        await room_button.click()
                    await dossier.wait_for(timeout=15000)
                except Exception:
                    await page.screenshot(path=str(output / 'reconnect-failure.png'), full_page=True)
                    (output / 'reconnect-failure.txt').write_text(await page.locator('body').inner_text(), encoding='utf8')
                    raise
            for i in range(1, 4):
                current = await req(i, base + 'view')
                await req(i, base + 'join', {'command_id': str(uuid4()), 'expected_lobby_revision': current['lobby']['lobby_revision'], 'params': {}})
            # Actual mounted UI handles own name/ready/start; APIs only prepare ordinary rooms/seats.
            for i, page in enumerate(pages):
                await page.goto(harness.origin + '/app#roomid=' + room['id'])
                await page.get_by_role('button', name='Открыть дело', exact=True).click()
                await page.get_by_role('button', name=room['title'], exact=True).click()
                await page.get_by_label('Имя в этой партии', exact=True).fill('Игрок ' + str(i + 1))
                await page.get_by_role('button', name='Я готов', exact=True).click()
                await page.get_by_role('button', name='Изменить имя и готовность', exact=True).wait_for()
            await pages[0].get_by_role('button', name='Начать дело', exact=True).wait_for(timeout=20000)
            await pages[0].get_by_role('button', name='Начать дело', exact=True).click()
            await pages[0].get_by_role('button', name='Досье', exact=True).wait_for()
            views = [await req(i, base + 'view') for i in range(4)]
            report['steps'].append('four_real_accounts_room_lobby_ready_start')
            role_to_index = {v['self']['character_id']: i for i, v in enumerate(views)}
            actor = role_to_index['investigator']
            for page in pages:
                await page.get_by_role('button', name='Досье', exact=True).wait_for(timeout=20000)
            page = pages[actor]
            async def refresh_ui():
                async with page.expect_response(lambda response: urlsplit(response.url).path == base + 'view' and response.status == 200) as pending:
                    await page.locator('[data-qw-gear]:visible').click()
                    await page.get_by_role('button', name='Обновить связь', exact=True).click()
                refreshed = await (await pending.value).json()
                await page.wait_for_function('(window) => document.querySelector(".nc-title h1")?.textContent.startsWith("Окно " + window + " ·")', arg=refreshed['public']['clock']['window_idx'])
                return refreshed
            await page.get_by_role('button', name='Досье', exact=True).click()
            await page.get_by_role('heading', name='Как засчитывается цель', exact=True).wait_for()
            if identity_only:
                report['scope'] = 'night_case_identity_focused_fence' if identity_focused else 'night_case_identity_fence'
                target = next(i for i in range(4) if i != actor)
                before = await req(target, base + 'view')
                a_role = views[actor]['self']['role']['bio']['text']
                b_role = views[target]['self']['role']['bio']['text']
                assert a_role in await page.locator('body').inner_text()
                original_cookie = next(cookie for cookie in await contexts[actor].cookies() if cookie['name'] == 'mqb_guest')
                replacement = next(cookie for cookie in await contexts[target].cookies() if cookie['name'] == 'mqb_guest')
                if identity_focused:
                    await page.get_by_role('button', name='Место', exact=True).click()
                    field = page.get_by_label('Что ты хочешь сделать?', exact=True)
                    await field.fill('A_ONLY_UNSENT_PRIVATE_DRAFT_CANARY')
                    await field.focus()
                    assert await field.evaluate('(node) => document.activeElement === node')
                    async with page.expect_response(lambda response: response.status == 409 and urlsplit(response.url).path in {base + 'view', '/api/night-case/bootstrap'}, timeout=20000) as pending:
                        await contexts[actor].add_cookies([replacement])
                        # No click, blur, submission or forced refresh: real polling must detect it.
                else:
                    await contexts[actor].add_cookies([replacement])
                    await page.locator('[data-qw-gear]:visible').click()
                    await page.get_by_role('button', name='Покинуть дело', exact=True).click()
                    async with page.expect_response(lambda response: urlsplit(response.url).path == base + 'quote') as pending:
                        await page.get_by_role('button', name='Подтвердить', exact=True).click()
                blocked = await pending.value
                assert blocked.status == 409 and (await blocked.json())['code'] == 'profile_changed'
                assert blocked.request.headers['x-night-expected-viewer'] == viewer_pins[actor]
                await page.get_by_role('heading', name='Открой дело заново', exact=True).wait_for()
                private = await page.locator('body').inner_text()
                assert a_role not in private and b_role not in private
                assert await page.locator('textarea').count() == 0
                # Direct same-sequence stale command also fails before applying as B.
                stale = await contexts[actor].request.post(harness.origin + base + 'commands?identity=guest',
                    headers={'Origin': harness.origin, 'X-Guest-CSRF': '1', 'X-Night-Expected-Viewer': viewer_pins[actor]},
                    data={'command_id': str(uuid4()), 'kind': 'seen', 'params': {},
                          'window_idx': before['public']['clock']['window_idx'], 'window_seq': before['public']['clock']['window_seq'],
                          'actor_seq': before['self']['actor_seq']})
                assert stale.status == 409 and (await stale.json())['code'] == 'profile_changed'
                after = await req(target, base + 'view')
                assert {key: after['self'][key] for key in ['actor_seq', 'ap', 'status']} == {key: before['self'][key] for key in ['actor_seq', 'ap', 'status']}
                for width, height in [(375, 812), (390, 844), (1280, 800)]:
                    await page.set_viewport_size({'width': width, 'height': height})
                    name = f'identity-locked-{width}x{height}.png'
                    await page.screenshot(path=str(output / name), full_page=True)
                    report['screenshots'].append(name)
                    result = await page.evaluate(SCANNER, [8, 44])
                    assert not result['issues'], result
                    report['gaps'].append({'width': width, **result})
                await contexts[actor].add_cookies([original_cookie])
                async with page.expect_response(lambda response: urlsplit(response.url).path == '/api/night-case/bootstrap') as restored:
                    await page.reload()
                    await reopen(page)
                assert (await (await restored.value).json())['viewer_account_id'] == viewer_pins[actor]
                await page.get_by_role('button', name='Досье', exact=True).click()
                await page.get_by_role('heading', name='Как засчитывается цель', exact=True).wait_for()
                assert a_role in await page.locator('body').inner_text()
                assert b_role not in await page.locator('body').inner_text()
                report['steps'].extend(['cookie_A_to_B_focused_unsent_draft_background_probe_and_same_sequence_seen_no_B_effect' if identity_focused else 'cookie_A_to_B_old_forfeit_and_same_sequence_seen_profile_changed_no_B_effect',
                    'locked_private_DOM_cleared_three_viewports', 'restored_A_new_bootstrap_own_role_only'])
                report.update({'passed': True, 'game_id': game, 'case_hash': harness.settings.allowed_hashes.__iter__().__next__()})
                await browser.close(); browser = None
                print(json.dumps({'scope': report['scope'], 'passed': True, 'steps': report['steps']}), flush=True)
                return
            await page.screenshot(path=str(output / 'role-before-action.png'), full_page=True)
            report['tabs_geometry'] = await page.locator('.ncase-tabs').evaluate('(node) => ({rect: node.getBoundingClientRect().toJSON(), tabs: [...node.children].map(child => ({text: child.textContent, rect: child.getBoundingClientRect().toJSON()}))})')
            # Generic legal command transport is reused for exhaustive authored path after UI probes.
            async def command(i, kind, params):
                state = await req(i, base + 'view')
                payload = {'command_id': str(uuid4()), 'kind': kind, 'params': params, 'window_idx': state['public']['clock']['window_idx'],
                           'window_seq': state['public']['clock']['window_seq'], 'actor_seq': state['self']['actor_seq']}
                result = await req(i, base + 'commands', payload)
                assert result['receipt']['accepted'], result
                return payload, result
            async def next_window():
                before = await req(actor, base + 'view')
                if before['public'].get('final') is not None:
                    return before
                for i in range(4):
                    await command(i, 'seen', {})
                before = await req(actor, base + 'view')
                settled = await harness.advance(game)
                async def read_transition():
                    response = await contexts[actor].request.get(harness.origin + base + 'view?identity=guest',
                        headers={'X-Night-Expected-Viewer': viewer_pins[actor]})
                    if response.status == 503:
                        return None
                    if not response.ok:
                        raise AssertionError('Transition view HTTP ' + str(response.status))
                    return await response.json()
                try:
                    after = await wait_for_window(read_transition, before['public']['clock']['window_seq'])
                except Exception:
                    report.setdefault('advance_failures', []).append(await harness.safe_metadata(game))
                    raise
                report.setdefault('window_transitions', []).append({'before': before['public']['clock'],
                    'after': after['public']['clock'], 'manual_settled': settled,
                    'terminal': after['public'].get('final') is not None})
                return after
            async def perform(action_id):
                document = json.loads(CASE_PATH.read_text(encoding='utf8'))
                action = next(a for a in document['actions'] if a['id'] == action_id)
                for _ in range(32):
                    state = await req(actor, base + 'view')
                    if state['public'].get('final') is not None:
                        raise AssertionError('Authored action path reached terminal state before completion')
                    if state['self']['ap'] < 1:
                        await next_window(); continue
                    if state['self']['location'] == action['location']:
                        await command(actor, 'act', {'action_id': action_id}); return
                    from domain.night_case_simulation import _route
                    route = _route(document, {'public': {'flags': state['public']['flags']}}, state['self']['location'], action['location'])
                    if any(lock['location'] == route[0] for lock in state['public']['locks']):
                        await next_window(); continue
                    await command(actor, 'move', {'location': route[0]})
                raise AssertionError('Authored action path exceeded its bounded move/window budget')
            # UI menu → persisted proposal → explicit confirmation.
            await page.get_by_role('button', name='Место', exact=True).click()
            await page.get_by_role('button', name='Ключ сервисной панели', exact=True).click()
            before_action = await req(actor, base + 'view')
            confirm_requests = []
            async def lose_first_confirm(route):
                confirm_requests.append(route.request.post_data_json)
                if len(confirm_requests) == 1:
                    committed = await route.fetch()
                    assert committed.ok, await committed.text()
                    await route.abort('failed')  # The server committed; this browser genuinely loses the response.
                else:
                    await route.continue_()
            await page.route('**/api/night-case/games/' + game + '/confirm?*', lose_first_confirm)
            await page.get_by_role('button', name='Подтвердить', exact=True).click()
            await page.get_by_role('button', name='Повторить', exact=True).click()
            await page.get_by_role('button', name='Повторить', exact=True).wait_for(state='hidden')
            await page.unroute('**/api/night-case/games/' + game + '/confirm?*', lose_first_confirm)
            assert len(confirm_requests) == 2 and confirm_requests[0] == confirm_requests[1]
            assert (await req(actor, base + 'view'))['self']['ap'] == before_action['self']['ap'] - 1
            await page.get_by_role('button', name='Досье', exact=True).wait_for()
            report['steps'].append('real_ui_role_proposal_confirm_lost_browser_response_same_proposal_retry_single_cost')
            # Public and frozen-recipient private MessageRecords through the real command endpoint.
            await command(actor, 'say', {'channel': 'square', 'recipients': [], 'text': 'Общее обсуждение усадьбы.'})
            partner = next(i for i in range(4) if i != actor)
            document = json.loads(CASE_PATH.read_text(encoding='utf8'))
            destination = (await req(actor, base + 'view'))['self']['location']
            for _ in range(20):
                partner_state = await req(partner, base + 'view')
                if partner_state['self']['location'] == destination:
                    break
                from domain.night_case_simulation import _route
                route = _route(document, {'public': {'flags': partner_state['public']['flags']}}, partner_state['self']['location'], destination)
                assert route, 'No legal partner route for private-message acceptance'
                if partner_state['self']['ap'] < 1 or any(lock['location'] == route[0] for lock in partner_state['public']['locks']):
                    await next_window()
                else:
                    await command(partner, 'move', {'location': route[0]})
            else:
                raise AssertionError('Partner did not reach the whisper location within bounded legal moves')
            private_command, first = await command(actor, 'say', {'channel': 'whisper', 'recipients': [views[partner]['self']['character_id']], 'text': 'Приватная сверка двух источников.'})
            repeat = await req(actor, base + 'commands', private_command)
            assert repeat == first
            outsider = next(i for i in range(4) if i not in {actor, partner})
            denied = await contexts[outsider].request.get(harness.origin + base + 'messages/' + first['caused_message_ids'][0] + '?identity=guest',
                headers={'X-Night-Expected-Viewer': viewer_pins[outsider]})
            assert denied.status == 404
            report['steps'].append('public_private_chat_duplicate_api_replay_other_actor_acl')
            # Capture real mounted views in two actual clock periods, not edited DTO fixtures.
            for period in ['day', 'night']:
                if period == 'night':
                    await next_window()
                    await harness.jump(harness.now.replace(hour=21, minute=0, second=0))
                await page.get_by_role('button', name='Место', exact=True).click()
                for width, height in [(375, 812), (390, 844), (1280, 800)]:
                    await page.set_viewport_size({'width': width, 'height': height})
                    refreshed = await refresh_ui()
                    await page.get_by_role('button', name='Досье', exact=True).wait_for()
                    pointer = refreshed['public']['art']
                    assert pointer == {'manifest_sha256': ART_HASH, 'manifest_url': f'/app/night/packs/{ART_HASH}/assets.json'}
                    manifest_response = await contexts[actor].request.get(harness.origin + pointer['manifest_url'])
                    assert manifest_response.ok
                    manifest = await manifest_response.json()
                    location = next(item for item in refreshed['public']['locations'] if item['id'] == refreshed['self']['location'])
                    from zoneinfo import ZoneInfo
                    hour = datetime.fromisoformat(refreshed['server_now'].replace('Z', '+00:00')).astimezone(ZoneInfo(refreshed['public']['clock']['timezone'])).hour
                    visual_time = 'night' if hour < 6 or hour >= 21 else 'morning' if hour < 11 else 'day' if hour < 17 else 'evening'
                    artwork = manifest['assets'][location['art']['asset_id']]
                    expected_url = pointer['manifest_url'].removesuffix('assets.json') + artwork.get('variants', {}).get(visual_time, artwork['url'])
                    await page.wait_for_function('(url) => document.querySelector(".ncase-main .nc-hero")?.style.getPropertyValue("--img").includes(url)', arg=expected_url)
                    await page.evaluate('() => { window.scrollTo(0, 0); return document.fonts.ready; }')
                    await page.screenshot(path=str(output / f'night-case-{period}-{width}x{height}.png'), full_page=True)
                    report['screenshots'].append(f'night-case-{period}-{width}x{height}.png')
                    if period == 'day' and width == 390:
                        await page.evaluate('window.scrollTo(0, 744)')
                        await page.screenshot(path=str(output / 'sticky-gap-scroll744.png'), full_page=False)
                        report['sticky_gap_diagnostic'] = await page.evaluate('''() => {
                            const header = document.querySelector('.nc-bar');
                            const rect = header.getBoundingClientRect();
                            const buttons = [...document.querySelectorAll('button')].filter(node => {
                                const r = node.getBoundingClientRect(); return r.bottom >= 0 && r.top < rect.bottom + 80;
                            });
                            return {scrollY, header: rect.toJSON(), buttons: buttons.map(node => {
                                const r = node.getBoundingClientRect(), x = Math.min(innerWidth - 1, Math.max(0, r.left + r.width / 2));
                                return {text: node.innerText || node.getAttribute('aria-label'), rect: r.toJSON(), samples: Array.from({length: Math.ceil(r.height) + 2}, (_, i) => {
                                    const y = Math.floor(r.top) + i, hit = document.elementFromPoint(x, y);
                                    return {x,y,hit: hit?.tagName, owner: hit?.closest('button')?.innerText || hit?.closest('button')?.getAttribute('aria-label'), own: !!hit && node.contains(hit)};
                                }).filter(sample => sample.y >= 0 && sample.y < innerHeight)};
                            })};
                        }''')
                    result = {'issues': [], 'scans': []}
                    page_height = await page.evaluate('document.documentElement.scrollHeight')
                    for scroll in range(0, page_height, max(1, height - 100)):
                        await page.evaluate('(top) => window.scrollTo(0, top)', scroll)
                        scan = await page.evaluate(SCANNER, [8, 44])
                        result['scans'].append({'scroll': scroll, **scan})
                        result['issues'] += scan['issues']
                    if width < 768:
                        result['issues'] += await page.evaluate(ZONE_SCANNER, [47, 48])
                    report['gaps'].append({'period': period, 'width': width, **result})
                await page.get_by_role('button', name='Досье', exact=True).click()
                await page.screenshot(path=str(output / f'night-case-{period}-dossier-detail.png'), full_page=True)
            # Sequential restart reuses real persisted sessions and exact factory/registry.
            await harness.stop(); await harness.start()
            for i, other in enumerate(pages):
                if i == actor:
                    continue
                async with other.expect_response(lambda response: urlsplit(response.url).path == base + 'view' and response.status == 200, timeout=20000):
                    pass  # Existing controller's real polling reconnects after the restart.
            await page.reload()
            await reopen(page)
            assert (await req(actor, base + 'view'))['game_id'] == game
            report['steps'].append('http_worker_restart_three_mounted_controllers_automatic_poll_reconnect')
            report['steps'].append('single_explicit_reload_cookie_session_restore')
            from storage.models import NightGameSealed
            async with harness.database.transaction() as session:
                variant = (await session.get(NightGameSealed, game)).kernel['sealed']['variant_id']
            letter = variant[-1]
            sources = {'a': [('a1', ['draft_copy', 'will_register_copy']), ('a2', ['key_ledger']), ('a3', ['lawyer_receipt', 'bolt_order'])],
                       'b': [('b1', ['horn_record', 'rope_record']), ('b2', ['duty_roster', 'ice_track_record']), ('b3', ['horn_record'])],
                       'c': [('c1', ['owner_letter', 'owner_hand_sample']), ('c2', ['undeveloped_plate']), ('c3', ['anonymous_invitation', 'invitation_order_copy'])]}
            known = set()
            for key, observations in sources[letter]:
                for observation in observations:
                    if observation not in known:
                        await perform('inspect_' + observation); known.add(observation)
                await perform('compare_' + key)
                await command(actor, 'pin', {'observation_id': key})
            state = await req(actor, base + 'view')
            while state['public']['clock']['window_idx'] < 3:
                await next_window(); state = await req(actor, base + 'view')
            culprit = {'a': 'lawyer', 'b': 'hunter', 'c': 'owner'}[letter]
            cited = [b['id'] for b in state['public']['board'] if b['observation_id'] in {letter + str(n) for n in [1, 2, 3]}]
            await command(actor, 'accuse', {'suspect': culprit, 'citations': cited})
            for i in range(4):
                state = await req(i, base + 'view')
                await command(i, 'vote', {'hearing_id': state['public']['hearing']['id'], 'choice': 'support', 'citations': []})
            for _ in range(2):
                await next_window()
            state = await req(actor, base + 'view')
            assert state['public']['final']['code'] == 'solved', state['public']['final']
            history = await req(actor, base + 'history?stream=self&limit=50')
            assert history['items']
            report['steps'].append('real_authored_keys_hearing_votes_worker_due_solved_history')
            report['shell_icon_http_statuses'] = [entry['status'] for entry in report['public_resource_statuses']
                if entry['path'] == '/app/night/shell/icons.svg']
            assert report['shell_icon_http_statuses'] and all(status in {200, 304} for status in report['shell_icon_http_statuses'])
            assert not report['audio_requests'], 'Unexpected media request in silent Night Case acceptance'
            if with_farm:
                await capture_farm(contexts[actor], harness, output, report)
            assert not any(scan['issues'] for scan in report['gaps']), report['gaps']
            report['game_id'], report['case_hash'], report['passed'] = game, harness.settings.allowed_hashes.__iter__().__next__(), True
            await browser.close(); browser = None
    except Exception:
        import traceback
        report['error'] = traceback.format_exc()
        if 'game' in locals():
            try:
                report['failure_metadata'] = await harness.safe_metadata(game)
            except Exception as diagnostic_error:
                report['diagnostic_error_type'] = type(diagnostic_error).__name__
        if browser:
            for context_index, context in enumerate(contexts):
                for page_index, failed_page in enumerate(context.pages):
                    try:
                        await failed_page.screenshot(path=str(output / f'failure-{context_index}-{page_index}.png'), full_page=True)
                        (output / f'failure-{context_index}-{page_index}.txt').write_text(await failed_page.locator('body').inner_text(), encoding='utf8')
                    except Exception:
                        pass
        raise
    finally:
        report['fixture_clock'] = 'accelerated_UTC_anchor_plus_monotonic_wall_elapsed'
        report['worker_runs'] = list(harness.worker_runs)
        report['readiness_probes'] = list(harness.probe_observations)
        if browser:
            try:
                await browser.close()
            except Exception:
                pass
        await harness.stop()
        await harness.database.dispose()
        (output / 'night-case-browser-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
    print(json.dumps({key: report[key] for key in ['scope', 'passed', 'game_id', 'case_hash', 'steps']}, ensure_ascii=False), flush=True)


async def exercise_farm(port, output):
    """Farm regression on the real platform clock; Night's accelerated clock is irrelevant."""
    from playwright.async_api import async_playwright
    output.mkdir(parents=True, exist_ok=True)
    harness = Harness(port, farm_only=True)
    report = {'scope': 'farm_predeploy', 'production': 'not_authorized', 'steps': [], 'screenshots': []}
    try:
        await harness.start()
        async with async_playwright() as playwright:
            browser = None
            for options in [{}, {'channel': 'msedge'}, {'channel': 'chrome'}]:
                try:
                    browser = await playwright.chromium.launch(**options)
                    break
                except Exception:
                    continue
            if browser is None:
                raise RuntimeError('No installed Chromium-family browser available for Farm QA')
            context = await browser.new_context(viewport={'width': 390, 'height': 844}, reduced_motion='reduce')
            report['reduced_motion'] = True
            response = await context.request.post(harness.origin + '/api/guest/start', headers={'Origin': harness.origin, 'X-Guest-CSRF': '1'})
            assert response.ok, await response.text()
            await capture_farm(context, harness, output, report)
            report['passed'] = True
            await browser.close()
    except Exception:
        import traceback
        report['error'] = traceback.format_exc()
        raise
    finally:
        await harness.stop()
        await harness.database.dispose()
        (output / 'farm-browser-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
    print(json.dumps({'passed': report['passed'], 'screenshots': len(report['screenshots'])}), flush=True)


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--setup', action='store_true')
    parser.add_argument('--farm-only', action='store_true')
    parser.add_argument('--with-farm', action='store_true')
    parser.add_argument('--identity-only', action='store_true')
    parser.add_argument('--identity-focused', action='store_true')
    parser.add_argument('--port', type=int, default=4899)
    parser.add_argument('--output', type=Path, default=Path(r'F:\Temp\mqb-night-browser-01a1dfba'))
    args = parser.parse_args()
    if args.setup:
        await setup()
    elif args.farm_only:
        await exercise_farm(args.port, args.output)
    else:
        await exercise(args.port, args.output, with_farm=args.with_farm,
                       identity_only=args.identity_only or args.identity_focused, identity_focused=args.identity_focused)


if __name__ == '__main__':
    asyncio.run(main())
