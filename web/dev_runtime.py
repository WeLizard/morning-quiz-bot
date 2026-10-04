from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from modules.dev_runtime import DevRuntime
from web.admin_actions import respond


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid')
    message: str | None = Field(default=None, max_length=4000)
    callback: str | None = Field(default=None, max_length=64)
    message_id: StrictInt | None = None
    poll_id: str | None = Field(default=None, max_length=100)
    option: StrictInt | None = Field(default=None, ge=0, le=20)

    @model_validator(mode='after')
    def one_action(self):
        if sum(value is not None for value in (self.message, self.callback, self.poll_id)) != 1:
            raise ValueError('Передайте ровно одно действие')
        return self


def runtime(request):
    if not getattr(request.app.state, 'dev_runtime', None):
        request.app.state.dev_runtime = DevRuntime(request.app.state.admin_database)
    return request.app.state.dev_runtime


def make_dev_runtime_router():
    router = APIRouter(prefix='/api/dev-runtime')

    @router.get('')
    async def status(request: Request):
        return runtime(request).status()

    @router.post('/{action}')
    async def control(request: Request, action: Literal['start', 'stop', 'restart']):
        instance = runtime(request)
        if action in {'stop', 'restart'}:
            await instance.stop()
        return await respond(instance.start()) if action != 'stop' else instance.status()

    @router.post('/input/update')
    async def update(request: Request, data: Input):
        return await respond(runtime(request).input(**data.model_dump()))

    return router
