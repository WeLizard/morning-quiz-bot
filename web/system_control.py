"""Local administrative controls over persisted state, not host shell access."""
from uuid import UUID

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt

from storage.system_control import SystemControl
from web.admin_actions import respond
from web.admin_actions import ResetRequest
from storage.category_statistics import CategoryStatistics


class MaintenanceRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    enabled: StrictBool
    reason: str = Field(min_length=1, max_length=500)
    expected_revision: StrictInt = Field(ge=0)
    action_id: UUID


def make_system_router():
    router = APIRouter()

    @router.get('/api/chats/{chat_id}/category-reset-preview')
    async def category_preview(request: Request, chat_id: int):
        return await respond(CategoryStatistics(request.app.state.admin_database).preview(chat_id))

    @router.post('/api/chats/{chat_id}/reset-categories')
    async def category_reset(request: Request, chat_id: int, data: ResetRequest):
        return await respond(CategoryStatistics(request.app.state.admin_database).reset_chat(chat_id,
            **{**data.model_dump(), 'action_id': str(data.action_id)}))

    @router.get('/api/control/maintenance')
    async def get_state(request: Request):
        return await SystemControl(request.app.state.admin_database).read()

    @router.put('/api/control/maintenance')
    async def set_state(request: Request, data: MaintenanceRequest):
        return await respond(SystemControl(request.app.state.admin_database).set_maintenance(
            **{**data.model_dump(), 'action_id': str(data.action_id)}))

    return router
