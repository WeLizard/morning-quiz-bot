"""Pure-negative tests for the Night Case database URL guard; no database is opened."""
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.night_case_test_database import night_case_test_url


class NightCaseTestDatabaseGuardTests(unittest.TestCase):
    LOCAL = 'postgresql+asyncpg://mqb_dev:local-development-only@127.0.0.1:55434/morning_quiz_test'

    def test_empty_or_missing_explicit_url_skips(self):
        for env in ({}, {'NIGHT_CASE_TEST_DATABASE_URL': ''},
                    {'NIGHT_CASE_TEST_DATABASE_URL': '', 'TEST_DATABASE_URL': self.LOCAL}):
            with self.subTest(env=env), self.assertRaises(unittest.SkipTest):
                night_case_test_url(env)

    def test_owned_local_and_exact_matching_test_url_are_allowed(self):
        self.assertEqual(night_case_test_url({'NIGHT_CASE_TEST_DATABASE_URL': self.LOCAL}), self.LOCAL)
        self.assertEqual(night_case_test_url({
            'NIGHT_CASE_TEST_DATABASE_URL': self.LOCAL, 'TEST_DATABASE_URL': self.LOCAL,
        }), self.LOCAL)

    def test_flagged_ci_service_is_allowed_only_on_its_exact_endpoint(self):
        ci = self.LOCAL.replace('127.0.0.1:55434', '127.0.0.1:55433')
        self.assertEqual(night_case_test_url({
            'NIGHT_CASE_TEST_DATABASE_URL': ci, 'MQB_CI_POSTGRES_SERVICE': '1',
        }), ci)
        with self.assertRaises(RuntimeError):
            night_case_test_url({'NIGHT_CASE_TEST_DATABASE_URL': ci})
        with self.assertRaises(RuntimeError):
            night_case_test_url({'NIGHT_CASE_TEST_DATABASE_URL': ci, 'MQB_CI_POSTGRES_SERVICE': 'true'})

    def test_dev_postgres_service_requires_flag_and_real_container_marker(self):
        container = self.LOCAL.replace('127.0.0.1:55434', 'postgres:5432')
        env = {'NIGHT_CASE_TEST_DATABASE_URL': container, 'MQB_DEV_CONTAINER': '1'}
        with patch.object(Path, 'is_file', return_value=False):
            with self.assertRaises(RuntimeError):
                night_case_test_url(env)
        with patch.object(Path, 'is_file', return_value=True):
            self.assertEqual(night_case_test_url(env), container)
        with patch.object(Path, 'is_file', return_value=True):
            with self.assertRaises(RuntimeError):
                night_case_test_url({'NIGHT_CASE_TEST_DATABASE_URL': container})

    def test_generic_database_url_must_match_explicit_night_url(self):
        other = self.LOCAL.replace('55434', '55433')
        with self.assertRaises(RuntimeError):
            night_case_test_url({'NIGHT_CASE_TEST_DATABASE_URL': self.LOCAL, 'TEST_DATABASE_URL': other})

    def test_wrong_host_port_user_database_and_url_options_are_rejected(self):
        bad_urls = (
            self.LOCAL.replace('127.0.0.1', '192.168.0.33'),
            self.LOCAL.replace('55434', '5432'),
            self.LOCAL.replace('mqb_dev:', 'owner:'),
            self.LOCAL.replace('/morning_quiz_test', '/morning_quiz_dev'),
            self.LOCAL + '?sslmode=require',
            self.LOCAL + '#fragment',
        )
        for url in bad_urls:
            with self.subTest(url=url), self.assertRaises(RuntimeError):
                night_case_test_url({'NIGHT_CASE_TEST_DATABASE_URL': url})


if __name__ == '__main__':
    unittest.main()
