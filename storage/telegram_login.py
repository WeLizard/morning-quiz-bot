"""Browser-started Telegram login requests: the bot approves, only the starting browser completes.

Only SHA-256 digests of the start token (shown in the t.me link) and of the browser secret
(HttpOnly cookie) are stored. The Telegram user id is never exposed through ``status``.
"""
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import secrets
import time
from uuid import uuid4

from sqlalchemy import delete, select

from storage.mini_app import MiniAppError
from storage.models import TelegramLoginRequest


TTL_SECONDS = 600
RETENTION = timedelta(days=1)


def _digest(value):
    return sha256(value.encode('utf-8')).hexdigest()


def _clean_name(value):
    text = ' '.join(''.join(ch if ch.isprintable() else ' ' for ch in str(value or '')).split())
    return text[:80] or None


class TelegramLogins:
    def __init__(self, database, *, clock=time.time):
        self.database, self.clock = database, clock

    def now(self):
        return datetime.fromtimestamp(self.clock(), timezone.utc)

    async def start(self, client_hint=''):
        """Creates a pending request; returns ``(request_id, start_token, browser_secret, expires_at)``."""
        now = self.now()
        request_id, start_token = uuid4().hex, secrets.token_urlsafe(24)
        browser_secret = secrets.token_urlsafe(32)
        expires = now + timedelta(seconds=TTL_SECONDS)
        async with self.database.transaction() as session:
            await session.execute(delete(TelegramLoginRequest).where(
                TelegramLoginRequest.expires_at < now - RETENTION))
            session.add(TelegramLoginRequest(
                id=request_id, start_token_hash=_digest(start_token),
                browser_secret_hash=_digest(browser_secret), status='pending',
                client_hint=(client_hint or '')[:120], created_at=now, expires_at=expires))
        return request_id, start_token, browser_secret, expires

    async def describe(self, start_token, telegram_user_id=None):
        """What the bot may show for a link: ``{id, client_hint, created_at, state}`` or None.

        ``state`` is 'pending' (buttons allowed), 'approved' (by this same user), 'expired' or 'closed'.
        Opening a link never approves anything. When a Telegram user id is given and the request
        is still pending, that user is remembered as the *viewer* (the last one to open the link,
        stored in ``telegram_user_id`` of the pending row): ``approve_by_id`` accepts only the
        viewer, so a button can be pressed only by the account the bot actually showed it to.
        """
        if not isinstance(start_token, str) or not 20 <= len(start_token) <= 64:
            return None
        async with self.database.transaction() as session:
            row = await session.scalar(select(TelegramLoginRequest).where(
                TelegramLoginRequest.start_token_hash == _digest(start_token)).with_for_update())
            if row is None:
                return None
            if (row.status == 'pending' and row.expires_at > self.now() and isinstance(telegram_user_id, int)
                    and not isinstance(telegram_user_id, bool) and telegram_user_id > 0):
                row.telegram_user_id = telegram_user_id
            if row.status in {'pending', 'approved'} and row.expires_at <= self.now():
                state = 'expired'
            elif row.status == 'pending':
                state = 'pending'
            elif row.status in {'approved', 'consumed'} and row.telegram_user_id == telegram_user_id:
                state = 'approved'
            else:
                state = 'closed'
            return {'id': row.id, 'client_hint': row.client_hint, 'created_at': row.created_at,
                    'state': state}

    async def approve(self, start_token, telegram_user_id, display_name, *, is_bot=False):
        if not isinstance(start_token, str):
            return 'unknown'
        return await self._decide('start_token_hash', _digest(start_token), telegram_user_id,
                                  display_name, approve=True, is_bot=is_bot)

    async def approve_by_id(self, request_id, telegram_user_id, display_name, *, is_bot=False):
        return await self._decide('id', request_id, telegram_user_id, display_name,
                                  approve=True, is_bot=is_bot, require_viewer=True)

    async def cancel(self, start_token, telegram_user_id, *, is_bot=False):
        if not isinstance(start_token, str):
            return 'unknown'
        return await self._decide('start_token_hash', _digest(start_token), telegram_user_id,
                                  None, approve=False, is_bot=is_bot)

    async def cancel_by_id(self, request_id, telegram_user_id, *, is_bot=False):
        return await self._decide('id', request_id, telegram_user_id, None,
                                  approve=False, is_bot=is_bot)

    async def _decide(self, column, value, uid, display_name, *, approve, is_bot, require_viewer=False):
        """Returns 'approved'|'already'|'expired'|'cancelled'|'unknown'|'taken'|'forbidden'."""
        if is_bot or not isinstance(uid, int) or isinstance(uid, bool) or uid <= 0:
            return 'forbidden'
        if not isinstance(value, str) or not value:
            return 'unknown'
        now = self.now()
        async with self.database.transaction() as session:
            row = await session.scalar(select(TelegramLoginRequest).where(
                getattr(TelegramLoginRequest, column) == value).with_for_update())
            if row is None:
                return 'unknown'
            if row.status == 'cancelled':
                return 'cancelled'
            if row.status in {'approved', 'consumed'}:
                return 'already' if row.telegram_user_id == uid else 'taken'
            if row.expires_at <= now:
                return 'expired'
            if require_viewer and row.telegram_user_id != uid:
                return 'forbidden'  # Only the user the bot showed the request to may approve it.
            row.telegram_user_id = uid
            if approve:
                row.status, row.approved_at = 'approved', now
                row.telegram_display_name = _clean_name(display_name)
                return 'approved'
            row.status = 'cancelled'
            return 'cancelled'

    async def status(self, browser_secret):
        """``{'status': pending|approved|cancelled|expired|consumed, 'expires_at': iso}``."""
        async with self.database.transaction() as session:
            row = await self._by_secret(session, browser_secret)
            return {'status': self._state(row), 'expires_at': row.expires_at.isoformat()}

    def _state(self, row):
        if row.status in {'pending', 'approved'} and row.expires_at <= self.now():
            return 'expired'
        return row.status

    @staticmethod
    async def _by_secret(session, browser_secret, *, lock=False):
        if not isinstance(browser_secret, str) or not 20 <= len(browser_secret) <= 128:
            raise MiniAppError(401, 'Вход через Telegram не начат')
        query = select(TelegramLoginRequest).where(
            TelegramLoginRequest.browser_secret_hash == _digest(browser_secret))
        if lock:
            query = query.with_for_update()
        row = await session.scalar(query.execution_options(populate_existing=True))
        if row is None:
            raise MiniAppError(404, 'Запрос входа не найден. Начните вход заново.')
        return row

    async def peek_in(self, session, browser_secret):
        """Unlocked read for the caller that needs the Telegram id before taking its advisory lock."""
        return await self._by_secret(session, browser_secret)

    async def approved_in(self, session, browser_secret, *, lock=True):
        """The approved, unexpired, unconsumed request of this browser, or MiniAppError(409/410/404)."""
        row = await self._by_secret(session, browser_secret, lock=lock)
        state = self._state(row)
        if state == 'consumed':
            raise MiniAppError(409, 'Этот вход уже использован. Начните вход заново.', code='login_used')
        if state == 'expired':
            raise MiniAppError(410, 'Время входа истекло. Начните вход заново.', code='login_expired')
        if state == 'cancelled':
            raise MiniAppError(410, 'Вход отменён. Начните вход заново.', code='login_cancelled')
        if state != 'approved' or row.telegram_user_id is None:
            raise MiniAppError(409, 'Вход ещё не подтверждён в Telegram.', code='login_pending')
        return row

    async def consume_in(self, session, row):
        row.status, row.consumed_at = 'consumed', self.now()
        await session.flush()
