"""Opt-in PostgreSQL sliding quotas, independent of game transaction rollback."""
import asyncio
from dataclasses import dataclass, field
from datetime import timedelta
import hashlib
import hmac
import ipaddress
import math
import os
import time

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError

from .domain import FarmError

WINDOW_SECONDS = 60
PREFLIGHT_SECONDS = 3


class RateLimited(FarmError):
    def __init__(self, retry_after):
        super().__init__('rate_limit', 'Слишком много действий. Попробуй чуть позже.', 429)
        self.retry_after = retry_after


def unavailable():
    return FarmError('rate_unavailable', 'Защита запросов временно недоступна.', 503)


def normalized_ip(request):
    # Only the server-normalized peer. Raw forwarding headers are never credentials.
    try:
        address = ipaddress.ip_address(request.client.host)
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
            address = address.ipv4_mapped
        return str(address)
    except (ValueError, AttributeError):
        return 'unknown'


def rate_table(metadata):
    if 'farm_rate_buckets' in metadata.tables:
        return metadata.tables['farm_rate_buckets']
    table = sa.Table('farm_rate_buckets', metadata,
        sa.Column('scope', sa.String(16), primary_key=True),
        sa.Column('subject', sa.String(64), primary_key=True),
        sa.Column('timestamps', sa.JSON, nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("scope IN ('ip_read','ip_write','account_read','account_write')",
                           name='ck_farm_rate_scope'))
    sa.Index('ix_farm_rate_expiry', table.c.expires_at)
    return table


@dataclass(frozen=True)
class RateSettings:
    secret: str = field(repr=False)
    ip_read: int = 1200
    ip_write: int = 400
    account_read: int = 480
    account_write: int = 180

    def __post_init__(self):
        if len(self.secret.encode('utf-8')) < 32:
            raise ValueError('QW_FARM_RATE_SECRET must be a separate shared secret of at least 32 bytes')
        for scope in ('ip_read', 'ip_write', 'account_read', 'account_write'):
            value = getattr(self, scope)
            if type(value) is not int or not 1 <= value <= 10000:
                raise ValueError(f'Invalid Farm rate limit: {scope}')

    @classmethod
    def from_env(cls):
        defaults = {'ip_read': 1200, 'ip_write': 400, 'account_read': 480, 'account_write': 180}
        return cls(os.getenv('QW_FARM_RATE_SECRET', ''), **{
            scope: int(os.getenv('QW_FARM_RATE_' + scope.upper(), str(value)))
            for scope, value in defaults.items()})


class SharedRateLimits:
    def __init__(self, database, table, settings):
        self.database, self.table, self.settings = database, table, settings
        self.next_cleanup = 0

    def subject(self, scope, value):
        return hmac.new(self.settings.secret.encode('utf-8'),
                        f'{scope}:{value}'.encode('utf-8'), hashlib.sha256).hexdigest()

    async def check_schema(self):
        # Startup never creates tables; a missing migration must stop shared mode.
        try:
            async with asyncio.timeout(PREFLIGHT_SECONDS):
                async with self.database.transaction() as session:
                    if session.get_bind().dialect.name != 'postgresql':
                        raise RuntimeError('Shared Farm quotas require PostgreSQL')
                    await session.execute(sa.select(self.table).limit(0))
        except (SQLAlchemyError, OSError, TimeoutError):
            raise RuntimeError('Shared Farm quota schema is unavailable; apply qw_farm_011 first') from None

    async def cleanup_in(self, session):
        # Opportunistic TTL maintenance, at most 100 rows per process per minute.
        # SKIP LOCKED never waits on another request's active bucket.
        now = time.monotonic()
        if now < self.next_cleanup:
            return
        self.next_cleanup = now + WINDOW_SECONDS
        table = self.table
        # A bound cutoff permits an expiry-index range scan; volatile
        # clock_timestamp() directly in the predicate cannot serve as that bound.
        cutoff = await session.scalar(sa.select(sa.func.clock_timestamp()))
        expired = sa.select(table.c.scope, table.c.subject).where(
            table.c.expires_at <= cutoff).order_by(
                table.c.expires_at, table.c.scope, table.c.subject).limit(100).with_for_update(
                    skip_locked=True).cte('expired_farm_rates')
        await session.execute(sa.delete(table).where(
            table.c.scope == expired.c.scope, table.c.subject == expired.c.subject))

    async def consume_in(self, session, scope, value):
        table = self.table
        subject = self.subject(scope, value)
        predicate = sa.and_(table.c.scope == scope, table.c.subject == subject)
        statement = insert(table).values(scope=scope, subject=subject, timestamps=[],
            expires_at=sa.func.clock_timestamp())
        # A no-op conflict update holds the existing row before the next SELECT.
        # DO NOTHING would let concurrent TTL cleanup delete an expired bucket
        # between statements. Never reset timestamps/expiry on conflict.
        await session.execute(statement.on_conflict_do_update(
            index_elements=[table.c.scope, table.c.subject],
            set_={'subject': statement.excluded.subject}))
        row = (await session.execute(sa.select(table).where(predicate).with_for_update())).mappings().one()
        # Read DB time AFTER the lock wait, so independent workers never disagree.
        now = await session.scalar(sa.select(sa.func.clock_timestamp()))
        stamp = now.timestamp()
        recent = [item for item in row['timestamps'] if item > stamp - WINDOW_SECONDS]
        if len(recent) >= getattr(self.settings, scope):
            raise RateLimited(max(1, math.ceil(recent[0] + WINDOW_SECONDS - stamp)))
        recent.append(stamp)
        await session.execute(sa.update(table).where(predicate).values(
            timestamps=recent, expires_at=now + timedelta(seconds=WINDOW_SECONDS)))

    async def ingress(self, request):
        scope = 'ip_read' if request.method in {'GET', 'HEAD'} else 'ip_write'
        rejected = None
        try:
            async with asyncio.timeout(PREFLIGHT_SECONDS):
                async with self.database.transaction() as session:
                    await self.cleanup_in(session)
                    try:
                        await self.consume_in(session, scope, normalized_ip(request))
                    except RateLimited as error:
                        # TTL cleanup must commit even under a continuous 429 stream.
                        # Raise only after the transaction has released its connection.
                        rejected = error
        except (SQLAlchemyError, OSError, TimeoutError):
            raise unavailable() from None
        if rejected is not None:
            raise rejected
