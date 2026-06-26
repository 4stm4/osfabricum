"""Xorg server package builder.

Builds xorg-server 21.1.x from source using the meson build system natively
on aarch64.  Ships only the modesetting DDX driver (built-in) which works on
any KMS/DRM-capable GPU including the Mali GPU found on Orange Pi boards via
the Panfrost/Lima kernel driver.  Also packages xf86-video-fbdev as a
fallback for purely framebuffer-based output.

Runtime shared libraries are bundled via ldd; xkb keyboard data is copied
from the system so keyboard layouts work out of the box.

Entry point::

    from osfabricum.packaging.xorgserver import build_xorgserver
    result = build_xorgserver(arch="aarch64", store_root=Path(...), db_url=...)
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

XORG_SERVER_VERSION = "21.1.11"
XORG_SERVER_URL = (
    f"https://www.x.org/releases/individual/xserver/"
    f"xorg-server-{XORG_SERVER_VERSION}.tar.xz"
)

FBDEV_VERSION = "0.5.0"
FBDEV_URL = (
    f"https://www.x.org/releases/individual/driver/"
    f"xf86-video-fbdev-{FBDEV_VERSION}.tar.gz"
)

XINIT_VERSION = "1.4.2"
XINIT_URL = (
    f"https://www.x.org/releases/individual/app/"
    f"xinit-{XINIT_VERSION}.tar.xz"
)

_BUILD_DEPS = [
    # Meson build system
    "meson", "ninja-build", "pkg-config",
    # X protocol + libs
    "xserver-xorg-dev", "x11proto-dev",
    "libx11-dev", "libxau-dev", "libxdmcp-dev", "libxext-dev",
    "libxfont-dev", "libxkbfile-dev", "libxkbcommon-dev",
    # DRM / GBM / pixman
    "libdrm-dev", "libgbm-dev", "libpixman-1-dev",
    # EGL / GL
    "libgl-dev", "libegl-dev", "libgles-dev",
    # Misc
    "libbsd-dev", "libssl-dev", "libzstd-dev",
    "libxshmfence-dev", "libdbus-1-dev",
    # xkb data (runtime + build)
    "xkb-data", "x11-xkb-utils",
    # xinit dependencies
    "libx11-dev",
    # for autoconf-based sub-packages (fbdev, xinit)
    "autoconf", "automake", "libtool",
    # font support — fontutil.pc is in xfonts-utils
    "libfreetype-dev", "libfontconfig-dev", "xfonts-utils",
]

# Minimal /etc/X11/xorg.conf using the modesetting (KMS) driver
_XORG_CONF = """\
Section "ServerFlags"
    Option "AutoAddGPU"    "on"
    Option "AutoEnableDevices" "on"
EndSection

Section "InputClass"
    Identifier "libinput"
    MatchIsPointer "on"
    Driver "libinput"
EndSection

Section "InputClass"
    Identifier "libinput keyboard"
    MatchIsKeyboard "on"
    Driver "libinput"
    Option "XkbLayout" "us"
EndSection

Section "Device"
    Identifier "modesetting"
    Driver "modesetting"
    Option "AccelMethod" "none"
EndSection

Section "Screen"
    Identifier "screen0"
    Device "modesetting"
    DefaultDepth 24
    SubSection "Display"
        Depth 24
        Modes "1920x1080" "1280x720" "1024x768" "800x600"
    EndSubSection
EndSection
"""

# Fallback xorg.conf using fbdev (when KMS is not available)
_XORG_CONF_FBDEV = """\
Section "Device"
    Identifier "fbdev"
    Driver "fbdev"
    Option "fbdev" "/dev/fb0"
EndSection

Section "Screen"
    Identifier "screen0"
    Device "fbdev"
    DefaultDepth 24
EndSection
"""

# /root/.xinitrc — starts openbox desktop session
_XINITRC = """\
#!/bin/sh
# /root/.xinitrc — X session startup

# Set background
xsetroot -solid '#1a1a2e' &

# Start Openbox window manager
exec openbox-session
"""

# /etc/init.d/S99desktop — starts X on tty1 at boot
_S99_DESKTOP = """\
#!/bin/sh
# /etc/init.d/S99desktop — Start X desktop session on tty1

case "$1" in
start)
    if [ ! -f /tmp/.X0-lock ]; then
        export DISPLAY=:0
        export HOME=/root
        export TERM=xterm
        startx /root/.xinitrc -- :0 vt1 -nolisten tcp &
        echo "Desktop started on :0"
    fi
    ;;
stop)
    pkill -f "Xorg :0" 2>/dev/null || true
    ;;
restart)
    "$0" stop; sleep 2; "$0" start
    ;;
esac
"""


@dataclass
class XorgBuildResult:
    success: bool
    artifact_id: str | None = None
    error: str | None = None
    logs: list[str] = field(default_factory=list)
    cache_hit: bool = False


def _store_key(arch: str) -> str:
    return f"packages/xorg-server/{XORG_SERVER_VERSION}-v4/{arch}/xorg-server.ofpkg"


def _run(cmd: list[str], *, cwd: Path, logs: list[str],
         extra_env: dict | None = None, tag: str = "xorg") -> None:
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, env=env)
    for line in proc.stdout.splitlines()[-40:]:
        logs.append(f"  {line}")
    if proc.returncode != 0:
        for line in proc.stderr.splitlines()[-80:]:
            logs.append(f"  ERR: {line}")
        raise RuntimeError(f"[{tag}] {cmd[0]} exited {proc.returncode}")


def _install_build_deps(logs: list[str]) -> None:
    logs.append("[xorg] apt-get update…")
    subprocess.run(["apt-get", "update", "-qq"], capture_output=True,
                   env={**os.environ, "DEBIAN_FRONTEND": "noninteractive"})
    logs.append("[xorg] installing build deps (this may take a few minutes)…")
    proc = subprocess.run(
        ["apt-get", "install", "-y", "--no-install-recommends"] + _BUILD_DEPS,
        capture_output=True, text=True,
        env={**os.environ, "DEBIAN_FRONTEND": "noninteractive"},
    )
    if proc.returncode != 0:
        raise RuntimeError(f"apt-get failed:\n{proc.stderr[-500:]}")
    logs.append("[xorg] build deps installed")


def _bundle_shared_libs(binary: Path, destdir: Path, logs: list[str],
                        tag: str = "xorg") -> None:
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
                logs.append(f"[{tag}] bundled: {src}")
        m2 = re.match(r"\s+(/[^\s]+ld-linux[^\s]+)\s+\(", line)
        if m2:
            src = Path(m2.group(1).strip())
            if src.exists() and str(src) not in copied:
                rel = src.relative_to("/")
                dst = destdir / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                copied.add(str(src))


def _copy_xkb_data(destdir: Path, logs: list[str]) -> None:
    """Copy XKB keyboard data from the system into the package."""
    xkb_src = Path("/usr/share/X11/xkb")
    xkb_dst = destdir / "usr" / "share" / "X11" / "xkb"
    if xkb_src.exists():
        shutil.copytree(xkb_src, xkb_dst, dirs_exist_ok=True)
        logs.append(f"[xorg] copied XKB data ({xkb_src})")
    else:
        logs.append("[xorg] WARNING: XKB data not found at /usr/share/X11/xkb")


def _copy_xkbcomp(destdir: Path, logs: list[str]) -> None:
    """Copy xkbcomp binary needed for keyboard layout compilation."""
    for candidate in ["/usr/bin/xkbcomp", "/usr/local/bin/xkbcomp"]:
        src = Path(candidate)
        if src.exists():
            dst = destdir / "usr" / "bin" / "xkbcomp"
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            dst.chmod(0o755)
            _bundle_shared_libs(dst, destdir, logs, tag="xkbcomp")
            logs.append(f"[xorg] copied xkbcomp from {src}")
            return
    logs.append("[xorg] WARNING: xkbcomp not found")


def _download(url: str, logs: list[str], tag: str = "xorg") -> bytes:
    logs.append(f"[{tag}] downloading {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "osfabricum/1.0"})
    with urllib.request.urlopen(req, timeout=600) as resp:
        data = resp.read()
    logs.append(f"[{tag}] downloaded {len(data)} bytes")
    return data


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
        "name": "xorg-server",
        "version": XORG_SERVER_VERSION,
        "arch": arch,
        "description": "Xorg X11 server with modesetting/fbdev drivers",
        "license": "MIT",
        "dependencies": [],
        "build_system": "meson",
    }
    manifest_bytes = json.dumps(manifest, indent=2, sort_keys=True).encode()
    sbom = json.dumps({
        "bomFormat": "CycloneDX", "specVersion": "1.4",
        "components": [
            {"name": "xorg-server", "version": XORG_SERVER_VERSION},
            {"name": "xf86-video-fbdev", "version": FBDEV_VERSION},
        ],
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


@register("xorg-server")
def build_xorgserver(
    *,
    arch: str,
    store_root: Path,
    db_url: str | None = None,
    jobs: int = 4,
) -> XorgBuildResult:
    """Build Xorg server + fbdev driver from source; ingest as package artifact."""
    logs: list[str] = []
    store_key = _store_key(arch)

    if db_url is not None:
        with sync_session(db_url) as session:
            existing = session.scalar(select(Artifact).where(Artifact.store_key == store_key))
            if existing is not None:
                logs.append(f"[xorg] cache hit: {existing.id[:8]}")
                return XorgBuildResult(success=True, artifact_id=existing.id, logs=logs, cache_hit=True)

    try:
        _install_build_deps(logs)
    except Exception as exc:
        return XorgBuildResult(success=False, error=f"dep install failed: {exc}", logs=logs)

    tmp = tempfile.mkdtemp(prefix="osfab-xorg-")
    destdir = Path(tmp) / "destdir"
    destdir.mkdir()

    try:
        # ---- Build xorg-server ----
        tarball = _download(XORG_SERVER_URL, logs)
        src = Path(tmp) / "xorg-server-src"
        src.mkdir()
        with tarfile.open(fileobj=io.BytesIO(tarball), mode="r:xz") as t:
            t.extractall(path=str(src), filter="data")
        entries = [e for e in src.iterdir() if e.is_dir()]
        xsrc = entries[0] if entries else src

        build_dir = xsrc / "_build"
        _run([
            "meson", "setup", str(build_dir),
            f"--prefix=/usr",
            f"--sysconfdir=/etc",
            f"--localstatedir=/var",
            "-Dxvfb=false",
            "-Dglamor=true",
            "-Dxf86bigfont=false",
            "-Dxdm-auth-1=false",
            "-Dxcsecurity=false",
            "-Dsecure-rpc=false",
            "-Dipv6=true",
        ], cwd=xsrc, logs=logs)

        _run(["ninja", f"-j{jobs}", "-C", str(build_dir)], cwd=xsrc, logs=logs)
        _run(["ninja", "-C", str(build_dir), "install",
              f"DESTDIR={destdir}"], cwd=xsrc, logs=logs)
        logs.append("[xorg] xorg-server installed")

        # Bundle runtime .so for the Xorg binary
        xorg_bin = destdir / "usr" / "bin" / "Xorg"
        if xorg_bin.exists():
            _bundle_shared_libs(xorg_bin, destdir, logs)

        # ---- Build xf86-video-fbdev ----
        fbdev_tarball = _download(FBDEV_URL, logs, tag="fbdev")
        fbsrc = Path(tmp) / "fbdev-src"
        fbsrc.mkdir()
        with tarfile.open(fileobj=io.BytesIO(fbdev_tarball), mode="r:gz") as t:
            t.extractall(path=str(fbsrc), filter="data")
        fbentries = [e for e in fbsrc.iterdir() if e.is_dir()]
        fbdir = fbentries[0] if fbentries else fbsrc

        for _cfg in ("config.guess", "config.sub"):
            _sys = Path("/usr/share/misc") / _cfg
            if _sys.exists():
                shutil.copy2(_sys, fbdir / _cfg)
                (fbdir / _cfg).chmod(0o755)

        _run(["./configure", "--prefix=/usr", f"CFLAGS=-O2 -Wno-error"],
             cwd=fbdir, logs=logs, tag="fbdev")
        _run(["make", f"-j{jobs}"], cwd=fbdir, logs=logs, tag="fbdev")
        _run(["make", "install", f"DESTDIR={destdir}"], cwd=fbdir, logs=logs, tag="fbdev")
        logs.append("[xorg] xf86-video-fbdev installed")

        # ---- Build xinit (startx command) ----
        xinit_tarball = _download(XINIT_URL, logs, tag="xinit")
        xinit_src = Path(tmp) / "xinit-src"
        xinit_src.mkdir()
        with tarfile.open(fileobj=io.BytesIO(xinit_tarball), mode="r:xz") as t:
            t.extractall(path=str(xinit_src), filter="data")
        xinit_entries = [e for e in xinit_src.iterdir() if e.is_dir()]
        xinit_dir = xinit_entries[0] if xinit_entries else xinit_src

        _run(["./configure", "--prefix=/usr", f"CFLAGS=-O2"],
             cwd=xinit_dir, logs=logs, tag="xinit")
        _run(["make", f"-j{jobs}"], cwd=xinit_dir, logs=logs, tag="xinit")
        _run(["make", "install", f"DESTDIR={destdir}"], cwd=xinit_dir, logs=logs, tag="xinit")
        logs.append("[xorg] xinit (startx) installed")

        # ---- Copy XKB data and xkbcomp ----
        _copy_xkb_data(destdir, logs)
        _copy_xkbcomp(destdir, logs)

        # ---- Write config + init files ----
        x11_conf_dir = destdir / "etc" / "X11"
        x11_conf_dir.mkdir(parents=True, exist_ok=True)
        (x11_conf_dir / "xorg.conf").write_text(_XORG_CONF)

        xorg_confd = x11_conf_dir / "xorg.conf.d"
        xorg_confd.mkdir(exist_ok=True)
        (xorg_confd / "20-fbdev-fallback.conf").write_text(_XORG_CONF_FBDEV)

        # /root/.xinitrc — desktop session startup
        root_dir = destdir / "root"
        root_dir.mkdir(exist_ok=True)
        xinitrc = root_dir / ".xinitrc"
        xinitrc.write_text(_XINITRC)
        xinitrc.chmod(0o755)

        # Init script — starts X at boot
        initd = destdir / "etc" / "init.d"
        initd.mkdir(parents=True, exist_ok=True)
        s99 = initd / "S99desktop"
        s99.write_text(_S99_DESKTOP)
        s99.chmod(0o755)

        # Ensure /tmp/.ICE-unix directory exists at boot
        tmpdir = destdir / "tmp"
        tmpdir.mkdir(exist_ok=True)

        logs.append(f"[xorg] destdir size: {_dir_size_mb(destdir):.1f} MB")

        ofpkg_data = _pack_ofpkg(destdir, arch)
        logs.append(f"[xorg] packaged {len(ofpkg_data) // 1_048_576:.1f} MB")

        artifact = ingest_blob(
            data=ofpkg_data,
            store_root=store_root,
            store_key=store_key,
            kind="package",
            name="xorg-server",
            version=XORG_SERVER_VERSION,
            arch=arch,
            media_type="application/zip",
            db_url=db_url,
            retention_class="permanent",
            input_hash=hashlib.sha256(tarball).hexdigest(),
        )
        logs.append(f"[xorg] artifact ingested: {artifact.id}")
        return XorgBuildResult(success=True, artifact_id=artifact.id, logs=logs)

    except Exception as exc:
        return XorgBuildResult(success=False, error=str(exc), logs=logs)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _dir_size_mb(path: Path) -> float:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) / 1_048_576
