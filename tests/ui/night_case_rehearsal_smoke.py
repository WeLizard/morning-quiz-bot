"""Opt-in public rehearsal smoke: four NEW guests, own Room, real first window.

No database, local server, worker control, clock jump, bot or external AI.
Run only after the coordinator's APPLIED signal, with --applied explicitly.
"""
import argparse
import asyncio
import json
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

ORIGIN = 'https://quiz.mr-lizard.ru'
ART = 'a640e3af35a3f2166778193d43d73bc874bb563a9c4888bbd2c3a999a5e5ca2f'


async def smoke(output):
    from playwright.async_api import async_playwright
    from ui_check import SCANNER
    output.mkdir(parents=True, exist_ok=True)
    report = {'scope': 'public_rehearsal_first_window', 'passed': False, 'steps': [], 'accounts': [],
              'frames': [], 'http_errors': [], 'missing_assets': [], 'audio_requests': [], 'unpinned_night_requests': [],
              'limits': ['Real clock, first window only; no full-week solved/restart claim.',
                         'Free text clarifies; explicit authored selection creates the proposal.',
                         'Frames use the actual server period; local r5 covers both day/night.']}
    browser = None
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(channel='msedge')
            contexts, pages, pins = [], [], []
            def response_seen(response):
                path = urlsplit(response.url).path
                row = {'path': path, 'status': response.status}
                if response.status >= 400:
                    report['http_errors'].append(row)
                    if path.startswith('/app/'):
                        report['missing_assets'].append(row)
            def request_seen(request):
                path = urlsplit(request.url).path
                if request.resource_type == 'media' or Path(path).suffix.lower() in {'.mp3', '.m4a', '.ogg', '.wav'}:
                    report['audio_requests'].append(path)
                if path.startswith('/api/night-case/') and path != '/api/night-case/bootstrap' and not request.headers.get('x-night-expected-viewer'):
                    report['unpinned_night_requests'].append(path)
            async def req(i, path, data=None):
                url = ORIGIN + path + ('&' if '?' in path else '?') + 'identity=guest'
                headers = {'X-Night-Expected-Viewer': pins[i]} if len(pins) > i else {}
                if data is None:
                    response = await contexts[i].request.get(url, headers=headers)
                else:
                    response = await contexts[i].request.post(url, data=data,
                        headers={**headers, 'Origin': ORIGIN, 'X-Guest-CSRF': '1'})
                assert response.ok, (path, response.status, await response.text())
                return await response.json()
            for _ in range(4):
                context = await browser.new_context(viewport={'width': 390, 'height': 844}, reduced_motion='reduce')
                context.on('response', response_seen)
                context.on('request', request_seen)
                contexts.append(context)
                response = await context.request.post(ORIGIN + '/api/guest/start',
                    headers={'Origin': ORIGIN, 'X-Guest-CSRF': '1'})
                assert response.ok, response.status
                me = await req(len(contexts) - 1, '/api/guest/me')
                bootstrap = await req(len(contexts) - 1, '/api/night-case/bootstrap')
                assert bootstrap['enabled'] and bootstrap['viewer_account_id'] == me['account_id']
                assert any(case['id'] == 'manor_lake_missing' and case['version'] == 2 for case in bootstrap['cases'])
                pins.append(bootstrap['viewer_account_id'])
                report['accounts'].append(me['account_id'])
                pages.append(await context.new_page())
            title = 'Rehearsal smoke ' + uuid4().hex[:8]
            room = await req(0, '/api/guest/rooms', {'request_id': str(uuid4()), 'title': title})
            report['room_id'] = room['id']
            invite = await req(0, f"/api/guest/rooms/{room['id']}/invites", {'expires_in_seconds': 3600, 'max_uses': 3})
            for i in range(1, 4):
                await req(i, '/api/guest/rooms/join', {'short_code': invite['short_code']})
            created = await req(0, f"/api/rooms/{room['id']}/night-case/lobby", {
                'command_id': str(uuid4()), 'expected_lobby_revision': 0,
                'params': {'case_id': 'manor_lake_missing', 'case_version': 2, 'timezone': 'Europe/Berlin'}})
            game = created['view']['game_id']; report['game_id'] = game
            base = f'/api/night-case/games/{game}/'
            for i in range(1, 4):
                view = await req(i, base + 'view')
                await req(i, base + 'join', {'command_id': str(uuid4()),
                    'expected_lobby_revision': view['lobby']['lobby_revision'], 'params': {}})
            for i, page in enumerate(pages):
                await page.goto(ORIGIN + '/app')
                await page.get_by_role('button', name='Открыть дело', exact=True).click()
                await page.get_by_role('button', name=title, exact=True).click()
                await page.get_by_label('Имя в этой партии', exact=True).fill(f'Проверка {i + 1}')
                await page.get_by_role('button', name='Я готов', exact=True).click()
                await page.get_by_role('button', name='Изменить имя и готовность', exact=True).wait_for()
            await pages[0].get_by_role('button', name='Начать дело', exact=True).click()
            for page in pages:
                await page.get_by_role('button', name='Досье', exact=True).wait_for(timeout=25000)
            views = [await req(i, base + 'view') for i in range(4)]
            assert all(view['public']['art']['manifest_sha256'] == ART for view in views)
            report['roles'] = [view['self']['character_id'] for view in views]
            report['server_now'] = views[0]['server_now']
            report['steps'].append('four_new_guests_own_room_invite_ready_start_roles')
            actor = next(i for i, view in enumerate(views) if any(row.get('quote', {}).get('kind') == 'act' and row['quote']['cost'] == 1 for row in view['menu']))
            page = pages[actor]
            await page.get_by_role('button', name='Место', exact=True).click()
            before = await req(actor, base + 'view')
            await page.get_by_label('Что ты хочешь сделать?', exact=True).fill('Хочу внимательно осмотреть комнату.')
            await page.get_by_role('button', name='Предложить действие', exact=True).click()
            await page.get_by_text('Уточни действие: выбери одну из доступных кнопок. Пока ничего не потрачено.', exact=True).wait_for()
            assert (await req(actor, base + 'view'))['self']['ap'] == before['self']['ap']
            action = next(row for row in before['menu'] if row.get('quote', {}).get('kind') == 'act' and row['quote']['cost'] == 1)
            await page.get_by_role('button', name=action['label'] + ' · 1 ОД', exact=True).click()
            confirms = []
            async def lose_first(route):
                confirms.append(route.request.post_data)
                assert route.request.headers['x-night-expected-viewer'] == pins[actor]
                if len(confirms) == 1:
                    committed = await route.fetch()
                    assert committed.ok, committed.status
                    await route.abort('failed')
                else:
                    await route.continue_()
            pattern = '**/api/night-case/games/' + game + '/confirm?*'
            await page.route(pattern, lose_first)
            await page.get_by_role('button', name='Подтвердить', exact=True).click()
            await page.get_by_role('button', name='Повторить', exact=True).click()
            await page.get_by_role('button', name='Повторить', exact=True).wait_for(state='hidden')
            await page.unroute(pattern, lose_first)
            assert len(confirms) == 2 and confirms[0] == confirms[1]
            assert (await req(actor, base + 'view'))['self']['ap'] == before['self']['ap'] - 1
            report['confirm_requests'] = len(confirms)
            report['steps'].append('free_text_clarification_authored_proposal_confirm_lost_response_exact_retry_one_AP')
            async def command(i, kind, params):
                view = await req(i, base + 'view')
                payload = {'command_id': str(uuid4()), 'kind': kind, 'params': params,
                    'window_idx': view['public']['clock']['window_idx'], 'window_seq': view['public']['clock']['window_seq'], 'actor_seq': view['self']['actor_seq']}
                result = await req(i, base + 'commands', payload)
                assert result['receipt']['accepted'], result['receipt']
                return payload, result
            await command(actor, 'say', {'channel': 'square', 'recipients': [], 'text': 'Обсуждение smoke: осмотр завершён.'})
            views = [await req(i, base + 'view') for i in range(4)]
            partner = next(i for i in range(4) if i != actor and views[i]['self']['location'] == views[actor]['self']['location'])
            payload, result = await command(actor, 'say', {'channel': 'whisper', 'recipients': [views[partner]['self']['character_id']], 'text': 'Только двум проверочным игрокам.'})
            assert await req(actor, base + 'commands', payload) == result
            outsider = next(i for i in range(4) if i not in {actor, partner})
            mid = result['caused_message_ids'][0]
            await req(partner, base + 'messages/' + mid)
            response = await contexts[outsider].request.get(ORIGIN + base + 'messages/' + mid + '?identity=guest', headers={'X-Night-Expected-Viewer': pins[outsider]})
            assert response.status == 404
            for stream in ['public', 'self', 'messages']:
                assert (await req(actor, base + 'history?stream=' + stream))['items']
            report['steps'].append('square_whisper_recipient_acl_exact_replay_first_window_history')
            for width, height in [(375, 812), (390, 844), (1280, 800)]:
                await page.set_viewport_size({'width': width, 'height': height})
                await page.get_by_role('button', name='Место', exact=True).click()
                await page.evaluate('scrollTo(0,0)')
                path = output / f'live-first-window-{width}.png'
                await page.screenshot(path=str(path), full_page=True)
                issues = []
                size = await page.evaluate('document.documentElement.scrollHeight')
                for top in range(0, size, height - 100):
                    await page.evaluate('(y) => scrollTo(0,y)', top)
                    issues.extend((await page.evaluate(SCANNER, [8, 44]))['issues'])
                assert not issues, issues
                report['frames'].append(str(path))
            await page.get_by_role('button', name='Досье', exact=True).click()
            await page.screenshot(path=str(output / 'live-own-dossier.png'), full_page=True)
            # Swap only these two NEW guest cookies; the old controller must lock.
            original = next(c for c in await contexts[actor].cookies() if c['name'] == 'mqb_guest')
            replacement = next(c for c in await contexts[partner].cookies() if c['name'] == 'mqb_guest')
            before_b = await req(partner, base + 'view')
            await page.get_by_role('button', name='Место', exact=True).click()
            await page.get_by_label('Что ты хочешь сделать?', exact=True).fill('PRIVATE_UNSENT_SMOKE_CANARY')
            await page.get_by_label('Что ты хочешь сделать?', exact=True).focus()
            async with page.expect_response(lambda r: r.status == 409 and urlsplit(r.url).path in {base + 'view', '/api/night-case/bootstrap'}, timeout=20000):
                await contexts[actor].add_cookies([replacement])
            await page.get_by_role('heading', name='Открой дело заново', exact=True).wait_for()
            locked_text = await page.locator('body').inner_text()
            assert 'PRIVATE_UNSENT_SMOKE_CANARY' not in locked_text
            assert all(views[i]['self']['role']['title'] not in locked_text for i in [actor, partner])
            assert await page.locator('textarea').count() == 0
            after_b = await req(partner, base + 'view')
            assert all(after_b['self'][key] == before_b['self'][key] for key in ['actor_seq', 'ap', 'status'])
            await contexts[actor].add_cookies([original])
            restored = await req(actor, '/api/night-case/bootstrap')
            assert restored['viewer_account_id'] == pins[actor]
            assert (await req(actor, base + 'view'))['self']['character_id'] == report['roles'][actor]
            report['steps'].append('focused_cookie_profile_fence_purge_no_B_cost_restore_A')
            assert not report['missing_assets'], report['missing_assets']
            assert not report['audio_requests'], report['audio_requests']
            assert not report['unpinned_night_requests'], report['unpinned_night_requests']
            report['passed'] = True
    finally:
        if browser:
            try:
                await browser.close()
            except Exception as error:
                # The async_playwright context may already have closed its pipe.
                report['browser_cleanup_note'] = type(error).__name__
        (output / 'rehearsal-smoke-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--applied', action='store_true', help='Coordinator explicitly confirmed deployment APPLIED')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not args.applied:
        parser.error('No live requests allowed before explicit APPLIED; supply --applied only after that signal.')
    asyncio.run(smoke(args.output))
