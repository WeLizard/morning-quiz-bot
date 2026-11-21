"""Night AI admin router (mounted by web.postgres_admin) with existing session and CSRF authority."""
from __future__ import annotations

import hmac
import inspect
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request

from application.night_case_ai import AdminPrincipal, NightAIControlError
from web.admin_auth import plain_http_allowed
from web.night_case_ai_routes import (_error, _integer, _invalid, _reply,
                                      _text, _uuid, bounded_json)


def _pagination(request):
    params=request.query_params
    if len(params.getlist('limit'))>1 or len(params.getlist('offset'))>1:
        _invalid()
    try:
        raw_limit,raw_offset=params.get('limit','50'),params.get('offset','0')
        if not raw_limit.isdecimal() or not raw_offset.isdecimal(): _invalid()
        limit=int(raw_limit);offset=int(raw_offset)
    except ValueError:
        _invalid()
    if not 1<=limit<=100 or not 0<=offset<=10000: _invalid()
    return limit,offset


def make_night_case_ai_admin_router(*, service_factory=None, views_factory=None,
                                    deployment_id: str, enabled=False, catalog=None) -> APIRouter:
    """Admin §7 read/write routes. Mount only behind existing AdminAuthMiddleware.

    Uses ``request.app.state.admin_database.transaction()`` and verifies the
    same live admin session before opening SQL and again before commit. The
    trusted deployment identity is constructor-only, never a request field.
    """
    principal=AdminPrincipal(deployment_id)
    router=APIRouter()

    def authenticated(request, *, write, require_enabled=True):
        if require_enabled and not enabled: raise HTTPException(404,'Unavailable')
        auth=getattr(request.app.state,'admin_auth',None)
        session=getattr(request.state,'admin_session',None)
        if auth is None or session is None or not getattr(auth,'configured',False):
            raise HTTPException(401,'Authentication required')
        # Same rule as AdminAuthMiddleware, kept here in case the router is mounted without it.
        if request.url.scheme!='https' and not plain_http_allowed(request):
            raise HTTPException(403,'Forbidden')
        if auth.get_session(request) is not session:
            raise HTTPException(401,'Authentication required')
        if write:
            origin=f'{request.url.scheme}://{request.url.netloc}'
            csrf=request.headers.get('x-csrf-token','')
            if (request.headers.get('origin')!=origin or
                    request.headers.get('sec-fetch-site')=='cross-site' or
                    not hmac.compare_digest(csrf.encode(),session.csrf.encode())):
                raise HTTPException(403,'Forbidden')
        return auth,session

    async def run(request, *, write, operation):
        auth,session=authenticated(request,write=write)
        factory=service_factory if write else views_factory
        if factory is None: raise HTTPException(503,'Unavailable')
        database=getattr(request.app.state,'admin_database',None)
        if database is None: raise HTTPException(503,'Unavailable')
        try:
            async with database.transaction() as sql:
                service=factory(sql)
                if inspect.isawaitable(service): service=await service
                result=await operation(service,principal)
                if auth.get_session(request) is not session:
                    raise HTTPException(401,'Authentication required')
            return _reply(result)
        except NightAIControlError as exc:
            return _error(exc)

    async def body(request,required,optional=frozenset()):
        authenticated(request,write=True)
        return await bounded_json(request,required=required,optional=optional)

    @router.get('/api/admin/night-case/ai/catalog')
    async def catalog_view(request: Request):
        # The only route answering while the narrator is off: the admin screen says why.
        authenticated(request,write=False,require_enabled=False)
        if not enabled or catalog is None:
            return _reply({'enabled':False})
        return _reply({'enabled':True,**catalog()})

    @router.get('/api/admin/night-case/ai/profiles')
    async def profiles(request: Request):
        authenticated(request,write=False)
        try: limit,offset=_pagination(request)
        except NightAIControlError as exc: return _error(exc)
        return await run(request,write=False,operation=lambda view,operator:
            view.list_admin_profiles(operator,limit=limit,offset=offset))

    @router.get('/api/admin/night-case/ai/profiles/{profile_id}/revisions')
    async def revisions(request: Request,profile_id: str):
        authenticated(request,write=False)
        try: ident=_uuid(profile_id);limit,offset=_pagination(request)
        except NightAIControlError as exc: return _error(exc)
        return await run(request,write=False,operation=lambda view,operator:
            view.list_admin_profile_revisions(operator,ident,limit=limit,offset=offset))

    @router.get('/api/admin/night-case/ai/profiles/{profile_id}/revisions/{revision}')
    async def revision(request: Request,profile_id: str,revision: str):
        authenticated(request,write=False)
        try:
            if not revision.isdecimal(): _invalid()
            ident=_uuid(profile_id);number=_integer(int(revision),zero=False)
        except (NightAIControlError,ValueError) as exc: return _error(exc if isinstance(exc,NightAIControlError) else NightAIControlError('invalid_config',422))
        return await run(request,write=False,operation=lambda view,operator:
            view.get_admin_profile_revision(operator,ident,number))

    async def save(request,profile_id):
        authenticated(request,write=True)
        try:
            ident=_uuid(profile_id) if profile_id is not None else None
            value=await body(request,{'expected_revision','label','settings','client_request_id'}, {'secret'})
            expected=_integer(value['expected_revision'])
            label=_text(value['label'],max_bytes=80)
            request_id=_text(value['client_request_id'])
            if type(value['settings']) is not dict: _invalid()
            secret=None
            if 'secret' in value:
                if type(value['secret']) is not str: _invalid()
                try: secret=value['secret'].encode('utf-8')
                except UnicodeError: _invalid()
                if not 1<=len(secret)<=8192: _invalid()
        except NightAIControlError as exc: return _error(exc)
        return await run(request,write=True,operation=lambda service,operator:
            service.save_profile_revision(operator=operator,profile_id=ident,expected_revision=expected,
                label=label,settings=value['settings'],secret=secret,client_request_id=request_id))

    @router.post('/api/admin/night-case/ai/profiles')
    async def create_profile(request: Request): return await save(request,None)

    @router.post('/api/admin/night-case/ai/profiles/{profile_id}/revisions')
    async def update_profile(request: Request,profile_id: str): return await save(request,profile_id)

    @router.post('/api/admin/night-case/ai/profiles/{profile_id}/enabled')
    async def enabled_profile(request: Request,profile_id: str):
        authenticated(request,write=True)
        try:
            ident=_uuid(profile_id);value=await body(request,{'enabled','client_request_id'})
            if type(value['enabled']) is not bool: _invalid()
            request_id=_text(value['client_request_id'])
        except NightAIControlError as exc: return _error(exc)
        return await run(request,write=True,operation=lambda service,operator:
            service.set_profile_enabled(operator=operator,profile_id=ident,enabled=value['enabled'],
                client_request_id=request_id))

    @router.post('/api/admin/night-case/ai/profiles/default')
    async def default_profile(request: Request):
        authenticated(request,write=True)
        try:
            value=await body(request,{'profile_id','client_request_id'})
            ident=_uuid(value['profile_id']) if value['profile_id'] is not None else None
            request_id=_text(value['client_request_id'])
        except NightAIControlError as exc: return _error(exc)
        return await run(request,write=True,operation=lambda service,operator:
            service.set_default_profile(operator=operator,profile_id=ident,client_request_id=request_id))

    @router.get('/api/admin/night-case/ai/requests')
    async def requests(request: Request):
        authenticated(request,write=False)
        try: limit,offset=_pagination(request)
        except NightAIControlError as exc: return _error(exc)
        return await run(request,write=False,operation=lambda view,operator:
            view.list_admin_requests(operator,limit=limit,offset=offset))

    @router.post('/api/admin/night-case/ai/requests/{request_id}/decision')
    async def decision(request: Request,request_id: str):
        authenticated(request,write=True)
        try:
            ident=_uuid(request_id)
            value=await body(request,{'decision','profile_id','profile_revision','caps','client_request_id'})
            if type(value['decision']) is not str or value['decision'] not in {'approve','deny'}: _invalid()
            profile=_uuid(value['profile_id']) if value['profile_id'] is not None else None
            revision=_integer(value['profile_revision'],zero=False) if value['profile_revision'] is not None else None
            if value['caps'] is not None and type(value['caps']) is not dict: _invalid()
            request_key=_text(value['client_request_id'])
        except NightAIControlError as exc: return _error(exc)
        return await run(request,write=True,operation=lambda service,operator:
            service.decide_request(operator=operator,request_id=ident,decision=value['decision'],
                profile_id=profile,profile_revision=revision,caps=value['caps'],client_request_id=request_key))

    @router.get('/api/admin/night-case/ai/bindings')
    async def bindings(request: Request):
        authenticated(request,write=False)
        try: limit,offset=_pagination(request)
        except NightAIControlError as exc: return _error(exc)
        return await run(request,write=False,operation=lambda view,operator:
            view.list_admin_bindings(operator,limit=limit,offset=offset))

    @router.post('/api/admin/night-case/ai/bindings/{binding_id}/revoke')
    async def revoke(request: Request,binding_id: str):
        authenticated(request,write=True)
        try:
            ident=_uuid(binding_id);value=await body(request,{'client_request_id'})
            request_id=_text(value['client_request_id'])
        except NightAIControlError as exc: return _error(exc)
        return await run(request,write=True,operation=lambda service,operator:
            service.revoke_binding(operator=operator,binding_id=ident,client_request_id=request_id))

    @router.post('/api/admin/night-case/ai/bindings/{binding_id}/replace')
    async def replace(request: Request,binding_id: str):
        authenticated(request,write=True)
        try:
            ident=_uuid(binding_id)
            value=await body(request,{'expected_epoch','profile_id','profile_revision','caps','client_request_id'})
            epoch=_integer(value['expected_epoch']);profile=_uuid(value['profile_id'])
            revision=_integer(value['profile_revision'],zero=False)
            if value['caps'] is not None and type(value['caps']) is not dict: _invalid()
            request_id=_text(value['client_request_id'])
        except NightAIControlError as exc: return _error(exc)
        return await run(request,write=True,operation=lambda service,operator:
            service.rebind_admin(operator=operator,binding_id=ident,expected_epoch=epoch,
                profile_id=profile,profile_revision=revision,caps=value['caps'],client_request_id=request_id))

    return router
