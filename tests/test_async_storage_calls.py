"""Guard the sync-to-async API migration against silently dropped coroutines."""
import ast
from pathlib import Path


def test_bot_awaits_async_storage_and_score_methods():
    root = Path(__file__).resolve().parents[1]
    methods = {
        "update_chat_setting", "update_quiz_setting", "reset_chat_settings",
        "disable_daily_quiz_for_chat", "get_chat_settings_async", "_get_effective_quiz_params",
        "get_chat_rating", "get_global_rating", "get_user_stats_in_chat",
        "get_current_chat_user_stats", "get_global_user_stats", "get_session_profiles",
    }
    files = [root / "data_manager.py", root / "modules/score_manager.py", root / "modules/quiz_engine.py", *sorted((root / "handlers").rglob("*.py"))]
    missing = []
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in methods:
                if not isinstance(parents.get(node), ast.Await):
                    missing.append(f"{path.relative_to(root)}:{node.lineno}: {node.func.attr}")
    assert not missing, "Unawaited async calls:\n" + "\n".join(missing)
