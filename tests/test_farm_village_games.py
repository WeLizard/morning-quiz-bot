from copy import deepcopy
import json
from pathlib import Path
from uuid import uuid4

import pytest

from domain import farm_ballista as physics
from application import farm_village_games as games
from qw_farm import progression
from qw_farm.domain import FarmError, new_farm, project
from qw_farm.expansion import upgrade_state

NOW = 1800000000
GAME = 'pukh_ballista'


def solve(plan):
    """Independent search over admissible controls, never uses a private seed."""
    log = []
    release = 600
    for target in plan['targets']:
        best = None
        for angle in range(15000, 75001, 2000):
            for power in range(200, 1001, 20):
                path = physics.trajectory(angle, power, target['wind'], target['roof'])
                distances = [(x-target['x'])**2+(y-target['y'])**2 for x,y in path]
                distance = min(distances)
                if best is None or distance < best[0]:
                    best = distance, angle, power, distances.index(distance)*40
                if distance == 0:
                    break
            if best[0] == 0:
                break
        assert best[0] <= target['radius']**2
        log.append([best[1], best[2], release])
        release += best[3]+600
    return log


def farm():
    f = upgrade_state(new_farm(str(uuid4()), 'Пух', NOW))
    progression.touch(f, NOW)
    return f


def start(f, now=NOW):
    games.command(f, 'vgame_start', {'game': GAME}, now)
    return f['village_games'][GAME]['run']


def finish(f, run, log, now=None):
    durations = physics.replay(run['plan'], log)[2]
    now = now or run['started_at']+(log[-1][2]+durations[-1]+999)//1000
    return games.command(f, 'vgame_finish', {'game':GAME,'run_id':run['id'],'log':log}, now)


def test_reachable_seeded_targets_and_shared_fixtures():
    for seed in range(12):
        plan = physics.make_plan(str(seed))
        assert plan == physics.make_plan(str(seed))
        log = solve(plan)
        score, hits, durations = physics.replay(plan, log)
        assert hits == 5 and score >= 900
        assert log[-1][2]+durations[-1] < physics.TTL*1000
    for fixture in json.loads((Path(__file__).parent/'fixtures/farm_ballista.json').read_text()):
        assert physics.make_plan(fixture['seed']) == fixture['plan']
        score, hits, durations = physics.replay(fixture['plan'], fixture['log'])
        assert (score,hits,durations) == (fixture['score'],fixture['hits'],fixture['durations'])


def test_three_attempts_best_only_practice_and_new_day():
    f = farm()
    run = start(f)
    log = solve(run['plan'])
    finish(f,run,log)
    paid = f['progress']['pool']
    assert paid == progression.pace(1)*3//100 and f['xp'] == 0
    assert finish(f,run,log)[1] is False
    for i in range(2):
        run = start(f,NOW+60*(i+1))
        finish(f,run,solve(run['plan']))
    assert f['progress']['pool'] == paid
    run = start(f,NOW+180)
    assert run['practice']
    finish(f,run,solve(run['plan']))
    assert f['progress']['pool'] == paid
    tomorrow = (progression.moscow_day(NOW)+1)*86400-10800
    assert not start(f,tomorrow)['practice']
    assert f['village_games'][GAME]['attempts'] == 1


def test_frozen_fallback_level_and_no_xp_award():
    f = farm()
    f['progress']['pool'] = progression.status(f,NOW)['pool_cap']
    run = start(f)
    state = f['village_games'][GAME]
    assert state['reward_kind'] == 'premium'
    base = state['reward_base']
    f['xp'] = 100000
    f['progress']['pool'] = 0
    before = f['coins']
    finish(f,run,solve(run['plan']))
    assert f['coins'] == before+base and f['xp'] == 100000
    assert state['reward_base'] == base and f['progress']['pool'] == 0


def test_fast_logs_bad_types_ttl_midnight_and_active_tabs():
    f = farm()
    run = start(f)
    assert start(f) == run and f['village_games'][GAME]['attempts'] == 1
    log = solve(run['plan'])
    with pytest.raises(FarmError,match='Дождись'):
        finish(f,run,log,NOW+1)
    for bad in ([],log[:-1],[[True,800,600]]*5,[[45000,800,600]]*5):
        with pytest.raises(ValueError):
            physics.replay(run['plan'],bad)
    assert finish(f,run,log,NOW+180)[1]
    assert f['village_games'][GAME]['last_result']['expired']
    midnight = (progression.moscow_day(NOW)+1)*86400-10800
    run = start(f,midnight-2)
    assert run['expires_at'] == midnight
    finish(f,run,solve(run['plan']),midnight)
    assert f['village_games'][GAME]['last_result']['expired']


def test_owner_allowlist_guest_privacy_and_unknown_version_preserved():
    f = farm()
    run = start(f)
    f['village_games']['future'] = {'secret':'answer'}
    f['village_games'][GAME]['private'] = 'secret'
    view = project(f,f,NOW)['village_games']
    assert set(view) == {GAME, 'agata_pie'} and 'private' not in view[GAME] and 'private' not in view['agata_pie']
    assert view[GAME]['active']['plan'] == run['plan']
    other = farm()
    f['settings']['visibility'] = 'public'
    assert 'village_games' not in project(f,other,NOW)
    f['village_games'][GAME]['version'] = 99
    before = deepcopy(f['village_games'])
    games.validate(f)
    visible = games.public(f,NOW)
    assert GAME not in visible and 'agata_pie' in visible
    with pytest.raises(FarmError):
        start(f)
    assert f['village_games'] == before


def test_idle_credit_precedes_vigour_cap():
    f = farm()
    f['progress']['last'] = progression.moscow_day(NOW)-5
    credited = progression.add_vigour(f,120,NOW)
    assert credited == 0
    assert f['progress']['pool'] == progression.status(f,NOW)['pool_cap']
