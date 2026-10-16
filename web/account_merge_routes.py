"""Player confirmation of an account merge offered by Telegram login or Mini App linking."""
import json

from fastapi import Request

from storage.mini_app import MiniAppError
from storage.telegram_login import TelegramLogins
from web.mini_auth import InvalidInitData, unique_object, validate_init_data
from web.telegram_login_routes import LOGIN_COOKIE, LOGIN_PATH

MERGE_KEYS = {'main', 'account_id', 'telegram_account_id'}


def install_account_merge(app, ctx):
    """POST {LOGIN_PATH}/merge (proof: bot-approved login cookie) and
    POST /api/account/telegram-link/merge (proof: fresh signed initData)."""
    from application.account_merge_flow import AccountMergeFlow
    flow = AccountMergeFlow(ctx.database, ctx.guest_store, logins=TelegramLogins(ctx.database, clock=ctx.clock),
                            allowed_user_ids=ctx.allowed_user_ids)

    def strings(value):
        if not all(isinstance(value[key], str) for key in MERGE_KEYS):
            raise MiniAppError(400, 'Некорректные параметры')
        return {key: value[key] for key in MERGE_KEYS}

    @app.post(LOGIN_PATH + '/merge')
    async def telegram_login_merge(request: Request):
        secret = request.cookies.get(LOGIN_COOKIE)
        if not secret:
            raise MiniAppError(401, 'Вход через Telegram не начат')
        value = strings(await ctx.account_json(request, MERGE_KEYS, MERGE_KEYS))
        return await flow.confirm(request.cookies.get(ctx.guest_cookie), browser_secret=secret, **value)

    @app.post('/api/account/telegram-link/merge')
    async def telegram_link_merge(request: Request):
        ctx.guest_access()
        if not ctx.settings.bot_token:
            raise MiniAppError(503, 'Вход через Telegram не настроен')
        if request.headers.get('content-type', '').split(';')[0].strip() != 'application/json':
            raise MiniAppError(415, 'Ожидается JSON')
        from web.mini_app import bounded_request_body
        raw = await bounded_request_body(request, max_bytes=20000)
        try:
            value = json.loads(raw, object_pairs_hook=unique_object)
            if not isinstance(value, dict) or set(value) != MERGE_KEYS | {'init_data'}:
                raise ValueError()
        except (ValueError, UnicodeError, RecursionError):
            raise MiniAppError(400, 'Некорректные параметры') from None
        try:
            identity = validate_init_data(value['init_data'], ctx.settings.bot_token, now=ctx.clock())
        except InvalidInitData:
            raise MiniAppError(401, 'Недействительные или просроченные данные Telegram') from None
        return await flow.confirm(request.cookies.get(ctx.guest_cookie), identity=identity,
                                  **strings(value))
