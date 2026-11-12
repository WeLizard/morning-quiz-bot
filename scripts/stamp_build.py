"""Stamp the deployed build: write build_info.json next to the deployed code.

The mini app reads the version shown in problem reports from this file
(storage/problem_reports.build_commit), so every deploy must end with a stamp.

    # after copying files to the sandbox
    python scripts/stamp_build.py --remote serverold:/home/lizard/mqb-rehearsal

    # local preview / inspect what would be written
    python scripts/stamp_build.py --print

`build` is the short HEAD commit. With --remote the script lists the runtime files on
the server (code, static files, migrations, minigames, requirements.txt) and compares
them with that commit, ignoring line endings. `-dirty` is appended when the server
differs: a file changed (`changed_files`), a file the commit lacks that git does not
ignore (`extra_files`) or a committed file absent on the server (`missing_files`).
Git-ignored files there (generated art, build outputs, local secrets) are only
counted in `ignored_files`. Without --remote the same check runs on the worktree.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
FILE_NAME = 'build_info.json'
# Code the deployed services load; data, tests, docs and dev scripts are not compared.
RUNTIME_DIRS = ('alembic', 'application', 'config', 'domain', 'handlers', 'minigames',
                'modules', 'qw_farm', 'storage', 'web')
RUNTIME_ROOT_FILES = ('alembic.ini', 'requirements.txt')  # plus top-level *.py

REMOTE_HASH = (
    'set -e; cd "$1"; shift; '
    '{ find "$@" -type f ! -path "*/__pycache__/*" ! -name "*.pyc" 2>/dev/null; '
    "find . -maxdepth 1 -type f \\( -name '*.py' -o -name alembic.ini -o -name requirements.txt \\) "
    "| sed 's|^\\./||'; } | while IFS= read -r f; do "
    "printf '%s\\t%s\\n' \"$(tr -d '\\r' < \"$f\" | md5sum | cut -c1-32)\" \"$f\"; done"
)


def run(*args: str, data: bytes | None = None, check: bool = True) -> bytes:
    return subprocess.run(list(args), cwd=ROOT, input=data, check=check, capture_output=True).stdout


def git_lines(*args: str, data: bytes | None = None, check: bool = True) -> list[str]:
    out = run('git', args[0], '-z', *args[1:], data=data, check=check)
    return [p.decode('utf-8') for p in out.split(b'\0') if p]


def digest(data: bytes) -> str:
    return hashlib.md5(data.replace(b'\r', b'')).hexdigest()


def is_runtime(path: str) -> bool:
    if '/' not in path:
        return path.endswith('.py') or path in RUNTIME_ROOT_FILES
    return path.split('/', 1)[0] in RUNTIME_DIRS and '/__pycache__/' not in path \
        and not path.endswith('.pyc')


def head_files() -> list[str]:
    return [f for f in git_lines('ls-tree', '-r', '--name-only', 'HEAD') if is_runtime(f)]


def head_hashes(files: list[str]) -> dict[str, str]:
    out = run('git', 'cat-file', '--batch', data=''.join(f'HEAD:{f}\n' for f in files).encode('utf-8'))
    hashes, pos = {}, 0
    for f in files:
        end = out.index(b'\n', pos)
        size = int(out[pos:end].split()[2])
        hashes[f] = digest(out[end + 1:end + 1 + size])
        pos = end + 1 + size + 1
    return hashes


def ignored(paths: list[str]) -> set[str]:
    if not paths:
        return set()
    # Exit code 1 only means "nothing ignored".
    return set(git_lines('check-ignore', '--no-index', '--stdin',
                         data=b'\0'.join(p.encode('utf-8') for p in paths), check=False))


def worktree_hashes() -> dict[str, str]:
    files = [f for f in git_lines('ls-files', '--cached', '--others', '--', *RUNTIME_DIRS, '.')
             if is_runtime(f)]
    hashes = {}
    for f in files:
        try:
            hashes[f] = digest((ROOT / f).read_bytes())
        except OSError:
            pass
    return hashes


def split_remote(target: str) -> tuple[str, str]:
    host, sep, directory = target.partition(':')
    if not sep or not host or not directory.startswith('/'):
        raise SystemExit('--remote must look like host:/absolute/app/dir')
    return host, directory.rstrip('/')


def quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def remote_hashes(host: str, directory: str) -> dict[str, str]:
    command = f'bash -c {quote(REMOTE_HASH)} _ {quote(directory)} ' + ' '.join(RUNTIME_DIRS)
    out = run('ssh', host, command)
    hashes = {}
    for line in out.decode('utf-8').splitlines():
        value, _, path = line.partition('\t')
        if path and is_runtime(path):
            hashes[path] = value
    return hashes


def build_info(deployed: dict[str, str]) -> dict:
    commit = run('git', 'rev-parse', '--short', 'HEAD').decode().strip()
    committed = head_files()
    head = head_hashes(committed)
    outside = sorted(set(deployed) - set(head))
    skipped = ignored(outside)
    changed = sorted(f for f in deployed if f in head and head[f] != deployed[f])
    extra = [f for f in outside if f not in skipped]
    missing = sorted(set(head) - set(deployed))
    dirty = bool(changed or extra or missing)
    return {
        'build': f'{commit}-dirty' if dirty else commit,
        'commit': commit,
        'dirty': dirty,
        'stamped_at': datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        'changed_files': changed,
        'extra_files': extra,
        'missing_files': missing,
        'ignored_files': len(skipped),
    }


def push_remote(host: str, directory: str, payload: str) -> None:
    path = quote(f'{directory}/{FILE_NAME}')
    tmp = quote(f'{directory}/{FILE_NAME}.tmp')
    run('ssh', host, f'cat > {tmp} && mv {tmp} {path}', data=payload.encode('utf-8'))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Write build_info.json for a deploy.')
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument('--remote', help='host:/app/dir: compare the files there and write the stamp over ssh')
    target.add_argument('--out', type=Path, help='local path to write the stamp of the worktree to')
    target.add_argument('--print', action='store_true', help='only print the stamp of the worktree')
    args = parser.parse_args(argv)

    remote = split_remote(args.remote) if args.remote else None
    deployed = remote_hashes(*remote) if remote else worktree_hashes()
    if not deployed:
        raise SystemExit(f'no runtime files found in {args.remote or ROOT}')
    payload = json.dumps(build_info(deployed), ensure_ascii=False, indent=2) + '\n'
    if remote:
        push_remote(*remote, payload)
    elif args.out:
        args.out.write_text(payload, encoding='utf-8')
    sys.stdout.write(payload)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
