"""Photo adapter authorization: Telegram verification is required on every surface."""
import asyncio
from unittest.mock import AsyncMock

from sqlalchemy import delete

from storage.models import ChatMember
from tests.test_mini_app import CHAT, USER, environment, login
from tests.test_postgres_members import pg_env


def test_group_photo_new_verified_participant_needs_no_historical_chat_member(pg_env, monkeypatch):
    from application.photo import PhotoApplicationService

    current = AsyncMock(return_value={'game_id': 'photo', 'answer_policy': 'group_private_deadline',
                                     'question': {'round_id': 'round', 'answered': False}})
    monkeypatch.setattr(PhotoApplicationService, 'current', current)

    async def run():
        async with environment(pg_env, runtime_enabled=True) as env:
            headers = await login(env)
            async with env.db.transaction() as session:
                await session.execute(delete(ChatMember).where(
                    ChatMember.chat_id == CHAT, ChatMember.user_id == USER))
            response = await env.client.get(f'/api/mini/photo/chats/{CHAT}/current', headers=headers)
            assert response.status_code == 200, response.text
            assert response.json()['answer_policy'] == 'group_private_deadline'
            env.verifier.allowed.assert_awaited_once_with(CHAT, USER)
            assert current.await_args.kwargs['user_id'] == USER

    asyncio.run(run())


def test_group_photo_rechecks_telegram_membership_for_read_sync_answer_and_media(pg_env, monkeypatch):
    from application.photo import PhotoApplicationService

    current = AsyncMock(return_value={'game_id': 'photo'})
    monkeypatch.setattr(PhotoApplicationService, 'current', current)

    async def run():
        async with environment(pg_env, membership=False, runtime_enabled=True) as env:
            headers = {**await login(env), 'Origin': env.settings.origin, 'X-Mini-CSRF': '1'}
            base = f'/api/mini/photo/chats/{CHAT}'
            calls = [
                ('GET', '/current', None), ('POST', '/sync', None),
                ('POST', '/answer', {'round_id': 'round', 'answer': 'Сова', 'command_id': 'private-command'}),
                ('GET', '/current/image?round_id=round', None),
            ]
            for method, path, body in calls:
                response = await env.client.request(method, base + path, headers=headers, **({'json': body} if body else {}))
                assert response.status_code == 403, (path, response.text)
            assert env.verifier.allowed.await_count == 4
            current.assert_not_awaited()

    asyncio.run(run())
