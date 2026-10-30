#!/usr/bin/env python3
"""End-to-end smoke test for scripts/mafia_seat.py on a sandbox.

Creates N guest seats (default 4), a room, an invite, sits everyone down,
starts a game and plays it to a winner with a random legal policy, going
through the real CLI code path (mafia_seat.main). Also checks projection
privacy: no seat may see another seat's role.

  python scripts/mafia_seat_smoke.py                 # host advances phases itself (fast)
  python scripts/mafia_seat_smoke.py --timers        # nobody advances: rely on the deadline worker
  python scripts/mafia_seat_smoke.py --players 6 --base https://quiz.mr-lizard.ru

Writes a step log to .local/mafia-seats/smoke-<timestamp>.log (stdout too).
Exit code 0 only when the game reached "finished" and the privacy checks passed.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mafia_seat as ms  # noqa: E402

LOG = None


def log(message):
    line = f"{time.strftime('%H:%M:%S')} {message}"
    print(line, flush=True)
    if LOG:
        LOG.write(line + '\n')
        LOG.flush()


def cli(seat_id, base, *argv):
    """Run the real CLI in-process; return (exit_code, parsed json)."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = ms.main([*argv, '--seat', seat_id, '--base', base])
    return code, json.loads(out.getvalue())


def step(seat_id, base, *argv, ok=True):
    code, data = cli(seat_id, base, *argv)
    shown = {k: v for k, v in data.items() if k not in ('chat', 'players', 'history', 'alive', 'eliminated')}
    if 'invite_code' in shown:
        shown['invite_code'] = shown['invite_code'][:6] + '...'
    log(f"{seat_id} :: {' '.join(argv)} -> {json.dumps(shown, ensure_ascii=False)[:230]}")
    if ok and code != 0:
        raise SystemExit(f'step failed: {data}')
    return data


def check_privacy(seats, base, roles):
    """No seat sees roles of others in any server response it can read."""
    problems = []
    for sid in seats:
        seat = ms.Seat(sid, base)
        lobby_raw = json.dumps(seat.request('GET', seat.room_path('/mafia/lobby')), ensure_ascii=False)
        chat_raw = json.dumps(seat.request('GET', seat.room_path('/mafia/discussion')), ensure_ascii=False)
        status = ms.snapshot(seat)
        status_raw = json.dumps(status, ensure_ascii=False)
        if 'assignments' in lobby_raw or '"role"' in lobby_raw or '"role"' in chat_raw:
            problems.append(f'{sid}: raw lobby/chat carries role data')
        if any('role' in p for p in status['players']):
            problems.append(f'{sid}: players list carries roles')
        if status.get('me', {}).get('role') != roles.get(sid):
            problems.append(f'{sid}: own role mismatch')
        # the status text must mention the "role" key only once (own role)
        if status_raw.count('"role"') > 1:
            problems.append(f'{sid}: status has several role keys')
        log(f'privacy {sid}: me.role={status.get("me", {}).get("role")} '
            f'role_keys_in_status={status_raw.count(chr(34) + "role" + chr(34))}')
    return problems


def main(argv=None):
    global LOG
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', default=os.environ.get('MAFIA_BASE') or ms.DEFAULT_BASE)
    parser.add_argument('--players', type=int, default=4)
    parser.add_argument('--timers', action='store_true', help='do not advance; wait for the deadline worker')
    parser.add_argument('--max-minutes', type=float, default=30)
    parser.add_argument('--seed', type=int, default=None)
    args = parser.parse_args(argv)
    rnd = random.Random(args.seed)
    base = args.base.rstrip('/')
    stamp = time.strftime('%Y%m%d-%H%M%S')
    ms.seats_dir().mkdir(parents=True, exist_ok=True)
    LOG = open(ms.seats_dir() / f'smoke-{stamp}.log', 'w', encoding='utf-8')
    seats = [f'smoke-{stamp}-{i + 1}' for i in range(args.players)]
    names = [f'ИИ-{i + 1}' for i in range(args.players)]
    host = seats[0]
    log(f'base={base} players={args.players} timers={args.timers}')

    for sid, name in zip(seats, names):
        step(sid, base, 'start', '--name', name)
    step(host, base, 'create-room', '--title', f'AI smoke {stamp}')
    code = step(host, base, 'invite', '--uses', str(args.players))['invite_code']
    step(host, base, 'lobby-create')
    for sid in seats[1:]:
        step(sid, base, 'join', code)
    for sid in seats[1:]:
        step(sid, base, 'sit')
    for sid in seats:
        step(sid, base, 'ready')
    st = step(host, base, 'status')
    assert any(a['action'] == 'begin' for a in st['available']), f'begin not offered: {st["available"]}'
    step(host, base, 'begin')

    roles = {}
    for sid in seats:
        roles[sid] = step(sid, base, 'status', '--no-chat')['me']['role']
    log(f'roles (for the log only): {roles}')
    privacy = check_privacy(seats, base, roles)

    deadline = time.monotonic() + args.max_minutes * 60
    done_marks = set()
    final = None
    while time.monotonic() < deadline:
        host_seat = ms.Seat(host, base)
        lobby = host_seat.lobby()
        phase = lobby['status']
        mark_base = (lobby.get('round'), lobby['phase_revision'])
        if phase == 'finished':
            final = lobby
            break
        if phase in ('night', 'voting'):
            for sid in seats:
                if (sid, mark_base) in done_marks:
                    continue
                seat = ms.Seat(sid, base)
                role = seat.role()
                done_marks.add((sid, mark_base))
                if not role or not role['alive']:
                    continue
                if phase == 'night' and role['role'] != 'citizen' and not role.get('acted'):
                    target = rnd.choice(role['targets'])
                    step(sid, base, 'act', target['name'] if rnd.random() < .5 else target['seat'])
                elif phase == 'voting' and not role.get('voted'):
                    target = rnd.choice(role['targets'])
                    step(sid, base, 'vote', target['seat'])
        elif phase == 'day' and ('say', mark_base) not in done_marks:
            done_marks.add(('say', mark_base))
            for sid in rnd.sample(seats, 2):
                step(sid, base, 'say', f'{sid[-1]}: подозреваю, что это не я', ok=False)
        if not args.timers:
            lobby = host_seat.lobby()
            if lobby['status'] == phase and lobby.get('can_advance') and (
                    phase != 'day' or ('said', mark_base) in done_marks or True):
                step(host, base, 'advance', ok=False)
        else:
            left = lobby.get('ends_at')
            log(f'timers mode: phase={phase} round={lobby.get("round")} '
                f'left={int(left - host_seat.server_now()) if left else None}s')
            time.sleep(10)
        time.sleep(1)
    else:
        log('TIMEOUT: game did not finish')
        return 2

    log(f'FINAL: winner={final["winner"]} round={final["round"]}')
    finals = {}
    for sid in seats:
        status = ms.snapshot(ms.Seat(sid, base))
        finals[sid] = (status['phase'], status.get('winner'))
        if sid == seats[0]:
            log('history: ' + ' | '.join(status['history']))
    if len(set(finals.values())) != 1 or next(iter(finals.values()))[0] != 'finished':
        log(f'MISMATCH in final views: {finals}')
        return 3
    # also verify the winner against the roles known to the log
    mafia_alive = sum(1 for p, sid in zip(final['players'], seats) if p['alive'] and roles[sid] == 'mafia')
    others_alive = sum(1 for p, sid in zip(final['players'], seats) if p['alive'] and roles[sid] != 'mafia')
    expected = 'citizens' if mafia_alive == 0 else 'mafia' if mafia_alive >= others_alive else None
    log(f'winner check: expected={expected} actual={final["winner"]}')
    privacy_ok = not privacy
    log('privacy: OK' if privacy_ok else f'privacy PROBLEMS: {privacy}')
    ok = privacy_ok and expected == final['winner']
    log('RESULT: PASS' if ok else 'RESULT: FAIL')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
