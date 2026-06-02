"""Synchronous session factory for CLI commands and migrations."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from osfabricum.db.engine import make_sync_engine
from osfabricum.settings import load_settings


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@contextmanager
def sync_session(database_url: str | None = None) -> Generator[Session]:
    """Context manager yielding a sync Session using the configured DB URL."""
    if database_url is None:
        settings = load_settings()
        database_url = settings.database.url
    engine = make_sync_engine(database_url)
    factory = make_session_factory(engine)
    with factory() as session:
        yield session
    engine.dispose()
