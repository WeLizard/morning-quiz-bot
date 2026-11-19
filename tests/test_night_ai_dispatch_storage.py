"""Closed dispatch storage contracts; PG scenarios use an owned isolated schema."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy.dialects.postgresql import dialect
from sqlalchemy.schema import CreateTable


def test_unified_attempt_has_typed_source_fks_and_slot():
    from storage.night_ai_models import NightAIDispatchAttempt, NightAIBinding
    sql = str(CreateTable(NightAIDispatchAttempt.__table__).compile(dialect=dialect()))
    assert 'night_ai_intent_requests' in sql and 'night_ai_job_bindings' in sql
    assert any(i.name == 'uq_nai_dispatch_active_binding' and i.unique for i in NightAIDispatchAttempt.__table__.indexes)
    pointer = next(c for c in NightAIBinding.__table__.foreign_key_constraints if c.name == 'fk_nai_binding_permit')
    assert pointer.deferrable and pointer.initially == 'DEFERRED'


def test_source_and_reservation_reject_invalid_before_sql():
    from storage.night_ai_dispatch import DispatchSource, ReserveSpec, QuotaDebit
    with pytest.raises(ValueError): DispatchSource('intent', 'not-a-uuid')
    with pytest.raises(ValueError): DispatchSource('render', 'x' * 97)
    with pytest.raises(ValueError): DispatchSource('other', uuid4())
    now = datetime(2026, 11, 16, tzinfo=timezone.utc)
    args = dict(id=uuid4(), source=DispatchSource('intent', uuid4()), game_id='g', binding_id=uuid4(), epoch=1,
                attempt_no=1, config_hash='a'*64, caps_hash='b'*64, payload_hash='c'*64,
                source_expires_at=now+timedelta(seconds=120), worker_id='worker-1', lease_nonce=uuid4(),
                reserved_at=now, lease_until=now+timedelta(seconds=30), network_deadline=now+timedelta(seconds=12),
                reserved_input_units=200, reserved_output_tokens=100,
                quota_debits=tuple(QuotaDebit(scope,period,1,300,10,120000) for scope,period in (
                    ('nai:global:minute',now),('nai:actor:'+str(uuid4())+':minute',now),
                    ('game:g:day',now),('game:g:total',datetime(1970,1,1,tzinfo=timezone.utc)))))
    assert ReserveSpec(**args).source.kind=='intent'
    for change in ({'epoch': True}, {'attempt_no': 3}, {'network_deadline': now+timedelta(seconds=13)},
                   {'lease_until': now+timedelta(seconds=31)}, {'reserved_output_tokens': 801}):
        with pytest.raises(ValueError): ReserveSpec(**(args | change))


def test_actual_offline_migration_keeps_literal_scopes_and_checks_retention_before_drop():
    import io
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from tests.test_night_ai_dispatch_postgres import migration
    output=io.StringIO()
    with Operations.context(MigrationContext.configure(dialect_name='postgresql',opts={'as_sql':True,'output_buffer':output})):
        migration('0050').upgrade()
        migration('0050').downgrade()
    sql=output.getvalue()
    assert '%(' not in sql and ':actor:' in sql and ':minute' in sql
    assert sql.index('night_ai_dispatch_retention_required')<sql.index('DROP TABLE night_ai_dispatch_attempts')
    assert 'DEFERRABLE INITIALLY DEFERRED' in sql


def test_retry_check_metadata_and_frozen_migration_ddl_are_identical_and_nonnullable():
    from storage.night_ai_models import NightAIDispatchAttempt
    from tests.test_night_ai_dispatch_postgres import migration
    sql=str(CreateTable(NightAIDispatchAttempt.__table__).compile(dialect=dialect()))
    assert migration('0050').TABLE_DDL==sql
    retry=next(c for c in NightAIDispatchAttempt.__table__.constraints if c.name=='ck_nai_dispatch_retry')
    assert 'error_code IS NOT NULL AND error_code IN' in str(retry.sqltext)
