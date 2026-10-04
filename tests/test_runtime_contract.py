"""Runtime-контракт: сессия Mini App не трогает operational-файлы.

В режиме PostgreSQL состояние живёт только в базе, поэтому ни один запрос
мини-аппа не должен менять `data/`. Чтение статичных файлов (config,
data/system/streak_achievements.json) разрешено по замыслу — проверка следит
именно за изменениями, потому что молчаливый откат к JSON-состоянию и есть тот
дефект, который закрывает пункт контракта.
"""
import asyncio
from pathlib import Path

from tests.test_mini_app import USER, environment, login
from tests.test_postgres_members import pg_env  # noqa: F401 — фикстура нужна в модуле

ROOT = Path(__file__).resolve().parents[1]
OPERATIONAL = ROOT / 'data'


def snapshot(root=OPERATIONAL):
    state = {}
    for path in Path(root).rglob('*'):
        if path.is_file():
            stat = path.stat()
            state[str(path.relative_to(Path(root)))] = (stat.st_size, stat.st_mtime_ns)
    return state


def test_mini_app_session_does_not_change_operational_files(pg_env):
    async def run():
        before = snapshot()
        async with environment(pg_env, runtime_enabled=True) as env:
            headers = await login(env)
            for path in ('/api/mini/me', '/api/mini/progress', '/api/mini/achievements', '/api/mini/history',
                         '/api/mini/config', '/api/mini/runtime', '/api/mini/categories',
                         '/api/mini/leaderboard', '/api/mini/chats?limit=50',
                         f'/api/mini/chats/{USER}/details', f'/api/mini/chats/{USER}/leaderboard'):
                assert (await env.client.get(path, headers=headers)).status_code == 200, path
        after = snapshot()
        changed = sorted(set(before.items()) ^ set(after.items()))
        assert not changed, f'сессия мини-аппа изменила operational-файлы: {changed[:5]}'
    asyncio.run(run())
