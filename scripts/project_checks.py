#!/usr/bin/env python3
"""Fast, read-only repository gates. Uses Git blobs, never imports the app."""
import argparse
import ast
import difflib
import subprocess
import sys
from pathlib import Path, PurePosixPath

ZERO = "0" * 40
EMPTY = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
BRIDGE = ("MiniBridge", "Update.de_json", "process_update")
SOURCE_SUFFIXES = (".py", ".js", ".mjs", ".cjs")


def git(root, *args, ok=False):
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True)
    if result.returncode and not ok:
        # Git output can include blob contents; never forward it.
        raise ValueError("Git operation failed: " + args[0])
    return result.stdout if not result.returncode else b""


def paths(raw):
    return [p.decode("utf-8", "surrogateescape") for p in raw.split(b"\0") if p]


def blob(root, ref, path):
    return git(root, "show", ref + ":" + path, ok=True)


def operational(path):
    parts = PurePosixPath(path.lower()).parts
    name = parts[-1]
    return (name == ".env" or name.startswith(".env.") and name != ".env.example"
            or "backups" in parts or "backup" in parts
            or any(parts[i:i + 2] in (("data", "chats"), ("data", "system"))
                   for i in range(len(parts) - 1))
            or name.endswith((".pickle", ".pkl")))


def additions(old, new):
    a, b = old.splitlines(), new.splitlines()
    for tag, _, _, begin, end in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag in ("insert", "replace"):
            yield from b[begin:end]


def check_file(path, old, new, is_new):
    errors = []
    if is_new and operational(path):
        errors.append(path + ": prohibited operational data/secret path")
        return errors  # Do not even decode operational data.
    parts = PurePosixPath(path).parts
    runtime = parts[0] not in ("tests", "scripts", "docs", ".codex", ".agents") and "fixtures" not in parts
    if path.endswith(SOURCE_SUFFIXES) and runtime and any(
            token.encode() in line for line in additions(old, new) for token in BRIDGE):
        errors.append(path + ": new legacy bridge code is prohibited")
    if not path.endswith(".py"):
        return errors
    try:
        tree = ast.parse(new, filename=path)
    except (SyntaxError, ValueError, UnicodeError) as exc:
        errors.append(path + ": invalid Python syntax (line " + str(getattr(exc, "lineno", "?")) + ")")
        return errors
    layer = PurePosixPath(path).parts[0]
    forbidden = {"telegram", "fastapi", "handlers", "web"}
    if layer == "domain":
        forbidden |= {"storage", "sqlalchemy"}
    if layer in ("domain", "application"):
        for node in ast.walk(tree):
            modules = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
                if not node.module:
                    modules.extend(alias.name for alias in node.names)
            if any(set(module.split(".")) & forbidden for module in modules):
                errors.append(path + ": forbidden " + layer + " dependency at line " + str(node.lineno))
    return errors


def check_range(root, base, head):
    changed = paths(git(root, "diff", "--name-only", "-z", "--no-renames", "--diff-filter=ACMT", base, head, "--"))
    existing = set(paths(git(root, "ls-tree", "-r", "--name-only", "-z", base)))
    errors = []
    for path in changed:
        if path not in existing and operational(path) or not path.endswith(SOURCE_SUFFIXES):
            errors.extend(check_file(path, b"", b"", path not in existing))
            continue
        errors.extend(check_file(path, blob(root, base, path), blob(root, head, path), path not in existing))
    return errors


def check_staged(root):
    changed = paths(git(root, "diff", "--cached", "--name-only", "-z", "--no-renames", "--diff-filter=ACMT", "--"))
    existing = set(paths(git(root, "ls-tree", "-r", "--name-only", "-z", "HEAD", ok=True)))
    errors = []
    for path in changed:
        if path not in existing and operational(path) or not path.endswith(SOURCE_SUFFIXES):
            errors.extend(check_file(path, b"", b"", path not in existing))
        else:
            errors.extend(check_file(path, blob(root, "HEAD", path), blob(root, "", path), path not in existing))
    return errors


def check_worktree(root):
    tracked = set(paths(git(root, "ls-files", "-z")))
    untracked = set(paths(git(root, "ls-files", "--others", "--exclude-standard", "-z")))
    existing = set(paths(git(root, "ls-tree", "-r", "--name-only", "-z", "HEAD", ok=True)))
    errors = []
    for path in sorted(tracked | untracked):
        file = root / path
        if file.is_file():
            if path not in existing and operational(path) or not path.endswith(SOURCE_SUFFIXES):
                errors.extend(check_file(path, b"", b"", path not in existing))
                continue
            errors.extend(check_file(path, blob(root, "HEAD", path), file.read_bytes(), path not in existing))
    return errors


def check_push(root, stream, remote_name=None, remote_url=None):
    errors, seen = [], set()
    # Only the destination remote is evidence of already published history.
    known = git(root, "remote").decode().splitlines()
    exclusions = []
    same_destination = False
    if remote_name in known and remote_url is not None:
        fetch_urls = git(root, "remote", "get-url", "--all", remote_name).decode().splitlines()
        push_urls = git(root, "remote", "get-url", "--push", "--all", remote_name).decode().splitlines()
        same_destination = (len(fetch_urls) == len(push_urls) == 1
                            and fetch_urls[0] == push_urls[0] == remote_url)
    if same_destination:
        exclusions = ["^" + oid.decode("ascii") for oid in git(
            root, "for-each-ref", "--format=%(objectname)",
            "refs/remotes/" + remote_name + "/").splitlines()]
    for line in stream:
        fields = line.split()
        if len(fields) != 4:
            raise ValueError("Invalid pre-push input")
        _, local, remote_ref, remote = fields
        if set(local) == {"0"}:  # Deleted remote ref.
            continue
        git(root, "rev-parse", "--verify", local + "^{commit}")
        if set(remote) == {"0"}:
            # URL/unconfigured remotes have no known history: inspect all ancestors.
            commits = git(root, "rev-list", local, *exclusions).splitlines()
        else:
            git(root, "rev-parse", "--verify", remote + "^{commit}")
            commits = git(root, "rev-list", local, "^" + remote).splitlines()
        for raw in commits:
            commit = raw.decode("ascii")
            if commit in seen:
                continue
            seen.add(commit)
            parents = git(root, "rev-list", "--parents", "-n", "1", commit).decode().split()[1:]
            errors.extend(check_range(root, parents[0] if parents else EMPTY, commit))
    return errors


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--staged", action="store_true")
    modes.add_argument("--worktree", action="store_true")
    modes.add_argument("--pre-push", action="store_true")
    parser.add_argument("--base")
    parser.add_argument("--head")
    parser.add_argument("--remote", help="Destination remote name supplied by Git pre-push")
    parser.add_argument("--remote-url", help="Destination URL supplied by Git pre-push")
    args = parser.parse_args(argv)
    if bool(args.base) != bool(args.head) or args.base and (args.staged or args.worktree or args.pre_push):
        parser.error("--base and --head must be used together, without other modes")
    if (args.remote is not None or args.remote_url is not None) and not args.pre_push:
        parser.error("--remote and --remote-url require --pre-push")
    try:
        root = Path(git(Path.cwd(), "rev-parse", "--show-toplevel").decode().strip())
        if args.base:
            errors = check_range(root, args.base, args.head)
        elif args.pre_push:
            errors = check_push(root, sys.stdin, args.remote, args.remote_url)
        elif args.staged:
            errors = check_staged(root)
        else:
            errors = check_worktree(root)
        for error in sorted(set(errors)):
            print(error, file=sys.stderr)
        return bool(errors)
    except (ValueError, OSError):
        print("Project checks failed: cannot read requested repository state.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
