"""Disk image composer (M17).

``compose_image`` is the single entry point.  Given an
:class:`ImageSpec` it:

1. Collects boot files (kernel, DTBs, firmware) into a ``{name: bytes}``
   mapping using :func:`~osfabricum.image.bootfiles.collect_boot_files`.
2. Builds a FAT16 boot partition image using
   :class:`~osfabricum.image.fat16.Fat16Writer`.
3. Loads the composed rootfs tarball (from M16) from the artifact store.
4. Builds an MBR partition table with two entries:
   * Partition 1 — FAT16 boot (type ``0x0E``)
   * Partition 2 — Linux rootfs (type ``0x83``)
5. Assembles the raw disk image:
   ``MBR (512B) | alignment gap | boot partition | rootfs partition``
6. Compresses with gzip and ingests as a ``image`` artifact.

The rootfs "partition" in the raw image is the rootfs tar.gz blob written
at the partition offset.  The :doc:`flash utility (M21)<flash>` is
responsible for formatting the rootfs partition as ext4 and extracting the
tarball.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import shutil
import tarfile
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select

from osfabricum.db.models import Artifact
from osfabricum.db.session import sync_session
from osfabricum.image.bootfiles import collect_boot_files
from osfabricum.image.fat16 import Fat16Writer
from osfabricum.image.mbr import PART_FAT16, PART_LINUX, PartitionEntry, write_mbr
from osfabricum.repro.chain import InputManifest, compute_input_hash, make_repro_record
from osfabricum.repro.env import BuildEnvSpec, compute_env_hash
from osfabricum.rootfs.cpio import pack_initramfs
from osfabricum.store.ingest import ingest_blob
from osfabricum.store.layout import blob_path

SECTOR_SIZE = 512

# Alignment: partitions start on 1 MiB boundaries (2048 sectors)
PART_ALIGN_SECTORS = 2048


# ---------------------------------------------------------------------------
# Spec & result
# ---------------------------------------------------------------------------


@dataclass
class ImageSpec:
    """Full specification for assembling a disk image.

    Attributes
    ----------
    distribution, profile, board, arch:
        Target triple.
    rootfs_artifact_id:
        UUID of the composed rootfs artifact (from M16).
    kernel_artifact_id:
        UUID of the kernel image artifact (optional; skipped if ``None``).
    firmware_artifact_ids:
        UUIDs of firmware blob artifacts (start4.elf, fixup4.dat, …).
    dtb_artifact_ids:
        UUIDs of DTB artifacts.
    boot_size_mb:
        Size of the FAT16 boot partition in MiB.  Default: 64.
    rootfs_size_mb:
        Size reserved for the rootfs partition in MiB.  Default: 512.
    extra_boot_files:
        Additional ``{filename: bytes}`` written to the boot partition.
    kernel_filename:
        Filename used for the kernel on the boot partition.
    dtb_filename:
        Override for DTB filename in ``config.txt``.
    root_device:
        Root device written into ``cmdline.txt``.
    arm64:
        Pass ``arm_64bit=1`` to ``config.txt``.
    """

    distribution: str
    profile: str
    board: str
    arch: str
    rootfs_artifact_id: str
    kernel_artifact_id: str | None = None
    firmware_artifact_ids: list[str] = field(default_factory=list)
    dtb_artifact_ids: list[str] = field(default_factory=list)
    boot_size_mb: int = 64
    rootfs_size_mb: int = 512
    extra_boot_files: dict[str, bytes] = field(default_factory=dict)
    kernel_filename: str = "Image"
    dtb_filename: str | None = None
    root_device: str = "/dev/mmcblk0p2"
    arm64: bool = True
    use_initramfs: bool = True  # convert rootfs tar.gz → cpio.gz in boot partition

    def store_key(self) -> str:
        return (
            f"images/{self.distribution}/{self.profile}"
            f"/{self.board}/{self.distribution}-{self.profile}-{self.board}.img.gz"
        )

    def total_size_mb(self) -> int:
        # 1 MiB gap before p1 + boot + gap before p2 + rootfs + 1 MiB trailer
        return 1 + self.boot_size_mb + 1 + self.rootfs_size_mb + 1


@dataclass
class ImageComposeResult:
    """Outcome of :func:`compose_image`."""

    success: bool
    artifact_id: str | None = None
    image_size_bytes: int = 0
    boot_files: list[str] = field(default_factory=list)
    error: str | None = None
    logs: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mb_to_sectors(mb: int) -> int:
    return mb * 1024 * 1024 // SECTOR_SIZE


def _load_artifact_blob(
    artifact_id: str,
    store_root: Path,
    db_url: str | None,
) -> bytes:
    with sync_session(db_url) as session:
        art: Artifact | None = session.scalar(select(Artifact).where(Artifact.id == artifact_id))
        if art is None:
            raise ValueError(f"artifact not found: {artifact_id!r}")
        sha256 = art.blob_sha256

    bp = blob_path(store_root, sha256)
    if not bp.exists():
        raise FileNotFoundError(f"blob not found for artifact {artifact_id}: {bp}")

    return bp.read_bytes()


def _rootfs_to_initramfs(rootfs_data: bytes) -> bytes:
    """Convert a rootfs tar.gz blob to a gzip-compressed newc cpio archive.

    Extracts the tarball to a temp directory, packs it as newc cpio, then
    gzip-compresses the result.  The temp directory is always cleaned up.
    """
    tmp = tempfile.mkdtemp(prefix="osfab-initramfs-")
    try:
        stage = Path(tmp)
        with tarfile.open(fileobj=io.BytesIO(rootfs_data), mode="r:gz") as tar:
            tar.extractall(path=str(stage), filter="fully_trusted")
        cpio_raw = pack_initramfs(stage)
        return gzip.compress(cpio_raw, compresslevel=9, mtime=0)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _build_fat16_partition(
    boot_files: dict[str, bytes],
    total_sectors: int,
    hidden_sectors: int,
) -> bytes:
    """Build a FAT16 partition image with *boot_files*."""
    writer = Fat16Writer(
        total_sectors=total_sectors,
        sectors_per_cluster=8,
        hidden_sectors=hidden_sectors,
    )
    for filename, data in sorted(boot_files.items()):
        writer.add_file(filename, data)
    return writer.get_image()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compose_image(
    spec: ImageSpec,
    *,
    store_root: Path,
    db_url: str | None = None,
) -> ImageComposeResult:
    """Assemble a bootable disk image from *spec*.

    Parameters
    ----------
    spec:
        The image specification.
    store_root:
        Artifact store root.
    db_url:
        SQLAlchemy database URL.

    Returns
    -------
    ImageComposeResult
        ``success=True`` with ``artifact_id`` set on success.
    """
    logs: list[str] = []

    try:
        # 1. Load rootfs tarball
        logs.append(f"[image] loading rootfs artifact {spec.rootfs_artifact_id[:8]}…")
        rootfs_data = _load_artifact_blob(spec.rootfs_artifact_id, store_root, db_url)
        logs.append(f"[image] rootfs: {len(rootfs_data)} bytes")

        # 2. Convert rootfs to initramfs cpio.gz (placed in boot partition)
        initramfs_filename: str | None = None
        extra_boot = dict(spec.extra_boot_files)
        if spec.use_initramfs:
            logs.append("[image] converting rootfs tar.gz → initramfs cpio.gz…")
            initramfs_gz = _rootfs_to_initramfs(rootfs_data)
            logs.append(f"[image] initramfs: {len(initramfs_gz)} bytes")
            initramfs_filename = "initramfs.gz"
            extra_boot[initramfs_filename] = initramfs_gz

        # 3. Collect boot files (kernel, DTBs, firmware, initramfs)
        logs.append("[image] collecting boot files…")
        boot_files = collect_boot_files(
            kernel_artifact_id=spec.kernel_artifact_id,
            firmware_artifact_ids=spec.firmware_artifact_ids,
            dtb_artifact_ids=spec.dtb_artifact_ids,
            store_root=store_root,
            db_url=db_url,
            kernel_filename=spec.kernel_filename,
            extra_files=extra_boot,
            dtb_filename=spec.dtb_filename,
            arm64=spec.arm64,
            # In initramfs mode: no root= in cmdline
            root_device=spec.root_device if not spec.use_initramfs else None,
            initramfs=initramfs_filename,
        )
        logs.append(f"[image] boot files: {sorted(boot_files)}")

        # 4. Compute partition layout (LBA) — boot only when initramfs
        boot_lba_start = PART_ALIGN_SECTORS  # 1 MiB offset
        boot_sectors = _mb_to_sectors(spec.boot_size_mb)
        boot_lba_end = boot_lba_start + boot_sectors

        if spec.use_initramfs:
            # Single boot partition, no rootfs partition
            total_sectors = boot_lba_start + boot_sectors + PART_ALIGN_SECTORS
            partitions = [
                PartitionEntry(
                    lba_start=boot_lba_start,
                    lba_size=boot_sectors,
                    partition_type=PART_FAT16,
                    bootable=True,
                ),
            ]
            logs.append(
                f"[image] layout (initramfs): total={total_sectors} sectors "
                f"boot={boot_lba_start}+{boot_sectors}"
            )
        else:
            rootfs_lba_start = (
                (boot_lba_end + PART_ALIGN_SECTORS - 1) // PART_ALIGN_SECTORS
            ) * PART_ALIGN_SECTORS
            rootfs_sectors = _mb_to_sectors(spec.rootfs_size_mb)
            total_sectors = _mb_to_sectors(spec.total_size_mb())
            partitions = [
                PartitionEntry(
                    lba_start=boot_lba_start,
                    lba_size=boot_sectors,
                    partition_type=PART_FAT16,
                    bootable=True,
                ),
                PartitionEntry(
                    lba_start=rootfs_lba_start,
                    lba_size=rootfs_sectors,
                    partition_type=PART_LINUX,
                    bootable=False,
                ),
            ]
            logs.append(
                f"[image] layout: total={total_sectors} sectors "
                f"boot={boot_lba_start}+{boot_sectors} "
                f"rootfs={rootfs_lba_start}+{rootfs_sectors}"
            )

        # 5. Build FAT16 boot partition
        logs.append("[image] building FAT16 boot partition…")
        fat16_image = _build_fat16_partition(
            boot_files, boot_sectors, hidden_sectors=boot_lba_start
        )
        logs.append(f"[image] FAT16: {len(fat16_image)} bytes")

        # 6. Assemble raw disk image
        image = bytearray(total_sectors * SECTOR_SIZE)

        mbr = write_mbr(partitions)
        image[0:512] = mbr

        boot_offset = boot_lba_start * SECTOR_SIZE
        image[boot_offset : boot_offset + len(fat16_image)] = fat16_image

        if not spec.use_initramfs:
            rootfs_offset = rootfs_lba_start * SECTOR_SIZE  # type: ignore[possibly-undefined]
            rootfs_end = rootfs_offset + len(rootfs_data)
            if rootfs_end > len(image):
                image.extend(b"\x00" * (rootfs_end - len(image)))
            image[rootfs_offset : rootfs_offset + len(rootfs_data)] = rootfs_data

        raw_image = bytes(image)
        logs.append(f"[image] raw image: {len(raw_image)} bytes")

        # 6. Compress
        logs.append("[image] compressing…")
        compressed = gzip.compress(raw_image, compresslevel=6, mtime=0)
        logs.append(f"[image] compressed: {len(compressed)} bytes")

    except Exception as exc:
        return ImageComposeResult(
            success=False,
            error=str(exc),
            logs=logs,
        )

    # 7. Repro chain
    env_spec = BuildEnvSpec(arch=spec.arch)
    env_hash = compute_env_hash(env_spec)
    config_hash = hashlib.sha256(
        (spec.rootfs_artifact_id + (spec.kernel_artifact_id or "")).encode()
    ).hexdigest()
    manifest = InputManifest(
        step_kind="image.compose",
        source_hash=spec.rootfs_artifact_id,
        config_hash=config_hash,
        env_hash=env_hash,
        extra={
            "distribution": spec.distribution,
            "profile": spec.profile,
            "board": spec.board,
        },
    )
    input_hash = compute_input_hash(manifest)
    repro_rec = make_repro_record(manifest, hashlib.sha256(compressed).hexdigest())

    # 8. Ingest
    try:
        artifact = ingest_blob(
            data=compressed,
            store_root=store_root,
            store_key=spec.store_key(),
            kind="image",
            name=f"{spec.distribution}-{spec.profile}-{spec.board}",
            version="latest",
            arch=spec.arch,
            media_type="application/gzip",
            db_url=db_url,
            retention_class="staging",
            input_hash=input_hash,
            repro_record=repro_rec,
        )
    except Exception as exc:
        return ImageComposeResult(
            success=False,
            error=f"ingest failed: {exc}",
            logs=logs,
        )

    logs.append(f"[image] artifact ingested: {artifact.id}")

    return ImageComposeResult(
        success=True,
        artifact_id=artifact.id,
        image_size_bytes=len(compressed),
        boot_files=sorted(boot_files.keys()),
        logs=logs,
    )
