"""Dev-only, explicitly attested offline quarantine of one observed sending row."""
import argparse
import asyncio
from datetime import datetime
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from storage.database import Database, DatabaseSettings, normalize_database_url
from storage.notifications import NotificationQueue, SENDERS_STOPPED_ATTESTATION


def validate_dev_database_url(url):
    """Never infer a target from DATABASE_URL or load dotenv/production config."""
    try:
        parsed = urlsplit(url)
        in_container = os.getenv('MQB_DEV_CONTAINER') == '1' and Path('/.dockerenv').is_file()
        endpoint = ('postgres', 5432) if in_container else ('127.0.0.1', 55433)
        valid = (parsed.scheme in {'postgresql', 'postgresql+asyncpg'}
                 and (parsed.hostname, parsed.port) == endpoint
                 and parsed.path in {'/morning_quiz_dev', '/morning_quiz_test'}
                 and parsed.username == 'mqb_dev' and not parsed.query and not parsed.fragment)
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise ValueError('Разрешена только явно выбранная локальная dev/test БД.')
    return normalize_database_url(url)


def nullable_claimed_by(value):
    return None if value == 'null' else value


def nullable_timestamp(value):
    if value == 'null':
        return None
    stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError('claimed_at требует часовой пояс или null.')
    return stamp


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument('--database-url-env', required=True,
                        help='Имя явно выбранной env-переменной с локальным URL; dotenv не читается.')
    result.add_argument('--item-id', required=True)
    result.add_argument('--expected-version', type=int, required=True)
    result.add_argument('--expected-claimed-by', required=True, help='Точное значение или null.')
    result.add_argument('--expected-claimed-at', required=True, help='ISO timestamp с timezone или null.')
    result.add_argument('--action-id', required=True, help='UUID; сохранить для идентичного повтора.')
    result.add_argument('--operator-id', required=True)
    result.add_argument('--reason', required=True)
    result.add_argument('--evidence-file', type=Path, required=True,
                        help='JSON с verification_method и sender_inventory; без секретов.')
    result.add_argument('--senders-stopped-attestation', required=True,
                        help=SENDERS_STOPPED_ATTESTATION)
    result.add_argument('--apply', action='store_true', help='Без флага транзакция всегда откатывается.')
    return result


async def run(url, request, *, apply=False):
    database = Database(DatabaseSettings(url=validate_dev_database_url(url)))
    try:
        # The dry run executes the same locked checks then rolls back both row
        # and receipt. It never commits; an apply always checks again.
        async with database.session_factory() as session:
            async with session.begin():
                receipt = await NotificationQueue.quarantine_in(session, **request)
                if not apply:
                    await session.rollback()
            return {'applied': apply, 'receipt': receipt,
                    'attestation_is_operator_assertion': True}
    finally:
        await database.dispose()


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        url = os.environ.get(args.database_url_env)
        validate_dev_database_url(url)
        if args.evidence_file.stat().st_size > 8192:
            raise ValueError('Слишком большое свидетельство.')
        request = dict(item_id=args.item_id, action_id=args.action_id,
                       operator_id=args.operator_id, expected_version=args.expected_version,
                       expected_claimed_by=nullable_claimed_by(args.expected_claimed_by),
                       expected_claimed_at=nullable_timestamp(args.expected_claimed_at),
                       reason=args.reason, evidence=json.loads(args.evidence_file.read_text(encoding='utf-8')),
                       senders_stopped_attestation=args.senders_stopped_attestation)
        print(json.dumps(asyncio.run(run(url, request, apply=args.apply)), ensure_ascii=False))
        return 0
    except Exception:
        # DB exception strings may contain credentials, raw SQL or payloads.
        # Keep the CLI failure safe; inspect the target through read-only tools.
        print('Карантин не подтверждён: проверь локальный URL, данные, схему и актуальную попытку.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
