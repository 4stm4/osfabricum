"""Verify and install .ofpkg archives (M9).

Usage::

    from pathlib import Path
    from osfabricum.packaging.installer import verify_ofpkg, install_ofpkg

    verify_ofpkg(Path("nanodhcp-1.0.0-aarch64.ofpkg"))   # raises on tamper
    install_ofpkg(Path("nanodhcp-1.0.0-aarch64.ofpkg"), prefix=Path("/"))
"""

from __future__ import annotations

import hashlib
import io
import json
import tarfile
import zipfile
from pathlib import Path
from typing import Any

from osfabricum.packaging.builder import MANIFEST_REQUIRED, REQUIRED_MEMBERS

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def verify_ofpkg(path: Path) -> dict[str, Any]:
    """Verify a ``.ofpkg`` archive and return its parsed manifest.

    Checks performed in order:

    1. All four required members (``manifest.json``, ``files.tar.gz``,
       ``checksums.sha256``, ``sbom.json``) are present.
    2. SHA-256 of each member matches the entry in ``checksums.sha256``.
    3. ``manifest.json`` contains all required fields with non-empty values.
    4. ``format_version`` is ``"1"``.
    5. ``sbom.json`` contains the required CycloneDX top-level fields.

    Parameters
    ----------
    path:
        Path to the ``.ofpkg`` file.

    Returns
    -------
    dict
        Parsed ``manifest.json`` contents.

    Raises
    ------
    ValueError:
        On any verification failure (missing member, checksum mismatch,
        invalid manifest, invalid SBOM).
    """
    if not path.exists():
        raise ValueError(f"package not found: {path}")

    with zipfile.ZipFile(path, "r") as zf:
        members = set(zf.namelist())

        # 1. Presence check
        for required in REQUIRED_MEMBERS:
            if required not in members:
                raise ValueError(f".ofpkg missing required member: {required!r}")

        # 2. Checksum verification
        checksums_raw = zf.read("checksums.sha256").decode()
        expected: dict[str, str] = _parse_checksums(checksums_raw)

        for filename, expected_hex in expected.items():
            if filename not in members:
                raise ValueError(f"checksums.sha256 references missing member: {filename!r}")
            data = zf.read(filename)
            actual_hex = hashlib.sha256(data).hexdigest()
            if actual_hex != expected_hex:
                raise ValueError(
                    f"checksum mismatch for {filename!r}: expected {expected_hex}, got {actual_hex}"
                )

        # 3–4. Manifest schema
        manifest_raw = zf.read("manifest.json")
        try:
            manifest: dict[str, Any] = json.loads(manifest_raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"manifest.json is not valid JSON: {exc}") from exc

        _validate_manifest(manifest)

        # 5. SBOM schema
        sbom_raw = zf.read("sbom.json")
        try:
            sbom: dict[str, Any] = json.loads(sbom_raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"sbom.json is not valid JSON: {exc}") from exc

        _validate_sbom(sbom)

    return manifest


def install_ofpkg(path: Path, prefix: Path) -> None:
    """Install a verified ``.ofpkg`` into *prefix*.

    Calls :func:`verify_ofpkg` before writing any files.  All files from
    ``files.tar.gz`` are extracted relative to *prefix*.

    Parameters
    ----------
    path:
        Path to the ``.ofpkg`` file.
    prefix:
        Installation prefix (e.g. ``Path("/")`` for a root filesystem or
        a staging directory for further packaging).

    Raises
    ------
    ValueError:
        If verification fails.
    """
    verify_ofpkg(path)
    prefix.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(path, "r") as zf:
        files_tar_bytes = zf.read("files.tar.gz")

    buf = io.BytesIO(files_tar_bytes)
    with tarfile.open(fileobj=buf, mode="r:gz") as tar:
        tar.extractall(path=str(prefix), filter="data")  # noqa: S202


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _parse_checksums(raw: str) -> dict[str, str]:
    """Parse a ``checksums.sha256`` file into ``{filename: sha256_hex}``."""
    result: dict[str, str] = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:  # noqa: PLR2004
            raise ValueError(f"malformed checksums.sha256 line: {line!r}")
        hex_digest, filename = parts
        result[filename] = hex_digest
    return result


def _validate_manifest(manifest: dict[str, Any]) -> None:
    """Raise :exc:`ValueError` if *manifest* is missing required fields."""
    for field in MANIFEST_REQUIRED:
        value = manifest.get(field)
        if not value:
            raise ValueError(f"manifest.json missing or empty required field: {field!r}")
    if manifest["format_version"] != "1":
        raise ValueError(
            f"unsupported format_version: {manifest['format_version']!r} (expected '1')"
        )


def _validate_sbom(sbom: dict[str, Any]) -> None:
    """Raise :exc:`ValueError` if *sbom* is missing required CycloneDX fields."""
    if sbom.get("bomFormat") != "CycloneDX":
        raise ValueError(f"sbom.json: bomFormat must be 'CycloneDX', got {sbom.get('bomFormat')!r}")
    for field in ("specVersion", "version", "components"):
        if field not in sbom:
            raise ValueError(f"sbom.json missing required field: {field!r}")
    if not isinstance(sbom["components"], list):
        raise ValueError("sbom.json: 'components' must be a list")
