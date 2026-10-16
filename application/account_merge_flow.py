"""Player-confirmed merge of the browser account with the account of a verified Telegram.

Telegram ownership is proven either by a bot-approved browser login request (cookie
``mqb_tglogin``) or by fresh signed Mini App ``initData``. The browser account comes from the
``mqb_guest`` session. Preview never writes; this confirmation rechecks both ids in one
transaction and then delegates to ``AccountMergeService.merge_in``.

Lock order inside ``confirm`` (platform order, rows before Accounts, accounts ascending):
operation_fence -> advisory ``mini-login:<uid>`` -> login request FOR UPDATE -> User(uid) ->
AccountIdentity(telegram uid) -> Users / AccountIdentities / GuestSessions of BOTH accounts
(``lock_owned_rows_in``) -> Account rows FOR NO KEY UPDATE ascending id -> (merge_in) AlchemyProgress
-> farm advisory locks. The browser account id is learned from the cookie without locking, then
re-verified after the locks; if the session moved meanwhile the request fails with profile_changed.
"""
from hashlib import sha256

from sqlalchemy import select, text

from application.account_merge import AccountMergeService
from storage.admin_actions import operation_fence
from storage.guest_accounts import credential_hash
from storage.mini_app import MiniAppError
from storage.models import Account, AccountIdentity, GuestSession, User

CHOICES = frozenset({'current', 'telegram'})


def login_lock_key(uid):
    return -1 - int(sha256(f'mini-login:{uid}'.encode()).hexdigest()[:15], 16)


async def telegram_account_id_in(session, uid):
    """Account of a Telegram user: its single active verified identity, else ``User.account_id``."""
    # User first, then identities: the platform lock order.
    user = await session.get(User, uid, with_for_update=True, populate_existing=True)
    if user is not None and (user.archived or user.bot_blocked):
        raise MiniAppError(403, 'Профиль Telegram недоступен.')
    rows = (await session.scalars(select(AccountIdentity).where(
        AccountIdentity.provider == 'telegram', AccountIdentity.provider_subject == str(uid),
        AccountIdentity.revoked_at.is_(None)).with_for_update()
        .execution_options(populate_existing=True))).all()
    if rows:
        if len(rows) != 1 or rows[0].verified_at is None:
            raise MiniAppError(409, 'Telegram требует восстановления.', code='telegram_link_conflict')
        if user is not None and user.account_id not in (None, rows[0].account_id):
            raise MiniAppError(409, 'Telegram требует восстановления.', code='telegram_link_conflict')
        return rows[0].account_id
    return user.account_id if user is not None else None


class AccountMergeFlow:
    def __init__(self, database, guest_store, *, logins=None, allowed_user_ids=None):
        self.database, self.guest_store, self.logins = database, guest_store, logins
        self.allowed_user_ids = allowed_user_ids

    async def _browser_account_id(self, session, credential):
        """Account of the browser session read WITHOUT locks (they are taken afterwards in order)."""
        digest = credential_hash(credential)  # MiniAppError(401) for a malformed cookie
        row = await session.scalar(select(GuestSession).where(GuestSession.token_hash == digest))
        if row is None or row.revoked or row.expires_at <= self.guest_store.now():
            raise MiniAppError(401, 'Гостевая сессия завершена')
        return row.account_id

    async def confirm(self, credential, *, main, account_id, telegram_account_id,
                      browser_secret=None, identity=None):
        """Exactly one Telegram proof: ``browser_secret`` (bot-approved login) or ``identity``."""
        if main not in CHOICES or (browser_secret is None) == (identity is None):
            raise MiniAppError(400, 'Некорректные параметры')
        async with self.database.transaction() as session:
            await operation_fence(session)
            request = None
            if browser_secret is not None:
                peek = await self.logins.peek_in(session, browser_secret)
                if peek.telegram_user_id is None:
                    raise MiniAppError(409, 'Вход ещё не подтверждён в Telegram.', code='login_pending')
                uid = peek.telegram_user_id
            else:
                uid = identity.user_id
            await session.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': login_lock_key(uid)})
            if browser_secret is not None:
                request = await self.logins.approved_in(session, browser_secret, lock=True)
                if request.telegram_user_id != uid:
                    raise MiniAppError(409, 'Профиль изменился. Повтори подтверждение.', code='profile_changed')
            if self.allowed_user_ids is not None and uid not in self.allowed_user_ids:
                raise MiniAppError(403, 'Этот тестовый Mini App доступен только приглашённому игроку')
            telegram_id = await telegram_account_id_in(session, uid)
            current_id = await self._browser_account_id(session, credential)
            ids = sorted({i for i in (current_id, telegram_id) if i is not None}, key=lambda value: value.bytes)
            merge = AccountMergeService(clock=self.guest_store.clock)
            # Users / identities / guest sessions of both accounts BEFORE any Account row.
            await merge.lock_owned_rows_in(session, ids)
            if ids:
                await session.execute(select(Account.id).where(Account.id.in_(ids)).order_by(Account.id)
                                      .with_for_update(key_share=True))
            current, browser = await self.guest_store.authorized_in(session, credential, lock=False)
            if current.id != current_id:
                raise MiniAppError(409, 'Профиль изменился. Повтори подтверждение.', code='profile_changed')
            now = self.guest_store.now()
            if identity is not None and not now.timestamp() - 300 <= identity.auth_date <= now.timestamp() + 30:
                raise MiniAppError(401, 'Недействительные или просроченные данные Telegram')
            if (telegram_id is None or str(current.id) != account_id
                    or str(telegram_id) != telegram_account_id):
                raise MiniAppError(409, 'Профиль изменился. Повтори подтверждение.', code='profile_changed')
            telegram = await session.get(Account, telegram_id, populate_existing=True)
            plan = await merge.plan_in(session, current=current, telegram_account=telegram)
            if plan['auto']:
                chosen, other = plan['main'], plan['secondary']
            else:
                chosen, other = (current, telegram) if main == 'current' else (telegram, current)
            summary = await merge.merge_in(session, main=chosen, secondary=other, via='player')
            if request is not None:
                await self.logins.consume_in(session, request)
            await session.refresh(browser)
            chosen = await session.get(Account, chosen.id, populate_existing=True)
            return {'result': 'merged', 'account_id': str(chosen.id),
                    'lost_login': summary.get('lost_login'),
                    'profile': await self.guest_store.projection_in(session, chosen, browser)}
