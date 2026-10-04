"""Create a retained dev snapshot and exercise isolated restore, never overwrite dev."""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from storage.database import Database, DatabaseSettings
from storage.dev_backups import create, verify_restore


async def main():
    database = Database(DatabaseSettings.from_env())
    try:
        snapshot = await create(database)
        result = await verify_restore(database, snapshot['id'])
        print(json.dumps(result))
    finally:
        await database.dispose()


if __name__ == '__main__':
    asyncio.run(main())
