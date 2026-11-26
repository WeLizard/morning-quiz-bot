"""Explicit, default-off Night Case runtime configuration."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

MANOR_HASH = '3e23930509daf49805cd8c6e9541893ab7aa95a53fd58b90545dbe717434dcf3'


def _flag(env, key):
    raw = env.get(key, 'false').strip().lower()
    if raw not in {'true', 'false', '1', '0', 'yes', 'no', 'on', 'off'}:
        raise ValueError(key + ' must be boolean')
    return raw in {'true', '1', 'yes', 'on'}


@dataclass(frozen=True)
class NightCaseSettings:
    enabled: bool = False
    starts_enabled: bool = False
    cursor_secret: bytes = b''
    allowed_hashes: frozenset[str] = frozenset({MANOR_HASH})
    readiness_url: str = 'http://127.0.0.1:8000/healthz'
    runtime_key: str = 'night-case'
    poll_seconds: float = 5.0
    heartbeat_seconds: float = 30.0
    stale_seconds: float = 120.0
    lease_seconds: float = 60.0
    batch_size: int = 20

    def __post_init__(self):
        import re
        if self.enabled and len(self.cursor_secret) < 32:
            raise ValueError('MQB_NIGHT_CASE_CURSOR_SECRET must contain at least 32 UTF8 bytes')
        if not self.allowed_hashes or any(re.fullmatch('[a-f0-9]{64}', h) is None for h in self.allowed_hashes):
            raise ValueError('MQB_NIGHT_CASE_CASE_HASHES must pin SHA256 hashes')
        if not (1 <= self.batch_size <= 100 and self.poll_seconds == 5 and self.heartbeat_seconds == 30 and self.stale_seconds == 120 and 5 <= self.lease_seconds <= 120):
            raise ValueError('invalid Night Case runtime bounds')
        from infrastructure.night_case_readiness import validate_readiness_url
        validate_readiness_url(self.readiness_url)

    @classmethod
    def from_env(cls, env=None):
        env = os.environ if env is None else env
        return cls(enabled=_flag(env, 'MQB_NIGHT_CASE_ENABLED'), starts_enabled=_flag(env, 'MQB_NIGHT_CASE_STARTS_ENABLED'),
            cursor_secret=env.get('MQB_NIGHT_CASE_CURSOR_SECRET', '').encode('utf-8'),
            allowed_hashes=frozenset(h.strip() for h in env.get('MQB_NIGHT_CASE_CASE_HASHES', MANOR_HASH).split(',') if h.strip()),
            readiness_url=env.get('MQB_NIGHT_CASE_READINESS_URL', 'http://127.0.0.1:8000/healthz'))

    def registry(self, paths=None):
        from application.night_case import NightCaseRegistry, FrozenCaseRef
        from domain.night_case_v2_format import compile_v2, load_v2
        paths = paths or [Path(__file__).resolve().parents[1] / 'content/night_city/manor_lake.case.json']
        refs = set()
        for path in paths:
            case = compile_v2(load_v2(Path(path).read_bytes()))
            if case.content_hash in self.allowed_hashes:
                refs.add(FrozenCaseRef(case.case_id, case.case_version, case.content_hash))
        if self.enabled and not refs: raise ValueError('no configured Night Case matches pinned hashes')
        from domain.account_timezone import timezones
        return NightCaseRegistry(frozenset(refs), timezones(), self.cursor_secret)
