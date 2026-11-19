import copy
import hashlib
import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from domain.night_case_narrative import LegalAction
from domain.night_case_projection import MenuChoice, available_actions
from domain.night_case_engine import _event, _digest, _initialize
from domain.night_case_state import PlayerActor, rules_snapshot
from domain.night_case_v2_format import compile_v2, load_v2
from domain.night_case_director import (
    AuthorizedSource, SafeRecord, SafeOffer, ContextUnavailable,
    build_frozen_context, FrozenContext, validate_director_result, audience_permitted,
)


NOW = datetime(2026, 11, 16, 12, tzinfo=timezone.utc)
ACCOUNT_ID = '00000000-0000-0000-0000-000000000001'
ACCOUNT = 'account:' + ACCOUNT_ID


def digest(*, event_window=2, summary_window=1):
    return AuthorizedSource('window_digest', 'digest-2', ACCOUNT, event_window,
                            summary_window, ('event-1',), ('proof-a',), '')


def record(body='Старая улика', *, audience=ACCOUNT, parent='event-1', window=1):
    return SafeRecord('observation', 'proof-a', 'proof', body, audience, window, parent)


def built(source=None, records=None, offers=()):
    return build_frozen_context(source or digest(), records if records is not None else
                                (SafeRecord('event', 'event-1', 'result', 'Дверь открыта', ACCOUNT, 1), record()),
                                offers, case_hash='c' * 64, ruleset_version='core/2',
                                fallback='Авторская сводка.', created_at=NOW,
                                closes_at=NOW + timedelta(minutes=20))


def rehash(document):
    data=copy.deepcopy(document)
    data['narrative'].pop('knowledge_revision',None)
    data.pop('context_hash',None)
    encoded=lambda value: json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')
    data['context_hash']=hashlib.sha256(encoded(data)).hexdigest()
    data['narrative']['knowledge_revision']=data['context_hash']
    return data,hashlib.sha256(encoded(data)).hexdigest()


class DirectorTests(unittest.TestCase):
    def test_real_visible_offer_is_variant_invariant(self):
        path=Path(__file__).parent/'fixtures'/'night_city'/'core_case_v2.json'
        case=compile_v2(load_v2(path.read_bytes()))
        rules=rules_snapshot('Europe/Berlin')
        ids=[f'00000000-0000-0000-0000-{i:012d}' for i in range(1,5)]
        roster={'players':[{'account_id':aid,'display_name':f'Player {i}'} for i,aid in enumerate(ids)],
                'npc_name_pool':[f'NPC {i}' for i in range(20)]}
        now=datetime(2026,11,15,10,tzinfo=timezone.utc)
        frozen=[]
        for variant in ('variant_a','variant_b'):
            transition=_initialize(case,rules,roster,game_id='testgame',seed=42,
                composition_id='players_04',selected_variant_id=variant,now_utc=now)
            digest_event=next(e for e in transition.events if e['kind']=='window_digest' and e['audience']['ids']==[ids[0]])
            visible=next(e for e in available_actions(case,rules,transition.state,PlayerActor(ids[0]),now_utc=now)
                         if isinstance(e,MenuChoice) and e.quote.kind=='move')
            source=AuthorizedSource('story_offer',digest_event['event_id'],'account:'+ids[0],
                digest_event['window_idx'],digest_event['payload']['window_idx'],
                tuple(digest_event['payload']['event_ids']),tuple(digest_event['payload']['observation_ids']),'')
            ctx=build_frozen_context(source,(),(SafeOffer(visible),),case_hash=case.content_hash,
                ruleset_version='core/2',fallback='Авторское предложение.',created_at=now,
                closes_at=now+timedelta(minutes=20))
            frozen.append(ctx.document())
        self.assertEqual(frozen[0],frozen[1])
        self.assertNotIn('variant_b',str(frozen[1]['narrative']))

    def test_real_digest_event_binds_previous_summary_to_open_window(self):
        doc={'game_id':'g','clock':{'window_idx':1},'public':{'chronicle':[],'board':[],'revision':0},'private_events':[]}
        batch=[]
        old=_event(doc,batch,'action_result',{'body':'Старый результат','observation_ids':[]},ACCOUNT_ID)
        doc['clock']['window_idx']=2
        _digest(doc,batch,ACCOUNT_ID,1)
        current=batch[-1]
        self.assertEqual((current['window_idx'],current['payload']['window_idx']),(2,1))
        source=AuthorizedSource('window_digest',current['event_id'],ACCOUNT,current['window_idx'],
                                current['payload']['window_idx'],tuple(current['payload']['event_ids']),(), '')
        ctx=built(source,(SafeRecord('event',old['event_id'],'result',old['payload']['body'],ACCOUNT,1),))
        self.assertNotIn('SEALED_OTHER_VARIANT_CANARY',str(ctx.narrative_job(job_id='j').provider_payload))
        self.assertEqual(ctx.document()['action_window'],2)

    def test_digest_summary_and_action_windows_remain_separate(self):
        ctx = built()
        self.assertEqual(ctx.document()['summarized_window'], 1)
        self.assertEqual(ctx.document()['action_window'], 2)
        job = ctx.narrative_job(job_id='job', expires_at=NOW + timedelta(minutes=5))
        self.assertEqual(job.view.window_idx, 2)
        self.assertIn('окно 1', ' '.join(job.view.facts))
        self.assertEqual(validate_director_result(ctx, {'request_token': job.request_token,
            'kind': 'window_digest', 'text': 'Ветер открыл дверь.', 'references': [],
            'catalog_ids': []}, job_id='job', now=NOW, current_window=3).source, 'fallback')
        self.assertEqual(built(AuthorizedSource('window_digest', 'initial', ACCOUNT, 1, 1,
            (), (), '') , ()).document()['action_window'], 1)

    def test_fails_closed_on_foreign_and_unreferenced_records(self):
        for bad in (record(audience='account:00000000-0000-0000-0000-000000000002'), record(parent='invented'),
                    SafeRecord('event', 'event-1', 'result', 'Дверь открыта', ACCOUNT, 2)):
            with self.assertRaises(ValueError):
                built(records=(bad,))

    def test_npc_only_exact_result_and_issued_cards(self):
        source = AuthorizedSource('npc_reply', 'talk-result', ACCOUNT, 2, None,
                                  ('grant-event',), ('claim-a',), 'NPC сказал ровно это', 'Садовник')
        right = SafeRecord('observation', 'claim-a', 'claim', 'Я видел свет', ACCOUNT, 2, 'grant-event','Садовник')
        ctx = built(source, (right,))
        self.assertIn('NPC сказал ровно это', ' '.join(ctx.narrative_job(job_id='j', expires_at=NOW+timedelta(minutes=5)).view.facts))
        with self.assertRaises(ValueError):
            built(source, (SafeRecord('observation', 'claim-a', 'claim', 'Я видел свет', ACCOUNT, 2, 'older-talk','Садовник'),))

    def test_conflicting_claims_and_npc_line_keep_authored_speakers(self):
        source=AuthorizedSource('window_digest','digest-2',ACCOUNT,2,1,('event-1',),('claim-a','claim-b'),'')
        records=(SafeRecord('event','event-1','result','Беседы завершились',ACCOUNT,1),
                 SafeRecord('observation','claim-a','claim','Я видел свет',ACCOUNT,1,'event-1','Садовник'),
                 SafeRecord('observation','claim-b','claim','Я не видел свет',ACCOUNT,1,'event-1','Сторож'))
        facts=built(source,records).narrative_job(job_id='j').view.facts
        self.assertTrue(any('Садовник' in fact and 'Я видел свет' in fact for fact in facts))
        self.assertTrue(any('Сторож' in fact and 'Я не видел свет' in fact for fact in facts))
        npc=AuthorizedSource('npc_reply','talk',ACCOUNT,2,None,(),(),'Я видел свет','Садовник')
        self.assertTrue(any('Садовник' in fact for fact in built(npc,()).narrative_job(job_id='n').view.facts))

    def test_rehashed_forged_facts_and_missing_blocks_are_rejected(self):
        ctx=built()
        for change in ('empty_blocks','invented_fact'):
            doc=ctx.document()
            if change=='empty_blocks': doc['exact_blocks']=[]
            else: doc['narrative']['facts']=['[r01; proof] SECRET_FABRICATED']
            forged,own_hash=rehash(doc)
            with self.assertRaises(ValueError): FrozenContext.from_document(forged,input_hash=own_hash,source=digest())

    def test_rehashed_bool_cost_and_nested_typed_params_cannot_match_quote(self):
        action=LegalAction('s1','move','library',1,'room',{'flag':True},'rev1')
        source=AuthorizedSource('story_offer','digest-2',ACCOUNT,2,1,(),(), '')
        ctx=built(source,(),(SafeOffer(MenuChoice('choice','s1','Осмотреть библиотеку',action)),))
        doc=ctx.document();doc['offers'][0]['cost']=True
        forged,own_hash=rehash(doc)
        with self.assertRaises(ValueError): FrozenContext.from_document(forged,input_hash=own_hash,source=source)
        # Even a direct malformed constructor cannot turn True into AP=1.
        self.assertIsNone(FrozenContext(forged).resolve_offer('c01',current_window=2,legal_actions=(action,)))
        self.assertIsNone(ctx.resolve_offer('c01',current_window=2,legal_actions=(
            LegalAction('s1','move','library',1,'room',{'flag':1},'rev1'),)))

    def test_frozen_hash_and_document_are_immutable_and_closed(self):
        ctx = built()
        cold=FrozenContext.from_document(ctx.document(),input_hash=ctx.input_hash,source=digest())
        self.assertEqual(cold.narrative_job(job_id='cold',cause_id='digest-2',kind='window_digest',
            expires_at=NOW+timedelta(minutes=5),fallback='Авторская сводка.').view.window_idx,2)
        document = ctx.document()
        document['exact_blocks'][0]['body'] = 'altered'
        self.assertNotEqual(ctx.document()['exact_blocks'][0]['body'], 'altered')
        for mutation in (lambda d: d['exact_blocks'][0].__setitem__('body', 'altered'),
                         lambda d: d.__setitem__('unknown', 1),
                         lambda d: d['reference_map'][0].__setitem__('source_id', 'foreign')):
            bad = ctx.document(); mutation(bad)
            with self.assertRaises(ValueError): FrozenContext.from_document(bad,input_hash=ctx.input_hash,source=digest())

    def test_offers_are_alias_only_and_require_current_quote(self):
        action = LegalAction('selection-1', 'move', 'library', 1, 'room', {'location':'library'}, 'rev1')
        offer = SafeOffer(MenuChoice('choice', action.selection_id, 'Осмотреть библиотеку', action))
        ctx = built(AuthorizedSource('story_offer', 'digest-2', ACCOUNT, 2, 1,
                                     (), (), ''), (), (offer,))
        payload = ctx.narrative_job(job_id='j', expires_at=NOW+timedelta(minutes=5)).provider_payload
        self.assertNotIn('selection-1', str(payload))
        self.assertNotIn('library', str(payload))
        self.assertEqual(ctx.resolve_offer('c01', current_window=2, legal_actions=(action,)), action)
        self.assertIsNone(ctx.resolve_offer('c01', current_window=3, legal_actions=(action,)))
        self.assertIsNone(ctx.resolve_offer('c01', current_window=2, legal_actions=(
            LegalAction('selection-1', 'move', 'library', 2, 'room', {'location':'library'}, 'rev1'),)))

    def test_critical_overflow_and_output_validation(self):
        source = AuthorizedSource('npc_reply', 'talk-result', ACCOUNT, 2, None, (), (), 'x' * 17000, 'Садовник')
        with self.assertRaises(ContextUnavailable): built(source, ())
        ctx = built(); job = ctx.narrative_job(job_id='j', expires_at=NOW+timedelta(minutes=5))
        valid = {'request_token':job.request_token,'kind':'window_digest','text':'Литературная выдумка.',
                 'references':[], 'catalog_ids':[]}
        self.assertEqual(validate_director_result(ctx, valid, job_id='j', now=NOW, current_window=2).source, 'candidate')
        for text in ('bad\x00text', 'bad\u202eltr', 'e\u0301', '<b>HTML</b>', 'https://example.test'):
            self.assertEqual(validate_director_result(ctx, {**valid,'text':text}, job_id='j', now=NOW,
                                                      current_window=2).source, 'fallback')
        self.assertEqual(validate_director_result(ctx, {**valid,'references':['r99']}, job_id='j',
                                                  now=NOW,current_window=2).source, 'fallback')
        self.assertEqual(validate_director_result(ctx, {**valid,'request_token':'wrong'}, job_id='j',
                                                  now=NOW,current_window=2).source, 'fallback')
        with self.assertRaises(ValueError): ctx.narrative_job(job_id='j',expires_at=NOW+timedelta(minutes=6))

    def test_byok_scope_is_single_owner_and_never_multi(self):
        self.assertTrue(audience_permitted('byok',ACCOUNT_ID,ACCOUNT))
        self.assertTrue(audience_permitted('byok',ACCOUNT_ID,'public'))
        self.assertFalse(audience_permitted('byok',ACCOUNT_ID,'account:00000000-0000-0000-0000-000000000002'))
        self.assertFalse(audience_permitted('admin',ACCOUNT_ID,'account:a,b'))


if __name__ == '__main__': unittest.main()
