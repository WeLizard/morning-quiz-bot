import asyncio
import base64
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal
import json

from fastapi import FastAPI
import httpx
import pytest
from sqlalchemy import select

from storage.admin_profiles import AdminProfiles, decode_cursor, encode_cursor
from storage.members import MemberService
from storage.models import Chat, ChatMember, DailySchedule, PollAnswer, QuizSession
from storage.repositories import OperationalRepository
from storage.settings import SettingsConflict, SettingsService
from tests.test_admin_auth import TOKEN, login
from tests.test_postgres_members import CHAT, OTHER_CHAT, USER, pg_env, scenario
from web.admin_auth import AdminAuth, install_admin_auth
from web.postgres_admin import install_postgres_admin


async def seed(db):
    async with db.transaction() as session:
        repo = OperationalRepository(session)
        await repo.ensure_chat({'id': CHAT, 'title': 'Чат <script>не HTML</script>', 'settings': {'private_marker': 'must-not-export'}})
        await repo.ensure_chat({'id': OTHER_CHAT, 'title': 'Другой чат'})
        await repo.ensure_user({'id': USER, 'display_name': 'Игрок <img src=x>', 'global_score': Decimal('12.345'), 'total_answered': 7})
        await repo.ensure_member({'chat_id': CHAT, 'user_id': USER, 'score': Decimal('10.345'), 'answered_count': 5,
            'correct_answers_count': 8, 'consecutive_correct': 2, 'max_consecutive_correct': 4,
            'milestone_codes': ['old-award'], 'streak_achievement_codes': ['streak-4'],
            'answered_poll_ids': ['legacy-poll-without-date']})
        await repo.ensure_member({'chat_id': OTHER_CHAT, 'user_id': USER, 'score': Decimal('2'), 'answered_count': 2})
        session.add(QuizSession(id=f'profile-test:{CHAT}', chat_id=CHAT, kind='classic', status='active',
            state={'future_correct_answer': 'must-not-export'}))
        for index in range(55):
            session.add(PollAnswer(poll_id=f'profile-{index:03}', user_id=USER, chat_id=CHAT,
                points_delta=Decimal('0.125'), is_correct=index % 2 == 0,
                answered_at=datetime(2026, 1, 1, tzinfo=timezone.utc), payload={'quiz_type': 'classic'}))
        session.add(PollAnswer(poll_id='other-chat-answer', user_id=USER, chat_id=OTHER_CHAT,
            points_delta=Decimal('1.5'), payload={'quiz_type': 'photo'}))


def test_profile_precision_scope_history_paging_and_no_fabricated_events(pg_env):
    async def run():
        async with scenario(pg_env) as db:
            await seed(db)
            service = AdminProfiles(db)
            user = await service.read('users', USER)
            assert user['stats']['score'] == '12.345'
            assert user['stats']['classic_answers'] == 7
            assert user['stats']['correct_answers_including_photo'] == 8
            assert user['memberships']['total'] == 2
            assert user['memberships']['items'][0]['milestone_codes'] == ['old-award']
            chat = await service.read('chats', CHAT)
            assert chat['stats']['score'] == '10.345'
            assert chat['stats']['memberships'] == 1
            assert len(chat['history']['items']) == 50 and chat['history']['has_more']
            second = await service.read('chats', CHAT, history_before=chat['history']['next_cursor'])
            assert len(second['history']['items']) == 5 and not second['history']['has_more']
            events = chat['history']['items'] + second['history']['items']
            assert len({item['poll_id'] for item in events}) == 55
            assert all(item['chat_id'] == str(CHAT) for item in events)
            assert all(item['points_delta'] == '0.125' for item in events)
            assert 'legacy-poll-without-date' not in json.dumps(events)
            assert chat['active_sessions'][0]['kind'] == 'classic'
            assert 'must-not-export' not in json.dumps(chat)
            # Manual score changes are visible in totals, not fabricated as poll events.
            await MemberService(db).set_score(CHAT, USER, Decimal('17.001'))
            fresh = await service.read('users', USER)
            assert fresh['stats']['score'] == '19.001'
            assert fresh['history']['items'] == user['history']['items']
            async with db.transaction() as session:
                member = await session.get(ChatMember, (CHAT, USER))
                assert member.answered_poll_ids == ['legacy-poll-without-date']
    asyncio.run(run())


def test_membership_page_has_exact_totals_and_separate_rows(pg_env):
    async def run():
        async with scenario(pg_env) as db:
            await seed(db)
            page = await AdminProfiles(db).read('users', USER, members_offset=1)
            assert page['memberships']['total'] == 2
            assert len(page['memberships']['items']) == 1
            assert page['memberships']['items'][0]['chat_id'] == str(OTHER_CHAT)
            empty = await AdminProfiles(db).read('users', USER, members_offset=10)
            assert empty['memberships']['items'] == [] and empty['stats']['score'] == '12.345'
    asyncio.run(run())


def test_profile_does_not_mix_score_versions_during_concurrent_edit(pg_env):
    async def run():
        async with scenario(pg_env) as db:
            await seed(db)
            class InterleavedDatabase:
                @asynccontextmanager
                async def transaction(self):
                    async with db.transaction() as session:
                        class Proxy:
                            def __getattr__(self, name):
                                return getattr(session, name)

                            async def execute(self, statement, *args, **kwargs):
                                result = await session.execute(statement, *args, **kwargs)
                                if 'sum(chat_members.score)' in str(statement):
                                    await MemberService(db).set_score(CHAT, USER, Decimal('20'))
                                return result
                        yield Proxy()
            snapshot = await AdminProfiles(InterleavedDatabase()).read('users', USER)
            assert snapshot['stats']['score'] == '12.345'
            assert snapshot['memberships']['items'][0]['score'] == '10.345'
            fresh = await AdminProfiles(db).read('users', USER)
            assert fresh['stats']['score'] == '22.000'
            assert fresh['memberships']['items'][0]['score'] == '20.000'
    asyncio.run(run())


@pytest.mark.parametrize('cursor', ['!', 'x' * 2049, base64.urlsafe_b64encode(b'{}').decode(),
    base64.urlsafe_b64encode(b'["2026-01-01", "poll", "1"]').decode(),
    base64.urlsafe_b64encode(b'["2026-01-01T00:00:00+00:00", "poll", "9999999999999999999999"]').decode()])
def test_invalid_history_cursors(cursor):
    with pytest.raises(ValueError, match='курсор'):
        decode_cursor(cursor)


def test_cursor_supports_full_length_unicode_poll_ids():
    event = PollAnswer(answered_at=datetime(2026, 1, 1, tzinfo=timezone.utc), poll_id='🦉' * 255, user_id=USER)
    token = encode_cursor(event)
    assert len(token) <= 2048
    assert decode_cursor(token) == (event.answered_at, event.poll_id, USER)


def test_chat_rename_serializes_against_settings_and_keeps_schedule_rows(pg_env):
    async def run():
        async with scenario(pg_env) as db:
            await seed(db)
            service = SettingsService(db)
            initial = await service.patch_paths(CHAT, [(('daily_quiz',), {'enabled': True, 'times_msk': [{'hour': 9, 'minute': 0}], 'timezone': 'Europe/Moscow'})])
            async with db.transaction() as session:
                schedule = await session.scalar(select(DailySchedule).where(DailySchedule.chat_id == CHAT))
                old = schedule.id, schedule.config, schedule.updated_at
            attempts = await asyncio.gather(
                service.rename_chat(CHAT, 'Новое название', expected_revision=initial.revision),
                service.patch_paths(CHAT, [(('auto_delete_bot_messages',), False)], expected_revision=initial.revision),
                return_exceptions=True)
            assert sum(isinstance(result, SettingsConflict) for result in attempts) == 1
            fresh = await service.get(CHAT)
            renamed = await service.rename_chat(CHAT, 'Итоговое название', expected_revision=fresh.revision)
            async with db.transaction() as session:
                chat = await session.get(Chat, CHAT)
                schedule = await session.scalar(select(DailySchedule).where(DailySchedule.chat_id == CHAT))
                assert chat.title == chat.settings['title'] == 'Итоговое название'
                assert chat.settings['private_marker'] == 'must-not-export'
                assert schedule.id == old[0] and schedule.config == old[1]
                # Updated_at might change only if the concurrent general settings patch won.
                schedule_time = schedule.updated_at
            again = await service.rename_chat(CHAT, 'Итоговое название', expected_revision=renamed.revision)
            assert again.revision == renamed.revision
            async with db.transaction() as session:
                assert (await session.scalar(select(DailySchedule).where(DailySchedule.chat_id == CHAT))).updated_at == schedule_time
            with pytest.raises(LookupError):
                await service.rename_chat(-99999999, 'Не создавать', expected_revision=0)
    asyncio.run(run())


def test_profiles_exports_title_api_auth_validation_and_no_legacy_mutations(pg_env):
    async def run():
        async with scenario(pg_env) as db:
            await seed(db)
            app = FastAPI()
            install_postgres_admin(app)
            install_admin_auth(app, auth=AdminAuth(TOKEN))
            async with app.router.lifespan_context(app):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://127.0.0.1') as client:
                    path = f'/api/chats/{CHAT}/profile'
                    assert (await client.get(path + '?download=true')).status_code == 401
                    csrf = await login(client)
                    result = await client.get(path)
                    assert result.status_code == 200
                    revision = result.json()['chat']['settings_revision']
                    exported = await client.get(path + '?download=true')
                    assert exported.headers['cache-control'] == 'no-store'
                    assert exported.headers['content-disposition'].startswith('attachment;')
                    assert exported.json()['history']['has_more']
                    assert 'must-not-export' not in exported.text
                    assert (await client.get(f'/api/users/{USER}/profile')).status_code == 200
                    assert (await client.get('/api/users/99999999/profile')).status_code == 404
                    assert (await client.get('/api/users/99999999999999999999/profile')).status_code == 422
                    assert (await client.get(path + '?history_before=bad')).status_code == 422
                    assert (await client.get(path + '?members_offset=-1')).status_code == 422
                    title_path = f'/api/chats/{CHAT}/title?expected_revision={revision}'
                    assert (await client.put(title_path, json={'title': 'Новое'})).status_code == 403
                    client.headers['X-CSRF-Token'] = csrf
                    assert (await client.put(f'/api/chats/{CHAT}/title', json={'title': 'Новое'})).status_code == 428
                    assert (await client.put(title_path, json={'title': '  '})).status_code == 422
                    assert (await client.put(title_path, json={'title': 'name\x00'})).status_code == 422
                    assert (await client.put(title_path, json={'title': 'Новое', 'extra': True})).status_code == 422
                    assert (await client.put(title_path, json={'title': 'Новое'})).status_code == 200
                    assert (await client.put(title_path, json={'title': 'Устаревшее'})).status_code == 409
                    assert (await client.post(f'/api/users/{USER}/ban')).status_code == 501
                    assert (await client.post(f'/api/chats/{CHAT}/reset-stats')).status_code == 501
                    assert (await client.delete(f'/api/users/{USER}')).status_code == 501
    asyncio.run(run())
