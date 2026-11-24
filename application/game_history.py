"""Account-scoped history for browser-room games."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import cast, func, or_, select
from sqlalchemy.dialects.postgresql import JSONB, JSONPATH

from application.photo_rounds import viewer_aliases
from domain.classic import normalize_classic
from domain.photo import is_group_photo, normalize_photo
from storage.models import ClassicAccountAnswer, Game, GamePlayer, Room


def _iso(value):
    if not value:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, timezone.utc).isoformat()
    return value.isoformat()


async def account_game_history(session, account_id, *, limit=20):
    """Return the caller's Classic/Photo games in standalone rooms.

    The creator is a participant for personal Photo games even before a
    ``GamePlayer`` row exists.  Membership is deliberately not checked here:
    leaving a room must not erase the account's own history.
    """
    account_id = UUID(str(account_id))
    limit = max(1, min(int(limit), 50))
    viewer_keys = await viewer_aliases(session, account_id)
    viewer_ids = [UUID(key) for key in viewer_keys]
    participant = select(GamePlayer.game_id).where(GamePlayer.account_id.in_(viewer_ids))
    creator = Game.state['creator_account_id'].as_string().in_(viewer_keys)
    responses = [func.jsonb_path_exists(cast(Game.state, JSONB), cast(
        f'$.rounds[*].responses."{key}"', JSONPATH,
    )) for key in viewer_keys]
    rows = (await session.execute(
        select(Game, Room)
        .join(Room, Room.id == Game.room_id)
        .where(
            Room.kind == 'standalone', Game.chat_id.is_(None),
            Game.mode.in_(['classic', 'photo']),
            Game.status.in_(['finished', 'stopped', 'interrupted']),
            or_(creator, Game.id.in_(participant), *responses),
        )
        .order_by(Game.ended_at.desc().nulls_last(), Game.created_at.desc(), Game.id.desc())
        .limit(limit)
    )).all()
    if not rows:
        return []

    game_ids = [game.id for game, _ in rows]
    classic_answers = (await session.scalars(select(ClassicAccountAnswer).where(
        ClassicAccountAnswer.game_id.in_(game_ids),
        ClassicAccountAnswer.account_id.in_(viewer_ids),
    ))).all()
    answers_by_game = {}
    for answer in classic_answers:
        bucket = answers_by_game.setdefault(answer.game_id, [0, 0, 0.0])
        bucket[0] += 1
        bucket[1] += int(answer.is_correct)
        bucket[2] += float(answer.points_delta)
    player_game_ids = set((await session.scalars(select(GamePlayer.game_id).where(
        GamePlayer.game_id.in_(game_ids), GamePlayer.account_id.in_(viewer_ids),
    ))).all())

    result = []
    for game, room in rows:
        state = (
            normalize_classic(game.state, room_id=room.id)
            if game.mode == 'classic' else normalize_photo(game.state, room_id=room.id)
        )
        if state is None:
            continue
        if game.mode == 'classic':
            if (state.get('creator_account_id') not in viewer_keys
                    and game.id not in player_game_ids and game.id not in answers_by_game):
                continue
            answers, correct, score = answers_by_game.get(game.id, [0, 0, 0.0])
            questions = len(state['rounds'])
        else:
            if is_group_photo(state):
                closed = [item for item in state['rounds'] if item['status'] == 'closed']
                answers = sum(any(r.get('attempts', 0) or r.get('answered')
                                  for actor, r in item.get('responses', {}).items() if actor in viewer_keys)
                              for item in closed)
                if not answers and state.get('creator_account_id') not in viewer_keys:
                    continue
                points = [max((float(row['points']) for row in item.get('solvers', [])
                               if str(row['account_id']) in viewer_keys), default=0.0)
                          for item in closed]
                correct = sum(value > 0 for value in points)
                score = sum(points, 0.0)
            else:
                if state.get('creator_account_id') not in viewer_keys:
                    continue
                # Personal Photo has no GamePlayer row.
                answers = sum(bool(item.get('attempts') or item.get('feedback') == 'correct')
                              for item in state['rounds'])
                correct = int(state.get('total_correct', 0))
                score = float(state.get('total_score', 0.0))
            questions = len(state['rounds'])
        result.append({
            'game_id': game.id,
            'room_id': room.id,
            'room_title': room.title or 'Комната',
            'mode': game.mode,
            'status': game.status,
            'phase': game.phase,
            'is_current': bool(game.is_current),
            'started_at': _iso(game.started_at),
            'ended_at': _iso(game.ended_at) or _iso(state.get('finished_at')),
            'questions': questions,
            'my_answers': answers,
            'my_correct': correct,
            'my_score': str(score),
        })
        if len(result) >= limit:
            break
    return result
