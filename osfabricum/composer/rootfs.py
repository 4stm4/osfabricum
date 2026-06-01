"""RootFS Composer (M16).

``compose_rootfs`` is the single entry point.  Given a
:class:`RootfsComposeSpec` it:

1. Extracts the base rootfs artifact (from M15) into a temp staging dir.
2. Installs each ``.ofpkg`` package artifact into the staging dir.
3. Applies each overlay artifact (tar.gz) on top.
4. Installs and enables requested services.
5. Packs the composed rootfs into a deterministic tar.gz via
   :func:`~osfabricum.rootfs.builder.pack_rootfs_deterministic`.
6. Ingests the result as a ``rootfs`` artifact with a full repro chain.

The composed artifact's ``store_key`` follows the pattern::

    rootfs/<distribution>/<profile>/<board>/composed.tar.gz
"""

from __future__ import annotations

import hashlib
import tarfile
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select

from osfabricum.composer.packages import install_packages_into_rootfs
from osfabricum.composer.services import install_services_into_rootfs
from osfabricum.config.overlay import apply_overlay
from osfabricum.db.models import Artifact
from osfabricum.db.session import sync_session
from osfabricum.repro.chain import InputManifest, compute_input_hash, make_repro_record
from osfabricum.repro.env import BuildEnvSpec, compute_env_hash
from osfabricum.rootfs.builder import pack_rootfs_deterministic
from osfabricum.store.ingest import ingest_blob
from osfabricum.store.layout import blob_path

# ---------------------------------------------------------------------------
# Spec & result
# ---------------------------------------------------------------------------


@dataclass
class RootfsComposeSpec:
    """Full specification for composing a rootfs.

    Attributes
    ----------
    distribution, profile, board, arch:
        Target triple and architecture.
    base_artifact_id:
        UUID of the ``rootfs-base`` artifact produced by M15.
    package_artifact_ids:
        Ordered list of package artifact UUIDs to install.
    overlay_artifact_ids:
        Ordered list of overlay artifact UUIDs to apply.
    service_names:
        Service names to install from the ``services`` table.
    init_system:
        Init system used for service installation (``"busybox"``/``"systemd"``).
    """

    distribution: str
    profile: str
    board: str
    arch: str
    base_artifact_id: str
    package_artifact_ids: list[str] = field(default_factory=list)
    overlay_artifact_ids: list[str] = field(default_factory=list)
    service_names: list[str] = field(default_factory=list)
    init_system: str = "busybox"

    def store_key(self) -> str:
        return f"rootfs/{self.distribution}/{self.profile}/{self.board}/composed.tar.gz"


@dataclass
class RootfsComposeResult:
    """Outcome of a :func:`compose_rootfs` call."""

    success: bool
    artifact_id: str | None = None
    installed_packages: list[str] = field(default_factory=list)
    applied_overlays: int = 0
    installed_services: list[str] = field(default_factory=list)
    error: str | None = None
    logs: list[str] = field(default_factory=list)
    stage_dir: Path | None = None  # preserved on failure


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_base_rootfs(
    artifact_id: str,
    stage_dir: Path,
    store_root: Path,
    *,
    db_url: str | None = None,
) -> None:
    """Extract the base rootfs tar.gz artifact into *stage_dir*."""
    with sync_session(db_url) as session:
        art: Artifact | None = session.scalar(
            select(Artifact).where(Artifact.id == artifact_id)
        )
        if art is None:
            raise ValueError(f"base rootfs artifact not found: {artifact_id!r}")
        blob_sha256 = art.blob_sha256

    bp = blob_path(store_root, blob_sha256)
    if not bp.exists():
        raise FileNotFoundError(f"base rootfs blob not found at {bp}")

    with tarfile.open(str(bp), mode="r:gz") as tar:
        tar.extractall(path=str(stage_dir), filter="data")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compose_rootfs(
    spec: RootfsComposeSpec,
    *,
    store_root: Path,
    db_url: str | None = None,
) -> RootfsComposeResult:
    """Compose a rootfs from a base image, packages, overlays, and services.

    Parameters
    ----------
    spec:
        The compose specification.
    store_root:
        Artifact store root.
    db_url:
        SQLAlchemy database URL.

    Returns
    -------
    RootfsComposeResult
        ``success=True`` with ``artifact_id`` set on success.
    """
    logs: list[str] = []
    tmp = tempfile.mkdtemp(prefix="osfab-compose-")
    stage_dir = Path(tmp)

    try:
        # 1. Extract base rootfs
        logs.append(
            f"[compose] extracting base rootfs artifact {spec.base_artifact_id[:8]}…"
        )
        _extract_base_rootfs(
            spec.base_artifact_id, stage_dir, store_root, db_url=db_url
        )
        logs.append(f"[compose] base rootfs extracted to {stage_dir}")

        # 2. Install packages
        installed_pkgs: list[str] = []
        if spec.package_artifact_ids:
            logs.append(f"[compose] installing {len(spec.package_artifact_ids)} package(s)")
            manifests = install_packages_into_rootfs(
                spec.package_artifact_ids, stage_dir, store_root, db_url=db_url
            )
            installed_pkgs = [
                f"{m.get('name', '?')}-{m.get('version', '?')}" for m in manifests
            ]
            for pkg in installed_pkgs:
                logs.append(f"[compose]   + {pkg}")

        # 3. Apply overlays
        overlay_count = 0
        for ov_id in spec.overlay_artifact_ids:
            logs.append(f"[compose] applying overlay {ov_id[:8]}…")
            extracted = apply_overlay(
                artifact_id=ov_id,
                target_dir=stage_dir,
                store_root=store_root,
                db_url=db_url,
            )
            overlay_count += 1
            logs.append(f"[compose]   overlay: {len(extracted)} files")

        # 4. Install services
        installed_svcs: list[str] = []
        if spec.service_names:
            logs.append(f"[compose] installing {len(spec.service_names)} service(s)")
            svc_map = install_services_into_rootfs(
                spec.service_names,
                stage_dir,
                store_root,
                init_system=spec.init_system,
                db_url=db_url,
            )
            installed_svcs = list(svc_map.keys())
            for svc in installed_svcs:
                logs.append(f"[compose]   svc: {svc}")

        # 5. Pack
        logs.append("[compose] packing composed rootfs…")
        archive = pack_rootfs_deterministic(stage_dir)
        logs.append(f"[compose] packed: {len(archive)} bytes")

    except Exception as exc:
        return RootfsComposeResult(
            success=False,
            stage_dir=stage_dir,
            error=str(exc),
            logs=logs,
        )

    # 6. Repro chain
    env_spec = BuildEnvSpec(arch=spec.arch)
    env_hash = compute_env_hash(env_spec)
    config_hash = hashlib.sha256(
        (spec.base_artifact_id + "".join(sorted(spec.package_artifact_ids))).encode()
    ).hexdigest()
    manifest = InputManifest(
        step_kind="rootfs.compose",
        source_hash=spec.base_artifact_id,
        config_hash=config_hash,
        env_hash=env_hash,
        extra={
            "distribution": spec.distribution,
            "profile": spec.profile,
            "board": spec.board,
        },
    )
    input_hash = compute_input_hash(manifest)
    repro_rec = make_repro_record(manifest, hashlib.sha256(archive).hexdigest())

    # 7. Ingest
    try:
        artifact = ingest_blob(
            data=archive,
            store_root=store_root,
            store_key=spec.store_key(),
            kind="rootfs",
            name=f"{spec.distribution}-{spec.profile}-{spec.board}",
            version="latest",
            arch=spec.arch,
            media_type="application/x-gzip",
            db_url=db_url,
            retention_class="staging",
            input_hash=input_hash,
            repro_record=repro_rec,
        )
    except Exception as exc:
        return RootfsComposeResult(
            success=False,
            stage_dir=stage_dir,
            error=f"ingest failed: {exc}",
            logs=logs,
        )

    logs.append(f"[compose] artifact ingested: {artifact.id}")

    return RootfsComposeResult(
        success=True,
        artifact_id=artifact.id,
        installed_packages=installed_pkgs,
        applied_overlays=overlay_count,
        installed_services=installed_svcs,
        logs=logs,
    )
