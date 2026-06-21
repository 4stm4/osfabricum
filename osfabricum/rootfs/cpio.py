"""newc cpio archive writer for Linux initramfs.

Produces a ``070701`` (newc) format cpio stream that the Linux kernel can
unpack as an initramfs.  Pure-Python — no ``cpio`` binary required.

Usage::

    from osfabricum.rootfs.cpio import pack_initramfs
    cpio_bytes = pack_initramfs(stage_dir)
    import gzip
    initramfs_gz = gzip.compress(cpio_bytes, compresslevel=9, mtime=0)
"""

from __future__ import annotations

import io
import os
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pad4(n: int) -> int:
    """Bytes of padding needed to align *n* to the next 4-byte boundary."""
    return (4 - n % 4) % 4


def _add_entry(
    buf: io.BytesIO,
    name: str,
    data: bytes,
    mode: int,
    *,
    ino: int,
    nlink: int = 1,
    uid: int = 0,
    gid: int = 0,
    mtime: int = 0,
    devmajor: int = 0,
    devminor: int = 0,
    rdevmajor: int = 0,
    rdevminor: int = 0,
) -> None:
    """Write one newc cpio entry to *buf*."""
    name_b = name.encode("ascii", errors="replace") + b"\x00"
    namesize = len(name_b)
    filesize = len(data)

    # 110-byte ASCII header
    hdr = (
        "070701"
        f"{ino:08x}{mode:08x}{uid:08x}{gid:08x}"
        f"{nlink:08x}{mtime:08x}{filesize:08x}"
        f"{devmajor:08x}{devminor:08x}{rdevmajor:08x}{rdevminor:08x}"
        f"{namesize:08x}{0:08x}"
    ).encode("ascii")

    # Padding after name: align (110 + namesize) to 4 bytes
    name_pad = _pad4(110 + namesize)
    # Padding after data: align (110 + namesize + name_pad + filesize) to 4 bytes
    data_end = 110 + namesize + name_pad + filesize
    data_pad = _pad4(data_end)

    buf.write(hdr)
    buf.write(name_b)
    buf.write(b"\x00" * name_pad)
    buf.write(data)
    buf.write(b"\x00" * data_pad)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def pack_initramfs(src_dir: Path) -> bytes:
    """Pack *src_dir* into a newc cpio archive for use as Linux initramfs.

    Handles regular files, directories, and symlinks.  Device nodes in the
    source directory are skipped (cannot be created without root); instead
    ``/dev/console`` and ``/dev/null`` are written explicitly as character
    devices so the kernel can open the console before devtmpfs is mounted.

    Parameters
    ----------
    src_dir:
        Root of the staged rootfs (the directory to pack).

    Returns
    -------
    bytes
        Raw (uncompressed) newc cpio archive.  Compress with gzip before
        placing in the boot partition.
    """
    buf = io.BytesIO()
    ino = 300_000  # arbitrary high start to avoid conflicts

    # ---- root directory ----
    _add_entry(buf, ".", b"", 0o040755, ino=ino, nlink=2)
    ino += 1

    # ---- walk source directory ----
    seen: set[str] = set()
    for path in sorted(src_dir.rglob("*"), key=lambda p: str(p.relative_to(src_dir))):
        rel = str(path.relative_to(src_dir))
        seen.add(rel)

        if path.is_symlink():
            target = os.readlink(str(path))
            _add_entry(buf, rel, target.encode(), 0o120777, ino=ino)
        elif path.is_dir():
            _add_entry(buf, rel, b"", 0o040755, ino=ino, nlink=2)
        elif path.is_file():
            file_data = path.read_bytes()
            st_mode = path.stat().st_mode & 0o7777
            # Preserve executable bit; default file mode 0644
            if st_mode & 0o111:
                mode = 0o100755
            else:
                mode = 0o100644
            _add_entry(buf, rel, file_data, mode, ino=ino)
        # Skip anything else (sockets, device nodes we can't read, etc.)
        ino += 1

    # ---- /dev device nodes (needed before devtmpfs is mounted) ----
    # Only add if not already present in src_dir (e.g. from a previous pack).
    if "dev" not in seen:
        _add_entry(buf, "dev", b"", 0o040755, ino=ino, nlink=2)
        ino += 1
    if "dev/console" not in seen:
        _add_entry(
            buf, "dev/console", b"", 0o020600, ino=ino,
            devmajor=0, devminor=0, rdevmajor=5, rdevminor=1,
        )
        ino += 1
    if "dev/null" not in seen:
        _add_entry(
            buf, "dev/null", b"", 0o020666, ino=ino,
            devmajor=0, devminor=0, rdevmajor=1, rdevminor=3,
        )
        ino += 1

    # ---- TRAILER!!! ----
    _add_entry(buf, "TRAILER!!!", b"", 0, ino=0, nlink=1)

    return buf.getvalue()
