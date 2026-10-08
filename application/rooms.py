"""Account-owned standalone rooms, invitations, and privacy-scoped projections."""

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import re
import secrets
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from storage.models import Room, RoomInvite, RoomMembership


MIN_INVITE_TTL_SECONDS = 300
MAX_INVITE_TTL_SECONDS = 30 * 24 * 60 * 60
MAX_INVITE_USES = 100


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
    def projection(room: Room, membership: RoomMembership) -> dict:
        return {
            'id': room.id,
            'kind': room.kind,
            'title': room.title,
            'role': membership.role,
            'created_at': room.created_at.isoformat() if room.created_at else None,
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
        row = RoomInvite(
            id=str(uuid4()), room_id=room_id, created_by_account_id=account_id,
            token_hash=sha256(token.encode('ascii')).hexdigest(),
            expires_at=current + timedelta(seconds=expires_in_seconds),
            max_uses=max_uses, uses=0,
        )
        self.session.add(row)
        await self.session.flush()
        # The bearer secret is returned only once; only its hash is persisted.
        return {
            'id': row.id, 'room_id': room_id, 'room_title': room.title,
            'invite_code': token, 'expires_at': row.expires_at.isoformat(),
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
        now: datetime | None = None,
    ) -> dict:
        if not isinstance(invite_code, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', invite_code):
            raise LookupError('Приглашение недействительно или срок его действия истёк.')
        digest = sha256(invite_code.encode('ascii')).hexdigest()
        room_id = await self.session.scalar(select(RoomInvite.room_id).where(
            RoomInvite.token_hash == digest,
        ))
        if room_id is None:
            raise LookupError('Приглашение недействительно или срок его действия истёк.')
        # All room invite operations lock Room before RoomInvite, avoiding a
        # join/revoke lock-order cycle while serializing max-use enforcement.
        room = await self.session.scalar(select(Room).where(
            Room.id == room_id, Room.kind == 'standalone',
        ).with_for_update())
        invite = await self.session.scalar(select(RoomInvite).where(
            RoomInvite.token_hash == digest,
        ).with_for_update())
        current = now or datetime.now(timezone.utc)
        if invite is None or invite.room_id != room_id or room is None:
            raise LookupError('Приглашение недействительно или срок его действия истёк.')
        membership = await self.session.get(RoomMembership, (room.id, account_id))
        if membership is not None and membership.status == 'active':
            # Retry after a lost response stays idempotent even if this was the
            # last use or the owner has since revoked the invitation.
            return {**self.projection(room, membership), 'joined': False}
        if (invite.revoked_at is not None or invite.expires_at <= current
                or invite.uses >= invite.max_uses):
            raise LookupError('Приглашение недействительно или срок его действия истёк.')
        if membership is None:
            membership = RoomMembership(
                room_id=room.id, account_id=account_id, role='member', status='active',
            )
            self.session.add(membership)
        else:
            membership.role = 'member'
            membership.status = 'active'
        invite.uses += 1
        await self.session.flush()
        return {**self.projection(room, membership), 'joined': True}
