"""Balance check and shared fixtures for «Битва с Сантой» (domain/farm_santa_battle.py).

    python scripts/farm_santa_battle_sim.py              # win rates of several bots over many seeds
    python scripts/farm_santa_battle_sim.py --fixtures   # also rewrite tests/fixtures/farm_santa_battle.json

Bots: «naive» — only plain attacks; «calm» — sensible skills, no accuracy bonus, no items (the bar the design
promises must be winnable); «skilled» — sensible skills, always hits the accuracy zone, eats a pie when low;
«random» — any legal move.
"""
from __future__ import annotations

import json
import random
import sys
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from domain import farm_santa_battle as sb  # noqa: E402

DAMAGING = {'switch', 'coal', 'hohoho', 'chain'}


def _weakest_enemy(state):
    return min(sb._alive(state, state['enemies']), key=lambda e: (state['hp'][e], e))


def _press(plan, state, skilled):
    if not skilled:
        return None
    zone = plan['zones'][state['bar'] % len(plan['zones'])]
    return (zone[0] + zone[1]) // 2


def smart(plan, state, skilled, items):
    hero = sb.actor(state)
    moves = {m[0]: m[1] for m in sb.legal(state)}
    intents = state['intents']
    heroes = sb._alive(state, sb.HEROES)
    if items and 'pie' in moves:
        low = [h for h in heroes if state['hp'][h] * 100 < state['max'][h] * 35]
        if low:
            return [hero, 'pie', low[0], None]
    if hero == 'player':
        incoming = sum(1 for i in intents.values() if i['move'] in ('hohoho', 'coal', 'switch'))
        if 'wall' in moves and incoming >= 2 or ('wall' in moves and any(i['move'] == 'hohoho' for i in intents.values())):
            return [hero, 'wall', None, None]
        return [hero, 'snowball', _weakest_enemy(state), _press(plan, state, skilled)]
    if hero == 'ded_moroz':
        if 'blizzard' in moves and len(sb._alive(state, state['enemies'])) > 1:
            return [hero, 'blizzard', None, _press(plan, state, skilled)]
        return [hero, 'staff', _weakest_enemy(state), _press(plan, state, skilled)]
    hurt = [h for h in heroes if state['hp'][h] * 2 < state['max'][h]]
    if 'song' in moves and len(hurt) >= 1:
        return [hero, 'song', None, None]
    if 'freeze' in moves:
        danger = [e for e, i in intents.items() if i['move'] in DAMAGING and e not in state['frozen'] and state['hp'][e] > 0]
        if danger:
            return [hero, 'freeze', danger[-1], None]
    return [hero, 'icestar', _weakest_enemy(state), _press(plan, state, skilled)]


def naive(plan, state):
    hero = sb.actor(state)
    attack = next(a for a, (h, _) in sb.ATTACKS.items() if h == hero)
    return [hero, attack, _weakest_enemy(state), None]


def randomized(rng):
    def bot(plan, state):
        hero = sb.actor(state)
        action, targets = rng.choice(sb.legal(state))
        press = rng.randint(0, sb.BAR_MS) if action in sb.ATTACKS or action == 'blizzard' else None
        return [hero, action, rng.choice(targets) if targets else None, press]
    return bot


BOTS = {
    'naive': lambda rng: naive,
    'calm': lambda rng: (lambda plan, state: smart(plan, state, False, False)),
    'skilled': lambda rng: (lambda plan, state: smart(plan, state, True, True)),
    'random': randomized,
}


def play(seed, battle, bot):
    plan = sb.make_plan(seed, battle)
    state = sb.new_state(plan)
    log, events = [], []
    while state['outcome'] is None:
        entry = bot(plan, state)
        log.append(entry)
        events.append(sb.act(plan, state, entry))
    return plan, log, events, state


def report(n=400):
    for battle in sb.BATTLES:
        for name, make in BOTS.items():
            wins = rounds = downs = stars3 = 0
            for i in range(n):
                rng = random.Random(i)
                _, _, _, state = play(f's{i}', battle, make(rng))
                if state['outcome'] == 'win':
                    wins += 1
                    rounds += state['round']
                    stars3 += sb.stars(state) == 3
                downs += sum(state['hp'][h] == 0 for h in sb.HEROES)
            print(f'battle {battle} {name:8} win {wins * 100 // n:3}%  rounds {rounds / max(1, wins):5.1f}  '
                  f'★★★ {stars3 * 100 // n:3}%  heroes down/battle {downs / n:4.2f}')


def fixtures():
    out = []
    for battle in sb.BATTLES:
        for name in ('calm', 'skilled', 'random'):
            seed = f'fixture-{battle}-{name}'
            plan, log, events, state = play(seed, battle, BOTS[name](random.Random(battle)))
            out.append(dict(seed=seed, battle=battle, bot=name, plan=plan, log=log, events=events,
                            result=sb.replay(plan, deepcopy(log)), state=state))
    path = ROOT / 'tests' / 'fixtures' / 'farm_santa_battle.json'
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(f'{len(out)} fixtures -> {path}')


if __name__ == '__main__':
    report()
    if '--fixtures' in sys.argv:
        fixtures()
