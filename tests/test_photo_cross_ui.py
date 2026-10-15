"""One disposable-PG Photo journey through real Telegram and Mini App adapters."""
import asyncio
from hashlib import sha256
import hmac
from io import BytesIO
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import urlencode
from uuid import uuid4

import httpx
from PIL import Image
from sqlalchemy import select
from telegram import Update
from telegram.ext import CallbackContext

from tests.local_database import isolated_database
from tests.test_telegram_test_scope import BOT, CHAT, TOKEN, message_update
from tests.test_postgres_members import pg_env


def test_photo_bot_and_mini_share_image_answer_and_score(pg_env, monkeypatch, tmp_path):
    from modules import dev_runtime as offline
    from modules.telegram_test_scope import PrivateTestScope
    from scripts import run_telegram_test as runner
    from storage.models import ChatMember, Game, GameCommand, PollAnswer, User
    from storage.photos import PhotoCatalog
    from storage.repositories import OperationalRepository
    from web.mini_app import MiniAppSettings, create_app
    import telegram.request

    encoded = BytesIO()
    Image.new('RGB', (2, 2), (45, 100, 175)).save(encoded, format='WEBP', lossless=True)
    image = encoded.getvalue()
    with Image.open(BytesIO(image)) as decoded:
        assert decoded.format == 'WEBP' and decoded.size == (2, 2)
        decoded.load()
    images = tmp_path / '.local' / 'preview' / 'images'
    images.mkdir(parents=True)
    for answer in ('Сова', 'Лиса', 'Бобёр'):
        (images / f'{answer}.webp').write_bytes(image)
    monkeypatch.setenv('PHOTO_IMAGES_DIR', str(images))
    monkeypatch.setenv('BOT_TOKEN', TOKEN)
    monkeypatch.setenv('STORAGE_BACKEND', 'postgres')
    monkeypatch.setenv('MINI_APP_URL', '')
    monkeypatch.setattr(runner, 'WORKSPACE', tmp_path)
    monkeypatch.setattr(offline, 'CHAT', CHAT)
    monkeypatch.setattr(offline, 'USER', CHAT)
    monkeypatch.setattr(offline, 'ROOM', {'id': CHAT, 'type': 'private', 'first_name': 'Tester'})
    monkeypatch.setattr(offline, 'PLAYER', {'id': CHAT, 'first_name': 'Tester', 'is_bot': False})

    async def run():
        async with isolated_database(pg_env) as (db, _):
            async with db.transaction() as session:
                repo = OperationalRepository(session)
                await repo.ensure_chat({'id': CHAT, 'type': 'private'})
                await repo.ensure_user({'id': CHAT, 'display_name': 'Tester'})
                await repo.ensure_member({'chat_id': CHAT, 'user_id': CHAT})
            for answer in ('Сова', 'Лиса', 'Бобёр'):
                await PhotoCatalog(db).get_or_create(answer)
            dummy = offline.DevRuntime(db)
            monkeypatch.setattr(telegram.request, 'HTTPXRequest', lambda **kwargs: offline.OfflineRequest(dummy))
            scope = PrivateTestScope(CHAT, BOT)
            app, config, quiz, photos, dm = await runner.build_application(db, scope, TOKEN, None)
            try:
                await app.initialize()
                await app.start()

                async def send(text):
                    if text.startswith('/'):
                        update = message_update(command=text, bot=app.bot)
                    else:
                        update = Update.de_json({'update_id': dummy.next_id(), 'message': {
                            'message_id': dummy.next_id(), 'date': int(time.time()),
                            'from': offline.PLAYER, 'chat': offline.ROOM, 'text': text,
                        }}, app.bot)
                    await runner.dispatch(app, config, scope, update)

                async def click(source, data):
                    await runner.dispatch(app, config, scope, Update.de_json({
                        'update_id': dummy.next_id(), 'callback_query': {
                            'id': uuid4().hex, 'from': offline.PLAYER,
                            'chat_instance': 'photo-test', 'message': source, 'data': data,
                        },
                    }, app.bot))

                def choice(data):
                    return next(message for message in dummy.messages.values()
                                for row in message.get('reply_markup', {}).get('inline_keyboard', [])
                                for button in row if button.get('callback_data') == data)

                await send('/photo_quiz')
                await click(choice('pqcfg_start'), 'pqcfg_start')
                assert any(message.get('photo') for message in dummy.messages.values())
                async with db.transaction() as session:
                    first = await session.scalar(select(Game).where(
                        Game.chat_id == CHAT, Game.mode == 'photo', Game.is_current.is_(True)))
                    assert first is not None and first.status == 'active'
                    assert (await session.get(User, CHAT)).global_score == 0
                    first_answer = first.state['rounds'][0]['display_answer']

                origin = 'http://127.0.0.1:4185'
                mini = create_app(database=db, settings=MiniAppSettings(TOKEN, origin, offline=True),
                                  membership=SimpleNamespace(allowed=AsyncMock(return_value=True)),
                                  clock=lambda: int(time.time()), runtime_enabled=True)
                fields = {'auth_date': str(int(time.time())),
                          'user': json.dumps({'id': CHAT, 'first_name': 'Tester'})}
                check = '\n'.join(f'{key}={value}' for key, value in sorted(fields.items()))
                key = hmac.new(b'WebAppData', TOKEN.encode(), sha256).digest()
                fields['hash'] = hmac.new(key, check.encode(), sha256).hexdigest()
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=mini),
                                             base_url=origin) as client:
                    login = await client.post('/api/mini/session', json={'init_data': urlencode(fields)})
                    assert login.status_code == 200, login.text
                    base = f'/api/mini/photo/chats/{CHAT}'
                    current = await client.get(base + '/current')
                    assert current.status_code == 200, current.text
                    question = current.json()['question']
                    assert question['round_id'] == first.state['current_round_id']
                    assert question['image_url'] == base + '/current/image?round_id=' + question['round_id']
                    assert first_answer not in current.text
                    loaded = await client.get(question['image_url'])
                    assert loaded.status_code == 200 and loaded.content == image
                    command_id = uuid4().hex
                    payload = {'command_id': command_id, 'round_id': question['round_id'],
                               'answer': first_answer.lower()}
                    headers = {'Origin': origin, 'X-Mini-CSRF': '1'}
                    answered = await client.post(base + '/answer', json=payload, headers=headers)
                    assert answered.status_code == 200, answered.text
                    assert answered.json()['applied'] is True
                    assert answered.json()['verdict'] == 'correct'
                    assert answered.json()['status'] == 'active'
                    replay = await client.post(base + '/answer', json=payload, headers=headers)
                    assert replay.status_code == 200 and replay.json() == answered.json()
                    async with db.transaction() as session:
                        score = (await session.get(User, CHAT)).global_score
                        member = await session.get(ChatMember, (CHAT, CHAT))
                        assert score > 0 and member.score == score
                        assert member.answered_count == 0  # Photo does not increment Classic poll count.
                    # Telegram text has no round id. Repeating the previous answer
                    # acts as a wrong attempt on the next, distinct photo question.
                    await send(first_answer.lower())
                    current = await client.get(base + '/current')
                    assert current.status_code == 200 and current.json()['status'] == 'active'
                    assert current.json()['question']['round_id'] != question['round_id']
                    async with db.transaction() as session:
                        assert (await session.get(User, CHAT)).global_score == score
                        member = await session.get(ChatMember, (CHAT, CHAT))
                        assert member.score == score and member.answered_count == 0
                        answers = (await session.scalars(select(PollAnswer).where(
                            PollAnswer.game_id == first.id, PollAnswer.user_id == CHAT))).all()
                        assert len(answers) == 1 and answers[0].round_id == question['round_id']
                        commands = (await session.scalars(select(GameCommand).where(
                            GameCommand.game_id == first.id, GameCommand.kind == 'photo.answer'))).all()
                        assert len(commands) == 2 and command_id in {row.id for row in commands}
                        assert first.state['rounds'][1]['display_answer'] != first_answer
                        current_game = await session.get(Game, first.id)
                        assert current_game.state['rounds'][1]['attempts'] == 1

                    stopped = await client.post(base + '/stop', headers=headers, json={
                        'command_id': uuid4().hex,
                        'expected_revision': current.json()['revision'],
                    })
                    assert stopped.status_code == 200 and stopped.json()['status'] == 'stopped'

                    # Reverse direction: Mini starts a new series and the actual
                    # Telegram text handler settles it against the same PG state.
                    sent_before = sum(bool(m.get('photo')) for m in dummy.messages.values())
                    started = await client.post(base + '/start', headers=headers, json={
                        'command_id': uuid4().hex, 'question_count': 1,
                        'open_seconds': 60, 'hints_enabled': True,
                    })
                    assert started.status_code == 200, started.text
                    second = started.json()
                    assert second['game_id'] != first.id
                    async with db.transaction() as session:
                        second_game = await session.get(Game, second['game_id'])
                        second_answer = second_game.state['rounds'][0]['display_answer']
                    await app.bot_data['game_runtime'].notification_job(CallbackContext(app))
                    photo_messages = [m for m in dummy.messages.values() if m.get('photo')]
                    assert len(photo_messages) > sent_before
                    await send(second_answer.lower())
                    after = await client.get(base + '/current')
                    assert after.status_code == 200 and after.json()['status'] == 'finished'
                    async with db.transaction() as session:
                        final_score = (await session.get(User, CHAT)).global_score
                        assert final_score > score
                        member = await session.get(ChatMember, (CHAT, CHAT))
                        assert member.score == final_score and member.answered_count == 0
                        answers = (await session.scalars(select(PollAnswer).where(
                            PollAnswer.game_id == second['game_id'], PollAnswer.user_id == CHAT))).all()
                        assert len(answers) == 1 and answers[0].round_id == second['question']['round_id']
                        commands = (await session.scalars(select(GameCommand).where(
                            GameCommand.game_id == second['game_id'], GameCommand.kind == 'photo.answer'))).all()
                        assert len(commands) == 1 and commands[0].id.startswith('tg:photo:answer:')
                    await send(second_answer.lower())
                    async with db.transaction() as session:
                        assert (await session.get(User, CHAT)).global_score == final_score
                assert not any(event['event'] in {'handler_error', 'blocked_outbound'}
                               for event in scope.events), scope.events
            finally:
                await photos.shutdown()
                if app.running:
                    await app.stop()
                await dm.flush_postgres_writes()
                await app.shutdown()

    asyncio.run(run())
