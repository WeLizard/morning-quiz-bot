from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from application import farm_village_games as games
from domain import farm_pie
from qw_farm import festivals, progression
from qw_farm.domain import FarmError, new_farm, validate_state
from qw_farm.expansion import upgrade_state

FAIR = int(datetime(2026, 11, 27, 12, tzinfo=timezone(timedelta(hours=3))).timestamp())
GAME = 'agata_pie'


def farm(at=FAIR):
    f = upgrade_state(new_farm(str(uuid4()), 'Пирог', at))
    progression.touch(f, at)
    return f


def solve(plan, layers=8):
    log = []
    start = 0
    lo = farm_pie.TOWER_CENTER - plan['base'] // 2
    hi = farm_pie.TOWER_CENTER + plan['base'] // 2
    for height in range(layers):
        center = (lo + hi) // 2
        best = None
        for t in range(start, min(plan['limit_ms'], start + 3000), 10):
            x = farm_pie.crane_x(plan, t, height)
            distance = abs(x - center)
            if best is None or distance < best[0]:
                best = (distance, t)
        t = best[1]
        log.append(t)
        landed = farm_pie.drop(lo, hi, farm_pie.crane_x(plan, t, height), plan['base'])
        if landed is None:
            break
        lo, hi = landed
        start = t + plan['min_gap_ms']
    return log


def start(f, now=FAIR):
    games.command(f, 'vgame_start', {'game': GAME}, now)
    return f['village_games'][GAME]['run']


def finish(f, run, log, now=None):
    now = now or run['started_at'] + (log[-1] // 1000 if log else 0) + 2
    return games.command(f, 'vgame_finish', {'game': GAME, 'run_id': run['id'], 'log': log}, now)


def test_start_is_fair_only_and_public_has_the_fair_key():
    f = farm()
    with pytest.raises(FarmError, match='ярмарк'):
        start(f, FAIR + 20 * 86400)
    run = start(f)
    assert run['practice'] is False and run['plan']['version'] == 1
    view = games.public(f, FAIR)[GAME]
    assert view['available'] is True and view['fair_key'] == 'posidelki-2026'
    assert view['attempts'] == 1 and view['attempts_left'] == 2 and view['active']['run_id'] == run['id']
    assert view['active']['plan'] == run['plan']


def test_finish_records_height_best_contribution_and_participation():
    f = farm()
    coins, xp = f['coins'], f['xp']
    run = start(f)
    log = solve(run['plan'])
    notice, changed = finish(f, run, log)
    assert changed is True and 'Лучшая высота' in notice
    state = f['village_games'][GAME]
    assert state['best'] == len(log) and state['contributed'] == len(log)
    assert state['run'] is None and state['last_result']['height'] == len(log)
    assert state['last_result']['miss'] is False
    assert f['festivals']['posidelki-2026']['tower'] is True
    assert f['coins'] == coins and f['xp'] == xp
    validate_state(f)
    assert finish(f, run, log, run['started_at'] + 5)[1] is False


def test_three_attempts_then_practice_does_not_move_the_best():
    f = farm()
    best = 0
    for i in range(3):
        run = start(f, FAIR + 60 * i)
        log = solve(run['plan'])
        finish(f, run, log)
        best = max(best, len(log))
    assert f['village_games'][GAME]['attempts'] == 3
    before = f['village_games'][GAME]['best']
    run = start(f, FAIR + 240)
    assert run['practice'] is True
    log = solve(run['plan'], layers=12)
    finish(f, run, log)
    assert f['village_games'][GAME]['best'] == before
    assert f['village_games'][GAME]['contributed'] == before
    assert best == before
    tomorrow = FAIR + 86400 - 12 * 3600  # the next Moscow midnight after FAIR is +12 h
    run = start(f, tomorrow)
    assert run['practice'] is False and f['village_games'][GAME]['attempts'] == 1


def test_bad_logs_and_miss_are_rejected_or_counted_honestly():
    f = farm()
    run = start(f)
    with pytest.raises(FarmError, match='журнал'):
        finish(f, run, [0, 1], run['started_at'] + 5)
    with pytest.raises(FarmError, match='Дождись'):
        finish(f, run, [5000], run['started_at'])
    log = [0, 60001]
    with pytest.raises(FarmError, match='журнал'):
        finish(f, run, log, run['started_at'] + 70)
    first = max(range(0, run['plan']['limit_ms'], 10), key=lambda t: farm_pie.crane_x(run['plan'], t, 0))
    landed = farm_pie.drop(farm_pie.TOWER_CENTER - 280, farm_pie.TOWER_CENTER + 280,
                           farm_pie.crane_x(run['plan'], first, 0), 560)
    assert landed is not None
    second = min(range(first + run['plan']['min_gap_ms'], run['plan']['limit_ms'], 10),
                 key=lambda t: farm_pie.crane_x(run['plan'], t, 1))
    result = farm_pie.replay(run['plan'], [first, second])
    assert result['miss'] is True and result['height'] == 1
    notice, changed = finish(f, run, [first, second])
    assert changed is True and 'упала' in notice
    assert f['village_games'][GAME]['best'] == 1
