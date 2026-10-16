"""Account score journal: idempotency, backfill reconciliation, writers, merge, recompute.

PG cases need TEST_DATABASE_URL (morning_quiz_test) and run in a private schema.
"""
import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text, update

from application.account_merge import AccountMergeService
from storage.admin_actions import AdminActions
from storage.database import normalize_database_url
from storage.members import MemberService
from storage.models import (Account, AlchemyProgress, Chat, ChatMember, ClassicAccountAnswer, Game,
                            PollAnswer, Room, ScoreEvent, ScoreTotal, User)
from storage.repositories import OperationalRepository
from storage.score_backfill import backfill
from storage.score_ledger import COMMON_SOURCES, AccountMerged, RewardLedger, ensure_account_for_user
from qw_farm.integration import register_models
from tests.local_database import isolated_database

D = Decimal
_uid = iter(range(981070000001, 981070009999))


@pytest.fixture
def pg_url(monkeypatch):
    raw = os.getenv('TEST_DATABASE_URL')
    if not raw:
        pytest.skip('TEST_DATABASE_URL is not configured')
    monkeypatch.setenv('QW_FARM_ENABLED', '1')
    return normalize_database_url(raw)


@asynccontextmanager
async def environment(url):
    register_models()  # the merge locks farm tables, which live in the shared metadata
    async with isolated_database(url) as (db, _):
        yield db


def run(coro):
    return asyncio.run(coro)


async def make_user(session, *, score=0, name='Игрок', account=True, **flags):
    uid = next(_uid)
    account_id = None
    if account:
        acc = Account(id=uuid4(), display_name=name)
        session.add(acc)
        await session.flush()
        account_id = acc.id
    session.add(User(id=uid, account_id=account_id, display_name=name, global_score=D(score), **flags))
    await session.flush()
    return uid, account_id


async def totals(session, account_id):
    return {r.source: r.total for r in (await session.scalars(
        select(ScoreTotal).where(ScoreTotal.account_id == account_id))).all()}


async def assert_consistent(session):
    """Totals equal the journal; users.global_score equals its common part."""
    events = {(a, s): (t, c) for a, s, t, c in (await session.execute(
        select(ScoreEvent.account_id, ScoreEvent.source, func.sum(ScoreEvent.amount), func.count())
        .group_by(ScoreEvent.account_id, ScoreEvent.source))).all()}
    stored = {(r.account_id, r.source): (r.total, r.events) for r in (await session.scalars(select(ScoreTotal))).all()}
    assert stored == events
    for user in (await session.scalars(select(User).where(User.account_id.is_not(None)))).all():
        common = sum((t for (a, s), (t, _) in events.items() if a == user.account_id and s in COMMON_SOURCES), D(0))
        assert user.global_score == common, (user.id, user.global_score, common)


# ----------------------------------------------------------------- ledger core
def test_award_is_idempotent_per_account_source_key(pg_url):
    async def case():
        async with environment(pg_url) as db:
            async with db.transaction() as session:
                uid, acc = await make_user(session)
                assert await RewardLedger.award(session, account_id=acc, source='classic', amount=D('2.5'), key='poll:1')
                assert not await RewardLedger.award(session, account_id=acc, source='classic', amount=D('2.5'), key='poll:1')
                # Same key in another source or for another account is a different event.
                assert await RewardLedger.award(session, account_id=acc, source='photo', amount=1, key='poll:1')
                assert await RewardLedger.award(session, account_id=acc, source='classic', amount=0, key='poll:zero')
            async with db.transaction() as session:
                assert await totals(session, acc) == {'classic': D('2.5'), 'photo': D('1')}
                assert (await session.get(User, uid)).global_score == D('3.5')
                assert await session.scalar(select(func.count()).select_from(ScoreEvent)) == 2
                await assert_consistent(session)
    run(case())


def test_alchemy_has_own_slice_and_does_not_touch_the_common_cache(pg_url):
    async def case():
        async with environment(pg_url) as db:
            async with db.transaction() as session:
                uid, acc = await make_user(session)
                await RewardLedger.award(session, account_id=acc, source='classic', amount=3, key='poll:a')
                await RewardLedger.award(session, account_id=acc, source='alchemy', amount=7, key='craft:abcdefgh')
            async with db.transaction() as session:
                assert (await session.get(User, uid)).global_score == D(3)
                assert await totals(session, acc) == {'classic': D(3), 'alchemy': D(7)}
                await assert_consistent(session)
    run(case())


def test_concurrent_duplicates_pay_once(pg_url):
    async def case():
        async with environment(pg_url) as db:
            async with db.transaction() as session:
                uid, acc = await make_user(session)

            async def once():
                async with db.transaction() as session:
                    return await RewardLedger.award(session, account_id=acc, source='classic', amount=4, key='room:g:r')
            results = await asyncio.gather(*[once() for _ in range(6)])
            assert sorted(results) == [False] * 5 + [True]
            async with db.transaction() as session:
                assert (await session.get(User, uid)).global_score == D(4)
                await assert_consistent(session)
    run(case())


def test_award_rejects_unknown_source_and_merged_account(pg_url):
    async def case():
        async with environment(pg_url) as db:
            async with db.transaction() as session:
                uid, acc = await make_user(session)
                _, main = await make_user(session)
                with pytest.raises(ValueError):
                    await RewardLedger.award(session, account_id=acc, source='farm', amount=1, key='k')
                (await session.get(Account, acc)).merged_into_id = main
                await session.flush()
                with pytest.raises(AccountMerged):
                    await RewardLedger.award(session, account_id=acc, source='classic', amount=1, key='k')
    run(case())


def test_recompute_rebuilds_totals_and_cache_from_the_journal(pg_url):
    async def case():
        async with environment(pg_url) as db:
            async with db.transaction() as session:
                uid, acc = await make_user(session)
                await RewardLedger.award(session, account_id=acc, source='classic', amount=3, key='poll:a')
                await RewardLedger.award(session, account_id=acc, source='alchemy', amount=7, key='craft:abcdefgh')
                await session.execute(update(User).where(User.id == uid).values(global_score=D(999)))
                await session.execute(update(ScoreTotal).where(ScoreTotal.account_id == acc).values(total=D(1)))
            async with db.transaction() as session:
                await RewardLedger.recompute(session, acc)
            async with db.transaction() as session:
                await assert_consistent(session)
                assert (await session.get(User, uid)).global_score == D(3)
    run(case())


# ---------------------------------------------------------------- chat writers
def test_chat_answer_writes_one_event_and_repeated_poll_does_not_pay(pg_url):
    async def case():
        async with environment(pg_url) as db:
            chat = -981070000001
            async with db.transaction() as session:
                repo = OperationalRepository(session)
                await repo.ensure_chat({'id': chat, 'type': 'group'})
                uid, acc = await make_user(session, account=False)
                await repo.ensure_member({'chat_id': chat, 'user_id': uid})
            for _ in range(2):
                async with db.transaction() as session:
                    await OperationalRepository(session).record_answer_and_add_score(
                        poll_id='p1', user_id=uid, chat_id=chat, points_delta=D('1.5'),
                        selected_option=0, is_correct=True, payload={'quiz_type': 'classic'})
            async with db.transaction() as session:
                user = await session.get(User, uid)
                assert user.account_id is not None, 'technical account is provisioned on first points'
                events = (await session.scalars(select(ScoreEvent))).all()
                assert [(e.source, e.key, e.amount, e.chat_id) for e in events] == [('classic', 'poll:p1', D('1.5'), chat)]
                assert user.global_score == D('1.5') and user.total_answered == 1
                assert (await session.get(ChatMember, (chat, uid))).score == D('1.5')
                await assert_consistent(session)
    run(case())


def test_admin_set_score_and_reset_go_through_the_journal(pg_url):
    async def case():
        async with environment(pg_url) as db:
            chat = -981070000002
            async with db.transaction() as session:
                repo = OperationalRepository(session)
                await repo.ensure_chat({'id': chat, 'type': 'group'})
                uid, acc = await make_user(session)
                await repo.ensure_member({'chat_id': chat, 'user_id': uid})
                await RewardLedger.award(session, account_id=acc, source='classic', amount=5, key='poll:p', chat_id=chat)
                await session.execute(update(ChatMember).where(ChatMember.chat_id == chat).values(score=D(5)))
                await RewardLedger.award(session, account_id=acc, source='classic', amount=2, key='room:g:r')
                await RewardLedger.award(session, account_id=acc, source='alchemy', amount=9, key='craft:abcdefgh')
            old = await MemberService(db).set_score(chat, uid, D(8), D(5))
            assert old == D(5)
            async with db.transaction() as session:
                assert (await session.get(User, uid)).global_score == D(10)  # 8 in the chat + 2 room points
                await assert_consistent(session)
            actions = AdminActions(db)
            preview = await actions.preview_reset('users', uid)
            await actions.reset('users', uid, expected_version=preview['version'], confirmation=str(uid),
                                action_id='reset-1')
            async with db.transaction() as session:
                user = await session.get(User, uid)
                assert user.global_score == D(0)
                assert (await totals(session, acc)).get('alchemy') == D(9), 'reset must not erase Alchemy'
                assert sum((t for s, t in (await totals(session, acc)).items() if s in COMMON_SOURCES), D(0)) == D(0)
                chat_slice = await session.scalar(select(func.sum(ScoreEvent.amount)).where(ScoreEvent.chat_id == chat))
                assert chat_slice == (await session.get(ChatMember, (chat, uid))).score == D(0)
                await assert_consistent(session)
    run(case())


def test_recompute_user_totals_keeps_alchemy_and_room_points(pg_url):
    async def case():
        async with environment(pg_url) as db:
            async with db.transaction() as session:
                uid, acc = await make_user(session)
                await RewardLedger.award(session, account_id=acc, source='classic', amount=2, key='room:g:r')
                await RewardLedger.award(session, account_id=acc, source='alchemy', amount=9, key='craft:abcdefgh')
                await OperationalRepository(session).recompute_user_totals(uid)
            async with db.transaction() as session:
                assert (await session.get(User, uid)).global_score == D(2)
                assert (await totals(session, acc))['alchemy'] == D(9)
    run(case())


# -------------------------------------------------------------------- backfill
async def seed_legacy(session):
    """Telegram player with chat scores, an explained and an unexplained rest, Alchemy credit and room points."""
    chat_a, chat_b = -981070000011, -981070000012
    repo = OperationalRepository(session)
    for chat in (chat_a, chat_b):
        await repo.ensure_chat({'id': chat, 'type': 'group'})
    uid, acc = await make_user(session, score=D('30.5'), account=False)   # 30.5 = 10 + 5 + 3 alchemy + 12.5 rest
    await repo.ensure_member({'chat_id': chat_a, 'user_id': uid})
    await repo.ensure_member({'chat_id': chat_b, 'user_id': uid})
    await session.execute(update(ChatMember).where(ChatMember.chat_id == chat_a, ChatMember.user_id == uid).values(score=D(10)))
    await session.execute(update(ChatMember).where(ChatMember.chat_id == chat_b, ChatMember.user_id == uid).values(score=D(5)))
    owner = Account(id=uuid4(), display_name='Alch')
    session.add(owner)
    await session.flush()
    await session.execute(update(User).where(User.id == uid).values(account_id=owner.id))
    session.add(AlchemyProgress(account_id=owner.id, user_id=uid, points_total=D(3)))
    # A blocked player stays; a guest-only Alchemy player has an own slice.
    blocked, _ = await make_user(session, score=D(4), account=False, bot_blocked=True, name='Blocked')
    guest = Account(id=uuid4(), display_name='Гость')
    session.add(guest)
    await session.flush()
    session.add(AlchemyProgress(account_id=guest.id, user_id=None, points_total=D(2)))
    await session.flush()
    return uid, owner.id, blocked, guest.id, (chat_a, chat_b)


def test_backfill_reconciles_every_balance_and_is_idempotent(pg_url):
    async def case():
        async with environment(pg_url) as db:
            async with db.transaction() as session:
                uid, acc, blocked, guest, chats = await seed_legacy(session)
                # Room points never counted before: common now, and the cache moves with them.
                user_row = await session.get(User, uid)
                room = Room(id='r1', kind='classic', title='t')
                session.add(room)
                await session.flush()
                session.add(Game(id='g1', room_id='r1', mode='classic', status='finished', phase='finished', state={}, is_current=False))
                await session.flush()
                session.add(ClassicAccountAnswer(game_id='g1', round_id='q1', account_id=acc, selected_option=0,
                                                 is_correct=True, points_delta=D('2.5')))
            for _ in range(2):  # twice: idempotent
                async with db.transaction() as session:
                    await backfill(session)
            async with db.transaction() as session:
                user = await session.get(User, uid)
                # 30.5 total - 3 Alchemy credit + 2.5 room = 30.0 common
                assert user.global_score == D('30.0')
                assert (await totals(session, acc)) == {'legacy_import': D('27.5'), 'alchemy': D(3), 'classic': D('2.5')}
                chat_a = await session.scalar(select(func.sum(ScoreEvent.amount)).where(ScoreEvent.chat_id == chats[0]))
                assert chat_a == D(10)
                legacy_at = {e.created_at.year for e in (await session.scalars(
                    select(ScoreEvent).where(ScoreEvent.source.in_(['legacy_import', 'alchemy'])))).all()}
                assert legacy_at == {2000}, 'legacy rows must stay outside week/month windows'
                room_event = await session.scalar(select(ScoreEvent).where(ScoreEvent.key == 'room:g1:q1'))
                assert (room_event.room_id, room_event.game_id) == ('r1', 'g1')
                # Blocked player is provisioned (flags copied) and keeps the score.
                blocked_user = await session.get(User, blocked)
                assert blocked_user.account_id is not None and blocked_user.global_score == D(4)
                assert (await session.get(Account, blocked_user.account_id)).bot_blocked
                assert (await totals(session, guest)) == {'alchemy': D(2)}
                await assert_consistent(session)
    run(case())


def test_backfill_leaves_profiles_with_foreign_telegram_identity_for_review(pg_url):
    async def case():
        async with environment(pg_url) as db:
            async with db.transaction() as session:
                from storage.models import AccountIdentity
                uid, _ = await make_user(session, score=D(5), account=False)
                other = Account(id=uuid4(), display_name='Other')
                session.add(other)
                await session.flush()
                session.add(AccountIdentity(account_id=other.id, provider='telegram', provider_subject=str(uid),
                                            verified_at=datetime.now(timezone.utc)))
            async with db.transaction() as session:
                await backfill(session)
            async with db.transaction() as session:
                assert (await session.get(User, uid)).account_id is None
                assert await session.scalar(select(func.count()).select_from(ScoreEvent)) == 0
    run(case())


# ----------------------------------------------------------------------- merge
def test_merge_moves_events_and_rebuilds_totals_and_alchemy_points(pg_url):
    async def case():
        async with environment(pg_url) as db:
            async with db.transaction() as session:
                uid, tg = await make_user(session, score=D(0))
                guest = Account(id=uuid4(), display_name='Гость')
                session.add(guest)
                await session.flush()
                session.add(AlchemyProgress(account_id=guest.id, user_id=None, points_total=D(4)))
                session.add(AlchemyProgress(account_id=tg, user_id=uid, points_total=D(6)))
                await session.flush()
                for acc in (tg, guest.id):
                    await RewardLedger.award(session, account_id=acc, source='alchemy', amount=D(6) if acc == tg else D(4),
                                             key='legacy:alchemy')
                await RewardLedger.award(session, account_id=tg, source='classic', amount=2, key='poll:1')
                await RewardLedger.award(session, account_id=tg, source='classic', amount=1, key='room:g:r')
                await RewardLedger.award(session, account_id=guest.id, source='classic', amount=1, key='room:g:r')  # same round, same human
                await RewardLedger.award(session, account_id=guest.id, source='classic', amount=3, key='room:g:r2')
                gid = guest.id
            async with db.transaction() as session:
                main = await session.get(Account, tg)
                secondary = await session.get(Account, gid)
                summary = await AccountMergeService().merge_in(session, main=main, secondary=secondary, via='test')
            async with db.transaction() as session:
                t = await totals(session, tg)
                assert t == {'classic': D(6), 'alchemy': D(10)}  # 2 + 1 + 3 ; imported 6 + 4
                assert (await session.get(User, uid)).global_score == D(6)
                assert (await session.get(AlchemyProgress, tg)).points_total == D(10)
                left = (await session.scalars(select(ScoreEvent).where(ScoreEvent.account_id == gid))).all()
                assert [e.key for e in left] == ['room:g:r'], 'the round answered by both is counted once'
                assert await totals(session, gid) == {'classic': D(1)}
                await assert_consistent(session)
            assert summary['moved']['score_events'] == 2
    run(case())


def test_reconcile_is_clean_after_backfill_and_repair_fixes_drift(pg_url):
    from storage.score_reconcile import reconcile, repair

    async def case():
        async with environment(pg_url) as db:
            async with db.transaction() as session:
                uid, acc, blocked, guest, chats = await seed_legacy(session)
            async with db.transaction() as session:
                await backfill(session)
            async with db.transaction() as session:
                report = await reconcile(session)
                assert report['ok'], report
                await session.execute(update(User).where(User.id == uid).values(global_score=D(1)))
                await session.execute(update(ScoreTotal).where(ScoreTotal.account_id == guest).values(total=D(99)))
            async with db.transaction() as session:
                report = await reconcile(session)
                assert not report['ok'] and report['counts']['cache'] == 1 and report['counts']['totals'] == 1
                await repair(session)
            async with db.transaction() as session:
                assert (await reconcile(session))['ok']
    run(case())
