"""MBR (Master Boot Record) partition table writer (M17).

Generates a 512-byte MBR with up to four primary partition entries.
Uses LBA addressing throughout — CHS fields are set to ``0xFF 0xFF 0xFF``
(as recommended when LBA > 1023 is used).

Partition types used by OSFabricum:
* ``0x0B`` — FAT32 (used for the boot partition; also readable as FAT16
  by many BIOSes/GPUs when written as FAT16)
* ``0x83`` — Linux native (ext4 rootfs)
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

SECTOR_SIZE = 512
MBR_SIZE = 512
BOOT_SIGNATURE = b"\x55\xaa"

# Partition type constants
PART_FAT16 = 0x0E  # FAT16 with LBA addressing
PART_FAT32 = 0x0C  # FAT32 with LBA addressing
PART_LINUX = 0x83  # Linux native
PART_EMPTY = 0x00  # Unused entry


@dataclass
class PartitionEntry:
    """One MBR partition entry.

    Attributes
    ----------
    lba_start:
        First LBA sector of the partition.
    lba_size:
        Number of sectors in the partition.
    partition_type:
        MBR partition type byte (e.g. :data:`PART_FAT16`, :data:`PART_LINUX`).
    bootable:
        ``True`` to mark this partition as bootable (status byte 0x80).
    """

    lba_start: int
    lba_size: int
    partition_type: int = PART_LINUX
    bootable: bool = False


def _lba_to_chs(lba: int) -> bytes:
    """Convert an LBA address to a 3-byte CHS tuple.

    For LBA > 1023, returns ``0xFF 0xFF 0xFF`` as per convention.
    """
    if lba >= 1024 * 63 * 255:
        return b"\xff\xff\xff"
    c = lba // (63 * 255)
    temp = lba % (63 * 255)
    h = temp // 63
    s = temp % 63 + 1
    chs_b = (h & 0xFF).to_bytes(1, "little")
    chs_b += ((s & 0x3F) | ((c >> 2) & 0xC0)).to_bytes(1, "little")
    chs_b += (c & 0xFF).to_bytes(1, "little")
    return chs_b


def _pack_entry(entry: PartitionEntry) -> bytes:
    """Pack a :class:`PartitionEntry` into 16 bytes."""
    status = 0x80 if entry.bootable else 0x00
    chs_start = _lba_to_chs(entry.lba_start)
    chs_end = _lba_to_chs(entry.lba_start + entry.lba_size - 1)

    return struct.pack(
        "B3sB3sII",
        status,
        chs_start,
        entry.partition_type,
        chs_end,
        entry.lba_start,
        entry.lba_size,
    )


def write_mbr(entries: list[PartitionEntry]) -> bytes:
    """Produce a 512-byte MBR with the given partition table.

    Parameters
    ----------
    entries:
        Up to four :class:`PartitionEntry` items.  If fewer than four are
        given the remaining slots are filled with empty (type 0x00) entries.

    Returns
    -------
    bytes
        Exactly 512 bytes (MBR sector).
    """
    if len(entries) > 4:
        raise ValueError(f"MBR supports at most 4 primary partitions, got {len(entries)}")

    mbr = bytearray(MBR_SIZE)

    # Bootstrap code area (bytes 0–445): leave as zeros (not bootable from this MBR)
    # The RPi loads from the FAT boot partition directly via GPU firmware.

    # Partition table (bytes 446–509)
    for i in range(4):
        offset = 446 + i * 16
        if i < len(entries):
            mbr[offset : offset + 16] = _pack_entry(entries[i])
        else:
            # Empty entry
            mbr[offset : offset + 16] = b"\x00" * 16

    # Signature
    mbr[510:512] = BOOT_SIGNATURE

    return bytes(mbr)


def read_mbr(data: bytes) -> list[PartitionEntry]:
    """Parse the four partition entries from a 512-byte MBR.

    Returns entries with ``partition_type != 0`` only.
    """
    if len(data) < MBR_SIZE:
        raise ValueError("data too short for MBR")
    if data[510:512] != BOOT_SIGNATURE:
        raise ValueError("invalid MBR boot signature")

    entries: list[PartitionEntry] = []
    for i in range(4):
        offset = 446 + i * 16
        status, _, ptype, _, lba_start, lba_size = struct.unpack_from("B3sB3sII", data, offset)
        if ptype != PART_EMPTY:
            entries.append(
                PartitionEntry(
                    lba_start=lba_start,
                    lba_size=lba_size,
                    partition_type=ptype,
                    bootable=(status == 0x80),
                )
            )

    return entries
