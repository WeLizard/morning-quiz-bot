#!/usr/bin/env python3
"""Chats the old bot still serves: this bot waits there until they are released.

    DATABASE_URL=postgresql+asyncpg://... python scripts/bot_handover.py list
    ... bot_handover.py hold --old-bot MorningQuizBot <chat_id> [<chat_id> ...]
    ... bot_handover.py hold --from-dir /path/to/old/bot/data/chats
    ... bot_handover.py release <chat_id> [...]     # one chat moves over
    ... bot_handover.py release --all               # switch day: every chat moves over

While a chat waits, this bot sends it no scheduled quizzes or wisdom; in groups it also leaves
messages and commands to the old bot and greets once when added. See storage/bot_handover.py.
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from storage import bot_handover  # noqa: E402
from storage.database import Database, DatabaseSettings  # noqa: E402


def chat_ids(args):
    ids = [int(value) for value in args.chat_ids]
    if getattr(args, 'from_dir', None):
        folder = Path(args.from_dir)
        if not folder.is_dir():
            raise SystemExit(f'Not a directory: {folder}')
        ids += [int(entry.name) for entry in folder.iterdir()
                if entry.is_dir() and entry.name.lstrip('-').isdigit()]
    return ids


async def main(args) -> int:
    database = Database(DatabaseSettings.from_env())
    try:
        if args.command == 'hold':
            ids = chat_ids(args)
            if not ids:
                raise SystemExit('Name chats or pass --from-dir')
            state = await bot_handover.hold(database, ids, old_bot=args.old_bot)
        elif args.command == 'release':
            if args.all == bool(args.chat_ids):
                raise SystemExit('Name chats or pass --all (not both)')
            state = await bot_handover.release(database, None if args.all else chat_ids(args))
        else:
            state = await bot_handover.read(database)
        print(json.dumps({'waiting': len(state['chats']), **state}, ensure_ascii=False, indent=2))
        return 0
    finally:
        await database.dispose()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('list', help='show the chats that wait')
    hold = commands.add_parser('hold', help='make chats wait for the switch')
    hold.add_argument('chat_ids', nargs='*')
    hold.add_argument('--from-dir', help="the old bot's data/chats directory: every chat in it waits")
    hold.add_argument('--old-bot', help='username of the old bot, shown in the greeting')
    release = commands.add_parser('release', help='let chats move over to this bot')
    release.add_argument('chat_ids', nargs='*')
    release.add_argument('--all', action='store_true')
    raise SystemExit(asyncio.run(main(parser.parse_args())))
