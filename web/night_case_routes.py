"""Thin Night Case HTTP boundary. Account/session and game rules belong to existing services."""
from __future__ import annotations

import inspect
import json
from contextlib import asynccontextmanager
from uuid import UUID

from fastapi import HTTPException, Query, Request
from fastapi.responses import JSONResponse

from application.night_case import NightCaseError
from application.night_case_ai import NightAIControlError


ERROR_TEXT = {
    'unavailable': 'Партия или запись недоступна.',
    'account_unavailable': 'Этот аккаунт сейчас недоступен.',
    'owner_required': 'Это действие доступно владельцу комнаты.',
    'command_conflict': 'Этот запрос уже использован с другими параметрами.',
    'actor_stale': 'Состояние изменилось. Обнови дело и выбери действие снова.',
    'proposal_stale': 'Предложение устарело. Выбери действие снова.',
    'window_closed': 'Это окно уже закрыто. Обнови дело.',
    'unsupported_count': 'Для этого дела столько игроков не подходит.',
    'seat_taken': 'Этого героя уже занял другой игрок.',
    'seats_unsolvable': 'С такими местами дело не сходится: пусть кто-то сядет за сыщика или выберет «любое свободное».',
    'players_not_ready': 'Сначала все участники должны подтвердить готовность.',
    'active_game_conflict': 'В комнате уже идёт партия.',
    'forfeit_required': 'Сначала подтверди выход из партии.',
    'runtime_delayed': 'Сервис восстанавливается. Повтори запрос позже.',
    'game_quarantined': 'Партия временно приостановлена для проверки.',
    'game_interrupted': 'Партия приостановлена.',
    'invalid_command': 'Проверь параметры действия.',
    'profile_changed': 'Профиль изменился. Открой дело заново из главного меню.',
    'ai_unavailable': 'AI сейчас недоступен. Выбери авторское начало дела.',
    'starter_unproven': 'Не удалось подтвердить, кто начал дело.',
    'rate_limited': 'Слишком много запросов подряд. Подожди немного.',
}
PUBLIC_CODES = frozenset(ERROR_TEXT) | frozenset({
    'account_ancestry_invalid', 'action_unavailable', 'case_unavailable', 'duplicate_name',
    'game_not_interrupted', 'game_not_lobby', 'game_not_running', 'game_not_started',
    'historical_command_ambiguous', 'lobby_full', 'operator_required',
})


def _unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('duplicate field')
        value[key] = item
    return value


def night_viewer_matches(expected, account_id, *, required):
    """The pin is a consistency fence; the verified Principal remains authority."""
    if expected is None:
        return not required
    try:
        return UUID(expected) == UUID(str(account_id))
    except (ValueError, TypeError, AttributeError):
        return False


def register_night_case_routes(app, *, principal, identity_for, read_body,
                               enabled=False, service_factory=None, orchestrator=None, ai_enabled=False):
    """Mount with the real room_principal context manager and an explicit service factory.

    The feature is off unless configured. Tests can inject a boundary fake; production
    never substitutes a fake service or loads an unregistered case from a local file.
    """

    async def body(request, fields=None):
        if not enabled:
            raise HTTPException(404, 'Недоступно.')
        if request.headers.get('content-type', '').split(';')[0].strip() != 'application/json':
            raise HTTPException(415, 'Ожидается JSON.')
        raw = await read_body(request, max_bytes=16384)
        try:
            value = json.loads(raw, object_pairs_hook=_unique)
            if type(value) is not dict or fields is not None and set(value) != set(fields):
                raise ValueError()
            return value
        except (ValueError, UnicodeError, RecursionError):
            raise HTTPException(422, 'Некорректные параметры действия.') from None

    async def invoke(request, identity, method, *, write=False, **kwargs):
        if not enabled:
            raise HTTPException(404, 'Недоступно.')
        if service_factory is None and orchestrator is None:
            raise HTTPException(503, 'Сервис дела ещё не подключён.')
        identity = identity_for(request, identity)
        if write:
            csrf = 'x-mini-csrf' if identity == 'telegram' else 'x-guest-csrf'
            origin = f'{request.url.scheme}://{request.url.netloc}'
            if request.headers.get('origin') != origin or request.headers.get(csrf) != '1':
                raise HTTPException(403, 'Подтверждение origin обязательно.')
        try:
            if orchestrator is not None and method in {'create_lobby','start_game','propose_intent'}:
                # Initial authority comes from the existing authenticated
                # Principal, never the viewer pin. Close this OUTER context
                # before calling orchestration or awaiting any transport.
                async with principal(request, identity, write=write) as (_, who):
                    account_id=UUID(str(who.account_id))
                    if not night_viewer_matches(request.headers.get('x-night-expected-viewer'),account_id,required=True):
                        raise NightCaseError('profile_changed',409)
                @asynccontextmanager
                async def authenticated_transaction():
                    # A fresh real principal/SQL transaction per prepare and
                    # finalize phase; this exact session is used by A and AI.
                    async with principal(request,identity,write=write) as (session,current):
                        if UUID(str(current.account_id))!=account_id or not night_viewer_matches(
                            request.headers.get('x-night-expected-viewer'),current.account_id,required=True):
                            raise NightCaseError('profile_changed',409)
                        yield session
                result=await getattr(orchestrator,method)(account_id=account_id,
                    transaction_factory=authenticated_transaction,**kwargs)
                return JSONResponse(result,headers={'Cache-Control':'private, no-store','Vary':'Cookie, Authorization'})
            async with principal(request, identity, write=write) as (session, who):
                viewer = str(UUID(str(who.account_id)))
                expected = request.headers.get('x-night-expected-viewer')
                if not night_viewer_matches(expected, who.account_id, required=method != 'list_cases'):
                    raise NightCaseError('profile_changed', 409)
                service = service_factory(session)
                if inspect.isawaitable(service):
                    service = await service
                result = await getattr(service, method)(account_id=UUID(str(who.account_id)), **kwargs)
                if method == 'list_cases':
                    # Entry availability only; legacy endpoints retain their own ACL.
                    # Free text needs a real intent transport; a bare orchestrator only carries AI start options.
                    free_intent = orchestrator is not None and (getattr(orchestrator, 'dispatcher', None) is not None
                                                                or getattr(orchestrator, 'transport', None) is not None)
                    result = {**result, 'viewer_account_id': viewer, 'account_timezone': getattr(who, 'timezone', None), 'capabilities': {
                        'legacy_mafia': True, 'free_intent': free_intent, 'ai_narrator': bool(ai_enabled)}}
                return JSONResponse(result, headers={'Cache-Control': 'private, no-store', 'Vary': 'Cookie, Authorization'})
        except (NightCaseError,NightAIControlError) as exc:
            # Neither service internals, provider text nor validation pointers become HTTP errors.
            code = exc.code if exc.code in PUBLIC_CODES else 'night_case_unavailable'
            return JSONResponse({'code': code, 'detail': ERROR_TEXT.get(code, 'Действие сейчас недоступно.')}, exc.status,
                                headers={'Cache-Control': 'private, no-store'})
        except ValueError:
            return JSONResponse({'code': 'invalid_command', 'detail': ERROR_TEXT['invalid_command']}, 422,
                                headers={'Cache-Control': 'private, no-store'})

    @app.get('/api/night-case/bootstrap')
    async def bootstrap(request: Request, identity: str | None = Query(None)):
        if not enabled:
            return JSONResponse({'enabled': False, 'cases': []}, headers={'Cache-Control': 'no-store'})
        return await invoke(request, identity, 'list_cases')

    @app.get('/api/night-case/mine')
    async def mine(request: Request, identity: str | None = Query(None)):
        return await invoke(request, identity, 'my_cases')

    @app.get('/api/rooms/{room_id}/night-case/current')
    async def current(request: Request, room_id: str, identity: str | None = Query(None)):
        return await invoke(request, identity, 'room_game', room_id=room_id)

    @app.post('/api/rooms/{room_id}/night-case/lobby')
    async def create(request: Request, room_id: str, identity: str | None = Query(None)):
        return await invoke(request, identity, 'create_lobby', write=True, room_id=room_id, command=await body(request))

    def lifecycle(path, method):
        async def handle(request: Request, game_id: str, identity: str | None = Query(None)):
            return await invoke(request, identity, method, write=True, game_id=game_id, command=await body(request))
        app.add_api_route('/api/night-case/games/{game_id}/' + path, handle, methods=['POST'], name='night_case_' + path)

    for path, method in [('join', 'join_lobby'), ('leave', 'leave_lobby'), ('ready', 'set_ready'), ('seat', 'take_seat'), ('start', 'start_game'),
                         ('lobby-chat', 'post_lobby_message')]:
        lifecycle(path, method)

    @app.get('/api/night-case/games/{game_id}/view')
    async def view(request: Request, game_id: str, identity: str | None = Query(None), original_account_id: str | None = None):
        selection = {} if original_account_id is None else {'original_account_id': original_account_id}
        return await invoke(request, identity, 'get_view', game_id=game_id, **selection)

    @app.post('/api/night-case/games/{game_id}/quote')
    async def quote(request: Request, game_id: str, identity: str | None = Query(None)):
        return await invoke(request, identity, 'quote', write=True, game_id=game_id, intent=await body(request, ['kind', 'params']))

    @app.post('/api/night-case/games/{game_id}/commands')
    async def commands(request: Request, game_id: str, identity: str | None = Query(None)):
        return await invoke(request, identity, 'execute', write=True, game_id=game_id, command=await body(request))

    @app.get('/api/night-case/games/{game_id}/history')
    async def history(request: Request, game_id: str, stream: str, cursor: str | None = None, limit: int = Query(50, ge=1, le=50), identity: str | None = Query(None), original_account_id: str | None = None):
        selection = {} if original_account_id is None else {'original_account_id': original_account_id}
        return await invoke(request, identity, 'history', game_id=game_id, stream=stream, cursor=cursor, limit=limit, **selection)

    @app.get('/api/night-case/games/{game_id}/messages/{message_id}')
    async def message(request: Request, game_id: str, message_id: str, identity: str | None = Query(None)):
        return await invoke(request, identity, 'get_message', game_id=game_id, message_id=message_id)

    @app.post('/api/night-case/games/{game_id}/intent')
    async def intent(request: Request, game_id: str, identity: str | None = Query(None)):
        value = await body(request, ['request_id', 'selection_id', 'text'])
        return await invoke(request, identity, 'propose_intent', write=True, game_id=game_id, **value)

    @app.post('/api/night-case/games/{game_id}/confirm')
    async def confirm(request: Request, game_id: str, identity: str | None = Query(None)):
        value = await body(request, ['proposal_id'])
        return await invoke(request, identity, 'confirm_intent', write=True, game_id=game_id, **value)

    @app.post('/api/night-case/games/{game_id}/renderings/{job_id}')
    async def rendering(request: Request, game_id: str, job_id: str, identity: str | None = Query(None)):
        await body(request, [])
        return await invoke(request, identity, 'get_rendering', write=True, game_id=game_id, job_id=job_id)
