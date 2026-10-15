"""Isolated PostgreSQL rehearsal for the Farm migration and backup/restore."""

import asyncio
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import warnings
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import FastAPI
from sqlalchemy import inspect, text

from storage.database import Database, DatabaseSettings
from storage.models import Account, User
from qw_farm.integration import install_farm


_TEMP_DATABASE = re.compile(r"mqb_farm_migration_[a-f0-9]{32}\Z")
_FARM_MIGRATION = "qw_farm_010"


async def _assert_farm_migration_is_in_head(session):
    """Verify the DB reached every current head and Farm is an ancestor."""
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    database_heads = set(await session.scalars(text("SELECT version_num FROM alembic_version")))
    expected_heads = set(scripts.get_heads())

    assert database_heads == expected_heads
    revisions = {
        revision.revision
        for revision in scripts.iterate_revisions(expected_heads, "base")
    }
    assert _FARM_MIGRATION in revisions


def _test_database_url():
    raw = os.getenv("TEST_DATABASE_URL", "").strip()
    if not raw:
        pytest.skip("TEST_DATABASE_URL is unset; no production fallback")
    parsed = urlsplit(raw)
    scheme = parsed.scheme.split("+", 1)[0]
    hostname = (parsed.hostname or "").lower()
    in_dev_container = os.getenv("MQB_DEV_CONTAINER") == "1" and Path("/.dockerenv").is_file()
    expected_endpoint = ("postgres", 5432) if in_dev_container else ("127.0.0.1", 55433)
    if (scheme not in {"postgres", "postgresql"}
            or parsed.username != "mqb_dev"
            or parsed.path != "/morning_quiz_test"
            or (hostname, parsed.port) != expected_endpoint):
        pytest.fail(
            "Farm migration rehearsal requires TEST_DATABASE_URL for "
            "mqb_dev@morning_quiz_test on loopback or the local postgres service"
        )
    return parsed


def _url_for(parsed, database_name):
    return urlunsplit((parsed.scheme, parsed.netloc, "/" + database_name, "", ""))


def _run(args, env, cwd=None):
    subprocess.run(
        args, check=True, capture_output=True, text=True, env=env, timeout=120,
        cwd=cwd or Path(__file__).resolve().parents[1],
    )


def test_farm_migration_preserves_accounts_and_dump_restores_pre_farm_state(tmp_path):
    parsed = _test_database_url()
    required = ("createdb", "dropdb", "pg_dump", "pg_restore")
    if any(shutil.which(command) is None for command in required):
        pytest.skip("PostgreSQL client tools are available in the dev test image")

    migration_db = "mqb_farm_migration_" + uuid4().hex
    restored_db = "mqb_farm_migration_" + uuid4().hex
    assert _TEMP_DATABASE.fullmatch(migration_db)
    assert _TEMP_DATABASE.fullmatch(restored_db)

    pg_env = os.environ.copy()
    pg_env["PGPASSWORD"] = parsed.password or ""
    pg = ["-h", parsed.hostname, "-p", str(parsed.port or 5432), "-U", parsed.username]
    migration_url = _url_for(parsed, migration_db)
    restored_url = _url_for(parsed, restored_db)
    alembic_env = {
        **pg_env,
        "DATABASE_URL": migration_url,
        "STORAGE_BACKEND": "postgres",
        "PYTHON_DOTENV_DISABLED": "1",
    }
    created = []
    archive = tmp_path / "farm-pre-migration.dump"
    account_id = uuid4()
    user_id = 913000000001

    async def verify_upgrade():
        db = Database(DatabaseSettings(url=migration_url))
        try:
            async with db.transaction() as session:
                account = await session.get(Account, account_id)
                user = await session.get(User, user_id)
                assert account and account.display_name == "Farm migration fixture"
                assert user and user.account_id == account_id
                async with db.engine.connect() as connection:
                    tables = await connection.run_sync(
                        lambda sync_connection: inspect(sync_connection).get_table_names()
                    )
                assert {"farm_states", "farm_receipts", "farm_ledger", "farm_village"} <= set(tables)
                await _assert_farm_migration_is_in_head(session)
        finally:
            await db.dispose()

    async def verify_restored_baseline():
        db = Database(DatabaseSettings(url=restored_url))
        try:
            async with db.transaction() as session:
                # Plain column reads: the restored schema is pre-0030, so an ORM load of
                # Account would select the missing accounts.address_form column.
                account_name = await session.scalar(
                    text("SELECT display_name FROM accounts WHERE id = :id"), {"id": account_id})
                user_row = (await session.execute(
                    text("SELECT display_name, account_id FROM users WHERE id = :id"),
                    {"id": user_id})).one_or_none()
                assert account_name == "Farm migration fixture"
                assert user_row and user_row[0] == "Farm migration user"
                assert user_row[1] == account_id
                version = await session.scalar(text("SELECT version_num FROM alembic_version"))
                assert version == "20261008_0021"
                async with db.engine.connect() as connection:
                    tables = await connection.run_sync(
                        lambda sync_connection: inspect(sync_connection).get_table_names()
                    )
                assert not {"farm_states", "farm_receipts", "farm_ledger", "farm_village"} & set(tables)
        finally:
            await db.dispose()

    async def verify_flag_off_keeps_migrated_data():
        """A disabled adapter must leave the upgraded database untouched."""
        db = Database(DatabaseSettings(url=migration_url))
        app = FastAPI()
        original_flag = os.environ.pop("QW_FARM_ENABLED", None)
        try:
            before_routes = tuple(route.path for route in app.routes)
            install_farm(app, db, type("Settings", (), {"origin": "https://test.invalid"})())
            assert tuple(route.path for route in app.routes) == before_routes
            async with db.transaction() as session:
                account = await session.get(Account, account_id)
                user = await session.get(User, user_id)
                assert account and account.display_name == "Farm migration fixture"
                assert user and user.account_id == account_id
                state_count = await session.scalar(text("SELECT count(*) FROM farm_states"))
                receipt_count = await session.scalar(text("SELECT count(*) FROM farm_receipts"))
                ledger_count = await session.scalar(text("SELECT count(*) FROM farm_ledger"))
                assert (state_count, receipt_count, ledger_count) == (0, 0, 0)
                await _assert_farm_migration_is_in_head(session)
        finally:
            if original_flag is not None:
                os.environ["QW_FARM_ENABLED"] = original_flag
            await db.dispose()

    try:
        _run(["createdb", *pg, migration_db], pg_env)
        created.append(migration_db)
        _run([
            sys.executable, "-m", "alembic", "upgrade", "20261008_0021",
        ], {**alembic_env, "DATABASE_URL": migration_url})

        async def seed_baseline():
            db = Database(DatabaseSettings(url=migration_url))
            try:
                # Core inserts name only the pre-farm columns: the ORM would also write
                # columns added by later migrations (e.g. accounts.address_form).
                async with db.transaction() as session:
                    await session.execute(Account.__table__.insert().values(
                        id=account_id, display_name="Farm migration fixture"))
                    await session.execute(User.__table__.insert().values(
                        id=user_id, account_id=account_id, display_name="Farm migration user"))
            finally:
                await db.dispose()

        asyncio.run(seed_baseline())
        _run([
            "pg_dump", *pg, "-d", migration_db, "-Fc", "--no-owner",
            "--no-privileges", "-f", str(archive),
        ], pg_env)
        _run([
            sys.executable, "-m", "alembic", "upgrade", "head",
        ], alembic_env)
        asyncio.run(verify_upgrade())
        asyncio.run(verify_flag_off_keeps_migrated_data())

        _run(["createdb", *pg, restored_db], pg_env)
        created.append(restored_db)
        _run([
            "pg_restore", *pg, "-d", restored_db, "--exit-on-error", str(archive),
        ], pg_env)
        asyncio.run(verify_restored_baseline())
    finally:
        cleanup_errors = []
        for database_name in reversed(created):
            if _TEMP_DATABASE.fullmatch(database_name):
                try:
                    _run(["dropdb", *pg, "--force", "--if-exists", database_name], pg_env)
                except (subprocess.SubprocessError, OSError) as exc:
                    cleanup_errors.append((database_name, exc))
        if cleanup_errors:
            names = ", ".join(name for name, _ in cleanup_errors)
            if sys.exc_info()[0] is None:
                raise RuntimeError(f"Temporary Farm test database cleanup failed: {names}") from cleanup_errors[0][1]
            warnings.warn(f"Temporary Farm test database cleanup also failed: {names}")
