"""Transport- and persistence-independent rules for the Night City game."""

from copy import deepcopy
from datetime import datetime, timezone
import secrets
from uuid import UUID

from domain.mafia_state import canonicalize_mafia_state


MIN_PLAYERS = 4
MAX_PLAYERS = 12
NIGHT_SECONDS = 90
DAY_SECONDS = 180
VOTING_SECONDS = 90


def _now_timestamp(now=None) -> int:
    if now is None:
        return int(datetime.now(timezone.utc).timestamp())
    if isinstance(now, datetime):
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        return int(now.timestamp())
    if type(now) in {int, float}:
        return int(now)
    raise ValueError('Некорректное время партии.')


def _deadline(now, seconds: int) -> int:
    return _now_timestamp(now) + seconds


def normalize_discussion_message(value: object) -> str:
    """Validate a public in-game message without interpreting markup."""
    if not isinstance(value, str):
        raise ValueError('Напиши сообщение текстом.')
    message = value.strip()
    if not message:
        raise ValueError('Пустое сообщение отправить нельзя.')
    if len(message) > 1000:
        raise ValueError('Сообщение слишком длинное: максимум 1000 символов.')
    if any(ord(char) < 32 and char not in '\n\t' for char in message):
        raise ValueError('Сообщение содержит недопустимые управляющие символы.')
    return message


def roles_for(players: int) -> list[dict[str, int | str]]:
    if not isinstance(players, int) or not MIN_PLAYERS <= players <= MAX_PLAYERS:
        raise ValueError('Для дела нужно от 4 до 12 игроков.')
    mafia = 1 if players <= 6 else 2 if players <= 9 else 3
    roles = [
        {'id': 'mafia', 'title': 'Мафия', 'count': mafia},
        {'id': 'citizen', 'title': 'Мирные', 'count': players - mafia},
    ]
    if players >= 5:
        roles.append({'id': 'detective', 'title': 'Детектив', 'count': 1})
        roles[1]['count'] -= 1
    if players >= 7:
        roles.append({'id': 'doctor', 'title': 'Доктор', 'count': 1})
        roles[1]['count'] -= 1
    return roles


def new_draft(players: int = 6, revision: int = 0) -> dict:
    return {
        'mode': 'mafia_lobby',
        'case': 'night_city',
        'title': 'Ночной город',
        'players': players,
        'roles': roles_for(players),
        'revision': revision,
        'status': 'draft',
    }


def normalized_draft(value: object) -> dict:
    if not isinstance(value, dict):
        return new_draft()
    players = value.get('players', 6)
    revision = value.get('revision', 0)
    if not isinstance(revision, int) or revision < 0:
        revision = 0
    try:
        return new_draft(players, revision)
    except ValueError:
        return new_draft()


def update_draft(current: object, *, players: object, expected_revision: object) -> dict:
    draft = normalized_draft(current)
    if not isinstance(expected_revision, int) or expected_revision != draft['revision']:
        raise RuntimeError('Черновик уже изменился. Обновите экран и повторите выбор.')
    if not isinstance(players, int):
        raise ValueError('Количество игроков должно быть числом.')
    result = new_draft(players, draft['revision'] + 1)
    return deepcopy(result)


LOBBY_PREFIX = 'mafia_lobby:'


def lobby_key(chat_id: int) -> str:
    return LOBBY_PREFIX + str(chat_id)


def new_lobby(room_id: str, account_id: str, host_name: str) -> dict:
    """Create a transport-neutral lobby; Telegram remains an application concern."""
    account_id = str(UUID(str(account_id)))
    return {
        'mode': 'mafia_lobby', 'state_version': 2, 'room_id': room_id,
        'host_account_id': account_id,
        'status': 'lobby', 'revision': 0, 'phase_revision': 0,
        'players': ([{'account_id': account_id, 'name': host_name[:120], 'ready': False}]
                    if account_id else []),
    }


def new_room_lobby(room_id: str, host_account_id: str, host_name: str) -> dict:
    """Compatibility alias for the shared account-based lobby constructor."""
    return new_lobby(room_id, host_account_id, host_name)


def _identity_field(value: dict) -> str:
    return 'account_id'


def _actor(player: dict, value: dict):
    return player.get(_identity_field(value))


def _host(value: dict):
    return value.get('host_account_id')


def normalized_lobby(value: object, *, chat_id: int | None = None,
                     room_id: str | None = None) -> dict | None:
    expected_room = room_id if room_id is not None else f'telegram:{chat_id}'
    if not isinstance(value, dict) or value.get('mode') != 'mafia_lobby':
        return None
    try:
        value = canonicalize_mafia_state(value, expected_room)
    except (TypeError, ValueError):
        return None
    actor_field = 'account_id'
    host_field = 'host_account_id'
    host = value.get(host_field)
    players = value.get('players')
    revision = value.get('revision', 0)
    valid_host = isinstance(host, str) and bool(host)
    if not valid_host or not isinstance(players, list) or not isinstance(revision, int) or revision < 0:
        return None
    phase_revision = value.get('phase_revision', revision)
    if type(phase_revision) is not int or phase_revision < 0:
        return None
    clean = []
    seen = set()
    for player in players:
        uid = player.get(actor_field) if isinstance(player, dict) else None
        name = player.get('name') if isinstance(player, dict) else None
        valid_actor = isinstance(uid, str) and bool(uid)
        if not valid_actor or uid in seen or not isinstance(name, str):
            return None
        seen.add(uid)
        clean.append({actor_field: uid, 'name': name[:120], 'ready': bool(player.get('ready'))})
    status = value.get('status')
    if not 1 <= len(clean) <= MAX_PLAYERS or host not in seen or status not in {
        'lobby', 'night', 'day', 'voting', 'finished'
    }:
        return None
    result = {'mode': 'mafia_lobby', 'state_version': 2, 'room_id': expected_room,
              host_field: host, 'status': status,
              'revision': revision, 'phase_revision': phase_revision, 'players': clean}
    assignments = value.get('assignments')
    if status != 'lobby':
        if not isinstance(assignments, dict) or set(assignments) != {str(item[actor_field]) for item in clean}:
            return None
        allowed = {'mafia', 'citizen', 'detective', 'doctor'}
        if any(role not in allowed for role in assignments.values()):
            return None
        result['assignments'] = assignments
        alive = value.get('alive', [item[actor_field] for item in clean])
        valid_alive = lambda uid: isinstance(uid, str)
        if (not isinstance(alive, list) or any(not valid_alive(uid) or uid not in seen for uid in alive)
                or len(set(alive)) != len(alive)):
            return None
        result.update(
            alive=alive,
            round=max(1, value.get('round', 1)) if type(value.get('round', 1)) is int else 1,
            night_actions=deepcopy(value.get('night_actions') or {}),
            votes=deepcopy(value.get('votes') or {}),
            investigations=deepcopy(value.get('investigations') or {}),
            history=deepcopy(value.get('history') or []),
            winner=value.get('winner') if value.get('winner') in {None, 'mafia', 'citizens'} else None,
            phase_deadline=(int(value['phase_deadline'])
                            if type(value.get('phase_deadline')) in {int, float} else None),
        )
    return result


def join_lobby(current: object, *, chat_id: int | None = None,
               name: str, room_id: str | None = None,
               account_id: str | None = None) -> tuple[dict, bool]:
    if account_id is None:
        raise ValueError('Не указан участник стола.')
    actor_id = str(UUID(str(account_id)))
    lobby = normalized_lobby(current, chat_id=chat_id, room_id=room_id)
    if lobby is None:
        if current is not None:
            raise ValueError('Состояние стола повреждено или не поддерживается.')
        return new_lobby(room_id or f'telegram:{chat_id}', account_id, name), True
    if lobby['status'] != 'lobby':
        raise ValueError('Партия уже началась.')
    actor_field = _identity_field(lobby)
    if any(player[actor_field] == actor_id for player in lobby['players']):
        return lobby, False
    if len(lobby['players']) >= MAX_PLAYERS:
        raise ValueError('За этим столом уже 12 игроков.')
    lobby['players'].append({actor_field: actor_id, 'name': name[:120], 'ready': False})
    lobby['revision'] += 1
    return lobby, True


def set_ready(current: object, *, chat_id: int | None = None,
              ready: object, expected_revision: object, room_id: str | None = None,
              account_id: str | None = None) -> dict:
    lobby = normalized_lobby(current, chat_id=chat_id, room_id=room_id)
    if lobby is None:
        raise LookupError('Лобби ещё не создано.')
    if lobby['status'] != 'lobby':
        raise ValueError('Готовность меняется только до старта партии.')
    if not isinstance(expected_revision, int) or expected_revision != lobby['revision']:
        raise RuntimeError('Лобби уже изменилось. Обновите экран и повторите действие.')
    if not isinstance(ready, bool):
        raise ValueError('Готовность должна быть указана явно.')
    actor_id = str(UUID(str(account_id))) if account_id is not None else None
    player = next((item for item in lobby['players'] if _actor(item, lobby) == actor_id), None)
    if player is None:
        raise PermissionError('Сначала присоединитесь к лобби.')
    if player['ready'] != ready:
        player['ready'] = ready
        lobby['revision'] += 1
    return lobby


def public_lobby(value: object, *, chat_id: int | None = None,
                 room_id: str | None = None,
                 viewer_account_id: str | None = None) -> dict | None:
    lobby = normalized_lobby(value, chat_id=chat_id, room_id=room_id)
    if lobby is None:
        return None
    actor_field = _identity_field(lobby)
    viewer = str(UUID(str(viewer_account_id))) if viewer_account_id is not None else None
    own = next((player for player in lobby['players'] if _actor(player, lobby) == viewer), None)
    alive = set(lobby.get('alive', []))
    result = {'mode': lobby['mode'], 'status': lobby['status'],
            'revision': lobby['revision'], 'phase_revision': lobby['phase_revision'],
            'players': [{'name': item['name'], 'ready': item['ready'],
                                  'seat': f'p{index + 1}', 'alive': item[actor_field] in alive if alive else True,
                                  'is_me': item[actor_field] == viewer} for index, item in enumerate(lobby['players'])],
            'is_host': _host(lobby) == viewer, 'joined': own is not None,
            'can_start': lobby['status'] == 'lobby' and len(lobby['players']) >= MIN_PLAYERS and all(item['ready'] for item in lobby['players'])}
    if lobby['status'] != 'lobby':
        result.update(round=lobby['round'], winner=lobby.get('winner'),
                      history=deepcopy(lobby.get('history', []))[-20:],
                      ends_at=lobby.get('phase_deadline'))
        if lobby['status'] == 'night':
            result['can_advance'] = result['is_host'] and night_complete(lobby)
        elif lobby['status'] == 'day':
            result['can_advance'] = result['is_host']
        elif lobby['status'] == 'voting':
            result['votes_cast'] = len(lobby.get('votes', {}))
            result['votes_needed'] = len(lobby.get('alive', []))
            result['can_advance'] = result['is_host'] and result['votes_cast'] >= result['votes_needed']
    return result


def start_lobby(current: object, *, chat_id: int | None = None,
                expected_revision: object,
                room_id: str | None = None, account_id: str | None = None,
                now=None) -> dict:
    lobby = normalized_lobby(current, chat_id=chat_id, room_id=room_id)
    if lobby is None:
        raise LookupError('Лобби ещё не создано.')
    actor_id = str(UUID(str(account_id))) if account_id is not None else None
    if _host(lobby) != actor_id:
        raise PermissionError('Запустить партию может только создатель стола.')
    if lobby['status'] != 'lobby':
        raise ValueError('Партия уже запущена.')
    if not isinstance(expected_revision, int) or expected_revision != lobby['revision']:
        raise RuntimeError('Лобби уже изменилось. Обновите экран и повторите действие.')
    if len(lobby['players']) < MIN_PLAYERS or not all(player['ready'] for player in lobby['players']):
        raise ValueError('Нужны минимум четыре готовых игрока.')
    role_pool = [role['id'] for role in roles_for(len(lobby['players'])) for _ in range(role['count'])]
    secrets.SystemRandom().shuffle(role_pool)
    actor_field = _identity_field(lobby)
    lobby['assignments'] = {str(player[actor_field]): role for player, role in zip(lobby['players'], role_pool)}
    lobby.update(status='night', round=1,
                 alive=[player[actor_field] for player in lobby['players']],
                 night_actions={}, votes={}, investigations={}, winner=None,
                 history=[{'type': 'started', 'round': 1}],
                 phase_deadline=_deadline(now, NIGHT_SECONDS))
    lobby['revision'] += 1
    lobby['phase_revision'] += 1
    return lobby


def restart_lobby(current: object, *, chat_id: int | None = None,
                  expected_revision: object,
                  room_id: str | None = None, account_id: str | None = None) -> dict:
    lobby = normalized_lobby(current, chat_id=chat_id, room_id=room_id)
    if lobby is None:
        raise LookupError('Стол не найден.')
    actor_id = str(UUID(str(account_id))) if account_id is not None else None
    if _host(lobby) != actor_id:
        raise PermissionError('Реванш может начать только ведущий стола.')
    if lobby['status'] != 'finished':
        raise ValueError('Текущая партия ещё не завершена.')
    _expect_revision(lobby, expected_revision)
    result = {
        'mode': 'mafia_lobby',
        'host_account_id': _host(lobby),
        'status': 'lobby',
        'room_id': room_id or lobby['room_id'],
        'state_version': 2,
        'revision': lobby['revision'] + 1,
        'phase_revision': lobby['phase_revision'] + 1,
        'players': [
            {_identity_field(lobby): _actor(player, lobby), 'name': player['name'], 'ready': False}
            for player in lobby['players']
        ],
    }
    return result


def own_role(value: object, *, chat_id: int | None = None,
             room_id: str | None = None,
             account_id: str | None = None) -> dict | None:
    lobby = normalized_lobby(value, chat_id=chat_id, room_id=room_id)
    if lobby is None or lobby['status'] == 'lobby':
        return None
    actor_id = str(UUID(str(account_id))) if account_id is not None else None
    actor_field = _identity_field(lobby)
    role = lobby['assignments'].get(str(actor_id))
    if role is None:
        raise PermissionError('Вы не участник этой партии.')
    titles = {'mafia': 'Мафия', 'citizen': 'Мирный', 'detective': 'Детектив', 'doctor': 'Доктор'}
    player = next(item for item in lobby['players'] if _actor(item, lobby) == actor_id)
    alive = actor_id in lobby.get('alive', [])
    result = {'phase': lobby['status'], 'round': lobby.get('round', 1), 'role': role,
              'title': titles[role], 'alive': alive, 'seat': _seat(lobby, actor_id),
              'winner': lobby.get('winner'), 'phase_revision': lobby['phase_revision']}
    if alive and lobby['status'] == 'night' and role != 'citizen':
        acted = str(actor_id) in (lobby.get('night_actions', {}).get(role) or {})
        result['acted'] = acted
        result['targets'] = [
            {'seat': _seat(lobby, _actor(item, lobby)), 'name': item['name']}
            for item in lobby['players']
            if _actor(item, lobby) in lobby['alive'] and _actor(item, lobby) != actor_id
            and not (role == 'mafia' and lobby['assignments'][str(_actor(item, lobby))] == 'mafia')
        ]
    if alive and lobby['status'] == 'voting':
        result['voted'] = str(actor_id) in lobby.get('votes', {})
        result['targets'] = [
            {'seat': _seat(lobby, _actor(item, lobby)), 'name': item['name']}
            for item in lobby['players'] if _actor(item, lobby) in lobby['alive'] and _actor(item, lobby) != actor_id
        ]
    checks = lobby.get('investigations', {}).get(str(actor_id), [])
    if role == 'detective' and checks:
        latest = checks[-1]
        result['investigation'] = {'round': latest['round'], 'seat': _seat(lobby, latest['target']),
                                   'is_mafia': latest['is_mafia']}
    return result


def _seat(lobby: dict, actor_id) -> str:
    return f"p{next(index for index, item in enumerate(lobby['players'], 1) if _actor(item, lobby) == actor_id)}"


def _target(lobby: dict, seat: object):
    if not isinstance(seat, str) or not seat.startswith('p') or not seat[1:].isdigit():
        raise ValueError('Игрок не найден.')
    index = int(seat[1:]) - 1
    if not 0 <= index < len(lobby['players']):
        raise ValueError('Игрок не найден.')
    return _actor(lobby['players'][index], lobby)


def _expect_revision(lobby: dict, expected_revision: object) -> None:
    if type(expected_revision) is not int or expected_revision != lobby['revision']:
        raise RuntimeError('Партия уже изменилась. Обновите экран и повторите действие.')


def _expect_phase_revision(lobby: dict, expected_revision: object) -> None:
    if type(expected_revision) is not int or expected_revision != lobby['phase_revision']:
        raise RuntimeError('Фаза уже изменилась. Обновите экран и повторите действие.')


def phase_due(lobby: dict, *, now=None) -> bool:
    deadline = lobby.get('phase_deadline')
    return type(deadline) is int and _now_timestamp(now) >= deadline


def night_complete(lobby: dict) -> bool:
    if lobby.get('status') != 'night':
        return False
    actions = lobby.get('night_actions', {})
    for uid in lobby.get('alive', []):
        role = lobby['assignments'][str(uid)]
        if role != 'citizen' and str(uid) not in (actions.get(role) or {}):
            return False
    return True


def night_action(current: object, *, chat_id: int | None = None,
                 target_seat: object,
                 expected_revision: object, room_id: str | None = None,
                 account_id: str | None = None, now=None) -> dict:
    lobby = normalized_lobby(current, chat_id=chat_id, room_id=room_id)
    if lobby is None or lobby['status'] != 'night':
        raise ValueError('Сейчас не ночная фаза.')
    _expect_phase_revision(lobby, expected_revision)
    if phase_due(lobby, now=now):
        raise ValueError('Ночь уже завершилась. Обновите стол.')
    actor_id = str(UUID(str(account_id))) if account_id is not None else None
    if actor_id not in lobby['alive']:
        raise PermissionError('Вы не участвуете в этой ночи.')
    role = lobby['assignments'].get(str(actor_id))
    if role == 'citizen':
        raise PermissionError('У мирного жителя нет ночного действия.')
    if str(actor_id) in (lobby.get('night_actions', {}).get(role) or {}):
        raise ValueError('Вы уже сделали ночной выбор. Дождитесь итогов фазы.')
    target = _target(lobby, target_seat)
    if target not in lobby['alive'] or target == actor_id:
        raise ValueError('Эту цель выбрать нельзя.')
    if role == 'mafia' and lobby['assignments'][str(target)] == 'mafia':
        raise ValueError('Мафия не выбирает своего участника.')
    lobby.setdefault('night_actions', {}).setdefault(role, {})[str(actor_id)] = target
    lobby['revision'] += 1
    return lobby


def _majority(values: list) -> object | None:
    if not values:
        return None
    counts = {value: values.count(value) for value in set(values)}
    highest = max(counts.values())
    winners = [value for value, count in counts.items() if count == highest]
    return winners[0] if len(winners) == 1 else None


def _winner(lobby: dict) -> str | None:
    mafia = sum(lobby['assignments'][str(uid)] == 'mafia' for uid in lobby['alive'])
    others = len(lobby['alive']) - mafia
    if mafia == 0:
        return 'citizens'
    if mafia >= others:
        return 'mafia'
    return None


def resolve_night(current: object, *, chat_id: int | None = None,
                  expected_revision: object,
                  room_id: str | None = None, account_id: str | None = None,
                  allow_incomplete=False, now=None) -> dict:
    lobby = normalized_lobby(current, chat_id=chat_id, room_id=room_id)
    if lobby is None or lobby['status'] != 'night':
        raise ValueError('Сейчас не ночная фаза.')
    _expect_revision(lobby, expected_revision)
    actor_id = str(UUID(str(account_id))) if account_id is not None else None
    if _host(lobby) != actor_id:
        raise PermissionError('Продолжить партию может только ведущий стола.')
    if not night_complete(lobby) and not allow_incomplete:
        raise ValueError('Не все ночные действия выполнены.')
    actions = lobby['night_actions']
    victim = _majority(list((actions.get('mafia') or {}).values()))
    protected = next(iter((actions.get('doctor') or {}).values()), None)
    killed = victim if victim is not None and victim != protected else None
    if killed in lobby['alive']:
        lobby['alive'].remove(killed)
    for detective, target in (actions.get('detective') or {}).items():
        lobby.setdefault('investigations', {}).setdefault(detective, []).append({
            'round': lobby['round'], 'target': target,
            'is_mafia': lobby['assignments'][str(target)] == 'mafia',
        })
    event = {'type': 'night_result', 'round': lobby['round'],
             'eliminated': _seat(lobby, killed) if killed is not None else None,
             'saved': victim is not None and victim == protected}
    lobby.setdefault('history', []).append(event)
    lobby['night_actions'] = {}
    lobby['winner'] = _winner(lobby)
    lobby['status'] = 'finished' if lobby['winner'] else 'day'
    lobby['phase_deadline'] = None if lobby['winner'] else _deadline(now, DAY_SECONDS)
    lobby['revision'] += 1
    lobby['phase_revision'] += 1
    return lobby


def open_voting(current: object, *, chat_id: int | None = None,
                expected_revision: object,
                room_id: str | None = None, account_id: str | None = None,
                now=None) -> dict:
    lobby = normalized_lobby(current, chat_id=chat_id, room_id=room_id)
    if lobby is None or lobby['status'] != 'day':
        raise ValueError('Голосование открывается после ночи.')
    _expect_revision(lobby, expected_revision)
    actor_id = str(UUID(str(account_id))) if account_id is not None else None
    if _host(lobby) != actor_id:
        raise PermissionError('Открыть голосование может только ведущий стола.')
    lobby['status'], lobby['votes'] = 'voting', {}
    lobby['phase_deadline'] = _deadline(now, VOTING_SECONDS)
    lobby['revision'] += 1
    lobby['phase_revision'] += 1
    return lobby


def cast_vote(current: object, *, chat_id: int | None = None,
              target_seat: object,
              expected_revision: object, room_id: str | None = None,
              account_id: str | None = None, now=None) -> dict:
    lobby = normalized_lobby(current, chat_id=chat_id, room_id=room_id)
    if lobby is None or lobby['status'] != 'voting':
        raise ValueError('Сейчас голосование закрыто.')
    _expect_phase_revision(lobby, expected_revision)
    if phase_due(lobby, now=now):
        raise ValueError('Голосование уже завершилось. Обновите стол.')
    actor_id = str(UUID(str(account_id))) if account_id is not None else None
    if actor_id not in lobby['alive']:
        raise PermissionError('Вы не участвуете в голосовании.')
    if str(actor_id) in (lobby.get('votes') or {}):
        raise ValueError('Вы уже проголосовали. Дождитесь итогов голосования.')
    target = _target(lobby, target_seat)
    if target not in lobby['alive'] or target == actor_id:
        raise ValueError('Эту цель выбрать нельзя.')
    lobby.setdefault('votes', {})[str(actor_id)] = target
    lobby['revision'] += 1
    return lobby


def resolve_vote(current: object, *, chat_id: int | None = None,
                 expected_revision: object,
                 room_id: str | None = None, account_id: str | None = None,
                 allow_incomplete=False, now=None) -> dict:
    lobby = normalized_lobby(current, chat_id=chat_id, room_id=room_id)
    if lobby is None or lobby['status'] != 'voting':
        raise ValueError('Сейчас голосование закрыто.')
    _expect_revision(lobby, expected_revision)
    actor_id = str(UUID(str(account_id))) if account_id is not None else None
    if _host(lobby) != actor_id:
        raise PermissionError('Завершить голосование может только ведущий стола.')
    if len(lobby.get('votes', {})) < len(lobby['alive']) and not allow_incomplete:
        raise ValueError('Не все живые игроки проголосовали.')
    eliminated = _majority(list(lobby['votes'].values()))
    if eliminated in lobby['alive']:
        lobby['alive'].remove(eliminated)
    lobby.setdefault('history', []).append({'type': 'vote_result', 'round': lobby['round'],
                                            'eliminated': _seat(lobby, eliminated) if eliminated else None})
    lobby['winner'] = _winner(lobby)
    if lobby['winner']:
        lobby['status'] = 'finished'
        lobby['phase_deadline'] = None
    else:
        lobby['round'] += 1
        lobby['status'] = 'night'
        lobby['night_actions'], lobby['votes'] = {}, {}
        lobby['phase_deadline'] = _deadline(now, NIGHT_SECONDS)
    lobby['revision'] += 1
    lobby['phase_revision'] += 1
    return lobby
