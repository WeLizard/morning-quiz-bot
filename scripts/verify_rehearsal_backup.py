"""Restore a retained rehearsal backup inside a private, disposable local PG17.

No network, published port, app process, existing database or server-side writer.
The dump travels through memory; only hashes/counts are written to the report.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shlex
import subprocess
import time
from uuid import uuid4


def checked(args, *, data=None):
    result = subprocess.run(args, input=data, capture_output=True)
    if result.returncode:
        raise RuntimeError(f'{args[0]} {args[1]} failed (exit {result.returncode})')
    return result.stdout


def run(args):
    path = PurePosixPath(args.backup)
    prefix = PurePosixPath('/home/lizard/mqb-rehearsal/backups')
    if not path.is_relative_to(prefix) or '..' in path.parts or path.suffix != '.dump':
        raise ValueError('Only an explicitly named retained rehearsal .dump is allowed')
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    ssh = ['C:/Windows/System32/OpenSSH/ssh.exe', '-F', 'NUL', '-o', 'BatchMode=yes',
           '-o', 'ConnectTimeout=8', 'lizard@192.168.0.33']
    expected = checked(ssh + ['sha256sum ' + shlex.quote(str(path))]).decode().split()[0]
    dump = checked(ssh + ['cat ' + shlex.quote(str(path))])
    actual = hashlib.sha256(dump).hexdigest()
    if actual != expected:
        raise RuntimeError('Backup transfer checksum mismatch')

    name = 'mqb-restore-verify-' + uuid4().hex[:12]
    dbname = 'mqb_rehearsal_restore_check'
    container_id = None
    report = {'backup': str(path), 'sha256': actual, 'dump_bytes': len(dump),
              'network': 'none', 'database': dbname, 'restore_passed': False,
              'container_removed': False}
    try:
        container_id = checked(['docker', 'run', '-d', '--network', 'none', '--name', name,
            '-e', 'POSTGRES_HOST_AUTH_METHOD=trust', 'postgres:17-alpine']).decode().strip()
        for _ in range(60):
            ready = subprocess.run(['docker', 'exec', name, 'psql', '-U', 'postgres', '-X', '-Atc',
                "SELECT current_setting('listen_addresses') <> ''"], capture_output=True)
            if ready.returncode == 0 and ready.stdout.strip() == b't':
                break
            time.sleep(.5)
        else:
            raise RuntimeError('Disposable PostgreSQL did not become ready')
        info = json.loads(checked(['docker', 'inspect', name]))[0]
        assert info['Id'] == container_id and info['HostConfig']['NetworkMode'] == 'none'
        assert not info['HostConfig'].get('PortBindings')
        checked(['docker', 'exec', name, 'createdb', '-U', 'postgres', dbname])
        checked(['docker', 'exec', '-i', name, 'pg_restore', '-U', 'postgres',
                 '--no-owner', '--no-acl', '--exit-on-error', '--dbname', dbname], data=dump)
        del dump

        def sql(query):
            return checked(['docker', 'exec', name, 'psql', '-U', 'postgres', '-d', dbname,
                '-X', '-At', '-v', 'ON_ERROR_STOP=1', '-c', query]).decode().strip()

        report['schema_version'] = sql('SELECT version_num FROM alembic_version ORDER BY version_num')
        from alembic.config import Config
        from alembic.script import ScriptDirectory
        root = Path(__file__).resolve().parents[1]
        config = Config(str(root / 'alembic.ini'))
        config.set_main_option('script_location', str(root / 'alembic'))
        report['checkout_schema_heads'] = ScriptDirectory.from_config(config).get_heads()
        report['schema_matches_checkout'] = report['schema_version'].splitlines() == sorted(report['checkout_schema_heads'])
        report['unvalidated_foreign_keys'] = int(sql("SELECT count(*) FROM pg_constraint WHERE contype='f' AND NOT convalidated"))
        assert report['unvalidated_foreign_keys'] == 0
        report['tables'] = {}
        for table in ['accounts', 'users', 'rooms', 'games', 'game_commands', 'score_events',
                      'farm_states', 'alchemy_progress', 'problem_reports']:
            assert sql(f"SELECT to_regclass('public.{table}') IS NOT NULL") == 't', table
            row = sql(f"SELECT count(*),md5(COALESCE(string_agg(md5(to_jsonb(t)::text),'' "
                      f"ORDER BY md5(to_jsonb(t)::text)),'')) FROM public.{table} t")
            count, fingerprint = row.split('|')
            report['tables'][table] = {'rows': int(count), 'fingerprint': fingerprint}
        report['restore_passed'] = True
    finally:
        if container_id:
            actual_id = checked(['docker', 'inspect', name, '--format', '{{.Id}}']).decode().strip()
            if actual_id != container_id:
                raise RuntimeError('Disposable container identity changed; refusing cleanup')
            checked(['docker', 'stop', name])
            checked(['docker', 'rm', '-v', name])
            report['container_removed'] = True
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup', required=True)
    parser.add_argument('--report', required=True)
    run(parser.parse_args())
