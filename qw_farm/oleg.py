"""Oleg's bell memory game. Three rounds, free retries, one coin-and-XP reward per Moscow day."""
from copy import deepcopy
from random import SystemRandom
from uuid import UUID, uuid4

from . import progression
from .domain import need

ROUNDS = 3
NOTES = (3, 4, 5)
BELLS = 4
MODIFIERS = ('echo', 'false_note', 'acceleration', 'shuffle')
REWARD_COINS = 12
REWARD_XP = 4
MAX_TIME = 10**12
STATE_ERROR = ('invalid_oleg_state', 'Некорректное состояние перезвона.', 500)


def blank():
    return dict(reward_day=-1, run=None, last_result=None)


def state(farm):
    return farm.setdefault('oleg_game', blank())


def _sequences():
    rng = SystemRandom()
    return [[rng.randrange(BELLS) for _ in range(length)] for length in NOTES]


def modifier_for_day(now):
    return MODIFIERS[progression.moscow_day(now) % len(MODIFIERS)]


def expected_notes(run, round_no):
    sequence = run['sequences'][round_no]
    if run.get('modifier') == 'echo':
        return list(reversed(sequence))
    if run.get('modifier') == 'false_note':
        return [run['false_notes'][round_no]]
    return list(sequence)


def _run_id(value):
    if type(value) is not str or len(value) != 36:
        return False
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError, TypeError):
        return False
    return parsed.version == 4 and str(parsed) == value


def _time(value):
    return type(value) is int and 0 <= value <= MAX_TIME


def public(farm, now):
    s = farm.get('oleg_game') or blank()
    run = s.get('run')
    active = None
    if run:
        modifier = run.get('modifier', 'classic')
        sequence = list(run['sequences'][run['round']])
        active = dict(run_id=run['id'], round=run['round'], rounds=ROUNDS,
                      notes=len(expected_notes(run, run['round'])), sequence=sequence,
                      started_at=run['started_at'], modifier=modifier)
        if modifier == 'false_note':
            active['reference_sequence'] = list(sequence)
            sequence.insert(len(sequence) // 2, run['false_notes'][run['round']])
        if modifier == 'shuffle':
            offset = 1 + (progression.moscow_day(run['started_at']) + run['round']) % (BELLS - 1)
            active['bell_order'] = [(i + offset) % BELLS for i in range(BELLS)]
    return dict(active=active, rewarded_today=s['reward_day'] == progression.moscow_day(now),
                modifier=modifier_for_day(now),
                next_reward=dict(coins=REWARD_COINS, xp=REWARD_XP),
                rounds=list(NOTES), last_result=deepcopy(s.get('last_result')))


def _fields(data, fields):
    need(type(data) is dict and set(data) == fields, 'invalid_command',
         'Некорректные параметры перезвона.', 422)


def start(farm, data, now):
    _fields(data, set())
    state(farm)['run'] = dict(id=str(uuid4()), started_at=now, round=0, sequences=_sequences())
    run = state(farm)['run']
    run['modifier'] = modifier_for_day(now)
    if run['modifier'] == 'false_note':
        rng = SystemRandom()
        run['false_notes'] = [rng.randrange(BELLS) for _ in NOTES]
        run['sequences'] = [[rng.choice([n for n in range(BELLS) if n != extra])
                             for _ in range(length)]
                            for length, extra in zip(NOTES, run['false_notes'])]
    return 'Олег готов. Послушай первую мелодию.', True


def answer(farm, data, now):
    _fields(data, {'run_id', 'round', 'notes'})
    run_id, round_no, notes = data['run_id'], data['round'], data['notes']
    need(_run_id(run_id), 'invalid_run', 'Некорректный номер перезвона.', 422)
    s = state(farm)
    run = s['run']
    need(run is not None and run['id'] == run_id,
         'run_not_found', 'Перезвон не найден. Начни заново.', 404)
    need(type(round_no) is int and round_no == run['round'],
         'stale_round', 'Этот раунд уже прошёл. Продолжай с текущей мелодии.', 409)
    expected = expected_notes(run, round_no)
    length = len(expected)
    need(type(notes) is list and len(notes) == length and
         all(type(note) is int and 0 <= note < BELLS for note in notes),
         'invalid_answer', 'Повтори мелодию колокольчиками 1–4.', 422)
    if notes != expected:
        return 'Не совпало. Послушай мелодию ещё раз и повтори.', False
    if round_no + 1 < ROUNDS:
        run['round'] = round_no + 1
        return f'Верно! Раунд {round_no + 1} из {ROUNDS} пройден.', True
    day = progression.moscow_day(now)
    rewarded = s['reward_day'] != day
    coins = xp = 0
    if rewarded:
        s['reward_day'] = day
        coins = REWARD_COINS
        farm['coins'] += coins
        xp = progression.grant_xp(farm, REWARD_XP, 'oleg', now, True)
    s['run'] = None
    s['last_result'] = dict(run_id=run_id, at=now, rewarded=rewarded, coins=coins, xp=xp)
    return ('Три мелодии сыграны! +12 монет и +4 опыта.' if rewarded else
            'Три мелодии сыграны! Сегодняшняя награда уже получена — приходи завтра.'), True


def validate(farm):
    s = farm.get('oleg_game')
    if s is None:
        return
    need(type(s) is dict and set(s) == {'reward_day', 'run', 'last_result'}, *STATE_ERROR)
    need(type(s['reward_day']) is int and -1 <= s['reward_day'] <= MAX_TIME, *STATE_ERROR)
    run = s['run']
    if run is not None:
        fields = {'id', 'started_at', 'round', 'sequences'}
        need(type(run) is dict, *STATE_ERROR)
        if 'modifier' in run:
            need(run['modifier'] in MODIFIERS, *STATE_ERROR)
            fields.add('modifier')
            if run['modifier'] == 'false_note':
                fields.add('false_notes')
        need(set(run) == fields, *STATE_ERROR)
        need(_run_id(run['id']) and _time(run['started_at']) and
             type(run['round']) is int and 0 <= run['round'] < ROUNDS, *STATE_ERROR)
        sequences = run['sequences']
        need(type(sequences) is list and len(sequences) == ROUNDS and
             all(type(seq) is list and len(seq) == NOTES[i] and
                 all(type(note) is int and 0 <= note < BELLS for note in seq)
                 for i, seq in enumerate(sequences)), *STATE_ERROR)
        if run.get('modifier') == 'false_note':
            extra = run['false_notes']
            need(type(extra) is list and len(extra) == ROUNDS and
                 all(type(n) is int and 0 <= n < BELLS and n not in sequences[i]
                     for i, n in enumerate(extra)), *STATE_ERROR)
    result = s['last_result']
    if result is not None:
        need(type(result) is dict and set(result) == {'run_id', 'at', 'rewarded', 'coins', 'xp'} and
             _run_id(result['run_id']) and _time(result['at']) and
             type(result['rewarded']) is bool and type(result['coins']) is int and
             type(result['xp']) is int and result['coins'] == (REWARD_COINS if result['rewarded'] else 0) and
             0 <= result['xp'], *STATE_ERROR)
        need(not result['rewarded'] or result['xp'] >= REWARD_XP, *STATE_ERROR)
