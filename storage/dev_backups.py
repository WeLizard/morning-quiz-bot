"""Verified local dev backups. Fixed Docker/database targets; no server access."""
import asyncio
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import urlsplit
from uuid import uuid4
import zipfile

from sqlalchemy import text

from .models import Base

WORKSPACE = Path(__file__).resolve().parents[1]
ROOT = WORKSPACE / '.local' / 'dev-backups'
CONTAINER = 'mqb-local-dev-postgres-1'
ROLE = 'mqb_dev'
DBNAME = 'morning_quiz_dev'
MAX_BYTES = 256 * 1024 * 1024


def _inside_dev_container():
    return os.getenv('MQB_DEV_CONTAINER') == '1' and Path('/.dockerenv').is_file()


def guard(database):
    url = urlsplit(database.settings.url)
    container_dev = _inside_dev_container()
    expected_endpoint = ('postgres', 5432) if container_dev else ('127.0.0.1', 55433)
    if ((url.hostname, url.port) != expected_endpoint or url.path != '/' + DBNAME or url.username != ROLE
            or (not container_dev and str(WORKSPACE).startswith('\\\\'))):
        raise ValueError('Операция доступна только для постоянной локальной dev-БД')
    if container_dev:
        return
    endpoint = subprocess.run(['docker', 'context', 'inspect', '--format', '{{.Endpoints.docker.Host}}'],
                              capture_output=True, timeout=15, check=True).stdout.decode().strip()
    for target in (endpoint, os.getenv('DOCKER_HOST', '')):
        if target and not (target.startswith('npipe:////./pipe/') or target == 'unix:///var/run/docker.sock'):
            raise ValueError('Удалённый Docker запрещён')


def command(args, *, raw=None):
    if _inside_dev_container():
        url = urlsplit(os.environ.get('DATABASE_URL', ''))
        if (url.hostname, url.port, url.path, url.username) != ('postgres', 5432, '/' + DBNAME, ROLE):
            raise ValueError('Операция доступна только для постоянной локальной dev-БД')
        environment = os.environ.copy()
        environment['PGPASSWORD'] = url.password or ''
        pg_command = [args[0], '-h', url.hostname, '-p', str(url.port), *args[1:]]
        result = subprocess.run(pg_command, input=raw, capture_output=True, timeout=90, env=environment)
    else:
        result = subprocess.run(['docker', 'exec', '-i', CONTAINER, *args], input=raw, capture_output=True, timeout=90)
    if result.returncode:
        # Do not return SQL/server diagnostics or connection details to a browser.
        raise RuntimeError('Локальная операция PostgreSQL не завершена')
    if len(result.stdout) > MAX_BYTES:
        raise ValueError('Архив превышает локальный лимит 256 МиБ')
    return result.stdout


def path_for(backup_id):
    if not re.fullmatch(r'[a-f0-9]{32}', backup_id):
        raise ValueError('Некорректный ID архива')
    path = (ROOT / f'{backup_id}.zip').resolve()
    if path.parent != ROOT.resolve() or not path.is_relative_to(WORKSPACE) or path.is_symlink():
        raise ValueError('Архив вне разрешённого каталога')
    return path


async def fingerprints(session):
    result = {}
    present = set((await session.scalars(text(
        'SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname = current_schema()'
    ))).all())
    # During an in-place upgrade the live dev schema may be one revision behind
    # the checked-out models. Fingerprint only known tables that actually exist;
    # this makes a pre-migration backup possible without inventing empty tables.
    for table in sorted(set(Base.metadata.tables) & present):
        # Table names are code-owned, never supplied by an HTTP client.
        row = (await session.execute(text(f'SELECT count(*), md5(coalesce(string_agg(row_to_json(t)::text, chr(10) ORDER BY row_to_json(t)::text), \'\')) FROM "{table}" t'))).one()
        result[table] = {'rows': row[0], 'digest': row[1]}
    return result


def validate_table_manifest(tables):
    if not isinstance(tables, dict):
        raise ValueError('Неполный манифест архива')
    known = set(Base.metadata.tables)
    for name, fingerprint in tables.items():
        if (not isinstance(name, str) or name not in known
                or not isinstance(fingerprint, dict)
                or set(fingerprint) != {'rows', 'digest'}
                or type(fingerprint['rows']) is not int or fingerprint['rows'] < 0
                or not isinstance(fingerprint['digest'], str)
                or not re.fullmatch(r'[a-f0-9]{32}', fingerprint['digest'])):
            raise ValueError('Некорректный манифест таблиц')
    return tables


async def create(database):
    await asyncio.to_thread(guard, database)
    backup_id = uuid4().hex
    async with database.transaction() as session:
        await session.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
        snapshot = await session.scalar(text('SELECT pg_export_snapshot()'))
        expected = await fingerprints(session)

        def capture():
            ROOT.mkdir(parents=True, exist_ok=True)
            target = path_for(backup_id)
            temporary = target.with_suffix('.part')
            manifest = {'id': backup_id, 'created_at': datetime.now(timezone.utc).isoformat(), 'database': DBNAME,
                        'format': 2, 'tables': expected, 'files': {}}
            try:
                raw = command(['pg_dump', '-U', ROLE, '-d', DBNAME, '--format=custom', '--no-owner', '--snapshot', snapshot])
                with zipfile.ZipFile(temporary, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
                    archive.writestr('database.dump', raw)
                    manifest['files']['database.dump'] = sha256(raw).hexdigest()
                    total = len(raw)
                    root = (WORKSPACE / '.local' / 'preview' / 'images').resolve()
                    if not root.is_relative_to(WORKSPACE) or root == WORKSPACE:
                        raise ValueError('Dev-каталог вне рабочей копии')
                    for path in sorted(root.rglob('*')):
                        if path.is_symlink() or not path.resolve().is_relative_to(root):
                            raise ValueError('Ссылки вне dev-каталога не архивируются')
                        if not path.is_file() or path.suffix.lower() not in {'.webp', '.png', '.jpg', '.jpeg'}:
                            continue
                        total += path.stat().st_size
                        if total > MAX_BYTES:
                            raise ValueError('Архив превышает локальный лимит 256 МиБ')
                        name = f'images/{path.relative_to(root).as_posix()}'
                        content = path.read_bytes(); archive.writestr(name, content)
                        manifest['files'][name] = sha256(content).hexdigest()
                    archive.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False))
                os.replace(temporary, target)
                return manifest
            finally:
                temporary.unlink(missing_ok=True)
        return await asyncio.to_thread(capture)


def read_verified(backup_id):
    path = path_for(backup_id)
    if not path.is_file():
        raise LookupError('Архив не найден')
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        if len(entries) > 50000 or sum(e.file_size for e in entries) > MAX_BYTES:
            raise ValueError('Архив превышает ограничения')
        names = [e.filename for e in entries]
        if len(names) != len(set(names)):
            raise ValueError('Повторяющиеся файлы архива')
        manifest = json.loads(archive.read('manifest.json'))
        if (manifest.get('id') != backup_id or manifest.get('database') != DBNAME
                or manifest.get('format') not in {1, 2}):
            raise ValueError('Неподдерживаемый архив')
        if not isinstance(manifest.get('files'), dict):
            raise ValueError('Неполный манифест архива')
        validate_table_manifest(manifest.get('tables'))
        if set(names) != set(manifest['files']) | {'manifest.json'}:
            raise ValueError('Состав архива не совпадает с манифестом')
        files = {}
        for name, digest in manifest['files'].items():
            if name != 'database.dump' and (not name.startswith(('questions/', 'images/')) or '\\' in name or ':' in name
                    or any(part in {'', '.', '..'} or part.endswith((' ', '.')) for part in name.split('/'))):
                raise ValueError('Недопустимый путь внутри архива')
            value = archive.read(name)
            if sha256(value).hexdigest() != digest:
                raise ValueError('Контрольная сумма архива не совпала')
            files[name] = value
        if 'database.dump' not in files:
            raise ValueError('В архиве отсутствует база данных')
        return manifest, files


def listing():
    result = []
    for path in sorted(ROOT.glob('*.zip'), reverse=True):
        try:
            with zipfile.ZipFile(path) as archive:
                info = archive.getinfo('manifest.json')
                if info.file_size > 5_000_000:
                    raise ValueError()
                manifest = json.loads(archive.read(info))
            result.append({'id': path.stem, 'created_at': manifest['created_at'], 'bytes': path.stat().st_size})
        except (ValueError, KeyError, OSError, zipfile.BadZipFile):
            result.append({'id': path.stem, 'error': 'Архив повреждён'})
    return sorted(result, key=lambda item: item.get('created_at', ''), reverse=True)


async def verify_restore(database, backup_id):
    await asyncio.to_thread(guard, database)
    manifest, files = await asyncio.to_thread(read_verified, backup_id)
    target = 'mqb_restore_' + uuid4().hex

    def restore_and_check():
        created = False
        try:
            command(['createdb', '-U', ROLE, '-T', 'template0', target]); created = True
            command(['pg_restore', '-U', ROLE, '-d', target, '--no-owner', '--exit-on-error'], raw=files['database.dump'])
            actual = {}
            for table in sorted(manifest['tables']):
                sql = f'SELECT count(*), md5(coalesce(string_agg(row_to_json(t)::text, chr(10) ORDER BY row_to_json(t)::text), \'\')) FROM "{table}" t'
                count, digest = command(['psql', '-U', ROLE, '-d', target, '-At', '-c', sql]).decode().strip().split('|')
                actual[table] = {'rows': int(count), 'digest': digest}
            if actual != manifest['tables']:
                raise ValueError('Восстановленные данные не совпали с исходным снимком')
            return {'id': backup_id, 'verified': True, 'tables': len(actual), 'files': len(files), 'dev_database_changed': False}
        finally:
            if created and re.fullmatch(r'mqb_restore_[a-f0-9]{32}', target):
                command(['dropdb', '-U', ROLE, target])
    return await asyncio.to_thread(restore_and_check)


def trash(backup_id):
    source = path_for(backup_id)
    if not source.is_file():
        raise LookupError('Архив не найден')
    destination = (ROOT / 'trash' / source.name).resolve()
    if not destination.is_relative_to(ROOT.resolve()):
        raise ValueError('Корзина вне разрешённого каталога')
    destination.parent.mkdir(exist_ok=True)
    if destination.exists():
        raise ValueError('Архив уже есть в корзине')
    source.rename(destination)
    return {'id': backup_id, 'removed_from_list': True, 'recoverable': True}


async def restore_dev(database, backup_id, *, confirmation):
    """Offline CLI only. PowerShell owns the exclusive dev lease and stopped-service guard."""
    if confirmation != DBNAME or os.getenv('MQB_DEV_RESTORE_ID') != backup_id:
        raise ValueError('Используйте Restore-LocalDevBackup.ps1 с явным подтверждением dev-БД')
    await asyncio.to_thread(guard, database)
    manifest, files = await asyncio.to_thread(read_verified, backup_id)
    safety = await create(database)
    _, previous_files = await asyncio.to_thread(read_verified, safety['id'])
    retained = ROOT / ('before-restore-' + uuid4().hex)
    moved = []
    def restore_database(raw):
        command(['pg_restore', '-U', ROLE, '-d', DBNAME, '--no-owner', '--clean', '--if-exists', '--single-transaction', '--exit-on-error'], raw=raw)
    try:
        await asyncio.to_thread(restore_database, files['database.dump'])
        await database.engine.dispose()  # Discard prepared statements tied to the replaced schema.
        # Format 1 archives contained the old file-backed bank. It is restored
        # only for backwards recovery; format 2 keeps the bank solely in PG.
        for name in (('questions', 'images') if manifest['format'] == 1 else ('images',)):
            destination = (WORKSPACE / '.local' / 'preview' / name).resolve()
            if not destination.is_relative_to(WORKSPACE / '.local') or destination == WORKSPACE / '.local':
                raise ValueError('Dev-каталог вне разрешённой области')
            retained.mkdir(parents=True, exist_ok=True)
            original = retained / name if destination.exists() else None
            if original:
                destination.rename(original)
            moved.append((destination, original))
            destination.mkdir(parents=True, exist_ok=True)
            for member, content in files.items():
                if not member.startswith(name + '/'):
                    continue
                path = (destination / member[len(name) + 1:]).resolve()
                if not path.is_relative_to(destination) or path == destination:
                    raise ValueError('Недопустимый путь файла архива')
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
        from sqlalchemy import delete, update
        from .models import MiniAppSession, QuizSession
        async with database.transaction() as session:
            # A restored login or stale game must not be silently resurrected.
            await session.execute(delete(MiniAppSession))
            await session.execute(update(QuizSession).where(QuizSession.status == 'active').values(status='interrupted'))
        return {'restored': backup_id, 'safety_backup': safety['id'], 'previous_files_retained': str(retained),
                'sessions_revoked': True, 'active_games_interrupted': True}
    except Exception:
        await asyncio.to_thread(restore_database, previous_files['database.dump'])
        await database.engine.dispose()
        for destination, original in moved:
            if destination.exists():
                destination.rename(retained / ('failed-' + destination.name))
            if original:
                original.rename(destination)
        raise


if __name__ == '__main__':
    import argparse
    from .database import Database, DatabaseSettings
    parser = argparse.ArgumentParser()
    parser.add_argument('operation', choices=['restore'])
    parser.add_argument('backup_id')
    parser.add_argument('--confirm', required=True)
    options = parser.parse_args()
    async def main():
        database = Database(DatabaseSettings.from_env())
        try:
            print(json.dumps(await restore_dev(database, options.backup_id, confirmation=options.confirm), ensure_ascii=False))
        finally:
            await database.dispose()
    asyncio.run(main())
