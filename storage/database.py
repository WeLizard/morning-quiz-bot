"""Async SQLAlchemy engine and transaction lifecycle."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator, Optional

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def _as_bool(value: Optional[str], default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def normalize_database_url(url: str) -> str:
    """Accept common PostgreSQL URLs and select the asyncpg driver."""
    normalized = url.strip()
    if normalized.startswith("postgres://"):
        normalized = "postgresql://" + normalized[len("postgres://") :]
    if normalized.startswith("postgresql://"):
        normalized = "postgresql+asyncpg://" + normalized[len("postgresql://") :]
    if not normalized.startswith("postgresql+asyncpg://"):
        raise ValueError("DATABASE_URL must use PostgreSQL (postgresql+asyncpg://)")
    return normalized


@dataclass(frozen=True)
class DatabaseSettings:
    url: str
    pool_size: int = 5
    max_overflow: int = 5
    pool_timeout: float = 10.0
    echo: bool = False

    @classmethod
    def from_env(cls) -> "DatabaseSettings":
        raw_url = os.getenv("DATABASE_URL", "").strip()
        if not raw_url:
            raise RuntimeError("DATABASE_URL is required for PostgreSQL operations")
        return cls(
            url=normalize_database_url(raw_url),
            pool_size=max(1, int(os.getenv("DATABASE_POOL_SIZE", "5"))),
            max_overflow=max(0, int(os.getenv("DATABASE_MAX_OVERFLOW", "5"))),
            pool_timeout=max(1.0, float(os.getenv("DATABASE_POOL_TIMEOUT", "10"))),
            echo=_as_bool(os.getenv("DATABASE_ECHO")),
        )


class Database:
    """Owns the engine and exposes short, explicit transaction scopes."""

    def __init__(self, settings: DatabaseSettings):
        self.settings = settings
        self.engine: AsyncEngine = create_async_engine(
            settings.url,
            echo=settings.echo,
            pool_pre_ping=True,
            pool_recycle=1800,
            pool_size=settings.pool_size,
            max_overflow=settings.max_overflow,
            pool_timeout=settings.pool_timeout,
        )
        self.session_factory = async_sessionmaker(
            self.engine,
            expire_on_commit=False,
            autoflush=False,
        )

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncSession]:
        async with self.session_factory() as session:
            async with session.begin():
                yield session

    async def check_connection(self) -> None:
        async with self.engine.connect() as connection:
            await connection.exec_driver_sql("SELECT 1")

    async def dispose(self) -> None:
        await self.engine.dispose()
