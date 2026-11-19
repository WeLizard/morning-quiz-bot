"""Common private Photo round settlement for room and Telegram adapters."""
from uuid import UUID
from decimal import Decimal
from sqlalchemy import select, update, func
from domain.photo import complete_group_round
from storage.models import Account, User, ChatMember
from storage.repositories import OperationalRepository
from storage.score_ledger import RewardLedger


async def canonical_account(session, account_id, *, chain=False):
    seen = set()
    while account_id is not None:
        account_id = UUID(str(account_id))
        if account_id in seen:
            raise RuntimeError('Цикл объединения аккаунтов.')
        seen.add(account_id)
        row = (await session.execute(select(Account.id, Account.merged_into_id).where(Account.id == account_id))).first()
        if row is None:
            raise LookupError('Аккаунт не найден.')
        if row.merged_into_id is None:
            return (account_id, seen) if chain else account_id
        account_id = row.merged_into_id
    raise LookupError('Аккаунт не найден.')


async def viewer_aliases(session, account_id):
    """Read only aliases of the canonical viewer, including earlier merge targets."""
    if account_id is None:
        return []
    target = await canonical_account(session, account_id)
    aliases = select(Account.id).where(Account.id == target).cte('photo_viewer_aliases', recursive=True)
    aliases = aliases.union(select(Account.id).join(aliases, Account.merged_into_id == aliases.c.id))
    return [str(key) for key in (await session.scalars(select(aliases.c.id))).all()]


async def settle_group_round(session, game, state, *, round_id, now):
    item = next(r for r in state['rounds'] if r['round_id'] == round_id)
    if now < item['closes_at']:
        raise RuntimeError('Время ответа ещё не истекло.')
    pending = {UUID(key): response for key, response in item.get('responses', {}).items() if response.get('answered')}
    # A merge can commit while we discover its chain. Retry the complete lock batch
    # in a savepoint, never acquire a new User lock after taking an Account lock.
    for _ in range(8):
        chains = {key: await canonical_account(session, key, chain=True) for key in pending}
        targets = {key: value[0] for key, value in chains.items()}
        ids = set().union(*(value[1] for value in chains.values()))
        async with session.begin_nested() as savepoint:
            await session.execute(select(User.id).where(User.account_id.in_(ids)).order_by(User.id).with_for_update())
            rows = (await session.execute(select(Account.id, Account.merged_into_id).where(Account.id.in_(ids)).order_by(Account.id).with_for_update(read=True))).all()
            locked = {r.id: r.merged_into_id for r in rows}
            def stable_chain(key, target):
                visited = set()
                while key in locked and key not in visited:
                    visited.add(key)
                    if locked[key] is None:
                        return key == target
                    key = locked[key]
                return False
            stable = all(stable_chain(key, target) for key, target in targets.items())
            if not stable:
                await savepoint.rollback()
                continue
            collapsed = {}
            for key, response in pending.items():
                target = targets[key]
                if target not in collapsed or response['points'] > collapsed[target]['points']:
                    collapsed[target] = response
            solvers = []
            for target, response in sorted(collapsed.items()):
                points = Decimal(str(response['points']))
                applied = await RewardLedger.award(session, account_id=target, source='photo', amount=points,
                    key=f'photo:{game.id}:{round_id}', game_id=game.id, room_id=game.room_id, chat_id=game.chat_id)
                if applied and game.chat_id is not None:
                    users = (await session.scalars(select(User.id).where(User.account_id == target))).all()
                    if users:
                        await session.execute(update(ChatMember).where(ChatMember.chat_id == game.chat_id, ChatMember.user_id.in_(users)).values(
                            score=ChatMember.score + points,
                            correct_answers_count=ChatMember.correct_answers_count + 1))
                        for user_id in users:
                            if not await OperationalRepository(session).reserve_answer(
                                    poll_id=round_id, user_id=user_id, chat_id=game.chat_id,
                                    points_delta=points, selected_option=None, is_correct=True,
                                    payload={'quiz_type': 'photo'}, game_id=game.id, round_id=round_id):
                                raise RuntimeError('Ответ уже записан без групповой награды.')
                            member = await session.get(ChatMember, (game.chat_id, user_id))
                            if member is not None:
                                # Personal Photo preserves member timestamps and reconciles
                                # the User cache from them; it does not count classic polls.
                                await session.execute(update(User).where(User.id == user_id).values(
                                    first_answer_at=func.coalesce(User.first_answer_at, member.first_answer_at),
                                    last_answer_at=member.last_answer_at if member.last_answer_at is not None else User.last_answer_at))
                solvers.append({'account_id': str(target), 'name': response.get('name') or 'Игрок', 'points': float(points)})
            return complete_group_round(state, round_id=round_id, solvers=solvers, now=now)
    raise RuntimeError('Аккаунты меняются; повторите завершение раунда.')
