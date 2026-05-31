"""Tests for the M3 artifact store (ingest, verify, CLI commands)."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from apps.cli.main import app
from osfabricum.db.engine import make_sync_engine
from osfabricum.db.models import Base
from osfabricum.store.ingest import ingest_blob
from osfabricum.store.layout import blob_path, compute_sha256
from osfabricum.store.verify import verify_store

runner = CliRunner()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def store_root(tmp_path: Path) -> Path:
    return tmp_path / "store"


@pytest.fixture()
def db_url(tmp_path: Path) -> str:
    db_file = tmp_path / "test.db"
    url = f"sqlite:///{db_file}"
    engine = make_sync_engine(url)
    Base.metadata.create_all(engine)
    engine.dispose()
    return url


# ---------------------------------------------------------------------------
# layout helpers
# ---------------------------------------------------------------------------


def test_blob_path_structure(tmp_path: Path) -> None:
    sha = "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890"
    p = blob_path(tmp_path, sha)
    assert p.parts[-4] == "sha256"
    assert p.parts[-3] == sha[:2]
    assert p.parts[-2] == sha[2:4]
    assert p.name == sha


def test_compute_sha256() -> None:
    data = b"hello"
    digest = compute_sha256(data)
    import hashlib

    assert digest == hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# ingest_blob
# ---------------------------------------------------------------------------


def test_ingest_creates_blob_file(store_root: Path, db_url: str) -> None:
    data = b"binary payload"
    art = ingest_blob(
        data,
        store_root,
        "packages/foo/1.0/x86_64/foo.ofpkg",
        "package",
        "foo",
        version="1.0",
        arch="x86_64",
        db_url=db_url,
    )
    sha = compute_sha256(data)
    assert blob_path(store_root, sha).exists()
    assert art.blob_sha256 == sha
    assert art.size_bytes == len(data)


def test_ingest_creates_ref_symlink(store_root: Path, db_url: str) -> None:
    data = b"some content"
    key = "packages/bar/2.0/aarch64/bar.ofpkg"
    ingest_blob(data, store_root, key, "package", "bar", db_url=db_url)
    ref = store_root / "refs" / key
    assert ref.is_symlink()
    assert ref.read_bytes() == data


def test_ingest_sha256_mismatch_rejected(store_root: Path, db_url: str) -> None:
    with pytest.raises(ValueError, match="sha256 mismatch"):
        ingest_blob(
            b"real data",
            store_root,
            "packages/x/1.0/x86_64/x.ofpkg",
            "package",
            "x",
            expected_sha256="0" * 64,
            db_url=db_url,
        )
    assert not (store_root / "blobs").exists()


def test_ingest_expected_sha256_matches(store_root: Path, db_url: str) -> None:
    data = b"verified content"
    sha = compute_sha256(data)
    art = ingest_blob(
        data,
        store_root,
        "packages/v/1.0/x86_64/v.ofpkg",
        "package",
        "v",
        expected_sha256=sha,
        db_url=db_url,
    )
    assert art.blob_sha256 == sha


def test_ingest_deduplication(store_root: Path, db_url: str) -> None:
    """Same blob ingested twice → one blob file, two separate refs."""
    data = b"shared content"
    sha = compute_sha256(data)

    ingest_blob(data, store_root, "refs/a", "package", "a", db_url=db_url)
    ingest_blob(data, store_root, "refs/b", "package", "b", db_url=db_url)

    dest = blob_path(store_root, sha)
    assert dest.exists()
    ref_a = store_root / "refs" / "refs" / "a"
    ref_b = store_root / "refs" / "refs" / "b"
    assert ref_a.is_symlink()
    assert ref_b.is_symlink()


def test_ingest_idempotent_same_store_key(store_root: Path, db_url: str) -> None:
    data = b"idempotent"
    art1 = ingest_blob(
        data, store_root, "packages/dup/1.0/x86_64/dup.ofpkg", "package", "dup", db_url=db_url
    )
    art2 = ingest_blob(
        data, store_root, "packages/dup/1.0/x86_64/dup.ofpkg", "package", "dup", db_url=db_url
    )
    assert art1.id == art2.id


# ---------------------------------------------------------------------------
# verify_store
# ---------------------------------------------------------------------------


def test_verify_empty_store(store_root: Path, db_url: str) -> None:
    ok, errors = verify_store(store_root, db_url)
    assert ok == 0
    assert errors == []


def test_verify_after_ingest(store_root: Path, db_url: str) -> None:
    data = b"good blob"
    ingest_blob(data, store_root, "packages/ok/1.0/x86_64/ok.ofpkg", "package", "ok", db_url=db_url)
    ok, errors = verify_store(store_root, db_url)
    assert ok == 1
    assert errors == []


def test_verify_missing_blob(store_root: Path, db_url: str) -> None:
    data = b"will be deleted"
    ingest_blob(
        data, store_root, "packages/gone/1.0/x86_64/gone.ofpkg", "package", "gone", db_url=db_url
    )
    sha = compute_sha256(data)
    blob_path(store_root, sha).unlink()
    ok, errors = verify_store(store_root, db_url)
    assert ok == 0
    assert len(errors) == 1
    assert "missing" in errors[0]


def test_verify_tampered_blob(store_root: Path, db_url: str) -> None:
    data = b"original content"
    ingest_blob(
        data,
        store_root,
        "packages/tampered/1.0/x86_64/t.ofpkg",
        "package",
        "tampered",
        db_url=db_url,
    )
    sha = compute_sha256(data)
    blob_path(store_root, sha).write_bytes(b"corrupted")
    ok, errors = verify_store(store_root, db_url)
    assert ok == 0
    assert len(errors) == 1
    assert "mismatch" in errors[0]


# ---------------------------------------------------------------------------
# CLI: store verify
# ---------------------------------------------------------------------------


def test_cli_store_verify_empty(store_root: Path, db_url: str) -> None:
    result = runner.invoke(
        app,
        ["store", "verify", "--store-root", str(store_root), "--db-url", db_url],
    )
    assert result.exit_code == 0, result.output
    assert "0 blob(s)" in result.output


def test_cli_store_verify_ok(store_root: Path, db_url: str) -> None:
    ingest_blob(b"data", store_root, "packages/p/1.0/x86_64/p.ofpkg", "package", "p", db_url=db_url)
    result = runner.invoke(
        app,
        ["store", "verify", "--store-root", str(store_root), "--db-url", db_url],
    )
    assert result.exit_code == 0, result.output
    assert "1 blob(s)" in result.output


def test_cli_store_verify_tampered(store_root: Path, db_url: str) -> None:
    data = b"tamper me"
    ingest_blob(data, store_root, "packages/q/1.0/x86_64/q.ofpkg", "package", "q", db_url=db_url)
    blob_path(store_root, compute_sha256(data)).write_bytes(b"bad")
    result = runner.invoke(
        app,
        ["store", "verify", "--store-root", str(store_root), "--db-url", db_url],
    )
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# CLI: artifacts list
# ---------------------------------------------------------------------------


def test_cli_artifacts_list_empty(db_url: str) -> None:
    result = runner.invoke(app, ["artifacts", "list", "--db-url", db_url])
    assert result.exit_code == 0, result.output
    assert "Artifacts" in result.output


def test_cli_artifacts_list_shows_artifacts(store_root: Path, db_url: str) -> None:
    ingest_blob(
        b"kernel img",
        store_root,
        "kernels/linux-rpi/6.6/aarch64/Image",
        "kernel",
        "linux-rpi",
        version="6.6",
        arch="aarch64",
        db_url=db_url,
    )
    result = runner.invoke(app, ["artifacts", "list", "--db-url", db_url])
    assert result.exit_code == 0, result.output
    assert "linux-rpi" in result.output
    assert "kernel" in result.output


def test_cli_artifacts_list_filter_kind(store_root: Path, db_url: str) -> None:
    ingest_blob(
        b"pkg data",
        store_root,
        "packages/mypkg/1.0/x86_64/mypkg.ofpkg",
        "package",
        "mypkg",
        version="1.0",
        arch="x86_64",
        db_url=db_url,
    )
    ingest_blob(
        b"kernel img",
        store_root,
        "kernels/linux/6.6/x86_64/Image",
        "kernel",
        "linux",
        version="6.6",
        arch="x86_64",
        db_url=db_url,
    )

    result = runner.invoke(app, ["artifacts", "list", "--kind", "package", "--db-url", db_url])
    assert result.exit_code == 0, result.output
    assert "mypkg" in result.output
    assert "linux" not in result.output
