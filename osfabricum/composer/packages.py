"""Package installation into a rootfs staging directory (M16).

Supports two artifact kinds:

* ``package`` / ``application/zip`` — ``.ofpkg`` ZIP archive produced by M9's
  :func:`~osfabricum.packaging.builder.build_ofpkg`.  The inner
  ``files.tar.gz`` is extracted relative to *stage_dir*.  Checksums are
  verified before any file is written.

* ``build-output`` / ``application/x-gzip`` — raw ``destdir`` tar.gz produced
  by M8's :func:`~osfabricum.builder.recipe.run_recipe`.  Extracted with a
  ``destdir/`` prefix strip.

``install_package_into_rootfs``
    Load one package artifact from the store and install it.

``install_packages_into_rootfs``
    Install a list of artifact IDs in order.
"""

from __future__ import annotations

import io
import json
import tarfile
import zipfile
from pathlib import Path
from typing import Any

from sqlalchemy import select

from osfabricum.db.models import Artifact
from osfabricum.db.session import sync_session
from osfabricum.store.layout import blob_path

# Relative path where installed-package metadata is written inside the rootfs
_PKG_DB_DIR = "var/lib/osfabricum/installed"


def _install_ofpkg_bytes(data: bytes, stage_dir: Path) -> dict[str, Any]:
    """Install a .ofpkg blob (bytes) into *stage_dir*.

    Verifies checksums before extracting any file.
    Returns the parsed manifest dict.
    """
    stage_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(io.BytesIO(data), "r") as zf:
        names = zf.namelist()
        if "manifest.json" not in names:
            raise ValueError("ofpkg is missing manifest.json")
        if "files.tar.gz" not in names:
            raise ValueError("ofpkg is missing files.tar.gz")
        if "checksums.sha256" not in names:
            raise ValueError("ofpkg is missing checksums.sha256")

        manifest: dict[str, Any] = json.loads(zf.read("manifest.json").decode("utf-8"))

        # Verify checksums
        import hashlib  # noqa: PLC0415

        checksums_text = zf.read("checksums.sha256").decode("utf-8")
        checksum_map: dict[str, str] = {}
        for line in checksums_text.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                digest, _, member = line.partition("  ")
                checksum_map[member.strip()] = digest.strip()

        for member_name, expected_sha256 in checksum_map.items():
            if member_name not in names:
                raise ValueError(f"ofpkg checksum references missing member: {member_name!r}")
            actual = hashlib.sha256(zf.read(member_name)).hexdigest()
            if actual != expected_sha256:
                raise ValueError(
                    f"ofpkg checksum mismatch for {member_name!r}: "
                    f"expected {expected_sha256}, got {actual}"
                )

        # Extract files
        files_tar_bytes = zf.read("files.tar.gz")

    with tarfile.open(fileobj=io.BytesIO(files_tar_bytes), mode="r:gz") as tar:
        tar.extractall(path=str(stage_dir), filter="data")

    return manifest


def _install_destdir_tarball(data: bytes, stage_dir: Path) -> None:
    """Install a raw destdir tar.gz into *stage_dir*, stripping ``destdir/``."""
    stage_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        for member in tar.getmembers():
            # Strip leading destdir/ prefix
            if member.name.startswith("destdir/"):
                member.name = member.name[len("destdir/"):]
            elif member.name == "destdir":
                continue
            if not member.name:
                continue
            tar.extract(member, path=str(stage_dir), filter="data")


def _write_pkg_record(stage_dir: Path, manifest: dict[str, Any]) -> None:
    """Write an installed-package record to /var/lib/osfabricum/installed/."""
    pkg_db = stage_dir / _PKG_DB_DIR
    pkg_db.mkdir(parents=True, exist_ok=True)
    name = manifest.get("name", "unknown")
    version = manifest.get("version", "0.0.0")
    arch = manifest.get("arch", "noarch")
    record_path = pkg_db / f"{name}-{version}-{arch}.json"
    record_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def install_package_into_rootfs(
    artifact_id: str,
    stage_dir: Path,
    store_root: Path,
    *,
    db_url: str | None = None,
) -> dict[str, Any]:
    """Install one package artifact into *stage_dir*.

    Parameters
    ----------
    artifact_id:
        UUID of the :class:`~osfabricum.db.models.Artifact` row.
    stage_dir:
        Rootfs staging directory root.
    store_root:
        Artifact store root.
    db_url:
        SQLAlchemy database URL.

    Returns
    -------
    dict
        Parsed manifest from the package.  For ``build-output`` artifacts
        a minimal synthetic manifest is returned.

    Raises
    ------
    ValueError
        If the artifact is not found or the package is malformed.
    """
    with sync_session(db_url) as session:
        art: Artifact | None = session.scalar(
            select(Artifact).where(Artifact.id == artifact_id)
        )
        if art is None:
            raise ValueError(f"artifact not found: {artifact_id!r}")
        kind = art.kind
        media_type = art.media_type or ""
        name = art.name
        version = art.version or "0.0.0"
        blob_sha256 = art.blob_sha256

    bp = blob_path(store_root, blob_sha256)
    if not bp.exists():
        raise FileNotFoundError(f"blob not found for artifact {artifact_id}: {bp}")

    data = bp.read_bytes()

    # Dispatch by media_type / kind
    if media_type == "application/zip" or kind in ("package",):
        manifest = _install_ofpkg_bytes(data, stage_dir)
    else:
        # raw destdir tar.gz (build-output from M8)
        _install_destdir_tarball(data, stage_dir)
        manifest = {
            "name": name,
            "version": version,
            "arch": "noarch",
            "kind": kind,
            "artifact_id": artifact_id,
        }

    _write_pkg_record(stage_dir, manifest)
    return manifest


def install_packages_into_rootfs(
    artifact_ids: list[str],
    stage_dir: Path,
    store_root: Path,
    *,
    db_url: str | None = None,
) -> list[dict[str, Any]]:
    """Install multiple packages into *stage_dir* in order.

    Returns a list of manifest dicts, one per installed package.
    """
    manifests: list[dict[str, Any]] = []
    for aid in artifact_ids:
        manifest = install_package_into_rootfs(
            aid, stage_dir, store_root, db_url=db_url
        )
        manifests.append(manifest)
    return manifests
