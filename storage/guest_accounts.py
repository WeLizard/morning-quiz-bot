"""Independent guest profile authentication; game/Alchemy integration is separate."""
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import re
import secrets
import time
import unicodedata

from sqlalchemy import select

from domain.address import effective_address_form, parse_address_form
from storage.mini_app import MiniAppError
from storage.models import Account, AccountIdentity, GuestSession


SESSION_SECONDS = 30 * 24 * 60 * 60


def normalize_display_name(value):
    """Plain display text: collapse whitespace and remove Unicode controls."""
    if not isinstance(value, str):
        raise MiniAppError(400, 'Имя: от 1 до 40 символов')
    cleaned = ''.join(' ' if char.isspace() else char for char in value
                      if char.isspace() or not unicodedata.category(char).startswith('C'))
    return ' '.join(cleaned.split())


def credential_hash(credential):
    if not isinstance(credential, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', credential):
        raise MiniAppError(401, 'Гостевая сессия завершена')
    return sha256(credential.encode('ascii')).hexdigest()


class GuestAccounts:
    def __init__(self, database, *, clock=time.time):
        self.database, self.clock = database, clock

    def now(self):
        return datetime.fromtimestamp(self.clock(), timezone.utc)

    @staticmethod
    def projection(account, row, login=None, telegram_user_id=None):
        return {'account_id': str(account.id), 'display_name': account.display_name,
                'authentication': 'guest', 'login': login, 'expires_at': row.expires_at.isoformat(),
                'telegram_user_id': telegram_user_id,
                'address_form': effective_address_form(account.address_form),
                'address_form_chosen': account.address_form is not None,
                'contrast_mode': bool(account.contrast_mode),
                'capabilities': ['guest-profile']}

    async def projection_in(self, session, account, row):
        telegram_user_id = await session.scalar(select(AccountIdentity.provider_subject).where(
            AccountIdentity.account_id == account.id, AccountIdentity.provider == 'telegram',
            AccountIdentity.revoked_at.is_(None), AccountIdentity.verified_at.is_not(None)))
        return self.projection(account, row, await self._login(session, account), telegram_user_id)

    @staticmethod
    async def _login(session, account):
        return await session.scalar(select(AccountIdentity.provider_subject).where(
            AccountIdentity.account_id == account.id, AccountIdentity.provider == 'password',
            AccountIdentity.revoked_at.is_(None)))

    async def _authorized(self, session, credential, *, lock=False, account_no_key_update=False):
        query = select(GuestSession).where(GuestSession.token_hash == credential_hash(credential))
        if lock:
            query = query.with_for_update()
        row = await session.scalar(query)
        if row is None or row.revoked or row.expires_at <= self.now():
            raise MiniAppError(401, 'Гостевая сессия завершена')
        query = select(Account).where(Account.id == row.account_id)
        if lock:
            # Game rosters and Farm ledgers reference other accounts while
            # holding game/room/farm locks. Their FK checks need KEY SHARE,
            # so account-owned commands must use the compatible NO KEY UPDATE.
            query = query.with_for_update(key_share=account_no_key_update)
        account = await session.scalar(query)
        if (account is None or account.archived or account.bot_blocked
                or account.moderation_revision != row.account_revision):
            raise MiniAppError(401, 'Гостевая сессия завершена')
        return account, row

    async def authorized_in(self, session, credential, *, lock=False, account_no_key_update=True):
        """Verify a credential inside the caller's transaction; returns ``(account, session_row)``.

        The caller owns the transaction and must already hold the platform operation fence
        when it intends to lock rows (see ``authorized`` for the full boundary).
        """
        return await self._authorized(session, credential, lock=lock,
                                      account_no_key_update=account_no_key_update)

    @asynccontextmanager
    async def authorized(self, credential, *, lock=False):
        """Public transaction boundary for account-owned application services."""
        async with self.database.transaction() as session:
            # Moderation takes the exclusive fence before Account locks. Every
            # guest boundary must take its shared counterpart before reading or
            # locking the session/account, including existing Mafia routes.
            from storage.admin_actions import operation_fence
            await operation_fence(session)
            account, guest_session = await self._authorized(
                session, credential, lock=lock, account_no_key_update=True,
            )
            yield session, account, guest_session

    def _session(self, account, *, created_via=None, user_agent=None):
        raw = secrets.token_urlsafe(32)
        now = self.now()
        return raw, GuestSession(token_hash=credential_hash(raw), account_id=account.id,
            account_revision=account.moderation_revision, created_at=now,
            expires_at=now + timedelta(seconds=SESSION_SECONDS), revoked=False,
            created_via=created_via, user_agent=(user_agent or '')[:120] or None)

    async def start(self, credential=None, user_agent=None):
        # A repeated start with an existing cookie never allocates another account.
        if credential is not None:
            return await self.profile(credential), None
        async with self.database.transaction() as session:
            account = Account(display_name='Гость')
            session.add(account)
            await session.flush()
            raw, row = self._session(account, created_via='guest', user_agent=user_agent)
            session.add(row)
            result = self.projection(account, row)
        return result, raw

    async def profile(self, credential):
        async with self.database.transaction() as session:
            account, row = await self._authorized(session, credential)
            return await self.projection_in(session, account, row)

    async def update_display_name(self, credential, name, *, only_placeholder=False):
        name = normalize_display_name(name)
        if only_placeholder:
            # Telegram names can exceed the profile limit. Import display text
            # only; no Telegram identity or account ownership is created here.
            name = name[:40].rstrip()
        elif not 1 <= len(name) <= 40:
            raise MiniAppError(400, 'Имя: от 1 до 40 символов')
        async with self.authorized(credential, lock=True) as (session, account, row):
            if name and (not only_placeholder or account.display_name == 'Гость'):
                account.display_name = name
            return await self.projection_in(session, account, row)

    async def update_address_form(self, credential, value):
        try:
            value = parse_address_form(value)
        except ValueError:
            raise MiniAppError(400, 'Некорректная форма обращения') from None
        async with self.authorized(credential, lock=True) as (session, account, row):
            account.address_form = value
            return await self.projection_in(session, account, row)

    async def resume(self, credential):
        async with self.database.transaction() as session:
            account, row = await self._authorized(session, credential, lock=True)
            # Stable renewal survives a lost HTTP response: retry uses the same
            # browser-held secret. Linking keeps this existing browser session.
            row.expires_at = self.now() + timedelta(seconds=SESSION_SECONDS)
            return await self.projection_in(session, account, row), credential

    async def logout(self, credential):
        if credential is None:
            return
        try:
            digest = credential_hash(credential)
        except MiniAppError:
            return  # Always allow clearing a malformed browser cookie.
        async with self.database.transaction() as session:
            row = await session.scalar(select(GuestSession).where(
                GuestSession.token_hash == digest).with_for_update())
            if row is not None:
                row.revoked = True
