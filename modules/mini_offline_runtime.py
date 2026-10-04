"""Local Mini App uses the same private handlers with a strictly offline transport."""
import asyncio
from contextlib import asynccontextmanager
from hashlib import sha256
import os


@asynccontextmanager
async def offline_game(database, user_id, token):
    from modules.dev_runtime import DevRuntime, OfflineRequest
    from modules.telegram_test_scope import PrivateTestScope
    from modules.mini_bridge_worker import run_worker
    from scripts.run_telegram_test import build_application
    from storage.mini_bridge import MiniBridge
    from storage.repositories import OperationalRepository
    from storage.dev_backups import guard
    if os.getenv('BOT_TOKEN') or user_id != 900000000091 or not token.startswith('123456:LOCAL_TEST_ONLY_'):
        raise ValueError('Offline Mini App requires the fixed synthetic identity and no real bot token')
    await asyncio.to_thread(guard, database)
    async with database.transaction() as session:
        repo = OperationalRepository(session)
        await repo.ensure_chat({'id': user_id, 'type': 'private', 'title': 'Моя тестовая игра'})
        await repo.ensure_member({'chat_id': user_id, 'user_id': user_id})
    scope = PrivateTestScope(user_id, 123456)
    dummy = DevRuntime(database)
    dummy.chat_id = user_id
    dummy.room = {'id': user_id, 'type': 'private', 'first_name': 'Тестовый игрок'}
    dummy.player = {'id': user_id, 'is_bot': False, 'first_name': 'Тестовый игрок'}
    bridge = MiniBridge(database, sha256(token.encode()).hexdigest(), user_id)
    scope.mini_bridge = bridge
    app, config, quiz, photos, dm = await build_application(database, scope, token, None,
        request_factory=lambda: OfflineRequest(dummy))
    worker = None
    try:
        await app.initialize(); await app.start()
        await quiz.restore_all_active_quizzes()
        scope.poll_ids.update(pid for pid, poll in app.bot_data['bot_state'].current_polls.items() if poll.get('chat_id') == user_id)
        quiz.schedule_quiz_auto_save()
        worker = asyncio.create_task(run_worker(bridge, app, photos, scope, asyncio.Lock()))
        yield
    finally:
        if worker:
            worker.cancel(); await asyncio.gather(worker, return_exceptions=True)
        await photos.shutdown()
        if app.running: await app.stop()
        await dm.flush_postgres_writes()
        await app.shutdown()
