"""Durable bindings between internal game effects and external transports."""

from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from .models import GameDelivery


class DeliveryConflict(RuntimeError):
    pass


class GameDeliveries:
    def __init__(self, session):
        self.session = session

    async def reserve(
        self, *, game_id: str, round_id: str, channel: str, kind: str,
        chat_id: int, metadata: dict | None = None,
    ) -> tuple[bool, GameDelivery]:
        """Reserve before I/O; false means this effect must not be sent again."""
        values = {
            'id': str(uuid4()),
            'game_id': game_id,
            'round_id': round_id,
            'channel': channel,
            'kind': kind,
            'chat_id': chat_id,
            'status': 'sending',
            'metadata_json': metadata or {},
        }
        statement = insert(GameDelivery).values(**values).on_conflict_do_nothing(
            constraint='uq_game_delivery_effect'
        ).returning(GameDelivery.id)
        created_id = await self.session.scalar(statement)
        row = await self.session.scalar(select(GameDelivery).where(
            GameDelivery.game_id == game_id,
            GameDelivery.round_id == round_id,
            GameDelivery.channel == channel,
            GameDelivery.kind == kind,
        ).with_for_update())
        if row is None:
            raise RuntimeError('Не удалось зарезервировать доставку.')
        if created_id is None and row.status == 'pending':
            row.status = 'sending'
            await self.session.flush()
            return True, row
        return created_id is not None, row

    async def acknowledge(
        self, *, delivery_id: str, external_id: str,
        message_id: int | None, metadata: dict | None = None,
    ) -> GameDelivery:
        if not external_id or len(external_id) > 255:
            raise ValueError('Некорректный внешний идентификатор доставки.')
        row = await self.session.scalar(select(GameDelivery).where(
            GameDelivery.id == delivery_id
        ).with_for_update())
        if row is None:
            raise LookupError('Доставка не найдена.')
        if row.status == 'sent':
            if row.external_id != external_id or row.message_id != message_id:
                raise DeliveryConflict('Доставка уже подтверждена другим результатом.')
            return row
        if row.status != 'sending':
            raise DeliveryConflict('Неподтверждённую доставку нельзя переигрывать автоматически.')
        row.external_id = external_id
        row.message_id = message_id
        row.status = 'sent'
        if metadata:
            row.metadata_json = {**(row.metadata_json or {}), **metadata}
        await self.session.flush()
        return row

    async def uncertain(self, *, delivery_id: str, error: str) -> None:
        result = await self.session.execute(update(GameDelivery).where(
            GameDelivery.id == delivery_id,
            GameDelivery.status == 'sending',
        ).values(
            status='uncertain',
            metadata_json={'error': str(error)[:500]},
        ))
        if result.rowcount != 1:
            raise DeliveryConflict('Статус доставки уже изменился.')

    async def retryable(self, *, delivery_id: str) -> None:
        result = await self.session.execute(update(GameDelivery).where(
            GameDelivery.id == delivery_id,
            GameDelivery.status == 'sending',
        ).values(status='pending'))
        if result.rowcount != 1:
            raise DeliveryConflict('Статус доставки уже изменился.')

    async def skipped(self, *, delivery_id: str, reason: str) -> None:
        result = await self.session.execute(update(GameDelivery).where(
            GameDelivery.id == delivery_id,
            GameDelivery.status == 'sending',
        ).values(status='skipped', metadata_json={'reason': reason[:200]}))
        if result.rowcount != 1:
            raise DeliveryConflict('Статус доставки уже изменился.')

    async def resolve(self, *, channel: str, external_id: str) -> GameDelivery | None:
        return await self.session.scalar(select(GameDelivery).where(
            GameDelivery.channel == channel,
            GameDelivery.external_id == external_id,
            GameDelivery.status == 'sent',
        ))
