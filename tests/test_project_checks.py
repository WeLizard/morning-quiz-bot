"""Repository gates are exercised in isolated temporary repositories only."""
import importlib.util
import io
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "project_checks.py"
spec = importlib.util.spec_from_file_location("project_checks", SCRIPT)
checks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checks)
installer_spec = importlib.util.spec_from_file_location("install_project_hooks", SCRIPT.with_name("install_project_hooks.py"))
installer = importlib.util.module_from_spec(installer_spec)
installer_spec.loader.exec_module(installer)


class ProjectChecksTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git("init", "-q")
        self.git("config", "user.name", "Gate Test")
        self.git("config", "user.email", "gate@example.invalid")
        self.git("config", "core.autocrlf", "false")
        self.git("config", "core.hooksPath", str(self.root / "no-hooks"))
        self.write("README.md", "test\n")
        self.commit()

    def git(self, *args):
        result = subprocess.run(["git", "-C", str(self.root), *args], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def commit(self):
        self.git("add", "--all")
        self.git("commit", "-qm", "fixture")
        return self.git("rev-parse", "HEAD")

    def push(self, local, remote, remote_name=None, remote_url=None):
        return checks.check_push(self.root, io.StringIO(
            f"refs/heads/test {local} refs/heads/test {remote}\n"), remote_name, remote_url)

    def test_staged_blob_not_worktree(self):
        self.write("domain/model.py", "import telegram\n")
        self.git("add", "domain/model.py")
        self.write("domain/model.py", "value = 1\n")
        self.assertTrue(checks.check_staged(self.root))
        self.assertFalse(checks.check_worktree(self.root))
        self.git("add", "domain/model.py")
        self.write("domain/model.py", "broken (\n")
        self.assertFalse(checks.check_staged(self.root))
        self.assertTrue(checks.check_worktree(self.root))

    def test_layer_boundaries(self):
        for path, source in [("domain/a.py", "from storage import thing\n"),
                             ("domain/b.py", "from sqlalchemy.orm import Session\n"),
                             ("application/a.py", "from handlers import thing\n"),
                             ("application/b.py", "from fastapi import FastAPI\n")]:
            with self.subTest(path=path):
                self.assertTrue(checks.check_file(path, b"", source.encode(), True))
        self.assertFalse(checks.check_file("application/c.py", b"", b"import storage\n", True))
        self.assertFalse(checks.check_file("domain/c.py", b"", b"import pathlib\n", True))

    def test_bridge_new_lines_only_and_fixture_exemptions(self):
        baseline = b"value = MiniBridge()\n"
        self.assertFalse(checks.check_file("web/api.py", baseline, baseline + b"x = 1\n", False))
        for token in checks.BRIDGE:
            source = ("value = " + token + "()\n").encode()
            self.assertTrue(checks.check_file("web/api.py", b"", source, True))
            self.assertFalse(checks.check_file("tests/api.py", b"", source, True))
            self.assertFalse(checks.check_file("fixtures/api.py", b"", source, True))

    def test_javascript_bridge_staged_and_range(self):
        base = self.git("rev-parse", "HEAD")
        for suffix in (".js", ".mjs", ".cjs"):
            self.write("web/bridge" + suffix, "const bridge = new MiniBridge();\n")
        self.git("add", "--all")
        self.assertEqual(len(checks.check_staged(self.root)), 3)
        head = self.commit()
        self.assertEqual(len(checks.check_range(self.root, base, head)), 3)
        self.assertEqual(len(checks.check_worktree(self.root)), 0)

    def test_secret_paths_never_print_contents(self):
        secret = "DO_NOT_DISPLAY_SECRET"
        for name in (".env", ".env.production", "backups/dump.json", "data/chats/a.json",
                     "data/system/a.json", "cache.pkl", "cache.pickle"):
            with self.subTest(name=name):
                errors = checks.check_file(name, b"", secret.encode(), True)
                self.assertTrue(errors)
                self.assertNotIn(secret, " ".join(errors))
        self.assertFalse(checks.check_file(".env.example", b"", b"TOKEN=example\n", True))
        self.assertFalse(checks.check_file("env.example", b"", b"TOKEN=example\n", True))

    def test_worktree_includes_untracked_and_excludes_ignored(self):
        self.write(".gitignore", "ignored/\n")
        self.write("ignored/bad.py", "bad (\n")
        self.assertFalse(checks.check_worktree(self.root))
        self.write("scripts/new_governance.py", "bad (\n")
        self.assertTrue(checks.check_worktree(self.root))

    def test_range_and_deleted_python(self):
        self.write("legacy.py", "bad (\n")
        base = self.commit()
        self.git("rm", "legacy.py")
        self.assertFalse(checks.check_staged(self.root))
        head = self.commit()
        self.assertFalse(checks.check_range(self.root, base, head))
        self.write("new.py", "bad (\n")
        bad = self.commit()
        self.assertTrue(checks.check_range(self.root, head, bad))

    def test_push_diverged_refs_and_reverted_violation(self):
        base = self.git("rev-parse", "HEAD")
        self.git("checkout", "-qb", "remote")
        self.write("remote.py", "x = 1\n")
        remote = self.commit()
        self.git("checkout", "-qb", "local", base)
        self.write("domain/new.py", "import telegram\n")
        self.commit()
        self.write("domain/new.py", "x = 1\n")
        local = self.commit()
        self.assertTrue(self.push(local, remote))
        self.assertFalse(self.push(checks.ZERO, remote))

    def test_new_branch_excludes_known_remote_history(self):
        self.write("old.py", "bad (\n")
        old = self.commit()
        self.git("remote", "add", "origin", "https://example.invalid/origin.git")
        self.git("update-ref", "refs/remotes/origin/main", old)
        self.write("good.py", "x = 1\n")
        local = self.commit()
        self.assertFalse(self.push(local, checks.ZERO, "origin", "https://example.invalid/origin.git"))
        self.git("update-ref", "-d", "refs/remotes/origin/main")
        self.assertTrue(self.push(local, checks.ZERO, "origin", "https://example.invalid/origin.git"))

    def test_new_branch_does_not_exclude_unrelated_remote(self):
        self.git("remote", "add", "origin", "https://example.invalid/origin.git")
        self.git("remote", "add", "unrelated", "https://example.invalid/unrelated.git")
        self.write("domain/bad.py", "import telegram\n")
        local = self.commit()
        self.git("update-ref", "refs/remotes/unrelated/main", local)
        self.assertTrue(self.push(local, checks.ZERO, "origin", "https://example.invalid/origin.git"))
        self.assertTrue(self.push(local, checks.ZERO, "https://example.invalid/new.git"))

    def test_distinct_push_destination_cannot_use_fetch_history(self):
        self.git("remote", "add", "origin", "source.git")
        self.git("config", "remote.origin.pushurl", "destination.git")
        self.write("domain/bad.py", "import telegram\n")
        local = self.commit()
        self.git("update-ref", "refs/remotes/origin/main", local)
        self.assertTrue(self.push(local, checks.ZERO, "origin", "destination.git"))
        # Missing destination and multiple configured URLs are conservative too.
        self.assertTrue(self.push(local, checks.ZERO, "origin"))
        self.git("config", "--unset", "remote.origin.pushurl")
        self.git("config", "--add", "remote.origin.url", "other-source.git")
        self.assertTrue(self.push(local, checks.ZERO, "origin", "source.git"))

    def test_operational_python_is_rejected_without_reading_blob(self):
        base = self.git("rev-parse", "HEAD")
        self.write("backups/secret.py", "SECRET_VALUE\n")
        self.git("add", "--all")
        with patch.object(checks, "blob", side_effect=AssertionError("secret blob read")):
            self.assertTrue(checks.check_staged(self.root))
        head = self.commit()
        with patch.object(checks, "blob", side_effect=AssertionError("secret blob read")):
            self.assertTrue(checks.check_range(self.root, base, head))
        # A new untracked operational Python file must not be read either.
        (self.root / "backups/secret.py").unlink()
        self.write("backups/new.py", "SECRET_VALUE\n")
        with patch.object(Path, "read_bytes", side_effect=AssertionError("secret file read")):
            self.assertTrue(checks.check_worktree(self.root))

    def test_unavailable_remote_commit_fails_without_fetch(self):
        with self.assertRaises(ValueError):
            self.push(self.git("rev-parse", "HEAD"), "1" * 40)

    def run_installer(self):
        self.write(".githooks/pre-commit", "#!/bin/sh\n")
        self.write(".githooks/pre-push", "#!/bin/sh\n")
        return subprocess.run([sys.executable, str(SCRIPT.with_name("install_project_hooks.py"))],
                              cwd=self.root, capture_output=True, text=True)

    def test_installer_refuses_custom_setting(self):
        configured = self.git("config", "--local", "--get", "core.hooksPath")
        self.assertEqual(self.run_installer().returncode, 1)
        self.assertEqual(self.git("config", "--local", "--get", "core.hooksPath"), configured)

    def test_installer_refuses_existing_hook_then_is_idempotent(self):
        self.git("config", "--local", "--unset", "core.hooksPath")
        self.write(".git/hooks/pre-commit", "#!/bin/sh\nexit 0\n")
        self.assertEqual(self.run_installer().returncode, 1)
        (self.root / ".git/hooks/pre-commit").unlink()
        self.assertEqual(self.run_installer().returncode, 0)
        self.assertEqual(self.run_installer().returncode, 0)
        self.assertEqual(self.git("config", "--local", "--get", "core.hooksPath"), ".githooks")

    def test_installer_sets_posix_executable_bits_without_index_mutation(self):
        fake_path = Mock()
        fake_path.stat.return_value.st_mode = 0o100644
        with patch.object(installer.os, "name", "posix"):
            installer.ensure_executable(fake_path)
        fake_path.chmod.assert_called_once_with(0o100755)
        if installer.os.name == "posix":
            self.git("config", "--local", "--unset", "core.hooksPath")
            before = self.git("ls-files", "--stage")
            self.assertEqual(self.run_installer().returncode, 0)
            for name in ("pre-commit", "pre-push"):
                self.assertEqual((self.root / ".githooks" / name).stat().st_mode & 0o111, 0o111)
            self.assertEqual(self.git("ls-files", "--stage"), before)

    def test_hook_files_use_lf(self):
        for name in ("pre-commit", "pre-push"):
            data = (SCRIPT.parents[1] / ".githooks" / name).read_bytes()
            self.assertNotIn(b"\r", data)
            self.assertTrue(data.startswith(b"#!/bin/sh\n"))


if __name__ == "__main__":
    unittest.main()
