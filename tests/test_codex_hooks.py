"""Lifecycle hook protocol tests without app imports, credentials or databases."""
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location(
    "mqb_codex_hook", Path(__file__).resolve().parents[1] / "scripts" / "codex_project_hook.py"
)
HOOK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HOOK)


class CodexHookTests(unittest.TestCase):
    def test_start_from_subdirectory_uses_repository(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            child = root / "child"
            child.mkdir()
            with patch.object(HOOK.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, str(root))):
                result = HOOK.response({"hook_event_name": "SessionStart", "cwd": str(child)}, root)
            self.assertEqual(result["hookSpecificOutput"]["hookEventName"], "SessionStart")

    def test_foreign_repository_never_runs_checker(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch.object(HOOK.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, str(root / "foreign"))) as run:
                result = HOOK.response({"hook_event_name": "Stop", "cwd": temp}, root)
            self.assertIn("differs", result["systemMessage"])
            self.assertEqual(run.call_count, 1)

    def test_failure_is_advisory_even_on_continuation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            replies = [subprocess.CompletedProcess([], 0, temp), subprocess.CompletedProcess([], 1, b"", b"domain/x.py: forbidden dependency")]
            with patch.object(HOOK.subprocess, "run", side_effect=replies):
                result = HOOK.response({"hook_event_name": "Stop", "cwd": temp, "stop_hook_active": True}, root)
            self.assertIn("failed", result["systemMessage"])
            self.assertNotIn("decision", result)
            self.assertNotIn("continue", result)

    def test_timeout_is_not_success(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(HOOK.subprocess, "run", side_effect=subprocess.TimeoutExpired("git", 5)):
                result = HOOK.response({"hook_event_name": "Stop", "cwd": temp}, Path(temp))
            self.assertIn("unverified", result["systemMessage"])

    def test_malformed_input_is_valid_json_response(self):
        result = subprocess.run([sys.executable, str(Path(HOOK.__file__))], input=b"not json", capture_output=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn("invalid event", json.loads(result.stdout)["systemMessage"])


if __name__ == "__main__":
    unittest.main()
