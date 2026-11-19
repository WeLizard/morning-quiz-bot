"""Unmounted Night AI game HTTP adapter; identity and SQL session stay caller-owned.

register_night_case_ai_routes adds explicit §7 endpoints. Disabled by default;
factories are supplied only after the separate runtime integration review.
"""
from __future__ import annotations

import inspect
import json
from uuid import UUID

from fastapi import HTTPException, Query, Request
from fastapi.responses import JSONResponse

from application.night_case import NightCaseError
from application.night_case_ai import NightAIControlError
from web.night_case_routes import night_viewer_matches


MAX_BODY = 32768
_PUBLIC = frozenset({'auth_required','forbidden','not_found','idempotency_conflict','stale_epoch',
    'stale_revision','request_stale','profile_disabled','game_not_running','game_not_lobby','invalid_config',
    'unsupported_preset','unsupported_model_contract','rate_limited','provider_unavailable',
    'account_unavailable','request_limit','request_cooldown','credential_unavailable',
    'ai_unavailable','starter_unproven','profile_changed'})


def _unique(pairs):
    result={}
    for key,value in pairs:
        if key in result: raise ValueError('duplicate')
        result[key]=value
    return result


def _invalid():
    raise NightAIControlError('invalid_config',422)


def _uuid(value):
    try:
        if type(value) is not str or str(UUID(value))!=value: _invalid()
        return UUID(value)
    except (ValueError,TypeError,AttributeError):
        _invalid()


def _integer(value, *, zero=True):
    if type(value) is not int or not (0 if zero else 1) <= value <= 2147483647: _invalid()
    return value


def _text(value, *, max_bytes=96):
    try:
        size=len(value.encode('utf-8')) if type(value) is str else 0
    except UnicodeError:
        _invalid()
    if not 1 <= size <= max_bytes:
        _invalid()
    return value


async def bounded_json(request: Request, *, required: set[str], optional=frozenset(), read_body=None) -> dict:
    """Closed UTF-8 JSON, duplicate-field rejection, no Pydantic input echo."""
    if request.headers.get('content-type','').split(';',1)[0].strip().lower()!='application/json':
        raise HTTPException(415,'JSON required')
    if read_body is None:
        length=request.headers.get('content-length')
        try:
            if length is not None and (not length.isdecimal() or int(length)>MAX_BODY): _invalid()
        except ValueError:
            _invalid()
        body=bytearray()
        async for chunk in request.stream():
            if len(body)+len(chunk)>MAX_BODY: _invalid()
            body.extend(chunk)
        raw=bytes(body)
    else:
        raw=await read_body(request,max_bytes=MAX_BODY)
        if type(raw) is not bytes or len(raw)>MAX_BODY: _invalid()
    try:
        value=json.loads(raw.decode('utf-8'),object_pairs_hook=_unique,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite')))
        if type(value) is not dict or not required <= set(value) or set(value)-required-set(optional):
            _invalid()
        return value
    except (ValueError,UnicodeError,RecursionError):
        _invalid()


def _error(exc):
    known=exc.code in _PUBLIC
    code=exc.code if known else 'ai_unavailable'
    status=exc.status if known and 400 <= exc.status <= 503 else 503
    return JSONResponse({'code':code,'request_id':None,
        'retry_after_seconds':exc.retry_after_seconds if isinstance(exc,NightAIControlError) else None},
        status_code=status,headers={'Cache-Control':'private, no-store'})


def _reply(value):
    return JSONResponse(value,headers={'Cache-Control':'private, no-store','Vary':'Cookie, Authorization'})


def register_night_case_ai_routes(app, *, principal, identity_for, read_body,
                                  service_factory=None, views_factory=None, enabled=False):
    """Game API: presets/status/byok/request/off. Requires real principal context.

    Caller injects ``service_factory(session)`` and ``views_factory(session)``;
    both must use that same SQL session. No service or secret is constructed here.
    """
    def write_boundary(request,identity):
        if not enabled: raise HTTPException(404,'Unavailable')
        selected=identity_for(request,identity)
        csrf='x-mini-csrf' if selected=='telegram' else 'x-guest-csrf'
        origin=f'{request.url.scheme}://{request.url.netloc}'
        if (request.headers.get('origin')!=origin or request.headers.get(csrf)!='1'
                or request.headers.get('sec-fetch-site')=='cross-site'):
            raise HTTPException(403,'Forbidden')
        return selected

    async def run(request,identity,*,write,operation,pin=True):
        if not enabled: raise HTTPException(404,'Unavailable')
        if (write and service_factory is None) or (not write and views_factory is None):
            raise HTTPException(503,'Unavailable')
        selected=write_boundary(request,identity) if write else identity_for(request,identity)
        try:
            async with principal(request,selected,write=write) as (session,who):
                account_id=UUID(str(who.account_id))
                if pin and not night_viewer_matches(request.headers.get('x-night-expected-viewer'),
                                                    account_id,required=True):
                    raise NightAIControlError('profile_changed',409)
                factory=service_factory if write else views_factory
                service=factory(session)
                if inspect.isawaitable(service): service=await service
                return _reply(await operation(service,account_id))
        except NightAIControlError as exc:
            return _error(exc)
        except NightCaseError as exc:
            return _error(exc)

    @app.get('/api/night-case/ai/presets')
    async def presets(request: Request, identity: str | None = Query(None)):
        return await run(request,identity,write=False,pin=False,
                         operation=lambda view,actor:view.list_presets(actor))

    @app.get('/api/night-case/games/{game_id}/ai')
    async def status(request: Request,game_id: str,identity: str | None = Query(None)):
        return await run(request,identity,write=False,
                         operation=lambda view,actor:view.get_ai_status(actor,game_id))

    @app.post('/api/night-case/games/{game_id}/ai/byok')
    async def byok(request: Request,game_id: str,identity: str | None = Query(None)):
        write_boundary(request,identity)
        try:
            body=await bounded_json(request,required={'expected_epoch','settings','secret','client_request_id'},read_body=read_body)
            epoch=_integer(body['expected_epoch'])
            request_id=_text(body['client_request_id'])
            if type(body['settings']) is not dict or type(body['secret']) is not str: _invalid()
            try: secret=body['secret'].encode('utf-8')
            except UnicodeError: _invalid()
            if not 1<=len(secret)<=8192: _invalid()
        except NightAIControlError as exc:
            return _error(exc)
        return await run(request,identity,write=True,operation=lambda service,actor:
            service.stage_or_activate_byok(account_id=actor,game_id=game_id,expected_epoch=epoch,
                settings=body['settings'],secret=secret,client_request_id=request_id))

    @app.post('/api/night-case/games/{game_id}/ai/request')
    async def request_admin(request: Request,game_id: str,identity: str | None = Query(None)):
        write_boundary(request,identity)
        try:
            body=await bounded_json(request,required={'expected_epoch','client_request_id'},read_body=read_body)
            epoch=_integer(body['expected_epoch']);request_id=_text(body['client_request_id'])
        except NightAIControlError as exc:
            return _error(exc)
        return await run(request,identity,write=True,operation=lambda service,actor:
            service.request_admin(account_id=actor,game_id=game_id,expected_epoch=epoch,
                client_request_id=request_id))

    @app.post('/api/night-case/games/{game_id}/ai/off')
    async def authored(request: Request,game_id: str,identity: str | None = Query(None)):
        write_boundary(request,identity)
        try:
            body=await bounded_json(request,required={'expected_epoch','client_request_id'},read_body=read_body)
            epoch=_integer(body['expected_epoch']);request_id=_text(body['client_request_id'])
        except NightAIControlError as exc:
            return _error(exc)
        return await run(request,identity,write=True,operation=lambda service,actor:
            service.use_authored(account_id=actor,game_id=game_id,expected_epoch=epoch,
                client_request_id=request_id))
