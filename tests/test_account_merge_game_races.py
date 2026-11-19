"""Real public merge flow versus Alchemy commands in disposable PostgreSQL schemas."""
import asyncio
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import func, select

from storage.alchemy import AlchemyService
from storage.mini_app import MiniAppError
from storage.models import (Account, AccountMerge, AlchemyCraftCommand,
                            AlchemyProgress, ScoreEvent, ScoreTotal)
from tests.test_account_merge_flow import (
    HEADERS, LOGIN, UID, begin_and_approve, complete, environment, guest,
    merge_body, telegram,
)
from tests.test_postgres_members import pg_env  # noqa: F401
from web.principal import GUEST_COOKIE


@pytest.mark.parametrize('rated', [False, True], ids=['guest-moves', 'telegram-rated'])
def test_public_merge_races_craft_without_lost_progress_or_duplicate_reward(pg_env, monkeypatch, rated):
    async def run():
        async with environment(pg_env, monkeypatch) as env:
            browser, guest_id = await guest(env, discovered=['air', 'stone'])
            telegram_id = await telegram(env, UID)
            service = AlchemyService(env.db)
            # Use the real sync command to make both profiles nonempty; imports award nothing.
            await service.sync(UID, discovered=['earth', 'lava'])
            await begin_and_approve(env, browser, UID)
            preview = await complete(browser)
            assert preview.status_code == 200, preview.text
            assert preview.json()['result'] == 'merge_required'
            assert preview.json()['auto'] is False
            raw = browser.cookies.get(GUEST_COOKIE)
            command = dict(command_id='merge-craft-race-0001',
                           ingredient_a='fire', ingredient_b='water')
            main_id, secondary_id = (guest_id, telegram_id) if rated else (telegram_id, guest_id)
            barrier = asyncio.Barrier(2)

            async def merge():
                await barrier.wait()
                response = await browser.post(LOGIN + '/merge', headers=HEADERS,
                    json=merge_body('current' if rated else 'telegram', guest_id, telegram_id))
                assert response.status_code == 200, response.text
                assert response.json()['account_id'] == main_id

            async def craft():
                await barrier.wait()
                try:
                    if rated:
                        return await service.craft(UID, **command)
                    return await service.guest_craft(raw, expected_account_id=guest_id, **command)
                except MiniAppError as error:
                    # The original guest actor may become stale while merge wins the locks.
                    assert not rated and error.status == 409 and error.code == 'profile_changed'
                    return None

            # No sleeps: both public operations start together; DB locks decide serialization.
            _, crafted = await asyncio.wait_for(asyncio.gather(merge(), craft()), timeout=20)
            async with env.db.transaction() as session:
                secondary = await session.get(Account, UUID(secondary_id))
                assert secondary.archived and str(secondary.merged_into_id) == main_id
                assert await session.scalar(select(func.count()).select_from(AccountMerge)) == 1
                receipt = await session.get(AlchemyCraftCommand, command['command_id'])
                if crafted is None:
                    assert receipt is None, 'Rejected original actor must not leave a command receipt'
                    assert 'steam' not in (await session.get(AlchemyProgress, UUID(main_id))).verified_discovered
                else:
                    assert crafted['verified'] and crafted['result'] == 'steam'
                    assert receipt.account_id == UUID(main_id) and receipt.result == crafted
                assert await session.scalar(select(func.count()).select_from(AlchemyCraftCommand)) == (crafted is not None)
                progress = await session.get(AlchemyProgress, UUID(main_id))
                assert {'air', 'stone', 'earth', 'lava'} <= set(progress.discovered)
                assert 'earth' in progress.verified_discovered
                if crafted is not None:
                    assert 'steam' in progress.verified_discovered
                total = await session.scalar(select(ScoreTotal.total).where(
                    ScoreTotal.account_id == UUID(main_id), ScoreTotal.source == 'alchemy'))
                awarded = Decimal(str(crafted['awarded'])) if crafted else Decimal(0)
                assert awarded > 0 if rated else awarded == 0
                assert (total or Decimal(0)) == awarded
                assert progress.points_total == awarded
                events = (await session.scalars(select(ScoreEvent).where(ScoreEvent.source == 'alchemy'))).all()
                assert sum((event.amount for event in events), Decimal(0)) == awarded
                assert all(event.account_id == UUID(main_id) for event in events)
            assert (await browser.get('/api/guest/me')).json()['account_id'] == main_id
            if crafted is not None:
                # Retry through the opposite channel after ownership moved: exact receipt, no award.
                if rated:
                    replay = await service.guest_craft(raw, expected_account_id=main_id, **command)
                else:
                    replay = await service.craft(UID, **command)
                assert replay == crafted
                async with env.db.transaction() as session:
                    assert await session.scalar(select(func.count()).select_from(AlchemyCraftCommand)) == 1
                    total = await session.scalar(select(ScoreTotal.total).where(
                        ScoreTotal.account_id == UUID(main_id), ScoreTotal.source == 'alchemy'))
                    assert (total or Decimal(0)) == awarded
    asyncio.run(run())
