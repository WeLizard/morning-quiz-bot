"""Deterministic backend/resolver spies; no actual cloud sockets or DB calls."""
import asyncio
from datetime import datetime, timedelta, timezone
import json
import ssl
import time
from uuid import uuid4

import pytest

from config.night_case_ai import EndpointPolicy
from infrastructure.night_ai_adapters import build_inference,build_oauth,OAuthToken,GIGA_OAUTH_ORIGIN
from infrastructure.night_ai_gateway import (CachedTokenRef, DispatchAuthorization, NetworkBudget,
    NightAIGateway, OAuthCache, OperatorPolicy, TicketFactory, TransportFailure)
from tests.test_night_ai_adapters import profile_fixture


class FakeStream:
    def __init__(self,response,peer,*,block=None,on_read=None):
        self.response,self.peer,self.block,self.on_read=response,peer,block,on_read
        self.writes=[];self.sni=[];self.closed=False
    async def read(self,max_bytes,timeout=None):
        if self.block is not None:await self.block.wait()
        data=self.response[:max_bytes];self.response=self.response[max_bytes:]
        if self.on_read is not None:self.on_read()
        return data
    async def write(self,buffer,timeout=None):self.writes.append(buffer)
    async def start_tls(self,ssl_context,server_hostname=None,timeout=None):self.sni.append(server_hostname);return self
    async def aclose(self):self.closed=True
    def get_extra_info(self,name):return self.peer if name=='server_addr' else None


class FakeBackend:
    def __init__(self,*,body=None,status=200,headers=(),block=None,on_read=None):
        body=body if body is not None else b'{"choices":[{"message":{"content":"safe"},"finish_reason":"stop"}]}'
        self.response=(b'HTTP/1.1 '+str(status).encode()+b' Synthetic\r\nContent-Length: '+str(len(body)).encode()+b'\r\n'
                       +b''.join(k+b': '+v+b'\r\n' for k,v in headers)+b'\r\n'+body)
        self.calls=[];self.streams=[];self.block=block;self.on_read=on_read
    async def connect_tcp(self,**kwargs):
        self.calls.append(kwargs)
        stream=FakeStream(self.response,(kwargs['host'],kwargs['port']),block=self.block,on_read=self.on_read)
        self.streams.append(stream);return stream


def cloud_ticket(*,remaining=12,profile=None,registry=None,wire=None):
    if profile is None:profile,registry=profile_fixture('openai',adapter='openai_chat')
    if wire is None:wire=build_inference(profile,registry,system='s',user='u',secret=b'synthetic-key',max_output_tokens=64)
    now=datetime.now(timezone.utc);authnow=now+timedelta(seconds=12-remaining);permit,nonce=uuid4(),uuid4()
    budget=NetworkBudget.create(permit,nonce,now,now+timedelta(seconds=12),now_utc=authnow,monotonic_now=time.monotonic())
    authorization=DispatchAuthorization(permit,nonce,profile.config_hash,uuid4(),budget.network_deadline,authnow)
    ticket=TicketFactory().issue(authorization,budget,wire)
    policy=OperatorPolicy(registry.policies[(wire.policy_id,wire.policy_version)],(),ssl.create_default_context())
    return ticket,policy


@pytest.mark.asyncio
@pytest.mark.parametrize('answers',[(),('8.8.8.8','127.0.0.1'),('8.8.8.8','169.254.169.254'),
    ('::ffff:8.8.8.8',),tuple('8.8.8.'+str(n) for n in range(1,34))])
async def test_all_dns_answers_are_checked_before_any_numeric_connect(answers):
    ticket,policy=cloud_ticket();backend=FakeBackend()
    async def resolve(host,port):return answers
    result=await NightAIGateway([policy],enabled=True,external_allowed=True,resolver=resolve,backend=backend).exchange(ticket)
    assert result.code=='endpoint_denied' and backend.calls==[]


@pytest.mark.asyncio
async def test_one_numeric_ip_is_pinned_no_failover_and_off_gateway_never_resolves():
    ticket,policy=cloud_ticket();backend=FakeBackend();dns=[]
    async def resolve(host,port):dns.append(host);return ('2606:4700:4700::1111','8.8.8.8','8.8.4.4')
    gateway=NightAIGateway([policy],resolver=resolve,backend=backend)
    assert (await gateway.exchange(ticket)).code=='disabled' and dns==[]
    gateway.enabled=True;gateway.external_allowed=True
    assert (await gateway.exchange(ticket)).code=='stale' and dns==[]
    ticket,policy=cloud_ticket()
    gateway=NightAIGateway([policy],enabled=True,external_allowed=True,resolver=resolve,backend=backend)
    result=await gateway.exchange(ticket)
    assert result.text=='safe' and len(backend.calls)==1 and backend.calls[0]['host']=='8.8.4.4'
    assert backend.streams[0].sni==['api.openai.com'] and backend.streams[0].closed


@pytest.mark.parametrize('url',['http://localhost.:123/v1','http://2130706433:123/v1','http://0177.0.0.1:123/v1',
    'http://0x7f000001:123/v1','http://llm.test:123/v1//hidden','http://llm.test:123/v1/../hidden',
    'http://user@llm.test:123/v1','http://llm.test:123/v1%2fsecret','http://[fe80::1%eth0]:123/v1'])
def test_operator_policy_rejects_host_and_path_confusion(url):
    with pytest.raises(ValueError):OperatorPolicy(EndpointPolicy('local:test',1,url,'trusted_local',None),('127.0.0.1/32',))


def test_local_policy_requires_exact_operator_cidrs_and_forbids_metadata():
    endpoint=EndpointPolicy('local:test',1,'http://llm.test:123/v1','trusted_local',None)
    with pytest.raises(ValueError):OperatorPolicy(endpoint)
    policy=OperatorPolicy(endpoint,('127.0.0.1/32','10.22.0.0/16','100.64.0.0/10','fd00::/8'))
    assert policy.address_allowed('127.0.0.1') and policy.address_allowed('10.22.2.3')
    assert not policy.address_allowed('10.23.2.3') and not policy.address_allowed('100.100.100.200')
    assert not policy.address_allowed('fd00:ec2::254')


@pytest.mark.asyncio
@pytest.mark.parametrize('status,headers,code,wait',[
    (302,[(b'Location',b'https://unsafe.invalid')],'endpoint_denied',None),
    (401,[],'auth_error',None),(403,[],'auth_error',None),(400,[],'config_error',None),
    (429,[(b'Retry-After',b'99')],'rate_limited',30),(503,[],'provider_error',2),
])
async def test_response_statuses_are_sanitized_without_retry_or_redirect(status,headers,code,wait):
    ticket,policy=cloud_ticket();backend=FakeBackend(status=status,headers=headers,body=b'synthetic-provider-secret-body')
    async def resolve(host,port):return ('8.8.8.8',)
    result=await NightAIGateway([policy],enabled=True,external_allowed=True,resolver=resolve,backend=backend).exchange(ticket)
    assert result==TransportFailure(code,status,wait) and len(backend.calls)==1
    assert 'secret-body' not in repr(result) and backend.streams[0].closed


@pytest.mark.asyncio
async def test_outer_deadline_and_external_cancel_close_the_pool():
    async def resolve(host,port):return ('8.8.8.8',)
    ticket,policy=cloud_ticket(remaining=.1);backend=FakeBackend(block=asyncio.Event())
    result=await NightAIGateway([policy],enabled=True,external_allowed=True,resolver=resolve,backend=backend).exchange(ticket)
    assert result.code=='timeout' and backend.streams[0].closed
    ticket,policy=cloud_ticket();backend=FakeBackend(block=asyncio.Event())
    task=asyncio.create_task(NightAIGateway([policy],enabled=True,external_allowed=True,resolver=resolve,backend=backend).exchange(ticket))
    for _ in range(50):
        if backend.streams:break
        await asyncio.sleep(.001)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):await task
    assert backend.streams[0].closed


def test_raw_urls_and_forged_tickets_or_mismatched_budget_are_not_accepted():
    ticket,_=cloud_ticket()
    factory=TicketFactory()
    from dataclasses import replace
    with pytest.raises(ValueError):factory.issue(replace(ticket.authorization,lease_nonce=uuid4()),ticket.budget,ticket.wire)
    with pytest.raises(ValueError):NetworkBudget(ticket.authorization.permit_id,ticket.authorization.lease_nonce,ticket.budget.network_deadline,float('inf'),object())


def test_oauth_cache_is_scoped_bounded_and_expiry_margin_applies():
    now=datetime(2026,11,16,tzinfo=timezone.utc);key=(uuid4(),'a'*64,'GIGACHAT_API_PERS')
    cache=OAuthCache(limit=1);token=OAuthToken(b'synthetic-token',now+timedelta(minutes=30))
    ref=cache.put(key,token,now)
    assert type(ref) is CachedTokenRef and 'synthetic-token' not in repr(ref)
    assert cache.get(*key,now) is ref and cache.get(uuid4(),key[1],key[2],now) is None
    assert cache.put((uuid4(),'b'*64,key[2]),token,now) is None
    assert cache.get(*key,now+timedelta(minutes=29)) is None


@pytest.mark.asyncio
async def test_oauth_and_inference_share_one_immutable_monotonic_twelve_seconds():
    profile,registry=profile_fixture('gigachat');now=datetime.now(timezone.utc)
    clock=[100.];wall=[now];permit,nonce,credential=uuid4(),uuid4(),uuid4()
    budget=NetworkBudget.create(permit,nonce,now,now+timedelta(seconds=12),now_utc=now,monotonic_now=clock[0])
    authorization=DispatchAuthorization(permit,nonce,profile.config_hash,credential,budget.network_deadline,now)
    oauth_wire=build_oauth(profile,registry,secret=b'synthetic-basic',policy_id='giga-oauth',policy_version=1)
    oauth_policy=OperatorPolicy(EndpointPolicy('giga-oauth',1,GIGA_OAUTH_ORIGIN,'cloud','operator-ca'),(),ssl.create_default_context())
    inference_endpoint=registry.policies[('cloud:gigachat',1)]
    policies=[oauth_policy,OperatorPolicy(inference_endpoint,(),ssl.create_default_context())]
    backend=FakeBackend(body=json.dumps({'access_token':'synthetic-token','expires_at':int((now+timedelta(minutes=30)).timestamp()*1000)}).encode(),
        on_read=lambda:clock.__setitem__(0,108.))
    async def resolver(host,port):return ('8.8.8.8',)
    gateway=NightAIGateway(policies,enabled=True,external_allowed=True,resolver=resolver,backend=backend,
        monotonic=lambda:clock[0],utcnow=lambda:wall[0])
    oauth_ticket=TicketFactory().issue(authorization,budget,oauth_wire)
    ref=await gateway.exchange(oauth_ticket)
    assert type(ref) is CachedTokenRef and budget.remaining(clock[0])==4
    wall[0]-=timedelta(hours=1)  # Wall correction does not create another12s budget.
    wire=build_inference(profile,registry,system='s',user='u',secret=None,access_token=ref.bytes_for_trusted_adapter(),max_output_tokens=64)
    sent=DispatchAuthorization(permit,nonce,profile.config_hash,credential,budget.network_deadline,now+timedelta(seconds=8))
    ticket=TicketFactory().issue(sent,budget,wire,token_ref=ref)
    late=FakeBackend(on_read=lambda:clock.__setitem__(0,113.));gateway.backend=late
    assert (await gateway.exchange(ticket)).code=='timeout'
    assert len(backend.calls)==1 and len(late.calls)==1 and late.streams[0].closed
    assert b'Basic synthetic-basic' in b''.join(backend.streams[0].writes)
    assert b'Basic' not in b''.join(late.streams[0].writes)


@pytest.mark.asyncio
async def test_giga_inference401_invalidates_exact_cache_ref_and_does_not_refresh_itself():
    profile,registry=profile_fixture('gigachat');now=datetime.now(timezone.utc);credential=uuid4()
    cache=OAuthCache();key=(credential,profile.config_hash,'GIGACHAT_API_PERS')
    ref=cache.put(key,OAuthToken(b'synthetic-token',now+timedelta(minutes=30)),now)
    wire=build_inference(profile,registry,system='s',user='u',secret=None,access_token=ref.bytes_for_trusted_adapter(),max_output_tokens=64)
    permit,nonce=uuid4(),uuid4();budget=NetworkBudget.create(permit,nonce,now,now+timedelta(seconds=12),now_utc=now,monotonic_now=time.monotonic())
    grant=DispatchAuthorization(permit,nonce,profile.config_hash,credential,budget.network_deadline,now)
    ticket=TicketFactory().issue(grant,budget,wire,token_ref=ref)
    backend=FakeBackend(status=401)
    async def resolver(host,port):return ('8.8.8.8',)
    gateway=NightAIGateway([OperatorPolicy(registry.policies[('cloud:gigachat',1)],(),ssl.create_default_context())],
        enabled=True,external_allowed=True,resolver=resolver,backend=backend,oauth_cache=cache)
    assert (await gateway.exchange(ticket)).code=='auth_error'
    assert len(backend.calls)==1 and cache.get(*key,now) is None
    from dataclasses import replace
    with pytest.raises(ValueError):TicketFactory().issue(replace(grant,credential_id=uuid4()),budget,wire,token_ref=ref)


@pytest.mark.asyncio
async def test_httpcore_debug_does_not_log_credential_or_private_prompt(caplog):
    import logging
    profile,registry=profile_fixture('openai',adapter='openai_chat')
    wire=build_inference(profile,registry,system='PRIVATE_TEMPLATE_CANARY',user='PRIVATE_VIEW_CANARY',secret=b'credential-canary',max_output_tokens=64)
    ticket,policy=cloud_ticket(profile=profile,registry=registry,wire=wire)
    async def resolver(host,port):return ('8.8.8.8',)
    caplog.set_level(logging.DEBUG,logger='httpcore')
    result=await NightAIGateway([policy],enabled=True,external_allowed=True,resolver=resolver,backend=FakeBackend()).exchange(ticket)
    assert result.text=='safe'
    assert all(secret not in caplog.text for secret in ('PRIVATE_TEMPLATE_CANARY','PRIVATE_VIEW_CANARY','credential-canary'))


@pytest.mark.asyncio
async def test_default_resolver_requests_both_ip_families_and_stream_sockets(monkeypatch):
    import socket
    from infrastructure.night_ai_gateway import resolve_all
    calls=[]
    async def getaddrinfo(host,port,*,family,type):
        calls.append((host,port,family,type))
        return [(socket.AF_INET,socket.SOCK_STREAM,6,'',('8.8.8.8',443)),
                (socket.AF_INET6,socket.SOCK_STREAM,6,'',('2606:4700:4700::1111',443,0,0))]
    monkeypatch.setattr(asyncio.get_running_loop(),'getaddrinfo',getaddrinfo)
    assert await resolve_all('api.openai.com',443)==('8.8.8.8','2606:4700:4700::1111')
    assert calls==[('api.openai.com',443,socket.AF_UNSPEC,socket.SOCK_STREAM)]


@pytest.mark.asyncio
@pytest.mark.parametrize('case',['status-line','header-line','success-cookie'])
async def test_provider_protocol_and_success_headers_never_enter_httpcore_debug(caplog,case):
    import logging
    ticket,policy=cloud_ticket();backend=FakeBackend(headers=[(b'Set-Cookie',b'PROVIDER_SESSION_CANARY')])
    if case=='status-line':backend.response=b'PROVIDER_PRIVATE_STATUS_CANARY\r\n\r\n'
    if case=='header-line':backend.response=b'HTTP/1.1 200 OK\r\nPROVIDER_PRIVATE_HEADER_CANARY\r\n\r\n'
    async def resolver(host,port):return ('8.8.8.8',)
    caplog.set_level(logging.DEBUG,logger='httpcore')
    result=await NightAIGateway([policy],enabled=True,external_allowed=True,resolver=resolver,backend=backend).exchange(ticket)
    if case=='success-cookie':assert result.text=='safe'
    else:assert result.code=='network_error'
    assert not any(value in caplog.text for value in (
        'PROVIDER_PRIVATE_STATUS_CANARY','PROVIDER_PRIVATE_HEADER_CANARY','PROVIDER_SESSION_CANARY'))


async def unrelated_httpcore_request(cookie):
    import httpcore
    backend=FakeBackend(body=b'OK',headers=[(b'Set-Cookie',cookie)])
    async with httpcore.AsyncConnectionPool(network_backend=backend,max_keepalive_connections=0,retries=0) as pool:
        async with pool.stream('GET','http://unrelated.test/',headers=[(b'Host',b'unrelated.test')]) as response:
            assert await response.aread()==b'OK'


@pytest.mark.asyncio
async def test_night_trace_scope_preserves_parallel_unrelated_httpcore_logs(caplog):
    import logging
    entered,release=asyncio.Event(),asyncio.Event()
    class PausingBackend(FakeBackend):
        async def connect_tcp(self,**kwargs):
            entered.set();await release.wait()
            return await super().connect_tcp(**kwargs)
    ticket,policy=cloud_ticket();backend=PausingBackend(headers=[(b'Set-Cookie',b'NIGHT_PARALLEL_COOKIE_CANARY')])
    async def resolver(host,port):return ('8.8.8.8',)
    caplog.set_level(logging.DEBUG,logger='httpcore')
    levels={name:logging.getLogger(name).level for name in ('httpcore','httpcore.connection','httpcore.http11')}
    task=asyncio.create_task(NightAIGateway([policy],enabled=True,external_allowed=True,resolver=resolver,backend=backend).exchange(ticket))
    try:
        await asyncio.wait_for(entered.wait(),1)
        await unrelated_httpcore_request(b'UNRELATED_PARALLEL_COOKIE_CANARY')
    finally:release.set()
    assert (await task).text=='safe'
    assert 'UNRELATED_PARALLEL_COOKIE_CANARY' in caplog.text
    assert 'NIGHT_PARALLEL_COOKIE_CANARY' not in caplog.text
    assert levels=={name:logging.getLogger(name).level for name in levels}


@pytest.mark.asyncio
async def test_trace_scope_resets_in_same_task_after_gateway_cancellation(caplog):
    import logging
    ticket,policy=cloud_ticket();backend=FakeBackend(block=asyncio.Event())
    async def resolver(host,port):return ('8.8.8.8',)
    gateway=NightAIGateway([policy],enabled=True,external_allowed=True,resolver=resolver,backend=backend)
    caplog.set_level(logging.DEBUG,logger='httpcore')
    async def caller():
        try:await gateway.exchange(ticket)
        except asyncio.CancelledError:pass
        # This executes in the exact cancelled request's Context, not merely
        # the outside test task. A missing finally/reset would suppress it.
        await unrelated_httpcore_request(b'UNRELATED_AFTER_CANCEL_CANARY')
    task=asyncio.create_task(caller())
    for _ in range(100):
        if backend.streams:break
        await asyncio.sleep(.001)
    task.cancel();await task
    assert backend.streams[0].closed
    assert 'UNRELATED_AFTER_CANCEL_CANARY' in caplog.text
