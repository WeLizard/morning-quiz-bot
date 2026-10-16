"""Real PostgreSQL acceptance for independent deadline workers."""

import asyncio
from datetime import datetime, timedelta, timezone
import multiprocessing
import queue

import pytest
from sqlalchemy import func, select

from application.classic import ClassicApplicationService
from application.game_deadlines import GameDeadlineProcessor
from application.mafia import MafiaApplicationService
from application.photo import PhotoApplicationService
from application.rooms import RoomApplicationService
from tests.deadline_worker_processes import (
    HANG_GUARD_SECONDS, _process_worker_once, _process_worker_once_without_barrier,
)
from tests.local_database import isolated_database
from tests.test_postgres_members import CHAT, USER, pg_env
from storage.models import (
    Account, Chat, Game, GameCommand, GameDeadline, GameEvent,
    NotificationOutbox, Room, User,
)
from storage.repositories import OperationalRepository


def _finish_process(process, results):
    """Wait for the child's own result (event-driven), then for its clean exit."""
    try:
        result = results.get(timeout=HANG_GUARD_SECONDS)
    except queue.Empty:
        process.terminate()
        process.join(5)
        raise AssertionError('Deadline worker process reported no result') from None
    process.join(HANG_GUARD_SECONDS)
    if process.is_alive():
        process.terminate()
        process.join(5)
        raise AssertionError('Deadline worker process did not exit after reporting')
    assert process.exitcode == 0
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


def _run_fresh_process_worker(database_url, schema, context, now=None):
    results = context.Queue()
    process = context.Process(
        target=_process_worker_once_without_barrier,
        args=(database_url, schema, results, now),
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


def test_independent_processes_finish_standalone_mafia_vote_once(pg_env):
    """Two OS workers settle a service-created room once, including after restart."""
    from uuid import uuid4

    async def run():
        async with isolated_database(pg_env) as (database, schema):
            accounts = [uuid4() for _ in range(4)]
            room_id = str(uuid4())
            async with database.transaction() as session:
                session.add_all([
                    Account(id=account_id, display_name=f'Player {index}')
                    for index, account_id in enumerate(accounts, 1)
                ])
                await session.flush()
                rooms = RoomApplicationService(session)
                await rooms.create(
                    account_id=accounts[0], request_id=room_id, title='Worker vote race',
                )
                invite = await rooms.create_invite(
                    account_id=accounts[0], room_id=room_id,
                    expires_in_seconds=300, max_uses=3,
                )
                for account_id in accounts[1:]:
                    await rooms.join_by_invite(
                        account_id=account_id, invite_code=invite['invite_code'],
                    )

            async with database.transaction() as session:
                service = MafiaApplicationService(session)
                lobby = await service.create_room_lobby(
                    room_id=room_id, account_id=accounts[0], name='Player 1',
                    command_id=f'mafia-create-{room_id}',
                )
                for index, account_id in enumerate(accounts[1:], 2):
                    lobby = await service.room_join(
                        room_id=room_id, account_id=account_id,
                        name=f'Player {index}', command_id=f'mafia-join-{index}-{room_id}',
                    )
                for index, account_id in enumerate(accounts, 1):
                    lobby = await service.room_ready(
                        room_id=room_id, account_id=account_id, ready=True,
                        expected_revision=lobby['revision'],
                        command_id=f'mafia-ready-{index}-{room_id}',
                    )
                await service.room_start(
                    room_id=room_id, account_id=accounts[0],
                    expected_revision=lobby['revision'],
                    command_id=f'mafia-start-{room_id}',
                )
                game = await service.games.current_in_room(room_id=room_id, mode='mafia')
                game_id = game.id
                state = game.state
                mafia_id = next(actor_id for actor_id, role in state['assignments'].items()
                                if role == 'mafia')
                citizens = [actor_id for actor_id, role in state['assignments'].items()
                            if role == 'citizen']
                victim_id = citizens[0]
                seats = {player['account_id']: f'p{index}'
                         for index, player in enumerate(state['players'], 1)}
                action = await service.room_action(
                    room_id=room_id, account_id=mafia_id,
                    target_seat=seats[victim_id],
                    expected_revision=state['phase_revision'],
                    command_id=f'mafia-action-{room_id}',
                )
                day = await service.room_advance(
                    room_id=room_id, account_id=accounts[0],
                    expected_revision=action['lobby']['revision'],
                    command_id=f'mafia-day-{room_id}',
                )
                assert day['lobby']['status'] == 'day'
                voting = await service.room_advance(
                    room_id=room_id, account_id=accounts[0],
                    expected_revision=day['lobby']['revision'],
                    command_id=f'mafia-voting-{room_id}',
                )
                assert voting['lobby']['status'] == 'voting'
                for index, voter_id in enumerate(citizens[1:], 1):
                    await service.room_vote(
                        room_id=room_id, account_id=voter_id,
                        target_seat=seats[mafia_id],
                        expected_revision=voting['lobby']['phase_revision'],
                        command_id=f'mafia-vote-{index}-{room_id}',
                    )
                vote_deadline = datetime.fromtimestamp(
                    voting['lobby']['ends_at'] + 1, tz=timezone.utc,
                )
                game = await session.get(Game, game_id)
                voting_revision = game.revision
                voting_phase_revision = game.state['phase_revision']
                command_count = await session.scalar(select(func.count()).select_from(GameCommand).where(
                    GameCommand.game_id == game_id,
                ))
                assert command_count == 14
                assert await session.scalar(select(func.count()).select_from(GameCommand).where(
                    GameCommand.game_id == game_id, GameCommand.status != 'completed',
                )) == 0
                deadline = await session.scalar(select(GameDeadline).where(
                    GameDeadline.game_id == game_id, GameDeadline.kind == 'phase',
                ))
                assert deadline.status == 'pending' and deadline.revision == voting_revision
                assert await session.scalar(select(func.count()).select_from(Chat)) == 0
                assert await session.scalar(select(func.count()).select_from(User)) == 0
                assert await session.scalar(select(func.count()).select_from(NotificationOutbox)) == 0

            context = multiprocessing.get_context('spawn')
            barrier = context.Barrier(2)
            results = context.Queue()
            workers = [context.Process(
                target=_process_worker_once,
                args=(pg_env, schema, barrier, results, vote_deadline),
            ) for _ in range(2)]
            try:
                for worker in workers:
                    worker.start()
                worker_results = [_finish_process(worker, results) for worker in workers]
            finally:
                for worker in workers:
                    if worker.is_alive():
                        worker.terminate()
                        worker.join(5)
                results.close()
                results.join_thread()

            async with database.transaction() as session:
                game = await session.get(Game, game_id)
                transitions = await session.scalar(select(func.count()).select_from(GameEvent).where(
                    GameEvent.game_id == game_id, GameEvent.kind == 'deadline_advanced',
                ))
                vote_results = [entry for entry in game.state['history']
                                if entry['type'] == 'vote_result']
                assert game.room_id == room_id and game.chat_id is None
                assert game.status == 'finished' and game.phase == 'finished'
                assert game.state['winner'] == 'citizens'
                assert game.ended_at is not None
                assert game.revision == voting_revision + 1
                assert game.state['phase_revision'] == voting_phase_revision + 1
                assert transitions == 1
                assert len(vote_results) == 1
                assert vote_results[0]['eliminated'] == seats[mafia_id]
                revision = game.revision
                deadline = await session.scalar(select(GameDeadline).where(
                    GameDeadline.game_id == game_id, GameDeadline.kind == 'phase',
                ))
                assert deadline.status == 'completed' and deadline.completed_at is not None
                assert await session.scalar(select(func.count()).select_from(GameCommand).where(
                    GameCommand.game_id == game_id,
                )) == command_count
                assert await session.scalar(select(func.count()).select_from(NotificationOutbox)) == 0
                assert await session.scalar(select(func.count()).select_from(Chat)) == 0
                assert await session.scalar(select(func.count()).select_from(User)) == 0

            restarted = await asyncio.to_thread(
                _run_fresh_process_worker, pg_env, schema, context,
                vote_deadline + timedelta(minutes=5),
            )
            assert sum(result['mafia'] for result in worker_results) == 1
            assert restarted == {'mafia': 0, 'classic': 0, 'photo': 0}
            async with database.transaction() as session:
                game = await session.get(Game, game_id)
                assert game.chat_id is None
                assert game.status == 'finished' and game.revision == revision
                assert game.state['phase_revision'] == voting_phase_revision + 1
                assert len([entry for entry in game.state['history']
                            if entry['type'] == 'vote_result']) == 1
                assert await session.scalar(select(func.count()).select_from(GameEvent).where(
                    GameEvent.game_id == game_id, GameEvent.kind == 'deadline_advanced',
                )) == 1
                assert await session.scalar(select(func.count()).select_from(GameDeadline).where(
                    GameDeadline.game_id == game_id, GameDeadline.status == 'pending',
                )) == 0
                assert await session.scalar(select(func.count()).select_from(GameCommand).where(
                    GameCommand.game_id == game_id,
                )) == command_count
                assert await session.scalar(select(func.count()).select_from(NotificationOutbox)) == 0
                assert await session.scalar(select(func.count()).select_from(Chat)) == 0
                assert await session.scalar(select(func.count()).select_from(User)) == 0

    asyncio.run(run())
