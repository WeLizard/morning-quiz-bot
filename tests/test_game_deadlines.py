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

    class RoomClassic:
        def __init__(self, session):
            self.session = session

        async def due_game_ids(self, *, now):
            return ['room-game-2', 'room-game-1', 'room-game-2']

        async def settle_due_game(self, *, game_id, now):
            calls.append(('room-classic', game_id, now))
            if game_id == 'room-game-2':
                raise RuntimeError('isolated room candidate failure')
            return {'status': 'finished'}

    class RoomPhoto:
        def __init__(self, session):
            self.session = session

        async def due_game_ids(self, *, now):
            return ['photo-room-2', 'photo-room-1', 'photo-room-2']

        async def settle_due_game(self, *, game_id, now):
            calls.append(('room-photo', game_id, now))
            if game_id == 'photo-room-2':
                raise RuntimeError('isolated room Photo candidate failure')
            return {'status': 'finished'}

    monkeypatch.setattr(game_deadlines, 'MafiaApplicationService', Mafia)
    monkeypatch.setattr(game_deadlines, 'ClassicApplicationService', Classic)
    monkeypatch.setattr(game_deadlines, 'PhotoApplicationService', Photo)
    monkeypatch.setattr(game_deadlines, 'RoomClassicApplicationService', RoomClassic)
    monkeypatch.setattr(game_deadlines, 'RoomPhotoApplicationService', RoomPhoto)

    result = asyncio.run(game_deadlines.GameDeadlineProcessor(database).run_once(now=now))

    assert result == {'mafia': 1, 'classic': 2, 'photo': 1}
    assert calls == [
        ('mafia', 'game-1', now), ('mafia', 'game-2', now),
        ('classic', -3, now), ('photo', -4, now),
        ('room-classic', 'room-game-1', now), ('room-classic', 'room-game-2', now),
        ('room-photo', 'photo-room-1', now), ('room-photo', 'photo-room-2', now),
    ]
    assert database.transactions == 9  # one candidate snapshot + one per target
    assert 'mode=mafia candidate=game-2' in caplog.text
    assert 'mode=classic candidate=room-game-2' in caplog.text
    assert 'mode=photo candidate=photo-room-2' in caplog.text


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
