"""Read-only health report for the disposable local notification outbox."""
import argparse
import asyncio
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def validate_test_database_url(url):
    parsed = urlsplit(url)
    in_dev_container = os.getenv('MQB_DEV_CONTAINER') == '1' and Path('/.dockerenv').is_file()
    expected = ('postgres', 5432) if in_dev_container else ('127.0.0.1', 55433)
    if ((parsed.hostname, parsed.port) != expected or parsed.path != '/morning_quiz_test'
            or parsed.username != 'mqb_dev'):
        raise SystemExit('Outbox audit is restricted to the disposable local morning_quiz_test database')
    return url


def summarize(rows, *, now=None, stale_after=timedelta(minutes=5)):
    now = now or datetime.now(timezone.utc)
    counts = Counter(row.status for row in rows)
    sending_cutoff = now - stale_after
    stale = [row for row in rows if row.status == 'sending'
             and (row.claimed_at is None or row.claimed_at <= sending_cutoff)]
    oldest = {}
    for row in rows:
        stamp = (row.available_at if row.status == 'pending' else
                 row.claimed_at if row.status in {'sending', 'uncertain'} else row.delivered_at)
        if stamp is not None and (row.status not in oldest or stamp < oldest[row.status]):
            oldest[row.status] = stamp
    errors = Counter(
        f'{row.status}:{(row.last_error or "unknown")[:80]}'
        for row in rows if row.status in {'uncertain', 'sending'}
    )
    return {
        'generated_at': now.isoformat(),
        'total': len(rows),
        'counts': {key: counts.get(key, 0) for key in ('pending', 'sending', 'uncertain', 'delivered')},
        'other_statuses': {key: count for key, count in sorted(counts.items())
                           if key not in {'pending', 'sending', 'uncertain', 'delivered'}},
        'stale_sending_after_seconds': int(stale_after.total_seconds()),
        'stale_sending': len(stale),
        'oldest_at': {key: value.isoformat() for key, value in sorted(oldest.items())},
        'error_groups': [{'status_and_type': key, 'count': count}
                         for key, count in errors.most_common(20)],
        'stale_items': [
            {'id': row.id, 'kind': row.kind, 'game_id': row.game_id,
             'claimed_at': row.claimed_at.isoformat() if row.claimed_at else None,
             'attempts': row.attempts,
             'last_error': row.last_error}
            for row in sorted(stale, key=lambda item: item.claimed_at or datetime.min.replace(tzinfo=timezone.utc))[:100]
        ],
        'uncertain_items': [
            {'id': row.id, 'kind': row.kind, 'game_id': row.game_id,
             'chat_id': row.chat_id, 'user_id': row.user_id,
             'attempts': row.attempts, 'last_error': row.last_error}
            for row in sorted((item for item in rows if item.status == 'uncertain'),
                              key=lambda item: item.id)[:100]
        ],
    }


async def inspect_database(url, *, now=None):
    from sqlalchemy import select
    from storage.database import Database, DatabaseSettings, normalize_database_url
    from storage.models import NotificationOutbox

    database = Database(DatabaseSettings(url=normalize_database_url(validate_test_database_url(url))))
    try:
        async with database.transaction() as session:
            rows = list((await session.scalars(
            select(NotificationOutbox).order_by(NotificationOutbox.id)
            )).all())
            return summarize(rows, now=now)
    finally:
        await database.dispose()


def render_markdown(report):
    lines = [
        '# Notification outbox audit', '',
        f"- Generated at: `{report['generated_at']}`",
        f"- Total inspected: {report['total']}",
        f"- Stale `sending` (>{report['stale_sending_after_seconds']}s): {report['stale_sending']}",
        '', '| Status | Count | Oldest |', '|---|---:|---|',
    ]
    for status, count in report['counts'].items():
        lines.append(f"| {status} | {count} | {report['oldest_at'].get(status, '—')} |")
    if report['other_statuses']:
        lines += ['', '## Unexpected statuses', '']
        lines.extend(f'- `{status}`: {count}' for status, count in report['other_statuses'].items())
    lines += ['', '## Uncertain items', '']
    if report['uncertain_items']:
        lines += ['| ID | Kind | Game | Attempts | Last error |', '|---|---|---|---:|---|']
        for item in report['uncertain_items']:
            lines.append(f"| `{item['id']}` | {item['kind']} | {item['game_id'] or '—'} | "
                         f"{item['attempts']} | {item['last_error'] or '—'} |")
    else:
        lines.append('No uncertain notifications.')
    lines += ['', 'Diagnostic only: this report does not retry, resolve, or mutate notifications.', '']
    return '\n'.join(lines)


async def run(args):
    url = os.environ.get('TEST_DATABASE_URL', '').strip()
    if not url:
        raise SystemExit('Set TEST_DATABASE_URL explicitly; DATABASE_URL is never used')
    if args.now is not None and args.now.tzinfo is None:
        raise SystemExit('--now must include a timezone, for example 2026-10-08T12:00:00+00:00')
    report = await inspect_database(url, now=args.now)
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.write_text(render_markdown(report), encoding='utf-8')
    return 1 if report['stale_sending'] or report['counts']['uncertain'] else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    output = ROOT / '.local' / 'acceptance'
    parser.add_argument('--json-output', type=Path, default=output / 'notification-outbox-audit.json')
    parser.add_argument('--markdown-output', type=Path, default=output / 'notification-outbox-audit.md')
    parser.add_argument('--now', type=lambda value: datetime.fromisoformat(value), default=None,
                        help='Fixed ISO timestamp for reproducible reports')
    raise SystemExit(asyncio.run(run(parser.parse_args())))


if __name__ == '__main__':
    main()
