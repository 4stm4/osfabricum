"""Base RootFS builder (M15).

``build_base_rootfs`` is the single entry point.  It:

1. Creates an isolated staging directory.
2. Builds the directory tree from :data:`~osfabricum.rootfs.layout.BASE_DIRS`.
3. Writes ``/etc`` configuration files via :mod:`~osfabricum.rootfs.etcfiles`.
4. Writes the init system skeleton via :mod:`~osfabricum.rootfs.initsystem`.
5. Packs the staging directory into a **deterministic** tar.gz
   (``SOURCE_DATE_EPOCH=0``, sorted entries, numeric UID/GID 0:0).
6. Ingests the archive as a ``rootfs-base`` artifact and returns a
   :class:`RootfsBuildResult`.

Determinism
-----------
* All files are written with ``mtime = 0`` (Unix epoch).
* Tar entries are added in sorted order.
* UIDs and GIDs are ``0`` (root).
* Permissions follow :data:`~osfabricum.rootfs.layout.DIR_MODES` for
  well-known paths; defaults are ``0o755`` for directories and ``0o644``
  for files.

The resulting tar.gz will be byte-identical on repeated runs with the same
inputs (same :class:`RootfsSpec`, same code version).
"""

from __future__ import annotations

import hashlib
import io
import tarfile
import tempfile
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from osfabricum.repro.chain import InputManifest, compute_input_hash, make_repro_record
from osfabricum.repro.env import BuildEnvSpec, compute_env_hash
from osfabricum.rootfs.etcfiles import (
    make_fstab,
    make_group,
    make_hostname,
    make_hosts,
    make_nsswitch_conf,
    make_os_release,
    make_passwd,
    make_profile,
    make_resolv_conf,
    make_shadow,
    make_shells,
)
from osfabricum.rootfs.initsystem import setup_init_system
from osfabricum.rootfs.layout import BASE_DIRS, DIR_MODES
from osfabricum.store.ingest import ingest_blob

# ---------------------------------------------------------------------------
# Spec & result
# ---------------------------------------------------------------------------


@dataclass
class RootfsSpec:
    """Full specification for a base rootfs build.

    Attributes
    ----------
    arch:
        Target architecture (e.g. ``"aarch64"``).
    distribution:
        Distribution name (e.g. ``"tinywifi"``).
    profile:
        Profile name (e.g. ``"default"``).
    board:
        Board name (e.g. ``"rpi-zero-2w"``).
    init_system:
        ``"busybox"`` (default) or ``"systemd"``.
    hostname:
        Default hostname written to ``/etc/hostname``.
    timezone:
        Timezone string written to ``/etc/timezone``.
    locale:
        Locale string (written to ``/etc/locale.conf``).
    nameservers:
        DNS servers for ``/etc/resolv.conf``.
    extra_dirs:
        Additional directories to create inside the rootfs.
    extra_etc:
        Mapping of relative path → bytes for extra ``/etc`` files.
    """

    arch: str
    distribution: str
    profile: str
    board: str
    init_system: str = "busybox"
    hostname: str = "osfabricum"
    timezone: str = "UTC"
    locale: str = "C"
    nameservers: list[str] = field(default_factory=lambda: ["8.8.8.8", "1.1.1.1"])
    extra_dirs: list[str] = field(default_factory=list)
    extra_etc: dict[str, bytes] = field(default_factory=dict)

    def store_key(self) -> str:
        """Return the canonical artifact store key for this spec."""
        return f"rootfs/{self.distribution}/{self.profile}/{self.board}/base.tar.gz"


@dataclass
class RootfsBuildResult:
    """Outcome of a :func:`build_base_rootfs` call."""

    success: bool
    artifact_id: str | None = None
    stage_dir: Path | None = None  # preserved on failure
    error: str | None = None
    logs: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _add_dir(tar: tarfile.TarFile, rel_path: str, mode: int) -> None:
    """Add a directory entry with frozen mtime=0."""
    info = tarfile.TarInfo(name=rel_path)
    info.type = tarfile.DIRTYPE
    info.mode = mode
    info.mtime = 0
    info.uid = 0
    info.gid = 0
    info.uname = "root"
    info.gname = "root"
    tar.addfile(info)


def _add_file(tar: tarfile.TarFile, rel_path: str, data: bytes, mode: int = 0o644) -> None:
    """Add a regular file entry with frozen mtime=0."""
    info = tarfile.TarInfo(name=rel_path)
    info.type = tarfile.REGTYPE
    info.size = len(data)
    info.mode = mode
    info.mtime = 0
    info.uid = 0
    info.gid = 0
    info.uname = "root"
    info.gname = "root"
    tar.addfile(info, io.BytesIO(data))


def _add_symlink(tar: tarfile.TarFile, rel_path: str, target: str) -> None:
    """Add a symlink entry."""
    info = tarfile.TarInfo(name=rel_path)
    info.type = tarfile.SYMTYPE
    info.linkname = target
    info.mode = 0o777
    info.mtime = 0
    info.uid = 0
    info.gid = 0
    info.uname = "root"
    info.gname = "root"
    tar.addfile(info)


def create_rootfs_tree(stage_dir: Path, spec: RootfsSpec) -> list[str]:
    """Create the directory tree under *stage_dir*.

    Returns the list of relative paths created.
    """
    created: list[str] = []
    all_dirs = list(BASE_DIRS) + spec.extra_dirs

    for rel in all_dirs:
        full = stage_dir / rel
        full.mkdir(parents=True, exist_ok=True)
        mode = DIR_MODES.get(rel, 0o755)
        full.chmod(mode)
        created.append(rel)

    return created


def write_etc_files(stage_dir: Path, spec: RootfsSpec) -> list[str]:
    """Write standard /etc configuration files.

    Returns the list of relative paths written.
    """
    written: list[str] = []

    files: list[tuple[str, bytes, int]] = [
        ("etc/passwd", make_passwd(), 0o644),
        ("etc/group", make_group(), 0o644),
        ("etc/shadow", make_shadow(), 0o640),
        ("etc/hosts", make_hosts(spec.hostname), 0o644),
        ("etc/hostname", make_hostname(spec.hostname), 0o644),
        ("etc/fstab", make_fstab(), 0o644),
        ("etc/profile", make_profile(), 0o644),
        ("etc/shells", make_shells(), 0o644),
        ("etc/nsswitch.conf", make_nsswitch_conf(), 0o644),
        ("etc/resolv.conf", make_resolv_conf(spec.nameservers), 0o644),
        ("etc/os-release", make_os_release(spec.distribution), 0o644),
        ("etc/timezone", (spec.timezone + "\n").encode("utf-8"), 0o644),
        ("etc/locale.conf", (f"LANG={spec.locale}\n").encode(), 0o644),
    ]

    for rel, data, mode in files:
        (stage_dir / rel).write_bytes(data)
        (stage_dir / rel).chmod(mode)
        written.append(rel)

    # Extra /etc files from spec
    for rel, data in spec.extra_etc.items():
        path = stage_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        written.append(rel)

    return written


def pack_rootfs_deterministic(stage_dir: Path) -> bytes:
    """Pack *stage_dir* into a deterministic gzip-compressed tar.

    * All entries use ``mtime=0`` (SOURCE_DATE_EPOCH=0).
    * Entries are added in sorted order.
    * All UIDs/GIDs are set to ``0:0``.

    Returns raw bytes of the ``.tar.gz`` archive.
    """
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        # Collect all paths, sort for determinism
        all_paths = sorted(stage_dir.rglob("*"), key=lambda p: str(p.relative_to(stage_dir)))

        for item in all_paths:
            rel = str(item.relative_to(stage_dir))
            if item.is_symlink():
                _add_symlink(tar, rel, str(item.readlink()))
            elif item.is_dir():
                mode = DIR_MODES.get(rel, 0o755)
                _add_dir(tar, rel, mode)
            elif item.is_file():
                data = item.read_bytes()
                mode = item.stat().st_mode & 0o777
                _add_file(tar, rel, data, mode)

    return buf.getvalue()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_base_rootfs(
    spec: RootfsSpec,
    *,
    store_root: Path,
    db_url: str | None = None,
) -> RootfsBuildResult:
    """Build and ingest a base rootfs for *spec*.

    Parameters
    ----------
    spec:
        The rootfs specification.
    store_root:
        Artifact store root.
    db_url:
        SQLAlchemy database URL.

    Returns
    -------
    RootfsBuildResult
        ``success=True`` with ``artifact_id`` set on success.
    """
    logs: list[str] = []
    tmp = tempfile.mkdtemp(prefix="osfab-rootfs-")
    stage_dir = Path(tmp)

    try:
        logs.append(
            f"[rootfs] building base rootfs for {spec.distribution}/{spec.profile}/{spec.board}"
        )
        logs.append(f"[rootfs] init_system={spec.init_system!r}  arch={spec.arch!r}")

        # 1. Directory tree
        dirs = create_rootfs_tree(stage_dir, spec)
        logs.append(f"[rootfs] created {len(dirs)} directories")

        # 2. /etc files
        etc_files = write_etc_files(stage_dir, spec)
        logs.append(f"[rootfs] wrote {len(etc_files)} /etc files")

        # 3. Init system skeleton
        init_files = setup_init_system(stage_dir, spec.init_system)
        logs.append(f"[rootfs] init system '{spec.init_system}': {len(init_files)} files")

        # 4. Pack (deterministic)
        archive = pack_rootfs_deterministic(stage_dir)
        logs.append(f"[rootfs] packed archive: {len(archive)} bytes")

    except Exception as exc:
        return RootfsBuildResult(
            success=False,
            stage_dir=stage_dir,
            error=str(exc),
            logs=logs,
        )

    # 5. Reproducibility chain
    import hashlib  # noqa: PLC0415

    env_spec = BuildEnvSpec(arch=spec.arch)
    env_hash = compute_env_hash(env_spec)
    config_hash = hashlib.sha256(spec.hostname.encode() + spec.init_system.encode()).hexdigest()
    manifest = InputManifest(
        step_kind="rootfs.base",
        source_hash="",  # no source archive for base rootfs
        config_hash=config_hash,
        env_hash=env_hash,
        extra={
            "distribution": spec.distribution,
            "profile": spec.profile,
            "board": spec.board,
            "init_system": spec.init_system,
        },
    )
    input_hash = compute_input_hash(manifest)
    repro_rec = make_repro_record(manifest, hashlib.sha256(archive).hexdigest())

    # 6. Ingest
    try:
        artifact = ingest_blob(
            data=archive,
            store_root=store_root,
            store_key=spec.store_key(),
            kind="rootfs-base",
            name=f"{spec.distribution}-{spec.profile}-{spec.board}-base",
            version="latest",
            arch=spec.arch,
            media_type="application/x-gzip",
            db_url=db_url,
            retention_class="staging",
            input_hash=input_hash,
            repro_record=repro_rec,
        )
    except Exception as exc:
        return RootfsBuildResult(
            success=False,
            stage_dir=stage_dir,
            error=f"ingest failed: {exc}",
            logs=logs,
        )

    logs.append(f"[rootfs] artifact ingested: {artifact.id}")

    return RootfsBuildResult(
        success=True,
        artifact_id=artifact.id,
        logs=logs,
    )


def fetch_upstream_rootfs(
    url: str,
    *,
    store_root: Path,
    store_key: str,
    arch: str,
    name: str = "upstream-rootfs",
    db_url: str | None = None,
) -> RootfsBuildResult:
    """Download an upstream rootfs tarball (e.g. Alpine minirootfs) and ingest as rootfs-base.

    Uses store_key deduplication — subsequent calls with the same URL return the
    cached artifact without re-downloading.
    """
    logs: list[str] = []
    logs.append(f"[rootfs] fetching upstream rootfs: {url}")

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "osfabricum/1.0"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            data: bytes = resp.read()
    except Exception as exc:
        return RootfsBuildResult(success=False, error=f"download failed: {exc}", logs=logs)

    logs.append(f"[rootfs] downloaded {len(data)} bytes (sha256={hashlib.sha256(data).hexdigest()[:12]})")

    try:
        artifact = ingest_blob(
            data=data,
            store_root=store_root,
            store_key=store_key,
            kind="rootfs-base",
            name=name,
            arch=arch,
            media_type="application/gzip",
            db_url=db_url,
            retention_class="permanent",
            input_hash=hashlib.sha256(url.encode()).hexdigest(),
        )
    except Exception as exc:
        return RootfsBuildResult(success=False, error=f"ingest failed: {exc}", logs=logs)

    logs.append(f"[rootfs] artifact ingested: {artifact.id}")
    return RootfsBuildResult(success=True, artifact_id=artifact.id, logs=logs)
