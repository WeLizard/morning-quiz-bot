"""One verified Telegram-to-platform mapping for login and game adapters."""
from datetime import datetime, timezone

from sqlalchemy import select

from .models import Account, AccountIdentity


class TelegramAccountUnavailable(RuntimeError):
    pass


async def telegram_account(session, user, *, provision=False, lock=False, now=None):
    """Resolve a verified mapping; only provisioning may create missing rows.

    Provisioning callers hold the User lock (and the login lock for a new User).
    No historical/revoked identity is silently restored or reassigned.
    """
    if user is None or user.archived or user.bot_blocked:
        raise TelegramAccountUnavailable('Профиль недоступен.')
    statement = select(AccountIdentity).where(
        AccountIdentity.provider == 'telegram',
        AccountIdentity.provider_subject == str(user.id),
    ).order_by(AccountIdentity.revoked_at.is_(None).desc()).limit(1)
    if provision:
        statement = statement.with_for_update()
    elif lock:
        statement = statement.with_for_update(read=True)
    identity = await session.scalar(statement.execution_options(populate_existing=True))
    if identity is not None:
        if identity.revoked_at is not None:
            raise TelegramAccountUnavailable('Telegram identity was revoked; explicit recovery is required.')
        if identity.verified_at is None:
            raise TelegramAccountUnavailable('Telegram identity не подтверждена.')
        if identity.account_id != user.account_id:
            raise TelegramAccountUnavailable('Telegram identity points to a different platform account.')
    if user.account_id is None:
        if not provision:
            raise TelegramAccountUnavailable('Аккаунт не зарегистрирован.')
        account = Account(display_name=(user.display_name or 'Игрок')[:255])
        session.add(account)
        await session.flush()
        user.account_id = account.id
        await session.flush()
    else:
        # NO KEY UPDATE permits concurrent neighbour FK checks in Farm.
        account = await session.get(Account, user.account_id,
            with_for_update={'key_share': True} if lock or provision else None,
            populate_existing=True)
    if account is None or account.archived or account.bot_blocked:
        raise TelegramAccountUnavailable('Аккаунт недоступен.')
    if identity is None:
        if not provision:
            raise TelegramAccountUnavailable('Telegram identity не зарегистрирована.')
        now = now or datetime.now(timezone.utc)
        session.add(AccountIdentity(account_id=account.id, provider='telegram',
            provider_subject=str(user.id), verified_at=now, linked_at=now))
        await session.flush()
    return account
