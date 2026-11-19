"""Bounded outbound text gateway, OFF by default. No database or live wiring.

Trusted dispatch code issues tickets AFTER durable CAS/commit. These Python
types prevent accidental raw-URL use; they are not a sandbox for malicious server
code. The small backend delegates TCP/TLS to pinned httpcore/AnyIO unchanged.
"""
import asyncio
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import ipaddress
import logging
import math
import re
import socket
import ssl
import time
from types import MappingProxyType
from urllib.parse import urlsplit
from uuid import UUID

import httpcore
from httpcore._backends.anyio import AnyIOBackend

from config.night_case_ai import CLOUD_PRESETS, PRESETS, EndpointPolicy
from infrastructure.night_ai_adapters import (AdapterError, BoundedResponse, WireRequest,
    GIGA_OAUTH_ORIGIN, GIGA_SCOPES, OAuthToken, parse_inference, parse_oauth)


_AUTHORITY=object()
_TOKEN_AUTHORITY=object()
_NIGHT_HTTP_TRACE=ContextVar('night_ai_http_trace',default=False)


class _NightTraceFilter(logging.Filter):
    def filter(self,record):
        # Pinned1.0.9 Trace eagerly repr-formats provider headers/protocol errors
        # before logger.debug(). Redacting only the transport exception or a
        # trace extension is too late. Drop this request's trace at the emitting
        # logger, before ANY handler sees it; other Tasks keep their own Context.
        return not _NIGHT_HTTP_TRACE.get()


_NIGHT_TRACE_FILTER=_NightTraceFilter()
# These are the actual emitting logger names in the pinned HTTP1-only pool.
# A parent logger's filter would not filter propagated descendant records.
# Installed once at module import; no per-request global level/filter toggles.
for _logger_name in ('httpcore.connection','httpcore.http11'):
    logging.getLogger(_logger_name).addFilter(_NIGHT_TRACE_FILTER)
_V4_CLOUD_DENY=tuple(ipaddress.ip_network(x) for x in (
    '0.0.0.0/8','10.0.0.0/8','100.64.0.0/10','127.0.0.0/8','169.254.0.0/16',
    '172.16.0.0/12','192.0.0.0/24','192.0.2.0/24','192.88.99.0/24','192.168.0.0/16',
    '198.18.0.0/15','198.51.100.0/24','203.0.113.0/24','224.0.0.0/4','240.0.0.0/4'))
_COMMON_DENY=tuple(ipaddress.ip_network(x) for x in (
    '0.0.0.0/8','169.254.0.0/16','224.0.0.0/4','240.0.0.0/4','100.100.100.200/32','168.63.129.16/32',
    '::/128','::ffff:0:0/96','64:ff9b::/96','64:ff9b:1::/48','2001::/32','2002::/16',
    'fe80::/10','ff00::/8','fd00:ec2::254/128'))
_V6_CLOUD_DENY=tuple(ipaddress.ip_network(x) for x in ('2001::/23','2001:db8::/32','3fff::/20'))


def _numeric(value):
    if type(value) is not str or '%' in value:raise ValueError()
    ip=ipaddress.ip_address(value)
    if str(ip)!=value:raise ValueError()
    return ip


def _in(ip,networks):
    return any(ip.version==n.version and ip in n for n in networks)


def cloud_ip_allowed(address):
    try:
        ip=_numeric(address)
        if _in(ip,_COMMON_DENY):return False
        return not _in(ip,_V4_CLOUD_DENY) if ip.version==4 else ip in ipaddress.ip_network('2000::/3') and not _in(ip,_V6_CLOUD_DENY)
    except ValueError:return False


def _utc(value):
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset()!=timedelta(0):raise ValueError('invalid_transport_authorization')


def _origin(policy):
    value=urlsplit(policy.base_url);host=value.hostname
    if not host or not host.isascii() or host.endswith('.') or any(x in policy.base_url for x in ('%','\\','@','?','#')):
        raise ValueError('invalid_endpoint_policy')
    try:_numeric(host)
    except ValueError:
        if (':' in host or re.fullmatch(r'(?:0x[0-9a-f]+|[0-9]+)(?:\.(?:0x[0-9a-f]+|[0-9]+))*',host)
                or len(host)>253 or not all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?',part) for part in host.split('.'))):
            raise ValueError('invalid_endpoint_policy')
    if value.path and (not re.fullmatch(r'(?:/[A-Za-z0-9._~-]+)+',value.path) or any(x in {'.','..'} for x in value.path.split('/'))):
        raise ValueError('invalid_endpoint_policy')
    return value.scheme,host,value.port or (443 if value.scheme=='https' else 80),value.path


@dataclass(frozen=True,repr=False)
class OperatorPolicy:
    endpoint: EndpointPolicy
    allowed_cidrs: tuple[str,...]=()
    ssl_context: ssl.SSLContext | None=field(default=None,repr=False)

    def __post_init__(self):
        if type(self.endpoint) is not EndpointPolicy or type(self.allowed_cidrs) is not tuple:raise ValueError('invalid_endpoint_policy')
        scheme,_,_,_=_origin(self.endpoint)
        if self.endpoint.network_class=='cloud':
            if self.endpoint.base_url not in {p.base_url for p in PRESETS.values() if p.base_url}|{GIGA_OAUTH_ORIGIN} or self.allowed_cidrs:
                raise ValueError('invalid_endpoint_policy')
        elif not self.allowed_cidrs:raise ValueError('invalid_endpoint_policy')
        for cidr in self.allowed_cidrs:
            if type(cidr) is not str or str(ipaddress.ip_network(cidr,strict=True))!=cidr:raise ValueError('invalid_endpoint_policy')
        if scheme=='https' and (not isinstance(self.ssl_context,ssl.SSLContext) or
                self.ssl_context.verify_mode!=ssl.CERT_REQUIRED or not self.ssl_context.check_hostname):
            raise ValueError('invalid_endpoint_policy')

    def address_allowed(self,address):
        try:
            ip=_numeric(address)
            if _in(ip,_COMMON_DENY):return False
            return cloud_ip_allowed(address) if self.endpoint.network_class=='cloud' else _in(ip,tuple(ipaddress.ip_network(n) for n in self.allowed_cidrs))
        except ValueError:return False


@dataclass(frozen=True)
class NetworkBudget:
    permit_id: UUID
    lease_nonce: UUID
    network_deadline: datetime
    monotonic_deadline: float
    _authority: object=field(repr=False)

    def __post_init__(self):
        if self._authority is not _AUTHORITY:raise ValueError('invalid_transport_budget')

    @classmethod
    def create(cls,permit_id,lease_nonce,reserved_at,network_deadline,*,now_utc,monotonic_now):
        for value in (reserved_at,network_deadline,now_utc):_utc(value)
        if (type(permit_id) is not UUID or type(lease_nonce) is not UUID or
                network_deadline!=reserved_at+timedelta(seconds=12) or now_utc<reserved_at
                or not 0<(network_deadline-now_utc).total_seconds()<=12
                or type(monotonic_now) not in (int,float) or not math.isfinite(monotonic_now)):
            raise ValueError('invalid_transport_authorization')
        return cls(permit_id,lease_nonce,network_deadline,float(monotonic_now)+(network_deadline-now_utc).total_seconds(),_AUTHORITY)

    def remaining(self,monotonic_now):
        return max(0.,self.monotonic_deadline-monotonic_now)


@dataclass(frozen=True)
class DispatchAuthorization:
    """Trusted factory input from committed durable authorize CAS, never HTTP input."""
    permit_id: UUID
    lease_nonce: UUID
    config_hash: str
    credential_id: UUID | None
    network_deadline: datetime
    authorized_at: datetime

    def __post_init__(self):
        _utc(self.network_deadline);_utc(self.authorized_at)
        if (type(self.permit_id) is not UUID or type(self.lease_nonce) is not UUID
                or self.credential_id is not None and type(self.credential_id) is not UUID
                or type(self.config_hash) is not str or not re.fullmatch('[a-f0-9]{64}',self.config_hash)
                or not self.authorized_at<self.network_deadline<=self.authorized_at+timedelta(seconds=12)):
            raise ValueError('invalid_transport_authorization')


@dataclass(frozen=True,repr=False)
class CachedTokenRef:
    credential_id: UUID
    config_hash: str
    scope: str
    _token: OAuthToken=field(repr=False)
    _authority: object=field(repr=False)

    def __post_init__(self):
        if self._authority is not _TOKEN_AUTHORITY:raise ValueError('invalid_token_ref')

    def bytes_for_trusted_adapter(self):return self._token.token


class OAuthCache:
    def __init__(self,limit=128):
        if type(limit) is not int or not 1<=limit<=128:raise ValueError('invalid_token_cache')
        self._limit,self._items=limit,{}

    def get(self,credential_id,config_hash,scope,now):
        self._prune(now)
        return self._items.get((credential_id,config_hash,scope))

    def put(self,key,token,now):
        self._prune(now)
        if type(token) is not OAuthToken or token.expires_at<=now+timedelta(seconds=60):raise AdapterError()
        if len(self._items)>=self._limit and key not in self._items:return None
        ref=CachedTokenRef(*key,token,_TOKEN_AUTHORITY);self._items[key]=ref
        return ref

    def invalidate(self,key):self._items.pop(key,None)

    def _prune(self,now):
        _utc(now)
        self._items={key:value for key,value in self._items.items() if value._token.expires_at>now+timedelta(seconds=60)}


@dataclass(frozen=True,repr=False)
class SendTicket:
    authorization: DispatchAuthorization
    budget: NetworkBudget
    wire: WireRequest=field(repr=False)
    cache_key: tuple | None=field(repr=False)
    _authority: object=field(repr=False)

    def __post_init__(self):
        if self._authority is not _AUTHORITY:raise ValueError('invalid_send_ticket')


@dataclass(frozen=True,repr=False)
class OAuthTicket(SendTicket):pass


class TicketFactory:
    """No transaction/ACL lookup here. Only committed dispatch code may issue."""
    def issue(self,authorization,budget,wire,*,token_ref=None):
        if (type(authorization) is not DispatchAuthorization or type(budget) is not NetworkBudget or type(wire) is not WireRequest
                or (authorization.permit_id,authorization.lease_nonce,authorization.network_deadline)!=(budget.permit_id,budget.lease_nonce,budget.network_deadline)
                or authorization.config_hash!=wire.config_hash):raise ValueError('invalid_send_ticket')
        key=None
        if wire.preset=='gigachat':
            if authorization.credential_id is None or wire.oauth_scope not in GIGA_SCOPES:raise ValueError('invalid_send_ticket')
            key=(authorization.credential_id,authorization.config_hash,wire.oauth_scope)
            if wire.family!='gigachat_oauth':
                if (type(token_ref) is not CachedTokenRef or key!=(token_ref.credential_id,token_ref.config_hash,token_ref.scope)
                        or token_ref._token.expires_at<=authorization.authorized_at+timedelta(seconds=60)
                        or (b'authorization',b'Bearer '+token_ref._token.token) not in wire.headers):raise ValueError('invalid_send_ticket')
        elif token_ref is not None:raise ValueError('invalid_send_ticket')
        kind=OAuthTicket if wire.family=='gigachat_oauth' else SendTicket
        return kind(authorization,budget,wire,key,_AUTHORITY)


@dataclass(frozen=True)
class TransportFailure:
    code: str
    http_status: int | None=None
    retry_after_seconds: int | None=None


class _Denied(Exception):
    def __init__(self,code):self.code=code;super().__init__(code)


async def resolve_all(host,port):
    records=await asyncio.get_running_loop().getaddrinfo(host,port,family=socket.AF_UNSPEC,type=socket.SOCK_STREAM)
    return tuple(record[4][0] for record in records if record[0] in {socket.AF_INET,socket.AF_INET6})


class _PinnedStream:
    def __init__(self,stream,backend,*,tls=False):
        self._stream,self._backend,self._tls=stream,backend,tls
        self._read,self._written=0,0

    def _timeout(self,provided,maximum):
        left=self._backend.budget.remaining(self._backend.monotonic())
        if left<=0:raise _Denied('timeout')
        return min(maximum,left,provided if provided is not None else maximum)

    async def read(self,max_bytes,timeout=None):
        data=await self._stream.read(min(max_bytes,65536),timeout=self._timeout(timeout,5))
        self._timeout(None,5)  # A ready callback at the deadline cannot publish late bytes.
        self._read+=len(data)
        if self._read>256*1024+100*1024+65536:raise _Denied('oversize')
        return data

    async def write(self,buffer,timeout=None):
        bound=self._timeout(timeout,3)
        if self._backend.scheme=='https' and not self._tls:raise _Denied('tls_failed')
        self._written+=len(buffer)
        if self._written>65536+32768:raise _Denied('oversize')
        await self._stream.write(buffer,timeout=bound)

    async def start_tls(self,ssl_context,server_hostname=None,timeout=None):
        if (server_hostname!=self._backend.host or ssl_context is not self._backend.policy.ssl_context
                or ssl_context.verify_mode!=ssl.CERT_REQUIRED or not ssl_context.check_hostname):raise _Denied('tls_failed')
        try:
            stream=await self._stream.start_tls(ssl_context=ssl_context,server_hostname=server_hostname,timeout=self._timeout(timeout,3))
        except httpcore.ConnectTimeout:raise
        except (httpcore.ConnectError,ssl.SSLError):raise _Denied('tls_failed') from None
        return _PinnedStream(stream,self._backend,tls=True)

    async def aclose(self):await self._stream.aclose()
    def get_extra_info(self,name):return self._stream.get_extra_info(name)


class _PinnedBackend:
    def __init__(self,policy,budget,resolver,delegate,monotonic):
        self.policy,self.budget,self.resolver,self.delegate,self.monotonic=policy,budget,resolver,delegate,monotonic
        self.scheme,self.host,self.port,_=_origin(policy.endpoint)
        self._connected=False

    async def connect_tcp(self,host,port,timeout=None,local_address=None,socket_options=None):
        if self._connected or host!=self.host or port!=self.port or local_address is not None or socket_options:
            raise _Denied('endpoint_denied')
        self._connected=True
        left=self.budget.remaining(self.monotonic())
        if left<=0:raise _Denied('timeout')
        try:
            async with asyncio.timeout(min(3,left)):
                addresses=await self.resolver(host,port)
        except (OSError,ValueError):raise _Denied('dns_failed') from None
        if type(addresses) not in (tuple,list) or not all(type(x) is str for x in addresses):raise _Denied('dns_failed')
        unique=set(addresses)
        if not 1<=len(unique)<=32 or not all(self.policy.address_allowed(x) for x in unique):raise _Denied('endpoint_denied')
        chosen=min(unique,key=lambda x:(_numeric(x).version,int(_numeric(x))))
        left=self.budget.remaining(self.monotonic())
        if left<=0:raise _Denied('timeout')
        stream=await self.delegate.connect_tcp(host=chosen,port=port,timeout=min(3,left,timeout if timeout is not None else 3),local_address=None,socket_options=None)
        peer=stream.get_extra_info('server_addr')
        if peer is not None and (type(peer) is not tuple or len(peer)<2 or peer[0]!=chosen or peer[1]!=port):
            await stream.aclose();raise _Denied('endpoint_denied')
        return _PinnedStream(stream,self)

    async def connect_unix_socket(self,*args,**kwargs):raise _Denied('endpoint_denied')
    async def sleep(self,*args,**kwargs):raise _Denied('network_error')


def _tls_error(error,depth=0):
    if depth>8 or error is None:return False
    return isinstance(error,ssl.SSLError) or _tls_error(error.__cause__,depth+1) or any(_tls_error(e,depth+1) for e in getattr(error,'exceptions',()))


class NightAIGateway:
    def __init__(self,policies,*,enabled=False,external_allowed=False,resolver=resolve_all,backend=None,
                 monotonic=time.monotonic,utcnow=lambda:datetime.now(timezone.utc),oauth_cache=None):
        if type(enabled) is not bool or type(external_allowed) is not bool:raise ValueError('invalid_transport_flags')
        values={}
        for policy in policies:
            if type(policy) is not OperatorPolicy:raise ValueError('invalid_endpoint_policy')
            key=(policy.endpoint.policy_id,policy.endpoint.policy_version)
            if key in values:raise ValueError('invalid_endpoint_policy')
            values[key]=policy
        self._policies=MappingProxyType(values)
        self.enabled,self.external_allowed=enabled,external_allowed
        self.resolver,self.backend,self.monotonic,self.utcnow=resolver,backend or AnyIOBackend(),monotonic,utcnow
        self.oauth_cache=oauth_cache or OAuthCache()
        self._used={}

    async def exchange(self,ticket):
        if type(ticket) not in {SendTicket,OAuthTicket} or ticket._authority is not _AUTHORITY:
            raise ValueError('invalid_send_ticket')
        now=self.monotonic();left=ticket.budget.remaining(now)
        if left<=0:return TransportFailure('timeout')
        self._used={key:end for key,end in self._used.items() if end>now}
        key=(ticket.authorization.permit_id,ticket.authorization.lease_nonce,type(ticket))
        if key in self._used:return TransportFailure('stale')
        if len(self._used)>=4096:return TransportFailure('binding_busy')
        self._used[key]=ticket.budget.monotonic_deadline
        if not self.enabled:return TransportFailure('disabled')
        wire=ticket.wire
        policy=self._policies.get((wire.policy_id,wire.policy_version))
        if policy is None or policy.endpoint.base_url!=wire.base_url:return TransportFailure('endpoint_denied')
        if policy.endpoint.network_class=='cloud' and not self.external_allowed:return TransportFailure('disabled')
        if wire.preset in CLOUD_PRESETS and policy.endpoint.network_class!='cloud':return TransportFailure('endpoint_denied')
        if type(ticket) is OAuthTicket and (wire.base_url!=GIGA_OAUTH_ORIGIN or wire.path_suffix!='/api/v2/oauth'):
            return TransportFailure('endpoint_denied')
        if len(wire.body)>(16384 if type(ticket) is OAuthTicket else 65536):return TransportFailure('oversize')
        trace_scope=_NIGHT_HTTP_TRACE.set(True)
        try:
            async with asyncio.timeout(left):return await self._exchange(ticket,policy)
        except _Denied as error:return TransportFailure(error.code)
        except AdapterError as error:return TransportFailure(error.code)
        except (TimeoutError,httpcore.TimeoutException):return TransportFailure('timeout')
        except httpcore.ConnectError as error:return TransportFailure('tls_failed' if _tls_error(error) else 'network_error')
        except (httpcore.NetworkError,httpcore.ProtocolError,OSError):return TransportFailure('network_error')
        finally:
            # Includes pool/stream cleanup logs and restores caller scope after
            # success, protocol error, timeout or external cancellation.
            _NIGHT_HTTP_TRACE.reset(trace_scope)

    async def _exchange(self,ticket,policy):
        wire=ticket.wire;scheme,host,port,_=_origin(policy.endpoint)
        host_header=('['+host+']' if ':' in host else host)+((':'+str(port)) if port!=(443 if scheme=='https' else 80) else '')
        headers=[(b'host',host_header.encode('ascii')),(b'accept-encoding',b'identity'),(b'connection',b'close'),*wire.headers]
        if len(headers)>128 or sum(len(k)+len(v)+4 for k,v in headers)>32768:raise _Denied('oversize')
        backend=_PinnedBackend(policy,ticket.budget,self.resolver,self.backend,self.monotonic)
        async with httpcore.AsyncConnectionPool(ssl_context=policy.ssl_context,proxy=None,max_connections=1,max_keepalive_connections=0,
                http1=True,http2=False,retries=0,uds=None,network_backend=backend) as pool:
            async with pool.stream('POST',wire.base_url+wire.path_suffix,headers=headers,content=wire.body,
                    extensions={'timeout':{'connect':3.,'read':5.,'write':3.,'pool':1.}}) as response:
                raw_headers=response.headers
                if len(raw_headers)>128 or sum(len(k)+len(v)+4 for k,v in raw_headers)>32768:raise _Denied('oversize')
                header_map={}
                for k,v in raw_headers:header_map.setdefault(k.lower(),[]).append(v)
                if any(v.lower()!=b'identity' for v in header_map.get(b'content-encoding',[])):raise _Denied('invalid_response')
                if 300<=response.status<400:return TransportFailure('endpoint_denied',response.status)
                if response.status in {401,403}:
                    if ticket.cache_key is not None and type(ticket) is SendTicket:self.oauth_cache.invalidate(ticket.cache_key)
                    return TransportFailure('auth_error',response.status)
                if response.status==429 or 500<=response.status<=599:
                    retry=header_map.get(b'retry-after',[])
                    wait=min(30,max(1,int(retry[0]))) if len(retry)==1 and re.fullmatch(rb'[0-9]{1,9}',retry[0]) else 2
                    return TransportFailure('rate_limited' if response.status==429 else 'provider_error',response.status,wait)
                if response.status!=200:return TransportFailure('config_error' if response.status in {400,404,422} else 'invalid_response',response.status)
                limit=16384 if type(ticket) is OAuthTicket else 256*1024
                lengths=header_map.get(b'content-length',[])
                if lengths and (len(lengths)!=1 or not re.fullmatch(rb'[0-9]{1,9}',lengths[0]) or int(lengths[0])>limit):raise _Denied('oversize')
                chunks=[];total=0
                async for data in response.aiter_stream():
                    total+=len(data)
                    if total>limit:raise _Denied('oversize')
                    chunks.append(data)
                raw=b''.join(chunks)
                if type(ticket) is OAuthTicket:
                    token=parse_oauth(raw,self.utcnow())
                    ref=self.oauth_cache.put(ticket.cache_key,token,self.utcnow())
                    return ref if ref is not None else TransportFailure('binding_busy')
                return parse_inference(wire.family,raw)
