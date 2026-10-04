"""Fresh score projections; reads never overwrite the bot's live cache."""
from sqlalchemy import and_, select
from .database import Database
from .models import ChatMember, SystemState, User
from .runtime import member_data


def _iso(value):
    return value.isoformat() if value else None


class ScoreQueries:
    def __init__(self, database: Database):
        self.database = database

    async def rating(self, chat_id: int | None = None, limit: int = 10):
        if limit <= 0:
            return []
        if chat_id is None:
            statement = select(User.id, User.display_name, User.global_score).where(User.archived.is_(False)).order_by(
                User.global_score.desc(), User.display_name, User.id,
            )
        else:
            statement = select(User.id, User.display_name, ChatMember.score).join(
                ChatMember, ChatMember.user_id == User.id,
            ).where(ChatMember.chat_id == chat_id, User.archived.is_(False)).order_by(
                ChatMember.score.desc(), User.display_name, User.id,
            )
        async with self.database.transaction() as session:
            rows = (await session.execute(statement.limit(limit))).all()
        return [{"user_id": uid, "name": name, "score": round(float(score), 1)} for uid, name, score in rows]

    async def profiles(self, chat_id: int | None, user_ids):
        ids = list({int(uid) for uid in user_ids})
        if not ids:
            return {}
        # One statement gives chat and global values from the same DB snapshot.
        statement = select(User, ChatMember).outerjoin(ChatMember, and_(
            ChatMember.user_id == User.id, ChatMember.chat_id == chat_id,
        )).where(User.id.in_(ids))
        async with self.database.transaction() as session:
            rows = (await session.execute(statement)).all()
        result = {}
        for user, member in rows:
            total = round(float(user.global_score), 1)
            global_stats = {
                "name": user.display_name, "total_score": total,
                "answered_polls": user.total_answered,
                "average_score_per_poll": round(total / user.total_answered, 2) if user.total_answered else 0.0,
                "first_answer_time_overall": _iso(user.first_answer_at),
                "last_answer_time_overall": _iso(user.last_answer_at),
            }
            chat_stats = None
            if member is not None:
                score = float(member.score)
                chat_stats = {
                    "name": user.display_name, "score": score, "total_score": round(score, 1),
                    "answered_polls": member.answered_count, "answered_polls_count": member.answered_count,
                    "correct_answers_count": member.correct_answers_count,
                    "average_score_per_poll": round(score / member.answered_count, 2) if member.answered_count else 0.0,
                    "first_answer_time": _iso(member.first_answer_at), "last_answer_time": _iso(member.last_answer_at),
                }
            result[str(user.id)] = {"chat": chat_stats, "global": global_stats}
        return result

    async def chat_statistics(self, chat_id: int):
        async with self.database.transaction() as session:
            rows = (await session.execute(select(ChatMember, User).join(
                User, User.id == ChatMember.user_id,
            ).where(ChatMember.chat_id == chat_id))).all()
            categories = await session.get(SystemState, "category_usage_stats")
        members = {str(m.user_id): dict(member_data(m, u), answered_count=m.answered_count) for m, u in rows}
        return {"users": members, "categories": categories.payload if categories else {}}
