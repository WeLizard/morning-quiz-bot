"""Night AI secret primitives. No provider calls, environment reads, or DB commits.

Callers persist SealedSecret only in night_ai_credentials, never a receipt or log.
The database additionally enforces nonce uniqueness across all credentials. Missing
retained keys and authentication failures have the same sanitized failure code.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z')
_PRESET = re.compile(r'[a-z][a-z0-9_]{0,31}\Z')


def canonical(value: Any, *, limit: int = 16384) -> bytes:
    """Closed JSON value types, finite numbers, deterministic UTF8 byte bounds."""
    def check(item, depth=0):
        if depth > 16:
            raise ValueError('night_ai_document_invalid')
        if item is None or type(item) in (str, bool, int, float):
            return
        if type(item) is dict and all(type(k) is str for k in item):
            for child in item.values():
                check(child, depth + 1)
            return
        if type(item) is list:
            for child in item:
                check(child, depth + 1)
            return
        raise ValueError('night_ai_document_invalid')
    try:
        check(value)
        result = json.dumps(value, ensure_ascii=False, sort_keys=True,
                            separators=(',', ':'), allow_nan=False).encode('utf8')
        if len(result) > limit:
            raise ValueError
        return result
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ValueError('night_ai_document_invalid') from None


def subject(value: str) -> str:
    """Validate audit namespace; this is not authentication or authorization."""
    if type(value) is str:
        if value.startswith('account:'):
            try:
                if str(UUID(value[8:])) == value[8:]:
                    return value
            except ValueError:
                pass
        parts = value.split(':')
        if len(parts) == 3 and parts[0] == 'admin' and parts[2] == 'operator' and _ID.fullmatch(parts[1]):
            return value
    raise ValueError('night_ai_subject_invalid')


class VaultUnavailable(RuntimeError):
    def __init__(self):
        super().__init__('night_ai_secret_unavailable')


@dataclass(frozen=True, repr=False)
class KeyRing:
    active_id: str
    _keys: Mapping[str, bytes] = field(repr=False)

    def __post_init__(self):
        if (type(self.active_id) is not str or not _ID.fullmatch(self.active_id)
                or not isinstance(self._keys, Mapping) or not 1 <= len(self._keys) <= 32
                or self.active_id not in self._keys
                or any(type(k) is not str or not _ID.fullmatch(k) or type(v) is not bytes
                       or len(v) != 32 for k, v in self._keys.items())):
            raise ValueError('night_ai_keyring_invalid')
        object.__setattr__(self, '_keys', MappingProxyType(dict(self._keys)))

    def __repr__(self):
        return 'KeyRing(<redacted>)'

    def key(self, key_id: str) -> bytes:
        try:
            return self._keys[key_id]
        except (KeyError, TypeError):
            raise VaultUnavailable() from None

    @classmethod
    def from_env(cls, env: Mapping[str, str], *, purpose: str) -> KeyRing | None:
        """Explicit env only. Receipt keys never fall back to encryption/admin keys.

        MASTER_KEYS is JSON {key_id: strict-base64-32-bytes}, MASTER_ACTIVE_KEY_ID
        names its active key. RECEIPT_HMAC_KEY is the equivalent versioned JSON
        keyring; RECEIPT_HMAC_ACTIVE_KEY_ID names the write version. Retain old
        entries for existing ciphertext/receipts. Entirely absent config is off.
        """
        if purpose not in {'master', 'receipt'}:
            raise ValueError('night_ai_keyring_invalid')
        key_name, active_name = (
            ('NIGHT_AI_MASTER_KEYS', 'NIGHT_AI_MASTER_ACTIVE_KEY_ID') if purpose == 'master'
            else ('NIGHT_AI_RECEIPT_HMAC_KEY', 'NIGHT_AI_RECEIPT_HMAC_ACTIVE_KEY_ID'))
        raw, active = env.get(key_name), env.get(active_name)
        if raw is None and active is None:
            return None
        def pairs(items):
            result = {}
            for k, v in items:
                if k in result:
                    raise ValueError
                result[k] = v
            return result
        try:
            if type(raw) is not str or len(raw) > 8192 or type(active) is not str:
                raise ValueError
            decoded = json.loads(raw, object_pairs_hook=pairs)
            if type(decoded) is not dict:
                raise ValueError
            keys = {k: base64.b64decode(v, validate=True) for k, v in decoded.items()}
            return cls(active, keys)
        except (ValueError, TypeError, UnicodeError):
            raise ValueError('night_ai_keyring_invalid') from None


@dataclass(frozen=True)
class CredentialContext:
    environment_id: str
    credential_id: UUID
    scope: str
    owner_subject: str
    game_id: str | None
    preset: str

    def __post_init__(self):
        if (type(self.environment_id) is not str or not _ID.fullmatch(self.environment_id)
                or type(self.credential_id) is not UUID or self.scope not in {'admin', 'game'}
                or type(self.preset) is not str or not _PRESET.fullmatch(self.preset)
                or (self.scope == 'game' and (type(self.game_id) is not str or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,64}', self.game_id)))
                or (self.scope == 'admin' and self.game_id is not None)):
            raise ValueError('night_ai_context_invalid')
        subject(self.owner_subject)
        if not self.owner_subject.startswith('admin:' if self.scope == 'admin' else 'account:'):
            raise ValueError('night_ai_context_invalid')

    def aad(self) -> bytes:
        return canonical(['night-ai-secret/1', self.environment_id, str(self.credential_id),
                          self.scope, self.owner_subject, self.game_id,
                          self.preset])


@dataclass(frozen=True, repr=False)
class SealedSecret:
    key_id: str
    nonce: bytes
    ciphertext: bytes
    aad_version: int = 1

    def __repr__(self):
        return 'SealedSecret(<redacted>)'


class SecretVault:
    def __init__(self, keyring: KeyRing | None):
        self._keyring = keyring

    def __repr__(self):
        return 'SecretVault(<redacted>)'

    def encrypt(self, secret: bytes, context: CredentialContext) -> SealedSecret:
        if type(secret) is not bytes or not 1 <= len(secret) <= 8192 or any(c in secret for c in (b'\r', b'\n', b'\x00')):
            raise ValueError('night_ai_secret_invalid')
        if self._keyring is None:
            raise VaultUnavailable()
        nonce = os.urandom(12)
        return SealedSecret(self._keyring.active_id, nonce,
                            AESGCM(self._keyring.key(self._keyring.active_id)).encrypt(nonce, secret, context.aad()))

    def decrypt(self, sealed: SealedSecret, context: CredentialContext) -> bytes:
        try:
            if (self._keyring is None or type(sealed) is not SealedSecret
                    or type(sealed.aad_version) is not int or sealed.aad_version != 1
                    or type(sealed.nonce) is not bytes or len(sealed.nonce) != 12
                    or type(sealed.ciphertext) is not bytes or not 17 <= len(sealed.ciphertext) <= 8208):
                raise VaultUnavailable()
            return AESGCM(self._keyring.key(sealed.key_id)).decrypt(sealed.nonce, sealed.ciphertext, context.aad())
        except (InvalidTag, ValueError, TypeError, VaultUnavailable):
            raise VaultUnavailable() from None

    def rewrap(self, sealed: SealedSecret, context: CredentialContext) -> SealedSecret:
        return self.encrypt(self.decrypt(sealed, context), context)


@dataclass(frozen=True)
class Fingerprint:
    digest: str
    version: str


class ReceiptFingerprinter:
    def __init__(self, keyring: KeyRing | None):
        self._keyring = keyring

    def create(self, validated_request: Any, *, key_bearing: bool) -> Fingerprint:
        data = canonical(validated_request)
        if key_bearing:
            if self._keyring is None:
                raise VaultUnavailable()
            version = self._keyring.active_id
            digest = hmac.new(self._keyring.key(version), b'night-ai-receipt/1\x00' + data, hashlib.sha256).hexdigest()
            return Fingerprint(digest, 'hmac-sha256:' + version)
        return Fingerprint(hashlib.sha256(data).hexdigest(), 'sha256:1')

    def verify(self, validated_request: Any, fingerprint: Fingerprint, *, key_bearing: bool) -> bool:
        if type(fingerprint) is not Fingerprint or not re.fullmatch('[a-f0-9]{64}', fingerprint.digest):
            return False
        data = canonical(validated_request)
        if not key_bearing:
            return fingerprint.version == 'sha256:1' and hmac.compare_digest(hashlib.sha256(data).hexdigest(), fingerprint.digest)
        if self._keyring is None or not fingerprint.version.startswith('hmac-sha256:'):
            return False
        try:
            key = self._keyring.key(fingerprint.version[len('hmac-sha256:'):])
        except VaultUnavailable:
            return False
        expected = hmac.new(key, b'night-ai-receipt/1\x00' + data, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, fingerprint.digest)
