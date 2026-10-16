"""Consistency checks of the score journal (shadow-mode reconciliation before the rating switches to it).

``reconcile`` is read-only. Every list is capped for printing; ``counts`` always has the full size.

1. totals       score_totals rows differ from sums of score_events
2. cache        users.global_score differs from the common part of the journal
3. chats        a player's chat_members.score differs from journal events with that chat_id
4. alchemy      alchemy_progress.points_total differs from the journal's Alchemy slice
5. unlinked     Telegram profiles with no account (not provisioned: they have a foreign/revoked identity)
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select

from .models import AlchemyProgress, ChatMember, ScoreEvent, ScoreTotal, User
from .score_ledger import COMMON_SOURCES

SAMPLE = 20


async def reconcile(session) -> dict:
    report: dict = {'counts': {}, 'samples': {}}

    def put(name, rows):
        report['counts'][name] = len(rows)
        report['samples'][name] = rows[:SAMPLE]

    events = {(a, s): (Decimal(t), c) for a, s, t, c in (await session.execute(
        select(ScoreEvent.account_id, ScoreEvent.source, func.sum(ScoreEvent.amount), func.count())
        .group_by(ScoreEvent.account_id, ScoreEvent.source))).all()}
    stored = {(r.account_id, r.source): (Decimal(r.total), r.events)
              for r in (await session.scalars(select(ScoreTotal))).all()}
    put('totals', [{'account': str(a), 'source': s, 'journal': str(events.get((a, s), (0, 0))[0]),
                    'stored': str(stored.get((a, s), (0, 0))[0])}
                   for (a, s) in sorted(set(events) | set(stored), key=str)
                   if events.get((a, s), (Decimal(0), 0)) != stored.get((a, s), (Decimal(0), 0))])

    common: dict = {}
    for (account, source), (total, _) in events.items():
        if source in COMMON_SOURCES:
            common[account] = common.get(account, Decimal(0)) + total
    users = (await session.execute(select(User.id, User.account_id, User.global_score))).all()
    put('cache', [{'user': uid, 'cache': str(score), 'journal': str(common.get(account, Decimal(0)))}
                  for uid, account, score in users
                  if account is not None and Decimal(score) != common.get(account, Decimal(0))])

    by_chat = {(a, c): Decimal(t) for a, c, t in (await session.execute(
        select(ScoreEvent.account_id, ScoreEvent.chat_id, func.sum(ScoreEvent.amount))
        .where(ScoreEvent.chat_id.is_not(None)).group_by(ScoreEvent.account_id, ScoreEvent.chat_id))).all()}
    members = (await session.execute(
        select(ChatMember.chat_id, ChatMember.user_id, ChatMember.score, User.account_id)
        .join(User, User.id == ChatMember.user_id))).all()
    put('chats', [{'chat': chat, 'user': uid, 'member': str(score), 'journal': str(by_chat.get((account, chat), Decimal(0)))}
                  for chat, uid, score, account in members
                  if account is not None and Decimal(score) != by_chat.get((account, chat), Decimal(0))])

    put('alchemy', [{'account': str(r.account_id), 'progress': str(r.points_total),
                     'journal': str(events.get((r.account_id, 'alchemy'), (Decimal(0), 0))[0])}
                    for r in (await session.scalars(select(AlchemyProgress))).all()
                    if Decimal(r.points_total) != events.get((r.account_id, 'alchemy'), (Decimal(0), 0))[0]])

    put('unlinked', [{'user': uid, 'score': str(score)} for uid, account, score in users if account is None])
    report['ok'] = not any(report['counts'][name] for name in ('totals', 'cache', 'chats', 'alchemy'))
    return report


async def repair(session) -> int:
    """Rebuild totals and the cache from the journal for every account that has events or totals."""
    from .score_ledger import RewardLedger
    accounts = {a for (a,) in (await session.execute(select(ScoreEvent.account_id).distinct())).all()}
    accounts |= {a for (a,) in (await session.execute(select(ScoreTotal.account_id).distinct())).all()}
    for account in accounts:
        await RewardLedger.recompute(session, account)
    return len(accounts)
