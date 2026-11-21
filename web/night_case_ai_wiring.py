"""Composition of the Night AI narrator access services for the HTTP processes.

Reads only an explicit env mapping (``NIGHT_NARRATOR_*``/``NIGHT_AI_*``, see
docs/tasks/night_city/NIGHT_CASE_AI_ACCESS.md §4). Everything is default-off:
without ``NIGHT_NARRATOR_ENABLED=true`` and a valid operator manifest no AI
service is built and the routes answer 404, while Night Case keeps its authored
narration. A broken AI configuration never stops the game API: it is logged and
the narrator stays authored.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Mapping

from config.night_case_ai import PRESETS, ProfileRegistry
from config.night_case_ai_runtime import NightAIRuntimeSettings, RuntimeManifest, load_manifest_file
from storage.night_ai import ReceiptFingerprinter, SecretVault

logger = logging.getLogger(__name__)


def _utc_now():
    return datetime.now(timezone.utc)


def _manual_presets(env: Mapping[str, str]) -> frozenset[str]:
    """``NIGHT_AI_MANUAL_PRESETS``: presets whose model ID the operator types by hand."""
    raw = env.get('NIGHT_AI_MANUAL_PRESETS', '')
    if type(raw) is not str or len(raw) > 1024:
        raise ValueError('night_ai_manual_presets_invalid')
    names = frozenset(part.strip() for part in raw.split(',') if part.strip())
    if any(name not in PRESETS for name in names):
        raise ValueError('night_ai_manual_presets_invalid')
    return names


@dataclass(frozen=True, repr=False)
class NightAIWiring:
    """Pinned settings, operator manifest and secret primitives shared by every request."""
    settings: NightAIRuntimeSettings
    registry: ProfileRegistry
    manifest: RuntimeManifest | None = None
    clock: Callable[[], datetime] = _utc_now
    vault: SecretVault = field(init=False)
    receipts: ReceiptFingerprinter = field(init=False)

    def __post_init__(self):
        object.__setattr__(self, 'vault', SecretVault(self.settings.master_keys))
        object.__setattr__(self, 'receipts', ReceiptFingerprinter(self.settings.receipt_keys))

    def __repr__(self):
        return 'NightAIWiring(%r)' % (self.settings,)

    @property
    def deployment_id(self) -> str:
        return self.settings.deployment_id

    @property
    def vault_ready(self) -> bool:
        return self.settings.master_keys is not None and self.settings.receipt_keys is not None

    def control(self, session, *, original_starter_resolver=None):
        from application.night_case_ai import NightAIControlService
        return NightAIControlService(session, self.clock, self.registry, self.vault, self.receipts,
            environment_id=self.settings.environment_id, original_starter_resolver=original_starter_resolver)

    def views(self, session, app):
        """Views over ``app`` (a NightCaseApplicationService) on the very same session."""
        from application.night_case_ai_views import NightCaseAIViews
        ai = self.control(session, original_starter_resolver=app.prove_original_starter)
        return NightCaseAIViews(session, app, ai, runtime_enabled=self.settings.enabled,
            external_enabled=self.settings.external_allowed, vault_ready=self.vault_ready)

    def admin_catalog(self) -> dict:
        """Safe operator catalog for the admin form: no URL, CIDR, CA path or secret."""
        policies = self.manifest.admin_catalog() if self.manifest is not None else []
        presets = sorted({name for row in policies for name in row['presets']})
        return {
            'policies': policies,
            'presets': [{'id': name, 'adapters': list(PRESETS[name].adapters),
                         'auth_modes': list(PRESETS[name].auth_modes),
                         'required_fields': list(PRESETS[name].required_fields),
                         'optional_fields': list(PRESETS[name].optional_fields),
                         'local': PRESETS[name].base_url is None,
                         'manual_model_id': name in self.registry.manual_presets}
                        for name in presets],
            'known_models': sorted([preset, model] for preset, model in self.registry.models),
            'external_allowed': self.settings.external_allowed,
            'vault_ready': self.vault_ready,
        }


def load_night_ai_wiring(env: Mapping[str, str]) -> NightAIWiring | None:
    """Build the wiring when the narrator is switched on; otherwise ``None`` (authored only)."""
    try:
        settings = NightAIRuntimeSettings.from_env(env)
    except ValueError:
        logger.error('Night AI narrator configuration is invalid; narrator stays authored')
        return None
    if not settings.enabled:
        return None
    try:
        manifest = load_manifest_file(settings.manifest_path,
            expected_environment_id=settings.environment_id, manual_presets=_manual_presets(env))
    except ValueError:
        logger.error('Night AI operator manifest is invalid or unreadable; narrator stays authored')
        return None
    if not settings.master_keys or not settings.receipt_keys:
        logger.warning('Night AI keyrings are not configured; keys cannot be saved, narrator uses keyless profiles only')
    return NightAIWiring(settings=settings, registry=manifest.registry, manifest=manifest)
