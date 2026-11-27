"""Who in a room can get a private Telegram message from the bot.

Room games (mafia, «Ночной город») live in the mini app; Telegram is only a nudge channel.
Only active room members with a verified, unrevoked Telegram identity qualify; the bot cannot
write to anyone else, and a player who left the room is not nudged about its tables.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import String, cast, select

from storage.models import Account, AccountIdentity, RoomMembership, User


async def telegram_members(session, room_id: str, accounts) -> list[tuple[UUID, int]]:
    """(account id, Telegram user id) of the given accounts that the bot may write to, by user id."""
    wanted = {UUID(str(value)) for value in accounts}
    if not wanted:
        return []
    active = set((await session.scalars(select(RoomMembership.account_id).where(
        RoomMembership.room_id == room_id, RoomMembership.status == 'active',
        RoomMembership.account_id.in_(wanted)))).all())
    if not active:
        return []
    rows = (await session.execute(
        select(User.account_id, User.id)
        .join(Account, Account.id == User.account_id)
        .join(AccountIdentity, AccountIdentity.account_id == User.account_id)
        .where(
            User.account_id.in_(active), User.archived.is_(False), User.bot_blocked.is_(False),
            Account.archived.is_(False), Account.bot_blocked.is_(False),
            AccountIdentity.provider == 'telegram',
            AccountIdentity.provider_subject == cast(User.id, String),
            AccountIdentity.revoked_at.is_(None), AccountIdentity.verified_at.is_not(None),
        ).order_by(User.id)
    )).all()
    return [(account_id, user_id) for account_id, user_id in rows]
