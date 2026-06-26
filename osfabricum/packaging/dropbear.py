"""Dropbear SSH package builder.

Downloads Dropbear source, compiles a fully static binary (no external deps —
bundled libtomcrypt/libtommath), and packages the result as a ``.ofpkg``
artifact ingested into the artifact store.

The build is cached by ``store_key``; if the artifact already exists the
download and compilation are skipped.

Entry point::

    from osfabricum.packaging.dropbear import build_dropbear
    result = build_dropbear(arch="aarch64", store_root=Path(...), db_url=...)
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
from osfabricum.packaging.registry import register

DROPBEAR_VERSION = "2022.83"
DROPBEAR_URL = (
    f"https://matt.ucc.asn.au/dropbear/releases/dropbear-{DROPBEAR_VERSION}.tar.bz2"
)

_S50_DROPBEAR = """\
#!/bin/sh
# /etc/init.d/S50dropbear — Start Dropbear SSH daemon
PIDFILE=/var/run/dropbear.pid

case "$1" in
start)
    mkdir -p /etc/dropbear /var/run /root/.ssh
    chmod 700 /root
    # -R: generate host keys if missing; -F background after fork
    dropbear -R -p 22 2>/dev/null || true
    ;;
stop)
    kill "$(cat $PIDFILE 2>/dev/null)" 2>/dev/null || true
    ;;
restart)
    "$0" stop; sleep 1; "$0" start
    ;;
esac
"""


@dataclass
class DropbearBuildResult:
    success: bool
    artifact_id: str | None = None
    error: str | None = None
    logs: list[str] = field(default_factory=list)
    cache_hit: bool = False


def _store_key(arch: str) -> str:
    return f"packages/dropbear/{DROPBEAR_VERSION}/{arch}/dropbear.ofpkg"


def _run(cmd: list[str], *, cwd: Path, logs: list[str], extra_env: dict | None = None) -> None:
    import os
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    proc = subprocess.run(
        cmd, cwd=str(cwd), capture_output=True, text=True, env=env
    )
    for line in proc.stdout.splitlines()[-30:]:
        logs.append(f"  {line}")
    if proc.returncode != 0:
        for line in proc.stderr.splitlines()[-50:]:
            logs.append(f"  ERR: {line}")
        raise RuntimeError(f"{cmd[0]} exited {proc.returncode}")


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
        "name": "dropbear",
        "version": DROPBEAR_VERSION,
        "arch": arch,
        "description": "Dropbear SSH server/client — lightweight, static binary",
        "license": "MIT",
        "dependencies": [],
        "build_system": "make",
    }
    manifest_bytes = json.dumps(manifest, indent=2, sort_keys=True).encode()
    sbom = json.dumps({
        "bomFormat": "CycloneDX", "specVersion": "1.4",
        "components": [{"name": "dropbear", "version": DROPBEAR_VERSION}],
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


@register("dropbear")
def build_dropbear(
    *,
    arch: str,
    store_root: Path,
    db_url: str | None = None,
    jobs: int = 1,
) -> DropbearBuildResult:
    """Build Dropbear SSH statically and ingest as a package artifact."""
    logs: list[str] = []
    store_key = _store_key(arch)

    if db_url is not None:
        with sync_session(db_url) as session:
            existing = session.scalar(select(Artifact).where(Artifact.store_key == store_key))
            if existing is not None:
                logs.append(f"[dropbear] cache hit: {existing.id[:8]}")
                return DropbearBuildResult(
                    success=True, artifact_id=existing.id, logs=logs, cache_hit=True
                )

    local_tarball = Path(f"/tmp/dropbear-{DROPBEAR_VERSION}.tar.bz2")
    if local_tarball.exists() and local_tarball.stat().st_size > 100_000:
        logs.append(f"[dropbear] using pre-downloaded {local_tarball}")
        tarball = local_tarball.read_bytes()
    else:
        logs.append(f"[dropbear] downloading {DROPBEAR_URL}")
        try:
            req = urllib.request.Request(DROPBEAR_URL, headers={"User-Agent": "osfabricum/1.0"})
            with urllib.request.urlopen(req, timeout=600) as resp:
                tarball = resp.read()
        except Exception as exc:
            return DropbearBuildResult(success=False, error=f"download failed: {exc}", logs=logs)

    logs.append(f"[dropbear] downloaded {len(tarball)} bytes")
    tmp = tempfile.mkdtemp(prefix="osfab-dropbear-")
    try:
        with tarfile.open(fileobj=io.BytesIO(tarball), mode="r:bz2") as tar:
            tar.extractall(path=tmp, filter="data")
        entries = list(Path(tmp).iterdir())
        src_dir = entries[0] if len(entries) == 1 and entries[0].is_dir() else Path(tmp)
        logs.append(f"[dropbear] extracted to {src_dir}")

        # Static build — dropbear bundles libtomcrypt/libtommath, so no external
        # crypto deps. Disable zlib compression to avoid needing zlib-dev.
        _run(
            [
                "./configure",
                "--prefix=/usr",
                "--disable-zlib",
                "--enable-bundled-libtom",
                "--disable-pam",
                "--disable-lastlog",
                "--disable-wtmp",
                "--disable-utmpx",
                "CFLAGS=-Os -Wno-error",
                "LDFLAGS=-static",
            ],
            cwd=src_dir, logs=logs,
        )
        logs.append(f"[dropbear] compiling with -j{jobs}…")
        _run(
            ["make", f"-j{jobs}", "PROGRAMS=dropbear dropbearkey"],
            cwd=src_dir, logs=logs,
        )

        # ---- install ----
        destdir = Path(tmp) / "destdir"
        destdir.mkdir()
        (destdir / "usr" / "sbin").mkdir(parents=True)
        (destdir / "usr" / "bin").mkdir(parents=True)
        (destdir / "etc" / "dropbear").mkdir(parents=True)
        (destdir / "etc" / "init.d").mkdir(parents=True)
        (destdir / "root" / ".ssh").mkdir(parents=True, mode=0o700)

        shutil.copy2(src_dir / "dropbear", destdir / "usr" / "sbin" / "dropbear")
        (destdir / "usr" / "sbin" / "dropbear").chmod(0o755)
        shutil.copy2(src_dir / "dropbearkey", destdir / "usr" / "bin" / "dropbearkey")
        (destdir / "usr" / "bin" / "dropbearkey").chmod(0o755)

        # Strip static binary to reduce size
        try:
            subprocess.run(["strip", str(destdir / "usr" / "sbin" / "dropbear")], check=False)
            subprocess.run(["strip", str(destdir / "usr" / "bin" / "dropbearkey")], check=False)
        except FileNotFoundError:
            pass

        # Init service script
        s50 = destdir / "etc" / "init.d" / "S50dropbear"
        s50.write_text(_S50_DROPBEAR)
        s50.chmod(0o755)

        logs.append(f"[dropbear] installed to {destdir}")

        ofpkg_data = _pack_ofpkg(destdir, arch)
        logs.append(f"[dropbear] packaged {len(ofpkg_data)} bytes")

        artifact = ingest_blob(
            data=ofpkg_data,
            store_root=store_root,
            store_key=store_key,
            kind="package",
            name="dropbear",
            version=DROPBEAR_VERSION,
            arch=arch,
            media_type="application/zip",
            db_url=db_url,
            retention_class="permanent",
            input_hash=hashlib.sha256(tarball).hexdigest(),
        )
        logs.append(f"[dropbear] artifact ingested: {artifact.id}")
        return DropbearBuildResult(success=True, artifact_id=artifact.id, logs=logs)

    except Exception as exc:
        return DropbearBuildResult(success=False, error=str(exc), logs=logs)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
