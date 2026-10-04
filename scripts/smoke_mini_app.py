"""Сквозная проверка Mini App: подписывает initData и проходит ключевые маршруты.

Запуск на тестовом контуре из каталога проекта:

    MINI_APP_BOT_TOKEN=<токен тестового бота> ./venv/bin/python scripts/smoke_mini_app.py \
        --base-url http://127.0.0.1:8081 --user-id 621817842

Хост в `--base-url` должен совпадать с `MINI_APP_ORIGIN` сервиса: мини-апп сравнивает
свой origin с адресом запроса и иначе отвечает 403.

Скрипт ничего не создаёт, кроме одной сессии мини-аппа: она тут же закрывается
(`DELETE /api/mini/session`), а старый токен проверяется на отказ. Поэтому запускать
его нужно на тестовом контуре, а не на боевом во время выкладки.
"""
import argparse
import asyncio
import hashlib
import hmac
import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402


def init_data(token, user_id, *, name='Smoke Check'):
    payload = {'auth_date': str(int(time.time())),
               'user': json.dumps({'id': user_id, 'first_name': name}, separators=(',', ':'))}
    check = '\n'.join(f'{key}={payload[key]}' for key in sorted(payload))
    secret = hmac.new(b'WebAppData', token.encode(), hashlib.sha256).digest()
    return urlencode({**payload, 'hash': hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()})


class Report:
    def __init__(self):
        self.failures = []

    def check(self, name, ok, detail=''):
        print(f"  {'OK  ' if ok else 'FAIL'} {name}{f' — {detail}' if detail else ''}")
        if not ok:
            self.failures.append(name)
        return ok

    def skip(self, name, reason):
        print(f'  SKIP {name} — {reason}')


async def main() -> int:
    parser = argparse.ArgumentParser(description='Сквозная проверка Mini App по ключевым маршрутам.')
    parser.add_argument('--base-url', default=os.getenv('MINI_APP_SMOKE_URL', 'http://127.0.0.1:8081'))
    parser.add_argument('--user-id', type=int, default=int(os.getenv('MINI_APP_SMOKE_USER') or 0))
    parser.add_argument('--bot-token', default=os.getenv('MINI_APP_BOT_TOKEN', ''))
    parser.add_argument('--timeout', type=float, default=30.0)
    args = parser.parse_args()
    if not args.bot_token:
        print('Нужен MINI_APP_BOT_TOKEN (или --bot-token).', file=sys.stderr)
        return 2
    if not args.user_id:
        print('Нужен --user-id (или MINI_APP_SMOKE_USER).', file=sys.stderr)
        return 2

    report = Report()
    async with httpx.AsyncClient(base_url=args.base_url.rstrip('/'), timeout=args.timeout) as client:
        health = await client.get('/healthz')
        report.check('GET /healthz', health.status_code == 200, f'{health.status_code}')

        page = await client.get('/app')
        body = page.text if page.status_code == 200 else ''
        report.check('GET /app', page.status_code == 200 and '/app/app.js' in body, f'{page.status_code}')

        client_js = await client.get('/app/app.js')
        report.check('GET /app/app.js', client_js.status_code == 200 and 'RENEW_AFTER_MS' in client_js.text,
                     f'{client_js.status_code}')

        login = await client.post('/api/mini/session', json={'init_data': init_data(args.bot_token, args.user_id)})
        if not report.check('POST /api/mini/session', login.status_code == 200, f'{login.status_code}'):
            print('Дальше идти нельзя: сессия не создана.', file=sys.stderr)
            return 1
        headers = {'Authorization': f"Bearer {login.json()['access_token']}"}

        for path, marker in (('/api/mini/me', 'user_id'), ('/api/mini/config', 'runtime_enabled'),
                             ('/api/mini/progress', 'correct_including_photo'),
                             ('/api/mini/achievements', 'summary'), ('/api/mini/history', 'chats'),
                             ('/api/mini/categories', 'items'), ('/api/mini/leaderboard', 'items')):
            response = await client.get(path, headers=headers)
            ok = response.status_code == 200 and marker in response.text
            report.check(f'GET {path}', ok, f'{response.status_code}, {len(response.content)} байт')

        chats = await client.get('/api/mini/chats?limit=50', headers=headers)
        items = chats.json().get('items', []) if chats.status_code == 200 else []
        report.check('GET /api/mini/chats', chats.status_code == 200 and isinstance(items, list),
                     f'{len(items)} чатов')
        if items:
            # Личный чат доступен и в offline-режиме; для групп проверка членства
            # отключена, и 503 там — ожидаемое поведение, а не поломка контура.
            target = next((item for item in items if item.get('type') == 'private'), items[0])
            chat_id = target['chat_id']
            details = await client.get(f'/api/mini/chats/{chat_id}/details', headers=headers)
            if details.status_code == 503:
                report.skip(f'GET /api/mini/chats/{chat_id}/details',
                            '503: проверка членства отключена в offline-режиме')
            else:
                ok = details.status_code == 200 and 'me' in details.text
                report.check(f'GET /api/mini/chats/{chat_id}/details', ok,
                             f'{details.status_code} {target.get("type")}')

        renew = await client.post('/api/mini/session/renew', headers=headers)
        report.check('POST /api/mini/session/renew', renew.status_code == 200 and 'expires_in' in renew.text,
                     f'{renew.status_code} {renew.text[:60]}')

        logout = await client.delete('/api/mini/session', headers=headers)
        report.check('DELETE /api/mini/session', logout.status_code == 204, f'{logout.status_code}')

        stale = await client.get('/api/mini/me', headers=headers)
        report.check('GET /api/mini/me после выхода', stale.status_code == 401, f'{stale.status_code}')

    print(f"\nИТОГ: {'всё в порядке' if not report.failures else 'проблемы: ' + ', '.join(report.failures)}")
    return 1 if report.failures else 0


if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))
