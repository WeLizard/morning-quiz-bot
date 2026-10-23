"""One account principal for every web channel (Telegram Mini App, browser guest/password).

The product is account-first: Telegram is a channel, not the identity. Routes that
should serve every channel resolve the caller here instead of reading cookies.
"""
from contextlib import asynccontextmanager
from dataclasses import dataclass

from domain.address import effective_address_form
from storage import admin_actions
from storage.models import User
from storage.telegram_accounts import TelegramAccountUnavailable, telegram_account

MINI_COOKIE = 'mqb_mini'
GUEST_COOKIE = 'mqb_guest'


class PrincipalError(Exception):
    def __init__(self, code, message, status=401):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


@dataclass(frozen=True)
class Principal:
    account_id: str
    display_name: str
    channel: str  # 'telegram' | 'guest' (password login shares the guest session)
    telegram_user_id: int | None = None
    address_form: str = 'n'  # 'm' | 'f' | 'n'; Account-level, see domain/address.py
    contrast_mode: bool = False  # Account-level «Контрастный режим» (docs/design/UI_RULES.md §16)


@asynccontextmanager
async def resolve_principal(request, *, database, guest_store, mini_store, lock=False,
                            identity=None, gate=None):
    """Yield ``(session, Principal)`` inside one transaction.

    ``identity`` ('guest' | 'telegram' | None) picks the channel when a request carries both
    cookies; None with both cookies raises ``identity_required`` rather than guessing.
    ``lock`` takes the row locks used by account-owned write commands. ``gate(session, user_id)``
    is awaited after the session is verified and before the account rows are locked
    (maintenance checks); ``user_id`` is None for the guest channel.
    """
    if identity not in {None, 'guest', 'telegram'}:
        raise PrincipalError('identity', 'Неизвестный способ входа.', 422)
    guest = request.cookies.get(GUEST_COOKIE)
    telegram = request.cookies.get(MINI_COOKIE)
    if identity is None:
        if guest and telegram:
            raise PrincipalError('identity_required',
                                 'Открой приложение с главной QuizzyWizzy: нужно явно выбрать профиль.')
        identity = 'telegram' if telegram else 'guest'
    if identity == 'guest':
        async with database.transaction() as session:
            # Platform fence BEFORE guest/account row locks, matching moderation lock order.
            await admin_actions.operation_fence(session)  # attribute lookup: patchable in tests
            # MiniAppError (401/403) from the store propagates unchanged, as before.
            account, _ = await guest_store.authorized_in(
                session, guest, lock=lock, account_no_key_update=True)
            if gate is not None:
                await gate(session, None)
            yield session, Principal(str(account.id), account.display_name, 'guest',
                                     address_form=effective_address_form(account.address_form),
                                     contrast_mode=bool(getattr(account, 'contrast_mode', False)))
        return
    if not telegram:
        raise PrincipalError('authentication', 'Сначала войди через QuizzyWizzy.')
    async with mini_store.authorized(telegram, write=lock) as (session, user):
        if gate is not None:
            await gate(session, user.id)
        if lock:
            # Re-read/lock the existing Telegram user; never create a synthetic User.
            user = await session.get(User, user.id, with_for_update=True, populate_existing=True)
        if user is None or user.archived or user.bot_blocked:
            raise PrincipalError('authentication', 'Профиль недоступен.')
        try:
            account = await telegram_account(session, user, lock=lock)
        except TelegramAccountUnavailable:
            raise PrincipalError('authentication', 'Аккаунт недоступен.') from None
        yield session, Principal(str(account.id), account.display_name, 'telegram', user.id,
                                 effective_address_form(account.address_form),
                                 bool(getattr(account, 'contrast_mode', False)))
