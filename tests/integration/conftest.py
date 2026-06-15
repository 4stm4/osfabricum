"""Shared fixtures for M52 integration tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api.app import create_app
from osfabricum.db.engine import make_sync_engine
from osfabricum.db.models import Base
from osfabricum.db.seed_data import (
    seed_cache_policy_kinds,
    seed_layer_kinds,
    seed_override_kinds,
    seed_probe_source_kinds,
    seed_sdk_export_kinds,
    seed_update_strategy_kinds,
)
from osfabricum.db.session import sync_session
from osfabricum.settings import Settings


@pytest.fixture(scope="session")
def db_url(tmp_path_factory) -> str:
    tmp = tmp_path_factory.mktemp("integration_db")
    url = f"sqlite:///{tmp / 'integration.db'}"
    engine = make_sync_engine(url)
    Base.metadata.create_all(engine)
    engine.dispose()

    with sync_session(url) as s:
        seed_sdk_export_kinds(s)
        seed_cache_policy_kinds(s)
        seed_probe_source_kinds(s)
        seed_layer_kinds(s)
        seed_override_kinds(s)
        seed_update_strategy_kinds(s)
        s.commit()

    return url


@pytest.fixture(scope="session")
def client(db_url: str) -> TestClient:
    settings = Settings()
    settings.database.url = db_url
    return TestClient(create_app(settings))
