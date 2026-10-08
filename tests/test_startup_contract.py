import asyncio
from pathlib import Path

import pytest

from storage.database import Database, DatabaseSettings
from storage.startup import expected_schema_heads, require_current_schema, require_postgres_backend
from tests.test_postgres_members import pg_env
from app_config import AppConfig


def test_runtime_rejects_json_backend():
    require_postgres_backend(' postgres ')
    with pytest.raises(RuntimeError, match='requires STORAGE_BACKEND=postgres'):
        require_postgres_backend('json')


def test_storage_backend_defaults_to_postgres(monkeypatch):
    monkeypatch.delenv('STORAGE_BACKEND', raising=False)
    assert AppConfig().storage_backend == 'postgres'


def test_local_dev_startup_includes_worker_without_enabling_telegram():
    script = Path(__file__).resolve().parents[1] / 'scripts' / 'Start-LocalDevelopment.ps1'
    source = script.read_text(encoding='utf-8')
    assert "if ($WithTelegram) { $arguments += @('--profile', 'telegram') }" in source
    assert "'seed', 'game-worker', 'admin', 'mini-app'" in source


def test_compose_admin_does_not_repeat_dependency_ordered_seed():
    root = Path(__file__).resolve().parents[1]
    compose = (root / 'compose.dev.yml').read_text(encoding='utf-8')
    runner = (root / 'scripts' / 'run_admin_preview.py').read_text(encoding='utf-8')
    admin = compose.split('  admin:', 1)[1].split('  mini-app:', 1)[0]
    assert 'MQB_DEV_SKIP_SEED: "1"' in admin
    assert "if os.getenv('MQB_DEV_SKIP_SEED') != '1':" in runner


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
