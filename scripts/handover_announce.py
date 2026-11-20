#!/usr/bin/env python3
"""Announce the move to the new bot in every chat of the old bot. Dry run unless --send.

    OLD_BOT_TOKEN=... TELEGRAM_PROXY_URL=socks5://... python scripts/handover_announce.py \
        --from-dir /home/lizard/morning-quiz-bot/data/chats --date "1 декабря" [--only <id> ...] [--send]

Sends through the OLD bot's token (it is the bot the chats know). A dry run prints each
recipient, whether the old bot can still reach it (getChat, read-only) and the exact text.
--send posts once per chat: every success is written to --ledger at once, and chats already
in the ledger are skipped, so a rerun after a failure never repeats a message.
The token is never printed.
"""
import argparse
import json
import os
import sys
from pathlib import Path

NEW_BOT = 'Quizywizzy_bot'

GROUP_TEXT = (
    '📢 Новости бота\n\n'
    'Скоро этот бот уходит на покой. Его заменит QuizzyWizzy — @{bot}: те же квизы, '
    'а в мини-приложении ещё и новые игры.\n\n'
    'Что сделать: добавьте @{bot} в этот чат (кнопка ниже). До {date} он будет молчать, '
    'чтобы вопросы не приходили дважды.\n\n'
    '{date} — переезд: настройки чата, расписание и очки перейдут к новому боту сами, '
    'а этот бот замолчит.'
)
PRIVATE_TEXT = (
    '📢 Новости бота\n\n'
    'Скоро этот бот уходит на покой. Его заменит QuizzyWizzy — @{bot}: те же квизы, '
    'а в мини-приложении ещё и новые игры.\n\n'
    'Что сделать: откройте @{bot} и нажмите «Старт» (кнопка ниже). До {date} квизы '
    'приходят отсюда, как обычно.\n\n'
    '{date} — переезд: ваши очки и настройки перейдут к новому боту сами, а этот бот замолчит.'
)


def is_group(chat_id):
    return int(chat_id) < 0


def message(chat_id, date, bot=NEW_BOT):
    """Text and inline button for one chat: groups add the bot, private chats open it."""
    if is_group(chat_id):
        text, label, url = GROUP_TEXT, 'Добавить QuizzyWizzy в чат', f'https://t.me/{bot}?startgroup=1'
    else:
        text, label, url = PRIVATE_TEXT, 'Открыть QuizzyWizzy', f'https://t.me/{bot}?start=moved'
    return {'text': text.format(bot=bot, date=date),
            'reply_markup': {'inline_keyboard': [[{'text': label, 'url': url}]]}}


def recipients(folder, only=()):
    ids = sorted(int(entry.name) for entry in Path(folder).iterdir()
                 if entry.is_dir() and entry.name.lstrip('-').isdigit())
    if only:
        wanted = {int(chat_id) for chat_id in only}
        missing = wanted - set(ids)
        if missing:
            raise SystemExit(f'Not chats of the old bot: {sorted(missing)}')
        ids = [chat_id for chat_id in ids if chat_id in wanted]
    # Groups first: they matter most and fail loudest if the bot was removed.
    return sorted(ids, key=lambda chat_id: (not is_group(chat_id), chat_id))


def load_ledger(path):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}


def main(args):
    import httpx
    token = os.environ.get('OLD_BOT_TOKEN', '').strip()
    if not token:
        raise SystemExit('OLD_BOT_TOKEN is not set')
    client = httpx.Client(proxy=os.environ.get('TELEGRAM_PROXY_URL') or None, timeout=60)

    def call(method, payload):
        return client.post(f'https://api.telegram.org/bot{token}/{method}', json=payload).json()

    me = call('getMe', {})
    if not me.get('ok'):
        raise SystemExit(f'getMe failed: {me.get("description")}')
    print(f'old bot: @{me["result"]["username"]}  mode: {"SEND" if args.send else "dry run"}')
    ledger_path = Path(args.ledger)
    ledger = load_ledger(ledger_path)
    failures = 0
    for chat_id in recipients(args.from_dir, args.only):
        body = message(chat_id, args.date)
        if str(chat_id) in ledger:
            print(f'{chat_id}: already sent as message {ledger[str(chat_id)]}, skipped')
            continue
        chat = call('getChat', {'chat_id': chat_id})
        name = (chat.get('result') or {}).get('title') or ('private' if chat.get('ok') else '')
        if not chat.get('ok'):
            failures += 1
            print(f'{chat_id}: unreachable ({chat.get("description")}), skipped')
            continue
        if not args.send:
            print(f'--- {chat_id} ({name})\n{body["text"]}\n[{body["reply_markup"]["inline_keyboard"][0][0]["text"]}]')
            continue
        sent = call('sendMessage', {'chat_id': chat_id, **body})
        if sent.get('ok'):
            ledger[str(chat_id)] = sent['result']['message_id']
            ledger_path.write_text(json.dumps(ledger, indent=2), encoding='utf-8')
            print(f'{chat_id} ({name}): sent, message {sent["result"]["message_id"]}')
        else:
            failures += 1
            print(f'{chat_id} ({name}): FAILED {sent.get("description")}')
    return 1 if failures and args.send else 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--from-dir', required=True, help="the old bot's data/chats directory")
    parser.add_argument('--date', required=True, help='switch day as it reads in the text, e.g. "1 декабря"')
    parser.add_argument('--only', nargs='*', default=(), help='limit to these chat ids (e.g. a preview)')
    parser.add_argument('--ledger', default='handover_announce_sent.json', help='ids already sent')
    parser.add_argument('--send', action='store_true', help='really send; without it nothing is posted')
    sys.exit(main(parser.parse_args()))
