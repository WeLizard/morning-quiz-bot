"""«Ночной город» nudges on PostgreSQL: a real case writes them in the move's transaction, once, publicly."""
import unittest
from datetime import datetime
from uuid import uuid4

from sqlalchemy import select

from application.night_case_nudges import KIND, nudge_is_current
from domain.night_case_engine import _due
from storage.models import Account, AccountIdentity, NightGameSealed, NotificationOutbox, User
from tests import test_night_case_application as base

# Everything a nudge may carry. Anything else (a role, a secret, a clue, a message text) is a leak.
PUBLIC_PAYLOAD = {'game_id', 'room_id', 'room_title', 'case_title', 'window_count', 'event', 'account_id',
                  'window_idx', 'window_seq', 'final_hearing', 'hearing_id', 'suspect'}


class NightCaseNudgePostgresTests(unittest.IsolatedAsyncioTestCase):
    service = base.NightApplicationPostgresTests.service
    lobby_command = base.NightApplicationPostgresTests.lobby_command
    lobby = base.NightApplicationPostgresTests.lobby
    ready_lobby = base.NightApplicationPostgresTests.ready_lobby
    running = base.NightApplicationPostgresTests.running
    player_command = base.NightApplicationPostgresTests.player_command
    asyncTearDown = base.NightApplicationPostgresTests.asyncTearDown

    async def asyncSetUp(self):
        await base.NightApplicationPostgresTests.asyncSetUp(self)
        # Three of the four seated players opened the bot; the fourth plays only in the browser.
        self.telegram = {}
        async with self.db.transaction() as session:
            for account in self.accounts[:3]:
                uid = 7_000_000_000 + uuid4().int % 1_000_000_000
                self.telegram[account] = uid
                session.add(User(id=uid, account_id=account, display_name='Synthetic'))
            await session.flush()
            for account, uid in self.telegram.items():
                session.add(AccountIdentity(account_id=account, provider='telegram', provider_subject=str(uid),
                                            verified_at=self.now, linked_at=self.now))

    async def nudges(self, game):
        async with self.db.transaction() as session:
            return list((await session.scalars(select(NotificationOutbox).where(
                NotificationOutbox.game_id == game, NotificationOutbox.kind == KIND)
                .order_by(NotificationOutbox.available_at, NotificationOutbox.user_id))).all())

    async def tick(self, game, command_id):
        async with self.db.transaction() as session:
            doc = (await session.get(NightGameSealed, game)).kernel
            due = _due(doc)
            self.now = datetime.fromisoformat(due['at'].replace('Z', '+00:00'))
            command = {'command_id': command_id, 'kind': 'system.tick', 'window_seq': doc['clock']['window_seq'],
                       'timer_seq': doc['clock']['timer_seq'], 'params': {'expected_due_at': due['at']}}
            result = await self.service(session).advance_due(game_id=game, command=command)
        self.assertTrue(result['receipt']['accepted'])
        return command

    async def current(self, row):
        async with self.db.transaction() as session:
            return await nudge_is_current(session, row.payload)

    async def test_start_and_windows_nudge_telegram_players_once_with_public_facts_only(self):
        game, *_ = await self.running()
        rows = await self.nudges(game)
        # The owner pressed «Начать»; the browser-only player has no Telegram.
        self.assertEqual(sorted((r.payload['event'], r.user_id) for r in rows),
                         sorted(('start', self.telegram[a]) for a in self.accounts[1:3]))
        command = await self.tick(game, 'nudge-tick-1')
        windows = [r for r in await self.nudges(game) if r.payload['event'] == 'window']
        self.assertEqual(sorted(r.user_id for r in windows), sorted(self.telegram.values()))
        self.assertEqual({r.payload['window_idx'] for r in windows}, {2})
        self.assertTrue(all(r.available_at == self.now for r in windows), 'a 09:00/19:00 window is not quiet time')
        for row in await self.nudges(game):
            self.assertLessEqual(set(row.payload), PUBLIC_PAYLOAD)
            self.assertEqual(row.chat_id, row.user_id)
        # A replayed tick is the same transition: nothing new is queued.
        async with self.db.transaction() as session:
            await self.service(session).advance_due(game_id=game, command=command)
        self.assertEqual(len(await self.nudges(game)), 5)
        self.assertTrue(await self.current(windows[0]))
        await self.tick(game, 'nudge-tick-2')
        self.assertFalse(await self.current(windows[0]), 'a window that has passed is not worth a message')

    async def test_switched_off_reminders_are_dropped_at_delivery_and_the_end_reaches_everyone(self):
        game, *_ = await self.running()
        async with self.db.transaction() as session:
            (await session.get(Account, self.accounts[1])).game_preferences = {'night_case_notifications': False}
        start = {r.user_id: r for r in await self.nudges(game)}
        self.assertFalse(await self.current(start[self.telegram[self.accounts[1]]]))
        self.assertTrue(await self.current(start[self.telegram[self.accounts[2]]]))
        for i in range(40):
            async with self.db.transaction() as session:
                if (await session.get(NightGameSealed, game)).lifecycle == 'finished':
                    break
            await self.tick(game, f'nudge-end-{i:03d}')
        else:
            self.fail('the case did not end')
        finals = [r for r in await self.nudges(game) if r.payload['event'] == 'final']
        self.assertEqual(sorted(r.user_id for r in finals), sorted(self.telegram.values()))
        self.assertTrue(await self.current(next(r for r in finals if r.user_id == self.telegram[self.owner])))


if __name__ == '__main__':
    unittest.main()
