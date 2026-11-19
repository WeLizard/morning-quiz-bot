"""Real Night AI control effects/races on explicitly owned PG55434, no transport."""
import asyncio
import copy
import os
import unittest
from datetime import timedelta
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError

from application.night_case_ai import AdminPrincipal, BindingCaps, ControlPointer, NightAIControlError, NightAIControlService, byok_audience_allowed
from config.night_case_ai import ModelCapabilities, ProfileRegistry
from storage.models import Account, Game, GameDeadline, GamePlayer, NightGameSealed, NightRenderJob, NotificationOutbox, Room, RoomMembership
from storage.night_ai import CredentialContext, KeyRing, ReceiptFingerprinter, SealedSecret, SecretVault
from storage.night_ai_models import NightAIBinding, NightAICredential, NightAIGameControl, NightAIJobBinding, NightAIOperation, NightAIProfile, NightAIProfileRevision, NightAIRequest
from storage.night_cases import NightCaseRepository, json_hash
from storage.notifications import NotificationQueue
from tests import test_night_case_application as base


@unittest.skipUnless(os.getenv('NIGHT_AI_CONTROL_TESTS') == '1', 'explicit NIGHT_AI_CONTROL_TESTS=1 required')
class NightAIControlPostgresTests(unittest.IsolatedAsyncioTestCase):
    service = base.NightApplicationPostgresTests.service
    lobby_command = base.NightApplicationPostgresTests.lobby_command
    lobby = base.NightApplicationPostgresTests.lobby
    ready_lobby = base.NightApplicationPostgresTests.ready_lobby
    player_command = base.NightApplicationPostgresTests.player_command

    async def asyncSetUp(self):
        from tests.night_case_test_database import night_case_test_url
        url = night_case_test_url()
        parsed = urlsplit(url)
        if os.getenv('TEST_DATABASE_URL') != url or parsed.hostname not in {'127.0.0.1', 'localhost'} or parsed.port != 55434:
            raise RuntimeError('control PG tests require matching TEST/NIGHT_CASE URL on owned55434')
        await base.NightApplicationPostgresTests.asyncSetUp(self)
        self.admin = AdminPrincipal('ai-test-' + uuid4().hex)
        self.ai_registry = ProfileRegistry.cloud({('openai', 'synthetic-model'): ModelCapabilities()})
        self.vault = SecretVault(KeyRing('synthetic', {'synthetic': b'v' * 32}))
        self.receipts = ReceiptFingerprinter(KeyRing('stable', {'stable': b'h' * 32}))
        self.settings = {'preset': 'openai', 'model_id': 'synthetic-model'}
        async with self.db.transaction() as session:
            self.assertEqual(await session.scalar(text('SELECT version_num FROM alembic_version')), '20261116_0049')

    async def asyncTearDown(self):
        async with self.db.transaction() as session:
            await session.execute(update(GameDeadline).where(GameDeadline.game_id.in_(
                select(NightGameSealed.game_id).where(NightGameSealed.case_id == self.ref.case_id))).values(status='cancelled', claimed_by=None, claimed_at=None))
        await self.db.dispose()

    def ai(self, session):
        return NightAIControlService(session, lambda: self.now, self.ai_registry, self.vault, self.receipts, environment_id='synthetic-test')

    async def call(self, method, **kwargs):
        async with self.db.transaction() as session:
            return await getattr(self.ai(session), method)(**kwargs)

    async def profile(self):
        saved = await self.call('save_profile_revision', operator=self.admin, profile_id=None,
            expected_revision=0, label='Synthetic model', settings=self.settings,
            secret=b'synthetic-provider-secret', client_request_id=uuid4().hex)
        profile_id = UUID(saved['result']['profile_id'])
        await self.call('set_profile_enabled', operator=self.admin, profile_id=profile_id,
                        enabled=True, client_request_id=uuid4().hex)
        return profile_id, 1

    async def start(self, mode='admin', *, staged=None, game=None, start_command=None):
        if game is None:
            game, _, start_command = await self.ready_lobby()
        from storage.games import night_room_lock
        # Standalone trusted-caller seam, not production orchestration. Room/mode
        # lock precedes Game, matching A. The whole caller transaction rolls back
        # if its subsequent real A start fails.
        async with self.db.transaction() as session:
            await night_room_lock(session, self.room)
            await session.scalar(select(Room).where(Room.id == self.room).with_for_update())
            ai = self.ai(session)
            await ai.acquire_start_config(account_id=self.owner)
            locked = await NightCaseRepository(session).lock_game(game)
            locked.game.started_at = self.now
            result = await ai.start_in_locked_game(account_id=self.owner, locked=locked,
                expected_epoch=0, now=self.now, mode=mode, staged_credential_id=staged)
            await self.service(session).start_game(account_id=self.owner, game_id=game, command=start_command)
        return game, result

    async def decide(self, request_id, decision='approve', profile=None, command=None):
        return await self.call('decide_request', operator=self.admin, request_id=UUID(request_id), decision=decision,
            profile_id=profile[0] if profile else None, profile_revision=profile[1] if profile else None,
            caps=None, client_request_id=command or uuid4().hex)

    async def synthetic_render_jobs(self, game):
        """Opaque storage/ACL fixtures, not a claimed narrator/intent implementation."""
        from storage.admin_actions import operation_fence
        ids = []
        async with self.db.transaction() as session:
            await operation_fence(session)
            repo = NightCaseRepository(session)
            await repo.lock_game(game)
            for audience in ('public', 'account:' + str(self.accounts[1])):
                job_id = uuid4().hex
                await repo.enqueue_render(NightRenderJob(job_id=job_id, game_id=game, cause_id=uuid4().hex,
                    kind='scene', audience_key=audience, knowledge_revision=0, template_version='synthetic-test/1',
                    frozen_view={}, input_hash=json_hash({}), expires_at=self.now+timedelta(minutes=5),
                    fallback='synthetic authored', status='pending', attempts=0, lease_owner=None,
                    lease_until=None, retry_at=None, sanitized_error=None))
                ids.append(job_id)
        return ids

    async def test_start_request_approval_exact_replay_expiry_and_no_game_rule_effects(self):
        profile = await self.profile()
        game, start = await self.start()
        async with self.db.transaction() as session:
            kernel = copy.deepcopy((await session.get(NightGameSealed, game)).kernel)
            revision = (await session.get(Game, game)).revision
            request = await session.get(NightAIRequest, UUID(start['request_id']))
            self.assertEqual(request.epoch, 1)
            self.assertEqual(request.expires_at, self.now + timedelta(hours=24))
        command = uuid4().hex
        approved = await self.decide(start['request_id'], profile=profile, command=command)
        self.now += timedelta(days=31)
        self.assertEqual((await self.decide(start['request_id'], profile=profile, command=command))['result'], approved['result'])
        async with self.db.transaction() as session:
            self.assertEqual((await session.get(NightGameSealed, game)).kernel, kernel)
            self.assertEqual((await session.get(Game, game)).revision, revision)
            self.assertEqual(await session.scalar(select(func.count()).select_from(NightAIBinding).where(NightAIBinding.game_id == game)), 1)
            self.assertEqual(await session.scalar(select(func.count()).select_from(NotificationOutbox).where(
                NotificationOutbox.game_id == game, NotificationOutbox.kind == 'night_ai_approval_requested')), 1)

    async def test_two_sessions_approve_deny_have_exactly_one_terminal_winner(self):
        profile = await self.profile()
        game, started = await self.start()
        results = await asyncio.gather(self.decide(started['request_id'], profile=profile),
                                       self.decide(started['request_id'], 'deny'), return_exceptions=True)
        self.assertEqual(sum(isinstance(r, dict) for r in results), 1)
        loser = next(r for r in results if not isinstance(r, dict))
        self.assertIsInstance(loser, NightAIControlError)
        self.assertEqual(loser.code, 'request_stale')
        async with self.db.transaction() as session:
            request = await session.get(NightAIRequest, UUID(started['request_id']))
            count = await session.scalar(select(func.count()).select_from(NightAIBinding).where(NightAIBinding.game_id == game))
            self.assertEqual(count, int(request.status == 'approved'))

    async def test_approve_racing_byok_cannot_replace_the_new_epoch(self):
        profile = await self.profile()
        game, started = await self.start()
        approved, byok = await asyncio.gather(self.decide(started['request_id'], profile=profile),
            self.call('stage_or_activate_byok', account_id=self.owner, game_id=game, expected_epoch=1,
                settings=self.settings, secret=b'synthetic-byok', client_request_id=uuid4().hex), return_exceptions=True)
        self.assertIsInstance(byok, dict)
        if isinstance(approved, Exception):
            self.assertIsInstance(approved, NightAIControlError)
            self.assertEqual(approved.code, 'request_stale')
        async with self.db.transaction() as session:
            control = await session.get(NightAIGameControl, game)
            binding = await session.get(NightAIBinding, control.current_binding_id)
            self.assertEqual((control.epoch, binding.mode, binding.status), (2, 'byok', 'active'))
            self.assertEqual(await session.scalar(select(func.count()).select_from(NightAIBinding).where(
                NightAIBinding.game_id == game, NightAIBinding.status == 'active')), 1)

    async def test_disable_reenable_never_revives_old_binding_and_stale_cleanup_keeps_new_key(self):
        profile = await self.profile()
        game, started = await self.start()
        approved = await self.decide(started['request_id'], profile=profile)
        old_id = UUID(approved['result']['binding_id'])
        for enabled in (False, True):
            await self.call('set_profile_enabled', operator=self.admin, profile_id=profile[0], enabled=enabled, client_request_id=uuid4().hex)
        byok = await self.call('stage_or_activate_byok', account_id=self.owner, game_id=game, expected_epoch=1,
            settings=self.settings, secret=b'synthetic-byok-new', client_request_id=uuid4().hex)
        pointer = ControlPointer(game, 'system:night_ai_cleanup', old_id, 'night_ai_cleanup')
        await self.call('cleanup_binding', operator=self.admin, pointer=pointer, client_request_id=uuid4().hex)
        async with self.db.transaction() as session:
            self.assertEqual((await session.get(NightAIBinding, old_id)).status, 'revoked')
            current = await session.get(NightAIBinding, UUID(byok['result']['binding_id']))
            credential = await session.get(NightAICredential, (await session.get(NightAIProfileRevision, (current.profile_id, current.profile_revision))).credential_id)
            self.assertEqual((current.status, credential.status), ('active', 'usable'))
            self.assertTrue(byok_audience_allowed(self.owner, 'public', frozenset()))
            self.assertFalse(byok_audience_allowed(self.owner, 'account:' + str(self.accounts[1]), frozenset({self.accounts[1]})))

    async def test_staged_start_rotates_id_nonce_aad_erases_old_and_old_receipt_is_only_replay(self):
        game, _, start_command = await self.ready_lobby()
        command = uuid4().hex
        kwargs = dict(account_id=self.owner, game_id=game, expected_epoch=0, settings=self.settings,
                      secret=b'synthetic-staged', client_request_id=command)
        staged = await self.call('stage_or_activate_byok', **kwargs)
        staged_id = UUID(staged['result']['staged_credential_id'])
        async with self.db.transaction() as session:
            old_nonce = (await session.get(NightAICredential, staged_id)).nonce
        self.now += timedelta(minutes=30)
        game, started = await self.start('byok', staged=staged_id, game=game, start_command=start_command)
        replay = await self.call('stage_or_activate_byok', **kwargs)
        self.assertTrue(replay['replayed'])
        self.assertEqual(replay['result'], staged['result'])
        async with self.db.transaction() as session:
            old = await session.get(NightAICredential, staged_id)
            binding = await session.get(NightAIBinding, UUID(started['binding_id']))
            revision = await session.get(NightAIProfileRevision, (binding.profile_id, binding.profile_revision))
            new = await session.get(NightAICredential, revision.credential_id)
            self.assertEqual(old.status, 'erased')
            self.assertIsNone(old.ciphertext)
            self.assertNotEqual(new.id, staged_id)
            self.assertNotEqual(new.nonce, old_nonce)
            self.assertEqual(new.expires_at, self.now + timedelta(days=30))
            self.assertEqual(self.vault.decrypt(SealedSecret(new.key_id, new.nonce, new.ciphertext, new.aad_version),
                CredentialContext('synthetic-test', UUID(str(new.id)), new.scope, new.owner_subject, new.game_id, new.preset)), b'synthetic-staged')

    async def test_generic_dispatch_never_claims_ai_or_poisoned_scopes_and_pins_are_immutable(self):
        profile = await self.profile()
        game, started = await self.start()
        kinds = {'night_ai_approval_requested', 'night_ai_cleanup', 'night_ai_unknown', 'mafia.phase'}
        async with self.db.transaction() as session:
            for kind, scope in [('night_ai_cleanup', 'public'), ('night_ai_unknown', 'public'), ('mafia.phase', 'admin:night_ai'), ('mafia.phase', 'system:night_ai_cleanup')]:
                await NotificationQueue.enqueue_in(session, kind=kind, game_id=game,
                    dedupe_key=uuid4().hex, payload={'scope': scope})
        queue = NotificationQueue(self.db)
        # Restrict to this game with unique kinds where possible. Existing public
        # test rows are not claimed: a transaction-scoped raw query below checks
        # the exact generic SQL against only these synthetic game rows.
        from unittest.mock import patch
        from sqlalchemy import Select
        original = Select.where
        def own_game(query, *criteria):
            if any('notification_outbox' in str(x) for x in query.get_final_froms()):
                criteria += (NotificationOutbox.game_id == game,)
            return original(query, *criteria)
        with patch.object(Select, 'where', own_game):
            self.assertIsNone(await queue.claim('ai-test', kinds=kinds, now=self.now + timedelta(days=1)))
        with self.assertRaises(DBAPIError):
            async with self.db.transaction() as session:
                await session.execute(update(NightAIProfileRevision).where(NightAIProfileRevision.profile_id == profile[0]).values(config_hash='f' * 64))

    async def test_approval_racing_profile_revocation_and_replay_racing_revoke_never_revive(self):
        profile = await self.profile()
        game, started = await self.start()
        results = await asyncio.gather(self.decide(started['request_id'], profile=profile),
            self.call('set_profile_enabled', operator=self.admin, profile_id=profile[0], enabled=False,
                      client_request_id=uuid4().hex), return_exceptions=True)
        self.assertIsInstance(results[1], dict)
        async with self.db.transaction() as session:
            self.assertEqual(await session.scalar(select(func.count()).select_from(NightAIBinding).where(
                NightAIBinding.game_id == game, NightAIBinding.status == 'active')), 0)
        if isinstance(results[0], Exception):
            self.assertIsInstance(results[0], NightAIControlError)
            self.assertEqual(results[0].code, 'profile_disabled')
        # A separate new request/grant, then own approval replay competes with
        # revoke. Replay may return the old receipt but cannot grant again.
        await self.call('set_profile_enabled', operator=self.admin, profile_id=profile[0], enabled=True, client_request_id=uuid4().hex)
        self.now += timedelta(minutes=5)
        pending = await self.call('request_admin', account_id=self.owner, game_id=game, expected_epoch=1, client_request_id=uuid4().hex)
        command = uuid4().hex
        granted = await self.decide(pending['result']['request_id'], profile=profile, command=command)
        binding_id = UUID(granted['result']['binding_id'])
        replay, revoked = await asyncio.gather(self.decide(pending['result']['request_id'], profile=profile, command=command),
            self.call('revoke_binding', operator=self.admin, binding_id=binding_id, client_request_id=uuid4().hex))
        self.assertTrue(replay['replayed'])
        self.assertEqual(replay['result'], granted['result'])
        async with self.db.transaction() as session:
            self.assertEqual((await session.get(NightAIBinding, binding_id)).status, 'revoked')

    async def test_profile_revision_cas_pins_existing_binding_and_invalid_config_rolls_back(self):
        profile = await self.profile()
        game, started = await self.start()
        approved = await self.decide(started['request_id'], profile=profile)
        async def save(tokens):
            return await self.call('save_profile_revision', operator=self.admin, profile_id=profile[0], expected_revision=1,
                label='New synthetic', settings={**self.settings, 'max_output_tokens': tokens}, client_request_id=uuid4().hex)
        results = await asyncio.gather(save(100), save(200), return_exceptions=True)
        self.assertEqual(sum(isinstance(r, dict) for r in results), 1,
                         [(type(r).__name__, getattr(r, 'code', None)) for r in results])
        failure = next(r for r in results if isinstance(r, Exception))
        self.assertIsInstance(failure, NightAIControlError)
        self.assertEqual(failure.code, 'stale_revision')
        async with self.db.transaction() as session:
            self.assertEqual((await session.get(NightAIProfile, profile[0])).current_revision, 2)
            self.assertEqual((await session.get(NightAIBinding, UUID(approved['result']['binding_id']))).profile_revision, 1)
            count = await session.scalar(select(func.count()).select_from(NightAICredential).where(NightAICredential.owner_subject == self.admin.subject))
        with self.assertRaises(NightAIControlError):
            await self.call('save_profile_revision', operator=self.admin, profile_id=profile[0], expected_revision=2,
                label='Invalid', settings={**self.settings, 'model_id': 'not-in-registry'}, secret=b'synthetic-new', client_request_id=uuid4().hex)
        async with self.db.transaction() as session:
            self.assertEqual((await session.get(NightAIProfile, profile[0])).current_revision, 2)
            self.assertEqual(await session.scalar(select(func.count()).select_from(NightAICredential).where(NightAICredential.owner_subject == self.admin.subject)), count)
        # Tightened registry makes an old pin unavailable; never substitute a
        # new model/default. Rebind fails and preserves the existing binding.
        old_id = UUID(approved['result']['binding_id'])
        self.ai_registry = ProfileRegistry.cloud({})
        with self.assertRaises(NightAIControlError) as caught:
            await self.call('rebind_admin', operator=self.admin, binding_id=old_id, expected_epoch=1,
                profile_id=profile[0], profile_revision=2, caps=None, client_request_id=uuid4().hex)
        self.assertEqual(caught.exception.code, 'config_unavailable')
        async with self.db.transaction() as session:
            self.assertEqual((await session.get(NightAIBinding, old_id)).status, 'active')
            self.assertEqual((await session.get(NightAIGameControl, game)).epoch, 1)

    async def test_key_receipt_replay_after_expiry_cleanup_and_block_denies_replay(self):
        game, _ = await self.start('authored')
        kwargs = dict(account_id=self.owner, game_id=game, expected_epoch=1,
            settings=self.settings, secret=b'synthetic-receipt-key', client_request_id=uuid4().hex)
        accepted = await self.call('stage_or_activate_byok', **kwargs)
        binding_id = UUID(accepted['result']['binding_id'])
        self.now += timedelta(days=31)
        cleaned = await self.call('cleanup_game', operator=self.admin, game_id=game, client_request_id=uuid4().hex)
        self.assertEqual(cleaned['result']['closed_bindings'], 1)
        replay = await self.call('stage_or_activate_byok', **kwargs)
        self.assertTrue(replay['replayed'])
        self.assertEqual(replay['result'], accepted['result'])
        async with self.db.transaction() as session:
            binding = await session.get(NightAIBinding, binding_id)
            revision = await session.get(NightAIProfileRevision, (binding.profile_id, binding.profile_revision))
            self.assertEqual((await session.get(NightAICredential, revision.credential_id)).status, 'erased')
            self.assertEqual(binding.status, 'expired')
        from storage.admin_actions import operation_fence
        async with self.db.transaction() as session:
            await operation_fence(session, exclusive=True)
            await session.execute(update(Account).where(Account.id == self.owner).values(bot_blocked=True))
        with self.assertRaises(NightAIControlError) as caught:
            await self.call('stage_or_activate_byok', **kwargs)
        self.assertEqual(caught.exception.code, 'account_unavailable')

    async def test_starter_departure_immediately_blocks_new_effects_then_cleanup_erases_byok(self):
        game, _ = await self.start('authored')
        bound = await self.call('stage_or_activate_byok', account_id=self.owner, game_id=game, expected_epoch=1,
            settings=self.settings, secret=b'synthetic-departure-key', client_request_id=uuid4().hex)
        command = await self.player_command(game, self.owner, 'forfeit')
        async with self.db.transaction() as session:
            result = await self.service(session).execute(account_id=self.owner, game_id=game, command=command)
            self.assertTrue(result['receipt']['accepted'])
        with self.assertRaises(NightAIControlError):
            await self.call('request_admin', account_id=self.owner, game_id=game, expected_epoch=2, client_request_id=uuid4().hex)
        await self.call('cleanup_game', operator=self.admin, game_id=game, client_request_id=uuid4().hex)
        async with self.db.transaction() as session:
            binding = await session.get(NightAIBinding, UUID(bound['result']['binding_id']))
            revision = await session.get(NightAIProfileRevision, (binding.profile_id, binding.profile_revision))
            self.assertEqual(binding.status, 'closed')
            self.assertEqual((await session.get(NightAICredential, revision.credential_id)).status, 'erased')

    async def test_request_cooldown_day_cap_secret_fingerprint_and_nonstarter_acl(self):
        game, _ = await self.start('admin')
        with self.assertRaises(NightAIControlError) as caught:
            await self.call('request_admin', account_id=self.owner, game_id=game, expected_epoch=1, client_request_id=uuid4().hex)
        self.assertEqual(caught.exception.code, 'request_cooldown')
        for epoch in (1, 2):
            self.now += timedelta(minutes=5)
            await self.call('request_admin', account_id=self.owner, game_id=game, expected_epoch=epoch, client_request_id=uuid4().hex)
        self.now += timedelta(minutes=5)
        with self.assertRaises(NightAIControlError) as caught:
            await self.call('request_admin', account_id=self.owner, game_id=game, expected_epoch=3, client_request_id=uuid4().hex)
        self.assertEqual(caught.exception.code, 'request_limit')
        kwargs = dict(account_id=self.owner, game_id=game, expected_epoch=3, settings=self.settings,
                      secret=b'synthetic-fingerprint-input', client_request_id=uuid4().hex)
        accepted = await self.call('stage_or_activate_byok', **kwargs)
        await self.synthetic_render_jobs(game)
        for changed, code in (({**kwargs, 'secret': b'changed-synthetic'}, 'idempotency_conflict'),
                              ({**kwargs, 'account_id': self.accounts[1]}, 'not_found')):
            with self.assertRaises(NightAIControlError) as caught:
                await self.call('stage_or_activate_byok', **changed)
            self.assertEqual(caught.exception.code, code)
        async with self.db.transaction() as session:
            operation = await session.get(NightAIOperation, ('account:' + str(self.owner), kwargs['client_request_id']))
            self.assertTrue(operation.fingerprint_version.startswith('hmac-sha256:'))
            self.assertNotIn('synthetic-fingerprint-input', str(operation.safe_result))
            self.assertEqual((await session.get(NightAIGameControl, game)).epoch, 4)
            self.assertEqual(await session.scalar(select(func.count()).select_from(NightAIRequest).where(NightAIRequest.game_id == game)), 3)
            binding = await session.get(NightAIBinding, UUID(accepted['result']['binding_id']))
            revision = await session.get(NightAIProfileRevision, (binding.profile_id, binding.profile_revision))
            owner = UUID((await session.get(NightAICredential, revision.credential_id)).owner_subject[8:])
            jobs = list((await session.scalars(select(NightRenderJob).where(NightRenderJob.game_id == game))).all())
            self.assertEqual(len(jobs), 2)
            for job in jobs:
                if job.audience_key.startswith('account:') and job.audience_key != 'account:' + str(owner):
                    self.assertFalse(byok_audience_allowed(owner, job.audience_key, frozenset({UUID(job.audience_key[8:])})))

    async def test_database_rejects_cross_game_credentials_binding_pointers_and_bad_scopes(self):
        game, _ = await self.start('authored')
        bound = await self.call('stage_or_activate_byok', account_id=self.owner, game_id=game, expected_epoch=1,
            settings=self.settings, secret=b'synthetic-scope-key', client_request_id=uuid4().hex)
        binding_id = UUID(bound['result']['binding_id'])
        job_id = (await self.synthetic_render_jobs(game))[0]
        async with self.db.transaction() as session:
            room = uuid4().hex
            session.add(Room(id=room, kind='standalone', owner_account_id=self.accounts[4]))
            await session.flush()
            session.add(RoomMembership(room_id=room, account_id=self.accounts[4], role='owner'))
            await session.flush()
            other = await self.service(session).create_lobby(account_id=self.accounts[4], room_id=room,
                command=self.lobby_command(params={'case_id': self.ref.case_id, 'case_version': self.ref.case_version, 'timezone': 'Europe/Berlin'}))
            other_game = other['view']['game_id']
        await self.call('ensure_lobby_control', account_id=self.accounts[4], game_id=other_game)
        async with self.db.transaction() as session:
            binding = await session.get(NightAIBinding, binding_id)
            original_revision = await session.get(NightAIProfileRevision, (binding.profile_id, binding.profile_revision))
            credential_id = original_revision.credential_id
            config, config_hash = copy.deepcopy(original_revision.config), original_revision.config_hash
        with self.assertRaises(DBAPIError):
            async with self.db.transaction() as session:
                session.add(NightAIJobBinding(job_id=job_id, game_id=other_game, epoch=2, binding_id=binding_id, created_at=self.now))
        with self.assertRaises(DBAPIError):
            async with self.db.transaction() as session:
                await session.execute(update(NightAIGameControl).where(NightAIGameControl.game_id == other_game).values(
                    current_binding_id=binding_id, epoch=2, starter_account_id=self.accounts[4]))
        with self.assertRaises(DBAPIError):
            async with self.db.transaction() as session:
                foreign_profile = NightAIProfile(id=uuid4(), scope='game', game_id=other_game, label='Bad cross-game',
                    current_revision=1, enabled=True, is_default=False, created_by_subject='account:' + str(self.accounts[4]), created_at=self.now)
                session.add(foreign_profile)
                await session.flush()
                session.add(NightAIProfileRevision(profile_id=foreign_profile.id, revision=1, config=config, config_hash=config_hash,
                    credential_id=credential_id, created_by_subject=foreign_profile.created_by_subject, created_at=self.now))
        with self.assertRaises(DBAPIError):
            async with self.db.transaction() as session:
                session.add(NightAICredential(id=uuid4(), scope='admin', owner_subject='account:' + str(self.owner), game_id=None,
                    preset='openai', status='usable', key_id='synthetic', nonce=b'bad-scope-12', ciphertext=b'x' * 17,
                    aad_version=1, created_at=self.now))
        async with self.db.transaction() as session:
            self.assertEqual((await session.get(NightAIGameControl, other_game)).epoch, 0)
            self.assertEqual((await session.get(NightAIBinding, binding_id)).status, 'active')

    async def test_missing_master_byok_start_rolls_back_and_authored_start_still_succeeds(self):
        game, _, command = await self.ready_lobby()
        staged = await self.call('stage_or_activate_byok', account_id=self.owner, game_id=game, expected_epoch=0,
            settings=self.settings, secret=b'synthetic-unavailable-master', client_request_id=uuid4().hex)
        staged_id = UUID(staged['result']['staged_credential_id'])
        self.vault = SecretVault(None)
        with self.assertRaises(NightAIControlError) as caught:
            await self.start('byok', staged=staged_id, game=game, start_command=command)
        self.assertEqual(caught.exception.code, 'ai_unavailable')
        async with self.db.transaction() as session:
            control = await session.get(NightAIGameControl, game)
            self.assertEqual((control.epoch, control.starter_account_id), (0, None))
            self.assertIsNone((await session.get(Game, game)).started_at)
            self.assertEqual((await session.get(NightAICredential, staged_id)).status, 'staged')
            self.assertEqual((await session.get(NightGameSealed, game)).lifecycle, 'lobby')
        _, result = await self.start('authored', game=game, start_command=command)
        self.assertEqual(result['status'], 'authored')

    async def test_default_profile_does_not_rebind_and_old_replay_has_no_new_effect(self):
        first = await self.profile()
        second = await self.profile()
        command = uuid4().hex
        old = await self.call('set_default_profile', operator=self.admin, profile_id=first[0], client_request_id=command)
        await self.call('set_default_profile', operator=self.admin, profile_id=second[0], client_request_id=uuid4().hex)
        for enabled in (False, True):
            await self.call('set_profile_enabled', operator=self.admin, profile_id=second[0], enabled=enabled, client_request_id=uuid4().hex)
        self.now += timedelta(days=40)
        replay = await self.call('set_default_profile', operator=self.admin, profile_id=first[0], client_request_id=command)
        self.assertTrue(replay['replayed'])
        self.assertEqual(replay['result'], old['result'])
        async with self.db.transaction() as session:
            self.assertFalse((await session.get(NightAIProfile, first[0])).is_default)
            self.assertFalse((await session.get(NightAIProfile, second[0])).is_default)

    async def test_terminal_merge_preserves_audit_ids_and_proven_alias_receipt_without_reviving_key(self):
        from application.account_merge import AccountMergeService
        from storage.admin_actions import operation_fence
        from storage.games import GameRepository
        game, _ = await self.start('authored')
        kwargs = dict(account_id=self.owner, game_id=game, expected_epoch=1, settings=self.settings,
                      secret=b'synthetic-retained-history', client_request_id=uuid4().hex)
        original = await self.call('stage_or_activate_byok', **kwargs)
        async with self.db.transaction() as session:
            await operation_fence(session, exclusive=True)
            await GameRepository(session).interrupt(await session.get(Game, game), event_kind='synthetic-stop')
        async with self.db.transaction() as session:
            await self.service(session).close_interrupted(operator=self.operator, game_id=game, action_id=uuid4().hex, reason='Synthetic terminal merge')
        await self.call('cleanup_game', operator=self.admin, game_id=game, client_request_id=uuid4().hex)
        main = self.accounts[4]
        async with self.db.transaction() as session:
            await operation_fence(session, exclusive=True)
            merge = AccountMergeService()
            await merge.lock_owned_rows_in(session, [main, self.owner])
            await merge.merge_in(session, main=await session.get(Account, main), secondary=await session.get(Account, self.owner), via='synthetic-test')
        replay = await self.call('stage_or_activate_byok', **{**kwargs, 'account_id': main})
        self.assertTrue(replay['replayed'])
        self.assertEqual(replay['result'], original['result'])
        async with self.db.transaction() as session:
            self.assertEqual((await session.get(NightAIGameControl, game)).starter_account_id, self.owner)
            binding = await session.get(NightAIBinding, UUID(original['result']['binding_id']))
            revision = await session.get(NightAIProfileRevision, (binding.profile_id, binding.profile_revision))
            self.assertEqual(binding.status, 'closed')
            self.assertEqual((await session.get(NightAICredential, revision.credential_id)).status, 'erased')

    async def test_two_sessions_same_request_id_replay_one_epoch_receipt_and_notification(self):
        game, _ = await self.start('admin')
        self.now += timedelta(minutes=5)
        kwargs = dict(account_id=self.owner, game_id=game, expected_epoch=1, client_request_id=uuid4().hex)
        first, second = await asyncio.gather(self.call('request_admin', **kwargs), self.call('request_admin', **kwargs))
        self.assertEqual(first['result'], second['result'])
        self.assertEqual(sorted([first['replayed'], second['replayed']]), [False, True])
        request_id = UUID(first['result']['request_id'])
        async with self.db.transaction() as session:
            self.assertEqual((await session.get(NightAIGameControl, game)).epoch, 2)
            self.assertEqual(await session.scalar(select(func.count()).select_from(NightAIOperation).where(
                NightAIOperation.principal_subject == 'account:' + str(self.owner),
                NightAIOperation.client_request_id == kwargs['client_request_id'])), 1)
            self.assertEqual(await session.scalar(select(func.count()).select_from(NotificationOutbox).where(
                NotificationOutbox.dedupe_key == 'night-ai-request:' + str(request_id))), 1)
