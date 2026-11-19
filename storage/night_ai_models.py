"""Owning Night AI tables. Import explicitly until shared model registration.

Existing Game IDs are String(64); Account/AI identities are native UUIDs. No AI
secret is stored in Game.state, jobs, operation receipts or notification payloads.
"""
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey,
                        ForeignKeyConstraint, Index, Integer, LargeBinary,
                        String, UniqueConstraint, Uuid, and_, column, func, or_, text)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from storage.models import Base


def game_fk():
    return ForeignKey('games.id', ondelete='RESTRICT')


class NightAICredential(Base):
    __tablename__ = 'night_ai_credentials'
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    scope: Mapped[str] = mapped_column(String(8))
    owner_subject: Mapped[str] = mapped_column(String(96))
    game_id: Mapped[str | None] = mapped_column(String(64), game_fk())
    preset: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(12))
    key_id: Mapped[str | None] = mapped_column(String(64))
    nonce: Mapped[bytes | None] = mapped_column(LargeBinary)
    ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary)
    aad_version: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    erased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        # Build a SQL expression: a colon inside the regex is a string literal,
        # never SQLAlchemy text() bind syntax. DDL compiler quotes it itself.
        CheckConstraint(or_(
            and_(column('scope') == 'admin', column('game_id').is_(None),
                 column('owner_subject').op('~')('^admin:[A-Za-z0-9][A-Za-z0-9_.-]{0,63}:operator$')),
            and_(column('scope') == 'game', column('game_id').is_not(None),
                 column('owner_subject').op('~')('^account:[a-f0-9-]{36}$')),
        ), name='ck_nai_credential_scope'),
        CheckConstraint("status IN ('staged','usable','revoked','erased') AND (status <> 'staged' OR scope='game')", name='ck_nai_credential_status'),
        CheckConstraint("(status='erased' AND key_id IS NULL AND nonce IS NULL AND ciphertext IS NULL AND aad_version IS NULL AND erased_at IS NOT NULL) OR (status <> 'erased' AND key_id IS NOT NULL AND octet_length(nonce)=12 AND nonce IS NOT NULL AND octet_length(ciphertext) BETWEEN 17 AND 8208 AND ciphertext IS NOT NULL AND aad_version=1 AND aad_version IS NOT NULL AND erased_at IS NULL)", name='ck_nai_credential_secret'),
        CheckConstraint("(scope <> 'game' OR expires_at IS NOT NULL) AND (expires_at IS NULL OR expires_at > created_at)", name='ck_nai_credential_expiry'),
        UniqueConstraint('key_id', 'nonce', name='uq_nai_credential_nonce'),
        Index('ix_nai_credential_expiry', 'status', 'expires_at'),
    )


class NightAIProfile(Base):
    __tablename__ = 'night_ai_profiles'
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    scope: Mapped[str] = mapped_column(String(8))
    game_id: Mapped[str | None] = mapped_column(String(64), game_fk())
    label: Mapped[str] = mapped_column(String(80))
    current_revision: Mapped[int] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default='false')
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, server_default='false')
    created_by_subject: Mapped[str] = mapped_column(String(96))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        CheckConstraint("(scope='admin' AND game_id IS NULL) OR (scope='game' AND game_id IS NOT NULL)", name='ck_nai_profile_scope'),
        CheckConstraint("current_revision >= 1 AND length(label) BETWEEN 1 AND 80", name='ck_nai_profile_revision'),
        CheckConstraint("NOT is_default OR (scope='admin' AND enabled)", name='ck_nai_profile_default'),
        Index('uq_nai_profile_default', 'is_default', unique=True, postgresql_where=text('is_default')),
    )


class NightAIProfileRevision(Base):
    __tablename__ = 'night_ai_profile_revisions'
    profile_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey('night_ai_profiles.id', ondelete='RESTRICT'), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB)
    config_hash: Mapped[str] = mapped_column(String(64))
    credential_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey('night_ai_credentials.id', ondelete='RESTRICT'))
    created_by_subject: Mapped[str] = mapped_column(String(96))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        CheckConstraint("revision >= 1 AND config_hash ~ '^[a-f0-9]{64}$'", name='ck_nai_revision_identity'),
        CheckConstraint("jsonb_typeof(config)='object' AND octet_length(config::text)<=16384", name='ck_nai_revision_config'),
    )


class NightAIBinding(Base):
    __tablename__ = 'night_ai_bindings'
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    game_id: Mapped[str] = mapped_column(String(64), game_fk())
    epoch: Mapped[int] = mapped_column(Integer)
    mode: Mapped[str] = mapped_column(String(8))
    profile_id: Mapped[UUID] = mapped_column(Uuid)
    profile_revision: Mapped[int] = mapped_column(Integer)
    config_hash: Mapped[str] = mapped_column(String(64))
    granted_by_subject: Mapped[str] = mapped_column(String(96))
    status: Mapped[str] = mapped_column(String(12))
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    caps: Mapped[dict[str, Any]] = mapped_column(JSONB)
    health: Mapped[str] = mapped_column(String(16), server_default='ok', default='ok')
    inflight_job_id: Mapped[str | None] = mapped_column(String(96), ForeignKey('night_render_jobs.job_id', ondelete='RESTRICT'))
    inflight_permit_id: Mapped[UUID | None] = mapped_column(Uuid)
    inflight_lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        ForeignKeyConstraint(['profile_id', 'profile_revision'], ['night_ai_profile_revisions.profile_id', 'night_ai_profile_revisions.revision'], ondelete='RESTRICT', name='fk_nai_binding_revision'),
        CheckConstraint("epoch >= 1 AND mode IN ('admin','byok') AND config_hash ~ '^[a-f0-9]{64}$'", name='ck_nai_binding_identity'),
        CheckConstraint("status IN ('active','revoked','superseded','expired','closed') AND ((status='active') = (closed_at IS NULL))", name='ck_nai_binding_status'),
        CheckConstraint("health IN ('ok','auth_error','config_error') AND inflight_job_id IS NULL AND ((inflight_permit_id IS NULL) = (inflight_lease_until IS NULL))", name='ck_nai_binding_health'),
        ForeignKeyConstraint(['inflight_permit_id', 'id', 'game_id', 'epoch'], ['night_ai_dispatch_attempts.id', 'night_ai_dispatch_attempts.binding_id', 'night_ai_dispatch_attempts.game_id', 'night_ai_dispatch_attempts.epoch'], ondelete='RESTRICT', deferrable=True, initially='DEFERRED', name='fk_nai_binding_permit', use_alter=True),
        CheckConstraint("valid_until > created_at AND valid_until <= created_at + interval '30 days'", name='ck_nai_binding_expiry'),
        CheckConstraint("jsonb_typeof(caps)='object' AND octet_length(caps::text)<=8192", name='ck_nai_binding_caps'),
        UniqueConstraint('game_id', 'epoch', name='uq_nai_binding_epoch'),
        UniqueConstraint('id', 'game_id', 'epoch', name='uq_nai_binding_pointer'),
        Index('uq_nai_binding_active', 'game_id', unique=True, postgresql_where=text("status='active'")),
        Index('ix_nai_binding_expiry', 'status', 'valid_until'),
    )


class NightAIGameControl(Base):
    __tablename__ = 'night_ai_game_control'
    game_id: Mapped[str] = mapped_column(String(64), game_fk(), primary_key=True)
    starter_account_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey('accounts.id', ondelete='RESTRICT'))
    epoch: Mapped[int] = mapped_column(Integer, default=0, server_default='0')
    current_binding_id: Mapped[UUID | None] = mapped_column(Uuid)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        CheckConstraint('epoch >= 0 AND (starter_account_id IS NOT NULL OR (epoch=0 AND current_binding_id IS NULL))', name='ck_nai_control_epoch'),
        ForeignKeyConstraint(['current_binding_id', 'game_id', 'epoch'], ['night_ai_bindings.id', 'night_ai_bindings.game_id', 'night_ai_bindings.epoch'], ondelete='RESTRICT', deferrable=True, initially='DEFERRED', name='fk_nai_control_binding'),
    )


class NightAIRequest(Base):
    __tablename__ = 'night_ai_requests'
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    game_id: Mapped[str] = mapped_column(String(64), game_fk())
    epoch: Mapped[int] = mapped_column(Integer)
    requester_account_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey('accounts.id', ondelete='RESTRICT'))
    status: Mapped[str] = mapped_column(String(12))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_by_subject: Mapped[str | None] = mapped_column(String(96))
    binding_id: Mapped[UUID | None] = mapped_column(Uuid)
    reason: Mapped[str | None] = mapped_column(String(32))
    __table_args__ = (
        CheckConstraint("epoch >= 1 AND status IN ('pending','approved','denied','expired','cancelled') AND ((status='approved') = (binding_id IS NOT NULL)) AND ((status='pending') = (decided_at IS NULL))", name='ck_nai_request_status'),
        CheckConstraint("expires_at=created_at + interval '24 hours'", name='ck_nai_request_expiry'),
        CheckConstraint("reason IS NULL OR reason IN ('operator_denied','expired','superseded','terminal','starter_unusable','profile_unavailable')", name='ck_nai_request_reason'),
        ForeignKeyConstraint(['binding_id', 'game_id', 'epoch'], ['night_ai_bindings.id', 'night_ai_bindings.game_id', 'night_ai_bindings.epoch'], ondelete='RESTRICT', deferrable=True, initially='DEFERRED', name='fk_nai_request_binding'),
        UniqueConstraint('game_id', 'epoch', name='uq_nai_request_epoch'),
        Index('uq_nai_request_pending', 'game_id', unique=True, postgresql_where=text("status='pending'")),
    )


class NightAIJobBinding(Base):
    __tablename__ = 'night_ai_job_bindings'
    job_id: Mapped[str] = mapped_column(String(96), ForeignKey('night_render_jobs.job_id', ondelete='RESTRICT'), primary_key=True)
    game_id: Mapped[str] = mapped_column(String(64), game_fk())
    epoch: Mapped[int] = mapped_column(Integer)
    binding_id: Mapped[UUID | None] = mapped_column(Uuid)
    fallback_reason: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        UniqueConstraint('job_id', 'game_id', 'binding_id', 'epoch', name='uq_nai_job_dispatch_source'),
        CheckConstraint("epoch >= 0 AND ((binding_id IS NULL AND fallback_reason IS NOT NULL) OR (binding_id IS NOT NULL AND fallback_reason IS NULL))", name='ck_nai_job_assignment'),
        CheckConstraint("fallback_reason IS NULL OR fallback_reason IN ('authored','pending_approval','binding_unavailable','byok_audience_denied','runtime_unavailable')", name='ck_nai_job_fallback'),
        ForeignKeyConstraint(['binding_id', 'game_id', 'epoch'], ['night_ai_bindings.id', 'night_ai_bindings.game_id', 'night_ai_bindings.epoch'], ondelete='RESTRICT', name='fk_nai_job_binding'),
    )


class NightAIOperation(Base):
    __tablename__ = 'night_ai_operations'
    principal_subject: Mapped[str] = mapped_column(String(96), primary_key=True)
    client_request_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    operation: Mapped[str] = mapped_column(String(40))
    target_id: Mapped[str] = mapped_column(String(96))
    fingerprint: Mapped[str] = mapped_column(String(64))
    fingerprint_version: Mapped[str] = mapped_column(String(80))
    safe_result: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        CheckConstraint("fingerprint ~ '^[a-f0-9]{64}$' AND (fingerprint_version='sha256:1' OR fingerprint_version ~ '^hmac-sha256:[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$')", name='ck_nai_operation_fingerprint'),
        CheckConstraint("jsonb_typeof(safe_result)='object' AND octet_length(safe_result::text)<=8192", name='ck_nai_operation_result'),
    )


class NightAIIntentRequest(Base):
    """Durable prepare, never a player/domain command receipt or fake render job."""
    __tablename__ = 'night_ai_intent_requests'
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    game_id: Mapped[str] = mapped_column(String(64), game_fk())
    requester_account_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey('accounts.id', ondelete='RESTRICT'))
    client_request_id: Mapped[str] = mapped_column(String(96))
    fingerprint: Mapped[str] = mapped_column(String(64))
    epoch: Mapped[int] = mapped_column(Integer)
    binding_id: Mapped[UUID | None] = mapped_column(Uuid)
    token: Mapped[dict[str, Any]] = mapped_column(JSONB)
    legal_candidates: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    safe_result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    __table_args__ = (
        UniqueConstraint('id', 'game_id', 'binding_id', 'epoch', name='uq_nai_intent_dispatch_source'),
        ForeignKeyConstraint(['binding_id', 'game_id', 'epoch'], ['night_ai_bindings.id', 'night_ai_bindings.game_id', 'night_ai_bindings.epoch'], ondelete='RESTRICT', name='fk_nai_intent_binding'),
        CheckConstraint("epoch >= 0 AND fingerprint ~ '^[a-f0-9]{64}$' AND status IN ('prepared','finalized','expired','cancelled') AND ((status='prepared') = (finalized_at IS NULL)) AND ((status='prepared') = (safe_result IS NULL))", name='ck_nai_intent_status'),
        CheckConstraint("expires_at > created_at AND expires_at <= created_at + interval '5 minutes'", name='ck_nai_intent_expiry'),
        CheckConstraint("jsonb_typeof(token)='object' AND octet_length(token::text)<=8192 AND jsonb_typeof(legal_candidates)='object' AND octet_length(legal_candidates::text)<=32768 AND (safe_result IS NULL OR (jsonb_typeof(safe_result)='object' AND octet_length(safe_result::text)<=8192))", name='ck_nai_intent_documents'),
        UniqueConstraint('game_id', 'requester_account_id', 'client_request_id', name='uq_nai_intent_request'),
        Index('ix_nai_intent_expiry', 'status', 'expires_at'),
    )


class NightAIDispatchAttempt(Base):
    """One durable reservation authorizes at most one inference HTTP request."""
    __tablename__ = 'night_ai_dispatch_attempts'
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    source_kind: Mapped[str] = mapped_column(String(8))
    intent_id: Mapped[UUID | None] = mapped_column(Uuid)
    job_id: Mapped[str | None] = mapped_column(String(96))
    game_id: Mapped[str] = mapped_column(String(64))
    binding_id: Mapped[UUID] = mapped_column(Uuid)
    epoch: Mapped[int] = mapped_column(Integer)
    attempt_no: Mapped[int] = mapped_column(Integer)
    config_hash: Mapped[str] = mapped_column(String(64))
    caps_hash: Mapped[str] = mapped_column(String(64))
    payload_hash: Mapped[str] = mapped_column(String(64))
    contract_version: Mapped[str] = mapped_column(String(32))
    source_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    worker_id: Mapped[str] = mapped_column(String(96))
    lease_nonce: Mapped[UUID] = mapped_column(Uuid)
    reserved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    lease_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    network_deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(12))
    oauth_claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reserved_input_units: Mapped[int] = mapped_column(BigInteger)
    reserved_output_tokens: Mapped[int] = mapped_column(Integer)
    quota_debits: Mapped[list] = mapped_column(JSONB)
    retry_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(32))
    response_hash: Mapped[str | None] = mapped_column(String(64))
    usage: Mapped[dict | None] = mapped_column(JSONB)
    __table_args__ = (
        ForeignKeyConstraint(['binding_id', 'game_id', 'epoch'], ['night_ai_bindings.id', 'night_ai_bindings.game_id', 'night_ai_bindings.epoch'], ondelete='RESTRICT', name='fk_nai_dispatch_binding'),
        ForeignKeyConstraint(['intent_id', 'game_id', 'binding_id', 'epoch'], ['night_ai_intent_requests.id', 'night_ai_intent_requests.game_id', 'night_ai_intent_requests.binding_id', 'night_ai_intent_requests.epoch'], ondelete='RESTRICT', name='fk_nai_dispatch_intent'),
        ForeignKeyConstraint(['job_id', 'game_id', 'binding_id', 'epoch'], ['night_ai_job_bindings.job_id', 'night_ai_job_bindings.game_id', 'night_ai_job_bindings.binding_id', 'night_ai_job_bindings.epoch'], ondelete='RESTRICT', name='fk_nai_dispatch_job'),
        UniqueConstraint('id', 'binding_id', 'game_id', 'epoch', name='uq_nai_dispatch_pointer'),
        CheckConstraint("(source_kind='intent' AND intent_id IS NOT NULL AND job_id IS NULL) OR (source_kind='render' AND job_id IS NOT NULL AND intent_id IS NULL)", name='ck_nai_dispatch_source'),
        CheckConstraint("epoch>=1 AND attempt_no BETWEEN 1 AND 2 AND contract_version='night-ai-transport/1' AND length(worker_id) BETWEEN 1 AND 96", name='ck_nai_dispatch_identity'),
        CheckConstraint("config_hash ~ '^[a-f0-9]{64}$' AND caps_hash ~ '^[a-f0-9]{64}$' AND payload_hash ~ '^[a-f0-9]{64}$' AND (response_hash IS NULL OR response_hash ~ '^[a-f0-9]{64}$')", name='ck_nai_dispatch_hashes'),
        CheckConstraint("network_deadline=reserved_at+interval '12 seconds' AND network_deadline<=lease_until AND lease_until<=reserved_at+interval '30 seconds' AND lease_until<=source_expires_at", name='ck_nai_dispatch_deadline'),
        CheckConstraint("status IN ('reserved','sending','succeeded','failed','cancelled','expired') AND ((status IN ('reserved','sending'))=(finished_at IS NULL)) AND (status<>'reserved' OR sent_at IS NULL) AND (status<>'sending' OR sent_at IS NOT NULL) AND (status<>'succeeded' OR (sent_at IS NOT NULL AND response_hash IS NOT NULL))", name='ck_nai_dispatch_status'),
        CheckConstraint("(oauth_claimed_at IS NULL OR oauth_claimed_at>=reserved_at) AND (sent_at IS NULL OR (sent_at>=reserved_at AND sent_at<network_deadline)) AND (finished_at IS NULL OR finished_at>=reserved_at) AND (response_hash IS NULL OR finished_at IS NOT NULL) AND (usage IS NULL OR finished_at IS NOT NULL)", name='ck_nai_dispatch_times'),
        CheckConstraint("reserved_input_units>=0 AND reserved_output_tokens BETWEEN 1 AND 800 AND jsonb_typeof(quota_debits)='array' AND jsonb_array_length(quota_debits)=4 AND octet_length(quota_debits::text)<=4096", name='ck_nai_dispatch_budget'),
        CheckConstraint("retry_after IS NULL OR (status='failed' AND retry_after>=finished_at+interval '1 second' AND retry_after<=finished_at+interval '30 seconds' AND error_code IS NOT NULL AND error_code IN ('timeout','network_error','rate_limited','provider_error','auth_error'))", name='ck_nai_dispatch_retry'),
        CheckConstraint("error_code IS NULL OR error_code IN ('disabled','stale','expired','acl_denied','quota_exhausted','binding_busy','circuit_open','credential_unavailable','endpoint_denied','dns_failed','tls_failed','timeout','network_error','rate_limited','provider_error','auth_error','config_error','oversize','invalid_response','source_closed')", name='ck_nai_dispatch_error'),
        Index('uq_nai_dispatch_active_binding', 'binding_id', unique=True, postgresql_where=text("status IN ('reserved','sending')")),
        Index('uq_nai_dispatch_intent_attempt', 'intent_id', 'attempt_no', unique=True, postgresql_where=text('intent_id IS NOT NULL')),
        Index('uq_nai_dispatch_job_attempt', 'job_id', 'attempt_no', unique=True, postgresql_where=text('job_id IS NOT NULL')),
        Index('ix_nai_dispatch_expiry', 'status', 'lease_until'),
    )


# Retained 0049 set; migration tests use this to verify that nine historical tables
# survive independently of the additive dispatch migration.
AI_MODELS = (NightAICredential, NightAIProfile, NightAIProfileRevision, NightAIBinding,
             NightAIGameControl, NightAIRequest, NightAIJobBinding, NightAIOperation,
             NightAIIntentRequest)
DISPATCH_MODELS = (NightAIDispatchAttempt,)
