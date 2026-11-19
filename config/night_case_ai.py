"""Immutable Night AI profile codecs and explicit server-side preset metadata.

These policies describe allowed configuration; they do not perform DNS checks,
provider discovery, or network requests. A transport must separately enforce live
egress policy, resolved addresses, TLS and redirect/proxy restrictions.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping
from urllib.parse import urlsplit
from uuid import UUID

from storage.night_ai import canonical


@dataclass(frozen=True)
class Preset:
    base_url: str | None
    adapters: tuple[str, ...]
    auth_modes: tuple[str, ...] = ('bearer',)
    optional_fields: tuple[str, ...] = ()
    required_fields: tuple[str, ...] = ()
    api_version: str | None = None


_PRESETS = {
    'openai': Preset('https://api.openai.com/v1', ('openai_responses', 'openai_chat'), optional_fields=('organization_id', 'project_id')),
    'anthropic': Preset('https://api.anthropic.com', ('anthropic_messages',), ('bearer', 'anthropic_api_key'), required_fields=('workspace_id',), api_version='2026-10-21'),
    'gemini': Preset('https://generativelanguage.googleapis.com/v1beta/openai', ('openai_chat',)),
    'openrouter': Preset('https://openrouter.ai/api/v1', ('openai_chat',)),
    'deepseek': Preset('https://api.deepseek.com', ('openai_chat',)),
    'xai': Preset('https://api.x.ai/v1', ('openai_responses',)),
    'mistral': Preset('https://api.mistral.ai/v1', ('openai_chat',)),
    'groq': Preset('https://api.groq.com/openai/v1', ('openai_chat',)),
    'together': Preset('https://api.together.ai/v1', ('openai_chat',)),
    'fireworks': Preset('https://api.fireworks.ai/inference/v1', ('openai_chat',)),
    'huggingface': Preset('https://router.huggingface.co/v1', ('openai_chat',)),
    'yandex': Preset('https://ai.api.cloud.yandex.net/v1', ('openai_chat',), required_fields=('folder_id',)),
    'gigachat': Preset('https://api.giga.chat/v1', ('gigachat_chat',), ('gigachat_oauth_basic',), required_fields=('scope',)),
    **{name: Preset(None, ('openai_chat',), ('none', 'bearer')) for name in
       ('ollama', 'lmstudio', 'vllm', 'llama_cpp', 'generic_openai')},
}
PRESETS = MappingProxyType(_PRESETS)
CLOUD_PRESETS = tuple(k for k, v in PRESETS.items() if v.base_url is not None)
_FIELDS = frozenset({'preset', 'preset_version', 'adapter', 'model_id', 'endpoint', 'auth_mode',
                     'project_fields', 'api_version', 'capabilities', 'generation', 'routing',
                     'credential_id', 'config_hash'})
_LABEL = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}\Z')
_ROUTE = re.compile(r'[A-Za-z0-9][A-Za-z0-9_./-]{0,127}\Z')
_OPENROUTER_DYNAMIC_IDS = frozenset({
    'openrouter/auto', 'openrouter/free', 'openrouter/auto-code', 'openrouter/auto-beta',
})


def _invalid():
    raise ValueError('night_ai_profile_invalid')


def _closed(value, fields):
    if type(value) is not dict or set(value) != set(fields):
        _invalid()


def _plain(value, limit=256):
    if (type(value) is not str or not value or value != value.strip()
            or any(ord(c) < 32 or ord(c) == 127 for c in value)
            or len(value.encode('utf8')) > limit):
        _invalid()
    return value


@dataclass(frozen=True)
class EndpointPolicy:
    policy_id: str
    policy_version: int
    base_url: str
    network_class: str
    ca_ref: str | None

    def __post_init__(self):
        try:
            if (type(self.policy_id) is not str or not _LABEL.fullmatch(self.policy_id)
                    or type(self.policy_version) is not int or not 1 <= self.policy_version <= 2147483647
                    or self.network_class not in {'cloud', 'trusted_local'}):
                _invalid()
            _plain(self.base_url, 2048)
            url = urlsplit(self.base_url)
            if (url.scheme not in {'https', 'http'} or not url.hostname or url.username is not None
                    or url.password is not None or url.query or url.fragment or self.base_url.endswith('/')
                    or any(c in self.base_url for c in ('\\', '%', '?', '#'))
                    or self.base_url != url.scheme + '://' + url.netloc.lower() + url.path
                    or any(part in {'.', '..'} for part in url.path.split('/'))
                    or url.port == 0
                    or (self.network_class == 'cloud' and url.scheme != 'https')):
                _invalid()
            if self.ca_ref is not None and (type(self.ca_ref) is not str or not _LABEL.fullmatch(self.ca_ref)):
                _invalid()
        except (ValueError, TypeError, AttributeError, UnicodeError):
            _invalid()

    def document(self):
        return {k: getattr(self, k) for k in ('policy_id', 'policy_version', 'base_url', 'network_class', 'ca_ref')}


@dataclass(frozen=True)
class ModelCapabilities:
    """Trusted discovery/manual selection result; absence never implies support."""
    json_output: str = 'prompt'
    supports_temperature: bool = False
    output_limit_field: str | None = None

    def __post_init__(self):
        if (self.json_output not in {'prompt', 'json_object', 'json_schema'}
                or type(self.supports_temperature) is not bool
                or self.output_limit_field not in {None, 'max_tokens', 'max_completion_tokens', 'max_output_tokens'}):
            _invalid()


@dataclass(frozen=True)
class ProfileRegistry:
    policies: Mapping[tuple[str, int], EndpointPolicy]
    models: Mapping[tuple[str, str], ModelCapabilities]
    manual_presets: frozenset[str] = frozenset()
    policy_presets: Mapping[tuple[str, int], frozenset[str]] | None = None

    def __post_init__(self):
        if (type(self.manual_presets) is not frozenset
                or any(type(name) is not str or name not in PRESETS for name in self.manual_presets)):
            _invalid()
        for key, policy in self.policies.items():
            if type(policy) is not EndpointPolicy or key != (policy.policy_id, policy.policy_version):
                _invalid()
            if policy.network_class == 'cloud' and not any(policy.base_url == p.base_url for p in PRESETS.values()):
                _invalid()
        for key, capabilities in self.models.items():
            if type(key) is not tuple or len(key) != 2 or key[0] not in PRESETS or type(capabilities) is not ModelCapabilities:
                _invalid()
            _plain(key[1])
        if self.policy_presets is not None:
            if (not isinstance(self.policy_presets, Mapping)
                    or set(self.policy_presets) != set(self.policies)):
                _invalid()
            for names in self.policy_presets.values():
                if (type(names) is not frozenset or not names
                        or any(type(name) is not str or name not in PRESETS for name in names)):
                    _invalid()
            object.__setattr__(self, 'policy_presets', MappingProxyType(dict(self.policy_presets)))
        object.__setattr__(self, 'policies', MappingProxyType(dict(self.policies)))
        object.__setattr__(self, 'models', MappingProxyType(dict(self.models)))

    def policy_allows(self, policy_key: tuple[str, int], preset: str) -> bool:
        return self.policy_presets is None or preset in self.policy_presets[policy_key]

    def model_contract(self, preset: str, model_id: str) -> ModelCapabilities | None:
        """Explicit operator capabilities win; manual admission grants only prompt text."""
        if preset not in PRESETS:
            return None
        _plain(model_id)
        if preset == 'openrouter' and model_id in _OPENROUTER_DYNAMIC_IDS:
            return None
        explicit = self.models.get((preset, model_id))
        if explicit is not None:
            return explicit
        return ModelCapabilities() if preset in self.manual_presets else None

    @classmethod
    def cloud(cls, models, *, manual_presets=frozenset()):
        policies = {}
        for name in CLOUD_PRESETS:
            policy = EndpointPolicy('cloud:' + name, 1, PRESETS[name].base_url, 'cloud', None)
            policies[(policy.policy_id, 1)] = policy
        return cls(policies, models, manual_presets)

    def byok_catalog(self):
        return [{'id': name, 'preset_version': 1,
                 'required_fields': list(PRESETS[name].required_fields),
                 'optional_fields': list(PRESETS[name].optional_fields),
                 'routing_required': name in {'openrouter', 'huggingface'}} for name in CLOUD_PRESETS]


@dataclass(frozen=True)
class ProfileRevision:
    _encoded: bytes

    @property
    def config_hash(self):
        return self.document()['config_hash']

    def document(self):
        return json.loads(self._encoded)

    @classmethod
    def decode(cls, document, registry: ProfileRegistry, *, byok=False):
        try:
            encoded = canonical(document)
            _closed(document, _FIELDS)
            preset = PRESETS.get(document['preset'])
            if preset is None or type(document['preset_version']) is not int or document['preset_version'] != 1:
                _invalid()
            name = document['preset']
            if byok and name not in CLOUD_PRESETS:
                _invalid()
            model = _plain(document['model_id'])
            capabilities = registry.model_contract(name, model)
            if capabilities is None or document['adapter'] not in preset.adapters or document['auth_mode'] not in preset.auth_modes:
                _invalid()
            endpoint = document['endpoint']
            _closed(endpoint, {'policy_id', 'policy_version', 'base_url', 'network_class', 'ca_ref'})
            if type(endpoint['policy_version']) is not int:
                _invalid()
            policy = registry.policies.get((endpoint['policy_id'], endpoint['policy_version']))
            if (policy is None or endpoint != policy.document()
                    or not registry.policy_allows((endpoint['policy_id'], endpoint['policy_version']), name)):
                _invalid()
            if preset.base_url is not None and (policy.base_url != preset.base_url or policy.network_class != 'cloud'):
                _invalid()
            if preset.base_url is None and policy.network_class != 'trusted_local':
                _invalid()
            if document['api_version'] != preset.api_version:
                _invalid()
            fields = document['project_fields']
            if (type(fields) is not dict or not set(preset.required_fields) <= set(fields)
                    or set(fields) - set(preset.required_fields + preset.optional_fields)):
                _invalid()
            for value in fields.values():
                _plain(value)
            if name == 'gigachat' and fields['scope'] not in {'GIGACHAT_API_PERS', 'GIGACHAT_API_B2B', 'GIGACHAT_API_CORP'}:
                _invalid()
            if name == 'yandex' and not model.startswith('gpt://' + fields['folder_id'] + '/'):
                _invalid()
            routing = document['routing']
            if name in {'openrouter', 'huggingface'}:
                _closed(routing, {'provider', 'allow_fallback'})
                if (type(routing['provider']) is not str or not _ROUTE.fullmatch(routing['provider'])
                        or routing['provider'].lower() == 'auto' or routing['allow_fallback'] is not False):
                    _invalid()
                if name == 'huggingface' and (':' not in model or model.rsplit(':', 1)[1] != routing['provider']):
                    _invalid()
            elif routing is not None:
                _invalid()
            caps = document['capabilities']
            _closed(caps, {'json_output', 'output_limit_field'})
            allowed_json = {'prompt', capabilities.json_output}
            limit_field = capabilities.output_limit_field or ('max_output_tokens' if document['adapter'] == 'openai_responses' else 'max_tokens')
            if caps['json_output'] not in allowed_json or caps['output_limit_field'] != limit_field:
                _invalid()
            generation = document['generation']
            _closed(generation, {'temperature', 'max_output_tokens'})
            tokens, temperature = generation['max_output_tokens'], generation['temperature']
            if type(tokens) is not int or not 1 <= tokens <= 800:
                _invalid()
            if temperature is not None and (not capabilities.supports_temperature or type(temperature) not in (int, float)
                                             or not math.isfinite(temperature) or not 0 <= temperature <= 1):
                _invalid()
            if name == 'anthropic' and temperature is not None:
                _invalid()
            credential = document['credential_id']
            if credential is not None and (type(credential) is not str or str(UUID(credential)) != credential):
                _invalid()
            if (document['auth_mode'] == 'none') != (credential is None):
                _invalid()
            expected = hashlib.sha256(canonical({k: v for k, v in document.items() if k != 'config_hash'})).hexdigest()
            if document['config_hash'] != expected:
                _invalid()
            return cls(encoded)
        except (ValueError, TypeError, KeyError, AttributeError, UnicodeError, OverflowError):
            _invalid()


def build_profile(*, registry: ProfileRegistry, preset: str, model_id: str, credential_id: UUID | None,
                  endpoint_policy: tuple[str, int] | None = None, adapter: str | None = None,
                  auth_mode: str | None = None, project_fields=None, routing=None,
                  temperature=None, max_output_tokens=800, json_output='prompt', byok=False) -> ProfileRevision:
    """Server-side builder; never accepts headers, URLs, metadata or arbitrary knobs."""
    try:
        metadata = PRESETS[preset]
        selected_adapter = adapter or metadata.adapters[0]
        selected_auth = auth_mode or ('none' if credential_id is None and metadata.base_url is None else metadata.auth_modes[0])
        if credential_id is not None and type(credential_id) is not UUID:
            _invalid()
        policy = registry.policies[endpoint_policy or ('cloud:' + preset, 1)]
        if not registry.policy_allows((policy.policy_id, policy.policy_version), preset):
            _invalid()
        caps = registry.model_contract(preset, model_id)
        if caps is None:
            _invalid()
        doc = {'preset': preset, 'preset_version': 1, 'adapter': selected_adapter, 'model_id': model_id,
               'endpoint': policy.document(), 'auth_mode': selected_auth, 'project_fields': project_fields if project_fields is not None else {},
               'api_version': metadata.api_version, 'capabilities': {'json_output': json_output,
                   'output_limit_field': caps.output_limit_field or ('max_output_tokens' if selected_adapter == 'openai_responses' else 'max_tokens')},
               'generation': {'temperature': temperature, 'max_output_tokens': max_output_tokens},
               'routing': routing, 'credential_id': str(credential_id) if credential_id else None}
        doc['config_hash'] = hashlib.sha256(canonical(doc)).hexdigest()
        return ProfileRevision.decode(doc, registry, byok=byok)
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError):
        _invalid()
