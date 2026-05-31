"""Build a .ofpkg archive from a DESTDIR staging root (M9).

Usage::

    from pathlib import Path
    from osfabricum.packaging.builder import build_ofpkg

    pkg_path = build_ofpkg(
        name="nanodhcp",
        version="1.0.0",
        arch="aarch64",
        destdir=Path("/tmp/stage/destdir"),
        output_dir=Path("/tmp/pkgs"),
    )
    # -> Path("/tmp/pkgs/nanodhcp-1.0.0-aarch64.ofpkg")
"""

from __future__ import annotations

import hashlib
import io
import json
import tarfile
import zipfile
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

#: Members that are always checked by the installer.
REQUIRED_MEMBERS = ("manifest.json", "files.tar.gz", "checksums.sha256", "sbom.json")

#: Manifest fields that must be present and non-empty.
MANIFEST_REQUIRED = ("format_version", "name", "version", "arch")

#: Current format version string.
FORMAT_VERSION = "1"


def build_ofpkg(
    *,
    name: str,
    version: str,
    arch: str,
    destdir: Path,
    output_dir: Path,
    description: str = "",
    license_spdx: str = "NOASSERTION",
    dependencies: list[dict[str, Any]] | None = None,
    build_system: str | None = None,
    source_hash: str | None = None,
    recipe_hash: str | None = None,
) -> Path:
    """Build an ``.ofpkg`` archive from *destdir* and write it to *output_dir*.

    Parameters
    ----------
    name:
        Package name (e.g. ``"nanodhcp"``).
    version:
        Version string (e.g. ``"1.0.0"``).
    arch:
        Target architecture (e.g. ``"aarch64"``).
    destdir:
        Staging root produced by the build recipe's install phase.  Files
        are packed relative to this root (i.e. the leading path is stripped).
    output_dir:
        Directory in which to write ``<name>-<version>-<arch>.ofpkg``.
    description:
        Human-readable description (optional).
    license_spdx:
        SPDX licence expression (optional, defaults to ``"NOASSERTION"``).
    dependencies:
        List of dependency dicts ``{"name": …, "type": …, "constraint": …}``.
    build_system:
        Build system identifier (stored in manifest for traceability).
    source_hash:
        SHA-256 of the upstream source artifact.
    recipe_hash:
        SHA-256 of the build recipe specification.

    Returns
    -------
    Path
        Absolute path of the written ``.ofpkg`` file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{name}-{version}-{arch}.ofpkg"

    # 1. Pack destdir into files.tar.gz (in memory)
    files_tar_bytes = _pack_destdir(destdir)

    # 2. Build manifest.json
    manifest: dict[str, Any] = {
        "format_version": FORMAT_VERSION,
        "name": name,
        "version": version,
        "arch": arch,
        "description": description,
        "license": license_spdx,
        "dependencies": dependencies or [],
    }
    if build_system is not None:
        manifest["build_system"] = build_system
    if source_hash is not None:
        manifest["source_hash"] = source_hash
    if recipe_hash is not None:
        manifest["recipe_hash"] = recipe_hash
    manifest_bytes = json.dumps(manifest, indent=2, sort_keys=True).encode()

    # 3. Build sbom.json (minimal CycloneDX 1.4)
    sbom = _make_sbom(name, version, arch)
    sbom_bytes = json.dumps(sbom, indent=2).encode()

    # 4. Build checksums.sha256
    checksums_bytes = _make_checksums(
        manifest_bytes=manifest_bytes,
        files_tar_bytes=files_tar_bytes,
        sbom_bytes=sbom_bytes,
    )

    # 5. Write ZIP archive
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_STORED) as zf:
        zf.writestr("manifest.json", manifest_bytes)
        zf.writestr("files.tar.gz", files_tar_bytes)
        zf.writestr("checksums.sha256", checksums_bytes)
        zf.writestr("sbom.json", sbom_bytes)

    return output_path.resolve()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _pack_destdir(destdir: Path) -> bytes:
    """Return a gzip-compressed tar of all files under *destdir*.

    Paths inside the archive are relative to *destdir* (leading path stripped).
    An empty ``destdir`` produces a valid (but empty) tar.gz.
    """
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        if destdir.exists():
            for item in sorted(destdir.rglob("*")):
                arcname = item.relative_to(destdir)
                tar.add(str(item), arcname=str(arcname))
    return buf.getvalue()


def _make_sbom(name: str, version: str, arch: str) -> dict[str, Any]:
    """Return a minimal CycloneDX 1.4 SBOM dict."""
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.4",
        "version": 1,
        "metadata": {
            "component": {
                "type": "application",
                "name": name,
                "version": version,
            }
        },
        "components": [
            {
                "type": "library",
                "name": name,
                "version": version,
                "purl": f"pkg:generic/{name}@{version}?arch={arch}",
            }
        ],
    }


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _make_checksums(
    *,
    manifest_bytes: bytes,
    files_tar_bytes: bytes,
    sbom_bytes: bytes,
) -> bytes:
    """Return UTF-8 ``checksums.sha256`` content."""
    lines = [
        f"{_sha256_hex(manifest_bytes)}  manifest.json",
        f"{_sha256_hex(files_tar_bytes)}  files.tar.gz",
        f"{_sha256_hex(sbom_bytes)}  sbom.json",
    ]
    return ("\n".join(lines) + "\n").encode()
