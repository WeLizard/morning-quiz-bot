"""Reviewed snapshot recovery and immutable art binding acceptance on own PG55434."""
import asyncio
import copy
import hashlib
import json
import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from datetime import timedelta
from types import SimpleNamespace as NS
from uuid import uuid4

from sqlalchemy import select, update
from application.night_case import NightCaseError, NightCaseRegistry
from application.night_case_recovery import NightCaseRecoveryService, decode_recovery_audit, coverage_status
from application.night_case_runtime import availability_snapshot, NightCaseDeadlineWorker
from config.night_case import NightCaseSettings
from storage.models import Game, GameCommand, GameDeadline, NightCase, NightGameSealed, NightRuntimeHealth, NightRuntimeOutage, Room, RoomMembership
from storage.night_cases import json_hash
from tests import test_night_case_application as base


class RecoveryCodecTests(unittest.TestCase):
    def test_cli_has_no_implicit_game_hash_review_operator_request_or_database(self):
        from contextlib import redirect_stderr
        from io import StringIO
        from scripts.recover_night_case import parser
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit) as caught:
            parser().parse_args([])
        self.assertEqual(caught.exception.code,2)

    def test_unknown_audit_fields_and_partial_coverage_fail_closed(self):
        with self.assertRaises(NightCaseError): decode_recovery_audit({'schema':'night-quarantine-recovery/1','unknown':True})
        from datetime import datetime, timezone
        now=datetime(2026,11,16,tzinfo=timezone.utc)
        self.assertEqual(coverage_status(now,now+timedelta(hours=1),[(now,now+timedelta(hours=2))]),'covered')
        with self.assertRaises(NightCaseError) as caught:
            coverage_status(now,now+timedelta(hours=3),[(now,now+timedelta(hours=2))])
        self.assertEqual(caught.exception.code,'recovery_coverage_overlap')


class RecoveryPostgresTests(unittest.IsolatedAsyncioTestCase):
    service=base.NightApplicationPostgresTests.service
    lobby_command=base.NightApplicationPostgresTests.lobby_command
    lobby=base.NightApplicationPostgresTests.lobby
    ready_lobby=base.NightApplicationPostgresTests.ready_lobby
    running=base.NightApplicationPostgresTests.running
    player_command=base.NightApplicationPostgresTests.player_command

    async def asyncSetUp(self):
        await base.NightApplicationPostgresTests.asyncSetUp(self)
        async with self.db.transaction() as session:
            outages=list((await session.scalars(select(NightRuntimeOutage))).all())
            if outages: self.now=max(self.now,max(o.ended_at or o.started_at for o in outages)+timedelta(days=2))
        self.settings=NightCaseSettings(enabled=True,starts_enabled=True,cursor_secret=self.registry.cursor_secret,runtime_key='recovery-'+uuid4().hex)

    async def asyncTearDown(self):
        async with self.db.transaction() as session:
            own_games=select(NightGameSealed.game_id).where(NightGameSealed.case_id==self.ref.case_id)
            await session.execute(update(GameDeadline).where(GameDeadline.game_id.in_(own_games)).values(status='cancelled',claimed_by=None,claimed_at=None))
        await self.db.dispose()

    def recovery(self,session):
        return NightCaseRecoveryService(session,lambda:self.now,self.registry)

    async def quarantined(self):
        game,*_=await self.running()
        async with self.db.transaction() as session:
            row=await session.get(GameDeadline,'night:'+game+':phase')
            due=row.due_at
            row.status='quarantined'; row.attempts=3; row.quarantined_at=due+timedelta(seconds=155); row.last_error_code='transition_failed'
            before=copy.deepcopy((await session.get(NightGameSealed,game)).kernel)
            snapshot=(await session.get(NightGameSealed,game)).snapshot_hash
        self.now=due+timedelta(hours=30)
        return game,snapshot,before,due

    async def recover(self,game,snapshot,request_id=None):
        async with self.db.transaction() as session:
            return await self.recovery(session).recover_quarantine(operator=self.operator,game_id=game,
                request_id=request_id or uuid4().hex,expected_snapshot_hash=snapshot,review_ref='review:test-codec-and-trace')

    async def healthy(self):
        from sqlalchemy.dialects.postgresql import insert
        async with self.db.transaction() as session:
            statement=insert(NightRuntimeHealth).values(runtime_key=self.settings.runtime_key,api_seen_at=self.now,worker_seen_at=self.now)
            await session.execute(statement.on_conflict_do_update(index_elements=['runtime_key'],set_={'api_seen_at':self.now,'worker_seen_at':self.now}))

    async def availability(self,game):
        async with self.db.transaction() as session:
            service=self.service(session)
            locked=await service.repo.lock_game(game)
            return await availability_snapshot(session,self.settings,NS(now=self.now,locked=locked))

    async def test_recovery_trace_is_atomic_and_exact_retry_survives_later_clock(self):
        game,snapshot,before,due=await self.quarantined(); request=uuid4().hex
        audit=await self.recover(game,snapshot,request)
        self.assertEqual(decode_recovery_audit(audit),audit)
        self.assertEqual(audit['failed_generation']['due_at'],due.isoformat().replace('+00:00','Z'))
        async with self.db.transaction() as session:
            sealed=await session.get(NightGameSealed,game); row=await session.get(GameDeadline,'night:'+game+':phase')
            self.assertEqual(sealed.kernel['players'],before['players'])
            self.assertEqual(sealed.kernel['clock']['window_idx'],before['clock']['window_idx'])
            self.assertEqual((row.status,row.attempts,row.quarantined_at),('pending',0,None))
            self.assertGreater(row.due_at,self.now)
            self.assertEqual(sealed.snapshot_hash,audit['final_snapshot_hash'])
        self.now+=timedelta(days=10)
        self.assertEqual(await self.recover(game,snapshot,request),audit)

    async def test_same_recovery_two_sessions_worker_and_retry_have_one_trace(self):
        game,snapshot,_,_=await self.quarantined(); request=uuid4().hex
        worker=NightCaseDeadlineWorker(self.db,self.settings,service_factory=self.service,clock=lambda:self.now)
        results=await asyncio.gather(self.recover(game,snapshot,request),self.recover(game,snapshot,request),worker.claim_due(self.now))
        self.assertEqual(results[0],results[1]); self.assertFalse(any(c.game_id==game for c in results[2]))
        async with self.db.transaction() as session:
            rows=list((await session.scalars(select(GameCommand).where(GameCommand.game_id==game,GameCommand.kind=='night.quarantine_recovery'))).all())
            self.assertEqual(len(rows),1)

    async def test_unknown_snapshot_remains_quarantined(self):
        game,snapshot,_,_=await self.quarantined()
        async with self.db.transaction() as session:
            row=await session.get(NightGameSealed,game); value=copy.deepcopy(row.kernel); value['unknown']=True; row.kernel=value
        with self.assertRaises(NightCaseError): await self.recover(game,snapshot)
        async with self.db.transaction() as session:
            self.assertEqual((await session.get(GameDeadline,'night:'+game+':phase')).status,'quarantined')
            self.assertFalse(await session.scalar(select(GameCommand.id).where(GameCommand.game_id==game,GameCommand.kind=='night.quarantine_recovery')))

    async def test_overlap_union_keeps_disjoint_order_and_no_double_global_resume(self):
        game,snapshot,before,due=await self.quarantined()
        async with self.db.transaction() as session:
            started=(await session.get(Game,game)).started_at
            first=NightRuntimeOutage(outage_id=uuid4().hex,started_at=started+timedelta(minutes=1),ended_at=started+timedelta(minutes=2),detected_by='worker')
            second=NightRuntimeOutage(outage_id=uuid4().hex,started_at=due-timedelta(minutes=10),ended_at=self.now-timedelta(minutes=10),detected_by='api')
            session.add_all([first,second]); ids={first.outage_id,second.outage_id}
        audit=await self.recover(game,snapshot)
        self.assertEqual(set(audit['covered_global_ids']),ids)
        self.assertEqual(len(audit['intervals']),2)
        self.assertLess(audit['intervals'][0]['resumed_at'],audit['intervals'][1]['unavailable_from'])
        await self.healthy()
        self.assertEqual((await self.availability(game)).completed_outages,())
        async with self.db.transaction() as session:
            after=(await session.get(NightGameSealed,game)).kernel
            self.assertEqual(after['players'],before['players'])
            self.assertEqual(len(after['clock']['resume_receipts']),2)

    async def test_late_covered_global_skip_but_partial_overlap_is_game_local_error(self):
        game,snapshot,_,due=await self.quarantined()
        await self.recover(game,snapshot)
        recovery_now=self.now
        async with self.db.transaction() as session:
            session.add(NightRuntimeOutage(outage_id=uuid4().hex,started_at=due+timedelta(hours=1),ended_at=due+timedelta(hours=2),detected_by='worker'))
        await self.healthy()
        self.assertEqual((await self.availability(game)).completed_outages,())
        async with self.db.transaction() as session:
            session.add(NightRuntimeOutage(outage_id=uuid4().hex,started_at=recovery_now-timedelta(hours=1),ended_at=recovery_now+timedelta(hours=1),detected_by='worker'))
        self.now+=timedelta(hours=2); await self.healthy()
        with self.assertRaises(NightCaseError) as caught: await self.availability(game)
        self.assertEqual(caught.exception.code,'recovery_coverage_overlap')
        # A later independent game has no overlap and remains usable.
        self.room=uuid4().hex
        async with self.db.transaction() as session:
            session.add(Room(id=self.room,kind='standalone',owner_account_id=self.owner))
            await session.flush()
            session.add_all([RoomMembership(room_id=self.room,account_id=aid,role='owner' if aid==self.owner else 'member') for aid in self.accounts])
        other,*_=await self.running()
        self.assertFalse((await self.availability(other)).delayed)

    async def test_art_binding_is_immutable_and_room_theme_does_not_rebind_history(self):
        from application.night_case import FrozenCaseRef
        from domain.night_case_format import canonical_content_hash
        document=copy.deepcopy(self.doc); document['meta']['id']='art_'+uuid4().hex[:24]
        document['meta']['world']='manor_lake'; document['meta']['style_pack']='noir_print_a'; document['meta']['crime_type']='missing'
        ref=FrozenCaseRef(document['meta']['id'],document['meta']['version'],canonical_content_hash(document))
        self.registry=NightCaseRegistry(frozenset({ref}),self.registry.allowed_timezones,self.registry.cursor_secret)
        # Core DB binding acceptance must not depend on ignored local art exports.
        # Real image/manifest validation belongs to the separate source-art gate.
        temporary=TemporaryDirectory(prefix='mqb-art-binding-')
        self.addCleanup(temporary.cleanup)
        fixture_bytes=b'public synthetic asset fixture'
        payload={'schema':'nc-assets/2','world':'manor_lake',
            'assets':{'fixture_public':{'url':'assets/fixture.txt','alt':'Public fixture'}},
            'files':{'assets/fixture.txt':hashlib.sha256(fixture_bytes).hexdigest()}}
        original_bytes=json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')
        digest=hashlib.sha256(original_bytes).hexdigest()
        manifest=Path(temporary.name)/'packs'/digest/'assets.json'
        manifest.parent.mkdir(parents=True)
        (manifest.parent/'assets').mkdir()
        (manifest.parent/'assets/fixture.txt').write_bytes(fixture_bytes)
        manifest.write_bytes(original_bytes)
        self.assertEqual(hashlib.sha256(original_bytes).hexdigest(),digest)
        report={'scope':'synthetic_fixture','art':{'schema':'night-art-binding/1','world':'manor_lake','style_pack':'noir_print_a','manifest_sha256':digest,
            'sealed':{'fixture_finale':'c'*64}}}
        async with self.db.transaction() as session:
            await self.service(session).register_case(operator=self.operator,content=document,validation_report=report,admission='rehearsal')
        self.ref=ref
        game,*_=await self.running()
        async with self.db.transaction() as session:
            first=await self.service(session).get_view(account_id=self.owner,game_id=game)
            room=await session.get(Room,self.room); room.world='other-world'
        self.assertEqual(first['public']['art'],{'manifest_sha256':digest,'manifest_url':'/app/night/packs/'+digest+'/assets.json'})
        self.assertNotIn('c'*64,json.dumps(first))  # sealed pictures never reach a running game's view
        async with self.db.transaction() as session:
            second=await self.service(session).get_view(account_id=self.owner,game_id=game)
            self.assertEqual(first['public']['art'],second['public']['art'])
            self.assertTrue(all(n.get('title') for n in second['public']['npcs']))
        # A new server default/version cannot rewrite the old case binding.
        newer=copy.deepcopy(document); newer['meta']['version']+=1
        newer_ref=FrozenCaseRef(newer['meta']['id'],newer['meta']['version'],canonical_content_hash(newer))
        self.registry=NightCaseRegistry(frozenset({newer_ref}),self.registry.allowed_timezones,self.registry.cursor_secret)
        newer_report=copy.deepcopy(report); newer_report['art']['manifest_sha256']='b'*64
        async with self.db.transaction() as session:
            await self.service(session).register_case(operator=self.operator,content=newer,validation_report=newer_report,admission='rehearsal')
            self.assertEqual((await self.service(session).get_view(account_id=self.owner,game_id=game))['public']['art'],first['public']['art'])
        departed=await self.player_command(game,self.owner,'forfeit')
        async with self.db.transaction() as session:
            await self.service(session).execute(account_id=self.owner,game_id=game,command=departed)
            self.assertEqual((await self.service(session).get_view(account_id=self.owner,game_id=game))['public']['art'],first['public']['art'])
        self.assertEqual(manifest.read_bytes(),original_bytes)
        self.assertEqual((manifest.parent/'assets/fixture.txt').read_bytes(),fixture_bytes)
        report['art']['manifest_sha256']='b'*64
        with self.assertRaises(NightCaseError) as caught:
            async with self.db.transaction() as session:
                await self.service(session).register_case(operator=self.operator,content=document,validation_report=report,admission='registered')
        self.assertEqual(caught.exception.code,'command_conflict')

    async def test_unknown_build_and_audit_overflow_do_not_clear_quarantine(self):
        from unittest.mock import patch
        game,snapshot,_,_=await self.quarantined()
        unavailable=NightCaseRegistry(self.registry.allowed_cases,self.registry.allowed_timezones,
            self.registry.cursor_secret,frozenset({'night-case-core/99'}))
        with self.assertRaises(NightCaseError):
            async with self.db.transaction() as session:
                await NightCaseRecoveryService(session,lambda:self.now,unavailable).recover_quarantine(
                    operator=self.operator,game_id=game,request_id=uuid4().hex,expected_snapshot_hash=snapshot,review_ref='review:unsupported-build')
        with patch('application.night_case_recovery.MAX_RECORD_BYTES',100):
            with self.assertRaises(NightCaseError) as caught:
                await self.recover(game,snapshot)
        self.assertEqual(caught.exception.code,'recovery_audit_too_large')
        async with self.db.transaction() as session:
            self.assertEqual((await session.get(NightGameSealed,game)).snapshot_hash,snapshot)
            self.assertEqual((await session.get(GameDeadline,'night:'+game+':phase')).status,'quarantined')
            self.assertFalse(await session.scalar(select(GameCommand.id).where(GameCommand.game_id==game,GameCommand.kind=='night.quarantine_recovery')))

    async def test_frozen_valid_snapshot_is_not_operator_recovered(self):
        from domain.night_case_engine import _due
        from application.night_case_runtime import tick_command
        game,*_=await self.running()
        for _ in range(6):
            async with self.db.transaction() as session:
                doc=(await session.get(NightGameSealed,game)).kernel
                due=_due(doc); self.now=base.datetime.fromisoformat(due['at'].replace('Z','+00:00'))
                await self.service(session).advance_due(game_id=game,command=tick_command(game,doc['clock'],self.now))
        async with self.db.transaction() as session:
            sealed=await session.get(NightGameSealed,game); snapshot=sealed.snapshot_hash
            self.assertEqual(sealed.kernel['clock']['phase'],'frozen')
            row=await session.get(GameDeadline,'night:'+game+':phase')
            row.status='quarantined'; row.quarantined_at=self.now; row.attempts=3
            self.now=row.due_at+timedelta(hours=1)
        with self.assertRaises(NightCaseError) as caught: await self.recover(game,snapshot)
        self.assertEqual(caught.exception.code,'recovery_generation_unavailable')
        async with self.db.transaction() as session:
            self.assertEqual((await session.get(GameDeadline,'night:'+game+':phase')).status,'quarantined')
