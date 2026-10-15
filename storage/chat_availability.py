"""Chat availability: one place that records "the bot can no longer serve this chat".

Both the Mini App (Telegram answered "chat not found") and the bot
(my_chat_member left/kicked, group -> supergroup migration) call these helpers.
`Chat.is_active` is the existing flag: the chat list, Mini App access checks and
the daily scheduler already filter on it, so nothing else needs to change.
"""

from __future__ import annotations

import logging

from sqlalchemy import literal, select, update
from sqlalchemy.dialects.postgresql import insert

from .models import Chat, ChatMember

logger = logging.getLogger(__name__)


async def set_chat_active(database, chat_id: int, active: bool) -> bool:
    """Set `is_active`; returns True only when a row actually changed."""
    async with database.transaction() as session:
        result = await session.execute(
            update(Chat).where(Chat.id == chat_id, Chat.is_active.is_(not active))
            .values(is_active=active))
        return bool(result.rowcount)


async def migrate_chat(database, old_id: int, new_id: int) -> bool:
    """Move a group to its supergroup id: copy chat settings and members, retire the old row.

    Idempotent. Games and history stay on the old id; only what the Mini App list
    and the scheduler need (settings, members with scores) follows the new id.
    """
    if old_id == new_id:
        return False
    async with database.transaction() as session:
        old = await session.get(Chat, old_id)
        if old is None:
            return False
        await session.execute(insert(Chat).values(
            id=new_id, type='supergroup', title=old.title, username=old.username,
            settings=old.settings, settings_revision=old.settings_revision,
            statistics=old.statistics, category_statistics=old.category_statistics,
            is_active=True).on_conflict_do_nothing(index_elements=[Chat.id]))
        columns = [column.name for column in ChatMember.__table__.columns if column.name != 'chat_id']
        await session.execute(insert(ChatMember).from_select(
            ['chat_id', *columns],
            select(literal(new_id), *[getattr(ChatMember, name) for name in columns])
            .where(ChatMember.chat_id == old_id),
        ).on_conflict_do_nothing())
        await session.execute(update(Chat).where(Chat.id == old_id).values(is_active=False))
    return True
