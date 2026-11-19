"""Control codecs and transaction ordering, without any provider calls."""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from storage.night_ai import KeyRing, ReceiptFingerprinter, SecretVault

from application.night_case_ai import (
    AdminPrincipal, BindingCaps, ControlPointer, NightAIControlError,
    NightAIControlService, byok_audience_allowed,
)


def test_typed_admin_subject_is_stable_and_not_an_account_fallback():
    assert AdminPrincipal('test', uuid4()).subject == AdminPrincipal('test').subject == 'admin:test:operator'
    for invalid in ('', 'test:other', 'account:' + str(uuid4())):
        with pytest.raises(ValueError):
            AdminPrincipal(invalid)


def test_caps_are_closed_and_only_reduce_platform_limits():
    doc = BindingCaps().document()
    assert BindingCaps.decode({**doc, 'requests_per_day': 1}).requests_per_day == 1
    for changes in ({'requests_per_day': 61}, {'total_requests': 421}, {'total_reserved_tokens': 840001},
                    {'max_output_tokens': True}, {'arbitrary': {}}, {'schema': 'future'}):
        with pytest.raises(NightAIControlError):
            BindingCaps.decode({**doc, **changes})


@pytest.mark.parametrize('kind,scope', [('night_ai_approval_requested', 'admin:night_ai'),
                                      ('night_ai_cleanup', 'system:night_ai_cleanup')])
def test_control_pointer_is_closed_and_checks_actual_row_identity(kind, scope):
    pointer = ControlPointer(uuid4().hex, scope, uuid4(), kind)
    assert ControlPointer.decode(pointer.document(), row_kind=kind, row_game_id=pointer.game_id) == pointer
    for changes in ({'kind': 'mafia.phase'}, {'scope': 'public'}, {'game_id': 'other'}, {'extra': 'secret'}):
        with pytest.raises(NightAIControlError):
            ControlPointer.decode({**pointer.document(), **changes}, row_kind=kind, row_game_id=pointer.game_id)


def test_byok_allows_public_or_exact_owner_without_other_private_context():
    owner, other = uuid4(), uuid4()
    assert byok_audience_allowed(owner, 'public', frozenset())
    assert byok_audience_allowed(owner, 'account:' + str(owner), frozenset({owner}))
    assert not byok_audience_allowed(owner, 'account:' + str(other), frozenset({other}))
    assert not byok_audience_allowed(owner, 'account:' + str(owner), frozenset({owner, other}))
    assert not byok_audience_allowed(owner, 'public', frozenset({owner}))


def test_shared_fence_precedes_even_invalid_admin_principal(monkeypatch):
    events = []
    async def fence(session):
        events.append('fence')
    monkeypatch.setattr('application.night_case_ai.operation_fence', fence)
    @asynccontextmanager
    async def nested():
        events.append('nested')
        yield
    service = NightAIControlService(SimpleNamespace(begin_nested=nested), lambda: datetime.now(timezone.utc),
                                   None, None, None, environment_id='test')
    with pytest.raises(NightAIControlError, match='operator_required'):
        asyncio.run(service.set_default_profile(operator='fake', profile_id=uuid4(), client_request_id='request-1'))
    assert events == ['fence', 'nested']


@pytest.mark.parametrize('key_bearing', [False, True])
def test_own_replay_precedes_game_clock_and_lost_master_key(monkeypatch, key_bearing):
    import base64
    account, game = uuid4(), uuid4().hex
    principal = 'account:' + str(account)
    settings, secret = {'preset': 'openai', 'model_id': 'synthetic'}, b'synthetic-only'
    kind = 'stage_or_activate_byok' if key_bearing else 'request_admin'
    payload = {'expected_epoch': 0}
    if key_bearing:
        payload.update(settings=settings, secret=base64.b64encode(secret).decode())
    receipts = ReceiptFingerprinter(KeyRing('stable', {'stable': b'h' * 32}))
    fingerprint = receipts.create({'operation': kind, 'target': game, 'payload': payload}, key_bearing=key_bearing)
    stored = SimpleNamespace(operation=kind, target_id=game, fingerprint=fingerprint.digest,
                             fingerprint_version=fingerprint.version, safe_result={'epoch': 1})
    @asynccontextmanager
    async def nested():
        yield
    async def fence(session):
        pass
    async def scope(*args):
        return (principal,)
    async def operation(*args):
        return [stored]
    async def forbidden(*args):
        raise AssertionError('replay reached a state/availability fence')
    def clock():
        raise AssertionError('replay read current time')
    monkeypatch.setattr('application.night_case_ai.operation_fence', fence)
    service = NightAIControlService(SimpleNamespace(begin_nested=nested), clock, None, SecretVault(None), receipts, environment_id='test')
    service._account_scope, service._locked = scope, forbidden
    service.repo.operation, service.repo.config_lock = operation, forbidden
    async def run():
        if key_bearing:
            return await service.stage_or_activate_byok(account_id=account, game_id=game, expected_epoch=0,
                settings=settings, secret=secret, client_request_id='request-1')
        return await service.request_admin(account_id=account, game_id=game, expected_epoch=0, client_request_id='request-1')
    assert asyncio.run(run()) == {'replayed': True, 'result': {'epoch': 1}}
