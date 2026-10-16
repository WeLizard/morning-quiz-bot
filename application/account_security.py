"""Login/password for any account, password change/recovery and the device (session) list.

Every method runs inside a transaction opened by ``web.principal.resolve_principal`` (platform
fence and account/user locks are already held, in the project lock order), so nothing here
opens its own transaction.
"""
import asyncio
from datetime import timedelta
import re
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from storage.account_passwords import (PROVIDER, hash_password, normalize_login,
                                       validate_password, verify_password)
from storage.guest_accounts import credential_hash
from storage.mini_app import MiniAppError, token_digest
from storage.models import Account, AccountCredential, AccountIdentity, GuestSession, MiniAppSession, User

FRESH_TELEGRAM = timedelta(minutes=15)
SESSION_ID = re.compile(r'[0-9a-f]{16}')
WRONG_PASSWORD = 'Неверный текущий пароль'


class AccountSecurityService:
    def __init__(self, guest_store, password_store):
        self.guests, self.passwords = guest_store, password_store

    # -- helpers -----------------------------------------------------------------------------
    @staticmethod
    async def _identity(session, account_id, provider):
        return await session.scalar(select(AccountIdentity).where(
            AccountIdentity.account_id == account_id, AccountIdentity.provider == provider,
            AccountIdentity.revoked_at.is_(None)))

    @staticmethod
    async def _linked_user_id(session, who):
        if who.telegram_user_id is not None:
            return who.telegram_user_id
        return await session.scalar(select(User.id).where(User.account_id == UUID(who.account_id)))

    @staticmethod
    def _guest_hash(who, guest_cookie):
        return credential_hash(guest_cookie) if who.channel == 'guest' and guest_cookie else None

    @staticmethod
    def _mini_hash(who, mini_cookie):
        return token_digest(mini_cookie) if who.channel == 'telegram' and mini_cookie else None

    @staticmethod
    async def _revoke_others(session, account_id, user_id, keep_guest, keep_mini):
        query = update(GuestSession).where(GuestSession.account_id == account_id,
                                           GuestSession.revoked.is_(False))
        if keep_guest:
            query = query.where(GuestSession.token_hash != keep_guest)
        count = (await session.execute(query.values(revoked=True))).rowcount or 0
        if user_id is not None:
            query = update(MiniAppSession).where(MiniAppSession.user_id == user_id,
                                                 MiniAppSession.revoked.is_(False))
            if keep_mini:
                query = query.where(MiniAppSession.token_hash != keep_mini)
            count += (await session.execute(query.values(revoked=True))).rowcount or 0
        return count

    # -- credentials ---------------------------------------------------------------------------
    @staticmethod
    def check_credentials(login, password):
        return normalize_login(login), validate_password(password)

    @staticmethod
    async def hash(password):
        return await asyncio.to_thread(hash_password, password)

    async def set_credentials(self, session, who, login, digest):
        account_id = UUID(who.account_id)
        if await self._identity(session, account_id, PROVIDER) is not None:
            raise MiniAppError(409, 'Для этого профиля логин уже задан', code='credentials_exist')
        if await self.passwords._taken(session, login):
            raise MiniAppError(409, 'Этот логин уже занят', code='login_taken')
        account = await session.get(Account, account_id)
        try:
            # A savepoint keeps the outer transaction usable after a unique-login race.
            async with session.begin_nested():
                await self.passwords._add(session, account, login, digest, None)
        except IntegrityError:
            raise MiniAppError(409, 'Этот логин уже занят', code='login_taken') from None
        return {'account_id': who.account_id, 'login': login}

    # -- password change / recovery ------------------------------------------------------------
    async def _fresh_telegram(self, session, who, row, mini_cookie):
        """A Telegram proof younger than 15 minutes: a recent Mini App session or browser Telegram login."""
        threshold = self.guests.now() - FRESH_TELEGRAM
        if who.channel == 'telegram':
            mini = await session.get(MiniAppSession, token_digest(mini_cookie)) if mini_cookie else None
            return mini is not None and not mini.revoked and mini.created_at > threshold
        return row is not None and row.created_via == 'telegram' and row.created_at > threshold

    async def change_password(self, session, who, *, guest_cookie, mini_cookie, new_digest,
                              current_password):
        account_id = UUID(who.account_id)
        credential = await session.get(AccountCredential, account_id, with_for_update=True)
        if credential is None or await self._identity(session, account_id, PROVIDER) is None:
            raise MiniAppError(409, 'Сначала задай логин и пароль', code='no_password')
        keep_guest = self._guest_hash(who, guest_cookie)
        row = await session.get(GuestSession, keep_guest) if keep_guest else None
        key = f'account:{who.account_id}'
        if not await self._fresh_telegram(session, who, row, mini_cookie):
            if not isinstance(current_password, str) or not current_password:
                raise MiniAppError(401, WRONG_PASSWORD, code='current_password_required')
            if self.passwords.limiter.blocked(key):
                raise MiniAppError(429, 'Слишком много попыток. Попробуй позже.')
            if not await asyncio.to_thread(verify_password, current_password, credential.password_hash):
                self.passwords.limiter.fail(key)
                raise MiniAppError(401, WRONG_PASSWORD, code='current_password_wrong')
            self.passwords.limiter.reset(key)
        credential.password_hash = new_digest
        credential.updated_at = self.guests.now()
        user_id = await self._linked_user_id(session, who)
        revoked = await self._revoke_others(session, account_id, user_id, keep_guest,
                                            self._mini_hash(who, mini_cookie))
        return {'ok': True, 'revoked_sessions': revoked}

    # -- devices -------------------------------------------------------------------------------
    async def sessions(self, session, who, *, guest_cookie):
        account_id, now = UUID(who.account_id), self.guests.now()
        current = self._guest_hash(who, guest_cookie)
        rows = (await session.scalars(select(GuestSession).where(
            GuestSession.account_id == account_id, GuestSession.revoked.is_(False),
            GuestSession.expires_at > now).order_by(GuestSession.created_at.desc()))).all()
        user_id = await self._linked_user_id(session, who)
        telegram_sessions = 0
        if user_id is not None:
            telegram_sessions = len((await session.scalars(select(MiniAppSession.token_hash).where(
                MiniAppSession.user_id == user_id, MiniAppSession.revoked.is_(False),
                MiniAppSession.expires_at > now))).all())
        login = await self._identity(session, account_id, PROVIDER)
        telegram = await session.scalar(select(AccountIdentity.id).where(
            AccountIdentity.account_id == account_id, AccountIdentity.provider == 'telegram',
            AccountIdentity.revoked_at.is_(None), AccountIdentity.verified_at.is_not(None)))
        telegram_linked = telegram is not None or who.telegram_user_id is not None
        return {'sessions': [{'id': row.token_hash[:16], 'created_at': row.created_at.isoformat(),
                              'expires_at': row.expires_at.isoformat(), 'created_via': row.created_via,
                              'user_agent': row.user_agent, 'current': row.token_hash == current}
                             for row in rows],
                'telegram_sessions': telegram_sessions, 'has_password': login is not None,
                'login': login.provider_subject if login else None,
                'telegram_linked': telegram_linked,
                'can_reset_password': login is not None and telegram_linked}

    async def revoke(self, session, who, session_id):
        if not isinstance(session_id, str) or not SESSION_ID.fullmatch(session_id):
            raise MiniAppError(404, 'Сессия не найдена')
        rows = (await session.scalars(select(GuestSession).where(
            GuestSession.account_id == UUID(who.account_id),
            GuestSession.token_hash.startswith(session_id)).with_for_update())).all()
        if len(rows) != 1:
            raise MiniAppError(404, 'Сессия не найдена')
        rows[0].revoked = True
        return {'ok': True}

    async def revoke_others(self, session, who, *, guest_cookie, mini_cookie):
        user_id = await self._linked_user_id(session, who)
        count = await self._revoke_others(session, UUID(who.account_id), user_id,
                                          self._guest_hash(who, guest_cookie),
                                          self._mini_hash(who, mini_cookie))
        return {'ok': True, 'revoked_sessions': count}
