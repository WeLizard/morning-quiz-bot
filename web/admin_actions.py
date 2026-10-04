"""Authenticated local moderation and explicit, versioned reset contracts."""
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Path, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt

from storage.admin_actions import AdminActions, AdminConflict

Scope = Literal['users', 'chats']
EntityId = Annotated[int, Path(ge=-(2**63), le=2**63-1)]


class BlockRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    blocked: StrictBool
    reason: str = Field(min_length=1, max_length=500)
    expected_revision: StrictInt = Field(ge=0)
    action_id: UUID


class ResetRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_version: str = Field(pattern=r'^[a-f0-9]{64}$')
    confirmation: str = Field(max_length=20)
    action_id: UUID


class ArchiveRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    archived: StrictBool
    expected_revision: StrictInt = Field(ge=0)
    confirmation: str = Field(max_length=20)
    action_id: UUID


async def respond(awaitable):
    try:
        return JSONResponse(await awaitable, headers={'Cache-Control': 'no-store'})
    except AdminConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


def make_actions_router():
    router = APIRouter()

    @router.post('/api/{scope}/{entity_id}/archive')
    async def archive(scope: Scope, entity_id: EntityId, data: ArchiveRequest, request: Request):
        return await respond(AdminActions(request.app.state.admin_database).archive(scope, entity_id,
            **{**data.model_dump(), 'action_id': str(data.action_id)}))

    @router.get('/api/{scope}/{entity_id}/moderation')
    async def state(scope: Scope, entity_id: EntityId, request: Request):
        return await respond(AdminActions(request.app.state.admin_database).state(scope, entity_id))

    @router.put('/api/{scope}/{entity_id}/moderation')
    async def block(scope: Scope, entity_id: EntityId, data: BlockRequest, request: Request):
        return await respond(AdminActions(request.app.state.admin_database).block(scope, entity_id,
            **{**data.model_dump(), 'action_id': str(data.action_id)}))

    @router.get('/api/{scope}/{entity_id}/reset-preview')
    async def preview(scope: Scope, entity_id: EntityId, request: Request):
        return await respond(AdminActions(request.app.state.admin_database).preview_reset(scope, entity_id))

    @router.post('/api/{scope}/{entity_id}/reset-progress')
    async def reset(scope: Scope, entity_id: EntityId, data: ResetRequest, request: Request):
        return await respond(AdminActions(request.app.state.admin_database).reset(scope, entity_id,
            **{**data.model_dump(), 'action_id': str(data.action_id)}))

    @router.get('/api/admin-actions/{action_id}')
    async def audit(action_id: UUID, request: Request):
        response = await respond(AdminActions(request.app.state.admin_database).read_receipt(str(action_id)))
        response.headers['Content-Disposition'] = f'attachment; filename="admin-action-{action_id}.json"'
        return response

    return router
