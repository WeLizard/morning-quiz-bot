import asyncio
from hashlib import sha256
import json
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4
import zipfile

import pytest

from storage import dev_backups as backups


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(backups, 'WORKSPACE', tmp_path)
    monkeypatch.setattr(backups, 'ROOT', tmp_path / 'backups')
    backups.ROOT.mkdir()
    return backups.ROOT


def archive(files, *, damage=False, tables=None):
    key = uuid4().hex
    manifest = {'id': key, 'database': backups.DBNAME, 'format': 1, 'tables': tables or {},
                'created_at': '2026-08-31T00:00:00+00:00',
                'files': {name: sha256(value).hexdigest() for name, value in files.items()}}
    with zipfile.ZipFile(backups.path_for(key), 'w') as output:
        output.writestr('manifest.json', json.dumps(manifest))
        for name, value in files.items():
            output.writestr(name, value + b'changed' if damage else value)
    return key


def test_backup_exact_manifest_checksums_and_recoverable_removal(root):
    key = archive({'database.dump': b'dump', 'questions/A.json': b'[]', 'images/one.webp': b'pixels'})
    manifest, files = backups.read_verified(key)
    assert len(files) == 3 and manifest['id'] == key
    assert backups.listing()[0]['id'] == key
    assert backups.trash(key)['recoverable']
    assert not backups.listing()
    assert (root / 'trash' / f'{key}.zip').is_file()


@pytest.mark.parametrize('name', ['images/../escape', 'questions/../../secret', 'images/C:/outside',
                                 'images//absolute', 'questions/./file', 'images/foo. /x', 'other/file'])
def test_backup_rejects_unsafe_paths(root, name):
    key = archive({'database.dump': b'dump', name: b'unsafe'})
    with pytest.raises(ValueError, match='путь'):
        backups.read_verified(key)


def test_backup_rejects_corruption_and_bad_ids(root):
    key = archive({'database.dump': b'dump'}, damage=True)
    with pytest.raises(ValueError, match='сумма'):
        backups.read_verified(key)
    with pytest.raises(ValueError, match='ID'):
        backups.path_for('../not-an-archive')


def test_backup_rejects_unknown_or_malformed_table_fingerprints(root):
    key = archive({'database.dump': b'dump'}, tables={
        'room_invites; DROP DATABASE morning_quiz_dev': {'rows': 0, 'digest': '0' * 32},
    })
    with pytest.raises(ValueError, match='манифест таблиц'):
        backups.read_verified(key)
    key = archive({'database.dump': b'dump'}, tables={
        'accounts': {'rows': True, 'digest': '0' * 32},
    })
    with pytest.raises(ValueError, match='манифест таблиц'):
        backups.read_verified(key)


def test_guard_rejects_nondev_before_any_docker_call(monkeypatch):
    call = Mock(side_effect=AssertionError('Docker must not be called'))
    monkeypatch.setattr(backups.subprocess, 'run', call)
    for url in ('postgresql://x@192.168.0.33:5432/live', 'postgresql://mqb_dev@127.0.0.1:55433/morning_quiz_test'):
        with pytest.raises(ValueError, match='dev'):
            backups.guard(SimpleNamespace(settings=SimpleNamespace(url=url)))
    call.assert_not_called()


def test_isolated_restore_drops_only_created_uuid_database_on_failure(root, monkeypatch):
    key = archive({'database.dump': b'dump'})
    monkeypatch.setattr(backups, 'guard', lambda _: None)
    calls = []
    def command(args, **kwargs):
        calls.append(args)
        if args[0] == 'pg_restore':
            raise RuntimeError('simulated failure')
        return b''
    monkeypatch.setattr(backups, 'command', command)
    with pytest.raises(RuntimeError, match='simulated'):
        asyncio.run(backups.verify_restore(None, key))
    assert [c[0] for c in calls] == ['createdb', 'pg_restore', 'dropdb']
    assert calls[0][-1] == calls[-1][-1]
    assert calls[-1][-1].startswith('mqb_restore_') and calls[-1][-1] != backups.DBNAME


def test_restore_verifies_only_tables_captured_in_pre_migration_snapshot(root, monkeypatch):
    digest = 'a' * 32
    key = archive({'database.dump': b'dump'}, tables={
        'accounts': {'rows': 0, 'digest': digest},
    })
    monkeypatch.setattr(backups, 'guard', lambda _: None)
    calls = []

    def command(args, **kwargs):
        calls.append(args)
        if args[0] == 'psql':
            return f'0|{digest}'.encode()
        return b''

    monkeypatch.setattr(backups, 'command', command)
    result = asyncio.run(backups.verify_restore(None, key))
    assert result['verified'] is True and result['tables'] == 1
    checks = [args[-1] for args in calls if args[0] == 'psql']
    assert len(checks) == 1 and 'FROM "accounts"' in checks[0]
    assert all('room_invites' not in query for query in checks)


def test_inplace_restore_rejects_missing_explicit_offline_intent(monkeypatch):
    monkeypatch.delenv('MQB_DEV_RESTORE_ID', raising=False)
    with pytest.raises(ValueError, match='PowerShell|ps1'):
        asyncio.run(backups.restore_dev(None, uuid4().hex, confirmation=backups.DBNAME))


def test_pg_backup_commands_never_register_legacy_file_archiver():
    from handlers.backup_handlers import BackupHandlers
    from handlers.postgres_backup_handlers import PostgresBackupHandlers
    handlers = BackupHandlers(SimpleNamespace(storage_backend='postgres'), Mock()).get_handlers()
    assert len(handlers) == 5
    assert all(isinstance(handler.callback.__self__, PostgresBackupHandlers) for handler in handlers)
