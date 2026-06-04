"""Block device discovery and allowlist (M21).

Safety model
------------
Flashing writes raw bytes to a block device — a mistake can destroy the
operator's system disk.  OSFabricum therefore **never** writes to a device
unless its path matches an explicit allowlist.  The default allowlist is
empty: the operator must opt in, either by passing ``--device`` together
with ``--allow`` patterns or by configuring an allowlist.

``FlashDevice``
    Metadata about one candidate block device.

``is_device_allowed``
    Return ``True`` iff *path* matches at least one allowlist pattern
    (``fnmatch`` glob syntax) and no denylist pattern.

``list_devices``
    Best-effort enumeration of removable block devices.  Platform-specific;
    returns an empty list when discovery is unsupported.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from pathlib import Path

#: Patterns that are ALWAYS refused, even if present in the allowlist.
#: Protects common system-disk device nodes.
DENYLIST: tuple[str, ...] = (
    "/dev/sda",  # almost always the system disk on x86 hosts
    "/dev/nvme0n1",  # primary NVMe
    "/dev/vda",  # primary virtio disk
    "/dev/mmcblk0boot*",  # eMMC boot hw partitions
)

#: A conservative default allowlist (empty — opt-in only).
DEFAULT_ALLOWLIST: tuple[str, ...] = ()


@dataclass
class FlashDevice:
    """Metadata about a candidate flash target."""

    path: str
    size_bytes: int | None = None
    model: str = ""
    removable: bool = False

    def human_size(self) -> str:
        n = self.size_bytes
        if n is None:
            return "?"
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if n < 1024:
                return f"{n:.1f}{unit}"
            n /= 1024
        return f"{n:.1f}PB"


def is_device_allowed(
    path: str,
    allowlist: tuple[str, ...] | list[str],
    *,
    denylist: tuple[str, ...] = DENYLIST,
) -> bool:
    """Return ``True`` iff *path* is permitted as a flash target.

    A device is permitted when it matches at least one *allowlist* glob and
    matches no *denylist* glob.  An empty allowlist permits nothing.
    """
    if any(fnmatch.fnmatch(path, deny) for deny in denylist):
        return False
    return any(fnmatch.fnmatch(path, allow) for allow in allowlist)


def list_devices() -> list[FlashDevice]:
    """Enumerate removable block devices (best-effort, Linux-focused).

    Reads ``/sys/block/*`` to find removable devices.  On non-Linux hosts
    (or when ``/sys`` is unavailable) returns an empty list.
    """
    devices: list[FlashDevice] = []
    sys_block = Path("/sys/block")
    if not sys_block.is_dir():
        return devices

    for entry in sorted(sys_block.iterdir()):
        name = entry.name
        # Skip loop / ram / device-mapper pseudo devices
        if name.startswith(("loop", "ram", "dm-")):
            continue
        removable_file = entry / "removable"
        size_file = entry / "size"
        model_file = entry / "device" / "model"

        removable = False
        if removable_file.exists():
            try:
                removable = removable_file.read_text().strip() == "1"
            except OSError:
                pass

        size_bytes: int | None = None
        if size_file.exists():
            try:
                # /sys reports size in 512-byte sectors
                size_bytes = int(size_file.read_text().strip()) * 512
            except (OSError, ValueError):
                pass

        model = ""
        if model_file.exists():
            try:
                model = model_file.read_text().strip()
            except OSError:
                pass

        devices.append(
            FlashDevice(
                path=f"/dev/{name}",
                size_bytes=size_bytes,
                model=model,
                removable=removable,
            )
        )

    return devices
