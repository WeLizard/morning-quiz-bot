"""Automatic client errors: scrubbing, noise filter, fingerprints, limits and the deduplicating upsert.

The browser already scrubs what it sends, but nothing from it is trusted: message, stack and source are
redacted again here (URL query/hash, initData fields, tokens, e-mails, phones) before anything is stored,
fingerprinted or put into a Telegram message.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError

from .mini_app import MiniAppError
from .models import NotificationOutbox, ProblemErrorHit, ProblemReport
from .notifications import NotificationQueue

BODY_BYTES_MAX = 16_000
MESSAGE_MAX = 300
SOURCE_MAX = 200
STACK_MAX = 2000
STACK_LINES_MAX = 20
BREADCRUMBS_MAX = 10
ACCOUNT_PER_HOUR = 30
IP_PER_HOUR = 120
GLOBAL_PER_HOUR = 600
HITS_KEEP = timedelta(days=2)
RETURN_COOLDOWN = timedelta(hours=6)
MILESTONES = (10, 100, 1000)
NOTIFY_PER_HOUR = 10  # every owner message about automatic errors, globally
NEW_PER_ACCOUNT_PER_DAY = 3  # messages about NEW errors per first reporter
CRUMB_KINDS = ('tap', 'nav', 'tab', 'visibility', 'menu')
ERROR_TYPES = ('error', 'unhandledrejection')
REDACTED = '[redacted]'

_CONTROL = re.compile('[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u200e\u200f\u202a-\u202e\u2066-\u2069]')
_SECRET_FIELDS = re.compile(
    r'(?:tgWebAppData|tgWebAppVersion|hash|auth_date|query_id|signature|token|access_token|init_?data)'
    r'\s*[=:]\s*[^\s&\'")\]>]*|user\s*=\s*(?:%7[Bb][^\s&\'")\]>]*|\{[^}]*\})|init_?data[^\s&\'")\]>]*'
    r'|Bearer\s+[^\s\'")\]>]+', re.IGNORECASE)
_URL = re.compile(
    r'(?P<base>(?:https?|wss?)://[^\s\'"<>()\[\]?#]*)(?:[?#][^\s\'"<>()\[\]]*?)?(?P<tail>(?::\d+){1,2})?'
    r'(?=[\s\'"<>()\[\]]|$)', re.IGNORECASE)
_JSON_SECRET = re.compile(
    r'\\?"(?:query_id|hash|auth_date|user|signature|tgWebAppData|initData|init_data|token|access_token)\\?"\s*:\s*'
    r'(?:\\?"[^"\\]*\\?"|\{[^}]*\}|[\w.-]+)', re.IGNORECASE)
_ISO_AT = re.compile(r'\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:?\d{2})?)?')
_PATH_QUERY = re.compile(r'(?P<path>/[\w.~%@+/-]+)[?#][^\s:\'"<>()\[\]]*')
_EMAIL = re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+')
_PHONE = re.compile(r'(?<![\w.])(?:\+7|8)[\s(-]*\d{3}[\s)-]*\d{3}[\s-]*\d{2}[\s-]*\d{2}(?!\d)|(?<![\w.])\+\d{10,15}(?!\d)')
_LONG_TOKEN = re.compile(r'[A-Za-z0-9_-]{32,}')
_DIGITS = re.compile(r'\d{3,}')
_CRUMB_TARGET = re.compile(r'[A-Za-z0-9_.:#/-]{1,60}')
_EXTENSION = re.compile(r'(?:chrome|moz|safari)-extension://', re.IGNORECASE)


def redact(value, limit: int) -> str:
    """Return ``value`` without secrets, URL queries/hashes or control characters, cut to ``limit``."""
    if not isinstance(value, str):
        return ''
    value = _CONTROL.sub('', value)[:limit * 3 + 200]
    value = _JSON_SECRET.sub(REDACTED, value)
    value = _URL.sub(lambda match: match.group('base') + (match.group('tail') or ''), value)  # query/hash carry secrets
    value = _PATH_QUERY.sub(lambda match: match.group('path'), value)
    value = _SECRET_FIELDS.sub(REDACTED, value)
    value = _EMAIL.sub(REDACTED, value)
    value = _PHONE.sub(REDACTED, value)
    value = _LONG_TOKEN.sub(REDACTED, value)
    return value.strip()[:limit]


def _looks_secret(value: str) -> bool:
    return any(pattern.search(value) for pattern in (_SECRET_FIELDS, _EMAIL, _PHONE, _LONG_TOKEN))


def clean_source(raw, own_host: str | None) -> str:
    """Path only; our own origin is dropped, a foreign one keeps host+path."""
    if not isinstance(raw, str) or not raw.strip():
        return ''
    raw = _CONTROL.sub('', raw.strip())[:600]
    try:
        parts = urlsplit(raw)
        if parts.scheme in ('http', 'https', 'ws', 'wss') and parts.netloc:
            host = parts.hostname or ''
            own = (own_host or '').split(':')[0].lower()
            raw = parts.path if host.lower() == own else host + parts.path
        else:
            raw = raw.split('?', 1)[0].split('#', 1)[0]
    except ValueError:
        raw = raw.split('?', 1)[0].split('#', 1)[0]
    return redact(raw, SOURCE_MAX)


def _int(value, high=10_000_000):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    try:
        return min(max(int(value), 0), high)
    except (OverflowError, ValueError):
        return 0


def sanitize_last_error(raw):
    """The ``last_error`` block a manual report may carry (same scrubbing as an automatic error)."""
    if not isinstance(raw, dict):
        return None
    message = redact(raw.get('message'), MESSAGE_MAX)
    if not message:
        return None
    report_id = raw.get('report_id')
    at = raw.get('at')
    return {'report_id': report_id if isinstance(report_id, int) and not isinstance(report_id, bool)
            and 0 < report_id < 2 ** 62 else None,
            'message': message, 'source': clean_source(raw.get('source'), None), 'line': _int(raw.get('line')),
            'at': at if isinstance(at, str) and len(at) <= 40 and _ISO_AT.fullmatch(at) else ''}


def fingerprint(message: str, source: str, line: int) -> str:
    return hashlib.sha256(f'{_DIGITS.sub("#", message)}|{source}|{line}'.encode()).hexdigest()


def parse_body(raw: bytes, own_host: str | None = None):
    """Return ``(request_id, error, breadcrumbs, context)``; ``error`` is None for ignorable noise."""
    from web.mini_auth import unique_object
    try:
        value = json.loads(raw, object_pairs_hook=unique_object)
        if not isinstance(value, dict) or not {'request_id', 'error'} <= set(value) <= {
                'request_id', 'error', 'breadcrumbs', 'context'}:
            raise ValueError()
        if not isinstance(value['request_id'], str) or not isinstance(value['error'], dict):
            raise ValueError()
        request_id = UUID(value['request_id'])
        error = value['error']
        if error.get('type') not in ERROR_TYPES:
            raise ValueError()
        crumbs = value.get('breadcrumbs') or []
        if not isinstance(crumbs, list):
            raise ValueError()
    except (ValueError, UnicodeError, RecursionError, TypeError):
        raise MiniAppError(400, 'Некорректные параметры ошибки', code='invalid') from None
    raw_message = error.get('message') if isinstance(error.get('message'), str) else ''
    raw_source = error.get('source') if isinstance(error.get('source'), str) else ''
    raw_stack = error.get('stack') if isinstance(error.get('stack'), str) else ''
    line = _int(error.get('line'))
    if (not raw_message.strip() or 'ResizeObserver loop' in raw_message
            or _EXTENSION.search(raw_source)
            or (raw_message.strip().rstrip('.').lower() == 'script error' and (not raw_source.strip() or not line))):
        if not raw_message.strip():
            raise MiniAppError(400, 'Пустое сообщение об ошибке', code='message')
        return request_id, None, [], {}
    message = redact(raw_message, MESSAGE_MAX)
    if not message:
        raise MiniAppError(400, 'Пустое сообщение об ошибке', code='message')
    source = clean_source(raw_source, own_host)
    lines = [redact(row, 300) for row in _CONTROL.sub('', raw_stack[:6000]).splitlines()[:STACK_LINES_MAX]]
    stack = '\n'.join(row for row in lines if row)[:STACK_MAX]
    breadcrumbs = []
    for item in crumbs[-BREADCRUMBS_MAX:]:
        if not isinstance(item, dict):
            continue
        target, kind, at = item.get('target'), item.get('kind'), item.get('t')
        if (kind not in CRUMB_KINDS or not isinstance(target, str) or not _CRUMB_TARGET.fullmatch(target)
                or _looks_secret(target) or isinstance(at, bool) or not isinstance(at, int)
                or not 0 <= at <= 10 ** 9):
            continue
        breadcrumbs.append({'t': at, 'kind': kind, 'target': target})
    from .problem_reports import sanitize_context
    context = sanitize_context(value.get('context'))
    context.pop('last_error', None)
    return request_id, {'type': error['type'], 'message': message, 'source': source, 'line': line,
                        'column': _int(error.get('column')), 'stack': stack}, breadcrumbs, context


def _aware(value):
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


async def _hits_since(session, column, value, since):
    query = select(func.count()).select_from(ProblemErrorHit).where(ProblemErrorHit.created_at > since)
    if column is not None:
        query = query.where(column == value)
    return await session.scalar(query)


def _lock_key(scope: str, value: str) -> int:
    digest = hashlib.sha256(f'problem-error:{scope}:{value}'.encode()).digest()
    return int.from_bytes(digest[:8], 'big', signed=True)


async def ingest(session, who, *, request_id, error, breadcrumbs, context, client_ip_hash, now=None):
    """Store or fold one error. Returns ``(report_id, is_new)``; raises 429 when over a limit."""
    from .problem_reports import build_commit, report_chat_id
    now = now or datetime.now(timezone.utc)
    account_id = UUID(who.account_id)
    if session.bind.dialect.name == 'postgresql':
        for scope, value in (('account', who.account_id), ('ip', client_ip_hash)):
            if not await session.scalar(text('SELECT pg_try_advisory_xact_lock(:key)'),
                                        {'key': _lock_key(scope, value)}):
                raise MiniAppError(429, 'Слишком много ошибок, попробуй позже', code='rate_limited')
    if session.bind.dialect.name != 'postgresql' or await session.scalar(
            text('SELECT pg_try_advisory_xact_lock(:key)'), {'key': _lock_key('gc', 'hits')}):
        # One collector at a time; a caller that loses the race simply skips the cleanup.
        await session.execute(delete(ProblemErrorHit).where(ProblemErrorHit.created_at < now - HITS_KEEP))
    hour = now - timedelta(hours=1)
    if (await _hits_since(session, ProblemErrorHit.account_id, account_id, hour) >= ACCOUNT_PER_HOUR
            or await _hits_since(session, ProblemErrorHit.ip_hash, client_ip_hash, hour) >= IP_PER_HOUR
            or await _hits_since(session, None, None, hour) >= GLOBAL_PER_HOUR):
        raise MiniAppError(429, 'Слишком много ошибок, попробуй позже', code='rate_limited')

    print_ = fingerprint(error['message'], error['source'], error['line'])
    stored = {**context, 'error': error, 'breadcrumbs': breadcrumbs}
    chat_id = report_chat_id()

    async def within_budget(new_error):
        sent = await session.scalar(select(func.count()).select_from(NotificationOutbox).where(
            NotificationOutbox.dedupe_key.like('problem_error:%'), NotificationOutbox.available_at > hour))
        if sent >= NOTIFY_PER_HOUR:
            return False
        if new_error:
            today = await session.scalar(select(func.count()).select_from(ProblemReport).where(
                ProblemReport.kind == 'auto_error', ProblemReport.account_id == account_id,
                ProblemReport.notified_at.is_not(None), ProblemReport.created_at > now - timedelta(days=1)))
            return today < NEW_PER_ACCOUNT_PER_DAY
        return True

    async def enqueue(report_id, variant, key, **payload):
        if chat_id is None:
            return False
        if not await within_budget(variant == 'new'):
            if variant == 'new':  # over budget: stored silently, announced by the hourly digest
                start = now.replace(minute=0, second=0, microsecond=0)
                await NotificationQueue.enqueue_in(
                    session, kind='problem_report.text', chat_id=chat_id, available_at=start + timedelta(hours=1),
                    dedupe_key=f'problem_errors:digest:{start:%Y%m%d%H}',
                    payload={'variant': 'digest', 'since': start.isoformat()})
            return False
        return await NotificationQueue.enqueue_in(
            session, kind='problem_report.text', dedupe_key=key, chat_id=chat_id, available_at=now,
            payload={'report_id': report_id, 'variant': variant, **payload})

    async def fold():
        row = await session.scalar(select(ProblemReport).where(
            ProblemReport.kind == 'auto_error', ProblemReport.fingerprint == print_).with_for_update())
        if row is None:
            return None
        was_done = row.status == 'done'
        row.occurrences += 1
        row.affected_accounts += 1 if row.last_account_id != account_id else 0
        row.last_account_id, row.last_seen_at, row.context = account_id, now, stored
        row.updated_at = now
        if was_done:
            row.status = 'new'
            last = _aware(row.notified_at)
            if (last is None or now - last >= RETURN_COOLDOWN) and await enqueue(
                    row.id, 'returned', f'problem_error:{row.id}:returned:{row.occurrences}',
                    count=row.occurrences, accounts=row.affected_accounts):
                row.notified_at = now
        if row.occurrences in MILESTONES:
            await enqueue(row.id, 'milestone', f'problem_error:{row.id}:milestone:{row.occurrences}',
                          count=row.occurrences, accounts=row.affected_accounts)
        return row

    row, is_new = await fold(), False
    if row is None:
        report = ProblemReport(
            account_id=account_id, request_id=request_id, channel=who.channel[:16], kind='auto_error',
            telegram_user_id=who.telegram_user_id, display_name=(who.display_name or '')[:120],
            text=error['message'], context=stored, build=build_commit(), ip_hash=client_ip_hash,
            created_at=now, fingerprint=print_, occurrences=1, affected_accounts=1,
            last_account_id=account_id, last_seen_at=now)
        try:
            async with session.begin_nested():
                session.add(report)
                await session.flush()
            row, is_new = report, True
        except IntegrityError:
            # A concurrent twin inserted the same fingerprint first (or the request id is taken): fold into it.
            if report in session:
                session.expunge(report)
            row = await fold()
            if row is None:
                raise MiniAppError(409, 'Повтор запроса', code='duplicate_request') from None
        else:
            if await enqueue(report.id, 'new', f'problem_error:{report.id}:new'):
                report.notified_at = now
    session.add(ProblemErrorHit(account_id=account_id, ip_hash=client_ip_hash, report_id=row.id, created_at=now))
    await session.flush()
    return row.id, is_new
