"""Bring the old bot's progress into a database that has lived on since its import (three-way sync).

The new bot's database was filled from a snapshot of the old bot's JSON (the *base*). Since then
both sides moved on: players kept playing the old bot (the *source*, a fresh JSON snapshot), and
the new bot gathered its own data (farm, Alchemy, rooms, quizzes in the sandbox). A fresh import
would erase the latter, so the sync applies only what changed in the source since the base:

* numbers that only grow or shrink by play (scores, answer counts, chat statistics) take the
  source's change on top of the database: ``db + (source - base)``;
* everything else (settings, questions, photos) is taken from the source only where the source
  changed it and the database did not; where both changed, the database keeps its value and the
  path is reported as a conflict for a person to decide;
* lists of ids and achievement codes are united; first/last timestamps take the min/max.

Scores go through the journal: every chat delta is one ``legacy_import`` event with the chat id
(the chat slice and the rating are built from the journal), the rest of a player's global change
is one residual event, and totals and the cache are rebuilt at the end. Keys carry the source
digest, so a repeated run of the same snapshot adds nothing.

Syncs form a chain: ``system_states['legacy_sync']`` remembers the digest of the last source, and
the next sync must use exactly that snapshot as its base. A dry run makes every change in a
transaction and rolls it back, so its report is exact.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert

from .json_importer import JsonSnapshot, import_score, parse_datetime, schedule_rows, string_list
from .models import Chat, ChatMember, PhotoQuizItem, QuestionCategory, ScoreEvent, SystemState, User
from .question_bank import PostgresQuestionBank, question_content_hash, validate_category_name
from .repositories import OperationalRepository
from .score_backfill import LINK_FROM_IDENTITY, REBUILD_CACHE, REBUILD_TOTALS
from .score_ledger import LEGACY_AT, ensure_account_for_user, quantize

STATE_KEY = 'legacy_sync'
MISSING = object()


class SyncRefused(RuntimeError):
    """The snapshots do not fit the database's sync chain; nothing was changed."""


class _DryRun(Exception):
    pass


def merge3(base, ours, theirs, path='', conflicts=None, *, add_numbers=False):
    """Three-way merge of JSON values; ``MISSING`` marks an absent key. Returns the merged value."""
    if theirs == base or theirs is ours:
        return ours
    if ours == base or ours == theirs:
        return theirs
    if all(isinstance(value, dict) for value in (ours, theirs)) and isinstance(base, (dict, type(MISSING))):
        base = base if isinstance(base, dict) else {}
        merged = {}
        for key in list(ours) + [key for key in theirs if key not in ours]:
            value = merge3(base.get(key, MISSING), ours.get(key, MISSING), theirs.get(key, MISSING),
                           f'{path}.{key}' if path else str(key), conflicts, add_numbers=add_numbers)
            if value is not MISSING:
                merged[key] = value
        return merged
    numbers = (int, float)
    if (add_numbers and all(isinstance(value, numbers) and not isinstance(value, bool)
                            for value in (base, ours, theirs))):
        return ours + (theirs - base)
    if conflicts is not None:
        conflicts.append(path or '(root)')
    return ours


def _union(first, second):
    return list(dict.fromkeys([*(first or []), *(second or [])]))


def _earliest(*values):
    present = [value for value in values if value is not None]
    return min(present) if present else None


def _latest(*values):
    present = [value for value in values if value is not None]
    return max(present) if present else None


def _member_ids(data):
    return string_list((data or {}).get('answered_polls'))


MEMBER_FIELDS = {
    'name', 'score', 'answered_polls', 'first_answer_time', 'last_answer_time', 'milestones_achieved',
    'consecutive_correct', 'max_consecutive_correct', 'streak_achievements_earned',
    'daily_answered_polls', 'last_daily_reset', 'correct_answers_count',
}


class LegacySync:
    def __init__(self, database, base: JsonSnapshot, source: JsonSnapshot):
        self.database, self.base, self.source = database, base, source

    async def run(self, *, apply: bool) -> dict[str, Any]:
        for name, snapshot in (('base', self.base), ('source', self.source)):
            if snapshot.errors:
                raise SyncRefused(f'{name} snapshot has errors: {snapshot.errors[:3]}')
        report: dict[str, Any] = {'base': self.base.digest, 'source': self.source.digest, 'applied': apply,
                                  'changes': {}, 'conflicts': {}, 'notes': []}
        try:
            async with self.database.transaction() as session:
                await session.execute(text('SELECT pg_advisory_xact_lock(724016823001)'))
                from .admin_actions import operation_fence
                await operation_fence(session, exclusive=True)
                await self._check_chain(session, report)
                if self.base.digest == self.source.digest:
                    report['notes'].append('source equals base: nothing to sync')
                else:
                    await self._sync(session, report)
                    await self._remember(session, report)
                if not apply:
                    raise _DryRun
        except _DryRun:
            pass
        return report

    async def _check_chain(self, session, report):
        row = await session.get(SystemState, STATE_KEY)
        state = row.payload if row else {}
        expected = state.get('last_source')
        if expected and expected != self.base.digest:
            raise SyncRefused(f'base must be the last synced source {expected[:12]}…, got {self.base.digest[:12]}…')
        for entry in state.get('history', []):
            if entry.get('source') == self.source.digest:
                raise SyncRefused('this source snapshot was already synced')
        report['chain'] = 'first sync' if not expected else 'continues ' + expected[:12]

    async def _remember(self, session, report):
        await session.execute(insert(SystemState).values(key=STATE_KEY, payload={}).on_conflict_do_nothing())
        row = await session.scalar(select(SystemState).where(SystemState.key == STATE_KEY).with_for_update())
        state = dict(row.payload or {})
        history = list(state.get('history', []))
        history.append({'base': self.base.digest, 'source': self.source.digest,
                        'at': datetime.now(timezone.utc).isoformat(), 'changes': report['changes']})
        row.payload = {'last_source': self.source.digest, 'history': history}

    def _count(self, report, name, amount=1):
        report['changes'][name] = report['changes'].get(name, 0) + amount

    async def _sync(self, session, report):
        repository = OperationalRepository(session)
        await session.execute(text(LINK_FROM_IDENTITY))
        score_deltas: dict[int, Decimal] = {}
        await self._chats(session, repository, report, score_deltas)
        await session.flush()
        await self._users(session, repository, report, score_deltas)
        await session.flush()
        await self._questions(session, report)
        await self._photos(session, report)
        self._system_states(report)
        await session.flush()  # autoflush is off: the rebuilds below must see every pending row
        await session.execute(text(REBUILD_TOTALS))
        await session.execute(text(REBUILD_CACHE))

    # --- players and scores -------------------------------------------------------------------

    async def _user(self, session, user_id, name, report):
        """The profile row (created when the old bot knows a player the database does not) and its account."""
        user = await session.scalar(select(User).where(User.id == user_id).with_for_update())
        if user is None:
            user = User(id=user_id, display_name=str(name or 'Unknown')[:255], global_score=Decimal(0),
                        total_answered=0, metadata_json={})
            session.add(user)
            await session.flush()
            self._count(report, 'users_created')
        await ensure_account_for_user(session, user)
        return user

    def _event(self, session, user, key, amount, chat_id=None):
        amount = quantize(amount)
        if not amount:
            return
        session.add(ScoreEvent(account_id=user.account_id, source='legacy_import',
                               key=f'legacy:sync:{self.source.digest[:16]}:{key}', amount=amount,
                               chat_id=chat_id, created_at=LEGACY_AT))

    async def _chats(self, session, repository, report, score_deltas):
        base_chats = {chat.chat_id: chat for chat in self.base.chats}
        for chat in self.source.chats:
            base = base_chats.get(chat.chat_id)
            row = await session.get(Chat, chat.chat_id, with_for_update=True)
            if row is None:
                await repository.upsert_chat({
                    'id': chat.chat_id,
                    'type': str(chat.settings.get('chat_type') or chat.metadata.get('type') or 'unknown'),
                    'title': chat.settings.get('title') or chat.metadata.get('title'),
                    'username': chat.metadata.get('username'), 'settings': chat.settings,
                    'statistics': chat.statistics, 'category_statistics': chat.category_statistics,
                    'is_active': chat.chat_id > 0})
                self._count(report, 'chats_created')
                settings_changed = True
            else:
                conflicts: list[str] = []
                settings = merge3(base.settings if base else {}, row.settings or {}, chat.settings, '', conflicts)
                statistics = merge3(base.statistics if base else {}, row.statistics or {}, chat.statistics,
                                    '', None, add_numbers=True)
                category_statistics = merge3(base.category_statistics if base else {}, row.category_statistics or {},
                                             chat.category_statistics, '', None, add_numbers=True)
                if conflicts:
                    report['conflicts'][f'chat {chat.chat_id} settings'] = conflicts
                settings_changed = settings != (row.settings or {})
                if settings_changed:
                    row.settings = settings
                    row.settings_revision = (row.settings_revision or 0) + 1
                    self._count(report, 'chat_settings_changed')
                if statistics != (row.statistics or {}) or category_statistics != (row.category_statistics or {}):
                    row.statistics, row.category_statistics = statistics, category_statistics
                    self._count(report, 'chat_statistics_changed')
                title = chat.settings.get('title') or chat.metadata.get('title')
                base_title = (base.settings.get('title') or base.metadata.get('title')) if base else None
                if title and title != base_title and title != row.title:
                    row.title = title
            if settings_changed:
                merged = (await session.get(Chat, chat.chat_id)).settings
                for values in schedule_rows(chat.chat_id, merged or {}):
                    await repository.upsert_schedule(values)
            for raw_user_id, data in chat.members.items():
                if str(raw_user_id).isdigit() and isinstance(data, dict):
                    old = (base.members.get(str(raw_user_id)) if base else None)
                    await self._member(session, repository, report, chat.chat_id, int(raw_user_id),
                                       old if isinstance(old, dict) else None, data, score_deltas)

    async def _member(self, session, repository, report, chat_id, user_id, base, source, score_deltas):
        user = await self._user(session, user_id, source.get('name'), report)
        row = await session.get(ChatMember, (chat_id, user_id), with_for_update=True)
        if row is None:
            base = None  # nothing of the base survives here: the source's whole value is the change
            row = ChatMember(chat_id=chat_id, user_id=user_id, score=Decimal(0), answered_count=0,
                             correct_answers_count=0, consecutive_correct=0, max_consecutive_correct=0,
                             answered_poll_ids=[], daily_answered_poll_ids=[], milestone_codes=[],
                             streak_achievement_codes=[], extra={})
            session.add(row)
            await session.flush()
            self._count(report, 'members_created')
        base = base or {}
        delta = import_score(source.get('score')) - import_score(base.get('score'))
        answered = len(_member_ids(source)) - len(_member_ids(base))
        correct = int(source.get('correct_answers_count') or 0) - int(base.get('correct_answers_count') or 0)
        before = (row.score, row.answered_count, list(row.answered_poll_ids or []), list(row.milestone_codes or []),
                  list(row.streak_achievement_codes or []))
        row.score = Decimal(row.score) + delta
        row.answered_count = max(0, (row.answered_count or 0) + answered)
        row.correct_answers_count = max(0, (row.correct_answers_count or 0) + correct)
        row.max_consecutive_correct = max(row.max_consecutive_correct or 0,
                                          int(source.get('max_consecutive_correct') or 0))
        if source.get('consecutive_correct') != base.get('consecutive_correct'):
            row.consecutive_correct = int(source.get('consecutive_correct') or 0)
        row.first_answer_at = _earliest(row.first_answer_at, parse_datetime(source.get('first_answer_time')))
        row.last_answer_at = _latest(row.last_answer_at, parse_datetime(source.get('last_answer_time')))
        source_reset = parse_datetime(source.get('last_daily_reset'))
        if source_reset and (row.last_daily_reset is None or source_reset > row.last_daily_reset):
            row.last_daily_reset = source_reset
            row.daily_answered_poll_ids = string_list(source.get('daily_answered_polls'))
        row.answered_poll_ids = _union(row.answered_poll_ids, _member_ids(source))
        row.milestone_codes = _union(row.milestone_codes, string_list(source.get('milestones_achieved')))
        row.streak_achievement_codes = _union(row.streak_achievement_codes,
                                              string_list(source.get('streak_achievements_earned')))
        extra = {key: value for key, value in source.items() if key not in MEMBER_FIELDS}
        base_extra = {key: value for key, value in base.items() if key not in MEMBER_FIELDS}
        row.extra = merge3(base_extra, dict(row.extra or {}), extra)
        codes = string_list(source.get('milestones_achieved')) + string_list(source.get('streak_achievements_earned'))
        await repository.add_achievement_codes(user_id, codes)
        if delta:
            self._event(session, user, f'chat:{chat_id}', delta, chat_id)
            score_deltas[user_id] = score_deltas.get(user_id, Decimal(0)) + delta
            self._count(report, 'member_scores_changed')
        if before != (row.score, row.answered_count, list(row.answered_poll_ids), list(row.milestone_codes),
                      list(row.streak_achievement_codes)):
            self._count(report, 'members_changed')

    async def _users(self, session, repository, report, score_deltas):
        for raw_user_id, data in self.source.global_users.items():
            if not str(raw_user_id).isdigit() or not isinstance(data, dict):
                continue
            user_id = int(raw_user_id)
            base = self.base.global_users.get(raw_user_id)
            base = base if isinstance(base, dict) else {}
            user = await self._user(session, user_id, data.get('name'), report)
            global_delta = import_score(data.get('global_score')) - import_score(base.get('global_score'))
            residual = global_delta - score_deltas.get(user_id, Decimal(0))
            self._event(session, user, 'residual', residual)
            answered = int(data.get('total_answered') or 0) - int(base.get('total_answered') or 0)
            if answered or global_delta:
                user.total_answered = max(0, (user.total_answered or 0) + answered)
                self._count(report, 'users_changed')
            user.first_answer_at = _earliest(user.first_answer_at, parse_datetime(data.get('first_answer_time')))
            user.last_answer_at = _latest(user.last_answer_at, parse_datetime(data.get('last_answer_time')))
            await repository.add_achievement_codes(user_id, string_list(data.get('milestones_achieved')))

    # --- content ------------------------------------------------------------------------------

    async def _questions(self, session, report):
        bank = PostgresQuestionBank(self.database)
        for name, questions in self.source.question_categories.items():
            validate_category_name(name)
            base = self.base.question_categories.get(name)
            source_hash = question_content_hash(questions)
            if base is not None and question_content_hash(base) == source_hash:
                continue
            row = await session.get(QuestionCategory, name, with_for_update=True)
            if row is None:
                if base is not None:
                    report['conflicts'].setdefault('questions', []).append(f'{name}: deleted here, changed there')
                    continue
                metadata = self.source.category_metadata.get(name, {})
                session.add(QuestionCategory(name=name, revision=0, content_hash=source_hash, questions=questions,
                                             metadata_json=metadata if isinstance(metadata, dict) else {},
                                             archived=False))
                self._count(report, 'question_categories_created')
            elif row.content_hash == source_hash:
                continue
            elif base is not None and row.content_hash == question_content_hash(base) and not row.archived:
                bank._history(session, row, 'legacy_sync')
                bank._replace(row, questions)
                self._count(report, 'question_categories_updated')
            else:
                report['conflicts'].setdefault('questions', []).append(f'{name}: changed on both sides')

    async def _photos(self, session, report):
        def shape(data):
            return (str(data.get('correct_answer')), data.get('hints') if isinstance(data.get('hints'), dict) else {},
                    bool(data.get('enabled', True)))

        for media_key, data in self.source.photo_items.items():
            if not isinstance(data, dict) or not data.get('correct_answer'):
                continue
            base = self.base.photo_items.get(media_key)
            if isinstance(base, dict) and shape(base) == shape(data):
                continue
            row = await session.get(PhotoQuizItem, media_key, with_for_update=True)
            values = dict(zip(('correct_answer', 'hints', 'enabled'), shape(data)))
            if row is None:
                if isinstance(base, dict):
                    report['conflicts'].setdefault('photos', []).append(f'{media_key}: deleted here, changed there')
                    continue
                session.add(PhotoQuizItem(media_key=media_key, metadata_json={
                    key: value for key, value in data.items() if key not in {'correct_answer', 'hints', 'enabled'}},
                    **values))
                self._count(report, 'photos_created')
                continue
            current = (row.correct_answer, row.hints or {}, row.enabled)
            if current == shape(data):
                continue
            if isinstance(base, dict) and current == shape(base):
                row.correct_answer, row.hints, row.enabled = values['correct_answer'], values['hints'], values['enabled']
                self._count(report, 'photos_updated')
            else:
                report['conflicts'].setdefault('photos', []).append(f'{media_key}: changed on both sides')

    def _system_states(self, report):
        changed = sorted(key for key in set(self.base.system_states) | set(self.source.system_states)
                         if self.base.system_states.get(key) != self.source.system_states.get(key))
        if changed:
            report['notes'].append('old bot system states changed (not synced, check by hand): ' + ', '.join(changed))
        if self.source.active_quizzes:
            report['notes'].append(f'{len(self.source.active_quizzes)} quizzes were running in the old bot '
                                   'at snapshot time (not synced)')
