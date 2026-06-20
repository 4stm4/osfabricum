"""Kernel build logic (M10).

``build_kernel`` is the single entry point for cross-compiling a registered
kernel, ingesting the outputs (Image / modules / DTBs) into the artifact store,
and returning a :class:`KernelBuildResult`.

Cache strategy
--------------
The composite cache key ``kernel/<id>/<source_hash>/<config_hash>/image`` is
used to look up an existing image artifact.  A cache hit skips compilation
entirely and returns the previously stored artifact IDs.

Build environment
-----------------
* ``SOURCE_DATE_EPOCH=0`` — reproducible timestamps
* ``KBUILD_BUILD_TIMESTAMP`` / ``KBUILD_BUILD_USER`` / ``KBUILD_BUILD_HOST``
  are frozen to constant values.
* ``PATH`` is restricted to ``toolchain/bin:/usr/bin:/bin``.
"""

from __future__ import annotations

import hashlib
import io
import platform
import subprocess
import tarfile
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import select

from osfabricum.db.models import Architecture, Artifact, Board, Kernel, KernelConfig
from osfabricum.db.session import sync_session
from osfabricum.repro.chain import InputManifest, compute_input_hash, make_repro_record
from osfabricum.repro.env import BuildEnvSpec, compute_env_hash
from osfabricum.store.ingest import ingest_blob

# ---------------------------------------------------------------------------
# ARCH mapping
# ---------------------------------------------------------------------------

_ARCH_MAP: dict[str, str] = {
    "aarch64": "arm64",
    "arm64": "arm64",
    "arm": "arm",
    "armv7": "arm",
    "x86_64": "x86_64",
    "x86": "x86",
}

# Default kernel image path within source tree for each ARCH
_IMAGE_PATH: dict[str, str] = {
    "arm64": "arch/arm64/boot/Image",
    "arm": "arch/arm/boot/zImage",
    "x86_64": "arch/x86_64/boot/bzImage",
    "x86": "arch/x86/boot/bzImage",
}

_IMAGE_TARGET: dict[str, str] = {
    "arm64": "Image",
    "arm": "zImage",
    "x86_64": "bzImage",
    "x86": "bzImage",
}


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class KernelBuildResult:
    """Outcome of a :func:`build_kernel` call."""

    success: bool
    source_hash: str
    config_hash: str
    logs: list[str] = field(default_factory=list)
    image_artifact_id: str | None = None
    modules_artifact_id: str | None = None
    dtb_artifact_ids: list[str] = field(default_factory=list)
    cache_hit: bool = False
    error: str | None = None
    work_dir: Path | None = None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _lookup_kernel(identifier: str, db_url: str | None) -> Kernel:
    """Return :class:`~osfabricum.db.models.Kernel` by name or id."""
    with sync_session(db_url) as session:
        src = session.scalar(select(Kernel).where(Kernel.name == identifier))
        if src is None:
            src = session.scalar(select(Kernel).where(Kernel.id == identifier))
        if src is None:
            raise ValueError(f"kernel not found: {identifier!r}")
        session.expunge(src)
        return src


def _lookup_board(name: str, db_url: str | None) -> Board | None:
    with sync_session(db_url) as session:
        board = session.scalar(select(Board).where(Board.name == name))
        if board is not None:
            session.expunge(board)
        return board


def _lookup_arch_name(arch_id: str, db_url: str | None) -> str:
    with sync_session(db_url) as session:
        arch = session.scalar(select(Architecture).where(Architecture.id == arch_id))
        if arch is None:
            raise ValueError(f"architecture not found: {arch_id!r}")
        return arch.name


def _compute_config_hash(config_data: bytes) -> str:
    return hashlib.sha256(config_data).hexdigest()


def _compute_source_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _make_build_env(toolchain_root: Path | None, arch: str, cross_compile: str) -> dict[str, str]:
    path_parts: list[str] = []
    if toolchain_root is not None:
        path_parts.append(str(toolchain_root / "bin"))
    path_parts.extend(["/usr/bin", "/bin"])
    return {
        "PATH": ":".join(path_parts),
        "ARCH": arch,
        "CROSS_COMPILE": cross_compile,
        "SOURCE_DATE_EPOCH": "0",
        "KBUILD_BUILD_TIMESTAMP": "Thu Jan  1 00:00:00 UTC 1970",
        "KBUILD_BUILD_USER": "osfabricum",
        "KBUILD_BUILD_HOST": "osfabricum",
        "HOME": str(Path.home()),
        "LANG": "C",
        "LC_ALL": "C",
    }


def _run_make(args: list[str], cwd: Path, env: dict[str, str], logs: list[str]) -> None:
    proc = subprocess.run(  # noqa: S603
        ["make", *args],
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        encoding="utf-8",
        errors="replace",
    )
    for line in (proc.stdout or "").splitlines():
        logs.append(line)
    if proc.returncode != 0:
        tail = "\n".join(logs[-20:])
        raise RuntimeError(f"make {' '.join(args)} failed (exit {proc.returncode})\n{tail}")


def _compile_kernel(
    *,
    src_dir: Path,
    arch: str,
    cross_compile: str,
    image_target: str,
    dtb_patterns: list[str],
    jobs: int,
    logs: list[str],
    toolchain_root: Path | None = None,
    defconfig_target: str | None = None,
) -> tuple[Path, list[Path], Path]:
    """Run kernel compile steps; return ``(image_path, dtb_paths, modules_dir)``.

    This function is designed to be replaced/patched in unit tests.
    """
    env = _make_build_env(toolchain_root, arch, cross_compile)

    if defconfig_target:
        # Generate .config from a named defconfig (e.g. "bcm2711_defconfig")
        _run_make([defconfig_target], src_dir, env, logs)
    else:
        _run_make(["olddefconfig"], src_dir, env, logs)
    _run_make(["-j", str(jobs), image_target, "modules"], src_dir, env, logs)

    if dtb_patterns:
        _run_make(["dtbs"], src_dir, env, logs)

    mod_dir = src_dir / "_modules"
    mod_dir.mkdir(exist_ok=True)
    _run_make(
        [f"INSTALL_MOD_PATH={mod_dir}", "modules_install"],
        src_dir,
        env,
        logs,
    )

    image_path = src_dir / _IMAGE_PATH.get(arch, f"arch/{arch}/boot/Image")

    dtb_paths: list[Path] = []
    for pattern in dtb_patterns:
        p = src_dir / pattern
        if p.exists():
            dtb_paths.append(p)

    return image_path, dtb_paths, mod_dir


def _pack_modules(mod_dir: Path) -> bytes:
    """Pack *mod_dir* into a gzip-compressed tar."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        if mod_dir.exists():
            for item in sorted(mod_dir.rglob("*")):
                tar.add(str(item), arcname=str(item.relative_to(mod_dir)))
    return buf.getvalue()


def _apply_patches(src_dir: Path, patches: list[str], logs: list[str]) -> None:
    """Apply *patches* (shell commands) to *src_dir* in order."""
    for patch_cmd in patches:
        proc = subprocess.run(  # noqa: S602
            patch_cmd,
            shell=True,
            cwd=src_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        for line in (proc.stdout or "").splitlines():
            logs.append(line)
        if proc.returncode != 0:
            raise RuntimeError(f"patch command failed: {patch_cmd!r}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_kernel(
    kernel_name_or_id: str,
    *,
    store_root: Path,
    board_name: str | None = None,
    toolchain_root: Path | None = None,
    config_data: bytes | None = None,
    src_dir: Path | None = None,
    db_url: str | None = None,
    jobs: int = 1,
) -> KernelBuildResult:
    """Build a kernel and store the outputs as artifacts.

    Parameters
    ----------
    kernel_name_or_id:
        Kernel name (e.g. ``"linux-rpi"``) or UUID.
    store_root:
        Artifact store root.
    board_name:
        Board name for DTB selection and KernelConfig lookup.
    toolchain_root:
        Optional cross-compilation toolchain prefix.
    config_data:
        Optional ``.config`` bytes.  When ``None`` the defconfig from
        ``metadata_json["defconfig"]`` is used.
    src_dir:
        Pre-extracted kernel source directory.  When supplied, the source
        fetch and extraction step is skipped.  Useful in tests.
    db_url:
        SQLAlchemy database URL.
    jobs:
        Parallel make jobs.

    Returns
    -------
    KernelBuildResult
    """
    # --- look up records ---
    kernel = _lookup_kernel(kernel_name_or_id, db_url)
    meta: dict[str, Any] = dict(kernel.metadata_json or {})
    arch_name = _lookup_arch_name(kernel.arch_id, db_url)
    arch = _ARCH_MAP.get(arch_name, arch_name)
    image_target = _IMAGE_TARGET.get(arch, "Image")
    dtb_patterns: list[str] = meta.get("dtbs", [])
    patches: list[str] = meta.get("patches", [])

    # Native build: host arch == target arch → no cross-compiler needed.
    # Bootlin toolchains are x86-64 host binaries; using them on aarch64 fails.
    host_machine = platform.machine()
    _arch_aliases = {"aarch64": "arm64", "arm64": "aarch64"}
    native_build = host_machine == arch_name or host_machine == _arch_aliases.get(arch_name, "")
    if native_build:
        toolchain_root = None
    cross_compile = ""
    if not native_build:
        if toolchain_root is not None:
            cross_compile = f"{arch_name}-linux-musl-"
        elif arch != "x86_64":
            cross_compile = f"{arch_name}-linux-musl-"

    # --- source fetch ---
    logs: list[str] = []
    if src_dir is None:
        tarball_url = str(meta.get("tarball_url") or kernel.source_uri or "")
        if not tarball_url:
            raise ValueError(f"kernel {kernel_name_or_id!r} has no tarball_url or source_uri")
        import urllib.request

        with urllib.request.urlopen(tarball_url) as resp:  # noqa: S310
            tarball_data = resp.read()
        source_hash = _compute_source_hash(tarball_data)

        tmp = tempfile.mkdtemp(prefix="osfab-kernel-src-")
        src_dir = Path(tmp)
        buf = io.BytesIO(tarball_data)
        with tarfile.open(fileobj=buf, mode="r:*") as tar:
            tar.extractall(path=str(src_dir), filter="data")
        # Unwrap single top-level directory if present
        entries = list(src_dir.iterdir())
        if len(entries) == 1 and entries[0].is_dir():
            src_dir = entries[0]
    else:
        source_hash = hashlib.sha256(str(src_dir).encode()).hexdigest()

    # --- config ---
    if config_data is None:
        defconfig = meta.get("defconfig", "")
        config_data = defconfig.encode() if defconfig else b""
    config_hash = _compute_config_hash(config_data)

    # --- reproducibility hash chain (M13) ---
    env_spec = BuildEnvSpec(
        arch=arch,
        cross_compile_prefix=cross_compile,
        toolchain_version=None,  # enriched later if toolchain_root provided
    )
    env_hash = compute_env_hash(env_spec)
    input_manifest = InputManifest(
        step_kind="kernel.build",
        source_hash=source_hash,
        config_hash=config_hash,
        env_hash=env_hash,
        extra={"kernel_id": kernel.id},
    )
    _input_hash = compute_input_hash(input_manifest)

    # --- cache check ---
    cache_prefix = f"kernel/{kernel.id}/{source_hash}/{config_hash}"
    image_key = f"{cache_prefix}/image"

    if db_url is not None:
        with sync_session(db_url) as session:
            existing_image = session.scalar(select(Artifact).where(Artifact.store_key == image_key))
            if existing_image is not None:
                mod_artifact = session.scalar(
                    select(Artifact).where(Artifact.store_key == f"{cache_prefix}/modules")
                )
                dtb_artifacts = session.scalars(
                    select(Artifact).where(Artifact.store_key.like(f"{cache_prefix}/dtb/%"))
                ).all()
                return KernelBuildResult(
                    success=True,
                    source_hash=source_hash,
                    config_hash=config_hash,
                    image_artifact_id=existing_image.id,
                    modules_artifact_id=mod_artifact.id if mod_artifact else None,
                    dtb_artifact_ids=[a.id for a in dtb_artifacts],
                    cache_hit=True,
                )

    # --- config: detect defconfig target vs raw .config content ---
    # metadata_json["defconfig"] may store a make target name like
    # "bcm2711_defconfig" (≤100 chars, no CONFIG_ lines) rather than
    # actual .config file content. Detect this and run make accordingly.
    defconfig_target: str | None = None
    if config_data and b"CONFIG_" not in config_data and len(config_data) < 200:
        defconfig_target = config_data.decode(errors="replace").strip()
        config_data = None  # let _compile_kernel handle it via make target
    if config_data and src_dir.exists():
        (src_dir / ".config").write_bytes(config_data)

    # --- apply patches ---
    if patches:
        _apply_patches(src_dir, patches, logs)

    # --- compile ---
    try:
        image_path, dtb_paths, mod_dir = _compile_kernel(
            src_dir=src_dir,
            arch=arch,
            cross_compile=cross_compile,
            image_target=image_target,
            dtb_patterns=dtb_patterns,
            jobs=jobs,
            logs=logs,
            toolchain_root=toolchain_root,
            defconfig_target=defconfig_target,
        )
    except Exception as exc:
        return KernelBuildResult(
            success=False,
            source_hash=source_hash,
            config_hash=config_hash,
            logs=logs,
            work_dir=src_dir,
            error=str(exc),
        )

    # --- ingest image ---
    try:
        if not image_path.exists():
            raise FileNotFoundError(f"kernel image not found: {image_path}")

        image_data = image_path.read_bytes()
        _repro_rec = make_repro_record(input_manifest, hashlib.sha256(image_data).hexdigest())
        image_artifact = ingest_blob(
            data=image_data,
            store_root=store_root,
            store_key=image_key,
            kind="kernel",
            name=f"{kernel.name}-{kernel.version}",
            version=kernel.version,
            media_type="application/octet-stream",
            db_url=db_url,
            retention_class="permanent",
            input_hash=_input_hash,
            repro_record=_repro_rec,
        )

        # --- ingest modules ---
        mod_data = _pack_modules(mod_dir)
        mod_artifact = ingest_blob(
            data=mod_data,
            store_root=store_root,
            store_key=f"{cache_prefix}/modules",
            kind="kernel-modules",
            name=f"{kernel.name}-{kernel.version}-modules",
            version=kernel.version,
            media_type="application/x-gzip",
            db_url=db_url,
            retention_class="permanent",
        )

        # --- ingest DTBs ---
        dtb_artifact_ids: list[str] = []
        for dtb_path in dtb_paths:
            dtb_data = dtb_path.read_bytes()
            dtb_name = dtb_path.name
            dtb_art = ingest_blob(
                data=dtb_data,
                store_root=store_root,
                store_key=f"{cache_prefix}/dtb/{dtb_name}",
                kind="dtb",
                name=dtb_name,
                version=kernel.version,
                media_type="application/octet-stream",
                db_url=db_url,
                retention_class="permanent",
            )
            dtb_artifact_ids.append(dtb_art.id)

        # --- update KernelConfig ---
        if board_name is not None and db_url is not None:
            board = _lookup_board(board_name, db_url)
            if board is not None:
                _upsert_kernel_config(kernel.id, board.id, image_artifact.id, db_url)

    except Exception as exc:
        return KernelBuildResult(
            success=False,
            source_hash=source_hash,
            config_hash=config_hash,
            logs=logs,
            work_dir=src_dir,
            error=str(exc),
        )

    return KernelBuildResult(
        success=True,
        source_hash=source_hash,
        config_hash=config_hash,
        logs=logs,
        image_artifact_id=image_artifact.id,
        modules_artifact_id=mod_artifact.id,
        dtb_artifact_ids=dtb_artifact_ids,
    )


def _upsert_kernel_config(
    kernel_id: str,
    board_id: str,
    artifact_id: str,
    db_url: str | None,
) -> None:
    """Create or update the KernelConfig row linking kernel+board→artifact."""
    with sync_session(db_url) as session:
        kc = session.scalar(
            select(KernelConfig).where(
                KernelConfig.kernel_id == kernel_id,
                KernelConfig.board_id == board_id,
            )
        )
        if kc is None:
            session.add(
                KernelConfig(
                    kernel_id=kernel_id,
                    board_id=board_id,
                    config_artifact_id=artifact_id,
                )
            )
        else:
            kc.config_artifact_id = artifact_id
        session.commit()
