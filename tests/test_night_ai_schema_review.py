"""Offline regression for emitted credential DDL; never connects to PostgreSQL."""
import importlib.util
import io
from pathlib import Path
import re

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
from sqlalchemy.dialects.postgresql import dialect
from sqlalchemy.schema import CreateTable

from storage.night_ai_models import NightAICredential


@pytest.mark.parametrize('source', ['metadata', 'migration'])
def test_emitted_admin_subject_constraint_accepts_canonical_operator(source):
    if source == 'metadata':
        sql = str(CreateTable(NightAICredential.__table__).compile(dialect=dialect()))
    else:
        path = Path(__file__).resolve().parents[1] / 'alembic/versions/20261116_0049_night_ai_access.py'
        spec = importlib.util.spec_from_file_location('night_ai_migration_review', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        output = io.StringIO()
        context = MigrationContext.configure(
            dialect_name='postgresql', opts={'as_sql': True, 'output_buffer': output})
        with Operations.context(context):
            module.upgrade()
        sql = output.getvalue()
    # This expression uses the shared PostgreSQL/Python regex subset. Check the
    # actual emitted literal, not the uncompiled source CheckConstraint string.
    pattern = re.search(r"owner_subject ~ '([^']+)'", sql).group(1)
    assert re.fullmatch(pattern, 'admin:test:operator'), pattern
    assert not re.fullmatch(pattern, 'admin:test:other')
