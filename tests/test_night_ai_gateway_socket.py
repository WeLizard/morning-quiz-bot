"""Owned ephemeral loopback TLS; no external DNS/provider or database access."""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import json
import os
import ssl
from uuid import uuid4

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from httpcore._backends.anyio import AnyIOBackend
import pytest

from config.night_case_ai import EndpointPolicy, ModelCapabilities, ProfileRegistry, build_profile
from infrastructure.night_ai_adapters import BoundedResponse, build_inference
from infrastructure.night_ai_gateway import (DispatchAuthorization, NetworkBudget, NightAIGateway,
    OperatorPolicy, TicketFactory, TransportFailure)


@pytest.fixture(scope='module')
def event_loop_policy():
    # Windows Proactor SSL server bookkeeping can hang wait_closed after a
    # peer rejects an oversized body (WinError10054 in _call_connection_lost).
    # This is a test-owned loop policy, matching Linux's selector socket loop;
    # no product/global OS settings or library internals are patched.
    return asyncio.WindowsSelectorEventLoopPolicy() if os.name=='nt' else asyncio.DefaultEventLoopPolicy()


@pytest.fixture
def tls_contexts(tmp_path):
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    now=datetime.now(timezone.utc)
    name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'night-llm.test')])
    cert=(x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(days=1)).not_valid_after(now+timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName('night-llm.test')]),critical=False)
        .add_extension(x509.BasicConstraints(ca=True,path_length=None),critical=True).sign(key,hashes.SHA256()))
    pem=cert.public_bytes(serialization.Encoding.PEM)
    certfile=tmp_path/'server.pem';keyfile=tmp_path/'server-key.pem'
    certfile.write_bytes(pem);keyfile.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
    server=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);server.load_cert_chain(certfile,keyfile)
    client=ssl.create_default_context(cadata=pem.decode())
    return server,client


@asynccontextmanager
async def own_server(context,*,reply=None,headers=None,delay=0,chunked=False,trickle_delay=0):
    requests=[];sni=[];handlers=set();closed=asyncio.Event()
    context.set_servername_callback(lambda sock,name,ctx:sni.append(name))
    async def handle(reader,writer):
        task=asyncio.current_task();handlers.add(task)
        try:
            raw=await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'),3)
            head={k.lower():v.strip() for k,v in (line.split(b':',1) for line in raw.split(b'\r\n')[1:] if line)}
            if b'content-length' in head:body=await reader.readexactly(int(head[b'content-length']))
            else:
                parts=[]
                while True:
                    length=int((await reader.readline()).strip(),16)
                    if length==0:
                        await reader.readline();break
                    parts.append(await reader.readexactly(length));await reader.readexactly(2)
                body=b''.join(parts)
            requests.append((raw,head,body))
            await asyncio.sleep(delay)
            payload=reply if reply is not None else b'{"choices":[{"message":{"content":"safe"},"finish_reason":"stop"}]}'
            extra=b''.join(k+b': '+v+b'\r\n' for k,v in (headers or []))
            if chunked:
                writer.write(b'HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n'+extra+b'\r\n')
                parts=(payload[i:i+1] for i in range(len(payload))) if trickle_delay else (payload[:3],payload[3:])
                for part in parts:
                    writer.write(hex(len(part))[2:].encode()+b'\r\n'+part+b'\r\n');await writer.drain()
                    if trickle_delay:await asyncio.sleep(trickle_delay)
                writer.write(b'0\r\n\r\n')
            else:writer.write(b'HTTP/1.1 200 OK\r\nContent-Length: '+str(len(payload)).encode()+b'\r\n'+extra+b'\r\n'+payload)
            await writer.drain()
        except (ConnectionError,asyncio.TimeoutError,asyncio.IncompleteReadError,ssl.SSLError):pass
        finally:
            writer.close()
            try:await asyncio.wait_for(writer.wait_closed(),1)
            except (ConnectionError,ssl.SSLError,TimeoutError):writer.transport.abort()
            handlers.discard(task);closed.set()
    server=await asyncio.start_server(handle,'127.0.0.1',0,ssl=context,ssl_handshake_timeout=1,ssl_shutdown_timeout=1)
    try:yield server.sockets[0].getsockname()[1],requests,sni,closed
    finally:
        server.close();await server.wait_closed()
        pending=list(handlers)
        for task in pending:task.cancel()
        if pending:await asyncio.gather(*pending,return_exceptions=True)


class BackendSpy:
    def __init__(self):self.calls=[];self.delegate=AnyIOBackend()
    async def connect_tcp(self,**kwargs):
        self.calls.append(kwargs.copy())
        return await self.delegate.connect_tcp(**kwargs)


def local_ticket(port,client,*,host='night-llm.test',clock=None):
    endpoint=EndpointPolicy('owned:test',1,f'https://{host}:{port}/v1','trusted_local','owned-test-ca')
    registry=ProfileRegistry({('owned:test',1):endpoint},{('generic_openai','synthetic-model'):ModelCapabilities()})
    credential=uuid4()
    profile=build_profile(registry=registry,preset='generic_openai',model_id='synthetic-model',credential_id=credential,
        endpoint_policy=('owned:test',1),auth_mode='bearer')
    wire=build_inference(profile,registry,system='synthetic system',user='synthetic user',secret=b'synthetic-secret-never-log',max_output_tokens=64)
    now=datetime.now(timezone.utc);permit,nonce=uuid4(),uuid4()
    mono=asyncio.get_running_loop().time() if clock is None else clock()
    budget=NetworkBudget.create(permit,nonce,now,now+timedelta(seconds=12),now_utc=now,monotonic_now=mono)
    authorization=DispatchAuthorization(permit,nonce,profile.config_hash,credential,budget.network_deadline,now)
    return TicketFactory().issue(authorization,budget,wire),OperatorPolicy(endpoint,('127.0.0.1/32',),client)


@pytest.mark.asyncio
async def test_actual_tls_numeric_connect_original_host_sni_and_no_second_dns(tls_contexts,monkeypatch):
    server_ctx,client=tls_contexts
    async with own_server(server_ctx) as (port,requests,sni,_):
        ticket,policy=local_ticket(port,client);spy=BackendSpy();resolved=[]
        async def resolver(host,port):resolved.append((host,port));return ('127.0.0.1',)
        loop=asyncio.get_running_loop()
        async def unexpected_dns(*args,**kwargs):raise AssertionError('delegate resolved original host again')
        monkeypatch.setattr(loop,'getaddrinfo',unexpected_dns)
        monkeypatch.setenv('HTTPS_PROXY','http://127.0.0.1:9');monkeypatch.setenv('ALL_PROXY','http://127.0.0.1:9')
        gateway=NightAIGateway([policy],enabled=True,resolver=resolver,backend=spy)
        result=await gateway.exchange(ticket)
        assert type(result) is BoundedResponse and result.text=='safe'
        assert resolved==[('night-llm.test',port)] and [c['host'] for c in spy.calls]==['127.0.0.1']
        assert sni==['night-llm.test'] and requests[0][1][b'host']==f'night-llm.test:{port}'.encode()
        assert requests[0][1][b'authorization']==b'Bearer synthetic-secret-never-log'
        assert requests[0][0].startswith(b'POST /v1/chat/completions HTTP/1.1\r\n')
        assert json.loads(requests[0][2])['model']=='synthetic-model'
        assert (await gateway.exchange(ticket)).code=='stale' and len(requests)==1


@pytest.mark.asyncio
async def test_wrong_hostname_or_untrusted_ca_sends_no_http_or_credential(tls_contexts):
    server_ctx,client=tls_contexts
    async with own_server(server_ctx) as (port,requests,sni,_):
        for name,context in [('wrong-night.test',client),('night-llm.test',ssl.create_default_context())]:
            ticket,policy=local_ticket(port,context,host=name)
            async def resolver(host,port):return ('127.0.0.1',)
            result=await NightAIGateway([policy],enabled=True,resolver=resolver).exchange(ticket)
            assert type(result) is TransportFailure and result.code=='tls_failed'
        assert requests==[] and sni==['wrong-night.test','night-llm.test']


@pytest.mark.asyncio
@pytest.mark.parametrize('headers,reply,chunked,expected',[
    ([(b'Content-Encoding',b'gzip')],None,False,'invalid_response'),
    ([],b'x'*(256*1024+1),False,'oversize'),
    ([],b'x'*(256*1024+1),True,'oversize'),
    ([(b'X-Big',b'x'*33000)],None,False,'oversize'),
],ids=['compressed','oversize-length','oversize-chunked','oversize-headers'])
async def test_actual_socket_response_bounds(tls_contexts,headers,reply,chunked,expected):
    server_ctx,client=tls_contexts
    async with own_server(server_ctx,headers=headers,reply=reply,chunked=chunked) as (port,_,_,_):
        ticket,policy=local_ticket(port,client)
        async def resolver(host,port):return ('127.0.0.1',)
        result=await NightAIGateway([policy],enabled=True,resolver=resolver).exchange(ticket)
        assert type(result) is TransportFailure and result.code==expected


@pytest.mark.asyncio
async def test_actual_slow_trickle_cannot_extend_shared_deadline(tls_contexts):
    server_ctx,client=tls_contexts
    async with own_server(server_ctx,chunked=True,trickle_delay=.025) as (port,_,_,_):
        # Simulate the same budget after earlier work consumed11.8s, without
        # waiting12s in every test. The wire/UTC deadline is never extended.
        ticket,policy=local_ticket(port,client,clock=lambda:asyncio.get_running_loop().time()-11.8)
        async def resolver(host,port):return ('127.0.0.1',)
        started=asyncio.get_running_loop().time()
        result=await NightAIGateway([policy],enabled=True,resolver=resolver).exchange(ticket)
        assert result.code=='timeout' and asyncio.get_running_loop().time()-started<1.5


@pytest.mark.asyncio
async def test_actual_client_cancellation_closes_own_tls_request(tls_contexts):
    server_ctx,client=tls_contexts
    async with own_server(server_ctx,delay=2) as (port,requests,_,_):
        ticket,policy=local_ticket(port,client)
        async def resolver(host,port):return ('127.0.0.1',)
        task=asyncio.create_task(NightAIGateway([policy],enabled=True,resolver=resolver).exchange(ticket))
        try:
            for _ in range(100):
                if requests:break
                await asyncio.sleep(.005)
            assert len(requests)==1
            task.cancel()
            with pytest.raises(asyncio.CancelledError):await task
        finally:
            if not task.done():task.cancel();await asyncio.gather(task,return_exceptions=True)
