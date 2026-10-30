"""Pure rules for open tables: start rule, waiting list, portraits, early close, discussion, codes."""
from uuid import UUID

import pytest

import domain.mafia as mafia
from application import room_limits
from domain.mafia import (PORTRAIT_COUNT, TableFull, cast_vote, discussion_access, join_lobby,
                          night_action, night_complete, normalized_lobby, open_table_summary, phase_complete,
                          leave_table, own_role, public_lobby, remove_player, restart_lobby, set_portrait, set_ready,
                          start_lobby, unseat_lobby, wait_lobby)

ROOM = 'room-open-1'


def acc(number):
    return str(UUID(int=number))


def table(count, ready=None):
    lobby = None
    for number in range(1, count + 1):
        lobby, _ = join_lobby(lobby, room_id=ROOM, account_id=acc(number), name=f'P{number}')
    for number in (ready if ready is not None else range(1, count + 1)):
        lobby = set_ready(lobby, room_id=ROOM, account_id=acc(number), ready=True,
                          expected_revision=lobby['revision'])
    return lobby


def start(lobby, who=1):
    return start_lobby(lobby, room_id=ROOM, account_id=acc(who), expected_revision=lobby['revision'])


def test_start_needs_four_ready_and_unready_sit_out(monkeypatch):
    monkeypatch.setattr(mafia, 'START_REQUIRES_ALL_READY', False)
    lobby = table(6, ready=[1, 2, 3, 4])
    view = public_lobby(lobby, room_id=ROOM, viewer_account_id=acc(1))
    assert view['can_start'] and view['ready_count'] == 4 and not view['start_requires_all_ready']
    started = start(lobby)
    assert [p['account_id'] for p in started['players']] == [acc(n) for n in (1, 2, 3, 4)]
    assert [w['account_id'] for w in started['waiting']] == [acc(5), acc(6)]
    assert set(started['assignments']) == {acc(n) for n in (1, 2, 3, 4)}
    shown = public_lobby(started, room_id=ROOM, viewer_account_id=acc(5))
    assert shown['is_waiting'] and not shown['joined']
    assert [w['name'] for w in shown['waiting']] == ['P5', 'P6'] and 'account_id' not in str(shown)
    with pytest.raises(ValueError):  # three ready are not enough
        start(table(5, ready=[1, 2, 3]))
    with pytest.raises(ValueError, match='себя готовым'):  # the host must be among the ready
        start(table(5, ready=[2, 3, 4, 5]))
    assert not public_lobby(table(5, ready=[2, 3, 4, 5]), room_id=ROOM, viewer_account_id=acc(1))['can_start']


def test_telegram_group_tables_keep_the_everyone_ready_rule():
    """The start-from-four rule belongs to app-room tables; a Telegram group table has no queue on screen."""
    chat = None
    for number in range(1, 6):
        chat, _ = join_lobby(chat, chat_id=-100500, account_id=acc(number), name=f'P{number}')
    for number in range(1, 5):
        chat = set_ready(chat, chat_id=-100500, account_id=acc(number), ready=True, expected_revision=chat['revision'])
    view = public_lobby(chat, chat_id=-100500, viewer_account_id=acc(1))
    assert view['start_requires_all_ready'] and not view['can_start'] and view['ready_count'] == 4
    with pytest.raises(ValueError, match='готовы все'):
        start_lobby(chat, chat_id=-100500, account_id=acc(1), expected_revision=chat['revision'])
    chat = set_ready(chat, chat_id=-100500, account_id=acc(5), ready=True, expected_revision=chat['revision'])
    assert public_lobby(chat, chat_id=-100500, viewer_account_id=acc(1))['can_start']
    started = start_lobby(chat, chat_id=-100500, account_id=acc(1), expected_revision=chat['revision'])
    assert started['status'] == 'night' and len(started['players']) == 5 and 'waiting' not in started
    # the same four-of-five table in an app room starts and the fifth waits
    app_room = table(5, ready=[1, 2, 3, 4])
    assert not public_lobby(app_room, room_id=ROOM, viewer_account_id=acc(1))['start_requires_all_ready']
    assert public_lobby(app_room, room_id=ROOM, viewer_account_id=acc(1))['can_start']


def test_start_rule_can_be_reverted_to_everyone_ready(monkeypatch):
    monkeypatch.setattr(mafia, 'START_REQUIRES_ALL_READY', True)
    lobby = table(5, ready=[1, 2, 3, 4])
    assert not public_lobby(lobby, room_id=ROOM, viewer_account_id=acc(1))['can_start']
    with pytest.raises(ValueError, match='готовы все'):
        start(lobby)
    assert start(table(5))['status'] == 'night'


def test_waiting_joins_rematch_and_capacity_counts_waiting(monkeypatch):
    started = start(table(5, ready=[1, 2, 3, 4]))
    assert wait_lobby(started, room_id=ROOM, account_id=acc(5), name='P5')[1] is False  # already waiting
    started, changed = wait_lobby(started, room_id=ROOM, account_id=acc(9), name='Новичок')
    assert changed and len(started['waiting']) == 2
    with pytest.raises(ValueError, match='играешь'):
        wait_lobby(started, room_id=ROOM, account_id=acc(2), name='x')
    with pytest.raises(ValueError, match='собирается'):
        wait_lobby(table(4), room_id=ROOM, account_id=acc(9), name='x')
    for number in range(20, 26):  # 4 players + 2 waiting + 6 = 12
        started, _ = wait_lobby(started, room_id=ROOM, account_id=acc(number), name=f'W{number}')
    with pytest.raises(TableFull):
        wait_lobby(started, room_id=ROOM, account_id=acc(99), name='late')
    finished = dict(started, status='finished', winner='citizens', alive=list(started['alive']))
    again = restart_lobby(finished, room_id=ROOM, account_id=acc(1), expected_revision=finished['revision'])
    assert again['status'] == 'lobby' and len(again['players']) == 12 and 'waiting' not in again
    assert not any(p['ready'] for p in again['players'])
    assert len({p['portrait'] for p in again['players']}) == 12
    left = restart_lobby(finished, room_id=ROOM, account_id=acc(1), expected_revision=finished['revision'],
                         active_accounts={acc(2), acc(3), acc(20)})
    assert [p['account_id'] for p in left['players']] == [acc(1), acc(2), acc(3), acc(20)]


def test_waiting_list_never_exceeds_table_capacity():
    started = start(table(4))
    started['waiting'] = [{'account_id': acc(100 + n), 'name': f'W{n}'} for n in range(10)]
    clean = normalized_lobby(started, room_id=ROOM)
    assert len(clean['players']) + len(clean['waiting']) == 12


def test_portraits_are_unique_default_by_seat_and_chosen_in_lobby():
    lobby = table(5)
    assert [p['portrait'] for p in lobby['players']] == [1, 2, 3, 4, 5]
    shown = public_lobby(lobby, room_id=ROOM, viewer_account_id=acc(1))
    assert [p['portrait'] for p in shown['players']] == [1, 2, 3, 4, 5] and shown['portrait_count'] == PORTRAIT_COUNT
    picked = set_portrait(lobby, room_id=ROOM, account_id=acc(2), portrait=9, expected_revision=lobby['revision'])
    assert picked['players'][1]['portrait'] == 9 and picked['revision'] == lobby['revision'] + 1
    with pytest.raises(ValueError, match='занят'):
        set_portrait(picked, room_id=ROOM, account_id=acc(3), portrait=9, expected_revision=picked['revision'])
    with pytest.raises(ValueError):
        set_portrait(picked, room_id=ROOM, account_id=acc(3), portrait=PORTRAIT_COUNT + 1,
                     expected_revision=picked['revision'])
    with pytest.raises(ValueError):
        set_portrait(picked, room_id=ROOM, account_id=acc(3), portrait=True, expected_revision=picked['revision'])
    with pytest.raises(RuntimeError):
        set_portrait(picked, room_id=ROOM, account_id=acc(3), portrait=10, expected_revision=0)
    with pytest.raises(PermissionError):
        set_portrait(picked, room_id=ROOM, account_id=acc(77), portrait=10, expected_revision=picked['revision'])
    full = table(12)
    assert sorted(p['portrait'] for p in full['players']) == list(range(1, 13))
    # Seat leaves, the next player's stored portrait does not move; a new one takes a free number.
    after = unseat_lobby(full, room_id=ROOM, account_id=acc(4))[0]
    assert [p['portrait'] for p in after['players']][:3] == [1, 2, 3] and after['players'][3]['portrait'] == 5
    rejoined, _ = join_lobby(after, room_id=ROOM, account_id=acc(50), name='N')
    assert rejoined['players'][-1]['portrait'] == 13  # scanning from the seat number finds the new free 13th portrait
    # Old states without portraits get deterministic unique ones.
    legacy = {k: v for k, v in table(4).items()}
    for player in legacy['players']:
        del player['portrait']
    assert [p['portrait'] for p in normalized_lobby(legacy, room_id=ROOM)['players']] == [1, 2, 3, 4]


def test_remove_player_rules():
    lobby = table(5)
    removed, account, name = remove_player(lobby, room_id=ROOM, account_id=acc(1), target='p3',
                                          expected_revision=lobby['revision'])
    assert account == acc(3) and name == 'P3' and len(removed['players']) == 4
    with pytest.raises(PermissionError):
        remove_player(lobby, room_id=ROOM, account_id=acc(2), target='p3', expected_revision=lobby['revision'])
    with pytest.raises(ValueError, match='Себя'):
        remove_player(lobby, room_id=ROOM, account_id=acc(1), target='p1', expected_revision=lobby['revision'])
    with pytest.raises(RuntimeError):
        remove_player(lobby, room_id=ROOM, account_id=acc(1), target='p3', expected_revision=0)
    with pytest.raises(ValueError):
        remove_player(lobby, room_id=ROOM, account_id=acc(1), target='p9', expected_revision=lobby['revision'])
    started = start(lobby)
    with pytest.raises(ValueError, match='Во время партии'):
        remove_player(started, room_id=ROOM, account_id=acc(1), target='p2', expected_revision=started['revision'])
    started, _ = wait_lobby(started, room_id=ROOM, account_id=acc(9), name='W')
    after, account, _ = remove_player(started, room_id=ROOM, account_id=acc(1), target='w1',
                                      expected_revision=started['revision'])
    assert account == acc(9) and 'waiting' not in after


def test_unseat_and_waiting_cancel():
    lobby = table(4)
    after, changed = unseat_lobby(lobby, room_id=ROOM, account_id=acc(3))
    assert changed and len(after['players']) == 3
    with pytest.raises(PermissionError):
        unseat_lobby(lobby, room_id=ROOM, account_id=acc(1))
    started = start(lobby)
    with pytest.raises(ValueError):
        unseat_lobby(started, room_id=ROOM, account_id=acc(2))
    started, _ = wait_lobby(started, room_id=ROOM, account_id=acc(9), name='W')
    cancelled, changed = unseat_lobby(started, room_id=ROOM, account_id=acc(9))
    assert changed and 'waiting' not in cancelled
    assert unseat_lobby(cancelled, room_id=ROOM, account_id=acc(9))[1] is False


def test_open_table_summary_has_no_accounts():
    lobby = table(4)
    summary = open_table_summary(lobby, room_id=ROOM)
    assert summary == {'status': 'gathering', 'phase': 'lobby', 'seated': 4, 'waiting': 0, 'host_name': 'P1'}
    assert open_table_summary(table(12), room_id=ROOM)['status'] == 'full'
    assert open_table_summary(start(lobby), room_id=ROOM)['status'] == 'playing'
    assert open_table_summary({'junk': 1}, room_id=ROOM) is None


def _night(count=5):
    lobby = start(table(count))
    return lobby


def test_only_the_voting_closes_early_the_night_never_does(monkeypatch):
    monkeypatch.setattr('domain.mafia.secrets.SystemRandom.shuffle', lambda self, values: None)
    lobby = _night(5)  # p1 mafia, p2 p3 citizens (shuffle off: order mafia, citizen..., detective last)
    roles = lobby['assignments']
    assert not phase_complete(lobby) and not night_complete(lobby)
    actors = [uid for uid, role in roles.items() if role != 'citizen']
    for index, uid in enumerate(actors):
        target = next(seat for seat, p in enumerate(lobby['players'], 1)
                      if p['account_id'] != uid and roles[p['account_id']] != 'mafia')
        assert not phase_complete(lobby)
        lobby = night_action(lobby, room_id=ROOM, account_id=uid, target_seat=f'p{target}',
                             expected_revision=lobby['phase_revision'])
    # Everyone alive has acted, yet the night stays open until its deadline: a quick end would tell the table
    # that the detective or the doctor is dead (nobody left to act). The host gets no «all acted» hint either.
    assert night_complete(lobby) and not phase_complete(lobby)
    assert public_lobby(lobby, room_id=ROOM, viewer_account_id=acc(1))['can_advance'] is False
    assert not phase_complete(dict(lobby, status='day'))
    voting = dict(lobby, status='voting', votes={}, alive=[acc(1), acc(2)])
    assert not phase_complete(voting)
    voting['votes'] = {acc(1): acc(2)}
    assert not phase_complete(voting)
    voting['votes'][acc(2)] = acc(1)
    assert phase_complete(voting)


def test_discussion_access_eliminated_read_only():
    lobby = table(4)
    assert discussion_access(lobby, room_id=ROOM, account_id=acc(2)) == (True, True)
    assert discussion_access(lobby, room_id=ROOM, account_id=acc(9)) == (False, False)
    started = start(lobby)
    day = dict(started, status='day', alive=[acc(1), acc(2), acc(3)])
    assert discussion_access(day, room_id=ROOM, account_id=acc(2)) == (True, True)
    assert discussion_access(day, room_id=ROOM, account_id=acc(4)) == (True, False)
    assert discussion_access(dict(day, status='voting'), room_id=ROOM, account_id=acc(2)) == (True, False)


def test_short_code_alphabet_normalization_and_hash():
    assert len(room_limits.SHORT_CODE_ALPHABET) == len(set(room_limits.SHORT_CODE_ALPHABET)) == 30
    assert not set('01ILOU') & set(room_limits.SHORT_CODE_ALPHABET)
    code = room_limits.generate_short_code()
    assert len(code) == 8 and set(code) <= set(room_limits.SHORT_CODE_ALPHABET)
    shown = room_limits.format_short_code('K7Q4MD2X')
    assert shown == 'K7Q4-MD2X'
    for typed in ('k7q4-md2x', 'K7Q4MD2X', ' k7q4 md2x ', 'K7Q4–MD2X'):
        assert room_limits.normalize_short_code(typed) == 'K7Q4MD2X'
    assert room_limits.normalize_short_code('К7Q4-МD2X') == 'K7Q4MD2X'  # Cyrillic look-alikes
    for bad in ('K7Q4-MD2', 'K7Q4-MD2XX', 'K7Q4-MD20', 'K7Q4-MDIX', None, 12345678, 'x' * 100):
        assert room_limits.normalize_short_code(bad) is None
    assert room_limits.short_code_hash('K7Q4MD2X') != room_limits.short_code_hash('K7Q4MD2Y')
    assert 'K7Q4MD2X' not in room_limits.short_code_hash('K7Q4MD2X')


def _fixed_night(roles=('citizen', 'mafia', 'doctor', 'detective', 'citizen', 'citizen')):
    lobby = start(table(len(roles)))
    lobby['assignments'] = {acc(n): role for n, role in enumerate(roles, 1)}
    return lobby


def test_portrait_pack_has_seventeen_and_old_twelve_stay_valid():
    assert PORTRAIT_COUNT == 17
    lobby = table(12)
    assert sorted(p['portrait'] for p in lobby['players']) == list(range(1, 13))
    again = normalized_lobby(lobby, room_id=ROOM)
    assert [p['portrait'] for p in again['players']] == list(range(1, 13))
    picked = set_portrait(lobby, room_id=ROOM, account_id=acc(3), portrait=17, expected_revision=lobby['revision'])
    assert picked['players'][2]['portrait'] == 17
    assert public_lobby(picked, room_id=ROOM, viewer_account_id=acc(1))['portrait_count'] == 17


def test_leave_table_lobby_waiting_and_host():
    lobby = table(4)
    after, outcome, name = leave_table(lobby, room_id=ROOM, account_id=acc(3))
    assert outcome == 'unseated' and name == 'P3' and len(after['players']) == 3
    assert leave_table(after, room_id=ROOM, account_id=acc(3))[1] == 'none'  # idempotent
    with pytest.raises(PermissionError):
        leave_table(lobby, room_id=ROOM, account_id=acc(1))
    started = start(lobby)
    started, _ = wait_lobby(started, room_id=ROOM, account_id=acc(9), name='W')
    queued, outcome, _ = leave_table(started, room_id=ROOM, account_id=acc(9))
    assert outcome == 'waiting' and 'waiting' not in queued
    assert leave_table(None, room_id=ROOM, account_id=acc(9))[1:] == ('none', '')


def test_leave_during_game_makes_the_hero_vanish_without_revealing_the_role():
    night = _fixed_night()
    after, outcome, name = leave_table(night, room_id=ROOM, account_id=acc(5))
    assert outcome == 'vanished' and name == 'P5' and acc(5) not in after['alive']
    assert after['revision'] == night['revision'] + 1 and after['phase_revision'] == night['phase_revision']
    assert after['winner'] is None and after['status'] == 'night'
    shown = public_lobby(after, room_id=ROOM, viewer_account_id=acc(1))
    assert shown['history'][-1] == {'type': 'vanished', 'round': 1, 'seat': 'p5', 'name': 'P5'}
    assert shown['players'][4]['alive'] is False and 'role' not in shown['players'][4]
    assert leave_table(after, room_id=ROOM, account_id=acc(5))[1] == 'none'  # already out: no change
    with pytest.raises(PermissionError):
        leave_table(night, room_id=ROOM, account_id=acc(1))  # host


def test_leave_drops_pending_choices_and_can_complete_the_night():
    night = _fixed_night()
    for uid in (acc(2), acc(3)):  # mafia and doctor have acted (both choose p1)
        night = night_action(night, room_id=ROOM, account_id=uid, target_seat='p1',
                             expected_revision=night['phase_revision'])
    assert not phase_complete(night)
    closed, outcome, _ = leave_table(night, room_id=ROOM, account_id=acc(4))  # the last missing actor
    assert outcome == 'vanished' and night_complete(closed) and not phase_complete(closed)  # waits for the deadline
    reopened, _, _ = leave_table(night, room_id=ROOM, account_id=acc(3))  # an acted doctor: choice is gone
    assert not reopened['night_actions'].get('doctor') and not phase_complete(reopened)
    # a mafia victim who vanished before the resolution is not killed and nothing fails
    fresh = _fixed_night()
    victim = night_action(fresh, room_id=ROOM, account_id=acc(2), target_seat='p5',
                          expected_revision=fresh['phase_revision'])
    gone, _, _ = leave_table(victim, room_id=ROOM, account_id=acc(5))
    for uid in (acc(3), acc(4)):
        gone = night_action(gone, room_id=ROOM, account_id=uid, target_seat='p1',
                            expected_revision=gone['phase_revision'])
    assert night_complete(gone) and not phase_complete(gone)
    resolved = mafia.resolve_night(gone, room_id=ROOM, account_id=acc(1), expected_revision=gone['revision'], allow_incomplete=True)  # the deadline ends the night
    assert resolved['history'][-1]['eliminated'] is None and len(resolved['alive']) == 5


def test_leave_checks_win_conditions_and_votes():
    night = _fixed_night()
    won, outcome, _ = leave_table(night, room_id=ROOM, account_id=acc(2))  # the only mafia
    assert outcome == 'vanished' and won['status'] == 'finished' and won['winner'] == 'citizens'
    assert won['phase_deadline'] is None and won['phase_revision'] == night['phase_revision'] + 1
    assert public_lobby(won, room_id=ROOM, viewer_account_id=acc(3))['players'][1]['role'] == 'mafia'
    four = _fixed_night(('citizen', 'mafia', 'citizen', 'citizen'))
    lost, _, _ = leave_table(four, room_id=ROOM, account_id=acc(3))
    assert lost['winner'] is None
    lost, _, _ = leave_table(lost, room_id=ROOM, account_id=acc(4))
    assert lost['winner'] == 'mafia' and lost['status'] == 'finished'
    # voting: the last missing vote closes the vote; the leaver's own vote is removed
    voting = dict(night, status='voting', alive=[acc(n) for n in range(1, 7)],
                  votes={acc(n): acc(1) for n in range(1, 6)})
    assert not phase_complete(voting)
    assert phase_complete(leave_table(voting, room_id=ROOM, account_id=acc(6))[0])
    mid, _, _ = leave_table(voting, room_id=ROOM, account_id=acc(2))
    assert acc(2) not in mid['votes'] and not phase_complete(mid)
    # votes for the vanished eliminate nobody
    cast = dict(voting, votes={acc(n): acc(6) for n in range(1, 6)})
    gone, _, _ = leave_table(cast, room_id=ROOM, account_id=acc(6))
    resolved = mafia.resolve_vote(gone, room_id=ROOM, account_id=acc(1), expected_revision=gone['revision'])
    assert resolved['history'][-1]['eliminated'] is None and len(resolved['alive']) == 5


def test_mafia_teammates_show_each_others_night_choice_to_mafia_only():
    lobby = _fixed_night(('citizen', 'mafia', 'mafia', 'doctor', 'detective', 'citizen', 'citizen'))
    assert [t['target_name'] for t in own_role(lobby, room_id=ROOM, account_id=acc(2))['teammates']] == [None]
    lobby = night_action(lobby, room_id=ROOM, account_id=acc(3), target_seat='p1',
                         expected_revision=lobby['phase_revision'])
    seen = own_role(lobby, room_id=ROOM, account_id=acc(2))
    assert seen['teammates'] == [{'seat': 'p3', 'name': 'P3', 'target_name': 'P1'}]
    assert 'teammates' not in own_role(lobby, room_id=ROOM, account_id=acc(4))
    # a teammate who is no longer alive shows no pick
    gone, outcome, _ = leave_table(lobby, room_id=ROOM, account_id=acc(3))
    assert outcome == 'vanished'
    assert own_role(gone, room_id=ROOM, account_id=acc(2))['teammates'] == [{'seat': 'p3', 'name': 'P3', 'target_name': None}]
    dead_pick = dict(lobby, alive=[uid for uid in lobby['alive'] if uid != acc(3)])
    assert own_role(dead_pick, room_id=ROOM, account_id=acc(2))['teammates'][0]['target_name'] is None
    assert 'target_name' not in str(own_role(lobby, room_id=ROOM, account_id=acc(5)))
    assert 'night_acted' not in public_lobby(lobby, room_id=ROOM, viewer_account_id=acc(2))
