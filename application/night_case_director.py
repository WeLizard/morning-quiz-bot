"""Optional, transaction-scoped Night Case narration source assignment.

The application supplies already applied transitions. No model, network call,
gameplay command or advisory lock is performed here.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re

from sqlalchemy import select

from domain.night_case_director import (
    AuthorizedSource, ContextUnavailable, SafeOffer, SafeRecord,
    audience_permitted, build_frozen_context,
)
from domain.night_case_projection import MenuChoice, available_actions
from domain.night_case_state import PlayerActor, event_scope
from storage.models import NightEvent, NightRenderJob
from storage.night_ai_models import (
    NightAIBinding, NightAIGameControl, NightAIJobBinding, NightAIProfile,
    NightAIProfileRevision,
)
from storage.night_cases import NightCaseRepository, canonical_json


_HASH = re.compile(r'[0-9a-f]{64}\Z')
_EVENT_LABELS = {
    'window':'Открыто окно', 'status':'Изменился статус персонажа',
    'hearing':'Началось или завершилось слушание', 'final':'Дело завершено',
    'board':'Публикация на доске', 'world_changed':'Изменилось общее состояние',
    'observation_granted':'Выдана карточка', 'archive_requested':'Запрошен архив',
    'version_marked':'Отмечена версия', 'npc_revealed':'Появился персонаж',
    'story_return_closed':'Решение по письму зафиксировано',
}
_BODY_KINDS = {'action_result','archive_response','scene','story_result',
               'story_offer','story_epilogue','authored_card_delivered'}
_OFFER_KINDS = {'move','act','talk','archive_request','version_mark'}


def stable_job_id(game_id: str, cause_id: str, kind: str, audience_key: str, template_hash: str) -> str:
    if not isinstance(template_hash,str) or not _HASH.fullmatch(template_hash):
        raise ValueError('invalid director template hash')
    raw=json.dumps(['night-director/1',game_id,cause_id,kind,audience_key,template_hash],
                   ensure_ascii=False,separators=(',',':')).encode('utf-8')
    return 'nr_'+hashlib.sha256(raw).hexdigest()


def _stamp(value):
    if not isinstance(value,str): raise ValueError('source clock missing')
    dt=datetime.fromisoformat(value.replace('Z','+00:00'))
    if dt.tzinfo is None or dt.utcoffset()!=timedelta(0): raise ValueError('source clock not UTC')
    return dt.astimezone(timezone.utc)


def _scope(event):
    return event_scope(event['audience'])


def _check_row(game_id, expected, row):
    if (row is None or row.game_id!=game_id or row.event_id!=expected['event_id']
            or row.kind!=expected['kind'] or row.scope!=_scope(expected)
            or type(row.window_idx) is not int or row.window_idx!=expected['window_idx']
            or type(row.audience_seq) is not int or row.audience_seq!=expected['audience_seq']
            or canonical_json(row.payload)!=canonical_json(expected['payload'])):
        raise ValueError('director_source_corrupt')


def _event_body(event):
    kind=event['kind']
    if kind in _BODY_KINDS:
        body=event['payload'].get('body')
        if type(body) is not dict or type(body.get('text')) is not str:
            raise ValueError('director_event_body_corrupt')
        return body['text']
    try: return _EVENT_LABELS[kind]
    except KeyError as exc: raise ValueError('director_event_kind_unhandled') from exc


def _known_observation(doc, account_id, oid):
    if any(o['observation_id']==oid for o in doc['public']['observations']): return True
    if any(b['observation_id']==oid for b in doc['public']['board']): return True
    return account_id is not None and any(k['account_id']==account_id and k['observation_id']==oid for k in doc['knowledge'])


def _observation_record(case_doc, doc, oid, account_id, parent):
    if not _known_observation(doc,account_id,oid): raise ValueError('director_observation_acl')
    item=next((o for o in case_doc['observations'] if o['id']==oid),None)
    if item is None: raise ValueError('director_observation_missing')
    speaker=None
    if item['kind']=='claim':
        character=next((c for c in case_doc['characters'] if c['id']==item.get('speaker')),None)
        speaker=character['title'] if character is not None else 'участник'
    return SafeRecord('observation',oid,item['kind'],item['body']['text'],_scope(parent),
                      parent['window_idx'],parent['event_id'],speaker)


def _event_observation_link(doc, event, oid):
    payload=event['payload']
    if payload.get('observation_id')==oid or oid in payload.get('observation_ids',()):
        return True
    if event['kind']=='board':
        board=next((b for b in doc['public']['board'] if b['id']==payload['board_id']),None)
        return board is not None and board['observation_id']==oid
    return False


@dataclass(frozen=True)
class DirectorPlan:
    source: AuthorizedSource
    context: object
    fallback: str
    expires_at: datetime
    audience_seq: int


def plan_sources(context, transition, stored_events) -> tuple[DirectorPlan,...]:
    """Select only new event causes; stored_events are freshly read PG rows by ID."""
    case_doc=context.case.document()
    doc=transition.state.document()
    game_id=context.locked.game.id
    state_events={e['event_id']:e for e in doc['public']['chronicle']+doc['private_events']}
    for event in transition.events:
        if state_events.get(event['event_id'])!=event:
            raise ValueError('director_source_not_in_sealed_state')
        _check_row(game_id,event,stored_events.get(event['event_id']))
    close=_stamp(doc['clock']['closes_at']) if doc['clock']['closes_at'] else None
    plans=[]
    for event in transition.events:
        kind=event['kind']
        if kind not in {'window_digest','scene','action_result'}: continue
        if doc['clock']['window_idx']!=event['window_idx'] or doc['clock']['phase']!='investigation' or close is None:
            continue
        row=stored_events[event['event_id']]
        expires=min(row.created_at+timedelta(minutes=5),close)
        if expires<=context.now: continue
        audience=_scope(event)
        if audience.startswith('account:'):
            recipient=next((p for p in doc['players'] if p['account_id']==audience.removeprefix('account:')),None)
            if recipient is None or recipient['status'] not in {'active','fog'}:
                # Exact kernel/history already retain this event. An optional
                # artistic job cannot materialize a departed/ghost audience.
                continue
        if kind=='action_result':
            summary=context.command_summary
            receipt=next((r for r in reversed(doc['receipts']) if r['actor_key']==audience
                and r['accepted'] and r['result_ref']=={'kind':'event','event_id':event['event_id']}),None)
            if (type(summary) is not dict or set(summary)!={'kind','target_character_id'}
                    or summary['kind']!='talk' or transition.receipt is None or not transition.receipt['accepted']
                    or receipt is None
                    or audience!='account:'+context.actor_key):
                continue
            target=summary['target_character_id']
            npc=next((n for n in doc['npcs'] if n['character_id']==target and n['status']=='active'),None)
            character=next((c for c in case_doc['characters'] if c['id']==target),None)
            if npc is None or character is None or any(p['character_id']==target for p in doc['players']): continue
            source=AuthorizedSource('npc_reply',event['event_id'],audience,event['window_idx'],None,
                (event['event_id'],),tuple(event['payload']['observation_ids']),_event_body(event),character['title'])
            account=context.actor_key
            records=tuple(_observation_record(case_doc,doc,oid,account,event) for oid in source.observation_ids)
            fallback=source.body if len(source.body)<=4000 else 'Ответ персонажа сохранён в точных событиях.'
            candidates=[(source,records,(),fallback)]
        elif kind=='scene':
            if audience!='public': raise ValueError('director_scene_audience_corrupt')
            source=AuthorizedSource('scene_narration',event['event_id'],'public',event['window_idx'],None,
                                    (),(),_event_body(event))
            fallback=source.body if len(source.body)<=4000 else 'Авторская сцена сохранена в точных событиях.'
            candidates=[(source,(),(),fallback)]
        else:
            if not audience.startswith('account:'): raise ValueError('director_digest_audience_corrupt')
            summarized=event['payload']['window_idx']
            refs=tuple(event['payload']['event_ids']); obs=tuple(event['payload']['observation_ids'])
            resolved=[]
            for eid in refs:
                old=state_events.get(eid)
                if old is None: raise ValueError('director_digest_missing_event')
                _check_row(game_id,old,stored_events.get(eid))
                if old['window_idx']!=summarized or _scope(old) not in {'public',audience}:
                    raise ValueError('director_digest_foreign_event')
                resolved.append(old)
            records=[SafeRecord('event',old['event_id'],'scene' if old['kind']=='scene' else 'result',
                                _event_body(old),_scope(old),old['window_idx']) for old in resolved]
            account=audience.removeprefix('account:')
            for oid in obs:
                parent=next((old for old in resolved if _event_observation_link(doc,old,oid)),None)
                if parent is None: raise ValueError('director_digest_observation_unlinked')
                records.append(_observation_record(case_doc,doc,oid,account,parent))
            source=AuthorizedSource('window_digest',event['event_id'],audience,event['window_idx'],
                                    summarized,refs,obs,'')
            candidates=[(source,tuple(records),(),'Окно завершено.')]
            player=next((p for p in doc['players'] if p['account_id']==account),None)
            if player is not None and player['status'] in {'active','fog'}:
                options=[e for e in available_actions(context.case,context.rules,transition.state,
                    PlayerActor(account),now_utc=context.now) if isinstance(e,MenuChoice) and e.quote.kind in _OFFER_KINDS]
                options=tuple(SafeOffer(e) for e in sorted(options,key=lambda e:(e.quote.kind,e.label,e.entry_id))[:3])
                if options:
                    offer=AuthorizedSource('story_offer',event['event_id'],audience,event['window_idx'],
                                           summarized,refs,obs,'')
                    candidates.append((offer,(),options,'Доступные действия показаны в меню.'))
        for source,records,offers,fallback in candidates:
            try:
                frozen=build_frozen_context(source,records,offers,case_hash=context.case.content_hash,
                    ruleset_version='core/'+str(case_doc['ruleset_ref']['version']),fallback=fallback,
                    created_at=row.created_at,closes_at=close)
            except ContextUnavailable:
                continue  # Artistic context is optional; committed exact events remain.
            plans.append(DirectorPlan(source,frozen,fallback,expires,row.audience_seq))
    return tuple(plans)


class NightCaseDirectorHook:
    """No factory registration here; caller owns the enclosing Game transaction."""
    def __init__(self, session, *, template_hash: str):
        if type(template_hash) is not str or not _HASH.fullmatch(template_hash):
            raise ValueError('director template hash required')
        self.session,self.template_hash=session,template_hash
        self.repo=NightCaseRepository(session)

    async def _events(self, context, transition):
        ids={e['event_id'] for e in transition.events}
        for e in transition.events:
            if e['kind']=='window_digest': ids.update(e['payload']['event_ids'])
        if not ids: return {}
        rows=(await self.session.scalars(select(NightEvent).where(NightEvent.game_id==context.locked.game.id,
            NightEvent.event_id.in_(ids)).execution_options(populate_existing=True))).all()
        return {row.event_id:row for row in rows}

    async def _assignment(self, context, audience):
        game_id=context.locked.game.id
        async def get(model,*conditions):
            return await self.session.scalar(select(model).where(*conditions).execution_options(populate_existing=True))
        control=await get(NightAIGameControl,NightAIGameControl.game_id==game_id)
        if control is None: return 0,None,'authored'
        epoch=control.epoch
        if control.current_binding_id is None:
            return epoch,None,'binding_unavailable' if epoch>0 else 'authored'
        binding=await get(NightAIBinding,NightAIBinding.id==control.current_binding_id)
        if (binding is None or binding.game_id!=game_id or binding.epoch!=epoch or binding.status!='active'
                or binding.health!='ok' or binding.valid_until<=context.now):
            return epoch,None,'binding_unavailable'
        if not audience_permitted(binding.mode,str(control.starter_account_id),audience):
            return epoch,None,'byok_audience_denied'
        profile=await get(NightAIProfile,NightAIProfile.id==binding.profile_id)
        revision=await get(NightAIProfileRevision,NightAIProfileRevision.profile_id==binding.profile_id,
            NightAIProfileRevision.revision==binding.profile_revision)
        if (profile is None or not profile.enabled or revision is None or revision.config_hash!=binding.config_hash
                or profile.scope!=('admin' if binding.mode=='admin' else 'game')
                or (binding.mode=='byok' and profile.game_id!=game_id)):
            return epoch,None,'binding_unavailable'
        config=revision.config
        try:
            expected=hashlib.sha256(canonical_json({k:v for k,v in config.items() if k!='config_hash'})).hexdigest()
            if (config['config_hash']!=expected or expected!=binding.config_hash
                    or config['credential_id']!=(str(revision.credential_id) if revision.credential_id else None)
                    or binding.mode=='byok' and revision.credential_id is None):
                return epoch,None,'binding_unavailable'
        except (TypeError,KeyError,ValueError,UnicodeError):
            return epoch,None,'binding_unavailable'
        return epoch,binding.id,None

    async def _count(self, game_id, audience, kind, window):
        rows=(await self.session.scalars(select(NightRenderJob).where(NightRenderJob.game_id==game_id,
            NightRenderJob.audience_key==audience,NightRenderJob.kind==kind).limit(100)
            .execution_options(populate_existing=True))).all()
        if len(rows)==100: raise ValueError('director_job_cap_corrupt')
        return sum(type(row.frozen_view) is dict and row.frozen_view.get('action_window')==window for row in rows)

    async def __call__(self, context, transition):
        rows=await self._events(context,transition)
        for plan in plan_sources(context,transition,rows):
            source=plan.source
            game_id=context.locked.game.id
            job_id=stable_job_id(game_id,source.cause_id,source.kind,source.audience_key,self.template_hash)
            prior=await self.session.get(NightRenderJob,job_id,populate_existing=True)
            if prior is not None:
                assignment=await self.session.get(NightAIJobBinding,job_id,populate_existing=True)
                if (assignment is None or assignment.game_id!=game_id
                        or prior.game_id!=game_id or prior.cause_id!=source.cause_id
                        or prior.kind!=source.kind or prior.audience_key!=source.audience_key
                        or prior.knowledge_revision!=plan.audience_seq
                        or prior.template_version!=self.template_hash
                        or prior.input_hash!=plan.context.input_hash
                        or canonical_json(prior.frozen_view)!=canonical_json(plan.context.document())
                        or prior.expires_at!=plan.expires_at or prior.fallback!=plan.fallback):
                    raise ValueError('director_job_replay_corrupt')
                continue
            cap=2 if source.kind=='npc_reply' else 1
            if await self._count(context.locked.game.id,source.audience_key,source.kind,source.action_window)>=cap:
                continue
            ghost=False
            if source.audience_key.startswith('account:'):
                account=source.audience_key.removeprefix('account:')
                player=next((p for p in transition.state.players if p['account_id']==account),None)
                ghost=player is None or player['status'] not in {'active','fog'}
            epoch,binding_id,reason=await self._assignment(context,source.audience_key)
            if ghost: binding_id,reason=None,'authored'
            job=NightRenderJob(job_id=job_id,game_id=game_id,cause_id=source.cause_id,kind=source.kind,
                audience_key=source.audience_key,knowledge_revision=plan.audience_seq,
                template_version=self.template_hash,frozen_view=plan.context.document(),
                input_hash=plan.context.input_hash,expires_at=plan.expires_at,fallback=plan.fallback,
                status='pending',attempts=0)
            await self.repo.enqueue_render(job)
            self.session.add(NightAIJobBinding(job_id=job_id,game_id=game_id,epoch=epoch,
                binding_id=binding_id,fallback_reason=reason,created_at=context.now))
            await self.session.flush()
