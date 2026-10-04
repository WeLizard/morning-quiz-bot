import asyncio

import pytest

from storage.database import Database, DatabaseSettings
from storage.startup import expected_schema_heads, require_current_schema, require_postgres_backend
from tests.test_postgres_members import pg_env


def test_runtime_rejects_json_backend():
    require_postgres_backend(' postgres ')
    with pytest.raises(RuntimeError, match='requires STORAGE_BACKEND=postgres'):
        require_postgres_backend('json')


def test_runtime_schema_gate_accepts_head_and_rejects_stale_revision(pg_env):
    async def run():
        database = Database(DatabaseSettings(url=pg_env))
        try:
            head = await require_current_schema(database)
            assert head in expected_schema_heads()
            with pytest.raises(RuntimeError, match='revision mismatch'):
                await require_current_schema(database, expected={'not-the-current-head'})
        finally:
            await database.dispose()

    asyncio.run(run())
