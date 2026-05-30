"""Synchronous SQLAlchemy engine factory.

CLI commands and Alembic migrations use a synchronous engine.  The async
engine for the API is a separate concern (M4).  If the configured URL uses
an async driver (e.g. ``sqlite+aiosqlite``, ``postgresql+asyncpg``), the
driver suffix is stripped so SQLAlchemy can create a sync engine.
"""

from __future__ import annotations

import re

import sqlalchemy as sa
from sqlalchemy import Engine


def _sync_url(url: str) -> str:
    """Convert an async driver URL to a sync-compatible URL."""
    return re.sub(r"\+(aiosqlite|asyncpg|aiomysql)", "", url)


def make_sync_engine(database_url: str, **kwargs: object) -> Engine:
    """Create and return a synchronous SQLAlchemy engine."""
    return sa.create_engine(_sync_url(database_url), **kwargs)
