"""No providers are contacted by these closed codec fixtures."""
import json
from uuid import uuid4

import pytest

from config.night_case_ai import PRESETS, EndpointPolicy, ModelCapabilities, ProfileRegistry, build_profile


def profile_fixture(name,*,adapter=None,capabilities=None,auth_mode=None):
    model='owner/synthetic'
    fields={};routing=None
    if name=='anthropic':fields={'workspace_id':'wrkspc_synthetic'}
    if name=='yandex':fields={'folder_id':'synthetic-folder'};model='gpt://synthetic-folder/synthetic'
    if name=='gigachat':fields={'scope':'GIGACHAT_API_PERS'}
    if name in {'openrouter','huggingface'}:routing={'provider':'provider-a','allow_fallback':False}
    if name=='huggingface':model+=':provider-a'
    caps=capabilities or ModelCapabilities(supports_temperature=True)
    cloud=ProfileRegistry.cloud({(name,model):caps});policies=dict(cloud.policies)
    endpoint=None
    if PRESETS[name].base_url is None:
        local=EndpointPolicy('local:'+name,1,'http://llm.test:8080/v1','trusted_local',None)
        policies[(local.policy_id,1)]=local;endpoint=(local.policy_id,1)
    registry=ProfileRegistry(policies,cloud.models)
    kwargs=dict(registry=registry,preset=name,model_id=model,credential_id=uuid4(),endpoint_policy=endpoint,
        project_fields=fields,routing=routing,temperature=None if name=='anthropic' else .2)
    if adapter is not None:kwargs['adapter']=adapter
    if auth_mode is not None:kwargs['auth_mode']=auth_mode
    elif PRESETS[name].base_url is None:kwargs['auth_mode']='bearer'
    return build_profile(**kwargs),registry


@pytest.mark.parametrize('family,wrapper',[
    ('openai_chat',{'choices':[{'message':{'content':'safe'},'finish_reason':'stop'}]}),
    ('gigachat_chat',{'choices':[{'message':{'content':'safe'},'finish_reason':'stop'}]}),
    ('openai_responses',{'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':'safe'}]}]}),
    ('anthropic_messages',{'stop_reason':'end_turn','content':[{'type':'text','text':'safe'}]}),
])
def test_four_response_codecs_extract_only_finished_text(family,wrapper):
    from infrastructure.night_ai_adapters import parse_inference
    response=parse_inference(family,json.dumps(wrapper).encode())
    assert response.text=='safe' and response.usage is None


@pytest.mark.parametrize('raw',[b'{"choices":[],"choices":[]}',b'{"x":NaN}',b'{} trailing',b'\xff'])
def test_json_decoder_is_strict(raw):
    from infrastructure.night_ai_adapters import strict_json, AdapterError
    with pytest.raises(AdapterError):strict_json(raw)


@pytest.mark.parametrize('preset',list(PRESETS))
def test_all_eighteen_preset_wire_metadata_are_explicit(preset):
    from infrastructure.night_ai_adapters import build_inference
    profile,registry=profile_fixture(preset)
    wire=build_inference(profile,registry,system='approved template',user='approved view',max_output_tokens=64,
        secret=None if preset=='gigachat' else b'synthetic-key',access_token=b'synthetic-access' if preset=='gigachat' else None)
    doc=json.loads(wire.body);headers=dict(wire.headers)
    assert wire.base_url==profile.document()['endpoint']['base_url']
    assert doc['model']==profile.document()['model_id'] and doc['stream'] is False
    assert all(k not in doc for k in ('tools','functions','attachments','background','previous_response_id'))
    assert headers[b'authorization']==b'Bearer '+(b'synthetic-access' if preset=='gigachat' else b'synthetic-key')
    if preset=='openrouter':assert doc['provider']=={'only':['provider-a'],'allow_fallbacks':False}
    if preset=='huggingface':assert doc['model'].endswith(':provider-a') and ':auto' not in doc['model']
    if preset=='yandex':assert headers[b'openai-project']==b'synthetic-folder' and headers[b'x-data-logging-enabled']==b'false'
    if preset=='anthropic':
        assert headers[b'anthropic-version']==b'2026-10-21' and headers[b'anthropic-workspace-id']==b'wrkspc_synthetic'
        assert all(field not in doc for field in ('temperature','top_p','top_k'))
    if wire.family=='openai_responses':assert doc['store'] is False
    assert 'synthetic-key' not in repr(wire) and 'approved view' not in repr(wire)


def test_auth_headers_and_generation_fields_are_closed():
    from infrastructure.night_ai_adapters import build_inference,AdapterError
    profile,registry=profile_fixture('anthropic',auth_mode='anthropic_api_key')
    wire=build_inference(profile,registry,system='s',user='u',secret=b'synthetic-key',max_output_tokens=64)
    assert dict(wire.headers)[b'x-api-key']==b'synthetic-key' and b'authorization' not in dict(wire.headers)
    for key in (b'key\r\ninjected: yes',b'key\x00',b''):
        with pytest.raises(AdapterError):build_inference(profile,registry,system='s',user='u',secret=key,max_output_tokens=64)
    with pytest.raises(AdapterError):build_inference(profile,registry,system='s',user='u',secret=b'key',max_output_tokens=801)
    incompatible,registry=profile_fixture('openai',adapter='openai_chat',capabilities=ModelCapabilities(output_limit_field='max_output_tokens',supports_temperature=True))
    with pytest.raises(AdapterError):build_inference(incompatible,registry,system='s',user='u',secret=b'key',max_output_tokens=64)


@pytest.mark.parametrize('family,doc',[
    ('openai_chat',{'choices':[{'message':{'content':'unsafe','tool_calls':[{}]},'finish_reason':'stop'}]}),
    ('openai_chat',{'choices':[{'message':{'content':'unsafe'},'finish_reason':'length'}]}),
    ('openai_chat',{'choices':[{'message':{'content':'unsafe','refusal':'no'},'finish_reason':'stop'}]}),
    ('openai_responses',{'status':'incomplete','output':[]}),
    ('openai_responses',{'status':'completed','output':[{'type':'function_call','arguments':'unsafe'}]}),
    ('anthropic_messages',{'stop_reason':'end_turn','content':[{'type':'thinking','thinking':'private'}]}),
    ('anthropic_messages',{'stop_reason':'tool_use','content':[{'type':'text','text':'unsafe'}]}),
    ('gigachat_chat',{'choices':[{'message':{'content':'unsafe'},'finish_reason':'function_call'}]}),
])
def test_non_text_or_unfinished_model_responses_fail_closed(family,doc):
    from infrastructure.night_ai_adapters import parse_inference,AdapterError
    with pytest.raises(AdapterError):parse_inference(family,json.dumps(doc).encode())


def test_nested_json_text_and_untrusted_usage_bounds():
    from infrastructure.night_ai_adapters import strict_json,parse_inference,AdapterError
    for raw in (b'['*17+b'0'+b']'*17,b'{"number":1e999}',b'x'*(256*1024+1)):
        with pytest.raises(AdapterError):strict_json(raw)
    doc={'choices':[{'message':{'content':'x'*4001},'finish_reason':'stop'}]}
    with pytest.raises(AdapterError):parse_inference('openai_chat',json.dumps(doc).encode())
    doc['choices'][0]['message']['content']='safe';doc['usage']={'prompt_tokens':True,'completion_tokens':1}
    assert parse_inference('openai_chat',json.dumps(doc).encode()).usage is None
    doc['usage']={'prompt_tokens':5,'completion_tokens':6}
    assert parse_inference('openai_chat',json.dumps(doc).encode()).usage=={'input_tokens':5,'output_tokens':6}


def test_giga_oauth_fixed_origin_basic_scope_uuid_and_response_expiry():
    from datetime import datetime,timedelta,timezone
    from uuid import UUID
    from infrastructure.night_ai_adapters import build_oauth,parse_oauth,AdapterError
    profile,registry=profile_fixture('gigachat')
    wire=build_oauth(profile,registry,secret=b'synthetic-basic',policy_id='giga-oauth',policy_version=1)
    assert wire.base_url=='https://ngw.devices.sberbank.ru:9443' and wire.path_suffix=='/api/v2/oauth'
    assert dict(wire.headers)[b'authorization']==b'Basic synthetic-basic'
    UUID(dict(wire.headers)[b'rquid'].decode());assert wire.body==b'scope=GIGACHAT_API_PERS'
    now=datetime(2026,11,16,tzinfo=timezone.utc)
    valid={'access_token':'synthetic-token','expires_at':int((now+timedelta(minutes=30)).timestamp()*1000)}
    assert parse_oauth(json.dumps(valid).encode(),now).token==b'synthetic-token'
    for expiry in (True,now.timestamp(),int((now-timedelta(seconds=1)).timestamp()*1000),int((now+timedelta(minutes=32)).timestamp()*1000)):
        with pytest.raises(AdapterError):parse_oauth(json.dumps(valid|{'expires_at':expiry}).encode(),now)
