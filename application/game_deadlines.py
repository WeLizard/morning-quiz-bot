"""Database-backed deadline runner shared by all game modes."""

from __future__ import annotations

import logging

from .classic import ClassicApplicationService
from .mafia import MafiaApplicationService
from .photo import PhotoApplicationService

logger = logging.getLogger(__name__)


class GameDeadlineProcessor:
    def __init__(self, database):
        self.database = database

    async def run_once(self, *, now=None) -> dict[str, int]:
        """Apply due transitions; every candidate is rechecked under its game lock."""
        async with self.database.transaction() as session:
            mafia_due = await MafiaApplicationService(session).due_game_ids(now=now)
            classic_due = await ClassicApplicationService(self.database, session).due(now=now)
            photo_due = await PhotoApplicationService(self.database, session).due(now=now)

        candidates = {
            'mafia': sorted(set(mafia_due)),
            'classic': sorted({item[0] for item in classic_due}),
            'photo': sorted(set(photo_due)),
        }
        settled = {mode: 0 for mode in candidates}
        for game_id in candidates['mafia']:
            result = await self._apply_one(
                'mafia', game_id,
                lambda session: MafiaApplicationService(session).advance_due_game(
                    game_id=game_id, now=now,
                ),
            )
            settled['mafia'] += result is not None

        for chat_id in candidates['classic']:
            result = await self._apply_one(
                'classic', chat_id,
                lambda session: ClassicApplicationService(
                    self.database, session,
                ).settle_due(chat_id=chat_id, now=now),
            )
            settled['classic'] += result is not None

        for chat_id in candidates['photo']:
            result = await self._apply_one(
                'photo', chat_id,
                lambda session: PhotoApplicationService(
                    self.database, session,
                ).settle_due(chat_id=chat_id, now=now),
            )
            settled['photo'] += result is not None

        if any(settled.values()):
            logger.info('Applied game deadlines: %s', settled)
        return settled

    async def _apply_one(self, mode: str, candidate_id, operation):
        """Isolate one bad/stale game so it cannot starve other due games."""
        try:
            async with self.database.transaction() as session:
                return await operation(session)
        except Exception:
            logger.exception(
                'Game deadline candidate failed (mode=%s candidate=%s)', mode, candidate_id,
            )
            return None
