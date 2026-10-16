"""Farm tests run with a FRACTIONAL wall clock by default (production uses time.time(), a float).

Every ``FarmService`` built inside a ``test_farm_*`` module gets ``clock() + FARM_TEST_CLOCK_FRACTION`` (default 0.8106), so
the single time-normalisation point (``qw_farm.catalog.tick``) is exercised by all scenarios: helpers/shifts, workshops,
animals, caravan, contracts, stage 14 economy, progression. ``FARM_TEST_CLOCK_FRACTION=0`` restores whole-second clocks.
"""
import os
import pytest


@pytest.fixture(autouse=True)
def _farm_fractional_clock(request, monkeypatch):
    if not request.node.fspath.basename.startswith('test_farm'):
        return
    fraction = float(os.getenv('FARM_TEST_CLOCK_FRACTION', '0.8106'))
    if not fraction:
        return
    from qw_farm import service
    original = service.FarmService.__init__

    def init(self, unit, principal, *, clock=None, speed=1, **kwargs):
        if clock is None:
            import time
            clock = time.time
        original(self, unit, principal, clock=lambda: clock() + fraction, speed=speed, **kwargs)

    monkeypatch.setattr(service.FarmService, '__init__', init)


# --- Hermetic PostgreSQL: every pytest run starts from the same schema state ---
#
# CI (a fresh service container), the local docker run and a re-run on a long-lived
# morning_quiz_test used to differ: leftovers of earlier runs, a schema migrated by
# somebody else's uncommitted revision, chats seeded by other tests. At the start of a
# session the ``public`` schema of the disposable test database (and any leaked
# ``mqb_acceptance_*`` schemas) is dropped and rebuilt with ``alembic upgrade head``,
# so the result no longer depends on who ran last. Opt out: MQB_TEST_DB_RESET=0.
# The guard is the same as in tests/local_database.py: only the loopback / compose
# ``postgres`` morning_quiz_test of the mqb_dev user is ever touched.

def _disposable_test_database_url():
    from urllib.parse import urlsplit
    url = os.getenv('TEST_DATABASE_URL', '').strip()
    if not url or os.getenv('MQB_TEST_DB_RESET', '1') == '0':
        return None
    parsed = urlsplit(url)
    if (parsed.hostname not in ('127.0.0.1', 'localhost', 'postgres')
            or parsed.path != '/morning_quiz_test' or parsed.username != 'mqb_dev'):
        return None
    return url


@pytest.fixture(scope='session', autouse=True)
def _fresh_test_database():
    url = _disposable_test_database_url()
    if url is None:
        yield
        return
    import asyncio
    import subprocess
    import sys
    from pathlib import Path
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine
    from storage.database import normalize_database_url

    async def reset():
        engine = create_async_engine(normalize_database_url(url))
        try:
            async with engine.begin() as connection:
                leaked = (await connection.execute(text(
                    "SELECT nspname FROM pg_namespace WHERE nspname LIKE 'mqb\\_acceptance\\_%'"
                ))).scalars().all()
                for name in leaked:
                    await connection.exec_driver_sql(f'DROP SCHEMA "{name}" CASCADE')
                await connection.exec_driver_sql('DROP SCHEMA IF EXISTS public CASCADE')
                await connection.exec_driver_sql('CREATE SCHEMA public')
        finally:
            await engine.dispose()

    asyncio.run(reset())
    root = Path(__file__).resolve().parents[1]
    environment = dict(os.environ, DATABASE_URL=url, PYTHONPATH=str(root))
    completed = subprocess.run(
        [sys.executable, '-m', 'alembic', 'upgrade', 'head'],
        cwd=root, env=environment, capture_output=True, text=True, timeout=600,
    )
    if completed.returncode != 0:
        pytest.exit('alembic upgrade head failed on the fresh test database:\n'
                    + completed.stdout[-2000:] + completed.stderr[-2000:], returncode=2)
    yield
