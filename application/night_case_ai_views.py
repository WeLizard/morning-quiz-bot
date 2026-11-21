"""Read-only, closed Night AI projections for future HTTP routes.

All methods return JSON-shaped dictionaries. The caller owns one AsyncSession,
shared with the game and AI services. This module never commits, flushes,
decrypts a credential, acquires the AI advisory lock, or calls a provider.
"""

from __future__ import annotations

import copy
from datetime import datetime
from uuid import UUID

from sqlalchemy import select

from application.night_case import NightCaseError
from application.night_case_ai import (AI_PARTICIPATING_STATUSES, BindingCaps,
                                       NightAIControlError)
from config.night_case_ai import ProfileRevision
from storage.models import Account, Game, GamePlayer, Room
from storage.night_ai_models import (NightAIBinding, NightAICredential,
                                     NightAIGameControl, NightAIProfile,
                                     NightAIProfileRevision, NightAIRequest)
from storage.admin_actions import operation_fence


def _page(limit: int, offset: int) -> tuple[int, int]:
    if type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or not 0 <= offset <= 10000:
        raise NightAIControlError('invalid_config', 422)
    return limit, offset


def _uid(value) -> UUID:
    if type(value) is not UUID:
        raise NightAIControlError('invalid_config', 422)
    return value


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


class NightCaseAIViews:
    """Safe DTO API: presets, game status, admin profiles/revisions/inbox/bindings.

    Constructor flags are trusted deployment readiness, default OFF. ``ai`` and
    ``app`` are the real services with the exact same caller-owned session.
    Non-starter game status has exactly ``status,model_label``. Admin list
    methods (profiles, profile revisions, requests, bindings) return
    ``{items,has_more}``; no raw config or credential is exposed.
    """

    def __init__(self, session, app, ai, *, runtime_enabled=False, external_enabled=False, vault_ready=False):
        if session is not app.session or session is not ai.session:
            raise ValueError('night_ai_session_mismatch')
        if any(type(flag) is not bool for flag in (runtime_enabled, external_enabled, vault_ready)):
            raise ValueError('night_ai_readiness_invalid')
        self.session, self.app, self.ai = session, app, ai
        self.runtime_enabled = runtime_enabled
        self.external_enabled = external_enabled
        self.vault_ready = vault_ready

    async def list_presets(self, account_id: UUID) -> dict:
        """Authenticated public BYOK catalog; never endpoint or admin model IDs."""
        await operation_fence(self.session)
        await self.ai._account(account_id)
        registry = self.ai.registry
        enabled = {preset for preset, _ in registry.models} | set(registry.manual_presets)
        items = [row for row in registry.byok_catalog() if row['id'] in enabled]
        for row in items:
            row['models'] = sorted(model for preset, model in registry.models if preset == row['id'])
            row['manual_model_id'] = row['id'] in registry.manual_presets
        # Readiness is reported before the form is submitted (§4): BYOK keys are cloud-only.
        reason = ('ai_disabled' if not self.runtime_enabled else 'egress_disabled' if not self.external_enabled
                  else 'vault_unavailable' if not self.vault_ready else 'no_presets' if not items else None)
        return {'items': items, 'byok_ready': reason is None, 'reason': reason}

    async def _credential_meta(self, credential_id: UUID | None):
        if credential_id is None:
            return None
        return (await self.session.execute(select(
            NightAICredential.id, NightAICredential.scope, NightAICredential.owner_subject,
            NightAICredential.game_id, NightAICredential.preset, NightAICredential.status,
            NightAICredential.expires_at).where(NightAICredential.id == credential_id))).one_or_none()

    async def _validated_revision(self, profile_id, revision_number, *, byok):
        profile = await self.session.get(NightAIProfile, profile_id, populate_existing=True)
        revision = await self.session.get(NightAIProfileRevision, (profile_id, revision_number), populate_existing=True)
        if profile is None or revision is None:
            return None
        try:
            decoded = ProfileRevision.decode(revision.config, self.ai.registry, byok=byok)
        except (ValueError, TypeError, KeyError):
            return None
        if decoded.config_hash != revision.config_hash or decoded.document()['credential_id'] != (
            str(revision.credential_id) if revision.credential_id else None):
            return None
        return profile, revision, decoded.document()

    async def get_ai_status(self, account_id: UUID, game_id: str) -> dict:
        """Game ACL status. Starter gains only §7 controls and own staged metadata."""
        await operation_fence(self.session)
        await self.ai._account(account_id)
        try:
            account, locked, aliases = await self.app._access(account_id, game_id, history=True)
        except NightCaseError as exc:
            raise NightAIControlError('not_found' if exc.status == 404 else 'game_unavailable',
                                      404 if exc.status == 404 else 503) from None
        if locked.game.mode != 'night_case':
            raise NightAIControlError('not_found', 404)
        now = self.ai._now()
        control = (await self.session.execute(select(
            NightAIGameControl.starter_account_id, NightAIGameControl.epoch,
            NightAIGameControl.current_binding_id).where(NightAIGameControl.game_id == game_id))).one_or_none()
        starter = control.starter_account_id if control else None
        lobby = locked.sealed.lifecycle == 'lobby' and locked.game.status == 'lobby'
        unavailable = locked.sealed.lifecycle in {'finished', 'stopped', 'interrupted'}
        running = locked.sealed.lifecycle == 'running' and locked.game.status == 'running'
        if control is None and not lobby:
            try:
                starter = await self.app.prove_original_starter(locked)
            except NightCaseError:
                starter = None
        room = None
        if lobby:
            room = await self.session.get(Room, locked.game.room_id, populate_existing=True)
            is_starter = room is not None and room.owner_account_id == account.id
        else:
            is_starter = starter == account.id
        own_active = False
        if is_starter and running:
            own_active = await self.session.scalar(select(GamePlayer.game_id).where(
                GamePlayer.game_id == game_id, GamePlayer.account_id == account.id,
                GamePlayer.status.in_(AI_PARTICIPATING_STATUSES)).limit(1)) is not None
        can_configure = bool(is_starter and (lobby or (running and own_active)))
        epoch = control.epoch if control else 0
        request = (await self.session.execute(select(
            NightAIRequest.id, NightAIRequest.status, NightAIRequest.expires_at,
            NightAIRequest.reason).where(NightAIRequest.game_id == game_id,
            NightAIRequest.epoch == epoch).order_by(NightAIRequest.created_at.desc(), NightAIRequest.id.desc()).limit(1))).one_or_none()
        pending = request is not None and request.status == 'pending' and request.expires_at > now and not unavailable
        binding = None
        if control and control.current_binding_id is not None:
            binding = await self.session.get(NightAIBinding, control.current_binding_id, populate_existing=True)
        model_label = None
        active = False
        reason = None
        mode = 'authored'
        expires_at = request.expires_at if pending else None
        if binding is not None:
            mode = binding.mode if binding.mode in {'admin', 'byok'} else 'authored'
            expires_at = binding.valid_until
            validated = await self._validated_revision(binding.profile_id, binding.profile_revision,
                                                       byok=binding.mode == 'byok')
            if validated is not None:
                profile, revision, config = validated
                credential = await self._credential_meta(revision.credential_id)
                credential_ok = (revision.credential_id is None or
                    (credential is not None and credential.status == 'usable' and
                     (credential.expires_at is None or credential.expires_at > now) and
                     credential.preset == config['preset'] and credential.scope == profile.scope and
                     credential.game_id == profile.game_id and
                     (binding.mode != 'byok' or credential.owner_subject == 'account:' + str(starter))))
                network_ready = (config['endpoint']['network_class'] == 'trusted_local'
                                 or self.external_enabled)
                secret_ready = config['auth_mode'] == 'none' or self.vault_ready
                active = bool(self.runtime_enabled and network_ready and secret_ready and running
                    and binding.game_id == game_id and binding.epoch == epoch
                    and binding.status == 'active' and binding.health == 'ok' and binding.valid_until > now
                    and binding.config_hash == revision.config_hash and profile.enabled and credential_ok
                    and ((binding.mode == 'admin' and profile.scope == 'admin' and profile.game_id is None)
                         or (binding.mode == 'byok' and profile.scope == 'game' and profile.game_id == game_id)))
                if active:
                    model_label = config['model_id']
            if not active:
                reason = 'binding_unavailable'
        status = 'ai' if active else 'fallback' if binding is not None else 'pending' if pending else 'authored'
        result = {'status': status, 'model_label': model_label}
        if not is_starter:
            return result
        staged = (await self.session.execute(select(
            NightAICredential.id, NightAICredential.expires_at).where(
                NightAICredential.scope == 'game', NightAICredential.game_id == game_id,
                NightAICredential.owner_subject == 'account:' + str(account.id),
                NightAICredential.status == 'staged', NightAICredential.expires_at > now)
            .order_by(NightAICredential.created_at.desc()).limit(1))).one_or_none()
        if lobby and staged is not None:
            mode = 'byok'
            expires_at = staged.expires_at
        elif pending:
            mode = 'admin'
        result.update({'mode': mode, 'epoch': epoch, 'request_id': str(request.id) if request else None,
            'request_status': request.status if request else None, 'expires_at': _iso(expires_at),
            'credential_configured': staged is not None or (binding is not None and binding.mode == 'byok' and active),
            # Own staged reference only; the start command must name it explicitly.
            'staged_credential_id': str(staged.id) if lobby and staged is not None else None,
            'can_configure': can_configure, 'reason': reason or (request.reason if request else None)})
        return result

    async def list_admin_profiles(self, principal, *, limit=50, offset=0) -> dict:
        """Operator-owned admin profiles, current revision and masked credential."""
        await operation_fence(self.session)
        subject = await self.ai._admin(principal)
        limit, offset = _page(limit, offset)
        rows = (await self.session.execute(select(NightAIProfile.id, NightAIProfile.label,
            NightAIProfile.current_revision, NightAIProfile.enabled, NightAIProfile.is_default,
            NightAIProfile.created_at).where(NightAIProfile.scope == 'admin',
            NightAIProfile.created_by_subject == subject).order_by(NightAIProfile.created_at.desc(),
            NightAIProfile.id.desc()).offset(offset).limit(limit+1))).all()
        items = []
        for row in rows[:limit]:
            revision = await self._validated_revision(row.id, row.current_revision, byok=False)
            if revision is None:
                raise NightAIControlError('config_unavailable', 503)
            _, rev, config = revision
            credential = await self._credential_meta(rev.credential_id)
            items.append({'profile_id': str(row.id), 'label': row.label, 'current_revision': row.current_revision,
                'enabled': row.enabled, 'is_default': row.is_default, 'created_at': _iso(row.created_at),
                'preset': config['preset'], 'model_id': config['model_id'],
                'credential_configured': credential is not None and credential.status == 'usable',
                'masked_key': '••••' if credential is not None and credential.status == 'usable' else None})
        return {'items': items, 'has_more': len(rows) > limit}

    async def get_admin_profile_revision(self, principal, profile_id: UUID, revision: int) -> dict:
        """One historical admin revision; selected settings only, never raw config."""
        await operation_fence(self.session)
        subject = await self.ai._admin(principal)
        _uid(profile_id)
        if type(revision) is not int or revision < 1:
            raise NightAIControlError('invalid_config', 422)
        validated = await self._validated_revision(profile_id, revision, byok=False)
        if validated is None or validated[0].scope != 'admin' or validated[0].created_by_subject != subject:
            raise NightAIControlError('not_found', 404)
        profile, rev, config = validated
        credential = await self._credential_meta(rev.credential_id)
        return {'profile_id': str(profile.id), 'label': profile.label, 'revision': rev.revision,
            'current_revision': profile.current_revision, 'enabled': profile.enabled, 'is_default': profile.is_default,
            'created_at': _iso(rev.created_at), 'preset': config['preset'], 'model_id': config['model_id'],
            'adapter': config['adapter'], 'auth_mode': config['auth_mode'],
            'json_output': config['capabilities']['json_output'],
            'max_output_tokens': config['generation']['max_output_tokens'],
            'temperature': config['generation']['temperature'],
            'credential_configured': credential is not None and credential.status == 'usable',
            'masked_key': '••••' if credential is not None and credential.status == 'usable' else None}

    async def list_admin_profile_revisions(self, principal, profile_id: UUID, *, limit=50, offset=0) -> dict:
        """Bounded historical revision refs for one operator-created admin profile."""
        await operation_fence(self.session)
        subject = await self.ai._admin(principal)
        _uid(profile_id)
        limit, offset = _page(limit, offset)
        profile = await self.session.get(NightAIProfile, profile_id, populate_existing=True)
        if profile is None or profile.scope != 'admin' or profile.created_by_subject != subject:
            raise NightAIControlError('not_found', 404)
        rows = (await self.session.execute(select(NightAIProfileRevision.revision,
            NightAIProfileRevision.created_at).where(NightAIProfileRevision.profile_id == profile_id)
            .order_by(NightAIProfileRevision.revision.desc()).offset(offset).limit(limit+1))).all()
        return {'items': [{'revision': row.revision, 'created_at': _iso(row.created_at)}
                          for row in rows[:limit]], 'has_more': len(rows) > limit}

    async def list_admin_requests(self, principal, *, limit=50, offset=0) -> dict:
        """Bounded pending-first inbox with only requester display name and room title."""
        await operation_fence(self.session)
        await self.ai._admin(principal)
        limit, offset = _page(limit, offset)
        rows = (await self.session.execute(select(NightAIRequest.id, NightAIRequest.game_id,
            NightAIRequest.epoch, NightAIRequest.status, NightAIRequest.created_at,
            NightAIRequest.expires_at, NightAIRequest.reason, Account.display_name, Room.title)
            .join(Account, Account.id == NightAIRequest.requester_account_id)
            .join(Game, Game.id == NightAIRequest.game_id).join(Room, Room.id == Game.room_id)
            .order_by((NightAIRequest.status == 'pending').desc(), NightAIRequest.created_at.desc(),
                      NightAIRequest.id.desc()).offset(offset).limit(limit+1))).all()
        return {'items': [{'request_id': str(r.id), 'game_id': r.game_id, 'epoch': r.epoch,
            'status': r.status, 'created_at': _iso(r.created_at), 'expires_at': _iso(r.expires_at),
            'reason': r.reason, 'requester_display_name': r.display_name, 'room_title': r.title}
            for r in rows[:limit]], 'has_more': len(rows) > limit}

    async def list_admin_bindings(self, principal, *, limit=50, offset=0) -> dict:
        """Bounded refs and safe admin caps; no profile config, BYOK owner or secret."""
        await operation_fence(self.session)
        await self.ai._admin(principal)
        limit, offset = _page(limit, offset)
        rows = (await self.session.execute(select(NightAIBinding.id, NightAIBinding.game_id,
            NightAIBinding.epoch, NightAIBinding.mode, NightAIBinding.status,
            NightAIBinding.valid_until, NightAIBinding.health, NightAIBinding.caps,
            NightAIBinding.created_at).order_by(NightAIBinding.created_at.desc(),
            NightAIBinding.id.desc()).offset(offset).limit(limit+1))).all()
        items = []
        for row in rows[:limit]:
            try:
                caps = BindingCaps.decode(row.caps).document() if row.mode == 'admin' else None
            except NightAIControlError:
                raise NightAIControlError('config_unavailable', 503) from None
            items.append({'binding_id': str(row.id), 'game_id': row.game_id, 'epoch': row.epoch,
                'mode': row.mode, 'status': row.status, 'valid_until': _iso(row.valid_until),
                'health': row.health, 'caps': copy.deepcopy(caps),
                'created_at': _iso(row.created_at)})
        return {'items': items, 'has_more': len(rows) > limit}
