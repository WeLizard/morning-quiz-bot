"""Persisted maintenance switch; no shell, Telegram I/O or operational JSON."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from .admin_actions import (
    AdminActions, AdminConflict, TERMINAL_GAME_STATUSES,
    operation_fence, access_allowed_in,
)
from .cleanup import CleanupQueue
from .games import GameRepository
from .models import Game, QuizSession, SystemState

KEY = 'maintenance_status'


def status(row):
    value = deepcopy(row.payload if row else {})
    return {'maintenance_mode': False, 'reason': '', 'revision': 0, **value}


class SystemControl:
    def __init__(self, database):
        self.database = database

    async def read(self):
        async with self.database.transaction() as session:
            return status(await session.get(SystemState, KEY))

    async def claim_notification(self, chat_id, user_id, *, now=None):
        """Reserve a once-per-minute notice before I/O; failed sends do not flood chats."""
        now = now or datetime.now(timezone.utc)
        async with self.database.transaction() as session:
            await operation_fence(session, exclusive=True)
            if not await access_allowed_in(session, chat_id, user_id, ignore_maintenance=True):
                return None
            row = await session.get(SystemState, KEY)
            value = status(row)
            if not value['maintenance_mode']:
                return None
            attempts = dict(value.get('notice_attempts', {}))
            previous = attempts.get(str(chat_id))
            if previous and now.timestamp() - previous < 60:
                return None
            attempts = {key: stamp for key, stamp in attempts.items() if now.timestamp() - stamp < 60}
            attempts[str(chat_id)] = now.timestamp()
            row.payload = {**value, 'notice_attempts': attempts}
            return {'reason': value['reason'], 'revision': value['revision']}

    async def notification_sent(self, chat_id, message_id, revision):
        async with self.database.transaction() as session:
            await operation_fence(session, exclusive=True)
            row = await session.get(SystemState, KEY)
            value = status(row)
            if value['maintenance_mode'] and value['revision'] == revision:
                notified = set(value.get('chats_notified', []))
                notified.add(str(chat_id))
                row.payload = {**value, 'chats_notified': sorted(notified)}
            if message_id:
                await CleanupQueue.enqueue_in(session, chat_id, message_id,
                    datetime.now(timezone.utc) + timedelta(minutes=5), source='maintenance_notice')

    async def set_maintenance(self, *, enabled, reason, expected_revision, action_id):
        reason = reason.strip()
        if not reason or len(reason) > 500 or '\x00' in reason:
            raise ValueError('Укажите причину длиной от 1 до 500 символов')
        request = dict(enabled=enabled, reason=reason, expected_revision=expected_revision)
        actions = AdminActions(self.database)
        async with self.database.transaction() as session:
            await operation_fence(session, exclusive=True)
            previous = await actions._retry(session, action_id, 'system', 0, 'maintenance', request)
            if previous:
                return previous
            await session.execute(insert(SystemState).values(key=KEY, payload={}).on_conflict_do_nothing())
            row = await session.scalar(select(SystemState).where(SystemState.key == KEY).with_for_update())
            before = status(row)
            if before['revision'] != expected_revision:
                raise AdminConflict('Режим обслуживания уже изменился. Обновите страницу.')
            interrupted = []
            if enabled:
                legacy_games = (await session.scalars(select(QuizSession).where(
                    QuizSession.status == 'active'
                ).with_for_update())).all()
                for game in legacy_games:
                    game.status = 'interrupted'; interrupted.append(game.id)
                    ids = set(game.state.get('message_ids_to_delete', [])) | set(game.state.get('results_message_ids', []))
                    for pair in game.state.get('poll_and_solution_message_ids', []):
                        if isinstance(pair, dict):
                            ids.update(pair.get(key) for key in ('poll_msg_id', 'solution_msg_id'))
                        elif isinstance(pair, (list, tuple)):
                            ids.update(mid for mid in pair if type(mid) is int)
                    for poll in game.state.get('polls', {}).values():
                        ids.update(poll.get(key) for key in ('message_id', 'solution_placeholder_message_id', 'solution_message_id'))
                    for mid in ids:
                        if type(mid) is int and mid > 0:
                            await CleanupQueue.enqueue_in(session, game.chat_id, mid, datetime.now(timezone.utc), source='maintenance')
                platform_games = (await session.scalars(select(Game).where(
                    Game.is_current.is_(True),
                    Game.status.not_in(TERMINAL_GAME_STATUSES),
                ).order_by(Game.id).with_for_update())).all()
                repository = GameRepository(session)
                for game in platform_games:
                    await repository.interrupt(game, event_kind='maintenance_interrupted')
                    interrupted.append(game.id)
            row.payload = {**before, 'maintenance_mode': enabled, 'reason': reason,
                'revision': before['revision'] + 1, 'start_time': datetime.now(timezone.utc).isoformat() if enabled else None}
            if enabled:
                row.payload = {**row.payload, 'notice_attempts': {}, 'chats_notified': []}
            return await actions._record(session, action_id, 'system', 0, 'maintenance', request, before,
                                         {**row.payload, 'interrupted_sessions': interrupted})
