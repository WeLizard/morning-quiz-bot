#!/usr/bin/env python3
"""mafia_seat.py - one seat at a "Night City" (Mafia) table, for AI players.

README (for an AI player)
=========================
You play Mafia as an ordinary guest player in a web room of the sandbox
(default https://quiz.mr-lizard.ru, override with --base or MAFIA_BASE).
One seat = one guest account = one state file in .local/mafia-seats/<seat>.json
(session cookie inside; it is never printed). Every command prints ONE JSON
object to stdout; on error: {"ok": false, "error": {...}} and exit code 1.
You cannot sleep, so use `wait` - it blocks (polling the server every 3 s).

Note: `wait` may return at once, right after your own action (the table
changed because of you) - just call it again.

Pass `--seat NAME` to every command (or set MAFIA_SEAT; if only one seat file
exists it is picked automatically). `--seat` defaults to the --name of `start`.

Setup (each player once)
  python scripts/mafia_seat.py start --name "ИИ-1"       # guest account + display name
  python scripts/mafia_seat.py create-room                # host only: new room
  python scripts/mafia_seat.py invite                     # host only: prints invite_code
  python scripts/mafia_seat.py join CODE                  # others: enter room by code
  python scripts/mafia_seat.py lobby-create               # host only: open the table
  python scripts/mafia_seat.py sit                        # take a place at the table
  python scripts/mafia_seat.py ready                      # mark ready (4-12 players)
  python scripts/mafia_seat.py begin                      # host only, when all are ready

The display name is copied to the table at `sit`, so run `start --name` first.

Game loop (repeat until phase == "finished")
  1. python scripts/mafia_seat.py wait --timeout 240   # returns on phase change / my turn
  2. read the JSON: phase, role, knowledge, players, available, chat
  3. decide and do what `available` lists:
       act TARGET     night: mafia kills, doctor protects, detective checks
       vote TARGET    voting phase: whom the town removes
       say "text"     lobby and day phase: public discussion (<= 1000 chars)
       advance        host only: close the phase now (the deadline worker
                      also does it by itself when time runs out)
     TARGET = player name from `players` or a seat like p3 (or just 3).
  4. go back to 1. `status` shows the same JSON without blocking.

Rules in short: 4-12 players; mafia 1 (<=6 players), 2 (7-9), 3 (10-12);
5+ players add a detective, 7+ a doctor, the rest are citizens. Night 90 s,
day 180 s, voting 90 s. Citizens win when the mafia is gone; mafia wins when
it equals or outnumbers the others. Dead players do not vote; roles of dead
players are not revealed. Your own role and detective results are in `me`.
A tie in the vote eliminates nobody. A phase can end early on its deadline,
so act promptly; an action sent too late is rejected (error is explained).

Privacy: the server shows you only your own role (and your mafia teammates are
NOT shown to you; mafia only sees which targets it may pick). `status`
never contains other players' roles.

Environment: MAFIA_BASE (server), MAFIA_SEATS_DIR (state dir), MAFIA_SEAT.
Only the standard library is used (Python 3.11+).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import uuid
from email.utils import parsedate_to_datetime
from pathlib import Path

DEFAULT_BASE = 'https://quiz.mr-lizard.ru'
ROOT = Path(__file__).resolve().parent.parent
POLL_SECONDS = 3.0
COOKIE_NAME = 'mqb_guest'


class SeatError(Exception):
    def __init__(self, message, http=None, code=None, extra=None):
        super().__init__(message)
        self.message, self.http, self.code, self.extra = message, http, code, extra or {}

    def payload(self):
        err = {'message': self.message}
        if self.http is not None:
            err['http'] = self.http
        if self.code:
            err['code'] = self.code
        err.update(self.extra)
        return {'ok': False, 'error': err}


# ---------------------------------------------------------------- state file
def seats_dir() -> Path:
    return Path(os.environ.get('MAFIA_SEATS_DIR') or ROOT / '.local' / 'mafia-seats')


def safe_name(value: str) -> str:
    cleaned = re.sub(r'[^\w.-]+', '_', value.strip(), flags=re.UNICODE).strip('_.')
    return cleaned[:60] or 'seat'


class Seat:
    def __init__(self, seat_id: str, base: str | None = None):
        self.seat_id = safe_name(seat_id)
        self.path = seats_dir() / f'{self.seat_id}.json'
        self.data = {}
        if self.path.exists():
            self.data = json.loads(self.path.read_text(encoding='utf-8'))
        if base:
            self.data['base'] = base.rstrip('/')
        self.data.setdefault('base', (os.environ.get('MAFIA_BASE') or DEFAULT_BASE).rstrip('/'))
        self.clock_offset = 0.0

    @property
    def base(self):
        return self.data['base']

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix('.tmp')
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding='utf-8')
        os.replace(tmp, self.path)

    # ---------------------------------------------------------------- http
    def request(self, method, path, body=None, *, idem=None, tries=4):
        url = self.base + path
        headers = {'Accept': 'application/json', 'Origin': self.base,
                   'X-Guest-CSRF': '1', 'User-Agent': 'mafia-seat/1.0'}
        if self.data.get('cookie'):
            headers['Cookie'] = f"{COOKIE_NAME}={self.data['cookie']}"
        payload = None
        if method != 'GET':
            payload = json.dumps(body if body is not None else {}, ensure_ascii=False).encode('utf-8')
            headers['Content-Type'] = 'application/json'
            # One key for all retries of this command: the server dedupes it.
            headers['Idempotency-Key'] = idem or uuid.uuid4().hex
        last = None
        for attempt in range(tries):
            req = urllib.request.Request(url, data=payload, headers=headers, method=method)
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    self._note_response(resp)
                    raw = resp.read()
                    return json.loads(raw) if raw else {}
            except urllib.error.HTTPError as err:
                raw = err.read()
                try:
                    detail = json.loads(raw)
                except ValueError:
                    detail = {}
                message = detail.get('detail') or detail.get('message') or f'HTTP {err.code}'
                if not isinstance(message, str):
                    message = json.dumps(message, ensure_ascii=False)
                if err.code == 429 and attempt < tries - 1:
                    wait = min(float(err.headers.get('Retry-After') or 20), 65)
                    print(f'[mafia_seat] 429 rate limit, sleeping {wait:.0f}s', file=sys.stderr, flush=True)
                    time.sleep(wait)
                    continue
                if err.code >= 500 and attempt < tries - 1:
                    time.sleep(2 + attempt * 2)
                    last = err.code
                    continue
                raise SeatError(message, http=err.code, code=detail.get('code')) from None
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as err:
                last = str(getattr(err, 'reason', err))
                time.sleep(2 + attempt * 2)
        raise SeatError(f'Сервер недоступен: {last}', http=None)

    def _note_response(self, resp):
        date = resp.headers.get('Date')
        if date:
            try:
                self.clock_offset = parsedate_to_datetime(date).timestamp() - time.time()
            except (TypeError, ValueError):
                pass
        cookie = resp.headers.get_all('Set-Cookie') or []
        for item in cookie:
            match = re.match(rf'{COOKIE_NAME}=([^;]+)', item)
            if match:
                self.data['cookie'] = match.group(1)

    def server_now(self):
        return time.time() + self.clock_offset

    # ---------------------------------------------------------------- api
    def room_path(self, suffix=''):
        room = self.data.get('room_id')
        if not room:
            raise SeatError('Нет комнаты: сначала create-room (хост) или join CODE.')
        return f'/api/guest/rooms/{room}{suffix}'

    def lobby(self):
        return self.request('GET', self.room_path('/mafia/lobby')).get('lobby')

    def role(self):
        try:
            return self.request('GET', self.room_path('/mafia/role'))
        except SeatError as err:
            if err.http in (404, 409):
                return None
            raise

    def chat(self, limit=10):
        try:
            items = self.request('GET', self.room_path('/mafia/discussion')).get('items', [])
        except SeatError as err:
            if err.http in (403, 404):
                return []
            raise
        return [{'author': i['author'], 'me': bool(i.get('is_me')), 'text': i['message']}
                for i in items[-limit:]]


# ------------------------------------------------------------------- status
def phase_of(lobby):
    return lobby['status'] if lobby else 'no_table'


def build_status(seat: Seat, lobby, role, chat=None):
    """Compact, role-safe description of the table from this seat's viewpoint."""
    out = {'ok': True, 'seat': seat.seat_id, 'room_id': seat.data.get('room_id'),
           'phase': phase_of(lobby)}
    if lobby is None:
        out['available'] = [{'action': 'lobby-create', 'note': 'host only'}]
        out['hint'] = 'Стол ещё не создан. Хост делает lobby-create; остальные ждут (wait).'
        return out
    players = lobby['players']
    names = {p['seat']: p['name'] for p in players}
    me = next((p for p in players if p.get('is_me')), None)
    out.update(round=lobby.get('round'), revision=lobby['revision'],
               phase_revision=lobby['phase_revision'], is_host=lobby['is_host'], joined=lobby['joined'])
    ends = lobby.get('ends_at')
    if ends and lobby['status'] != 'finished':
        out['seconds_left'] = int(ends - seat.server_now())
    out['players'] = [{'seat': p['seat'], 'name': p['name'], 'alive': p['alive'],
                       'is_me': p['is_me'], **({'ready': p['ready']} if lobby['status'] == 'lobby' else {})}
                      for p in players]
    out['alive'] = [p['name'] + f"({p['seat']})" for p in players if p['alive']]
    out['eliminated'] = [p['name'] + f"({p['seat']})" for p in players if not p['alive']]
    me_out = {'seat': me['seat'], 'name': me['name']} if me else None
    if role:
        me_out = {'seat': role['seat'], 'name': me['name'] if me else None, 'role': role['role'],
                  'role_title': role['title'], 'alive': role['alive']}
        if 'acted' in role:
            me_out['acted'] = role['acted']
        if 'voted' in role:
            me_out['voted'] = role['voted']
        know = seat.data.setdefault('knowledge', [])
        inv = role.get('investigation')
        if inv and not any(k['round'] == inv['round'] for k in know):
            know.append({'round': inv['round'], 'seat': inv['seat'], 'name': names.get(inv['seat']),
                         'is_mafia': inv['is_mafia']})
        if role['role'] == 'detective':
            me_out['knowledge'] = [
                {'night': k['round'], 'player': f"{k['name']}({k['seat']})",
                 'result': 'МАФИЯ' if k['is_mafia'] else 'не мафия'} for k in know]
    out['me'] = me_out
    history = []
    for ev in lobby.get('history', []):
        who = names.get(ev.get('eliminated'))
        if ev['type'] == 'night_result':
            text = (f"Ночь {ev['round']}: убит {who}({ev['eliminated']})" if who
                    else f"Ночь {ev['round']}: " + ('доктор спас жертву' if ev.get('saved') else 'без потерь'))
        elif ev['type'] == 'vote_result':
            text = (f"Голосование {ev['round']}: выбыл {who}({ev['eliminated']})" if who
                    else f"Голосование {ev['round']}: никто не выбыл")
        else:
            text = 'Партия началась'
        history.append(text)
    out['history'] = history[-8:]
    if lobby.get('winner'):
        out['winner'] = lobby['winner']
        out['winner_title'] = 'Город (мирные)' if lobby['winner'] == 'citizens' else 'Мафия'
    if lobby['status'] == 'voting':
        out['votes_cast'], out['votes_needed'] = lobby.get('votes_cast'), lobby.get('votes_needed')
    out['available'] = available_actions(lobby, role, me)
    if chat is not None:
        out['chat'] = chat
    if lobby['status'] == 'finished':
        out['hint'] = 'Партия окончена.' + (' Хост может сделать restart.' if lobby['is_host'] else '')
    elif out.get('seconds_left', 1) < 0:
        out['hint'] = 'Дедлайн фазы прошёл: воркер вот-вот переведёт её; хост может сделать advance.'
    return out


def available_actions(lobby, role, me):
    acts, status = [], lobby['status']
    if not lobby['joined']:
        return [{'action': 'sit', 'note': 'сесть за стол (при заполненном/начатом столе сервер откажет)'}]
    if status == 'lobby':
        if me and not me['ready']:
            acts.append({'action': 'ready'})
        if lobby['is_host'] and lobby['can_start']:
            acts.append({'action': 'begin'})
        acts.append({'action': 'say', 'note': 'публичный чат'})
        return acts
    if status == 'finished':
        if lobby['is_host']:
            acts.append({'action': 'restart'})
        return acts
    if role and role['alive']:
        if status == 'night' and role['role'] != 'citizen' and not role.get('acted'):
            acts.append({'action': 'act', 'targets': [f"{t['name']}({t['seat']})" for t in role.get('targets', [])],
                         'note': {'mafia': 'выбрать жертву', 'doctor': 'кого защитить',
                                  'detective': 'кого проверить'}.get(role['role'])})
        if status == 'voting' and not role.get('voted'):
            acts.append({'action': 'vote', 'targets': [f"{t['name']}({t['seat']})" for t in role.get('targets', [])]})
    if status == 'day':
        acts.append({'action': 'say', 'note': 'публичное обсуждение'})
    if lobby.get('can_advance') and lobby['is_host']:
        acts.append({'action': 'advance', 'note': 'host: закрыть фазу сейчас (иначе по таймеру)'})
    return acts


def signature(lobby, role=None):
    if lobby is None:
        return ['none']
    me = next((p for p in lobby['players'] if p.get('is_me')), None)
    return [lobby['status'], lobby.get('round'), lobby['phase_revision'], lobby['joined'],
            bool(me and me['ready']), len(lobby['players']), bool(lobby.get('can_start')),
            bool(lobby['is_host'] and lobby.get('can_advance'))]


def snapshot(seat: Seat, chat=True, lobby=False):
    lob = seat.lobby() if lobby is False else lobby
    role = seat.role() if lob and lob['joined'] and lob['status'] != 'lobby' else None
    status = build_status(seat, lob, role, seat.chat() if chat and lob and lob['joined'] else None)
    seat.data['last_sig'] = signature(lob)
    seat.save()
    return status


def pending(status):
    return [a['action'] for a in status.get('available', []) if a['action'] not in ('say', 'advance')]


# ----------------------------------------------------------------- commands
def need_cookie(seat):
    if not seat.data.get('cookie'):
        raise SeatError('Нет сессии: сначала `start --name ...`.')


def cmd_start(args):
    seat = Seat(args.seat or args.name, args.base)
    if seat.data.get('cookie') and not args.force:
        try:
            seat.request('GET', '/api/guest/me')
            seat.request('POST', '/api/guest/profile', {'display_name': args.name})
            seat.data['name'] = args.name
            seat.save()
            return {'ok': True, 'seat': seat.seat_id, 'name': args.name, 'reused': True,
                    'room_id': seat.data.get('room_id')}
        except SeatError:
            pass
    seat.data = {'base': seat.base}
    seat.request('POST', '/api/guest/start', {})
    if not seat.data.get('cookie'):
        raise SeatError('Сервер не выдал гостевую сессию.')
    seat.request('POST', '/api/guest/profile', {'display_name': args.name})
    seat.data['name'] = args.name
    seat.save()
    return {'ok': True, 'seat': seat.seat_id, 'name': args.name, 'base': seat.base}


def cmd_create_room(seat, args):
    need_cookie(seat)
    room = seat.request('POST', '/api/guest/rooms', {'request_id': str(uuid.uuid4()), 'title': args.title})
    seat.data.update(room_id=room['id'], knowledge=[])
    seat.save()
    return {'ok': True, 'room_id': room['id'], 'title': room['title'], 'role': room['role']}


def cmd_invite(seat, args):
    need_cookie(seat)
    inv = seat.request('POST', seat.room_path('/invites'),
                       {'expires_in_seconds': args.ttl, 'max_uses': args.uses})
    return {'ok': True, 'invite_code': inv['invite_code'], 'expires_at': inv['expires_at'],
            'max_uses': inv['max_uses']}


def cmd_join(seat, args):
    need_cookie(seat)
    room = seat.request('POST', '/api/guest/rooms/join', {'invite_code': args.code.strip()})
    seat.data.update(room_id=room['id'], knowledge=[])
    seat.save()
    return {'ok': True, 'room_id': room['id'], 'title': room.get('title'), 'role': room.get('role')}


def cmd_lobby_create(seat, args):
    need_cookie(seat)
    seat.request('POST', seat.room_path('/mafia/lobby'), {})
    return {'ok': True, 'phase': 'lobby'}


def cmd_sit(seat, args):
    need_cookie(seat)
    seat.request('POST', seat.room_path('/mafia/lobby/join'), {})
    return {'ok': True, 'phase': 'lobby'}


def revision_retry(call, tries=3):
    for attempt in range(tries):
        try:
            return call()
        except SeatError as err:
            if err.http == 409 and 'изменилось' in err.message and attempt < tries - 1:
                continue
            raise


def cmd_ready(seat, args):
    need_cookie(seat)

    def call():
        lobby = seat.lobby()
        if lobby is None:
            raise SeatError('Стол ещё не создан.')
        return seat.request('POST', seat.room_path('/mafia/lobby/ready'),
                            {'ready': not args.off, 'expected_revision': lobby['revision']})
    revision_retry(call)
    return {'ok': True, 'ready': not args.off}


def cmd_begin(seat, args):
    need_cookie(seat)

    def call():
        lobby = seat.lobby()
        if lobby is None:
            raise SeatError('Стол ещё не создан.')
        return seat.request('POST', seat.room_path('/mafia/lobby/start'),
                            {'expected_revision': lobby['revision']})
    revision_retry(call)
    return {'ok': True, 'phase': 'night'}


def resolve_target(token: str, targets: list[dict]):
    token = token.strip()
    low = token.casefold()
    seat_token = f'p{token}' if token.isdigit() else low
    for t in targets:
        if t['seat'] == seat_token:
            return t
    exact = [t for t in targets if t['name'].casefold() == low]
    if len(exact) == 1:
        return exact[0]
    part = [t for t in targets if low and low in t['name'].casefold()]
    if len(part) == 1:
        return part[0]
    names = [f"{t['name']}({t['seat']})" for t in targets]
    raise SeatError('Цель не найдена или неоднозначна' if token else 'Не указана цель',
                    extra={'allowed_targets': names})


def cmd_target(kind):
    def run(seat, args):
        need_cookie(seat)
        lobby = seat.lobby()
        role = seat.role() if lobby and lobby['joined'] else None
        if not role:
            raise SeatError('Роль появится после начала партии.')
        want = 'night' if kind == 'action' else 'voting'
        if role['phase'] != want:
            raise SeatError(f"Сейчас фаза {role['phase']}, а {kind} возможен только в фазе {want}.")
        if not role['alive']:
            raise SeatError('Ты выбыл из игры.')
        if kind == 'action' and role['role'] == 'citizen':
            raise SeatError('У мирного нет ночного действия: просто жди.')
        if role.get('acted') or role.get('voted'):
            raise SeatError('Выбор уже сделан в этой фазе.')
        target = resolve_target(args.target, role.get('targets', []))
        seat.request('POST', seat.room_path(f'/mafia/{kind}'),
                     {'target': target['seat'], 'expected_revision': role['phase_revision']})
        return {'ok': True, 'done': kind, 'target': f"{target['name']}({target['seat']})"}
    return run


def cmd_say(seat, args):
    need_cookie(seat)
    text = ' '.join(args.text).strip()
    result = seat.request('POST', seat.room_path('/mafia/discussion'), {'message': text})
    return {'ok': True, 'message_id': result.get('id')}


def cmd_advance(seat, args):
    need_cookie(seat)
    lobby = seat.lobby()
    if lobby is None:
        raise SeatError('Стол ещё не создан.')
    seat.request('POST', seat.room_path('/mafia/advance'), {'expected_revision': lobby['revision']})
    return {'ok': True, 'advanced_from': lobby['status']}


def cmd_restart(seat, args):
    need_cookie(seat)
    lobby = seat.lobby()
    if lobby is None:
        raise SeatError('Стол ещё не создан.')
    seat.request('POST', seat.room_path('/mafia/restart'), {'expected_revision': lobby['revision']})
    return {'ok': True, 'phase': 'lobby'}


def cmd_status(seat, args):
    need_cookie(seat)
    return snapshot(seat, chat=not args.no_chat)


def cmd_wait(seat, args):
    need_cookie(seat)
    started = time.monotonic()
    seen = seat.data.get('last_sig')          # what the player saw last time
    first = snapshot(seat)
    if pending(first) or first['phase'] == 'finished' or seen != seat.data['last_sig']:
        first['woke'] = 'action_available' if pending(first) else 'changed'
        return first
    base_sig = seat.data['last_sig']
    while time.monotonic() - started < args.timeout:
        time.sleep(args.interval)
        lobby = seat.lobby()
        if signature(lobby) != base_sig:
            status = snapshot(seat, lobby=lobby)
            status['woke'] = 'changed'
            return status
        if args.chat and lobby and lobby['joined']:
            if seat.chat() != first.get('chat'):
                status = snapshot(seat, lobby=lobby)
                status['woke'] = 'chat'
                return status
    status = snapshot(seat)
    status['woke'] = 'timeout'
    return status


COMMANDS = {
    'create-room': cmd_create_room, 'invite': cmd_invite, 'join': cmd_join,
    'lobby-create': cmd_lobby_create, 'sit': cmd_sit, 'ready': cmd_ready, 'begin': cmd_begin,
    'status': cmd_status, 'act': cmd_target('action'), 'vote': cmd_target('vote'),
    'say': cmd_say, 'advance': cmd_advance, 'restart': cmd_restart, 'wait': cmd_wait,
}


def build_parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument('--seat', default=None, help='имя файла места (по умолчанию env MAFIA_SEAT)')
    common.add_argument('--base', default=None, help=f'адрес сервера (по умолчанию {DEFAULT_BASE})')
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[1])
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('start', parents=[common], help='создать гостевой аккаунт с именем')
    p.add_argument('--name', required=True)
    p.add_argument('--force', action='store_true', help='создать новый аккаунт, даже если место уже есть')
    p = sub.add_parser('create-room', parents=[common])
    p.add_argument('--title', default='Ночной город (ИИ)')
    p = sub.add_parser('invite', parents=[common])
    p.add_argument('--ttl', type=int, default=3600, help='секунд жизни (300..)')
    p.add_argument('--uses', type=int, default=12)
    p = sub.add_parser('join', parents=[common])
    p.add_argument('code')
    for name in ('lobby-create', 'sit', 'begin', 'advance', 'restart'):
        sub.add_parser(name, parents=[common])
    p = sub.add_parser('ready', parents=[common])
    p.add_argument('--off', action='store_true', help='снять готовность')
    p = sub.add_parser('status', parents=[common])
    p.add_argument('--no-chat', action='store_true')
    for name in ('act', 'vote'):
        p = sub.add_parser(name, parents=[common])
        p.add_argument('target', help='имя игрока или место (p3 / 3)')
    p = sub.add_parser('say', parents=[common])
    p.add_argument('text', nargs='+')
    p = sub.add_parser('wait', parents=[common], help='блокировать до смены фазы / своего хода')
    p.add_argument('--timeout', type=float, default=240)
    p.add_argument('--interval', type=float, default=POLL_SECONDS)
    p.add_argument('--chat', action='store_true', help='просыпаться и от новых сообщений чата')
    return parser


def pick_seat_id(explicit):
    if explicit:
        return explicit
    if os.environ.get('MAFIA_SEAT'):
        return os.environ['MAFIA_SEAT']
    files = sorted(seats_dir().glob('*.json')) if seats_dir().exists() else []
    files = [f for f in files if not f.name.startswith('smoke-')]
    if len(files) == 1:
        return files[0].stem
    raise SeatError('Укажи --seat NAME (или MAFIA_SEAT).',
                    extra={'known_seats': [f.stem for f in files]})


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    args = build_parser().parse_args(argv)
    try:
        if args.command == 'start':
            result = cmd_start(args)
        else:
            seat = Seat(pick_seat_id(args.seat), args.base)
            result = COMMANDS[args.command](seat, args)
            seat.save()
    except SeatError as err:
        print(json.dumps(err.payload(), ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
