"""Read-only Codex context and advisory Stop checks; no app imports or secrets."""
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def response(event, root=ROOT):
    name = event.get("hook_event_name")
    if name not in {"SessionStart", "Stop"}:
        return {}
    cwd = event.get("cwd")
    if not isinstance(cwd, str) or not Path(cwd).is_dir():
        return {"systemMessage": "MQB hook: no valid workspace; checks not run."}
    try:
        located = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=5, check=True,
        )
        if Path(located.stdout.strip()).resolve() != root.resolve():
            return {"systemMessage": "MQB hook: workspace differs from hook repository; checks not run."}
        if name == "SessionStart":
            return {"hookSpecificOutput": {
                "hookEventName": name,
                "additionalContext": (
                    "Morning Quiz project: read AGENTS.md and the relevant skill in .agents/skills. "
                    "Development and release criteria live in docs/engineering/. "
                    "Standalone, Mafia and Alchemy readiness require current user-scenario evidence; "
                    "historical test counts are not proof. Preserve pre-existing changes. "
                    "Use the dev checkout; production cutover requires explicit user authorization. "
                    "These hooks grant no permissions and do not establish product readiness."
                ),
            }}
        result = subprocess.run(
            [sys.executable, str(root / "scripts" / "project_checks.py"), "--worktree"],
            cwd=root, capture_output=True, timeout=20,
        )
        if result.returncode:
            # The checker only emits paths and fixed diagnostics, never source/secret values.
            detail = result.stderr.decode("utf-8", errors="replace")[:4000]
            return {"systemMessage": (
                "MQB fast checks failed. Review the relevant diff; pre-existing changes may belong "
                "to the user. Report unresolved results accurately. No automatic continuation.\n" + detail
            )}
        return {}  # Static success is not a release claim.
    except (OSError, subprocess.SubprocessError):
        return {"systemMessage": "MQB hook: fast checks unavailable or timed out; validation is unverified."}


def main():
    try:
        event = json.load(sys.stdin)
        output = response(event) if isinstance(event, dict) else {
            "systemMessage": "MQB hook: invalid event; checks not run."
        }
    except (ValueError, UnicodeError):
        output = {"systemMessage": "MQB hook: invalid event; checks not run."}
    print(json.dumps(output, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
