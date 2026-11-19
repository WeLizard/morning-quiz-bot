"""Pure runtime config: operator input never grants model capabilities or network access."""
import json
import hashlib
from pathlib import Path
from uuid import uuid4

import pytest

from config.night_case_ai import ModelCapabilities, ProfileRegistry, ProfileRevision, build_profile
from config.night_case_ai_runtime import NightAIRuntimeSettings, load_manifest, load_manifest_file
from storage.night_ai import canonical


def _manifest(**changes):
    value = {'manifest_version': 1, 'environment_id': 'test-env', 'policies': [
        {'policy_id': 'cloud:openai', 'policy_version': 1,
         'base_url': 'https://api.openai.com/v1', 'network_class': 'cloud',
         'allowed_cidrs': [], 'ca_ref': None, 'label': 'OpenAI', 'presets': ['openai'],
         'inventory_route': 'openai_models', 'local_model_allowlist': []},
        {'policy_id': 'local:ollama', 'policy_version': 1,
         'base_url': 'http://127.0.0.1:11434/v1', 'network_class': 'trusted_local',
         'allowed_cidrs': ['127.0.0.1/32'], 'ca_ref': None, 'label': 'Local',
         'presets': ['ollama'], 'inventory_route': 'ollama_tags',
         'local_model_allowlist': ['owned-local']},
        {'policy_id': 'giga-oauth', 'policy_version': 1,
         'base_url': 'https://ngw.devices.sberbank.ru:9443', 'network_class': 'cloud',
         'allowed_cidrs': [], 'ca_ref': None, 'label': 'Giga OAuth', 'presets': [],
         'inventory_route': 'none', 'local_model_allowlist': []}], 'ca_bundles': {}}
    value.update(changes)
    return value


def test_manual_is_explicit_conservative_and_uses_same_codec():
    strict = ProfileRegistry.cloud({})
    with pytest.raises(ValueError):
        build_profile(registry=strict, preset='openai', model_id='unknown', credential_id=uuid4())
    runtime = ProfileRegistry.cloud({}, manual_presets=frozenset({'openai', 'anthropic'}))
    chosen = build_profile(registry=runtime, preset='openai', model_id='unknown', credential_id=uuid4())
    assert chosen.document()['capabilities'] == {'json_output': 'prompt', 'output_limit_field': 'max_output_tokens'}
    assert chosen.document()['generation'] == {'temperature': None, 'max_output_tokens': 800}
    assert ProfileRevision.decode(chosen.document(), runtime).config_hash == chosen.config_hash
    with pytest.raises(ValueError):
        ProfileRevision.decode(chosen.document(), strict)
    with pytest.raises(ValueError):
        build_profile(registry=runtime, preset='openai', model_id='unknown', credential_id=uuid4(), temperature=0.3)
    with pytest.raises(ValueError):
        build_profile(registry=runtime, preset='openai', model_id='unknown', credential_id=uuid4(), json_output='json_schema')
    with pytest.raises(ValueError):
        build_profile(registry=runtime, preset='openai', model_id='unknown\nsecret', credential_id=uuid4())


def test_explicit_capabilities_keep_old_hash_and_anthropic_never_samples():
    strict = ProfileRegistry.cloud({('openai', 'known'): ModelCapabilities(supports_temperature=True)})
    chosen = build_profile(registry=strict, preset='openai', model_id='known', credential_id=uuid4(), temperature=0.2)
    runtime = ProfileRegistry.cloud({('openai', 'known'): ModelCapabilities(supports_temperature=True)},
                                    manual_presets=frozenset({'openai'}))
    assert ProfileRevision.decode(chosen.document(), runtime).config_hash == chosen.config_hash
    anthropic = ProfileRegistry.cloud({('anthropic', 'known'): ModelCapabilities(supports_temperature=True)})
    with pytest.raises(ValueError):
        build_profile(registry=anthropic, preset='anthropic', model_id='known', credential_id=uuid4(),
                      project_fields={'workspace_id': 'work'}, temperature=0.2)
    manual = ProfileRegistry.cloud({}, manual_presets=frozenset({'anthropic'}))
    chosen_manual = build_profile(registry=manual, preset='anthropic', model_id='other', credential_id=uuid4(),
                                  project_fields={'workspace_id': 'work'})
    assert chosen_manual.document()['capabilities']['output_limit_field'] == 'max_tokens'


def test_settings_default_off_and_no_secret_in_repr():
    off = NightAIRuntimeSettings.from_env({})
    assert not off.enabled and not off.external_allowed and off.master_keys is None
    assert not off.config_ready
    with pytest.raises(ValueError):
        NightAIRuntimeSettings.from_env({'NIGHT_NARRATOR_ENABLED': 'true'})
    with pytest.raises(ValueError):
        NightAIRuntimeSettings.from_env({'NIGHT_AI_MANIFEST_PATH': 'relative.json'})
    settings = NightAIRuntimeSettings.from_env({'NIGHT_NARRATOR_ENABLED': 'true',
        'NIGHT_AI_ENVIRONMENT_ID': 'test-env', 'NIGHT_AI_DEPLOYMENT_ID': 'test-deployment',
        'NIGHT_AI_MANIFEST_PATH': str(Path('owned-night-manifest.json').resolve())})
    assert settings.enabled and settings.config_ready and settings.master_keys is None
    assert '<redacted>' in repr(settings)


def test_manifest_filters_oauth_validates_retained_pins_and_safe_catalog():
    data = _manifest()
    runtime = load_manifest(json.dumps(data).encode(), expected_environment_id='test-env')
    assert ('giga-oauth', 1) not in runtime.registry.policies
    assert ('giga-oauth', 1) in runtime.operator_policies
    assert runtime.registry.policies[('local:ollama', 1)].network_class == 'trusted_local'
    assert runtime.policy_rules[('local:ollama', 1)].local_model_allowlist == frozenset({'owned-local'})
    assert all('base_url' not in row and 'ca_ref' not in row and 'allowed_cidrs' not in row
               for row in runtime.admin_catalog())
    pin = runtime.policy_hashes[('local:ollama', 1)]
    assert load_manifest(json.dumps(data).encode(), expected_environment_id='test-env',
                         retained_policy_hashes={('local:ollama', 1): pin}).policy_hashes[('local:ollama', 1)] == pin
    data['policies'][1]['base_url'] = 'http://127.0.0.1:11435/v1'
    with pytest.raises(ValueError):
        load_manifest(json.dumps(data).encode(), expected_environment_id='test-env',
                      retained_policy_hashes={('local:ollama', 1): pin})


@pytest.mark.parametrize('mutation', [
    lambda d: d['policies'].append(dict(d['policies'][0])),
    lambda d: d['policies'][1].update(allowed_cidrs=['0.0.0.0/0']),
    lambda d: d['policies'][0].update(base_url='https://evil.invalid/v1'),
    lambda d: d['policies'][0].update(extra='secret'),
    lambda d: d['policies'][1].update(ca_ref='missing'),
    lambda d: d.update(manifest_version=True),
])
def test_manifest_rejects_bad_metadata(mutation):
    data = _manifest(); mutation(data)
    with pytest.raises(ValueError, match='^night_ai_runtime_invalid$'):
        load_manifest(json.dumps(data).encode(), expected_environment_id='test-env')


def test_manifest_rejects_duplicate_json_keys():
    with pytest.raises(ValueError, match='^night_ai_runtime_invalid$'):
        load_manifest(b'{"manifest_version":1,"manifest_version":1}', expected_environment_id='test-env')


def test_runtime_manual_local_configuration_is_not_execution_proof():
    runtime = load_manifest(json.dumps(_manifest()).encode(), expected_environment_id='test-env',
                            manual_presets=frozenset({'ollama'}))
    profile = build_profile(registry=runtime.registry, preset='ollama', model_id='manual-local',
                            credential_id=None, endpoint_policy=('local:ollama', 1))
    assert profile.document()['auth_mode'] == 'none'
    assert profile.document()['capabilities']['json_output'] == 'prompt'
    assert 'manual-local' not in runtime.policy_rules[('local:ollama', 1)].local_model_allowlist


def test_manifest_preset_membership_is_authoritative_at_build_and_decode():
    runtime = load_manifest(json.dumps(_manifest()).encode(), expected_environment_id='test-env',
                            manual_presets=frozenset({'ollama', 'generic_openai'}))
    valid = build_profile(registry=runtime.registry, preset='ollama', model_id='owned-local',
                          credential_id=None, endpoint_policy=('local:ollama', 1))
    assert ProfileRevision.decode(valid.document(), runtime.registry).config_hash == valid.config_hash
    with pytest.raises(ValueError, match='^night_ai_profile_invalid$'):
        build_profile(registry=runtime.registry, preset='generic_openai', model_id='owned-local',
                      credential_id=None, endpoint_policy=('local:ollama', 1))
    tampered = valid.document()
    tampered['preset'] = 'generic_openai'
    tampered['config_hash'] = hashlib.sha256(canonical({k: v for k, v in tampered.items()
                                                       if k != 'config_hash'})).hexdigest()
    with pytest.raises(ValueError, match='^night_ai_profile_invalid$'):
        ProfileRevision.decode(tampered, runtime.registry)


@pytest.mark.parametrize('router_id',
    ['openrouter/auto', 'openrouter/free', 'openrouter/auto-code', 'openrouter/auto-beta'])
@pytest.mark.parametrize('explicit', [False, True])
def test_openrouter_dynamic_router_ids_are_not_fixed_models(router_id, explicit):
    models = ({('openrouter', router_id): ModelCapabilities(),
               ('openrouter', 'owned/fixed:free'): ModelCapabilities()} if explicit else {})
    runtime = ProfileRegistry.cloud(models, manual_presets=frozenset({'openrouter'}))
    with pytest.raises(ValueError, match='^night_ai_profile_invalid$'):
        build_profile(registry=runtime, preset='openrouter', model_id=router_id,
                      credential_id=uuid4(), routing={'provider': 'owned', 'allow_fallback': False})
    normal = build_profile(registry=runtime, preset='openrouter', model_id='owned/fixed:free',
                           credential_id=uuid4(), routing={'provider': 'owned', 'allow_fallback': False})
    assert normal.document()['model_id'] == 'owned/fixed:free'
    tampered = normal.document()
    tampered['model_id'] = router_id
    tampered['config_hash'] = hashlib.sha256(canonical({k: v for k, v in tampered.items()
                                                       if k != 'config_hash'})).hexdigest()
    with pytest.raises(ValueError, match='^night_ai_profile_invalid$'):
        ProfileRevision.decode(tampered, runtime)


def test_named_ca_is_not_accepted_without_bundle_or_https():
    data = _manifest()
    data['policies'][0]['ca_ref'] = 'operator'
    with pytest.raises(ValueError, match='^night_ai_runtime_invalid$'):
        load_manifest(json.dumps(data).encode(), expected_environment_id='test-env')
    data['ca_bundles'] = {'operator': 'relative-ca.pem'}
    with pytest.raises(ValueError, match='^night_ai_runtime_invalid$'):
        load_manifest(json.dumps(data).encode(), expected_environment_id='test-env')
    data['ca_bundles'] = {'operator': str(Path(__file__).resolve().parents[1] / 'config/night_case_ai.py')}
    with pytest.raises(ValueError, match='^night_ai_runtime_invalid$'):
        load_manifest(json.dumps(data).encode(), expected_environment_id='test-env')


def test_file_loader_rejects_relative_path_and_oversize_manifest():
    with pytest.raises(ValueError, match='^night_ai_runtime_invalid$'):
        load_manifest_file(Path('manifest.json'), expected_environment_id='test-env')
    with pytest.raises(ValueError, match='^night_ai_runtime_invalid$'):
        load_manifest(b' ' * 262145, expected_environment_id='test-env')
