"""Operator-only recovery trace from a valid saved Night Case snapshot.

This is a codec/trace recovery, never a replacement-state editor or a replay of
all game history. Coverage is game-local; global outage history stays immutable.
"""
from __future__ import annotations

import copy
import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select

from application.night_case import (
    NightCaseApplicationService, NightCaseError, OperatorPrincipal, _parse, _stamp,
)
from domain.night_case_engine import _due, step
from domain.night_case_state import SystemActor, decode_state, encode_state, parse_command
from storage.admin_actions import operation_fence
from storage.models import GameCommand, GameDeadline, NightRuntimeOutage
from storage.night_cases import MAX_RECORD_BYTES, NightStorageConflict, canonical_json, json_hash, command_key

SCHEMA = 'night-quarantine-recovery/1'
KIND = 'night.quarantine_recovery'
MAX_INTERVALS = 16
MAX_SOURCES = 64
MAX_AUDITS = 32
HASH = re.compile('[0-9a-f]{64}\\Z')


def _fail(code='recovery_audit_invalid'):
    raise NightCaseError(code,503)


def _text(value, maximum=128):
    return type(value) is str and 1 <= len(value) <= maximum and not any(ord(c)<32 for c in value)


def _hash(value):
    return type(value) is str and HASH.fullmatch(value) is not None


def _interval(value, *, covered=False):
    fields={'outage_id','unavailable_from','resumed_at'} | ({'covered_global_ids'} if covered else set())
    if type(value) is not dict or set(value)!=fields or not _text(value['outage_id'],96): _fail()
    try:
        start,end=_parse(value['unavailable_from']),_parse(value['resumed_at'])
        if _stamp(start)!=value['unavailable_from'] or _stamp(end)!=value['resumed_at'] or not start<end: _fail()
    except (ValueError,TypeError,AttributeError): _fail()
    if covered: _ids(value['covered_global_ids'])
    return start,end


def _ids(value):
    if type(value) is not list or len(value)>MAX_SOURCES or any(not _text(v,96) for v in value) or len(set(value))!=len(value): _fail()


def decode_recovery_audit(value):
    """Closed, bounded operator audit codec shared by recovery and readonly W."""
    fields={'schema','game_id','review_ref','initial_snapshot_hash','final_snapshot_hash','failed_generation',
        'recovered_at','source_outages','intervals','commands','covered_global_ids'}
    if type(value) is not dict or set(value)!=fields or value['schema']!=SCHEMA: _fail()
    if not _text(value['game_id'],64) or not _text(value['review_ref'],500) or not all(_hash(value[k]) for k in ('initial_snapshot_hash','final_snapshot_hash')): _fail()
    try:
        canonical_json(value,max_bytes=MAX_RECORD_BYTES)
        recovered=_parse(value['recovered_at'])
        if _stamp(recovered)!=value['recovered_at']: _fail()
    except (ValueError,TypeError,AttributeError): _fail()
    generation=value['failed_generation']
    if (type(generation) is not dict or set(generation)!={'deadline_id','timer_seq','due_at'}
            or not _text(generation['deadline_id'],96) or type(generation['timer_seq']) is not int or generation['timer_seq']<1): _fail()
    try:
        if _stamp(_parse(generation['due_at']))!=generation['due_at']: _fail()
    except (ValueError,TypeError,AttributeError): _fail()
    _ids(value['covered_global_ids'])
    if type(value['source_outages']) is not list or len(value['source_outages'])>MAX_SOURCES: _fail()
    sources={}; source_end=None
    for source in value['source_outages']:
        start,end=_interval(source)
        if end>recovered or source['outage_id'] in sources or (source_end is not None and start<source_end): _fail()
        source_end=end
        sources[source['outage_id']]=(start,end)
    if set(sources)!=set(value['covered_global_ids']): _fail()
    if type(value['intervals']) is not list or not 1<=len(value['intervals'])<=MAX_INTERVALS: _fail()
    if type(value['commands']) is not list or len(value['commands'])!=len(value['intervals']): _fail()
    previous_end=None; previous_hash=value['initial_snapshot_hash']; covered_ids=[]; interval_ids=set()
    for interval,trace in zip(value['intervals'],value['commands']):
        start,end=_interval(interval,covered=True)
        if end>recovered or (previous_end is not None and start<=previous_end) or interval['outage_id'] in interval_ids: _fail()
        previous_end=end; interval_ids.add(interval['outage_id'])
        for oid in interval['covered_global_ids']:
            if oid not in sources or not start<=sources[oid][0]<sources[oid][1]<=end: _fail()
        covered_ids.extend(interval['covered_global_ids'])
        if type(trace) is not dict or set(trace)!={'command','receipt','before_hash','after_hash'}: _fail()
        if trace['before_hash']!=previous_hash or not _hash(trace['after_hash']): _fail()
        try: command=parse_command(trace['command'],SystemActor(),ruleset_version=2).document()
        except (ValueError,TypeError): _fail()
        expected={k:interval[k] for k in ('outage_id','unavailable_from','resumed_at')}
        if command['kind']!='system.resume' or command['params']!=expected: _fail()
        receipt=trace['receipt']
        if (type(receipt) is not dict or set(receipt)!={'accepted','code','actor_revision'} or receipt['accepted'] is not True
                or receipt['code']!='accepted' or type(receipt['actor_revision']) is not int or receipt['actor_revision']<0): _fail()
        previous_hash=trace['after_hash']
    if previous_hash!=value['final_snapshot_hash'] or len(covered_ids)!=len(set(covered_ids)) or set(covered_ids)!=set(sources): _fail()
    # The reviewed local pause must actually be covered, not merely asserted.
    due=_parse(generation['due_at'])
    if not any(_parse(i['unavailable_from'])<=due<recovered<=_parse(i['resumed_at']) for i in value['intervals']): _fail()
    return copy.deepcopy(value)


async def recovery_coverage(session,game_id):
    """Read-only, bounded and called only after the caller's Game/fence boundary."""
    rows=list((await session.scalars(select(GameCommand).where(GameCommand.game_id==game_id,
        GameCommand.kind==KIND,GameCommand.status=='applied').order_by(GameCommand.id).limit(MAX_AUDITS+1))).all())
    if len(rows)>MAX_AUDITS: _fail('recovery_coverage_limit')
    intervals=[]; source_hashes={}
    for row in rows:
        audit=decode_recovery_audit(row.result)
        if audit['game_id']!=game_id: _fail()
        wrapper=row.payload
        if (type(wrapper) is not dict or set(wrapper)!={'client_command_id','actor_key','command','payload_hash'}
                or not _text(wrapper['actor_key'],128) or not wrapper['actor_key'].startswith('operator:')
                or len(wrapper['actor_key'])<=9 or not _text(wrapper['client_command_id'],64) or len(wrapper['client_command_id'])<8
                or row.id!=command_key(game_id,wrapper['actor_key'],wrapper['client_command_id'])
                or type(wrapper['command']) is not dict or set(wrapper['command'])!={'schema','expected_snapshot_hash','review_ref'}
                or wrapper['command']!={'schema':SCHEMA,'expected_snapshot_hash':audit['initial_snapshot_hash'],'review_ref':audit['review_ref']}
                or wrapper['payload_hash']!=json_hash(wrapper['command'])): _fail()
        intervals.extend((_parse(i['unavailable_from']),_parse(i['resumed_at'])) for i in audit['intervals'])
        for source in audit['source_outages']:
            fingerprint=json_hash(source)
            prior=source_hashes.setdefault(source['outage_id'],fingerprint)
            if prior!=fingerprint: _fail('recovery_source_conflict')
    merged=[]
    for start,end in sorted(intervals):
        if merged and start<=merged[-1][1]: merged[-1]=(merged[-1][0],max(end,merged[-1][1]))
        else: merged.append((start,end))
    return RecoveryCoverage(tuple(merged),tuple(sorted(source_hashes.items())))


@dataclass(frozen=True)
class RecoveryCoverage:
    intervals: tuple[tuple[datetime,datetime],...]
    source_payload_hashes: tuple[tuple[str,str],...]

    def __iter__(self):
        return iter(self.intervals)

    def verify_source(self,source):
        expected=dict(self.source_payload_hashes).get(source['outage_id'])
        if expected is not None and expected!=json_hash(source): _fail('recovery_source_conflict')


def coverage_status(start,end,coverage):
    """A late fully covered outage is safe; a partial overlap needs review."""
    if any(left<=start<end<=right for left,right in coverage): return 'covered'
    if any(start<right and left<end for left,right in coverage): _fail('recovery_coverage_overlap')
    return 'uncovered'


def _union(sources,pause):
    candidates=[(start,end,{oid}) for oid,start,end in sources]+[(pause[0],pause[1],set())]
    merged=[]
    for start,end,ids in sorted(candidates,key=lambda item:(item[0],item[1])):
        if merged and start<=merged[-1][1]:
            old_start,old_end,old_ids=merged[-1]
            merged[-1]=(old_start,max(end,old_end),old_ids|ids)
        else: merged.append((start,end,ids))
    if len(merged)>MAX_INTERVALS: _fail('recovery_audit_too_large')
    return merged


class NightCaseRecoveryService:
    def __init__(self,session,clock,registry):
        self.session,self.clock,self.registry=session,clock,registry
        self.application=NightCaseApplicationService(session,clock,registry)
        self.repo=self.application.repo

    async def recover_quarantine(self,*,operator: OperatorPrincipal,game_id,request_id,expected_snapshot_hash,review_ref):
        await operation_fence(self.session)
        async with self.session.begin_nested():
            try:
                return await self._recover(operator,game_id,request_id,expected_snapshot_hash,review_ref)
            except NightStorageConflict as exc:
                raise NightCaseError('recovery_command_conflict',409) from exc

    async def _recover(self,operator,game_id,request_id,expected_snapshot_hash,review_ref):
        if (not isinstance(operator,OperatorPrincipal) or not _text(operator.operator_id,119)
                or not _text(game_id,64) or not _text(request_id,64) or len(request_id)<8 or not _hash(expected_snapshot_hash) or not _text(review_ref,500)):
            raise NightCaseError('invalid_recovery_request',422)
        if operator.account_id is not None: await self.application._principal(operator.account_id)
        actor='operator:'+operator.operator_id
        payload={'schema':SCHEMA,'expected_snapshot_hash':expected_snapshot_hash,'review_ref':review_ref}
        prior=await self.repo.command_receipt(game_id,actor,request_id,json_hash(payload))
        if prior: return decode_recovery_audit(prior.result)
        locked=await self.repo.lock_game(game_id)
        if locked is None: raise NightCaseError('unavailable',404)
        deadline=(await self.session.execute(select(GameDeadline).where(GameDeadline.game_id==game_id,
            GameDeadline.kind=='night.phase').with_for_update())).scalar_one_or_none()
        prior=await self.repo.command_receipt(game_id,actor,request_id,json_hash(payload))
        if prior: return decode_recovery_audit(prior.result)
        if (locked.sealed.lifecycle!='running' or deadline is None or deadline.quarantined_at is None
                or deadline.status!='quarantined' or deadline.id!='night:'+game_id+':phase' or deadline.attempts<3):
            raise NightCaseError('recovery_generation_unavailable',409)
        if locked.sealed.snapshot_hash!=expected_snapshot_hash: raise NightCaseError('recovery_snapshot_conflict',409)
        case,rules,state=await self.application._runtime(locked)
        initial=encode_state(state); doc=state.document(); now=self.clock(); _stamp(now)
        due=_due(doc)
        if (doc['clock']['phase'] not in {'investigation','final_hearing'} or due is None
                or deadline.revision!=doc['clock']['timer_seq'] or deadline.due_at!=_parse(due['at'])
                or not deadline.due_at<now or deadline.quarantined_at>now):
            raise NightCaseError('recovery_generation_unavailable',409)
        generation={'deadline_id':deadline.id,'timer_seq':deadline.revision,'due_at':_stamp(deadline.due_at)}
        coverage=await recovery_coverage(self.session,game_id)
        if coverage_status(deadline.due_at,now,coverage)!='uncovered': _fail('recovery_coverage_overlap')
        started=locked.game.started_at
        if started is None or not started<=deadline.due_at: _fail('recovery_snapshot_invalid')
        global_rows=list((await self.session.scalars(select(NightRuntimeOutage).where(NightRuntimeOutage.ended_at.is_not(None),
            NightRuntimeOutage.ended_at>started).order_by(NightRuntimeOutage.started_at).limit(MAX_SOURCES+1))).all())
        if len(global_rows)>MAX_SOURCES: _fail('recovery_audit_too_large')
        applied={r['outage_id']:r['payload_hash'] for r in doc['clock']['resume_receipts']}
        sources=[]; source_docs=[]
        for row in global_rows:
            start,end=max(started,row.started_at),row.ended_at
            if not start<end<=now: _fail('recovery_outage_invalid')
            source={'outage_id':row.outage_id,'unavailable_from':_stamp(start),'resumed_at':_stamp(end)}
            _interval(source)
            coverage.verify_source(source)
            if row.outage_id in applied:
                if applied[row.outage_id]!=json_hash(source): _fail('recovery_source_conflict')
                continue
            if coverage_status(start,end,coverage)=='covered': continue
            sources.append((row.outage_id,start,end)); source_docs.append(source)
        intervals=[]
        for index,(start,end,ids) in enumerate(_union(sources,(deadline.due_at,now))):
            oid='recovery_'+json_hash([game_id,request_id,index,_stamp(start),_stamp(end)])[:56]
            intervals.append({'outage_id':oid,'unavailable_from':_stamp(start),'resumed_at':_stamp(end),'covered_global_ids':sorted(ids)})
        transitions=[]; traces=[]; current=state
        for interval in intervals:
            before=hashlib.sha256(encode_state(current)).hexdigest(); clock=current.clock
            params={key:interval[key] for key in ('outage_id','unavailable_from','resumed_at')}
            raw={'command_id':'recovery_'+json_hash([game_id,request_id,params])[:55],'kind':'system.resume',
                'window_seq':clock['window_seq'],'timer_seq':clock['timer_seq'],'params':params}
            transition=step(case,rules,current,SystemActor(),raw,now_utc=_parse(interval['resumed_at']))
            if not transition.receipt['accepted']: _fail('recovery_resume_refused')
            current=transition.state; transitions.append(transition)
            traces.append({'command':raw,'receipt':transition.receipt,'before_hash':before,
                'after_hash':hashlib.sha256(encode_state(current)).hexdigest()})
        audit={'schema':SCHEMA,'game_id':game_id,'review_ref':review_ref,'initial_snapshot_hash':expected_snapshot_hash,
            'final_snapshot_hash':hashlib.sha256(encode_state(current)).hexdigest(),'failed_generation':generation,
            'recovered_at':_stamp(now),'source_outages':source_docs,'intervals':intervals,'commands':traces,
            'covered_global_ids':sorted(s['outage_id'] for s in source_docs)}
        try: canonical_json(audit,max_bytes=MAX_RECORD_BYTES)
        except ValueError as exc: raise NightCaseError('recovery_audit_too_large',503) from exc
        decode_recovery_audit(audit)
        # Independent trace replay from the same saved snapshot, not from world history.
        replay=decode_state(initial,case,rules)
        for interval,trace in zip(intervals,traces):
            check=step(case,rules,replay,SystemActor(),trace['command'],now_utc=_parse(interval['resumed_at']))
            if check.receipt!=trace['receipt'] or hashlib.sha256(encode_state(check.state)).hexdigest()!=trace['after_hash']: _fail('recovery_trace_mismatch')
            replay=check.state
        if encode_state(replay)!=encode_state(current): _fail('recovery_trace_mismatch')
        for transition,trace in zip(transitions,traces):
            actual=await self.application._persist(locked,case,rules,transition,now,'system',trace['command']['command_id'])
            if encode_state(actual)!=encode_state(transition.state): _fail('recovery_trace_mismatch')
            await self.repo.put_command_receipt(game_id=game_id,actor_key='system',actor_account_id=None,
                client_command_id=trace['command']['command_id'],kind='system.resume',payload=trace['command'],
                result={'receipt':{'command_id':trace['command']['command_id'],**trace['receipt']},'caused_event_ids':[],
                'caused_message_ids':[]},status='applied',now=now)
        if locked.sealed.snapshot_hash!=audit['final_snapshot_hash']: _fail('recovery_trace_mismatch')
        await self.session.refresh(deadline)
        if deadline.revision!=current.clock['timer_seq'] or deadline.due_at<=now: _fail('recovery_deadline_invalid')
        deadline.status='pending'; deadline.attempts=0; deadline.last_error_code=None; deadline.retry_at=None
        deadline.quarantined_at=None; deadline.claimed_by=None; deadline.claimed_at=None; deadline.completed_at=None
        await self.repo.put_command_receipt(game_id=game_id,actor_key=actor,actor_account_id=operator.account_id,
            client_command_id=request_id,kind=KIND,payload=payload,result=audit,status='applied',now=now)
        await self.session.flush()
        return audit
