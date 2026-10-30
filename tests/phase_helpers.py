"""Test helper: the Night City night never closes early, only the deadline worker ends it."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select


async def end_phase(db, *, room_id=None, chat_id=None):
    """Advance the due phase of the current Mafia game the way the deadline worker does.

    The clock handed to the worker is an hour ahead, so the phase is always due; the next phase gets
    its own deadline counted from that moment. Returns the public lobby or ``None`` when nothing was due.
    """
    from application.mafia import MafiaApplicationService
    from storage.models import Game

    condition = (Game.room_id == room_id) if room_id is not None else (Game.chat_id == chat_id)
    async with db.transaction() as session:
        game_id = await session.scalar(select(Game.id).where(
            condition, Game.mode == 'mafia', Game.is_current.is_(True)))
    async with db.transaction() as session:
        return await MafiaApplicationService(session).advance_due_game(
            game_id=game_id, now=datetime.now(timezone.utc) + timedelta(hours=1))
