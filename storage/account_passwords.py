"""Login + password accounts without email.

A password login is a ``password`` AccountIdentity plus an AccountCredential
row. Sessions are the existing GuestSession rows (cookie ``mqb_guest``), so
every /api/guest/* feature works for a logged-in account. Email can later be
added as another identity on the same account; nothing here depends on its absence.
"""
import asyncio
import base64
from collections import deque
import hashlib
import hmac
import re
import secrets
import time

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from domain.address import parse_address_form
from storage.guest_accounts import GuestAccounts
from storage.mini_app import MiniAppError
from storage.models import Account, AccountCredential, AccountIdentity

PROVIDER = 'password'
LOGIN_RE = re.compile(r'[a-z0-9_.-]{3,32}')
MIN_PASSWORD, MAX_PASSWORD = 8, 128
SCRYPT_N, SCRYPT_R, SCRYPT_P, SALT_BYTES, KEY_BYTES = 2 ** 14, 8, 1, 16, 32
BAD_CREDENTIALS = 'Неверный логин или пароль'


def normalize_login(value):
    login = value.strip().lower() if isinstance(value, str) else ''
    if not LOGIN_RE.fullmatch(login):
        raise MiniAppError(400, 'Логин: 3–32 символа, латиница, цифры и _ . -')
    return login


def validate_password(value):
    if not isinstance(value, str) or not MIN_PASSWORD <= len(value) <= MAX_PASSWORD:
        raise MiniAppError(400, f'Пароль: от {MIN_PASSWORD} до {MAX_PASSWORD} символов')
    return value


def _scrypt(password, salt, n, r, p, length):
    return hashlib.scrypt(password.encode('utf-8'), salt=salt, n=n, r=r, p=p,
                          dklen=length, maxmem=256 * n * r + (1 << 20))


def hash_password(password):
    salt = secrets.token_bytes(SALT_BYTES)
    key = _scrypt(password, salt, SCRYPT_N, SCRYPT_R, SCRYPT_P, KEY_BYTES)

    def b64(raw):
        return base64.b64encode(raw).decode('ascii')
    return f'scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${b64(salt)}${b64(key)}'


def verify_password(password, stored):
    """Constant-time comparison; malformed stored hashes simply fail."""
    try:
        scheme, n, r, p, salt, key = stored.split('$')
        if scheme != 'scrypt':
            return False
        expected = base64.b64decode(key)
        actual = _scrypt(password, base64.b64decode(salt), int(n), int(r), int(p), len(expected))
    except (ValueError, TypeError, AttributeError, MemoryError):
        return False
    return hmac.compare_digest(actual, expected)


_DUMMY_HASH = hash_password('dummy-password-for-timing')


class AttemptLimiter:
    """In-memory sliding window of failed logins, per login and per client IP.

    Per-process only (like RequestLimits): a restart or a second worker resets
    it, so an edge limit is still expected in production. Idle keys are pruned
    on every call and the key table is capped.
    """
    def __init__(self, limit=10, window=15 * 60, clock=time.monotonic, max_keys=10000):
        self.limit, self.window, self.clock, self.max_keys = limit, window, clock, max_keys
        self.failures = {}

    def _prune(self):
        cutoff = self.clock() - self.window
        for key in list(self.failures):
            queue = self.failures[key]
            while queue and queue[0] <= cutoff:
                queue.popleft()
            if not queue:
                del self.failures[key]

    def blocked(self, *keys):
        self._prune()
        return any(len(self.failures.get(key, ())) >= self.limit for key in keys)

    def fail(self, *keys):
        self._prune()
        now = self.clock()
        for key in keys:
            if key not in self.failures and len(self.failures) >= self.max_keys:
                continue
            self.failures.setdefault(key, deque()).append(now)

    def reset(self, key):
        self.failures.pop(key, None)


class PasswordAccounts:
    def __init__(self, guests: GuestAccounts, limiter=None):
        self.guests = guests
        self.database = guests.database
        self.limiter = limiter or AttemptLimiter()

    async def register(self, login, password, display_name=None, guest_credential=None, address_form=None,
                       user_agent=None):
        """Returns (profile, raw_cookie_or_None). With a live guest session the
        credentials attach to THAT account (progress kept, cookie unchanged)."""
        login = normalize_login(login)
        validate_password(password)
        name = None
        if display_name is not None:
            name = display_name.strip() if isinstance(display_name, str) else ''
            if not 1 <= len(name) <= 40:
                raise MiniAppError(400, 'Имя: от 1 до 40 символов')
        if address_form is not None:
            try:
                address_form = parse_address_form(address_form)
            except ValueError:
                raise MiniAppError(400, 'Некорректная форма обращения') from None
        digest = await asyncio.to_thread(hash_password, password)
        try:
            if guest_credential is not None:
                try:
                    return await self._attach(login, digest, name, guest_credential, address_form)
                except MiniAppError as error:
                    if error.status != 401:
                        raise
                    # Stale cookie: continue with a fresh account.
            return await self._create(login, digest, name, address_form, user_agent)
        except IntegrityError:
            raise MiniAppError(409, 'Этот логин уже занят') from None

    @staticmethod
    async def _taken(session, login):
        return await session.scalar(select(AccountIdentity.id).where(
            AccountIdentity.provider == PROVIDER, AccountIdentity.provider_subject == login,
            AccountIdentity.revoked_at.is_(None)))

    async def _add(self, session, account, login, digest, name, address_form=None):
        now = self.guests.now()
        session.add(AccountIdentity(account_id=account.id, provider=PROVIDER,
                                    provider_subject=login, verified_at=now))
        session.add(AccountCredential(account_id=account.id, password_hash=digest, updated_at=now))
        if name:
            account.display_name = name
        elif account.display_name == 'Гость':
            account.display_name = login
        if address_form is not None:
            account.address_form = address_form
        await session.flush()

    async def _attach(self, login, digest, name, guest_credential, address_form=None):
        async with self.guests.authorized(guest_credential, lock=True) as (session, account, row):
            existing = await session.scalar(select(AccountIdentity.id).where(
                AccountIdentity.account_id == account.id, AccountIdentity.provider == PROVIDER,
                AccountIdentity.revoked_at.is_(None)))
            if existing is not None:
                raise MiniAppError(409, 'Этот профиль уже защищён логином и паролем')
            if await self._taken(session, login):
                raise MiniAppError(409, 'Этот логин уже занят')
            await self._add(session, account, login, digest, name, address_form)
            return self.guests.projection(account, row, login), None

    async def _create(self, login, digest, name, address_form=None, user_agent=None):
        async with self.database.transaction() as session:
            from storage.admin_actions import operation_fence
            await operation_fence(session)
            if await self._taken(session, login):
                raise MiniAppError(409, 'Этот логин уже занят')
            account = Account(display_name='Гость')
            session.add(account)
            await session.flush()
            await self._add(session, account, login, digest, name, address_form)
            raw, row = self.guests._session(account, created_via='password', user_agent=user_agent)
            session.add(row)
            return self.guests.projection(account, row, login), raw

    async def login(self, login, password, client, user_agent=None):
        try:
            login = normalize_login(login)
        except MiniAppError:
            raise MiniAppError(401, BAD_CREDENTIALS) from None
        if not isinstance(password, str) or not password or len(password) > MAX_PASSWORD:
            raise MiniAppError(401, BAD_CREDENTIALS)
        keys = (f'login:{login}', f'ip:{client}')
        if self.limiter.blocked(*keys):
            raise MiniAppError(429, 'Слишком много попыток входа. Попробуй позже.')
        async with self.database.transaction() as session:
            from storage.admin_actions import operation_fence
            await operation_fence(session)
            found = (await session.execute(
                select(Account, AccountCredential.password_hash)
                .join(AccountIdentity, AccountIdentity.account_id == Account.id)
                .join(AccountCredential, AccountCredential.account_id == Account.id)
                .where(AccountIdentity.provider == PROVIDER, AccountIdentity.provider_subject == login,
                       AccountIdentity.revoked_at.is_(None)))).first()
            ok = await asyncio.to_thread(verify_password, password, found[1] if found else _DUMMY_HASH)
            account = found[0] if found else None
            if not (ok and account is not None) or account.archived or account.bot_blocked:
                self.limiter.fail(*keys)
                raise MiniAppError(401, BAD_CREDENTIALS)
            self.limiter.reset(keys[0])
            raw, row = self.guests._session(account, created_via='password', user_agent=user_agent)
            session.add(row)
            return self.guests.projection(account, row, login), raw
