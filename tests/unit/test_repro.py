"""Tests for M13: Reproducibility Model — BuildEnvSpec, hash chain, ingest."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from osfabricum.db.engine import make_sync_engine
from osfabricum.db.models import Base
from osfabricum.repro.chain import (
    InputManifest,
    compute_input_hash,
    make_repro_record,
    repro_record_from_dict,
    verify_repro,
)
from osfabricum.repro.env import (
    PROTECTED_ENV_VARS,
    SOURCE_DATE_EPOCH,
    BuildEnvSpec,
    compute_env_hash,
    make_reproducible_env,
)
from osfabricum.store.ingest import ingest_blob

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_url(tmp_path: Path) -> str:
    url = f"sqlite:///{tmp_path / 'test.db'}"
    engine = make_sync_engine(url)
    Base.metadata.create_all(engine)
    engine.dispose()
    return url


@pytest.fixture()
def store_root(tmp_path: Path) -> Path:
    return tmp_path / "store"


# ---------------------------------------------------------------------------
# BuildEnvSpec
# ---------------------------------------------------------------------------


def test_source_date_epoch_is_zero() -> None:
    assert SOURCE_DATE_EPOCH == 0


def test_protected_env_vars_contains_sde() -> None:
    assert "SOURCE_DATE_EPOCH" in PROTECTED_ENV_VARS
    assert "LANG" in PROTECTED_ENV_VARS
    assert "TZ" in PROTECTED_ENV_VARS


def test_build_env_spec_defaults() -> None:
    spec = BuildEnvSpec()
    assert spec.arch == ""
    assert spec.toolchain_id is None
    assert spec.cross_compile_prefix == ""


def test_build_env_spec_to_dict() -> None:
    spec = BuildEnvSpec(arch="aarch64", cross_compile_prefix="aarch64-linux-musl-")
    d = spec.to_dict()
    assert d["arch"] == "aarch64"
    assert d["cross_compile_prefix"] == "aarch64-linux-musl-"


# ---------------------------------------------------------------------------
# compute_env_hash
# ---------------------------------------------------------------------------


def test_compute_env_hash_returns_hex_string() -> None:
    spec = BuildEnvSpec(arch="aarch64")
    h = compute_env_hash(spec)
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)


def test_compute_env_hash_deterministic() -> None:
    spec = BuildEnvSpec(arch="aarch64")
    assert compute_env_hash(spec) == compute_env_hash(spec)


def test_compute_env_hash_changes_with_arch() -> None:
    h1 = compute_env_hash(BuildEnvSpec(arch="aarch64"))
    h2 = compute_env_hash(BuildEnvSpec(arch="x86_64"))
    assert h1 != h2


def test_compute_env_hash_changes_with_toolchain() -> None:
    h1 = compute_env_hash(BuildEnvSpec(toolchain_id="tc-v1"))
    h2 = compute_env_hash(BuildEnvSpec(toolchain_id="tc-v2"))
    assert h1 != h2


def test_compute_env_hash_same_for_equal_specs() -> None:
    spec_a = BuildEnvSpec(arch="arm", cross_compile_prefix="arm-linux-musl-")
    spec_b = BuildEnvSpec(arch="arm", cross_compile_prefix="arm-linux-musl-")
    assert compute_env_hash(spec_a) == compute_env_hash(spec_b)


# ---------------------------------------------------------------------------
# make_reproducible_env
# ---------------------------------------------------------------------------


def test_make_reproducible_env_sets_sde() -> None:
    env = make_reproducible_env(BuildEnvSpec())
    assert env["SOURCE_DATE_EPOCH"] == "0"


def test_make_reproducible_env_sets_locale() -> None:
    env = make_reproducible_env(BuildEnvSpec())
    assert env["LANG"] == "C"
    assert env["LC_ALL"] == "C"
    assert env["TZ"] == "UTC"


def test_make_reproducible_env_sets_arch() -> None:
    env = make_reproducible_env(BuildEnvSpec(arch="aarch64"))
    assert env["ARCH"] == "aarch64"


def test_make_reproducible_env_sets_cross_compile() -> None:
    env = make_reproducible_env(
        BuildEnvSpec(cross_compile_prefix="aarch64-linux-musl-")
    )
    assert env["CROSS_COMPILE"] == "aarch64-linux-musl-"


def test_make_reproducible_env_path_includes_toolchain() -> None:
    env = make_reproducible_env(
        BuildEnvSpec(), path_extra=["/opt/toolchain/bin"]
    )
    assert env["PATH"].startswith("/opt/toolchain/bin")


def test_make_reproducible_env_protected_vars_cannot_be_overridden() -> None:
    """Caller cannot override SOURCE_DATE_EPOCH via env_extra."""
    env = make_reproducible_env(
        BuildEnvSpec(),
        env_extra={"SOURCE_DATE_EPOCH": "9999999"},
    )
    assert env["SOURCE_DATE_EPOCH"] == "0"


def test_make_reproducible_env_non_protected_extra_included() -> None:
    env = make_reproducible_env(
        BuildEnvSpec(),
        env_extra={"MY_CUSTOM_VAR": "hello"},
    )
    assert env["MY_CUSTOM_VAR"] == "hello"


# ---------------------------------------------------------------------------
# InputManifest & compute_input_hash
# ---------------------------------------------------------------------------


def _make_manifest(**kwargs) -> InputManifest:
    defaults = dict(
        step_kind="package.build",
        source_hash="a" * 64,
        config_hash="b" * 64,
        env_hash="c" * 64,
    )
    defaults.update(kwargs)
    return InputManifest(**defaults)


def test_compute_input_hash_returns_hex() -> None:
    m = _make_manifest()
    h = compute_input_hash(m)
    assert len(h) == 64


def test_compute_input_hash_deterministic() -> None:
    m = _make_manifest()
    assert compute_input_hash(m) == compute_input_hash(m)


def test_compute_input_hash_changes_with_source_hash() -> None:
    h1 = compute_input_hash(_make_manifest(source_hash="a" * 64))
    h2 = compute_input_hash(_make_manifest(source_hash="b" * 64))
    assert h1 != h2


def test_compute_input_hash_changes_with_env_hash() -> None:
    h1 = compute_input_hash(_make_manifest(env_hash="x" * 64))
    h2 = compute_input_hash(_make_manifest(env_hash="y" * 64))
    assert h1 != h2


def test_compute_input_hash_changes_with_step_kind() -> None:
    h1 = compute_input_hash(_make_manifest(step_kind="kernel.build"))
    h2 = compute_input_hash(_make_manifest(step_kind="package.build"))
    assert h1 != h2


def test_input_manifest_to_dict() -> None:
    m = _make_manifest()
    d = m.to_dict()
    assert d["step_kind"] == "package.build"
    assert "source_hash" in d


# ---------------------------------------------------------------------------
# make_repro_record & verify_repro
# ---------------------------------------------------------------------------


def test_make_repro_record_captures_hashes() -> None:
    m = _make_manifest()
    output_sha256 = "f" * 64
    rec = make_repro_record(m, output_sha256)
    assert rec.input_hash == compute_input_hash(m)
    assert rec.output_sha256 == output_sha256
    assert rec.env_hash == m.env_hash
    assert rec.source_hash == m.source_hash
    assert rec.config_hash == m.config_hash
    assert rec.step_kind == "package.build"
    assert rec.verified is False


def test_verify_repro_true_when_same_output() -> None:
    m = _make_manifest()
    sha = "d" * 64
    rec = make_repro_record(m, sha)
    assert verify_repro(rec, sha) is True


def test_verify_repro_false_when_different_output() -> None:
    m = _make_manifest()
    rec = make_repro_record(m, "d" * 64)
    assert verify_repro(rec, "e" * 64) is False


def test_repro_record_roundtrip_via_dict() -> None:
    m = _make_manifest()
    rec = make_repro_record(m, "f" * 64)
    d = rec.to_dict()
    restored = repro_record_from_dict(d)
    assert restored.input_hash == rec.input_hash
    assert restored.output_sha256 == rec.output_sha256
    assert restored.step_kind == rec.step_kind


# ---------------------------------------------------------------------------
# ingest_blob integration: input_hash & repro_record stored
# ---------------------------------------------------------------------------


def test_ingest_blob_stores_input_hash(
    tmp_path: Path, db_url: str, store_root: Path
) -> None:
    data = b"test-data-for-repro"
    m = _make_manifest()
    ih = compute_input_hash(m)
    art = ingest_blob(
        data=data,
        store_root=store_root,
        store_key="test/repro/v1",
        kind="test",
        name="repro-test",
        db_url=db_url,
        input_hash=ih,
    )
    assert art.input_hash == ih


def test_ingest_blob_stores_repro_record_in_metadata(
    tmp_path: Path, db_url: str, store_root: Path
) -> None:
    data = b"artifact-with-repro"
    m = _make_manifest()
    rec = make_repro_record(m, hashlib.sha256(data).hexdigest())
    art = ingest_blob(
        data=data,
        store_root=store_root,
        store_key="test/repro/v2",
        kind="test",
        name="repro-full",
        db_url=db_url,
        input_hash=rec.input_hash,
        repro_record=rec,
    )
    assert art.metadata_json is not None
    assert "repro" in art.metadata_json
    stored = art.metadata_json["repro"]
    assert stored["input_hash"] == rec.input_hash
    assert stored["output_sha256"] == rec.output_sha256


def test_ingest_blob_no_repro_has_no_metadata(
    tmp_path: Path, db_url: str, store_root: Path
) -> None:
    """Without repro params, metadata_json should be None."""
    art = ingest_blob(
        data=b"plain-data",
        store_root=store_root,
        store_key="test/plain/v1",
        kind="test",
        name="plain",
        db_url=db_url,
    )
    assert art.metadata_json is None
    assert art.input_hash is None


def test_ingest_blob_input_hash_indexed(
    tmp_path: Path, db_url: str, store_root: Path
) -> None:
    """Two artifacts with the same input_hash can be looked up by it."""
    from sqlalchemy import select as sa_select

    from osfabricum.db.models import Artifact
    from osfabricum.db.session import sync_session

    ih = "x" * 64
    ingest_blob(
        data=b"blob-a",
        store_root=store_root,
        store_key="test/indexed/a",
        kind="test",
        name="a",
        db_url=db_url,
        input_hash=ih,
    )
    ingest_blob(
        data=b"blob-b",
        store_root=store_root,
        store_key="test/indexed/b",
        kind="test",
        name="b",
        db_url=db_url,
        input_hash=ih,
    )
    with sync_session(db_url) as session:
        rows = session.scalars(
            sa_select(Artifact).where(Artifact.input_hash == ih)
        ).all()
    assert len(rows) == 2
