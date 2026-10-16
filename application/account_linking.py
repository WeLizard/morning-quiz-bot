"""Explicitly add a verified Telegram login to the current browser account."""
from hashlib import sha256

from sqlalchemy import or_, select, text
from sqlalchemy.dialects.postgresql import insert

from storage.admin_actions import operation_fence
from storage.guest_accounts import normalize_display_name
from storage.mini_app import MiniAppError
from storage.models import Account, AccountIdentity, AlchemyProgress, User


CONFLICT = ('Этот Telegram уже связан с другим профилем или требует восстановления. '
            'Для двух профилей потребуется отдельное слияние. '
            'Текущий профиль и его прогресс сохранены.')


class AccountLinkingService:
    def __init__(self, database, guest_store, *, allowed_user_ids=None):
        self.database, self.guest_store = database, guest_store
        self.allowed_user_ids = allowed_user_ids

    async def telegram(self, credential, identity, *, confirm=False,
                       expected_account_id=None, expected_telegram_user_id=None):
        """Preview is read-only; confirmation rechecks everything in one transaction.

        No session provisioning: a first Telegram login would allocate a competing
        Account. Lock order matches MiniAppStore: fence, login, User, identity,
        browser session, Account, progress. Account's NO KEY UPDATE lock also
        serializes links from different Telegram users to the same account.
        """
        uid = identity.user_id
        if self.allowed_user_ids is not None and uid not in self.allowed_user_ids:
            raise MiniAppError(403, 'Этот тестовый Mini App доступен только приглашённому игроку')
        async with self.database.transaction() as session:
            await operation_fence(session)
            key = -1 - int(sha256(f'mini-login:{uid}'.encode()).hexdigest()[:15], 16)
            await session.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': key})
            user = await session.get(User, uid, with_for_update=True, populate_existing=True)
            if user is not None and (user.archived or user.bot_blocked):
                raise MiniAppError(403, 'Профиль Telegram недоступен.')
            mappings = (await session.scalars(select(AccountIdentity).where(
                AccountIdentity.provider == 'telegram',
                AccountIdentity.provider_subject == str(uid),
            ).with_for_update())).all()
            account, browser = await self.guest_store.authorized_in(session, credential, lock=True)
            if confirm and (expected_account_id != str(account.id)
                            or expected_telegram_user_id != str(uid)):
                raise MiniAppError(409, 'Профиль изменился. Повтори подтверждение.', code='profile_changed')
            active = [row for row in mappings if row.revoked_at is None]
            other_id = None
            if (len(active) == 1 and active[0].verified_at is not None and active[0].account_id != account.id
                    and (user is None or user.account_id in (None, active[0].account_id))):
                other_id = active[0].account_id
            elif not mappings and user is not None and user.account_id not in (None, account.id):
                other_id = user.account_id
            if other_id is not None:
                # One account for the whole app: the Telegram already owns another account,
                # so offer the merge (preview only); confirmation goes through
                # /api/account/telegram-link/merge with an explicit choice of the main profile.
                if confirm:
                    raise MiniAppError(409, 'Нужно объединить профили. Повтори подтверждение.',
                                       code='merge_required')
                return await self._merge_offer(session, account, other_id, identity)
            if (user is not None and user.account_id not in (None, account.id)) or (
                    mappings and (len(active) != 1 or active[0].account_id != account.id
                                  or active[0].verified_at is None)):
                raise MiniAppError(409, CONFLICT, code='telegram_link_conflict')
            other_user = await session.scalar(select(User.id).where(
                User.account_id == account.id, User.id != uid).limit(1))
            other_identity = await session.scalar(select(AccountIdentity.id).where(
                AccountIdentity.account_id == account.id,
                AccountIdentity.provider == 'telegram',
                AccountIdentity.provider_subject != str(uid),
                AccountIdentity.revoked_at.is_(None)).limit(1))
            if other_user is not None or other_identity is not None:
                raise MiniAppError(409, CONFLICT, code='telegram_link_conflict')
            progress_rows = (await session.scalars(select(AlchemyProgress).where(or_(
                AlchemyProgress.account_id == account.id, AlchemyProgress.user_id == uid,
            )).order_by(AlchemyProgress.account_id).with_for_update())).all()
            # A request may wait on concurrent login/game commands. Authentication
            # must still be fresh once all ownership locks have been acquired.
            now = self.guest_store.now()
            if not now.timestamp() - 300 <= identity.auth_date <= now.timestamp() + 30:
                raise MiniAppError(401, 'Недействительные или просроченные данные Telegram')
            if browser.revoked or browser.expires_at <= now:
                raise MiniAppError(401, 'Гостевая сессия завершена')
            if any(row.account_id != account.id or row.user_id not in (None, uid)
                   for row in progress_rows):
                raise MiniAppError(409, CONFLICT, code='telegram_link_conflict')
            already_linked = bool(active and user is not None and user.account_id == account.id)
            result = {'account_id': str(account.id), 'display_name': account.display_name,
                      'telegram_user_id': str(uid),
                      'telegram_display_name': normalize_display_name(
                          f'{identity.first_name} {identity.last_name}')[:40] or 'Игрок',
                      'already_linked': already_linked}
            if not confirm:
                return result
            if user is None:
                await session.execute(insert(User).values(
                    id=uid, display_name=result['telegram_display_name']).on_conflict_do_nothing())
                user = await session.get(User, uid, with_for_update=True, populate_existing=True)
                # A bot adapter can create User without the Mini App advisory lock.
                if (user is None or user.archived or user.bot_blocked
                        or user.account_id not in (None, account.id)):
                    raise MiniAppError(409, CONFLICT, code='telegram_link_conflict')
            user.account_id = account.id
            if not active:
                session.add(AccountIdentity(account_id=account.id, provider='telegram',
                    provider_subject=str(uid), verified_at=now, linked_at=now))
            # Keep the exact account/progress; only its transitional Telegram
            # projection changes. Offline claims and existing reward receipts stay intact.
            for row in progress_rows:
                row.user_id = uid
            await session.flush()
            return {**result, 'already_linked': True, 'linked': True,
                    'profile': await self.guest_store.projection_in(session, account, browser)}

    async def _merge_offer(self, session, account, other_id, identity):
        from application.account_merge import AccountMergeService
        other = await session.get(Account, other_id, populate_existing=True)
        plan = await AccountMergeService(clock=self.guest_store.clock).plan_in(
            session, current=account, telegram_account=other)
        return {'account_id': str(account.id), 'display_name': account.display_name,
                'telegram_user_id': str(identity.user_id),
                'telegram_display_name': normalize_display_name(
                    f'{identity.first_name} {identity.last_name}')[:40] or 'Игрок',
                'already_linked': False, 'merge_required': True, 'auto': plan['auto'],
                'telegram_account_id': str(other_id), 'preview': plan['preview']}
