"""«Ночной город» presence on PostgreSQL: opening the case is «Я здесь», once per window, and the time shows to the table."""
import unittest
from datetime import datetime, timedelta

from domain.night_case_engine import _due
from storage.models import NightGameSealed, NightPresence
from tests import test_night_case_application as base


class NightCasePresencePostgresTests(unittest.IsolatedAsyncioTestCase):
    service = base.NightApplicationPostgresTests.service
    lobby_command = base.NightApplicationPostgresTests.lobby_command
    lobby = base.NightApplicationPostgresTests.lobby
    ready_lobby = base.NightApplicationPostgresTests.ready_lobby
    running = base.NightApplicationPostgresTests.running
    player_command = base.NightApplicationPostgresTests.player_command
    asyncSetUp = base.NightApplicationPostgresTests.asyncSetUp
    asyncTearDown = base.NightApplicationPostgresTests.asyncTearDown

    async def tick(self, game, command_id):
        async with self.db.transaction() as session:
            doc = (await session.get(NightGameSealed, game)).kernel
            due = _due(doc)
            self.now = datetime.fromisoformat(due['at'].replace('Z', '+00:00'))
            command = {'command_id': command_id, 'kind': 'system.tick', 'window_seq': doc['clock']['window_seq'],
                       'timer_seq': doc['clock']['timer_seq'], 'params': {'expected_due_at': due['at']}}
            result = await self.service(session).advance_due(game_id=game, command=command)
        self.assertTrue(result['receipt']['accepted'])

    async def seat(self, game, account):
        async with self.db.transaction() as session:
            doc = (await session.get(NightGameSealed, game)).kernel
        return next(p for p in doc['players'] if p['account_id'] == str(account)), doc['clock']

    async def present(self, game, account):
        async with self.db.transaction() as session:
            return await self.service(session).mark_present(account_id=account, game_id=game)

    async def test_opening_the_case_marks_the_seat_once_per_window_and_the_table_sees_when(self):
        game, *_ = await self.running()
        await self.tick(game, 'presence-tick-1')
        reader = self.accounts[2]
        before, clock = await self.seat(game, reader)
        self.assertNotEqual(before['last_seen_window'], clock['window_idx'])
        self.assertEqual(await self.present(game, reader), {'marked': True})
        after, _ = await self.seat(game, reader)
        self.assertEqual(after['last_seen_window'], clock['window_idx'])
        self.assertEqual(after['actor_seq'], before['actor_seq'] + 1, 'the mark is the ordinary «seen» move')
        self.assertEqual(after['ap'], before['ap'], 'being here costs nothing')
        # Again in the same window: only the time moves, and not more often than once a minute.
        first = self.now
        self.now += timedelta(seconds=30)
        self.assertEqual(await self.present(game, reader), {'marked': False})
        self.now += timedelta(minutes=5)
        self.assertEqual(await self.present(game, reader), {'marked': False})
        async with self.db.transaction() as session:
            row = await session.get(NightPresence, (game, reader))
            self.assertEqual(row.seen_at, self.now)
            view = await self.service(session).get_view(account_id=self.owner, game_id=game)
        seen = {p['account_id']: p.get('seen_at') for p in view['public']['players']}
        self.assertEqual(seen[str(reader)], self.now.replace(second=0, microsecond=0).isoformat().replace('+00:00', 'Z'))
        self.assertGreater(self.now, first)
        # The next window needs a new mark, and gets it on the next opening.
        await self.tick(game, 'presence-tick-2')
        self.assertEqual(await self.present(game, reader), {'marked': True})

    async def test_a_finished_case_is_not_marked(self):
        game, *_ = await self.running()
        for i in range(40):
            async with self.db.transaction() as session:
                if (await session.get(NightGameSealed, game)).lifecycle == 'finished':
                    break
            await self.tick(game, f'presence-end-{i:03d}')
        self.assertEqual(await self.present(game, self.accounts[1]), {'marked': False})


if __name__ == '__main__':
    unittest.main()
