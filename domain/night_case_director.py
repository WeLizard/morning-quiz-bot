"""Pure, source-bound context for optional Night Case narration.

Callers must select authorized source events, materialized cards and menu choices.
This module checks their declared relationship and never reads a game snapshot.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
import unicodedata

from .night_case_narrative import (
    MAX_CONTEXT_TEXT, MAX_FACT_TEXT, MAX_ITEMS, LegalAction, NarrationView, RenderingDecision,
    build_narrative_job, validate_narrative_result,
)
from .night_case_projection import MenuChoice


SCHEMA = 'night-director-view/1'
SCHEMA_CAST = 'night-director-view/2'   # /1 plus the cast of heroes, items and places (rule P9)
_REF = re.compile(r'r[0-9]{2}\Z')
_OFFER = re.compile(r'c[0-9]{2}\Z')
_HEX = re.compile(r'[0-9a-f]{64}\Z')
_ACCOUNT_SCOPE = re.compile(r'account:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z')


class ContextUnavailable(ValueError):
    """Critical source cannot fit the narrative codec; use authored output."""


def _text(value, *, limit=4000, nonempty=True):
    if (type(value) is not str or (nonempty and not value) or len(value) > limit
            or unicodedata.normalize('NFC', value) != value
            or any(unicodedata.category(c) in {'Cc', 'Cf', 'Cs'} and c != '\n' for c in value)):
        raise ValueError('invalid director text')
    return value


def _role_title(value):
    _text(value,limit=80)
    if value.startswith('account:') or re.fullmatch(r'[0-9a-fA-F-]{36}',value):
        raise ValueError('authored role title required')
    return value


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
                      allow_nan=False).encode('utf-8')


def _hash(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def _window(value):
    if type(value) is not int or not 1 <= value <= 14:
        raise ValueError('invalid director window')
    return value


def _audience(value):
    if type(value) is not str or not (value == 'public' or _ACCOUNT_SCOPE.fullmatch(value)):
        raise ValueError('invalid director audience')
    return value


def _utc(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError('UTC datetime required')
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class AuthorizedSource:
    kind: str
    cause_id: str
    audience_key: str
    action_window: int
    summarized_window: int | None
    event_ids: tuple[str, ...]
    observation_ids: tuple[str, ...]
    body: str
    speaker_title: str | None = None

    def __post_init__(self):
        if self.kind not in {'window_digest', 'npc_reply', 'scene_narration', 'story_offer'}:
            raise ValueError('unknown director source')
        _text(self.cause_id, limit=128)
        _audience(self.audience_key)
        _window(self.action_window)
        if self.kind in {'window_digest', 'story_offer'}:
            _window(self.summarized_window)
            if self.summarized_window > self.action_window or self.audience_key == 'public':
                raise ValueError('invalid digest window/audience')
        elif self.summarized_window is not None:
            raise ValueError('unexpected summarized window')
        if self.kind == 'scene_narration' and self.audience_key != 'public':
            raise ValueError('scene must be public')
        if self.kind == 'npc_reply' and self.audience_key == 'public':
            raise ValueError('NPC reply must be private')
        for values in (self.event_ids, self.observation_ids):
            if type(values) is not tuple or len(values) > MAX_ITEMS or len(set(values)) != len(values):
                raise ValueError('invalid source references')
            for item in values: _text(item, limit=128)
        _text(self.body, nonempty=self.kind in {'npc_reply', 'scene_narration'}, limit=32000)
        if self.kind=='npc_reply': _role_title(self.speaker_title)
        elif self.speaker_title is not None: raise ValueError('unexpected source speaker')
        if self.kind in {'window_digest', 'story_offer'} and self.body:
            raise ValueError('digest body is referenced, not copied')


@dataclass(frozen=True)
class SafeRecord:
    kind: str  # event | observation
    source_id: str
    classification: str  # proof | claim | result | scene
    body: str
    audience_key: str
    window_idx: int
    parent_event_id: str | None = None
    speaker_title: str | None = None

    def __post_init__(self):
        if self.kind not in {'event', 'observation'} or self.classification not in {'proof', 'claim', 'result', 'scene'}:
            raise ValueError('invalid safe record kind')
        _text(self.source_id, limit=128)
        _text(self.body, limit=32000)
        _audience(self.audience_key)
        _window(self.window_idx)
        if self.kind == 'observation':
            _text(self.parent_event_id, limit=128)
        elif self.parent_event_id is not None:
            raise ValueError('event cannot have parent event')
        if self.classification=='claim': _role_title(self.speaker_title)
        elif self.speaker_title is not None: raise ValueError('speaker only for claim')


@dataclass(frozen=True)
class SafeCast:
    """Authored description of a hero look, an item or a place the records touch (rule P9).

    Only case content: a look's name, age and bio, an item's or place's body. Never a player label."""
    kind: str  # hero | item | place
    title: str
    body: str

    def __post_init__(self):
        if self.kind not in {'hero', 'item', 'place'}:
            raise ValueError('invalid cast kind')
        _role_title(self.title)
        _text(self.body, limit=1000)


@dataclass(frozen=True)
class SafeOffer:
    choice: MenuChoice

    def __post_init__(self):
        if not isinstance(self.choice, MenuChoice) or self.choice.kind != 'choice':
            raise ValueError('visible MenuChoice required')
        if self.choice.entry_id != self.choice.quote.selection_id:
            raise ValueError('menu quote mismatch')
        _text(self.choice.label, limit=256)


def audience_permitted(mode: str, starter_account_id: str, audience_key: str) -> bool:
    """Pure transport scope decision; caller still checks live binding and ACL."""
    try: _audience(audience_key)
    except ValueError: return False
    if mode == 'admin': return True
    return mode == 'byok' and (audience_key == 'public' or audience_key == 'account:' + starter_account_id)


def _chunks(alias, classification, body, speaker_title=None):
    role = f'; роль: {speaker_title}' if speaker_title is not None else ''
    prefix = f'[{alias}; {classification}{role}] '
    length = MAX_FACT_TEXT - len(prefix) - 16
    if length < 1: raise ContextUnavailable('prefix exceeds codec')
    parts = [body[i:i + length] for i in range(0, len(body), length)]
    return [f'[{alias}; {classification}{role}; part {i}/{len(parts)}] {part}' if len(parts) > 1 else prefix + part
            for i, part in enumerate(parts, 1)]


_CAST_LABEL = {'hero': 'герой', 'item': 'предмет', 'place': 'место'}


def _facts_for(kind, action_window, summarized_window, blocks, offers, cast=()):
    facts=[]
    if kind=='story_offer': facts.append(f'[предложение; окно {action_window}]')
    elif summarized_window is not None: facts.append(f'[digest; окно {summarized_window}]')
    for block in blocks:
        facts.extend(_chunks(block['reference'],block['kind'],block['body'],block['speaker_title']))
    for offer in offers:
        facts.append(f"[{offer['alias']}; предложение; {offer['cost']} AP] {offer['label']}")
    for row in cast:
        facts.append(f"[{_CAST_LABEL[row['kind']]}; {row['title']}] {row['body']}")
    return facts


def _check_source_record(source, record):
    if record.audience_key not in {'public', source.audience_key}:
        raise ValueError('foreign record audience')
    if source.kind in {'window_digest', 'story_offer'}:
        if record.kind == 'event':
            if record.source_id not in source.event_ids or record.window_idx != source.summarized_window:
                raise ValueError('event outside digest')
        elif (record.source_id not in source.observation_ids or record.parent_event_id not in source.event_ids
              or record.window_idx > source.summarized_window):
            raise ValueError('observation outside digest')
    elif (record.kind != 'observation' or record.source_id not in source.observation_ids
          or record.parent_event_id not in source.event_ids or record.window_idx != source.action_window):
        raise ValueError('record outside source')


class FrozenContext:
    def __init__(self, document, *, source=None, fallback=None, expires_at=None):
        self._encoded = _canonical(document)
        self.input_hash = hashlib.sha256(self._encoded).hexdigest()
        self._source = source
        self._fallback = fallback
        self._expires_at = expires_at

    def document(self):
        return json.loads(self._encoded)

    @classmethod
    def from_document(cls, document, *, input_hash, source: AuthorizedSource):
        try:
            return cls._from_document(document, input_hash=input_hash, source=source)
        except (TypeError, KeyError, UnicodeError, OverflowError, RecursionError) as exc:
            raise ValueError('malformed frozen context') from exc

    @classmethod
    def _from_document(cls, document, *, input_hash, source):
        if not isinstance(source,AuthorizedSource): raise ValueError('authorized source required')
        if type(input_hash) is not str or not _HEX.fullmatch(input_hash):
            raise ValueError('invalid input hash')
        base = {'schema','narrative','reference_map','exact_blocks','offers','references','catalog_ids','summarized_window','action_window','context_hash'}
        if type(document) is not dict or set(document) not in (base, base | {'cast'}):
            raise ValueError('invalid frozen context shape')
        if document['schema'] != (SCHEMA_CAST if 'cast' in document else SCHEMA) or not _HEX.fullmatch(document['context_hash']):
            raise ValueError('invalid frozen context schema/hash')
        cast = document.get('cast', [])
        if 'cast' in document and (type(cast) is not list or not cast or len(cast) > MAX_ITEMS
                                   or any(type(c) is not dict or set(c) != {'kind','title','body'} for c in cast)):
            raise ValueError('invalid frozen cast')
        for row in cast:
            SafeCast(row['kind'], row['title'], row['body'])
        raw = copy.deepcopy(document)
        narrative = raw['narrative']
        if type(narrative) is not dict or set(narrative) != {'audience','audience_key','facts','references','catalog_ids','knowledge_revision','window_idx','case_hash','ruleset_version'}:
            raise ValueError('invalid narrative shape')
        if any(type(narrative[k]) is not list for k in ('facts','references','catalog_ids')):
            raise ValueError('invalid narrative arrays')
        saved_revision = narrative.pop('knowledge_revision')
        context_hash = raw.pop('context_hash')
        if _hash(raw) != context_hash or saved_revision != context_hash:
            raise ValueError('frozen context hash mismatch')
        if (narrative['window_idx'] != document['action_window'] or type(document['references']) is not list
                or len(document['references'])!=1 or type(document['references'][0]) is not str
                or document['catalog_ids']!=[]):
            raise ValueError('frozen context window/refs')
        _window(document['action_window'])
        if document['summarized_window'] is not None: _window(document['summarized_window'])
        view = NarrationView(**{**document['narrative'], 'facts':tuple(narrative['facts']),
                                'references':tuple(narrative['references']), 'catalog_ids':tuple(narrative['catalog_ids'])})
        if view.audience != ('public' if view.audience_key=='public' else 'private'):
            raise ValueError('narrative audience mismatch')
        _audience(view.audience_key)
        if not _HEX.fullmatch(view.case_hash): raise ValueError('invalid frozen case hash')
        refs, offers = document['reference_map'], document['offers']
        if (type(refs) is not list or len(refs)>MAX_ITEMS or type(offers) is not list or len(offers)>3
                or any(type(r) is not dict or set(r)!={'alias','kind','source_id','body_hash'} or not _REF.fullmatch(r['alias']) or r['kind'] not in {'event','observation'} or not _HEX.fullmatch(r['body_hash']) for r in refs)
                or any(type(o) is not dict or set(o)!={'alias','selection_id','label','kind','target_id','cost','resource_id','resource_revision','params'} or not _OFFER.fullmatch(o['alias']) for o in offers)):
            raise ValueError('invalid frozen maps')
        if len({r['alias'] for r in refs}) != len(refs) or len({o['alias'] for o in offers}) != len(offers):
            raise ValueError('duplicate alias')
        if ([r['alias'] for r in refs] != [f'r{i:02d}' for i in range(1,len(refs)+1)]
                or [o['alias'] for o in offers] != [f'c{i:02d}' for i in range(1,len(offers)+1)]):
            raise ValueError('noncanonical alias')
        for ref in refs:
            _text(ref['source_id'],limit=128)
        if list(view.references) != [r['alias'] for r in refs] or list(view.catalog_ids) != [o['alias'] for o in offers]:
            raise ValueError('alias mismatch')
        blocks=document['exact_blocks']
        if (type(blocks) is not list or len(blocks)!=len(refs)
                or any(type(b) is not dict or set(b)!={'reference','kind','body','speaker_title'} or b['kind'] not in {'proof','claim','result','scene'} for b in blocks)
                or [b['reference'] for b in blocks]!=[r['alias'] for r in refs]):
            raise ValueError('invalid exact blocks')
        for ref,block in zip(refs,blocks):
            _text(block['body'],limit=32000)
            if block['kind']=='claim': _role_title(block['speaker_title'])
            elif block['speaker_title'] is not None and not (source.kind=='npc_reply' and ref['source_id']==source.cause_id):
                raise ValueError('unexpected exact speaker')
            elif block['speaker_title'] is not None: _role_title(block['speaker_title'])
            if ref['kind']=='observation' and block['kind'] not in {'proof','claim'}:
                raise ValueError('observation classification mismatch')
            if ref['kind']=='event' and block['kind'] not in {'result','scene'}:
                raise ValueError('event classification mismatch')
            if hashlib.sha256(block['body'].encode('utf-8')).hexdigest()!=ref['body_hash']:
                raise ValueError('exact body hash mismatch')
        for offer in offers:
            _text(offer['label'],limit=256)
            if type(offer['cost']) is not int or offer['cost']<0 or type(offer['params']) is not str or len(offer['params'])>8192:
                raise ValueError('invalid offer price/params')
            legal=LegalAction(offer['selection_id'],offer['kind'],offer['target_id'],offer['cost'],
                              offer['resource_id'],json.loads(offer['params']),offer['resource_revision'])
            if legal.params!=offer['params']:
                raise ValueError('noncanonical offer params')
        if len(self_bytes:=_canonical(document))>65536 or hashlib.sha256(self_bytes).hexdigest()!=input_hash:
            raise ValueError('frozen context size/input hash')
        if (source.action_window!=document['action_window'] or source.summarized_window!=document['summarized_window']
                or document['references'] != [source.cause_id] or source.audience_key!=view.audience_key):
            raise ValueError('frozen source window mismatch')
        expected_refs=({('event',source.cause_id)} if source.body else set())
        if source.kind=='window_digest': expected_refs|={('event',eid) for eid in source.event_ids}
        if source.kind!='story_offer': expected_refs|={('observation',oid) for oid in source.observation_ids}
        if {(r['kind'],r['source_id']) for r in refs}!=expected_refs or len(refs)!=len(expected_refs):
            raise ValueError('frozen source records incomplete')
        if source.body:
            block=next((b for r,b in zip(refs,blocks) if r['source_id']==source.cause_id and r['kind']=='event'),None)
            if (block is None or block['body']!=source.body or block['kind']!=('scene' if source.kind=='scene_narration' else 'result')
                    or block['speaker_title']!=source.speaker_title):
                raise ValueError('frozen exact source changed')
        if tuple(_facts_for(source.kind,source.action_window,source.summarized_window,blocks,offers,cast))!=view.facts:
            raise ValueError('frozen facts differ from exact records')
        if len(_canonical({'request_token':'0'*64,'kind':'window_digest','facts':list(view.facts),
                           'references':list(view.references),'catalog_ids':list(view.catalog_ids)}))>32768:
            raise ValueError('provider payload too large')
        return cls(document,source=source)

    def narrative_job(self, *, job_id, cause_id=None, kind=None, expires_at=None, fallback=None):
        d=self.document()
        view=NarrationView(**{**d['narrative'],'facts':tuple(d['narrative']['facts']),
                               'references':tuple(d['narrative']['references']), 'catalog_ids':tuple(d['narrative']['catalog_ids'])})
        cause_id = cause_id or (self._source.cause_id if self._source else None)
        kind = kind or (self._source.kind if self._source else None)
        expires_at = expires_at or self._expires_at
        fallback = fallback or self._fallback
        if cause_id is None or kind is None or expires_at is None or fallback is None:
            raise ValueError('saved job metadata required')
        if self._source is not None and (cause_id!=self._source.cause_id or kind!=self._source.kind):
            raise ValueError('saved job source mismatch')
        if self._expires_at is not None and _utc(expires_at)>self._expires_at:
            raise ValueError('job deadline cannot extend')
        if d['references'] != [cause_id] or kind not in {'window_digest','npc_reply','scene_narration','story_offer'}:
            raise ValueError('saved job source mismatch')
        return build_narrative_job(view,job_id=job_id,cause_id=cause_id,kind=kind,
                                   expires_at=expires_at,fallback=fallback)

    def resolve_offer(self, alias, *, current_window, legal_actions):
        d=self.document()
        if type(current_window) is not int or current_window!=d['action_window']: return None
        match=next((o for o in d['offers'] if o['alias']==alias),None)
        if match is None: return None
        for action in legal_actions:
            if not isinstance(action,LegalAction) or type(match['cost']) is not int or type(action.cost) is not int:
                continue
            if (action.selection_id==match['selection_id'] and action.kind==match['kind'] and action.target_id==match['target_id']
                    and action.cost==match['cost'] and action.resource_id==match['resource_id']
                    and action.resource_revision==match['resource_revision'] and action.params==match['params']):
                return action
        return None


def build_frozen_context(source: AuthorizedSource, records, offers, *, case_hash, ruleset_version,
                         fallback, created_at, closes_at, cast=()) -> FrozenContext:
    if not isinstance(source,AuthorizedSource): raise ValueError('authorized source required')
    if type(records) not in {tuple,list} or type(offers) not in {tuple,list} or len(records)>MAX_ITEMS or len(offers)>3:
        raise ValueError('invalid director selection')
    if type(case_hash) is not str or not _HEX.fullmatch(case_hash):
        raise ValueError('invalid case hash')
    _text(ruleset_version,limit=128); _text(fallback)
    created_at,closes_at=_utc(created_at),_utc(closes_at)
    if closes_at<=created_at: raise ValueError('closed source window')
    if source.kind!='story_offer' and offers:  # A separate offer job owns its catalog.
        raise ValueError('offers outside story_offer')
    if source.kind=='story_offer' and records: raise ValueError('offer does not copy digest facts')
    if len({(r.kind,r.source_id) for r in records})!=len(records): raise ValueError('duplicate safe record')
    present_events={r.source_id for r in records if isinstance(r,SafeRecord) and r.kind=='event'}
    present_observations={r.source_id for r in records if isinstance(r,SafeRecord) and r.kind=='observation'}
    if (source.kind!='story_offer' and present_observations!=set(source.observation_ids) or
            source.kind=='window_digest' and present_events!=set(source.event_ids) or
            source.kind not in {'window_digest','story_offer'} and present_events):
        raise ValueError('critical source records incomplete')
    references=[]; blocks=[]
    if source.body:
        references.append({'alias':'r01','kind':'event','source_id':source.cause_id,'body_hash':hashlib.sha256(source.body.encode('utf-8')).hexdigest()})
        blocks.append({'reference':'r01','kind':'scene' if source.kind=='scene_narration' else 'result','body':source.body,'speaker_title':source.speaker_title})
    for record in records:
        if not isinstance(record,SafeRecord): raise ValueError('safe record required')
        _check_source_record(source,record)
        alias=f'r{len(references)+1:02d}'
        references.append({'alias':alias,'kind':record.kind,'source_id':record.source_id,'body_hash':hashlib.sha256(record.body.encode('utf-8')).hexdigest()})
        blocks.append({'reference':alias,'kind':record.classification,'body':record.body,'speaker_title':record.speaker_title})
    offer_rows=[]
    for offer in offers:
        if not isinstance(offer,SafeOffer): raise ValueError('safe offer required')
        q=offer.choice.quote; alias=f'c{len(offer_rows)+1:02d}'
        offer_rows.append({'alias':alias,'selection_id':q.selection_id,'label':offer.choice.label,'kind':q.kind,
                           'target_id':q.target_id,'cost':q.cost,'resource_id':q.resource_id,
                           'resource_revision':q.resource_revision,'params':q.params})
    if type(cast) not in {tuple,list} or any(not isinstance(c,SafeCast) for c in cast):
        raise ValueError('safe cast required')
    cast_rows=[{'kind':c.kind,'title':c.title,'body':c.body} for c in dict.fromkeys(cast)]
    facts=_facts_for(source.kind,source.action_window,source.summarized_window,blocks,offer_rows)
    if len(facts)>MAX_ITEMS or any(len(f)>MAX_FACT_TEXT for f in facts) or sum(map(len,facts))>MAX_CONTEXT_TEXT:
        raise ContextUnavailable('critical narrative context exceeds codec')
    # The cast is optional colour: whatever does not fit the codec is left out, the records never are.
    while cast_rows:
        full=_facts_for(source.kind,source.action_window,source.summarized_window,blocks,offer_rows,cast_rows)
        if len(full)<=MAX_ITEMS and all(len(f)<=MAX_FACT_TEXT for f in full) and sum(map(len,full))<=MAX_CONTEXT_TEXT:
            facts=full; break
        cast_rows.pop()
    narrative={'audience':'public' if source.audience_key=='public' else 'private','audience_key':source.audience_key,
               'facts':facts,'references':[r['alias'] for r in references],
               'catalog_ids':[o['alias'] for o in offer_rows],'window_idx':source.action_window,
               'case_hash':case_hash,'ruleset_version':ruleset_version}
    doc={'schema':SCHEMA_CAST if cast_rows else SCHEMA,'narrative':narrative,'reference_map':references,'exact_blocks':blocks,
         'offers':offer_rows,'references':[source.cause_id], 'catalog_ids':[],
         'summarized_window':source.summarized_window,'action_window':source.action_window}
    if cast_rows: doc['cast']=cast_rows
    doc['context_hash']=_hash(doc)
    narrative['knowledge_revision']=doc['context_hash']
    if len(_canonical(doc))>65536 or len(_canonical({'request_token':'0'*64,'kind':source.kind,
        'facts':facts,'references':narrative['references'],'catalog_ids':narrative['catalog_ids']}))>32768:
        raise ContextUnavailable('critical context cannot fit encoded budget')
    result=FrozenContext.from_document(doc,input_hash=_hash(doc),source=source)
    result._fallback=fallback
    result._expires_at=min(created_at+timedelta(minutes=5),closes_at)
    return result


def validate_director_result(context: FrozenContext, result, *, job_id, now, current_window,
                             cause_id=None, kind=None, expires_at=None, fallback=None):
    d=context.document()
    job=context.narrative_job(job_id=job_id,cause_id=cause_id,kind=kind,expires_at=expires_at,fallback=fallback)
    fallback=RenderingDecision(job.fallback,'fallback')
    if type(current_window) is not int or current_window!=d['action_window']: return fallback
    decision=validate_narrative_result(job,result,now=now)
    if decision.source!='candidate': return fallback
    try:
        text=_text(decision.text)
        if ('<' in text or '>' in text or re.search(r'(?:https?://|www\.|\[[^\]]+\]\([^)]+\))',text,re.I)):
            return fallback
        if len(decision.catalog_ids)>(1 if job.kind=='story_offer' else 0): return fallback
    except ValueError: return fallback
    return decision
