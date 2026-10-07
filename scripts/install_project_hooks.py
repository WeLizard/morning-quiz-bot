#!/usr/bin/env python3
"""Opt-in installation of the repository's hooks, without replacing custom hooks."""
import subprocess
import os
import stat
import sys
from pathlib import Path


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True)


def ensure_executable(path):
    if os.name == "posix":
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def main():
    result = git("rev-parse", "--show-toplevel")
    if result.returncode:
        print("Run this installer inside the project repository.", file=sys.stderr)
        return 1
    root = Path(result.stdout.strip())
    hooks = root / ".githooks"
    if any(not (hooks / name).is_file() for name in ("pre-commit", "pre-push")):
        print("Project hook files are missing.", file=sys.stderr)
        return 1
    configured = git("config", "--get-all", "core.hooksPath")
    values = configured.stdout.splitlines()
    if any(value != ".githooks" for value in values):
        print("Refusing to replace an existing core.hooksPath setting.", file=sys.stderr)
        return 1
    default = git("rev-parse", "--git-path", "hooks")
    default_path = Path(default.stdout.strip())
    if not default_path.is_absolute():
        default_path = Path.cwd() / default_path
    if not values and default_path.exists() and any(
            entry.is_file() and not entry.name.endswith(".sample") for entry in default_path.iterdir()):
        print("Refusing to bypass existing Git hooks.", file=sys.stderr)
        return 1
    try:
        for name in ("pre-commit", "pre-push"):
            ensure_executable(hooks / name)
    except OSError:
        print("Could not make project hooks executable.", file=sys.stderr)
        return 1
    result = git("config", "--local", "core.hooksPath", ".githooks")
    if result.returncode:
        print("Could not install project hooks.", file=sys.stderr)
        return 1
    print("Installed local core.hooksPath=.githooks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
