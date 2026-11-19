"""Closed profile snapshots, independent of real model discovery/providers."""
import hashlib
from uuid import uuid4

import pytest

from config.night_case_ai import (
    CLOUD_PRESETS, EndpointPolicy, ModelCapabilities, ProfileRegistry,
    ProfileRevision, build_profile,
)
from storage.night_ai import canonical


def registry(preset='openai', model='synthetic-model', **kwargs):
    return ProfileRegistry.cloud({(preset, model): ModelCapabilities(**kwargs)})


def profile(preset='openai', model='synthetic-model', **kwargs):
    return build_profile(registry=registry(preset, model), preset=preset, model_id=model,
                         credential_id=uuid4(), **kwargs)


def rehash(doc):
    doc['config_hash'] = hashlib.sha256(canonical({k: v for k, v in doc.items() if k != 'config_hash'})).hexdigest()
    return doc


def test_snapshot_hash_exact_and_deeply_immutable():
    chosen = profile()
    doc = chosen.document()
    assert chosen.config_hash == hashlib.sha256(canonical({k: v for k, v in doc.items() if k != 'config_hash'})).hexdigest()
    doc['generation']['max_output_tokens'] = 1
    assert chosen.document()['generation']['max_output_tokens'] == 800
    with pytest.raises(ValueError):
        ProfileRevision.decode(doc, registry())
    assert ProfileRevision.decode(chosen.document(), registry()).config_hash == chosen.config_hash


@pytest.mark.parametrize('path,value', [
    (('secret',), 'never accepted'), (('metadata',), {}),
    (('endpoint', 'header'), 'anything'), (('capabilities', 'unknown'), True),
    (('generation', 'max_output_tokens'), True), (('generation', 'max_output_tokens'), 801),
    (('generation', 'max_output_tokens'), 0), (('generation', 'temperature'), float('nan')),
    (('generation', 'temperature'), 0.5), (('model_id',), 'x' * 257),
    (('model_id',), 'line\nbreak'), (('endpoint', 'base_url'), 'https://evil.invalid/v1'),
    (('endpoint', 'policy_version'), True), (('auth_mode',), 'custom_header'),
    (('adapter',), 'unregistered'), (('preset_version',), True),
    (('credential_id',), 'not-uuid'), (('capabilities', 'json_output'), 'json_schema'),
])
def test_external_config_fields_cannot_expand_pinned_registry(path, value):
    doc = profile().document()
    target = doc
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    try:
        rehash(doc)
    except ValueError:
        pass
    with pytest.raises(ValueError, match='^night_ai_profile_invalid$'):
        ProfileRevision.decode(doc, registry())


def test_each_cloud_family_has_explicit_metadata_and_safe_byok_catalog():
    for preset in CLOUD_PRESETS:
        fields = ({'folder_id': 'folder'} if preset == 'yandex' else
                  {'workspace_id': 'workspace'} if preset == 'anthropic' else
                  {'scope': 'GIGACHAT_API_PERS'} if preset == 'gigachat' else {})
        routing = {'provider': 'chosen', 'allow_fallback': False} if preset in {'huggingface', 'openrouter'} else None
        model = 'model:chosen' if preset == 'huggingface' else 'gpt://folder/model' if preset == 'yandex' else 'synthetic-model'
        reg = registry(preset, model)
        chosen = build_profile(registry=reg, preset=preset, model_id=model,
                               credential_id=uuid4(), project_fields=fields, routing=routing, byok=True)
        assert chosen.document()['preset'] == preset
        public = next(item for item in reg.byok_catalog() if item['id'] == preset)
        assert not any(k in public for k in ('endpoint', 'credentials', 'models', 'base_url'))


@pytest.mark.parametrize('preset,fields,routing,model', [
    ('yandex', {}, None, 'model'), ('yandex', {'folder_id': 'folder'}, None, 'gpt://other/model'),
    ('anthropic', {}, None, 'model'), ('gigachat', {'scope': 'made_up'}, None, 'model'),
    ('openrouter', {}, None, 'model'),
    ('openrouter', {}, {'provider': 'chosen', 'allow_fallback': True}, 'model'),
    ('huggingface', {}, {'provider': 'auto', 'allow_fallback': False}, 'model:auto'),
    ('huggingface', {}, {'provider': 'chosen', 'allow_fallback': False}, 'model:other'),
    ('deepseek', {'folder_id': 'not-supported'}, None, 'model'),
])
def test_provider_specific_forms_are_closed(preset, fields, routing, model):
    with pytest.raises(ValueError, match='^night_ai_profile_invalid$'):
        build_profile(registry=registry(preset, model), preset=preset, model_id=model,
                      credential_id=uuid4(), project_fields=fields, routing=routing)


def test_capabilities_are_explicit_and_endpoint_policy_cannot_be_rewritten():
    reg = registry(json_output='json_schema', supports_temperature=True)
    chosen = build_profile(registry=reg, preset='openai', model_id='synthetic-model',
                           credential_id=uuid4(), json_output='json_schema', temperature=0.2)
    assert chosen.document()['generation']['temperature'] == 0.2
    with pytest.raises(ValueError):
        ProfileRevision.decode(chosen.document(), registry())
    original = reg.policies[('cloud:openai', 1)]
    with pytest.raises(TypeError):
        reg.policies[('cloud:openai', 1)] = EndpointPolicy('cloud:openai', 1, 'https://evil.invalid', 'cloud', None)
    assert original.base_url == 'https://api.openai.com/v1'


def test_local_endpoint_requires_explicit_operator_registry_and_is_never_byok():
    policy = EndpointPolicy('local:ollama', 1, 'http://127.0.0.1:11434/v1', 'trusted_local', None)
    reg = ProfileRegistry({('local:ollama', 1): policy},
                          {('ollama', 'model'): ModelCapabilities()})
    chosen = build_profile(registry=reg, preset='ollama', model_id='model',
                           credential_id=None, endpoint_policy=('local:ollama', 1))
    assert chosen.document()['auth_mode'] == 'none'
    with pytest.raises(ValueError):
        ProfileRevision.decode(chosen.document(), reg, byok=True)
    with pytest.raises(ValueError):
        EndpointPolicy('local:bad', 1, 'http://user:password@127.0.0.1/v1', 'trusted_local', None)


def test_registry_does_not_infer_unknown_model_capabilities():
    with pytest.raises(ValueError):
        build_profile(registry=ProfileRegistry.cloud({}), preset='openai', model_id='unknown', credential_id=uuid4())
