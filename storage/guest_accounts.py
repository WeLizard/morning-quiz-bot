"""Independent guest profile authentication; game/Alchemy integration is separate."""
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import re
import secrets
import time

from sqlalchemy import select

from storage.mini_app import MiniAppError
from storage.models import Account, GuestSession


SESSION_SECONDS = 30 * 24 * 60 * 60


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
    def projection(account, row):
        return {'account_id': str(account.id), 'display_name': account.display_name,
                'authentication': 'guest', 'expires_at': row.expires_at.isoformat(),
                'capabilities': ['guest-profile']}

    async def _authorized(self, session, credential, *, lock=False):
        query = select(GuestSession).where(GuestSession.token_hash == credential_hash(credential))
        if lock:
            query = query.with_for_update()
        row = await session.scalar(query)
        if row is None or row.revoked or row.expires_at <= self.now():
            raise MiniAppError(401, 'Гостевая сессия завершена')
        query = select(Account).where(Account.id == row.account_id)
        if lock:
            query = query.with_for_update()
        account = await session.scalar(query)
        if (account is None or account.archived or account.bot_blocked
                or account.moderation_revision != row.account_revision):
            raise MiniAppError(401, 'Гостевая сессия завершена')
        return account, row

    def _session(self, account):
        raw = secrets.token_urlsafe(32)
        now = self.now()
        return raw, GuestSession(token_hash=credential_hash(raw), account_id=account.id,
            account_revision=account.moderation_revision, created_at=now,
            expires_at=now + timedelta(seconds=SESSION_SECONDS), revoked=False)

    async def start(self, credential=None):
        # A repeated start with an existing cookie never allocates another account.
        if credential is not None:
            return await self.profile(credential), None
        async with self.database.transaction() as session:
            account = Account(display_name='Гость')
            session.add(account)
            await session.flush()
            raw, row = self._session(account)
            session.add(row)
            result = self.projection(account, row)
        return result, raw

    async def profile(self, credential):
        async with self.database.transaction() as session:
            account, row = await self._authorized(session, credential)
            return self.projection(account, row)

    async def resume(self, credential):
        async with self.database.transaction() as session:
            account, row = await self._authorized(session, credential, lock=True)
            # Stable renewal survives a lost HTTP response: retry uses the same
            # browser-held secret. Explicit linking/rotation is a later flow.
            row.expires_at = self.now() + timedelta(seconds=SESSION_SECONDS)
            return self.projection(account, row), credential

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
