"""Private synthetic schemas, restricted to the disposable loopback database."""
from contextlib import asynccontextmanager
import os
from pathlib import Path
import re
from urllib.parse import urlsplit
import uuid

from sqlalchemy.ext.asyncio import async_sessionmaker

from storage.database import Database, DatabaseSettings
from storage.models import Base


def disposable_endpoint_allowed(url):
    parsed = urlsplit(url)
    in_dev_container = os.getenv('MQB_DEV_CONTAINER') == '1' and Path('/.dockerenv').is_file()
    expected_endpoint = ('postgres', 5432) if in_dev_container else ('127.0.0.1', 55433)
    owned_night = (url == os.getenv('NIGHT_CASE_TEST_DATABASE_URL')
                   and parsed.hostname in ('127.0.0.1', 'localhost') and parsed.port == 55434)
    return (((parsed.hostname, parsed.port) == expected_endpoint or owned_night)
            and parsed.path == '/morning_quiz_test' and parsed.username == 'mqb_dev')


@asynccontextmanager
async def isolated_database(url):
    if not disposable_endpoint_allowed(url):
        raise RuntimeError(
            'Acceptance tests require morning_quiz_test in the shared local PostgreSQL'
        )
    schema = 'mqb_acceptance_' + uuid.uuid4().hex
    database = Database(DatabaseSettings(url=url))
    async with database.engine.begin() as connection:
        await connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    # Изоляция схемы: translate_map для Core/ORM и search_path для сырого SQL
    # Alembic (ALTER TABLE без схемы), который через translate_map не проходит.
    from sqlalchemy.ext.asyncio import create_async_engine
    await database.engine.dispose()
    isolated_engine = create_async_engine(
        url,
        connect_args={'server_settings': {'search_path': f'"{schema}",public'}},
    )
    database.engine = isolated_engine.execution_options(schema_translate_map={None: schema})
    database.session_factory = async_sessionmaker(database.engine, expire_on_commit=False, autoflush=False)
    try:
        async with database.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        yield database, schema
    finally:
        assert re.fullmatch(r'mqb_acceptance_[a-f0-9]{32}', schema)
        async with database.engine.begin() as connection:
            await connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        await database.dispose()
