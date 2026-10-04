"""Content-level verification for the one-shot JSON -> PostgreSQL migration."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select

from .models import (
    AchievementGrant,
    Chat,
    ChatMember,
    DailySchedule,
    MessageCleanupItem,
    PhotoQuizItem,
    QuestionCategory,
    QuizSession,
    SystemState,
    User,
)


GROUPS = {
    'chats': (Chat, ('id',), {
        'id': None, 'type': 'unknown', 'title': None, 'username': None,
        'settings': {}, 'settings_revision': 0, 'statistics': {},
        'category_statistics': {}, 'is_active': True, 'archived': False,
        'bot_blocked': False, 'moderation_revision': 0, 'moderation_reason': '',
    }),
    'users': (User, ('id',), {
        'id': None, 'display_name': 'Unknown', 'global_score': Decimal('0.000'),
        'total_answered': 0, 'first_answer_at': None, 'last_answer_at': None,
        'metadata_json': {}, 'archived': False, 'bot_blocked': False,
        'moderation_revision': 0, 'moderation_reason': '',
    }),
    'chat_members': (ChatMember, ('chat_id', 'user_id'), {
        'chat_id': None, 'user_id': None, 'score': Decimal('0.000'),
        'answered_count': 0, 'correct_answers_count': 0,
        'consecutive_correct': 0, 'max_consecutive_correct': 0,
        'first_answer_at': None, 'last_answer_at': None, 'last_daily_reset': None,
        'answered_poll_ids': [], 'daily_answered_poll_ids': [],
        'milestone_codes': [], 'streak_achievement_codes': [], 'extra': {},
    }),
    'achievement_grants': (AchievementGrant, ('user_id', 'chat_id', 'code'), {
        'user_id': None, 'chat_id': 0, 'code': None, 'metadata_json': {},
    }),
    'daily_schedules': (DailySchedule, ('chat_id', 'kind'), {
        'chat_id': None, 'kind': None, 'enabled': False,
        'timezone': 'Europe/Moscow', 'run_times': [], 'config': {},
    }),
    'active_quizzes': (QuizSession, ('id',), {
        'id': None, 'chat_id': None, 'kind': 'classic', 'status': 'active',
        'state': {}, 'started_at': None, 'ends_at': None,
    }),
    'photo_quiz_items': (PhotoQuizItem, ('media_key',), {
        'media_key': None, 'correct_answer': None, 'hints': {},
        'enabled': True, 'metadata_json': {},
    }),
    'question_categories': (QuestionCategory, ('name',), {
        'name': None, 'revision': 0, 'content_hash': None, 'questions': [],
        'metadata_json': {}, 'archived': False,
    }),
    'system_states': (SystemState, ('key',), {'key': None, 'payload': {}}),
    'message_cleanup_items': (MessageCleanupItem, ('chat_id', 'message_id'), {
        'chat_id': None, 'message_id': None, 'delete_after': None, 'payload': {},
    }),
}


def _canonical(value):
    if isinstance(value, Decimal):
        return format(value.quantize(Decimal('0.001')), 'f')
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, dict):
        return {str(key): _canonical(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    return value


def _digest(rows):
    payload = json.dumps(_canonical(rows), ensure_ascii=False, sort_keys=True,
                         separators=(',', ':'))
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


class MigrationVerification:
    """Mirror intended normalized writes and compare them with committed ORM values."""

    def __init__(self):
        self.expected = {name: {} for name in GROUPS}

    @staticmethod
    def _key(group, values):
        return tuple(values[field] for field in GROUPS[group][1])

    def record(self, group, values, *, ensure=False):
        _, _, defaults = GROUPS[group]
        key = self._key(group, values)
        current = self.expected[group].get(key)
        if current is not None and ensure:
            return
        if current is None:
            current = dict(defaults)
            self.expected[group][key] = current
        current.update({field: values[field] for field in defaults if field in values})

    def record_legacy_block(self, scope, values):
        group = 'users' if scope == 'users' else 'chats'
        key = self._key(group, values)
        if key not in self.expected[group]:
            self.record(group, values, ensure=True)
        current = self.expected[group][key]
        for field in ('bot_blocked', 'moderation_revision', 'moderation_reason'):
            current[field] = values[field]

    async def compare(self, session):
        result = {}
        for group, (model, key_fields, defaults) in GROUPS.items():
            actual = {}
            for row in (await session.scalars(select(model))).all():
                values = {field: getattr(row, field) for field in defaults}
                actual[tuple(values[field] for field in key_fields)] = values
            expected_rows = [self.expected[group][key] for key in sorted(self.expected[group], key=str)]
            actual_rows = [actual[key] for key in sorted(actual, key=str)]
            source = _digest(expected_rows)
            database = _digest(actual_rows)
            result[group] = {
                'source': source,
                'database': database,
                'rows': len(actual_rows),
                'matched': source == database and len(expected_rows) == len(actual_rows),
            }
        return result
