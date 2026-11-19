"""Caller-transaction dispatch primitives. No ACL decisions, commits or network I/O.

Caller acquires fence/ACL/replay, AI config advisory, Game/sealed/control, binding,
profile/revision/credential, source, then these sorted budget rows. Any exception
requires rollback of the caller transaction. A reservation is NOT a send ticket.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
import re
from uuid import UUID

from sqlalchemy import null, select, update
from sqlalchemy.dialects.postgresql import insert

from storage.models import Game, NightNarratorLimit, NightRenderJob, NightRendering
from storage.night_ai_models import (NightAIBinding, NightAIDispatchAttempt, NightAIProfileRevision,
    NightAICredential, NightAIGameControl, NightAIIntentRequest, NightAIRequest)


ACTIVE = frozenset({'reserved', 'sending'})
TERMINAL = frozenset({'succeeded', 'failed', 'cancelled', 'expired'})
ERRORS = frozenset({'disabled','stale','expired','acl_denied','quota_exhausted','binding_busy',
    'circuit_open','credential_unavailable','endpoint_denied','dns_failed','tls_failed','timeout',
    'network_error','rate_limited','provider_error','auth_error','config_error','oversize','invalid_response','source_closed'})
HASH = re.compile(r'[a-f0-9]{64}\Z')
TRANSIENT_ERRORS = frozenset({'timeout','network_error','rate_limited','provider_error'})


class DispatchConflict(ValueError):
    """Sanitized storage failure; the application chooses source fallback/retry."""


def _instant(value):
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError('night_dispatch_invalid')


def _integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError('night_dispatch_invalid')


@dataclass(frozen=True)
class DispatchSource:
    kind: str
    id: UUID | str

    def __post_init__(self):
        if not ((self.kind == 'intent' and type(self.id) is UUID) or
                (self.kind == 'render' and type(self.id) is str and re.fullmatch(r'[A-Za-z0-9_.:-]{1,96}', self.id))):
            raise ValueError('night_dispatch_source_invalid')


@dataclass(frozen=True)
class QuotaDebit:
    scope: str
    period_start: datetime
    requests: int
    tokens: int
    max_requests: int
    max_tokens: int

    def __post_init__(self):
        if type(self.scope) is not str or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', self.scope):
            raise ValueError('night_dispatch_quota_invalid')
        _instant(self.period_start)
        _integer(self.requests, 1, 1)
        _integer(self.tokens, 1, 2**63-1)
        _integer(self.max_requests, 1, 2**31-1)
        _integer(self.max_tokens, 1, 2**63-1)

    def document(self):
        return {'scope':self.scope, 'period_start':self.period_start.isoformat(),
                'requests':self.requests, 'tokens':self.tokens}


@dataclass(frozen=True)
class ReserveSpec:
    id: UUID
    source: DispatchSource
    game_id: str
    binding_id: UUID
    epoch: int
    attempt_no: int
    config_hash: str
    caps_hash: str
    payload_hash: str
    source_expires_at: datetime
    worker_id: str
    lease_nonce: UUID
    reserved_at: datetime
    lease_until: datetime
    network_deadline: datetime
    reserved_input_units: int
    reserved_output_tokens: int
    quota_debits: tuple[QuotaDebit, ...]

    def __post_init__(self):
        if (any(type(x) is not UUID for x in (self.id,self.binding_id,self.lease_nonce))
                or type(self.source) is not DispatchSource
                or type(self.game_id) is not str or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,64}', self.game_id)
                or type(self.worker_id) is not str or not re.fullmatch(r'[!-~]{1,96}', self.worker_id)
                or any(type(x) is not str or not HASH.fullmatch(x) for x in (self.config_hash,self.caps_hash,self.payload_hash))):
            raise ValueError('night_dispatch_invalid')
        for value in (self.reserved_at,self.source_expires_at,self.lease_until,self.network_deadline): _instant(value)
        _integer(self.epoch,1,2**31-1)
        _integer(self.attempt_no,1,2)
        _integer(self.reserved_input_units,0,2**63-801)
        _integer(self.reserved_output_tokens,1,800)
        if not (self.network_deadline == self.reserved_at+timedelta(seconds=12)
                and self.network_deadline <= self.lease_until <= min(self.reserved_at+timedelta(seconds=30),self.source_expires_at)):
            raise ValueError('night_dispatch_deadline_invalid')
        if (type(self.quota_debits) is not tuple or len(self.quota_debits)!=4
                or any(type(x) is not QuotaDebit for x in self.quota_debits)
                or len({(x.scope,x.period_start) for x in self.quota_debits})!=4
                or any(x.tokens != self.reserved_input_units+self.reserved_output_tokens for x in self.quota_debits)):
            raise ValueError('night_dispatch_quota_invalid')
        expected={'nai:global:minute',f'game:{self.game_id}:day',f'game:{self.game_id}:total'}
        scopes={x.scope for x in self.quota_debits}
        if not expected < scopes or len(scopes-expected)!=1:
            raise ValueError('night_dispatch_quota_invalid')
        actor=next(iter(scopes-expected))
        if not re.fullmatch(r'nai:actor:[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}:minute',actor):
            raise ValueError('night_dispatch_quota_invalid')


class NightAIDispatchRepository:
    def __init__(self, session):
        self.session=session

    async def attempt(self, permit_id, *, lock=False):
        query=select(NightAIDispatchAttempt).where(NightAIDispatchAttempt.id==permit_id).execution_options(populate_existing=True)
        return await self.session.scalar(query.with_for_update() if lock else query)

    async def source_attempts(self, source, *, lock=False):
        if type(source) is not DispatchSource: raise ValueError('night_dispatch_source_invalid')
        column=NightAIDispatchAttempt.intent_id if source.kind=='intent' else NightAIDispatchAttempt.job_id
        query=select(NightAIDispatchAttempt).where(column==source.id).order_by(NightAIDispatchAttempt.attempt_no).execution_options(populate_existing=True)
        return list((await self.session.scalars(query.with_for_update() if lock else query)).all())

    async def reserve(self, spec: ReserveSpec):
        if type(spec) is not ReserveSpec: raise ValueError('night_dispatch_invalid')
        binding=await self.session.scalar(select(NightAIBinding).where(NightAIBinding.id==spec.binding_id).with_for_update().execution_options(populate_existing=True))
        if binding is None or binding.status!='active' or binding.inflight_permit_id is not None:
            raise DispatchConflict('binding_busy')
        source_job=None
        if spec.source.kind=='render':
            source_job=await self.session.scalar(select(NightRenderJob).where(NightRenderJob.job_id==spec.source.id).with_for_update().execution_options(populate_existing=True))
            if (source_job is None or source_job.game_id!=spec.game_id or source_job.status not in {'pending','retry'}
                    or source_job.lease_owner is not None or source_job.lease_until is not None
                    or source_job.attempts!=spec.attempt_no-1 or source_job.expires_at!=spec.source_expires_at
                    or source_job.expires_at<=spec.reserved_at
                    or source_job.retry_at is not None and source_job.retry_at>spec.reserved_at
                    or await self.session.get(NightRendering,spec.source.id) is not None):
                raise DispatchConflict('source_closed')
        if spec.attempt_no==2:
            previous=await self.source_attempts(spec.source,lock=True)
            prior=next((p for p in previous if p.attempt_no==1),None)
            if (prior is None or prior.status!='failed' or prior.retry_after is None or prior.retry_after>spec.reserved_at
                    or not await self._retry_error_allowed(prior,prior.error_code)
                    or (prior.binding_id,prior.epoch,prior.config_hash,prior.caps_hash,prior.payload_hash,prior.source_expires_at)
                        !=(spec.binding_id,spec.epoch,spec.config_hash,spec.caps_hash,spec.payload_hash,spec.source_expires_at)):
                raise DispatchConflict('source_closed')
        for quota in sorted(spec.quota_debits,key=lambda x:(x.scope,x.period_start)):
            await self.session.execute(insert(NightNarratorLimit).values(scope=quota.scope,period_start=quota.period_start).on_conflict_do_nothing())
            counter=await self.session.scalar(select(NightNarratorLimit).where(NightNarratorLimit.scope==quota.scope,NightNarratorLimit.period_start==quota.period_start).with_for_update().execution_options(populate_existing=True))
            if counter.reserved_requests+quota.requests>quota.max_requests or counter.reserved_tokens+quota.tokens>quota.max_tokens:
                raise DispatchConflict('quota_exhausted')
            counter.reserved_requests+=quota.requests
            counter.reserved_tokens+=quota.tokens
        values={k:getattr(spec,k) for k in spec.__dataclass_fields__ if k not in {'source','quota_debits'}}
        row=NightAIDispatchAttempt(**values, source_kind=spec.source.kind,
            intent_id=spec.source.id if spec.source.kind=='intent' else None,
            job_id=spec.source.id if spec.source.kind=='render' else None,
            contract_version='night-ai-transport/1',status='reserved',quota_debits=[x.document() for x in spec.quota_debits])
        self.session.add(row)
        binding.inflight_permit_id,binding.inflight_lease_until=row.id,row.lease_until
        if source_job is not None:
            source_job.status,source_job.attempts='leased',spec.attempt_no
            source_job.lease_owner,source_job.lease_until=spec.worker_id,spec.lease_until
            source_job.retry_at=None
        await self.session.flush()
        return row

    async def authorize_oauth(self, permit_id, nonce, now):
        _instant(now)
        result=await self.session.execute(update(NightAIDispatchAttempt).where(
            NightAIDispatchAttempt.id==permit_id,NightAIDispatchAttempt.lease_nonce==nonce,
            NightAIDispatchAttempt.status=='reserved',NightAIDispatchAttempt.oauth_claimed_at.is_(None),
            NightAIDispatchAttempt.network_deadline>now).values(oauth_claimed_at=now))
        return result.rowcount==1

    async def authorize_send(self, permit_id, nonce, now):
        _instant(now)
        result=await self.session.execute(update(NightAIDispatchAttempt).where(
            NightAIDispatchAttempt.id==permit_id,NightAIDispatchAttempt.lease_nonce==nonce,
            NightAIDispatchAttempt.status=='reserved',NightAIDispatchAttempt.network_deadline>=now+timedelta(seconds=1))
            .values(status='sending',sent_at=now))
        return result.rowcount==1

    async def finish(self, permit_id, nonce, *, now, status, error_code=None, response_hash=None, usage=None, retry_after=None):
        _instant(now)
        if status not in TERMINAL or error_code is not None and error_code not in ERRORS:
            raise ValueError('night_dispatch_outcome_invalid')
        if response_hash is not None and (type(response_hash) is not str or not HASH.fullmatch(response_hash)):
            raise ValueError('night_dispatch_outcome_invalid')
        if usage is not None:
            if type(usage) is not dict or set(usage)!={'input_tokens','output_tokens'}: raise ValueError('night_dispatch_usage_invalid')
            for number in usage.values(): _integer(number,0,2**63-1)
        if retry_after is not None:
            _instant(retry_after)
            if (status!='failed' or error_code not in TRANSIENT_ERRORS|{'auth_error'}
                    or not now+timedelta(seconds=1)<=retry_after<=now+timedelta(seconds=30)):
                raise ValueError('night_dispatch_retry_invalid')
        row=await self.attempt(permit_id,lock=True)
        if row is None or row.lease_nonce!=nonce or row.status not in ACTIVE: return False
        if retry_after is not None and not await self._retry_error_allowed(row,error_code):
            raise ValueError('night_dispatch_retry_invalid')
        row.status,row.finished_at,row.error_code=status,now,error_code
        row.response_hash,row.usage,row.retry_after=response_hash,null() if usage is None else usage,retry_after
        # CAS protects a newer reservation. Never mutate a terminal binding.
        await self.session.execute(update(NightAIBinding).where(NightAIBinding.id==row.binding_id,
            NightAIBinding.status=='active',NightAIBinding.inflight_permit_id==row.id)
            .values(inflight_permit_id=None,inflight_lease_until=None))
        if row.source_kind=='render':
            await self.session.execute(update(NightRenderJob).where(NightRenderJob.job_id==row.job_id,
                NightRenderJob.lease_owner==row.worker_id,NightRenderJob.lease_until==row.lease_until)
                .values(status='completed' if status=='succeeded' else ('retry' if retry_after is not None else 'fallback'),
                    lease_owner=None,lease_until=None,retry_at=retry_after,sanitized_error=error_code))
        await self.session.flush()
        return True

    async def _retry_error_allowed(self, row, error_code):
        if error_code in TRANSIENT_ERRORS: return True
        if error_code!='auth_error' or row.sent_at is None: return False
        # Only an observed Giga inference401 allows the one refresh retry;
        # OAuth401/403 (no inference sent) never does.
        adapter=await self.session.scalar(select(NightAIProfileRevision.config['adapter'].astext).join(
            NightAIBinding,(NightAIBinding.profile_id==NightAIProfileRevision.profile_id)&
            (NightAIBinding.profile_revision==NightAIProfileRevision.revision)).where(NightAIBinding.id==row.binding_id))
        return adapter=='gigachat_chat'

    async def cancel_binding(self, binding_id, *, now, error_code='stale'):
        """After caller's binding lock, before caller makes binding terminal."""
        row=await self.session.scalar(select(NightAIDispatchAttempt).where(
            NightAIDispatchAttempt.binding_id==binding_id,NightAIDispatchAttempt.status.in_(ACTIVE)).with_for_update())
        return False if row is None else await self.finish(row.id,row.lease_nonce,now=now,status='cancelled',error_code=error_code)


async def revoke_account_night_ai_in(session,account_id,*,now):
    """Trusted moderation hook AFTER own replay, BEFORE Account FOR UPDATE.

Caller already holds EXCLUSIVE operation_fence and owns rollback (including
invalid moderation revision/order). No application imports/game interruption.
Only blocked starter grants close; another starter's grant stays active while
the blocked recipient's own private permit is cancelled. Reusable admin keys
are never erased. Unblock does not revive the retained revoked bindings.
"""
    from storage.night_ai_control import NightAIControlRepository
    from storage.notifications import NotificationQueue
    if type(account_id) is not UUID:raise ValueError('invalid_account_target')
    _instant(now)
    control_repo=NightAIControlRepository(session)
    await control_repo.config_lock()
    subject='account:'+str(account_id)
    starter_games=select(NightAIGameControl.game_id).where(NightAIGameControl.starter_account_id==account_id)
    credential_games=select(NightAICredential.game_id).where(NightAICredential.scope=='game',NightAICredential.owner_subject==subject,NightAICredential.status!='erased')
    intent_games=select(NightAIIntentRequest.game_id).join(NightAIDispatchAttempt,NightAIDispatchAttempt.intent_id==NightAIIntentRequest.id).where(
        NightAIIntentRequest.requester_account_id==account_id,NightAIDispatchAttempt.status.in_(ACTIVE))
    private_games=select(NightRenderJob.game_id).join(NightAIDispatchAttempt,NightAIDispatchAttempt.job_id==NightRenderJob.job_id).where(
        NightRenderJob.audience_key==subject,NightAIDispatchAttempt.status.in_(ACTIVE))
    game_ids=set((await session.scalars(starter_games.union(credential_games,intent_games,private_games))).all())
    if not game_ids:return
    # All Games first, deterministic; ordinary game commands do not take the
    # AI advisory, so avoid interleaving new Game locks with AI child row locks.
    games=list((await session.scalars(select(Game).where(Game.id.in_(game_ids),Game.mode=='night_case')
        .order_by(Game.id).with_for_update().execution_options(populate_existing=True))).all())
    for game in games:
        locked=await control_repo.lock_game(game.id)
        closes_grant=locked.control is not None and locked.control.starter_account_id==account_id
        bindings=list((await session.scalars(select(NightAIBinding).where(NightAIBinding.game_id==game.id,NightAIBinding.status=='active')
            .order_by(NightAIBinding.id).with_for_update().execution_options(populate_existing=True))).all())
        credentials=list((await session.scalars(select(NightAICredential).where(NightAICredential.game_id==game.id,
            NightAICredential.scope=='game',NightAICredential.owner_subject==subject,NightAICredential.status!='erased')
            .order_by(NightAICredential.id).with_for_update().execution_options(populate_existing=True))).all())
        for binding in bindings:
            attempt=await session.scalar(select(NightAIDispatchAttempt).where(NightAIDispatchAttempt.binding_id==binding.id,
                NightAIDispatchAttempt.status.in_(ACTIVE)))
            source=None;owns_private=False
            if attempt is not None:
                model=NightAIIntentRequest if attempt.source_kind=='intent' else NightRenderJob
                source=await session.scalar(select(model).where(
                    (model.id==attempt.intent_id) if attempt.source_kind=='intent' else (model.job_id==attempt.job_id)).with_for_update())
                owns_private=(isinstance(source,NightAIIntentRequest) and source.requester_account_id==account_id
                    or isinstance(source,NightRenderJob) and source.audience_key==subject)
            if closes_grant or owns_private:
                await NightAIDispatchRepository(session).cancel_binding(binding.id,now=now,error_code='acl_denied')
                if isinstance(source,NightAIIntentRequest) and source.status=='prepared':
                    source.status,source.finalized_at,source.safe_result='cancelled',now,{'kind':'clarification','code':'choose_available_action'}
            if closes_grant:
                binding.status,binding.closed_at='revoked',now
                binding.inflight_job_id=binding.inflight_permit_id=binding.inflight_lease_until=None
                pointer={'game_id':game.id,'scope':'system:night_ai_cleanup','cause_id':str(binding.id),'kind':'night_ai_cleanup'}
                await NotificationQueue.enqueue_in(session,kind='night_ai_cleanup',game_id=game.id,payload=pointer,
                    dedupe_key='night-ai-cleanup:'+str(binding.id),available_at=now)
        for credential in credentials:
            credential.status,credential.erased_at='erased',now
            credential.key_id=credential.nonce=credential.ciphertext=credential.aad_version=None
        if closes_grant:
            pending=await control_repo.pending(game.id)
            if pending is not None:pending.status,pending.reason,pending.decided_at='cancelled','starter_unusable',now
        await session.flush()
