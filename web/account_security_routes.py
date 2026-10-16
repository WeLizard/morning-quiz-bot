"""Account credentials, password change/recovery and the device (session) list."""
from fastapi import Query, Request

from storage.mini_app import MiniAppError
from web.principal import GUEST_COOKIE, MINI_COOKIE, PrincipalError, resolve_principal


def install_account_security(app, ctx):
    """Registers /api/account/credentials, /password and /sessions routes."""
    from application.account_security import AccountSecurityService
    service = AccountSecurityService(ctx.guest_store, ctx.password_store)

    def principal(request, identity, *, lock):
        # The guest channel is used for identity=guest and when only the guest cookie is present.
        if identity == 'guest' or (identity is None and not request.cookies.get(MINI_COOKIE)):
            ctx.guest_access()
        return resolve_principal(request, database=ctx.database, guest_store=ctx.guest_store,
                                 mini_store=ctx.mini_store, lock=lock, identity=identity)

    def cookies(request):
        return request.cookies.get(GUEST_COOKIE), request.cookies.get(MINI_COOKIE)

    def text(value, name):
        if not isinstance(value, str):
            raise MiniAppError(400, 'Некорректные параметры')
        return value

    @app.post('/api/account/credentials')
    async def account_credentials(request: Request, identity: str | None = Query(None)):
        value = await ctx.account_json(request, {'login', 'password'}, {'login', 'password'})
        login, password = service.check_credentials(value['login'], value['password'])
        try:
            # Cheap authentication first: an anonymous caller must not make the server run scrypt.
            async with principal(request, identity, lock=False):
                pass
            digest = await service.hash(password)
            async with principal(request, identity, lock=True) as (session, who):
                return await service.set_credentials(session, who, login, digest)
        except PrincipalError as error:
            raise MiniAppError(error.status, error.message, code=error.code) from None

    @app.post('/api/account/password')
    async def account_password(request: Request, identity: str | None = Query(None)):
        value = await ctx.account_json(request, {'new_password', 'current_password'}, {'new_password'})
        new_password = service.check_credentials('valid_login', value['new_password'])[1]
        current = value.get('current_password')
        if current is not None:
            text(current, 'current_password')
        guest_cookie, mini_cookie = cookies(request)
        try:
            async with principal(request, identity, lock=False):
                pass
            digest = await service.hash(new_password)
            async with principal(request, identity, lock=True) as (session, who):
                return await service.change_password(
                    session, who, guest_cookie=guest_cookie, mini_cookie=mini_cookie,
                    new_digest=digest, current_password=current)
        except PrincipalError as error:
            raise MiniAppError(error.status, error.message, code=error.code) from None

    @app.get('/api/account/sessions')
    async def account_sessions(request: Request, identity: str | None = Query(None)):
        guest_cookie, _ = cookies(request)
        try:
            async with principal(request, identity, lock=False) as (session, who):
                return await service.sessions(session, who, guest_cookie=guest_cookie)
        except PrincipalError as error:
            raise MiniAppError(error.status, error.message, code=error.code) from None

    @app.post('/api/account/sessions/revoke')
    async def account_sessions_revoke(request: Request, identity: str | None = Query(None)):
        value = await ctx.account_json(request, {'id'}, {'id'})
        try:
            async with principal(request, identity, lock=True) as (session, who):
                return await service.revoke(session, who, value['id'])
        except PrincipalError as error:
            raise MiniAppError(error.status, error.message, code=error.code) from None

    @app.post('/api/account/sessions/revoke-others')
    async def account_sessions_revoke_others(request: Request, identity: str | None = Query(None)):
        guest_cookie, mini_cookie = cookies(request)
        try:
            async with principal(request, identity, lock=True) as (session, who):
                return await service.revoke_others(session, who, guest_cookie=guest_cookie,
                                                   mini_cookie=mini_cookie)
        except PrincipalError as error:
            raise MiniAppError(error.status, error.message, code=error.code) from None
