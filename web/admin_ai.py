import asyncio
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from modules.admin_ai import AIUnavailable, configuration, reply


class Message(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    role: Literal['user', 'assistant']
    content: str = Field(min_length=1, max_length=12000)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    provider: Literal['offline', 'anthropic', 'openrouter', 'puter']
    messages: list[Message] = Field(min_length=1, max_length=40)
    model: str = Field(default='', max_length=150, pattern=r'^[a-zA-Z0-9._:/-]*$')
    confirmed_external: StrictBool = False


def make_ai_router():
    router = APIRouter(prefix='/api/admin-ai')
    lock = asyncio.Lock()

    @router.get('/providers')
    async def providers():
        return configuration()

    @router.post('/chat')
    async def chat(data: ChatRequest):
        if lock.locked():
            raise HTTPException(429, 'Дождитесь текущего AI-запроса.')
        async with lock:
            try:
                return await reply(data.provider, [m.model_dump() for m in data.messages], data.model,
                                   confirmed_external=data.confirmed_external)
            except AIUnavailable as exc:
                raise HTTPException(503, str(exc)) from None
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from None
    return router
