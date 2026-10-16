from copy import deepcopy
from uuid import uuid4

import pytest

from qw_farm import minigames
from qw_farm import economy, progression
from qw_farm.catalog import LEVELS, income_ref
from qw_farm.domain import FarmError, new_farm
from qw_farm.expansion import upgrade_state
from qw_farm.service import FarmService, Principal


NOW = 50_000
QUESTION = {'question': 'Сколько будет два плюс два?',
            'options': ['3', '4', '5'], 'correct_option_text': '4'}


def _farm():
    # every real farm carries xp: the reward size depends on the player's level (minigames.next_reward)
    return {'coins': 0, 'inventory': {}, 'xp': 0}


def _start_house(farm, now=NOW):
    message, started = minigames.start(farm, {'game': 'house'}, now, QUESTION)
    assert started
    assert message == 'Задание начато.'
    return farm['minigames']['house']['active']['attempt_id']


def test_house_question_reward_cooldown_and_repeat_answer_are_idempotent():
    farm = _farm()
    attempt_id = _start_house(farm)
    active = farm['minigames']['house']['active']

    assert active['challenge'] == {'question': QUESTION['question'], 'options': QUESTION['options']}
    assert active['solution'] == '4'
    assert farm['minigames']['house']['available_at'] == NOW + minigames.COOLDOWN
    assert minigames.should_select_question(farm, {'game': 'house'}, NOW) is False
    # the payout is snapshotted at start and scales with the player's level: coins = income_ref(level) // 100, at least 10
    reward = active['reward']
    assert reward == {'kind': 'coins', 'amount': max(10, income_ref(1) // 100)} and reward['amount'] >= 10

    assert minigames.answer(farm, {'game': 'house', 'attempt_id': attempt_id, 'answer': '4'}, NOW + 2) == ('Верно!', True)
    assert farm['coins'] == reward['amount']
    assert farm['minigames']['house']['active'] is None
    assert minigames.answer(farm, {'game': 'house', 'attempt_id': attempt_id, 'answer': '3'}, NOW + 3) == ('Верно!', False)
    assert farm['coins'] == reward['amount']
    with pytest.raises(FarmError) as error:
        minigames.start(farm, {'game': 'house'}, NOW + 4, QUESTION)
    assert error.value.code == 'minigame_cooldown'


def test_wrong_house_answer_gives_no_reward_and_records_result():
    farm = _farm()
    attempt_id = _start_house(farm)

    assert minigames.answer(farm, {'game': 'house', 'attempt_id': attempt_id, 'answer': '3'}, NOW + 1) == ('На этот раз не вышло.', True)
    assert farm['coins'] == 0
    assert farm['minigames']['house']['last_result']['reward'] == 0


def test_barn_correct_answer_rewards_coins_and_feed_and_public_state_never_exposes_solution():
    farm = _farm()
    minigames.start(farm, {'game': 'barn'}, NOW)
    active = farm['minigames']['barn']['active']
    public = minigames.public(farm, NOW)['barn']['active']

    assert set(public) == {'sacks', 'shelves', 'attempt_id', 'started_at', 'expires_at', 'reward'}   # the promised payout is public, the solution is not
    assert 'solution' not in public
    assert all('category' not in sack for sack in public['sacks'])
    solution = deepcopy(active['solution'])
    assert minigames.answer(farm, {'game': 'barn', 'attempt_id': active['attempt_id'], 'answer': solution}, NOW + 1) == ('Верно!', True)
    assert public['reward'] == {'kind': 'coins', 'amount': public['reward']['amount'], 'bonus_feed': 1}
    assert farm['coins'] == public['reward']['amount'] and farm['inventory'].get('feed', 0) == 1
    assert farm['minigames']['barn']['last_result']['bonus_feed'] == 1
    assert minigames.public(farm, NOW + 2)['barn']['next_reward']['bonus_feed'] == 1
    assert 'bonus_feed' not in minigames.public(farm, NOW + 2)['house']['next_reward']
    # replaying the same attempt pays nothing more
    assert minigames.answer(farm, {'game': 'barn', 'attempt_id': active['attempt_id'], 'answer': solution}, NOW + 3)[1] is False
    assert farm['inventory']['feed'] == 1 and farm['coins'] == public['reward']['amount']
    minigames.validate(farm)


def test_barn_wrong_answer_pays_nothing():
    farm = _farm()
    minigames.start(farm, {'game': 'barn'}, NOW)
    active = farm['minigames']['barn']['active']
    wrong = {key: 'berry' if value != 'berry' else 'grain' for key, value in active['solution'].items()}
    assert minigames.answer(farm, {'game': 'barn', 'attempt_id': active['attempt_id'], 'answer': wrong}, NOW + 1) == ('На этот раз не вышло.', True)
    assert farm['coins'] == 0 and farm['inventory'].get('feed', 0) == 0
    assert farm['minigames']['barn']['last_result']['bonus_feed'] == 0
    minigames.validate(farm)


def test_old_barn_attempts_keep_their_payout_and_old_states_validate():
    amount = minigames.next_reward(_farm())['amount']
    for reward, coins, feed in ((None, 0, 1), ({'kind': 'coins', 'amount': amount}, amount, 0),
                                ({'kind': 'coins', 'amount': amount, 'bonus_feed': 1}, amount, 1)):
        farm = _farm()
        minigames.start(farm, {'game': 'barn'}, NOW)
        active = farm['minigames']['barn']['active']
        if reward is None:
            del active['reward']
        else:
            active['reward'] = reward
        minigames.validate(farm)
        solution = deepcopy(active['solution'])
        minigames.answer(farm, {'game': 'barn', 'attempt_id': active['attempt_id'], 'answer': solution}, NOW + 1)
        assert (farm['coins'], farm['inventory'].get('feed', 0)) == (coins, feed)
        minigames.validate(farm)
    legacy = {'attempt_id': str(uuid4()), 'correct': True, 'reward': 1, 'reward_kind': 'feed', 'answered_at': NOW}
    farm = _farm()
    minigames.upgrade(farm)
    farm['minigames']['barn']['last_result'] = legacy
    minigames.validate(farm)
    farm['minigames']['barn']['last_result'] = {k: v for k, v in legacy.items() if k != 'reward_kind'}
    minigames.validate(farm)


def test_validate_rejects_bad_bonus_feed():
    def bad(game, mutate):
        farm = _farm()
        minigames.start(farm, {'game': game}, NOW, QUESTION)
        mutate(farm['minigames'][game]['active'])
        with pytest.raises(FarmError):
            minigames.validate(farm)

    bad('barn', lambda a: a['reward'].update(bonus_feed=2))
    bad('barn', lambda a: a['reward'].update(bonus_feed=True))
    bad('house', lambda a: a['reward'].update(bonus_feed=1))
    farm = _farm()
    minigames.upgrade(farm)
    result = {'attempt_id': str(uuid4()), 'correct': True, 'reward': 10, 'reward_kind': 'coins',
              'bonus_feed': 1, 'answered_at': NOW}
    farm['minigames']['house']['last_result'] = dict(result)
    with pytest.raises(FarmError):
        minigames.validate(farm)
    for bonus, correct in ((2, True), (0, True), (1, False)):
        farm['minigames']['house']['last_result'] = None
        farm['minigames']['barn']['last_result'] = dict(result, bonus_feed=bonus, correct=correct,
                                                         reward=10 if correct else 0)
        with pytest.raises(FarmError):
            minigames.validate(farm)


def test_attempt_started_before_the_reward_snapshot_keeps_its_old_payout():
    # old attempts have no 'reward' key and still pay what they promised: 1 feed for the barn (no coins)
    farm = _farm()
    minigames.start(farm, {'game': 'barn'}, NOW)
    active = farm['minigames']['barn']['active']
    del active['reward']
    solution = deepcopy(active['solution'])
    assert minigames.answer(farm, {'game': 'barn', 'attempt_id': active['attempt_id'], 'answer': solution}, NOW + 1) == ('Верно!', True)
    assert farm['inventory']['feed'] == 1 and farm['coins'] == 0


def test_expired_attempt_is_hidden_and_cannot_be_answered():
    farm = _farm()
    attempt_id = _start_house(farm)
    active = farm['minigames']['house']['active']
    public = minigames.public(farm, active['expires_at'])

    assert public['house']['active'] is None
    with pytest.raises(FarmError) as error:
        minigames.answer(farm, {'game': 'house', 'attempt_id': attempt_id, 'answer': '4'}, active['expires_at'])
    assert error.value.code == 'attempt_expired'
    assert farm['minigames']['house']['last_result'] is None


def test_service_answers_touch_and_bill_once_even_when_attempt_is_replayed():
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
        farm = upgrade_state(new_farm(str(uuid4()), 'Service', NOW))
        farm['xp'] = LEVELS[10]
        farm['coins'], farm['starter_credit'] = 1_000, 250
        attempt_id = minigames.start(farm, {'game': 'barn'}, NOW)[1]
        assert attempt_id
        attempt_id = farm['minigames']['barn']['active']['attempt_id']

        day = economy.moscow_day(NOW)
        economy.state(farm)['billed_day'] = day - 1
        progress = progression.progress(farm)
        progress.update(day=day - 1, last=day - 1)

        unit = FakeUnit('account', farm)
        clock = [NOW]
        service = FarmService(unit, Principal('account', 'Игрок'), clock=lambda: clock[0])
        data = {'game': 'barn', 'attempt_id': attempt_id,
                'answer': deepcopy(farm['minigames']['barn']['active']['solution'])}
        await service.command('answer-0001', 'minigame_answer', data)

        assert farm['progress']['last'] == day
        assert farm['economy']['billed_day'] == day
        billed_coins = farm['coins']
        billed_total = farm['economy']['stats']['upkeep_billed']
        billed_paid = farm['economy']['stats']['upkeep_paid']

        clock[0] = NOW + 86_400
        replay = await service.command('answer-0002', 'minigame_answer', data)

        assert replay['notice'] == 'Верно!'
        assert farm['progress']['last'] == day
        assert farm['economy']['billed_day'] == day
        assert farm['coins'] == billed_coins
        assert farm['economy']['stats']['upkeep_billed'] == billed_total
        assert farm['economy']['stats']['upkeep_paid'] == billed_paid

    import asyncio
    asyncio.run(run())

