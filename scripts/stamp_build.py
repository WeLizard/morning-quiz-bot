"""Stamp the deployed build: write build_info.json next to the deployed code.

The mini app reads the version shown in problem reports from this file
(storage/problem_reports.build_commit), so every deploy must end with a stamp.

    # after copying files to the sandbox
    python scripts/stamp_build.py --remote serverold:/home/lizard/mqb-rehearsal

    # local preview / inspect what would be written
    python scripts/stamp_build.py --print

`build` is the short HEAD commit. With --remote the script compares every runtime
file that exists on the server with that commit (line endings ignored) and appends
`-dirty` when any differs, listing them in `changed_files`: deploys copy files from
the working tree, so the server may hold changes no commit has. Locally the same
check runs against the worktree.
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
RUNTIME_ROOT_FILES = (':(glob)*.py', 'alembic.ini', 'requirements.txt')

REMOTE_HASH = (
    "set -e; cd \"$1\"; while IFS= read -r f; do "
    "[ -f \"$f\" ] && printf '%s\\t%s\\n' \"$(tr -d '\\r' < \"$f\" | md5sum | cut -c1-32)\" \"$f\"; "
    "done; true"
)


def git(*args: str) -> str:
    return subprocess.run(['git', *args], cwd=ROOT, check=True, capture_output=True,
                          text=True, encoding='utf-8').stdout.rstrip('\n')


def digest(data: bytes) -> str:
    return hashlib.md5(data.replace(b'\r', b'')).hexdigest()


def runtime_files() -> list[str]:
    out = subprocess.run(['git', 'ls-files', '-z', '--', *RUNTIME_DIRS, *RUNTIME_ROOT_FILES],
                         cwd=ROOT, check=True, capture_output=True).stdout
    files = [p.decode('utf-8') for p in out.split(b'\0') if p]
    return [f for f in files if '/' in f or not f.startswith('.')]


def head_hashes(files: list[str]) -> dict[str, str]:
    request = ''.join(f'HEAD:{f}\n' for f in files).encode('utf-8')
    out = subprocess.run(['git', 'cat-file', '--batch'], cwd=ROOT, input=request,
                         check=True, capture_output=True).stdout
    hashes, pos = {}, 0
    for f in files:
        end = out.index(b'\n', pos)
        header = out[pos:end].split()
        size = int(header[2])
        hashes[f] = digest(out[end + 1:end + 1 + size])
        pos = end + 1 + size + 1
    return hashes


def worktree_hashes(files: list[str]) -> dict[str, str]:
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


def remote_hashes(host: str, directory: str, files: list[str]) -> dict[str, str]:
    # Bytes, not text mode: on Windows text mode turns '\n' into '\r\n' in the file list.
    out = subprocess.run(['ssh', host, f'bash -c {quote(REMOTE_HASH)} _ {quote(directory)}'],
                         input=''.join(f + '\n' for f in files).encode('utf-8'), check=True,
                         capture_output=True).stdout
    hashes = {}
    for line in out.decode('utf-8').splitlines():
        value, _, path = line.partition('\t')
        if path:
            hashes[path] = value
    return hashes


def quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def build_info(deployed: dict[str, str]) -> dict:
    commit = git('rev-parse', '--short', 'HEAD').strip()
    head = head_hashes(sorted(deployed))
    changed = sorted(f for f, value in deployed.items() if head.get(f) != value)
    return {
        'build': f'{commit}-dirty' if changed else commit,
        'commit': commit,
        'dirty': bool(changed),
        'stamped_at': datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        'changed_files': changed,
    }


def push_remote(host: str, directory: str, payload: str) -> None:
    path = quote(f'{directory}/{FILE_NAME}')
    tmp = quote(f'{directory}/{FILE_NAME}.tmp')
    subprocess.run(['ssh', host, f'cat > {tmp} && mv {tmp} {path}'],
                   input=payload.encode('utf-8'), check=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Write build_info.json for a deploy.')
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument('--remote', help='host:/app/dir: compare the files there and write the stamp over ssh')
    target.add_argument('--out', type=Path, help='local path to write the stamp of the worktree to')
    target.add_argument('--print', action='store_true', help='only print the stamp of the worktree')
    args = parser.parse_args(argv)

    files = runtime_files()
    remote = split_remote(args.remote) if args.remote else None
    if remote:
        deployed = remote_hashes(*remote, files)
        if not deployed:
            raise SystemExit(f'no runtime files found in {args.remote}')
    else:
        deployed = worktree_hashes(files)
    payload = json.dumps(build_info(deployed), ensure_ascii=False, indent=2) + '\n'
    if remote:
        push_remote(*remote, payload)
    elif args.out:
        args.out.write_text(payload, encoding='utf-8')
    sys.stdout.write(payload)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
