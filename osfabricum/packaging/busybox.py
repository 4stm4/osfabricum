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
from osfabricum.packaging.registry import register
from osfabricum.store.ingest import ingest_blob

BUSYBOX_VERSION = "1.37.0"
BUSYBOX_URL = (
    f"https://busybox.net/downloads/busybox-{BUSYBOX_VERSION}.tar.bz2"
)

# Minimal .config fragment — static build, no Linux module utilities
# (those require kernel headers we don't ship).
# Minimal embedded config — used with "make allnoconfig" so EVERY option is
# explicitly listed.  This avoids compile errors in optional applets that
# require obscure kernel headers (i2c_tools.c, tc.c, etc.).
_MINIMAL_CONFIG = """\
CONFIG_STATIC=y
CONFIG_STATIC_LIBGCC=y
CONFIG_LFS=y
CONFIG_FEATURE_INSTALLER=y
CONFIG_DESKTOP=y
CONFIG_EXTRA_COMPAT=y
CONFIG_INCLUDE_SUSv2=y

# Shell
CONFIG_ASH=y
CONFIG_ASH_BASH_COMPAT=y
CONFIG_ASH_JOB_CONTROL=y
CONFIG_ASH_ALIAS=y
CONFIG_ASH_BUILTIN_ECHO=y
CONFIG_ASH_BUILTIN_PRINTF=y
CONFIG_ASH_BUILTIN_TEST=y
CONFIG_ASH_CMDCMD=y
CONFIG_FEATURE_SH_EXTRA_QUIET=y
CONFIG_SH_IS_ASH=y
CONFIG_BASH_IS_NONE=y

# Coreutils
CONFIG_LS=y
CONFIG_FEATURE_LS_FILETYPES=y
CONFIG_FEATURE_LS_SORTFILES=y
CONFIG_FEATURE_LS_TIMESTAMPS=y
CONFIG_FEATURE_LS_COLOR=y
CONFIG_ECHO=y
CONFIG_FEATURE_FANCY_ECHO=y
CONFIG_CAT=y
CONFIG_CP=y
CONFIG_FEATURE_CP_LONG_OPTIONS=y
CONFIG_MV=y
CONFIG_RM=y
CONFIG_MKDIR=y
CONFIG_RMDIR=y
CONFIG_LN=y
CONFIG_CHMOD=y
CONFIG_CHOWN=y
CONFIG_TOUCH=y
CONFIG_STAT=y
CONFIG_FEATURE_STAT_FORMAT=y
CONFIG_TEST=y
CONFIG_PRINTF=y
CONFIG_PWD=y
CONFIG_WHOAMI=y
CONFIG_DATE=y
CONFIG_FEATURE_DATE_ISOFMT=y
CONFIG_SORT=y
CONFIG_UNIQ=y
CONFIG_WC=y
CONFIG_HEAD=y
CONFIG_TAIL=y
CONFIG_CUT=y
CONFIG_TR=y
CONFIG_BASENAME=y
CONFIG_DIRNAME=y
CONFIG_ID=y
CONFIG_GROUPS=y
CONFIG_FIND=y
CONFIG_FEATURE_FIND_TYPE=y
CONFIG_FEATURE_FIND_EXEC=y
CONFIG_XARGS=y
CONFIG_ENV=y
CONFIG_EXPR=y
CONFIG_TRUE=y
CONFIG_FALSE=y
CONFIG_YES=y
CONFIG_TEE=y
CONFIG_SEQ=y
CONFIG_SHUF=y
CONFIG_NPROC=y

# Text tools
CONFIG_GREP=y
CONFIG_EGREP=y
CONFIG_FGREP=y
CONFIG_FEATURE_GREP_CONTEXT=y
CONFIG_SED=y
CONFIG_AWK=y
CONFIG_DIFF=y
CONFIG_PATCH=y

# File tools
CONFIG_TAR=y
CONFIG_FEATURE_TAR_CREATE=y
CONFIG_FEATURE_TAR_GZIP=y
CONFIG_FEATURE_TAR_BZIP2=y
CONFIG_GZIP=y
CONFIG_GUNZIP=y
CONFIG_ZCAT=y
CONFIG_BZIP2=y
CONFIG_BZCAT=y
CONFIG_XZ=y
CONFIG_UNXZ=y
CONFIG_CPIO=y
CONFIG_DD=y
CONFIG_DU=y
CONFIG_DF=y
CONFIG_SYNC=y
CONFIG_MD5SUM=y
CONFIG_SHA1SUM=y
CONFIG_SHA256SUM=y
CONFIG_FILE=y

# Init
CONFIG_INIT=y
CONFIG_FEATURE_USE_INITTAB=y
CONFIG_FEATURE_INIT_SYSLOG=y
CONFIG_GETTY=y
CONFIG_LOGIN=y
CONFIG_FEATURE_NOLOGIN=y
CONFIG_SU=y

# Process tools
CONFIG_PS=y
CONFIG_FEATURE_PS_WIDE=y
CONFIG_TOP=y
CONFIG_KILL=y
CONFIG_KILLALL=y
CONFIG_SLEEP=y
CONFIG_FEATURE_FANCY_SLEEP=y
CONFIG_USLEEP=y
CONFIG_TIMEOUT=y
CONFIG_NICE=y
CONFIG_NOHUP=y

# Network
CONFIG_PING=y
CONFIG_FEATURE_FANCY_PING=y
CONFIG_WGET=y
CONFIG_FEATURE_WGET_HTTPS=y
CONFIG_FEATURE_WGET_OPENSSL=n
CONFIG_FEATURE_WGET_STATUSBAR=y
CONFIG_NETSTAT=y
CONFIG_IFCONFIG=y
CONFIG_IP=y
CONFIG_FEATURE_IP_ADDRESS=y
CONFIG_FEATURE_IP_ROUTE=y
CONFIG_FEATURE_IP_LINK=y
CONFIG_FEATURE_IP_TUNNEL=y
CONFIG_UDHCPC=y
CONFIG_FEATURE_UDHCPC_ARPING=y
CONFIG_UDHCPD=y
CONFIG_FEATURE_UDHCPD_BASE=y

# Misc
CONFIG_DMESG=y
CONFIG_UNAME=y
CONFIG_REBOOT=y
CONFIG_HALT=y
CONFIG_POWEROFF=y
CONFIG_MOUNT=y
CONFIG_FEATURE_MOUNT_FLAGS=y
CONFIG_FEATURE_MOUNT_LABEL=y
CONFIG_UMOUNT=y
CONFIG_SYSCTL=y
CONFIG_MODINFO=n
CONFIG_INSMOD=n
CONFIG_RMMOD=n
CONFIG_LSMOD=n
CONFIG_DEPMOD=n
CONFIG_FREE=y
CONFIG_UPTIME=y
CONFIG_CLEAR=y
CONFIG_STTY=y
CONFIG_LESS=y
CONFIG_HEXDUMP=y
CONFIG_XXDUMP=n
CONFIG_VI=y

# System
CONFIG_HOSTNAME=y
CONFIG_DNSDOMAINNAME=y
CONFIG_FDISK=y
CONFIG_FDISK_SUPPORT_LARGE_DISKS=y
CONFIG_MKSWAP=y
CONFIG_SWAPON=y
CONFIG_SWAPOFF=y
CONFIG_LOSETUP=y
CONFIG_BLKID=y
CONFIG_MDEV=y
CONFIG_FEATURE_MDEV_CONF=y
CONFIG_FEATURE_MDEV_DAEMON=y

# Password / shadow
CONFIG_FEATURE_DEFAULT_PASSWD_ALGO="md5"
CONFIG_PASSWD=y
CONFIG_ADDUSER=y
CONFIG_ADDGROUP=y
CONFIG_DELUSER=y
CONFIG_DELGROUP=y
"""


@dataclass
class BusyboxBuildResult:
    success: bool
    artifact_id: str | None = None
    error: str | None = None
    logs: list[str] = field(default_factory=list)
    cache_hit: bool = False


def _patch_busybox_config(config_path: Path) -> None:
    """Patch defconfig: enable static, disable applets with compile issues."""
    text = config_path.read_text()

    # Options to SET to y
    enable = [
        "CONFIG_STATIC",
        "CONFIG_STATIC_LIBGCC",
        "CONFIG_LFS",
        "CONFIG_FEATURE_INSTALLER",
    ]
    # Options to SET to n (have compile issues or need obscure kernel headers)
    # These are known to fail on GCC 13+/14 in BusyBox 1.37.0
    disable = [
        "CONFIG_TC",           # tc.c: needs kernel TC/CBQ headers (struct tc_cbq_wrropt undefined)
        "CONFIG_I2CGET",       # i2c_tools.c: format-string issues on GCC 13+
        "CONFIG_I2CSET",
        "CONFIG_I2CDUMP",
        "CONFIG_I2CDETECT",
        "CONFIG_I2CTRANSFER",
        "CONFIG_TFTP",         # tftp.c: uses char *x = x; self-init trick rejected by GCC 14
        "CONFIG_TFTPD",
        "CONFIG_MODPROBE_SMALL",
        "CONFIG_DEPMOD",
        "CONFIG_INSMOD",
        "CONFIG_RMMOD",
        "CONFIG_LSMOD",
        "CONFIG_MODINFO",
        "CONFIG_FEATURE_MODPROBE_BLACKLIST",
    ]
    # String values to SET
    set_values: dict[str, str] = {
        # Suppress all warnings-as-errors to handle GCC version differences
        "CONFIG_EXTRA_CFLAGS": '"-Wno-error"',
    }

    lines = text.splitlines()
    result = []
    seen: set[str] = set()

    for line in lines:
        # Match "CONFIG_FOO=..." or "# CONFIG_FOO is not set"
        matched_key: str | None = None
        for key in list(enable) + list(disable) + list(set_values):
            if line.startswith(f"{key}=") or line == f"# {key} is not set":
                matched_key = key
                break
        if matched_key:
            if matched_key not in seen:
                seen.add(matched_key)
                if matched_key in set_values:
                    result.append(f"{matched_key}={set_values[matched_key]}")
                elif matched_key in enable:
                    result.append(f"{matched_key}=y")
                else:
                    result.append(f"# {matched_key} is not set")
            # drop duplicate occurrences
        else:
            result.append(line)

    # Add any entries that weren't found in the original config
    for key in enable:
        if key not in seen:
            result.append(f"{key}=y")
    for key in disable:
        if key not in seen:
            result.append(f"# {key} is not set")
    for key, val in set_values.items():
        if key not in seen:
            result.append(f"{key}={val}")

    config_path.write_text("\n".join(result) + "\n")


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


@register("busybox")
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

        # ---- patch source for GCC 14 compatibility ----
        # BusyBox 1.37.0 has SHA-NI code that fails to compile on GCC 14 when
        # ARM crypto extensions are present: sha1_process_block64_shaNI is called
        # without a declaration being in scope.  Replace with the software path.
        sha_file = src_dir / "libbb" / "hash_md5_sha.c"
        if sha_file.exists():
            sha_src = sha_file.read_text()
            if "sha1_process_block64_shaNI" in sha_src:
                sha_src = sha_src.replace(
                    "sha1_process_block64_shaNI", "sha1_process_block64"
                )
                sha_file.write_text(sha_src)
                logs.append("[busybox] patched hash_md5_sha.c: sha1_process_block64_shaNI → software path")

        # ---- configure ----
        # Start from defconfig (a complete, known-good config) and patch it:
        # enable static linking, disable applets that need obscure kernel headers.
        _run(["make", "defconfig"], cwd=src_dir, logs=logs)
        _patch_busybox_config(src_dir / ".config")

        # ---- compile ----
        # -march=armv8-a: disable ARM crypto extensions (SHA-NI) that cause
        # undeclared-function errors in BusyBox 1.37.0 on GCC 14.
        # -Wno-error: downgrade remaining warnings to non-fatal.
        logs.append(f"[busybox] compiling with -j{jobs}…")
        _run(
            ["make", f"-j{jobs}",
             "EXTRA_CFLAGS=-Wno-error -march=armv8-a"],
            cwd=src_dir, logs=logs,
        )

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
