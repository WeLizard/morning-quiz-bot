"""Three-way sync of the old bot's progress into a database that lived on since its import."""
import asyncio
import json
from decimal import Decimal

import pytest
from sqlalchemy import delete, func, select

from storage.json_importer import JsonSnapshot
from storage.legacy_sync import MISSING, LegacySync, SyncRefused, merge3
from storage.models import (
    AchievementGrant, Chat, ChatMember, PhotoQuizItem, QuestionCategory, QuestionCategoryRevision, ScoreEvent,
    SystemState, User,
)
from storage.question_bank import question_content_hash
from storage.repositories import OperationalRepository
from storage.score_ledger import COMMON_SOURCES, ensure_account_for_user
from tests.test_postgres_members import CHAT, OTHER_CHAT, USER, pg_env, scenario  # noqa: F401

CATEGORY = 'Синк-тест'
PHOTO = 'sync-test-photo.webp'
FRIEND, NEWCOMER = USER + 1, USER + 2


# --- merge rules ------------------------------------------------------------------------------

def test_merge_takes_the_side_that_changed_and_reports_real_conflicts():
    conflicts = []
    base = {'a': 1, 'b': {'x': 1, 'y': 1}, 'gone': 1, 'c': 'old'}
    ours = {'a': 1, 'b': {'x': 2, 'y': 1}, 'gone': 1, 'c': 'ours', 'mine': True}
    theirs = {'a': 5, 'b': {'x': 1, 'y': 3}, 'c': 'theirs', 'new': 'x'}
    merged = merge3(base, ours, theirs, '', conflicts)
    assert merged == {'a': 5, 'b': {'x': 2, 'y': 3}, 'c': 'ours', 'mine': True, 'new': 'x'}
    assert conflicts == ['c']


def test_counters_changed_on_both_sides_add_up():
    merged = merge3({'played': 10, 'name': 'a'}, {'played': 14, 'name': 'b'}, {'played': 13, 'name': 'c'},
                    '', None, add_numbers=True)
    assert merged == {'played': 17, 'name': 'b'}
    assert merge3(MISSING, MISSING, 3) == 3


# --- snapshots --------------------------------------------------------------------------------

def write_snapshot(root, *, scores, global_scores, settings, questions, answer, extra_chat=False):
    """A minimal old-bot data/ directory; ``scores`` maps (chat, user) to a score."""
    data = root / 'data'
    (data / 'global').mkdir(parents=True)
    (data / 'questions').mkdir()
    chats = {CHAT} | ({OTHER_CHAT} if extra_chat else set())
    (data / 'global' / 'chats_index.json').write_text(json.dumps({str(c): {'type': 'supergroup'} for c in chats}))
    (data / 'global' / 'users.json').write_text(json.dumps({
        str(uid): {'name': f'p{uid}', 'global_score': score, 'total_answered': int(score),
                   'milestones_achieved': ['first'] if score else []}
        for uid, score in global_scores.items()}))
    (data / 'global' / 'categories.json').write_text(json.dumps({CATEGORY: {}}))
    for chat in chats:
        folder = data / 'chats' / str(chat)
        folder.mkdir(parents=True)
        (folder / 'settings.json').write_text(json.dumps(settings if chat == CHAT else {}))
        (folder / 'stats.json').write_text(json.dumps({'quizzes': sum(s for (c, _), s in scores.items() if c == chat)}))
        (folder / 'categories_stats.json').write_text('{}')
        (folder / 'users.json').write_text(json.dumps({
            str(uid): {'name': f'p{uid}', 'score': score, 'answered_polls': [f'q{i}' for i in range(int(score))]}
            for (c, uid), score in scores.items() if c == chat}))
    (data / 'questions' / f'{CATEGORY}.json').write_text(json.dumps(questions, ensure_ascii=False))
    (data / 'photo_quiz_metadata.json').write_text(json.dumps({PHOTO: {'correct_answer': answer}}))
    return JsonSnapshot.scan(data)


QUESTION = {'question': 'Сколько?', 'options': ['1', '2'], 'correct_option_index': 0}
EDITED = {'question': 'Сколько всего?', 'options': ['1', '2'], 'correct_option_index': 0}


async def seed_from(db, snapshot):
    """What the import did, for this test's rows only: profiles, members, accounts with legacy events."""
    async with db.transaction() as session:
        repository = OperationalRepository(session)
        for chat in snapshot.chats:
            await repository.upsert_chat({'id': chat.chat_id, 'type': 'supergroup', 'settings': chat.settings,
                                          'statistics': chat.statistics, 'is_active': True})
        for uid, data in snapshot.global_users.items():
            await repository.upsert_user({'id': int(uid), 'display_name': data['name'],
                                          'global_score': Decimal(str(data['global_score']))})
        for chat in snapshot.chats:
            for uid, data in chat.members.items():
                await repository.upsert_member({'chat_id': chat.chat_id, 'user_id': int(uid),
                                                'score': Decimal(str(data['score'])),
                                                'answered_count': len(data['answered_polls']),
                                                'answered_poll_ids': data['answered_polls']})
        session.add(QuestionCategory(name=CATEGORY, revision=0, content_hash=question_content_hash([QUESTION]),
                                     questions=[QUESTION], metadata_json={}, archived=False))
        session.add(PhotoQuizItem(media_key=PHOTO, correct_answer='кот', hints={}, enabled=True, metadata_json={}))
        await session.flush()
        for uid in snapshot.global_users:
            user = await session.get(User, int(uid))
            await ensure_account_for_user(session, user)


async def sandbox_play(db, user_id, chat_id, points):
    """The new bot scores a quiz in a chat: member row and journal move together."""
    async with db.transaction() as session:
        user = await session.get(User, user_id)
        member = await session.get(ChatMember, (chat_id, user_id))
        member.score = Decimal(member.score) + points
        session.add(ScoreEvent(account_id=user.account_id, source='classic', key=f'test:{chat_id}:{points}',
                               amount=points, chat_id=chat_id))
        user.global_score = Decimal(user.global_score) + points


async def consistent(db, user_ids):
    """The checks of storage/score_reconcile.py, limited to this test's players."""
    async with db.transaction() as session:
        for uid in user_ids:
            user = await session.get(User, uid)
            common = await session.scalar(select(func.coalesce(func.sum(ScoreEvent.amount), 0)).where(
                ScoreEvent.account_id == user.account_id, ScoreEvent.source.in_(COMMON_SOURCES)))
            assert Decimal(user.global_score) == Decimal(common), uid
            for member in (await session.scalars(select(ChatMember).where(ChatMember.user_id == uid))).all():
                journal = await session.scalar(select(func.coalesce(func.sum(ScoreEvent.amount), 0)).where(
                    ScoreEvent.account_id == user.account_id, ScoreEvent.chat_id == member.chat_id))
                assert Decimal(member.score) == Decimal(journal), (uid, member.chat_id)


async def cleanup(db):
    async with db.transaction() as session:
        await session.execute(delete(SystemState).where(SystemState.key == 'legacy_sync'))
        await session.execute(delete(QuestionCategoryRevision).where(QuestionCategoryRevision.category_name == CATEGORY))
        await session.execute(delete(QuestionCategory).where(QuestionCategory.name == CATEGORY))
        await session.execute(delete(PhotoQuizItem).where(PhotoQuizItem.media_key == PHOTO))
        await session.execute(delete(AchievementGrant).where(AchievementGrant.user_id.in_([USER, FRIEND, NEWCOMER])))


def test_sync_adds_the_old_bots_progress_and_keeps_the_new_bots(pg_env, tmp_path):
    base = write_snapshot(tmp_path / 'base', scores={(CHAT, USER): 10, (CHAT, FRIEND): 5},
                          global_scores={USER: 10, FRIEND: 5},
                          settings={'daily_quiz': {'enabled': False, 'times_msk': []}, 'language': 'ru'},
                          questions=[QUESTION], answer='кот')
    source = write_snapshot(tmp_path / 'source',
                            scores={(CHAT, USER): 13, (CHAT, FRIEND): 5, (OTHER_CHAT, NEWCOMER): 4},
                            global_scores={USER: 15, FRIEND: 5, NEWCOMER: 4},
                            settings={'daily_quiz': {'enabled': True, 'times_msk': [{'hour': 8, 'minute': 0}]},
                                      'language': 'ru'},
                            questions=[QUESTION, EDITED], answer='кошка', extra_chat=True)

    async def run():
        async with scenario(pg_env) as db:
            await cleanup(db)
            try:
                await seed_from(db, base)
                await sandbox_play(db, FRIEND, CHAT, Decimal('2.5'))
                async with db.transaction() as session:  # the sandbox also changed a setting of its own
                    chat = await session.get(Chat, CHAT)
                    chat.settings = dict(chat.settings, language='en')

                dry = await LegacySync(db, base, source).run(apply=False)
                assert dry['changes']['member_scores_changed'] == 2 and not dry['conflicts']
                async with db.transaction() as session:
                    assert Decimal((await session.get(ChatMember, (CHAT, USER))).score) == 10  # rolled back
                    assert await session.get(SystemState, 'legacy_sync') is None

                report = await LegacySync(db, base, source).run(apply=True)
                assert report['changes']['users_created'] == 1 and report['changes']['chats_created'] == 1
                async with db.transaction() as session:
                    assert Decimal((await session.get(ChatMember, (CHAT, USER))).score) == 13
                    assert Decimal((await session.get(ChatMember, (CHAT, FRIEND))).score) == Decimal('7.5')
                    assert Decimal((await session.get(ChatMember, (OTHER_CHAT, NEWCOMER))).score) == 4
                    assert (await session.get(ChatMember, (CHAT, USER))).answered_count == 13
                    assert Decimal((await session.get(User, USER)).global_score) == 15  # 13 in chat + 2 elsewhere
                    assert Decimal((await session.get(User, FRIEND)).global_score) == Decimal('7.5')
                    settings = (await session.get(Chat, CHAT)).settings
                    assert settings['daily_quiz']['enabled'] is True and settings['language'] == 'en'
                    row = await session.get(QuestionCategory, CATEGORY)
                    assert row.questions == [QUESTION, EDITED] and row.revision == 1
                    assert (await session.get(PhotoQuizItem, PHOTO)).correct_answer == 'кошка'
                await consistent(db, [USER, FRIEND, NEWCOMER])

                with pytest.raises(SyncRefused):  # the same snapshot twice
                    await LegacySync(db, source, source).run(apply=True)
                with pytest.raises(SyncRefused):  # a base that is not the last synced source
                    await LegacySync(db, base, source).run(apply=True)
            finally:
                await cleanup(db)
    asyncio.run(run())


def test_both_sides_changing_a_question_category_is_a_conflict(pg_env, tmp_path):
    common = dict(scores={(CHAT, USER): 1}, global_scores={USER: 1}, settings={}, answer='кот')
    base = write_snapshot(tmp_path / 'base', questions=[QUESTION], **common)
    source = write_snapshot(tmp_path / 'source', questions=[EDITED], **dict(common, answer='пёс'))

    async def run():
        async with scenario(pg_env) as db:
            await cleanup(db)
            try:
                await seed_from(db, base)
                async with db.transaction() as session:
                    row = await session.get(QuestionCategory, CATEGORY)
                    row.questions = [QUESTION, QUESTION]
                    row.content_hash = question_content_hash(row.questions)
                    photo = await session.get(PhotoQuizItem, PHOTO)
                    photo.correct_answer = 'кошка'
                report = await LegacySync(db, base, source).run(apply=True)
                assert report['conflicts'] == {'questions': [f'{CATEGORY}: changed on both sides'],
                                               'photos': [f'{PHOTO}: changed on both sides']}
                async with db.transaction() as session:
                    assert (await session.get(QuestionCategory, CATEGORY)).questions == [QUESTION, QUESTION]
                    assert (await session.get(PhotoQuizItem, PHOTO)).correct_answer == 'кошка'
            finally:
                await cleanup(db)
    asyncio.run(run())
