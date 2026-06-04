"""Minimal FAT16 filesystem writer (M17).

Pure-Python implementation — no external dependencies or OS-level tools.
Produces a byte-exact FAT16 partition image that can be written to a raw
device or embedded in a disk image.

Supports:
* 8.3 short filenames
* VFAT Long File Name (LFN) entries — required for RPi boot files like
  ``bcm2710-rpi-zero-2-w.dtb``
* Files of arbitrary size (up to partition capacity)

Usage::

    writer = Fat16Writer(total_sectors=131072)   # 64 MB
    writer.add_file("config.txt", b"kernel=Image\\n")
    writer.add_file("bcm2710-rpi-zero-2-w.dtb", dtb_bytes)
    image_bytes = writer.get_image()
"""

from __future__ import annotations

import struct

SECTOR_SIZE = 512
FAT16_EOC = 0xFFFF
FAT16_MEDIA = 0xFFF8
FAT16_FREE = 0x0000
ATTR_LFN = 0x0F  # Long File Name attribute
ATTR_ARCHIVE = 0x20


# ---------------------------------------------------------------------------
# 8.3 filename helpers
# ---------------------------------------------------------------------------


def _short_name_checksum(name83: bytes) -> int:
    """Compute the 8.3 checksum used by LFN entries."""
    assert len(name83) == 11  # noqa: S101
    csum = 0
    for byte in name83:
        csum = ((csum >> 1) | (csum << 7) & 0xFF) + byte
        csum &= 0xFF
    return csum


def _to_83(filename: str) -> tuple[bytes, bytes]:
    """Convert *filename* to ``(name_8, ext_3)`` bytes, both space-padded.

    For files with a ``.`` extension the last dot is used.
    Names longer than 8 chars are truncated with a ``~1`` suffix.
    """
    filename = filename.upper().replace(" ", "_")
    dot_idx = filename.rfind(".")
    if dot_idx < 0:
        name, ext = filename, ""
    else:
        name, ext = filename[:dot_idx], filename[dot_idx + 1 :]

    if len(name) > 8:
        # Truncate to 6 chars + ~1
        name = name[:6] + "~1"

    name_b = name[:8].encode("ascii", errors="replace").ljust(8, b" ")
    ext_b = ext[:3].encode("ascii", errors="replace").ljust(3, b" ")
    return name_b, ext_b


# ---------------------------------------------------------------------------
# LFN entry builder
# ---------------------------------------------------------------------------


def _lfn_entries(filename: str, checksum: int) -> list[bytes]:
    """Build a list of 32-byte LFN directory entries for *filename*.

    The entries are returned in the order they should appear in the
    directory (reverse sequence order, i.e. last fragment first).
    """
    # Encode filename as UTF-16LE, padded with 0xFFFF
    utf16 = filename.encode("utf-16-le")
    # Pad to multiple of 13 UTF-16LE chars (26 bytes)
    while len(utf16) % 26 != 0:
        utf16 += b"\x00\x00"  # NULL terminator
        if len(utf16) % 26 != 0:
            utf16 += b"\xff\xff"  # padding

    # Split into 13-char chunks (26 bytes each)
    chunks: list[bytes] = [utf16[i : i + 26] for i in range(0, len(utf16), 26)]

    total = len(chunks)

    # Build entries in forward order (seq 1 = first 13 chars, seq N = last 13 chars).
    # They are stored in REVERSE order in the directory (highest seq first).
    entries: list[bytes] = []
    for seq_0 in range(total):
        seq = seq_0 + 1
        is_last = seq == total
        chunk = chunks[seq_0]

        entry = bytearray(32)
        seq_byte = seq | (0x40 if is_last else 0)
        entry[0] = seq_byte
        # Characters: positions 1-10, 14-25, 28-31
        entry[1:11] = chunk[0:10]
        entry[11] = ATTR_LFN
        entry[12] = 0
        entry[13] = checksum
        entry[14:26] = chunk[10:22]
        struct.pack_into("<H", entry, 26, 0)
        entry[28:32] = chunk[22:26]
        entries.append(bytes(entry))

    # LFN entries in directory must be in REVERSE sequence order
    # (highest seq first, then descending to seq=1, then the 8.3 entry)
    return list(reversed(entries))


# ---------------------------------------------------------------------------
# FAT16 writer
# ---------------------------------------------------------------------------


class Fat16Writer:
    """Write a FAT16 partition image.

    Parameters
    ----------
    total_sectors:
        Total sectors in the partition (sector = 512 bytes).
        Default: 131072 → 64 MB.
    sectors_per_cluster:
        Cluster size in sectors.  Must be a power of 2.
        Default: 8 → 4 KB clusters.
    volume_label:
        11-character volume label (shorter strings are space-padded).
    hidden_sectors:
        LBA start of this partition on the physical disk.  Written into
        the BPB so the FAT16 structures are self-consistent.
    """

    def __init__(
        self,
        total_sectors: int = 131072,
        sectors_per_cluster: int = 8,
        volume_label: str = "OSFAB BOOT ",
        hidden_sectors: int = 0,
    ) -> None:
        self.total_sectors = total_sectors
        self.sectors_per_cluster = sectors_per_cluster
        self.bytes_per_cluster = SECTOR_SIZE * sectors_per_cluster
        self.volume_label = volume_label[:11].ljust(11)
        self.hidden_sectors = hidden_sectors

        self.reserved_sectors = 4  # room for extended boot record
        self.fat_count = 2
        self.root_dir_entries = 512  # 16 sectors of root dir

        # Compute FAT size iteratively
        self.root_dir_sectors = (self.root_dir_entries * 32) // SECTOR_SIZE

        # Approximation first
        overhead = self.reserved_sectors + self.root_dir_sectors
        data_sectors_est = total_sectors - overhead
        clusters_est = data_sectors_est // sectors_per_cluster
        fat_size_sectors = max(1, (clusters_est * 2 + SECTOR_SIZE - 1) // SECTOR_SIZE)
        fat_size_sectors += 1  # safety margin

        self.fat_size_sectors = fat_size_sectors
        self.data_start_sector = (
            self.reserved_sectors + self.fat_count * self.fat_size_sectors + self.root_dir_sectors
        )
        total_data_sectors = max(0, self.total_sectors - self.data_start_sector)
        self.total_clusters = total_data_sectors // self.sectors_per_cluster

        # FAT table (bytes), initialized with media and EOC marks
        self._fat = bytearray(self.fat_size_sectors * SECTOR_SIZE)
        struct.pack_into("<H", self._fat, 0, FAT16_MEDIA)
        struct.pack_into("<H", self._fat, 2, FAT16_EOC)

        # Next free cluster (2 is first data cluster)
        self._next_cluster = 2

        # Root directory (flat bytearray)
        self._root_dir = bytearray(self.root_dir_sectors * SECTOR_SIZE)
        self._root_dir_entries_used = 0

        # Cluster payload storage: cluster_num → bytes (padded to cluster size)
        self._cluster_data: dict[int, bytes] = {}

    # ------------------------------------------------------------------

    def _alloc_clusters(self, data: bytes) -> int:
        """Allocate FAT clusters for *data*; return first cluster number."""
        if not data:
            # Allocate one empty cluster for zero-length files
            c = self._next_cluster
            self._next_cluster += 1
            struct.pack_into("<H", self._fat, c * 2, FAT16_EOC)
            self._cluster_data[c] = b"\x00" * self.bytes_per_cluster
            return c

        n_clusters = (len(data) + self.bytes_per_cluster - 1) // self.bytes_per_cluster
        first_cluster = self._next_cluster

        for i in range(n_clusters):
            c = self._next_cluster
            self._next_cluster += 1
            next_c = self._next_cluster if i < n_clusters - 1 else FAT16_EOC
            struct.pack_into("<H", self._fat, c * 2, next_c)

            start = i * self.bytes_per_cluster
            chunk = data[start : start + self.bytes_per_cluster]
            self._cluster_data[c] = chunk.ljust(self.bytes_per_cluster, b"\x00")

        return first_cluster

    def _append_dir_entries(self, entries: list[bytes]) -> None:
        for entry in entries:
            offset = self._root_dir_entries_used * 32
            if offset + 32 > len(self._root_dir):
                raise RuntimeError("Root directory is full")
            self._root_dir[offset : offset + 32] = entry
            self._root_dir_entries_used += 1

    # ------------------------------------------------------------------

    def add_file(self, filename: str, data: bytes) -> None:
        """Add *filename* with *data* to the root directory.

        Long filenames (> 8+3 chars) get VFAT LFN entries automatically.
        """
        name_b, ext_b = _to_83(filename)
        name83 = name_b + ext_b  # 11 bytes
        checksum = _short_name_checksum(name83)

        first_cluster = self._alloc_clusters(data)

        # Build 8.3 directory entry
        entry = bytearray(32)
        entry[0:8] = name_b
        entry[8:11] = ext_b
        entry[11] = ATTR_ARCHIVE
        struct.pack_into("<H", entry, 26, first_cluster)
        struct.pack_into("<I", entry, 28, len(data))
        # mtime / mdate = 0 (epoch, reproducible)
        entry83 = bytes(entry)

        # Does this filename need LFN entries?
        dot_idx = filename.rfind(".")
        if dot_idx >= 0:
            short_name = filename[:dot_idx]
            short_ext = filename[dot_idx + 1 :]
        else:
            short_name = filename
            short_ext = ""

        needs_lfn = (
            len(short_name) > 8
            or len(short_ext) > 3
            or any(c in filename for c in " +,;=[]")
            or filename != filename.upper()
        )

        if needs_lfn:
            lfn_entries = _lfn_entries(filename, checksum)
            self._append_dir_entries(lfn_entries)

        self._append_dir_entries([entry83])

    # ------------------------------------------------------------------

    def get_image(self) -> bytes:
        """Render the full FAT16 partition image as bytes."""
        image = bytearray(self.total_sectors * SECTOR_SIZE)

        # Boot sector (sector 0)
        image[0:SECTOR_SIZE] = self._build_boot_sector()

        # FAT1
        fat1_offset = self.reserved_sectors * SECTOR_SIZE
        fat_bytes = bytes(self._fat).ljust(self.fat_size_sectors * SECTOR_SIZE, b"\x00")
        image[fat1_offset : fat1_offset + len(fat_bytes)] = fat_bytes

        # FAT2 (identical copy)
        fat2_offset = (self.reserved_sectors + self.fat_size_sectors) * SECTOR_SIZE
        image[fat2_offset : fat2_offset + len(fat_bytes)] = fat_bytes

        # Root directory
        root_offset = (self.reserved_sectors + self.fat_count * self.fat_size_sectors) * SECTOR_SIZE
        image[root_offset : root_offset + len(self._root_dir)] = self._root_dir

        # Cluster data
        for c, data in self._cluster_data.items():
            sector = self.data_start_sector + (c - 2) * self.sectors_per_cluster
            offset = sector * SECTOR_SIZE
            image[offset : offset + len(data)] = data

        return bytes(image)

    def _build_boot_sector(self) -> bytes:
        bs = bytearray(SECTOR_SIZE)
        bs[0:3] = bytes([0xEB, 0x58, 0x90])  # JMP SHORT + NOP
        bs[3:11] = b"OSFAB   "  # OEM name
        struct.pack_into("<H", bs, 11, SECTOR_SIZE)
        bs[13] = self.sectors_per_cluster
        struct.pack_into("<H", bs, 14, self.reserved_sectors)
        bs[16] = self.fat_count
        struct.pack_into("<H", bs, 17, self.root_dir_entries)
        # Total sectors: use 32-bit field if > 65535
        if self.total_sectors <= 65535:
            struct.pack_into("<H", bs, 19, self.total_sectors)
        else:
            struct.pack_into("<I", bs, 32, self.total_sectors)
        bs[21] = 0xF8  # media: fixed disk
        struct.pack_into("<H", bs, 22, self.fat_size_sectors)
        struct.pack_into("<H", bs, 24, 63)  # sectors/track
        struct.pack_into("<H", bs, 26, 255)  # heads
        struct.pack_into("<I", bs, 28, self.hidden_sectors)
        bs[36] = 0x80  # drive number
        bs[38] = 0x29  # extended boot signature
        struct.pack_into("<I", bs, 39, 0xDEADC0DE)  # volume ID
        bs[43:54] = self.volume_label.encode("ascii")[:11].ljust(11, b" ")
        bs[54:62] = b"FAT16   "
        bs[510] = 0x55
        bs[511] = 0xAA
        return bytes(bs)
