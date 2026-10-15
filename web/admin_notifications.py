"""Authenticated local operator reconciliation; never sends notifications."""
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, field_validator, model_validator
from sqlalchemy import select

from storage.models import NotificationOutbox, NotificationResolution
from storage.notifications import NotificationQueue, NotificationResolutionConflict


class PrivateValidationRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def safe_handler(request):
            try:
                return await handler(request)
            except RequestValidationError as exc:
                # FastAPI's default errors include rejected values and field names.
                raise HTTPException(422, 'Некорректные параметры уведомления.') from exc

        return safe_handler


class ResolutionRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    action_id: UUID
    expected_version: StrictInt = Field(ge=0)
    decision: Literal['confirmed_delivered', 'closed_without_resend']
    reason: StrictStr = Field(min_length=1, max_length=2000)
    verification_method: StrictStr = Field(min_length=1, max_length=200)
    chat_id: StrictInt | None = Field(default=None, ge=-(2**63), le=2**63 - 1)
    message_id: StrictInt | None = Field(default=None, ge=1, le=2**63 - 1)

    @field_validator('reason', 'verification_method')
    @classmethod
    def nonblank(cls, value):
        if not value.strip() or '\x00' in value:
            raise ValueError('Требуется непустой текст.')
        return value

    @model_validator(mode='after')
    def confirmed_evidence(self):
        if self.chat_id == 0:
            raise ValueError('Некорректный chat_id.')
        if self.decision == 'confirmed_delivered' and (self.chat_id is None or self.message_id is None):
            raise ValueError('Требуется идентификатор проверенного сообщения.')
        return self


def _require_session(request: Request):
    if getattr(request.state, 'admin_session', None) is None:
        raise HTTPException(401, 'Требуется вход в админку.')


def _projection():
    row = NotificationOutbox
    return select(row.id, row.game_id, row.chat_id, row.user_id, row.kind,
                  row.status, row.attempts, row.version, row.available_at,
                  row.claimed_at, row.delivered_at, row.resolved_at,
                  row.last_error.is_not(None).label('has_error'))


def _public_row(row):
    result = dict(row)
    # Browser numbers cannot represent every PostgreSQL bigint exactly.
    for key in ('chat_id', 'user_id'):
        if result[key] is not None:
            result[key] = str(result[key])
    return result


def make_notifications_router():
    router = APIRouter(route_class=PrivateValidationRoute, dependencies=[Depends(_require_session)])
    item_path = Annotated[str, Path(min_length=1, max_length=64)]

    @router.get('/api/notifications')
    async def notifications(request: Request,
                            status: Literal['uncertain', 'sending', 'resolved'] = 'uncertain',
                            limit: Annotated[int, Query(ge=1, le=50)] = 25,
                            offset: Annotated[int, Query(ge=0)] = 0):
        async with request.app.state.admin_database.transaction() as session:
            rows = (await session.execute(_projection().where(NotificationOutbox.status == status)
                    .order_by(NotificationOutbox.available_at, NotificationOutbox.id)
                    .limit(limit + 1).offset(offset))).mappings().all()
        return {'items': [_public_row(row) for row in rows[:limit]], 'status': status,
                'limit': limit, 'offset': offset, 'has_more': len(rows) > limit}

    @router.get('/api/notifications/{item_id}')
    async def notification(item_id: item_path, request: Request):
        async with request.app.state.admin_database.transaction() as session:
            row = (await session.execute(_projection().where(NotificationOutbox.id == item_id))).mappings().first()
            if row is None or row['status'] not in {'uncertain', 'sending', 'resolved'}:
                raise HTTPException(404, 'Уведомление не найдено.')
            result = _public_row(row)
            receipt = (await session.execute(select(
                NotificationResolution.action_id, NotificationResolution.operator_id,
                NotificationResolution.decision, NotificationResolution.previous_version,
                NotificationResolution.resulting_version.label('version'),
                NotificationResolution.created_at.label('resolved_at'),
            ).where(NotificationResolution.item_id == item_id))).mappings().first()
            result['resolution'] = dict(receipt) if receipt else None
        return result

    @router.post('/api/notifications/{item_id}/resolve')
    async def resolve(item_id: item_path, data: ResolutionRequest, request: Request):
        evidence = {'verification_method': data.verification_method}
        for name in ('chat_id', 'message_id'):
            value = getattr(data, name)
            if value is not None:
                evidence[name] = value
        try:
            # Do not GET the outbox first: durable receipts replay after deletion.
            return await NotificationQueue(request.app.state.admin_database).resolve(
                item_id=item_id, action_id=str(data.action_id), operator_id='local-admin',
                expected_version=data.expected_version, decision=data.decision,
                reason=data.reason, evidence=evidence,
            )
        except NotificationResolutionConflict as exc:
            raise HTTPException(409, 'Решение конфликтует с текущим состоянием. Загрузите запись заново.') from exc
        except ValueError as exc:
            raise HTTPException(422, 'Некорректное свидетельство проверки уведомления.') from exc

    return router
