"""Burst benchmark for the Night Case read path (test PostgreSQL only).

Starts a real manor game with 8 players, then measures how long one player's
``propose_intent`` takes while N other ``get_view`` calls of the same game run
concurrently (the window-open refresh burst).

Usage (from the repo root, with the Night Case PG test env set):
    .venv-local/Scripts/python.exe scripts/bench_night_case_burst.py --rounds 5 --bursts 8 16
"""
import argparse
import asyncio
import json
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from application.night_case import (FrozenCaseRef, NightCaseApplicationService, NightCaseRegistry,  # noqa: E402
                                    OperatorPrincipal)
from domain.night_case_format import canonical_content_hash  # noqa: E402
from storage.database import Database, DatabaseSettings  # noqa: E402
from storage.models import Account, Room, RoomMembership  # noqa: E402
from tests.night_case_test_database import night_case_test_url  # noqa: E402

CASE = ROOT / 'content/night_city/manor_lake.case.json'
PLAYERS = 8


class Bench:
    def __init__(self, db):
        self.db = db
        self.now = datetime(2026, 11, 15, 10, tzinfo=timezone.utc)
        self.accounts = [uuid4() for _ in range(PLAYERS)]
        self.owner = self.accounts[0]
        self.room = uuid4().hex
        doc = json.loads(CASE.read_text(encoding='utf-8'))
        doc['meta']['id'] = 'bench_' + uuid4().hex[:24]
        self.doc = doc
        self.ref = FrozenCaseRef(doc['meta']['id'], doc['meta']['version'], canonical_content_hash(doc))
        self.registry = NightCaseRegistry(frozenset({self.ref}), frozenset({'Europe/Moscow'}), b'night-bench-cursor-secret-32-bytes!')

    def service(self, session):
        return NightCaseApplicationService(session, lambda: self.now, self.registry)

    async def call(self, method, **kwargs):
        async with self.db.transaction() as session:
            return await getattr(self.service(session), method)(**kwargs)

    async def setup(self):
        async with self.db.transaction() as session:
            session.add_all([Account(id=a, display_name=f'Bench {i}') for i, a in enumerate(self.accounts)])
            await session.flush()
            session.add(Room(id=self.room, kind='standalone', owner_account_id=self.owner))
            await session.flush()
            session.add_all([RoomMembership(room_id=self.room, account_id=a, role='owner' if a == self.owner else 'member')
                             for a in self.accounts])
            await session.flush()
            await self.service(session).register_case(operator=OperatorPrincipal('bench', self.owner), content=self.doc,
                                                      validation_report={'scope': 'bench', 'publication': 'not_checked'},
                                                      admission='rehearsal')
        cmd = lambda rev, params=None: {'command_id': uuid4().hex, 'expected_lobby_revision': rev, 'params': params or {}}
        created = await self.call('create_lobby', account_id=self.owner, room_id=self.room,
                                  command=cmd(0, {'case_id': self.ref.case_id, 'case_version': self.ref.case_version,
                                                  'timezone': 'Europe/Moscow'}))
        self.game = created['view']['game_id']
        view = created['view']
        for i, account in enumerate(self.accounts):
            if account != self.owner:
                view = (await self.call('join_lobby', account_id=account, game_id=self.game,
                                        command=cmd(view['lobby_revision'])))['view']
            view = (await self.call('set_ready', account_id=account, game_id=self.game,
                                    command=cmd(view['lobby_revision'], {'name': f'Bench {i}', 'address_form': 'n',
                                                                         'ready': True})))['view']
        await self.call('start_game', account_id=self.owner, game_id=self.game, command=cmd(view['lobby_revision']))

    async def selection(self, account):
        view = await self.call('get_view', account_id=account, game_id=self.game)
        return next(e['quote']['selection_id'] for e in view['menu'] if 'quote' in e)

    async def timed(self, coro):
        start = time.perf_counter()
        await coro
        return (time.perf_counter() - start) * 1000

    async def burst(self, views):
        actor = self.accounts[-1]
        selection = await self.selection(actor)
        viewers = [self.accounts[i % (PLAYERS - 1)] for i in range(views)]
        tasks = [asyncio.create_task(self.timed(self.call('get_view', account_id=v, game_id=self.game))) for v in viewers]
        await asyncio.sleep(0.005)  # the intent lands just after the burst started
        intent = await self.timed(self.call('propose_intent', account_id=actor, game_id=self.game,
                                            request_id=uuid4().hex, selection_id=selection))
        view_ms = await asyncio.gather(*tasks)
        return intent, max(view_ms)


def fmt(values):
    return f'median {statistics.median(values):7.1f} ms  min {min(values):7.1f}  max {max(values):7.1f}'


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--rounds', type=int, default=5)
    parser.add_argument('--bursts', type=int, nargs='+', default=[8, 16])
    parser.add_argument('--pool-size', type=int, default=5, help='same default as production DatabaseSettings')
    parser.add_argument('--max-overflow', type=int, default=5)
    args = parser.parse_args()
    db = Database(DatabaseSettings(url=night_case_test_url(), pool_size=args.pool_size, max_overflow=args.max_overflow))
    try:
        bench = Bench(db)
        await bench.setup()
        actor = bench.accounts[-1]
        for _ in range(3):  # warm-up: connections, imports, caches
            await bench.call('get_view', account_id=bench.owner, game_id=bench.game)
        single_view = [await bench.timed(bench.call('get_view', account_id=bench.owner, game_id=bench.game))
                       for _ in range(args.rounds)]
        single_intent = []
        for _ in range(args.rounds):
            selection = await bench.selection(actor)
            single_intent.append(await bench.timed(bench.call('propose_intent', account_id=actor, game_id=bench.game,
                                                              request_id=uuid4().hex, selection_id=selection)))
        print(f'single get_view       {fmt(single_view)}')
        print(f'single propose_intent {fmt(single_intent)}')
        for views in args.bursts:
            intents, walls = [], []
            for _ in range(args.rounds):
                intent, wall = await bench.burst(views)
                intents.append(intent); walls.append(wall)
            print(f'burst {views:2d} views: intent {fmt(intents)} | slowest view median {statistics.median(walls):7.1f} ms')
    finally:
        await db.dispose()


if __name__ == '__main__':
    asyncio.run(main())
