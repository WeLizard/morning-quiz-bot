"""Agata's fair pie tower: a per-fair replay game with a shared village goal."""
from secrets import token_hex
from uuid import uuid4

from domain import farm_pie
from qw_farm import festivals, progression
from qw_farm.domain import need

GAME = 'agata_pie'
STATE_FIELDS = {'version', 'fair', 'day', 'attempts', 'practice', 'best', 'contributed', 'run', 'last_result'}


def tower_config(fid):
    return festivals.content(fid).get('tower')


def open_fair(now):
    cur = festivals.current(now)
    if not cur or cur['phase'] != 'fair' or not tower_config(cur['id']):
        return None
    return cur


def blank(day, key):
    return dict(version=1, fair=key, day=day, attempts=0, practice=0, best=0, contributed=0,
                run=None, last_result=None)


def games(farm):
    value = farm.setdefault('village_games', {})
    need(type(value) is dict, 'invalid_state', 'Некорректное состояние игр.', 500)
    return value


def _expire(state, now):
    run = state.get('run')
    if run and run.get('version') == 1 and now >= run['expires_at']:
        state['last_result'] = dict(run_id=run['id'], height=0, best=state['best'], practice=run['practice'],
                                    expired=True, miss=False)
        state['run'] = None
        return True
    return False


def command(farm, kind, data, now):
    store = games(farm)
    if kind == 'vgame_start':
        cur = open_fair(now)
        need(cur is not None, 'fair_closed', 'Пирог до небес ждёт ярмарки.', 409)
        day = progression.moscow_day(now)
        state = store.get(GAME)
        if not (type(state) is dict and state.get('version') == 1 and state.get('fair') == cur['key']):
            state = store[GAME] = blank(day, cur['key'])
        if state['day'] != day:
            state['day'] = day
            state['attempts'] = 0
            state['practice'] = 0
        _expire(state, now)
        run = state.get('run')
        if run:
            need(run.get('version') == 1, 'unsupported_game', 'Эта версия игры пока недоступна.', 409)
            return 'Продолжай башню.', False
        progression.touch(farm, now)
        practice = state['attempts'] >= 3
        if practice:
            state['practice'] += 1
        else:
            state['attempts'] += 1
        state['run'] = dict(id=str(uuid4()), version=1, started_at=now, expires_at=now + farm_pie.TTL,
                            practice=practice, plan=farm_pie.make_plan(token_hex(16)))
        return ('Тренировка: сложи башню до небес.' if practice else 'Сложи башню до небес!'), True

    state = store.get(GAME)
    run_id = data['run_id']
    need(type(run_id) is str, 'invalid_run', 'Некорректный номер попытки.', 422)
    need(type(state) is dict and state.get('version') == 1, 'run_not_found', 'Попытка не найдена. Начни заново.', 404)
    last = state.get('last_result')
    if last and last.get('run_id') == run_id:
        return 'Результат уже учтён.', False
    run = state.get('run')
    need(run and run.get('id') == run_id, 'run_not_found', 'Попытка не найдена. Начни заново.', 404)
    need(run.get('version') == 1, 'unsupported_game', 'Эта версия игры пока недоступна.', 409)
    log = data['log']
    need(farm_pie.log_valid(run['plan'], log), 'invalid_log', 'Некорректный журнал башни.', 422)
    if now >= run['expires_at']:
        state['run'] = None
        state['last_result'] = dict(run_id=run_id, height=0, best=state['best'], practice=run['practice'],
                                    expired=True, miss=False)
        return 'Время попытки вышло. Начни новую.', True
    if log:
        need(log[-1] <= (now - run['started_at']) * 1000 + 2000, 'too_fast', 'Дождись окончания броска.', 409)
    result = farm_pie.replay(run['plan'], log)
    height = result['height']
    state['run'] = None
    if not run['practice'] and height > state['best']:
        delta = height - state['best']
        state['best'] = height
        state['contributed'] += delta
    state['last_result'] = dict(run_id=run_id, height=height, best=state['best'], practice=run['practice'],
                                expired=False, miss=result['miss'])
    if not run['practice'] and height > 0:
        festivals.entry(farm, state['fair'])['tower'] = True
    text = f'Поставлено {height} коржей. Лучшая высота: {state["best"]}.'
    if run['practice']:
        text += ' Тренировка.'
    elif result['miss']:
        text += ' Башня упала.'
    return text, True


def public(farm, now):
    state = (farm.get('village_games') or {}).get(GAME)
    cur = open_fair(now)
    if not (type(state) is dict and state.get('version') == 1) or (cur is not None and state.get('fair') != cur['key']):
        state = blank(progression.moscow_day(now), cur['key'] if cur else '')
    day = progression.moscow_day(now)
    if state['day'] != day:
        state = {**state, 'day': day, 'attempts': 0, 'practice': 0}
    run = state.get('run')
    active = None
    if run and run.get('version') == 1:
        active = dict(run_id=run['id'], started_at=run['started_at'], expires_at=run['expires_at'],
                      practice=run['practice'], plan=run['plan'])
    return dict(npc='agata', min_level=1, locked=False, fair_key=state['fair'], available=cur is not None,
                attempts=state['attempts'], attempts_left=max(0, 3 - state['attempts']), practice=state['practice'],
                best=state['best'], active=active, last_result=state.get('last_result'))


def validate(farm):
    state = (farm.get('village_games') or {}).get(GAME)
    if state is None:
        return
    need(type(state) is dict and state.get('version') == 1 and set(state) == STATE_FIELDS
         and type(state.get('fair')) is str and type(state.get('day')) is int
         and type(state.get('attempts')) is int and 0 <= state['attempts'] <= 3
         and type(state.get('practice')) is int and state['practice'] >= 0
         and type(state.get('best')) is int and type(state.get('contributed')) is int
         and 0 <= state['contributed'] <= state['best'],
         'invalid_state', 'Некорректное состояние игр.', 500)
    run = state.get('run')
    need(run is None or (type(run) is dict and set(run) == {'id', 'version', 'started_at', 'expires_at', 'practice', 'plan'}
                         and type(run.get('id')) is str and len(run['id']) == 36
                         and type(run.get('started_at')) is int and type(run.get('expires_at')) is int
                         and run['started_at'] < run['expires_at'] <= run['started_at'] + farm_pie.TTL
                         and type(run.get('practice')) is bool and type(run.get('plan')) is dict
                         and run['plan'].get('version') == 1),
         'invalid_state', 'Некорректная попытка.', 500)
    last = state.get('last_result')
    need(last is None or (type(last) is dict and set(last) == {'run_id', 'height', 'best', 'practice', 'expired', 'miss'}
                          and type(last.get('run_id')) is str and type(last.get('height')) is int
                          and type(last.get('best')) is int and type(last.get('practice')) is bool
                          and type(last.get('expired')) is bool and type(last.get('miss')) is bool),
         'invalid_state', 'Некорректный результат.', 500)
