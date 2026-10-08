from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from scripts.audit_notification_outbox import summarize, validate_test_database_url


NOW = datetime(2026, 10, 8, 12, tzinfo=timezone.utc)


def row(status, *, id='n1', claimed_at=None, available_at=None, delivered_at=None,
        last_error=None, attempts=1):
    return SimpleNamespace(id=id, status=status, kind='game_notice', game_id='g1',
                           chat_id=10, user_id=None, claimed_at=claimed_at,
                           available_at=available_at, delivered_at=delivered_at,
                           last_error=last_error, attempts=attempts)


def test_summary_exposes_old_pending_stale_sending_and_uncertain_without_payloads():
    report = summarize([
        row('pending', available_at=NOW - timedelta(minutes=9)),
        row('sending', id='n2', claimed_at=NOW - timedelta(minutes=8), last_error='TimeoutError'),
        row('uncertain', id='n3', claimed_at=NOW - timedelta(minutes=3), last_error='NetworkError'),
        row('delivered', delivered_at=NOW - timedelta(hours=1)),
    ], now=NOW)
    assert report['counts'] == {'pending': 1, 'sending': 1, 'uncertain': 1, 'delivered': 1}
    assert report['stale_sending'] == 1
    assert report['oldest_at']['pending'] == (NOW - timedelta(minutes=9)).isoformat()
    assert report['oldest_at']['uncertain'] == (NOW - timedelta(minutes=3)).isoformat()
    assert report['uncertain_items'][0]['id'] == 'n3'
    assert 'payload' not in report['uncertain_items'][0]


def test_fresh_sending_is_not_marked_stale():
    report = summarize([row('sending', claimed_at=NOW - timedelta(minutes=4))], now=NOW)
    assert report['stale_sending'] == 0


def test_sending_without_claim_timestamp_and_unknown_status_are_visible():
    report = summarize([row('sending'), row('legacy_error')], now=NOW)
    assert report['stale_sending'] == 1
    assert report['other_statuses'] == {'legacy_error': 1}


@pytest.mark.parametrize('url', [
    'postgresql://mqb_dev:secret@db.example.com:5432/production',
    'postgresql://mqb_dev:secret@127.0.0.1:55432/morning_quiz_test',
    'postgresql://other:secret@127.0.0.1:55433/morning_quiz_test',
])
def test_database_target_is_restricted_to_local_disposable_test_database(url):
    with pytest.raises(SystemExit, match='disposable local'):
        validate_test_database_url(url)


def test_database_target_accepts_expected_local_test_database(monkeypatch):
    monkeypatch.delenv('MQB_DEV_CONTAINER', raising=False)
    assert validate_test_database_url(
        'postgresql://mqb_dev:secret@127.0.0.1:55433/morning_quiz_test'
    )
