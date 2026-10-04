import asyncio
from contextlib import asynccontextmanager
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from fastapi import FastAPI
import httpx
import pytest
from sqlalchemy import delete, func, select
from telegram import Update, User as TelegramUser, PollAnswer as TelegramPollAnswer
from telegram.ext import ApplicationHandlerStop

from tests.test_postgres_members import CHAT, OTHER_CHAT, USER, pg_env, scenario
from handlers.moderation import moderation_handler
from storage.admin_actions import AdminActions, AdminConflict, BotAccessBlocked
from storage.members import MemberService
from storage.models import AdminAction, Chat, ChatMember, Game, PollAnswer, QuizSession, User, MessageCleanupItem
from storage.photos import PhotoSessions, PhotoSessionConflict
from storage.repositories import OperationalRepository
from storage.schedule_source import ScheduleSource
from tests.test_admin_auth import TOKEN, login
from tests.test_classic_recovery import game
from tests.test_postgres_photos import payload, manager as photo_manager, context as photo_context
from modules.photo_quiz_manager import PhotoQuizState
from web.admin_auth import AdminAuth, install_admin_auth
from web.postgres_admin import install_postgres_admin


@asynccontextmanager
async def setup(url):
    async with scenario(url) as db:
        try:
            async with db.transaction() as session:
                repo = OperationalRepository(session)
                await repo.ensure_chat({'id': CHAT, 'title': 'Тест сброса'})
                await repo.ensure_chat({'id': OTHER_CHAT, 'title': 'Не менять'})
                await repo.ensure_user({'id': USER, 'display_name': 'Тест', 'global_score': Decimal('12.345'), 'total_answered': 7})
                await repo.ensure_member({'chat_id': CHAT, 'user_id': USER, 'score': Decimal('10.345'), 'answered_count': 5,
                    'correct_answers_count': 6, 'consecutive_correct': 2, 'max_consecutive_correct': 4,
                    'answered_poll_ids': ['old', 'legacy-only'], 'daily_answered_poll_ids': ['old'],
                    'milestone_codes': ['award-1'], 'streak_achievement_codes': ['streak-4']})
                await repo.ensure_member({'chat_id': OTHER_CHAT, 'user_id': USER, 'score': Decimal('2'), 'answered_count': 2})
                session.add(PollAnswer(poll_id='old', user_id=USER, chat_id=CHAT, points_delta=Decimal('1')))
            yield db, AdminActions(db)
        finally:
            async with db.transaction() as session:
                await session.execute(delete(AdminAction).where(AdminAction.target_id.in_([CHAT, OTHER_CHAT, USER])))


async def award(db, answer_id='new', transition=None, **kwargs):
    async def increment(profile):
        profile['score'] += 1
    return await MemberService(db).apply_answer(chat_id=CHAT, user_id=USER, display_name='Тест',
        answer_id=answer_id, is_correct=True, transition=transition or increment, **kwargs)


async def block(service, scope='users', target=USER, blocked=True, revision=0, **kwargs):
    return await service.block(scope, target, blocked=blocked, reason='Тестовая операция',
                               expected_revision=revision, action_id=str(uuid4()), **kwargs)


@pytest.mark.parametrize('scope,target', [('users', USER), ('chats', CHAT)])
def test_archive_requires_block_and_preserves_progress_and_dedup(pg_env, scope, target):
    async def run():
        async with setup(pg_env) as (db, service):
            params = dict(archived=True, expected_revision=0, confirmation=str(target), action_id=str(uuid4()))
            with pytest.raises(AdminConflict, match='заблокируйте'):
                await service.archive(scope, target, **params)
            await block(service, scope=scope, target=target)
            params['expected_revision'] = 1
            result = await service.archive(scope, target, **params)
            assert result['after']['archived']
            assert await service.archive(scope, target, **params) == result
            assert not await service.allowed(CHAT, USER)
            with pytest.raises(AdminConflict, match='восстановите'):
                await block(service, scope=scope, target=target, blocked=False, revision=2)
            async with db.transaction() as session:
                assert (await session.get(ChatMember, (CHAT, USER))).score == Decimal('10.345')
                assert await session.get(PollAnswer, ('old', USER)) is not None
                assert (await session.get(ChatMember, (OTHER_CHAT, USER))).score == 2
            await service.archive(scope, target, archived=False, expected_revision=2,
                                  confirmation=str(target), action_id=str(uuid4()))
            assert not await service.allowed(CHAT, USER)
            await block(service, scope=scope, target=target, blocked=False, revision=3)
            assert await service.allowed(CHAT, USER)
            assert not (await award(db, 'old')).applied
            assert (await award(db)).applied
    asyncio.run(run())


@pytest.mark.parametrize('scope,target,score,answers', [('users', USER, '0', 0), ('chats', CHAT, '2', 2)])
def test_reset_keeps_ledger_dedup_awards_records_and_scopes_totals(pg_env, scope, target, score, answers):
    async def run():
        async with setup(pg_env) as (db, service):
            preview = await service.preview_reset(scope, target)
            params = dict(expected_version=preview['version'], confirmation=str(target), action_id=str(uuid4()))
            result = await service.reset(scope, target, **params)
            assert next(m for m in result['before']['members'] if m['chat_id'] == str(CHAT))['score'] == '10.345'
            assert result['after']['members'][0]['score'] == '0.000'
            assert await service.reset(scope, target, **params) == result
            async with db.transaction() as session:
                member = await session.get(ChatMember, (CHAT, USER))
                assert member.score == 0 and member.answered_count == 0 and member.consecutive_correct == 0
                assert member.answered_poll_ids == ['old', 'legacy-only'] and member.daily_answered_poll_ids == ['old']
                assert member.milestone_codes == ['award-1'] and member.streak_achievement_codes == ['streak-4']
                assert member.max_consecutive_correct == 4
                assert await session.get(PollAnswer, ('old', USER)) is not None
                user = await session.get(User, USER)
                assert user.global_score == Decimal(score) and user.total_answered == answers
                other = await session.get(ChatMember, (OTHER_CHAT, USER))
                assert other.score == (0 if scope == 'users' else 2)
            assert not (await award(db, 'old')).applied
            assert not (await award(db, 'legacy-only')).applied
            assert (await award(db)).applied
            # Retry after new activity must return the old receipt, not erase it.
            assert await service.reset(scope, target, **params) == result
            async with db.transaction() as session:
                assert (await session.get(ChatMember, (CHAT, USER))).score == 1
    asyncio.run(run())


def test_reset_rejects_wrong_confirmation_stale_preview_and_active_games(pg_env):
    async def run():
        async with setup(pg_env) as (db, service):
            preview = await service.preview_reset('users', USER)
            with pytest.raises(ValueError, match='ID'):
                await service.reset('users', USER, expected_version=preview['version'], confirmation='wrong', action_id=str(uuid4()))
            await award(db)
            with pytest.raises(AdminConflict, match='изменился'):
                await service.reset('users', USER, expected_version=preview['version'], confirmation=str(USER), action_id=str(uuid4()))
            await game(db)
            for scope, target in [('users', USER), ('chats', CHAT)]:
                preview = await service.preview_reset(scope, target)
                assert preview['active_sessions']
                with pytest.raises(AdminConflict, match='активной'):
                    await service.reset(scope, target, expected_version=preview['version'], confirmation=str(target), action_id=str(uuid4()))
            async with db.transaction() as session:
                assert not await session.scalar(select(func.count()).select_from(AdminAction))
    asyncio.run(run())


def test_user_ban_blocks_real_poll_updates_and_all_awards_but_not_other_group_game(pg_env):
    async def run():
        async with setup(pg_env) as (db, service):
            live, quiz = await game(db)
            await block(service)
            with pytest.raises(BotAccessBlocked):
                await award(db)
            with pytest.raises(BotAccessBlocked):
                await award(db, 'photo:fake:1', kind='photo')
            gate = moderation_handler(db)
            update = Update(1, poll_answer=TelegramPollAnswer('durable-poll', [1], user=TelegramUser(USER, 'Test', False), option_persistent_ids=['option-1']))
            with pytest.raises(ApplicationHandlerStop):
                await gate.callback(update, None)
            assert await service.session_active(f'classic:{CHAT}', quiz.session_id)
            assert not await service.allowed(user_id=USER)
            assert not await service.allowed(chat_id=USER)
            await block(service, blocked=False, revision=1)
            await gate.callback(update, None)
            assert (await award(db)).applied
    asyncio.run(run())


def test_update_gate_fails_closed_without_telegram_io():
    class Broken:
        def transaction(self):
            raise ConnectionError('offline')
    async def run():
        with pytest.raises(ApplicationHandlerStop):
            await moderation_handler(Broken()).callback(Update(2), None)
    asyncio.run(run())


def test_chat_ban_interrupts_game_queues_cleanup_and_removes_old_runtime_even_after_unban(pg_env):
    async def run():
        async with setup(pg_env) as (db, service):
            live, quiz = await game(db)
            result = await block(service, 'chats', CHAT)
            assert result['after']['interrupted_sessions'] == [f'classic:{CHAT}']
            async with db.transaction() as session:
                assert await session.get(MessageCleanupItem, (CHAT, 10))
            with pytest.raises(BotAccessBlocked):
                await award(db)
            await block(service, 'chats', CHAT, blocked=False, revision=1)
            await live._send_next_question(SimpleNamespace(), CHAT)
            live.quiz_engine.send_quiz_poll.assert_not_awaited()
            assert live.state.get_active_quiz(CHAT) is None
            assert await service.allowed(CHAT, USER)
    asyncio.run(run())


def test_user_ban_cancels_photo_without_awarding_or_resuming(pg_env, tmp_path):
    async def run():
        async with setup(pg_env) as (db, service):
            saved = await PhotoSessions(db).create(payload())
            live = photo_manager(db, tmp_path)
            photo = PhotoQuizState(CHAT, USER, [])
            live._accept_record(photo, saved)
            live.active_photo_quizzes[CHAT] = photo
            await block(service)
            with pytest.raises(PhotoSessionConflict):
                await PhotoSessions(db).complete_question(saved, correct=True, points=6)
            context = photo_context()
            await live._end_photo_quiz(CHAT, context, correct=True)
            context.bot.send_message.assert_not_awaited()
            assert CHAT not in live.active_photo_quizzes
            async with db.transaction() as session:
                assert (await session.get(User, USER)).global_score == Decimal('12.345')
            await block(service, blocked=False, revision=1)
            assert not await service.session_active(f'photo:{CHAT}', saved['session_id'])
    asyncio.run(run())


def test_ban_suspends_both_schedules_without_changing_configuration(pg_env):
    async def run():
        async with setup(pg_env) as (db, service):
            settings = {'daily_quiz': {'enabled': True, 'times_msk': [{'hour': 9, 'minute': 0}]},
                        'daily_wisdom': {'enabled': True, 'time': '12:00'}}
            async with db.transaction() as session:
                (await session.get(Chat, CHAT)).settings = settings
            source = ScheduleSource(db, SimpleNamespace(default_chat_settings={}, daily_quiz_defaults={}))
            state = (await source.read(CHAT))[CHAT]
            plans = {kind: source.plan(state, kind) for kind in ('quiz', 'wisdom')}
            assert all(p.times for p in plans.values())
            await block(service, 'chats', CHAT)
            for kind, plan in plans.items():
                assert not await source.is_current(CHAT, kind, plan.token)
            await block(service, 'chats', CHAT, blocked=False, revision=1)
            assert (await source.read(CHAT))[CHAT].values == settings
            assert all([await source.is_current(CHAT, kind, plan.token) for kind, plan in plans.items()])
    asyncio.run(run())


@pytest.mark.parametrize('operation', ['reset', 'block'])
def test_answer_racing_admin_change_is_serialized_not_lost(pg_env, operation):
    async def run():
        async with setup(pg_env) as (db, service):
            preview = await service.preview_reset('users', USER)
            locked, release = asyncio.Event(), asyncio.Event()
            async def transition(profile):
                locked.set()
                await release.wait()
                profile['score'] += 1
            task = asyncio.create_task(award(db, transition=transition))
            await asyncio.wait_for(locked.wait(), 5)
            admin = asyncio.create_task(service.reset('users', USER, expected_version=preview['version'],
                confirmation=str(USER), action_id=str(uuid4())) if operation == 'reset' else block(service))
            await asyncio.sleep(.02)
            assert not admin.done()
            release.set()
            assert (await asyncio.wait_for(task, 5)).applied
            if operation == 'reset':
                with pytest.raises(AdminConflict):
                    await asyncio.wait_for(admin, 5)
            else:
                await asyncio.wait_for(admin, 5)
                with pytest.raises(BotAccessBlocked):
                    await award(db, 'later')
            async with db.transaction() as session:
                assert (await session.get(User, USER)).global_score == Decimal('13.345')
    asyncio.run(run())


def test_admin_actions_api_requires_auth_csrf_versions_and_is_idempotent(pg_env):
    async def run():
        async with setup(pg_env) as (db, service):
            app = FastAPI()
            install_postgres_admin(app)
            install_admin_auth(app, auth=AdminAuth(TOKEN))
            async with app.router.lifespan_context(app):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://127.0.0.1') as client:
                    root = f'/api/users/{USER}'
                    assert (await client.get(root + '/reset-preview')).status_code == 401
                    csrf = await login(client)
                    state = (await client.get(root + '/moderation')).json()
                    body = dict(blocked=True, reason='<script>plain text</script>', expected_revision=state['revision'], action_id=str(uuid4()))
                    assert (await client.put(root + '/moderation', json=body)).status_code == 403
                    client.headers['X-CSRF-Token'] = csrf
                    result = await client.put(root + '/moderation', json=body)
                    assert result.status_code == 200, result.text
                    assert (await client.put(root + '/moderation', json=body)).json() == result.json()
                    changed = {**body, 'blocked': False}
                    assert (await client.put(root + '/moderation', json=changed)).status_code == 409
                    assert (await client.put(root + '/moderation', json={**body, 'action_id': str(uuid4())})).status_code == 409
                    assert (await client.put(root + '/moderation', json={**body, 'reason': '\x00'})).status_code == 422
                    receipt_path = '/api/admin-actions/' + result.json()['id']
                    export = await client.get(receipt_path)
                    assert export.headers['cache-control'] == 'no-store'
                    assert 'attachment;' in export.headers['content-disposition']
                    assert (await client.get('/api/users/99999999/moderation')).status_code == 404
                    assert (await client.get('/api/chats/9999999999999999999999/reset-preview')).status_code == 422
                    preview = (await client.get(root + '/reset-preview')).json()
                    reset_body = dict(expected_version=preview['version'], confirmation=str(USER), action_id=str(uuid4()))
                    reset = await client.post(root + '/reset-progress', json=reset_body)
                    assert reset.status_code == 200, reset.text
                    assert (await client.post(root + '/reset-progress', json=reset_body)).json() == reset.json()
                    assert (await client.post(root + '/reset-stats')).status_code == 501
    asyncio.run(run())


def test_reset_keeps_photo_dedup_and_completed_series_checkpoint(pg_env):
    async def run():
        async with setup(pg_env) as (db, service):
            photos = PhotoSessions(db)
            state = await photos.create(payload())
            finished = await photos.complete_question(state, correct=True, points=6)
            await photos.save(finished, status='completed')
            preview = await service.preview_reset('users', USER)
            await service.reset('users', USER, expected_version=preview['version'], confirmation=str(USER), action_id=str(uuid4()))
            assert not (await award(db, f"photo:{state['session_id']}:0", kind='photo')).applied
            await photos.complete_question(state, correct=True, points=6)
            async with db.transaction() as session:
                assert (await session.get(User, USER)).global_score == 0
                row = await session.scalar(select(Game).where(
                    Game.chat_id == CHAT, Game.mode == 'photo', Game.is_current.is_(True)))
                assert row.status == 'finished'
    asyncio.run(run())


def test_reset_rollback_keeps_counters_if_receipt_cannot_be_written(pg_env):
    class FailingAudit(AdminActions):
        async def _record(self, *args, **kwargs):
            raise ConnectionError('Audit unavailable')
    async def run():
        async with setup(pg_env) as (db, service):
            preview = await service.preview_reset('users', USER)
            with pytest.raises(ConnectionError):
                await FailingAudit(db).reset('users', USER, expected_version=preview['version'], confirmation=str(USER), action_id=str(uuid4()))
            assert (await service.preview_reset('users', USER)) == preview
    asyncio.run(run())


def test_new_session_waits_for_reset_commit(pg_env):
    async def run():
        async with setup(pg_env) as (db, service):
            locked, release = asyncio.Event(), asyncio.Event()
            class PausedAudit(AdminActions):
                async def _record(self, *args, **kwargs):
                    result = await super()._record(*args, **kwargs)
                    locked.set()
                    await release.wait()
                    return result
            preview = await service.preview_reset('users', USER)
            reset = asyncio.create_task(PausedAudit(db).reset('users', USER,
                expected_version=preview['version'], confirmation=str(USER), action_id=str(uuid4())))
            await asyncio.wait_for(locked.wait(), 5)
            start = asyncio.create_task(PhotoSessions(db).create(payload()))
            await asyncio.sleep(.02)
            assert not start.done()
            release.set()
            await asyncio.wait_for(reset, 5)
            state = await asyncio.wait_for(start, 5)
            assert await service.session_active(f'photo:{CHAT}', state['session_id'])
            async with db.transaction() as session:
                assert (await session.get(User, USER)).global_score == 0
    asyncio.run(run())
