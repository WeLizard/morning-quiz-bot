"""«Битва с Сантой»: the replay engine (domain/farm_santa_battle.py) and its shared fixtures with the JS mirror."""
import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from domain import farm_santa_battle as sb

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = json.loads((ROOT / 'tests' / 'fixtures' / 'farm_santa_battle.json').read_text(encoding='utf-8'))


def _sim():
    sys.path.insert(0, str(ROOT / 'scripts'))
    import farm_santa_battle_sim
    return farm_santa_battle_sim


def _attack(state, target=None, press=None):
    hero = sb.actor(state)
    action = next(a for a, (h, _) in sb.ATTACKS.items() if h == hero)
    return [hero, action, target or sb._alive(state, state['enemies'])[0], press]


def test_fixtures_replay_to_the_same_events_and_result():
    assert {(f['battle'], f['bot']) for f in FIXTURES} == {(b, n) for b in sb.BATTLES for n in ('calm', 'skilled', 'random')}
    assert {f['result']['outcome'] for f in FIXTURES} == {'win', 'lose'}
    for fixture in FIXTURES:
        plan = sb.make_plan(fixture['seed'], fixture['battle'])
        assert plan == fixture['plan']
        state = sb.new_state(plan)
        events = [sb.act(plan, state, deepcopy(entry)) for entry in fixture['log']]
        assert events == fixture['events'], fixture['seed']
        assert json.loads(json.dumps(state)) == fixture['state']
        assert sb.replay(plan, deepcopy(fixture['log'])) == fixture['result']


def test_plan_is_deterministic_and_in_range():
    assert sb.make_plan('a', 1) == sb.make_plan('a', 1)
    assert sb.make_plan('a', 1) != sb.make_plan('a', 2) != sb.make_plan('b', 2)
    plan = sb.make_plan('zones', 3)
    assert all(180 <= lo and hi - lo == sb.ZONE_MS and hi < sb.BAR_MS - 80 for lo, hi in plan['zones'])
    assert all(0 <= t < 6 for t in plan['targets']) and set(plan['gifts']) <= {0, 1}
    with pytest.raises(ValueError):
        sb.make_plan('a', 4)


def test_turn_order_and_legal_moves():
    plan = sb.make_plan('order', 1)
    state = sb.new_state(plan)
    assert sb.actor(state) == 'player' and state['intents']['krampus']['move'] == 'switch'
    moves = dict((a, t) for a, t in sb.legal(state))
    assert moves['snowball'] == ['krampus'] and moves['wall'] == [] and moves['gingerbread'] == []
    assert moves['pie'] == list(sb.HEROES) and 'staff' not in moves and 'freeze' not in moves
    sb.act(plan, state, ['player', 'wall', None, None])
    assert sb.actor(state) == 'ded_moroz' and 'wall' not in dict(sb.legal({**state, 'turn': 0}))


@pytest.mark.parametrize('entry, why', [
    (['ded_moroz', 'staff', 'krampus', None], 'actor'),
    (['player', 'staff', 'krampus', None], 'action'),
    (['player', 'snowball', 'santa', None], 'target'),
    (['player', 'wall', 'krampus', None], 'target'),
    (['player', 'wall', None, 100], 'press'),
    (['player', 'snowball', 'krampus', 1201], 'press'),
    (['player', 'snowball', 'krampus', True], 'press'),
    (['player', 'snowball', 'krampus', 1.5], 'press'),
    (['player', 'snowball', 'krampus'], 'entry'),
    (('player', 'snowball', 'krampus', None), 'entry'),
])
def test_illegal_entries_are_refused(entry, why):
    plan = sb.make_plan('bad', 1)
    with pytest.raises(ValueError, match=why):
        sb.act(plan, sb.new_state(plan), entry)


def test_accuracy_zone_gives_half_again():
    plan = sb.make_plan('bar', 1)
    lo, hi = plan['zones'][0]
    state = sb.new_state(plan)
    assert sb.act(plan, state, ['player', 'snowball', 'krampus', lo])[0] == dict(t='hit', by='player', to='krampus', amount=18, bonus=True)
    assert sb.act(plan, state, ['ded_moroz', 'staff', 'krampus', plan['zones'][1][1] + 1])[0]['amount'] == 18
    assert state['bar'] == 2 and state['hp']['krampus'] == 160 - 36


def test_items_limit_honey_and_tea():
    plan = sb.make_plan('items', 3)
    state = sb.new_state(plan)
    state['chain'] = ['snegurochka']
    sb.act(plan, state, ['player', 'honey', 'ded_moroz', None])
    events = sb.act(plan, state, ['ded_moroz', 'tea', 'snegurochka', None])
    assert 'snegurochka' not in state['chain'] and events[0]['item'] == 'tea'
    sb.act(plan, state, ['snegurochka', 'gingerbread', None, None])
    assert state['n_items'] == 3 and not [m for m in sb.legal(state) if m[0] in sb.ITEMS]
    while sb.actor(state) != 'ded_moroz':
        sb.act(plan, state, _attack(state, 'krampus'))
    hit = sb.act(plan, state, ['ded_moroz', 'staff', 'krampus', None])[0]
    assert hit['amount'] == 36 and state['honey'] == []


def test_chain_skips_a_turn_and_freeze_skips_the_enemy():
    plan = sb.make_plan('chain', 1)
    state = sb.new_state(plan)
    state['intents'] = {'krampus': dict(move='chain', target='ded_moroz')}
    sb.act(plan, state, _attack(state))
    sb.act(plan, state, _attack(state))
    events = sb.act(plan, state, _attack(state))
    assert dict(t='move', who='krampus', move='chain', to='ded_moroz') in events
    events = sb.act(plan, state, _attack(state))
    assert dict(t='skip', who='ded_moroz', why='chain') in events and sb.actor(state) == 'snegurochka'
    events = sb.act(plan, state, ['snegurochka', 'freeze', 'krampus', None])
    assert dict(t='skip', who='krampus', why='freeze') in events
    assert state['round'] == 3 and state['chain'] == [] and state['frozen'] == []


def test_sack_wall_rage_and_power():
    plan = sb.make_plan('sack', 2)
    state = sb.new_state(plan)
    state['sack'] = True
    assert sb.act(plan, state, ['player', 'snowball', 'santa', None])[0] == dict(t='miss', by='player', to='santa', why='sack')
    assert not state['sack'] and state['hp']['santa'] == 240
    state = sb.new_state(plan)
    state['intents'] = {'santa': dict(move='coal', target='player')}
    sb.act(plan, state, ['player', 'wall', None, None])
    sb.act(plan, state, _attack(state))
    events = sb.act(plan, state, _attack(state))
    coal = sb.COAL * sb.BATTLES[2]['power'] // 100 // 2
    assert dict(t='hit', by='santa', to='player', amount=coal, bonus=False) in events and not state['wall']
    plan = sb.make_plan('rage', 3)
    state = sb.new_state(plan)
    state['rage'] = 2
    state['intents'] = {'krampus': dict(move='switch', target='player'), 'santa': dict(move='coal', target='player')}
    for _ in range(3):
        events = sb.act(plan, state, _attack(state, 'santa'))
    hits = {e['by']: e['amount'] for e in events if e['t'] == 'hit' and e['to'] == 'player'}
    assert hits == {'krampus': sb.SWITCH * 13 // 10, 'santa': sb.COAL} and state['rage'] == 1


def test_dead_target_is_replaced_and_the_reindeer_come_every_fourth_round():
    plan = sb.make_plan('deer', 3)
    state = sb.new_state(plan)
    state['round'] = 4
    state['hp']['player'] = 0
    state['turn'] = 1
    state['intents'] = {'krampus': dict(move='switch', target='player'), 'santa': dict(move='hohoho', target=None)}
    sb.act(plan, state, _attack(state))
    events = sb.act(plan, state, _attack(state))
    switch = next(e for e in events if e['t'] == 'move' and e['who'] == 'krampus')
    assert switch['to'] in ('ded_moroz', 'snegurochka')
    assert dict(t='move', who='reindeer', move='sleigh', to=None) in events
    assert sum(e['t'] == 'hit' and e['by'] == 'reindeer' for e in events) == 2


def test_win_lose_timeout_and_stars():
    plan = sb.make_plan('end', 1)
    state = sb.new_state(plan)
    state['hp']['krampus'] = 5
    events = sb.act(plan, state, _attack(state))
    assert events[-1] == dict(t='down', who='krampus') and state['outcome'] == 'win' and sb.stars(state) == 3
    assert sb.actor(state) is None and sb.legal(state) == []
    with pytest.raises(ValueError, match='over'):
        sb.act(plan, state, ['player', 'snowball', 'krampus', None])
    state['round'] = 5
    assert sb.stars(state) == 2
    state['hp']['player'] = 0
    assert sb.stars(state) == 1
    state = sb.new_state(plan)
    state['round'] = sb.MAX_ROUNDS
    state['hp']['krampus'] = 10 ** 6
    state['intents'] = {'krampus': dict(move='roar', target=None)}
    for _ in range(2):
        sb.act(plan, state, _attack(state))
    events = sb.act(plan, state, _attack(state))
    assert events[-1] == dict(t='timeout') and state['outcome'] == 'lose' and sb.stars(state) == 0


def test_replay_refuses_bad_and_unfinished_logs():
    plan = sb.make_plan('replay', 1)
    for bad in (None, [], 'log', [['player', 'snowball', 'krampus', None]] * (sb.MAX_LOG + 1)):
        with pytest.raises(ValueError):
            sb.replay(plan, bad)
    with pytest.raises(ValueError, match='unfinished'):
        sb.replay(plan, [['player', 'snowball', 'krampus', None]])


def test_balance_targets_hold():
    sim = _sim()
    import random
    for battle, bot, lo in ((1, 'calm', 100), (2, 'calm', 100), (3, 'calm', 90), (3, 'skilled', 100)):
        wins = sum(sim.play(f's{i}', battle, sim.BOTS[bot](random.Random(i)))[3]['outcome'] == 'win' for i in range(60))
        assert wins * 100 // 60 >= lo, (battle, bot, wins)
    for battle in sb.BATTLES:
        _, _, _, state = sim.play('par', battle, sim.BOTS['skilled'](random.Random(0)))
        assert sb.stars(state) == 3
        _, _, _, state = sim.play('par', battle, sim.BOTS['calm'](random.Random(0)))
        assert sb.stars(state) == 2
    naive = sum(sim.play(f's{i}', 3, sim.BOTS['naive'](random.Random(i)))[3]['outcome'] == 'win' for i in range(60))
    assert naive < 30
