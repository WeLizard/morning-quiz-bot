"""Account-level form of address for channels that identify a player only by Telegram id (the bot)."""
from hashlib import sha256

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert

from domain.address import effective_address_form, parse_address_form
from .admin_actions import operation_fence
from .models import Account, User
from .telegram_accounts import TelegramAccountUnavailable, telegram_account


async def telegram_address_form(database, user_id):
    """``(effective_form, chosen)`` for a Telegram user; unknown or unlinked users read as neutral."""
    async with database.transaction() as session:
        form = await session.scalar(select(Account.address_form).join(
            User, User.account_id == Account.id).where(User.id == user_id))
        return effective_address_form(form), form is not None


async def set_telegram_address_form(database, user_id, value):
    """Store the choice on the user's Account, provisioning it the way a first Mini App login does."""
    value = parse_address_form(value)
    async with database.transaction() as session:
        await operation_fence(session)
        # Same lock order as MiniAppStore.create_session: login advisory lock, then the User row.
        login_lock = -1 - int(sha256(f'mini-login:{user_id}'.encode()).hexdigest()[:15], 16)
        await session.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': login_lock})
        await session.execute(insert(User).values(id=user_id, display_name='Игрок').on_conflict_do_nothing())
        user = await session.get(User, user_id, with_for_update=True)
        account = await telegram_account(session, user, provision=True, lock=True)
        account.address_form = value
        return value
