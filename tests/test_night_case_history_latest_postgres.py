"""«Ночной город» history from the end (the feed «Гостиная у камина»): the newest page first, older pages on request."""
import unittest
from datetime import timedelta

from application.night_case import NightCaseError
from tests import test_night_case_application as base
from tests import test_night_case_presence_postgres as presence_tests


class NightCaseLatestHistoryPostgresTests(unittest.IsolatedAsyncioTestCase):
    service = base.NightApplicationPostgresTests.service
    lobby_command = base.NightApplicationPostgresTests.lobby_command
    lobby = base.NightApplicationPostgresTests.lobby
    ready_lobby = base.NightApplicationPostgresTests.ready_lobby
    running = base.NightApplicationPostgresTests.running
    player_command = base.NightApplicationPostgresTests.player_command
    asyncSetUp = base.NightApplicationPostgresTests.asyncSetUp
    asyncTearDown = base.NightApplicationPostgresTests.asyncTearDown
    tick = presence_tests.NightCasePresencePostgresTests.tick

    async def say(self, game, account, text):
        self.now += timedelta(seconds=7)
        command = await self.player_command(game, account, 'say', {'channel': 'square', 'recipients': [], 'text': text})
        async with self.db.transaction() as session:
            result = await self.service(session).execute(account_id=account, game_id=game, command=command)
        self.assertTrue(result['receipt']['accepted'], result)

    async def pages(self, account, game, stream, limit):
        """Walks the stream from the end; returns the pages in the order they were read."""
        pages, cursor = [], None
        while True:
            async with self.db.transaction() as session:
                page = await self.service(session).history(account_id=account, game_id=game, stream=stream, limit=limit,
                                                           latest=True, cursor=cursor)
            pages.append(page['items'])
            cursor = page['next_cursor']
            if cursor is None:
                return pages

    async def test_the_feed_reads_the_newest_page_first_and_walks_back(self):
        game, *_ = await self.running()
        speakers = self.accounts[:4]
        texts = [f'реплика {i}' for i in range(7)]
        for i, text in enumerate(texts):
            await self.say(game, speakers[i % len(speakers)], text)
        reader = self.accounts[1]
        pages = await self.pages(reader, game, 'messages', 3)
        self.assertEqual([[row['text'] for row in page] for page in pages],
                         [texts[4:], texts[1:4], texts[:1]], 'newest page first, each page oldest first')
        self.assertTrue(all(row['at'].endswith('Z') for page in pages for row in page), 'each line knows its time')
        async with self.db.transaction() as session:
            ordinary = await self.service(session).history(account_id=reader, game_id=game, stream='messages')
        self.assertEqual([row['text'] for row in ordinary['items']], texts)

        for i in range(3):
            await self.tick(game, f'latest-tick-{i}')
        async with self.db.transaction() as session:
            ordinary = await self.service(session).history(account_id=reader, game_id=game, stream='public')
        walked = [row for page in reversed(await self.pages(reader, game, 'public', 2)) for row in page]
        self.assertGreater(len(walked), 2)
        self.assertEqual([row['event_id'] for row in walked], [row['event_id'] for row in ordinary['items']])
        self.assertEqual([row['at'] for row in walked], sorted(row['at'] for row in walked))

    async def test_a_cursor_from_the_end_does_not_open_the_ordinary_order(self):
        game, *_ = await self.running()
        for i in range(3):
            await self.say(game, self.accounts[i], f'строка {i}')
        async with self.db.transaction() as session:
            page = await self.service(session).history(account_id=self.owner, game_id=game, stream='messages', limit=1, latest=True)
        self.assertIsNotNone(page['next_cursor'])
        with self.assertRaises(NightCaseError):
            async with self.db.transaction() as session:
                await self.service(session).history(account_id=self.owner, game_id=game, stream='messages', limit=1,
                                                    cursor=page['next_cursor'])
        with self.assertRaises(NightCaseError):
            async with self.db.transaction() as session:
                await self.service(session).history(account_id=self.owner, game_id=game, stream='messages', latest='yes')


if __name__ == '__main__':
    unittest.main()
