from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from storage.broadcasts import Broadcasts
from web.admin_actions import respond


class Preview(BaseModel):
    model_config = ConfigDict(extra='forbid')
    draft_id: UUID
    chat_ids: list[Annotated[StrictInt, Field(ge=-(2**63), le=2**63-1)]] = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=4000)


class Confirm(BaseModel):
    model_config = ConfigDict(extra='forbid')
    confirmation: str = Field(max_length=30)


def make_broadcast_router():
    router = APIRouter(prefix='/api/dev-broadcasts')

    @router.get('')
    async def history(request: Request):
        return {'mode': 'offline', 'items': await Broadcasts(request.app.state.admin_database).history()}

    @router.post('/preview')
    async def preview(request: Request, data: Preview):
        return await respond(Broadcasts(request.app.state.admin_database).preview(
            draft_id=str(data.draft_id), chat_ids=data.chat_ids, message=data.message))

    @router.post('/{draft_id}/simulate')
    async def simulate(request: Request, draft_id: UUID, data: Confirm):
        return await respond(Broadcasts(request.app.state.admin_database).simulate(str(draft_id), confirmation=data.confirmation))

    return router
