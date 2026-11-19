"""Bounded loopback API/PG readiness probe; no proxies, redirects or game locks."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import re
from urllib.parse import urlsplit


def validate_readiness_url(url):
    p = urlsplit(url)
    if p.scheme != 'http' or p.hostname not in {'127.0.0.1', 'localhost', '::1'} or p.path != '/healthz' or p.query or p.fragment or p.username or p.password:
        raise ValueError('Night Case readiness must use loopback HTTP /healthz')
    port = p.port or 80
    if not 1 <= port <= 65535: raise ValueError('invalid readiness port')
    return p


def readiness_token(secret: bytes) -> str:
    if type(secret) is not bytes or len(secret) < 32:
        raise ValueError('Night Case readiness secret must contain at least 32 bytes')
    return hmac.new(secret, b'night-case-readiness/1', hashlib.sha256).hexdigest()


async def readiness_probe(url, *, timeout=3.0, token=None):
    p = validate_readiness_url(url)
    if not 0 < timeout <= 3: raise ValueError('readiness timeout must be at most 3 seconds')
    if token is not None and (type(token) is not str or re.fullmatch(r'[0-9a-f]{64}', token) is None):
        raise ValueError('invalid Night Case readiness token')
    cleanup_budget = min(0.5, timeout / 4)
    async def request():
        writer = None
        try:
            reader, writer = await asyncio.open_connection(p.hostname, p.port or 80, limit=8192)
            auth = '' if token is None else 'X-Night-Readiness: ' + token + '\r\n'
            writer.write(('GET /healthz HTTP/1.1\r\nHost: ' + p.netloc + '\r\n' + auth + 'Connection: close\r\n\r\n').encode('ascii'))
            await writer.drain()
            headers = await reader.readuntil(b'\r\n\r\n')
            if len(headers) > 8192 or headers.split(b'\r\n', 1)[0].split()[1:2] != [b'200']: return False
            header_map = {}
            for line in headers.split(b'\r\n')[1:]:
                if b':' in line:
                    key, value = line.split(b':', 1)
                    header_map[key.strip().lower()] = value.strip()
            length = int(header_map.get(b'content-length', b'4097'))
            if not 1 <= length <= 4096 or b'transfer-encoding' in header_map: return False
            body = await reader.readexactly(length)
            payload = json.loads(body)
            return type(payload) is dict and payload.get('status') == 'ok'
        finally:
            if writer is not None:
                writer.close()
                try: await asyncio.wait_for(writer.wait_closed(), timeout=cleanup_budget)
                except (OSError, TimeoutError): pass
    try:
        return await asyncio.wait_for(request(), timeout=timeout - cleanup_budget)
    except (OSError, TimeoutError, ValueError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
        return False
