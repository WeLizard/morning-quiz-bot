"""Strict opt-in database URL guard for Night Case PostgreSQL tests only."""
import os
from pathlib import Path
import unittest
from urllib.parse import urlsplit


def night_case_test_url(env=None):
    env = os.environ if env is None else env
    url = env.get('NIGHT_CASE_TEST_DATABASE_URL', '')
    if not url:
        raise unittest.SkipTest('NIGHT_CASE_TEST_DATABASE_URL is required for Night Case PostgreSQL tests')
    if 'TEST_DATABASE_URL' in env and env['TEST_DATABASE_URL'] != url:
        raise RuntimeError('TEST_DATABASE_URL must exactly match NIGHT_CASE_TEST_DATABASE_URL')

    try:
        parsed = urlsplit(url)
        endpoint = (parsed.hostname, parsed.port)
    except ValueError as exc:
        raise RuntimeError('invalid NIGHT_CASE_TEST_DATABASE_URL') from exc
    if (parsed.scheme != 'postgresql+asyncpg' or parsed.username != 'mqb_dev'
            or parsed.path != '/morning_quiz_test' or parsed.query or parsed.fragment):
        raise RuntimeError('Night Case tests require mqb_dev and the exact morning_quiz_test database')

    local = endpoint in {('localhost', 55434), ('127.0.0.1', 55434)}
    ci_service = (endpoint == ('127.0.0.1', 55433)
                  and env.get('MQB_CI_POSTGRES_SERVICE') == '1')
    dev_container = (endpoint == ('postgres', 5432)
                     and env.get('MQB_DEV_CONTAINER') == '1'
                     and Path('/.dockerenv').is_file())
    if not (local or ci_service or dev_container):
        raise RuntimeError('Night Case tests may use only owned PG55434, flagged CI PG55433, or the test container')
    return url
