"""Completes a bot-approved Telegram login in the browser that started it.

Lock order matches MiniAppStore / AccountLinkingService: fence, advisory ``mini-login:<uid>``,
login request, User, identities, browser GuestSession, Accounts (ascending id), AlchemyProgress.

Nothing here changes a profile that is already open in the browser without an explicit second
step: with a current browser profile ``auto`` never links or merges, it returns ``link_required``
or ``merge_required`` and leaves the request unconsumed. Linking is ``mode='link'``; merging goes
through ``AccountMergeFlow.confirm`` (POST /api/account/telegram-login/merge), which takes the
row locks of both accounts before their Account rows. This service therefore never calls
``merge_in`` itself.
"""
from hashlib import sha256

from sqlalchemy import or_, select, text
from sqlalchemy.dialects.postgresql import insert

from storage.admin_actions import operation_fence
from storage.guest_accounts import credential_hash
from storage.mini_app import MiniAppError
from storage.models import (Account, AccountIdentity, AlchemyProgress, Chat, ChatMember,
                            GuestSession, User)
from storage.telegram_accounts import TelegramAccountUnavailable, telegram_account


OTHER_TELEGRAM = ('К этому профилю уже привязан другой Telegram. '
                  'Можно войти в профиль этого Telegram, текущий останется нетронутым.')
LINK_CONFLICT = ('Этот Telegram уже связан с другим профилем или требует восстановления. '
                 'Текущий профиль и его прогресс сохранены.')
MODES = frozenset({'auto', 'switch', 'link'})


class TelegramLoginService:
    def __init__(self, database, guest_store, logins, *, allowed_user_ids=None):
        self.database, self.guest_store, self.logins = database, guest_store, logins
        self.allowed_user_ids = allowed_user_ids

    async def complete(self, browser_secret, credential, *, mode='auto', user_agent=None):
        """Returns ``(payload, raw_session_or_None)``; payload['result'] names the branch taken."""
        if mode not in MODES:
            raise MiniAppError(400, 'Некорректные параметры')
        async with self.database.transaction() as session:
            await operation_fence(session)
            # The Telegram id lives in the request row, so read it unlocked, take the shared
            # login advisory lock, then re-read the row under FOR UPDATE.
            peek = await self.logins.peek_in(session, browser_secret)
            if peek.telegram_user_id is None or peek.status != 'approved':
                # Not approved yet (or already closed): answer immediately without any lock.
                await self.logins.approved_in(session, browser_secret, lock=False)
                raise MiniAppError(409, 'Вход ещё не подтверждён в Telegram.', code='login_pending')
            key = -1 - int(sha256(f'mini-login:{peek.telegram_user_id}'.encode()).hexdigest()[:15], 16)
            await session.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': key})
            request = await self.logins.approved_in(session, browser_secret, lock=True)
            uid = request.telegram_user_id
            if self.allowed_user_ids is not None and uid not in self.allowed_user_ids:
                raise MiniAppError(403, 'Этот тестовый Mini App доступен только приглашённому игроку')
            now = self.guest_store.now()

            user = await session.get(User, uid, with_for_update=True, populate_existing=True)
            if user is not None and (user.archived or user.bot_blocked):
                raise MiniAppError(403, 'Профиль Telegram недоступен.')
            mappings = (await session.scalars(select(AccountIdentity).where(
                AccountIdentity.provider == 'telegram',
                AccountIdentity.provider_subject == str(uid),
            ).with_for_update().execution_options(populate_existing=True))).all()
            active = [row for row in mappings if row.revoked_at is None]
            if mappings and (len(active) != 1 or active[0].verified_at is None):
                raise MiniAppError(403, 'Профиль Telegram недоступен.')
            telegram_id = None
            if active:
                telegram_id = active[0].account_id
                if user is not None and user.account_id != telegram_id:
                    raise MiniAppError(409, LINK_CONFLICT, code='telegram_link_conflict')
            elif user is not None:
                telegram_id = user.account_id

            current_session, current_id = await self._browser_session(session, credential)
            ids = sorted({i for i in (current_id, telegram_id) if i is not None})
            locked = {}
            if ids:
                rows = (await session.scalars(select(Account).where(Account.id.in_(ids))
                    .order_by(Account.id).with_for_update(key_share=True)
                    .execution_options(populate_existing=True))).all()
                locked = {row.id: row for row in rows}
            current = locked.get(current_id)
            if current is not None and (current.archived or current.bot_blocked
                    or current.moderation_revision != current_session.account_revision):
                current, current_session = None, None
            telegram = locked.get(telegram_id)
            if telegram is not None and (telegram.archived or telegram.bot_blocked):
                raise MiniAppError(403, 'Аккаунт недоступен.')
            if telegram_id is not None and telegram is None:
                raise MiniAppError(403, 'Аккаунт недоступен.')

            if telegram is not None and not active:
                # Legacy User with an account but no identity row: normalise like Mini App login.
                try:
                    await telegram_account(session, user, provision=True, now=now)
                except TelegramAccountUnavailable as error:
                    raise MiniAppError(403, str(error)) from None
            payload = await self._branch(session, request, uid, user, active, current,
                                         current_session, telegram, mode, now, user_agent)
            if payload['result'] not in ('merge_required', 'link_required'):
                await self.logins.consume_in(session, request)
            return payload, payload.pop('_raw', None)

    async def _browser_session(self, session, credential):
        if not credential:
            return None, None
        try:
            digest = credential_hash(credential)
        except MiniAppError:
            return None, None
        row = await session.scalar(select(GuestSession).where(
            GuestSession.token_hash == digest).with_for_update())
        if row is None or row.revoked or row.expires_at <= self.guest_store.now():
            return None, None
        return row, row.account_id

    async def _branch(self, session, request, uid, user, active, current, current_session,
                      telegram, mode, now, user_agent):
        if current is not None and telegram is not None and current.id == telegram.id:
            # Same account: the player just proved Telegram again, so this is a fresh Telegram
            # sign-in. Replace the browser session (it may be old or password-created) so that
            # password recovery without the old password works from the new one.
            current_session.revoked = True
            raw, row = self.guest_store._session(current, created_via='telegram', user_agent=user_agent)
            session.add(row)
            await session.flush()
            return {'result': 'already_linked', 'account_id': str(current.id), '_raw': raw,
                    'profile': await self.guest_store.projection_in(session, current, row)}
        if current is None or mode == 'switch':
            if telegram is None:
                telegram, user = await self._provision(session, request, uid, user, now)
            if current_session is not None:
                current_session.revoked = True
            raw, row = self.guest_store._session(telegram, created_via='telegram', user_agent=user_agent)
            session.add(row)
            await session.flush()
            return {'result': 'logged_in', 'account_id': str(telegram.id), '_raw': raw,
                    'profile': await self.guest_store.projection_in(session, telegram, row)}
        other = await session.scalar(select(AccountIdentity.id).where(
            AccountIdentity.account_id == current.id, AccountIdentity.provider == 'telegram',
            AccountIdentity.provider_subject != str(uid), AccountIdentity.revoked_at.is_(None)).limit(1))
        other_user = await session.scalar(select(User.id).where(
            User.account_id == current.id, User.id != uid).limit(1))
        if other is not None or other_user is not None:
            raise MiniAppError(409, OTHER_TELEGRAM, code='telegram_other_linked')
        if telegram is None:
            if mode != 'link':
                # Never attach a Telegram to the open profile silently: the player must confirm.
                return {'result': 'link_required', 'account_id': str(current.id),
                        'display_name': current.display_name, 'telegram_user_id': str(uid),
                        'telegram_display_name': request.telegram_display_name,
                        'profile': await self.guest_store.projection_in(session, current, current_session)}
            await self._link(session, request, uid, user, current, now)
            return {'result': 'linked', 'account_id': str(current.id),
                    'profile': await self.guest_store.projection_in(session, current, current_session)}
        from application.account_merge import AccountMergeService  # Lazy: avoids an import cycle.
        merge = AccountMergeService(clock=self.guest_store.clock)
        plan = await merge.plan_in(session, current=current, telegram_account=telegram)
        # Even when one side is empty ('auto'), the merge itself is a separate confirmed step.
        return {'result': 'merge_required', 'auto': bool(plan['auto']), 'preview': plan['preview'],
                'account_id': str(current.id), 'telegram_account_id': str(telegram.id),
                'profile': await self.guest_store.projection_in(session, current, current_session)}

    async def _provision(self, session, request, uid, user, now):
        """First Telegram login: same rows MiniAppStore.create_session(provision=True) creates."""
        if user is None:
            await session.execute(insert(User).values(
                id=uid, display_name=request.telegram_display_name or 'Игрок').on_conflict_do_nothing())
            user = await session.get(User, uid, with_for_update=True, populate_existing=True)
            if user is None or user.archived or user.bot_blocked:
                raise MiniAppError(403, 'Профиль Telegram недоступен.')
        try:
            account = await telegram_account(session, user, provision=True, now=now)
        except TelegramAccountUnavailable as error:
            raise MiniAppError(403, str(error)) from None
        await session.execute(insert(Chat).values(
            id=user.id, type='private', title=user.display_name).on_conflict_do_nothing())
        await session.execute(insert(ChatMember).values(
            chat_id=user.id, user_id=user.id).on_conflict_do_nothing())
        return account, user

    async def _link(self, session, request, uid, user, current, now):
        """Attach this Telegram to the browser account (no other Telegram, no T account)."""
        if user is None:
            await session.execute(insert(User).values(
                id=uid, display_name=request.telegram_display_name or 'Игрок').on_conflict_do_nothing())
            user = await session.get(User, uid, with_for_update=True, populate_existing=True)
            if user is None or user.archived or user.bot_blocked or user.account_id is not None:
                raise MiniAppError(409, LINK_CONFLICT, code='telegram_link_conflict')
        progress = (await session.scalars(select(AlchemyProgress).where(or_(
            AlchemyProgress.account_id == current.id, AlchemyProgress.user_id == uid,
        )).order_by(AlchemyProgress.account_id).with_for_update())).all()
        if any(row.account_id != current.id or row.user_id not in (None, uid) for row in progress):
            raise MiniAppError(409, LINK_CONFLICT, code='telegram_link_conflict')
        user.account_id = current.id
        session.add(AccountIdentity(account_id=current.id, provider='telegram',
            provider_subject=str(uid), verified_at=now, linked_at=now))
        for row in progress:
            row.user_id = uid
        await session.flush()
