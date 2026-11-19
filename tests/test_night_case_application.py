"""Application acceptance on explicitly owned Night Case PostgreSQL only."""
import unittest


class NightApplicationContractTests(unittest.TestCase):
    def test_lobby_envelope_is_strict_and_bool_is_not_revision(self):
        from application.night_case import LobbyCommand
        for bad in ({'command_id':'command01','expected_lobby_revision':True,'params':{}},
                    {'command_id':'command01','expected_lobby_revision':0,'params':{},'actor_id':'x'}):
            with self.assertRaises(ValueError):
                LobbyCommand.parse(bad)

    def test_cursor_requires_server_secret(self):
        from application.night_case import NightCaseRegistry
        with self.assertRaises(ValueError):
            NightCaseRegistry(frozenset(),frozenset({'UTC'}),b'short')


import asyncio
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4
from sqlalchemy import select, update
from storage.database import Database, DatabaseSettings
from storage.models import Account, Room, RoomMembership, Game, NightGameSealed, GamePlayer, NightMessage, NightEvent, NightRenderJob


def application_test_url():
    from tests.night_case_test_database import night_case_test_url
    return night_case_test_url()


class NightApplicationPostgresTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from application.night_case import FrozenCaseRef, NightCaseRegistry, OperatorPrincipal, NightCaseApplicationService
        from domain.night_case_format import canonical_content_hash
        self.db=Database(DatabaseSettings(url=application_test_url()))
        self.now=datetime(2026,11,15,10,tzinfo=timezone.utc)
        self.accounts=[uuid4() for _ in range(5)]
        self.owner=self.accounts[0]; self.room=uuid4().hex
        self.doc=json.loads((Path(__file__).parent/'fixtures/night_city/runtime_case_v2.json').read_text(encoding='utf-8'))
        self.doc['meta']['id']='app_'+uuid4().hex[:24]
        self.ref=FrozenCaseRef(self.doc['meta']['id'],self.doc['meta']['version'],canonical_content_hash(self.doc))
        self.registry=NightCaseRegistry(frozenset({self.ref}),frozenset({'Europe/Berlin'}),b'night-test-cursor-secret-32-bytes!!')
        self.operator=OperatorPrincipal('test-operator',self.owner)
        async with self.db.transaction() as session:
            session.add_all([Account(id=aid,display_name=f'Player {i}') for i,aid in enumerate(self.accounts)])
            await session.flush()
            session.add(Room(id=self.room,kind='standalone',owner_account_id=self.owner)); await session.flush()
            session.add_all([RoomMembership(room_id=self.room,account_id=aid,role='owner' if aid==self.owner else 'member') for aid in self.accounts])
            await session.flush()
            await self.service(session).register_case(operator=self.operator,content=self.doc,
                validation_report={'scope':'synthetic_fixture','publication':'not_checked'},admission='rehearsal')

    def service(self,session):
        from application.night_case import NightCaseApplicationService
        return NightCaseApplicationService(session,lambda:self.now,self.registry)

    async def asyncTearDown(self):
        await self.db.dispose()

    def lobby_command(self,revision=0,params=None,command_id=None):
        return {'command_id':command_id or uuid4().hex,'expected_lobby_revision':revision,'params':params or {}}

    async def lobby(self):
        command=self.lobby_command(params={'case_id':self.ref.case_id,'case_version':self.ref.case_version,'timezone':'Europe/Berlin'})
        async with self.db.transaction() as session:
            created=await self.service(session).create_lobby(account_id=self.owner,room_id=self.room,command=command)
        return created,command

    async def ready_lobby(self):
        created,create=self.created if hasattr(self,'created') else await self.lobby()
        game=created['view']['game_id']; view=created['view']
        for i,account in enumerate(self.accounts[:4]):
            async with self.db.transaction() as session:
                if account!=self.owner:
                    joined=await self.service(session).join_lobby(account_id=account,game_id=game,
                        command=self.lobby_command(view['lobby_revision']))
                    view=joined['view']
                readied=await self.service(session).set_ready(account_id=account,game_id=game,
                    command=self.lobby_command(view['lobby_revision'],{'name':f'Player {i}','address_form':'n','ready':True}))
                view=readied['view']
        start_command=self.lobby_command(view['lobby_revision'])
        return game,create,start_command

    async def running(self):
        game,create,start_command=await self.ready_lobby()
        async with self.db.transaction() as session:
            started=await self.service(session).start_game(account_id=self.owner,game_id=game,command=start_command)
        return game,create,start_command,started

    async def player_command(self,game,actor,kind,params=None,command_id=None):
        async with self.db.transaction() as session:
            view=await self.service(session).get_view(account_id=actor,game_id=game)
        return {'command_id':command_id or uuid4().hex,'kind':kind,'window_idx':view['public']['clock']['window_idx'],
            'window_seq':view['public']['clock']['window_seq'],'actor_seq':view['self']['actor_seq'],'params':params or {}}

    async def test_four_accounts_start_private_action_and_lost_response_replay(self):
        game,create,start_command,started=await self.running()
        async with self.db.transaction() as session:
            retry=await self.service(session).create_lobby(account_id=self.owner,room_id=self.room,command=create)
            self.assertEqual(retry['view']['status'],'lobby')
            self.assertEqual(retry['view']['game_id'],game)
            self.assertEqual(await self.service(session).start_game(account_id=self.owner,game_id=game,command=start_command),started)
        command=await self.player_command(game,self.owner,'seen')
        async with self.db.transaction() as session:
            before=await session.get(Game,game)
            old=(before.revision,before.updated_at)
            result=await self.service(session).execute(account_id=self.owner,game_id=game,command=command)
            self.assertTrue(result['receipt']['accepted'])
        self.now+=timedelta(days=2)
        async with self.db.transaction() as session:
            self.assertEqual(await self.service(session).execute(account_id=self.owner,game_id=game,command=command),result)
            row=await session.get(Game,game)
            self.assertEqual((row.revision,row.updated_at),old)
            self.assertNotIn('canary',json.dumps(row.state))

    async def test_two_sessions_same_and_different_actor_commands(self):
        game,*_=await self.running()
        a=await self.player_command(game,self.owner,'seen')
        b=await self.player_command(game,self.accounts[1],'seen')
        async def execute(actor,raw):
            async with self.db.transaction() as session:
                return await self.service(session).execute(account_id=actor,game_id=game,command=raw)
        results=await asyncio.gather(execute(self.owner,a),execute(self.owner,a),execute(self.accounts[1],b))
        self.assertEqual(results[0],results[1]); self.assertTrue(results[2]['receipt']['accepted'])

    async def test_block_revokes_receipt_view_and_message_access(self):
        from application.night_case import NightCaseError
        game,*_=await self.running()
        command=await self.player_command(game,self.owner,'seen')
        async with self.db.transaction() as session:
            await self.service(session).execute(account_id=self.owner,game_id=game,command=command)
        from storage.admin_actions import operation_fence
        async with self.db.transaction() as session:
            await operation_fence(session,exclusive=True)
            await session.execute(update(Account).where(Account.id==self.owner).values(bot_blocked=True))
        for method in ('get_view','execute'):
            with self.assertRaises(NightCaseError) as caught:
                async with self.db.transaction() as session:
                    args={'account_id':self.owner,'game_id':game}
                    if method=='execute': args['command']=command
                    await getattr(self.service(session),method)(**args)
            self.assertEqual(caught.exception.code,'account_unavailable')

    async def test_history_private_canaries_message_acl_and_forged_cursor(self):
        from application.night_case import NightCaseError
        game,*_=await self.running()
        command=await self.player_command(game,self.owner,'say',{'channel':'square','recipients':[],'text':'public exact text'})
        async with self.db.transaction() as session:
            result=await self.service(session).execute(account_id=self.owner,game_id=game,command=command)
            mid=result['caused_message_ids'][0]
            own=await self.service(session).get_message(account_id=self.owner,game_id=game,message_id=mid)
            self.assertEqual(own['text'],'public exact text')
            self.assertEqual((await self.service(session).get_message(account_id=self.accounts[1],game_id=game,message_id=mid))['text'],'public exact text')
            public=await self.service(session).history(account_id=self.owner,game_id=game,stream='public',limit=1)
            self.assertEqual(len(public['items']),1)
            cursor=public['next_cursor']
        with self.assertRaises(NightCaseError):
            async with self.db.transaction() as session:
                await self.service(session).history(account_id=self.accounts[1],game_id=game,stream='public',cursor=cursor,limit=1)
        with self.assertRaises(NightCaseError):
            async with self.db.transaction() as session:
                await self.service(session).get_message(account_id=self.accounts[4],game_id=game,message_id=mid)
        async with self.db.transaction() as session:
            a=await self.service(session).history(account_id=self.owner,game_id=game,stream='self')
            b=await self.service(session).history(account_id=self.accounts[1],game_id=game,stream='self')
            self.assertTrue(a['items']); self.assertTrue(b['items'])
            self.assertTrue(set(x['event_id'] for x in a['items']).isdisjoint(x['event_id'] for x in b['items']))

    async def test_deadline_boundary_refusal_and_replay_before_clock(self):
        game,*_=await self.running()
        raw=await self.player_command(game,self.owner,'seen')
        async with self.db.transaction() as session:
            doc=(await session.get(NightGameSealed,game)).kernel
            self.now=datetime.fromisoformat(doc['clock']['closes_at'].replace('Z','+00:00'))
            denied=await self.service(session).execute(account_id=self.owner,game_id=game,command=raw)
            self.assertFalse(denied['receipt']['accepted'])
            self.assertEqual(denied['receipt']['code'],'deadline_pending')
        self.now+=timedelta(days=20)
        async with self.db.transaction() as session:
            self.assertEqual(await self.service(session).execute(account_id=self.owner,game_id=game,command=raw),denied)

    async def test_proposal_confirm_lost_response_after_expiry(self):
        game,*_=await self.running()
        async with self.db.transaction() as session:
            view=await self.service(session).get_view(account_id=self.owner,game_id=game)
            chosen=next(e['quote']['selection_id'] for e in view['menu'] if e.get('quote',{}).get('kind')=='seen')
            proposal=await self.service(session).propose_intent(account_id=self.owner,game_id=game,
                request_id=uuid4().hex,selection_id=chosen)
            self.assertEqual(proposal['kind'],'proposal')
        async with self.db.transaction() as session:
            confirmed=await self.service(session).confirm_intent(account_id=self.owner,game_id=game,proposal_id=proposal['proposal']['proposal_id'])
        self.now+=timedelta(hours=5)
        async with self.db.transaction() as session:
            self.assertEqual(await self.service(session).confirm_intent(account_id=self.owner,game_id=game,proposal_id=proposal['proposal']['proposal_id']),confirmed)

    async def test_lobby_same_create_race_one_game(self):
        command=self.lobby_command(params={'case_id':self.ref.case_id,'case_version':self.ref.case_version,'timezone':'Europe/Berlin'})
        async def create():
            async with self.db.transaction() as session:
                return await self.service(session).create_lobby(account_id=self.owner,room_id=self.room,command=command)
        results=await asyncio.gather(create(),create())
        self.assertEqual(results[0],results[1])

    async def test_interrupted_blocks_start_leave_and_merge_until_explicit_close(self):
        from application.night_case import NightCaseError
        from application.account_merge import AccountMergeService
        from storage.admin_actions import operation_fence
        from storage.games import GameRepository
        from storage.mini_app import MiniAppError
        game,*_=await self.running()
        async with self.db.transaction() as session:
            await operation_fence(session,exclusive=True)
            row=await session.get(Game,game)
            await GameRepository(session).interrupt(row,event_kind='operator-test')
            sealed=await session.get(NightGameSealed,game)
            self.assertEqual((row.status,row.is_current,sealed.lifecycle),('interrupted',True,'interrupted'))
        with self.assertRaises(NightCaseError):
            async with self.db.transaction() as session:
                await self.service(session).create_lobby(account_id=self.owner,room_id=self.room,
                    command=self.lobby_command(params={'case_id':self.ref.case_id,'case_version':self.ref.case_version,'timezone':'Europe/Berlin'}))
        with self.assertRaises(MiniAppError) as caught:
            async with self.db.transaction() as session:
                await operation_fence(session,exclusive=True)
                await AccountMergeService().merge_in(session,main=await session.get(Account,self.accounts[4]),
                    secondary=await session.get(Account,self.owner),via='test')
        self.assertEqual(caught.exception.code,'night_case_merge_active')
        async with self.db.transaction() as session:
            stopped=await self.service(session).close_interrupted(operator=self.operator,game_id=game,
                action_id=uuid4().hex,reason='test cleanup')
            self.assertEqual(stopped['status'],'stopped')
            self.assertFalse((await session.get(Game,game)).is_current)

    async def test_room_leave_requires_forfeit_and_retains_seat(self):
        from application.rooms import RoomApplicationService
        game,*_=await self.running()
        actor=self.accounts[1]
        async with self.db.transaction() as session:
            member=await session.get(RoomMembership,(self.room,actor))
            version=member.updated_at.isoformat()
        with self.assertRaises(RuntimeError):
            async with self.db.transaction() as session:
                await RoomApplicationService(session).leave(account_id=actor,room_id=self.room,membership_version=version)
        command=await self.player_command(game,actor,'forfeit')
        async with self.db.transaction() as session:
            result=await self.service(session).execute(account_id=actor,game_id=game,command=command)
            self.assertTrue(result['receipt']['accepted'])
        async with self.db.transaction() as session:
            left=await RoomApplicationService(session).leave(account_id=actor,room_id=self.room,membership_version=version)
            self.assertTrue(left['left'])
            seat=await session.get(GamePlayer,(game,actor))
            self.assertEqual(seat.status,'departed')

    async def test_same_timestamp_departure_cutoff_hides_later_messages_and_public_state(self):
        from application.night_case import NightCaseError
        game,*_=await self.running()
        departing=self.accounts[1]; sender=self.owner
        before=await self.player_command(game,sender,'say',{'channel':'square','recipients':[],'text':'before cutoff'})
        async with self.db.transaction() as session:
            first=await self.service(session).execute(account_id=sender,game_id=game,command=before)
        leave=await self.player_command(game,departing,'forfeit')
        async with self.db.transaction() as session:
            await self.service(session).execute(account_id=departing,game_id=game,command=leave)
            frozen=await self.service(session).get_view(account_id=departing,game_id=game)
        later=await self.player_command(game,sender,'say',{'channel':'square','recipients':[],'text':'after cutoff canary'})
        async with self.db.transaction() as session:
            after=await self.service(session).execute(account_id=sender,game_id=game,command=later)
            # The same physical clock is deliberate; timestamps cannot decide access.
            messages=list((await session.scalars(select(NightMessage).where(NightMessage.game_id==game))).all())
            self.assertEqual(messages[0].created_at,messages[1].created_at)
        async with self.db.transaction() as session:
            history=await self.service(session).history(account_id=departing,game_id=game,stream='messages')
            self.assertEqual([m['text'] for m in history['items']],['before cutoff'])
            self.assertEqual((await self.service(session).get_message(account_id=departing,game_id=game,
                message_id=first['caused_message_ids'][0]))['text'],'before cutoff')
            latest=await self.service(session).get_view(account_id=departing,game_id=game)
            self.assertEqual((latest['public'],latest['self']),(frozen['public'],frozen['self']))
            self.assertNotIn('after cutoff canary',json.dumps(latest))
        with self.assertRaises(NightCaseError):
            async with self.db.transaction() as session:
                await self.service(session).get_message(account_id=departing,game_id=game,message_id=after['caused_message_ids'][0])

    async def test_private_finish_window_updates_timer_without_public_revision(self):
        game,*_=await self.running()
        # All four finishing changes early scheduling; neither technical timer nor
        # another actor's readiness is a public Game.state/ETag counter.
        async with self.db.transaction() as session:
            row=await session.get(Game,game); old=(row.revision,row.state,row.updated_at)
        for actor in self.accounts[:4]:
            command=await self.player_command(game,actor,'finish_window')
            async with self.db.transaction() as session:
                await self.service(session).execute(account_id=actor,game_id=game,command=command)
        async with self.db.transaction() as session:
            row=await session.get(Game,game)
            self.assertEqual((row.revision,row.state,row.updated_at),old)
            self.assertGreater((await session.get(NightGameSealed,game)).kernel['clock']['timer_seq'],1)
            view=await self.service(session).get_view(account_id=self.owner,game_id=game)
            self.assertNotIn('timer_seq',view['public']['clock'])

    async def test_system_terminal_cycle_rewards_once_and_new_lobby_preserves_history(self):
        from domain.night_case_engine import _due
        from storage.models import NightRewardClaim
        from sqlalchemy import func
        game,create,*_=await self.running()
        last=None
        for i in range(20):
            async with self.db.transaction() as session:
                sealed=await session.get(NightGameSealed,game)
                if sealed.lifecycle=='finished': break
                doc=sealed.kernel; due=_due(doc); self.now=datetime.fromisoformat(due['at'].replace('Z','+00:00'))
                last={'command_id':f'worker-command-{i:04d}','kind':'system.tick',
                    'window_seq':doc['clock']['window_seq'],'timer_seq':doc['clock']['timer_seq'],
                    'params':{'expected_due_at':due['at']}}
                result=await self.service(session).advance_due(game_id=game,command=last)
                self.assertTrue(result['receipt']['accepted'])
        else: self.fail('terminal clock bound exceeded')
        async with self.db.transaction() as session:
            self.assertEqual((await session.get(NightGameSealed,game)).lifecycle,'finished')
            self.assertEqual(await session.scalar(select(func.count()).select_from(NightRewardClaim).where(NightRewardClaim.game_id==game)),4)
            self.assertEqual(await self.service(session).advance_due(game_id=game,command=last),result)
            retry=await self.service(session).create_lobby(account_id=self.owner,room_id=self.room,command=create)
            self.assertEqual(retry['view']['game_id'],game)
            new=await self.service(session).create_lobby(account_id=self.owner,room_id=self.room,
                command=self.lobby_command(params={'case_id':self.ref.case_id,'case_version':self.ref.case_version,'timezone':'Europe/Berlin'}))
            self.assertNotEqual(new['view']['game_id'],game)
            self.assertFalse((await session.get(Game,game)).is_current)

    async def test_account_uuid_moderation_audit_and_admin_without_account(self):
        from application.night_case import OperatorPrincipal
        from storage.admin_actions import AdminActions,AdminConflict
        from storage.models import AdminAction,NightCase
        async with self.db.transaction() as session:
            duplicate=await self.service(session).register_case(operator=OperatorPrincipal('global-admin',None),content=self.doc,
                validation_report={'scope':'synthetic_fixture','publication':'not_checked'},admission='rehearsal')
            self.assertEqual(duplicate,self.ref)
            original=await session.get(NightCase,(self.ref.case_id,self.ref.case_version))
            self.assertEqual(original.registered_operator_id,'operator:test-operator')
            operator_doc=json.loads(json.dumps(self.doc))
            operator_doc['meta']['id']='operator_'+uuid4().hex[:22]
            registered=await self.service(session).register_case(operator=OperatorPrincipal('global-admin'),content=operator_doc,
                validation_report={'scope':'synthetic_fixture','publication':'not_checked'},admission='registered')
            operator_row=await session.get(NightCase,(registered.case_id,registered.case_version))
            self.assertIsNone(operator_row.registered_by)
            self.assertEqual(operator_row.registered_operator_id,'operator:global-admin')
        action=uuid4().hex
        moderation=await AdminActions(self.db).moderate_account(self.accounts[1],operator_id='global-admin',action_id=action,
            expected_revision=0,reason='test block',blocked=True)
        self.assertEqual((moderation['scope'],moderation['target_id']),('accounts',str(self.accounts[1])))
        replay=await AdminActions(self.db).moderate_account(self.accounts[1],operator_id='global-admin',action_id=action,
            expected_revision=0,reason='test block',blocked=True)
        self.assertEqual(replay,moderation)
        async with self.db.transaction() as session:
            row=await session.get(AdminAction,action)
            self.assertIsNone(row.target_id); self.assertEqual(row.target_account_id,self.accounts[1])

    async def test_moderation_races_replay_under_shared_exclusive_fence(self):
        from application.night_case import NightCaseError
        from storage.admin_actions import AdminActions
        game,*_=await self.running()
        command=await self.player_command(game,self.owner,'seen')
        async with self.db.transaction() as session:
            first=await self.service(session).execute(account_id=self.owner,game_id=game,command=command)
        barrier=asyncio.Barrier(2)
        async def replay():
            await barrier.wait()
            try:
                async with self.db.transaction() as session:
                    return await self.service(session).execute(account_id=self.owner,game_id=game,command=command)
            except NightCaseError as error:
                self.assertEqual(error.code,'account_unavailable')
                return None
        async def block():
            await barrier.wait()
            return await AdminActions(self.db).moderate_account(self.owner,operator_id='admin',action_id=uuid4().hex,
                expected_revision=0,reason='race block',blocked=True)
        result,moderated=await asyncio.wait_for(asyncio.gather(replay(),block()),20)
        self.assertIn(result,(None,first)); self.assertTrue(moderated['after']['blocked'])
        with self.assertRaises(NightCaseError):
            async with self.db.transaction() as session:
                await self.service(session).get_view(account_id=self.owner,game_id=game)

    async def test_finished_merge_retains_original_seats_receipts_and_private_history(self):
        from application.account_merge import AccountMergeService
        from application.night_case import NightCaseError
        from storage.admin_actions import operation_fence
        from storage.games import GameRepository
        game,create,*_=await self.running()
        original=self.accounts[1]; canonical=self.accounts[4]
        async with self.db.transaction() as session:
            before=await self.service(session).history(account_id=original,game_id=game,stream='self')
        async with self.db.transaction() as session:
            await operation_fence(session,exclusive=True)
            await GameRepository(session).interrupt(await session.get(Game,game),event_kind='test-stopping')
        async with self.db.transaction() as session:
            await self.service(session).close_interrupted(operator=self.operator,game_id=game,action_id=uuid4().hex,reason='test stop')
        async with self.db.transaction() as session:
            await operation_fence(session,exclusive=True)
            merge=AccountMergeService()
            await merge.lock_owned_rows_in(session,[original,canonical])
            await merge.merge_in(session,main=await session.get(Account,canonical),secondary=await session.get(Account,original),via='test')
            self.assertIsNotNone(await session.get(GamePlayer,(game,original)))
            self.assertIsNone(await session.get(GamePlayer,(game,canonical)))
        async with self.db.transaction() as session:
            after=await self.service(session).history(account_id=canonical,game_id=game,stream='self')
            self.assertEqual(before,after)
        with self.assertRaises(NightCaseError):
            async with self.db.transaction() as session:
                await self.service(session).history(account_id=original,game_id=game,stream='self')
        # A forged merged_into edge without AccountMerge audit proves no ancestry.
        async with self.db.transaction() as session:
            other=await session.get(Account,self.accounts[2]); other.archived=True; other.merged_into_id=canonical; other.merged_at=self.now
        async with self.db.transaction() as session:
            history=await self.service(session).history(account_id=canonical,game_id=game,stream='self')
            self.assertEqual(history['items'],before['items'])

    async def test_merged_seats_keep_public_rendering_without_lifting_departed_private_cutoff(self):
        from application.account_merge import AccountMergeService
        from application.night_case import NightCaseError
        from storage.admin_actions import operation_fence
        from storage.games import GameRepository
        from storage.night_cases import NightCaseRepository, json_hash

        game,*_=await self.running()
        departed,continuing=self.accounts[1:3]
        forfeit=await self.player_command(game,departed,'forfeit')
        async with self.db.transaction() as session:
            self.assertTrue((await self.service(session).execute(account_id=departed,game_id=game,command=forfeit))['receipt']['accepted'])
        claim=await self.player_command(game,continuing,'claim',{'text':'public after departure'})
        message_command=await self.player_command(game,continuing,'say',{'channel':'square','recipients':[],'text':'message after departure'})
        async with self.db.transaction() as session:
            message_result=await self.service(session).execute(account_id=continuing,game_id=game,command=message_command)
        # The message changed the continuing actor fence; quote the claim again.
        claim=await self.player_command(game,continuing,'claim',{'text':'public after departure'})
        async with self.db.transaction() as session:
            result=await self.service(session).execute(account_id=continuing,game_id=game,command=claim)
            self.assertTrue(result['receipt']['accepted'])
            public_id=result['caused_event_ids'][0]
            public_event=await session.get(NightEvent,(game,public_id))
            self.assertEqual(public_event.scope,'public')
            service=self.service(session)
            locked=await service.repo.lock_game(game)
            _,_,state=await service._runtime(locked)
            cutoff=await service._departure(locked,state,departed)
            private_id='private_after_cutoff_'+uuid4().hex
            # An ACL sentinel after the departed seat's retained frontier.
            session.add(NightEvent(game_id=game,event_id=private_id,scope='account:'+str(departed),
                audience_seq=cutoff['self_seq']+1,window_idx=public_event.window_idx,kind='action_result',
                payload={},created_at=self.now))
            public_job='public_'+uuid4().hex
            private_job='private_'+uuid4().hex
            public_message_job='public_message_'+uuid4().hex
            private_message_job='private_message_'+uuid4().hex
            for job_id,cause_id,audience in ((public_job,public_id,'public'),
                                              (private_job,private_id,'account:'+str(departed)),
                                              (public_message_job,message_result['caused_message_ids'][0],'public'),
                                              (private_message_job,message_result['caused_message_ids'][0],'account:'+str(departed))):
                await NightCaseRepository(session).enqueue_render(NightRenderJob(job_id=job_id,
                    game_id=game,cause_id=cause_id,kind='scene',audience_key=audience,
                    knowledge_revision=0,template_version='1',frozen_view={},input_hash=json_hash({}),
                    expires_at=self.now+timedelta(minutes=5),fallback='authored',status='pending',
                    attempts=0,lease_owner=None,lease_until=None,retry_at=None,sanitized_error=None))
        async with self.db.transaction() as session:
            await operation_fence(session,exclusive=True)
            await GameRepository(session).interrupt(await session.get(Game,game),event_kind='test-stopping')
        async with self.db.transaction() as session:
            await self.service(session).close_interrupted(operator=self.operator,game_id=game,
                action_id=uuid4().hex,reason='test stop')
        async with self.db.transaction() as session:
            await operation_fence(session,exclusive=True)
            merge=AccountMergeService()
            await merge.lock_owned_rows_in(session,[departed,continuing])
            await merge.merge_in(session,main=await session.get(Account,continuing),
                secondary=await session.get(Account,departed),via='test')
        async with self.db.transaction() as session:
            service=self.service(session)
            history=await service.history(account_id=continuing,game_id=game,stream='public')
            self.assertIn(public_id,[item['event_id'] for item in history['items']])
            private=await service.history(account_id=continuing,game_id=game,stream='self')
            self.assertNotIn(private_id,[item['event_id'] for item in private['items']])
            self.assertEqual((await service.get_rendering(account_id=continuing,game_id=game,
                job_id=public_job))['source'],'authored')
            self.assertEqual((await service.get_rendering(account_id=continuing,game_id=game,
                job_id=public_message_job))['source'],'authored')
            for denied_job in (private_job,private_message_job):
                with self.assertRaises(NightCaseError) as denied:
                    await service.get_rendering(account_id=continuing,game_id=game,job_id=denied_job)
                self.assertEqual(denied.exception.status,404)

    async def test_mafia_night_creation_race_has_one_winner(self):
        from storage.games import GameRepository
        from storage.admin_actions import operation_fence
        from application.night_case import NightCaseError
        command=self.lobby_command(params={'case_id':self.ref.case_id,'case_version':self.ref.case_version,'timezone':'Europe/Berlin'})
        barrier=asyncio.Barrier(2)
        async def night():
            await barrier.wait()
            try:
                async with self.db.transaction() as session:
                    await self.service(session).create_lobby(account_id=self.owner,room_id=self.room,command=command)
                return True
            except NightCaseError as e:
                self.assertEqual(e.code,'active_game_conflict'); return False
        async def mafia():
            await barrier.wait()
            try:
                async with self.db.transaction() as session:
                    await operation_fence(session)
                    await __import__('application.mafia',fromlist=['MafiaApplicationService']).MafiaApplicationService(session).create_room_lobby(
                        room_id=self.room,account_id=self.owner,name='Owner',command_id=uuid4().hex)
                return True
            except ValueError as e:
                self.assertEqual(str(e),'active_game_conflict'); return False
        self.assertEqual(sorted(await asyncio.wait_for(asyncio.gather(night(),mafia()),20)),[False,True])

    async def test_fence_is_first_sql_and_generic_command_api_rejects_internal_markers(self):
        from sqlalchemy import event
        from storage.games import GameRepository
        await self.db.check_connection()
        seen=[]
        def record(connection,cursor,statement,parameters,context,executemany): seen.append(statement)
        event.listen(self.db.engine.sync_engine,'before_cursor_execute',record)
        try:
            async with self.db.transaction() as session:
                await self.service(session).list_cases(account_id=self.owner)
            self.assertIn('pg_advisory_xact_lock_shared',seen[0])
        finally:
            event.remove(self.db.engine.sync_engine,'before_cursor_execute',record)
        game,*_=await self.running()
        with self.assertRaisesRegex(ValueError,'night_case_use_mode_repository'):
            async with self.db.transaction() as session:
                await GameRepository(session).reserve_command(command_id='internal-attempt',game_id=game,
                    actor_account_id=self.owner,kind='night.departure_cutoff',expected_revision=None,payload={})

    async def test_start_readiness_and_starts_flag_gate_new_effects_but_not_old_receipts(self):
        from application.night_case import NightCaseApplicationService,NightCaseError,AvailabilityDecision
        game,create,start_command=await self.ready_lobby()
        calls=[]
        async def unavailable(context):
            calls.append(context.locked.sealed.lifecycle)
            return AvailabilityDecision(True)
        with self.assertRaises(NightCaseError) as caught:
            async with self.db.transaction() as session:
                service=NightCaseApplicationService(session,lambda:self.now,self.registry,availability_hook=unavailable)
                await service.start_game(account_id=self.owner,game_id=game,command=start_command)
        self.assertEqual(caught.exception.code,'runtime_delayed')
        self.assertEqual(calls,['lobby'])
        async with self.db.transaction() as session:
            self.assertIsNone((await session.get(NightGameSealed,game)).kernel)
            self.assertEqual((await session.get(Game,game)).status,'lobby')
            started=await self.service(session).start_game(account_id=self.owner,game_id=game,command=start_command)
        async with self.db.transaction() as session:
            disabled=NightCaseApplicationService(session,lambda:(_ for _ in ()).throw(AssertionError('replay clock called')),
                self.registry,starts_enabled=False,availability_hook=unavailable)
            self.assertEqual(await disabled.start_game(account_id=self.owner,game_id=game,command=start_command),started)
            self.assertEqual((await disabled.create_lobby(account_id=self.owner,room_id=self.room,command=create))['view']['game_id'],game)
        self.assertEqual(calls,['lobby'])

    async def test_corrupt_lobby_hash_quarantines_new_reads_and_mutations_but_not_owned_receipt(self):
        from application.night_case import NightCaseError
        created,command=await self.lobby(); game=created['view']['game_id']
        async with self.db.transaction() as session:
            sealed=await session.get(NightGameSealed,game)
            corrupted=json.loads(json.dumps(sealed.lobby)); corrupted['revision']+=1
            sealed.lobby=corrupted
        for method,arguments in [('get_view',{}),('join_lobby',{'command':self.lobby_command(1)})]:
            with self.assertRaises(NightCaseError) as caught:
                async with self.db.transaction() as session:
                    await getattr(self.service(session),method)(account_id=self.owner,game_id=game,**arguments)
            self.assertEqual(caught.exception.code,'game_quarantined')
        async with self.db.transaction() as session:
            self.assertEqual(await self.service(session).create_lobby(account_id=self.owner,room_id=self.room,command=command),created)

    async def test_public_board_event_increments_game_revision(self):
        game,*_=await self.running()
        raw=await self.player_command(game,self.owner,'claim',{'text':'public revision witness'})
        async with self.db.transaction() as session:
            row=await session.get(Game,game); before=row.revision
            result=await self.service(session).execute(account_id=self.owner,game_id=game,command=raw)
            self.assertTrue(result['receipt']['accepted'])
        async with self.db.transaction() as session:
            row=await session.get(Game,game)
            self.assertEqual(row.revision,before+1)
            self.assertGreater(row.state['public_projection']['public_event_seq'],0)

    async def test_terminal_history_seat_selector_separates_roles_and_frontiers(self):
        from application.account_merge import AccountMergeService
        from application.night_case import NightCaseError
        from storage.admin_actions import operation_fence
        from storage.games import GameRepository
        game,*_=await self.running(); departed,continuing=self.accounts[1:3]
        before_message=await self.player_command(game,continuing,'say',{'channel':'square','recipients':[],'text':'before selected departure'})
        async with self.db.transaction() as session:
            before=await self.service(session).execute(account_id=continuing,game_id=game,command=before_message)
        forfeit=await self.player_command(game,departed,'forfeit')
        async with self.db.transaction() as session:
            await self.service(session).execute(account_id=departed,game_id=game,command=forfeit)
            departed_view=await self.service(session).get_view(account_id=departed,game_id=game)
        late_message=await self.player_command(game,continuing,'say',{'channel':'square','recipients':[],'text':'late selected departure canary'})
        async with self.db.transaction() as session:
            late=await self.service(session).execute(account_id=continuing,game_id=game,command=late_message)
        claim=await self.player_command(game,continuing,'claim',{'text':'late public frontier canary'})
        async with self.db.transaction() as session:
            public=await self.service(session).execute(account_id=continuing,game_id=game,command=claim)
            continuing_view=await self.service(session).get_view(account_id=continuing,game_id=game)
        async with self.db.transaction() as session:
            await operation_fence(session,exclusive=True)
            await GameRepository(session).interrupt(await session.get(Game,game),event_kind='test-stopping')
        async with self.db.transaction() as session:
            await self.service(session).close_interrupted(operator=self.operator,game_id=game,action_id=uuid4().hex,reason='test stop')
        async with self.db.transaction() as session:
            await operation_fence(session,exclusive=True)
            merge=AccountMergeService(); await merge.lock_owned_rows_in(session,[departed,continuing])
            await merge.merge_in(session,main=await session.get(Account,continuing),secondary=await session.get(Account,departed),via='test')
        async with self.db.transaction() as session:
            service=self.service(session)
            default=await service.get_view(account_id=continuing,game_id=game)
            old=await service.get_view(account_id=continuing,game_id=game,original_account_id=str(departed))
            own=await service.get_view(account_id=continuing,game_id=game,original_account_id=str(continuing))
            self.assertEqual(default['self']['character_id'],continuing_view['self']['character_id'])
            self.assertEqual(old['self'],departed_view['self'])
            self.assertNotEqual(old['self']['character_id'],own['self']['character_id'])
            for field in ('goal','secrets','role'):
                self.assertEqual(own['self'][field],continuing_view['self'][field])
            self.assertEqual(default['selected_original_account_id'],str(continuing))
            self.assertEqual(old['selected_original_account_id'],str(departed))
            self.assertEqual({r['original_account_id'] for r in old['history_seats']},{str(departed),str(continuing)})
            self.assertTrue(all(set(r)=={'original_account_id','display_name','role_title','status'} for r in old['history_seats']))
            self.assertEqual(await service.execute(account_id=continuing,game_id=game,command=late_message),late)
            old_private=await service.history(account_id=continuing,game_id=game,stream='self',original_account_id=departed)
            own_private=await service.history(account_id=continuing,game_id=game,stream='self',original_account_id=continuing)
            self.assertTrue(old_private['items']); self.assertTrue(own_private['items'])
            self.assertTrue({e['event_id'] for e in old_private['items']}.isdisjoint({e['event_id'] for e in own_private['items']}))
            old_public=await service.history(account_id=continuing,game_id=game,stream='public',original_account_id=departed)
            own_public=await service.history(account_id=continuing,game_id=game,stream='public',original_account_id=continuing)
            self.assertNotIn(public['caused_event_ids'][0],{e['event_id'] for e in old_public['items']})
            self.assertIn(public['caused_event_ids'][0],{e['event_id'] for e in own_public['items']})
            old_messages=await service.history(account_id=continuing,game_id=game,stream='messages',original_account_id=departed)
            own_messages=await service.history(account_id=continuing,game_id=game,stream='messages',original_account_id=continuing)
            union=await service.history(account_id=continuing,game_id=game,stream='messages')
            self.assertEqual({m['id'] for m in old_messages['items']},set(before['caused_message_ids']))
            self.assertIn(late['caused_message_ids'][0],{m['id'] for m in own_messages['items']})
            self.assertEqual(own_messages,union)
            first=await service.history(account_id=continuing,game_id=game,stream='public',original_account_id=departed,limit=1)
            self.assertIsNotNone(first['next_cursor'])
            for wrong_selector in (continuing,None):
                with self.assertRaises(NightCaseError):
                    await service.history(account_id=continuing,game_id=game,stream='public',original_account_id=wrong_selector,cursor=first['next_cursor'])
            for invalid in (self.owner,self.accounts[4],'not-a-uuid'):
                with self.assertRaises(NightCaseError) as caught:
                    await service.get_view(account_id=continuing,game_id=game,original_account_id=invalid)
                self.assertEqual(caught.exception.status,404)
                with self.assertRaises(NightCaseError):
                    await service.history(account_id=continuing,game_id=game,stream='self',original_account_id=invalid)

    async def test_active_history_selector_never_grants_new_rights(self):
        from application.night_case import NightCaseError
        game,*_=await self.running()
        async with self.db.transaction() as session:
            service=self.service(session)
            for selected in (self.owner,self.accounts[1],'invalid'):
                with self.assertRaises(NightCaseError) as caught:
                    await service.get_view(account_id=self.owner,game_id=game,original_account_id=selected)
                self.assertEqual(caught.exception.status,404)
                for stream in ('public','self','messages'):
                    with self.assertRaises(NightCaseError) as denied:
                        await service.history(account_id=self.owner,game_id=game,stream=stream,original_account_id=selected)
                    self.assertEqual(denied.exception.status,404)
            self.assertEqual((await service.get_view(account_id=self.owner,game_id=game))['self']['account_id'],str(self.owner))


class NightOwnedDatabaseGuardTests(unittest.TestCase):
    def test_owned_optin_cannot_redirect_host_port_user_database_or_url(self):
        from unittest.mock import patch
        from tests.local_database import disposable_endpoint_allowed
        url='postgresql+asyncpg://mqb_dev:local-development-only@127.0.0.1:55434/morning_quiz_test'
        with patch.dict(os.environ,{'NIGHT_CASE_TEST_DATABASE_URL':url},clear=False):
            self.assertTrue(disposable_endpoint_allowed(url))
            for bad in (url.replace('127.0.0.1','192.168.0.33'),url.replace('55434','55435'),
                        url.replace('morning_quiz_test','morning_quiz_dev'),url.replace('mqb_dev:','owner:'),
                        url.replace('development-only','different-password')):
                self.assertFalse(disposable_endpoint_allowed(bad),bad)
        for bad in (url.replace('127.0.0.1','192.168.0.33'),url.replace('55434','55435'),
                    url.replace('morning_quiz_test','morning_quiz_dev'),url.replace('mqb_dev:','owner:')):
            with patch.dict(os.environ,{'NIGHT_CASE_TEST_DATABASE_URL':bad},clear=False):
                self.assertFalse(disposable_endpoint_allowed(bad),bad)
