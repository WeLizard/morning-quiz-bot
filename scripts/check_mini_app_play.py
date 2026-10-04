"""HTTP gameplay smoke: fixed synthetic localhost profile only, never live Telegram."""
import asyncio
import json
from uuid import uuid4
import httpx


async def main():
    async with httpx.AsyncClient(base_url='http://127.0.0.1:4185', timeout=15, trust_env=False) as client:
        info = (await client.get('/api/dev/info')).json()
        if not info.get('synthetic_player'):
            raise RuntimeError('Refusing gameplay against a non-synthetic profile')
        login = await client.post('/api/dev/session', json={})
        login.raise_for_status()
        client.headers['Authorization'] = 'Bearer ' + login.json()['access_token']
        try:
            me = (await client.get('/api/mini/me')).json()
            assert me['user_id'] == '900000000091'
            games = (await client.get('/api/mini/chats/900000000091/games')).json()
            if games['items']:
                raise RuntimeError('A synthetic game is already active: left untouched')
            async def state():
                result = await client.get('/api/mini/runtime'); result.raise_for_status(); return result.json()
            async def action(**fields):
                payload = {'request_id': uuid4().hex, **fields}
                accepted = await client.post('/api/mini/runtime/actions', json=payload)
                accepted.raise_for_status()
                for _ in range(35):
                    await asyncio.sleep(.3)
                    value = await state()
                    receipt = next(r for r in value['requests'] if r['id'] == payload['request_id'])
                    if receipt['status'] not in {'pending', 'running'}:
                        if receipt['status'] != 'done':
                            raise RuntimeError(receipt.get('error', receipt['status']))
                        return value
                raise RuntimeError('Action did not complete')
            async def click(data):
                value = await state()
                card = next(m for m in reversed(value['messages']) if any(b.get('data') == data for row in m['buttons'] for b in row))
                return await action(type='callback', value=data, message_id=card['id'], revision=card['revision'])
            classic_path = '/api/mini/classic/chats/900000000091'
            start = await client.post(
                classic_path + '/start', json={'command_id': uuid4().hex}
            )
            start.raise_for_status()
            started = start.json()
            assert started['question']['round_id'] and 'correct_option' not in started['question']
            answer_payload = {
                'round_id': started['question']['round_id'],
                'selected_option': 0,
                'command_id': uuid4().hex,
            }
            answer = await client.post(classic_path + '/answer', json=answer_payload)
            answer.raise_for_status()
            answered = answer.json()
            duplicate = await client.post(classic_path + '/answer', json=answer_payload)
            duplicate.raise_for_status()
            assert duplicate.json() == answered
            stop = await client.post(classic_path + '/stop', json={
                'command_id': uuid4().hex,
                'expected_revision': answered['revision'],
            })
            stop.raise_for_status()
            assert stop.json()['status'] == 'stopped'
            settings = await action(type='command', value='/adminsettings')
            assert any(b['data'].startswith('admcfg_') for m in settings['messages'] for row in m['buttons'] for b in row)
            await action(type='command', value='/start')
            photo_path = '/api/mini/photo/chats/900000000091'
            photo_start = await client.post(photo_path + '/start', json={
                'command_id': uuid4().hex, 'question_count': 1,
                'open_seconds': 60, 'hints_enabled': True,
            })
            photo_start.raise_for_status()
            photo = photo_start.json()
            image = await client.get(photo_path + '/current/image')
            image.raise_for_status()
            assert image.headers.get('content-type', '').startswith('image/') and len(image.content) > 100
            wrong_payload = {'command_id': uuid4().hex,
                'round_id': photo['question']['round_id'],
                'answer': '__smoke_answer_that_cannot_match__'}
            wrong = await client.post(photo_path + '/answer', json=wrong_payload)
            wrong.raise_for_status()
            duplicate = await client.post(photo_path + '/answer', json=wrong_payload)
            duplicate.raise_for_status()
            assert duplicate.json() == wrong.json() and wrong.json()['verdict'] == 'wrong'
            photo_stop = await client.post(photo_path + '/stop', json={
                'command_id': uuid4().hex,
                'expected_revision': wrong.json()['revision'],
            })
            photo_stop.raise_for_status()
            assert photo_stop.json()['status'] == 'stopped'
            print(json.dumps({'http_gameplay': 'passed', 'classic_direct_start_answer_stop': True,
                'shared_settings': True, 'photo_direct_start_answer_stop': True,
                'photo_image_loaded': True,
                'telegram_requests': 0}))
        finally:
            await client.delete('/api/mini/session')


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except Exception as error:
        print('HTTP gameplay check failed: ' + type(error).__name__ + ': ' + str(error).split(' for url ')[0])
        raise SystemExit(1)
