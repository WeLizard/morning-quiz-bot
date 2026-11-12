"""Stamp the deployed build: write build_info.json next to the deployed code.

The mini app reads the version shown in problem reports from this file
(storage/problem_reports.build_commit), so every deploy must end with a stamp.

    # after copying files to the sandbox
    python scripts/stamp_build.py --remote serverold:/home/lizard/mqb-rehearsal \
        --files qw_farm/static/app.js web/mini_app.py

    # local preview / inspect what would be written
    python scripts/stamp_build.py --print

`build` is the short HEAD commit; `-dirty` is appended when the deployed files
(or, without --files, the whole worktree) differ from that commit, because
deploys copy files from the working tree, not from a clean checkout.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
FILE_NAME = 'build_info.json'


def git(*args: str) -> str:
    return subprocess.run(['git', *args], cwd=ROOT, check=True, capture_output=True,
                          text=True, encoding='utf-8').stdout.rstrip('\n')


def build_info(files: list[str]) -> dict:
    commit = git('rev-parse', '--short', 'HEAD').strip()
    status = git('status', '--porcelain', '--untracked-files=all', '--', *files) if files \
        else git('status', '--porcelain', '--untracked-files=no')
    changed = sorted({line[3:].split(' -> ')[-1].strip('"') for line in status.splitlines() if line})
    info = {
        'build': f'{commit}-dirty' if changed else commit,
        'commit': commit,
        'dirty': bool(changed),
        'stamped_at': datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }
    if files:
        info['changed_files'] = changed
    return info


def push_remote(target: str, payload: str) -> None:
    host, sep, directory = target.partition(':')
    if not sep or not host or not directory.startswith('/'):
        raise SystemExit('--remote must look like host:/absolute/app/dir')
    path = f"{directory.rstrip('/')}/{FILE_NAME}"
    command = f"cat > '{path}.tmp' && mv '{path}.tmp' '{path}'"
    subprocess.run(['ssh', host, command], input=payload, text=True, encoding='utf-8', check=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Write build_info.json for a deploy.')
    parser.add_argument('--files', nargs='*', default=[],
                        help='deployed paths (relative to the repo); dirty is checked on them only')
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument('--remote', help='host:/app/dir to write build_info.json into over ssh')
    target.add_argument('--out', type=Path, help='local path to write the file to')
    target.add_argument('--print', action='store_true', help='only print the stamp')
    args = parser.parse_args(argv)

    payload = json.dumps(build_info(args.files), ensure_ascii=False, indent=2) + '\n'
    if args.remote:
        push_remote(args.remote, payload)
    elif args.out:
        args.out.write_text(payload, encoding='utf-8')
    sys.stdout.write(payload)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
