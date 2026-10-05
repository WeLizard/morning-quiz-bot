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
from .models import (AchievementGrant, Chat, ChatMember, Game, GamePlayer, MiniAppSession,
                     PollAnswer, QuizSession, User)


class MiniAppError(Exception):
    def __init__(self, status, detail):
        self.status, self.detail = status, detail
        super().__init__(detail)


def token_digest(token):
    if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', token):
        raise MiniAppError(401, 'Требуется вход через Telegram')
    return sha256(token.encode()).hexdigest()


class MiniAppStore:
    def __init__(self, database, bot_token, *, clock=time.time, allowed_user_ids=None,
                 chat_achievements=None, streak_achievements=None):
        self.database, self.clock = database, clock
        self.bot_key_id = sha256(bot_token.encode()).hexdigest()
        self.allowed_user_ids = frozenset(allowed_user_ids) if allowed_user_ids is not None else None
        # Каталоги достижений: порог -> текст поздравления. Из config и data/system.
        self.chat_achievements = dict(chat_achievements or {})
        self.streak_achievements = dict(streak_achievements or {})

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

    async def renew_session(self, token, *, minutes=15):
        """Продлевает текущую сессию тем же токеном, не создавая новый вход.

        Сессия живёт 15 минут, а входов на пользователя разрешено не больше пяти за
        тот же интервал, поэтому без продления активный игрок упирался бы в отказ.
        Продление не считается новым входом и не расходует квоту.
        """
        digest = token_digest(token)
        now = self.now()
        async with self.database.transaction() as session:
            await operation_fence(session)
            row = await session.scalar(select(MiniAppSession).where(
                MiniAppSession.token_hash == digest,
                MiniAppSession.bot_key_id == self.bot_key_id,
            ).with_for_update())
            # Минутная поблажка согласована с очисткой просроченных сессий в create_session.
            if row is None or row.revoked or row.expires_at <= now - timedelta(minutes=1):
                raise MiniAppError(401, 'Сессия завершена. Откройте Mini App заново.')
            user = await session.get(User, row.user_id)
            if user is None or user.bot_blocked or user.moderation_revision != row.user_revision:
                raise MiniAppError(401, 'Сессия завершена. Откройте Mini App заново.')
            if self.allowed_user_ids is not None and user.id not in self.allowed_user_ids:
                raise MiniAppError(403, 'Доступ к тестовому Mini App закрыт')
            row.expires_at = now + timedelta(minutes=minutes)
            expires = row.expires_at
        return {'expires_in': minutes * 60, 'expires_at': expires.isoformat()}

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

    @staticmethod
    def _threshold_from_code(code):
        match = re.search(r'(-?\d+)$', str(code or ''))
        return int(match.group(1)) if match else None

    @staticmethod
    def _achievement_kind(code):
        text = str(code or '')
        if text.startswith('chat_achievement_'):
            return 'chat'
        if text.startswith('motivational_'):
            return 'motivational'
        if text.startswith('streak_'):
            return 'streak'
        return 'other'

    @staticmethod
    def _achievement_title(kind, threshold):
        if kind == 'streak':
            return f'{threshold} подряд'
        if threshold is None:
            return 'Достижение'
        if threshold > 0:
            return f'{threshold} очков'
        if threshold < 0:
            return f'минус {abs(threshold)} очков'
        return 'Старт в чате'

    @staticmethod
    def _render_achievement_message(template, *, user_name, user_score, streak):
        if not template:
            return None
        return (str(template).replace('{user_name}', user_name)
                .replace('{user_score}', user_score).replace('{streak}', str(streak)))

    async def achievements(self, token):
        """Личные достижения: что уже получено и что ещё впереди.

        Канонический источник — `achievement_grants`; коды из `chat_members`
        (легаси `milestones_achieved` / `streak_achievements_earned`) добавляются,
        чтобы старые открытия не терялись. Наружу уходят только пороги, названия,
        свои же очки и тексты поздравлений — без чужих данных и метаданных наград.
        """
        async with self.authorized(token) as (session, user):
            members = (await session.scalars(select(ChatMember).where(ChatMember.user_id == user.id))).all()
            grants = (await session.scalars(select(AchievementGrant).where(
                AchievementGrant.user_id == user.id))).all()
            chat_ids = {m.chat_id for m in members} | {g.chat_id for g in grants if g.chat_id}
            titles = dict((await session.execute(select(Chat.id, Chat.title).where(
                Chat.id.in_(chat_ids)))).all()) if chat_ids else {}

            earned = {}
            for grant in grants:
                if grant.chat_id:
                    earned.setdefault(grant.chat_id, {})[str(grant.code)] = grant.awarded_at
            for member in members:
                bucket = earned.setdefault(member.chat_id, {})
                for code in list(member.milestone_codes or []) + list(member.streak_achievement_codes or []):
                    bucket.setdefault(str(code), None)

            active = [m for m in members if earned.get(m.chat_id)]
            active.sort(key=lambda m: (float(m.score), m.chat_id), reverse=True)

            catalog = sorted(self.chat_achievements)
            streaks = sorted(self.streak_achievements)
            best_streak = max((m.max_consecutive_correct or 0 for m in members), default=0)
            best_score = f'{max((float(m.score) for m in members), default=0.0):.1f}'

            chats, earned_total = [], 0
            for member in active[:5]:
                score = str(member.score)
                seen, rows = set(), []
                for code, awarded_at in earned.get(member.chat_id, {}).items():
                    threshold = self._threshold_from_code(code)
                    if threshold in seen:
                        continue
                    seen.add(threshold)
                    rows.append({
                        'kind': self._achievement_kind(code), 'threshold': threshold,
                        'title': self._achievement_title(self._achievement_kind(code), threshold),
                        'earned': True, 'awarded_at': awarded_at.isoformat() if awarded_at else None,
                        'message': self._render_achievement_message(
                            self.chat_achievements.get(threshold), user_name=user.display_name,
                            user_score=score, streak=member.max_consecutive_correct)})
                rows.sort(key=lambda row: (row['threshold'] is None, -(row['threshold'] or 0)))
                rows = rows[:6]                     # полученные показываем выборочно
                score_value = float(member.score)
                upcoming = [t for t in catalog if t not in seen and (
                    (t > 0 and score_value < t) or (t == 0 and score_value != 0))]
                for threshold in upcoming[:3]:
                    rows.append({
                        'kind': 'chat', 'threshold': threshold,
                        'title': self._achievement_title('chat', threshold),
                        'earned': False, 'awarded_at': None,
                        'message': self._render_achievement_message(
                            self.chat_achievements.get(threshold), user_name=user.display_name,
                            user_score=score, streak=member.max_consecutive_correct)})
                earned_total += len(seen)
                chats.append({'chat_id': str(member.chat_id),
                              'title': titles.get(member.chat_id) or f'Чат {member.chat_id}',
                              'earned': len(seen), 'available': len(catalog), 'items': rows})

            streak_items = []
            for threshold in streaks[:8]:
                templates = self.streak_achievements.get(threshold) or []
                streak_items.append({
                    'kind': 'streak', 'threshold': threshold,
                    'title': self._achievement_title('streak', threshold),
                    'earned': threshold <= best_streak, 'awarded_at': None,
                    'message': self._render_achievement_message(
                        templates[0] if templates else None, user_name=user.display_name,
                        user_score=best_score, streak=threshold)})
            streak_earned = sum(1 for item in streak_items if item['earned'])
            return {'summary': {'earned': earned_total + streak_earned,
                                'available': len(catalog) + len(streaks),
                                'chat_achievements': len(catalog),
                                'streak_achievements': len(streaks)},
                    'chats': chats,
                    'streak': {'best': best_streak, 'earned': streak_earned,
                               'available': len(streaks), 'items': streak_items}}

    async def history(self, token, *, limit=20):
        """Личная история: последние игры, последние ответы и агрегаты по чатам.

        Отдельных ответов в перенесённых из JSON данных нет — там были только
        агрегаты, поэтому история по чатам строится из `chat_members`, а списки
        игр и ответов наполняются уже в PostgreSQL. Чужие строки и служебные
        payload-ы наружу не уходят.
        """
        limit = max(1, min(int(limit), 50))
        async with self.authorized(token) as (session, user):
            members = (await session.scalars(select(ChatMember).where(
                ChatMember.user_id == user.id))).all()
            recent = (await session.scalars(select(PollAnswer).where(
                PollAnswer.user_id == user.id).order_by(PollAnswer.answered_at.desc()).limit(limit))).all()
            seats = (await session.scalars(select(GamePlayer.game_id).where(
                GamePlayer.user_id == user.id))).all()
            game_ids = {row.game_id for row in recent if row.game_id} | set(seats)
            games = (await session.scalars(select(Game).where(Game.id.in_(game_ids)).order_by(
                Game.ended_at.desc().nullslast(), Game.created_at.desc()))).all() if game_ids else []
            chat_ids = ({m.chat_id for m in members} | {row.chat_id for row in recent}
                        | {game.chat_id for game in games})
            titles = dict((await session.execute(select(Chat.id, Chat.title).where(
                Chat.id.in_(chat_ids)))).all()) if chat_ids else {}

            counts = {}
            for row in recent:
                if row.game_id:
                    bucket = counts.setdefault(row.game_id, [0, 0])
                    bucket[0] += 1
                    bucket[1] += 1 if row.is_correct else 0

            answers = [{'chat_id': str(row.chat_id),
                        'chat_title': titles.get(row.chat_id) or f'Чат {row.chat_id}',
                        'is_correct': bool(row.is_correct), 'points': str(row.points_delta),
                        'answered_at': row.answered_at.isoformat() if row.answered_at else None}
                       for row in recent]
            game_items = [{'game_id': game.id, 'mode': game.mode, 'status': game.status,
                           'chat_id': str(game.chat_id),
                           'chat_title': titles.get(game.chat_id) or f'Чат {game.chat_id}',
                           'started_at': game.started_at.isoformat() if game.started_at else None,
                           'ended_at': game.ended_at.isoformat() if game.ended_at else None,
                           'my_answers': counts.get(game.id, [0, 0])[0],
                           'my_correct': counts.get(game.id, [0, 0])[1]}
                          for game in games[:10]]
            chat_items = sorted(({'chat_id': str(member.chat_id),
                                  'title': titles.get(member.chat_id) or f'Чат {member.chat_id}',
                                  'answered': int(member.answered_count or 0),
                                  'correct': int(member.correct_answers_count or 0),
                                  'score': str(member.score),
                                  'last_answer_at': member.last_answer_at.isoformat()
                                  if member.last_answer_at else None}
                                 for member in members),
                                key=lambda item: item['last_answer_at'] or '', reverse=True)[:10]
            return {'games': game_items, 'answers': answers, 'chats': chat_items}

    async def _alchemy_identity(self, token):
        async with self.authorized(token) as (session, user):
            return user.id

    async def alchemy_sync(self, token, *, discovered, crafted, attempts):
        """Принять сводку «Алхимии» и начислить очки в общий профиль.

        Очки идут только за первое открытие, суточный потолок считает сервис.
        """
        from .alchemy import AlchemyService
        return await AlchemyService(self.database).sync(
            await self._alchemy_identity(token), discovered=discovered, crafted=crafted, attempts=attempts)

    async def alchemy_progress(self, token):
        from .alchemy import AlchemyService
        return await AlchemyService(self.database).progress(await self._alchemy_identity(token))

    async def alchemy_leaderboard(self, token, *, limit=20, offset=0):
        from .alchemy import AlchemyService
        return await AlchemyService(self.database).leaderboard(
            limit=limit, offset=offset, user_id=await self._alchemy_identity(token))

    async def global_leaderboard(self, token, *, limit=20, offset=0):
        async with self.authorized(token) as (session, user):
            ranking = select(User.id, User.display_name, User.global_score,
                func.rank().over(order_by=User.global_score.desc()).label('rank')).where(User.bot_blocked.is_(False)).subquery()
            rows = (await session.execute(select(ranking).order_by(ranking.c.global_score.desc(), ranking.c.id).offset(offset).limit(limit + 1))).mappings().all()
            return {'items': [{'rank': row['rank'], 'display_name': row['display_name'], 'score': str(row['global_score']),
                               'is_me': row['id'] == user.id} for row in rows[:limit]], 'has_more': len(rows) > limit}

    async def chat_details(self, token, chat_id):
        async with self.authorized(token) as (session, user):
            chat, member = await self.require_chat(session, user.id, chat_id)
            settings = chat.settings or {}
            daily = settings.get('daily_quiz') or {}
            wisdom = settings.get('daily_wisdom') or {}
            current = settings.get('quiz') or {}
            from modules.quiz_preferences import category_preferences
            category_mode, category_pool, random_count = category_preferences(settings)
            # Личная статистика именно в этом чате: место, точность, серии и достижения.
            answered = int(member.answered_count or 0)
            correct = int(member.correct_answers_count or 0)
            better = await session.scalar(select(func.count()).select_from(ChatMember).where(
                ChatMember.chat_id == chat_id, ChatMember.score > member.score))
            members_total = await session.scalar(select(func.count()).select_from(ChatMember).where(
                ChatMember.chat_id == chat_id))
            earned = await session.scalar(select(func.count()).select_from(AchievementGrant).where(
                AchievementGrant.user_id == user.id, AchievementGrant.chat_id == chat_id))
            return {'chat_id': str(chat.id), 'title': chat.title or 'Чат',
                'settings_revision': chat.settings_revision, 'can_edit': chat.id == user.id,
                'telegram_url': f'https://t.me/{chat.username}' if chat.username and re.fullmatch(r'[A-Za-z0-9_]{5,32}', chat.username) else None,
                'me': {'score': str(member.score), 'answered': answered, 'correct': correct,
                       'accuracy': round(100 * correct / answered, 1) if answered else None,
                       'streak': int(member.consecutive_correct or 0),
                       'best_streak': int(member.max_consecutive_correct or 0),
                       'rank': int(better or 0) + 1, 'members': int(members_total or 0),
                       'achievements_earned': int(earned or 0),
                       'achievements_available': len(self.chat_achievements),
                       'first_answer_at': member.first_answer_at.isoformat() if member.first_answer_at else None,
                       'last_answer_at': member.last_answer_at.isoformat() if member.last_answer_at else None},
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
