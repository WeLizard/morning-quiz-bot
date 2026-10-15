"""Small PostgreSQL aggregate store with receipts and an append-only economic ledger.

The SQLite backend is ONLY the downloadable local demo/test harness. The
integrated game uses the host's AsyncSession and PostgreSQL transaction.
"""
from __future__ import annotations
import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from uuid import UUID, uuid4
from hashlib import sha256
import sqlalchemy as sa
from .domain import FarmError, need


def tables(metadata: sa.MetaData):
    if 'farm_states' in metadata.tables:
        return {name:metadata.tables['farm_'+name] for name in ['states','receipts','ledger','village','invites','neighbor_pairs']}
    states=sa.Table('farm_states',metadata,
        sa.Column('id',sa.Uuid,primary_key=True),
        sa.Column('account_id',sa.Uuid,sa.ForeignKey('accounts.id',ondelete='RESTRICT'),nullable=False,unique=True),
        sa.Column('name',sa.String(28),nullable=False),
        sa.Column('coins',sa.BigInteger,nullable=False),sa.Column('xp',sa.BigInteger,nullable=False),
        sa.Column('revision',sa.Integer,nullable=False),sa.Column('visibility',sa.String(10),nullable=False),
        sa.Column('payload',sa.JSON,nullable=False),
        sa.CheckConstraint('coins >= 0 AND coins <= 1000000000000',name='ck_farm_coins'),
        sa.CheckConstraint('xp >= 0',name='ck_farm_xp'),
        sa.CheckConstraint('revision >= 0',name='ck_farm_revision'),
        sa.CheckConstraint("visibility IN ('private','friends','public')",name='ck_farm_visibility'))
    receipts=sa.Table('farm_receipts',metadata,
        sa.Column('account_id',sa.Uuid,sa.ForeignKey('accounts.id',ondelete='RESTRICT'),primary_key=True),
        sa.Column('command_id',sa.String(64),primary_key=True),
        sa.Column('fingerprint',sa.String(64),nullable=False),
        sa.Column('result',sa.JSON,nullable=False),sa.Column('created_at',sa.Float,nullable=False))
    ledger=sa.Table('farm_ledger',metadata,
        sa.Column('id',sa.Uuid,primary_key=True),
        sa.Column('farm_id',sa.Uuid,sa.ForeignKey('farm_states.id',ondelete='RESTRICT'),nullable=False),
        sa.Column('actor_account_id',sa.Uuid,sa.ForeignKey('accounts.id',ondelete='RESTRICT'),nullable=False),
        sa.Column('command_id',sa.String(64),nullable=False),
        sa.Column('kind',sa.String(32),nullable=False),sa.Column('coins_delta',sa.BigInteger,nullable=False),
        sa.Column('coins_after',sa.BigInteger,nullable=False),sa.Column('inventory_delta',sa.JSON,nullable=False),
        sa.Column('xp_delta',sa.BigInteger,nullable=False),sa.Column('created_at',sa.Float,nullable=False),
        sa.UniqueConstraint('farm_id','actor_account_id','command_id',name='uq_farm_ledger_command'))
    village=sa.Table('farm_village',metadata,
        sa.Column('season',sa.Integer,primary_key=True),
        sa.Column('total',sa.BigInteger,nullable=False,server_default='0'),
        sa.Column('goal',sa.BigInteger,nullable=False),sa.Column('created_at',sa.Float,nullable=False),
        sa.CheckConstraint('total >= 0 AND goal > 0',name='ck_farm_village_amounts'))
    invites=sa.Table('farm_invites',metadata,
        sa.Column('invitee_farm_id',sa.Uuid,sa.ForeignKey('farm_states.id',ondelete='RESTRICT'),primary_key=True),
        sa.Column('inviter_farm_id',sa.Uuid,sa.ForeignKey('farm_states.id',ondelete='RESTRICT'),nullable=False),
        sa.Column('created_at',sa.Float,nullable=False),sa.Column('rewarded_at',sa.Float,nullable=True),
        sa.CheckConstraint('inviter_farm_id <> invitee_farm_id',name='ck_farm_invites_not_self'))
    sa.Index('ix_farm_invites_inviter',invites.c.inviter_farm_id)
    neighbor_pairs=sa.Table('farm_neighbor_pairs',metadata,
        sa.Column('farm_low_id',sa.Uuid,sa.ForeignKey('farm_states.id',ondelete='RESTRICT'),primary_key=True),
        sa.Column('farm_high_id',sa.Uuid,sa.ForeignKey('farm_states.id',ondelete='RESTRICT'),primary_key=True),
        sa.Column('created_at',sa.Float,nullable=False),
        sa.CheckConstraint('farm_low_id <> farm_high_id',name='ck_farm_neighbor_pairs_distinct'))
    sa.Index('ix_farm_ledger_history',ledger.c.farm_id,ledger.c.created_at)
    sa.Index('ix_farm_states_public',states.c.visibility,states.c.name)
    return dict(states=states,receipts=receipts,ledger=ledger,village=village,invites=invites,neighbor_pairs=neighbor_pairs)


def unpack(row):
    if row is None:return None
    value=deepcopy(row['payload'])
    value.update(id=str(row['id']),coins=row['coins'],xp=row['xp'],revision=row['revision'],name=row['name'])
    return value


class Unit:
    def __init__(self, connection, schema, *, asynchronous=True, dialect='postgresql'):
        self.connection,self.t,self.asynchronous,self.dialect=connection,schema,asynchronous,dialect

    async def execute(self, statement, parameters=None):
        result=self.connection.execute(statement,parameters or {})
        return await result if self.asynchronous else result

    async def lock(self, *keys):
        if self.dialect=='postgresql':
            for key in sorted(set(keys)):
                await self.execute(sa.text('SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))'),{'k':'qw-farm:'+key})

    async def by_account(self, account_id):
        t=self.t['states']
        row=(await self.execute(sa.select(t).where(t.c.account_id==UUID(str(account_id))))).mappings().first()
        return unpack(row)

    async def get(self, farm_id):
        t=self.t['states']
        try:uid=UUID(str(farm_id))
        except (ValueError,TypeError,AttributeError):raise FarmError('not_found','Ферма не найдена.',404)
        statement=sa.select(t).where(t.c.id==uid)
        accounts=t.metadata.tables['accounts']
        if 'archived' in accounts.c and 'bot_blocked' in accounts.c:
            statement=statement.join(accounts,t.c.account_id==accounts.c.id).where(accounts.c.archived.is_(False),accounts.c.bot_blocked.is_(False))
        row=(await self.execute(statement)).mappings().first()
        return unpack(row)

    async def owner_account(self, farm_id):
        t=self.t['states']
        result=await self.execute(sa.select(t.c.account_id).where(t.c.id==UUID(str(farm_id))))
        return str(result.scalar_one())

    async def save(self, farm, account_id=None):
        t=self.t['states']; payload=deepcopy(farm)
        for k in ['id','name','coins','xp','revision']:payload.pop(k,None)
        values=dict(name=farm['name'],coins=farm['coins'],xp=farm['xp'],revision=farm['revision'],
                    visibility=farm['settings']['visibility'],payload=payload)
        if account_id is not None:
            await self.execute(sa.insert(t).values(id=UUID(farm['id']),account_id=UUID(str(account_id)),**values))
        else:await self.execute(sa.update(t).where(t.c.id==UUID(farm['id'])).values(**values))

    async def receipt(self, account_id, key):
        t=self.t['receipts']
        return (await self.execute(sa.select(t).where(t.c.account_id==UUID(str(account_id)),t.c.command_id==key))).mappings().first()

    async def remember(self, account_id, key, fingerprint, result, now):
        await self.execute(sa.insert(self.t['receipts']).values(account_id=UUID(str(account_id)),command_id=key,
            fingerprint=fingerprint,result=result,created_at=now))

    async def record(self, actor, key, kind, before, after, now):
        old=before or {'coins':0,'xp':0,'inventory':{}}
        delta={k:after['inventory'].get(k,0)-old['inventory'].get(k,0) for k in set(old['inventory'])|set(after['inventory'])}
        delta={k:q for k,q in delta.items() if q}
        await self.execute(sa.insert(self.t['ledger']).values(id=uuid4(),farm_id=UUID(after['id']),actor_account_id=UUID(str(actor)),
             command_id=key,kind=kind,coins_delta=after['coins']-old['coins'],coins_after=after['coins'],
             xp_delta=after['xp']-old['xp'],inventory_delta=delta,created_at=now))

    async def history(self, farm_id):
        t=self.t['ledger']
        rows=(await self.execute(sa.select(t).where(t.c.farm_id==UUID(farm_id)).order_by(t.c.created_at.desc(),t.c.id).limit(80))).mappings().all()
        return [{k:r[k] for k in ['kind','coins_delta','coins_after','inventory_delta','xp_delta','created_at']} for r in rows]

    # ---- r9 stage 14: the shared village counter (one row per season). Never touches farm rows or farm locks.
    async def village_peek(self, season):
        t=self.t['village']
        row=(await self.execute(sa.select(t).where(t.c.season==season))).mappings().first()
        return dict(season=row['season'],total=row['total'],goal=row['goal']) if row else None

    async def village_goal(self, now):
        """Season goal: 3 reference days of income of every ACTIVE farm that can join the fund (never below the floor)."""
        from . import economy
        from .catalog import FUND_LEVEL, LEVELS, VILLAGE_GOAL_FLOOR, VILLAGE_ACTIVE_DAYS, level, income_ref
        t=self.t['states']
        since=economy.moscow_day(now)-VILLAGE_ACTIVE_DAYS
        rows=(await self.execute(sa.select(t.c.xp).where(t.c.xp>=LEVELS[FUND_LEVEL-1],
              t.c.payload['progress']['last'].as_integer()>=since).limit(20000))).all()
        return max(VILLAGE_GOAL_FLOOR,sum(economy.goal_share(income_ref(level(r[0]))) for r in rows))

    async def village_add(self, season, value, now):
        """Atomic ``total = total + :v``; the row is created once (ON CONFLICT DO NOTHING), then only incremented."""
        t=self.t['village']
        if self.dialect=='postgresql':
            from sqlalchemy.dialects.postgresql import insert
        else:
            from sqlalchemy.dialects.sqlite import insert
        if await self.village_peek(season) is None:
            goal=await self.village_goal(now)
            await self.execute(insert(t).values(season=season,total=0,goal=goal,created_at=now).on_conflict_do_nothing(index_elements=['season']))
        row=(await self.execute(sa.update(t).where(t.c.season==season).values(total=t.c.total+value).returning(t.c.total,t.c.goal))).first()
        return dict(season=season,total=row[0],goal=row[1])

    # ---- invitations: who brought whom. One row per invited farm (primary key) = at most one reward per invited farm.
    async def invite_add(self, invitee_id, inviter_id, now):
        """True only for the call that created the link (ON CONFLICT DO NOTHING on the invitee's primary key)."""
        t=self.t['invites']
        if self.dialect=='postgresql':
            from sqlalchemy.dialects.postgresql import insert
        else:
            from sqlalchemy.dialects.sqlite import insert
        result=await self.execute(insert(t).values(invitee_farm_id=UUID(str(invitee_id)),inviter_farm_id=UUID(str(inviter_id)),
            created_at=now).on_conflict_do_nothing(index_elements=['invitee_farm_id']))
        return result.rowcount==1

    async def invite_of(self, invitee_id):
        t=self.t['invites']
        row=(await self.execute(sa.select(t.c.inviter_farm_id).where(t.c.invitee_farm_id==UUID(str(invitee_id))))).first()
        return str(row[0]) if row else None

    async def invite_list(self, inviter_id):
        """The farms this farm invited (newest first, at most 40) with the invitee's name and XP."""
        t,s=self.t['invites'],self.t['states']
        rows=(await self.execute(sa.select(t.c.invitee_farm_id,t.c.rewarded_at,s.c.name,s.c.xp).join(s,s.c.id==t.c.invitee_farm_id)
            .where(t.c.inviter_farm_id==UUID(str(inviter_id))).order_by(t.c.created_at.desc(),t.c.invitee_farm_id).limit(40))).all()
        return [dict(id=str(r[0]),rewarded_at=r[1],name=r[2],xp=r[3]) for r in rows]

    async def invite_mark(self, invitee_id, now):
        """Atomically claim the reward of one invited farm: True exactly once."""
        t=self.t['invites']
        result=await self.execute(sa.update(t).where(t.c.invitee_farm_id==UUID(str(invitee_id)),t.c.rewarded_at.is_(None)).values(rewarded_at=now))
        return result.rowcount==1

    # ---- neighbourhood reward: one row per UNORDERED pair, kept for good even after the neighbours part.
    async def neighbor_pairs_paid(self, farm_id):
        """IDs of farms whose one-time neighbour reward was already paid with this farm."""
        t=self.t['neighbor_pairs'];uid=UUID(str(farm_id))
        rows=(await self.execute(sa.select(t.c.farm_low_id,t.c.farm_high_id).where(
            sa.or_(t.c.farm_low_id==uid,t.c.farm_high_id==uid)))).all()
        return {str(high if low==uid else low) for low,high in rows}

    async def neighbor_pair_claim(self, a, b, now):
        """True only for the call that recorded the pair for the first time (ON CONFLICT DO NOTHING on the pair key)."""
        t=self.t['neighbor_pairs']
        if self.dialect=='postgresql':
            from sqlalchemy.dialects.postgresql import insert
        else:
            from sqlalchemy.dialects.sqlite import insert
        low,high=sorted((UUID(str(a)),UUID(str(b))))
        result=await self.execute(insert(t).values(farm_low_id=low,farm_high_id=high,created_at=now)
            .on_conflict_do_nothing(index_elements=['farm_low_id','farm_high_id']))
        return result.rowcount==1

    async def public_farms(self):
        t=self.t['states']
        statement=sa.select(t).where(t.c.visibility=='public')
        accounts=t.metadata.tables['accounts']
        if 'archived' in accounts.c and 'bot_blocked' in accounts.c:
            statement=statement.join(accounts,t.c.account_id==accounts.c.id).where(accounts.c.archived.is_(False),accounts.c.bot_blocked.is_(False))
        rows=(await self.execute(statement.order_by(t.c.name,t.c.id).limit(50))).mappings().all()
        return [unpack(r) for r in rows]


class DemoDatabase:
    """Local-only database; serialized SQLite writes, never used by the QW adapter."""
    def __init__(self, path):
        self.engine=sa.create_engine('sqlite:///'+str(path),connect_args={'check_same_thread':False,'timeout':10})
        @sa.event.listens_for(self.engine,'connect')
        def configure(dbapi_connection, _):
            dbapi_connection.execute('PRAGMA foreign_keys=ON')
            dbapi_connection.execute('PRAGMA journal_mode=WAL')
        self.metadata=sa.MetaData()
        self.accounts=sa.Table('accounts',self.metadata,sa.Column('id',sa.Uuid,primary_key=True),
           sa.Column('name',sa.String(28),nullable=False),sa.Column('recovery_hash',sa.String(64),nullable=False,unique=True))
        self.sessions=sa.Table('demo_sessions',self.metadata,sa.Column('digest',sa.String(64),primary_key=True),
           sa.Column('account_id',sa.Uuid,sa.ForeignKey('accounts.id'),nullable=False),sa.Column('expires',sa.Float,nullable=False))
        self.schema=tables(self.metadata)
        self.metadata.create_all(self.engine)
        self.mutex=asyncio.Lock()

    @asynccontextmanager
    async def transaction(self):
        async with self.mutex:
            connection=self.engine.connect()
            try:
                connection.execute(sa.text('BEGIN IMMEDIATE'))
                yield Unit(connection,self.schema,asynchronous=False,dialect='sqlite')
                connection.commit()
            except BaseException:
                connection.rollback();raise
            finally:connection.close()
