"""Pure vault regressions: synthetic keys only, no environment or provider I/O."""
import base64
import json
from dataclasses import replace
from uuid import uuid4

import pytest

from storage.night_ai import (
    CredentialContext, KeyRing, ReceiptFingerprinter, SecretVault, VaultUnavailable,
)


def ring(active='a', **keys):
    return KeyRing(active, keys or {'a': b'a' * 32})


def context():
    return CredentialContext('test-environment', uuid4(), 'game',
                             'account:' + str(uuid4()), uuid4().hex, 'openai')


def test_roundtrip_and_every_aad_dimension_is_authenticated():
    vault = SecretVault(ring())
    ctx = context()
    encrypted = vault.encrypt(b' do not strip ', ctx)
    assert vault.decrypt(encrypted, ctx) == b' do not strip '
    assert len(encrypted.nonce) == 12
    assert len(encrypted.ciphertext) == len(b' do not strip ') + 16
    for changed in (
        replace(ctx, environment_id='other'), replace(ctx, credential_id=uuid4()),
        replace(ctx, owner_subject='account:' + str(uuid4())),
        replace(ctx, game_id=uuid4().hex), replace(ctx, preset='anthropic'),
        replace(ctx, scope='admin', game_id=None, owner_subject='admin:test:operator'),
    ):
        with pytest.raises(VaultUnavailable, match='night_ai_secret_unavailable'):
            vault.decrypt(encrypted, changed)


def test_nonce_changes_on_every_encrypt_and_rotation_retains_identity():
    ctx = context()
    old = SecretVault(ring())
    first = old.encrypt(b'synthetic', ctx)
    second = old.encrypt(b'synthetic', ctx)
    assert first.nonce != second.nonce
    rotated = SecretVault(ring('b', a=b'a' * 32, b=b'b' * 32))
    repacked = rotated.rewrap(first, ctx)
    assert repacked.key_id == 'b'
    assert repacked.nonce != first.nonce
    assert rotated.decrypt(repacked, ctx) == b'synthetic'
    assert rotated.decrypt(first, ctx) == b'synthetic'
    with pytest.raises(VaultUnavailable):
        SecretVault(ring('b', b=b'b' * 32)).decrypt(first, ctx)


@pytest.mark.parametrize('secret', [b'', b'x' * 8193, b'x\r', b'\nx', b'x\x00', 'not bytes'])
def test_invalid_secrets_never_echo_input(secret):
    with pytest.raises(ValueError, match='^night_ai_secret_invalid$'):
        SecretVault(ring()).encrypt(secret, context())


def test_ciphertext_tampering_and_wrong_versions_fail_closed():
    ctx = context()
    vault = SecretVault(ring())
    sealed = vault.encrypt(b'synthetic', ctx)
    for changed in (replace(sealed, ciphertext=sealed.ciphertext[:-1] + bytes([sealed.ciphertext[-1] ^ 1])),
                    replace(sealed, nonce=b'bad'), replace(sealed, aad_version=2)):
        with pytest.raises(VaultUnavailable):
            vault.decrypt(changed, ctx)


def test_keyring_is_copied_and_repr_hides_all_key_material():
    keys = {'a': b'UNIQUE' + b'x' * 26}
    keyring = ring('a', **keys)
    keys['a'] = b'b' * 32
    assert 'UNIQUE' not in repr(keyring)
    assert 'UNIQUE' not in repr(SecretVault(keyring))
    with pytest.raises(ValueError):
        ring('unknown', a=b'a' * 32)
    with pytest.raises(ValueError):
        ring('a', a=b'short')


def test_env_parser_is_explicit_and_fails_closed_without_existing_admin_key():
    assert KeyRing.from_env({}, purpose='master') is None
    assert KeyRing.from_env({'OPENAI_API_KEY': 'ignored'}, purpose='master') is None
    encoded = base64.b64encode(b'a' * 32).decode()
    env = {'NIGHT_AI_MASTER_KEYS': json.dumps({'a': encoded}),
           'NIGHT_AI_MASTER_ACTIVE_KEY_ID': 'a'}
    assert KeyRing.from_env(env, purpose='master').active_id == 'a'
    for bad in ({**env, 'NIGHT_AI_MASTER_ACTIVE_KEY_ID': 'missing'},
                {**env, 'NIGHT_AI_MASTER_KEYS': '{"a":"secret"}'},
                {**env, 'NIGHT_AI_MASTER_KEYS': '{"a":"' + encoded + '","a":"' + encoded + '"}'}):
        with pytest.raises(ValueError, match='^night_ai_keyring_invalid$'):
            KeyRing.from_env(bad, purpose='master')


def test_receipts_survive_hmac_rotation_without_retaining_request_body():
    request = {'secret': 'SYNTHETIC-ONLY', 'model': 'chosen'}
    before = ReceiptFingerprinter(ring('v1', v1=b'a' * 32))
    fingerprint = before.create(request, key_bearing=True)
    assert fingerprint.version == 'hmac-sha256:v1'
    assert 'SYNTHETIC' not in repr(fingerprint)
    after = ReceiptFingerprinter(ring('v2', v1=b'a' * 32, v2=b'b' * 32))
    assert after.verify(request, fingerprint, key_bearing=True)
    assert not after.verify({**request, 'secret': 'different'}, fingerprint, key_bearing=True)
    assert not after.verify(request, fingerprint, key_bearing=False)
    assert not ReceiptFingerprinter(ring('v2', v2=b'b' * 32)).verify(request, fingerprint, key_bearing=True)
    plain = after.create({'operation': 'deny'}, key_bearing=False)
    assert plain.version == 'sha256:1'
    assert after.verify({'operation': 'deny'}, plain, key_bearing=False)


def test_secret_and_receipt_keys_are_independent():
    env = {'NIGHT_AI_MASTER_KEYS': json.dumps({'a': base64.b64encode(b'a' * 32).decode()}),
           'NIGHT_AI_MASTER_ACTIVE_KEY_ID': 'a'}
    assert KeyRing.from_env(env, purpose='receipt') is None
    with pytest.raises(VaultUnavailable):
        ReceiptFingerprinter(None).create({'secret': 'synthetic'}, key_bearing=True)
