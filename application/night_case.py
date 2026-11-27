"""Night Case use cases; adapters supply verified account/operator principals.

Each public entry acquires the operation fence before database reads. The caller
owns Database.transaction(); no HTTP, Telegram, provider or background loop lives
here. Domain step is the sole authority for gameplay and AP. Hooks are trusted,
transaction-scoped integrations and must never perform network I/O under locks.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import hmac
import json
import secrets
import re
from functools import lru_cache
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Awaitable, Callable
from uuid import UUID, uuid4

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from domain.address import effective_address_form, parse_address_form
from domain.night_case_engine import Transition, open_counts, start, start_open, step
from domain.night_case_text import chosen_looks, looks_of, public_look
from domain.night_case_projection import CommandIntent, available_actions, project, quote_action
from domain.night_case_state import (KernelState, PlayerActor, SystemActor, RulesSnapshot,
    decode_state, encode_state, engine_build_for, event_scope, parse_command, rules_snapshot)
from domain.frozen_json import freeze, thaw
from application import night_art
from application.night_case_nudges import enqueue_case_nudges
from domain.night_case_v2_format import CompiledCase, compile_v2, load_v2
from domain.night_case_narrative import (ActionContext, ActionProposal, confirm_action, propose_action)
from storage.admin_actions import operation_fence
from storage.guest_accounts import normalize_display_name
from domain.night_case_delivery_state import normalize_say_text
from storage.models import (Account, AccountMerge, Game, GamePlayer, GameCommand,
    NightCase, NightGameSealed, NightLobbyCommand, NightLobbyMessage, NightEvent, NightMessage,
    NightIntentProposal, NightPresence, NightRenderJob, NightRendering, NightRewardClaim,
    Room, RoomMembership)
from storage.night_cases import (NightCaseRepository, NightStorageConflict, SealedGame, canonical_json, json_hash, command_key, public_envelope, MAX_KERNEL_BYTES)


class NightCaseError(ValueError):
    def __init__(self, code: str, status: int = 409):
        self.code, self.status = code, status
        super().__init__(code)


@dataclass(frozen=True)
class FrozenCaseRef:
    case_id: str
    case_version: int
    content_hash: str


@dataclass(frozen=True)
class NightCaseRegistry:
    allowed_cases: frozenset[FrozenCaseRef]
    allowed_timezones: frozenset[str]
    cursor_secret: bytes
    allowed_builds: frozenset[str] = frozenset({"night-case-core/1", "night-case-core/2"})

    def __post_init__(self):
        if type(self.cursor_secret) is not bytes or len(self.cursor_secret) < 32:
            raise ValueError('night_cursor_secret_required')


@dataclass(frozen=True)
class LobbyCommand:
    command_id: str
    expected_lobby_revision: int
    params: dict

    @classmethod
    def parse(cls, raw: dict | 'LobbyCommand') -> 'LobbyCommand':
        if isinstance(raw, cls):
            raw = asdict(raw)
        if type(raw) is not dict or set(raw) != {'command_id','expected_lobby_revision','params'}:
            raise ValueError('invalid_command')
        if type(raw['command_id']) is not str or not 8 <= len(raw['command_id']) <= 64:
            raise ValueError('invalid_command')
        if type(raw['expected_lobby_revision']) is not int or raw['expected_lobby_revision'] < 0 or type(raw['params']) is not dict:
            raise ValueError('invalid_command')
        canonical_json(raw)
        return cls(raw['command_id'],raw['expected_lobby_revision'],copy.deepcopy(raw['params']))


@dataclass(frozen=True)
class OperatorPrincipal:
    """Trusted internal principal, constructed only after existing admin auth/CSRF."""
    operator_id: str
    account_id: UUID | None = None


@dataclass(frozen=True)
class StartRequest:
    command: LobbyCommand
    payload: dict
    payload_hash: str
    options: dict | None


def _lobby_name(display_name, seat: str, taken: set[str]) -> str:
    """A joining player without a free display name sits as «Игрок N» (N is the seat number), never as the seat id."""
    number=int(seat[4:]); base=normalize_display_name(display_name)[:120]
    for candidate in (base, f'Игрок {number}', *(f'Игрок {number}.{k}' for k in range(2, 14))):
        if candidate and candidate.casefold() not in taken: return candidate
    return seat


def parse_start_request(command) -> StartRequest:
    cmd = LobbyCommand.parse(command)
    params = copy.deepcopy(cmd.params)
    options = None
    if params:
        if set(params) != {'ai'} or type(params['ai']) is not dict:
            raise NightCaseError('invalid_command', 422)
        options = params['ai']
        if (set(options) != {'mode', 'expected_epoch', 'staged_credential_id'}
                or type(options['mode']) is not str or options['mode'] not in {'authored', 'admin', 'byok'}
                or type(options['expected_epoch']) is not int or options['expected_epoch'] < 0):
            raise NightCaseError('invalid_command', 422)
        if options['mode'] == 'byok':
            try:
                if type(options['staged_credential_id']) is not str or str(UUID(options['staged_credential_id'])) != options['staged_credential_id']:
                    raise ValueError()
            except (ValueError, TypeError, AttributeError):
                raise NightCaseError('invalid_command', 422) from None
        elif options['staged_credential_id'] is not None:
            raise NightCaseError('invalid_command', 422)
    payload = {'kind': 'start_game', 'expected_lobby_revision': cmd.expected_lobby_revision, 'params': params}
    return StartRequest(cmd, payload, json_hash(payload), options)


@dataclass(frozen=True)
class ValidatedStartContext:
    locked: SealedGame
    case: CompiledCase
    rules: RulesSnapshot
    now: datetime
    actor_id: UUID
    options: dict


@dataclass(frozen=True)
class TransitionContext:
    locked: SealedGame
    case: CompiledCase
    rules: RulesSnapshot
    now: datetime
    actor_key: str
    command_summary: dict | None = None


def _director_command_summary(case: CompiledCase, raw: dict, transition: Transition) -> dict | None:
    """Only the normalized, accepted NPC target crosses the optional story hook."""
    if raw['kind'] != 'talk' or transition.receipt is None or not transition.receipt['accepted']:
        return None
    dialogue_id=raw['params']['dialogue_id']
    dialogue=next((d for d in case.document()['dialogues'] if d['id']==dialogue_id),None)
    if dialogue is None: raise ValueError('validated dialogue disappeared')
    return {'kind':'talk','target_character_id':dialogue['character']}


@dataclass(frozen=True)
class CompletedOutage:
    outage_id: str
    unavailable_from: datetime
    resumed_at: datetime


@dataclass(frozen=True)
class AvailabilityDecision:
    delayed: bool
    completed_outages: tuple[CompletedOutage, ...] = ()


TransitionHook = Callable[[TransitionContext, Transition], Awaitable[None]]
AvailabilityHook = Callable[[TransitionContext], Awaitable[AvailabilityDecision]]


@lru_cache(maxsize=32)
def _compile(content_bytes: bytes) -> CompiledCase:
    return compile_v2(load_v2(content_bytes))


def _registered_case(row) -> CompiledCase:
    """The compiled case of a registered row, verified against its content hash; cached like a game's case."""
    key=(row.case_id,row.version,row.content_hash)
    case=_VERIFIED_CASES.get(key)
    if case is None:
        case=_compile(canonical_json(row.content))
        if (case.case_id,case.case_version,case.content_hash)!=key: raise ValueError('night_content_hash')
        if len(_VERIFIED_CASES)>=_VERIFIED_CASES_MAX: _VERIFIED_CASES.pop(next(iter(_VERIFIED_CASES)))
        _VERIFIED_CASES[key]=case
    return case


def _lobby_counts(case_doc, version):
    """Lobby v1 starts the authored compositions; v2 is free seating for 3..12 players."""
    return [r['players'] for r in case_doc['compositions']] if version==1 else open_counts(case_doc)


def _lobby_heroes(case_doc):
    """Seats of a free-seating lobby: every playable hero with the looks a player may take."""
    return [{'id':c['id'],'title':c['title'],'looks':[public_look(x) for x in looks_of(c)],'multiple':bool(c.get('looks'))}
            for c in case_doc['characters'] if c['can_be_player']]


# (case_id, version, content_hash) -> CompiledCase whose stored content was
# re-hashed once in this process. night_cases content is immutable in SQL and
# night_game_sealed pins exactly this triple, so later reads only confirm the pin.
_VERIFIED_CASES: dict[tuple[str,int,str],CompiledCase]={}
_VERIFIED_CASES_MAX=32


# Pure-function caches for the read path. Keys carry every input: the exact
# case (content hash + compiler), rules hash, kernel hash and viewer.
# KernelState is immutable; projections are stored frozen and every caller gets
# its own plain copy, so no caller can see another's mutations.
_STATES: dict[tuple,KernelState]={}
_PROJECTIONS: dict[tuple,dict]={}


def _remember(cache,key,value,limit):
    if len(cache)>=limit: cache.pop(next(iter(cache)))
    cache[key]=value
    return value


def _projection(case,rules,state,viewer_id=None):
    key=(case.content_hash,case.compiler_version,rules.rules_hash,
        hashlib.sha256(encode_state(state)).hexdigest(),viewer_id)
    frozen=_PROJECTIONS.get(key)
    if frozen is None:
        frozen=_remember(_PROJECTIONS,key,freeze(project(case,rules,state,None if viewer_id is None else PlayerActor(viewer_id))),256)
    return thaw(frozen)


async def historical_aliases(session: AsyncSession, account_id: UUID) -> frozenset[UUID]:
    """Only a matching AccountMerge audit AND immutable merged_into edge prove ancestry."""
    found, frontier = {account_id}, {account_id}
    for _ in range(32):
        audits=list((await session.scalars(select(AccountMerge).where(AccountMerge.main_account_id.in_(frontier)))).all())
        next_frontier=set()
        for audit in audits:
            if audit.merged_account_id in found:
                raise NightCaseError('account_ancestry_invalid',503)
            source=await session.get(Account,audit.merged_account_id,populate_existing=True)
            if source is None or not source.archived or source.merged_into_id != audit.main_account_id or source.merged_at is None:
                raise NightCaseError('account_ancestry_invalid',503)
            next_frontier.add(source.id)
        if not next_frontier:
            return frozenset(found)
        found.update(next_frontier); frontier=next_frontier
    raise NightCaseError('account_ancestry_invalid',503)


def _atomic(method):
    from functools import wraps
    @wraps(method)
    async def wrapped(self,*args,**kwargs):
        # No SAVEPOINT/lookup precedes the shared operational fence.
        await operation_fence(self.session)
        async with self.session.begin_nested():
            try:
                return await method(self,*args,**kwargs)
            except NightStorageConflict as exc:
                raise NightCaseError('command_conflict') from exc
    return wrapped


def _stamp(value: datetime) -> str:
    if not isinstance(value,datetime) or value.tzinfo is None or value.utcoffset()!=timedelta(0):
        raise ValueError('aware UTC clock required')
    return value.isoformat().replace('+00:00','Z')


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace('Z','+00:00'))


def _art_binding(report, metadata):
    """Immutable case-registration binding; no latest-world or Room lookup."""
    if type(report) is not dict: raise NightCaseError('invalid_art_binding',422)
    art=report.get('art')
    if art is None:
        if 'art' in report: raise NightCaseError('invalid_art_binding',422)
        return None
    if (type(art) is not dict or set(art)!={'schema','world','style_pack','manifest_sha256'}
            or art['schema']!='night-art-binding/1' or art['world']!=metadata.get('world')
            or art['style_pack']!=metadata.get('style_pack')
            or any(type(art[k]) is not str or re.fullmatch('[a-z][a-z0-9_]{1,63}',art[k]) is None for k in ('world','style_pack'))
            or type(art['manifest_sha256']) is not str or re.fullmatch('[0-9a-f]{64}',art['manifest_sha256']) is None):
        raise NightCaseError('invalid_art_binding',422)
    return {'manifest_sha256':art['manifest_sha256'],
            'manifest_url':'/app/night/packs/'+art['manifest_sha256']+'/assets.json'}


def _reveal_finale(own,sealed):
    """After the final only: the played variant's picture gets its sealed address."""
    art=(own.get('postmortem') or {}).get('variant_art')
    if type(art) is not dict: return
    digest=sealed.get(art.get('asset_id'))
    own['postmortem']['variant_art']={**art,'url':'/app/night/sealed/'+digest+'.webp'} if digest else None


def _public(case, rules, state, art=None):
    raw=_projection(case,rules,state)
    allowed=('game_id','case_id','flags','locks','observations','board','chronicle','players','npcs','hearing','final','locations','modules','looks')
    result={k:raw[k] for k in allowed if k in raw}
    result['clock']={k:raw['clock'][k] for k in ('timezone','window_idx','window_seq','phase','opened_at','closes_at','freeze_at','forget_at')}
    meta=case.readonly()['meta']
    result['world']=copy.deepcopy(meta.get('world'))
    result['style_pack']=copy.deepcopy(meta.get('style_pack'))
    result['crime_type']=copy.deepcopy(meta.get('crime_type'))
    result['art']=copy.deepcopy(art)
    # Titles follow the party's sealed looks (e.g. «Фотограф-гостья» or «Фотограф-гость»).
    for npc in result['npcs']: npc['title']=raw['looks'][npc['character_id']]['title']
    return result


def _compact_public(public):
    compact={key:copy.deepcopy(public[key]) for key in ('game_id','case_id','clock','players','npcs','hearing','final','world','style_pack','crime_type','art') if key in public}
    # Public-only frontier captures board/flags/materialized content changes
    # without copying the journal or signaling a private stream's activity.
    compact['public_event_seq']=len(public['chronicle'])
    return compact


def _action_art(content,action_id):
    """The picture of the item an action leads to: every outcome grants a record about that one item."""
    action=next((a for a in content['actions'] if a['id']==action_id),None)
    if action is None or not action.get('outcomes'):
        return None
    observations={o['id']:o for o in content['observations']}
    subjects={(observations[e['observation']].get('subject') or {}).get('item')
              for o in action['outcomes'] for e in o['effects'] if e['kind']=='grant_observation'}
    if len(subjects)!=1 or None in subjects:
        return None
    item=next((i for i in content.get('items',[]) if i['id'] in subjects),None)
    return copy.deepcopy(item['art']) if item and item.get('art') else None


def _menu(entries,case=None):
    result=[]
    for entry in entries:
        row=asdict(entry)
        if 'quote' in row:
            row['quote']['params']=json.loads(row['quote']['params'])
            if case is not None and row['quote']['kind']=='act':
                art=_action_art(case.readonly(),row['quote']['params'].get('action_id'))
                if art is not None:
                    row['art']=art
            if case is not None and row['quote']['kind']=='talk':
                content=case.readonly()
                dialogue=next(d for d in content['dialogues'] if d['id']==row['quote']['params']['dialogue_id'])
                title=next(c['title'] for c in content['characters'] if c['id']==dialogue['character'])
                row['npc_title']=title
                row['npc_character_id']=dialogue['character']
        result.append(row)
    return result


class NightCaseApplicationService:
    def __init__(self,session: AsyncSession,clock: Callable[[],datetime],registry: NightCaseRegistry,
                 *,transition_hook: TransitionHook | None=None,availability_hook: AvailabilityHook | None=None,
                 starts_enabled: bool=True):
        self.session,self.clock,self.registry=session,clock,registry
        self.repo=NightCaseRepository(session)
        self.transition_hook,self.availability_hook=transition_hook,availability_hook
        self.starts_enabled=starts_enabled

    async def _principal(self,account_id: UUID) -> Account:
        await operation_fence(self.session)
        try: aid=UUID(str(account_id))
        except (ValueError,TypeError): raise NightCaseError('account_unavailable',403) from None
        row=await self.session.get(Account,aid,populate_existing=True)
        if row is None or row.archived or row.bot_blocked or row.merged_into_id is not None:
            raise NightCaseError('account_unavailable',403)
        return row

    async def _member(self,room_id,account_id,*,lock=False):
        statement=select(RoomMembership).where(RoomMembership.room_id==room_id,RoomMembership.account_id==account_id)
        if lock: statement=statement.with_for_update()
        row=(await self.session.execute(statement.execution_options(populate_existing=True))).scalar_one_or_none()
        if row is None or row.status!='active': raise NightCaseError('unavailable',404)
        return row

    async def _load_case(self,sealed):
        key=(sealed.case_id,sealed.version,sealed.content_hash)
        case=_VERIFIED_CASES.get(key)
        if case is not None:
            pin=await self.repo.case_pin(sealed.case_id,sealed.version)
            if pin is None or pin.content_hash!=sealed.content_hash: raise NightCaseError('game_quarantined',503)
        else:
            row=await self.repo.get_case(sealed.case_id,sealed.version)
            if row is None or row.content_hash!=sealed.content_hash:
                raise NightCaseError('game_quarantined',503)
            try:
                content=canonical_json(row.content)  # json_hash(row.content) is sha256 of exactly these bytes
                if hashlib.sha256(content).hexdigest()!=row.content_hash: raise ValueError('night_content_hash')
                case=_compile(content)
            except (ValueError, KeyError) as exc:
                raise NightCaseError('game_quarantined',503) from exc
            if (case.case_id,case.case_version,case.content_hash)!=key: raise NightCaseError('game_quarantined',503)
            if len(_VERIFIED_CASES)>=_VERIFIED_CASES_MAX: _VERIFIED_CASES.pop(next(iter(_VERIFIED_CASES)))
            _VERIFIED_CASES[key]=case
        try:
            build=engine_build_for(case.readonly()['ruleset_ref'])
            rules=RulesSnapshot.from_document(sealed.rules)
        except (ValueError, KeyError) as exc:
            raise NightCaseError('game_quarantined',503) from exc
        if build not in self.registry.allowed_builds or build!=sealed.engine_build or case.compiler_version!=sealed.compiler_version:
            raise NightCaseError('game_quarantined',503)
        if rules.rules_hash!=sealed.rules_hash: raise NightCaseError('game_quarantined',503)
        return case,rules

    async def _art(self,sealed,case,*,with_sealed=False):
        registered=await self.repo.case_pin(sealed.case_id,sealed.version)
        if registered is None or registered.content_hash!=sealed.content_hash: raise NightCaseError('game_quarantined',503)
        try:
            binding=_art_binding(registered.validation_report,case.readonly()['meta'])
        except NightCaseError as exc: raise NightCaseError('game_quarantined',503) from exc
        if not with_sealed: return binding
        # Pictures withheld until the final (per-variant finales) belong to the bound pack;
        # the game finds them itself from the pack index the asset builder published.
        sealed_map=night_art.sealed_pictures(binding['manifest_sha256'],sealed.content_hash) if binding else {}
        return binding,sealed_map

    async def _runtime(self,locked):
        case,rules=await self._load_case(locked.sealed)
        sealed=locked.sealed
        if sealed.kernel is None: raise NightCaseError('game_not_started')
        encoded=canonical_json(sealed.kernel,max_bytes=MAX_KERNEL_BYTES)
        if hashlib.sha256(encoded).hexdigest()!=sealed.snapshot_hash: raise NightCaseError('game_quarantined',503)
        key=(case.content_hash,case.compiler_version,rules.rules_hash,sealed.snapshot_hash)
        state=_STATES.get(key)
        if state is None:
            try: state=_remember(_STATES,key,decode_state(encoded,case,rules),64)
            except ValueError as exc: raise NightCaseError('game_quarantined',503) from exc
        seats=list((await self.session.scalars(select(GamePlayer).where(GamePlayer.game_id==locked.game.id))).all())
        if {str(s.account_id) for s in seats}!={p['account_id'] for p in state.players}:
            raise NightCaseError('game_quarantined',503)
        return case,rules,state

    def _checked_lobby(self,sealed,case,rules):
        lobby=sealed.lobby
        fields={'version','revision','owner_account_id','case_ref','rules_hash','roster','created_at','title','allowed_counts'}
        try:
            if (type(lobby) is not dict or set(lobby)!=fields or type(lobby['version']) is not int or lobby['version'] not in {1,2}
                    or type(lobby['revision']) is not int or lobby['revision']<0 or json_hash(lobby)!=sealed.snapshot_hash
                    or lobby['case_ref']!={'id':sealed.case_id,'version':sealed.version,'hash':sealed.content_hash}
                    or lobby['rules_hash']!=rules.rules_hash or lobby['title']!=case.readonly()['meta']['title']
                    or lobby['allowed_counts']!=_lobby_counts(case.readonly(),lobby['version'])
                    or type(lobby['roster']) is not list or not 1<=len(lobby['roster'])<=12):
                raise ValueError()
            ids,seats,names,heroes=set(),set(),set(),set()
            row_fields={'account_id','seat','name','address_form','ready'}|({'character_id','look_id'} if lobby['version']==2 else set())
            playable={c['id']:{x['id'] for x in c.get('looks') or ()} for c in case.readonly()['characters'] if c['can_be_player']}
            for row in lobby['roster']:
                if type(row) is not dict or set(row)!=row_fields:
                    raise ValueError()
                if lobby['version']==2:
                    hero,look=row['character_id'],row['look_id']
                    if hero is None:
                        if look is not None: raise ValueError()
                    elif hero not in playable or hero in heroes or (look is not None and look not in playable[hero]):
                        raise ValueError()
                    if hero is not None: heroes.add(hero)
                if (str(UUID(row['account_id']))!=row['account_id'] or row['account_id'] in ids
                        or row['seat'] not in {f'seat{i:02d}' for i in range(1,13)} or row['seat'] in seats
                        or type(row['name']) is not str or not 1<=len(row['name'])<=120
                        or normalize_display_name(row['name'])!=row['name'] or row['name'].casefold() in names
                        or row['address_form'] not in {'m','f','n'} or type(row['ready']) is not bool):
                    raise ValueError()
                ids.add(row['account_id']); seats.add(row['seat']); names.add(row['name'].casefold())
            if lobby['owner_account_id'] not in ids: raise ValueError()
            _stamp(_parse(lobby['created_at']))
        except (ValueError,TypeError,KeyError,AttributeError) as exc:
            raise NightCaseError('game_quarantined',503) from exc
        return copy.deepcopy(lobby)

    async def _access(self,account_id,game_id,*,history=False,shared=False,snapshot=False):
        # shared=True only for strictly read-only callers (no write anywhere in
        # the transaction): FOR SHARE still excludes every writer, readers of
        # one game just stop queueing behind each other.
        account=await self._principal(account_id)
        locked=await self.repo.lock_game(game_id,shared=shared,snapshot=snapshot)
        if locked is None: raise NightCaseError('unavailable',404)
        aliases=await historical_aliases(self.session,account.id) if history else frozenset({account.id})
        if locked.sealed.lifecycle=='lobby':
            await self._member(locked.game.room_id,account.id)
            return account,locked,aliases
        seats=list((await self.session.scalars(select(GamePlayer).where(GamePlayer.game_id==game_id,GamePlayer.account_id.in_(aliases)))).all())
        if not seats: raise NightCaseError('unavailable',404)
        if not history or (locked.sealed.lifecycle not in {'finished','stopped'} and any(s.status!='departed' for s in seats)):
            await self._member(locked.game.room_id,account.id)
        return account,locked,frozenset(s.account_id for s in seats)

    async def register_case(self,*,operator: OperatorPrincipal,content: dict,validation_report: dict,admission='registered') -> FrozenCaseRef:
        await operation_fence(self.session,exclusive=True)
        if not isinstance(operator,OperatorPrincipal) or not isinstance(operator.operator_id,str) or not 1<=len(operator.operator_id)<=119: raise NightCaseError('operator_required',403)
        if operator.account_id is not None: await self._principal(operator.account_id)
        original=load_v2(canonical_json(content)); case=compile_v2(original)
        requested=validation_report
        if type(validation_report) is dict and 'art' not in validation_report:
            # No hand-made binding: the case binds to the pack built for its exact content hash.
            found=night_art.binding_for_case(case.document()['meta'],case.content_hash)
            if found is not None: validation_report={**validation_report,'art':found}
        _art_binding(validation_report,case.document()['meta'])
        ref=FrozenCaseRef(case.case_id,case.case_version,case.content_hash)
        build=engine_build_for(case.document()['ruleset_ref'])
        if build not in self.registry.allowed_builds or admission not in {'registered','rehearsal','retired'}:
            raise NightCaseError('case_unavailable')
        if admission=='rehearsal' and ref not in self.registry.allowed_cases: raise NightCaseError('case_unavailable')
        existing=await self.repo.get_case(ref.case_id,ref.case_version)
        if existing:
            # A repeat registration without art keeps whatever pack the first one found.
            stored=existing.validation_report
            if requested is not validation_report and type(stored) is dict:
                stored={k:v for k,v in stored.items() if k!='art'}
                validation_report=requested
            if existing.content_hash!=ref.content_hash or canonical_json(stored)!=canonical_json(validation_report):
                raise NightCaseError('command_conflict')
            return ref
        report=copy.deepcopy(validation_report)
        await self.repo.register_case(NightCase(case_id=ref.case_id,version=ref.case_version,
            content_hash=ref.content_hash,content=original.document(),compiler_version=case.compiler_version,
            engine_build=build,validation_report=report,registered_at=self.clock(),
            registered_by=operator.account_id,registered_operator_id='operator:'+operator.operator_id,admission=admission))
        return ref

    def _lobby_view(self,locked,account_id,case=None):
        lobby=locked.sealed.lobby
        if lobby is None: raise NightCaseError('game_not_lobby')
        own=next((r for r in lobby['roster'] if r['account_id']==str(account_id)),None)
        open_seating=lobby['version']==2
        seat_keys=('seat','name','ready')+(('character_id','look_id') if open_seating else ())
        view={'game_id':locked.game.id,'mode':'night_case',
            'case':{'id':locked.sealed.case_id,'version':locked.sealed.version,'title':lobby['title']},
            'timezone':locked.sealed.rules['timezone'],'status':locked.sealed.lifecycle,
            'windows':{'slots':list(locked.sealed.rules.get('slots') or []),'count':locked.sealed.rules.get('window_count')},
            'lobby_revision':lobby['revision'],'seats':[{k:r[k] for k in seat_keys} for r in lobby['roster']],
            'self_seat':own['seat'] if own else None,
            'self':{k:own[k] for k in ('name','address_form','ready')} if own else None,
            'allowed_counts':copy.deepcopy(lobby['allowed_counts']),
            'can_start':str(account_id)==lobby['owner_account_id']
            and len(lobby['roster']) in lobby['allowed_counts'] and all(r['ready'] for r in lobby['roster'])}
        if open_seating:
            view['seating']='open'
            if case is not None:
                view['heroes']=_lobby_heroes(case.readonly())
                # Heroes the game always plays (never a seat): only their title and public portrait.
                view['npc_heroes']=[{'id':c['id'],'title':c['title'],'art':copy.deepcopy(looks_of(c)[0].get('art'))}
                    for c in case.readonly()['characters'] if not c['can_be_player']]
        return view

    async def _create_prior(self,room_id,aliases,command_id,fingerprint):
        rows=list((await self.session.scalars(select(NightLobbyCommand).where(
            NightLobbyCommand.room_id==room_id,NightLobbyCommand.original_actor_account_id.in_(aliases),
            NightLobbyCommand.client_command_id==command_id))).all())
        if len(rows)>1: raise NightCaseError('historical_command_ambiguous')
        if rows:
            if rows[0].fingerprint!=fingerprint: raise NightCaseError('command_conflict')
            return copy.deepcopy(rows[0].result)
        return None

    @_atomic
    async def create_lobby(self,*,account_id: UUID,room_id: str,command: LobbyCommand | dict):
        account=await self._principal(account_id); cmd=LobbyCommand.parse(command)
        if set(cmd.params)!={'case_id','case_version','timezone'} or cmd.expected_lobby_revision!=0:
            raise NightCaseError('invalid_command',422)
        if type(cmd.params['case_id']) is not str or type(cmd.params['case_version']) is not int or type(cmd.params['timezone']) is not str:
            raise NightCaseError('invalid_command',422)
        fingerprint=json_hash({'kind':'create_lobby','expected_lobby_revision':0,'params':cmd.params})
        aliases=await historical_aliases(self.session,account.id)
        prior=await self._create_prior(room_id,aliases,cmd.command_id,fingerprint)
        if prior: return prior
        if not self.starts_enabled: raise NightCaseError('night_starts_disabled',503)
        from storage.games import night_room_lock
        await night_room_lock(self.session,room_id)
        prior=await self._create_prior(room_id,aliases,cmd.command_id,fingerprint)
        if prior: return prior
        room=(await self.session.execute(select(Room).where(Room.id==room_id,Room.kind=='standalone').with_for_update())).scalar_one_or_none()
        await self._member(room_id,account.id,lock=True)
        if room is None or room.owner_account_id!=account.id: raise NightCaseError('owner_required',403)
        current=list((await self.session.scalars(select(Game).where(Game.room_id==room_id,Game.is_current.is_(True),Game.mode.in_(['mafia','night_case'])).with_for_update())).all())
        for row in current:
            terminal={'finished','stopped'} if row.mode=='night_case' else {'finished','stopped','interrupted'}
            if row.status not in terminal: raise NightCaseError('active_game_conflict')
        registered=await self.repo.get_case(cmd.params['case_id'],cmd.params['case_version'])
        if registered is None or registered.admission!='rehearsal' or FrozenCaseRef(registered.case_id,registered.version,registered.content_hash) not in self.registry.allowed_cases or cmd.params['timezone'] not in self.registry.allowed_timezones:
            raise NightCaseError('case_unavailable')
        case=_compile(canonical_json(registered.content))
        if registered.engine_build not in self.registry.allowed_builds or case.content_hash!=registered.content_hash:
            raise NightCaseError('case_unavailable')
        for row in current:
            if row.mode=='night_case': row.is_current=False
        await self.session.flush()
        rules=rules_snapshot(cmd.params['timezone']); now=self.clock(); gid=str(uuid4())
        ref={'id':registered.case_id,'version':registered.version,'hash':registered.content_hash}
        lobby={'version':2,'revision':0,'owner_account_id':str(account.id),'case_ref':ref,'rules_hash':rules.rules_hash,
            'roster':[{'account_id':str(account.id),'seat':'seat01','name':normalize_display_name(account.display_name)[:120] or 'Игрок 1',
            'address_form':effective_address_form(account.address_form),'ready':False,'character_id':None,'look_id':None}],
            'created_at':_stamp(now),'title':case.document()['meta']['title'],
            'allowed_counts':_lobby_counts(case.document(),2)}
        game=Game(id=gid,room_id=room_id,mode='night_case',status='lobby',phase='lobby',revision=0,
            state=public_envelope(ref,'lobby',{'lobby_revision':0}),is_current=True)
        self.session.add(game); await self.session.flush()
        sealed=await self.repo.create_sealed(NightGameSealed(game_id=gid,case_id=registered.case_id,version=registered.version,
            content_hash=registered.content_hash,rules=rules.document(),rules_hash=rules.rules_hash,
            engine_build=registered.engine_build,compiler_version=registered.compiler_version,storage_version=1,
            kernel=None,lobby=lobby,snapshot_hash=json_hash(lobby),storage_revision=0,lifecycle='lobby',interruption=None))
        from storage.night_ai_control import NightAIControlRepository
        await NightAIControlRepository(self.session).ensure_empty_lobby_control_locked(gid, now)
        locked=SealedGame(game,sealed); view=self._lobby_view(locked,account.id,case)
        receipt={'command_id':cmd.command_id,'accepted':True,'code':'accepted','lobby_revision':0,'self_seat':'seat01'}
        result={'receipt':receipt,'view':view}
        await self.repo.put_lobby_receipt(NightLobbyCommand(room_id=room_id,original_actor_account_id=account.id,
            client_command_id=cmd.command_id,kind='create_lobby',fingerprint=fingerprint,game_id=gid,result=result,created_at=now))
        return result

    async def _lobby_command(self,*,account_id,game_id,command,kind,parsed_start=None,before_start=None):
        account=await self._principal(account_id); cmd=LobbyCommand.parse(command)
        params=copy.deepcopy(cmd.params)
        if kind=='set_ready':
            if set(params)!={'name','address_form','ready'} or type(params['ready']) is not bool:
                raise NightCaseError('invalid_command',422)
            params['name']=normalize_display_name(params['name'])
            if not 1<=len(params['name'])<=120: raise NightCaseError('invalid_command',422)
            params['address_form']=parse_address_form(params['address_form'])
        elif kind=='take_seat':
            if (set(params)!={'character_id','look_id'} or not all(v is None or type(v) is str for v in params.values())
                    or (params['character_id'] is None and params['look_id'] is not None)):
                raise NightCaseError('invalid_command',422)
        elif kind=='start_game' and parsed_start is not None:
            if not isinstance(parsed_start,StartRequest) or parse_start_request(command)!=parsed_start or before_start is None:
                raise NightCaseError('invalid_command',422)
        elif params: raise NightCaseError('invalid_command',422)
        payload={'kind':kind,'expected_lobby_revision':cmd.expected_lobby_revision,'params':params}
        room_id=await self.session.scalar(select(Game.room_id).where(Game.id==game_id,Game.mode=='night_case'))
        if room_id is None: raise NightCaseError('unavailable',404)
        from storage.games import night_room_lock
        await night_room_lock(self.session,room_id)
        room=(await self.session.execute(select(Room).where(Room.id==room_id).with_for_update())).scalar_one()
        locked=await self.repo.lock_game(game_id)
        prior=await self.repo.command_receipt(game_id,str(account.id),cmd.command_id,json_hash(payload))
        if prior: return copy.deepcopy(prior.result)
        await self._member(room_id,account.id,lock=True)
        if locked.sealed.lifecycle!='lobby' or locked.sealed.lobby is None:
            raise NightCaseError('game_interrupted' if locked.sealed.lifecycle=='interrupted' else 'game_not_lobby')
        case,rules=await self._load_case(locked.sealed)
        lobby=self._checked_lobby(locked.sealed,case,rules)
        if cmd.expected_lobby_revision!=lobby['revision']: raise NightCaseError('actor_stale')
        own=next((r for r in lobby['roster'] if r['account_id']==str(account.id)),None)
        now=self.clock(); changed=False
        if kind=='join_lobby':
            if own is None:
                if len(lobby['roster'])>=12: raise NightCaseError('lobby_full')
                used={r['seat'] for r in lobby['roster']}; seat=next(f'seat{i:02d}' for i in range(1,13) if f'seat{i:02d}' not in used)
                name=_lobby_name(account.display_name, seat, {r['name'].casefold() for r in lobby['roster']})
                own={'account_id':str(account.id),'seat':seat,'name':name,'address_form':effective_address_form(account.address_form),'ready':False}
                if lobby['version']==2: own.update(character_id=None,look_id=None)
                lobby['roster'].append(own); changed=True
        elif kind=='leave_lobby':
            if own is not None:
                if str(account.id)==lobby['owner_account_id'] and len(lobby['roster'])>1: raise NightCaseError('owner_required',403)
                lobby['roster'].remove(own); changed=True; own=None
                if not lobby['roster']:
                    locked.sealed.lifecycle='stopped'; locked.game.is_current=False
        elif kind=='set_ready':
            if own is None: raise NightCaseError('unavailable',404)
            if any(r['account_id']!=str(account.id) and r['name'].casefold()==params['name'].casefold() for r in lobby['roster']):
                raise NightCaseError('duplicate_name')
            own.update(params); changed=True
        elif kind=='take_seat':
            if own is None: raise NightCaseError('unavailable',404)
            if lobby['version']!=2: raise NightCaseError('invalid_command',422)
            hero,look=params['character_id'],params['look_id']
            if hero is not None:
                found=next((c for c in case.readonly()['characters'] if c['id']==hero and c['can_be_player']),None)
                if found is None or (look is not None and look not in {x['id'] for x in found.get('looks') or ()}):
                    raise NightCaseError('invalid_command',422)
                if any(r is not own and r['character_id']==hero for r in lobby['roster']): raise NightCaseError('seat_taken')
            if (own['character_id'],own['look_id'])!=(hero,look):
                own.update(character_id=hero,look_id=look,ready=False); changed=True
        elif kind=='start_game':
            if not self.starts_enabled: raise NightCaseError('night_starts_disabled',503)
            if room.owner_account_id!=account.id or lobby['owner_account_id']!=str(account.id): raise NightCaseError('owner_required',403)
            if len(lobby['roster']) not in lobby['allowed_counts'] or (lobby['version']==1 and len(lobby['roster']) not in {4,5,8,12}):
                raise NightCaseError('unsupported_count')
            if not all(r['ready'] for r in lobby['roster']): raise NightCaseError('players_not_ready')
            for r in lobby['roster']:
                participant=await self._principal(UUID(r['account_id']))
                await self._member(room_id,participant.id)
            case,rules=await self._load_case(locked.sealed)
            if self.availability_hook is not None:
                availability=await self.availability_hook(TransitionContext(locked,case,rules,now,str(account.id)))
                if not isinstance(availability,AvailabilityDecision) or availability.delayed:
                    raise NightCaseError('runtime_delayed',503)
                # New games have no historical outage to replay into their clock.
            pool=[f'Житель {i}' for i in range(1,33)]
            if lobby['version']==2:
                roster={'players':[{'account_id':r['account_id'],'display_name':r['name'],'character_id':r['character_id'],
                    'look_id':r['look_id']} for r in lobby['roster']],'npc_name_pool':pool}
                try: transition=start_open(case,rules,roster,game_id=game_id,seed=secrets.randbits(63),now_utc=now)
                except ValueError as exc:
                    if str(exc)=='no variant for seats': raise NightCaseError('seats_unsolvable') from exc
                    raise
            else:
                roster={'players':[{'account_id':r['account_id'],'display_name':r['name']} for r in lobby['roster']],'npc_name_pool':pool}
                transition=start(case,rules,roster,game_id=game_id,seed=secrets.randbits(63),now_utc=now)
            locked.game.started_at=now
            if before_start is not None:
                options=parsed_start.options or {'mode':'admin','expected_epoch':0,'staged_credential_id':None}
                await before_start(ValidatedStartContext(locked,case,rules,now,account.id,options))
            else:
                from storage.night_ai_control import NightAIControlRepository
                await NightAIControlRepository(self.session).finalize_authored_starter_locked(game_id,account.id,now)
            for r in lobby['roster']:
                self.session.add(GamePlayer(game_id=game_id,account_id=UUID(r['account_id']),seat=r['seat'],status='active',
                    public_state={'name':r['name'],'seat':r['seat'],'status':'active'},private_state={},joined_at=now))
            await self.session.flush()
            view=self._lobby_view(locked,account.id,case)
            view['status']='running'; view['can_start']=False
            await self._persist(locked,case,rules,transition,now,str(account.id))
            result={'receipt':{'command_id':cmd.command_id,'accepted':True,'code':'accepted','lobby_revision':lobby['revision'],
                'self_seat':own['seat'] if own else None},'view':view}
            await self.repo.put_command_receipt(game_id=game_id,actor_key=str(account.id),actor_account_id=account.id,
                client_command_id=cmd.command_id,kind=kind,payload=payload,result=result,status='applied',now=now)
            return result
        if changed:
            from application.rooms import RoomApplicationService
            RoomApplicationService.touch_open(room)   # lobby activity keeps an open table listed (real time)
            lobby['revision']+=1
            await self.repo.write_snapshot(locked,expected_storage_revision=locked.sealed.storage_revision,
                kernel=None,lobby=lobby,snapshot_hash=json_hash(lobby),lifecycle=locked.sealed.lifecycle)
            await self.repo.sync_public(locked,projection={'lobby_revision':lobby['revision']},phase=locked.sealed.lifecycle,
                public_revision=locked.game.revision+1)
        view=self._lobby_view(locked,account.id,case)
        result={'receipt':{'command_id':cmd.command_id,'accepted':True,'code':'accepted','lobby_revision':lobby['revision'],
            'self_seat':own['seat'] if own else None},'view':view}
        await self.repo.put_command_receipt(game_id=game_id,actor_key=str(account.id),actor_account_id=account.id,
            client_command_id=cmd.command_id,kind=kind,payload=payload,result=result,status='applied',now=now)
        return result

    # Lobby talk («Обсуждение», mockup 4): the last lines in the lobby view; only players at the table write.
    LOBBY_CHAT_SHOWN=50
    LOBBY_CHAT_BURST=8          # lines per sender in LOBBY_CHAT_WINDOW
    LOBBY_CHAT_WINDOW=timedelta(seconds=60)

    async def _lobby_chat(self,game_id,aliases):
        rows=list((await self.session.scalars(select(NightLobbyMessage).where(NightLobbyMessage.game_id==game_id)
            .order_by(NightLobbyMessage.seq.desc()).limit(self.LOBBY_CHAT_SHOWN))).all())
        return [self._lobby_line(row,aliases) for row in reversed(rows)]

    @staticmethod
    def _lobby_line(row,aliases):
        return {'id':row.id,'name':row.name,'character_id':row.character_id,'look_id':row.look_id,'text':row.text,
            'at':_stamp(row.created_at),'mine':row.sender_account_id in aliases}

    @_atomic
    async def post_lobby_message(self,*,account_id,game_id,command):
        account=await self._principal(account_id)
        if type(command) is not dict or set(command)!={'command_id','text'}: raise NightCaseError('invalid_command',422)
        command_id=command['command_id']
        if type(command_id) is not str or not 8<=len(command_id)<=64: raise NightCaseError('invalid_command',422)
        try: line=normalize_say_text(command['text']).strip()
        except ValueError: raise NightCaseError('invalid_command',422) from None
        if not 1<=len(line)<=500: raise NightCaseError('invalid_command',422)
        digest=hashlib.sha256(line.encode('utf-8')).hexdigest()
        locked=await self.repo.lock_game(game_id)
        if locked is None or locked.game.mode!='night_case': raise NightCaseError('unavailable',404)
        await self._member(locked.game.room_id,account.id)
        aliases=await historical_aliases(self.session,account.id)
        prior=(await self.session.execute(select(NightLobbyMessage).where(NightLobbyMessage.game_id==game_id,
            NightLobbyMessage.sender_account_id==account.id,NightLobbyMessage.command_id==command_id))).scalar_one_or_none()
        if prior is not None:
            if prior.text_hash!=digest: raise NightCaseError('command_conflict')
            return {'message':self._lobby_line(prior,aliases),'chat':await self._lobby_chat(game_id,aliases)}
        if locked.sealed.lifecycle!='lobby' or locked.sealed.lobby is None: raise NightCaseError('game_not_lobby')
        own=next((r for r in locked.sealed.lobby['roster'] if r['account_id']==str(account.id)),None)
        if own is None: raise NightCaseError('unavailable',404)
        now=self.clock()
        recent=await self.session.scalar(select(func.count()).select_from(NightLobbyMessage).where(NightLobbyMessage.game_id==game_id,
            NightLobbyMessage.sender_account_id==account.id,NightLobbyMessage.created_at>now-self.LOBBY_CHAT_WINDOW))
        if recent>=self.LOBBY_CHAT_BURST: raise NightCaseError('rate_limited',429)
        # The game row is held FOR UPDATE: the next number is unique and follows the order of writes.
        seq=(await self.session.scalar(select(func.max(NightLobbyMessage.seq)).where(NightLobbyMessage.game_id==game_id)) or 0)+1
        row=NightLobbyMessage(game_id=game_id,id=str(uuid4()),seq=seq,command_id=command_id,sender_account_id=account.id,
            name=own['name'],character_id=own.get('character_id'),look_id=own.get('look_id'),text=line,text_hash=digest,created_at=now)
        self.session.add(row); await self.session.flush()
        return {'message':self._lobby_line(row,aliases),'chat':await self._lobby_chat(game_id,aliases)}

    @_atomic
    async def join_lobby(self,*,account_id,game_id,command):
        return await self._lobby_command(account_id=account_id,game_id=game_id,command=command,kind='join_lobby')

    @_atomic
    async def leave_lobby(self,*,account_id,game_id,command):
        return await self._lobby_command(account_id=account_id,game_id=game_id,command=command,kind='leave_lobby')

    @_atomic
    async def set_ready(self,*,account_id,game_id,command):
        return await self._lobby_command(account_id=account_id,game_id=game_id,command=command,kind='set_ready')

    @_atomic
    async def take_seat(self,*,account_id,game_id,command):
        return await self._lobby_command(account_id=account_id,game_id=game_id,command=command,kind='take_seat')

    @_atomic
    async def start_game(self,*,account_id,game_id,command):
        return await self._lobby_command(account_id=account_id,game_id=game_id,command=command,kind='start_game')

    async def _start_prior(self,account_id,game_id,parsed):
        account=await self._principal(account_id)
        if not await self.session.scalar(select(exists().where(Game.id==game_id,Game.mode=='night_case'))):
            raise NightCaseError('unavailable',404)
        aliases=await historical_aliases(self.session,account.id)
        found=[]
        for actor in aliases:
            prior=await self.repo.command_receipt(game_id,str(actor),parsed.command.command_id,parsed.payload_hash)
            if prior: found.append(prior.result)
        if len(found)>1: raise NightCaseError('historical_command_ambiguous')
        return copy.deepcopy(found[0]) if found else None

    async def prove_original_starter(self,locked):
        """Only immutable accepted start evidence, never current Room ownership."""
        _,_,state=await self._runtime(locked)
        rows=list((await self.session.scalars(select(GameCommand).where(GameCommand.game_id==locked.game.id,
            GameCommand.kind=='start_game',GameCommand.status=='applied').execution_options(populate_existing=True))).all())
        try:
            if len(rows)!=1: raise ValueError()
            row=rows[0]; payload=row.payload; actor=str(row.actor_account_id)
            seat=await self.session.get(GamePlayer,(locked.game.id,row.actor_account_id),populate_existing=True) if row.actor_account_id else None
            if (row.actor_account_id is None or actor not in {p['account_id'] for p in state.players}
                or set(payload)!={'client_command_id','actor_key','command','payload_hash'}
                or payload['actor_key']!=actor or payload['command']['kind']!='start_game'
                or row.id!=command_key(locked.game.id,actor,payload['client_command_id'])
                or json_hash(payload['command'])!=payload['payload_hash']
                or row.result['receipt']['command_id']!=payload['client_command_id']
                or row.result['receipt']['accepted'] is not True or row.result['receipt']['code']!='accepted'
                or row.result['view']['game_id']!=locked.game.id or seat is None
                or row.result['receipt']['self_seat']!=seat.seat or row.error is not None
                or locked.game.started_at is None or row.created_at!=locked.game.started_at
                or row.processed_at!=locked.game.started_at): raise ValueError()
            parsed=parse_start_request({'command_id':payload['client_command_id'],
                'expected_lobby_revision':payload['command']['expected_lobby_revision'],'params':payload['command']['params']})
            if parsed.payload!=payload['command']: raise ValueError()
            return UUID(actor)
        except (ValueError,TypeError,KeyError,AttributeError):
            raise NightCaseError('starter_unproven') from None

    async def _intent_identity(self,account_id,game_id):
        account=await self._principal(account_id)
        if not await self.session.scalar(select(exists().where(Game.id==game_id,Game.mode=='night_case'))):
            raise NightCaseError('unavailable',404)
        return account,await historical_aliases(self.session,account.id)

    async def _intent_prior(self,game_id,aliases,request_id,fingerprint):
        from storage.night_ai_control import NightAIControlRepository
        ordinary,prepared=await NightAIControlRepository(self.session).intent_rows(game_id,aliases,request_id)
        actors={str(r.original_actor_account_id) for r in ordinary}|{str(r.requester_account_id) for r in prepared}
        if len(actors)>1: raise NightCaseError('historical_command_ambiguous')
        if len(ordinary)>1 or len(prepared)>1: raise NightCaseError('game_quarantined',503)
        if any(r.input_hash!=fingerprint for r in ordinary) or any(r.fingerprint!=fingerprint for r in prepared):
            raise NightCaseError('command_conflict')
        result={'kind':'proposal','proposal':copy.deepcopy(ordinary[0].proposal['task2'])} if ordinary else None
        if prepared:
            row=prepared[0]
            if ordinary and (row.status!='finalized' or canonical_json(row.safe_result)!=canonical_json(result)):
                raise NightCaseError('game_quarantined',503)
            if row.status=='prepared': return row
            value=copy.deepcopy(row.safe_result)
            if (type(value) is not dict or value.get('kind') not in {'proposal','clarification'}
                or (value['kind']=='proposal' and not ordinary)
                or (value['kind']=='clarification' and (set(value)!={'kind','code'} or value['code']!='choose_available_action'))):
                raise NightCaseError('game_quarantined',503)
            return value
        return result

    async def _persist(self,locked,case,rules,transition: Transition,now,actor_key,command_id=None,command_summary=None):
        # Decode the exact bytes before persistence, including all strict profile checks.
        encoded=encode_state(transition.state); state=decode_state(encoded,case,rules); doc=state.document()
        public=_public(case,rules,state,await self._art(locked.sealed,case))
        if public['hearing']:
            public['hearing'].pop('votes',None)
        old_players={str(r.account_id):r for r in (await self.session.scalars(select(GamePlayer).where(GamePlayer.game_id==locked.game.id))).all()}
        if set(old_players)!={p['account_id'] for p in doc['players']}: raise NightCaseError('game_quarantined',503)
        # A new departure marker is captured inclusive of this transition under the Game lock.
        for player in doc['players']:
            old=old_players[player['account_id']]
            if old.status!='departed' and player['status']=='departed':
                frozen=project(case,rules,state,PlayerActor(player['account_id']))
                own=frozen['self']; own.pop('private_events',None); own.pop('receipts',None); own.pop('nearby',None)
                frozen_public=copy.deepcopy(public); frozen_public.pop('chronicle',None)
                marker={'version':1,'original_account_id':player['account_id'],
                    'public_seq':len(doc['public']['chronicle']),
                    'self_seq':sum(e['audience'].get('ids')==[player['account_id']] for e in doc['private_events']),
                    'sender_actor_seq':{p['account_id']:p['actor_seq'] for p in doc['players']},
                    'frozen_view':{'public':frozen_public,'self':own}}
                await self.repo.put_command_receipt(game_id=locked.game.id,actor_key='system:departure:'+player['account_id'],
                    actor_account_id=None,client_command_id='departure-cutoff',kind='night.departure_cutoff',
                    payload={'original_account_id':player['account_id']},result=marker,status='applied',now=now)
            old.status=player['status']
            old.public_state={'name':player['name'],'seat':old.seat,'status':player['status']}
        lifecycle='finished' if doc['clock']['phase']=='finished' else 'running'
        before=copy.deepcopy(locked.sealed.kernel) if locked.sealed.kernel else None
        await self.repo.write_snapshot(locked,expected_storage_revision=locked.sealed.storage_revision,kernel=doc,lobby=None,
            snapshot_hash=hashlib.sha256(encoded).hexdigest(),lifecycle=lifecycle)
        await self.repo.append_events([NightEvent(game_id=locked.game.id,event_id=e['event_id'],scope=event_scope(e['audience']),
            audience_seq=e['audience_seq'],window_idx=e['window_idx'],kind=e['kind'],payload=e['payload'],created_at=now) for e in transition.events])
        await self.repo.append_messages([NightMessage(game_id=locked.game.id,id=m['id'],command_id=command_id,
            thread_key=m['thread_key'],channel=m['channel'],sender_account_id=UUID(m['sender_account_id']),
            recipients=m['recipient_account_ids'],window_idx=m['window_idx'],text=m['text'],text_hash=m['text_hash'],created_at=now) for m in transition.messages])
        compact=_compact_public(public)
        await self.repo.sync_public(locked,projection=compact,phase=doc['clock']['phase'],public_revision=locked.game.revision+1)
        due=transition.due
        await self.repo.project_deadline(game_id=locked.game.id,due_at=_parse(due['at']) if due else None,timer_seq=doc['clock']['timer_seq'])
        if lifecycle=='finished':
            locked.game.ended_at=now
            for fact in doc['final']['reward_facts']:
                ids=sorted(k['observation_id'] for k in doc['knowledge'] if k['account_id']==fact['account_id'])
                # Existing immutable claims are checked, never recomputed with a later clock.
                prior=await self.session.get(NightRewardClaim,(locked.game.id,UUID(fact['account_id']),'case_result'))
                if prior:
                    if canonical_json(prior.reward_facts)!=canonical_json(fact) or prior.seen_observation_ids!=ids:
                        raise NightCaseError('game_quarantined',503)
                else:
                    await self.repo.put_reward(NightRewardClaim(game_id=locked.game.id,original_account_id=UUID(fact['account_id']),
                        kind='case_result',reward_facts=fact,seen_observation_ids=ids,formula_version=1,created_at=now))
        if self.transition_hook:
            await self.transition_hook(TransitionContext(locked,case,rules,now,actor_key,command_summary),transition)
        # Private Telegram nudges: public facts only, deduped, delivered by the bot (MQB-012 stage 11).
        await enqueue_case_nudges(self.session,game=locked.game,case_doc=case.readonly(),rules_doc=rules.document(),
            before=before,after=doc,messages=transition.messages,events=transition.events,actor_key=actor_key,now=now)
        await self.session.flush()
        return state

    async def _availability(self,locked,case,rules,state,now,actor_key):
        if self.availability_hook is None: return state
        decision=await self.availability_hook(TransitionContext(locked,case,rules,now,actor_key))
        if not isinstance(decision,AvailabilityDecision): raise NightCaseError('runtime_delayed',503)
        if decision.delayed: raise NightCaseError('runtime_delayed',503)
        for outage in decision.completed_outages:
            if not outage.unavailable_from < outage.resumed_at <= now:
                raise NightCaseError('runtime_delayed',503)
            doc=state.document(); raw={'command_id':'resume-'+hashlib.sha256(outage.outage_id.encode()).hexdigest()[:56],
                'kind':'system.resume','window_seq':doc['clock']['window_seq'],'timer_seq':doc['clock']['timer_seq'],
                'params':{'outage_id':outage.outage_id,'unavailable_from':_stamp(outage.unavailable_from),'resumed_at':_stamp(outage.resumed_at)}}
            prior=next((r for r in doc['clock']['resume_receipts'] if r['outage_id']==outage.outage_id),None)
            if prior:
                if prior['payload_hash']!=json_hash(raw['params']):
                    raise NightCaseError('game_quarantined',503)
                continue
            # A prior refusal is also an immutable receipt; a changed timer must
            # not reuse this outage's stable ID for a different command.
            existing=await self.session.get(GameCommand,command_key(locked.game.id,'system',raw['command_id']))
            if existing is not None:
                if existing.payload['command']['params'] != raw['params']:
                    raise NightCaseError('game_quarantined',503)
                continue
            # The logical resume happened at the immutable outage end. Its SQL
            # audit is written now; the following player/tick still uses now.
            transition=step(case,rules,state,SystemActor(),raw,now_utc=outage.resumed_at)
            state=await self._persist(locked,case,rules,transition,now,'system',raw['command_id'])
            result={'receipt':transition.receipt,'caused_event_ids':[],'caused_message_ids':[]}
            await self.repo.put_command_receipt(game_id=locked.game.id,actor_key='system',actor_account_id=None,
                client_command_id=raw['command_id'],kind='system.resume',payload=raw,result=result,
                status='applied' if transition.receipt['accepted'] else 'rejected',now=now)
        return state

    @_atomic
    async def execute(self,*,account_id,game_id,command):
        account,locked,aliases=await self._access(account_id,game_id)
        actor=PlayerActor(str(account.id))
        # Normalize the closed supported command envelope before replay. Pinned
        # case/build/state checks belong AFTER an owned committed receipt.
        try: cmd=parse_command(command,actor,ruleset_version=2)
        except ValueError as exc: raise NightCaseError('invalid_command',422) from exc
        raw=cmd.document()
        prior=await self.repo.command_receipt(game_id,str(account.id),raw['command_id'],json_hash(raw))
        if prior: return copy.deepcopy(prior.result)
        if locked.sealed.lifecycle in {'interrupted','stopped','lobby'}: raise NightCaseError('game_interrupted' if locked.sealed.lifecycle=='interrupted' else 'game_not_running')
        case,rules,state=await self._runtime(locked); now=self.clock(); _stamp(now)
        try: cmd=parse_command(raw,actor,ruleset_version=case.readonly()['ruleset_ref']['version'])
        except ValueError as exc: raise NightCaseError('invalid_command',422) from exc
        state=await self._availability(locked,case,rules,state,now,str(account.id))
        transition=step(case,rules,state,actor,cmd,now_utc=now)
        await self._persist(locked,case,rules,transition,now,str(account.id),raw['command_id'],
            _director_command_summary(case,raw,transition))
        allowed_events=[e['event_id'] for e in transition.events if event_scope(e['audience']) in {'public','account:'+str(account.id)}]
        result={'receipt':{'command_id':raw['command_id'],**transition.receipt},'caused_event_ids':allowed_events,
            'caused_message_ids':[m['id'] for m in transition.messages if str(account.id) in m['recipient_account_ids']]}
        await self.repo.put_command_receipt(game_id=game_id,actor_key=str(account.id),actor_account_id=account.id,
            client_command_id=raw['command_id'],kind=raw['kind'],payload=raw,result=result,
            status='applied' if transition.receipt['accepted'] else 'rejected',now=now)
        return result

    async def _departure(self,locked,state,original_id):
        key=command_key(locked.game.id,'system:departure:'+str(original_id),'departure-cutoff')
        row=await self.session.get(GameCommand,key)
        if row is None or row.kind!='night.departure_cutoff' or row.actor_account_id is not None:
            raise NightCaseError('game_quarantined',503)
        doc=state.document(); value=copy.deepcopy(row.result)
        fields={'version','original_account_id','public_seq','self_seq','sender_actor_seq','frozen_view'}
        roster={p['account_id']:p['actor_seq'] for p in doc['players']}
        valid=(type(value) is dict and set(value)==fields and type(value['version']) is int and value['version']==1
            and value['original_account_id']==str(original_id) and type(value['sender_actor_seq']) is dict
            and set(value['sender_actor_seq'])==set(roster)
            and all(type(v) is int and 0<=v<=roster[k] for k,v in value['sender_actor_seq'].items())
            and all(type(value[k]) is int and value[k]>=0 for k in ('public_seq','self_seq'))
            and type(value['frozen_view']) is dict and set(value['frozen_view'])=={'public','self'}
            and type(value['frozen_view']['self']) is dict and type(value['frozen_view']['public']) is dict
            and value['frozen_view']['self'].get('account_id')==str(original_id))
        if not valid: raise NightCaseError('game_quarantined',503)
        frozen_public=value['frozen_view']['public']; frozen_self=value['frozen_view']['self']
        public_fields={'game_id','case_id','clock','flags','locks','observations','board','players','npcs','hearing','final','locations','modules','world','style_pack','crime_type','art','looks'}
        self_fields={'account_id','character_id','status','location','ap','actor_seq','knowledge_revision','faction','goal','secrets','truth','knowledge','observations','dialogue_cursors','postmortem','modules','communication','personal','role','finished_window','final_ballot'}
        own_max=sum(e['audience'].get('ids')==[str(original_id)] for e in doc['private_events'])
        if (set(frozen_public)-public_fields or set(frozen_self)-self_fields
                or frozen_public.get('game_id')!=locked.game.id or frozen_self.get('status')!='departed'
                or type(frozen_public.get('clock')) is not dict
                or set(frozen_public['clock'])!={'timezone','window_idx','window_seq','phase','opened_at','closes_at','freeze_at','forget_at'}
                or value['public_seq']>len(doc['public']['chronicle']) or value['self_seq']>own_max):
            raise NightCaseError('game_quarantined',503)
        return value

    @staticmethod
    def _history_selection(locked,aliases,original_account_id):
        if original_account_id is None: return None
        if locked.sealed.lifecycle not in {'finished','stopped'}:
            raise NightCaseError('unavailable',404)
        try: selected=UUID(str(original_account_id))
        except (ValueError,TypeError,AttributeError): raise NightCaseError('unavailable',404) from None
        if selected not in aliases: raise NightCaseError('unavailable',404)
        return selected

    async def get_view(self,*,account_id,game_id,original_account_id=None):
        # Lock-free first: the view is a function of the sealed row plus rows that
        # every game writer changes together with storage_revision (seats, cutoffs)
        # or that are immutable (case). ACL rows are read after the sealed row, so
        # they are never older than the state. If any game write committed while
        # we read, the revision moved: redo the view under FOR SHARE, which
        # excludes writers exactly like the old FOR UPDATE did.
        result,locked=await self._view(account_id,game_id,original_account_id,snapshot=True)
        revision=await self.session.scalar(select(NightGameSealed.storage_revision).where(NightGameSealed.game_id==game_id))
        if revision==locked.sealed.storage_revision: return result
        result,_=await self._view(account_id,game_id,original_account_id,snapshot=False)
        return result

    # Presence (owner decision 2026-11-27): having the case open is «Я здесь». The client reports that the case is open;
    # the server keeps the time for «в сети / был недавно» and, once per window, marks the seat present in the case with
    # the same free «seen» move the button made, so a player who only reads is not taken for gone (fog, idle table).
    # A paused table is not woken by this: there «Я здесь» stays a deliberate press.
    PRESENCE_STEP=timedelta(minutes=1)

    async def mark_present(self,*,account_id,game_id):
        account,locked,_=await self._access(account_id,game_id,snapshot=True)
        now=self.clock(); _stamp(now)
        if locked.sealed.lifecycle!='running': return {'marked':False}
        await self.session.execute(pg_insert(NightPresence).values(game_id=game_id,account_id=account.id,seen_at=now)
            .on_conflict_do_update(index_elements=[NightPresence.game_id,NightPresence.account_id],set_={'seen_at':now},
                where=NightPresence.seen_at<=now-self.PRESENCE_STEP))
        case,rules,state=await self._runtime(locked)
        player=next((p for p in state.players if p['account_id']==str(account.id)),None)
        clock=state.clock
        if (player is None or player['status'] not in {'active','fog','ghost'} or clock['phase'] not in {'investigation','final_hearing'}
                or player['last_seen_window']==clock['window_idx'] or now>=_parse(clock['closes_at'])):
            return {'marked':False}
        # One id per seat, window and own move count: a replay is the same command, a later move makes a new one.
        command_id=hashlib.sha256(f"presence:{game_id}:{account.id}:{clock['window_seq']}:{player['actor_seq']}".encode()).hexdigest()
        result=await self.execute(account_id=account.id,game_id=game_id,command={'command_id':command_id,'kind':'seen','params':{},
            'window_idx':clock['window_idx'],'window_seq':clock['window_seq'],'actor_seq':player['actor_seq']})
        return {'marked':result['receipt']['accepted'] is True}

    async def _presence_of(self,game_id):
        rows=(await self.session.execute(select(NightPresence.account_id,NightPresence.seen_at).where(NightPresence.game_id==game_id))).all()
        return {str(account):_stamp(seen.replace(second=0,microsecond=0)) for account,seen in rows}

    async def _view(self,account_id,game_id,original_account_id,*,snapshot):
        account,locked,aliases=await self._access(account_id,game_id,history=True,snapshot=snapshot,shared=not snapshot)
        selected=self._history_selection(locked,aliases,original_account_id)
        now=self.clock()
        if locked.sealed.lifecycle=='lobby':
            case,rules=await self._load_case(locked.sealed)
            self._checked_lobby(locked.sealed,case,rules)
            # The lobby is dressed like the case: the world pack and the case's public pictures (portraits of
            # the heroes and their looks). Nothing of the truth: the pack holds no finales (they are sealed).
            meta=case.readonly()['meta']
            try: art=await self._art(locked.sealed,case)
            except NightCaseError: art=None   # no binding: the lobby is simply drawn without pictures
            public={'world':copy.deepcopy(meta.get('world')),'style_pack':copy.deepcopy(meta.get('style_pack')),'art':art}
            lobby=self._lobby_view(locked,account.id,case)
            lobby['chat']=await self._lobby_chat(game_id,aliases)
            return {'game_id':game_id,'mode':'night_case','lobby':lobby,
                'public':public,'self':None,'menu':[],'server_now':_stamp(now),'runtime_status':'ok'},locked
        case,rules,state=await self._runtime(locked)
        original=selected if selected is not None else account.id if account.id in aliases else sorted(aliases,key=str)[0]
        player=next(p for p in state.players if p['account_id']==str(original))
        if player['status']=='departed':
            cutoff=await self._departure(locked,state,original)
            view=copy.deepcopy(cutoff['frozen_view']); menu=[]
            if view['public'].get('art')!=await self._art(locked.sealed,case):
                raise NightCaseError('game_quarantined',503)
            # The final summary is separately allowed; fresh public state is never mixed in.
            final=None if state.final is None else {k:state.final[k] for k in ('code','at')}
        else:
            raw=_projection(case,rules,state,str(original))
            art,sealed=await self._art(locked.sealed,case,with_sealed=True)
            view={'public':_public(case,rules,state,art),'self':raw['self']}
            view['self'].pop('receipts',None)
            # «в сети / был недавно» beside each hero: when the player last had the case open, to the minute.
            seen=await self._presence_of(game_id)
            for row in view['public'].get('players',[]):
                if row['account_id'] in seen: row['seen_at']=seen[row['account_id']]
            _reveal_finale(view['self'],sealed)
            titles={cid:look['title'] for cid,look in raw['looks'].items()}
            for nearby in view['self'].get('nearby',[]):
                if nearby.get('controller')=='npc': nearby['title']=titles[nearby['character_id']]
            menu=_menu(available_actions(case,rules,state,PlayerActor(str(account.id)),now_utc=now),case) if original==account.id and locked.sealed.lifecycle=='running' else []
            final=None
        result={'game_id':game_id,'mode':'night_case',**view,'menu':menu,'server_now':_stamp(now),
            'runtime_status':locked.sealed.lifecycle,'final_summary':final}
        if locked.sealed.lifecycle in {'finished','stopped'}:
            titles={cid:look['title'] for cid,look in _projection(case,rules,state)['looks'].items()}
            result['history_seats']=[{'original_account_id':p['account_id'],'display_name':p['name'],
                'role_title':titles[p['character_id']],'status':p['status']} for p in state.players if UUID(p['account_id']) in aliases]
            result['selected_original_account_id']=str(original)
        return result,locked

    async def quote(self,*,account_id,game_id,intent: CommandIntent | dict):
        account,locked,_=await self._access(account_id,game_id,shared=True)
        if locked.sealed.lifecycle!='running': raise NightCaseError('game_not_running')
        case,rules,state=await self._runtime(locked)
        try: quote=quote_action(case,rules,state,PlayerActor(str(account.id)),intent,now_utc=self.clock())
        except ValueError as exc: raise NightCaseError('action_unavailable') from exc
        result=asdict(quote); result['params']=json.loads(quote.params)
        return result

    def _cursor(self,account_id,game_id,stream,key):
        raw=canonical_json({'principal':str(account_id),'game':game_id,'stream':stream,'last_key':key})
        signature=hmac.new(self.registry.cursor_secret,raw,hashlib.sha256).digest()
        return base64.urlsafe_b64encode(raw+signature).decode().rstrip('=')

    def _uncursor(self,cursor,account_id,game_id,stream):
        if cursor is None: return None
        try:
            if type(cursor) is not str or len(cursor)>4096: raise ValueError()
            packed=base64.urlsafe_b64decode(cursor+'='*(-len(cursor)%4)); raw,signature=packed[:-32],packed[-32:]
            if not hmac.compare_digest(signature,hmac.new(self.registry.cursor_secret,raw,hashlib.sha256).digest()): raise ValueError()
            value=json.loads(raw)
            if set(value)!={'principal','game','stream','last_key'} or (value['principal'],value['game'],value['stream'])!=(str(account_id),game_id,stream): raise ValueError()
            return value['last_key']
        except (ValueError,TypeError,KeyError): raise NightCaseError('unavailable',404) from None

    async def _message_allowed(self,locked,state,row,aliases):
        doc=state.document()
        receipt=next((r for r in doc['receipts'] if r['actor_key']=='account:'+str(row.sender_account_id)
            and r['command_id']==row.command_id and r['accepted'] and r.get('result_ref')
            and r['result_ref'].get('kind')=='message' and r['result_ref'].get('message_id')==row.id),None)
        if receipt is None:
            return False
        ref=receipt['result_ref']
        if (ref['text_hash'],ref['channel'],ref['thread_key'],ref['recipient_account_ids'],ref['window_idx']) != (
                row.text_hash,row.channel,row.thread_key,row.recipients,row.window_idx) or hashlib.sha256(row.text.encode()).hexdigest()!=row.text_hash:
            raise NightCaseError('game_quarantined',503)
        for aid in aliases:
            if str(aid) not in row.recipients: continue
            player=next(p for p in doc['players'] if p['account_id']==str(aid))
            if player['status']!='departed': return True
            cutoff=await self._departure(locked,state,aid)
            if receipt and receipt['actor_revision']<=cutoff['sender_actor_seq'].get(str(row.sender_account_id),-1):
                return True
        return False

    @staticmethod
    def _message_dto(row):
        return {key:copy.deepcopy(getattr(row,key)) for key in ('id','thread_key','channel','window_idx','text','text_hash')} | {
            'sender_account_id':str(row.sender_account_id),'recipient_account_ids':copy.deepcopy(row.recipients)}

    async def get_message(self,*,account_id,game_id,message_id):
        _,locked,aliases=await self._access(account_id,game_id,history=True,shared=True)
        case,rules,state=await self._runtime(locked)
        row=await self.repo.message(game_id,message_id,authorized_aliases=tuple(aliases))
        if row is None or not await self._message_allowed(locked,state,row,aliases): raise NightCaseError('unavailable',404)
        return self._message_dto(row)

    async def history(self,*,account_id,game_id,stream,cursor=None,limit=50,original_account_id=None):
        account,locked,aliases=await self._access(account_id,game_id,history=True,shared=True)
        selected=self._history_selection(locked,aliases,original_account_id)
        if selected is not None: aliases=frozenset({selected})
        if stream not in {'public','self','messages'} or type(limit) is not int or not 1<=limit<=50:
            raise NightCaseError('invalid_command',422)
        cursor_scope=stream if selected is None else stream+':original:'+str(selected)
        key=self._uncursor(cursor,account.id,game_id,cursor_scope)
        case,rules,state=await self._runtime(locked)
        doc=state.document(); cutoffs={}
        for aid in aliases:
            p=next(p for p in doc['players'] if p['account_id']==str(aid))
            if p['status']=='departed': cutoffs[str(aid)]=await self._departure(locked,state,aid)
        if stream=='messages':
            # ACL and departure frontier are applied before pagination/limit.
            clauses=[NightMessage.recipients.contains([str(a)]) for a in aliases]
            query=select(NightMessage).where(NightMessage.game_id==game_id,or_(*clauses))
            if key is not None:
                if type(key) is not list or len(key)!=2: raise NightCaseError('unavailable',404)
                query=query.where(or_(NightMessage.created_at>_parse(key[0]),and_(NightMessage.created_at==_parse(key[0]),NightMessage.id>key[1])))
            rows=list((await self.session.scalars(query.order_by(NightMessage.created_at,NightMessage.id))).all())
            allowed=[]
            for row in rows:
                if await self._message_allowed(locked,state,row,aliases): allowed.append(row)
                if len(allowed)>limit: break
            page=allowed[:limit]; items=[self._message_dto(r) for r in page]
            next_key=[_stamp(page[-1].created_at),page[-1].id] if len(allowed)>limit and page else None
        else:
            scopes=['public'] if stream=='public' else ['account:'+str(a) for a in aliases]
            clauses=[]
            for scope in scopes:
                cutoff=None
                if scope=='public' and len(cutoffs)==len(aliases): cutoff=max(c['public_seq'] for c in cutoffs.values())
                elif scope.startswith('account:') and scope[8:] in cutoffs: cutoff=cutoffs[scope[8:]]['self_seq']
                clause=NightEvent.scope==scope
                if cutoff is not None: clause=and_(clause,NightEvent.audience_seq<=cutoff)
                clauses.append(clause)
            query=select(NightEvent).where(NightEvent.game_id==game_id,or_(*clauses))
            if key is not None:
                if type(key) is not list or len(key)!=2 or type(key[1]) is not int: raise NightCaseError('unavailable',404)
                query=query.where(or_(NightEvent.scope>key[0],and_(NightEvent.scope==key[0],NightEvent.audience_seq>key[1])))
            rows=list((await self.session.scalars(query.order_by(NightEvent.scope,NightEvent.audience_seq).limit(limit+1))).all())
            page=rows[:limit]; items=[{k:copy.deepcopy(getattr(r,k)) for k in ('event_id','audience_seq','window_idx','kind','payload')} for r in page]
            next_key=[page[-1].scope,page[-1].audience_seq] if len(rows)>limit and page else None
        return {'items':items,'next_cursor':self._cursor(account.id,game_id,cursor_scope,next_key) if next_key is not None else None}

    @_atomic
    async def propose_intent(self,*,account_id,game_id,request_id,selection_id=None,text=None):
        account,aliases=await self._intent_identity(account_id,game_id)
        if (type(request_id) is not str or not 8 <= len(request_id) <= 128
                or (selection_id is not None and type(selection_id) is not str)
                or (text is not None and (type(text) is not str or not 1 <= len(text) <= 1000))):
            raise NightCaseError('invalid_command',422)
        fingerprint=json_hash({'selection_id':selection_id,'text':text})
        prior=await self._intent_prior(game_id,aliases,request_id,fingerprint)
        if prior is not None: return prior if type(prior) is dict else {'kind':'clarification','code':'intent_pending'}
        locked=await self.repo.lock_game(game_id)
        prior=await self._intent_prior(game_id,aliases,request_id,fingerprint)
        if prior is not None: return prior if type(prior) is dict else {'kind':'clarification','code':'intent_pending'}
        account,locked,_=await self._access(account.id,game_id)
        if locked.sealed.lifecycle!='running': raise NightCaseError('game_not_running')
        case,rules,state=await self._runtime(locked); now=self.clock()
        if selection_id is None:
            # No provider/parser is configured in A. Buttons remain the actual path.
            return {'kind':'clarification','code':'choose_available_action'}
        legal=[e.quote for e in available_actions(case,rules,state,PlayerActor(str(account.id)),now_utc=now) if hasattr(e,'quote')]
        return await self._create_action_proposal(account,locked,request_id,fingerprint,selection_id,state,legal,
            created_at=now,expires_at=now+timedelta(seconds=120))

    async def _create_action_proposal(self,account,locked,request_id,fingerprint,selection_id,state,legal,*,created_at,expires_at):
        """Caller owns Game lock, cross-table replay and fresh action eligibility."""
        game_id=locked.game.id
        context=ActionContext(game_id,str(account.id),state.clock['window_idx'],state.clock['window_seq'],created_at)
        proposal=propose_action(selection_id,legal,context,proposal_id=str(uuid4()),expires_at=expires_at)
        raw=asdict(proposal)
        raw['created_at']=_stamp(proposal.created_at); raw['expires_at']=_stamp(proposal.expires_at)
        command_id=hashlib.sha256(json.dumps([game_id,str(account.id),proposal.proposal_id],ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
        player=next(p for p in state.players if p['account_id']==str(account.id))
        envelope={'command_id':command_id,'kind':proposal.kind,'window_idx':proposal.window_idx,'window_seq':proposal.window_seq,
            'actor_seq':player['actor_seq'],'params':json.loads(proposal.params)}
        await self.repo.put_proposal(NightIntentProposal(proposal_id=proposal.proposal_id,game_id=game_id,
            original_actor_account_id=account.id,request_id=request_id,input_hash=fingerprint,
            proposal={'task2':raw,'command':envelope},expires_at=proposal.expires_at,confirmed_command_id=None))
        return {'kind':'proposal','proposal':raw}

    @_atomic
    async def confirm_intent(self,*,account_id,game_id,proposal_id):
        account,locked,_=await self._access(account_id,game_id)
        proposal=await self.repo.proposal(proposal_id,authorized_aliases=[account.id])
        if proposal is None or proposal.game_id!=game_id: raise NightCaseError('unavailable',404)
        envelope=proposal.proposal['command']; command_id=envelope['command_id']
        prior=await self.repo.command_receipt(game_id,str(account.id),command_id,json_hash(envelope))
        if prior:
            if proposal.confirmed_command_id not in (None,command_id): raise NightCaseError('game_quarantined',503)
            await self.repo.confirm_proposal(proposal,command_id)
            return copy.deepcopy(prior.result)
        if proposal.confirmed_command_id is not None: raise NightCaseError('game_quarantined',503)
        if locked.sealed.lifecycle!='running': raise NightCaseError('game_not_running')
        case,rules,state=await self._runtime(locked); now=self.clock()
        raw=copy.deepcopy(proposal.proposal['task2'])
        raw['created_at']=_parse(raw['created_at']); raw['expires_at']=_parse(raw['expires_at'])
        task2=ActionProposal(**raw)
        legal=[e.quote for e in available_actions(case,rules,state,PlayerActor(str(account.id)),now_utc=now) if hasattr(e,'quote')]
        context=ActionContext(game_id,str(account.id),state.clock['window_idx'],state.clock['window_seq'],now)
        try: authorized=confirm_action(task2,context,legal,now=now)
        except ValueError as exc: raise NightCaseError('proposal_stale') from exc
        if authorized.command_id!=command_id: raise NightCaseError('game_quarantined',503)
        result=await self.execute(account_id=account.id,game_id=game_id,command=envelope)
        await self.repo.confirm_proposal(proposal,command_id)
        return result

    async def list_cases(self,*,account_id):
        await self._principal(account_id)
        cases=[]
        for ref in sorted(self.registry.allowed_cases,key=lambda r:(r.case_id,r.case_version)):
            row=await self.repo.get_case(ref.case_id,ref.case_version)
            if row is None or row.admission!='rehearsal' or row.content_hash!=ref.content_hash or row.engine_build not in self.registry.allowed_builds:
                continue
            item={'id':row.case_id,'version':row.version,'title':row.content['meta']['title'],
                'timezones':sorted(self.registry.allowed_timezones)}
            cases.append(item)
            # The case card (mockup 3): its world, premise, table size and cast — what the lobby shows anyone in the company.
            try:
                case=_registered_case(row); doc=case.readonly(); meta=doc['meta']; counts=_lobby_counts(doc,2)
                art=_art_binding(row.validation_report,meta)
            except (NightCaseError,ValueError,KeyError):
                continue
            item.update(world=meta.get('world'),summary=meta.get('summary') or '',players={'min':min(counts),'max':max(counts)},art=art,
                heroes=_lobby_heroes(doc),
                npc_heroes=[{'id':c['id'],'title':c['title'],'art':copy.deepcopy(looks_of(c)[0].get('art'))} for c in doc['characters'] if not c['can_be_player']])
        return {'enabled':True,'cases':cases}

    async def room_game(self,*,account_id,room_id):
        account=await self._principal(account_id)
        await self._member(room_id,account.id)
        row=await self.session.scalar(select(Game).where(Game.room_id==room_id,Game.mode=='night_case',Game.is_current.is_(True)))
        return {'game_id':row.id if row else None}

    async def my_cases(self,*,account_id):
        """Root of the case screen (mockup 1): every company of mine with its current case and my hero in it.

        Read from the sealed rows without locks or a decoded kernel. Nothing secret leaves it: only the case,
        the window, the hero I took and my own status; the side, the truth and other players stay in the view."""
        account=await self._principal(account_id)
        aliases={str(a) for a in await historical_aliases(self.session,account.id)}
        members=select(RoomMembership.room_id,func.count().label('n')).where(RoomMembership.status=='active').group_by(RoomMembership.room_id).subquery()
        rows=(await self.session.execute(select(Room,members.c.n,Game,NightGameSealed)
            .join(RoomMembership,and_(RoomMembership.room_id==Room.id,RoomMembership.account_id==account.id,RoomMembership.status=='active'))
            .join(members,members.c.room_id==Room.id)
            .outerjoin(Game,and_(Game.room_id==Room.id,Game.mode=='night_case',Game.is_current.is_(True)))
            .outerjoin(NightGameSealed,NightGameSealed.game_id==Game.id)
            .where(Room.kind=='standalone').order_by(Room.created_at.desc(),Room.id))).all()
        items=[]
        for room,count,game,sealed in rows:
            item={'room_id':room.id,'title':room.title,'members':int(count),'game_id':None,'status':'none'}
            items.append(item)
            if game is None or sealed is None: continue
            item.update(game_id=game.id,status=sealed.lifecycle,window={'idx':0,'count':sealed.rules.get('window_count')},hero=None)
            try:
                case,_rules=await self._load_case(sealed)
                art=await self._art(sealed,case)
            except NightCaseError:
                item['status']='unavailable'; continue
            content=case.readonly()
            item.update(case_title=(sealed.lobby or {}).get('title') or content['meta']['title'],world=content['meta'].get('world'),art=art)
            heroes={c['id']:c for c in content['characters']}
            if sealed.lifecycle=='lobby':
                roster=sealed.lobby['roster']
                own=next((r for r in roster if r['account_id'] in aliases),None)
                item.update(seated=own is not None,players=len(roster))
                if own and own.get('character_id') in heroes:
                    looks=looks_of(heroes[own['character_id']])
                    look=next((x for x in looks if x['id']==own.get('look_id')),looks[0])
                    item['hero']={'character_id':own['character_id'],'look':public_look(look)}
                continue
            kernel=sealed.kernel or {}
            clock=kernel.get('clock') or {}
            item['window']['idx']=clock.get('window_idx',0)
            item['phase']=clock.get('phase')
            players=list(kernel.get('players') or ())
            own=next((p for p in players if p.get('account_id') in aliases),None)
            item.update(seated=own is not None,players=len(players))
            if own and own.get('character_id') in heroes:
                item['hero']={'character_id':own['character_id'],'look':public_look(chosen_looks(content,kernel)[own['character_id']])}
                item['self_status']=own.get('status')
        return {'items':items}

    @_atomic
    async def get_rendering(self,*,account_id,game_id,job_id):
        account,locked,aliases=await self._access(account_id,game_id,history=True)
        case,rules,state=await self._runtime(locked)
        audiences={'public',*('account:'+str(a) for a in aliases)}
        job=(await self.session.execute(select(NightRenderJob).where(NightRenderJob.job_id==job_id,
            NightRenderJob.game_id==game_id,NightRenderJob.audience_key.in_(audiences)))).scalar_one_or_none()
        if job is None: raise NightCaseError('unavailable',404)
        job_aliases=frozenset(aid for aid in aliases if job.audience_key in {'public','account:'+str(aid)})
        # Causes are immutable authorized events/messages, never a room-owner privilege.
        event=await self.session.get(NightEvent,(game_id,job.cause_id))
        if event is not None:
            eligible=False
            for aid in job_aliases:
                if event.scope not in {'public','account:'+str(aid)}: continue
                p=next(p for p in state.players if p['account_id']==str(aid))
                if p['status']=='departed':
                    cutoff=await self._departure(locked,state,aid)
                    maximum=cutoff['public_seq'] if event.scope=='public' else cutoff['self_seq']
                    if event.audience_seq>maximum: continue
                eligible=True
                break
            if not eligible: raise NightCaseError('unavailable',404)
        else:
            message=await self.repo.message(game_id,job.cause_id,authorized_aliases=tuple(job_aliases))
            if message is None or not await self._message_allowed(locked,state,message,job_aliases):
                raise NightCaseError('unavailable',404)
        existing=await self.repo.rendering(job_id,authorized_audiences=tuple(audiences))
        if existing is None:
            view=job.frozen_view
            existing=await self.repo.commit_rendering(NightRendering(job_id=job_id,text=job.fallback,source='authored',
                content_hash=hashlib.sha256(job.fallback.encode()).hexdigest(),references=view.get('references',[]),
                catalog_ids=view.get('catalog_ids',[]),created_at=self.clock(),first_shown_at=None))
        await self.repo.mark_rendering_shown(job_id,self.clock())
        return {k:copy.deepcopy(getattr(existing,k)) for k in ('job_id','text','source','content_hash','references','catalog_ids')}

    @_atomic
    async def advance_due(self,*,game_id,command):
        """Trusted worker entry; adapters must never expose SystemActor to players."""
        locked=await self.repo.lock_game(game_id)
        if locked is None: raise NightCaseError('unavailable',404)
        try: parsed=parse_command(command,SystemActor(),ruleset_version=2)
        except ValueError as exc: raise NightCaseError('invalid_command',422) from exc
        raw=parsed.document()
        prior=await self.repo.command_receipt(game_id,'system',raw['command_id'],json_hash(raw))
        if prior: return copy.deepcopy(prior.result)
        if locked.sealed.lifecycle!='running': raise NightCaseError('game_not_running')
        case,rules,state=await self._runtime(locked); now=self.clock()
        if raw['kind']=='system.tick':
            state=await self._availability(locked,case,rules,state,now,'system')
        transition=step(case,rules,state,SystemActor(),parsed,now_utc=now)
        await self._persist(locked,case,rules,transition,now,'system',raw['command_id'])
        result={'receipt':{'command_id':raw['command_id'],**transition.receipt},
            'caused_event_ids':[e['event_id'] for e in transition.events],'caused_message_ids':[]}
        await self.repo.put_command_receipt(game_id=game_id,actor_key='system',actor_account_id=None,
            client_command_id=raw['command_id'],kind=raw['kind'],payload=raw,result=result,
            status='applied' if transition.receipt['accepted'] else 'rejected',now=now)
        return result

    async def resume_outage(self,*,game_id,command):
        if type(command) is not dict or command.get('kind')!='system.resume': raise NightCaseError('invalid_command',422)
        return await self.advance_due(game_id=game_id,command=command)

    async def close_interrupted(self,*,operator: OperatorPrincipal,game_id,action_id,reason):
        await operation_fence(self.session,exclusive=True)
        if not isinstance(operator,OperatorPrincipal) or not operator.operator_id or not reason.strip():
            raise NightCaseError('operator_required',403)
        if operator.account_id is not None: await self._principal(operator.account_id)
        room_id=await self.session.scalar(select(Game.room_id).where(Game.id==game_id,Game.mode=='night_case'))
        if room_id is None: raise NightCaseError('unavailable',404)
        from storage.games import night_room_lock
        await night_room_lock(self.session,room_id)
        locked=await self.repo.lock_game(game_id)
        actor='operator:'+operator.operator_id; payload={'action':'close_interrupted','reason':reason}
        prior=await self.repo.command_receipt(game_id,actor,action_id,json_hash(payload))
        if prior: return copy.deepcopy(prior.result)
        if locked.sealed.lifecycle!='interrupted': raise NightCaseError('game_not_interrupted')
        sealed=locked.sealed; now=self.clock()
        await self.repo.write_snapshot(locked,expected_storage_revision=sealed.storage_revision,
            kernel=copy.deepcopy(sealed.kernel),lobby=copy.deepcopy(sealed.lobby),snapshot_hash=sealed.snapshot_hash,
            lifecycle='stopped',interruption=copy.deepcopy(sealed.interruption))
        await self.repo.sync_public(locked,projection=copy.deepcopy(locked.game.state['public_projection']),phase='stopped',public_revision=locked.game.revision+1)
        locked.game.is_current=False; locked.game.ended_at=now
        await self.repo.project_deadline(game_id=game_id,due_at=None,timer_seq=0)
        result={'game_id':game_id,'status':'stopped','action_id':action_id}
        await self.repo.put_command_receipt(game_id=game_id,actor_key=actor,actor_account_id=operator.account_id,
            client_command_id=action_id,kind='night.close_interrupted',payload=payload,result=result,status='applied',now=now)
        return result


async def check_room_leave(session,game,account_id):
    """Called after shared fence + family/mode/Room locks, never mutates a seat."""
    if game.status in {'finished','stopped'}: return
    sealed=await session.get(NightGameSealed,game.id)
    if sealed is None: raise RuntimeError('game_quarantined')
    if sealed.lobby is not None:
        participant=any(r['account_id']==str(account_id) for r in sealed.lobby['roster'])
    else:
        participant=await session.get(GamePlayer,(game.id,account_id))
    if not participant: return
    if game.status=='interrupted': raise RuntimeError('game_interrupted')
    if sealed.lifecycle=='lobby': raise RuntimeError('leave_lobby_required')
    if participant.status!='departed': raise RuntimeError('forfeit_required')


async def assert_merge_available(session,account_ids):
    from storage.mini_app import MiniAppError
    rows=list((await session.scalars(select(Game).where(Game.mode=='night_case',Game.is_current.is_(True),
        Game.status.not_in(['finished','stopped'])))).all())
    for game in rows:
        owner=await session.scalar(select(Room.owner_account_id).where(Room.id==game.room_id))
        if owner in account_ids: raise MiniAppError(409,'Заверши дело перед объединением.',code='night_case_merge_active')
        if await session.scalar(select(exists().where(GamePlayer.game_id==game.id,GamePlayer.account_id.in_(account_ids)))):
            raise MiniAppError(409,'Заверши дело перед объединением.',code='night_case_merge_active')
        sealed=await session.get(NightGameSealed,game.id)
        if sealed and sealed.lobby and any(UUID(r['account_id']) in account_ids for r in sealed.lobby['roster']):
            raise MiniAppError(409,'Заверши дело перед объединением.',code='night_case_merge_active')
