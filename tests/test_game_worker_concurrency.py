"""Real PostgreSQL acceptance for independent deadline workers."""

import asyncio
from datetime import datetime, timedelta, timezone
import multiprocessing

import pytest
from sqlalchemy import func, select

from application.classic import ClassicApplicationService
from application.game_deadlines import GameDeadlineProcessor
from application.mafia import MafiaApplicationService
from application.photo import PhotoApplicationService
from tests.local_database import isolated_database
from tests.test_postgres_members import CHAT, USER, pg_env
from storage.models import Account, Game, GameEvent, Room
from storage.repositories import OperationalRepository


def _process_worker_once(database_url, schema, barrier, results):
    """Run one real worker pass in a separate OS process and isolated schema."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from application.game_deadlines import GameDeadlineProcessor
    from storage.database import Database, DatabaseSettings

    async def run():
        database = Database(DatabaseSettings(url=database_url))
        await database.engine.dispose()
        engine = create_async_engine(
            database_url,
            connect_args={'server_settings': {'search_path': f'"{schema}",public'}},
        )
        database.engine = engine
        database.session_factory = async_sessionmaker(
            engine, expire_on_commit=False, autoflush=False,
        )

        class SynchronizedWorker(GameDeadlineProcessor):
            async def _apply_one(self, mode, chat_id, operation):
                await asyncio.to_thread(barrier.wait, 10)
                return await super()._apply_one(mode, chat_id, operation)

        try:
            await database.check_connection()
            return await SynchronizedWorker(database).run_once()
        finally:
            await database.dispose()

    try:
        results.put(('ok', asyncio.run(run())))
    except BaseException as error:
        results.put(('error', f'{type(error).__name__}: {error}'))


def _process_worker_once_without_barrier(database_url, schema, results):
    """A fresh process must observe durable state without replaying it."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from application.game_deadlines import GameDeadlineProcessor
    from storage.database import Database, DatabaseSettings

    async def run():
        database = Database(DatabaseSettings(url=database_url))
        await database.engine.dispose()
        engine = create_async_engine(
            database_url,
            connect_args={'server_settings': {'search_path': f'"{schema}",public'}},
        )
        database.engine = engine
        database.session_factory = async_sessionmaker(
            engine, expire_on_commit=False, autoflush=False,
        )
        try:
            await database.check_connection()
            return await GameDeadlineProcessor(database).run_once()
        finally:
            await database.dispose()

    try:
        results.put(('ok', asyncio.run(run())))
    except BaseException as error:
        results.put(('error', f'{type(error).__name__}: {error}'))


def _finish_process(process, results):
    process.join(20)
    if process.is_alive():
        process.terminate()
        process.join(5)
        raise AssertionError('Deadline worker process did not exit in time')
    assert process.exitcode == 0
    result = results.get(timeout=5)
    assert result[0] == 'ok', result[1]
    return result[1]


async def race_workers(database, *, now):
    """Release two processors only after both have snapshotted due candidates."""
    candidates_ready = asyncio.Event()
    arrivals = 0

    class SynchronizedWorker(GameDeadlineProcessor):
        async def _apply_one(self, mode, chat_id, operation):
            nonlocal arrivals
            arrivals += 1
            if arrivals == 2:
                candidates_ready.set()
            await asyncio.wait_for(candidates_ready.wait(), timeout=5)
            return await super()._apply_one(mode, chat_id, operation)

    return await asyncio.wait_for(asyncio.gather(
        SynchronizedWorker(database).run_once(now=now),
        SynchronizedWorker(database).run_once(now=now),
    ), timeout=15)


def test_two_deadline_workers_apply_one_transition_and_restart_is_safe(pg_env):
    async def run():
        async with isolated_database(pg_env) as (database, _):
            base = datetime.now(timezone.utc) - timedelta(minutes=3)
            async with database.transaction() as session:
                started = await ClassicApplicationService(database, session).start(
                    chat_id=CHAT,
                    user_id=USER,
                    display_name="Deadline worker",
                    questions=[{
                        "question": "Worker test",
                        "options": ["Да", "Нет"],
                        "correct_option_text": "Да",
                    }],
                    open_seconds=1,
                    now=base,
                )
                game_id = started["game_id"]

            due_time = base + timedelta(seconds=2)
            results = await race_workers(database, now=due_time)

            async with database.transaction() as session:
                game = await session.get(Game, game_id)
                deadline_events = await session.scalar(select(func.count()).select_from(GameEvent).where(
                    GameEvent.game_id == game_id,
                    GameEvent.kind == "classic_deadline_advanced",
                ))
                assert game.status == "finished"
                assert game.state["finish_reason"] == "completed"
                assert deadline_events == 1

            # A fresh, stateless worker (the process-restart case) reads the
            # durable terminal state and cannot replay the finished transition.
            restarted = await GameDeadlineProcessor(database).run_once(now=due_time + timedelta(minutes=1))
            assert restarted == {"mafia": 0, "classic": 0, "photo": 0}
            assert sum(result["classic"] for result in results) == 1

    asyncio.run(run())


def test_independent_worker_processes_apply_one_deadline_and_restart(pg_env):
    """The PostgreSQL row lock, not Python process memory, owns the transition."""
    async def run():
        async with isolated_database(pg_env) as (database, schema):
            base = datetime.now(timezone.utc) - timedelta(minutes=3)
            async with database.transaction() as session:
                started = await ClassicApplicationService(database, session).start(
                    chat_id=CHAT,
                    user_id=USER,
                    display_name='Process deadline worker',
                    questions=[{
                        'question': 'Process restart test',
                        'options': ['Да', 'Нет'],
                        'correct_option_text': 'Да',
                    }],
                    open_seconds=1,
                    now=base,
                )
                game_id = started['game_id']

            context = multiprocessing.get_context('spawn')
            barrier = context.Barrier(2)
            results = context.Queue()
            workers = [context.Process(
                target=_process_worker_once,
                args=(pg_env, schema, barrier, results),
            ) for _ in range(2)]
            for worker in workers:
                worker.start()
            worker_results = [_finish_process(worker, results) for worker in workers]

            async with database.transaction() as session:
                game = await session.get(Game, game_id)
                events = await session.scalar(select(func.count()).select_from(GameEvent).where(
                    GameEvent.game_id == game_id,
                    GameEvent.kind == 'classic_deadline_advanced',
                ))
                assert game.status == 'finished'
                assert events == 1

            restarted_result = await asyncio.to_thread(
                _run_fresh_process_worker, pg_env, schema, context,
            )
            assert sum(result['classic'] for result in worker_results) == 1
            assert restarted_result == {'mafia': 0, 'classic': 0, 'photo': 0}

    asyncio.run(run())


def _run_fresh_process_worker(database_url, schema, context):
    results = context.Queue()
    process = context.Process(
        target=_process_worker_once_without_barrier,
        args=(database_url, schema, results),
    )
    process.start()
    result = _finish_process(process, results)
    results.close()
    results.join_thread()
    return result


def test_two_deadline_workers_apply_one_photo_timeout(pg_env):
    async def run():
        async with isolated_database(pg_env) as (database, _):
            base = datetime.now(timezone.utc) - timedelta(seconds=10)
            async with database.transaction() as session:
                started = await PhotoApplicationService(database, session).start(
                    chat_id=CHAT, user_id=USER, display_name="Photo worker",
                    question_count=1, open_seconds=5, hints_enabled=False,
                    questions=[{
                        "display_answer": "Сова",
                        "media": {"media_key": "owl", "storage_name": "owl"},
                    }],
                    now=base,
                )
                game_id = started["game_id"]

            due_time = base + timedelta(seconds=6)
            results = await race_workers(database, now=due_time)
            async with database.transaction() as session:
                game = await session.get(Game, game_id)
                timeouts = await session.scalar(select(func.count()).select_from(GameEvent).where(
                    GameEvent.game_id == game_id, GameEvent.kind == "photo_timed_out",
                ))
                assert game.status == "finished"
                assert game.state["finish_reason"] == "completed"
                assert timeouts == 1
            assert sum(result["photo"] for result in results) == 1
            assert await GameDeadlineProcessor(database).run_once(now=due_time + timedelta(minutes=1)) == {
                "mafia": 0, "classic": 0, "photo": 0,
            }

    asyncio.run(run())


def test_two_deadline_workers_apply_one_mafia_phase_transition(pg_env):
    async def run():
        chat_id = -880000000045
        player_ids = range(900000000021, 900000000025)
        async with isolated_database(pg_env) as (database, _):
            async with database.transaction() as session:
                repository = OperationalRepository(session)
                await repository.ensure_chat({"id": chat_id, "type": "supergroup", "title": "Worker test"})
                for user_id in player_ids:
                    await repository.ensure_user({"id": user_id, "display_name": f"Player {user_id}"})
                    await repository.ensure_member({"chat_id": chat_id, "user_id": user_id})
            for user_id in player_ids:
                async with database.transaction() as session:
                    await MafiaApplicationService(session).join(
                        chat_id=chat_id, user_id=user_id, name=f"Player {user_id}",
                    )
            for user_id in player_ids:
                async with database.transaction() as session:
                    service = MafiaApplicationService(session)
                    current = await service.lobby(chat_id=chat_id, viewer_id=user_id)
                    await service.ready(
                        chat_id=chat_id, user_id=user_id, ready=True,
                        expected_revision=current["revision"],
                    )
            async with database.transaction() as session:
                service = MafiaApplicationService(session)
                current = await service.lobby(chat_id=chat_id, viewer_id=next(iter(player_ids)))
                started = await service.start(
                    chat_id=chat_id, user_id=next(iter(player_ids)),
                    expected_revision=current["revision"],
                )
                game_id = (await service.games.current(chat_id=chat_id, mode="mafia")).id

            due_time = datetime.fromtimestamp(started["ends_at"] + 1, tz=timezone.utc)
            results = await race_workers(database, now=due_time)
            async with database.transaction() as session:
                game = await session.get(Game, game_id)
                transitions = await session.scalar(select(func.count()).select_from(GameEvent).where(
                    GameEvent.game_id == game_id, GameEvent.kind == "deadline_advanced",
                ))
                assert game.phase == "day"
                assert game.state["status"] == "day"
                assert transitions == 1
            assert sum(result["mafia"] for result in results) == 1
            assert await GameDeadlineProcessor(database).run_once(now=due_time + timedelta(minutes=1)) == {
                "mafia": 0, "classic": 0, "photo": 0,
            }

    asyncio.run(run())


def test_two_deadline_workers_apply_one_standalone_mafia_phase_transition(pg_env):
    async def run():
        from uuid import uuid4

        from storage.games import GameRepository

        room_id = str(uuid4())
        accounts = [uuid4() for _ in range(4)]
        actor_ids = [str(value) for value in accounts]
        deadline = datetime.now(timezone.utc) - timedelta(seconds=5)
        state = {
            'mode': 'mafia_lobby', 'scope': 'standalone', 'room_id': room_id,
            'host_account_id': actor_ids[0], 'status': 'night',
            'revision': 1, 'phase_revision': 1, 'round': 1,
            'players': [{'account_id': actor_id, 'name': f'Player {index}', 'ready': True}
                        for index, actor_id in enumerate(actor_ids, 1)],
            'assignments': {actor_id: 'mafia' if index == 0 else 'citizen'
                            for index, actor_id in enumerate(actor_ids)},
            'alive': actor_ids, 'night_actions': {}, 'votes': {},
            'investigations': {}, 'history': [], 'winner': None,
            'phase_deadline': int(deadline.timestamp()),
        }
        async with isolated_database(pg_env) as (database, _):
            async with database.transaction() as session:
                session.add_all([
                    Account(id=account_id, display_name=f'Player {index}')
                    for index, account_id in enumerate(accounts, 1)
                ])
                session.add(Room(
                    id=room_id, kind='standalone', title='Worker race',
                    owner_account_id=accounts[0], state={},
                ))
            async with database.transaction() as session:
                game = await GameRepository(session).create_room_current(
                    room_id=room_id, mode='mafia', state=state,
                )
                game_id = game.id

            results = await race_workers(database, now=deadline)
            async with database.transaction() as session:
                game = await session.get(Game, game_id)
                transitions = await session.scalar(select(func.count()).select_from(GameEvent).where(
                    GameEvent.game_id == game_id, GameEvent.kind == 'deadline_advanced',
                ))
                assert game.chat_id is None
                assert game.phase == 'day' and game.state['status'] == 'day'
                assert transitions == 1
            assert sum(result['mafia'] for result in results) == 1
            assert await GameDeadlineProcessor(database).run_once(now=deadline + timedelta(minutes=1)) == {
                'mafia': 0, 'classic': 0, 'photo': 0,
            }

    asyncio.run(run())
