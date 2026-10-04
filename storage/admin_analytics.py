"""Consistent report projections with honest imported-history boundaries."""
from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select, text

from .models import Chat, ChatMember, PollAnswer, SystemState, User


async def report(database, *, chat_id=None, days=30, category_names=()):
    if not 1 <= days <= 366:
        raise ValueError('Период должен быть от 1 до 366 дней')
    async with database.transaction() as session:
        await session.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
        chats = (await session.scalars(select(Chat).where(Chat.archived.is_(False)).order_by(Chat.id))).all()
        if chat_id is not None and not any(c.id == chat_id for c in chats):
            raise LookupError('Чат не найден')
        members_query = select(ChatMember).join(User, User.id == ChatMember.user_id).join(Chat, Chat.id == ChatMember.chat_id).where(User.archived.is_(False), Chat.archived.is_(False))
        if chat_id is not None:
            members_query = members_query.where(ChatMember.chat_id == chat_id)
        members = (await session.scalars(members_query)).all()
        users = (await session.scalars(select(User).where(User.archived.is_(False)))).all()
        users_by_id = {u.id: u for u in users}
        today = datetime.now(timezone.utc).date()
        start = today - timedelta(days=days - 1)
        date_expr = func.date(func.timezone('UTC', PollAnswer.answered_at))
        query = select(date_expr, func.count(), func.count().filter(PollAnswer.is_correct.is_(True))).where(
            PollAnswer.answered_at >= datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc),
            PollAnswer.answered_at < datetime.combine(today + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc))
        if chat_id is not None:
            query = query.where(PollAnswer.chat_id == chat_id)
        activity = {str(day): (count, correct) for day, count, correct in (await session.execute(query.group_by(date_expr))).all()}
        if chat_id is None:
            ranking = [(u.id, u.display_name, u.global_score, u.total_answered) for u in users]
        else:
            ranking = [(m.user_id, users_by_id[m.user_id].display_name, m.score, m.answered_count) for m in members]
        ranking.sort(key=lambda row: (-row[2], row[0]))
        leaders, previous_score, rank = [], None, 0
        for index, (uid, name, score, answers) in enumerate(ranking, 1):
            if score != previous_score:
                rank, previous_score = index, score
            leaders.append({'rank': rank, 'user_id': str(uid), 'name': name, 'score': str(score), 'classic_answers': answers})
        bins = Counter()
        for _, _, score, _ in ranking:
            bins['< 0' if score < 0 else '0' if score == 0 else '0–10' if score < 10 else '10–100' if score < 100 else '100–1000' if score < 1000 else '≥ 1000'] += 1
        state = await session.get(SystemState, 'category_usage_stats')
        categories = []
        usage = state.payload if state else {}
        for name in sorted(set(usage) | set(category_names)):
            value = usage.get(name, {})
            count = int(value.get('global_usage', value.get('total_usage', 0))) if chat_id is None else int(value.get('chat_usage', {}).get(str(chat_id), 0))
            days_since_use = max(0, (datetime.now(timezone.utc).timestamp() - value.get('last_used', datetime.now(timezone.utc).timestamp())) / 86400)
            categories.append({'name': name, 'usage': count,
                'weight': None if chat_id is None else round(100 / max(1, count) + days_since_use * 2, 3),
                'recently_used': name in usage and days_since_use < 2})
        return {
            'generated_at': datetime.now(timezone.utc).isoformat(), 'chat_id': str(chat_id) if chat_id is not None else None,
            'days': days, 'timezone': 'UTC',
            'chats': [{'id': str(c.id), 'title': c.title or f'Чат {c.id}'} for c in chats],
            'totals': {'users': len(ranking), 'memberships': len(members),
                'score': str(sum((r[2] for r in ranking), Decimal(0))),
                'classic_answers': sum(r[3] for r in ranking),
                'correct_including_photo': sum(m.correct_answers_count for m in members),
                'best_streak': max((m.max_consecutive_correct for m in members), default=0)},
            'leaderboard': leaders,
            'distribution': [{'label': key, 'users': bins[key]} for key in ('< 0', '0', '0–10', '10–100', '100–1000', '≥ 1000')],
            'activity': [{'date': str(day := start + timedelta(days=i)), 'answers': activity.get(str(day), (0, 0))[0],
                          'correct': activity.get(str(day), (0, 0))[1]} for i in range(days)],
            'categories': categories,
            'notice': 'Итоги и рейтинг — за всё время. Период применяется только к журналу новых ответов. Старые JSON-агрегаты не превращаются в выдуманную историю. Веса категорий показаны до фильтрации пула игры.',
        }
