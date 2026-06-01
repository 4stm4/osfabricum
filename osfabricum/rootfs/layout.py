"""RootFS directory layout constants (M15).

``BASE_DIRS``
    Minimum set of directories that must exist in every OSFabricum rootfs.
    The list follows the FHS (Filesystem Hierarchy Standard) as closely as
    possible while remaining minimal.

``MERGED_USR_SYMLINKS``
    Legacy compatibility symlinks for merged-usr systems
    (``/bin → usr/bin``, etc.).  Created as relative symlinks so the rootfs
    is relocatable.
"""

from __future__ import annotations

#: All directories created by :func:`~osfabricum.rootfs.builder.create_rootfs_tree`.
BASE_DIRS: list[str] = [
    # Core binaries
    "usr/bin",
    "usr/sbin",
    "usr/lib",
    "usr/lib64",
    "usr/share",
    "usr/local/bin",
    "usr/local/lib",
    "usr/local/share",
    # /etc and sub-trees
    "etc",
    "etc/init.d",
    "etc/profile.d",
    "etc/rc.d",
    "etc/rc.d/init.d",
    "etc/sysconfig",
    # Kernel virtual fs mount points
    "proc",
    "sys",
    "dev",
    "dev/pts",
    "dev/shm",
    # Runtime
    "run",
    "tmp",
    # Variable data
    "var",
    "var/cache",
    "var/log",
    "var/run",
    "var/tmp",
    "var/spool",
    # Home directories
    "root",
    "home",
    # Storage / media
    "mnt",
    "media",
    "opt",
    # Boot
    "boot",
    # Libraries (merged-usr targets use these as stubs)
    "lib",
    "lib64",
    # Compatibility bin/sbin (stubs for merged-usr)
    "bin",
    "sbin",
]

#: Relative symlinks to create for merged-usr systems.
#: Each tuple is (link_name, target) relative to the rootfs root.
MERGED_USR_SYMLINKS: list[tuple[str, str]] = [
    # These are NOT created when using merged-usr — the directories above
    # serve as the real paths.  They are only needed for non-merged-usr.
]

#: Files that must be writable at runtime (permissions 1777).
STICKY_DIRS: list[str] = ["tmp", "var/tmp"]

#: Standard permissions for well-known directories.
DIR_MODES: dict[str, int] = {
    "root": 0o750,
    "tmp": 0o1777,
    "var/tmp": 0o1777,
    "dev": 0o755,
    "proc": 0o555,
    "sys": 0o555,
    "run": 0o755,
}
