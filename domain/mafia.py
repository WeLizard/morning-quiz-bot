"""Transport- and persistence-independent rules for the Night City game."""

from copy import deepcopy
from datetime import datetime, timezone
import re
import secrets
from uuid import UUID

from domain.mafia_state import canonicalize_mafia_state
from domain.night_worlds import DEFAULT_WORLD, is_world, world_age


MIN_PLAYERS = 4
MAX_PLAYERS = 12
NIGHT_SECONDS = 90
DAY_SECONDS = 180
VOTING_SECONDS = 90
# A started table where nobody acted for this many whole rounds (no night choice, no vote, no manual
# phase change) is closed as abandoned: otherwise phase deadlines cycle it forever.
IDLE_ROUNDS_LIMIT = 3

# Owner decision 2026-10-28 (recommendation, can be reverted): at an app-room table the host may start
# the night as soon as at least MIN_PLAYERS seated players are ready; seated players who are not ready do
# not enter the game and wait for the next one. True restores the old rule «everyone seated must be ready»
# for every table. Telegram group tables always keep the old rule (see ``start_requires_all_ready``):
# their interface shows no queue, so a seated player would just vanish from the game.
START_REQUIRES_ALL_READY = False


def start_requires_all_ready(lobby: dict) -> bool:
    """A property of the table: Telegram group tables (room id ``telegram:<chat>``) need everybody ready."""
    return START_REQUIRES_ALL_READY or str(lobby.get('room_id', '')).startswith('telegram:')

# Portraits are numbered 1..PORTRAIT_COUNT. Unique per table; must cover every seat
# (PORTRAIT_COUNT >= MAX_PLAYERS) or the surplus players get portrait None.
PORTRAIT_COUNT = 17


class TableFull(ValueError):
    """No free seat (or waiting place) at the table."""


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


def _free_portrait(taken, preferred: int):
    """First portrait not in ``taken``, scanning from the seat's own number; None when all are used."""
    for step in range(PORTRAIT_COUNT):
        candidate = (preferred + step) % PORTRAIT_COUNT + 1
        if candidate not in taken:
            return candidate
    return None


def _valid_portrait(value) -> bool:
    return type(value) is int and 1 <= value <= PORTRAIT_COUNT


LOBBY_PREFIX = 'mafia_lobby:'


def lobby_key(chat_id: int) -> str:
    return LOBBY_PREFIX + str(chat_id)


def new_lobby(room_id: str, account_id: str, host_name: str, world: str | None = None) -> dict:
    """Create a transport-neutral lobby; Telegram remains an application concern.

    ``world`` is the story of the room (domain/night_worlds.py); it is stored only when it is not the default,
    so older states and Telegram group tables stay as they were.
    """
    account_id = str(UUID(str(account_id)))
    lobby = {
        'mode': 'mafia_lobby', 'state_version': 2, 'room_id': room_id,
        'host_account_id': account_id,
        'status': 'lobby', 'revision': 0, 'phase_revision': 0,
        'players': ([{'account_id': account_id, 'name': host_name[:120], 'ready': False,
                      'portrait': _free_portrait(set(), 0)}]
                    if account_id else []),
    }
    if is_world(world) and world != DEFAULT_WORLD:
        lobby['world'] = world
    return lobby


def new_room_lobby(room_id: str, host_account_id: str, host_name: str, world: str | None = None) -> dict:
    """Compatibility alias for the shared account-based lobby constructor."""
    return new_lobby(room_id, host_account_id, host_name, world)


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
        clean.append({actor_field: uid, 'name': name[:120], 'ready': bool(player.get('ready')),
                      'portrait': player.get('portrait')})
    # Explicit unique portraits keep their place; the rest get the first free one from their seat number.
    taken = set()
    for item in clean:
        if _valid_portrait(item['portrait']) and item['portrait'] not in taken:
            taken.add(item['portrait'])
        else:
            item['portrait'] = None
    for index, item in enumerate(clean):
        if item['portrait'] is None:
            item['portrait'] = _free_portrait(taken, index)
            if item['portrait'] is not None:
                taken.add(item['portrait'])
    status = value.get('status')
    if not 1 <= len(clean) <= MAX_PLAYERS or host not in seen or status not in {
        'lobby', 'night', 'day', 'voting', 'finished'
    }:
        return None
    result = {'mode': 'mafia_lobby', 'state_version': 2, 'room_id': expected_room,
              host_field: host, 'status': status,
              'revision': revision, 'phase_revision': phase_revision, 'players': clean}
    waiting = _clean_waiting(value.get('waiting'), seen, len(clean))
    if waiting:
        result['waiting'] = waiting
    if is_world(value.get('world')) and value['world'] != DEFAULT_WORLD:
        result['world'] = value['world']
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
            idle_rounds=value['idle_rounds'] if type(value.get('idle_rounds')) is int and value['idle_rounds'] >= 0 else 0,
            round_active=value.get('round_active') is True,
            phase_deadline=(int(value['phase_deadline'])
                            if type(value.get('phase_deadline')) in {int, float} else None),
        )
    return result


def _clean_waiting(raw, seated: set, seats: int) -> list[dict]:
    """People who sit out the running game and join the next one; never overlap the roster."""
    if not isinstance(raw, list):
        return []
    result, seen = [], set(seated)
    for item in raw:
        uid = item.get('account_id') if isinstance(item, dict) else None
        name = item.get('name') if isinstance(item, dict) else None
        if not isinstance(uid, str) or not uid or uid in seen or not isinstance(name, str):
            continue
        if seats + len(result) >= MAX_PLAYERS:
            break
        seen.add(uid)
        entry = {'account_id': uid, 'name': name[:120]}
        if _valid_portrait(item.get('portrait')):
            entry['portrait'] = item['portrait']
        result.append(entry)
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
        raise TableFull('За этим столом уже 12 игроков.')
    entry = next((item for item in lobby.get('waiting', []) if item['account_id'] == actor_id), None)
    if entry is not None:
        lobby['waiting'].remove(entry)
        if not lobby['waiting']:
            del lobby['waiting']
    taken = {item['portrait'] for item in lobby['players']}
    preferred = entry.get('portrait') if entry is not None else None
    portrait = preferred if _valid_portrait(preferred) and preferred not in taken else _free_portrait(
        taken, len(lobby['players']))
    lobby['players'].append({actor_field: actor_id, 'name': name[:120], 'ready': False,
                             'portrait': portrait})
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


def set_portrait(current: object, *, chat_id: int | None = None, portrait: object,
                 expected_revision: object, room_id: str | None = None,
                 account_id: str | None = None) -> dict:
    """Pick a portrait before the night starts; portraits are unique at the table."""
    lobby = normalized_lobby(current, chat_id=chat_id, room_id=room_id)
    if lobby is None:
        raise LookupError('Лобби ещё не создано.')
    if lobby['status'] != 'lobby':
        raise ValueError('Портрет выбирается только до старта партии.')
    if not isinstance(expected_revision, int) or expected_revision != lobby['revision']:
        raise RuntimeError('Лобби уже изменилось. Обновите экран и повторите действие.')
    if not _valid_portrait(portrait):
        raise ValueError(f'Портрет — число от 1 до {PORTRAIT_COUNT}.')
    actor_id = str(UUID(str(account_id))) if account_id is not None else None
    player = next((item for item in lobby['players'] if _actor(item, lobby) == actor_id), None)
    if player is None:
        raise PermissionError('Сначала присоединитесь к лобби.')
    if any(item is not player and item['portrait'] == portrait for item in lobby['players']):
        raise ValueError('Этот портрет уже занят за столом.')
    if player['portrait'] != portrait:
        player['portrait'] = portrait
        lobby['revision'] += 1
    return lobby


def set_world(current: object, *, world: object, expected_revision: object,
              room_id: str | None = None, account_id: str | None = None) -> dict:
    """The host picks the story of the room before the night starts; it shows for everybody at the table."""
    lobby = normalized_lobby(current, room_id=room_id)
    if lobby is None:
        raise LookupError('Лобби ещё не создано.')
    actor_id = str(UUID(str(account_id))) if account_id is not None else None
    if _host(lobby) != actor_id:
        raise PermissionError('Сменить сюжет может только ведущий стола.')
    if lobby['status'] != 'lobby':
        raise ValueError('Сюжет выбирается только до старта партии.')
    if type(expected_revision) is not int or expected_revision != lobby['revision']:
        raise RuntimeError('Лобби уже изменилось. Обновите экран и повторите действие.')
    if not is_world(world):
        raise ValueError('Неизвестный сюжет.')
    if world != lobby.get('world', DEFAULT_WORLD):
        if world == DEFAULT_WORLD:
            lobby.pop('world', None)
        else:
            lobby['world'] = world
        lobby['revision'] += 1
    return lobby


def wait_lobby(current: object, *, chat_id: int | None = None, name: str,
               room_id: str | None = None, account_id: str | None = None) -> tuple[dict, bool]:
    """«Ждать следующую»: sit out the running game, take part in the rematch."""
    if account_id is None:
        raise ValueError('Не указан участник стола.')
    actor_id = str(UUID(str(account_id)))
    lobby = normalized_lobby(current, chat_id=chat_id, room_id=room_id)
    if lobby is None:
        raise LookupError('Стол ещё не создан.')
    if lobby['status'] == 'lobby':
        raise ValueError('Стол ещё собирается: садись за стол.')
    if any(_actor(player, lobby) == actor_id for player in lobby['players']):
        if lobby['status'] == 'finished':
            return lobby, False
        raise ValueError('Ты уже играешь в этой партии.')
    if any(item['account_id'] == actor_id for item in lobby.get('waiting', [])):
        return lobby, False
    if len(lobby['players']) + len(lobby.get('waiting', [])) >= MAX_PLAYERS:
        raise TableFull('Стол полон: мест на следующую партию нет.')
    lobby.setdefault('waiting', []).append({'account_id': actor_id, 'name': name[:120]})
    lobby['revision'] += 1
    return lobby, True


def unseat_lobby(current: object, *, chat_id: int | None = None,
                 room_id: str | None = None, account_id: str | None = None) -> tuple[dict, bool]:
    """Stand up: leave the waiting list at any time, or an unstarted table seat (never the host)."""
    lobby = normalized_lobby(current, chat_id=chat_id, room_id=room_id)
    if lobby is None:
        raise LookupError('Стол не найден.')
    actor_id = str(UUID(str(account_id))) if account_id is not None else None
    waiting = next((item for item in lobby.get('waiting', []) if item['account_id'] == actor_id), None)
    if waiting is not None:
        lobby['waiting'].remove(waiting)
        if not lobby['waiting']:
            del lobby['waiting']
        lobby['revision'] += 1
        return lobby, True
    seat = next((item for item in lobby['players'] if _actor(item, lobby) == actor_id), None)
    if seat is None:
        return lobby, False
    if _host(lobby) == actor_id:
        raise PermissionError('Хозяин не может встать из-за своего стола.')
    if lobby['status'] != 'lobby':
        raise ValueError('Во время партии встать из-за стола нельзя.')
    lobby['players'].remove(seat)
    lobby['revision'] += 1
    return lobby, True


def leave_table(current: object, *, room_id: str, account_id: str) -> tuple[dict | None, str, str]:
    """A non-host member leaves the room: ``(state, outcome, name)``.

    ``outcome``: ``unseated`` (left an unstarted table), ``waiting`` (left the queue), ``vanished``
    (a living hero drops out of a running game), ``none`` (no table place or already out; state untouched).
    A vanished hero stays in the roster (seats keep their numbers) but is no longer alive; the history
    gets a ``vanished`` event with the name and no role. Win conditions are re-checked; finishing the
    game is done here, an early phase close is the caller's job (``phase_complete``).
    """
    lobby = normalized_lobby(current, room_id=room_id)
    if lobby is None:
        return None, 'none', ''
    actor_id = str(UUID(str(account_id)))
    if _host(lobby) == actor_id:
        raise PermissionError('Хозяин не может выйти из своей комнаты.')
    waiting = next((item for item in lobby.get('waiting', []) if item['account_id'] == actor_id), None)
    if waiting is not None:
        lobby['waiting'].remove(waiting)
        if not lobby['waiting']:
            del lobby['waiting']
        lobby['revision'] += 1
        return lobby, 'waiting', waiting['name']
    seat = next((item for item in lobby['players'] if _actor(item, lobby) == actor_id), None)
    if seat is None:
        return lobby, 'none', ''
    if lobby['status'] == 'lobby':
        lobby['players'].remove(seat)
        lobby['revision'] += 1
        return lobby, 'unseated', seat['name']
    if lobby['status'] == 'finished' or actor_id not in lobby['alive']:
        return lobby, 'none', seat['name']
    event_seat = _seat(lobby, actor_id)
    lobby['alive'].remove(actor_id)
    for role_actions in lobby.get('night_actions', {}).values():
        role_actions.pop(actor_id, None)
    lobby.get('votes', {}).pop(actor_id, None)
    lobby.setdefault('history', []).append({'type': 'vanished', 'round': lobby['round'],
                                            'seat': event_seat, 'name': seat['name']})
    lobby['winner'] = _winner(lobby)
    if lobby['winner']:
        lobby['status'] = 'finished'
        lobby['phase_deadline'] = None
        lobby['phase_revision'] += 1
    lobby['revision'] += 1
    return lobby, 'vanished', seat['name']


def remove_player(current: object, *, chat_id: int | None = None, target: object,
                  expected_revision: object, room_id: str | None = None,
                  account_id: str | None = None) -> tuple[dict, str, str]:
    """The host removes someone from the lobby (seat ``pN``) or the waiting list (``wN``).

    Returns ``(state, removed_account_id, removed_name)``. A seated player cannot be removed from a
    running game: the roles and deadlines already count on them.
    """
    lobby = normalized_lobby(current, chat_id=chat_id, room_id=room_id)
    if lobby is None:
        raise LookupError('Стол не найден.')
    actor_id = str(UUID(str(account_id))) if account_id is not None else None
    if _host(lobby) != actor_id:
        raise PermissionError('Убрать игрока может только хозяин стола.')
    if not isinstance(expected_revision, int) or expected_revision != lobby['revision']:
        raise RuntimeError('Лобби уже изменилось. Обновите экран и повторите действие.')
    if not isinstance(target, str) or not re.fullmatch(r'[pw][1-9][0-9]?', target):
        raise ValueError('Игрок не найден.')
    index = int(target[1:]) - 1
    if target[0] == 'w':
        waiting = lobby.get('waiting', [])
        if not 0 <= index < len(waiting):
            raise ValueError('Игрок не найден.')
        removed = waiting.pop(index)
        if not waiting:
            lobby.pop('waiting', None)
        lobby['revision'] += 1
        return lobby, removed['account_id'], removed['name']
    if not 0 <= index < len(lobby['players']):
        raise ValueError('Игрок не найден.')
    removed = lobby['players'][index]
    if _actor(removed, lobby) == actor_id:
        raise ValueError('Себя убрать нельзя.')
    if lobby['status'] != 'lobby':
        raise ValueError('Во время партии игрока убрать нельзя.')
    lobby['players'].pop(index)
    lobby['revision'] += 1
    return lobby, _actor(removed, lobby), removed['name']


def ready_count(lobby: dict) -> int:
    return sum(1 for item in lobby['players'] if item['ready'])


def can_start_now(lobby: dict) -> bool:
    """The host may start: enough ready players and the host is among them."""
    if lobby['status'] != 'lobby':
        return False
    host = next((item for item in lobby['players'] if _actor(item, lobby) == _host(lobby)), None)
    if host is None or not host['ready'] or ready_count(lobby) < MIN_PLAYERS:
        return False
    return not start_requires_all_ready(lobby) or ready_count(lobby) == len(lobby['players'])


def phase_complete(lobby: dict) -> bool:
    """True when every living player has voted (early close).

    The night never closes early (decided 2026-10-29): a night that ends before the deadline would tell
    everyone that the detective or the doctor is dead (nobody is left to act). Only the voting closes early.
    """
    status = lobby.get('status')
    if status == 'voting':
        alive = lobby.get('alive') or []
        votes = lobby.get('votes') or {}
        return bool(alive) and all(str(uid) in votes for uid in alive)
    return False


def discussion_access(value: object, *, chat_id: int | None = None,
                      room_id: str | None = None, account_id: str | None = None) -> tuple[bool, bool]:
    """``(may_read, may_post)``: the roster reads; only the lobby table and the living (day) post."""
    lobby = normalized_lobby(value, chat_id=chat_id, room_id=room_id)
    if lobby is None or account_id is None:
        return False, False
    actor_id = str(UUID(str(account_id)))
    if not any(_actor(item, lobby) == actor_id for item in lobby['players']):
        return False, False
    if lobby['status'] == 'lobby':
        return True, True
    return True, lobby['status'] == 'day' and actor_id in lobby.get('alive', [])


def open_table_summary(value: object, *, room_id: str) -> dict | None:
    """Public facts for the open-tables list: no accounts, no Telegram data."""
    lobby = normalized_lobby(value, room_id=room_id)
    if lobby is None:
        return None
    seated = len(lobby['players'])
    waiting = len(lobby.get('waiting', []))
    if lobby['status'] == 'lobby':
        state = 'full' if seated >= MAX_PLAYERS else 'gathering'
    else:
        state = 'full' if seated + waiting >= MAX_PLAYERS else 'playing'
    host = next((item for item in lobby['players'] if _actor(item, lobby) == _host(lobby)), None)
    return {'status': state, 'phase': lobby['status'], 'seated': seated, 'waiting': waiting,
            'host_name': host['name'] if host else ''}


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
            'server_now': _now_timestamp(),
            'players': [{'name': item['name'], 'ready': item['ready'], 'portrait': item['portrait'],
                                  'seat': f'p{index + 1}', 'alive': item[actor_field] in alive if alive else True,
                                  'is_me': item[actor_field] == viewer} for index, item in enumerate(lobby['players'])],
            'is_host': _host(lobby) == viewer, 'joined': own is not None,
            'min_players': MIN_PLAYERS, 'max_players': MAX_PLAYERS,
            'portrait_count': PORTRAIT_COUNT,
            'world': lobby.get('world', DEFAULT_WORLD),
            'world_age': world_age(lobby.get('world', DEFAULT_WORLD)),
            'ready_count': ready_count(lobby),
            'start_requires_all_ready': start_requires_all_ready(lobby),
            'can_start': can_start_now(lobby)}
    waiting = lobby.get('waiting', [])
    result['waiting'] = [{'name': item['name'], 'ref': f'w{index + 1}', 'is_me': item['account_id'] == viewer}
                         for index, item in enumerate(waiting)]
    result['is_waiting'] = any(item['account_id'] == viewer for item in waiting)
    if lobby['status'] != 'lobby':
        names = {f'p{index + 1}': item['name'] for index, item in enumerate(lobby['players'])}
        history = deepcopy(lobby.get('history', []))[-20:]
        for event in history:
            if event.get('eliminated') in names:
                event['eliminated_name'] = names[event['eliminated']]
        result.update(round=lobby['round'], winner=lobby.get('winner'),
                      abandoned=lobby['status'] == 'finished' and lobby.get('winner') is None,
                      history=history, ends_at=lobby.get('phase_deadline'))
        if lobby['status'] == 'finished':
            # The game is over: roles are public now (never before).
            for entry, item in zip(result['players'], lobby['players']):
                entry['role'] = lobby['assignments'].get(str(_actor(item, lobby)))
        if lobby['status'] == 'voting':
            votes = lobby.get('votes') or {}
            for entry, item in zip(result['players'], lobby['players']):
                if entry['alive']:
                    entry['voted'] = str(_actor(item, lobby)) in votes
        if lobby['status'] == 'night':
            result['can_advance'] = False  # a visible «all acted» would give away who is still alive
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
    if ready_count(lobby) < MIN_PLAYERS:
        raise ValueError('Нужны минимум четыре готовых игрока.')
    if start_requires_all_ready(lobby) and ready_count(lobby) != len(lobby['players']):
        raise ValueError('Начать можно, когда готовы все сидящие.')
    if not next(item for item in lobby['players'] if _actor(item, lobby) == actor_id)['ready']:
        raise ValueError('Сначала отметь себя готовым.')
    # Seated but not ready: they do not enter this game and wait for the next one.
    sitting_out = [item for item in lobby['players'] if not item['ready']]
    if sitting_out:
        lobby['players'] = [item for item in lobby['players'] if item['ready']]
        lobby['waiting'] = [{'account_id': item['account_id'], 'name': item['name'],
                             **({'portrait': item['portrait']} if item.get('portrait') else {})}
                            for item in sitting_out] + list(lobby.get('waiting', []))
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
                  room_id: str | None = None, account_id: str | None = None,
                  active_accounts: set | None = None) -> dict:
    lobby = normalized_lobby(current, chat_id=chat_id, room_id=room_id)
    if lobby is None:
        raise LookupError('Стол не найден.')
    actor_id = str(UUID(str(account_id))) if account_id is not None else None
    if _host(lobby) != actor_id:
        raise PermissionError('Реванш может начать только ведущий стола.')
    if lobby['status'] != 'finished':
        raise ValueError('Текущая партия ещё не завершена.')
    _expect_revision(lobby, expected_revision)
    host = _host(lobby)
    # Finished roster first, then those who waited. ``active_accounts`` (room members) filters both;
    # whoever does not fit into MAX_PLAYERS keeps waiting for the next table.
    people = [{'account_id': _actor(player, lobby), 'name': player['name'],
               'portrait': player.get('portrait')} for player in lobby['players']]
    people += [{'account_id': item['account_id'], 'name': item['name'], 'portrait': item.get('portrait')}
               for item in lobby.get('waiting', [])]
    if active_accounts is not None:
        people = [item for item in people if item['account_id'] == host or item['account_id'] in active_accounts]
    seated, overflow = people[:MAX_PLAYERS], people[MAX_PLAYERS:]
    taken = set()
    players = []
    for index, item in enumerate(seated):
        portrait = item['portrait'] if _valid_portrait(item['portrait']) and item['portrait'] not in taken else None
        if portrait is None:
            portrait = _free_portrait(taken, index)
        if portrait is not None:
            taken.add(portrait)
        players.append({'account_id': item['account_id'], 'name': item['name'], 'ready': False,
                        'portrait': portrait})
    result = {
        'mode': 'mafia_lobby',
        'host_account_id': host,
        'status': 'lobby',
        'room_id': room_id or lobby['room_id'],
        'state_version': 2,
        'revision': lobby['revision'] + 1,
        'phase_revision': lobby['phase_revision'] + 1,
        'players': players,
    }
    if overflow:
        result['waiting'] = [{'account_id': item['account_id'], 'name': item['name']} for item in overflow]
    if lobby.get('world'):
        result['world'] = lobby['world']
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
        raise PermissionError('Вы не участвуете в этой партии.')
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
    if role == 'mafia':
        # Only mafia sees this: whom each teammate has already chosen tonight (None until then).
        picks = (lobby.get('night_actions', {}).get('mafia') or {}) if lobby['status'] == 'night' else {}
        names = {_actor(item, lobby): item['name'] for item in lobby['players']}
        result['teammates'] = [
            {'seat': _seat(lobby, _actor(item, lobby)), 'name': item['name'],
             # Only a living teammate's pick is shown (a dead one's is moot and could mislead).
             'target_name': (names.get(picks.get(str(_actor(item, lobby))))
                             if _actor(item, lobby) in lobby.get('alive', []) else None)}
            for item in lobby['players']
            if _actor(item, lobby) != actor_id and lobby['assignments'][str(_actor(item, lobby))] == 'mafia'
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
    lobby['round_active'] = True
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
    if not allow_incomplete and not phase_due(lobby, now=now):
        # No manual or early end of the night: the moment it ends must not tell the table who is still alive.
        raise ValueError('Ночь закончится по таймеру.')
    actions = lobby['night_actions']
    # A target who vanished from the table meanwhile (left the room) cannot be a victim.
    victim = _majority([target for target in (actions.get('mafia') or {}).values()
                        if target in lobby['alive']])
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
    if not phase_due(lobby, now=now):
        lobby['round_active'] = True  # the host opened the vote before the timer: someone is at the table
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
    lobby['round_active'] = True
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
    eliminated = _majority([target for target in lobby['votes'].values() if target in lobby['alive']])
    if eliminated in lobby['alive']:
        lobby['alive'].remove(eliminated)
    lobby.setdefault('history', []).append({'type': 'vote_result', 'round': lobby['round'],
                                            'eliminated': _seat(lobby, eliminated) if eliminated else None})
    lobby['winner'] = _winner(lobby)
    lobby['idle_rounds'] = 0 if lobby.get('round_active') or not allow_incomplete else lobby.get('idle_rounds', 0) + 1
    lobby['round_active'] = False
    if lobby['winner']:
        lobby['status'] = 'finished'
        lobby['phase_deadline'] = None
    elif lobby['idle_rounds'] >= IDLE_ROUNDS_LIMIT:
        lobby['status'] = 'finished'
        lobby['phase_deadline'] = None
        lobby['history'].append({'type': 'abandoned', 'round': lobby['round']})
    else:
        lobby['round'] += 1
        lobby['status'] = 'night'
        lobby['night_actions'], lobby['votes'] = {}, {}
        lobby['phase_deadline'] = _deadline(now, NIGHT_SECONDS)
    lobby['revision'] += 1
    lobby['phase_revision'] += 1
    return lobby
