"""Alembic migration environment.

The DB URL is resolved from (in order):
1. ``OSFABRICUM_DB_URL`` environment variable
2. ``OSFABRICUM_CONFIG`` file or default config path
3. Built-in default (SQLite dev file)

Async driver suffixes are stripped so Alembic can use a sync engine.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Ensure all models are registered on Base.metadata before comparison.
import osfabricum.db.models  # noqa: F401
from osfabricum.db.base import Base
from osfabricum.db.engine import _sync_url
from osfabricum.settings import load_settings

config = context.config
if config.config_file_name is not None:
    # disable_existing_loggers=False: running migrations in-process (CLI, tests,
    # programmatic upgrade) must not silence the application's loggers.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _get_url() -> str:
    if url := os.environ.get("OSFABRICUM_DB_URL"):
        return _sync_url(url)
    settings = load_settings()
    return _sync_url(settings.database.url)


def run_migrations_offline() -> None:
    url = _get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    cfg = config.get_section(config.config_ini_section, {})
    cfg["sqlalchemy.url"] = _get_url()
    connectable = engine_from_config(
        cfg,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
