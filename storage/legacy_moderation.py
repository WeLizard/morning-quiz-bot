"""Strict, non-destructive promotion of an imported legacy blacklist."""
from sqlalchemy.dialects.postgresql import insert

from .models import Chat, User


def legacy_block_records(payload):
    if not isinstance(payload, dict):
        raise ValueError('Legacy blacklist must be an object; nothing was changed')
    records = []
    for scope, model in (('users', User), ('chats', Chat)):
        entries = payload.get(scope, {})
        if not isinstance(entries, dict):
            raise ValueError('Legacy blacklist section must be an object')
        for key, entry in entries.items():
            try:
                target_id = int(key)
                if not -(2**63) <= target_id < 2**63 or target_id == 0 or (scope == 'users' and target_id < 0):
                    raise ValueError()
            except (TypeError, ValueError) as exc:
                raise ValueError('Invalid legacy blacklist ID; nothing was changed') from exc
            if not isinstance(entry, dict):
                raise ValueError('Invalid legacy blacklist entry')
            reason = str(entry.get('reason') or 'Перенесено из прежнего списка блокировок')[:500]
            if '\x00' in reason:
                raise ValueError('Invalid legacy blacklist reason')
            values = dict(id=target_id, bot_blocked=True, moderation_revision=1, moderation_reason=reason)
            if scope == 'users':
                values['display_name'] = str(entry.get('name') or f'User {target_id}')[:255]
            else:
                values['title'] = str(entry.get('title') or entry.get('name') or f'Чат {target_id}')[:255]
            # Existing names/scores/settings remain untouched. Never undo a new admin decision.
            records.append((scope, model, values))
    return records


def legacy_block_statements(payload):
    return [
        insert(model).values(**values).on_conflict_do_update(
            index_elements=[model.id],
            set_={key: values[key] for key in ('bot_blocked', 'moderation_revision', 'moderation_reason')},
            where=model.moderation_revision == 0,
        )
        for _, model, values in legacy_block_records(payload)
    ]
