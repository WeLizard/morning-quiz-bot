"""Previewed, auditable OFFLINE broadcasts. This module has no network transport."""
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select

from .admin_actions import AdminActions, AdminConflict, access_allowed_in, operation_fence
from .models import Chat, SystemState

PREFIX = 'dev_broadcast:'


class OfflineDelivery:
    """Deterministic outcome injection for local acceptance, never Telegram I/O."""
    def __init__(self, outcomes=None):
        self.outcomes = outcomes or {}

    def deliver(self, chat_id, message):
        outcome = self.outcomes.get(chat_id, 'simulated')
        if outcome not in {'simulated', 'simulated_rejected', 'simulated_unknown'}:
            raise ValueError('Unknown offline delivery outcome')
        return outcome


class Broadcasts:
    def __init__(self, database, delivery=None):
        self.database = database
        self.delivery = delivery or OfflineDelivery()

    async def preview(self, *, draft_id, chat_ids, message):
        draft_id = str(UUID(draft_id))
        message = message.strip()
        if not message or '\x00' in message or len(message.encode('utf-16-le')) // 2 > 4000:
            raise ValueError('Сообщение должно содержать от 1 до 4000 символов Telegram')
        if not 1 <= len(chat_ids) <= 100 or any(type(cid) is not int or not -(2**63) <= cid < 2**63 for cid in chat_ids):
            raise ValueError('Выберите от 1 до 100 чатов явно')
        chat_ids = sorted(set(chat_ids))
        async with self.database.transaction() as session:
            await operation_fence(session, exclusive=True)
            previous = await session.get(SystemState, PREFIX + draft_id)
            if previous:
                if (previous.payload['chat_ids'], previous.payload['message']) != (chat_ids, message):
                    raise AdminConflict('ID предпросмотра уже использован. Создайте новый.')
                return previous.payload
            chats = (await session.scalars(select(Chat).where(Chat.id.in_(chat_ids)))).all()
            if len(chats) != len(chat_ids):
                raise LookupError('Один из выбранных чатов отсутствует')
            if any(c.archived for c in chats):
                raise ValueError('Архивные чаты не могут быть адресатами')
            draft = {'id': draft_id, 'mode': 'offline', 'telegram_delivery': False, 'chat_ids': chat_ids,
                     'message': message, 'created_at': datetime.now(timezone.utc).isoformat(),
                     'expires_at': (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat(),
                     'targets': [{'id': str(c.id), 'title': c.title, 'blocked': c.bot_blocked} for c in chats],
                     'confirmation': f'SIMULATE {len(chat_ids)}', 'report': None}
            session.add(SystemState(key=PREFIX + draft_id, payload=draft))
            return draft

    async def simulate(self, draft_id, *, confirmation):
        draft_id = str(UUID(draft_id))
        async with self.database.transaction() as session:
            await operation_fence(session, exclusive=True)
            row = await session.get(SystemState, PREFIX + draft_id)
            if row is None:
                raise LookupError('Предпросмотр не найден')
            draft = row.payload
            if confirmation != draft['confirmation']:
                raise ValueError('Подтвердите точное число адресатов')
            if draft['report'] is not None:
                return draft['report']
            if datetime.fromisoformat(draft['expires_at']) <= datetime.now(timezone.utc):
                raise AdminConflict('Предпросмотр истёк. Подготовьте новый.')
            results = []
            for cid in draft['chat_ids']:
                chat = await session.get(Chat, cid)
                if not chat or chat.archived or not await access_allowed_in(session, chat_id=cid):
                    outcome = 'skipped_blocked'
                else:
                    # Synchronous offline function; no network under the transaction fence.
                    outcome = self.delivery.deliver(cid, draft['message'])
                results.append({'chat_id': str(cid), 'status': outcome})
            report = {'id': draft_id, 'mode': 'offline', 'telegram_delivery': False, 'results': results,
                      'created_at': datetime.now(timezone.utc).isoformat()}
            row.payload = {**draft, 'report': report}
            await AdminActions(self.database)._record(session, draft_id, 'broadcast', 0, 'sim_broadcast',
                {'draft_id': draft_id, 'confirmation': confirmation}, {'targets': draft['targets']}, report)
            return report

    async def history(self):
        async with self.database.transaction() as session:
            rows = (await session.scalars(select(SystemState).where(SystemState.key.startswith(PREFIX))
                .order_by(SystemState.payload['created_at'].as_string().desc()).limit(30))).all()
            return [row.payload for row in rows]
