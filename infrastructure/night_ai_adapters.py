"""Closed text-only wire codecs. No HTTP, DB, retries, endpoints or key lookup.

These are protocol codecs, not evidence of model quality or live capability.
Only trusted dispatch code may call the builders with already approved prompts.
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import json
import math
import re
from uuid import UUID, uuid4

from config.night_case_ai import PRESETS, ProfileRegistry, ProfileRevision
from storage.night_ai import canonical


FAMILIES=frozenset({'openai_chat','openai_responses','anthropic_messages','gigachat_chat'})
_WIRE_AUTHORITY=object()


class AdapterError(ValueError):
    def __init__(self,code='invalid_response'):
        self.code=code
        super().__init__(code)


def strict_json(raw: bytes, *, limit=256*1024):
    def pairs(items):
        result={}
        for key,value in items:
            if key in result: raise ValueError()
            result[key]=value
        return result
    def reject(_): raise ValueError()
    def check(value,depth=0):
        if depth>16: raise ValueError()
        if type(value) is float and not math.isfinite(value): raise ValueError()
        if type(value) is dict:
            for child in value.values():check(child,depth+1)
        elif type(value) is list:
            for child in value:check(child,depth+1)
    try:
        if type(raw) is not bytes or len(raw)>limit: raise ValueError()
        value=json.loads(raw.decode('utf8'),object_pairs_hook=pairs,parse_constant=reject)
        check(value)
        return value
    except (ValueError,TypeError,UnicodeError,RecursionError,OverflowError):
        raise AdapterError() from None


def _text(value, *, allow_empty=False):
    if (type(value) is not str or not allow_empty and not value or '\x00' in value
            or len(value)>4000 or len(value.encode('utf8'))>16000): raise AdapterError()
    return value


def _secret(value,limit=8192):
    if type(value) is not bytes or not 1<=len(value)<=limit or any(x<33 or x>126 for x in value):
        raise AdapterError('credential_unavailable')
    return value


def _usage(document,left,right):
    if type(document) is not dict:return None
    a,b=document.get(left),document.get(right)
    if any(type(x) is not int or not 0<=x<=2**63-1 for x in (a,b)):return None
    return {'input_tokens':a,'output_tokens':b}


@dataclass(frozen=True,repr=False)
class BoundedResponse:
    text: str=field(repr=False)
    usage: dict | None=field(repr=False)


def parse_inference(family,raw):
    try:
        if family not in FAMILIES:raise AdapterError('config_error')
        doc=strict_json(raw)
        if type(doc) is not dict:raise AdapterError()
        if family in {'openai_chat','gigachat_chat'}:
            choices=doc['choices']
            if type(choices) is not list or len(choices)!=1:raise AdapterError()
            choice=choices[0];message=choice['message']
            if (choice['finish_reason']!='stop' or type(message) is not dict
                    or message.get('tool_calls') or message.get('function_call') or message.get('refusal')
                    or message.get('role','assistant')!='assistant'):raise AdapterError()
            text=_text(message['content']);usage=_usage(doc.get('usage'),'prompt_tokens','completion_tokens')
        elif family=='openai_responses':
            if doc['status']!='completed' or type(doc['output']) is not list:raise AdapterError()
            parts=[]
            for item in doc['output']:
                if type(item) is not dict:raise AdapterError()
                if item.get('type')=='reasoning':continue
                if item.get('type')!='message' or item.get('status','completed')!='completed' or type(item.get('content')) is not list:raise AdapterError()
                for part in item['content']:
                    if type(part) is not dict or part.get('type')!='output_text':raise AdapterError()
                    parts.append(_text(part['text'],allow_empty=True))
            text=_text(''.join(parts));usage=_usage(doc.get('usage'),'input_tokens','output_tokens')
        else:
            if doc['stop_reason']!='end_turn' or type(doc['content']) is not list:raise AdapterError()
            parts=[]
            for part in doc['content']:
                if type(part) is not dict or part.get('type')!='text':raise AdapterError()
                parts.append(_text(part['text'],allow_empty=True))
            text=_text(''.join(parts));usage=_usage(doc.get('usage'),'input_tokens','output_tokens')
        return BoundedResponse(text,usage)
    except AdapterError:raise
    except (KeyError,TypeError,AttributeError,UnicodeError,ValueError,OverflowError):
        raise AdapterError() from None


@dataclass(frozen=True,repr=False)
class WireRequest:
    """Internal builder output; contains credentials and private prompt bytes."""
    family: str
    preset: str
    policy_id: str
    policy_version: int
    base_url: str
    path_suffix: str
    config_hash: str
    oauth_scope: str | None
    headers: tuple[tuple[bytes,bytes],...]=field(repr=False)
    body: bytes=field(repr=False)
    _authority: object=field(repr=False)

    def __post_init__(self):
        routes={'openai_chat':'/chat/completions','openai_responses':'/responses',
            'anthropic_messages':'/v1/messages','gigachat_chat':'/chat/completions','gigachat_oauth':'/api/v2/oauth'}
        allowed_headers={b'content-type',b'accept',b'authorization',b'x-api-key',b'openai-organization',
            b'openai-project',b'anthropic-version',b'anthropic-workspace-id',b'x-data-logging-enabled',b'rquid'}
        if (self._authority is not _WIRE_AUTHORITY or self.family not in routes or self.preset not in PRESETS
                or self.path_suffix!=routes[self.family] or type(self.policy_id) is not str
                or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}',self.policy_id)
                or type(self.policy_version) is not int or not 1<=self.policy_version<=2147483647
                or type(self.config_hash) is not str or not re.fullmatch('[a-f0-9]{64}',self.config_hash)
                or type(self.body) is not bytes or len(self.body)>(16384 if self.family=='gigachat_oauth' else 65536)
                or type(self.headers) is not tuple):raise AdapterError('config_error')
        if self.family=='gigachat_oauth':
            if self.preset!='gigachat' or self.base_url!=GIGA_OAUTH_ORIGIN or self.oauth_scope not in GIGA_SCOPES:raise AdapterError('config_error')
        elif self.family not in PRESETS[self.preset].adapters:raise AdapterError('config_error')
        if PRESETS[self.preset].base_url is not None and self.family!='gigachat_oauth' and self.base_url!=PRESETS[self.preset].base_url:
            raise AdapterError('config_error')
        for pair in self.headers:
            if (type(pair) is not tuple or len(pair)!=2 or type(pair[0]) is not bytes or type(pair[1]) is not bytes
                    or pair[0] not in allowed_headers or len(pair[1])>16392
                    or any(x<32 or x>126 for x in pair[1])):raise AdapterError('config_error')
        headers=dict(self.headers)
        if len(headers)!=len(self.headers) or headers.get(b'accept')!=b'application/json':raise AdapterError('config_error')
        expected=b'application/x-www-form-urlencoded' if self.family=='gigachat_oauth' else b'application/json'
        if headers.get(b'content-type')!=expected:raise AdapterError('config_error')
        auth=headers.get(b'authorization')
        if auth is not None and not auth.startswith(b'Basic ' if self.family=='gigachat_oauth' else b'Bearer '):raise AdapterError('config_error')
        if b'x-api-key' in headers and (self.preset!='anthropic' or auth is not None):raise AdapterError('config_error')


def build_inference(profile: ProfileRevision, registry: ProfileRegistry, *, system: str, user: str,
                    secret: bytes | None, max_output_tokens: int, access_token: bytes | None=None,
                    output_schema: dict | None=None) -> WireRequest:
    """No arbitrary URL/header/generation options. Config is re-decoded, never guessed."""
    try:
        if type(profile) is not ProfileRevision or type(registry) is not ProfileRegistry:raise ValueError()
        doc=ProfileRevision.decode(profile.document(),registry).document()
        if type(system) is not str or type(user) is not str or any('\x00' in s for s in (system,user)):raise ValueError()
        if type(max_output_tokens) is not int or not 1<=max_output_tokens<=min(800,doc['generation']['max_output_tokens']):raise ValueError()
        family,name=doc['adapter'],doc['preset'];endpoint=doc['endpoint']
        field_name=doc['capabilities']['output_limit_field']
        allowed={'openai_chat':{'max_tokens','max_completion_tokens'},'openai_responses':{'max_output_tokens'},
                 'anthropic_messages':{'max_tokens'},'gigachat_chat':{'max_tokens'}}
        if field_name not in allowed[family]:raise ValueError()
        headers=[(b'content-type',b'application/json'),(b'accept',b'application/json')]
        if family=='gigachat_chat':
            if secret is not None or access_token is None:raise AdapterError('credential_unavailable')
            headers.append((b'authorization',b'Bearer '+_secret(access_token,16384)))
        elif doc['auth_mode']=='none':
            if secret is not None or access_token is not None:raise ValueError()
        else:
            if access_token is not None:raise ValueError()
            headers.append((b'x-api-key' if doc['auth_mode']=='anthropic_api_key' else b'authorization',
                _secret(secret) if doc['auth_mode']=='anthropic_api_key' else b'Bearer '+_secret(secret)))
        fields=doc['project_fields']
        if name=='openai':
            for key,header in [('organization_id',b'openai-organization'),('project_id',b'openai-project')]:
                if key in fields:headers.append((header,_secret(fields[key].encode('ascii'),256)))
        if name=='anthropic':
            headers.extend([(b'anthropic-version',doc['api_version'].encode('ascii')),
                            (b'anthropic-workspace-id',_secret(fields['workspace_id'].encode('ascii'),256))])
        if name=='yandex':
            headers.extend([(b'openai-project',_secret(fields['folder_id'].encode('ascii'),256)),(b'x-data-logging-enabled',b'false')])
        body={'model':doc['model_id'],'stream':False,field_name:max_output_tokens}
        if family=='openai_responses':
            suffix='/responses';body.update(instructions=system,input=user,store=False)
        elif family=='anthropic_messages':
            suffix='/v1/messages';body.update(system=system,messages=[{'role':'user','content':user}])
        else:
            suffix='/chat/completions';body['messages']=[{'role':'system','content':system},{'role':'user','content':user}]
            if family=='openai_chat':body['n']=1
        temperature=doc['generation']['temperature']
        if temperature is not None:body['temperature']=temperature
        json_output=doc['capabilities']['json_output']
        if json_output!='prompt':
            if family not in {'openai_chat','openai_responses'}:raise ValueError()
            if json_output=='json_object':format={'type':'json_object'}
            elif json_output=='json_schema' and type(output_schema) is dict:
                canonical(output_schema,limit=16384)
                format={'type':'json_schema','name':'night_result','strict':True,'schema':output_schema}
            else:raise ValueError()
            if family=='openai_chat':
                body['response_format']=({'type':'json_schema','json_schema':{k:v for k,v in format.items() if k!='type'}}
                                         if json_output=='json_schema' else format)
            else:body['text']={'format':format}
        if name=='openrouter':body['provider']={'only':[doc['routing']['provider']],'allow_fallbacks':False}
        encoded=canonical(body,limit=65536)
        return WireRequest(family,name,endpoint['policy_id'],endpoint['policy_version'],endpoint['base_url'],suffix,
            doc['config_hash'],fields['scope'] if name=='gigachat' else None,
            tuple(headers),encoded,_WIRE_AUTHORITY)
    except AdapterError:raise
    except (ValueError,KeyError,TypeError,AttributeError,UnicodeError,OverflowError):
        raise AdapterError('config_error') from None


GIGA_OAUTH_ORIGIN='https://ngw.devices.sberbank.ru:9443'
GIGA_SCOPES=frozenset({'GIGACHAT_API_PERS','GIGACHAT_API_B2B','GIGACHAT_API_CORP'})


def build_oauth(profile: ProfileRevision, registry: ProfileRegistry, *, secret: bytes,
                policy_id: str, policy_version: int) -> WireRequest:
    try:
        doc=ProfileRevision.decode(profile.document(),registry).document()
        if doc['preset']!='gigachat' or doc['auth_mode']!='gigachat_oauth_basic':raise ValueError()
        scope=doc['project_fields']['scope']
        if scope not in GIGA_SCOPES:raise ValueError()
        return WireRequest('gigachat_oauth','gigachat',policy_id,policy_version,GIGA_OAUTH_ORIGIN,'/api/v2/oauth',doc['config_hash'],scope,
            ((b'content-type',b'application/x-www-form-urlencoded'),(b'accept',b'application/json'),
             (b'authorization',b'Basic '+_secret(secret)),(b'rquid',str(uuid4()).encode('ascii'))),
            ('scope='+scope).encode('ascii'),_WIRE_AUTHORITY)
    except AdapterError:raise
    except (ValueError,KeyError,TypeError,AttributeError,UnicodeError):raise AdapterError('config_error') from None


@dataclass(frozen=True,repr=False)
class OAuthToken:
    token: bytes=field(repr=False)
    expires_at: datetime


def parse_oauth(raw,now):
    try:
        doc=strict_json(raw,limit=16384)
        expiry=doc['expires_at']
        if type(expiry) is not int or expiry<0:raise ValueError()
        expires_at=datetime.fromtimestamp(expiry/1000,tz=timezone.utc)
        if not now<expires_at<=now+timedelta(minutes=31):raise ValueError()
        token=_secret(doc['access_token'].encode('ascii'),16384)
        return OAuthToken(token,expires_at)
    except (ValueError,KeyError,TypeError,AttributeError,UnicodeError,OverflowError,OSError):
        raise AdapterError() from None
