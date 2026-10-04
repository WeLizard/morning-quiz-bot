"""Usage counters committed with classic session completion, never snapshots."""
from copy import deepcopy
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from .models import Chat, SystemState


class CategoryStatistics:
    def __init__(self, database):
        self.database = database

    async def snapshot_in(self, session, chat_id):
        from .models import Game, QuizSession
        from .admin_actions import digest
        row = await session.get(SystemState, 'category_usage_stats')
        chat = await session.get(Chat, chat_id)
        if chat is None:
            raise LookupError('Чат не найден')
        global_data = deepcopy(row.payload if row else {})
        values = {name: value for name, value in global_data.items() if str(chat_id) in value.get('chat_usage', {})}
        legacy_active = list((await session.scalars(select(QuizSession.id).where(
            QuizSession.chat_id == chat_id,
            QuizSession.status == 'active',
        ))).all())
        platform_active = list((await session.scalars(select(Game.id).where(
            Game.chat_id == chat_id,
            Game.is_current.is_(True),
            Game.status.not_in(('finished', 'stopped', 'interrupted')),
        ))).all())
        active = [*legacy_active, *platform_active]
        result = {'chat_id': str(chat_id), 'global_entries': values, 'local': deepcopy(chat.category_statistics), 'active_sessions': active}
        return {**result, 'version': digest(result)}

    async def preview(self, chat_id):
        from .admin_actions import operation_fence
        async with self.database.transaction() as session:
            await operation_fence(session, exclusive=True)
            return await self.snapshot_in(session, chat_id)

    async def reset_chat(self, chat_id, *, expected_version, confirmation, action_id):
        from .admin_actions import AdminActions, AdminConflict, operation_fence
        if confirmation != str(chat_id):
            raise ValueError('Введите ID чата для подтверждения')
        actions = AdminActions(self.database)
        request = dict(expected_version=expected_version, confirmation=confirmation)
        async with self.database.transaction() as session:
            await operation_fence(session, exclusive=True)
            repeated = await actions._retry(session, action_id, 'categories', chat_id, 'category_reset', request)
            if repeated:
                return repeated
            before = await self.snapshot_in(session, chat_id)
            if before['version'] != expected_version or before['active_sessions']:
                raise AdminConflict('Статистика изменилась или в чате идёт игра. Обновите предварительный просмотр.')
            row = await session.scalar(select(SystemState).where(SystemState.key == 'category_usage_stats').with_for_update())
            if row:
                payload = deepcopy(row.payload)
                for name, value in payload.items():
                    usage = value.get('chat_usage', {})
                    removed = int(usage.pop(str(chat_id), 0))
                    if removed:
                        value['global_usage'] = max(0, int(value.get('global_usage', value.get('total_usage', 0))) - removed)
                    value['chats_used_in'] = [cid for cid in value.get('chats_used_in', []) if str(cid) != str(chat_id)]
                row.payload = payload
            chat = await session.get(Chat, chat_id)
            chat.category_statistics = {}
            await session.flush()
            after = await self.snapshot_in(session, chat_id)
            return await actions._record(session, action_id, 'categories', chat_id, 'category_reset', request, before, after)


async def record_completed_in(session, state):
    # Lock order: quiz (caller), chat, global counters. Completion's revision
    # check is also the idempotency guard for these increments.
    chat = await session.scalar(select(Chat).where(Chat.id == state['chat_id']).with_for_update())
    await session.execute(insert(SystemState).values(key='category_usage_stats', payload={})
                          .on_conflict_do_nothing(index_elements=[SystemState.key]))
    row = await session.scalar(select(SystemState).where(SystemState.key == 'category_usage_stats').with_for_update())
    counters = deepcopy(row.payload or {})
    local = deepcopy(chat.category_statistics or {})
    if state.get('mode') == 'classic' and isinstance(state.get('rounds'), list):
        categories = {item.get('category') for item in state['rounds'] if isinstance(item, dict)}
    else:
        categories = {q.get('current_category_name_for_quiz') or q.get('original_category')
                      for q in state.get('questions', []) if isinstance(q, dict)}
    now = datetime.now(timezone.utc).timestamp()
    for category in sorted(c for c in categories if c):
        value = counters.setdefault(category, {})
        usage = value.setdefault('chat_usage', {})
        chat_key = str(chat.id)
        usage[chat_key] = int(usage.get(chat_key, 0)) + 1
        value['global_usage'] = int(value.get('global_usage', value.get('total_usage', 0))) + 1
        value['last_used'] = now
        value['chats_used_in'] = sorted(set(value.get('chats_used_in', [])) | {chat_key})
        local[category] = {**local.get(category, {}), 'chat_usage': usage[chat_key], 'last_used': now}
    row.payload = counters
    chat.category_statistics = local
    stats = deepcopy(chat.statistics or {})
    stats['total_quizzes'] = int(stats.get('total_quizzes', 0)) + 1
    chat.statistics = stats
