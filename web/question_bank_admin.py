"""Authenticated static-bank routes installed only in PostgreSQL admin mode."""
import inspect
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from storage.question_bank import PostgresQuestionBank, BankConflict, BankQuestion, normalized


class CategoryName(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=100)


class ImportQuestions(BaseModel):
    model_config = ConfigDict(extra='forbid')
    questions: list[dict] = Field(min_length=1, max_length=5000)


class ImportBank(BaseModel):
    model_config = ConfigDict(extra='forbid')
    categories: dict[str, list[dict]] = Field(min_length=1, max_length=200)
    expected_versions: dict[str, str | None] = Field(min_length=1, max_length=200)


Version = Annotated[str | None, Query(pattern=r'^[a-f0-9]{64}$')]


def bank(request):
    database = getattr(request.app.state, 'admin_database', None)
    if database is None:
        raise HTTPException(503, 'PostgreSQL question bank is unavailable')
    return PostgresQuestionBank(database)


async def invoke(function, *args, **kwargs):
    try:
        if inspect.iscoroutinefunction(function):
            return await function(*args, **kwargs)
        return await run_in_threadpool(function, *args, **kwargs)
    except BankConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, str(exc)) from exc


def required(version):
    if version is None:
        raise HTTPException(428, 'Передайте expected_version из ответа категории')
    return version


def make_bank_router():
    router = APIRouter(prefix='/api/bank')

    @router.get('/export')
    async def export_bank(request: Request):
        return JSONResponse(await invoke(bank(request).export_all), headers={'Content-Disposition': 'attachment; filename="quiz-bank.json"'})

    @router.post('/import')
    async def import_bank(data: ImportBank, request: Request):
        result = await invoke(bank(request).import_all, data.categories, data.expected_versions)
        return JSONResponse(result, status_code=207 if result['failed'] else 200)

    @router.get('/categories')
    async def categories(request: Request):
        return {'categories': await invoke(bank(request).categories)}

    @router.post('/categories', status_code=201)
    async def create(data: CategoryName, request: Request):
        return await invoke(bank(request).create, data.name)

    @router.get('/categories/{name}')
    async def category(name: str, request: Request):
        result = await invoke(bank(request).read, name)
        items = []
        for index, raw in enumerate(result['questions']):
            try:
                item = normalized(raw)
            except (ValueError, TypeError):
                item = {'invalid': True, 'raw': raw}
            items.append(dict(item, index=index))
        return dict(result, questions=items)

    @router.get('/categories/{name}/export')
    async def export(name: str, request: Request):
        result = await invoke(bank(request).read, name)
        return JSONResponse(result['questions'], headers={'Content-Disposition': 'attachment; filename="questions.json"'})

    @router.get('/categories/{name}/raw')
    async def raw_category(name: str, request: Request):
        raw = await invoke(bank(request).raw, name)
        return Response(raw, media_type='text/plain', headers={'Content-Disposition': 'attachment; filename="original-category.json"'})

    @router.put('/categories/{name}/repair')
    async def repair_category(name: str, data: ImportQuestions, request: Request, expected_version: Version = None):
        return await invoke(bank(request).repair, name, required(expected_version), data.questions)

    @router.delete('/categories/{name}')
    async def delete_category(name: str, request: Request, expected_version: Version = None):
        return await invoke(bank(request).change, name, required(expected_version), remove=True)

    @router.post('/categories/{name}/questions', status_code=201)
    async def add(name: str, question: BankQuestion, request: Request, expected_version: Version = None):
        return await invoke(bank(request).change, name, required(expected_version), question=question.model_dump())

    @router.put('/categories/{name}/questions/{index}')
    async def edit(name: str, index: int, question: BankQuestion, request: Request, expected_version: Version = None):
        return await invoke(bank(request).change, name, required(expected_version), index=index, question=question.model_dump())

    @router.delete('/categories/{name}/questions/{index}')
    async def delete_question(name: str, index: int, request: Request, expected_version: Version = None):
        return await invoke(bank(request).change, name, required(expected_version), index=index, remove=True)

    @router.post('/categories/{name}/import')
    async def import_questions(name: str, data: ImportQuestions, request: Request, expected_version: Version = None):
        return await invoke(bank(request).change, name, required(expected_version), import_values=data.questions)

    return router
