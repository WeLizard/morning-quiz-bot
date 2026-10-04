"""Transport- and persistence-independent rules for the Night City game."""

from copy import deepcopy
from datetime import datetime, timezone
import secrets


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


def new_lobby(chat_id: int, host_id: int, host_name: str) -> dict:
    return {
        'mode': 'mafia_lobby', 'chat_id': chat_id, 'host_id': host_id,
        'status': 'lobby', 'revision': 0,
        'players': [{'user_id': host_id, 'name': host_name[:120], 'ready': False}],
    }


def normalized_lobby(value: object, *, chat_id: int) -> dict | None:
    if not isinstance(value, dict) or value.get('mode') != 'mafia_lobby' or value.get('chat_id') != chat_id:
        return None
    host = value.get('host_id')
    players = value.get('players')
    revision = value.get('revision', 0)
    if not isinstance(host, int) or not isinstance(players, list) or not isinstance(revision, int) or revision < 0:
        return None
    clean = []
    seen = set()
    for player in players:
        uid = player.get('user_id') if isinstance(player, dict) else None
        name = player.get('name') if isinstance(player, dict) else None
        if not isinstance(uid, int) or uid in seen or not isinstance(name, str):
            return None
        seen.add(uid)
        clean.append({'user_id': uid, 'name': name[:120], 'ready': bool(player.get('ready'))})
    status = value.get('status')
    if not 1 <= len(clean) <= MAX_PLAYERS or host not in seen or status not in {
        'lobby', 'night', 'day', 'voting', 'finished'
    }:
        return None
    result = {'mode': 'mafia_lobby', 'chat_id': chat_id, 'host_id': host, 'status': status,
              'revision': revision, 'players': clean}
    assignments = value.get('assignments')
    if status != 'lobby':
        if not isinstance(assignments, dict) or set(assignments) != {str(item['user_id']) for item in clean}:
            return None
        allowed = {'mafia', 'citizen', 'detective', 'doctor'}
        if any(role not in allowed for role in assignments.values()):
            return None
        result['assignments'] = assignments
        alive = value.get('alive', [item['user_id'] for item in clean])
        if (not isinstance(alive, list) or any(type(uid) is not int or uid not in seen for uid in alive)
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


def join_lobby(current: object, *, chat_id: int, user_id: int, name: str) -> tuple[dict, bool]:
    lobby = normalized_lobby(current, chat_id=chat_id)
    if lobby is None:
        return new_lobby(chat_id, user_id, name), True
    if lobby['status'] != 'lobby':
        raise ValueError('Партия уже началась.')
    if any(player['user_id'] == user_id for player in lobby['players']):
        return lobby, False
    if len(lobby['players']) >= MAX_PLAYERS:
        raise ValueError('За этим столом уже 12 игроков.')
    lobby['players'].append({'user_id': user_id, 'name': name[:120], 'ready': False})
    lobby['revision'] += 1
    return lobby, True


def set_ready(current: object, *, chat_id: int, user_id: int, ready: object, expected_revision: object) -> dict:
    lobby = normalized_lobby(current, chat_id=chat_id)
    if lobby is None:
        raise LookupError('Лобби ещё не создано.')
    if lobby['status'] != 'lobby':
        raise ValueError('Готовность меняется только до старта партии.')
    if not isinstance(expected_revision, int) or expected_revision != lobby['revision']:
        raise RuntimeError('Лобби уже изменилось. Обновите экран и повторите действие.')
    if not isinstance(ready, bool):
        raise ValueError('Готовность должна быть указана явно.')
    player = next((item for item in lobby['players'] if item['user_id'] == user_id), None)
    if player is None:
        raise PermissionError('Сначала присоединитесь к лобби.')
    if player['ready'] != ready:
        player['ready'] = ready
        lobby['revision'] += 1
    return lobby


def public_lobby(value: object, *, chat_id: int, viewer_id: int) -> dict | None:
    lobby = normalized_lobby(value, chat_id=chat_id)
    if lobby is None:
        return None
    own = next((player for player in lobby['players'] if player['user_id'] == viewer_id), None)
    alive = set(lobby.get('alive', []))
    result = {'mode': lobby['mode'], 'chat_id': lobby['chat_id'], 'status': lobby['status'],
            'revision': lobby['revision'], 'players': [{'name': item['name'], 'ready': item['ready'],
                                  'seat': f'p{index + 1}', 'alive': item['user_id'] in alive if alive else True,
                                  'is_me': item['user_id'] == viewer_id} for index, item in enumerate(lobby['players'])],
            'is_host': lobby['host_id'] == viewer_id, 'joined': own is not None,
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


def start_lobby(current: object, *, chat_id: int, user_id: int, expected_revision: object,
                now=None) -> dict:
    lobby = normalized_lobby(current, chat_id=chat_id)
    if lobby is None:
        raise LookupError('Лобби ещё не создано.')
    if lobby['host_id'] != user_id:
        raise PermissionError('Запустить партию может только создатель стола.')
    if lobby['status'] != 'lobby':
        raise ValueError('Партия уже запущена.')
    if not isinstance(expected_revision, int) or expected_revision != lobby['revision']:
        raise RuntimeError('Лобби уже изменилось. Обновите экран и повторите действие.')
    if len(lobby['players']) < MIN_PLAYERS or not all(player['ready'] for player in lobby['players']):
        raise ValueError('Нужны минимум четыре готовых игрока.')
    role_pool = [role['id'] for role in roles_for(len(lobby['players'])) for _ in range(role['count'])]
    secrets.SystemRandom().shuffle(role_pool)
    lobby['assignments'] = {str(player['user_id']): role for player, role in zip(lobby['players'], role_pool)}
    lobby.update(status='night', round=1,
                 alive=[player['user_id'] for player in lobby['players']],
                 night_actions={}, votes={}, investigations={}, winner=None,
                 history=[{'type': 'started', 'round': 1}],
                 phase_deadline=_deadline(now, NIGHT_SECONDS))
    lobby['revision'] += 1
    return lobby


def restart_lobby(current: object, *, chat_id: int, user_id: int,
                  expected_revision: object) -> dict:
    lobby = normalized_lobby(current, chat_id=chat_id)
    if lobby is None:
        raise LookupError('Стол не найден.')
    if lobby['host_id'] != user_id:
        raise PermissionError('Реванш может начать только ведущий стола.')
    if lobby['status'] != 'finished':
        raise ValueError('Текущая партия ещё не завершена.')
    _expect_revision(lobby, expected_revision)
    return {
        'mode': 'mafia_lobby',
        'chat_id': chat_id,
        'host_id': lobby['host_id'],
        'status': 'lobby',
        'revision': lobby['revision'] + 1,
        'players': [
            {'user_id': player['user_id'], 'name': player['name'], 'ready': False}
            for player in lobby['players']
        ],
    }


def own_role(value: object, *, chat_id: int, user_id: int) -> dict | None:
    lobby = normalized_lobby(value, chat_id=chat_id)
    if lobby is None or lobby['status'] == 'lobby':
        return None
    role = lobby['assignments'].get(str(user_id))
    if role is None:
        raise PermissionError('Вы не участник этой партии.')
    titles = {'mafia': 'Мафия', 'citizen': 'Мирный', 'detective': 'Детектив', 'doctor': 'Доктор'}
    player = next(item for item in lobby['players'] if item['user_id'] == user_id)
    alive = user_id in lobby.get('alive', [])
    result = {'phase': lobby['status'], 'round': lobby.get('round', 1), 'role': role,
              'title': titles[role], 'alive': alive, 'seat': _seat(lobby, user_id),
              'winner': lobby.get('winner')}
    if alive and lobby['status'] == 'night' and role != 'citizen':
        acted = str(user_id) in (lobby.get('night_actions', {}).get(role) or {})
        result['acted'] = acted
        result['targets'] = [
            {'seat': _seat(lobby, item['user_id']), 'name': item['name']}
            for item in lobby['players']
            if item['user_id'] in lobby['alive'] and item['user_id'] != user_id
            and not (role == 'mafia' and lobby['assignments'][str(item['user_id'])] == 'mafia')
        ]
    if alive and lobby['status'] == 'voting':
        result['voted'] = str(user_id) in lobby.get('votes', {})
        result['targets'] = [
            {'seat': _seat(lobby, item['user_id']), 'name': item['name']}
            for item in lobby['players'] if item['user_id'] in lobby['alive'] and item['user_id'] != user_id
        ]
    checks = lobby.get('investigations', {}).get(str(user_id), [])
    if role == 'detective' and checks:
        latest = checks[-1]
        result['investigation'] = {'round': latest['round'], 'seat': _seat(lobby, latest['target']),
                                   'is_mafia': latest['is_mafia']}
    return result


def _seat(lobby: dict, user_id: int) -> str:
    return f"p{next(index for index, item in enumerate(lobby['players'], 1) if item['user_id'] == user_id)}"


def _target(lobby: dict, seat: object) -> int:
    if not isinstance(seat, str) or not seat.startswith('p') or not seat[1:].isdigit():
        raise ValueError('Игрок не найден.')
    index = int(seat[1:]) - 1
    if not 0 <= index < len(lobby['players']):
        raise ValueError('Игрок не найден.')
    return lobby['players'][index]['user_id']


def _expect_revision(lobby: dict, expected_revision: object) -> None:
    if type(expected_revision) is not int or expected_revision != lobby['revision']:
        raise RuntimeError('Партия уже изменилась. Обновите экран и повторите действие.')


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


def night_action(current: object, *, chat_id: int, user_id: int, target_seat: object,
                 expected_revision: object, now=None) -> dict:
    lobby = normalized_lobby(current, chat_id=chat_id)
    if lobby is None or lobby['status'] != 'night':
        raise ValueError('Сейчас не ночная фаза.')
    _expect_revision(lobby, expected_revision)
    if phase_due(lobby, now=now):
        raise ValueError('Ночь уже завершилась. Обновите стол.')
    if user_id not in lobby['alive']:
        raise PermissionError('Вы не участвуете в этой ночи.')
    role = lobby['assignments'].get(str(user_id))
    if role == 'citizen':
        raise PermissionError('У мирного жителя нет ночного действия.')
    target = _target(lobby, target_seat)
    if target not in lobby['alive'] or target == user_id:
        raise ValueError('Эту цель выбрать нельзя.')
    if role == 'mafia' and lobby['assignments'][str(target)] == 'mafia':
        raise ValueError('Мафия не выбирает своего участника.')
    lobby.setdefault('night_actions', {}).setdefault(role, {})[str(user_id)] = target
    lobby['revision'] += 1
    return lobby


def _majority(values: list[int]) -> int | None:
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


def resolve_night(current: object, *, chat_id: int, user_id: int,
                  expected_revision: object, allow_incomplete=False, now=None) -> dict:
    lobby = normalized_lobby(current, chat_id=chat_id)
    if lobby is None or lobby['status'] != 'night':
        raise ValueError('Сейчас не ночная фаза.')
    _expect_revision(lobby, expected_revision)
    if lobby['host_id'] != user_id:
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
    return lobby


def open_voting(current: object, *, chat_id: int, user_id: int,
                expected_revision: object, now=None) -> dict:
    lobby = normalized_lobby(current, chat_id=chat_id)
    if lobby is None or lobby['status'] != 'day':
        raise ValueError('Голосование открывается после ночи.')
    _expect_revision(lobby, expected_revision)
    if lobby['host_id'] != user_id:
        raise PermissionError('Открыть голосование может только ведущий стола.')
    lobby['status'], lobby['votes'] = 'voting', {}
    lobby['phase_deadline'] = _deadline(now, VOTING_SECONDS)
    lobby['revision'] += 1
    return lobby


def cast_vote(current: object, *, chat_id: int, user_id: int, target_seat: object,
              expected_revision: object, now=None) -> dict:
    lobby = normalized_lobby(current, chat_id=chat_id)
    if lobby is None or lobby['status'] != 'voting':
        raise ValueError('Сейчас голосование закрыто.')
    _expect_revision(lobby, expected_revision)
    if phase_due(lobby, now=now):
        raise ValueError('Голосование уже завершилось. Обновите стол.')
    if user_id not in lobby['alive']:
        raise PermissionError('Вы не участвуете в голосовании.')
    target = _target(lobby, target_seat)
    if target not in lobby['alive'] or target == user_id:
        raise ValueError('Эту цель выбрать нельзя.')
    lobby.setdefault('votes', {})[str(user_id)] = target
    lobby['revision'] += 1
    return lobby


def resolve_vote(current: object, *, chat_id: int, user_id: int,
                 expected_revision: object, allow_incomplete=False, now=None) -> dict:
    lobby = normalized_lobby(current, chat_id=chat_id)
    if lobby is None or lobby['status'] != 'voting':
        raise ValueError('Сейчас голосование закрыто.')
    _expect_revision(lobby, expected_revision)
    if lobby['host_id'] != user_id:
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
    return lobby
