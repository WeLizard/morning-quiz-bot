"""IANA timezone allowlist contract for Night City case creation."""

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pytest

from config.night_case import NightCaseSettings


def test_registry_exposes_valid_global_iana_zones_and_keeps_legacy_zones():
    settings = NightCaseSettings(cursor_secret=b'test-night-case-cursor-secret-32-bytes')
    zones = settings.registry().allowed_timezones

    for zone in ('UTC', 'Europe/Berlin', 'Asia/Tokyo', 'America/New_York'):
        assert zone in zones
        ZoneInfo(zone)


def test_registry_does_not_admit_unknown_timezone_names():
    settings = NightCaseSettings(cursor_secret=b'test-night-case-cursor-secret-32-bytes')
    zones = settings.registry().allowed_timezones

    with pytest.raises(ZoneInfoNotFoundError):
        ZoneInfo('Not/A_Real_Timezone')
    assert 'Not/A_Real_Timezone' not in zones
