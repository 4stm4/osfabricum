"""Tests for M9: .ofpkg Package Format (build, verify, install, CLI)."""

from __future__ import annotations

import hashlib
import io
import json
import tarfile
import zipfile
from pathlib import Path

import pytest

from osfabricum.packaging.builder import (
    REQUIRED_MEMBERS,
    build_ofpkg,
)
from osfabricum.packaging.installer import install_ofpkg, verify_ofpkg

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def destdir(tmp_path: Path) -> Path:
    """Minimal staging root with a single binary."""
    d = tmp_path / "destdir"
    (d / "usr" / "bin").mkdir(parents=True)
    (d / "usr" / "bin" / "nanodhcp").write_bytes(b"\x7fELF fake binary")
    (d / "usr" / "share" / "doc" / "nanodhcp").mkdir(parents=True)
    (d / "usr" / "share" / "doc" / "nanodhcp" / "README").write_text("minimal DHCP client\n")
    return d


@pytest.fixture()
def pkg_path(tmp_path: Path, destdir: Path) -> Path:
    """A valid .ofpkg built from the minimal destdir fixture."""
    return build_ofpkg(
        name="nanodhcp",
        version="1.0.0",
        arch="aarch64",
        destdir=destdir,
        output_dir=tmp_path / "pkgs",
        description="Minimal DHCP client",
        license_spdx="GPL-2.0-only",
    )


# ---------------------------------------------------------------------------
# build_ofpkg — structure
# ---------------------------------------------------------------------------


def test_build_ofpkg_returns_path(tmp_path: Path, destdir: Path) -> None:
    result = build_ofpkg(
        name="pkg", version="1.0", arch="x86_64", destdir=destdir, output_dir=tmp_path
    )
    assert isinstance(result, Path)
    assert result.exists()


def test_build_ofpkg_filename_convention(tmp_path: Path, destdir: Path) -> None:
    path = build_ofpkg(
        name="mypkg", version="2.3.4", arch="armv7", destdir=destdir, output_dir=tmp_path
    )
    assert path.name == "mypkg-2.3.4-armv7.ofpkg"


def test_build_ofpkg_is_valid_zip(pkg_path: Path) -> None:
    assert zipfile.is_zipfile(pkg_path)


def test_build_ofpkg_contains_required_members(pkg_path: Path) -> None:
    with zipfile.ZipFile(pkg_path) as zf:
        members = set(zf.namelist())
    for required in REQUIRED_MEMBERS:
        assert required in members, f"missing member: {required}"


def test_build_ofpkg_manifest_json_valid(pkg_path: Path) -> None:
    with zipfile.ZipFile(pkg_path) as zf:
        manifest = json.loads(zf.read("manifest.json"))
    assert manifest["name"] == "nanodhcp"
    assert manifest["version"] == "1.0.0"
    assert manifest["arch"] == "aarch64"
    assert manifest["format_version"] == "1"
    assert manifest["license"] == "GPL-2.0-only"
    assert manifest["description"] == "Minimal DHCP client"


def test_build_ofpkg_sbom_json_cyclonedx(pkg_path: Path) -> None:
    with zipfile.ZipFile(pkg_path) as zf:
        sbom = json.loads(zf.read("sbom.json"))
    assert sbom["bomFormat"] == "CycloneDX"
    assert "specVersion" in sbom
    assert isinstance(sbom["components"], list)
    assert len(sbom["components"]) >= 1


def test_build_ofpkg_checksums_sha256_format(pkg_path: Path) -> None:
    with zipfile.ZipFile(pkg_path) as zf:
        raw = zf.read("checksums.sha256").decode()
    lines = [ln for ln in raw.splitlines() if ln.strip()]
    assert len(lines) == 3  # manifest.json, files.tar.gz, sbom.json
    for line in lines:
        parts = line.split(None, 1)
        assert len(parts) == 2  # noqa: PLR2004
        sha_hex, _filename = parts
        assert len(sha_hex) == 64  # sha256 hex
        int(sha_hex, 16)  # valid hex


def test_build_ofpkg_files_tar_gz_valid(pkg_path: Path) -> None:
    with zipfile.ZipFile(pkg_path) as zf:
        tar_bytes = zf.read("files.tar.gz")
    buf = io.BytesIO(tar_bytes)
    with tarfile.open(fileobj=buf, mode="r:gz") as tar:
        names = tar.getnames()
    # Should contain the files from destdir (relative paths, no leading /)
    assert any("nanodhcp" in n for n in names)
    assert not any(n.startswith("/") for n in names)


def test_build_ofpkg_files_tar_gz_correct_checksums(pkg_path: Path) -> None:
    with zipfile.ZipFile(pkg_path) as zf:
        checksums_raw = zf.read("checksums.sha256").decode()
        tar_bytes = zf.read("files.tar.gz")

    expected_hex = None
    for line in checksums_raw.splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2 and parts[1] == "files.tar.gz":  # noqa: PLR2004
            expected_hex = parts[0]
    assert expected_hex is not None
    actual_hex = hashlib.sha256(tar_bytes).hexdigest()
    assert actual_hex == expected_hex


def test_build_ofpkg_creates_output_dir(tmp_path: Path, destdir: Path) -> None:
    nested = tmp_path / "a" / "b" / "c"
    path = build_ofpkg(name="x", version="1", arch="x86_64", destdir=destdir, output_dir=nested)
    assert path.exists()


def test_build_ofpkg_optional_fields_stored(tmp_path: Path, destdir: Path) -> None:
    path = build_ofpkg(
        name="x",
        version="1",
        arch="x86_64",
        destdir=destdir,
        output_dir=tmp_path,
        build_system="make",
        source_hash="a" * 64,
        recipe_hash="b" * 64,
    )
    with zipfile.ZipFile(path) as zf:
        manifest = json.loads(zf.read("manifest.json"))
    assert manifest["build_system"] == "make"
    assert manifest["source_hash"] == "a" * 64
    assert manifest["recipe_hash"] == "b" * 64


def test_build_ofpkg_empty_destdir(tmp_path: Path) -> None:
    empty = tmp_path / "empty_stage"
    empty.mkdir()
    path = build_ofpkg(
        name="empty", version="0.1", arch="x86_64", destdir=empty, output_dir=tmp_path
    )
    assert path.exists()
    # Empty tar.gz is still a valid archive
    with zipfile.ZipFile(path) as zf:
        tar_bytes = zf.read("files.tar.gz")
    buf = io.BytesIO(tar_bytes)
    with tarfile.open(fileobj=buf, mode="r:gz") as tar:
        assert tar.getmembers() == []


# ---------------------------------------------------------------------------
# verify_ofpkg — happy path
# ---------------------------------------------------------------------------


def test_verify_ofpkg_returns_manifest(pkg_path: Path) -> None:
    manifest = verify_ofpkg(pkg_path)
    assert isinstance(manifest, dict)
    assert manifest["name"] == "nanodhcp"


def test_verify_ofpkg_passes_valid_package(pkg_path: Path) -> None:
    # Must not raise
    verify_ofpkg(pkg_path)


# ---------------------------------------------------------------------------
# verify_ofpkg — tamper detection
# ---------------------------------------------------------------------------


def _tamper_member(pkg_path: Path, member: str, new_content: bytes) -> Path:
    """Return a new .ofpkg path with *member* replaced by *new_content*."""
    tampered = pkg_path.parent / f"tampered-{pkg_path.name}"
    with (
        zipfile.ZipFile(pkg_path, "r") as src,
        zipfile.ZipFile(tampered, "w", compression=zipfile.ZIP_STORED) as dst,
    ):
        for item in src.infolist():
            if item.filename == member:
                dst.writestr(item, new_content)
            else:
                dst.writestr(item, src.read(item.filename))
    return tampered


def test_verify_rejects_tampered_files_tar_gz(pkg_path: Path) -> None:
    tampered = _tamper_member(pkg_path, "files.tar.gz", b"CORRUPTED")
    with pytest.raises(ValueError, match="checksum mismatch"):
        verify_ofpkg(tampered)


def test_verify_rejects_tampered_manifest(pkg_path: Path) -> None:
    with zipfile.ZipFile(pkg_path) as zf:
        original = json.loads(zf.read("manifest.json"))
    original["name"] = "HACKED"
    tampered = _tamper_member(pkg_path, "manifest.json", json.dumps(original).encode())
    with pytest.raises(ValueError, match="checksum mismatch"):
        verify_ofpkg(tampered)


def test_verify_rejects_tampered_sbom(pkg_path: Path) -> None:
    tampered = _tamper_member(pkg_path, "sbom.json", b'{"bomFormat":"EVIL"}')
    with pytest.raises(ValueError, match="checksum mismatch"):
        verify_ofpkg(tampered)


def test_verify_rejects_missing_member(tmp_path: Path, destdir: Path) -> None:
    # Build a package missing files.tar.gz
    output_path = tmp_path / "incomplete.ofpkg"
    with zipfile.ZipFile(output_path, "w") as zf:
        zf.writestr("manifest.json", b"{}")
        zf.writestr("checksums.sha256", b"")
        zf.writestr("sbom.json", b"{}")
        # intentionally omit files.tar.gz
    with pytest.raises(ValueError, match="missing required member"):
        verify_ofpkg(output_path)


def test_verify_rejects_nonexistent_file(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="package not found"):
        verify_ofpkg(tmp_path / "ghost.ofpkg")


def test_verify_rejects_invalid_format_version(tmp_path: Path, destdir: Path) -> None:
    path = build_ofpkg(name="x", version="1", arch="x86_64", destdir=destdir, output_dir=tmp_path)
    # Rebuild with wrong format_version bypassing checksums
    with zipfile.ZipFile(path) as zf:
        manifest = json.loads(zf.read("manifest.json"))
    manifest["format_version"] = "99"
    tampered = _tamper_member(path, "manifest.json", json.dumps(manifest).encode())
    with pytest.raises(ValueError):
        verify_ofpkg(tampered)


def test_verify_rejects_missing_manifest_fields(tmp_path: Path) -> None:
    # Build a valid package then strip a required field
    from osfabricum.packaging.builder import _make_checksums, _make_sbom, _pack_destdir

    d = tmp_path / "d"
    d.mkdir()
    tar_bytes = _pack_destdir(d)
    sbom = _make_sbom("x", "1", "x86_64")
    sbom_bytes = json.dumps(sbom).encode()
    manifest = {"format_version": "1", "name": "x", "version": "1"}  # missing arch
    manifest_bytes = json.dumps(manifest).encode()
    checksums_bytes = _make_checksums(
        manifest_bytes=manifest_bytes,
        files_tar_bytes=tar_bytes,
        sbom_bytes=sbom_bytes,
    )
    out = tmp_path / "bad.ofpkg"
    with zipfile.ZipFile(out, "w") as zf:
        zf.writestr("manifest.json", manifest_bytes)
        zf.writestr("files.tar.gz", tar_bytes)
        zf.writestr("checksums.sha256", checksums_bytes)
        zf.writestr("sbom.json", sbom_bytes)
    with pytest.raises(ValueError, match="missing or empty required field"):
        verify_ofpkg(out)


def test_verify_rejects_invalid_sbom(tmp_path: Path) -> None:
    from osfabricum.packaging.builder import _make_checksums, _pack_destdir

    d = tmp_path / "d"
    d.mkdir()
    tar_bytes = _pack_destdir(d)
    manifest = {
        "format_version": "1",
        "name": "x",
        "version": "1",
        "arch": "x86_64",
    }
    manifest_bytes = json.dumps(manifest).encode()
    bad_sbom = {"bomFormat": "NotCycloneDX"}
    sbom_bytes = json.dumps(bad_sbom).encode()
    checksums_bytes = _make_checksums(
        manifest_bytes=manifest_bytes,
        files_tar_bytes=tar_bytes,
        sbom_bytes=sbom_bytes,
    )
    out = tmp_path / "bad_sbom.ofpkg"
    with zipfile.ZipFile(out, "w") as zf:
        zf.writestr("manifest.json", manifest_bytes)
        zf.writestr("files.tar.gz", tar_bytes)
        zf.writestr("checksums.sha256", checksums_bytes)
        zf.writestr("sbom.json", sbom_bytes)
    with pytest.raises(ValueError, match="bomFormat must be 'CycloneDX'"):
        verify_ofpkg(out)


# ---------------------------------------------------------------------------
# install_ofpkg
# ---------------------------------------------------------------------------


def test_install_ofpkg_extracts_files(tmp_path: Path, pkg_path: Path) -> None:
    prefix = tmp_path / "root"
    install_ofpkg(pkg_path, prefix)
    installed = prefix / "usr" / "bin" / "nanodhcp"
    assert installed.exists()
    assert installed.read_bytes() == b"\x7fELF fake binary"


def test_install_ofpkg_creates_prefix(tmp_path: Path, pkg_path: Path) -> None:
    prefix = tmp_path / "new" / "prefix"
    assert not prefix.exists()
    install_ofpkg(pkg_path, prefix)
    assert prefix.exists()


def test_install_ofpkg_rejects_tampered_package(tmp_path: Path, pkg_path: Path) -> None:
    tampered = _tamper_member(pkg_path, "files.tar.gz", b"BAD DATA")
    prefix = tmp_path / "root"
    with pytest.raises(ValueError, match="checksum mismatch"):
        install_ofpkg(tampered, prefix)
    # prefix must not be created with partial data
    assert not (prefix / "usr").exists()


# ---------------------------------------------------------------------------
# CLI — package build
# ---------------------------------------------------------------------------


def test_cli_package_build_produces_ofpkg(tmp_path: Path, destdir: Path) -> None:
    from typer.testing import CliRunner

    from apps.cli.main import app

    runner = CliRunner()
    out_dir = tmp_path / "out"
    result = runner.invoke(
        app,
        [
            "package",
            "build",
            "nanodhcp",
            "--version",
            "1.0.0",
            "--arch",
            "aarch64",
            "--destdir",
            str(destdir),
            "--output-dir",
            str(out_dir),
        ],
    )
    assert result.exit_code == 0, result.output
    pkg = out_dir / "nanodhcp-1.0.0-aarch64.ofpkg"
    assert pkg.exists()
    assert str(pkg) in result.output


def test_cli_package_verify_valid(tmp_path: Path, pkg_path: Path) -> None:
    from typer.testing import CliRunner

    from apps.cli.main import app

    runner = CliRunner()
    result = runner.invoke(app, ["package", "verify", str(pkg_path)])
    assert result.exit_code == 0, result.output
    combined = result.output.lower() + (result.stderr or "").lower()
    assert "ok" in combined or "valid" in combined


def test_cli_package_verify_tampered(tmp_path: Path, pkg_path: Path) -> None:
    from typer.testing import CliRunner

    from apps.cli.main import app

    runner = CliRunner()
    tampered = _tamper_member(pkg_path, "files.tar.gz", b"CORRUPTED")
    result = runner.invoke(app, ["package", "verify", str(tampered)])
    assert result.exit_code != 0
    combined = result.output.lower() + (result.stderr or "").lower()
    assert "checksum" in combined or "failed" in combined


def test_cli_package_build_missing_required_options(tmp_path: Path, destdir: Path) -> None:
    from typer.testing import CliRunner

    from apps.cli.main import app

    runner = CliRunner()
    # Missing --version, --arch, --destdir → exit non-zero
    result = runner.invoke(app, ["package", "build", "nanodhcp"])
    assert result.exit_code != 0
