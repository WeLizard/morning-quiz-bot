"""Moderation and reset commands with a shared/exclusive transaction fence.

All score writes and session transitions acquire the shared fence BEFORE row
locks. Administrative changes take its exclusive counterpart. Normal games
remain concurrent; reset cannot race a new answer/session or manual score edit.
No Telegram I/O is performed under these locks.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
import json

from sqlalchemy import and_, select, text, or_

from .models import AdminAction, Chat, ChatMember, Game, QuizSession, User, SystemState
from .games import GameRepository

FENCE = 7319480024
COUNTERS = ('score', 'answered_count', 'correct_answers_count', 'consecutive_correct')
TERMINAL_GAME_STATUSES = ('finished', 'completed', 'stopped', 'interrupted')


class AdminConflict(ValueError):
    pass


class BotAccessBlocked(RuntimeError):
    pass


async def operation_fence(session, *, exclusive=False):
    function = 'pg_advisory_xact_lock' if exclusive else 'pg_advisory_xact_lock_shared'
    await session.execute(text(f'SELECT {function}(:key)'), {'key': FENCE})


async def access_allowed_in(session, chat_id=None, user_id=None, *, ignore_maintenance=False):
    if not ignore_maintenance:
        maintenance = await session.get(SystemState, 'maintenance_status')
        if maintenance and maintenance.payload.get('maintenance_mode'):
            return False
    # Unknown entities are allowed: the first interaction creates their profile.
    if chat_id is not None and await session.scalar(select(Chat.bot_blocked).where(Chat.id == chat_id)):
        return False
    if chat_id is not None and chat_id > 0 and await session.scalar(select(User.bot_blocked).where(User.id == chat_id)):
        return False  # Private-chat scheduled sends also obey a user's block.
    if user_id is not None and await session.scalar(select(User.bot_blocked).where(User.id == user_id)):
        return False
    return True


async def require_access(session, chat_id=None, user_id=None):
    if not await access_allowed_in(session, chat_id, user_id):
        raise BotAccessBlocked('Доступ к боту заблокирован администратором.')


async def active_platform_games(
    session, scope, target_id, *, chat_ids=(), include_group_memberships=False,
    lock=False,
):
    """Return unfinished platform games affected by a profile operation."""
    statement = select(Game).where(
        Game.is_current.is_(True),
        Game.status.not_in(TERMINAL_GAME_STATUSES),
    )
    if scope == 'chats':
        statement = statement.where(Game.chat_id == target_id)
    elif scope == 'users':
        # Blocking one member must not terminate a group game for everybody.
        # Their commands are rejected by require_access; only a private game
        # addressed to the same Telegram user is invalidated here.
        addressed_chats = ({target_id} | set(chat_ids)) if include_group_memberships else {target_id}
        statement = statement.where(or_(
            Game.chat_id.in_(addressed_chats),
            and_(
                Game.mode == 'photo',
                or_(
                    Game.state['creator_id'].as_string() == str(target_id),
                    Game.state['user_id'].as_string() == str(target_id),
                ),
            ),
        ))
    else:
        raise ValueError('Недопустимый тип профиля.')
    statement = statement.order_by(Game.id)
    if lock:
        statement = statement.with_for_update()
    return list((await session.scalars(statement)).all())


def moderation(row):
    return {'blocked': row.bot_blocked, 'revision': row.moderation_revision, 'reason': row.moderation_reason, 'archived': row.archived}


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def receipt(row):
    return {'id': row.id, 'scope': row.scope, 'target_id': str(row.target_id), 'kind': row.kind,
            'created_at': row.created_at.isoformat(), 'request': row.request,
            'before': row.before, 'after': row.after, 'actor': 'local-admin-session'}


class AdminActions:
    def __init__(self, database):
        self.database = database

    async def allowed(self, chat_id=None, user_id=None, *, ignore_maintenance=False):
        async with self.database.transaction() as session:
            return await access_allowed_in(session, chat_id, user_id, ignore_maintenance=ignore_maintenance)

    async def session_active(self, key, session_id):
        async with self.database.transaction() as session:
            if key.startswith(('classic:', 'photo:')):
                try:
                    chat_id = int(key.split(':', 1)[1])
                except ValueError:
                    return False
                mode = key.split(':', 1)[0]
                game = await session.scalar(select(Game).where(
                    Game.chat_id == chat_id,
                    Game.mode == mode,
                    Game.is_current.is_(True),
                ))
                if game is not None:
                    return bool(
                        game.status == 'active'
                        and game.state.get('session_id') == session_id
                    )
            row = await session.get(QuizSession, key)
            return bool(row and row.status == 'active' and row.state.get('session_id') == session_id)

    async def _target(self, session, scope, target_id):
        if scope not in {'users', 'chats'}:
            raise ValueError('Недопустимый тип профиля.')
        row = await session.get(User if scope == 'users' else Chat, target_id)
        if row is None:
            raise LookupError('Профиль не найден.')
        return row

    async def state(self, scope, target_id):
        async with self.database.transaction() as session:
            row = await self._target(session, scope, target_id)
            actions = (await session.scalars(select(AdminAction).where(
                AdminAction.scope == scope, AdminAction.target_id == target_id
            ).order_by(AdminAction.created_at.desc(), AdminAction.id).limit(20))).all()
            return {**moderation(row), 'actions': [
                {'id': a.id, 'kind': a.kind, 'created_at': a.created_at.isoformat()} for a in actions]}

    async def read_receipt(self, action_id):
        async with self.database.transaction() as session:
            row = await session.get(AdminAction, action_id)
            if row is None:
                raise LookupError('Квитанция не найдена.')
            return receipt(row)

    async def _retry(self, session, action_id, scope, target_id, kind, request):
        row = await session.get(AdminAction, action_id)
        if row:
            if (row.scope, row.target_id, row.kind, row.request) != (scope, target_id, kind, request):
                raise AdminConflict('Идентификатор операции уже использован для другого действия.')
            return receipt(row)

    async def _record(self, session, action_id, scope, target_id, kind, request, before, after):
        row = AdminAction(id=action_id, scope=scope, target_id=target_id, kind=kind,
                          request=request, before=before, after=after)
        session.add(row)
        await session.flush()
        return receipt(row)

    async def block(self, scope, target_id, *, blocked, reason, expected_revision, action_id):
        reason = reason.strip()
        if not reason or len(reason) > 500 or '\x00' in reason:
            raise ValueError('Укажите причину: от 1 до 500 символов.')
        request = dict(blocked=blocked, reason=reason, expected_revision=expected_revision)
        async with self.database.transaction() as session:
            await operation_fence(session, exclusive=True)
            previous = await self._retry(session, action_id, scope, target_id, 'moderation', request)
            if previous:
                return previous
            row = await self._target(session, scope, target_id)
            if row.moderation_revision != expected_revision:
                raise AdminConflict('Блокировка уже изменена. Обновите профиль.')
            if row.archived and not blocked:
                raise AdminConflict('Сначала восстановите профиль из архива, затем разблокируйте.')
            before = moderation(row)
            row.bot_blocked, row.moderation_reason = blocked, reason
            row.moderation_revision += 1
            interrupted = []
            if blocked:
                legacy_games = (await session.scalars(select(QuizSession).where(QuizSession.status == 'active')
                                                      .order_by(QuizSession.id).with_for_update())).all()
                for game in legacy_games:
                    if (scope == 'chats' and game.chat_id == target_id) or (
                        scope == 'users' and (game.chat_id == target_id or
                            (game.kind == 'photo' and str(game.state.get('user_id')) == str(target_id)))):
                        game.status = 'interrupted'
                        interrupted.append(game.id)
                        from .cleanup import CleanupQueue
                        state = game.state
                        ids = set(state.get('message_ids_to_delete', [])) | set(state.get('results_message_ids', []))
                        for poll in state.get('polls', {}).values():
                            ids.update(poll.get(key) for key in ('message_id', 'solution_placeholder_message_id', 'solution_message_id'))
                        for pair in state.get('poll_and_solution_message_ids', []):
                            ids.update(pair.get(key) for key in ('poll_msg_id', 'solution_msg_id'))
                        for mid in ids - {None}:
                            await CleanupQueue.enqueue_in(session, game.chat_id, mid,
                                datetime.now(timezone.utc) + timedelta(seconds=180), source='moderation')
                platform_games = await active_platform_games(
                    session, scope, target_id, lock=True,
                )
                repository = GameRepository(session)
                for game in platform_games:
                    from .cleanup import CleanupQueue
                    state = game.state or {}
                    ids = set(state.get('message_ids_to_delete', [])) | set(
                        state.get('results_message_ids', [])
                    )
                    for poll in (state.get('polls') or {}).values():
                        if isinstance(poll, dict):
                            ids.update(poll.get(key) for key in (
                                'message_id', 'solution_placeholder_message_id',
                                'solution_message_id',
                            ))
                    for pair in state.get('poll_and_solution_message_ids', []):
                        if isinstance(pair, dict):
                            ids.update(pair.get(key) for key in ('poll_msg_id', 'solution_msg_id'))
                    for message_id in ids:
                        if type(message_id) is int and message_id > 0:
                            await CleanupQueue.enqueue_in(
                                session, game.chat_id, message_id,
                                datetime.now(timezone.utc) + timedelta(seconds=180),
                                source='moderation',
                            )
                    await repository.interrupt(
                        game, event_kind='moderation_interrupted',
                        actor_user_id=target_id if scope == 'users' else None,
                    )
                    interrupted.append(
                        f'classic:{game.chat_id}' if game.mode == 'classic' else game.id
                    )
            return await self._record(session, action_id, scope, target_id, 'moderation', request,
                                      before, {**moderation(row), 'interrupted_sessions': interrupted})

    async def archive(self, scope, target_id, *, archived, expected_revision, confirmation, action_id):
        if confirmation != str(target_id):
            raise ValueError('Введите ID профиля целиком')
        request = dict(archived=archived, expected_revision=expected_revision, confirmation=confirmation)
        async with self.database.transaction() as session:
            await operation_fence(session, exclusive=True)
            previous = await self._retry(session, action_id, scope, target_id, 'archive', request)
            if previous:
                return previous
            row = await self._target(session, scope, target_id)
            if row.moderation_revision != expected_revision:
                raise AdminConflict('Профиль изменился. Обновите его.')
            if archived and not row.bot_blocked:
                raise AdminConflict('Сначала заблокируйте профиль: это остановит его игровые действия.')
            before = moderation(row)
            row.archived = archived
            row.moderation_revision += 1
            return await self._record(session, action_id, scope, target_id, 'archive', request, before, moderation(row))

    async def _reset_snapshot(self, session, scope, target_id):
        target = await self._target(session, scope, target_id)
        query = select(ChatMember).where(ChatMember.user_id == target_id if scope == 'users' else ChatMember.chat_id == target_id)
        members = (await session.scalars(query.order_by(ChatMember.chat_id, ChatMember.user_id))).all()
        user_ids = {m.user_id for m in members} | ({target_id} if scope == 'users' else set())
        users = (await session.scalars(select(User).where(User.id.in_(user_ids)).order_by(User.id))).all()
        chats = {m.chat_id for m in members} | ({target_id} if scope == 'chats' else set())
        legacy_games = (await session.scalars(select(QuizSession).where(QuizSession.status == 'active', or_(
            QuizSession.chat_id.in_(chats), or_(QuizSession.state['user_id'].as_string() == str(target_id),
                QuizSession.state['created_by_user_id'].as_string() == str(target_id), QuizSession.chat_id == target_id) if scope == 'users' else False
        )).order_by(QuizSession.id))).all()
        platform_games = await active_platform_games(
            session, scope, target_id, chat_ids=chats,
            include_group_memberships=scope == 'users',
        )
        snapshot = {
            'scope': scope, 'target_id': str(target_id), 'name': target.display_name if scope == 'users' else target.title,
            'members': [{'chat_id': str(m.chat_id), 'user_id': str(m.user_id),
                         **{key: str(getattr(m, key)) if key == 'score' else getattr(m, key) for key in COUNTERS},
                         'version': m.updated_at.isoformat()} for m in members],
            'users': [{'user_id': str(u.id), 'global_score': str(u.global_score), 'total_answered': u.total_answered,
                       'version': u.updated_at.isoformat()} for u in users],
            'active_sessions': [g.id for g in legacy_games] + [g.id for g in platform_games],
        }
        return snapshot, members, users

    async def preview_reset(self, scope, target_id):
        async with self.database.transaction() as session:
            await operation_fence(session, exclusive=True)
            snapshot, _, _ = await self._reset_snapshot(session, scope, target_id)
            return {**snapshot, 'version': digest(snapshot)}

    async def reset(self, scope, target_id, *, expected_version, confirmation, action_id):
        if confirmation != str(target_id):
            raise ValueError('Для подтверждения введите ID профиля целиком.')
        request = dict(expected_version=expected_version, confirmation=confirmation)
        async with self.database.transaction() as session:
            await operation_fence(session, exclusive=True)
            previous = await self._retry(session, action_id, scope, target_id, 'reset', request)
            if previous:
                return previous
            before, members, users = await self._reset_snapshot(session, scope, target_id)
            if before['active_sessions']:
                raise AdminConflict('Сброс недоступен во время активной игры в затронутых чатах.')
            if digest(before) != expected_version:
                raise AdminConflict('Прогресс изменился. Загрузите новый предварительный просмотр.')
            by_id = {u.id: u for u in users}
            for member in members:
                user = by_id[member.user_id]
                if scope == 'chats' and user.total_answered < member.answered_count:
                    raise AdminConflict('Глобальный счётчик ответов меньше вклада чата. Сначала нужна сверка данных; ничего не сброшено.')
                user.global_score -= member.score
                user.total_answered -= member.answered_count
                for key in COUNTERS:
                    setattr(member, key, Decimal('0.000') if key == 'score' else 0)
            if scope == 'users':
                by_id[target_id].global_score = Decimal('0.000')
                by_id[target_id].total_answered = 0
            await session.flush()
            after, _, _ = await self._reset_snapshot(session, scope, target_id)
            return await self._record(session, action_id, scope, target_id, 'reset', request, before, after)
