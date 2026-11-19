"""Shared Night Case transaction orchestration. Real provider HTTP is disabled.

Only TestOnlyIntentTransport is callable in this slice. A future reviewed durable
dispatch permit/union lease is mandatory before adding any live transport path.
HTTP callers may supply a trusted authenticated transaction context per phase;
no principal/session context may span the transport await.
"""
from __future__ import annotations

import copy
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import null

from application.night_case import NightCaseError, AvailabilityDecision, TransitionContext, parse_start_request, _stamp, _parse
from application.night_case_ai import BindingCaps, byok_audience_allowed, AI_PARTICIPATING_STATUSES
from config.night_case_ai import ProfileRevision
from domain.night_case_projection import available_actions
from domain.night_case_state import PlayerActor
from domain.night_case_narrative import LegalAction
from storage.admin_actions import operation_fence
from storage.models import GamePlayer
from storage.night_ai_control import NightAIControlRepository
from storage.night_ai_models import NightAIIntentRequest, NightAIGameControl
from storage.night_cases import NightStorageConflict, canonical_json, json_hash


CLARIFICATION = {'kind': 'clarification', 'code': 'choose_available_action'}


def _jsonb_bound(value, limit):
    """Match PG CHECK's spaced JSONB text bound, not only compact hash bytes."""
    canonical_json(value, max_bytes=limit)
    def nul(item):
        if type(item) is str: return '\x00' in item
        if type(item) is list: return any(nul(x) for x in item)
        if type(item) is dict: return any(nul(k) or nul(v) for k,v in item.items())
        return False
    rendered=json.dumps(value,ensure_ascii=False,sort_keys=True,allow_nan=False,separators=(', ',': ')).encode('utf8')
    if nul(value) or len(rendered)>limit: raise ValueError('intent_document_bound')


@dataclass(frozen=True, repr=False)
class PreparedIntent:
    id: UUID
    game_id: str
    account_id: UUID
    request_id: str
    _token: bytes = field(repr=False)
    _legal: bytes = field(repr=False)
    replayed: bool = False

    def __repr__(self):
        return 'PreparedIntent(<private>)'

    @property
    def token(self): return json.loads(self._token)

    @property
    def legal(self): return json.loads(self._legal)


@dataclass(frozen=True, repr=False)
class TestOnlyIntentTransport:
    """Explicit test injection, never constructed by runtime/env/HTTP adapters."""
    __test__ = False
    callback: object = field(repr=False)

    async def infer(self, payload):
        return await self.callback(payload)


def _envelope(request_id, selection_id, text):
    if (type(request_id) is not str or not 8 <= len(request_id) <= 128
            or selection_id is not None and type(selection_id) is not str
            or text is not None and (type(text) is not str or not 1 <= len(text) <= 1000)):
        raise NightCaseError('invalid_command', 422)
    return json_hash({'selection_id': selection_id, 'text': text})


def _work(row, *, replayed=False):
    token, legal = _decode(row)
    return PreparedIntent(UUID(str(row.id)), row.game_id, UUID(str(row.requester_account_id)), row.client_request_id,
                          canonical_json(token, max_bytes=8192), canonical_json(legal, max_bytes=32768), replayed)


def _decode(row):
    token, legal = copy.deepcopy(row.token), copy.deepcopy(row.legal_candidates)
    fields = {'schema','request_token','case_hash','rules_hash','engine_build','window_idx','window_seq','actor_seq',
              'prepared_at','expires_at','text','config_hash','caps_hash'}
    try:
        _jsonb_bound(token,8192); _jsonb_bound(legal,32768)
        if (type(token) is not dict or set(token) != fields or token['schema'] != 'night-ai-intent-token/1'
                or type(legal) is not dict or set(legal) != {'schema','items'} or legal['schema'] != 'night-ai-legal/1'
                or type(legal['items']) is not list or len(legal['items']) > 64
                or type(token['request_token']) is not str or re.fullmatch('[a-f0-9]{64}',token['request_token']) is None
                or _parse(token['prepared_at']) != row.created_at or _parse(token['expires_at']) != row.expires_at
                or row.expires_at != row.created_at + timedelta(seconds=120)
                or any(type(token[k]) is not int or token[k] < 0 for k in ('window_idx','window_seq','actor_seq'))):
            raise ValueError()
        if (type(token['text']) is not str or not 1 <= len(token['text']) <= 1000 or len(token['text'].encode('utf8')) > 4096
            or type(token['engine_build']) is not str or not 1 <= len(token['engine_build']) <= 96
            or any(type(token[k]) is not str or re.fullmatch('[a-f0-9]{64}',token[k]) is None for k in ('case_hash','rules_hash'))
            or any(token[k] is not None and (type(token[k]) is not str or re.fullmatch('[a-f0-9]{64}',token[k]) is None)
                   for k in ('config_hash','caps_hash'))
            or row.status=='prepared' and (row.binding_id is None or token['config_hash'] is None or token['caps_hash'] is None)):
            raise ValueError()
        for item in legal['items']:
            if type(item) is not dict or set(item) != {'selection_id','kind','target_id','cost','resource_id','resource_revision','params','label'}:
                raise ValueError()
            LegalAction(**{k:v for k,v in item.items() if k != 'label'})
            if type(item['label']) is not str or not 1 <= len(item['label']) <= 256: raise ValueError()
        if len({x['selection_id'] for x in legal['items']}) != len(legal['items']): raise ValueError()
        return token, legal
    except (ValueError, KeyError, TypeError, AttributeError):
        raise NightCaseError('game_quarantined', 503) from None


class NightCaseOrchestrator:
    def __init__(self, db, factory, ai, transport=None, *, dispatcher=None):
        if dispatcher is not None:
            from application.night_case_ai_dispatch import NightCaseAIDispatcher
            if type(dispatcher) is not NightCaseAIDispatcher or transport is not None:
                raise ValueError('durable_dispatcher_required')
        self.db, self.factory, self.ai_factory, self.transport = db, factory, ai, transport
        self.dispatcher = dispatcher

    def _tx(self, transaction_factory):
        return (transaction_factory or self.db.transaction)()

    async def create_lobby(self, *, account_id, room_id, command, transaction_factory=None):
        async with self._tx(transaction_factory) as session:
            return await self.factory(session).create_lobby(account_id=account_id, room_id=room_id, command=command)

    async def start_game(self, *, account_id, game_id, command, transaction_factory=None):
        async with self._tx(transaction_factory) as session:
            await operation_fence(session)
            app = self.factory(session)
            await app._principal(account_id)
            parsed = parse_start_request(command)
            try:
                prior = await app._start_prior(account_id, game_id, parsed)
                if prior is not None: return prior
                ai = self.ai_factory(session)
                await ai.acquire_start_config(account_id=account_id)
                prior = await app._start_prior(account_id, game_id, parsed)
                if prior is not None: return prior
                async def before_start(context):
                    options = context.options
                    await ai.start_in_locked_game(account_id=context.actor_id, locked=context.locked,
                        expected_epoch=options['expected_epoch'], now=context.now, mode=options['mode'],
                        staged_credential_id=UUID(options['staged_credential_id']) if options['staged_credential_id'] else None)
                return await app._lobby_command(account_id=account_id, game_id=game_id, command=command,
                    kind='start_game', parsed_start=parsed, before_start=before_start)
            except NightStorageConflict:
                raise NightCaseError('command_conflict') from None

    async def propose_intent(self, *, account_id, game_id, request_id, selection_id=None, text=None, transaction_factory=None):
        if selection_id is not None:
            async with self._tx(transaction_factory) as session:
                return await self.factory(session).propose_intent(account_id=account_id, game_id=game_id,
                    request_id=request_id, selection_id=selection_id, text=text)
        work = await self.prepare_intent(account_id=account_id, game_id=game_id, request_id=request_id,
                                         text=text, transaction_factory=transaction_factory)
        if type(work) is dict: return work
        if self.dispatcher is not None:
            from application.night_case_ai_dispatch import AccountPrincipal
            from storage.night_ai_dispatch import DispatchSource
            result = await self.dispatcher.dispatch(DispatchSource('intent',UUID(str(work.id))),
                actor=AccountPrincipal(account_id), worker_id='intent:'+str(account_id),
                transaction_factory=transaction_factory)
            return result.result
        if work.replayed:
            # Replaying durable prepare is not a dispatch permit or a new
            # inference. T will own restart/reclaim; no fake/live retry here.
            return {'kind':'clarification','code':'intent_pending'}
        result = await self.transport_intent(work)
        return await self.finalize_intent(account_id=account_id, game_id=game_id, request_id=request_id,
                                          transport_result=result, transaction_factory=transaction_factory)

    async def _eligible(self, ai, locked, account_id, now):
        repo = ai.repo
        control = await repo.row(NightAIGameControl, NightAIGameControl.game_id == locked.game.id)
        if control is None or control.current_binding_id is None: return control, None, None
        binding = await repo.binding(control.current_binding_id, lock=False)
        if (binding is None or binding.game_id != locked.game.id or binding.epoch != control.epoch
                or binding.status != 'active' or binding.health != 'ok' or binding.valid_until <= now):
            return control, None, None
        if not await ai._starter_usable(control, locked.game.id): return control, None, None
        profile, revision = await repo.profile_revision(binding.profile_id, binding.profile_revision, lock=False)
        if profile is None or revision is None or not profile.enabled: return control, None, None
        try:
            config = ProfileRevision.decode(revision.config, ai.registry, byok=binding.mode == 'byok')
            caps = BindingCaps.decode(binding.caps)
            if config.config_hash != binding.config_hash or revision.config_hash != binding.config_hash: raise ValueError()
            credential = await repo.credential(revision.credential_id, lock=False) if revision.credential_id else None
            if revision.credential_id and (credential is None or credential.status != 'usable'
                    or credential.expires_at is not None and credential.expires_at <= now): raise ValueError()
            if credential and (credential.scope != profile.scope or credential.game_id != profile.game_id
                    or credential.preset != config.document()['preset']): raise ValueError()
            if config.document()['credential_id'] != (str(revision.credential_id) if revision.credential_id else None): raise ValueError()
            if binding.mode == 'byok':
                if (credential is None or credential.game_id != locked.game.id or profile.scope!='game'
                    or profile.game_id!=locked.game.id or credential.owner_subject!='account:'+str(control.starter_account_id)):
                    raise ValueError()
                owner = UUID(credential.owner_subject[8:])
                if not byok_audience_allowed(owner, 'account:' + str(account_id), frozenset({account_id})): raise ValueError()
            elif binding.mode != 'admin' or profile.scope != 'admin': raise ValueError()
        except (ValueError, TypeError, AttributeError):
            return control, None, None
        return control, binding, caps

    async def _active(self, app, account_id, game_id):
        account, locked, _ = await app._access(account_id, game_id)
        if locked.sealed.lifecycle != 'running': raise NightCaseError('game_not_running')
        seat = await app.session.get(GamePlayer, (game_id, account.id), populate_existing=True)
        if seat is None or seat.status not in AI_PARTICIPATING_STATUSES: raise NightCaseError('unavailable', 404)
        case, rules, state = await app._runtime(locked)
        if state.clock['phase'] not in {'investigation','final_hearing'}:
            raise NightCaseError('game_not_running')
        now = app.clock()
        # Intent preparation must never perform even a system.resume transition.
        # Unapplied outages wait for the ordinary A/W transition path.
        if app.availability_hook is not None:
            decision = await app.availability_hook(TransitionContext(locked,case,rules,now,str(account.id)))
            if not isinstance(decision,AvailabilityDecision) or decision.delayed:
                raise NightCaseError('runtime_delayed',503)
            for outage in decision.completed_outages:
                if not outage.unavailable_from < outage.resumed_at <= now: raise NightCaseError('runtime_delayed',503)
                prior=next((r for r in state.clock['resume_receipts'] if r['outage_id']==outage.outage_id),None)
                payload={'outage_id':outage.outage_id,'unavailable_from':_stamp(outage.unavailable_from),'resumed_at':_stamp(outage.resumed_at)}
                if prior is None: raise NightCaseError('runtime_delayed',503)
                if prior['payload_hash']!=json_hash(payload): raise NightCaseError('game_quarantined',503)
        return account, locked, case, rules, state, now

    @staticmethod
    def _legal(case, rules, state, account_id, now):
        items = []
        for choice in available_actions(case, rules, state, PlayerActor(str(account_id)), now_utc=now):
            if not hasattr(choice, 'quote'): continue
            action = choice.quote
            item = asdict(action)
            item['params'] = json.loads(action.params)
            label = action.kind + (': ' + choice.label if choice.label else '')
            if not 1 <= len(label) <= 256: raise ValueError('intent_menu_bound')
            item['label'] = label
            items.append(item)
        if len(items) > 64: raise ValueError('intent_menu_bound')
        value = {'schema': 'night-ai-legal/1', 'items': items}
        _jsonb_bound(value,32768)
        return value

    async def prepare_intent(self, *, account_id, game_id, request_id, text, transaction_factory=None):
        async with self._tx(transaction_factory) as session:
            await operation_fence(session)
            app = self.factory(session)
            account, aliases = await app._intent_identity(account_id, game_id)
            fingerprint = _envelope(request_id, None, text)
            prior = await app._intent_prior(game_id, aliases, request_id, fingerprint)
            if prior is not None: return prior if type(prior) is dict else _work(prior,replayed=True)
            ai = self.ai_factory(session)
            await ai.repo.config_lock()
            await app.repo.lock_game(game_id)
            prior = await app._intent_prior(game_id, aliases, request_id, fingerprint)
            if prior is not None: return prior if type(prior) is dict else _work(prior,replayed=True)
            if len(request_id) > 96 or text is None or '\x00' in text or len(text.encode('utf8')) > 4096:
                raise NightCaseError('invalid_command', 422)
            account, locked, case, rules, state, now = await self._active(app, account.id, game_id)
            control, binding, caps = await self._eligible(ai, locked, account.id, now)
            player = next(p for p in state.players if p['account_id'] == str(account.id))
            token = {'schema':'night-ai-intent-token/1','request_token':uuid4().hex+uuid4().hex,
                'case_hash':locked.sealed.content_hash,'rules_hash':locked.sealed.rules_hash,'engine_build':locked.sealed.engine_build,
                'window_idx':state.clock['window_idx'],'window_seq':state.clock['window_seq'],'actor_seq':player['actor_seq'],
                'prepared_at':_stamp(now),'expires_at':_stamp(now+timedelta(seconds=120)),'text':text,
                'config_hash':binding.config_hash if binding else None,'caps_hash':json_hash(caps.document()) if caps else None}
            _jsonb_bound(token,8192)
            try: legal = self._legal(case, rules, state, account.id, now)
            except ValueError: legal = {'schema':'night-ai-legal/1','items':[]}
            ready = (type(self.transport) is TestOnlyIntentTransport or self.dispatcher is not None) and binding is not None and bool(legal['items'])
            row = NightAIIntentRequest(id=uuid4(), game_id=game_id, requester_account_id=account.id,
                client_request_id=request_id, fingerprint=fingerprint, epoch=control.epoch if control else 0,
                binding_id=binding.id if binding else None, token=token, legal_candidates=legal,
                status='prepared' if ready else 'finalized', created_at=now, expires_at=now+timedelta(seconds=120),
                finalized_at=None if ready else now, safe_result=null() if ready else copy.deepcopy(CLARIFICATION))
            session.add(row)
            await session.flush()
            return _work(row) if ready else copy.deepcopy(CLARIFICATION)

    async def transport_intent(self, work):
        if type(work) is not PreparedIntent or work.replayed or type(self.transport) is not TestOnlyIntentTransport:
            return None
        payload = {'request_token':work.token['request_token'],'kind':'intent_selection','text':work.token['text'],
                   'choices':[{k:item[k] for k in ('selection_id','kind','label')} for item in work.legal['items']]}
        canonical_json(payload, max_bytes=32768)
        try: return await self.transport.infer(payload)
        except Exception: return None  # no raw provider error enters receipts/logs

    async def finalize_intent(self, *, account_id, game_id, request_id, transport_result, transaction_factory=None):
        async with self._tx(transaction_factory) as session:
            await operation_fence(session)
            app = self.factory(session)
            account, aliases = await app._intent_identity(account_id, game_id)
            ordinary, rows = await NightAIControlRepository(session).intent_rows(game_id, aliases, request_id)
            if len(rows) != 1: raise NightCaseError('unavailable', 404)
            row = rows[0]
            prior = await app._intent_prior(game_id, aliases, request_id, row.fingerprint)
            if type(prior) is dict: return prior
            if self.dispatcher is not None:
                # Runtime bodies enter only through the durable sending permit.
                # Kept public for the explicit pre-transport test seam.
                raise NightCaseError('unavailable', 404)
            ai = self.ai_factory(session)
            await ai.repo.config_lock()
            locked = await app.repo.lock_game(game_id)
            row = await ai.repo.intent(row.id, lock=True)
            prior = await app._intent_prior(game_id, aliases, request_id, row.fingerprint)
            if type(prior) is dict: return prior
            return await self._finalize_prepared_in(session,app,ai,account.id,locked,row,transport_result)

    async def _finalize_prepared_in(self, session, app, ai, account_id, locked, row, transport_result):
        """Caller already owns fence/AI/Game/source locks; never opens/commits a tx."""
        game_id,request_id=row.game_id,row.client_request_id
        token, legal = _decode(row)
        now = app.clock()
        result = copy.deepcopy(CLARIFICATION)
        expired = now >= row.expires_at
        try:
            if expired: raise ValueError()
            account, locked, case, rules, state, _ = await self._active(app, account_id, game_id)
            control, binding, caps = await self._eligible(ai, locked, account_id, now)
            player = next(p for p in state.players if p['account_id'] == str(account_id))
            if (binding is None or binding.id != row.binding_id or control.epoch != row.epoch
                    or token['config_hash'] != binding.config_hash or token['caps_hash'] != json_hash(caps.document())
                    or token['case_hash'] != locked.sealed.content_hash or token['rules_hash'] != locked.sealed.rules_hash
                    or token['engine_build'] != locked.sealed.engine_build
                    or (token['window_idx'],token['window_seq'],token['actor_seq']) !=
                       (state.clock['window_idx'],state.clock['window_seq'],player['actor_seq'])): raise ValueError()
            canonical_json(transport_result, max_bytes=4096)
            if (type(transport_result) is not dict or set(transport_result) != {'request_token','kind','selection_id'}
                    or transport_result['request_token'] != token['request_token'] or transport_result['kind'] != 'intent_selection'):
                raise ValueError()
            selection = transport_result['selection_id']
            saved = [x for x in legal['items'] if x['selection_id'] == selection]
            fresh = [x for x in self._legal(case,rules,state,account_id,now)['items'] if x['selection_id'] == selection]
            if len(saved) != 1 or canonical_json(saved) != canonical_json(fresh): raise ValueError()
            actions = [LegalAction(**{k:v for k,v in item.items() if k != 'label'}) for item in fresh]
            result = await app._create_action_proposal(account,locked,request_id,row.fingerprint,selection,state,actions,
                created_at=row.created_at,expires_at=row.expires_at)
        except (ValueError, NightCaseError):
            result = copy.deepcopy(CLARIFICATION)
        row.status, row.finalized_at, row.safe_result = ('expired' if expired else 'finalized'), now, result
        await session.flush()
        return result
