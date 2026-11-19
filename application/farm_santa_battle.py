"""«Битва с Сантой»: the New Year turn-based battle (docs/tasks/FARM_SANTA_BATTLE.md), a replay game of the village.

The client plays a whole battle locally on the plan the start gave it and sends the log; the finish replays it with
domain/farm_santa_battle.py. Three battles per New Year: each opens on its date and after a win in the previous one.
The first win of a battle gives its festival item (never coins or XP); a rematch keeps only the record. The «Корзинка»
items eaten in battle leave the barn at the finish, win or lose; if the barn no longer has them the battle is not counted.
"""
from datetime import date
from secrets import token_hex
from uuid import uuid4

from domain import farm_santa_battle as sb
from qw_farm import economy, festivals, progression
from qw_farm.domain import inventory, need

GAME = 'santa_battle'
FESTIVAL = 'new_year'
OPENS = {1: (12, 20), 2: (12, 25), 3: (12, 31)}   # (month, day) in the December of the festival
REWARDS = {1: 'fest_ny_krampus_bell', 2: 'fest_ny_santa_sack', 3: 'fest_ny_santa_visit'}
MIN_MOVE_MS = 600   # the client animates every move for longer; a log played faster than this is not a person
STATE_FIELDS = {'version', 'festival', 'best', 'rounds', 'fights', 'run', 'last_result'}
RUN_FIELDS = {'id', 'version', 'battle', 'started_at', 'expires_at', 'plan'}
RESULT_FIELDS = {'run_id', 'battle', 'outcome', 'stars', 'rounds', 'items', 'reward'}
OUTCOMES = ('win', 'lose', 'expired', 'basket')
NAMES = {1: 'Крампус', 2: 'Санта', 3: 'Санта и Крампус'}


def open_festival(now):
    cur = festivals.current(now)
    return cur if cur is not None and cur['id'] == FESTIVAL else None


def opens_on(key, battle):
    """Moscow day number on which ``battle`` of the occurrence ``key`` (``new_year-<year it ends>``) opens."""
    year = int(festivals.KEY_RE.match(key).group(2))
    month, day = OPENS[battle]
    return festivals.day_number(date(year - 1, month, day))


def blank(key):
    return dict(version=1, festival=key, best=[0, 0, 0], rounds=[0, 0, 0], fights=0, run=None, last_result=None)


def _store(farm):
    value = farm.setdefault('village_games', {})
    need(type(value) is dict, 'invalid_state', 'Некорректное состояние игр.', 500)
    return value


def _result(run, outcome, stars=0, rounds=0, items=None, reward=None):
    return dict(run_id=run['id'], battle=run['battle'], outcome=outcome, stars=stars, rounds=rounds,
                items=items or {}, reward=reward)


def _expire(state, now):
    run = state.get('run')
    if run and run.get('version') == sb.VERSION and now >= run['expires_at']:
        state['last_result'] = _result(run, 'expired')
        state['run'] = None
        return True
    return False


def _state(farm, cur):
    store = _store(farm)
    state = store.get(GAME)
    if not (type(state) is dict and state.get('version') == 1 and state.get('festival') == cur['key']):
        state = store[GAME] = blank(cur['key'])
    return state


def _start(farm, data, now):
    battle = data['battle']
    need(type(battle) is int and battle in sb.BATTLES, 'invalid_command', 'Такого боя нет.', 422)
    cur = open_festival(now)
    need(cur is not None, 'festival_closed', 'Битва с Сантой идёт только на Новый год.', 409)
    state = _state(farm, cur)
    _expire(state, now)
    month, day = OPENS[battle]
    need(economy.moscow_day(now) >= opens_on(cur['key'], battle), 'battle_closed',
         f'Этот бой начнётся {day} декабря.', 409)
    need(battle == 1 or state['best'][battle - 2] > 0, 'battle_locked',
         f'Сначала победи в бою {battle - 1}.', 409)
    run = state.get('run')
    if run and run.get('battle') == battle:
        need(run.get('version') == sb.VERSION, 'unsupported_game', 'Эта версия игры пока недоступна.', 409)
        return 'Продолжай бой.', False
    # A run of another battle is given up: nothing was eaten from the barn yet, the log only lives on the client.
    progression.touch(farm, now)
    state['fights'] += 1
    state['run'] = dict(id=str(uuid4()), version=sb.VERSION, battle=battle, started_at=now,
                        expires_at=now + sb.TTL, plan=sb.make_plan(token_hex(16), battle))
    return f'Бой {battle}: {NAMES[battle]}! Дед Мороз и Снегурочка рядом.', True


def _finish(farm, data, now):
    run_id = data['run_id']
    need(type(run_id) is str, 'invalid_run', 'Некорректный номер боя.', 422)
    state = _store(farm).get(GAME)
    need(type(state) is dict and state.get('version') == 1, 'run_not_found', 'Бой не найден. Начни заново.', 404)
    last = state.get('last_result')
    if last and last.get('run_id') == run_id:
        return 'Результат уже учтён.', False
    run = state.get('run')
    need(run and run.get('id') == run_id, 'run_not_found', 'Бой не найден. Начни заново.', 404)
    need(run.get('version') == sb.VERSION, 'unsupported_game', 'Эта версия игры пока недоступна.', 409)
    if _expire(state, now):
        return 'Время боя вышло. Начни новый.', True
    log = data['log']
    try:
        result = sb.replay(run['plan'], log)
    except (ValueError, TypeError, KeyError, IndexError):
        need(False, 'invalid_log', 'Некорректный журнал боя.', 422)
    need((now - run['started_at']) * 1000 + 2000 >= len(log) * MIN_MOVE_MS, 'too_fast', 'Дождись конца хода.', 409)
    state['run'] = None
    battle, items = run['battle'], result['items']
    progression.touch(farm, now)
    if any(farm['inventory'].get(item, 0) < qty for item, qty in items.items()):
        state['last_result'] = _result(run, 'basket', items=items)
        return 'В амбаре не хватило припасов из «Корзинки» — бой не засчитан.', True
    if items:
        inventory(farm, items, -1)
    if result['outcome'] != 'win':
        state['last_result'] = _result(run, 'lose', rounds=result['rounds'], items=items)
        return f'{NAMES[battle]} оказались сильнее. Отдохни и попробуй ещё раз.' if battle == 3 else \
            f'{NAMES[battle]} оказался сильнее. Отдохни и попробуй ещё раз.', True
    stars, rounds = result['stars'], result['rounds']
    first = state['best'][battle - 1] == 0
    state['best'][battle - 1] = max(state['best'][battle - 1], stars)
    old = state['rounds'][battle - 1]
    state['rounds'][battle - 1] = rounds if old == 0 else min(old, rounds)
    reward = None
    entry = festivals.entry(farm, state['festival'])
    good = festivals.good_of(FESTIVAL, REWARDS[battle])
    if first and festivals.owned(entry, good['id']) < good['limit']:
        entry['rewards'][good['id']] = 1
        reward = good['id']
    state['last_result'] = _result(run, 'win', stars, rounds, items, reward)
    text = f'Победа! Звёзд: {stars}, раундов: {rounds}.'
    if reward:
        text += f' «{good["name"]}» — в коллекции праздника.'
    return text, True


def command(farm, kind, data, now):
    if kind == 'vgame_start':
        return _start(farm, data, now)
    return _finish(farm, data, now)


def public(farm, now):
    cur = open_festival(now)
    state = (farm.get('village_games') or {}).get(GAME)
    if not (type(state) is dict and state.get('version') == 1) or (cur is not None and state.get('festival') != cur['key']):
        state = blank(cur['key'] if cur else '')
    run = state.get('run')
    if run and run.get('version') == sb.VERSION and now >= run['expires_at']:
        state = {**state, 'run': None, 'last_result': _result(run, 'expired')}
        run = None
    active = None
    if run and run.get('version') == sb.VERSION:
        active = dict(run_id=run['id'], battle=run['battle'], started_at=run['started_at'],
                      expires_at=run['expires_at'], plan=run['plan'])
    day = economy.moscow_day(now)
    owned = festivals.peek(farm, state['festival']) if state['festival'] else festivals.blank()
    battles = []
    for n in sb.BATTLES:
        good = festivals.good_of(FESTIVAL, REWARDS[n])
        opens = opens_on(cur['key'], n) if cur else None
        battles.append(dict(n=n, enemies=list(sb.BATTLES[n]['enemies']), par=sb.BATTLES[n]['par'],
                            opens_at=opens * festivals.DAY - festivals.TZ_OFFSET if opens is not None else None,
                            open=cur is not None and day >= opens and (n == 1 or state['best'][n - 2] > 0),
                            stars=state['best'][n - 1], rounds=state['rounds'][n - 1],
                            reward=dict(id=good['id'], name=good['name'], got=festivals.owned(owned, good['id']) > 0)))
    return dict(npc='ded_moroz', available=cur is not None, festival=state['festival'], fights=state['fights'],
                basket=sb.MAX_ITEMS, battles=battles, active=active, last_result=state.get('last_result'))


def validate(farm):
    state = (farm.get('village_games') or {}).get(GAME)
    if state is None:
        return
    ok = (type(state) is dict and state.get('version') == 1 and set(state) == STATE_FIELDS
          and type(state['festival']) is str and festivals.KEY_RE.match(state['festival'])
          and all(type(v) is list and len(v) == 3 and all(type(x) is int for x in v) for v in (state['best'], state['rounds']))
          and all(0 <= x <= 3 for x in state['best']) and all(0 <= x <= sb.MAX_ROUNDS for x in state['rounds'])
          and type(state['fights']) is int and state['fights'] >= 0)
    need(ok, 'invalid_state', 'Некорректное состояние игр.', 500)
    run = state['run']
    need(run is None or (type(run) is dict and set(run) == RUN_FIELDS and type(run['id']) is str and len(run['id']) == 36
                         and run['version'] == sb.VERSION and run['battle'] in sb.BATTLES
                         and type(run['started_at']) is int and type(run['expires_at']) is int
                         and run['started_at'] < run['expires_at'] <= run['started_at'] + sb.TTL
                         and type(run['plan']) is dict and run['plan'].get('battle') == run['battle']),
         'invalid_state', 'Некорректный бой.', 500)
    last = state['last_result']
    need(last is None or (type(last) is dict and set(last) == RESULT_FIELDS and type(last['run_id']) is str
                          and last['battle'] in sb.BATTLES and last['outcome'] in OUTCOMES
                          and type(last['stars']) is int and 0 <= last['stars'] <= 3 and type(last['rounds']) is int
                          and type(last['items']) is dict
                          and all(k in sb.ITEMS and type(q) is int and 0 < q <= sb.MAX_ITEMS for k, q in last['items'].items())
                          and last['reward'] in (None, *REWARDS.values())),
         'invalid_state', 'Некорректный результат боя.', 500)
