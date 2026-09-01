"""Alembic environment.

Migrations run over a *synchronous* psycopg connection even though the
application uses asyncpg. That is deliberate: `db/schema.sql` is one
script containing PL/pgSQL function bodies, and asyncpg's prepared-
statement path cannot execute a multi-statement script. psycopg can, so
migrations get a driver suited to migrations and the request path keeps
the async driver it needs.

The URL comes from Settings, so there is one source of truth.
"""

from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# Make the app package importable when alembic runs from backend/.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packages" / "domain"))

from ledgergraph_api.config import get_settings  # noqa: E402
from ledgergraph_api.db import Base  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _sync_url() -> str:
    """Swap the async driver for the sync one used by migrations."""
    return get_settings().database_url.replace("+asyncpg", "+psycopg")


# Autogenerate is available for future migrations, but the initial schema
# is applied from db/schema.sql because autogenerate cannot see triggers,
# partial indexes, or constraint expressions.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=_sync_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _sync_url()

    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
