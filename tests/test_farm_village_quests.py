"""Village errands and Dasha's server-timed presence rules."""
from copy import deepcopy
from uuid import uuid4

import pytest

from qw_farm.catalog import NPCS
from qw_farm.domain import FarmError, apply, make_order, new_farm, project, validate_state
from qw_farm.expansion import upgrade_state
from qw_farm import village_quests


def farm():
    return upgrade_state(new_farm(str(uuid4()), 'Village', 1000))


def run(state, npc, action, now=1000):
    return apply(state, state, 'village_quest', {'npc': npc, 'action': action}, now, str(uuid4()))


def test_legacy_order_assignment_is_unchanged():
    state = farm()
    for seq in range(3, 30):
        state['order_seq'] = seq
        order = make_order(state, 0, 1000)
        assert order['npc'] in {name for name, _ in NPCS}
    assert len(NPCS) == 9


@pytest.mark.parametrize('npc', list(village_quests.QUESTS))
def test_village_quest_take_deliver_and_repeat(npc):
    state = farm()
    spec = village_quests.QUESTS[npc]
    state['inventory'][spec['item']] = spec['qty']
    original = (state['coins'], state['xp'])
    with pytest.raises(FarmError):
        run(state, npc, 'deliver')
    run(state, npc, 'take')
    with pytest.raises(FarmError):
        run(state, npc, 'take')
    run(state, npc, 'deliver')
    assert state['coins'] == original[0] + spec['coins']
    assert state['inventory'][spec['item']] == 0
    assert state['village_errands']['quests'][npc]['phase'] == 'done'
    with pytest.raises(FarmError):
        run(state, npc, 'deliver')
    validate_state(state)


def test_active_quest_survives_day_boundary_but_completed_quest_resets_next_day():
    state = farm()
    state['inventory']['carrot'] = 4
    run(state, 'Лиса Даша', 'take', 1000)
    later = 1000 + 86400
    assert village_quests.public(state, later)['quests']['Лиса Даша'] == 'active'
    run(state, 'Лиса Даша', 'deliver', later)
    assert village_quests.public(state, later)['quests']['Лиса Даша'] == 'done'
    with pytest.raises(FarmError):
        run(state, 'Лиса Даша', 'take', later)
    assert village_quests.public(state, later + 86400)['quests']['Лиса Даша'] == 'available'
    run(state, 'Лиса Даша', 'take', later + 86400)


def test_theft_requires_live_uninterrupted_presence_and_has_daily_cooldown():
    state = farm()
    session = str(uuid4())
    assert village_quests.presence(state, 'enter', session, 1000) == 0
    assert village_quests.presence(state, 'pulse', session, 1010) == 0
    assert village_quests.presence(state, 'pulse', session, 1020) == 0
    assert village_quests.presence(state, 'pulse', session, 1030) == 0
    assert village_quests.presence(state, 'pulse', session, 1040) == 0
    assert village_quests.presence(state, 'pulse', session, 1050) == 2
    assert state['coins'] == 248 and state['starter_credit'] == 248
    assert village_quests.presence(state, 'pulse', session, 1060) == 0
    assert village_quests.presence(state, 'enter', str(uuid4()), 2000) == 0
    assert village_quests.presence(state, 'pulse', session, 2100) == 0
    assert state['coins'] == 248
    validate_state(state)


def test_talk_leave_and_lease_gap_prevent_theft():
    state = farm()
    session = str(uuid4())
    village_quests.presence(state, 'enter', session, 1000)
    village_quests.presence(state, 'talk', session, 1010)
    for now in (1020, 1030, 1040, 1050):
        assert village_quests.presence(state, 'pulse', session, now) == 0
    village_quests.presence(state, 'leave', session, 1060)
    assert village_quests.presence(state, 'pulse', session, 1100) == 0
    village_quests.presence(state, 'enter', session, 2000)
    assert village_quests.presence(state, 'pulse', session, 2100) == 0
    assert village_quests.presence(state, 'pulse', session, 2130) == 0
    assert state['coins'] == 250


def test_dasha_quest_action_itself_cancels_pending_theft():
    state = farm()
    session = str(uuid4())
    village_quests.presence(state, 'enter', session, 1000)
    run(state, 'Лиса Даша', 'take', 1010)
    for now in (1020, 1030, 1040, 1050):
        assert village_quests.presence(state, 'pulse', session, now) == 0
    assert state['village_errands']['presence']['talked'] is True


def test_theft_clamps_to_available_coins_and_owner_projection():
    owner = farm()
    visitor = farm()
    owner['coins'] = owner['starter_credit'] = 1
    session = str(uuid4())
    village_quests.presence(owner, 'enter', session, 1000)
    for now in (1010, 1020, 1030, 1040):
        village_quests.presence(owner, 'pulse', session, now)
    assert village_quests.presence(owner, 'pulse', session, 1050) == 1
    assert owner['coins'] == owner['starter_credit'] == 0
    assert 'village_errands' in project(owner, owner, 1050)
    owner['settings']['visibility'] = 'public'
    assert 'village_errands' not in project(owner, visitor, 1050)
