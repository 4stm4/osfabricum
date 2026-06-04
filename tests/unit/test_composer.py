"""Tests for M16: RootFS Composer."""

from __future__ import annotations

import io
import json
import tarfile
import zipfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

from apps.cli.main import app
from osfabricum.composer.packages import install_package_into_rootfs
from osfabricum.composer.rootfs import RootfsComposeSpec, compose_rootfs
from osfabricum.composer.services import install_service_into_rootfs, install_services_into_rootfs
from osfabricum.db.engine import make_sync_engine
from osfabricum.db.models import Artifact, Base
from osfabricum.db.session import sync_session
from osfabricum.rootfs.builder import RootfsSpec, build_base_rootfs
from osfabricum.store.ingest import ingest_blob
from osfabricum.store.layout import blob_path

runner = CliRunner()

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


@pytest.fixture()
def base_rootfs_artifact(db_url: str, store_root: Path) -> Artifact:
    """Build and return a base rootfs artifact."""
    spec = RootfsSpec(
        arch="aarch64",
        distribution="tinywifi",
        profile="default",
        board="rpi-zero-2w",
        init_system="busybox",
    )
    result = build_base_rootfs(spec, store_root=store_root, db_url=db_url)
    assert result.success
    from sqlalchemy import select as sa_select

    with sync_session(db_url) as session:
        art = session.scalar(sa_select(Artifact).where(Artifact.id == result.artifact_id))
    return art


def _make_ofpkg(name: str, version: str, arch: str, files: dict[str, bytes]) -> bytes:
    """Build a minimal in-memory .ofpkg ZIP."""
    manifest = {
        "name": name,
        "version": version,
        "arch": arch,
        "description": f"Test package {name}",
        "license": "MIT",
    }
    # Build files.tar.gz
    tar_buf = io.BytesIO()
    with tarfile.open(fileobj=tar_buf, mode="w:gz") as tar:
        for rel_path, content in files.items():
            info = tarfile.TarInfo(name=rel_path)
            info.size = len(content)
            info.mtime = 0
            info.uid = 0
            info.gid = 0
            tar.addfile(info, io.BytesIO(content))
    files_tar = tar_buf.getvalue()

    # Build checksums
    import hashlib

    manifest_bytes = json.dumps(manifest, sort_keys=True).encode()
    sbom_bytes = json.dumps({"bomFormat": "CycloneDX"}).encode()
    checksums = (
        f"{hashlib.sha256(manifest_bytes).hexdigest()}  manifest.json\n"
        f"{hashlib.sha256(files_tar).hexdigest()}  files.tar.gz\n"
        f"{hashlib.sha256(sbom_bytes).hexdigest()}  sbom.json\n"
    ).encode()

    # Pack into ZIP
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", manifest_bytes)
        zf.writestr("files.tar.gz", files_tar)
        zf.writestr("checksums.sha256", checksums)
        zf.writestr("sbom.json", sbom_bytes)
    return buf.getvalue()


@pytest.fixture()
def package_artifact(db_url: str, store_root: Path) -> Artifact:
    """Ingest a minimal .ofpkg artifact and return it."""
    ofpkg_data = _make_ofpkg(
        name="nanodhcp",
        version="0.1.0",
        arch="aarch64",
        files={
            "usr/bin/nanodhcp": b"#!/bin/sh\necho nanodhcp\n",
            "etc/nanodhcp.conf": b"# nanodhcp config\n",
        },
    )
    return ingest_blob(
        data=ofpkg_data,
        store_root=store_root,
        store_key="packages/nanodhcp/0.1.0/aarch64",
        kind="package",
        name="nanodhcp",
        version="0.1.0",
        arch="aarch64",
        media_type="application/zip",
        db_url=db_url,
    )


# ---------------------------------------------------------------------------
# install_package_into_rootfs
# ---------------------------------------------------------------------------


def test_install_package_extracts_files(
    tmp_path: Path, db_url: str, store_root: Path, package_artifact: Artifact
) -> None:
    stage = tmp_path / "rootfs"
    stage.mkdir()
    manifest = install_package_into_rootfs(package_artifact.id, stage, store_root, db_url=db_url)
    assert manifest["name"] == "nanodhcp"
    assert (stage / "usr" / "bin" / "nanodhcp").exists()
    assert (stage / "etc" / "nanodhcp.conf").exists()


def test_install_package_writes_pkg_record(
    tmp_path: Path, db_url: str, store_root: Path, package_artifact: Artifact
) -> None:
    stage = tmp_path / "rootfs"
    stage.mkdir()
    install_package_into_rootfs(package_artifact.id, stage, store_root, db_url=db_url)
    pkg_db = stage / "var" / "lib" / "osfabricum" / "installed"
    records = list(pkg_db.glob("*.json"))
    assert len(records) == 1
    data = json.loads(records[0].read_text())
    assert data["name"] == "nanodhcp"


def test_install_package_unknown_artifact_raises(
    tmp_path: Path, db_url: str, store_root: Path
) -> None:
    stage = tmp_path / "rootfs"
    stage.mkdir()
    with pytest.raises(ValueError, match="artifact not found"):
        install_package_into_rootfs(
            "00000000-0000-0000-0000-000000000000", stage, store_root, db_url=db_url
        )


def test_install_package_checksum_tamper_raises(
    tmp_path: Path, db_url: str, store_root: Path
) -> None:
    """A tampered .ofpkg (wrong checksums) should raise ValueError."""
    # Build a valid .ofpkg then corrupt the blob
    ofpkg_data = _make_ofpkg("bad", "1.0", "aarch64", {"usr/bin/bad": b"bad"})
    art = ingest_blob(
        data=ofpkg_data,
        store_root=store_root,
        store_key="packages/bad/1.0/aarch64",
        kind="package",
        name="bad",
        version="1.0",
        media_type="application/zip",
        db_url=db_url,
    )
    # Corrupt the blob on disk
    bp = blob_path(store_root, art.blob_sha256)
    bp.write_bytes(b"corrupted ZIP data")

    stage = tmp_path / "rootfs"
    stage.mkdir()
    with pytest.raises((ValueError, zipfile.BadZipFile)):
        install_package_into_rootfs(art.id, stage, store_root, db_url=db_url)


# ---------------------------------------------------------------------------
# install_service_into_rootfs
# ---------------------------------------------------------------------------


def test_install_busybox_service_creates_initd(tmp_path: Path) -> None:
    (tmp_path / "etc" / "init.d").mkdir(parents=True)
    paths = install_service_into_rootfs(
        "myservice", tmp_path, tmp_path / "store", init_system="busybox"
    )
    assert len(paths) == 1
    script = tmp_path / paths[0]
    assert script.exists()
    assert script.stat().st_mode & 0o100  # executable


def test_install_busybox_service_script_has_start_stop(tmp_path: Path) -> None:
    (tmp_path / "etc" / "init.d").mkdir(parents=True)
    paths = install_service_into_rootfs(
        "myservice", tmp_path, tmp_path / "store", init_system="busybox"
    )
    content = (tmp_path / paths[0]).read_text()
    assert "start" in content
    assert "stop" in content


def test_install_systemd_service_creates_unit(tmp_path: Path) -> None:
    paths = install_service_into_rootfs(
        "myservice", tmp_path, tmp_path / "store", init_system="systemd"
    )
    unit_path = tmp_path / "etc" / "systemd" / "system" / "myservice.service"
    assert unit_path.exists()
    assert any("myservice.service" in p for p in paths)


def test_install_systemd_service_creates_wants_symlink(tmp_path: Path) -> None:
    install_service_into_rootfs(
        "myservice", tmp_path, tmp_path / "store", init_system="systemd", enabled=True
    )
    wants = (
        tmp_path / "etc" / "systemd" / "system" / "multi-user.target.wants" / "myservice.service"
    )
    assert wants.is_symlink()


def test_install_services_multiple(tmp_path: Path) -> None:
    (tmp_path / "etc" / "init.d").mkdir(parents=True)
    result = install_services_into_rootfs(
        ["svc-a", "svc-b"], tmp_path, tmp_path / "store", init_system="busybox"
    )
    assert "svc-a" in result
    assert "svc-b" in result


def test_install_service_unknown_init_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown init_system"):
        install_service_into_rootfs("x", tmp_path, tmp_path / "store", init_system="openrc")


# ---------------------------------------------------------------------------
# compose_rootfs — integration
# ---------------------------------------------------------------------------


def _make_spec(base_artifact_id: str, **kwargs) -> RootfsComposeSpec:
    return RootfsComposeSpec(
        distribution="tinywifi",
        profile="default",
        board="rpi-zero-2w",
        arch="aarch64",
        base_artifact_id=base_artifact_id,
        **kwargs,
    )


def test_compose_rootfs_base_only(
    db_url: str, store_root: Path, base_rootfs_artifact: Artifact
) -> None:
    spec = _make_spec(base_rootfs_artifact.id)
    result = compose_rootfs(spec, store_root=store_root, db_url=db_url)
    assert result.success is True
    assert result.artifact_id is not None
    assert result.error is None


def test_compose_rootfs_artifact_kind(
    db_url: str, store_root: Path, base_rootfs_artifact: Artifact
) -> None:
    spec = _make_spec(base_rootfs_artifact.id)
    result = compose_rootfs(spec, store_root=store_root, db_url=db_url)
    from sqlalchemy import select as sa_select

    with sync_session(db_url) as session:
        art = session.scalar(sa_select(Artifact).where(Artifact.id == result.artifact_id))
    assert art.kind == "rootfs"
    assert art.arch == "aarch64"


def test_compose_rootfs_has_repro_chain(
    db_url: str, store_root: Path, base_rootfs_artifact: Artifact
) -> None:
    spec = _make_spec(base_rootfs_artifact.id)
    result = compose_rootfs(spec, store_root=store_root, db_url=db_url)
    from sqlalchemy import select as sa_select

    with sync_session(db_url) as session:
        art = session.scalar(sa_select(Artifact).where(Artifact.id == result.artifact_id))
    assert art.input_hash is not None
    assert art.metadata_json is not None
    assert art.metadata_json["repro"]["step_kind"] == "rootfs.compose"


def test_compose_rootfs_with_package(
    db_url: str, store_root: Path, base_rootfs_artifact: Artifact, package_artifact: Artifact
) -> None:
    spec = _make_spec(
        base_rootfs_artifact.id,
        package_artifact_ids=[package_artifact.id],
    )
    result = compose_rootfs(spec, store_root=store_root, db_url=db_url)
    assert result.success is True
    assert len(result.installed_packages) == 1
    assert "nanodhcp" in result.installed_packages[0]


def test_compose_rootfs_package_present_in_tar(
    db_url: str, store_root: Path, base_rootfs_artifact: Artifact, package_artifact: Artifact
) -> None:
    """nanodhcp binary should be inside the composed rootfs tar."""
    spec = _make_spec(
        base_rootfs_artifact.id,
        package_artifact_ids=[package_artifact.id],
    )
    result = compose_rootfs(spec, store_root=store_root, db_url=db_url)
    from sqlalchemy import select as sa_select

    with sync_session(db_url) as session:
        art = session.scalar(sa_select(Artifact).where(Artifact.id == result.artifact_id))
    bp = blob_path(store_root, art.blob_sha256)
    with tarfile.open(str(bp), mode="r:gz") as tar:
        names = tar.getnames()
    assert "usr/bin/nanodhcp" in names


def test_compose_rootfs_with_service(
    db_url: str, store_root: Path, base_rootfs_artifact: Artifact
) -> None:
    spec = _make_spec(
        base_rootfs_artifact.id,
        service_names=["nanodhcp"],
        init_system="busybox",
    )
    result = compose_rootfs(spec, store_root=store_root, db_url=db_url)
    assert result.success is True
    assert "nanodhcp" in result.installed_services


def test_compose_rootfs_service_in_tar(
    db_url: str, store_root: Path, base_rootfs_artifact: Artifact
) -> None:
    spec = _make_spec(
        base_rootfs_artifact.id,
        service_names=["nanodhcp"],
        init_system="busybox",
    )
    result = compose_rootfs(spec, store_root=store_root, db_url=db_url)
    from sqlalchemy import select as sa_select

    with sync_session(db_url) as session:
        art = session.scalar(sa_select(Artifact).where(Artifact.id == result.artifact_id))
    bp = blob_path(store_root, art.blob_sha256)
    with tarfile.open(str(bp), mode="r:gz") as tar:
        names = tar.getnames()
    assert any("nanodhcp" in n for n in names)


def test_compose_rootfs_invalid_base_fails(db_url: str, store_root: Path) -> None:
    spec = _make_spec("00000000-0000-0000-0000-000000000000")
    result = compose_rootfs(spec, store_root=store_root, db_url=db_url)
    assert result.success is False
    assert result.error is not None


def test_compose_rootfs_idempotent(
    db_url: str, store_root: Path, base_rootfs_artifact: Artifact
) -> None:
    spec = _make_spec(base_rootfs_artifact.id)
    r1 = compose_rootfs(spec, store_root=store_root, db_url=db_url)
    r2 = compose_rootfs(spec, store_root=store_root, db_url=db_url)
    assert r1.artifact_id == r2.artifact_id


def test_compose_rootfs_logs(db_url: str, store_root: Path, base_rootfs_artifact: Artifact) -> None:
    spec = _make_spec(base_rootfs_artifact.id)
    result = compose_rootfs(spec, store_root=store_root, db_url=db_url)
    assert any("[compose]" in line for line in result.logs)


# ---------------------------------------------------------------------------
# CLI compose rootfs
# ---------------------------------------------------------------------------


def test_cli_compose_rootfs(db_url: str, store_root: Path, base_rootfs_artifact: Artifact) -> None:
    result = runner.invoke(
        app,
        [
            "compose",
            "rootfs",
            "tinywifi/default",
            "--board",
            "rpi-zero-2w",
            "--arch",
            "aarch64",
            "--base",
            base_rootfs_artifact.id,
            "--store-root",
            str(store_root),
            "--db-url",
            db_url,
        ],
    )
    assert result.exit_code == 0, result.output
    assert "artifact" in result.output


def test_cli_compose_rootfs_bad_target(
    db_url: str, store_root: Path, base_rootfs_artifact: Artifact
) -> None:
    result = runner.invoke(
        app,
        [
            "compose",
            "rootfs",
            "noslash",
            "--board",
            "rpi-zero-2w",
            "--arch",
            "aarch64",
            "--base",
            base_rootfs_artifact.id,
            "--store-root",
            str(store_root),
            "--db-url",
            db_url,
        ],
    )
    assert result.exit_code != 0
