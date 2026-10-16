#!/usr/bin/env python3
"""Reconcile the score journal with the legacy counters (read-only unless --repair).

    DATABASE_URL=postgresql+asyncpg://... python scripts/reconcile_scores.py [--repair]

Exit code 0 when totals, the users.global_score cache, per-chat scores and Alchemy points all agree.
Run it on a COPY of the database before the switch and on the sandbox after every deploy.
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from storage.database import Database, DatabaseSettings  # noqa: E402
from storage.score_reconcile import reconcile, repair  # noqa: E402


async def main(args) -> int:
    database = Database(DatabaseSettings.from_env())
    try:
        async with database.transaction() as session:
            report = await reconcile(session)
            if args.repair and not report['ok']:
                print('repaired accounts:', await repair(session))
                report = await reconcile(session)
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        return 0 if report['ok'] else 1
    finally:
        await database.dispose()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repair', action='store_true', help='rebuild totals and caches from the journal')
    raise SystemExit(asyncio.run(main(parser.parse_args())))
