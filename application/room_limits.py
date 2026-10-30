"""Short invite codes and database-backed rate limits for room membership changes.

Limits live in PostgreSQL (``room_join_attempts``), not in process memory, so they survive a
restart and apply to every worker. Counting is serialized per account with a transaction advisory
lock. Lock order everywhere: game -> room -> membership rows first, advisory locks last. The one
exception is the failed-code check, which runs before the lookup and therefore only TRIES its lock
(never waits), so it cannot take part in a deadlock cycle.

Short invite codes are stored as HMAC-SHA256 under a server secret that survives restarts
(``MQB_ROOM_CODE_SECRET`` or, failing that, a key derived from the Mini App bot token). Codes issued
before the keyed hash existed (plain SHA-256) are still accepted until they expire.
"""

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
from hashlib import sha256
import os
import secrets

from sqlalchemy import delete, func, select, text

from storage.models import RoomJoinAttempt

# 30 letters/digits without look-alikes (no I, L, O, U, 0, 1): 30**8 ~ 6.6e11 codes.
SHORT_CODE_ALPHABET = 'ABCDEFGHJKMNPQRSTVWXYZ23456789'
SHORT_CODE_LENGTH = 8

# Entering, being let in and leaving rooms: per account.
MEMBERSHIP_LIMIT = 20
MEMBERSHIP_WINDOW = timedelta(minutes=10)
# Failed short-code entries: per account, and per client address (hashed) across accounts, so a
# guesser who farms accounts is still stopped while nobody else is locked out.
CODE_FAIL_ACCOUNT_LIMIT = 10
CODE_FAIL_ACCOUNT_WINDOW = timedelta(minutes=15)
CODE_FAIL_CLIENT_LIMIT = 60
CODE_FAIL_CLIENT_WINDOW = timedelta(minutes=10)
LEDGER_RETENTION = timedelta(days=1)

KIND_MEMBERSHIP = 'membership'
KIND_CODE_FAIL = 'code_fail'

_LOOKALIKES = str.maketrans({
    'А': 'A', 'В': 'B', 'Е': 'E', 'К': 'K', 'М': 'M', 'Н': 'H', 'Р': 'P',
    'С': 'C', 'Т': 'T', 'Х': 'X', 'У': 'Y',
})


class RoomRateLimited(Exception):
    """Too many membership changes or wrong codes; ``retry_after`` is in seconds."""

    def __init__(self, message: str, retry_after: int = 60):
        super().__init__(message)
        self.retry_after = retry_after


class InviteRejected(LookupError):
    """A well-formed code that cannot be used. ``reason``: unknown|expired|revoked|exhausted."""

    def __init__(self, reason: str, message: str, room_title: str | None = None):
        super().__init__(message)
        self.reason = reason
        self.room_title = room_title


def generate_short_code() -> str:
    return ''.join(secrets.choice(SHORT_CODE_ALPHABET) for _ in range(SHORT_CODE_LENGTH))


def format_short_code(code: str) -> str:
    return f'{code[:4]}-{code[4:]}'


def normalize_short_code(value: object) -> str | None:
    """Case/hyphen/space-insensitive; Cyrillic look-alike letters count as their Latin twins."""
    if not isinstance(value, str) or len(value) > 40:
        return None
    code = ''.join(value.split()).replace('-', '').replace('–', '').replace('—', '').upper().translate(_LOOKALIKES)
    if len(code) != SHORT_CODE_LENGTH or any(char not in SHORT_CODE_ALPHABET for char in code):
        return None
    return code


_fallback_secret: str = ''


def configure_code_secret(fallback: str) -> None:
    """The application hands over a persistent secret (the Mini App bot token) as the fallback key."""
    global _fallback_secret
    _fallback_secret = fallback or ''


def _code_key() -> bytes | None:
    explicit = (os.getenv('MQB_ROOM_CODE_SECRET') or '').strip().encode()
    if len(explicit) >= 32:
        return sha256(b'room-short-code-secret:' + explicit).digest()
    if _fallback_secret:
        return sha256(b'room-short-code-token:' + _fallback_secret.encode()).digest()
    return None  # offline / tests without any secret: only the legacy unkeyed hash exists


def _legacy_hash(code: str) -> str:
    return sha256(('mqb-room-short:' + code).encode('ascii')).hexdigest()


def short_code_hash(code: str) -> str:
    """Hash stored for a new code: keyed when a persistent secret is configured."""
    key = _code_key()
    if key is None:
        return _legacy_hash(code)
    return hmac.new(key, ('mqb-room-short:' + code).encode('ascii'), hashlib.sha256).hexdigest()


def short_code_hashes(code: str) -> list[str]:
    """Every hash a stored code may carry: keyed (current) and legacy (issued before the secret)."""
    current, legacy = short_code_hash(code), _legacy_hash(code)
    return [current] if current == legacy else [current, legacy]


async def _lock(session, key: str) -> None:
    await session.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))'), {'key': key})


async def _try_lock(session, key: str) -> bool:
    return bool((await session.execute(
        text('SELECT pg_try_advisory_xact_lock(hashtextextended(:key, 0))'), {'key': key})).scalar())


async def _count(session, *, kind: str, since: datetime, account_id=None, client=None) -> tuple[int, datetime | None]:
    statement = select(func.count(), func.min(RoomJoinAttempt.created_at)).where(
        RoomJoinAttempt.kind == kind, RoomJoinAttempt.created_at > since)
    if account_id is not None:
        statement = statement.where(RoomJoinAttempt.account_id == account_id)
    if client is not None:
        statement = statement.where(RoomJoinAttempt.client_hash == client)
    count, oldest = (await session.execute(statement)).one()
    return int(count), oldest


def _retry_after(oldest, window, now) -> int:
    if oldest is None:
        return 60
    return max(1, int((oldest + window - now).total_seconds()) + 1)


async def record(session, account_id, kind: str, now: datetime, client: str | None = None) -> None:
    session.add(RoomJoinAttempt(account_id=account_id, kind=kind, created_at=now, client_hash=client))
    await session.flush()


async def charge_membership(session, account_id, now: datetime | None = None) -> None:
    """Count one membership change (enter / be let in / leave); raise when over the limit."""
    now = now or datetime.now(timezone.utc)
    await _lock(session, f'roomlimit:{KIND_MEMBERSHIP}:{account_id}')
    count, oldest = await _count(session, kind=KIND_MEMBERSHIP, account_id=account_id,
                                 since=now - MEMBERSHIP_WINDOW)
    if count >= MEMBERSHIP_LIMIT:
        raise RoomRateLimited('Слишком часто заходишь в комнаты и выходишь из них. Подожди немного.',
                              _retry_after(oldest, MEMBERSHIP_WINDOW, now))
    await record(session, account_id, KIND_MEMBERSHIP, now)
    if secrets.randbelow(20) == 0:
        await session.execute(delete(RoomJoinAttempt).where(
            RoomJoinAttempt.created_at < now - LEDGER_RETENTION))


async def check_code_entry_allowed(session, account_id, now: datetime, client: str | None = None) -> None:
    """Before looking a code up: refuse when this account or this client address guessed too much.

    ``client`` is a hash of the caller's network address (``None``: no address limit). The account lock
    is only tried: a parallel code entry of the same account is answered with a short retry instead of
    waiting, so this check can never be part of a lock cycle.
    """
    if not await _try_lock(session, f'roomlimit:{KIND_CODE_FAIL}:{account_id}'):
        raise RoomRateLimited('Предыдущий код ещё проверяется. Повтори через секунду.', 1)
    count, oldest = await _count(session, kind=KIND_CODE_FAIL, account_id=account_id,
                                 since=now - CODE_FAIL_ACCOUNT_WINDOW)
    if count >= CODE_FAIL_ACCOUNT_LIMIT:
        raise RoomRateLimited('Слишком много неверных кодов. Попробуй позже.',
                              _retry_after(oldest, CODE_FAIL_ACCOUNT_WINDOW, now))
    if client:
        count, oldest = await _count(session, kind=KIND_CODE_FAIL, client=client,
                                     since=now - CODE_FAIL_CLIENT_WINDOW)
        if count >= CODE_FAIL_CLIENT_LIMIT:
            raise RoomRateLimited('С этого адреса слишком много неверных кодов. Попробуй через несколько '
                                  'минут или открой ссылку-приглашение.',
                                  _retry_after(oldest, CODE_FAIL_CLIENT_WINDOW, now))


async def record_code_failure(session, account_id, now: datetime, client: str | None = None) -> None:
    await record(session, account_id, KIND_CODE_FAIL, now, client)
