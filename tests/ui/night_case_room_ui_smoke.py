"""Two NEW rehearsal guests: all onboarding/Room/invite/lobby writes by actual UI."""
import argparse
import asyncio
import json
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

ORIGIN = 'https://quiz.mr-lizard.ru'


async def smoke(output):
    from playwright.async_api import async_playwright
    output.mkdir(parents=True, exist_ok=True)
    report = {'scope': 'rehearsal_room_invite_entirely_UI', 'passed': False,
              'steps': [], 'frames': [], 'http_errors': [], 'audio_requests': [],
              'direct_write_API_calls': 0, 'clipboard_used': False,
              'limits': ['Two-seat lobby only; party not started.', 'Invite UI is available after creating its table.']}
    pages = []
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(channel='msedge')
            try:
                contexts = []
                for _ in range(2):
                    context = await browser.new_context(viewport={'width': 390, 'height': 844}, reduced_motion='reduce')
                    contexts.append(context)
                    context.on('response', lambda response: report['http_errors'].append({'path': urlsplit(response.url).path, 'status': response.status}) if response.status >= 400 else None)
                    context.on('request', lambda request: report['audio_requests'].append(urlsplit(request.url).path) if request.resource_type == 'media' else None)
                    page = await context.new_page(); pages.append(page)
                    await page.goto(ORIGIN + '/app')
                    await page.get_by_role('button', name='Продолжить как гость', exact=True).click()
                    await page.get_by_role('button', name='Открыть дело', exact=True).click()
                    await page.get_by_label('Название комнаты', exact=True).wait_for()
                report['steps'].append('two_new_guests_by_visible_guest_onboarding_and_open_case')
                host, joiner = pages
                title = 'UI invite smoke ' + uuid4().hex[:8]
                await host.get_by_label('Название комнаты', exact=True).fill(title)
                async with host.expect_response(lambda r: urlsplit(r.url).path == '/api/guest/rooms' and r.request.method == 'POST') as pending:
                    await host.get_by_role('button', name='Создать', exact=True).click()
                response = await pending.value; assert response.ok, (response.status, await response.text())
                room = await response.json(); report['room_id'] = room['id']
                async with host.expect_response(lambda r: urlsplit(r.url).path == f"/api/rooms/{room['id']}/night-case/lobby" and r.request.method == 'POST') as pending:
                    await host.get_by_role('button', name='Создать стол', exact=True).click()
                response = await pending.value; assert response.ok, (response.status, await response.text())
                game = (await response.json())['view']['game_id']; report['game_id'] = game
                async with host.expect_response(lambda r: urlsplit(r.url).path == f"/api/guest/rooms/{room['id']}/invites" and r.request.method == 'POST') as pending:
                    await host.get_by_role('button', name='Создать приглашение', exact=True).click()
                response = await pending.value; assert response.ok, (response.status, await response.text())
                code_node = host.get_by_label('Код приглашения', exact=True)
                await code_node.wait_for()
                short = (await code_node.inner_text()).strip()
                assert len(short.replace('-', '')) == 8
                report['visible_code_format'] = '4-4' if '-' in short else '8'
                report['steps'].append('UI_create_new_room_create_table_create_invite_read_visible_short_code')
                path = output / 'host-visible-invite-390.png'
                await host.screenshot(path=str(path), full_page=True); report['frames'].append(str(path))
                await joiner.get_by_label('Код или ссылка приглашения', exact=True).fill(short)
                async with joiner.expect_response(lambda r: urlsplit(r.url).path == '/api/guest/rooms/join' and r.request.method == 'POST') as pending:
                    await joiner.get_by_role('button', name='Войти в комнату', exact=True).click()
                response = await pending.value; assert response.ok, (response.status, await response.text())
                assert (await response.json())['id'] == room['id']
                async with joiner.expect_response(lambda r: urlsplit(r.url).path == f'/api/night-case/games/{game}/join' and r.request.method == 'POST') as pending:
                    await joiner.get_by_role('button', name='Присоединиться к столу', exact=True).click()
                response = await pending.value; assert response.ok, (response.status, await response.text())
                await joiner.get_by_label('Имя в этой партии', exact=True).wait_for()
                report['steps'].append('UI_enter_visible_short_code_join_own_room_explicitly_join_table')
                path = output / 'joiner-two-seat-lobby-390.png'
                await joiner.screenshot(path=str(path), full_page=True); report['frames'].append(str(path))
                accounts = []
                for context in contexts:
                    # Read-only verification after UI completion; no injected cookies.
                    response = await context.request.get(ORIGIN + '/api/night-case/bootstrap?identity=guest')
                    assert response.ok; pin = (await response.json())['viewer_account_id']; accounts.append(pin)
                    response = await context.request.get(ORIGIN + f'/api/night-case/games/{game}/view?identity=guest', headers={'X-Night-Expected-Viewer': pin})
                    assert response.ok; view = await response.json()
                    assert view['mode'] == 'night_case' and len(view['lobby']['seats']) == 2
                    assert view['lobby']['self_seat'] is not None and not view['lobby']['can_start']
                report['accounts'] = accounts
                assert not report['audio_requests'], report['audio_requests']
                report['passed'] = True
            except Exception:
                for i, page in enumerate(pages):
                    await page.screenshot(path=str(output / f'failure-{i}.png'), full_page=True)
                    (output / f'failure-{i}.txt').write_text(await page.locator('body').inner_text(), encoding='utf8')
                raise
            finally:
                await browser.close()
    finally:
        (output / 'room-ui-smoke-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--applied', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not args.applied:
        parser.error('Explicit rehearsal authorization required.')
    asyncio.run(smoke(args.output))
