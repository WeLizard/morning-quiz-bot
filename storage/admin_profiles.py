"""Read-only, consistent administrative slices; never reconstruct old events."""
import base64
from datetime import datetime
import json

from sqlalchemy import func, select, text, tuple_

from .models import Chat, ChatMember, Game, PollAnswer, QuizSession, User
from .admin_actions import TERMINAL_GAME_STATUSES

PAGE_SIZE = 50
HISTORY_NOTICE = ('Журнал содержит только записанные после миграции события. '
                  'Старые агрегаты входят в итоги, но их даты и отдельные ответы не восстанавливаются. '
                  'Начисления журнала не включают ручные изменения баллов и сбросы прогресса; '
                  'квитанции сбросов находятся в разделе доступа и безопасного сброса.')


def _iso(value):
    return value.isoformat() if value else None


def _title(chat):
    return chat.title or (chat.settings or {}).get('title') or f'Чат {chat.id}'


def encode_cursor(answer):
    raw = json.dumps([_iso(answer.answered_at), answer.poll_id, str(answer.user_id)], ensure_ascii=False).encode()
    return base64.urlsafe_b64encode(raw).decode()


def decode_cursor(value):
    try:
        if len(value) > 2048:
            raise ValueError()
        decoded = json.loads(base64.b64decode(value, altchars=b'-_', validate=True))
        if not isinstance(decoded, list) or len(decoded) != 3 or not all(isinstance(x, str) for x in decoded):
            raise ValueError()
        stamp, poll, user = decoded
        stamp = datetime.fromisoformat(stamp)
        user = int(user)
        if stamp.tzinfo is None or not 0 < len(poll) <= 255 or not -(2**63) <= user < 2**63:
            raise ValueError()
        return stamp, poll, user
    except (ValueError, TypeError, UnicodeError, OverflowError) as exc:
        raise ValueError('Некорректный курсор истории.') from exc


class AdminProfiles:
    def __init__(self, database):
        self.database = database

    async def read(self, kind, entity_id, *, members_offset=0, history_before=None):
        if kind not in {'users', 'chats'} or not 0 <= members_offset <= 1_000_000:
            raise ValueError('Недопустимая область профиля.')
        cursor = decode_cursor(history_before) if history_before else None
        async with self.database.transaction() as session:
            await session.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
            snapshot_at = await session.scalar(select(func.current_timestamp()))
            entity = await session.get(User if kind == 'users' else Chat, entity_id)
            if entity is None:
                raise LookupError('Участник не найден.' if kind == 'users' else 'Чат не найден.')
            member_scope = ChatMember.user_id == entity_id if kind == 'users' else ChatMember.chat_id == entity_id
            answer_scope = PollAnswer.user_id == entity_id if kind == 'users' else PollAnswer.chat_id == entity_id
            totals = (await session.execute(select(func.count(), func.coalesce(func.sum(ChatMember.score), 0),
                func.coalesce(func.sum(ChatMember.answered_count), 0), func.coalesce(func.sum(ChatMember.correct_answers_count), 0),
                func.coalesce(func.max(ChatMember.max_consecutive_correct), 0),
                func.min(ChatMember.first_answer_at), func.max(ChatMember.last_answer_at))
                .select_from(ChatMember).where(member_scope))).one()
            rows = (await session.execute(select(ChatMember, User, Chat)
                .join(User, User.id == ChatMember.user_id).join(Chat, Chat.id == ChatMember.chat_id)
                .where(member_scope).order_by(ChatMember.score.desc(), ChatMember.user_id, ChatMember.chat_id)
                .offset(members_offset).limit(PAGE_SIZE))).all()
            members = [{
                'user_id': str(user.id), 'name': user.display_name, 'chat_id': str(chat.id), 'chat_title': _title(chat),
                'score': str(member.score), 'classic_answers': member.answered_count,
                'correct_answers_including_photo': member.correct_answers_count,
                'current_streak': member.consecutive_correct, 'max_streak': member.max_consecutive_correct,
                'first_answer_at': _iso(member.first_answer_at), 'last_answer_at': _iso(member.last_answer_at),
                'milestone_codes': member.milestone_codes or [], 'streak_codes': member.streak_achievement_codes or [],
            } for member, user, chat in rows]
            query = select(PollAnswer, User.display_name, Chat.title).join(User, User.id == PollAnswer.user_id).join(Chat, Chat.id == PollAnswer.chat_id).where(answer_scope)
            if cursor:
                query = query.where(tuple_(PollAnswer.answered_at, PollAnswer.poll_id, PollAnswer.user_id) < tuple_(*cursor))
            history = (await session.execute(query.order_by(PollAnswer.answered_at.desc(), PollAnswer.poll_id.desc(), PollAnswer.user_id.desc()).limit(PAGE_SIZE + 1))).all()
            more = len(history) > PAGE_SIZE
            history = history[:PAGE_SIZE]
            events = [{
                'poll_id': answer.poll_id, 'user_id': str(answer.user_id), 'name': name,
                'chat_id': str(answer.chat_id), 'chat_title': title or f'Чат {answer.chat_id}',
                'answered_at': _iso(answer.answered_at), 'is_correct': answer.is_correct,
                'points_delta': str(answer.points_delta), 'kind': (answer.payload or {}).get('quiz_type', 'unknown'),
            } for answer, name, title in history]
            result = {
                'schema_version': 1, 'scope': kind, 'id': str(entity.id), 'snapshot_at': _iso(snapshot_at),
                'name': entity.display_name if kind == 'users' else _title(entity),
                'stats': {'score': str(entity.global_score) if kind == 'users' else str(totals[1]),
                    'memberships': totals[0], 'classic_answers': entity.total_answered if kind == 'users' else totals[2],
                    'correct_answers_including_photo': totals[3], 'max_streak': totals[4],
                    'first_answer_at': _iso(totals[5]), 'last_answer_at': _iso(totals[6])},
                'memberships': {'items': members, 'offset': members_offset, 'limit': PAGE_SIZE,
                                'total': totals[0], 'has_more': members_offset + PAGE_SIZE < totals[0]},
                'history': {'items': events, 'notice': HISTORY_NOTICE, 'limit': PAGE_SIZE, 'has_more': more,
                            'next_cursor': encode_cursor(history[-1][0]) if more else None},
                'export_scope': 'Текущая страница участников/чатов и журнала, не полная резервная копия.',
            }
            if kind == 'chats':
                result['chat'] = {'type': entity.type, 'settings_revision': entity.settings_revision,
                                  'daily_quiz_enabled': bool((entity.settings or {}).get('daily_quiz', {}).get('enabled'))}
                legacy_games = (await session.scalars(select(QuizSession).where(QuizSession.chat_id == entity_id,
                    QuizSession.status == 'active').order_by(QuizSession.id))).all()
                platform_games = (await session.scalars(select(Game).where(
                    Game.chat_id == entity_id,
                    Game.is_current.is_(True),
                    Game.status.not_in(TERMINAL_GAME_STATUSES),
                ).order_by(Game.id))).all()
                result['active_sessions'] = [
                    {'kind': game.kind, 'started_at': _iso(game.started_at),
                     'ends_at': _iso(game.ends_at)}
                    for game in legacy_games
                ] + [
                    {'kind': game.mode, 'started_at': _iso(game.started_at),
                     'ends_at': _iso(game.ended_at), 'phase': game.phase}
                    for game in platform_games
                ]
                # Deliberately omit future questions, correct options, tokens and raw settings.
            return result
