#!/usr/bin/env python3
"""Sync the old bot's JSON progress into the new bot's database (three-way, see storage/legacy_sync.py).

    DATABASE_URL=postgresql+asyncpg://... python scripts/legacy_sync.py \
        --base /path/to/snapshot/the/database/was/filled/from/data \
        --source /path/to/fresh/copy/of/old/bot/data [--apply]

Without --apply the sync runs in a transaction that is rolled back and prints the exact report.
Take --source from a COPY of the old bot's data/ (stopped bot on the switch day) and keep that
copy: it is the --base of the next sync. Exit code 2 when the sync is refused, 1 with conflicts.
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from storage.database import Database, DatabaseSettings  # noqa: E402
from storage.json_importer import JsonSnapshot  # noqa: E402
from storage.legacy_sync import LegacySync, SyncRefused  # noqa: E402


async def main(args) -> int:
    base, source = JsonSnapshot.scan(Path(args.base)), JsonSnapshot.scan(Path(args.source))
    database = Database(DatabaseSettings.from_env())
    try:
        report = await LegacySync(database, base, source).run(apply=args.apply)
    except SyncRefused as refused:
        print(json.dumps({'refused': str(refused)}, ensure_ascii=False))
        return 2
    finally:
        await database.dispose()
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 1 if report['conflicts'] else 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--base', required=True, help='data/ of the snapshot the database was filled from')
    parser.add_argument('--source', required=True, help="data/ of a fresh copy of the old bot")
    parser.add_argument('--apply', action='store_true', help='commit; without it the run is rolled back')
    raise SystemExit(asyncio.run(main(parser.parse_args())))
