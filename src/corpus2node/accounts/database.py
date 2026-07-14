from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from corpus2node.config import settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None
_database_url = ""
_initialized_url = ""


def engine() -> AsyncEngine:
    global _engine, _session_factory, _database_url
    if _engine is None or _database_url != settings.database_url:
        _database_url = settings.database_url
        parsed = make_url(_database_url)
        if parsed.get_backend_name() == "sqlite" and parsed.database and parsed.database != ":memory:":
            Path(parsed.database).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        _engine = create_async_engine(_database_url, pool_pre_ping=True)
        _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def session_factory() -> async_sessionmaker[AsyncSession]:
    engine()
    assert _session_factory is not None
    return _session_factory


async def get_db() -> AsyncIterator[AsyncSession]:
    async with session_factory()() as db:
        yield db


async def init_db() -> None:
    global _initialized_url
    if not settings.database_auto_create:
        return
    if _initialized_url == settings.database_url:
        return
    from corpus2node.accounts.models import Base

    async with engine().begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    _initialized_url = settings.database_url


async def dispose_db() -> None:
    global _engine, _session_factory, _database_url, _initialized_url
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None
    _database_url = ""
    _initialized_url = ""
