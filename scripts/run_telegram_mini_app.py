"""HTTPS-facing test Mini App, isolated from admin and restricted to one Telegram user."""
import argparse
import asyncio
import logging
import os
from pathlib import Path
import sys

WORKSPACE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKSPACE))


async def run(args):
    from scripts.run_telegram_test import configure_environment
    from modules.telegram_test_scope import PrivateTestScope, ScopedRequest
    from storage.database import Database, DatabaseSettings
    from storage.dev_backups import guard
    from modules.mini_app_launch import configured_url
    from web.mini_app import MiniAppSettings, create_app
    from telegram import Bot
    from telegram.request import HTTPXRequest
    import uvicorn
    token, proxy = configure_environment(WORKSPACE, args.token_file)
    scope = PrivateTestScope(args.user_id, args.expected_bot_id)
    if token.split(':', 1)[0] != str(args.expected_bot_id):
        raise ValueError('Unexpected test bot identity')
    os.environ['MINI_APP_URL'] = args.public_origin + '/app'
    configured_url()
    database = Database(DatabaseSettings.from_env())
    await asyncio.to_thread(guard, database)
    from storage.startup import require_current_schema
    await require_current_schema(database)
    request = ScopedRequest(HTTPXRequest(proxy=proxy, httpx_kwargs={'trust_env': False}), scope, token)
    async with Bot(token, request=request) as bot:
        if bot.id != args.expected_bot_id:
            raise ValueError('Unexpected Telegram identity')
        username = bot.username
    class NoGroupAccess:
        async def allowed(self, chat_id, user_id):
            return False
    settings = MiniAppSettings(token, args.public_origin, bot_username=username)
    app = create_app(database=database, settings=settings, membership=NoGroupAccess(), allowed_user_ids={args.user_id}, runtime_enabled=True)
    try:
        await uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=4187, proxy_headers=True,
            forwarded_allow_ips='127.0.0.1', access_log=False, log_level='warning')).serve()
    finally:
        await database.dispose()


if __name__ == '__main__':
    logging.disable(logging.CRITICAL)
    parser = argparse.ArgumentParser()
    parser.add_argument('--user-id', type=int, required=True)
    parser.add_argument('--expected-bot-id', type=int, required=True)
    parser.add_argument('--token-file', choices=['.env', '.env.telegram-test'], required=True)
    parser.add_argument('--public-origin', required=True)
    try:
        asyncio.run(run(parser.parse_args()))
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        print('Mini App startup failed: ' + type(exc).__name__, flush=True)
        sys.exit(1)
