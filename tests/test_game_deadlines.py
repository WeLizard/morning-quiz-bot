import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from application import game_deadlines
from scripts import run_game_worker


class _Database:
    def __init__(self):
        self.transactions = 0

    @asynccontextmanager
    async def transaction(self):
        self.transactions += 1
        yield object()


def test_deadline_processor_isolates_failures_and_runs_each_mode(monkeypatch, caplog):
    now = datetime(2026, 10, 8, tzinfo=timezone.utc)
    database = _Database()
    calls = []

    class Mafia:
        def __init__(self, session):
            self.session = session

        async def due_game_ids(self, *, now):
            assert now is not None
            return ['game-2', 'game-1', 'game-2']

        async def advance_due_game(self, *, game_id, now):
            calls.append(('mafia', game_id, now))
            if game_id == 'game-2':
                raise RuntimeError('isolated candidate failure')
            return {'status': 'day'} if game_id == 'game-1' else None

    class Classic:
        def __init__(self, database, session):
            self.session = session

        async def due(self, *, now):
            return [(-3, 'close', 'r1', 2), (-3, 'advance', 'r1', 3)]

        async def settle_due(self, *, chat_id, now):
            calls.append(('classic', chat_id, now))
            return {'status': 'finished'}

    class Photo:
        def __init__(self, database, session):
            self.session = session

        async def due(self, *, now):
            return [-4]

        async def settle_due(self, *, chat_id, now):
            calls.append(('photo', chat_id, now))
            return None

    monkeypatch.setattr(game_deadlines, 'MafiaApplicationService', Mafia)
    monkeypatch.setattr(game_deadlines, 'ClassicApplicationService', Classic)
    monkeypatch.setattr(game_deadlines, 'PhotoApplicationService', Photo)

    result = asyncio.run(game_deadlines.GameDeadlineProcessor(database).run_once(now=now))

    assert result == {'mafia': 1, 'classic': 1, 'photo': 0}
    assert calls == [
        ('mafia', 'game-1', now), ('mafia', 'game-2', now),
        ('classic', -3, now), ('photo', -4, now),
    ]
    assert database.transactions == 5  # one candidate snapshot + one per target
    assert 'mode=mafia candidate=game-2' in caplog.text


def test_worker_interval_has_a_bounded_polling_range(monkeypatch):
    monkeypatch.setenv('GAME_WORKER_INTERVAL_SECONDS', '0.5')
    assert run_game_worker._interval() == 0.5
    for invalid in ('0', '31', 'not-a-number'):
        monkeypatch.setenv('GAME_WORKER_INTERVAL_SECONDS', invalid)
        try:
            run_game_worker._interval()
        except SystemExit as error:
            assert 'between 0.25 and 30' in str(error)
        else:
            raise AssertionError(f'Invalid worker interval accepted: {invalid}')
