"""Metadata checks do not replace migration and concurrency tests on PostgreSQL."""
from sqlalchemy.dialects.postgresql import dialect
from sqlalchemy.schema import CreateIndex, CreateTable

from storage.models import Base
from storage.night_ai_models import AI_MODELS


def test_nine_tables_share_platform_metadata_and_compile_postgres():
    assert len(AI_MODELS) == 9
    for model in AI_MODELS:
        assert model.metadata is Base.metadata
        assert 'CREATE TABLE night_ai_' in str(CreateTable(model.__table__).compile(dialect=dialect()))
        for index in model.__table__.indexes:
            assert 'CREATE' in str(CreateIndex(index).compile(dialect=dialect()))
        for fk in model.__table__.foreign_key_constraints:
            assert fk.ondelete == 'RESTRICT'


def test_new_account_fks_are_history_not_automatically_moved():
    from application.account_merge import MERGE_POLICY
    seen = {(table.name, fk.parent.name) for table in Base.metadata.tables.values()
            if table.name.startswith('night_ai_') for fk in table.foreign_keys if fk.target_fullname == 'accounts.id'}
    assert seen == {('night_ai_game_control', 'starter_account_id'),
                    ('night_ai_requests', 'requester_account_id'),
                    ('night_ai_intent_requests', 'requester_account_id')}
    assert all(MERGE_POLICY[item] == 'history' for item in seen)


def test_unique_live_grants_pending_requests_and_nonce_are_database_constraints():
    tables = Base.metadata.tables
    for table, name in [('night_ai_bindings', 'uq_nai_binding_active'),
                        ('night_ai_requests', 'uq_nai_request_pending'),
                        ('night_ai_profiles', 'uq_nai_profile_default')]:
        index = next(i for i in tables[table].indexes if i.name == name)
        assert index.unique and index.dialect_options['postgresql']['where'] is not None
    assert any(c.name == 'uq_nai_credential_nonce' for c in tables['night_ai_credentials'].constraints)
    fk = next(c for c in tables['night_ai_game_control'].foreign_key_constraints if c.name == 'fk_nai_control_binding')
    assert fk.deferrable and fk.initially == 'DEFERRED'
