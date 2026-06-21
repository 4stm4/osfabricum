"""BusyBox package builder.

Downloads BusyBox source, compiles a fully static binary, and packages the
result as a ``.ofpkg`` artifact ingested into the artifact store.

The build is cached by ``store_key``; if the artifact already exists in the
store the download and compilation are skipped entirely.

Entry point::

    from osfabricum.packaging.busybox import build_busybox
    result = build_busybox(arch="aarch64", store_root=Path(...), db_url=...)
"""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select

from osfabricum.db.models import Artifact
from osfabricum.db.session import sync_session
from osfabricum.store.ingest import ingest_blob

BUSYBOX_VERSION = "1.37.0"
BUSYBOX_URL = (
    f"https://busybox.net/downloads/busybox-{BUSYBOX_VERSION}.tar.bz2"
)

# Minimal .config fragment — static build, no Linux module utilities
# (those require kernel headers we don't ship).
_CONFIG_FRAGMENT = """\
CONFIG_STATIC=y
CONFIG_STATIC_LIBGCC=y
CONFIG_LFS=y
CONFIG_FEATURE_INSTALLER=y
# Disable things that need extra headers / libs
CONFIG_MODPROBE_SMALL=n
CONFIG_DEPMOD=n
CONFIG_INSMOD=n
CONFIG_RMMOD=n
CONFIG_LSMOD=n
CONFIG_MODINFO=n
CONFIG_FEATURE_MODPROBE_BLACKLIST=n
CONFIG_UDHCPD=n
"""


@dataclass
class BusyboxBuildResult:
    success: bool
    artifact_id: str | None = None
    error: str | None = None
    logs: list[str] = field(default_factory=list)
    cache_hit: bool = False


def _store_key(arch: str) -> str:
    return f"packages/busybox/{BUSYBOX_VERSION}/{arch}/busybox.ofpkg"


def _pack_ofpkg(destdir: Path, arch: str) -> bytes:
    """Pack *destdir* into an in-memory .ofpkg (zip) archive."""
    # files.tar.gz
    files_buf = io.BytesIO()
    with tarfile.open(fileobj=files_buf, mode="w:gz") as tar:
        for item in sorted(destdir.rglob("*"), key=lambda p: str(p.relative_to(destdir))):
            rel = str(item.relative_to(destdir))
            if item.is_symlink():
                info = tarfile.TarInfo(name=rel)
                info.type = tarfile.SYMTYPE
                info.linkname = str(item.readlink())
                info.mtime = 0
                tar.addfile(info)
            elif item.is_dir():
                info = tarfile.TarInfo(name=rel)
                info.type = tarfile.DIRTYPE
                info.mode = 0o755
                info.mtime = 0
                tar.addfile(info)
            elif item.is_file():
                data = item.read_bytes()
                info = tarfile.TarInfo(name=rel)
                info.size = len(data)
                info.mode = item.stat().st_mode & 0o777
                info.mtime = 0
                tar.addfile(info, io.BytesIO(data))
    files_tar = files_buf.getvalue()

    manifest = {
        "format_version": "1",
        "name": "busybox",
        "version": BUSYBOX_VERSION,
        "arch": arch,
        "description": "BusyBox — the Swiss Army Knife of embedded Linux (static)",
        "license": "GPL-2.0-only",
        "dependencies": [],
        "build_system": "make",
    }
    manifest_bytes = json.dumps(manifest, indent=2, sort_keys=True).encode()

    def _sha256(b: bytes) -> str:
        return hashlib.sha256(b).hexdigest()

    checksums = (
        f"{_sha256(manifest_bytes)}  manifest.json\n"
        f"{_sha256(files_tar)}  files.tar.gz\n"
    ).encode()

    sbom = json.dumps({"bomFormat": "CycloneDX", "specVersion": "1.4",
                        "components": [{"name": "busybox", "version": BUSYBOX_VERSION}]},
                       indent=2).encode()

    checksums = (
        f"{_sha256(manifest_bytes)}  manifest.json\n"
        f"{_sha256(files_tar)}  files.tar.gz\n"
        f"{_sha256(sbom)}  sbom.json\n"
    ).encode()

    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", manifest_bytes)
        zf.writestr("files.tar.gz", files_tar)
        zf.writestr("checksums.sha256", checksums)
        zf.writestr("sbom.json", sbom)

    return zip_buf.getvalue()


def build_busybox(
    *,
    arch: str,
    store_root: Path,
    db_url: str | None = None,
    jobs: int = 1,
) -> BusyboxBuildResult:
    """Build BusyBox statically and ingest as a package artifact.

    If the artifact already exists in the store (by ``store_key``) the
    build is skipped and the cached artifact is returned immediately.

    Parameters
    ----------
    arch:
        Target architecture string (e.g. ``"aarch64"``).
    store_root:
        Artifact store root directory.
    db_url:
        SQLAlchemy database URL.
    jobs:
        Number of parallel make jobs.

    Returns
    -------
    BusyboxBuildResult
        ``success=True`` with ``artifact_id`` set on success.
    """
    logs: list[str] = []
    store_key = _store_key(arch)

    # ---- cache check ----
    if db_url is not None:
        with sync_session(db_url) as session:
            existing = session.scalar(select(Artifact).where(Artifact.store_key == store_key))
            if existing is not None:
                logs.append(f"[busybox] cache hit: {existing.id[:8]}")
                return BusyboxBuildResult(
                    success=True, artifact_id=existing.id, logs=logs, cache_hit=True
                )

    logs.append(f"[busybox] downloading source {BUSYBOX_URL}")
    try:
        req = urllib.request.Request(BUSYBOX_URL, headers={"User-Agent": "osfabricum/1.0"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            tarball = resp.read()
    except Exception as exc:
        return BusyboxBuildResult(success=False, error=f"download failed: {exc}", logs=logs)

    logs.append(f"[busybox] downloaded {len(tarball)} bytes")

    tmp = tempfile.mkdtemp(prefix="osfab-busybox-")
    src_dir: Path | None = None
    try:
        # ---- extract ----
        with tarfile.open(fileobj=io.BytesIO(tarball), mode="r:bz2") as tar:
            tar.extractall(path=tmp, filter="data")
        entries = list(Path(tmp).iterdir())
        src_dir = entries[0] if len(entries) == 1 and entries[0].is_dir() else Path(tmp)
        logs.append(f"[busybox] extracted to {src_dir}")

        # ---- configure ----
        _run(["make", "defconfig"], cwd=src_dir, logs=logs)

        # Append config fragment and merge
        with open(src_dir / ".config", "a") as f:
            f.write(_CONFIG_FRAGMENT)
        _run(["make", "olddefconfig"], cwd=src_dir, logs=logs)

        # ---- compile ----
        logs.append(f"[busybox] compiling with -j{jobs}…")
        _run(["make", f"-j{jobs}"], cwd=src_dir, logs=logs)

        # ---- install ----
        destdir = Path(tmp) / "destdir"
        destdir.mkdir()
        env = {"CONFIG_PREFIX": str(destdir), "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"}
        _run(["make", f"CONFIG_PREFIX={destdir}", "install"], cwd=src_dir, logs=logs, extra_env=env)
        logs.append(f"[busybox] installed to {destdir}")

        # Ensure /sbin/init symlink exists
        sbin = destdir / "sbin"
        sbin.mkdir(exist_ok=True)
        init_link = sbin / "init"
        if not init_link.exists():
            init_link.symlink_to("/bin/busybox")

        # ---- package ----
        ofpkg_data = _pack_ofpkg(destdir, arch)
        logs.append(f"[busybox] packaged {len(ofpkg_data)} bytes")

        # ---- ingest ----
        artifact = ingest_blob(
            data=ofpkg_data,
            store_root=store_root,
            store_key=store_key,
            kind="package",
            name="busybox",
            version=BUSYBOX_VERSION,
            arch=arch,
            media_type="application/zip",
            db_url=db_url,
            retention_class="permanent",
            input_hash=hashlib.sha256(tarball).hexdigest(),
        )
        logs.append(f"[busybox] artifact ingested: {artifact.id}")
        return BusyboxBuildResult(success=True, artifact_id=artifact.id, logs=logs)

    except Exception as exc:
        return BusyboxBuildResult(success=False, error=str(exc), logs=logs)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _run(
    cmd: list[str],
    *,
    cwd: Path,
    logs: list[str],
    extra_env: dict[str, str] | None = None,
) -> None:
    import os as _os
    env = dict(_os.environ)
    if extra_env:
        env.update(extra_env)
    result = subprocess.run(
        cmd,
        cwd=str(cwd),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    # Log last 20 lines to avoid flooding
    out_lines = (result.stdout or "").splitlines()
    for line in out_lines[-20:]:
        logs.append(f"[busybox]   {line}")
    if result.returncode != 0:
        raise RuntimeError(
            f"command failed (exit {result.returncode}): {' '.join(cmd)}\n"
            + "\n".join(out_lines[-30:])
        )
