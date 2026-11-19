"""Explicit, default-off Night AI configuration and immutable operator catalog.

Composition only: no environment reads, SQL, provider calls, discovery or generated keys.
Callers supply the same settings/manifest and retained policy pins to every process.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import ssl
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from config.night_case_ai import CLOUD_PRESETS, PRESETS, EndpointPolicy, ModelCapabilities, ProfileRegistry
from infrastructure.night_ai_gateway import GIGA_OAUTH_ORIGIN, OperatorPolicy
from storage.night_ai import KeyRing, canonical

_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z')
_HASH = re.compile(r'[a-f0-9]{64}\Z')
_POLICY_FIELDS = frozenset({'policy_id', 'policy_version', 'base_url', 'network_class',
    'allowed_cidrs', 'ca_ref', 'label', 'presets', 'inventory_route', 'local_model_allowlist'})
_ROUTES = {'none', 'openai_models', 'anthropic_models', 'gemini_models', 'gigachat_models',
    'ollama_tags', 'lmstudio_models', 'vllm_models', 'llama_cpp_models'}
_ROUTE_PRESETS = {'openai_models': 'openai', 'anthropic_models': 'anthropic',
    'gemini_models': 'gemini', 'gigachat_models': 'gigachat', 'ollama_tags': 'ollama',
    'lmstudio_models': 'lmstudio', 'vllm_models': 'vllm', 'llama_cpp_models': 'llama_cpp'}


def _invalid():
    raise ValueError('night_ai_runtime_invalid')


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            _invalid()
        result[key] = value
    return result


def _bounded(value, *, max_depth=12, max_nodes=5000):
    nodes = 0
    def walk(item, depth):
        nonlocal nodes
        nodes += 1
        if depth > max_depth or nodes > max_nodes:
            _invalid()
        if type(item) is dict:
            for key, child in item.items():
                if type(key) is not str or len(key.encode('utf-8')) > 256:
                    _invalid()
                walk(child, depth + 1)
        elif type(item) is list:
            for child in item:
                walk(child, depth + 1)
        elif type(item) is str and len(item.encode('utf-8')) > 4096:
            _invalid()
        elif type(item) not in (str, int, bool, type(None)):
            _invalid()
    walk(value, 0)


def _flag(env, name):
    raw = env.get(name, 'false')
    if type(raw) is not str or raw not in {'true', 'false', '1', '0'}:
        _invalid()
    return raw in {'true', '1'}


@dataclass(frozen=True, repr=False)
class NightAIRuntimeSettings:
    """Server-provided Night flags and keyrings; missing keys leave authored mode available."""
    enabled: bool = False
    external_allowed: bool = False
    environment_id: str | None = None
    deployment_id: str | None = None
    manifest_path: Path | None = None
    master_keys: KeyRing | None = field(default=None, repr=False)
    receipt_keys: KeyRing | None = field(default=None, repr=False)

    def __post_init__(self):
        if (type(self.enabled) is not bool or type(self.external_allowed) is not bool
                or self.external_allowed and not self.enabled):
            _invalid()
        for value in (self.environment_id, self.deployment_id):
            if value is not None and (type(value) is not str or not _ID.fullmatch(value)):
                _invalid()
        if self.manifest_path is not None and (not isinstance(self.manifest_path, Path)
                or not self.manifest_path.is_absolute()):
            _invalid()
        if self.master_keys is not None and type(self.master_keys) is not KeyRing:
            _invalid()
        if self.receipt_keys is not None and type(self.receipt_keys) is not KeyRing:
            _invalid()
        if self.enabled and not self.config_ready:
            _invalid()

    @property
    def config_ready(self):
        return all((self.environment_id, self.deployment_id, self.manifest_path))

    @classmethod
    def from_env(cls, env: Mapping[str, str]):
        """Read only the supplied mapping; never fall back to process os.environ."""
        try:
            if not isinstance(env, Mapping):
                _invalid()
            path = env.get('NIGHT_AI_MANIFEST_PATH')
            if path is not None and (type(path) is not str or not path or len(path) > 4096):
                _invalid()
            return cls(enabled=_flag(env, 'NIGHT_NARRATOR_ENABLED'),
                external_allowed=_flag(env, 'NIGHT_NARRATOR_EXTERNAL_ALLOWED'),
                environment_id=env.get('NIGHT_AI_ENVIRONMENT_ID'),
                deployment_id=env.get('NIGHT_AI_DEPLOYMENT_ID'),
                manifest_path=Path(path) if path is not None else None,
                master_keys=KeyRing.from_env(env, purpose='master'),
                receipt_keys=KeyRing.from_env(env, purpose='receipt'))
        except (ValueError, TypeError, UnicodeError):
            _invalid()

    def __repr__(self):
        return ('NightAIRuntimeSettings(enabled=%r, external_allowed=%r, config_ready=%r, '
                'keys=<redacted>)' % (self.enabled, self.external_allowed, self.config_ready))


@dataclass(frozen=True, repr=False)
class RuntimePolicyRule:
    presets: frozenset[str]
    inventory_route: str
    local_model_allowlist: frozenset[str]
    policy_hash: str


@dataclass(frozen=True, repr=False)
class RuntimeManifest:
    environment_id: str
    manifest_hash: str
    registry: ProfileRegistry
    operator_policies: Mapping[tuple[str, int], OperatorPolicy]
    policy_hashes: Mapping[tuple[str, int], str]
    policy_rules: Mapping[tuple[str, int], RuntimePolicyRule]
    _catalog: tuple[tuple[str, int, str, tuple[str, ...], str, bool], ...]

    def admin_catalog(self):
        """Fresh safe DTOs: no URL, CIDR, CA path, allowlist, secret or raw manifest."""
        return [{'policy_id': pid, 'version': version, 'label': label,
                 'presets': list(presets), 'network_class': network_class,
                 'inventory_supported': inventory}
                for pid, version, label, presets, network_class, inventory in self._catalog]


def _context(ca_ref, bundles):
    if ca_ref is None:
        return ssl.create_default_context(), None
    path = bundles.get(ca_ref)
    if path is None:
        _invalid()
    path = Path(path)
    if not path.is_absolute() or not path.is_file() or path.stat().st_size > 262144:
        _invalid()
    with path.open('rb') as stream:
        contents = stream.read(262145)
    if not contents or len(contents) > 262144:
        _invalid()
    context = ssl.create_default_context(cadata=contents.decode('ascii'))
    return context, hashlib.sha256(contents).hexdigest()


def load_manifest(raw: bytes, *, expected_environment_id: str,
                  retained_policy_hashes: Mapping[tuple[str, int], str] | None = None,
                  models: Mapping[tuple[str, str], ModelCapabilities] | None = None,
                  manual_presets: frozenset[str] = frozenset()) -> RuntimeManifest:
    """Validate one bounded operator manifest; retained pins prevent id/version reuse."""
    try:
        if type(raw) is not bytes or len(raw) > 262144 or type(expected_environment_id) is not str:
            _invalid()
        source = json.loads(raw.decode('utf-8'), object_pairs_hook=_pairs,
                            parse_constant=lambda _: _invalid())
        _bounded(source)
        if type(source) is not dict or set(source) != {'manifest_version', 'environment_id', 'policies', 'ca_bundles'}:
            _invalid()
        if (type(source['manifest_version']) is not int or source['manifest_version'] != 1
                or type(source['environment_id']) is not str
                or not _ID.fullmatch(source['environment_id'])
                or source['environment_id'] != expected_environment_id):
            _invalid()
        rows, bundles = source['policies'], source['ca_bundles']
        if type(rows) is not list or len(rows) > 128 or type(bundles) is not dict or len(bundles) > 32:
            _invalid()
        for name, path in bundles.items():
            if (type(name) is not str or not _ID.fullmatch(name) or type(path) is not str
                    or not Path(path).is_absolute() or len(path) > 4096):
                _invalid()
        retained = retained_policy_hashes or {}
        if not isinstance(retained, Mapping):
            _invalid()
        for key, digest in retained.items():
            if (type(key) is not tuple or len(key) != 2 or type(key[0]) is not str
                    or type(key[1]) is not int or type(digest) is not str or not _HASH.fullmatch(digest)):
                _invalid()
        policies, operators, hashes, rules, catalog = {}, {}, {}, {}, []
        for row in rows:
            if type(row) is not dict or set(row) != _POLICY_FIELDS:
                _invalid()
            endpoint = EndpointPolicy(*(row[k] for k in ('policy_id', 'policy_version', 'base_url', 'network_class', 'ca_ref')))
            key = endpoint.policy_id, endpoint.policy_version
            if key in operators:
                _invalid()
            cidrs = row['allowed_cidrs']
            if type(cidrs) is not list or len(cidrs) > 32 or len(set(cidrs)) != len(cidrs):
                _invalid()
            for cidr in cidrs:
                if type(cidr) is not str or ipaddress.ip_network(cidr, strict=True).prefixlen == 0:
                    _invalid()
            presets = row['presets']
            if (type(presets) is not list or len(presets) > len(PRESETS)
                    or len(set(presets)) != len(presets)
                    or any(type(name) is not str or name not in PRESETS for name in presets)):
                _invalid()
            route = row['inventory_route']
            if type(route) is not str or route not in _ROUTES:
                _invalid()
            allowlist = row['local_model_allowlist']
            if (type(allowlist) is not list or len(allowlist) > 500 or len(set(allowlist)) != len(allowlist)
                    or any(type(name) is not str or not name or name != name.strip()
                           or len(name.encode('utf-8')) > 256 for name in allowlist)):
                _invalid()
            if (type(row['label']) is not str or not row['label'] or len(row['label'].encode('utf-8')) > 80
                    or any(ord(c) < 32 for c in row['label'])):
                _invalid()
            if endpoint.network_class == 'cloud':
                if allowlist or cidrs:
                    _invalid()
                if endpoint.base_url == GIGA_OAUTH_ORIGIN:
                    if endpoint.policy_id != 'giga-oauth' or presets or route != 'none':
                        _invalid()
                elif (not presets or any(name not in CLOUD_PRESETS or PRESETS[name].base_url != endpoint.base_url
                                         for name in presets)):
                    _invalid()
            elif not presets or any(name in CLOUD_PRESETS for name in presets):
                _invalid()
            if route != 'none' and (_ROUTE_PRESETS[route] not in presets or len(presets) != 1):
                _invalid()
            if endpoint.ca_ref is not None and (not endpoint.base_url.startswith('https://')
                                                or endpoint.ca_ref not in bundles):
                _invalid()
            context, ca_hash = (_context(endpoint.ca_ref, bundles)
                                if endpoint.base_url.startswith('https://') else (None, None))
            operator = OperatorPolicy(endpoint, tuple(cidrs), context)
            digest = hashlib.sha256(canonical([row, ca_hash])).hexdigest()
            if key in retained and retained[key] != digest:
                _invalid()
            operators[key], hashes[key] = operator, digest
            rules[key] = RuntimePolicyRule(frozenset(presets), route, frozenset(allowlist), digest)
            if endpoint.base_url != GIGA_OAUTH_ORIGIN:
                policies[key] = endpoint
                catalog.append((endpoint.policy_id, endpoint.policy_version, row['label'], tuple(presets),
                                endpoint.network_class, route != 'none'))
        registry = ProfileRegistry(policies, models or {}, manual_presets,
            {key: rules[key].presets for key in policies})
        return RuntimeManifest(source['environment_id'], hashlib.sha256(canonical(source)).hexdigest(),
            registry, MappingProxyType(operators), MappingProxyType(hashes),
            MappingProxyType(rules), tuple(catalog))
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError, OverflowError,
            OSError, ssl.SSLError):
        _invalid()


def load_manifest_file(path: Path, **kwargs) -> RuntimeManifest:
    """Read one private absolute manifest with a hard byte cap; no cwd or env fallback."""
    try:
        if not isinstance(path, Path) or not path.is_absolute() or not path.is_file():
            _invalid()
        with path.open('rb') as stream:
            raw = stream.read(262145)
        return load_manifest(raw, **kwargs)
    except (OSError, ValueError, TypeError):
        _invalid()
