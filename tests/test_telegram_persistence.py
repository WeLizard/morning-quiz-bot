import asyncio

from telegram.ext import Application, ExtBot

from modules.telegram_persistence import build_telegram_persistence


def test_postgres_startup_uses_only_ephemeral_ui_state(tmp_path):
    async def run():
        path = tmp_path / "state.pickle"
        bot = ExtBot("123:TEST-NOT-A-REAL-TOKEN")
        legacy = build_telegram_persistence(path)
        legacy.set_bot(bot)
        await legacy.get_bot_data()
        await legacy.update_bot_data({"bot_state": "old memory", "data_manager": "old service"})
        await legacy.flush()
        before = path.read_bytes()

        pg = build_telegram_persistence(path, postgres=True)
        pg.set_bot(bot)
        await pg.get_chat_data()
        await pg.update_user_data(42, {"menu": "quiz"})
        await pg.update_conversation("quiz_interactive_setup_conv", (42, 42), 1)
        await pg.flush()
        fresh = build_telegram_persistence(path, postgres=True)
        app = Application.builder().token("123:TEST-NOT-A-REAL-TOKEN").persistence(fresh).build()
        sentinel = object()
        app.bot_data["bot_state"] = sentinel
        # This step only reads local persistence. Never initialize the Bot/network.
        await app._initialize_persistence()
        assert app.bot_data["bot_state"] is sentinel
        assert 42 not in app.user_data
        assert await fresh.get_conversations("quiz_interactive_setup_conv") == {}
        assert path.read_bytes() == before
        assert not (tmp_path / 'state.postgres-ui.pickle').exists()
        assert not fresh.store_data.bot_data
    asyncio.run(run())
