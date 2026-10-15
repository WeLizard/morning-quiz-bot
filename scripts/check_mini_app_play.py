"""HTTP gameplay smoke: fixed synthetic localhost profile only, never live Telegram."""
import asyncio
import json
from uuid import uuid4
import httpx


async def main():
    step = 'load synthetic dev profile'
    async with httpx.AsyncClient(base_url='http://127.0.0.1:4185', timeout=15, trust_env=False) as client:
        info = (await client.get('/api/dev/info')).json()
        if not info.get('synthetic_player'):
            raise RuntimeError('Refusing gameplay against a non-synthetic profile')
        login = await client.post('/api/dev/session', json={})
        login.raise_for_status()
        client.headers.update({'Origin': 'http://127.0.0.1:4185', 'X-Mini-CSRF': '1'})
        try:
            step = 'load Mini App identity and active games'
            me = (await client.get('/api/mini/me')).json()
            assert me['user_id'] == '900000000091'
            games = (await client.get('/api/mini/chats/900000000091/games')).json()
            if games['items']:
                raise RuntimeError('A synthetic game is already active: left untouched')
            classic_path = '/api/mini/classic/chats/900000000091'
            photo_path = '/api/mini/photo/chats/900000000091'
            classic_stopped = False
            photo_stopped = False
            try:
                step = 'start Classic game'
                start = await client.post(classic_path + '/start', json={'command_id': uuid4().hex})
                start.raise_for_status()
                started = start.json()
                assert started['question']['round_id'] and 'correct_option' not in started['question']
                step = 'answer Classic question and verify idempotency'
                answer_payload = {'round_id': started['question']['round_id'], 'selected_option': 0, 'command_id': uuid4().hex}
                answer = await client.post(classic_path + '/answer', json=answer_payload)
                answer.raise_for_status()
                answered = answer.json()
                duplicate = await client.post(classic_path + '/answer', json=answer_payload)
                duplicate.raise_for_status()
                assert duplicate.json() == answered
                stop = await client.post(classic_path + '/stop', json={
                    'command_id': uuid4().hex, 'expected_revision': answered['revision'],
                })
                stop.raise_for_status()
                assert stop.json()['status'] == 'stopped'
                classic_stopped = True
                step = 'load chat settings and Photo setup'
                details = await client.get('/api/mini/chats/900000000091/details')
                details.raise_for_status()
                assert 'settings_revision' in details.json()
                photo_setup = await client.get(photo_path + '/setup')
                photo_setup.raise_for_status()
                setup = photo_setup.json()
                if not setup.get('can_start'):
                    raise RuntimeError('Synthetic photo catalog has no playable question')
                step = 'start Photo game and verify protected image delivery'
                photo_start = await client.post(photo_path + '/start', json={
                    'command_id': uuid4().hex,
                    'question_count': setup['question_count'],
                    'open_seconds': setup['open_seconds'],
                    'hints_enabled': setup['hints_enabled'],
                })
                photo_start.raise_for_status()
                photo = photo_start.json()
                image = await client.get(photo_path + '/current/image')
                image.raise_for_status()
                assert image.headers.get('content-type', '').startswith('image/') and len(image.content) > 100
                step = 'answer Photo question and verify idempotency'
                wrong_payload = {'command_id': uuid4().hex,
                    'round_id': photo['question']['round_id'],
                    'answer': '__smoke_answer_that_cannot_match__'}
                wrong = await client.post(photo_path + '/answer', json=wrong_payload)
                wrong.raise_for_status()
                duplicate = await client.post(photo_path + '/answer', json=wrong_payload)
                duplicate.raise_for_status()
                assert duplicate.json() == wrong.json() and wrong.json()['verdict'] == 'wrong'
                photo_stop = await client.post(photo_path + '/stop', json={
                    'command_id': uuid4().hex, 'expected_revision': wrong.json()['revision'],
                })
                photo_stop.raise_for_status()
                assert photo_stop.json()['status'] == 'stopped'
                photo_stopped = True
                step = 'complete'
            finally:
                if not classic_stopped:
                    sync = await client.post(classic_path + '/sync')
                    if sync.is_success and sync.json().get('revision') is not None:
                        await client.post(classic_path + '/stop', json={
                            'command_id': uuid4().hex, 'expected_revision': sync.json()['revision'],
                        })
                if not photo_stopped:
                    sync = await client.post(photo_path + '/sync')
                    if sync.is_success and sync.json().get('revision') is not None:
                        await client.post(photo_path + '/stop', json={
                            'command_id': uuid4().hex, 'expected_revision': sync.json()['revision'],
                        })
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
        print('HTTP gameplay check failed at ' + step + ': ' + type(error).__name__ + ': ' + str(error).split(' for url ')[0])
        raise SystemExit(1)
