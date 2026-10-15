"""Server-owned house and barn challenges. No transport or question-bank dependency."""
from copy import deepcopy
from random import SystemRandom
from uuid import UUID, uuid4

from .domain import need, FarmError
from .catalog import income_ref, level, INCOME_REF_BANDS


GAMES = ('house', 'barn')
COOLDOWN = 4 * 60 * 60
LIFETIME = 15 * 60
SHELVES = ('grain', 'vegetable', 'berry')
SACKS = (
    ('wheat', 'Пшеница', 'grain'),
    ('oats', 'Овёс', 'grain'),
    ('carrot', 'Морковь', 'vegetable'),
    ('potato', 'Картофель', 'vegetable'),
    ('strawberry', 'Клубника', 'berry'),
    ('raspberry', 'Малина', 'berry'),
)
_SACK_CATEGORIES = {key: category for key, _, category in SACKS}
_SACK_LABELS = {key: label for key, label, _ in SACKS}
_STATE_ERROR = ('invalid_minigame_state', 'Некорректное состояние мини-игры.', 500)
_COIN_REWARDS = {max(10, value // 100) for _, _, value in INCOME_REF_BANDS}


def next_reward(farm):
    return {'kind': 'coins', 'amount': max(10, income_ref(level(farm['xp'])) // 100)}


def _attempt_reward(game, active):
    # Attempts started before the reward snapshot retain their promised payout.
    return active.get('reward', {'kind': 'coins' if game == 'house' else 'feed',
                                 'amount': 10 if game == 'house' else 1})


def _valid_attempt_id(value):
    if type(value) is not str or len(value) != 36:
        return False
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError, TypeError):
        return False
    return parsed.version == 4 and str(parsed) == value


def _time(value):
    return type(value) is int and 0 <= value <= 10**12


def upgrade(farm):
    games = farm.setdefault('minigames', {})
    need(type(games) is dict, *_STATE_ERROR)
    for game in GAMES:
        games.setdefault(game, {'available_at': 0, 'active': None, 'last_result': None})
    validate(farm)
    return games


def public(farm, now):
    result = {}
    for game, state in upgrade(deepcopy(farm)).items():
        if game not in GAMES:
            continue
        active = state['active']
        if active is not None and now < active['expires_at']:
            challenge = deepcopy(active['challenge'])
            challenge.update(attempt_id=active['attempt_id'], started_at=active['started_at'],
                             expires_at=active['expires_at'], reward=deepcopy(_attempt_reward(game, active)))
        else:
            challenge = None
        result[game] = {'available_at': state['available_at'], 'active': challenge,
                        'last_result': deepcopy(state['last_result']), 'next_reward': next_reward(farm)}
    return result


def _game(data, fields):
    need(type(data) is dict and set(data) == fields, 'invalid_command',
         'Некорректные параметры мини-игры.', 422)
    game = data['game']
    need(type(game) is str and game in GAMES, 'invalid_game', 'Неизвестная мини-игра.', 422)
    return game


def should_select_question(farm, data, now):
    game = _game(data, {'game'})
    state = upgrade(farm)[game]
    return game == 'house' and not (state['active'] and now < state['active']['expires_at']) and now >= state['available_at']


def start(farm, data, now, question=None):
    game = _game(data, {'game'})
    state = upgrade(farm)[game]
    if state['active'] and now < state['active']['expires_at']:
        return 'Задание уже начато.', False
    need(now >= state['available_at'], 'minigame_cooldown', 'Следующее задание появится позже.')
    if game == 'house':
        need(type(question) is dict, 'no_questions', 'Сейчас нет доступных вопросов для Филиныча.')
        prompt, options, correct = question.get('question'), question.get('options'), question.get('correct_option_text')
        need(type(prompt) is str and bool(prompt.strip()) and type(options) is list and
             2 <= len(options) <= 10 and all(type(x) is str and x for x in options) and
             len(set(options)) == len(options) and type(correct) is str and correct in options,
             'no_questions', 'Сейчас нет доступных вопросов для Филиныча.')
        challenge = {'question': prompt, 'options': list(options)}
        solution = correct
    else:
        sacks = list(SACKS)
        SystemRandom().shuffle(sacks)
        challenge = {'sacks': [{'id': key, 'label': label} for key, label, _ in sacks],
                     'shelves': list(SHELVES)}
        solution = {key: category for key, _, category in sacks}
    state['active'] = {'attempt_id': str(uuid4()), 'started_at': now,
                       'expires_at': now + LIFETIME, 'challenge': challenge, 'solution': solution,
                       'reward': next_reward(farm)}
    state['available_at'] = now + COOLDOWN
    return 'Задание начато.', True


def answer(farm, data, now):
    game = _game(data, {'game', 'attempt_id', 'answer'})
    attempt_id = data['attempt_id']
    try:
        need(type(attempt_id) is str and str(UUID(attempt_id)) == attempt_id,
             'invalid_attempt', 'Некорректный номер попытки.', 422)
    except (ValueError, AttributeError, TypeError):
        raise FarmError('invalid_attempt', 'Некорректный номер попытки.', 422) from None
    state = upgrade(farm)[game]
    previous = state['last_result']
    if previous and previous['attempt_id'] == attempt_id:
        return ('Верно!' if previous['correct'] else 'На этот раз не вышло.'), False
    active = state['active']
    need(active is not None and active['attempt_id'] == attempt_id,
         'invalid_attempt', 'Эта попытка не найдена.', 404)
    need(now < active['expires_at'], 'attempt_expired', 'Время задания истекло.')
    value = data['answer']
    if game == 'house':
        options = active['challenge']['options']
        need(type(value) is str and value in options, 'invalid_answer', 'Выбери один из вариантов.', 422)
    else:
        ids = set(active['solution'])
        need(type(value) is dict and set(value) == ids and
             all(type(key) is str and type(shelf) is str and shelf in SHELVES for key, shelf in value.items()),
             'invalid_answer', 'Разложи все шесть мешков по полкам.', 422)
    correct = value == active['solution']
    payout = _attempt_reward(game, active)
    reward = payout['amount'] if correct else 0
    if payout['kind'] == 'coins':
        farm['coins'] += reward
    else:
        farm['inventory']['feed'] = farm['inventory'].get('feed', 0) + reward
    state['last_result'] = {'attempt_id': attempt_id, 'correct': correct,
                            'reward': reward, 'reward_kind': payout['kind'], 'answered_at': now}
    state['active'] = None
    return ('Верно!' if correct else 'На этот раз не вышло.'), True


def validate(farm):
    games = farm.get('minigames')
    if games is None:
        return
    need(type(games) is dict and set(games) == set(GAMES), *_STATE_ERROR)
    for game in GAMES:
        state = games[game]
        need(type(state) is dict and set(state) == {'available_at', 'active', 'last_result'}, *_STATE_ERROR)
        need(_time(state['available_at']), *_STATE_ERROR)
        active = state['active']
        if active is not None:
            base_fields = {'attempt_id', 'started_at', 'expires_at', 'challenge', 'solution'}
            need(type(active) is dict and set(active) in (base_fields, base_fields | {'reward'}), *_STATE_ERROR)
            if 'reward' in active:
                payout = active['reward']
                need(type(payout) is dict and set(payout) == {'kind', 'amount'} and
                     payout['kind'] == 'coins' and type(payout['amount']) is int and
                     payout['amount'] in _COIN_REWARDS, *_STATE_ERROR)
            need(_valid_attempt_id(active['attempt_id']) and _time(active['started_at']) and
                 _time(active['expires_at']) and active['expires_at']-active['started_at'] == LIFETIME and
                 state['available_at'] >= active['started_at'] + COOLDOWN, *_STATE_ERROR)
            challenge, solution = active['challenge'], active['solution']
            if game == 'house':
                need(type(challenge) is dict and set(challenge) == {'question', 'options'} and
                     type(challenge['question']) is str and
                     1 <= len(challenge['question'].strip()) <= 300 and
                     type(challenge['options']) is list and 2 <= len(challenge['options']) <= 10,
                     *_STATE_ERROR)
                options = challenge['options']
                need(all(type(option) is str and 1 <= len(option) <= 100 and option == option.strip()
                         for option in options) and len(set(options)) == len(options) and
                     type(solution) is str and solution in options, *_STATE_ERROR)
            else:
                need(type(challenge) is dict and set(challenge) == {'sacks', 'shelves'} and
                     challenge['shelves'] == list(SHELVES) and type(challenge['sacks']) is list and
                     len(challenge['sacks']) == len(SACKS), *_STATE_ERROR)
                sacks = challenge['sacks']
                need(all(type(sack) is dict and set(sack) == {'id', 'label'} and
                         type(sack['id']) is str and sack['id'] in _SACK_LABELS and
                         sack['label'] == _SACK_LABELS[sack['id']] for sack in sacks), *_STATE_ERROR)
                need({sack['id'] for sack in sacks} == set(_SACK_LABELS) and
                     type(solution) is dict and solution == _SACK_CATEGORIES, *_STATE_ERROR)
        result = state['last_result']
        if result is not None:
            base_fields = {'attempt_id', 'correct', 'reward', 'answered_at'}
            need(type(result) is dict and set(result) in (base_fields, base_fields | {'reward_kind'}), *_STATE_ERROR)
            if 'reward_kind' in result:
                allowed_rewards = (_COIN_REWARDS | ({10} if game == 'house' else set())
                                   if result['reward_kind'] == 'coins' else
                                   {1} if result['reward_kind'] == 'feed' and game == 'barn' else set())
            else:
                allowed_rewards = {10 if game == 'house' else 1}
            need(_valid_attempt_id(result['attempt_id']) and type(result['correct']) is bool and
                 type(result['reward']) is int and bool(allowed_rewards) and
                 (result['reward'] in allowed_rewards if result['correct'] else result['reward'] == 0) and
                 _time(result['answered_at']), *_STATE_ERROR)
            if active is not None:
                need(result['attempt_id'] != active['attempt_id'], *_STATE_ERROR)
