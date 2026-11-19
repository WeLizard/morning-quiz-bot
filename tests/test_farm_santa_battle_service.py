"""«Битва с Сантой» on the farm: dates, unlocks, the «Корзинка», festival rewards, idempotency and the service ledger."""
import asyncio
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from application import farm_santa_battle as battle_app
from application import farm_village_games as games
from domain import farm_santa_battle as sb
from qw_farm import progression
from qw_farm.catalog import LEVELS
from qw_farm.domain import FarmError, new_farm, validate_state
from qw_farm.expansion import upgrade_state

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import farm_santa_battle_sim as sim  # noqa: E402

GAME = 'santa_battle'
KEY = 'new_year-2027'


def ts(y, m, d, h=12):
    return int(datetime(y, m, d, h, tzinfo=timezone(timedelta(hours=3))).timestamp())


DEC21, DEC26, JAN02 = ts(2026, 12, 21), ts(2026, 12, 26), ts(2027, 1, 2)


def farm(lv=5, at=DEC21, inv=None):
    f = upgrade_state(new_farm(str(uuid4()), 'Битва', at))
    f['xp'] = LEVELS[lv - 1]
    f['inventory'].update(inv or {})
    progression.touch(f, at)
    return f


def code(fn):
    with pytest.raises(FarmError) as err:
        fn()
    return err.value.code


def start(f, n, now):
    return games.command(f, 'vgame_start', {'game': GAME, 'battle': n}, now)


def run_of(f):
    return f['village_games'][GAME]['run']


def play(plan, bot='skilled'):
    state = sb.new_state(plan)
    log = []
    make = sim.BOTS[bot](random.Random(1))
    while state['outcome'] is None:
        entry = make(plan, state)
        log.append(entry)
        sb.act(plan, state, entry)
    return log, state


def finish(f, run, log, now=None):
    now = now or run['started_at'] + len(log) + 5
    return games.command(f, 'vgame_finish', {'game': GAME, 'run_id': run['id'], 'log': log}, now)


def test_battle_opens_with_the_new_year_level_dates_and_wins():
    assert code(lambda: start(farm(lv=4), 1, DEC21)) == 'locked'
    assert code(lambda: start(farm(at=ts(2026, 12, 10)), 1, ts(2026, 12, 10))) == 'festival_closed'
    assert code(lambda: start(farm(at=ts(2027, 1, 20)), 1, ts(2027, 1, 20))) == 'festival_closed'
    f = farm()
    assert code(lambda: start(f, 2, DEC21)) == 'battle_closed'
    assert code(lambda: start(f, 2, DEC26)) == 'battle_locked'
    assert code(lambda: games.command(f, 'vgame_start', {'game': GAME}, DEC21)) == 'invalid_command'
    assert code(lambda: games.command(f, 'vgame_start', {'game': GAME, 'battle': 4}, DEC21)) == 'invalid_command'
    view = games.public(f, DEC21)[GAME]
    assert view['available'] and not view['locked'] and view['min_level'] == 5
    assert [b['open'] for b in view['battles']] == [True, False, False]
    assert view['battles'][1]['opens_at'] == ts(2026, 12, 25, 0)
    assert games.public(farm(lv=4), DEC21)[GAME]['locked']


def test_first_win_gives_the_festival_item_once_and_unlocks_the_next_battle():
    f = farm()
    assert start(f, 1, DEC21) == ('Бой 1: Крампус! Дед Мороз и Снегурочка рядом.', True)
    run = run_of(f)
    log, state = play(run['plan'])
    text, changed = finish(f, run, log)
    assert changed and 'Колокольчик Крампуса' in text
    game = f['village_games'][GAME]
    assert game['best'] == [3, 0, 0] and game['rounds'][0] == state['round'] and game['run'] is None
    assert game['last_result']['reward'] == 'fest_ny_krampus_bell' and game['last_result']['outcome'] == 'win'
    assert f['festivals'][KEY]['rewards'] == {'fest_ny_krampus_bell': 1}
    validate_state(f)
    # the same run again: nothing changes, even through a new command id
    assert finish(f, run, log) == ('Результат уже учтён.', False)
    # a rematch keeps only the record
    start(f, 1, DEC21 + 3600)
    run = run_of(f)
    log, _ = play(run['plan'], 'calm')
    text, _ = finish(f, run, log)
    assert 'коллекции' not in text and f['village_games'][GAME]['best'] == [3, 0, 0]
    assert f['village_games'][GAME]['last_result']['reward'] is None and f['village_games'][GAME]['fights'] == 2
    assert games.public(f, DEC26)[GAME]['battles'][1]['open'] is True
    start(f, 2, DEC26)
    assert run_of(f)['battle'] == 2 and run_of(f)['plan']['battle'] == 2


def test_basket_items_leave_the_barn_win_or_lose_and_a_missing_item_voids_the_battle():
    f = farm(inv={'pie': 1, 'honey': 1})
    start(f, 1, DEC21)
    run = run_of(f)
    plan = run['plan']
    state = sb.new_state(plan)
    log = [['player', 'honey', 'player', None], ['ded_moroz', 'pie', 'ded_moroz', None]]
    for entry in log:
        sb.act(plan, state, entry)
    while state['outcome'] is None:
        entry = sim.naive(plan, state)
        log.append(entry)
        sb.act(plan, state, entry)
    finish(f, run, log)
    assert f['inventory'].get('pie', 0) == 0 and f['inventory'].get('honey', 0) == 0
    assert f['village_games'][GAME]['last_result']['items'] == {'honey': 1, 'pie': 1}
    validate_state(f)
    # the barn has no pie any more: the same plan with a pie is not counted, nothing is taken, no record
    start(f, 1, DEC21 + 7200)
    run = run_of(f)
    plan = run['plan']
    state = sb.new_state(plan)
    log = [['player', 'pie', 'player', None]]
    sb.act(plan, state, log[0])
    while state['outcome'] is None:
        entry = sim.smart(plan, state, True, False)
        log.append(entry)
        sb.act(plan, state, entry)
    text, changed = finish(f, run, log)
    assert changed and 'не засчитан' in text
    last = f['village_games'][GAME]['last_result']
    assert last['outcome'] == 'basket' and last['reward'] is None and last['items'] == {'pie': 1}
    validate_state(f)


def test_lose_expiry_bad_logs_and_switching_battles():
    f = farm(at=JAN02)
    f['village_games'] = {}
    f['village_games'][GAME] = dict(battle_app.blank(KEY), best=[2, 2, 0], rounds=[6, 9, 0])
    start(f, 3, JAN02)
    run = run_of(f)
    log, state = play(run['plan'], 'naive')
    assert state['outcome'] == 'lose'
    assert code(lambda: finish(f, run, log[:-1])) == 'invalid_log'
    assert code(lambda: finish(f, run, [['player', 'staff', 'krampus', None]])) == 'invalid_log'
    assert code(lambda: finish(f, run, 'log')) == 'invalid_log'
    assert code(lambda: finish(f, run, log, run['started_at'] + 1)) == 'too_fast'
    assert code(lambda: games.command(f, 'vgame_finish', {'game': GAME, 'run_id': 'x' * 36, 'log': log}, JAN02 + 99)) == 'run_not_found'
    text, _ = finish(f, run, log)
    assert 'сильнее' in text and f['village_games'][GAME]['last_result']['outcome'] == 'lose'
    assert f['village_games'][GAME]['best'] == [2, 2, 0]
    # the same battle continues, another battle replaces the run
    start(f, 3, JAN02 + 100)
    first = run_of(f)['id']
    assert start(f, 3, JAN02 + 120) == ('Продолжай бой.', False) and run_of(f)['id'] == first
    start(f, 1, JAN02 + 130)
    assert run_of(f)['battle'] == 1 and run_of(f)['id'] != first
    # a run left for longer than its TTL expires
    run = run_of(f)
    log, _ = play(run['plan'])
    assert finish(f, run, log, run['expires_at']) == ('Время боя вышло. Начни новый.', True)
    assert f['village_games'][GAME]['last_result']['outcome'] == 'expired' and run_of(f) is None
    validate_state(f)


def test_validate_refuses_a_broken_state():
    f = farm()
    start(f, 1, DEC21)
    validate_state(f)
    f['village_games'][GAME]['best'] = [4, 0, 0]
    assert code(lambda: validate_state(f)) == 'invalid_state'


def test_the_service_writes_one_receipt_per_battle():
    from qw_farm.service import FarmService, Principal
    from tests.test_farm_economy_r9 import SharedUnit, SharedVillage

    async def run():
        f = farm(inv={'pie': 2})
        f['name'] = 'santa'
        unit = SharedUnit('santa', f, SharedVillage(goal=10 ** 9))
        now = [DEC21]
        service = FarmService(unit, Principal('santa', 'santa'), clock=lambda: now[0])
        started = await service.command('santa-start-0001', 'vgame_start', {'game': GAME, 'battle': 1})
        active = started['village_games'][GAME]['active']
        assert active['battle'] == 1 and active['plan']['zones']
        log, _ = play(active['plan'])
        now[0] = active['started_at'] + len(log) + 3
        data = {'game': GAME, 'run_id': active['run_id'], 'log': log}
        first = await service.command('santa-finish-0001', 'vgame_finish', data)
        assert 'Колокольчик Крампуса' in first['notice']
        again = await service.command('santa-finish-0002', 'vgame_finish', data)
        assert again['notice'] == 'Результат уже учтён.'
        assert ('vgame:' + active['run_id'], 'vgame_santa') in unit.records
        assert sum(kind == 'vgame_santa' for _, kind in unit.records) == 1
        view = await service.view()
        assert 'fest_ny_krampus_bell' in view['farm']['festival']['collection']
        assert view['farm']['village_games'][GAME]['battles'][0]['reward']['got'] is True
    asyncio.run(run())
