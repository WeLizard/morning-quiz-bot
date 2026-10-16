"""Merge two platform accounts into one (secondary -> main).

Runs inside the caller's transaction; the caller already holds ``operation_fence``
(and, for Telegram flows, the ``mini-login:<uid>`` advisory lock). Lock order, continuing the
platform order: User FOR UPDATE -> AccountIdentity FOR UPDATE -> GuestSession FOR UPDATE ->
Account(s) FOR NO KEY UPDATE (ascending id) -> AlchemyProgress (ascending account id) -> Farm
advisory locks (``Unit.lock``: ``account:<id>``, ``farm:<id>``).

``merge_in`` does NOT take the first three groups: they must be locked BEFORE any Account row,
so the caller calls ``lock_owned_rows_in(session, ids)`` for both accounts as soon as it knows
the ids, then locks the Account rows ascending, and only then calls ``merge_in``. Taking them
here, after the Accounts, would invert the order against any transaction that holds one of
those rows and waits for an Account.

Nothing is deleted except a duplicate room membership of the secondary account. The
secondary account is archived and marked ``merged_into_id``; an ``AccountMerge`` row
records what moved.  ``MERGE_POLICY`` classifies every foreign key that points at
``accounts.id``; a guard test fails when a new table appears without a decision.
"""
from __future__ import annotations

import time
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import exists, func, select, update

from storage.alchemy import BASE_ELEMENTS
from storage.mini_app import MiniAppError
from storage.models import (
    Account, AccountCredential, AccountIdentity, AccountMerge, AlchemyClaimCommand,
    AlchemyCraftCommand, AlchemyProgress, AlchemyStageClaim, Base, ClassicAccountAnswer,
    GamePlayer, GuestSession, Room, RoomInvite, RoomMembership, User,
)

MAX_QTY = 10 ** 9
MAX_COINS = 10 ** 12

# (table, column) -> how a merge treats rows that reference accounts.id.
#   move             rows are re-pointed to main
#   move_no_conflict re-pointed unless main already has the same key (then stay on secondary)
#   union            merged field by field / by key (see merge_in)
#   history          audit trail, never touched
#   special          handled explicitly by dedicated code
MERGE_POLICY = {
    ('accounts', 'merged_into_id'): 'special',
    ('account_merges', 'main_account_id'): 'special',
    ('account_merges', 'merged_account_id'): 'special',
    ('account_identities', 'account_id'): 'special',
    ('account_credentials', 'account_id'): 'special',
    ('rooms', 'owner_account_id'): 'move',
    ('room_memberships', 'account_id'): 'union',
    ('room_invites', 'created_by_account_id'): 'move',
    ('guest_sessions', 'account_id'): 'move',
    ('users', 'account_id'): 'move',
    ('game_players', 'account_id'): 'move_no_conflict',
    ('classic_account_answers', 'account_id'): 'move_no_conflict',
    ('game_commands', 'actor_account_id'): 'history',
    ('game_events', 'actor_account_id'): 'history',
    ('alchemy_progress', 'account_id'): 'union',
    ('alchemy_craft_commands', 'account_id'): 'move',
    ('alchemy_stage_claims', 'account_id'): 'move_no_conflict',
    ('alchemy_claim_commands', 'account_id'): 'move',
    ('farm_states', 'account_id'): 'special',
    ('farm_receipts', 'account_id'): 'special',
    ('farm_ledger', 'actor_account_id'): 'history',
    ('problem_reports', 'account_id'): 'history',
}

_UNION_LISTS = ('discovered', 'crafted', 'verified_discovered', 'verified_crafted',
                'verified_chapters', 'verified_achievements', 'chapters', 'achievements')
_SCALARS_FROM_MAIN = ('points_total', 'points_today', 'points_day', 'goal_streak',
                      'last_goal_day', 'attempts')


def policy_gaps(metadata=None):
    """Return foreign keys on accounts.id that MERGE_POLICY does not classify."""
    metadata = metadata or Base.metadata
    seen = set()
    for table in metadata.tables.values():
        for fk in table.foreign_keys:
            if fk.column.table.name == 'accounts' and fk.column.name == 'id':
                seen.add((table.name, fk.parent.name))
    return sorted(seen - set(MERGE_POLICY)), sorted(set(MERGE_POLICY) - seen)


def _union(first, second):
    out, seen = [], set()
    for item in list(first or []) + list(second or []):
        key = repr(item)
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


def _farm_tables(session):
    # Farm tables always exist after the Alembic chain (qw_farm_010), even when the web farm
    # routes are switched off, so register them here instead of trusting QW_FARM_ENABLED.
    from qw_farm.integration import register_models
    return register_models()


def _initial_farm_revision():
    try:
        from qw_farm.domain import new_farm
        from qw_farm.expansion import upgrade_state
        return int(upgrade_state(new_farm('00000000-0000-0000-0000-000000000000', 'x', 0))['revision'])
    except Exception:  # domain is owned by other sessions; fall back to the documented start
        return 0


class AccountMergeService:
    def __init__(self, clock=time.time):
        self.clock = clock

    def _now(self):
        return datetime.fromtimestamp(self.clock(), timezone.utc)

    # ------------------------------------------------------------------ reads
    async def _telegram_subject(self, session, account_id):
        subject = await session.scalar(select(AccountIdentity.provider_subject).where(
            AccountIdentity.account_id == account_id, AccountIdentity.provider == 'telegram',
            AccountIdentity.revoked_at.is_(None)).limit(1))
        if subject is None:
            user_id = await session.scalar(select(User.id).where(User.account_id == account_id))
            subject = str(user_id) if user_id is not None else None
        return subject

    async def _login(self, session, account_id):
        return await session.scalar(select(AccountIdentity.provider_subject).where(
            AccountIdentity.account_id == account_id, AccountIdentity.provider == 'password',
            AccountIdentity.revoked_at.is_(None)).limit(1))

    async def _count(self, session, column, value, *extra):
        return int(await session.scalar(select(func.count()).select_from(column.table).where(
            column == value, *extra)) or 0)

    async def _farm_info(self, session, account_id):
        schema = _farm_tables(session)
        info = {'exists': False, 'level': None, 'xp': 0, 'coins': 0, 'touched': False, 'id': None}
        if schema is None:
            return info
        states, ledger, receipts = schema['states'], schema['ledger'], schema['receipts']
        row = (await session.execute(select(states.c.id, states.c.xp, states.c.coins, states.c.revision)
                                     .where(states.c.account_id == account_id))).first()
        if row is None:
            return info
        touched = row.revision > _initial_farm_revision()
        if not touched:
            touched = bool(await session.scalar(select(exists().where(
                ledger.c.farm_id == row.id, ledger.c.kind != 'bootstrap'))))
        if not touched:
            touched = bool(await session.scalar(select(exists().where(
                receipts.c.account_id == account_id))))
        level = None
        try:
            from qw_farm.catalog import level as farm_level
            level = int(farm_level(row.xp))
        except Exception:
            pass
        info.update(exists=True, level=level, xp=int(row.xp), coins=int(row.coins),
                    touched=bool(touched), id=str(row.id))
        return info

    async def summary_in(self, session, account):
        aid = account.id
        progress = await session.get(AlchemyProgress, aid)
        alchemy = {'discovered': 0, 'points_total': '0', 'chapters': 0, 'claims': 0, 'dirty': False}
        if progress is not None:
            extra = (set(progress.discovered or []) | set(progress.verified_discovered or [])) - BASE_ELEMENTS
            claims = await self._count(session, AlchemyStageClaim.account_id, aid)
            alchemy.update(discovered=len(extra), points_total=str(progress.points_total or 0),
                           chapters=len(progress.chapters or []), claims=claims)
            alchemy['dirty'] = bool(extra or Decimal(progress.points_total or 0) > 0 or claims
                                    or progress.crafted or progress.verified_crafted
                                    or progress.chapters or progress.verified_chapters
                                    or progress.achievements or progress.verified_achievements)
        farm = await self._farm_info(session, aid)
        owned = await self._count(session, Room.owner_account_id, aid)
        memberships = await self._count(session, RoomMembership.account_id, aid)
        games = await self._count(session, GamePlayer.account_id, aid)
        answers = await self._count(session, ClassicAccountAnswer.account_id, aid)
        login = await self._login(session, aid)
        empty = not (login or alchemy['dirty'] or (farm['exists'] and farm['touched'])
                     or owned or memberships or games or answers)
        public_farm = {k: farm[k] for k in ('exists', 'level', 'xp', 'coins', 'touched')}
        public_alchemy = {k: alchemy[k] for k in ('discovered', 'points_total', 'chapters')}
        return {'account_id': str(aid), 'display_name': account.display_name, 'login': login,
                'telegram_user_id': await self._telegram_subject(session, aid),
                'alchemy': public_alchemy, 'farm': public_farm, 'rooms_owned': owned,
                'rooms_member': max(memberships - owned, 0), 'games': games,
                'classic_answers': answers, 'empty': bool(empty)}

    # ------------------------------------------------------------------- plan
    def _check_usable(self, *accounts):
        for account in accounts:
            if account is None or account.archived or account.bot_blocked or account.merged_into_id is not None:
                raise MiniAppError(409, 'Один из профилей недоступен для слияния.', code='merge_unavailable')

    async def _two_telegrams(self, session, first, second):
        a = await self._telegram_subject(session, first)
        b = await self._telegram_subject(session, second)
        return a is not None and b is not None

    async def plan_in(self, session, *, current, telegram_account):
        self._check_usable(current, telegram_account)
        if current.id == telegram_account.id:
            raise MiniAppError(409, 'Профили уже совпадают.', code='merge_unavailable')
        if await self._two_telegrams(session, current.id, telegram_account.id):
            raise MiniAppError(409, 'В одном профиле не может быть двух разных Telegram.',
                               code='merge_two_telegram')
        cs = await self.summary_in(session, current)
        ts = await self.summary_in(session, telegram_account)
        main = secondary = None
        auto = cs['empty'] or ts['empty']
        if auto:
            if cs['empty'] and not ts['empty']:
                main, secondary = telegram_account, current
            elif ts['empty'] and not cs['empty']:
                main, secondary = current, telegram_account
            else:
                main, secondary = telegram_account, current
        both = bool(cs['login'] and ts['login'])
        # The main profile keeps its login; the other profile's login stops working.
        lost_if_current_main = ts['login'] if both else None
        lost_if_telegram_main = cs['login'] if both else None
        # ``lost_login`` follows the actual main when it is known, else the default (current).
        lost = lost_if_telegram_main if main is not None and main.id != current.id else lost_if_current_main
        rules = ['Открытия и предметы объединяются.',
                 'Очки и рейтинг остаются от основного профиля.',
                 'Ферма основного профиля сохраняется; склад и заработанные монеты второй фермы добавляются к ней.']
        if both:
            rules.append(f'Вход по логину «{lost}» перестанет работать: останется логин основного профиля.'
                         if main is not None else
                         'Вход по логину второго профиля перестанет работать: останется логин основного.')
        return {'auto': auto, 'main': main, 'secondary': secondary,
                'preview': {'current': cs, 'telegram': ts, 'rules': rules, 'lost_login': lost,
                            'lost_login_if_current_main': lost_if_current_main,
                            'lost_login_if_telegram_main': lost_if_telegram_main}}

    # ------------------------------------------------------------------ merge
    @staticmethod
    async def lock_owned_rows_in(session, account_ids):
        """Lock Users, AccountIdentities and GuestSessions of the accounts, in platform order.

        Call this before locking any Account row of a merge (see the module docstring); rows that
        the caller already holds are re-locked harmlessly.
        """
        ids = list(account_ids)
        if not ids:
            return
        await session.execute(select(User.id).where(User.account_id.in_(ids))
                              .order_by(User.id).with_for_update())
        await session.execute(select(AccountIdentity.id).where(AccountIdentity.account_id.in_(ids))
                              .order_by(AccountIdentity.id).with_for_update())
        await session.execute(select(GuestSession.token_hash).where(GuestSession.account_id.in_(ids))
                              .order_by(GuestSession.token_hash).with_for_update())

    async def merge_in(self, session, *, main, secondary, via):
        if main is None or secondary is None or main.id == secondary.id:
            raise MiniAppError(409, 'Слияние невозможно.', code='merge_unavailable')
        ids = sorted([main.id, secondary.id], key=lambda value: value.bytes)
        # Users, identities and guest sessions were locked by the caller (``lock_owned_rows_in``)
        # before any Account row; accounts come next, ascending id, NO KEY UPDATE (compatible
        # with the FK checks of games/farm).
        locked = {row.id: row for row in (await session.scalars(
            select(Account).where(Account.id.in_(ids)).order_by(Account.id)
            .with_for_update(key_share=True).execution_options(populate_existing=True))).all()}
        main, secondary = locked.get(main.id), locked.get(secondary.id)
        self._check_usable(main, secondary)
        if await self._two_telegrams(session, main.id, secondary.id) or (
                await session.scalar(select(User.id).where(User.account_id == main.id)) is not None
                and await session.scalar(select(User.id).where(User.account_id == secondary.id)) is not None):
            raise MiniAppError(409, 'В одном профиле не может быть двух разных Telegram.',
                               code='merge_two_telegram')
        # 3) alchemy progress, 4) farm advisory locks
        await session.execute(select(AlchemyProgress.account_id).where(AlchemyProgress.account_id.in_(ids))
                              .order_by(AlchemyProgress.account_id).with_for_update())
        schema = _farm_tables(session)
        unit = None
        if schema is not None:
            from qw_farm.persistence import Unit
            unit = Unit(session, schema)
            states = schema['states']
            farm_ids = [str(r[0]) for r in (await session.execute(
                select(states.c.id).where(states.c.account_id.in_(ids)))).all()]
            await unit.lock('account:' + str(main.id), 'account:' + str(secondary.id),
                            *('farm:' + f for f in farm_ids))

        now = self._now()
        before_main = await self.summary_in(session, main)
        before_secondary = await self.summary_in(session, secondary)
        summary = {'main_account_id': str(main.id), 'secondary_account_id': str(secondary.id),
                   'via': via, 'before': {'main': before_main, 'secondary': before_secondary},
                   'moved': {}, 'left_on_secondary': {}, 'truncated': [], 'lost_login': None}
        moved, left = summary['moved'], summary['left_on_secondary']

        await self._merge_identities(session, main, secondary, now, summary)
        moved['users'] = (await session.execute(
            update(User).where(User.account_id == secondary.id).values(account_id=main.id))).rowcount
        moved['guest_sessions'] = (await session.execute(
            update(GuestSession).where(GuestSession.account_id == secondary.id)
            # created_via is cleared: a session that came from the secondary account must not keep
            # the "fresh Telegram login" status that allows a password change without the old one.
            .values(account_id=main.id, account_revision=main.moderation_revision,
                    created_via=None))).rowcount
        await self._merge_alchemy(session, main, secondary, summary)
        await self._merge_rooms(session, main, secondary, summary)
        await self._merge_games(session, main, secondary, summary)
        await self._merge_farm(session, unit, main, secondary, now, summary)

        if (main.display_name or '') == 'Гость' and secondary.display_name not in (None, '', 'Гость'):
            main.display_name = secondary.display_name
        if not main.address_form and secondary.address_form:
            main.address_form = secondary.address_form
        secondary.archived = True
        secondary.merged_into_id = main.id
        secondary.merged_at = now
        secondary.moderation_revision += 1
        await session.flush()
        after = await self.summary_in(session, main)
        summary['after'] = after
        session.add(AccountMerge(main_account_id=main.id, merged_account_id=secondary.id,
                                 initiated_via=str(via)[:16], summary=summary, created_at=now))
        await session.flush()
        return summary

    async def _merge_identities(self, session, main, secondary, now, summary):
        rows = (await session.scalars(select(AccountIdentity).where(
            AccountIdentity.account_id == secondary.id, AccountIdentity.revoked_at.is_(None))
            .execution_options(populate_existing=True))).all()
        main_has_password = await self._login(session, main.id) is not None
        count = 0
        for row in rows:
            if row.provider == 'password':
                if main_has_password:
                    row.revoked_at = now
                    summary['lost_login'] = row.provider_subject
                    continue
                credential = await session.get(AccountCredential, secondary.id)
                if credential is not None:
                    await session.execute(update(AccountCredential)
                                          .where(AccountCredential.account_id == secondary.id)
                                          .values(account_id=main.id))
            row.account_id = main.id
            count += 1
        summary['moved']['identities'] = count
        await session.flush()

    async def _merge_alchemy(self, session, main, secondary, summary):
        sec = await session.get(AlchemyProgress, secondary.id, populate_existing=True)
        mine = await session.get(AlchemyProgress, main.id, populate_existing=True)
        moved = summary['moved']
        if sec is not None and mine is None:
            await session.execute(update(AlchemyProgress).where(AlchemyProgress.account_id == secondary.id)
                                  .values(account_id=main.id))
            session.expunge(sec)
            moved['alchemy_progress'] = 'moved'
        elif sec is not None and mine is not None:
            carried_user = sec.user_id
            sec.user_id = None
            await session.flush()
            for field in _UNION_LISTS:
                setattr(mine, field, _union(getattr(mine, field), getattr(sec, field)))
            if mine.user_id is None and carried_user is not None:
                mine.user_id = carried_user
            moved['alchemy_progress'] = 'union'
        main_claims = select(AlchemyStageClaim.stage_id).where(AlchemyStageClaim.account_id == main.id)
        moved['alchemy_stage_claims'] = (await session.execute(
            update(AlchemyStageClaim).where(AlchemyStageClaim.account_id == secondary.id,
                                            AlchemyStageClaim.stage_id.not_in(main_claims))
            .values(account_id=main.id))).rowcount
        summary['left_on_secondary']['alchemy_stage_claims'] = await self._count(
            session, AlchemyStageClaim.account_id, secondary.id)
        for model, key in ((AlchemyCraftCommand, 'alchemy_craft_commands'),
                           (AlchemyClaimCommand, 'alchemy_claim_commands')):
            moved[key] = (await session.execute(
                update(model).where(model.account_id == secondary.id).values(account_id=main.id))).rowcount
        await session.flush()

    async def _merge_rooms(self, session, main, secondary, summary):
        moved = summary['moved']
        moved['rooms_owned'] = (await session.execute(
            update(Room).where(Room.owner_account_id == secondary.id).values(owner_account_id=main.id))).rowcount
        moved['room_invites'] = (await session.execute(
            update(RoomInvite).where(RoomInvite.created_by_account_id == secondary.id)
            .values(created_by_account_id=main.id))).rowcount
        theirs = (await session.scalars(select(RoomMembership).where(
            RoomMembership.account_id == secondary.id).order_by(RoomMembership.room_id)
            .execution_options(populate_existing=True))).all()
        mine = {m.room_id: m for m in (await session.scalars(select(RoomMembership).where(
            RoomMembership.account_id == main.id).execution_options(populate_existing=True))).all()}
        count = conflicts = 0
        for row in theirs:
            target = mine.get(row.room_id)
            if target is None:
                await session.execute(update(RoomMembership).where(
                    RoomMembership.room_id == row.room_id, RoomMembership.account_id == secondary.id)
                    .values(account_id=main.id))
                count += 1
            else:
                conflicts += 1
                if row.role == 'owner' and target.role != 'owner':
                    target.role = 'owner'
                    target.status = row.status
                await session.delete(row)
        moved['room_memberships'] = count
        summary['moved']['room_membership_conflicts'] = conflicts
        await session.flush()

    async def _merge_games(self, session, main, secondary, summary):
        gp = select(GamePlayer.game_id).where(GamePlayer.account_id == main.id)
        summary['moved']['game_players'] = (await session.execute(
            update(GamePlayer).where(GamePlayer.account_id == secondary.id, GamePlayer.game_id.not_in(gp))
            .values(account_id=main.id))).rowcount
        summary['left_on_secondary']['game_players'] = await self._count(
            session, GamePlayer.account_id, secondary.id)
        answered = select(ClassicAccountAnswer.game_id, ClassicAccountAnswer.round_id).where(
            ClassicAccountAnswer.account_id == main.id).subquery()
        conflict = exists().where(answered.c.game_id == ClassicAccountAnswer.game_id,
                                  answered.c.round_id == ClassicAccountAnswer.round_id)
        summary['moved']['classic_answers'] = (await session.execute(
            update(ClassicAccountAnswer).where(ClassicAccountAnswer.account_id == secondary.id, ~conflict)
            .values(account_id=main.id))).rowcount
        summary['left_on_secondary']['classic_answers'] = await self._count(
            session, ClassicAccountAnswer.account_id, secondary.id)

    async def _merge_farm(self, session, unit, main, secondary, now, summary):
        if unit is None:
            summary['farm'] = 'tables_absent'
            return
        t = unit.t
        states, receipts = t['states'], t['receipts']
        theirs = await unit.by_account(secondary.id)
        mine = await unit.by_account(main.id)
        if theirs is None:
            summary['farm'] = 'none_on_secondary'
            return
        info = await self._farm_info(session, secondary.id)
        if mine is None:
            await session.execute(update(states).where(states.c.account_id == secondary.id)
                                  .values(account_id=main.id))
            kept = select(receipts.c.command_id).where(receipts.c.account_id == main.id)
            await session.execute(update(receipts).where(receipts.c.account_id == secondary.id,
                                                         receipts.c.command_id.not_in(kept))
                                  .values(account_id=main.id))
            summary['farm'] = 'moved_to_main'
            return
        if not info['touched']:
            summary['farm'] = 'secondary_untouched_skipped'
            return
        before = deepcopy(mine)
        farm = deepcopy(mine)
        # Only earned coins move: the starter gift (``starter_credit``) cannot be spent on the market,
        # so merging a barely touched farm must not turn its gift into spendable coins.
        earned = max(0, int(theirs['coins']) - int(theirs.get('starter_credit') or 0))
        coins = int(farm['coins']) + earned
        if coins > MAX_COINS:
            summary['truncated'].append({'what': 'coins', 'lost': coins - MAX_COINS})
            earned -= coins - MAX_COINS
            coins = MAX_COINS
        farm['coins'] = coins
        inventory = dict(farm.get('inventory') or {})
        for key, qty in (theirs.get('inventory') or {}).items():
            total = int(inventory.get(key, 0)) + int(qty)
            if total > MAX_QTY:
                summary['truncated'].append({'what': 'item:' + key, 'lost': total - MAX_QTY})
                total = MAX_QTY
            inventory[key] = total
        farm['inventory'] = {k: v for k, v in inventory.items() if v}
        farm['revision'] = int(farm['revision']) + 1
        try:
            from qw_farm.domain import validate_state
            validate_state(farm)
        except Exception as error:
            raise MiniAppError(409, 'Не удалось объединить фермы.', code='merge_unavailable') from error
        await unit.save(farm)
        await unit.record(main.id, 'merge:' + str(secondary.id), 'account_merge', before, farm, self.clock())
        summary['farm'] = {'merged': True, 'coins_added': earned,
                           'starter_credit_not_moved': min(int(theirs['coins']), int(theirs.get('starter_credit') or 0)),
                           'items_added': {k: int(v) for k, v in (theirs.get('inventory') or {}).items()}}
