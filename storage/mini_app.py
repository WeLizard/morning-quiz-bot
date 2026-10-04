"""Whitelisted user projections. Never expose admin payloads or correct answers."""
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import re
import secrets
import time

from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert

from .admin_actions import operation_fence
from .models import AchievementGrant, Chat, ChatMember, Game, MiniAppSession, QuizSession, User


class MiniAppError(Exception):
    def __init__(self, status, detail):
        self.status, self.detail = status, detail
        super().__init__(detail)


def token_digest(token):
    if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', token):
        raise MiniAppError(401, 'Требуется вход через Telegram')
    return sha256(token.encode()).hexdigest()


class MiniAppStore:
    def __init__(self, database, bot_token, *, clock=time.time, allowed_user_ids=None):
        self.database, self.clock = database, clock
        self.bot_key_id = sha256(bot_token.encode()).hexdigest()
        self.allowed_user_ids = frozenset(allowed_user_ids) if allowed_user_ids is not None else None

    def now(self):
        return datetime.fromtimestamp(self.clock(), timezone.utc)

    async def create_session(self, identity, *, session_limit=5):
        if self.allowed_user_ids is not None and identity.user_id not in self.allowed_user_ids:
            raise MiniAppError(403, 'Этот тестовый Mini App доступен только приглашённому игроку')
        now = self.now()
        raw_token = secrets.token_urlsafe(32)
        expires = now + timedelta(minutes=15)
        async with self.database.transaction() as session:
            await operation_fence(session)
            # Serialize login quotas without needing UPDATE permission on users.
            login_lock = -1 - int(sha256(f'mini-login:{identity.user_id}'.encode()).hexdigest()[:15], 16)
            await session.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': login_lock})
            user = await session.get(User, identity.user_id)
            if user is None or user.bot_blocked:
                raise MiniAppError(403, 'Профиль недоступен. Сначала откройте бота.')
            # Expired sessions cannot validate initData again: its TTL is only 5 min.
            await session.execute(delete(MiniAppSession).where(MiniAppSession.expires_at < now - timedelta(minutes=1)))
            replay = await session.scalar(select(MiniAppSession.token_hash).where(
                MiniAppSession.bot_key_id == self.bot_key_id,
                MiniAppSession.init_data_hash == identity.fingerprint))
            if replay:
                raise MiniAppError(409, 'Этот вход уже использован. Откройте Mini App заново.')
            count = await session.scalar(select(func.count()).select_from(MiniAppSession).where(
                MiniAppSession.user_id == user.id, MiniAppSession.bot_key_id == self.bot_key_id,
                MiniAppSession.expires_at > now))
            if session_limit is not None and count >= session_limit:
                raise MiniAppError(429, 'Слишком много входов. Повторите позже.')
            created = await session.scalar(insert(MiniAppSession).values(
                token_hash=token_digest(raw_token), bot_key_id=self.bot_key_id,
                init_data_hash=identity.fingerprint, user_id=user.id, user_revision=user.moderation_revision,
                auth_date=datetime.fromtimestamp(identity.auth_date, timezone.utc),
                created_at=now, expires_at=expires, revoked=False,
            ).on_conflict_do_nothing().returning(MiniAppSession.token_hash))
            if not created:
                raise MiniAppError(409, 'Этот вход уже использован. Откройте Mini App заново.')
        return {'access_token': raw_token, 'token_type': 'Bearer', 'expires_in': 900,
                'expires_at': expires.isoformat()}

    @asynccontextmanager
    async def authorized(self, token, *, write=False):
        digest = token_digest(token)
        async with self.database.transaction() as session:
            if write:
                await operation_fence(session)
            else:
                await session.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
            user = await session.scalar(select(User).join(MiniAppSession, MiniAppSession.user_id == User.id).where(
                MiniAppSession.token_hash == digest, MiniAppSession.bot_key_id == self.bot_key_id,
                MiniAppSession.expires_at > self.now(), MiniAppSession.revoked.is_(False),
                User.bot_blocked.is_(False), User.moderation_revision == MiniAppSession.user_revision))
            if user is None:
                raise MiniAppError(401, 'Сессия завершена. Откройте Mini App заново.')
            if self.allowed_user_ids is not None and user.id not in self.allowed_user_ids:
                raise MiniAppError(403, 'Доступ к тестовому Mini App закрыт')
            yield session, user

    async def logout(self, token):
        digest = token_digest(token)
        async with self.database.transaction() as session:
            row = await session.get(MiniAppSession, digest)
            if row and row.bot_key_id == self.bot_key_id:
                row.revoked = True  # Keep replay tombstone until expiry.

    async def profile(self, token):
        async with self.authorized(token) as (_, user):
            return {'user_id': str(user.id), 'display_name': user.display_name,
                    'score': str(user.global_score), 'answered_count': user.total_answered}

    @staticmethod
    def own_stats(member):
        return {'score': str(member.score), 'answered_count': member.answered_count,
                'correct_answers_count': member.correct_answers_count,
                'streak': member.consecutive_correct, 'best_streak': member.max_consecutive_correct}

    @staticmethod
    def visible_chat(chat, uid):
        return chat.id == uid or (chat.id < 0 and chat.type in {'group', 'supergroup'})

    async def chats(self, token, *, limit=20, offset=0):
        async with self.authorized(token) as (session, user):
            rows = (await session.execute(select(Chat, ChatMember).join(ChatMember,
                ChatMember.chat_id == Chat.id).where(ChatMember.user_id == user.id,
                    Chat.bot_blocked.is_(False), Chat.is_active.is_(True),
                    (Chat.id == user.id) | ((Chat.id < 0) & Chat.type.in_(['group', 'supergroup']))
                ).order_by(Chat.id).offset(offset).limit(limit + 1))).all()
            return {'items': [{'chat_id': str(chat.id), 'title': chat.title, 'type': chat.type,
                'own_statistics': self.own_stats(member), 'membership_verified': chat.id == user.id}
                for chat, member in rows[:limit]], 'has_more': len(rows) > limit}

    async def require_chat(self, session, uid, chat_id):
        row = (await session.execute(select(Chat, ChatMember).join(ChatMember, ChatMember.chat_id == Chat.id).where(
            Chat.id == chat_id, ChatMember.user_id == uid, Chat.is_active.is_(True), Chat.bot_blocked.is_(False)))).first()
        if not row or not self.visible_chat(row[0], uid):
            raise MiniAppError(404, 'Чат недоступен')
        return row

    async def chat_identity(self, token, chat_id):
        async with self.authorized(token) as (session, user):
            await self.require_chat(session, user.id, chat_id)
            return user.id

    async def leaderboard(self, token, chat_id, *, limit=20, offset=0):
        # The HTTP layer verifies current Telegram membership before calling this projection.
        async with self.authorized(token) as (session, user):
            await self.require_chat(session, user.id, chat_id)
            ranking = select(User.id.label('uid'), User.display_name.label('name'), ChatMember.score,
                func.rank().over(order_by=ChatMember.score.desc()).label('rank')).join(
                    ChatMember, ChatMember.user_id == User.id).where(ChatMember.chat_id == chat_id,
                        User.bot_blocked.is_(False))
            if chat_id > 0:
                ranking = ranking.where(User.id == user.id)
            ranked = ranking.subquery()
            rows = (await session.execute(select(ranked).order_by(ranked.c.score.desc(), ranked.c.uid)
                                          .offset(offset).limit(limit + 1))).mappings().all()
            return {'items': [{'rank': row['rank'], 'display_name': row['name'],
                              'score': str(row['score']), 'is_me': row['uid'] == user.id}
                             for row in rows[:limit]], 'has_more': len(rows) > limit}

    async def games(self, token, chat_id):
        async with self.authorized(token) as (session, user):
            await self.require_chat(session, user.id, chat_id)
            rows = list((await session.scalars(select(Game).where(
                Game.chat_id == chat_id,
                Game.mode.in_(['classic', 'photo']),
                Game.status == 'active',
                Game.is_current.is_(True),
            ))).all())
            items = []
            for row in rows:
                state = row.state
                if not isinstance(state, dict):
                    continue
                kind = row.mode
                photo_owner = state.get('creator_id') if state.get('mode') == 'photo' else state.get('user_id')
                if kind not in {'classic', 'photo'} or (kind == 'photo' and photo_owner != user.id):
                    continue
                phase = state.get('phase') if state.get('mode') == 'classic' else (
                    state.get('storage_phase') if kind == 'classic' else state.get('phase')
                )
                phase = phase if phase in {'active', 'question_open', 'sending', 'between'} else 'unavailable'
                if state.get('is_stopping'):
                    phase = 'stopping'
                questions = state.get('rounds') if state.get('mode') in {'classic', 'photo'} else state.get('questions')
                count = state.get('config', {}).get('question_count') if state.get('mode') in {'classic', 'photo'} else state.get(
                    'num_questions_to_ask', len(questions) if isinstance(questions, list) else 0
                )
                if state.get('mode') in {'classic', 'photo'}:
                    active_round = next((item for item in questions or []
                                         if item.get('round_id') == state.get('current_round_id')), None)
                    current = active_round['index'] + 1 if active_round else 0
                else:
                    current = state.get('current_question_index', 0)
                count = max(0, min(count, 1000)) if type(count) is int else 0
                current = max(0, min(current, count)) if type(current) is int else 0
                items.append({'kind': kind, 'phase': phase, 'question_number': current,
                              'question_count': count, 'answer_in_chat': True})
            # Explicit whitelist: no questions, correct options, hints, paths, raw UUIDs or other users' scores.
            return {'items': items}

    async def progress(self, token):
        async with self.authorized(token) as (session, user):
            members = (await session.scalars(select(ChatMember).where(ChatMember.user_id == user.id))).all()
            grants = (await session.scalars(select(AchievementGrant).where(AchievementGrant.user_id == user.id).order_by(AchievementGrant.code))).all()
            # Personal counters only, no grant metadata, admin receipts or other players.
            return {'best_streak': max((m.max_consecutive_correct for m in members), default=0),
                'current_streak': max((m.consecutive_correct for m in members), default=0),
                'correct_including_photo': sum(m.correct_answers_count for m in members),
                'achievements': [{'code': g.code, 'chat_id': str(g.chat_id)} for g in grants],
                'legacy_achievements': [{'chat_id': str(m.chat_id), 'milestones': m.milestone_codes,
                                         'streaks': m.streak_achievement_codes} for m in members],
                'first_activity': user.first_answer_at.isoformat() if user.first_answer_at else None,
                'last_activity': user.last_answer_at.isoformat() if user.last_answer_at else None}

    async def global_leaderboard(self, token, *, limit=20, offset=0):
        async with self.authorized(token) as (session, user):
            ranking = select(User.id, User.display_name, User.global_score,
                func.rank().over(order_by=User.global_score.desc()).label('rank')).where(User.bot_blocked.is_(False)).subquery()
            rows = (await session.execute(select(ranking).order_by(ranking.c.global_score.desc(), ranking.c.id).offset(offset).limit(limit + 1))).mappings().all()
            return {'items': [{'rank': row['rank'], 'display_name': row['display_name'], 'score': str(row['global_score']),
                               'is_me': row['id'] == user.id} for row in rows[:limit]], 'has_more': len(rows) > limit}

    async def chat_details(self, token, chat_id):
        async with self.authorized(token) as (session, user):
            await self.require_chat(session, user.id, chat_id)
            chat = await session.get(Chat, chat_id)
            settings = chat.settings or {}
            daily = settings.get('daily_quiz') or {}
            wisdom = settings.get('daily_wisdom') or {}
            current = settings.get('quiz') or {}
            from modules.quiz_preferences import category_preferences
            category_mode, category_pool, random_count = category_preferences(settings)
            return {'chat_id': str(chat.id), 'title': chat.title or 'Чат',
                'settings_revision': chat.settings_revision, 'can_edit': chat.id == user.id,
                'telegram_url': f'https://t.me/{chat.username}' if chat.username and re.fullmatch(r'[A-Za-z0-9_]{5,32}', chat.username) else None,
                'daily': {key: daily.get(key) for key in ('enabled', 'times_msk', 'timezone', 'num_questions',
                    'interval_seconds', 'poll_open_seconds', 'categories_mode', 'specific_categories',
                    'num_random_categories')},
                'wisdom': {'enabled': bool(wisdom.get('enabled')), 'time': wisdom.get('time'), 'timezone': daily.get('timezone', 'Europe/Moscow')},
                'auto_delete': bool(settings.get('auto_delete_bot_messages', True)),
                'classic': {'questions': current.get('num_questions', settings.get('default_num_questions', 10)),
                            'seconds': current.get('open_period_seconds', settings.get('default_open_period_seconds', 30)),
                            'interval': current.get('interval_seconds', settings.get('default_interval_seconds', 30)),
                            'announce': bool(current.get('announce', settings.get('default_announce_quiz', False))),
                            'announce_delay': current.get('announce_delay_seconds', settings.get('default_announce_delay_seconds', 5)),
                            'category_mode': category_mode, 'categories': category_pool,
                            'random_categories': random_count},
                'enabled_categories': settings.get('enabled_categories') or [],
                'disabled_categories': settings.get('disabled_categories') or [],
                'category_usage': [{'name': name, 'uses': value.get('chat_usage', 0)} for name, value in sorted((chat.category_statistics or {}).items())]}
