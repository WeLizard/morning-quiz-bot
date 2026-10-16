"""One ranking core for the app, the browser and the Telegram bot.

``rank(scope, period, game)`` reads the account score journal (``score_events`` / ``score_totals``)
and never returns identifiers: a row is ``{rank, display_name, score, is_me}``.

Scopes
  global   everybody; common points (classic, photo, admin, imported history)
  room     events of one room                       (caller checks membership)
  chat     events of one Telegram chat              (caller checks membership)
  friends  me + players who share an active room with me + accepted farm neighbours
  farm     farm XP (own slice; not part of the common rating)
  alchemy  Alchemy points (own slice; not part of the common rating)
Periods ``week`` / ``month`` are rolling 7 / 30 days over event timestamps (imported history is dated 2000-01-01,
so it never appears there); there are no resets or seasons.

Who is listed: not archived, not merged, ``rating_hidden`` off. In the public scopes (global, farm, alchemy)
the account must also have a name of its own (not the guest placeholder). The viewer always gets their own
place even when they are not listed.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy import and_, func, literal, or_, select

from storage.models import Account, RoomMembership, ScoreEvent, ScoreTotal
from storage.score_ledger import COMMON_SOURCES

SCOPES = ('global', 'room', 'chat', 'friends', 'farm', 'alchemy')
PERIODS = {'all': None, 'week': timedelta(days=7), 'month': timedelta(days=30)}
GAMES = {'all': COMMON_SOURCES, 'classic': ('classic',), 'photo': ('photo',)}
PUBLIC_SCOPES = ('global', 'farm', 'alchemy')
PLACEHOLDER_NAMES = ('', 'Гость')
MAX_LIMIT = 50


class RatingError(ValueError):
    pass


def _farm_tables():
    try:
        from qw_farm.integration import register_models
        return register_models()
    except Exception:  # farm is optional (QW_FARM_ENABLED)
        return None


def _scores(scope, game, room_id, chat_id, since, *, include_private=True, farm=None):
    """Selectable ``(account_id, score)`` before eligibility filters."""
    if scope == 'farm':
        if farm is None:
            return select(Account.id.label('account_id'), literal(0).label('score')).where(Account.id.is_(None)).subquery()
        states, ledger = farm['states'], farm['ledger']
        if since is None:
            query = select(states.c.account_id.label('account_id'), states.c.xp.label('score'))
        else:
            query = (select(states.c.account_id.label('account_id'), func.sum(ledger.c.xp_delta).label('score'))
                     .join(ledger, ledger.c.farm_id == states.c.id)
                     .where(ledger.c.created_at >= since.timestamp()).group_by(states.c.account_id))
        if not include_private:
            query = query.where(states.c.visibility != 'private')
        return query.subquery()
    sources = ('alchemy',) if scope == 'alchemy' else GAMES[game]
    if since is None and room_id is None and chat_id is None:
        query = (select(ScoreTotal.account_id.label('account_id'), func.sum(ScoreTotal.total).label('score'))
                 .where(ScoreTotal.source.in_(sources)).group_by(ScoreTotal.account_id))
        return query.subquery()
    query = select(ScoreEvent.account_id.label('account_id'), func.sum(ScoreEvent.amount).label('score')).where(
        ScoreEvent.source.in_(sources))
    if since is not None:
        query = query.where(ScoreEvent.created_at >= since)
    if room_id is not None:
        query = query.where(ScoreEvent.room_id == room_id)
    if chat_id is not None:
        query = query.where(ScoreEvent.chat_id == chat_id)
    return query.group_by(ScoreEvent.account_id).subquery()


def _eligible(scope):
    conditions = [Account.archived.is_(False), Account.merged_into_id.is_(None), Account.rating_hidden.is_(False)]
    if scope in PUBLIC_SCOPES:
        conditions.append(Account.display_name.not_in(PLACEHOLDER_NAMES))
    return and_(*conditions)


async def friend_account_ids(session, viewer: UUID, farm=None) -> set[UUID]:
    """Players who share an active room with ``viewer`` plus mutual farm neighbours, plus the viewer."""
    mine = select(RoomMembership.room_id).where(
        RoomMembership.account_id == viewer, RoomMembership.status == 'active')
    mates = {a for (a,) in (await session.execute(select(RoomMembership.account_id).where(
        RoomMembership.room_id.in_(mine), RoomMembership.status == 'active'))).all()}
    if farm is not None:
        states, pairs = farm['states'], farm['neighbor_pairs']
        farm_id = await session.scalar(select(states.c.id).where(states.c.account_id == viewer))
        if farm_id is not None:
            others = {low if high == farm_id else high for low, high in (await session.execute(
                select(pairs.c.farm_low_id, pairs.c.farm_high_id).where(
                    or_(pairs.c.farm_low_id == farm_id, pairs.c.farm_high_id == farm_id)))).all()}
            if others:
                mates |= {a for (a,) in (await session.execute(
                    select(states.c.account_id).where(states.c.id.in_(others)))).all()}
    mates.add(viewer)
    return mates


def _number(value) -> str:
    return format(Decimal(value or 0).normalize(), 'f')


async def rank(
    session, *, viewer: Optional[UUID], scope: str = 'global', period: str = 'all', game: str = 'all',
    room_id: Optional[str] = None, chat_id: Optional[int] = None, limit: int = 20, offset: int = 0,
    now: Optional[datetime] = None,
) -> dict:
    if scope not in SCOPES:
        raise RatingError('Неизвестный раздел рейтинга.')
    if period not in PERIODS:
        raise RatingError('Неизвестный период.')
    if game not in GAMES:
        raise RatingError('Неизвестная игра.')
    if scope == 'room' and not room_id or scope == 'chat' and chat_id is None:
        raise RatingError('Не указана комната или чат.')
    if scope in ('farm', 'alchemy') and game != 'all':
        raise RatingError('Фильтр по игре здесь не применяется.')
    limit = max(1, min(int(limit), MAX_LIMIT))
    offset = max(0, int(offset))
    delta = PERIODS[period]
    since = (now or datetime.now(timezone.utc)) - delta if delta else None
    farm = _farm_tables() if scope == 'farm' or scope == 'friends' else None
    friends = None
    if scope == 'friends':
        if viewer is None:
            raise RatingError('Друзья доступны только вошедшему игроку.')
        friends = await friend_account_ids(session, viewer, farm)

    def listing(include_private=False):
        s = _scores(scope, game, room_id if scope == 'room' else None, chat_id if scope == 'chat' else None,
                    since, include_private=include_private, farm=farm)
        conditions = [_eligible(scope), s.c.score > 0]
        if friends is not None:
            conditions.append(s.c.account_id.in_(friends))
        return s, conditions

    s, conditions = listing()
    ranked = (select(s.c.account_id, s.c.score, Account.display_name,
                     func.rank().over(order_by=s.c.score.desc()).label('rank'))
              .join(Account, Account.id == s.c.account_id).where(*conditions).subquery())
    rows = (await session.execute(
        select(ranked).order_by(ranked.c.rank, ranked.c.display_name, ranked.c.account_id)
        .offset(offset).limit(limit + 1))).all()
    items = [{'rank': row.rank, 'display_name': row.display_name, 'score': _number(row.score),
              'is_me': viewer is not None and row.account_id == viewer} for row in rows[:limit]]

    me = None
    if viewer is not None:
        own, _ = listing(include_private=True)
        mine = await session.scalar(select(own.c.score).where(own.c.account_id == viewer))
        account = await session.get(Account, viewer)
        listed = bool(account and account.archived is False and account.merged_into_id is None
                      and not account.rating_hidden
                      and (scope not in PUBLIC_SCOPES or account.display_name not in PLACEHOLDER_NAMES))
        place = None
        if mine is not None and Decimal(mine) > 0:
            ahead, ahead_conditions = listing()
            place = 1 + (await session.scalar(
                select(func.count()).select_from(ahead).join(Account, Account.id == ahead.c.account_id)
                .where(*ahead_conditions, ahead.c.score > mine)) or 0)
        me = {'rank': place, 'score': _number(mine), 'listed': listed,
              'hidden': bool(account and account.rating_hidden),
              'needs_nickname': bool(account and account.display_name in PLACEHOLDER_NAMES and scope in PUBLIC_SCOPES)}
    return {'scope': scope, 'period': period, 'game': game, 'items': items, 'me': me,
            'has_more': len(rows) > limit}
