"""Account score journal: the only place that changes points.

Every point of every game (quiz in a chat, quiz in a room, photo, admin corrections, imported
legacy scores, Alchemy) is one row of ``score_events`` keyed by ``(account_id, source, key)``,
so a repeated command from any channel cannot pay twice. ``score_totals`` is the per-source
running total and ``users.global_score`` is a cache of the *common* part of the journal.

Lock order inside ``award`` (continues the platform order, see ``application/account_merge``):
User FOR UPDATE -> Account FOR SHARE -> score_events -> score_totals -> users cache.
Alchemy skips the first two: its own AlchemyProgress lock already serialises it with a merge, and
taking an Account lock after it would invert the merge order (Account -> AlchemyProgress).
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import aliased

from .models import Account, ChatMember, ScoreEvent, ScoreTotal, User

# Counted by the common rating and cached in users.global_score.
COMMON_SOURCES = ('classic', 'photo', 'mafia', 'admin', 'legacy_import')
# Own slices only; never part of the common rating.
SEPARATE_SOURCES = ('alchemy',)
SOURCES = COMMON_SOURCES + SEPARATE_SOURCES
# Legacy rows get this timestamp so they never fall into a week/month window.
LEGACY_AT = datetime(2000, 1, 1, tzinfo=timezone.utc)
MAX_KEY = 300
QUANT = Decimal('0.001')
LIMIT = Decimal('99999999999.999')


class LedgerError(RuntimeError):
    pass


class AccountMerged(LedgerError):
    """The target account was merged into another one; the caller must use the main account."""


def quantize(amount) -> Decimal:
    value = Decimal(str(amount))
    if not value.is_finite() or abs(value) > LIMIT:
        raise ValueError('Score amount must be finite and fit Numeric(14,3)')
    return value.quantize(QUANT)


async def ensure_account_for_user(session, user: User) -> UUID:
    """Technical account of a Telegram profile. Caller holds the User row lock.

    Mirrors the moderation flags (a blocked player stays in the rating) and creates no identity:
    ``telegram_account(provision=True)`` adds it at the next Telegram login.
    """
    if user.account_id is not None:
        return user.account_id
    account = Account(display_name=(user.display_name or 'Игрок')[:255], archived=user.archived,
                      bot_blocked=user.bot_blocked, moderation_revision=user.moderation_revision,
                      moderation_reason=user.moderation_reason)
    session.add(account)
    await session.flush()
    user.account_id = account.id
    await session.flush()
    await _import_legacy_score(session, user, account.id)
    return account.id


async def _import_legacy_score(session, user: User, account_id: UUID) -> None:
    """A profile that reached the journal without migration 0034 (e.g. a foreign Telegram identity) keeps its score."""
    members = (await session.execute(select(ChatMember.chat_id, ChatMember.score).where(
        ChatMember.user_id == user.id, ChatMember.score != 0))).all()
    if not members and not user.global_score:
        return
    rest = Decimal(user.global_score) - sum((Decimal(score) for _, score in members), Decimal('0'))
    rows = [dict(account_id=account_id, source='legacy_import', key=f'legacy:chat:{chat}', amount=score,
                 chat_id=chat, created_at=LEGACY_AT) for chat, score in members]
    if rest:
        rows.append(dict(account_id=account_id, source='legacy_import', key='legacy:residual', amount=rest,
                         chat_id=None, created_at=LEGACY_AT))
    if rows:
        await session.execute(insert(ScoreEvent).values(rows).on_conflict_do_nothing(constraint='uq_score_events_key'))
        await RewardLedger.recompute(session, account_id)


async def account_id_for_telegram(session, user_id: int) -> UUID:
    """Resolve (provisioning if needed) the account of a Telegram user; locks the User row."""
    user = await session.scalar(select(User).where(User.id == user_id).with_for_update())
    if user is None:
        raise LookupError(f'User {user_id} does not exist')
    return await ensure_account_for_user(session, user)


class RewardLedger:
    """Namespace for the journal operations; all methods take the caller's session."""

    @staticmethod
    async def award(
        session, *, account_id: UUID, source: str, amount, key: str,
        game_id: Optional[str] = None, room_id: Optional[str] = None,
        chat_id: Optional[int] = None, at: Optional[datetime] = None,
    ) -> bool:
        """Record ``amount`` points once per ``(account_id, source, key)``.

        Returns True when applied (or when ``amount`` is zero, which is a no-op) and False when
        the same key was already recorded. Callers that have just reserved the underlying answer
        should treat False as a bug and raise.
        """
        if source not in SOURCES:
            raise ValueError(f'Unknown score source {source!r}')
        if not key or len(key) > MAX_KEY:
            raise ValueError('Score key must be 1..%d characters' % MAX_KEY)
        amount = quantize(amount)
        if amount == 0:
            return True
        account_id = UUID(str(account_id))
        common = source in COMMON_SOURCES
        if common:
            await session.execute(select(User.id).where(User.account_id == account_id).order_by(User.id).with_for_update())
            merged = (await session.execute(
                select(Account.id, Account.merged_into_id).where(Account.id == account_id).with_for_update(read=True)
            )).first()
            if merged is None:
                raise LookupError('Account does not exist')
            if merged.merged_into_id is not None:
                raise AccountMerged(str(merged.merged_into_id))
        values = dict(account_id=account_id, source=source, key=key, amount=amount,
                      game_id=game_id, room_id=room_id, chat_id=chat_id)
        if at is not None:
            values['created_at'] = at
        inserted = await session.scalar(
            insert(ScoreEvent).values(**values)
            .on_conflict_do_nothing(constraint='uq_score_events_key').returning(ScoreEvent.id))
        if inserted is None:
            return False
        totals = insert(ScoreTotal).values(account_id=account_id, source=source, total=amount, events=1)
        await session.execute(totals.on_conflict_do_update(
            index_elements=[ScoreTotal.account_id, ScoreTotal.source],
            set_={'total': ScoreTotal.total + amount, 'events': ScoreTotal.events + 1,
                  'updated_at': func.now()}))
        if common:
            await session.execute(update(User).where(User.account_id == account_id)
                                  .values(global_score=User.global_score + amount))
        return True

    @staticmethod
    async def common_total(session, account_id: UUID) -> Decimal:
        value = await session.scalar(select(func.coalesce(func.sum(ScoreEvent.amount), 0)).where(
            ScoreEvent.account_id == account_id, ScoreEvent.source.in_(COMMON_SOURCES)))
        return Decimal(value or 0)

    @staticmethod
    async def totals(session, account_id: UUID) -> dict[str, Decimal]:
        rows = (await session.execute(select(ScoreTotal.source, ScoreTotal.total)
                                      .where(ScoreTotal.account_id == account_id))).all()
        return {source: Decimal(total) for source, total in rows}

    @staticmethod
    async def recompute(session, account_id: UUID) -> dict[str, Decimal]:
        """Rebuild ``score_totals`` and the ``users.global_score`` cache of one account from events."""
        account_id = UUID(str(account_id))
        rows = (await session.execute(
            select(ScoreEvent.source, func.sum(ScoreEvent.amount), func.count())
            .where(ScoreEvent.account_id == account_id).group_by(ScoreEvent.source))).all()
        await session.execute(delete(ScoreTotal).where(ScoreTotal.account_id == account_id))
        result = {}
        for source, total, events in rows:
            await session.execute(insert(ScoreTotal).values(
                account_id=account_id, source=source, total=total, events=events))
            result[source] = Decimal(total)
        common = sum((v for k, v in result.items() if k in COMMON_SOURCES), Decimal('0'))
        await session.execute(update(User).where(User.account_id == account_id).values(global_score=common))
        return result

    @staticmethod
    async def move_events(session, *, source_account: UUID, target_account: UUID) -> int:
        """Re-point the events of a merged account to the main one.

        Events whose ``(source, key)`` already exist on the main account stay behind (the same
        round can not pay twice); totals of both accounts are rebuilt from the journal.
        """
        main = aliased(ScoreEvent)
        clash = select(1).where(main.account_id == target_account, main.source == ScoreEvent.source,
                                main.key == ScoreEvent.key).exists()
        moved = (await session.execute(
            update(ScoreEvent).where(ScoreEvent.account_id == source_account, ~clash)
            .values(account_id=target_account).execution_options(synchronize_session=False))).rowcount
        # Imported balances are per account, not per round: both accounts keep theirs, the
        # secondary's key is made unique by its own id.
        moved += (await session.execute(
            update(ScoreEvent).where(ScoreEvent.account_id == source_account, ScoreEvent.key.like('legacy:%'))
            .values(account_id=target_account, key=ScoreEvent.key + '@' + str(source_account))
            .execution_options(synchronize_session=False))).rowcount
        await RewardLedger.recompute(session, source_account)
        await RewardLedger.recompute(session, target_account)
        return moved
