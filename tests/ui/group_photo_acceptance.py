"""Real two-browser Photo journey against dev/rehearsal, using only QA-owned games.

Reads the selected QA game's answer through the local dev DB or --remote SSH.
Never mocks HTTP, reads other games, prints credentials, or resets a database.
"""
import argparse
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
import subprocess
import time
from urllib.parse import urlsplit
from uuid import uuid4

from playwright.sync_api import sync_playwright


def owned_answer(game_id, round_id, remote):
    assert re.fullmatch(r'[0-9a-f-]{36}', game_id)
    assert re.fullmatch(r'[0-9a-f]{32}', round_id)
    query = ("SELECT r->>'display_answer' FROM games g, "
             "jsonb_array_elements(g.state::jsonb->'rounds') r "
             f"WHERE g.id='{game_id}' AND r->>'round_id'='{round_id}';")
    if remote:
        command = 'docker exec -i morning-quiz-postgres sh -c \'psql -U "$POSTGRES_USER" -d morning_quiz_rehearsal -X -At\''
        out = subprocess.run(['C:/Windows/System32/OpenSSH/ssh.exe', '-F', 'NUL',
                              '-o', 'BatchMode=yes', 'lizard@192.168.0.33', command],
                             input=query, capture_output=True, text=True, encoding='utf-8', check=True).stdout.strip()
        assert out, 'QA game answer was not found'
        return out

    async def read():
        import asyncpg
        connection = await asyncpg.connect(user='mqb_dev', password='local-development-only',
                                          host='127.0.0.1', port=55433, database='morning_quiz_dev')
        try:
            return await connection.fetchval(query)
        finally:
            await connection.close()
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(lambda: asyncio.run(read())).result()


def run(args):
    parsed = urlsplit(args.base)
    origin = f'{parsed.scheme}://{parsed.netloc}'
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    title = 'QA Group Photo ' + uuid4().hex[:8]
    with sync_playwright() as p:
        installed = Path('F:/Caches/ms-playwright/chromium-1248/chrome-win64/chrome.exe')
        browser = p.chromium.launch(headless=True, **({'executable_path': str(installed)} if installed.is_file() else {}))
        contexts = [browser.new_context(ignore_https_errors=True) for _ in range(3)]
        pages = [ctx.new_page() for ctx in contexts]
        errors = []
        for page in pages:
            page.on('pageerror', lambda error: errors.append(str(error)))

        def api(index, path, body=None, *, key=False, expected=200):
            headers = {'Origin': origin, 'X-Guest-CSRF': '1'}
            if key:
                headers['Idempotency-Key'] = str(uuid4())
            response = contexts[index].request.fetch(origin + path,
                method='GET' if body is None else 'POST', data=body, headers=headers)
            assert response.status == expected, f'{path}: {response.status} {response.text()[:220]}'
            return response.json() if expected == 200 else None

        for index in range(3):
            api(index, '/api/guest/start', {})
            api(index, '/api/account/address-form?identity=guest', {'address_form': 'n'})
        room = api(0, '/api/guest/rooms', {'request_id': str(uuid4()), 'title': title})
        room_id = room['id']
        base = f'/api/guest/rooms/{room_id}/photo'
        invite = api(0, f'/api/guest/rooms/{room_id}/invites',
                     {'expires_in_seconds': 86400, 'max_uses': 3}, key=True)
        api(1, '/api/guest/rooms/join', {'invite_code': invite['invite_code']})
        started = api(0, base + '/start', {'question_count': 2, 'open_seconds': args.seconds,
            'hints_enabled': False, 'answer_policy': 'group_private_deadline'}, key=True)
        game = started.get('current', started)
        round_id = game['question']['round_id']
        answer = owned_answer(game['game_id'], round_id, args.remote)
        assert answer
        api(2, base + '/current', expected=404)
        image = contexts[2].request.get(origin + game['question']['image_url'])
        assert image.status == 404

        for page in pages[:2]:
            page.goto(origin + '/app', wait_until='networkidle')
            room_card = page.locator('article.guest-room-item').filter(
                has=page.get_by_text(title, exact=True))
            room_card.get_by_role('button', name='Открыть фото-загадки', exact=True).click()
            page.get_by_role('textbox', name='Твой ответ на фото').wait_for()
        for page in pages[:2]:
            page.get_by_role('textbox', name='Твой ответ на фото').fill(answer)
            page.get_by_role('button', name='Ответить', exact=True).click()
            page.get_by_text('Ответ принят, ждём завершения раунда', exact=True).wait_for()
        own = api(0, base + '/current')['current']
        assert own['question']['answered'] and float(own['score']) == 0
        assert 'responses' not in json.dumps(own)
        if args.restart_worker:
            if args.remote:
                subprocess.run(['C:/Windows/System32/OpenSSH/ssh.exe', '-F', 'NUL',
                    'lizard@192.168.0.33', 'sudo -n systemctl restart mqb-game-worker.service'], check=True)
            else:
                subprocess.run(['docker', 'restart', 'mqb-local-dev-game-worker-1'], check=True, capture_output=True)

        def shots(label):
            for width, height in [(375, 812), (390, 844), (1280, 800)]:
                pages[0].set_viewport_size({'width': width, 'height': height})
                for theme in ['light', 'dark']:
                    pages[0].evaluate('(theme) => {document.documentElement.dataset.theme=theme}', theme)
                    pages[0].evaluate('window.scrollTo(0, 0)')
                    pages[0].screenshot(path=str(output / f'{label}-{width}-{theme}.png'), full_page=False)
                    pages[0].evaluate('window.scrollTo(0, document.documentElement.scrollHeight)')
                    pages[0].screenshot(path=str(output / f'{label}-{width}-{theme}-bottom.png'), full_page=False)
            pages[0].locator('#content').screenshot(path=str(output / f'{label}-closeup.png'))
        shots('accepted')

        until = time.monotonic() + args.seconds + 15
        while time.monotonic() < until:
            current = api(0, base + '/current')['current']
            if current.get('last_result'):
                break
            time.sleep(.5)
        else:
            raise AssertionError('Independent worker did not close the Photo round')
        assert len(current['last_result']['solvers']) == 2
        assert float(current['score']) > 0 and current['question']['round_id'] != round_id
        assert float(api(1, base + '/current')['current']['score']) > 0
        pages[0].get_by_text(re.compile('Верно ответили:')).wait_for(timeout=10000)
        shots('results')
        stopped = api(0, base + '/stop', {'game_id': current['game_id'],
            'expected_revision': current['revision']}, key=True)
        assert stopped.get('stop_requested') or stopped.get('current', {}).get('stop_requested')
        assert not errors, errors
        manifest = {'room_id': room_id, 'game_id': game['game_id'], 'title': title,
                    'base': args.base, 'two_solvers': True, 'pre_deadline_score': 0,
                    'independent_worker': True, 'outsider_denied': True, 'page_errors': errors,
                    'worker_restarted_while_pending': args.restart_worker,
                    'second_round_stop_requested': True}
        (output / 'result.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(manifest, ensure_ascii=False))
        for context in contexts:
            context.close()
        browser.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--remote', action='store_true')
    parser.add_argument('--seconds', type=int, default=30)
    parser.add_argument('--restart-worker', action='store_true')
    run(parser.parse_args())
