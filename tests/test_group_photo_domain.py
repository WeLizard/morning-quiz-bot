from domain.photo import prepare_photo, record_attempt, project_photo, complete_group_round, stop_photo
import pytest


def state():
    return prepare_photo(room_id='r', creator_account_id='a', questions=[{'display_answer':'Кот','media':{'media_key':'cat'}}], answer_policy='group_private_deadline', now=100)


def test_private_responses_and_independent_points():
    s = state()
    rid = s['current_round_id']
    s, _ = record_attempt(s, round_id=rid, answer='нет', account_id='a', now=101)
    s, verdict = record_attempt(s, round_id=rid, answer='кот', account_id='b', now=102)
    assert verdict == 'correct'
    assert s['current_round_id'] == rid and s['total_score'] == 0
    a, b = project_photo(s, viewer_account_id='a', now=103), project_photo(s, viewer_account_id='b', now=103)
    assert a['question']['attempts'] == 1 and not a['question']['answered']
    assert b['question']['attempts'] == 0 and b['question']['answered']
    assert a['last_result'] is None and a['score'] == '0.0'
    assert s['rounds'][0]['responses']['b']['points'] == 6
    again, _ = record_attempt(s, round_id=rid, answer='кот', account_id='b', now=104)
    assert again == s


def test_half_open_deadline_and_deferred_stop():
    s = state()
    rid = s['current_round_id']
    with pytest.raises(RuntimeError):
        record_attempt(s, round_id=rid, answer='кот', account_id='a', now=160)
    s = stop_photo(s, expected_revision=s['revision'], now=110)
    assert s['status'] == 'active' and s['last_result'] is None
    with pytest.raises(RuntimeError):
        complete_group_round(s, round_id=rid, solvers=[], now=159)
    s = complete_group_round(s, round_id=rid, solvers=[], now=160)
    assert s['status'] == 'stopped' and s['last_result']['answer'] == 'Кот'


def test_projection_own_totals_and_merged_viewer_aliases():
    s = state()
    rid = s['current_round_id']
    s, _ = record_attempt(s, round_id=rid, answer='кот', account_id='a', now=101)
    pending = project_photo(s, viewer_account_id='canonical', viewer_account_ids=['a', 'canonical'], now=102)
    assert pending['question']['answered'] is True
    assert pending['own_score'] == '0.0' and pending['own_correct'] == 0
    s = complete_group_round(s, round_id=rid, solvers=[
        {'account_id':'a','name':'A','points':6.0}, {'account_id':'b','name':'B','points':5.5}], now=160)
    view = project_photo(s, viewer_account_id='canonical', viewer_account_ids=['a', 'canonical'], now=160)
    assert view['score'] == view['own_score'] == '6.0'
    assert view['correct'] == view['own_correct'] == 1
    assert view['last_result']['own_points'] == 6.0 and view['last_result']['own_correct']
    other = project_photo(s, viewer_account_id='outsider', now=160)
    assert other['score'] == '0.0' and other['correct'] == 0
    assert other['last_result']['own_points'] == 0 and not other['last_result']['own_correct']
