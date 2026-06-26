"""Openbox window manager package builder.

Builds Openbox 3.6.1 from source natively on aarch64.  Build-time X11
headers are installed via apt-get; runtime shared libraries are bundled
via ldd.  Ships a minimal rc.xml and right-click menu so the desktop is
usable immediately after boot.

Entry point::

    from osfabricum.packaging.openbox_pkg import build_openbox
    result = build_openbox(arch="aarch64", store_root=Path(...), db_url=...)
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

OPENBOX_VERSION = "3.6.1"
OPENBOX_URL = f"http://openbox.org/dist/openbox/openbox-{OPENBOX_VERSION}.tar.gz"

_BUILD_DEPS = [
    "libx11-dev", "libxft-dev", "libxrender-dev", "libxrandr-dev",
    "libxinerama-dev", "libxext-dev", "libxau-dev",
    "libxml2-dev", "libglib2.0-dev", "libpango1.0-dev",
    "libcairo2-dev", "libstartup-notification0-dev",
    "autoconf", "automake", "libtool", "intltool",
    "pkg-config", "gettext",
]

# Minimal Openbox config — clean dark theme, right-click launches xterm
_RC_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<openbox_config xmlns="http://openbox.org/3.4/rc">
  <resistance><strength>10</strength><screen_edge_strength>20</screen_edge_strength></resistance>
  <focus><focusNew>yes</focusNew><followMouse>no</followMouse><focusLast>yes</focusLast></focus>
  <theme>
    <name>Clearlooks</name>
    <titleLayout>NLIMC</titleLayout>
  </theme>
  <desktops><number>2</number><names><name>Desktop 1</name><name>Desktop 2</name></names></desktops>
  <keyboard>
    <chainQuitKey>C-g</chainQuitKey>
    <keybind key="A-F4"><action name="Close"/></keybind>
    <keybind key="A-Tab"><action name="NextWindow"/></keybind>
    <keybind key="C-A-t"><action name="Execute"><command>xterm</command></action></keybind>
    <keybind key="A-F2"><action name="Execute"><command>xterm</command></action></keybind>
    <keybind key="Super_L"><action name="ShowMenu"><menu>root-menu</menu></action></keybind>
  </keyboard>
  <mouse>
    <dragThreshold>8</dragThreshold>
    <doubleClickTime>200</doubleClickTime>
    <context name="Frame">
      <mousebind button="A-Left" action="Press"><action name="Focus"/><action name="Move"/></mousebind>
      <mousebind button="A-Right" action="Press"><action name="Focus"/><action name="Resize"/></mousebind>
    </context>
    <context name="Desktop">
      <mousebind button="Right" action="Press"><action name="ShowMenu"><menu>root-menu</menu></action></mousebind>
    </context>
    <context name="Titlebar">
      <mousebind button="Left" action="Press"><action name="Focus"/><action name="Raise"/></mousebind>
      <mousebind button="Left" action="Drag"><action name="Move"/></mousebind>
      <mousebind button="Left" action="DoubleClick"><action name="MaximizeFull"/></mousebind>
    </context>
  </mouse>
  <applications/>
</openbox_config>
"""

_MENU_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<openbox_menu xmlns="http://openbox.org/3.4/menu">
  <menu id="root-menu" label="Openbox">
    <item label="Terminal"><action name="Execute"><command>xterm</command></action></item>
    <separator/>
    <item label="Reconfigure"><action name="Reconfigure"/></item>
    <item label="Restart"><action name="Restart"/></item>
    <separator/>
    <item label="Exit"><action name="Exit"/></item>
  </menu>
</openbox_menu>
"""

# System-wide Openbox autostart: set background and start compositor (optional)
_AUTOSTART = """\
#!/bin/sh
# /etc/xdg/openbox/autostart

# Set solid black background
xsetroot -solid '#1a1a2e' &
"""


@dataclass
class OpenboxBuildResult:
    success: bool
    artifact_id: str | None = None
    error: str | None = None
    logs: list[str] = field(default_factory=list)
    cache_hit: bool = False


def _store_key(arch: str) -> str:
    return f"packages/openbox/{OPENBOX_VERSION}/{arch}/openbox.ofpkg"


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
    logs.append("[openbox] apt-get update…")
    subprocess.run(["apt-get", "update", "-qq"], capture_output=True,
                   env={**os.environ, "DEBIAN_FRONTEND": "noninteractive"})
    logs.append(f"[openbox] installing build deps…")
    proc = subprocess.run(
        ["apt-get", "install", "-y", "--no-install-recommends"] + _BUILD_DEPS,
        capture_output=True, text=True,
        env={**os.environ, "DEBIAN_FRONTEND": "noninteractive"},
    )
    if proc.returncode != 0:
        raise RuntimeError(f"apt-get failed:\n{proc.stderr[-500:]}")
    logs.append("[openbox] build deps installed")


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
                logs.append(f"[openbox] bundled: {src}")
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
        "name": "openbox",
        "version": OPENBOX_VERSION,
        "arch": arch,
        "description": "Openbox — a lightweight, standards-compliant window manager",
        "license": "GPL-2.0-only",
        "dependencies": [],
        "build_system": "autoconf",
    }
    manifest_bytes = json.dumps(manifest, indent=2, sort_keys=True).encode()
    sbom = json.dumps({
        "bomFormat": "CycloneDX", "specVersion": "1.4",
        "components": [{"name": "openbox", "version": OPENBOX_VERSION}],
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


@register("openbox")
def build_openbox(
    *,
    arch: str,
    store_root: Path,
    db_url: str | None = None,
    jobs: int = 4,
) -> OpenboxBuildResult:
    """Build Openbox from source and ingest as a package artifact."""
    logs: list[str] = []
    store_key = _store_key(arch)

    if db_url is not None:
        with sync_session(db_url) as session:
            existing = session.scalar(select(Artifact).where(Artifact.store_key == store_key))
            if existing is not None:
                logs.append(f"[openbox] cache hit: {existing.id[:8]}")
                return OpenboxBuildResult(success=True, artifact_id=existing.id, logs=logs, cache_hit=True)

    try:
        _install_build_deps(logs)
    except Exception as exc:
        return OpenboxBuildResult(success=False, error=f"dep install failed: {exc}", logs=logs)

    logs.append(f"[openbox] downloading {OPENBOX_URL}")
    try:
        req = urllib.request.Request(OPENBOX_URL, headers={"User-Agent": "osfabricum/1.0"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            tarball = resp.read()
    except Exception as exc:
        return OpenboxBuildResult(success=False, error=f"download failed: {exc}", logs=logs)

    logs.append(f"[openbox] downloaded {len(tarball)} bytes")
    tmp = tempfile.mkdtemp(prefix="osfab-openbox-")
    try:
        with tarfile.open(fileobj=io.BytesIO(tarball), mode="r:gz") as tar:
            tar.extractall(path=tmp, filter="data")
        entries = [e for e in Path(tmp).iterdir() if e.is_dir()]
        src_dir = entries[0] if entries else Path(tmp)
        logs.append(f"[openbox] extracted to {src_dir}")

        destdir = Path(tmp) / "destdir"
        destdir.mkdir()

        # openbox 3.6.1 ships config.guess from 2008 that doesn't know aarch64.
        # Replace with the system copy before running configure.
        for _cfg in ("config.guess", "config.sub"):
            _sys = Path("/usr/share/misc") / _cfg
            if _sys.exists():
                shutil.copy2(_sys, src_dir / _cfg)
                (src_dir / _cfg).chmod(0o755)

        _run([
            "./configure",
            "--prefix=/usr",
            "--sysconfdir=/etc",
            "--disable-nls",
            "CFLAGS=-O2 -Wno-error",
        ], cwd=src_dir, logs=logs)

        _run(["make", f"-j{jobs}"], cwd=src_dir, logs=logs)
        _run(["make", "install", f"DESTDIR={destdir}"], cwd=src_dir, logs=logs)
        logs.append(f"[openbox] installed to {destdir}")

        # Bundle shared lib dependencies for each binary
        for bin_name in ("openbox", "obxprop", "openbox-session"):
            binpath = destdir / "usr" / "bin" / bin_name
            if binpath.exists():
                _bundle_shared_libs(binpath, destdir, logs)

        # Write default config files to /etc/xdg/openbox/ (system-wide)
        xdg_dir = destdir / "etc" / "xdg" / "openbox"
        xdg_dir.mkdir(parents=True, exist_ok=True)
        (xdg_dir / "rc.xml").write_text(_RC_XML)
        (xdg_dir / "menu.xml").write_text(_MENU_XML)
        p = xdg_dir / "autostart"
        p.write_text(_AUTOSTART)
        p.chmod(0o755)

        # Also write to /root/.config/openbox/ so root has it immediately
        root_cfg = destdir / "root" / ".config" / "openbox"
        root_cfg.mkdir(parents=True, exist_ok=True)
        (root_cfg / "rc.xml").write_text(_RC_XML)
        (root_cfg / "menu.xml").write_text(_MENU_XML)

        ofpkg_data = _pack_ofpkg(destdir, arch)
        logs.append(f"[openbox] packaged {len(ofpkg_data)} bytes")

        artifact = ingest_blob(
            data=ofpkg_data,
            store_root=store_root,
            store_key=store_key,
            kind="package",
            name="openbox",
            version=OPENBOX_VERSION,
            arch=arch,
            media_type="application/zip",
            db_url=db_url,
            retention_class="permanent",
            input_hash=hashlib.sha256(tarball).hexdigest(),
        )
        logs.append(f"[openbox] artifact ingested: {artifact.id}")
        return OpenboxBuildResult(success=True, artifact_id=artifact.id, logs=logs)

    except Exception as exc:
        return OpenboxBuildResult(success=False, error=str(exc), logs=logs)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
