"""HTTP-only acceptance of already running loopback previews; never real Telegram."""
import asyncio
import json
import httpx


async def main():
    async with httpx.AsyncClient(base_url='http://127.0.0.1:4184', timeout=60) as client:
        response = await client.post('/auth/login', json={'token': 'local-tests-only-admin-key-0000012345'})
        response.raise_for_status()
        response = await client.get('/auth/session')
        response.raise_for_status()
        client.headers['X-CSRF-Token'] = response.json()['csrf_token']
        for path in ('/', '/api/control/maintenance', '/api/dev-backups', '/api/dev-broadcasts', '/api/admin-ai/providers', '/api/analytics/report', '/api/chats', '/api/bank/categories'):
            response = await client.get(path)
            response.raise_for_status()
        before = (await client.get('/api/dev-runtime')).json()
        if before['running']:
            raise SystemExit('A user-started offline runtime is already running; leaving it unchanged.')
        try:
            response = await client.post('/api/dev-runtime/start', json={})
            response.raise_for_status()
            assert response.json()['running'] and not response.json()['telegram_delivery']
            response = await client.post('/api/dev-runtime/input/update', json={'message': '/start'})
            response.raise_for_status()
            assert response.json()['messages'] and not any(e['event'] == 'handler_error' for e in response.json()['events'])
        finally:
            response = await client.post('/api/dev-runtime/stop', json={})
            response.raise_for_status()
        await client.post('/auth/logout')
    async with httpx.AsyncClient(base_url='http://127.0.0.1:4185', timeout=15) as mini:
        (await mini.get('/app')).raise_for_status()
        response = await mini.post('/api/dev/session')
        response.raise_for_status()
        mini.headers['Authorization'] = 'Bearer ' + response.json()['access_token']
        for path in ('/api/mini/me', '/api/mini/progress', '/api/mini/chats', '/api/mini/leaderboard', '/api/mini/chats/-900000000091/details'):
            (await mini.get(path)).raise_for_status()
        (await mini.delete('/api/mini/session')).raise_for_status()
    print(json.dumps({'admin_http': 'passed', 'offline_runtime': 'start-command-stop passed', 'mini_http': 'passed', 'telegram_calls': 0}))


if __name__ == '__main__':
    asyncio.run(main())
