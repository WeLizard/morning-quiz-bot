"""Closed administrative profiles/exports and optimistic chat title updates."""
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Path, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from storage.admin_profiles import AdminProfiles
from storage.settings import SettingsConflict, SettingsService


class TitlePatch(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=255)

    @field_validator('title')
    @classmethod
    def no_nul(cls, value):
        if '\x00' in value:
            raise ValueError('Название содержит недопустимый символ.')
        return value


def make_profiles_router():
    router = APIRouter()

    @router.get('/api/{scope}/{entity_id}/profile')
    async def profile(scope: Literal['users', 'chats'], entity_id: Annotated[int, Path(ge=-(2**63), le=2**63-1)], request: Request,
                      members_offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
                      history_before: Annotated[str | None, Query(max_length=2048)] = None,
                      download: bool = False):
        try:
            data = await AdminProfiles(request.app.state.admin_database).read(scope, entity_id,
                members_offset=members_offset, history_before=history_before)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        headers = {'Cache-Control': 'no-store'}
        if download:
            headers['Content-Disposition'] = f'attachment; filename="{scope}-{entity_id}-snapshot.json"'
        return JSONResponse(data, headers=headers)

    @router.put('/api/chats/{chat_id}/title')
    async def rename_chat(chat_id: Annotated[int, Path(ge=-(2**63), le=2**63-1)], patch: TitlePatch, request: Request, response: Response,
                          expected_revision: Annotated[int | None, Query(ge=0)] = None):
        if expected_revision is None:
            raise HTTPException(428, 'Передайте актуальную версию настроек чата.')
        try:
            snapshot = await SettingsService(request.app.state.admin_database).rename_chat(
                chat_id, patch.title, expected_revision=expected_revision)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except SettingsConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        response.headers['X-Settings-Revision'] = str(snapshot.revision)
        return {'title': snapshot.values['title'], 'revision': snapshot.revision}

    return router
