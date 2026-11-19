"""Private group Photo persistence, privacy and races on real PostgreSQL."""
import asyncio
from uuid import uuid4
from sqlalchemy import select, func, update
import pytest
from application.room_photo import RoomPhotoApplicationService
from application.game_deadlines import GameDeadlineProcessor
from storage.models import Game, GameEvent, ScoreEvent, NotificationOutbox, Account
from tests.local_database import isolated_database
from tests.test_postgres_members import pg_env
from tests.test_room_classic import seed
from tests.test_room_photo import photo_media, catalog


def test_group_photo_private_deferred_awards_replays_and_workers(pg_env, photo_media):
    async def run():
        async with isolated_database(pg_env) as (db, _):
            room, a, b, outsider = await seed(db)
            await catalog(db, photo_media)
            async with db.transaction() as session:
                started = await RoomPhotoApplicationService(session).start(room_id=room, account_id=a,
                    command_id=str(uuid4()), question_count=2, open_seconds=60, now=100,
                    answer_policy='group_private_deadline')
            base = dict(room_id=room, game_id=started['game_id'], kind='answer', round_id=started['question']['round_id'])
            async def answer(actor, text, now=101, command=None):
                async with db.transaction() as session:
                    return await RoomPhotoApplicationService(session).command(**base, account_id=actor,
                        command_id=command or str(uuid4()), answer=text, now=now, expected_revision=1)
            wrong = await answer(a, 'Нет')
            cmd = str(uuid4())
            correct_a, correct_b = await asyncio.gather(answer(a, 'Сова', command=cmd), answer(b, 'Сова'))
            assert correct_a == await answer(a, 'Сова', command=cmd)
            assert correct_a['question']['answered'] and correct_b['question']['answered']
            assert correct_a['last_result'] is None and correct_a['score'] == '0.0'
            await answer(a, 'Сова', now=102)
            with pytest.raises(RuntimeError):
                await answer(b, 'Сова', now=160)
            with pytest.raises(RuntimeError):
                await answer(b, 'Сова', command=cmd)
            with pytest.raises(LookupError):
                await answer(outsider, 'Сова')
            async with db.transaction() as session:
                assert await session.scalar(select(func.count()).select_from(ScoreEvent)) == 0
                assert await session.scalar(select(func.count()).select_from(NotificationOutbox)) == 0
                public = (await session.scalars(select(GameEvent).where(GameEvent.game_id == started['game_id'], GameEvent.visibility == 'public'))).all()
                assert not any(e.kind in {'photo_answered','photo_attempted','photo_private_response'} for e in public)
                view = await RoomPhotoApplicationService(session).current(room_id=room, account_id=b, now=102)
                assert view['question']['attempts'] == 0
            await asyncio.gather(GameDeadlineProcessor(db).run_once(now=160), GameDeadlineProcessor(db).run_once(now=160))
            async with db.transaction() as session:
                result = await RoomPhotoApplicationService(session).current(room_id=room, account_id=a, now=160)
                assert sorted(x['points'] for x in result['last_result']['solvers']) == [5.5, 6.0]
                assert result['score'] == result['own_score'] == '5.5'
                assert result['own_correct'] == result['correct'] == 1
                assert result['last_result']['own_points'] == 5.5
                assert result['question']['ends_at'] == 220
                assert await session.scalar(select(func.count()).select_from(ScoreEvent)) == 2
                stopped = await RoomPhotoApplicationService(session).command(room_id=room, account_id=a,
                    game_id=started['game_id'], command_id=str(uuid4()), kind='stop', expected_revision=result['revision'], now=161)
                assert stopped['status'] == 'active' and stopped['stop_requested']
            await GameDeadlineProcessor(db).run_once(now=220)
            async with db.transaction() as session:
                result = await RoomPhotoApplicationService(session).current(room_id=room, account_id=b, now=220)
                assert result['status'] == 'stopped'
    asyncio.run(run())


def test_group_photo_pending_merge_max_award(pg_env, photo_media):
    async def run():
        async with isolated_database(pg_env) as (db, _):
            room, a, b, _ = await seed(db)
            await catalog(db, photo_media)
            async with db.transaction() as session:
                started = await RoomPhotoApplicationService(session).start(room_id=room, account_id=a,
                    command_id=str(uuid4()), question_count=1, open_seconds=60, now=100,
                    answer_policy='group_private_deadline')
            for actor, text in [(a,'нет'),(a,'Сова'),(b,'Сова')]:
                async with db.transaction() as session:
                    await RoomPhotoApplicationService(session).command(room_id=room, account_id=actor,
                        game_id=started['game_id'], round_id=started['question']['round_id'], kind='answer',
                        answer=text, command_id=str(uuid4()), now=101)
            async with db.transaction() as session:
                await session.execute(update(Account).where(Account.id == b).values(merged_into_id=a, archived=True))
            await GameDeadlineProcessor(db).run_once(now=160)
            async with db.transaction() as session:
                events = (await session.scalars(select(ScoreEvent))).all()
                assert len(events) == 1 and events[0].account_id == a and float(events[0].amount) == 6
                game = await session.get(Game, started['game_id'])
                assert len(game.state['last_result']['solvers']) == 1
    asyncio.run(run())


def test_group_photo_overlapping_batches_and_multihop_merge(pg_env, photo_media):
    from application.rooms import RoomApplicationService
    from storage.models import RoomMembership, User
    async def run():
        async with isolated_database(pg_env) as (db, _):
            room, a, b, c = await seed(db)
            room2 = str(uuid4())
            await catalog(db, photo_media)
            async with db.transaction() as session:
                await RoomApplicationService(session).create(account_id=a, request_id=room2, title='Вторая')
                session.add(RoomMembership(room_id=room2, account_id=b, role='member', status='active'))
                session.add_all([User(id=881001, account_id=a, display_name='A'), User(id=881002, account_id=b, display_name='B')])
            games=[]
            for room_id in (room, room2):
                async with db.transaction() as session:
                    result = await RoomPhotoApplicationService(session).start(room_id=room_id, account_id=a,
                        command_id=str(uuid4()), question_count=1, open_seconds=60, now=100,
                        answer_policy='group_private_deadline')
                    games.append(result['game_id'])
                for actor in (b,a):
                    async with db.transaction() as session:
                        await RoomPhotoApplicationService(session).command(room_id=room_id, account_id=actor,
                            game_id=result['game_id'], round_id=result['question']['round_id'], kind='answer',
                            answer='Сова', command_id=str(uuid4()), now=101)
            async def settle(game):
                async with db.transaction() as session:
                    await RoomPhotoApplicationService(session).settle_due_game(game_id=game, now=160)
            await asyncio.wait_for(asyncio.gather(*(settle(g) for g in games)), timeout=10)
            async with db.transaction() as session:
                assert await session.scalar(select(func.count()).select_from(ScoreEvent)) == 4
                assert all(float(u.global_score)==12 for u in (await session.scalars(select(User))).all())
            # A response survives two successive merges, including an intermediate tombstone.
            async with db.transaction() as session:
                result = await RoomPhotoApplicationService(session).start(room_id=room, account_id=a,
                    command_id=str(uuid4()), question_count=1, open_seconds=60, now=200,
                    answer_policy='group_private_deadline')
                await RoomPhotoApplicationService(session).command(room_id=room, account_id=b,
                    game_id=result['game_id'], round_id=result['question']['round_id'], kind='answer',
                    answer='Сова', command_id=str(uuid4()), now=201)
            async with db.transaction() as session:
                await session.execute(update(Account).where(Account.id == b).values(merged_into_id=a, archived=True))
                await session.execute(update(Account).where(Account.id == a).values(merged_into_id=c, archived=True))
            async with db.transaction() as session:
                await RoomPhotoApplicationService(session).settle_due_game(game_id=result['game_id'], now=260)
            async with db.transaction() as session:
                assert float(await session.scalar(select(ScoreEvent.amount).where(ScoreEvent.account_id == c))) == 6
    asyncio.run(run())


def test_telegram_group_uses_same_private_settlement(pg_env):
    from application.photo import PhotoApplicationService
    from storage.models import ChatMember, PollAnswer, User
    from storage.mini_app import MiniAppStore
    from types import SimpleNamespace
    async def run():
        async with isolated_database(pg_env) as (db, _):
            async with db.transaction() as session:
                started = await PhotoApplicationService(db, session).start(chat_id=-881000, user_id=881001,
                    display_name='A', question_count=1, open_seconds=60, now=100,
                    answer_policy='group_private_deadline', questions=[{'display_answer':'Сова','media':{'media_key':'owl'}}])
            async def answer(user):
                async with db.transaction() as session:
                    return await PhotoApplicationService(db, session).answer(chat_id=-881000, user_id=user,
                        display_name=str(user), round_id=started['question']['round_id'], answer='Сова',
                        command_id=str(uuid4()), now=101)
            await asyncio.gather(answer(881001), answer(881002))
            store = MiniAppStore(db, 'test-token', clock=lambda: 102)
            token = (await store.create_session(SimpleNamespace(user_id=881002, fingerprint=str(uuid4()), auth_date=100)))['access_token']
            before_history = await store.history(token)
            assert before_history['answers'] == [] and before_history['games'] == []
            async with db.transaction() as session:
                assert await session.scalar(select(func.count()).select_from(ScoreEvent)) == 0
                assert await session.scalar(select(func.count()).select_from(NotificationOutbox).where(NotificationOutbox.kind != 'photo.question')) == 0
            await asyncio.gather(GameDeadlineProcessor(db).run_once(now=160), GameDeadlineProcessor(db).run_once(now=160))
            async with db.transaction() as session:
                assert await session.scalar(select(func.count()).select_from(ScoreEvent)) == 2
                members = (await session.scalars(select(ChatMember).where(ChatMember.chat_id == -881000))).all()
                assert all(float(m.score)==6 and m.correct_answers_count == 1 and m.answered_count == 0 for m in members)
                assert all(m.first_answer_at is None and m.last_answer_at is None for m in members)
                assert all(u.first_answer_at is None and u.last_answer_at is None and u.total_answered == 0 for u in (await session.scalars(select(User))).all())
                finished_payload = await session.scalar(select(NotificationOutbox.payload).where(NotificationOutbox.kind == 'photo.finished'))
                assert finished_payload['answer_policy'] == 'group_private_deadline'
                answers = (await session.scalars(select(PollAnswer))).all()
                assert len(answers) == 2 and all(row.is_correct and float(row.points_delta) == 6 and row.game_id == started['game_id'] and row.round_id == started['question']['round_id'] for row in answers)
            history = await store.history(token)
            assert len(history['answers']) == 1 and history['answers'][0]['is_correct'] and float(history['answers'][0]['points']) == 6
            assert len(history['games']) == 1 and history['games'][0]['game_id'] == started['game_id']
            assert history['games'][0]['my_answers'] == history['games'][0]['my_correct'] == 1
    asyncio.run(run())


@pytest.mark.parametrize('answer_at', [159.999, 160.0])
def test_group_photo_answer_worker_boundary_contends_on_game_lock(pg_env, photo_media, answer_at):
    async def run():
        async with isolated_database(pg_env) as (db, _):
            room, a, _, _ = await seed(db)
            await catalog(db, photo_media)
            async with db.transaction() as session:
                started = await RoomPhotoApplicationService(session).start(room_id=room, account_id=a,
                    command_id=str(uuid4()), question_count=1, open_seconds=60, now=100,
                    answer_policy='group_private_deadline')
            answer_ready, worker_ready = asyncio.Event(), asyncio.Event()
            async def answer():
                async with db.transaction() as session:
                    answer_ready.set()
                    return await RoomPhotoApplicationService(session).command(room_id=room, account_id=a,
                        game_id=started['game_id'], round_id=started['question']['round_id'], kind='answer',
                        answer='Сова', command_id=str(uuid4()), now=answer_at)
            async def worker():
                async with db.transaction() as session:
                    worker_ready.set()
                    return await RoomPhotoApplicationService(session).settle_due_game(game_id=started['game_id'], now=160)
            async with db.transaction() as session:
                await session.execute(select(Game.id).where(Game.id == started['game_id']).with_for_update())
                answer_task, worker_task = asyncio.create_task(answer()), asyncio.create_task(worker())
                await asyncio.wait_for(asyncio.gather(answer_ready.wait(), worker_ready.wait()), timeout=5)
            answer_result, worker_result = await asyncio.wait_for(asyncio.gather(answer_task, worker_task, return_exceptions=True), timeout=10)
            assert not isinstance(worker_result, Exception)
            accepted = not isinstance(answer_result, Exception)
            if isinstance(answer_result, Exception):
                assert isinstance(answer_result, RuntimeError)
            if answer_at == 160:
                assert not accepted
            async with db.transaction() as session:
                game = await session.get(Game, started['game_id'])
                assert game.status == 'finished'
                assert len(game.state['last_result']['solvers']) == int(accepted)
                assert await session.scalar(select(func.count()).select_from(ScoreEvent)) == int(accepted)
                assert await session.scalar(select(func.count()).select_from(GameEvent).where(GameEvent.kind == 'photo_timed_out')) == 1
    asyncio.run(run())


def test_group_photo_real_account_merge_races_settlement(pg_env, photo_media):
    from application.account_merge import AccountMergeService
    from qw_farm.integration import register_models
    register_models()
    from storage.models import User
    async def run():
        async with isolated_database(pg_env) as (db, _):
            room, a, b, _ = await seed(db)
            await catalog(db, photo_media)
            async with db.transaction() as session:
                session.add(User(id=881010, account_id=b, display_name='B'))
                started = await RoomPhotoApplicationService(session).start(room_id=room, account_id=a,
                    command_id=str(uuid4()), question_count=1, open_seconds=60, now=100,
                    answer_policy='group_private_deadline')
                await RoomPhotoApplicationService(session).command(room_id=room, account_id=b,
                    game_id=started['game_id'], round_id=started['question']['round_id'], kind='answer',
                    answer='Сова', command_id=str(uuid4()), now=101)
            async def merge():
                async with db.transaction() as session:
                    service = AccountMergeService(clock=lambda: 160)
                    await service.lock_owned_rows_in(session, [a, b])
                    return await service.merge_in(session, main=await session.get(Account,a), secondary=await session.get(Account,b), via='test')
            async def worker():
                async with db.transaction() as session:
                    return await RoomPhotoApplicationService(session).settle_due_game(game_id=started['game_id'], now=160)
            results = await asyncio.wait_for(asyncio.gather(merge(), worker(), return_exceptions=True), timeout=15)
            assert not any(isinstance(result, Exception) for result in results), repr(results)
            async with db.transaction() as session:
                events = (await session.scalars(select(ScoreEvent))).all()
                assert len(events) == 1 and events[0].account_id == a and float(events[0].amount) == 6
                user = await session.get(User, 881010)
                assert user.account_id == a and float(user.global_score) == 6
                view = await RoomPhotoApplicationService(session).current(room_id=room, account_id=a, now=160)
                assert view['own_score'] == '6.0' and view['own_correct'] == 1
    asyncio.run(run())
