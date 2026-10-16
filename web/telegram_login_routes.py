"""Browser login with Telegram: start -> bot approval -> completion in the same browser."""
from fastapi import Request
from fastapi.responses import JSONResponse

from storage.mini_app import MiniAppError
from storage.telegram_login import TTL_SECONDS, TelegramLogins
from web.client_hint import client_hint

LOGIN_COOKIE = 'mqb_tglogin'
LOGIN_PATH = '/api/account/telegram-login'


def install_telegram_login(app, ctx):
    """Registers /api/account/telegram-login/* routes. ``ctx`` is built in web.mini_app.create_app."""
    from application.telegram_login import TelegramLoginService
    logins = TelegramLogins(ctx.database, clock=ctx.clock)
    service = TelegramLoginService(ctx.database, ctx.guest_store, logins,
                                   allowed_user_ids=ctx.allowed_user_ids)

    def browser_secret(request):
        value = request.cookies.get(LOGIN_COOKIE)
        if not value:
            raise MiniAppError(401, 'Вход через Telegram не начат')
        return value

    @app.post(LOGIN_PATH + '/start')
    async def telegram_login_start(request: Request):
        username = ctx.settings.bot_username
        if not username:
            raise MiniAppError(503, 'Вход через Telegram не настроен')
        hint = client_hint(request.headers.get('user-agent'))
        _request_id, start_token, secret, expires = await logins.start(hint)
        response = JSONResponse({
            'link': f'https://t.me/{username}?start=login_{start_token}',
            'expires_at': expires.isoformat()})
        response.set_cookie(LOGIN_COOKIE, secret, max_age=TTL_SECONDS, httponly=True,
                            secure=ctx.guest_cookie_secure, samesite='strict', path=LOGIN_PATH)
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.get(LOGIN_PATH + '/status')
    async def telegram_login_status(request: Request):
        result = await logins.status(browser_secret(request))
        return JSONResponse(result, headers={'Cache-Control': 'no-store'})

    @app.post(LOGIN_PATH + '/complete')
    async def telegram_login_complete(request: Request):
        secret = browser_secret(request)
        if request.headers.get('content-type', '').split(';')[0].strip() == 'application/json':
            value = await ctx.account_json(request, {'mode'}, set())
        else:
            raise MiniAppError(415, 'Ожидается JSON')
        mode = value.get('mode', 'auto')
        if mode not in ('auto', 'switch', 'link'):
            raise MiniAppError(400, 'Некорректные параметры')
        payload, raw = await service.complete(
            secret, request.cookies.get(ctx.guest_cookie), mode=mode,
            user_agent=client_hint(request.headers.get('user-agent')))
        response = ctx.guest_response(payload, raw)
        response.headers['Cache-Control'] = 'no-store'
        return response
