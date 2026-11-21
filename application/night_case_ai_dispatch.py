"""Durable Night AI application dispatch. Runtime/factory/HTTP wiring is absent.

Every operation opens and closes a real caller-authenticated transaction. Only
pure tickets/DTOs cross the network await; no Session, connection or ORM rows do.
Account principals may dispatch their own intent. Trusted workers dispatch render
jobs and expire unknown outcomes; they never impersonate a browser to propose.
"""
from __future__ import annotations

import asyncio
import copy
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
import time
from uuid import UUID, uuid4

from sqlalchemy import cast, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.dialects.postgresql import JSONB

from application.night_case import NightCaseError, _parse, command_key
from application.night_case_ai import BindingCaps, byok_audience_allowed, AI_PARTICIPATING_STATUSES
from application.night_case_orchestrator import CLARIFICATION, NightCaseOrchestrator, _decode
from application.night_case_director import (stable_job_id, _check_row, _event_body, _look_title,
    _event_observation_link, _observation_record, director_cast)
from config.night_case_ai import ProfileRevision
from domain.night_case_director import AuthorizedSource, SafeRecord, SafeOffer, FrozenContext, build_frozen_context, validate_director_result
from domain.night_case_narrative import LegalAction
from domain.night_case_projection import MenuChoice, available_actions
from domain.night_case_state import PlayerActor, event_scope
from infrastructure.night_ai_adapters import (AdapterError, BoundedResponse, build_inference,
    build_oauth, strict_json)
from infrastructure.night_ai_gateway import (CachedTokenRef, DispatchAuthorization, NetworkBudget,
    NightAIGateway, OAuthTicket, SendTicket, TicketFactory, TransportFailure)
from storage.admin_actions import operation_fence
from storage.models import Account, GameCommand, GamePlayer, NightEvent, NightNarratorLimit, NightRenderJob, NightRendering
from storage.night_ai import CredentialContext, SealedSecret, VaultUnavailable
from storage.night_ai_control import NightAIControlRepository
from storage.night_ai_dispatch import ACTIVE, TRANSIENT_ERRORS, DispatchConflict, DispatchSource, NightAIDispatchRepository, QuotaDebit, ReserveSpec
from storage.night_ai_models import NightAIBinding, NightAICredential, NightAIDispatchAttempt, NightAIGameControl, NightAIIntentRequest, NightAIJobBinding, NightAIProfile, NightAIProfileRevision
from storage.night_cases import canonical_json, json_hash


INTENT_SYSTEM='Выбери одно доступное действие из choices. Верни только JSON с request_token, kind="intent_selection", selection_id. Не придумывай действия, правила, факты или новые поля.'
RENDER_SYSTEM='Ты художественный редактор. Используй только данные facts и разрешённые references/catalog_ids. Proof — установленный факт; claim — слова указанной роли, а не истина. Не добавляй события, команды, правила, людей, ссылки или HTML. Верни только JSON: request_token, kind, text, references, catalog_ids.'
RENDER_TEMPLATE_HASH=hashlib.sha256(RENDER_SYSTEM.encode()).hexdigest()
EPOCH=datetime(1970,1,1,tzinfo=timezone.utc)
PENDING={'kind':'clarification','code':'intent_pending'}


@dataclass(frozen=True)
class AccountPrincipal:
    account_id: UUID
    def __post_init__(self):
        if type(self.account_id) is not UUID:raise ValueError('invalid_dispatch_principal')


@dataclass(frozen=True)
class WorkerPrincipal:
    worker_id: str
    def __post_init__(self):
        if type(self.worker_id) is not str or not re.fullmatch(r'[!-~]{1,96}',self.worker_id):raise ValueError('invalid_dispatch_principal')


@dataclass(frozen=True)
class DispatchFlags:
    enabled: bool=False
    external_allowed: bool=False
    def __post_init__(self):
        if type(self.enabled) is not bool or type(self.external_allowed) is not bool:raise ValueError('invalid_dispatch_flags')


@dataclass(frozen=True,repr=False)
class ReservedPermit:
    id: UUID
    lease_nonce: UUID
    source: DispatchSource
    worker_id: str
    preset: str
    budget: NetworkBudget


@dataclass(frozen=True,repr=False)
class DispatchResult:
    result: dict=field(repr=False)
    status: str='completed'
    retry_after: datetime | None=None


@dataclass(frozen=True)
class Denied:
    code: str


class _Unavailable(Exception):
    def __init__(self,code):self.code=code;super().__init__(code)


@dataclass(repr=False)
class _Locked:
    session: object
    app: object
    ai: object
    locked: object
    source: DispatchSource
    row: object
    actor_id: UUID
    control: object
    binding: object
    profile: object
    revision: object
    credential: object
    case: object
    rules: object
    state: object
    config: ProfileRevision
    caps: BindingCaps
    payload: dict
    system: str
    body: bytes
    payload_hash: str
    context: object=None


class NightCaseAIDispatcher:
    def __init__(self,db,app_factory,ai_factory,*,gateway,flags=lambda:DispatchFlags(),clock=lambda:datetime.now(timezone.utc),monotonic=time.monotonic):
        if type(gateway) is not NightAIGateway:raise ValueError('reviewed_gateway_required')
        self.db,self.app_factory,self.ai_factory=db,app_factory,ai_factory
        self.gateway,self.flags,self.clock,self.monotonic=gateway,flags,clock,monotonic
        self.orchestration=NightCaseOrchestrator(db,app_factory,ai_factory)

    def current_flags(self):
        value=self.flags()
        if type(value) is not DispatchFlags:raise ValueError('invalid_dispatch_flags')
        return value

    def _tx(self,factory):return (factory or self.db.transaction)()

    async def _metadata(self,s,source):
        if type(source) is not DispatchSource:raise ValueError('invalid_dispatch_source')
        model=NightAIIntentRequest if source.kind=='intent' else NightRenderJob
        row=await s.get(model,source.id,populate_existing=True)
        if row is None:raise NightCaseError('unavailable',404)
        return row

    async def _identity(self,s,app,source,row,actor,worker_id):
        WorkerPrincipal(worker_id)
        if type(actor) is AccountPrincipal:
            if source.kind!='intent':raise NightCaseError('unavailable',404)
            account,aliases=await app._intent_identity(actor.account_id,row.game_id)
            if row.requester_account_id not in aliases:raise NightCaseError('unavailable',404)
            return account.id,aliases
        if type(actor) is not WorkerPrincipal or actor.worker_id!=worker_id or source.kind!='render':
            raise NightCaseError('unavailable',404)
        if row.audience_key=='public':
            control=await s.get(NightAIGameControl,row.game_id,populate_existing=True)
            account_id=control.starter_account_id if control is not None else None
        else:
            try:account_id=UUID(row.audience_key.removeprefix('account:')) if row.audience_key.startswith('account:') else None
            except ValueError:account_id=None
        if account_id is None:raise _Unavailable('acl_denied')
        account=await app._principal(account_id)
        return account.id,frozenset({account.id})

    async def _existing(self,s,app,source,row,aliases):
        if source.kind=='intent':
            prior=await app._intent_prior(row.game_id,aliases,row.client_request_id,row.fingerprint)
            return DispatchResult(prior) if type(prior) is dict else None
        rendering=await s.get(NightRendering,row.job_id,populate_existing=True)
        if rendering is not None:return DispatchResult(self._render_result(rendering))
        return None

    @staticmethod
    def _render_result(row):
        return {'kind':'rendering','rendering':{key:copy.deepcopy(getattr(row,key)) for key in ('job_id','text','source','content_hash','references','catalog_ids')}}

    async def _config_lock(self,s,ai):
        # Reuse only THIS transaction's proven lock; never acquire it for the
        # first time under Game in a cleanup/fallback branch.
        transaction=s.get_transaction()
        if s.info.get('night_dispatch_config_lock') is not transaction:
            await ai.repo.config_lock()
            s.info['night_dispatch_config_lock']=transaction

    async def _load(self,s,source,actor,worker_id,*,validate=True):
        await operation_fence(s)
        app,ai=self.app_factory(s),self.ai_factory(s)
        if type(actor) is AccountPrincipal:await app._principal(actor.account_id)
        row=await self._metadata(s,source)
        actor_id,aliases=await self._identity(s,app,source,row,actor,worker_id)
        existing=await self._existing(s,app,source,row,aliases)
        if existing is not None:return existing
        await self._config_lock(s,ai)
        locked=await ai.repo.lock_game(row.game_id)
        if locked is None:raise NightCaseError('unavailable',404)
        control=locked.control
        assignment=await s.get(NightAIJobBinding,row.job_id,populate_existing=True) if source.kind=='render' else None
        binding_id=row.binding_id if source.kind=='intent' else assignment.binding_id if assignment is not None else None
        if control is None or binding_id is None:raise _Unavailable('source_closed')
        binding=await ai.repo.binding(binding_id)
        if binding is None:raise _Unavailable('stale')
        profile,revision=await ai.repo.profile_revision(binding.profile_id,binding.profile_revision)
        credential=await ai.repo.credential(revision.credential_id) if revision is not None and revision.credential_id else None
        model=NightAIIntentRequest if source.kind=='intent' else NightRenderJob
        key=model.id if source.kind=='intent' else model.job_id
        row=await s.scalar(select(model).where(key==source.id).with_for_update().execution_options(populate_existing=True))
        if source.kind=='render':
            assignment=await s.scalar(select(NightAIJobBinding).where(NightAIJobBinding.job_id==row.job_id).with_for_update().execution_options(populate_existing=True))
        existing=await self._existing(s,app,source,row,aliases)
        if existing is not None:return existing
        base=_Locked(s,app,ai,locked,source,row,actor_id,control,binding,profile,revision,credential,
            None,None,None,None,None,None,None,None,None)
        return await self._validate(base) if validate else base

    async def _validate(self,base):
        s,app,ai,locked,source,row,actor_id,control,binding,profile,revision,credential=(
            base.session,base.app,base.ai,base.locked,base.source,base.row,base.actor_id,base.control,base.binding,base.profile,base.revision,base.credential)
        assignment=await s.get(NightAIJobBinding,row.job_id,populate_existing=True) if source.kind=='render' else None
        now=self.clock();flags=self.current_flags()
        if not flags.enabled:raise _Unavailable('disabled')
        if (locked.game.status!='running' or locked.sealed.lifecycle!='running' or control.current_binding_id!=binding.id
                or control.epoch!=binding.epoch or binding.game_id!=row.game_id or binding.status!='active'
                or binding.valid_until<=now or binding.health!='ok' or profile is None or revision is None or not profile.enabled):
            raise _Unavailable('stale')
        if row.expires_at<=now:raise _Unavailable('expired')
        if not await ai._starter_usable(control,row.game_id):raise _Unavailable('acl_denied')
        account=await app._principal(actor_id)
        seat=await s.get(GamePlayer,(row.game_id,account.id),populate_existing=True)
        if seat is None or seat.status not in AI_PARTICIPATING_STATUSES:raise _Unavailable('acl_denied')
        case,rules,state=await app._runtime(locked)
        player=next((p for p in state.players if p['account_id']==str(actor_id)),None)
        if player is None or player['status'] not in AI_PARTICIPATING_STATUSES:raise _Unavailable('acl_denied')
        if source.kind=='render' and row.audience_key!='public' and player['status']=='ghost':raise _Unavailable('acl_denied')
        # Shared A read-only availability/window guard; never step/resume here.
        await self.orchestration._active(app,actor_id,row.game_id)
        try:
            config=ProfileRevision.decode(revision.config,ai.registry,byok=binding.mode=='byok')
            caps=BindingCaps.decode(binding.caps);doc=config.document()
            if config.config_hash!=binding.config_hash or revision.config_hash!=binding.config_hash:raise ValueError()
            if doc['credential_id']!=(str(revision.credential_id) if revision.credential_id else None):raise ValueError()
            if doc['endpoint']['network_class']=='cloud' and not flags.external_allowed:raise _Unavailable('disabled')
            if credential is not None and (credential.status!='usable' or credential.scope!=profile.scope
                    or credential.game_id!=profile.game_id or credential.preset!=doc['preset']
                    or credential.expires_at is not None and credential.expires_at<=now):raise ValueError()
            if binding.mode=='byok':
                if (credential is None or profile.scope!='game' or profile.game_id!=row.game_id
                        or credential.owner_subject!='account:'+str(control.starter_account_id)):raise ValueError()
            elif binding.mode!='admin' or profile.scope!='admin':raise ValueError()
            audience='account:'+str(row.requester_account_id) if source.kind=='intent' else row.audience_key
            private=frozenset() if audience=='public' else frozenset({UUID(audience[8:])})
            if binding.mode=='byok' and not byok_audience_allowed(control.starter_account_id,audience,private):raise _Unavailable('acl_denied')
            if source.kind=='intent':
                if row.status!='prepared' or row.requester_account_id!=account.id or row.epoch!=binding.epoch:raise _Unavailable('stale')
                token,legal=_decode(row)
                player=next(p for p in state.players if p['account_id']==str(account.id))
                if (token['config_hash']!=binding.config_hash or token['caps_hash']!=json_hash(caps.document())
                        or token['case_hash']!=locked.sealed.content_hash or token['rules_hash']!=locked.sealed.rules_hash
                        or token['engine_build']!=locked.sealed.engine_build or
                        (token['window_idx'],token['window_seq'],token['actor_seq'])!=(state.clock['window_idx'],state.clock['window_seq'],player['actor_seq'])):
                    raise _Unavailable('stale')
                fresh=self.orchestration._legal(case,rules,state,actor_id,now)
                if not any(canonical_json(saved)==canonical_json(current) for saved in legal['items'] for current in fresh['items']):
                    raise _Unavailable('stale')
                payload={'request_token':token['request_token'],'kind':'intent_selection','text':token['text'],
                    'choices':[{k:item[k] for k in ('selection_id','kind','label')} for item in legal['items']]}
                system=INTENT_SYSTEM;context=None
            else:
                if assignment is None or (assignment.game_id,assignment.binding_id,assignment.epoch)!=(row.game_id,binding.id,binding.epoch):raise _Unavailable('stale')
                context=await self._render_context(s,locked,case,rules,state,row)
                payload=context.narrative_job(job_id=row.job_id,cause_id=row.cause_id,kind=row.kind,
                    expires_at=row.expires_at,fallback=row.fallback).provider_payload
                system=RENDER_SYSTEM
            output=min(800,caps.max_output_tokens,doc['generation']['max_output_tokens'])
            wire=build_inference(config,ai.registry,system=system,user=canonical_json(payload,max_bytes=32768).decode(),
                secret=None if doc['auth_mode']=='none' or doc['preset']=='gigachat' else b'reservation-placeholder',
                access_token=b'reservation-placeholder' if doc['preset']=='gigachat' else None,
                max_output_tokens=output,output_schema=self._output_schema(source,payload))
        except _Unavailable:raise
        except (ValueError,KeyError,TypeError,AttributeError,StopIteration):raise _Unavailable('config_error') from None
        return _Locked(s,app,ai,locked,source,row,actor_id,control,binding,profile,revision,credential,case,rules,state,
            config,caps,payload,system,wire.body,hashlib.sha256(wire.body).hexdigest(),context)

    @staticmethod
    def _output_schema(source,payload):
        properties={'request_token':{'type':'string','const':payload['request_token']},'kind':{'type':'string','const':payload['kind']}}
        if source.kind=='intent':properties['selection_id']={'type':'string','enum':[x['selection_id'] for x in payload['choices']]}
        else:
            properties.update(text={'type':'string','minLength':1,'maxLength':4000},
                references={'type':'array','items':{'type':'string','enum':payload['references']},'maxItems':64},
                catalog_ids={'type':'array','items':{'type':'string','enum':payload['catalog_ids']},'maxItems':1 if payload['kind']=='story_offer' else 0})
        return {'type':'object','properties':properties,'required':list(properties),'additionalProperties':False}

    async def _render_context(self,s,locked,case,rules,state,job):
        """Rebuild from canonical source evidence. Never trust a rehashed speaker."""
        doc=state.document();case_doc=case.document();window=doc['clock']['window_idx']
        if (job.template_version!=RENDER_TEMPLATE_HASH or job.job_id!=stable_job_id(job.game_id,job.cause_id,job.kind,job.audience_key,RENDER_TEMPLATE_HASH)
                or type(job.frozen_view) is not dict or job.frozen_view.get('action_window')!=window):raise _Unavailable('stale')
        events={e['event_id']:e for e in doc['public']['chronicle']+doc['private_events']}
        cause=events.get(job.cause_id)
        if cause is None:raise _Unavailable('source_closed')
        row=await s.get(NightEvent,(job.game_id,job.cause_id),populate_existing=True)
        _check_row(job.game_id,cause,row)
        if event_scope(cause['audience'])!=job.audience_key or row.audience_seq!=job.knowledge_revision or cause['window_idx']!=window:
            raise _Unavailable('acl_denied')
        close=_parse(doc['clock']['closes_at'])
        if job.expires_at>min(row.created_at+timedelta(minutes=5),close):raise _Unavailable('stale')
        records=[];offers=[]
        if job.kind=='scene_narration':
            if cause['kind']!='scene' or job.audience_key!='public':raise _Unavailable('source_closed')
            source=AuthorizedSource(job.kind,job.cause_id,'public',window,None,(),(),_event_body(cause,case_doc,doc))
        elif job.kind=='npc_reply':
            if cause['kind']!='action_result' or not job.audience_key.startswith('account:'):raise _Unavailable('source_closed')
            account=UUID(job.audience_key[8:])
            commands=list((await s.scalars(select(GameCommand).where(GameCommand.game_id==job.game_id,
                GameCommand.kind=='talk',GameCommand.status=='applied',GameCommand.actor_account_id==account,
                cast(GameCommand.result,JSONB).op('->')('caused_event_ids').contains([job.cause_id])).limit(2))).all())
            if len(commands)!=1:raise _Unavailable('source_closed')
            command=commands[0];payload=command.payload;raw=payload['command'];cid=payload['client_command_id']
            receipt=next((r for r in doc['receipts'] if r['actor_key']==job.audience_key and r['command_id']==cid),None)
            if (set(payload)!={'client_command_id','actor_key','command','payload_hash'} or payload['actor_key']!=str(account)
                    or command.id!=command_key(job.game_id,str(account),cid) or json_hash(raw)!=payload['payload_hash']
                    or raw['kind']!='talk' or command.result['receipt']['accepted'] is not True
                    or command.result['receipt']['command_id']!=cid or receipt is None or not receipt['accepted']
                    or receipt['result_ref']!={'kind':'event','event_id':job.cause_id}):raise _Unavailable('source_closed')
            dialogue=next((d for d in case_doc['dialogues'] if d['id']==raw['params']['dialogue_id']),None)
            if dialogue is None:raise _Unavailable('source_closed')
            target=dialogue['character']
            if any(p['character_id']==target for p in doc['players']):raise _Unavailable('source_closed')
            character=next(c for c in case_doc['characters'] if c['id']==target)
            source=AuthorizedSource(job.kind,job.cause_id,job.audience_key,window,None,(job.cause_id,),
                tuple(cause['payload']['observation_ids']),_event_body(cause,case_doc,doc),_look_title(case_doc,doc,character['id']))
            records=[_observation_record(case_doc,doc,oid,str(account),cause) for oid in source.observation_ids]
        else:
            if job.kind not in {'window_digest','story_offer'} or cause['kind']!='window_digest' or not job.audience_key.startswith('account:'):
                raise _Unavailable('source_closed')
            refs=tuple(cause['payload']['event_ids']);observations=tuple(cause['payload']['observation_ids']);summarized=cause['payload']['window_idx']
            resolved=[]
            for eid in refs:
                event=events.get(eid)
                if event is None or event['window_idx']!=summarized or event_scope(event['audience']) not in {'public',job.audience_key}:
                    raise _Unavailable('acl_denied')
                _check_row(job.game_id,event,await s.get(NightEvent,(job.game_id,eid),populate_existing=True));resolved.append(event)
            source=AuthorizedSource(job.kind,job.cause_id,job.audience_key,window,summarized,refs,observations,'')
            if job.kind=='window_digest':
                records=[SafeRecord('event',e['event_id'],'scene' if e['kind']=='scene' else 'result',_event_body(e,case_doc,doc),event_scope(e['audience']),e['window_idx']) for e in resolved]
                for oid in observations:
                    parent=next((e for e in resolved if _event_observation_link(doc,e,oid)),None)
                    if parent is None:raise _Unavailable('source_closed')
                    records.append(_observation_record(case_doc,doc,oid,job.audience_key[8:],parent))
            else:
                for saved in job.frozen_view.get('offers',[]):
                    # Persisted menu whitelist is historical, not a new command.
                    # Current quote eligibility belongs to later UI/confirm;
                    # ordinary actions must not rewrite the saved offer/price.
                    quote=LegalAction(saved['selection_id'],saved['kind'],saved['target_id'],saved['cost'],
                        saved['resource_id'],json.loads(saved['params']),saved['resource_revision'])
                    offers.append(SafeOffer(MenuChoice('choice',quote.selection_id,saved['label'],quote)))
        heroes=(character['id'],) if job.kind=='npc_reply' else ()
        cast=director_cast(case_doc,doc,heroes=heroes,observation_ids=source.observation_ids) if job.kind in {'npc_reply','window_digest'} else ()
        expected=build_frozen_context(source,records,offers,case_hash=case.content_hash,
            ruleset_version='core/'+str(case_doc['ruleset_ref']['version']),fallback=job.fallback,created_at=row.created_at,closes_at=close,cast=cast)
        if expected.input_hash!=job.input_hash or canonical_json(expected.document())!=canonical_json(job.frozen_view):raise _Unavailable('source_closed')
        return FrozenContext.from_document(job.frozen_view,input_hash=job.input_hash,source=source)

    async def _limit(self,s,scope,period):
        await s.execute(insert(NightNarratorLimit).values(scope=scope,period_start=period).on_conflict_do_nothing())
        return await s.scalar(select(NightNarratorLimit).where(NightNarratorLimit.scope==scope,
            NightNarratorLimit.period_start==period).with_for_update().execution_options(populate_existing=True))

    def _quotas(self,ctx,now):
        total=len(ctx.body)+min(ctx.caps.max_output_tokens,ctx.config.document()['generation']['max_output_tokens'],800)
        return tuple(QuotaDebit(scope,period,1,total,requests,tokens) for scope,period,requests,tokens in (
            ('nai:global:minute',now.replace(second=0,microsecond=0),10,2**63-1),
            ('nai:actor:'+str(ctx.actor_id)+':minute',now.replace(second=0,microsecond=0),4,2**63-1),
            ('game:'+ctx.row.game_id+':day',now.replace(hour=0,minute=0,second=0,microsecond=0),ctx.caps.requests_per_day,ctx.caps.reserved_tokens_per_day),
            ('game:'+ctx.row.game_id+':total',EPOCH,ctx.caps.total_requests,ctx.caps.total_reserved_tokens)))

    @staticmethod
    def _circuit(ctx):return 'nai:circuit:'+str(ctx.profile.id)+':'+str(ctx.revision.revision)

    async def _fallback(self,s,source,*,expired=False):
        row=await self._metadata(s,source);app,ai=self.app_factory(s),self.ai_factory(s)
        await self._config_lock(s,ai);await ai.repo.lock_game(row.game_id)
        model=NightAIIntentRequest if source.kind=='intent' else NightRenderJob;column=model.id if source.kind=='intent' else model.job_id
        row=await s.scalar(select(model).where(column==source.id).with_for_update().execution_options(populate_existing=True))
        if source.kind=='intent':
            if row.status=='prepared':row.status,row.finalized_at,row.safe_result=('expired' if expired else 'finalized'),self.clock(),copy.deepcopy(CLARIFICATION)
            await s.flush()
            return DispatchResult(copy.deepcopy(row.safe_result))
        rendering=await app.repo.commit_rendering(NightRendering(job_id=row.job_id,text=row.fallback,source='authored',
            content_hash=hashlib.sha256(row.fallback.encode()).hexdigest(),references=[],catalog_ids=[],created_at=self.clock()))
        if row.status in {'pending','retry'} and row.lease_owner is None:row.status,row.retry_at='fallback',None
        await s.flush();return DispatchResult(self._render_result(rendering),status='authored')

    async def reserve(self,source,*,actor,worker_id,transaction_factory=None):
        async with self._tx(transaction_factory) as s:
            try:
                ctx=await self._load(s,source,actor,worker_id,validate=False)
                if type(ctx) is DispatchResult:return ctx
                repo=NightAIDispatchRepository(s);now=self.clock()
                attempts=await repo.source_attempts(source,lock=True)
                if attempts:
                    prior=attempts[-1]
                    if prior.status in ACTIVE:return DispatchResult(copy.deepcopy(PENDING),status='pending')
                    if (prior.status!='failed' or prior.retry_after is None or prior.attempt_no!=1):return await self._fallback(s,source)
                    if prior.retry_after>now:return DispatchResult(copy.deepcopy(PENDING),status='deferred',retry_after=prior.retry_after)
                ctx=await self._validate(ctx)
                if ctx.binding.inflight_permit_id is not None:raise _Unavailable('binding_busy')
                if now+timedelta(seconds=12)>ctx.row.expires_at:raise _Unavailable('expired')
                quotas=self._quotas(ctx,now)
                periods={(q.scope,q.period_start) for q in quotas}|{(self._circuit(ctx),EPOCH)}
                limits={key:await self._limit(s,*key) for key in sorted(periods)}
                breaker=limits[(self._circuit(ctx),EPOCH)]
                if breaker.circuit_open_until is not None and breaker.circuit_open_until>now:raise _Unavailable('circuit_open')
                if any(limits[(q.scope,q.period_start)].reserved_requests+1>q.max_requests
                        or limits[(q.scope,q.period_start)].reserved_tokens+q.tokens>q.max_tokens for q in quotas):raise _Unavailable('quota_exhausted')
                permit,nonce=uuid4(),uuid4();output=min(ctx.caps.max_output_tokens,ctx.config.document()['generation']['max_output_tokens'],800)
                spec=ReserveSpec(id=permit,source=source,game_id=ctx.row.game_id,binding_id=UUID(str(ctx.binding.id)),epoch=ctx.binding.epoch,
                    attempt_no=len(attempts)+1,config_hash=ctx.binding.config_hash,caps_hash=json_hash(ctx.caps.document()),payload_hash=ctx.payload_hash,
                    source_expires_at=ctx.row.expires_at,worker_id=worker_id,lease_nonce=nonce,reserved_at=now,
                    lease_until=min(now+timedelta(seconds=30),ctx.row.expires_at),network_deadline=now+timedelta(seconds=12),
                    reserved_input_units=len(ctx.body),reserved_output_tokens=output,quota_debits=quotas)
                budget=NetworkBudget.create(permit,nonce,now,spec.network_deadline,now_utc=now,monotonic_now=self.monotonic())
                await repo.reserve(spec)
                return ReservedPermit(permit,nonce,source,worker_id,ctx.config.document()['preset'],budget)
            except _Unavailable as error:return await self._fallback(s,source,expired=error.code=='expired')

    async def _permit_context(self,s,permit,actor,worker_id,*,validate=True):
        await operation_fence(s)
        row=await s.get(NightAIDispatchAttempt,permit.id,populate_existing=True)
        if row is None or row.lease_nonce!=permit.lease_nonce or row.worker_id!=worker_id or worker_id!=permit.worker_id:
            raise NightCaseError('unavailable',404)
        source=DispatchSource(row.source_kind,UUID(str(row.intent_id)) if row.source_kind=='intent' else row.job_id)
        if source!=permit.source:raise NightCaseError('unavailable',404)
        ctx=await self._load(s,source,actor,worker_id,validate=False)
        if type(ctx) is DispatchResult:return ctx,row
        row=await NightAIDispatchRepository(s).attempt(permit.id,lock=True)
        if row is None or row.lease_nonce!=permit.lease_nonce:raise NightCaseError('unavailable',404)
        if validate:
            ctx=await self._validate(ctx)
            if (row.binding_id,row.epoch,row.config_hash,row.caps_hash,row.payload_hash,row.source_expires_at)!=(
                    ctx.binding.id,ctx.binding.epoch,ctx.config.config_hash,json_hash(ctx.caps.document()),ctx.payload_hash,ctx.row.expires_at):
                raise _Unavailable('stale')
        return ctx,row

    def _decrypt(self,ctx):
        credential=ctx.credential
        if credential is None:
            if ctx.config.document()['auth_mode']=='none':return None
            raise _Unavailable('credential_unavailable')
        try:
            return ctx.ai.vault.decrypt(SealedSecret(credential.key_id,credential.nonce,credential.ciphertext,credential.aad_version),
                CredentialContext(ctx.ai.environment_id,UUID(str(credential.id)),credential.scope,credential.owner_subject,credential.game_id,credential.preset))
        except VaultUnavailable:raise _Unavailable('credential_unavailable') from None

    @staticmethod
    def _authorization(ctx,attempt,now):
        return DispatchAuthorization(UUID(str(attempt.id)),UUID(str(attempt.lease_nonce)),ctx.config.config_hash,
            UUID(str(ctx.credential.id)) if ctx.credential else None,attempt.network_deadline,now)

    async def authorize_oauth(self,permit,*,actor,worker_id,transaction_factory=None):
        if type(permit) is not ReservedPermit:raise ValueError('invalid_reserved_permit')
        async with self._tx(transaction_factory) as s:
            try:
                ctx,attempt=await self._permit_context(s,permit,actor,worker_id)
                now=self.clock()
                if type(ctx) is DispatchResult or attempt.status!='reserved' or attempt.lease_until<=now or permit.budget.remaining(self.monotonic())<=0:
                    return Denied('stale')
                if ctx.config.document()['preset']!='gigachat':return Denied('config_error')
                secret=self._decrypt(ctx)  # A cache never bypasses current vault/credential checks.
                scope=ctx.config.document()['project_fields']['scope']
                cached=self.gateway.oauth_cache.get(ctx.credential.id,ctx.config.config_hash,scope,now)
                if cached is not None:return cached
                if attempt.oauth_claimed_at is not None:return Denied('stale')
                periods=[('nai:control:global:minute',30),('nai:control:'+ctx.credential.owner_subject+':minute',5)]
                counters=[(await self._limit(s,scope,now.replace(second=0,microsecond=0)),cap) for scope,cap in sorted(periods)]
                if any(row.reserved_requests>=cap for row,cap in counters):return Denied('quota_exhausted')
                # Exact fixed OAuth policy is selected from the operator registry,
                # never inferred from an arbitrary profile URL or a browser field.
                policies=[p for p in self.gateway._policies.values() if p.endpoint.base_url=='https://ngw.devices.sberbank.ru:9443']
                if len(policies)!=1:return Denied('endpoint_denied')
                policy=policies[0].endpoint
                wire=build_oauth(ctx.config,ctx.ai.registry,secret=secret,policy_id=policy.policy_id,policy_version=policy.policy_version)
                if not await NightAIDispatchRepository(s).authorize_oauth(attempt.id,attempt.lease_nonce,now):return Denied('stale')
                for row,_ in counters:row.reserved_requests+=1
                await s.flush()
                ticket=TicketFactory().issue(self._authorization(ctx,attempt,now),permit.budget,wire)
            except _Unavailable as error:return Denied(error.code)
            except AdapterError as error:return Denied(error.code)
        return ticket  # Commit has completed before credentials can reach gateway.

    async def authorize_inference(self,permit,*,actor,worker_id,token_ref=None,transaction_factory=None):
        if type(permit) is not ReservedPermit:raise ValueError('invalid_reserved_permit')
        async with self._tx(transaction_factory) as s:
            try:
                ctx,attempt=await self._permit_context(s,permit,actor,worker_id)
                now=self.clock()
                if type(ctx) is DispatchResult or attempt.status!='reserved' or attempt.lease_until<=now or permit.budget.remaining(self.monotonic())<1:
                    return Denied('stale')
                secret=self._decrypt(ctx);config=ctx.config.document()
                if config['preset']=='gigachat':
                    if type(token_ref) is not CachedTokenRef:return Denied('credential_unavailable')
                    secret=None;access=token_ref.bytes_for_trusted_adapter()
                else:access=None
                wire=build_inference(ctx.config,ctx.ai.registry,system=ctx.system,user=canonical_json(ctx.payload,max_bytes=32768).decode(),
                    secret=secret,access_token=access,max_output_tokens=attempt.reserved_output_tokens,output_schema=self._output_schema(ctx.source,ctx.payload))
                if hashlib.sha256(wire.body).hexdigest()!=attempt.payload_hash:return Denied('stale')
                ticket=TicketFactory().issue(self._authorization(ctx,attempt,now),permit.budget,wire,token_ref=token_ref)
                if not await NightAIDispatchRepository(s).authorize_send(attempt.id,attempt.lease_nonce,now):return Denied('stale')
            except _Unavailable as error:return Denied(error.code)
            except AdapterError as error:return Denied(error.code)
        return ticket

    async def _finish(self,s,permit,*,status,error=None,response_hash=None,usage=None,retry_after=None):
        attempt=await s.get(NightAIDispatchAttempt,permit.id,populate_existing=True)
        ai=self.ai_factory(s);await self._config_lock(s,ai)
        await ai.repo.lock_game(attempt.game_id);await ai.repo.binding(attempt.binding_id)
        await s.scalar(select(NightAIIntentRequest if attempt.source_kind=='intent' else NightRenderJob)
            .where((NightAIIntentRequest.id==attempt.intent_id) if attempt.source_kind=='intent' else (NightRenderJob.job_id==attempt.job_id)).with_for_update())
        return await NightAIDispatchRepository(s).finish(attempt.id,permit.lease_nonce,now=self.clock(),status=status,
            error_code=error,response_hash=response_hash,usage=usage,retry_after=retry_after)

    async def _health(self,ctx,attempt,outcome,*,will_retry=False):
        if attempt.sent_at is None and attempt.oauth_claimed_at is None:return
        counter=await self._limit(ctx.session,self._circuit(ctx),EPOCH)
        if type(outcome) is BoundedResponse:
            counter.failures=0;counter.circuit_open_until=None
        elif outcome.code in {'dns_failed','tls_failed','timeout','network_error','rate_limited','provider_error','auth_error','config_error','oversize','invalid_response'}:
            counter.failures+=1
            if counter.failures>=5:counter.circuit_open_until=self.clock()+timedelta(minutes=5)
            if outcome.code in {'auth_error','config_error'} and not (outcome.code=='auth_error' and will_retry):ctx.binding.health=outcome.code
        await ctx.session.flush()

    async def complete(self,permit,*,actor,worker_id,outcome,transaction_factory=None):
        if type(permit) is not ReservedPermit or type(outcome) not in {BoundedResponse,TransportFailure}:raise ValueError('invalid_dispatch_completion')
        async with self._tx(transaction_factory) as s:
            try:
                ctx,attempt=await self._permit_context(s,permit,actor,worker_id,validate=False)
                if attempt.status not in ACTIVE:
                    if type(ctx) is DispatchResult:return ctx
                    if attempt.status=='failed' and attempt.retry_after is not None:
                        return DispatchResult(copy.deepcopy(PENDING),'deferred',attempt.retry_after)
                    return await self._fallback(s,permit.source,expired=attempt.status=='expired')
                if type(ctx) is DispatchResult:
                    await self._finish(s,permit,status='cancelled',error='stale');return ctx
                now=self.clock()
                if attempt.lease_until<=now:
                    await self._finish(s,permit,status='expired',error='expired')
                    return await self._fallback(s,permit.source,expired=True)
                ctx=await self._validate(ctx)
                if (attempt.binding_id,attempt.epoch,attempt.config_hash,attempt.caps_hash,attempt.payload_hash)!=(
                    ctx.binding.id,ctx.binding.epoch,ctx.config.config_hash,json_hash(ctx.caps.document()),ctx.payload_hash):raise _Unavailable('stale')
                if type(outcome) is TransportFailure:
                    # Only an observed outcome can retry. Expiry/crash/cancel
                    # never fabricates a failed transient attempt.
                    giga_refresh=(outcome.code=='auth_error' and outcome.http_status==401
                        and ctx.config.document()['preset']=='gigachat' and attempt.sent_at is not None)
                    if giga_refresh and ctx.credential is not None:
                        self.gateway.oauth_cache.invalidate((UUID(str(ctx.credential.id)),ctx.config.config_hash,
                            ctx.config.document()['project_fields']['scope']))
                    retryable=outcome.code in TRANSIENT_ERRORS or giga_refresh
                    pause=min(30,max(1,outcome.retry_after_seconds if type(outcome.retry_after_seconds) is int else 2))
                    retry=now+timedelta(seconds=pause) if retryable and attempt.attempt_no==1 and now+timedelta(seconds=pause+12)<=ctx.row.expires_at else None
                    await self._health(ctx,attempt,outcome,will_retry=retry is not None)
                    await self._finish(s,permit,status='failed',error=outcome.code,retry_after=retry)
                    if retry is not None:return DispatchResult(copy.deepcopy(PENDING),'deferred',retry)
                    return await self._fallback(s,permit.source)
                if attempt.status!='sending' or attempt.sent_at is None:raise _Unavailable('stale')
                try:parsed=strict_json(outcome.text.encode('utf8'),limit=16000)
                except (AdapterError,UnicodeError):parsed=None
                if ctx.source.kind=='intent':
                    result=await self.orchestration._finalize_prepared_in(s,ctx.app,ctx.ai,ctx.actor_id,ctx.locked,ctx.row,parsed)
                else:
                    decision=validate_director_result(ctx.context,parsed,job_id=ctx.row.job_id,now=now,
                        current_window=ctx.state.clock['window_idx'],cause_id=ctx.row.cause_id,kind=ctx.row.kind,
                        expires_at=ctx.row.expires_at,fallback=ctx.row.fallback)
                    document=ctx.context.document()
                    # Validate/resolve aliases against this job's frozen maps;
                    # persist aliases, never treat them as global gameplay IDs.
                    refmap={r['alias']:r for r in document['reference_map']};offermap={o['alias']:o for o in document['offers']}
                    if any(a not in refmap for a in decision.references) or any(a not in offermap for a in decision.catalog_ids):raise _Unavailable('invalid_response')
                    rendering=await ctx.app.repo.commit_rendering(NightRendering(job_id=ctx.row.job_id,text=decision.text,
                        source='ai' if decision.source=='candidate' else 'authored',content_hash=hashlib.sha256(decision.text.encode()).hexdigest(),
                        references=list(decision.references),catalog_ids=list(decision.catalog_ids),created_at=now))
                    result=self._render_result(rendering)
                await self._health(ctx,attempt,outcome)
                await self._finish(s,permit,status='succeeded',response_hash=hashlib.sha256(outcome.text.encode('utf8')).hexdigest(),usage=outcome.usage)
                return DispatchResult(result)
            except _Unavailable as error:
                await self._finish(s,permit,status='cancelled',error=error.code)
                return await self._fallback(s,permit.source,expired=error.code=='expired')

    async def dispatch(self,source,*,actor,worker_id,transaction_factory=None):
        permit=await self.reserve(source,actor=actor,worker_id=worker_id,transaction_factory=transaction_factory)
        if type(permit) is DispatchResult:return permit
        ref=None
        if permit.preset=='gigachat':
            ticket=await self.authorize_oauth(permit,actor=actor,worker_id=worker_id,transaction_factory=transaction_factory)
            if type(ticket) is OAuthTicket:ticket=await self.gateway.exchange(ticket)
            if type(ticket) is CachedTokenRef:ref=ticket
            else:
                outcome=ticket if type(ticket) is TransportFailure else TransportFailure(ticket.code)
                return await self.complete(permit,actor=actor,worker_id=worker_id,outcome=outcome,transaction_factory=transaction_factory)
        ticket=await self.authorize_inference(permit,actor=actor,worker_id=worker_id,token_ref=ref,transaction_factory=transaction_factory)
        outcome=await self.gateway.exchange(ticket) if type(ticket) is SendTicket else TransportFailure(ticket.code)
        return await self.complete(permit,actor=actor,worker_id=worker_id,outcome=outcome,transaction_factory=transaction_factory)

    async def expire_due(self,*,actor,limit=20):
        if type(actor) is not WorkerPrincipal or type(limit) is not int or not 1<=limit<=20:raise ValueError('invalid_dispatch_cleanup')
        async with self.db.transaction() as s:
            await operation_fence(s)
            rows=list((await s.scalars(select(NightAIDispatchAttempt).where(NightAIDispatchAttempt.status.in_(ACTIVE),
                NightAIDispatchAttempt.lease_until<=self.clock()).order_by(NightAIDispatchAttempt.lease_until,NightAIDispatchAttempt.id).limit(limit))).all())
            identities=[(r.id,r.lease_nonce,DispatchSource(r.source_kind,UUID(str(r.intent_id)) if r.source_kind=='intent' else r.job_id)) for r in rows]
        expired=0
        for ident,nonce,source in identities:
            async with self.db.transaction() as s:
                await operation_fence(s)
                ai=self.ai_factory(s);await self._config_lock(s,ai)
                row=await s.get(NightAIDispatchAttempt,ident,populate_existing=True)
                await ai.repo.lock_game(row.game_id);await ai.repo.binding(row.binding_id)
                model=NightAIIntentRequest if source.kind=='intent' else NightRenderJob
                await s.scalar(select(model).where((model.id==source.id) if source.kind=='intent' else (model.job_id==source.id)).with_for_update())
                row=await NightAIDispatchRepository(s).attempt(ident,lock=True)
                if row.status not in ACTIVE or row.lease_nonce!=nonce or row.lease_until>self.clock():continue
                await NightAIDispatchRepository(s).finish(ident,nonce,now=self.clock(),status='expired',error_code='expired')
                await self._fallback(s,source,expired=True);expired+=1
        return {'expired':expired}
