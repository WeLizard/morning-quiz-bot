"""HTTP adapter. The supplied context owns authentication AND the transaction."""
import json
from pathlib import Path
from collections import defaultdict, deque
import time
from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse
from .domain import FarmError, need

STATIC=Path(__file__).with_name('static')
API='/api/farm/v1'
LOCAL_LIMITS={False:600,True:300}  # per IP per minute: reads / writes (one farm action = one write + one read)
ASSETS={'village.svg','app.js','scene.js','style.css','icons.svg','farm-card.svg','invite.js','scene_expansion.js','scene_buildings.js','scene_map.js','tractor_game.js','trip_game.js','farm_runs.js','address.js','dasha-game.js','dasha-game.css','dasha-scene.svg','oleg-game.js','oleg-game.css','festivals.js','festivals.css','village-fest-posidelki.svg','village-merchant.svg','merchant.js','merchant.css'}
CSP="default-src 'none'; script-src 'self' https://telegram.org; style-src 'self'; img-src 'self' data:; connect-src 'self'; media-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors https://web.telegram.org https://*.telegram.org"


def unique(pairs):
    value={}
    for k,v in pairs:
        if k in value:raise ValueError('duplicate key')
        value[k]=v
    return value


async def body(request, maximum=8192):
    need(request.headers.get('content-type','').split(';')[0]=='application/json','json_required','Ожидается JSON.',415)
    raw=bytearray()
    async for chunk in request.stream():
        need(len(raw)+len(chunk)<=maximum,'too_large','Запрос слишком большой.',413)
        raw.extend(chunk)
    try:
        value=json.loads(raw,object_pairs_hook=unique)
        need(isinstance(value,dict),'invalid_body','Нужен объект JSON.',422)
        return value
    except (ValueError,UnicodeError,RecursionError):raise FarmError('invalid_json','Не удалось прочитать запрос.',422)


def create_router(context, *, demo=False, origin="", bot_username="", mini_app_short_name="play", prepare_share=None):
    """prepare_share(telegram_user_id, invitation) -> prepared message id or None (Telegram shareMessage)."""
    router=APIRouter()
    @router.get('/app/farm')
    async def index():return FileResponse(STATIC/'index.html',headers={'Content-Security-Policy':CSP,'Cache-Control':'no-store'})
    @router.get('/app/farm/assets/{asset}')
    async def asset(asset:str):
        need(asset in ASSETS,'not_found','Файл не найден.',404)
        return FileResponse(STATIC/asset)
    @router.get(API+'/config')
    async def config():return dict(demo=demo,version='0.2.0',home='/app',server_owned=True,bot_username=bot_username)
    @router.post(API+'/start')
    async def start(request:Request):
        invite=None
        if request.headers.get('content-length','0') not in ('0',''):
            value=await body(request,512)
            need(set(value)<={'invite'} and (value.get('invite') is None or isinstance(value['invite'],str) and len(value['invite'])<=64),
                 'invalid_body','Неверные поля запроса.',422)
            invite=value.get('invite')
        async with context(request) as service:
            result=await service.open(invite)
            result['identity']=service.p.authentication
        return result
    @router.get(API+'/me')
    async def me(request:Request):
        async with context(request) as service:result=await service.view()
        return result
    @router.get(API+'/farms/{farm_id}')
    async def view(farm_id:str,request:Request):
        async with context(request) as service:result=await service.view(farm_id)
        return result
    @router.get(API+'/neighbors')
    async def neighbors(request:Request):
        async with context(request) as service:result=await service.neighbors()
        return result
    @router.get(API+'/invite')
    async def invite(request:Request):
        """Read-only legacy code and reward progress; viewing the screen creates no token."""
        from .sharing import safe_public_origin
        async with context(request) as service:
            farm=await service.me()
            return dict(code=farm['id'],farm_name=farm['name'],rewards=await service._invites(farm),
                        link=await service.share_link_status(),
                        local_only=not bool(safe_public_origin(origin) or bot_username))
    @router.post(API+'/invite/share')
    async def share_invite(request:Request):
        from .sharing import invite_info
        empty=(request.headers.get('content-length','0') in ('0','') and not request.headers.get('content-type'))
        value={} if empty else await body(request,512)
        need(set(value)<={'recipient','telegram','rotate'} and (value.get('recipient') is None or isinstance(value['recipient'],str))
             and isinstance(value.get('telegram',False),bool) and isinstance(value.get('rotate',False),bool),
             'invalid_body','Неверные поля запроса.',422)
        recipient=value.get('recipient') or ''
        async with context(request) as service:
            farm=await service.me()
            link=await service.share_link(rotate=value.get('rotate',False))
            result=invite_info(farm['id'],farm['name'],token=link['token'],origin=origin,bot_username=bot_username,mini_app_short_name=mini_app_short_name,recipient=recipient)
            result.update(uses=link['uses'],max_uses=link['max_uses'],expires_at=link['expires_at'])
            result['rewards']=await service._invites(farm)
            telegram_user_id=getattr(service,'telegram_user_id',None)
        # The Bot API call runs after the game transaction; a failure only drops the native chat picker.
        result['prepared_message_id']=None
        if value.get('telegram') and prepare_share and telegram_user_id and result['mini_app_url']:
            result['prepared_message_id']=await prepare_share(telegram_user_id,result)
        return result
    @router.post(API+'/invite/share/revoke')
    async def revoke_share_invite(request:Request):
        value=await body(request,512)
        need(set(value)=={'token'} and isinstance(value['token'],str) and len(value['token'])==43,
             'invalid_body','Неверные поля запроса.',422)
        async with context(request) as service:result=await service.revoke_share_invite(value['token'])
        return result
    @router.post(API+'/invite/accept')
    async def accept_invite(request:Request):
        value=await body(request,512)
        need(set(value)=={'code'} and isinstance(value['code'],str) and len(value['code'])<=2048,'invalid_body','Неверные поля запроса.',422)
        code=value['code'].strip()
        if code.startswith('farm_'):code=code[5:]
        async with context(request) as service:result=await service.accept_invite(code)
        return result
    @router.post(API+'/invite/join')
    async def join_invite(request:Request):
        value=await body(request,512)
        need(set(value)=={'token'} and isinstance(value['token'],str) and len(value['token'])==43,
             'invalid_body','Неверные поля запроса.',422)
        async with context(request) as service:result=await service.join_share_invite(value['token'])
        return result
    @router.get(API+'/ledger')
    async def ledger(request:Request):
        async with context(request) as service:result=await service.history()
        return result
    @router.post(API+'/village/presence')
    async def village_presence(request:Request):
        value=await body(request,512)
        need(isinstance(value,dict) and set(value)=={'action','session'},
             'invalid_body','Неверные поля присутствия.',422)
        async with context(request) as service:
            return await service.village_presence(value['action'],value['session'])

    @router.post(API+'/commands')
    async def command(request:Request):
        value=await body(request)
        need(set(value)=={'command_id','kind','data','target','actor'},'invalid_body','Неверные поля команды.',422)
        need(isinstance(value['actor'],str) and len(value['actor'])==36 and
             isinstance(value['kind'],str) and isinstance(value['data'],dict) and
             (value['target'] is None or isinstance(value['target'],str) and len(value['target'])==36),
             'invalid_body','Неверные параметры команды.',422)
        async with context(request) as service:
            need((await service.me())['id']==value['actor'], 'profile_changed',
                 'Профиль изменился. Открой ферму заново; действие не выполнено.',409)
            result=await service.command(value['command_id'],value['kind'],value['data'],value['target'])
        return result
    return router


def install_boundary(app, origin, *, enabled=True, shared=False):
    buckets={}
    @app.exception_handler(FarmError)
    async def errors(request,error):
        return JSONResponse({'code':error.code,'message':error.message},status_code=error.status,
            headers={'Cache-Control':'no-store', **({'Retry-After':str(error.retry_after)}
                    if hasattr(error,'retry_after') else {})})
    @app.middleware('http')
    async def farm_boundary(request,call_next):
        path=request.url.path
        if not (path=='/app/farm' or path.startswith('/app/farm/assets/') or path.startswith(API+'/') or path.startswith('/api/farm-demo/')):
            return await call_next(request)
        if not enabled:return JSONResponse({'code':'disabled','message':'Ферма пока выключена.'},404)
        if f'{request.url.scheme}://{request.url.netloc}'!=origin:
            return JSONResponse({'code':'origin','message':'Недопустимый адрес сервиса.'},400)
        if request.headers.get('origin') not in (None,origin):
            return JSONResponse({'code':'origin','message':'Межсайтовый запрос запрещён.'},403)
        if request.method not in {'GET','HEAD'} and (request.headers.get('origin')!=origin or request.headers.get('x-qw-farm')!='1'):
            return JSONResponse({'code':'csrf','message':'Нет подтверждения источника запроса.'},403)
        if '/api/' in path and not shared:
            now=time.monotonic(); ip=request.client.host if request.client else 'unknown'
            # Bound keys and queues. This is local ingress protection, not an
            # internet-scale anti-bot system (edge limits still required).
            # Reads and writes have separate buckets: every farm action is a command PLUS a state refresh.
            write=request.method not in {'GET','HEAD'}
            for key in list(buckets):
                if not buckets[key] or buckets[key][-1] < now-60:del buckets[key]
            key=(ip,write)
            if key not in buckets and len(buckets)>=2000:
                return JSONResponse({'code':'busy','message':'Сервис занят.'},429,headers={'Retry-After':'10'})
            bucket=buckets.setdefault(key,deque())
            while bucket and bucket[0]<now-60:bucket.popleft()
            limit=LOCAL_LIMITS[write]
            if len(bucket)>=limit:
                wait=max(1,min(60,int(bucket[0]+60-now)+1))
                return JSONResponse({'code':'rate_limit','message':'Слишком много действий. Попробуй чуть позже.'},429,headers={'Retry-After':str(wait)})
            bucket.append(now)
        response=await call_next(request)
        response.headers.update({'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer'})
        if path=='/app/farm' or path.startswith('/app/farm/assets/'):
            response.headers['Content-Security-Policy']=CSP
        return response
