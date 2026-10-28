"""Village replay commands operating on a locked farm aggregate."""
from copy import deepcopy
from secrets import token_hex
from uuid import uuid4

from domain import farm_ballista as ballista
from domain.farm_village_games import GAMES, stars, reward_total
from qw_farm import progression
from qw_farm.catalog import level, income_ref
from qw_farm.domain import need

COMMANDS = {'vgame_start', 'vgame_finish'}


def _game(data, fields):
    need(type(data) is dict and set(data) == fields, 'invalid_command', 'Некорректные параметры игры.', 422)
    game = data['game']
    need(type(game) is str and game in GAMES, 'unknown_game', 'Игра не найдена.', 422)
    return game, GAMES[game]


def _supported(state):
    return type(state) is dict and state.get('version') == 1


def _blank(day):
    return dict(version=1, day=day, attempts=0, best_stars=0, practice=0,
                run=None, last_result=None, reward_kind=None, reward_base=0, paid=0)


def _expire(state, now):
    run = state.get('run')
    if run and run.get('version') == 1 and now >= run['expires_at']:
        state['last_result'] = dict(run_id=run['id'], score=0, stars=0, hits=0,
                                    practice=run['practice'], expired=True, reward_kind=state['reward_kind'], reward=0)
        state['run'] = None
        return True
    return False


def command(farm, kind, data, now):
    game, spec = _game(data, {'game'} if kind == 'vgame_start' else {'game', 'run_id', 'log'})
    need(level(farm['xp']) >= spec.min_level, 'locked', 'Пух пока не готов играть.')
    games = farm.setdefault('village_games', {})
    need(type(games) is dict, 'invalid_state', 'Некорректное состояние игр.', 500)
    state = games.setdefault(game, _blank(progression.moscow_day(now)))
    need(_supported(state), 'unsupported_game', 'Эта версия игры пока недоступна.', 409)
    expired = _expire(state, now)
    day = progression.moscow_day(now)
    if kind == 'vgame_start':
        if state['run']:
            need(state['run'].get('version') == spec.version, 'unsupported_game', 'Эта версия игры пока недоступна.', 409)
            return 'Продолжай начатую доставку.', False
        if state['day'] != day:
            state = games[game] = _blank(day)
        progression.touch(farm, now)
        practice = state['attempts'] >= 3
        if practice:
            state['practice'] += 1
        else:
            if state['reward_kind'] is None:
                status = progression.status(farm, now)
                state['reward_kind'] = 'premium' if status['pool'] >= status['pool_cap'] else 'vigour'
                state['reward_base'] = (max(10, income_ref(level(farm['xp'])) // 100)
                                        if state['reward_kind'] == 'premium' else progression.pace(level(farm['xp'])))
            state['attempts'] += 1
        state['run'] = dict(id=str(uuid4()), version=spec.version, started_at=now,
                            expires_at=min(now+spec.ttl, (day+1)*86400-10800),
                            practice=practice, plan=ballista.make_plan(token_hex(16)))
        return ('Тренировка: доставь пять банок.' if practice else 'Пух готов! Доставь пять банок в окна.'), True
    run_id = data['run_id']
    need(type(run_id) is str, 'invalid_run', 'Некорректный номер доставки.', 422)
    last = state.get('last_result')
    if last and last['run_id'] == run_id:
        return ('Время доставки вышло.' if last.get('expired') else 'Результат уже учтён.'), expired
    run = state['run']
    need(run and run['id'] == run_id, 'run_not_found', 'Доставка не найдена. Начни заново.', 404)
    need(run.get('version') == spec.version, 'unsupported_game', 'Эта версия игры пока недоступна.', 409)
    try:
        score, hits, durations = ballista.replay(run['plan'], data['log'])
    except (ValueError, TypeError, KeyError):
        need(False, 'invalid_log', 'Некорректный журнал доставки.', 422)
    end_ms = data['log'][-1][2] + durations[-1]
    need(end_ms <= (now-run['started_at'])*1000+2000, 'too_fast', 'Дождись окончания полёта.', 409)
    need(end_ms <= (run['expires_at']-run['started_at'])*1000, 'invalid_log', 'Доставка вышла за отведённое время.', 422)
    earned_stars = stars(score)
    reward = 0
    progression.touch(farm, now)
    if not run['practice']:
        state['best_stars'] = max(state['best_stars'], earned_stars)
        target = reward_total(state['reward_kind'], state['reward_base'], state['best_stars'])
        delta = max(0, target-state['paid'])
        if state['reward_kind'] == 'vigour':
            reward = progression.add_vigour(farm, delta, now)
        else:
            reward = min(delta, max(0, 10**12-farm['coins']))
            farm['coins'] += reward
        # Entitlement is consumed even if another action filled the pool or wallet.
        state['paid'] = target
    state['last_result'] = dict(run_id=run_id, score=score, stars=earned_stars, hits=hits,
                               practice=run['practice'], expired=False, reward_kind=state['reward_kind'], reward=reward)
    state['run'] = None
    return f'Доставлено: {hits} из 5. Звёзд: {earned_stars}.', True


def public(farm, now):
    result = {}
    games = farm.get('village_games') or {}
    if type(games) is not dict:
        return result
    for game, spec in GAMES.items():
        state = games.get(game)
        if state is not None and not _supported(state):
            continue
        state = deepcopy(state) if state else _blank(progression.moscow_day(now))
        _expire(state, now)
        if state['day'] != progression.moscow_day(now):
            state = _blank(progression.moscow_day(now))
        run = state['run']
        active = None
        if run and run.get('version') == spec.version:
            plan = run['plan']
            visible_plan = {k:deepcopy(plan[k]) for k in ('version','width','height','step_ms')}
            visible_plan['targets'] = [{k:deepcopy(target[k]) for k in ('x','y','radius','wind','roof')}
                                       for target in plan['targets']]
            active = dict(run_id=run['id'], started_at=run['started_at'], expires_at=run['expires_at'],
                          practice=run['practice'], plan=visible_plan)
        last = state['last_result']
        visible_last = ({k:deepcopy(last[k]) for k in ('run_id','score','stars','hits','practice','expired','reward_kind','reward')}
                        if last else None)
        result[game] = dict(npc=spec.npc, min_level=spec.min_level, locked=level(farm['xp']) < spec.min_level,
                            attempts=state['attempts'], attempts_left=max(0,3-state['attempts']),
                            best_stars=state['best_stars'], reward_kind=state['reward_kind'],
                            reward_base=state['reward_base'], paid=state['paid'], active=active,
                            last_result=visible_last)
    return result


def validate(farm):
    games = farm.get('village_games')
    if games is None:
        return
    need(type(games) is dict, 'invalid_state', 'Некорректное состояние игр.', 500)
    for game, state in games.items():
        if game not in GAMES or not _supported(state):
            continue  # A rollback must preserve future games/versions without executing them.
        need(all(type(state.get(k)) is int and state[k] >= 0 for k in
                 ('day','attempts','best_stars','practice','reward_base','paid'))
             and state['attempts'] <= 3 and state['best_stars'] <= 3
             and state.get('reward_kind') in (None,'vigour','premium'),
             'invalid_state', 'Некорректное состояние игр.', 500)
        run = state.get('run')
        need(run is None or type(run) is dict, 'invalid_state', 'Некорректная доставка.', 500)
        if run and run.get('version') == 1:
            need(type(run.get('id')) is str and len(run['id']) == 36
                 and type(run.get('started_at')) is int and type(run.get('expires_at')) is int
                 and run['started_at'] < run['expires_at'] <= run['started_at']+GAMES[game].ttl
                 and type(run.get('practice')) is bool and type(run.get('plan')) is dict
                 and run['plan'].get('version') == 1 and len(run['plan'].get('targets', [])) == 5,
                 'invalid_state', 'Некорректная доставка.', 500)
