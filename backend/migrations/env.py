"""Alembic environment configuration for async SQLAlchemy."""

import asyncio
from collections.abc import Iterable
from logging.config import fileConfig

from alembic import context
from alembic.operations.ops import MigrationScript
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

import app.core.db.registry  # noqa: F401  # register models on BaseSchema.metadata for autogenerate
from app.core.config import config as app_config
from app.core.db.schema import BaseSchema

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = BaseSchema.metadata


def process_revision_directives(
    context: MigrationContext,
    revision: str | Iterable[str | None] | Iterable[str],
    directives: list[MigrationScript],
) -> None:
    """Assign sequential zero-padded revision ids (0000, 0001, ...) to new revisions."""
    head = ScriptDirectory.from_config(config).get_current_head()
    next_id = int(head) + 1 if head is not None else 0
    directives[0].rev_id = f"{next_id:04d}"


def run_migrations_offline() -> None:
    """Run migrations in offline mode without an engine."""
    context.configure(
        url=app_config.SQLALCHEMY_DATABASE_URI,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        process_revision_directives=process_revision_directives,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Run migrations with the given connection."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        process_revision_directives=process_revision_directives,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in online mode with an async engine."""
    connectable = create_async_engine(app_config.SQLALCHEMY_DATABASE_URI, poolclass=pool.NullPool)
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_async_migrations())
