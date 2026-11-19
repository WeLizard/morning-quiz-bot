"""Account-owned standalone rooms, invitations, and privacy-scoped projections."""

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import re
import secrets
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert

from domain.mafia import MIN_PLAYERS, MAX_PLAYERS, open_table_summary
from domain.night_worlds import require_age_ok, world_age, world_or_default
from storage.models import Game, Room, RoomInvite, RoomMembership
from storage.admin_actions import operation_fence
from storage.games import GameRepository
from application import room_limits
from application.room_limits import InviteRejected, RoomRateLimited  # noqa: F401  (re-exported for adapters)


MIN_INVITE_TTL_SECONDS = 300
MAX_INVITE_TTL_SECONDS = 30 * 24 * 60 * 60
MAX_INVITE_USES = 100
# An open room leaves the public list after this long without activity.
OPEN_ROOM_IDLE = timedelta(minutes=30)
OPEN_LIST_LIMIT = 50


def normalize_room_title(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError('Название комнаты должно быть текстом.')
    title = ' '.join(value.split())
    if not title:
        raise ValueError('Дай комнате название.')
    if len(title) > 80:
        raise ValueError('Название комнаты — максимум 80 символов.')
    if any(ord(char) < 32 for char in title):
        raise ValueError('Название содержит недопустимые символы.')
    return title


class RoomApplicationService:
    """Standalone account rooms; identity always comes from the auth adapter."""

    def __init__(self, session):
        self.session = session

    @staticmethod
    def open_is_fresh(room: Room, now: datetime | None = None) -> bool:
        """Open and active within the last OPEN_ROOM_IDLE; otherwise it is off the public list."""
        if not room.is_open or room.open_activity_at is None:
            return False
        return room.open_activity_at + OPEN_ROOM_IDLE > (now or datetime.now(timezone.utc))

    @staticmethod
    def touch_open(room: Room, now: datetime | None = None) -> None:
        """Activity keeps a still-listed room listed; it never revives an expired one."""
        current = now or datetime.now(timezone.utc)
        if RoomApplicationService.open_is_fresh(room, current):
            room.open_activity_at = current

    @classmethod
    def projection(cls, room: Room, membership: RoomMembership) -> dict:
        fresh = cls.open_is_fresh(room)
        return {
            'id': room.id,
            'kind': room.kind,
            'title': room.title,
            'role': membership.role,
            'membership_version': membership.updated_at.isoformat(),
            'created_at': room.created_at.isoformat() if room.created_at else None,
            'world': world_or_default(room.world),
            'world_age': world_age(room.world),
            'open': fresh,
            # When an idle open room drops off the public list (null when closed).
            'open_expires_at': (room.open_activity_at + OPEN_ROOM_IDLE).isoformat() if fresh else None,
        }

    async def create(self, *, account_id: UUID, request_id: str, title: object) -> dict:
        try:
            room_id = str(UUID(request_id))
        except (TypeError, ValueError, AttributeError):
            raise ValueError('Некорректный ключ создания комнаты.') from None
        normalized_title = normalize_room_title(title)
        statement = insert(Room).values(
            id=room_id, kind='standalone', title=normalized_title,
            owner_account_id=account_id, state={},
        ).on_conflict_do_nothing(index_elements=[Room.id])
        await self.session.execute(statement)
        room = await self.session.scalar(select(Room).where(Room.id == room_id).with_for_update())
        if (room is None or room.kind != 'standalone'
                or room.owner_account_id != account_id or room.title != normalized_title):
            raise RuntimeError('Ключ уже использован. Обнови список комнат и повтори создание.')

        member = await self.session.get(RoomMembership, (room_id, account_id))
        if member is None:
            member = RoomMembership(
                room_id=room_id, account_id=account_id, role='owner', status='active'
            )
            self.session.add(member)
            await self.session.flush()
        elif member.role != 'owner' or member.status != 'active':
            raise RuntimeError('Нет доступа к этой комнате.')
        return self.projection(room, member)

    async def list_mine(self, *, account_id: UUID) -> list[dict]:
        rows = (await self.session.execute(
            select(Room, RoomMembership).join(
                RoomMembership, RoomMembership.room_id == Room.id
            ).where(
                RoomMembership.account_id == account_id,
                RoomMembership.status == 'active',
                Room.kind == 'standalone',
            ).order_by(Room.created_at.desc(), Room.id)
        )).all()
        return [self.projection(room, membership) for room, membership in rows]

    async def get_mine(self, *, account_id: UUID, room_id: str) -> dict:
        row = await self.session.execute(
            select(Room, RoomMembership).join(
                RoomMembership, RoomMembership.room_id == Room.id
            ).where(
                Room.id == room_id,
                Room.kind == 'standalone',
                RoomMembership.account_id == account_id,
                RoomMembership.status == 'active',
            )
        )
        result = row.first()
        if result is None:
            raise LookupError('Комната не найдена.')
        return self.projection(*result)

    async def leave(self, *, account_id: UUID, room_id: str,
                    membership_version: object) -> dict:
        """Deactivate own membership, retaining accounts, games and history.

        Lock absent game keys too, so first starts/restarts cannot bypass the
        active-game check. Membership is re-read after Room serialization.
        """
        if not isinstance(membership_version, str) or not 1 <= len(membership_version) <= 64:
            raise ValueError('Обнови список комнат перед выходом.')
        await operation_fence(self.session)
        from storage.games import night_room_lock
        await night_room_lock(self.session, room_id)
        games = GameRepository(self.session)
        current_games = [await games.current_in_room(room_id=room_id, mode=mode, lock=True)
                         for mode in ('classic', 'mafia', 'photo', 'night_case')]
        room = await self.session.scalar(select(Room).where(
            Room.id == room_id, Room.kind == 'standalone',
        ).with_for_update().execution_options(populate_existing=True))
        member = await self.session.scalar(select(RoomMembership).where(
            RoomMembership.room_id == room_id, RoomMembership.account_id == account_id,
        ).with_for_update().execution_options(populate_existing=True))
        if room is None or member is None:
            raise LookupError('Комната не найдена.')
        if room.owner_account_id == account_id or member.role == 'owner':
            raise PermissionError('Владелец не может выйти из своей комнаты.')
        if member.status == 'inactive':
            return {'left': False}
        if member.status != 'active':
            raise LookupError('Комната не найдена.')
        if member.updated_at.isoformat() != membership_version:
            raise RuntimeError('Участие в комнате изменилось. Обнови список и повтори выход.')
        if any(game is not None and game.mode not in {'mafia', 'night_case'}
               and game.status not in {'finished', 'stopped', 'interrupted'}
               for game in current_games):
            raise RuntimeError('Нельзя выйти, пока в комнате есть незавершённая игра или лобби.')
        night = next((g for g in current_games if g is not None and g.mode == 'night_case'), None)
        if night is not None:
            from application.night_case import check_room_leave
            await check_room_leave(self.session, night, account_id)
        await room_limits.charge_membership(self.session, account_id)
        table = None
        mafia = next((game for game in current_games if game is not None and game.mode == 'mafia'), None)
        if mafia is not None:
            # Night City: a seat / queue place is given up, a living hero drops out of the case.
            from application.mafia import MafiaApplicationService
            outcome = (await MafiaApplicationService(self.session).leave_table(mafia, room, account_id))['outcome']
            table = None if outcome == 'none' else outcome
        member.status = 'inactive'
        # now() is transaction-start time: after waiting for a lock it can be
        # older than the previous write. Keep this token monotonic on the DB.
        member.updated_at = func.greatest(func.clock_timestamp(),
                                         RoomMembership.updated_at + text("interval '1 microsecond'"))
        await self.session.flush()
        await self.session.refresh(member, ['updated_at'])
        return {'left': True} if table is None else {'left': True, 'table': table}

    async def create_invite(
        self, *, account_id: UUID, room_id: str,
        expires_in_seconds: object, max_uses: object,
        now: datetime | None = None,
    ) -> dict:
        if type(expires_in_seconds) is not int or not (
            MIN_INVITE_TTL_SECONDS <= expires_in_seconds <= MAX_INVITE_TTL_SECONDS
        ):
            raise ValueError('Срок приглашения должен быть от 5 минут до 30 дней.')
        if type(max_uses) is not int or not 1 <= max_uses <= MAX_INVITE_USES:
            raise ValueError('Лимит использований должен быть от 1 до 100.')
        room = await self.session.scalar(select(Room).where(
            Room.id == room_id, Room.kind == 'standalone',
        ).with_for_update())
        member = await self.session.get(RoomMembership, (room_id, account_id))
        if room is None or room.owner_account_id != account_id or member is None \
                or member.role != 'owner' or member.status != 'active':
            raise LookupError('Комната не найдена.')

        token = secrets.token_urlsafe(32)
        current = now or datetime.now(timezone.utc)
        for _ in range(8):
            short = room_limits.generate_short_code()
            short_hash = room_limits.short_code_hash(short)
            taken = select(RoomInvite.id).where(
                RoomInvite.short_hash.in_(room_limits.short_code_hashes(short))).limit(1)
            if await self.session.scalar(taken) is None:
                break
        else:
            raise RuntimeError('Не удалось выпустить короткий код. Повтори.')
        row = RoomInvite(
            id=str(uuid4()), room_id=room_id, created_by_account_id=account_id,
            token_hash=sha256(token.encode('ascii')).hexdigest(), short_hash=short_hash,
            expires_at=current + timedelta(seconds=expires_in_seconds),
            max_uses=max_uses, uses=0,
        )
        self.session.add(row)
        await self.session.flush()
        # The bearer secret is returned only once; only its hash is persisted.
        return {
            'id': row.id, 'room_id': room_id, 'room_title': room.title,
            'invite_code': token, 'short_code': room_limits.format_short_code(short),
            'expires_at': row.expires_at.isoformat(),
            'max_uses': row.max_uses, 'uses': row.uses,
        }

    async def list_invites(self, *, account_id: UUID, room_id: str) -> list[dict]:
        room = await self.session.scalar(select(Room).where(
            Room.id == room_id, Room.kind == 'standalone',
            Room.owner_account_id == account_id,
        ))
        if room is None:
            raise LookupError('Комната не найдена.')
        rows = (await self.session.scalars(select(RoomInvite).where(
            RoomInvite.room_id == room_id,
        ).order_by(RoomInvite.created_at.desc(), RoomInvite.id))).all()
        return [{
            'id': row.id, 'expires_at': row.expires_at.isoformat(),
            'max_uses': row.max_uses, 'uses': row.uses,
            'revoked': row.revoked_at is not None,
        } for row in rows]

    async def revoke_invite(
        self, *, account_id: UUID, room_id: str, invite_id: str,
        now: datetime | None = None,
    ) -> bool:
        room = await self.session.scalar(select(Room).where(
            Room.id == room_id, Room.kind == 'standalone',
            Room.owner_account_id == account_id,
        ).with_for_update())
        if room is None:
            raise LookupError('Комната не найдена.')
        invite = await self.session.scalar(select(RoomInvite).where(
            RoomInvite.id == invite_id, RoomInvite.room_id == room_id,
        ).with_for_update())
        if invite is None:
            raise LookupError('Приглашение не найдено.')
        if invite.revoked_at is None:
            invite.revoked_at = now or datetime.now(timezone.utc)
            await self.session.flush()
        return True

    async def join_by_invite(
        self, *, account_id: UUID, invite_code: object,
        now: datetime | None = None, age_ok: bool = False,
    ) -> dict:
        """Join with the long link token (unchanged contract: one generic refusal)."""
        if not isinstance(invite_code, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', invite_code):
            raise LookupError('Приглашение недействительно или срок его действия истёк.')
        digest = sha256(invite_code.encode('ascii')).hexdigest()
        try:
            return await self._join_with_invite(
                account_id=account_id, column=RoomInvite.token_hash, digests=[digest], now=now, age_ok=age_ok)
        except InviteRejected as rejected:
            raise LookupError('Приглашение недействительно или срок его действия истёк.') from rejected

    async def join_by_short_code(
        self, *, account_id: UUID, code: object, now: datetime | None = None,
        client: str | None = None, age_ok: bool = False,
    ) -> dict:
        """Join with the typed code (K7Q4-MD2X): case/hyphen-insensitive, brute-force limited.

        A refusal is recorded in the failure ledger and raised as ``InviteRejected`` with a reason
        (unknown / expired / revoked / exhausted) and, for a real code, the room title. The caller
        must COMMIT the transaction when it catches ``InviteRejected`` or ``RoomRateLimited``
        (answer from inside the transaction block) or the failure is not counted.
        ``client`` is a hash of the caller's network address for the per-address failure limit.
        """
        current = now or datetime.now(timezone.utc)
        await room_limits.check_code_entry_allowed(self.session, account_id, current, client)
        normalized = room_limits.normalize_short_code(code)
        if normalized is None:
            await room_limits.record_code_failure(self.session, account_id, current, client)
            raise InviteRejected('unknown', 'Код не подходит. Проверь буквы и цифры.')
        try:
            return await self._join_with_invite(
                account_id=account_id, column=RoomInvite.short_hash,
                digests=room_limits.short_code_hashes(normalized), now=current, age_ok=age_ok)
        except InviteRejected:
            await room_limits.record_code_failure(self.session, account_id, current, client)
            raise

    async def _join_with_invite(self, *, account_id: UUID, column, digests: list[str],
                                now: datetime | None, age_ok: bool = False) -> dict:
        room_id = await self.session.scalar(select(RoomInvite.room_id).where(column.in_(digests)))
        if room_id is None:
            raise InviteRejected('unknown', 'Код не подходит. Проверь буквы и цифры.')
        # All room invite operations lock Room before RoomInvite, avoiding a
        # join/revoke lock-order cycle while serializing max-use enforcement.
        room = await self.session.scalar(select(Room).where(
            Room.id == room_id, Room.kind == 'standalone',
        ).with_for_update())
        invite = await self.session.scalar(select(RoomInvite).where(
            column.in_(digests),
        ).with_for_update())
        current = now or datetime.now(timezone.utc)
        if invite is None or invite.room_id != room_id or room is None:
            raise InviteRejected('unknown', 'Код не подходит. Проверь буквы и цифры.')
        membership = await self.session.scalar(select(RoomMembership).where(
            RoomMembership.room_id == room.id, RoomMembership.account_id == account_id,
        ).execution_options(populate_existing=True))
        if membership is not None and membership.status == 'active':
            # Retry after a lost response stays idempotent even if this was the
            # last use or the owner has since revoked the invitation.
            return {**self.projection(room, membership), 'joined': False}
        if invite.revoked_at is not None:
            raise InviteRejected('revoked', f'Приглашение в «{room.title}» отозвано хозяином.', room.title)
        if invite.expires_at <= current:
            raise InviteRejected('expired', f'Срок приглашения в «{room.title}» истёк.', room.title)
        if invite.uses >= invite.max_uses:
            raise InviteRejected('exhausted', f'Приглашение в «{room.title}» уже использовано '
                                 'максимальное число раз.', room.title)
        require_age_ok(room.world, age_ok)    # an 18+ world: the new player confirms it first (nothing spent, nothing stored)
        await room_limits.charge_membership(self.session, account_id, current)
        if membership is None:
            membership = RoomMembership(
                room_id=room.id, account_id=account_id, role='member', status='active',
            )
            self.session.add(membership)
        else:
            # inactive (left) or removed by the owner: an invitation is the way back in.
            membership.role = 'member'
            membership.status = 'active'
            membership.updated_at = func.greatest(func.clock_timestamp(),
                RoomMembership.updated_at + text("interval '1 microsecond'"))
        invite.uses += 1
        await self.session.flush()
        await self.session.refresh(membership, ['updated_at'])
        return {**self.projection(room, membership), 'joined': True}

    async def set_open(self, *, account_id: UUID, room_id: str, open: object,
                       now: datetime | None = None) -> dict:
        """The owner lists the room in «Открытые столы» or takes it off; closed by default."""
        if type(open) is not bool:
            raise ValueError('Укажи, открыта ли комната.')
        room = await self.session.scalar(select(Room).where(
            Room.id == room_id, Room.kind == 'standalone',
        ).with_for_update())
        member = await self.session.get(RoomMembership, (room_id, account_id))
        if room is None or room.owner_account_id != account_id or member is None \
                or member.role != 'owner' or member.status != 'active':
            raise LookupError('Комната не найдена.')
        current = now or datetime.now(timezone.utc)
        room.is_open = open
        room.open_activity_at = current if open else None
        await self.session.flush()
        return self.projection(room, member)

    async def list_open(self, *, account_id: UUID, limit: int = OPEN_LIST_LIMIT,
                        now: datetime | None = None) -> list[dict]:
        """Public list of open tables: room, host display name, seated count, status; no accounts."""
        current = now or datetime.now(timezone.utc)
        rows = (await self.session.execute(
            select(Room, Game).join(Game, (Game.room_id == Room.id) & (Game.mode == 'mafia')
                                    & Game.is_current.is_(True))
            .where(Room.kind == 'standalone', Room.is_open.is_(True),
                   Room.open_activity_at > current - OPEN_ROOM_IDLE)
            .order_by(Room.open_activity_at.desc(), Room.id).limit(max(1, min(int(limit), OPEN_LIST_LIMIT)))
        )).all()
        mine = set((await self.session.scalars(select(RoomMembership.room_id).where(
            RoomMembership.account_id == account_id, RoomMembership.status == 'active',
            RoomMembership.room_id.in_([room.id for room, _ in rows] or ['']),
        ))).all())
        items = []
        for room, game in rows:
            summary = open_table_summary(game.state, room_id=room.id)
            if summary is None:
                continue
            items.append({
                'room_id': room.id, 'title': room.title, 'host_name': summary['host_name'],
                'seated': summary['seated'], 'waiting': summary['waiting'],
                'needs_from': MIN_PLAYERS, 'capacity': MAX_PLAYERS,
                'status': summary['status'],  # gathering | playing | full
                'world': world_or_default(room.world),
                'world_age': world_age(room.world),
                'joined': room.id in mine,
            })
        return items
