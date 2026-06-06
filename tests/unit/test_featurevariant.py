"""Tests for the Package Feature / Variant Manager (M36).

Covers the variant resolver: schema validation, defaults, feature-dependent
dependencies, and the deterministic ``feature_hash`` — including the tie-in that
makes it matter: the feature hash is the M35 cache-key component, so a feature
change yields a new cache key (a rebuild).
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from apps.api.app import create_app
from osfabricum import packageworkspace as pw
from osfabricum.db.base import Base
from osfabricum.db.models import Package
from osfabricum.settings import Settings


@pytest.fixture
def db_url(tmp_path) -> Iterator[str]:
    url = f"sqlite:///{tmp_path / 'fv.db'}"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    engine.dispose()
    yield url


@pytest.fixture
def pkg(db_url: str) -> str:
    engine = create_engine(db_url)
    try:
        with Session(engine) as s:
            p = Package(name="curl")
            s.add(p)
            s.commit()
            return p.id
    finally:
        engine.dispose()


@pytest.fixture
def curl(db_url: str, pkg: str) -> str:
    """curl with an ssl choice (backends pull deps) and a bool dbus feature."""
    pw.define_feature(
        pkg,
        "ssl",
        "choice",
        default="openssl",
        values=[
            {"value": "openssl", "implied_deps": ["openssl"]},
            {"value": "mbedtls", "implied_deps": ["mbedtls"]},
            {"value": "none", "implied_deps": []},
        ],
        db_url=db_url,
    )
    pw.define_feature(
        pkg,
        "dbus",
        "bool",
        default="n",
        values=[{"value": "y", "implied_deps": ["dbus"]}],
        db_url=db_url,
    )
    return pkg


# --- define_feature ---------------------------------------------------------


def test_unknown_feature_type_rejected(db_url: str, pkg: str) -> None:
    with pytest.raises(ValueError, match="unknown feature type"):
        pw.define_feature(pkg, "x", "enum", db_url=db_url)


def test_choice_requires_values(db_url: str, pkg: str) -> None:
    with pytest.raises(ValueError, match="requires at least one value"):
        pw.define_feature(pkg, "ssl", "choice", db_url=db_url)


def test_duplicate_feature_rejected(db_url: str, pkg: str) -> None:
    pw.define_feature(pkg, "static", "bool", default="n", db_url=db_url)
    with pytest.raises(ValueError, match="already defined"):
        pw.define_feature(pkg, "static", "bool", db_url=db_url)


# --- resolve_variant --------------------------------------------------------


def test_defaults_applied(db_url: str, curl: str) -> None:
    r = pw.resolve_variant(curl, {}, db_url=db_url)
    assert r["valid"] is True
    assert r["resolved"] == {"ssl": "openssl", "dbus": "n"}
    assert r["deps"] == ["openssl"]  # default ssl=openssl pulls openssl; dbus=n pulls nothing


def test_feature_dependent_deps_collected(db_url: str, curl: str) -> None:
    r = pw.resolve_variant(curl, {"ssl": "mbedtls", "dbus": "y"}, db_url=db_url)
    assert r["valid"] is True
    assert r["deps"] == ["dbus", "mbedtls"]


def test_unknown_requested_feature_errors(db_url: str, curl: str) -> None:
    r = pw.resolve_variant(curl, {"nope": "1"}, db_url=db_url)
    assert r["valid"] is False
    assert any("unknown feature" in e for e in r["errors"])


def test_invalid_choice_value_errors(db_url: str, curl: str) -> None:
    r = pw.resolve_variant(curl, {"ssl": "wolfssl"}, db_url=db_url)
    assert r["valid"] is False
    assert any("invalid value" in e for e in r["errors"])


def test_invalid_bool_value_errors(db_url: str, curl: str) -> None:
    r = pw.resolve_variant(curl, {"dbus": "maybe"}, db_url=db_url)
    assert r["valid"] is False


def test_feature_without_default_requires_value(db_url: str, pkg: str) -> None:
    pw.define_feature(pkg, "backend", "string", db_url=db_url)  # no default
    r = pw.resolve_variant(pkg, {}, db_url=db_url)
    assert r["valid"] is False
    assert any("no value and no default" in e for e in r["errors"])


# --- feature hash ↔ M35 cache key (the point) -------------------------------


def test_feature_hash_changes_with_values(db_url: str, curl: str) -> None:
    a = pw.resolve_variant(curl, {"ssl": "openssl"}, db_url=db_url)
    b = pw.resolve_variant(curl, {"ssl": "mbedtls"}, db_url=db_url)
    assert a["feature_hash"] != b["feature_hash"]
    assert a["feature_hash"].startswith("sha256:")


def test_feature_change_changes_cache_key_rebuild(db_url: str, curl: str) -> None:
    a = pw.resolve_variant(curl, {"ssl": "openssl"}, db_url=db_url)
    b = pw.resolve_variant(curl, {"ssl": "mbedtls"}, db_url=db_url)
    key_a = pw.compute_cache_key(
        name="curl", version="8.7", arch="arm64", feature_hash=a["feature_hash"]
    )
    key_b = pw.compute_cache_key(
        name="curl", version="8.7", arch="arm64", feature_hash=b["feature_hash"]
    )
    assert key_a["cache_key"] != key_b["cache_key"]  # feature change ⇒ rebuild


def test_diff_variants_reports_changed_feature(db_url: str, curl: str) -> None:
    a = pw.resolve_variant(curl, {"ssl": "openssl"}, db_url=db_url)["resolved"]
    b = pw.resolve_variant(curl, {"ssl": "mbedtls"}, db_url=db_url)["resolved"]
    d = pw.diff_variants(a, b)
    assert d["differs"] == ["ssl"]
    assert d["detail"]["ssl"] == {"a": "openssl", "b": "mbedtls"}


# --- record build variant ---------------------------------------------------


def test_record_build_variant_idempotent(db_url: str, curl: str) -> None:
    first = pw.record_build_variant(curl, "default", {"ssl": "openssl"}, db_url=db_url)
    assert first["hit"] is False
    again = pw.record_build_variant(curl, "default", {"ssl": "openssl"}, db_url=db_url)
    assert again["hit"] is True
    assert pw.list_build_variants(curl, db_url=db_url)[0]["feature_hash"] == first["feature_hash"]


def test_record_invalid_variant_raises(db_url: str, curl: str) -> None:
    with pytest.raises(ValueError, match="invalid value"):
        pw.record_build_variant(curl, "bad", {"ssl": "wolfssl"}, db_url=db_url)


# --- HTTP API ---------------------------------------------------------------


@pytest.fixture
def client(db_url: str) -> TestClient:
    settings = Settings()
    settings.database.url = db_url
    settings.auth.enabled = False
    return TestClient(create_app(settings))


def test_api_features_and_resolve(client: TestClient, curl: str) -> None:
    feats = client.get(f"/v1/packages/{curl}/features").json()
    assert {f["name"] for f in feats} == {"ssl", "dbus"}

    resolved = client.post(
        "/v1/package-variants/resolve",
        json={"package_id": curl, "requested": {"ssl": "mbedtls", "dbus": "y"}},
    ).json()
    assert resolved["valid"] is True
    assert resolved["deps"] == ["dbus", "mbedtls"]
    assert resolved["feature_hash"].startswith("sha256:")


def test_api_define_feature(client: TestClient, pkg: str) -> None:
    resp = client.post(
        f"/v1/packages/{pkg}/features",
        json={
            "name": "static",
            "type": "bool",
            "default": "n",
            "values": [{"value": "y", "implied_deps": []}],
        },
    )
    assert resp.status_code == 201
    assert client.get(f"/v1/packages/{pkg}/features").json()[0]["name"] == "static"
