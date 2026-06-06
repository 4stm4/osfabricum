"""Tests for the Package Workspace / Package Manager service (M35).

Covers the two things that close G-04/G-28: the cache key that folds in the full
package identity (kernel-bound kinds require a kernel binding, a different config
yields a different key, every hit/miss is explained) and the layer-ordered
install-plan resolution. Also covers taxonomy classification, group reuse across
distributions, and locks.
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
from osfabricum.db.seed_data import seed_package_kinds, seed_package_layers
from osfabricum.settings import Settings


@pytest.fixture
def db_url(tmp_path) -> Iterator[str]:
    url = f"sqlite:///{tmp_path / 'pw.db'}"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    with Session(engine) as s:  # the taxonomy is seeded by migration 0011, not create_all
        seed_package_kinds(s)
        seed_package_layers(s)
        s.commit()
    engine.dispose()
    yield url


def _mk_package(
    db_url: str, name: str, *, kind: str | None = None, layer: str | None = None
) -> str:
    engine = create_engine(db_url)
    try:
        with Session(engine) as s:
            pkg = Package(name=name, kind=kind, layer=layer)
            s.add(pkg)
            s.commit()
            return pkg.id
    finally:
        engine.dispose()


# --- cache key (G-28) -------------------------------------------------------


def test_kernel_bound_requires_kernel_binding() -> None:
    with pytest.raises(ValueError, match="kernel_release and kernel_config_hash"):
        pw.compute_cache_key(name="rtl88", version="1.0", arch="arm64", kind="kernel-module")


def test_cache_key_includes_toolchain_not_just_name_ver_arch() -> None:
    a = pw.compute_cache_key(name="zlib", version="1.3", arch="arm64", toolchain_hash="tc-a")
    b = pw.compute_cache_key(name="zlib", version="1.3", arch="arm64", toolchain_hash="tc-b")
    assert a["cache_key"] != b["cache_key"]  # name+version+arch alone must not decide the key


def test_kernel_module_config_change_changes_key() -> None:
    common = dict(
        name="brcmfmac",
        version="6.6",
        arch="arm64",
        kind="kernel-module",
        kernel_release="6.6.1",
        toolchain_hash="tc",
    )
    a = pw.compute_cache_key(**common, kernel_config_hash="cfgA")
    b = pw.compute_cache_key(**common, kernel_config_hash="cfgB")
    assert a["cache_key"] != b["cache_key"]
    diff = pw.explain_cache(a["components"], b["components"])
    assert diff["same"] is False
    assert diff["differs"] == ["kernel_config_hash"]


# --- cache record / lookup --------------------------------------------------


def test_record_then_lookup_is_hit(db_url: str) -> None:
    ident = dict(
        name="busybox", version="1.36", arch="arm64", toolchain_hash="tc", artifact_id=None
    )
    rec = pw.record_cache_entry(db_url=db_url, **ident)
    assert rec["hit"] is False
    again = pw.record_cache_entry(db_url=db_url, **ident)
    assert again["hit"] is True
    look = pw.lookup_cache(
        db_url=db_url, name="busybox", version="1.36", arch="arm64", toolchain_hash="tc"
    )
    assert look["hit"] is True


def test_lookup_miss_is_explained(db_url: str) -> None:
    pw.record_cache_entry(
        db_url=db_url, name="openssl", version="3.3", arch="arm64", toolchain_hash="tc-a"
    )
    miss = pw.lookup_cache(
        db_url=db_url, name="openssl", version="3.3", arch="arm64", toolchain_hash="tc-b"
    )
    assert miss["hit"] is False
    assert miss["explain"]["differs"] == ["toolchain_hash"]


def test_kernel_module_not_reused_across_configs(db_url: str) -> None:
    base = dict(
        name="r8125",
        version="9.0",
        arch="arm64",
        kind="kernel-module",
        kernel_release="6.6.1",
        toolchain_hash="tc",
    )
    pw.record_cache_entry(db_url=db_url, **base, kernel_config_hash="cfgA")
    # Same module, different kernel .config → must be a miss (rebuild), explained.
    miss = pw.lookup_cache(db_url=db_url, **base, kernel_config_hash="cfgB")
    assert miss["hit"] is False
    assert "kernel_config_hash" in miss["explain"]["differs"]
    # The original config is still a hit.
    assert pw.lookup_cache(db_url=db_url, **base, kernel_config_hash="cfgA")["hit"] is True


# --- taxonomy ---------------------------------------------------------------


def test_kinds_and_layers_seeded(db_url: str) -> None:
    assert len(pw.list_kinds(db_url=db_url)) == 18
    layers = pw.list_layers(db_url=db_url)
    assert len(layers) == 13
    assert [layer["name"] for layer in layers][:2] == ["base", "hardware"]  # ordered


def test_classify_separates_system_and_application(db_url: str) -> None:
    sysp = _mk_package(db_url, "init")
    app = _mk_package(db_url, "firefox")
    pw.classify_package(sysp, kind="system", layer="system", db_url=db_url)
    pw.classify_package(app, kind="application", layer="applications", db_url=db_url)
    # distinct kinds → system and application are not interchangeable
    with pytest.raises(ValueError, match="unknown package kind"):
        pw.classify_package(sysp, kind="bogus", layer="system", db_url=db_url)


# --- groups (reuse across distributions) ------------------------------------


def test_group_reused_across_distributions(db_url: str) -> None:
    pkg = _mk_package(db_url, "coreutils")
    group = pw.create_group("core", db_url=db_url)["id"]  # global (distribution_id=None)
    pw.add_to_group(group, pkg, db_url=db_url)

    set_a = pw.create_set("edge-core", distribution_id="dist-a", db_url=db_url)["id"]
    set_b = pw.create_set("router-core", distribution_id="dist-b", db_url=db_url)["id"]
    pw.add_to_set(set_a, member_kind="group", group_id=group, db_url=db_url)
    pw.add_to_set(set_b, member_kind="group", group_id=group, db_url=db_url)

    groups = {g["name"]: g for g in pw.list_groups(db_url=db_url)}
    assert groups["core"]["global"] is True
    # the same group resolves inside both distributions' sets
    assert pw.resolve_set(set_a, db_url=db_url)["packages"][0]["package"] == "coreutils"
    assert pw.resolve_set(set_b, db_url=db_url)["packages"][0]["package"] == "coreutils"


# --- set resolve → layer-ordered install plan -------------------------------


def test_resolve_set_orders_by_layer(db_url: str) -> None:
    app = _mk_package(db_url, "app", kind="application", layer="applications")  # pos 8
    base = _mk_package(db_url, "libc", kind="library", layer="base")  # pos 0
    sysd = _mk_package(db_url, "systemd", kind="system", layer="system")  # pos 4
    pset = pw.create_set("full", db_url=db_url)["id"]
    for pid in (app, base, sysd):
        pw.add_to_set(pset, member_kind="package", package_id=pid, db_url=db_url)

    plan = pw.resolve_set(pset, db_url=db_url)
    assert [p["package"] for p in plan["packages"]] == ["libc", "systemd", "app"]
    assert plan["plan_hash"].startswith("sha256:")
    # deterministic
    assert pw.resolve_set(pset, db_url=db_url)["plan_hash"] == plan["plan_hash"]


# --- locks ------------------------------------------------------------------


def test_lock_create_and_duplicate(db_url: str) -> None:
    pw.create_lock("openssl", "3.3.0", reason="CVE pin", db_url=db_url)
    with pytest.raises(ValueError, match="already exists"):
        pw.create_lock("openssl", "3.3.0", db_url=db_url)
    assert pw.list_locks(db_url=db_url)[0]["package_name"] == "openssl"


# --- HTTP API (thin wrapper, auth disabled) ---------------------------------


@pytest.fixture
def client(db_url: str) -> TestClient:
    settings = Settings()
    settings.database.url = db_url
    settings.auth.enabled = False
    return TestClient(create_app(settings))


def test_api_cache_explain_flow(client: TestClient) -> None:
    # record an entry, then a differing lookup is explained over HTTP
    rec = client.post(
        "/v1/packages/cache",
        json={"name": "zstd", "version": "1.5", "arch": "arm64", "toolchain_hash": "tc-a"},
    )
    assert rec.status_code == 201
    miss = client.post(
        "/v1/packages/cache/lookup",
        json={"name": "zstd", "version": "1.5", "arch": "arm64", "toolchain_hash": "tc-b"},
    ).json()
    assert miss["hit"] is False
    assert miss["explain"]["differs"] == ["toolchain_hash"]


def test_api_kinds_listed(client: TestClient) -> None:
    kinds = client.get("/v1/package-kinds").json()
    assert {k["name"] for k in kinds} >= {"system", "application", "kernel-module"}
