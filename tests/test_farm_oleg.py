from copy import deepcopy
from uuid import uuid4

import pytest

from qw_farm import oleg, progression
from qw_farm.catalog import LEVELS
from qw_farm.domain import FarmError, new_farm, project
from qw_farm.expansion import upgrade_state
from qw_farm.service import FarmService, Principal


NOW = 1_800_000_000
DAY = progression.moscow_day(NOW)
NEXT_DAY = (DAY + 1) * 86400 - 10800


def _farm():
    return {'coins': 0, 'inventory': {}, 'xp': 0,
            'progress': dict(day=DAY, dew=10**9, short=0, pool=0, last=DAY, carry=0,
                             total=dict(m1=0, m2=0, m3=0))}


def _start(farm, now=NOW):
    message, changed = oleg.start(farm, {}, now)
    assert changed and message == 'Олег готов. Послушай первую мелодию.'
    return farm['oleg_game']['run']


def _solve(farm, run=None, now=NOW):
    run = run or farm['oleg_game']['run']
    run_id, sequences = run['id'], deepcopy(run['sequences'])
    for number, notes in enumerate(sequences):
        message, changed = oleg.answer(farm, {'run_id': run_id, 'round': number, 'notes': notes}, now)
        assert changed
    return message


def _wrong(notes):
    return [(notes[0] + 1) % oleg.BELLS] + list(notes[1:])


def test_public_projection_exposes_only_the_current_round():
    farm = _farm()
    run = _start(farm)
    seen = oleg.public(farm, NOW)

    assert [len(sequence) for sequence in run['sequences']] == list(oleg.NOTES) == [3, 4, 5]
    assert all(0 <= note < oleg.BELLS for sequence in run['sequences'] for note in sequence)
    assert set(seen['active']) == {'run_id', 'round', 'rounds', 'notes', 'sequence', 'started_at'}
    assert seen['active']['sequence'] == run['sequences'][0] and seen['active']['round'] == 0
    assert seen['rounds'] == [3, 4, 5] and seen['next_reward'] == {'coins': 12, 'xp': 4}
    assert seen['rewarded_today'] is False and seen['last_result'] is None

    oleg.answer(farm, {'run_id': run['id'], 'round': 0, 'notes': run['sequences'][0]}, NOW + 1)
    seen = oleg.public(farm, NOW + 1)
    assert seen['active']['round'] == 1 and seen['active']['sequence'] == run['sequences'][1]
    assert seen['active']['notes'] == 4
    oleg.validate(farm)


def test_wrong_notes_keep_the_round_and_pay_nothing():
    farm = _farm()
    run = _start(farm)
    message, changed = oleg.answer(farm, {'run_id': run['id'], 'round': 0,
                                          'notes': _wrong(run['sequences'][0])}, NOW + 1)

    assert changed is False and 'Не совпало' in message
    assert farm['oleg_game']['run']['round'] == 0
    assert farm['oleg_game']['last_result'] is None
    assert farm['coins'] == 0 and farm['xp'] == 0
    oleg.validate(farm)


def test_three_rounds_pay_once_per_moscow_day():
    farm = _farm()
    run = _start(farm)
    message = _solve(farm, run, NOW + 10)

    assert message == 'Три мелодии сыграны! +12 монет и +4 опыта.'
    assert farm['coins'] == 12 and farm['xp'] == 4
    assert farm['oleg_game']['run'] is None
    assert farm['oleg_game']['reward_day'] == DAY
    assert farm['oleg_game']['last_result'] == dict(run_id=run['id'], at=NOW + 10, rewarded=True,
                                                    coins=12, xp=4)
    assert oleg.public(farm, NOW + 11)['rewarded_today'] is True

    second = _start(farm, NEXT_DAY - 1)
    message = _solve(farm, second, NEXT_DAY - 1)
    assert 'уже получена' in message
    assert farm['coins'] == 12 and farm['xp'] == 4
    assert farm['oleg_game']['last_result']['rewarded'] is False
    assert farm['oleg_game']['last_result']['coins'] == 0 and farm['oleg_game']['last_result']['xp'] == 0

    third = _start(farm, NEXT_DAY)
    progression.progress(farm).update(day=DAY + 1, dew=10**9, last=DAY + 1)
    _solve(farm, third, NEXT_DAY)
    assert farm['coins'] == 24 and farm['xp'] == 8
    assert farm['oleg_game']['reward_day'] == DAY + 1
    oleg.validate(farm)


def test_invalid_payloads_are_rejected():
    farm = _farm()
    with pytest.raises(FarmError) as error:
        oleg.start(farm, {'round': 0}, NOW)
    assert error.value.code == 'invalid_command'

    run = _start(farm)
    with pytest.raises(FarmError) as error:
        oleg.answer(farm, {'run_id': 'not-a-uuid', 'round': 0, 'notes': [0, 0, 0]}, NOW)
    assert error.value.code == 'invalid_run'
    with pytest.raises(FarmError) as error:
        oleg.answer(farm, {'run_id': str(uuid4()), 'round': 0, 'notes': [0, 0, 0]}, NOW)
    assert error.value.code == 'run_not_found' and error.value.status == 404
    with pytest.raises(FarmError) as error:
        oleg.answer(farm, {'run_id': run['id'], 'round': 1, 'notes': [0, 0, 0]}, NOW)
    assert error.value.code == 'stale_round'
    for notes in ([0, 0], [0, 0, 0, 0], [0, 0, True], [0, 0, 4], ['0', 0, 0]):
        with pytest.raises(FarmError) as error:
            oleg.answer(farm, {'run_id': run['id'], 'round': 0, 'notes': notes}, NOW)
        assert error.value.code == 'invalid_answer'


def test_validate_rejects_tampered_state_and_accepts_a_farm_without_the_game():
    oleg.validate(_farm())

    def tampered(mutate):
        farm = _farm()
        _start(farm)
        mutate(farm['oleg_game'])
        with pytest.raises(FarmError):
            oleg.validate(farm)

    tampered(lambda state: state['run']['sequences'][0].append(0))
    tampered(lambda state: state['run']['sequences'][2].__setitem__(0, 4))
    tampered(lambda state: state['run'].__setitem__('round', 3))
    farm = _farm()
    _solve(farm, _start(farm))
    farm['oleg_game']['last_result']['coins'] = 0
    with pytest.raises(FarmError):
        oleg.validate(farm)
    farm = _farm()
    _solve(farm, _start(farm))
    farm['oleg_game']['last_result']['xp'] = 0
    with pytest.raises(FarmError):
        oleg.validate(farm)


def test_owner_projection_includes_the_game_and_guests_never_see_it():
    farm = upgrade_state(new_farm(str(uuid4()), 'Олег', NOW))
    other = upgrade_state(new_farm(str(uuid4()), 'Гость', NOW))
    farm['settings']['visibility'] = 'public'
    _start(farm)

    assert project(farm, farm, NOW)['oleg_game']['active']['round'] == 0
    assert 'oleg_game' not in project(farm, other, NOW)


def test_service_replay_refreshes_state_without_a_second_reward_and_wrong_answers_are_free():
    class FakeUnit:
        def __init__(self, account_id, farm):
            self.account_id, self.farm = account_id, farm
            self.receipts = {}

        async def lock(self, *keys):
            pass

        async def by_account(self, account_id):
            return self.farm if account_id == self.account_id else None

        async def get(self, farm_id):
            return self.farm if farm_id == self.farm['id'] else None

        async def owner_account(self, farm_id):
            return self.account_id

        async def save(self, farm, account_id=None):
            self.farm = farm

        async def receipt(self, account_id, key):
            return self.receipts.get((account_id, key))

        async def remember(self, account_id, key, fingerprint, result, now):
            self.receipts[(account_id, key)] = {'fingerprint': fingerprint, 'result': result}

        async def record(self, *args):
            pass

    async def run():
        farm = upgrade_state(new_farm(str(uuid4()), 'Сервис', NOW))
        farm['xp'] = LEVELS[10]
        farm['coins'], farm['starter_credit'] = 1_000, 250
        progress = progression.progress(farm)
        progress.update(day=DAY, dew=10**9, last=DAY)

        unit = FakeUnit('account', farm)
        clock = [NOW]
        service = FarmService(unit, Principal('account', 'Игрок'), clock=lambda: clock[0])

        started = await service.command('oleg-start-01', 'oleg_start', {})
        started_revision = started['revision']
        run = farm['oleg_game']['run']
        wrong = {'run_id': run['id'], 'round': 0, 'notes': _wrong(run['sequences'][0])}
        missed = await service.command('oleg-wrong-01', 'oleg_answer', wrong)
        assert missed['oleg_game']['active']['round'] == 0
        assert missed['revision'] == started_revision
        assert farm['coins'] == 1_000 and unit.farm['oleg_game']['run']['round'] == 0

        for number, notes in enumerate(deepcopy(run['sequences'])):
            clock[0] = NOW + number + 1
            result = await service.command(f'oleg-round-{number:02}', 'oleg_answer',
                                           {'run_id': run['id'], 'round': number, 'notes': notes})
            if number < 2:
                assert result['oleg_game']['active']['round'] == number + 1
            else:
                assert result['oleg_game']['active'] is None
        assert farm['coins'] == 1_012 and farm['xp'] == LEVELS[10] + 4
        completed_revision = farm['revision']

        replay_wrong = await service.command('oleg-wrong-01', 'oleg_answer', wrong)
        assert 'Не совпало' in replay_wrong['notice']
        assert replay_wrong['oleg_game']['active'] is None
        assert replay_wrong['revision'] == completed_revision
        replay_complete = await service.command('oleg-round-02', 'oleg_answer',
                                                {'run_id': run['id'], 'round': 2, 'notes': deepcopy(run['sequences'])[2]})
        assert replay_complete['revision'] == completed_revision
        assert farm['coins'] == 1_012 and farm['xp'] == LEVELS[10] + 4

        with pytest.raises(FarmError) as error:
            await service.command('oleg-foreign-01', 'oleg_start', {}, target_id=str(uuid4()))
        assert error.value.code == 'not_owner' and error.value.status == 403

    import asyncio
    asyncio.run(run())
