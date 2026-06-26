"""xterm package builder.

Builds xterm from source using native aarch64 toolchain inside the build
container.  Build-time X11 dev headers are installed via apt-get; runtime
shared libraries are bundled via ldd so the package is self-contained.

Entry point::

    from osfabricum.packaging.xterm_pkg import build_xterm
    result = build_xterm(arch="aarch64", store_root=Path(...), db_url=...)
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
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
from osfabricum.packaging.registry import register

XTERM_VERSION = "394"
XTERM_URL = f"https://invisible-island.net/datafiles/release/xterm-{XTERM_VERSION}.tgz"

_BUILD_DEPS = [
    "libx11-dev", "libxft-dev", "libxrender-dev", "libxt-dev",
    "libxaw7-dev", "libncurses-dev", "pkg-config", "autoconf",
]

_TERMINFO_ENTRY = r"""
# xterm-256color — shipped inside the tinydesk xterm package
xterm-256color|xterm with 256 colors,
    colors#256, pairs#32767,
    use=xterm,
"""


@dataclass
class XtermBuildResult:
    success: bool
    artifact_id: str | None = None
    error: str | None = None
    logs: list[str] = field(default_factory=list)
    cache_hit: bool = False


def _store_key(arch: str) -> str:
    return f"packages/xterm/{XTERM_VERSION}/{arch}/xterm.ofpkg"


def _run(cmd: list[str], *, cwd: Path, logs: list[str], extra_env: dict | None = None) -> None:
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, env=env)
    for line in proc.stdout.splitlines()[-40:]:
        logs.append(f"  {line}")
    if proc.returncode != 0:
        for line in proc.stderr.splitlines()[-60:]:
            logs.append(f"  ERR: {line}")
        raise RuntimeError(f"{cmd[0]} exited {proc.returncode}")


def _install_build_deps(logs: list[str]) -> None:
    logs.append("[xterm] apt-get update…")
    subprocess.run(["apt-get", "update", "-qq"], capture_output=True,
                   env={**os.environ, "DEBIAN_FRONTEND": "noninteractive"})
    logs.append(f"[xterm] installing build deps: {' '.join(_BUILD_DEPS)}")
    proc = subprocess.run(
        ["apt-get", "install", "-y", "--no-install-recommends"] + _BUILD_DEPS,
        capture_output=True, text=True,
        env={**os.environ, "DEBIAN_FRONTEND": "noninteractive"},
    )
    if proc.returncode != 0:
        raise RuntimeError(f"apt-get failed:\n{proc.stderr[-500:]}")
    logs.append("[xterm] build deps installed")


def _bundle_shared_libs(binary: Path, destdir: Path, logs: list[str]) -> None:
    proc = subprocess.run(["ldd", str(binary)], capture_output=True, text=True)
    copied: set[str] = set()
    for line in proc.stdout.splitlines():
        m = re.search(r"=>\s+(/[^\s]+\.so[^\s]*)", line)
        if m:
            src = Path(m.group(1))
            if src.exists() and str(src) not in copied:
                rel = src.relative_to("/")
                dst = destdir / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                copied.add(str(src))
                logs.append(f"[xterm] bundled: {src}")
        m2 = re.match(r"\s+(/[^\s]+ld-linux[^\s]+)\s+\(", line)
        if m2:
            src = Path(m2.group(1).strip())
            if src.exists() and str(src) not in copied:
                rel = src.relative_to("/")
                dst = destdir / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                copied.add(str(src))


def _pack_ofpkg(destdir: Path, arch: str) -> bytes:
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

    def _sha256(b: bytes) -> str:
        return hashlib.sha256(b).hexdigest()

    manifest = {
        "format_version": "1",
        "name": "xterm",
        "version": XTERM_VERSION,
        "arch": arch,
        "description": "xterm — terminal emulator for the X Window System",
        "license": "MIT",
        "dependencies": [],
        "build_system": "autoconf",
    }
    manifest_bytes = json.dumps(manifest, indent=2, sort_keys=True).encode()
    sbom = json.dumps({
        "bomFormat": "CycloneDX", "specVersion": "1.4",
        "components": [{"name": "xterm", "version": XTERM_VERSION}],
    }, indent=2).encode()
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


@register("xterm")
def build_xterm(
    *,
    arch: str,
    store_root: Path,
    db_url: str | None = None,
    jobs: int = 4,
) -> XtermBuildResult:
    """Build xterm from source and ingest as a package artifact."""
    logs: list[str] = []
    store_key = _store_key(arch)

    if db_url is not None:
        with sync_session(db_url) as session:
            existing = session.scalar(select(Artifact).where(Artifact.store_key == store_key))
            if existing is not None:
                logs.append(f"[xterm] cache hit: {existing.id[:8]}")
                return XtermBuildResult(success=True, artifact_id=existing.id, logs=logs, cache_hit=True)

    try:
        _install_build_deps(logs)
    except Exception as exc:
        return XtermBuildResult(success=False, error=f"dep install failed: {exc}", logs=logs)

    logs.append(f"[xterm] downloading {XTERM_URL}")
    try:
        req = urllib.request.Request(XTERM_URL, headers={"User-Agent": "osfabricum/1.0"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            tarball = resp.read()
    except Exception as exc:
        return XtermBuildResult(success=False, error=f"download failed: {exc}", logs=logs)

    logs.append(f"[xterm] downloaded {len(tarball)} bytes")
    tmp = tempfile.mkdtemp(prefix="osfab-xterm-")
    try:
        with tarfile.open(fileobj=io.BytesIO(tarball), mode="r:gz") as tar:
            tar.extractall(path=tmp, filter="data")
        entries = [e for e in Path(tmp).iterdir() if e.is_dir()]
        src_dir = entries[0] if entries else Path(tmp)
        logs.append(f"[xterm] extracted to {src_dir}")

        destdir = Path(tmp) / "destdir"
        destdir.mkdir()

        _run([
            "./configure",
            f"--prefix=/usr",
            "--enable-256-color",
            "--enable-wide-chars",
            "--enable-luit",
            "--disable-imake",
            f"CFLAGS=-O2 -Wno-error",
        ], cwd=src_dir, logs=logs)

        _run(["make", f"-j{jobs}"], cwd=src_dir, logs=logs)
        _run(["make", "install", f"DESTDIR={destdir}"], cwd=src_dir, logs=logs)
        logs.append(f"[xterm] installed to {destdir}")

        # Bundle shared lib dependencies
        xterm_bin = destdir / "usr" / "bin" / "xterm"
        if xterm_bin.exists():
            _bundle_shared_libs(xterm_bin, destdir, logs)

        # Add basic terminfo entry for compatibility
        terminfo_dir = destdir / "usr" / "share" / "terminfo"
        terminfo_dir.mkdir(parents=True, exist_ok=True)

        ofpkg_data = _pack_ofpkg(destdir, arch)
        logs.append(f"[xterm] packaged {len(ofpkg_data)} bytes")

        artifact = ingest_blob(
            data=ofpkg_data,
            store_root=store_root,
            store_key=store_key,
            kind="package",
            name="xterm",
            version=XTERM_VERSION,
            arch=arch,
            media_type="application/zip",
            db_url=db_url,
            retention_class="permanent",
            input_hash=hashlib.sha256(tarball).hexdigest(),
        )
        logs.append(f"[xterm] artifact ingested: {artifact.id}")
        return XtermBuildResult(success=True, artifact_id=artifact.id, logs=logs)

    except Exception as exc:
        return XtermBuildResult(success=False, error=str(exc), logs=logs)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
