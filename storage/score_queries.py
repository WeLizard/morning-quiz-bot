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
        """/top and /globaltop: the same ranking core as the app (rows carry names only)."""
        if limit <= 0:
            return []
        from application.rating import rank
        async with self.database.transaction() as session:
            result = await rank(session, viewer=None, scope='global' if chat_id is None else 'chat',
                                chat_id=chat_id, limit=limit)
        return [{"name": item["display_name"], "score": round(float(item["score"]), 1)}
                for item in result["items"]]

    async def profiles(self, chat_id: int | None, user_ids, *, with_place: bool = False):
        ids = list({int(uid) for uid in user_ids})
        if not ids:
            return {}
        # One statement gives chat and global values from the same DB snapshot.
        statement = select(User, ChatMember).outerjoin(ChatMember, and_(
            ChatMember.user_id == User.id, ChatMember.chat_id == chat_id,
        )).where(User.id.in_(ids))
        from application.rating import rank
        async with self.database.transaction() as session:
            rows = (await session.execute(statement)).all()
            places = {}
            for user, _ in rows:
                if with_place and user.account_id is not None:
                    places[user.id] = (await rank(session, viewer=user.account_id, limit=1))["me"]["rank"]
        result = {}
        for user, member in rows:
            total = round(float(user.global_score), 1)
            global_stats = {
                "place": places.get(user.id),
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
