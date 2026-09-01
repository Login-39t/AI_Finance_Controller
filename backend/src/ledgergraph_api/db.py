"""Database engine and session.

The engine is created lazily and does not connect at import time, so the
service starts even when Postgres is unreachable. That is deliberate: a
process that refuses to boot without its database cannot serve a health
check that tells you the database is the thing that is down.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .config import get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None

# A readiness probe must answer within the platform's health-check budget.
# Three seconds to connect, five for the whole probe including the queries.
DB_CONNECT_TIMEOUT_SECONDS = 3.0
DB_PROBE_TIMEOUT_SECONDS = 5.0


class Base(DeclarativeBase):
    """Declarative base for ORM models.

    Note that `db/schema.sql` is the source of truth for the schema, not
    these models. The schema carries triggers, partial indexes, and
    constraint expressions that SQLAlchemy's autogenerate cannot see, so
    models are for querying, and migrations are hand-written.
    """


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        settings = get_settings()
        connect_args: dict[str, Any] = {}
        if "+asyncpg" in settings.database_url:
            # Without an explicit connect timeout, a host that accepts the
            # TCP connection but never completes the handshake leaves the
            # probe hanging until the platform's own timeout kills it, and
            # the diagnostic is lost. Fail fast and report the reason.
            connect_args["timeout"] = DB_CONNECT_TIMEOUT_SECONDS

        _engine = create_async_engine(
            settings.database_url,
            echo=settings.db_echo,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_pre_ping=True,
            connect_args=connect_args,
        )
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(
            get_engine(),
            expire_on_commit=False,
            autoflush=False,
        )
    return _sessionmaker


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a session bound to one request.

    The transaction commits only if the handler returns cleanly. Every
    mutation writes its audit event inside this same transaction, so a
    partially-audited change is not representable.
    """
    async with get_sessionmaker()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def check_database() -> dict[str, Any]:
    """Probe the database for the readiness endpoint.

    Returns a status dict rather than raising, because "the database is
    down" is information the endpoint exists to report, not an error it
    should hide behind a 500.
    """
    import asyncio

    from sqlalchemy import text

    async def _probe() -> dict[str, Any]:
        async with get_engine().connect() as conn:
            version = (await conn.execute(text("SHOW server_version"))).scalar_one()
            # Missing table means the database exists but has never been
            # migrated, which is a different problem from being unreachable
            # and deserves to be reported differently.
            try:
                migration = (
                    await conn.execute(text("SELECT version_num FROM alembic_version LIMIT 1"))
                ).scalar_one_or_none()
            except Exception:
                migration = None
        return {"reachable": True, "serverVersion": version, "migration": migration}

    try:
        return await asyncio.wait_for(_probe(), timeout=DB_PROBE_TIMEOUT_SECONDS)
    except TimeoutError:
        return {
            "reachable": False,
            "error": f"probe exceeded {DB_PROBE_TIMEOUT_SECONDS:.0f}s",
        }
    except Exception as exc:  # noqa: BLE001 - the reason is the payload
        return {"reachable": False, "error": f"{type(exc).__name__}: {exc}"[:300]}


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None
