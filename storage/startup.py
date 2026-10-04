"""Fail-closed runtime checks shared by server entry points."""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError


def require_postgres_backend(value: str) -> None:
    if value.strip().lower() != 'postgres':
        raise RuntimeError(
            'Morning Quiz runtime requires STORAGE_BACKEND=postgres; '
            'JSON is supported only as an explicit migration input.'
        )


def expected_schema_heads() -> set[str]:
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / 'alembic.ini'))
    scripts = ScriptDirectory.from_config(config)
    heads = set(scripts.get_heads())
    if len(heads) != 1:
        raise RuntimeError(f'Expected exactly one Alembic head, found {sorted(heads)}')
    return heads


async def require_current_schema(database, *, expected: set[str] | None = None) -> str:
    """Reject missing, split or stale schemas before serving any requests."""
    wanted = expected if expected is not None else expected_schema_heads()
    if len(wanted) != 1:
        raise RuntimeError(f'Expected exactly one schema revision, found {sorted(wanted)}')
    try:
        async with database.engine.connect() as connection:
            rows = (await connection.execute(text('SELECT version_num FROM alembic_version'))).scalars().all()
    except SQLAlchemyError as exc:
        raise RuntimeError('PostgreSQL schema is not initialized; run Alembic migrations first.') from exc
    current = set(rows)
    if current != wanted:
        raise RuntimeError(
            f'PostgreSQL schema revision mismatch: current={sorted(current)}, '
            f'expected={sorted(wanted)}. Run Alembic migrations before startup.'
        )
    return next(iter(current))
