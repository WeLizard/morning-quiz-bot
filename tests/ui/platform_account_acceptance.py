"""Real browser account/device acceptance using only a fresh QA account.

Credentials are generated in memory, never logged or persisted in artifacts.
No Telegram identity, existing player account, or farm command is used.
"""
import argparse
import json
from pathlib import Path
import secrets
from urllib.parse import urlsplit
from uuid import uuid4

from playwright.sync_api import sync_playwright


def run(args):
    parsed = urlsplit(args.base)
    base = f'{parsed.scheme}://{parsed.netloc}'
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    login = 'qa_next_' + uuid4().hex[:12]
    password, replacement = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    title = 'QA Account continuity ' + uuid4().hex[:8]
    with sync_playwright() as p:
        cached = Path('F:/Caches/ms-playwright/chromium-1248/chrome-win64/chrome.exe')
        browser = p.chromium.launch(headless=True, **({'executable_path': str(cached)} if cached.exists() else {}))
        contexts = [browser.new_context(ignore_https_errors=True, viewport={'width': 390, 'height': 844},
                    user_agent=f'Mozilla/5.0 (MQB QA device {label})') for label in ['A', 'B']]
        pages = [context.new_page() for context in contexts]
        errors = []
        for page in pages:
            page.on('pageerror', lambda error: errors.append(str(error)))

        def api(index, path, body=None, expected=200):
            headers = {'Origin': base, 'X-Guest-CSRF': '1'}
            if path.startswith('/api/farm/v1/'):
                headers['X-QW-Farm'] = '1'
            response = contexts[index].request.fetch(base + path,
                method='GET' if body is None else 'POST', data=body,
                headers=headers)
            assert response.status == expected, f'{path}: {response.status}'
            return response.json() if expected == 200 else None

        def login_ui(page, secret, expected=200):
            page.goto(base + '/app', wait_until='networkidle')
            page.get_by_role('button', name='Войти по логину', exact=True).click()
            page.locator('input[name=username]').fill(login)
            page.locator('input[name=password]').fill(secret)
            with page.expect_response(lambda response: '/api/account/login' in response.url) as result:
                page.get_by_role('button', name='Войти', exact=True).click()
            assert result.value.status == expected
            if expected == 200:
                page.get_by_role('button', name='На свою ферму', exact=True).wait_for()

        try:
            original = api(0, '/api/guest/start', {})
            api(0, '/api/account/address-form?identity=guest', {'address_form': 'n'})
            pages[0].goto(base + '/app#settings', wait_until='networkidle')
            pages[0].get_by_role('button', name='Сохранить профиль: задать логин и пароль', exact=True).click()
            form = pages[0].locator('form.account-form').filter(
                has=pages[0].get_by_role('button', name='Сохранить профиль', exact=True))
            form.locator('input[name=username]').fill(login)
            form.locator('input[name=password]').fill(password)
            with pages[0].expect_response(lambda response: '/api/account/register' in response.url) as result:
                form.get_by_role('button', name='Сохранить профиль', exact=True).click()
            assert result.value.status == 200
            assert api(0, '/api/guest/me')['account_id'] == original['account_id']
            farm = api(0, '/api/farm/v1/start?identity=guest', {})
            farm_id = farm['farm']['id']
            room = api(0, '/api/guest/rooms', {'request_id': str(uuid4()), 'title': title})

            login_ui(pages[1], password)
            assert api(1, '/api/guest/me')['account_id'] == original['account_id']
            assert api(1, '/api/farm/v1/me?identity=guest')['farm']['id'] == farm_id
            assert room['id'] in [item['id'] for item in api(1, '/api/guest/rooms')['items']]
            pages[1].screenshot(path=str(output / 'new-device-home.png'), full_page=True)

            # Force the existing settings document to fetch the newly logged-in
            # device list; the one-time settings fragment has been consumed.
            pages[0].reload(wait_until='networkidle')
            session_rows = api(0, '/api/account/sessions?identity=guest')['sessions']
            assert len(session_rows) == 2 and sum(bool(row['current']) for row in session_rows) == 1
            pages[0].locator('#navigation button[data-page="profile"]').click()
            pages[0].locator('button.settings-open').click()
            pages[0].locator('.devices-card').wait_for()
            # The server normalizes user-agent strings; select the only row
            # carrying the revoke action instead of matching that label.
            device = pages[0].locator('.devices-card li.device-row').filter(
                has=pages[0].get_by_role('button', name='Выйти', exact=True))
            assert device.count() == 1, 'Expected exactly one revocable device'
            with pages[0].expect_response(lambda response: '/api/account/sessions/revoke?' in response.url) as result:
                device.get_by_role('button', name='Выйти', exact=True).click()
            assert result.value.status == 200
            api(1, '/api/guest/me', expected=401)
            login_ui(pages[1], password)
            assert api(1, '/api/farm/v1/me?identity=guest')['farm']['id'] == farm_id

            change = pages[0].locator('form.account-form').filter(has=pages[0].locator('input[name=new_password]'))
            change.locator('input[name=current_password]').fill(password)
            change.locator('input[name=new_password]').fill(replacement)
            with pages[0].expect_response(lambda response: '/api/account/password?' in response.url) as result:
                change.get_by_role('button', name='Сменить пароль', exact=True).click()
            assert result.value.status == 200
            api(1, '/api/guest/me', expected=401)
            assert api(0, '/api/guest/me')['account_id'] == original['account_id']
            login_ui(pages[1], password, expected=401)
            login_ui(pages[1], replacement)
            assert api(1, '/api/farm/v1/me?identity=guest')['farm']['id'] == farm_id
            assert room['id'] in [item['id'] for item in api(1, '/api/guest/rooms')['items']]
            pages[0].reload(wait_until='networkidle')
            assert api(0, '/api/guest/me')['account_id'] == original['account_id']
            pages[0].screenshot(path=str(output / 'account-settings.png'), full_page=True)
            assert not errors, errors
            report = {'base': base, 'qa_account_id': original['account_id'], 'qa_room_id': room['id'],
                      'new_device_same_account': True, 'same_farm_and_room': True,
                      'revoked_device_denied': True, 'password_revokes_others': True,
                      'old_password_denied': True, 'new_password_works': True,
                      'current_device_kept': True, 'reload_preserves_account': True, 'page_errors': errors}
            (output / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps(report, ensure_ascii=False))
        finally:
            for context in contexts:
                context.close()
            browser.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', required=True)
    parser.add_argument('--output', required=True)
    run(parser.parse_args())
