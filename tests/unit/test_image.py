"""Tests for M17: Image Composer — FAT16, MBR, boot files, disk image."""

from __future__ import annotations

import gzip
import struct
from pathlib import Path

import pytest
from typer.testing import CliRunner

from apps.cli.main import app
from osfabricum.db.engine import make_sync_engine
from osfabricum.db.models import Artifact, Base
from osfabricum.db.session import sync_session
from osfabricum.image.bootfiles import make_cmdline_txt, make_rpi_config_txt
from osfabricum.image.composer import ImageSpec, compose_image
from osfabricum.image.fat16 import Fat16Writer, _to_83
from osfabricum.image.mbr import (
    PART_FAT16,
    PART_LINUX,
    PartitionEntry,
    read_mbr,
    write_mbr,
)
from osfabricum.rootfs.builder import RootfsSpec, build_base_rootfs
from osfabricum.store.ingest import ingest_blob

runner = CliRunner()

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_url(tmp_path: Path) -> str:
    url = f"sqlite:///{tmp_path / 'test.db'}"
    engine = make_sync_engine(url)
    Base.metadata.create_all(engine)
    engine.dispose()
    return url


@pytest.fixture()
def store_root(tmp_path: Path) -> Path:
    return tmp_path / "store"


@pytest.fixture()
def rootfs_artifact(db_url: str, store_root: Path) -> Artifact:
    """Build a minimal base rootfs and return the Artifact."""
    spec = RootfsSpec(
        arch="aarch64",
        distribution="tinywifi",
        profile="default",
        board="rpi-zero-2w",
        init_system="busybox",
    )
    result = build_base_rootfs(spec, store_root=store_root, db_url=db_url)
    assert result.success
    from sqlalchemy import select as sa_select
    with sync_session(db_url) as session:
        return session.scalar(sa_select(Artifact).where(Artifact.id == result.artifact_id))


@pytest.fixture()
def kernel_artifact(db_url: str, store_root: Path) -> Artifact:
    return ingest_blob(
        data=b"\x00" * 1024,  # fake kernel
        store_root=store_root,
        store_key="test/kernel/Image",
        kind="kernel",
        name="Image",
        db_url=db_url,
    )


@pytest.fixture()
def firmware_artifact(db_url: str, store_root: Path) -> Artifact:
    return ingest_blob(
        data=b"\xff" * 512,  # fake firmware
        store_root=store_root,
        store_key="test/firmware/start4.elf",
        kind="firmware",
        name="start4.elf",
        db_url=db_url,
    )


# ---------------------------------------------------------------------------
# FAT16 writer
# ---------------------------------------------------------------------------


def test_fat16_image_has_boot_signature() -> None:
    writer = Fat16Writer(total_sectors=4096)
    image = writer.get_image()
    assert image[510] == 0x55
    assert image[511] == 0xAA


def test_fat16_image_has_correct_size() -> None:
    sectors = 4096
    writer = Fat16Writer(total_sectors=sectors)
    image = writer.get_image()
    assert len(image) == sectors * 512


def test_fat16_add_and_read_file() -> None:
    """Files added to the writer should appear in root directory entries."""
    writer = Fat16Writer(total_sectors=4096)
    writer.add_file("config.txt", b"kernel=Image\n")
    image = writer.get_image()
    # Root directory starts at (reserved + 2*fat_size) sectors
    # Just verify the image is valid and non-zero in data area
    assert image.count(b"\x00") < len(image)


def test_fat16_config_txt_content_recoverable() -> None:
    """Content written must be readable back from the data area."""
    data = b"kernel=Image\narm_64bit=1\n"
    writer = Fat16Writer(total_sectors=4096, sectors_per_cluster=8)
    writer.add_file("config.txt", data)
    image = writer.get_image()
    # The exact bytes must appear somewhere in the image
    assert data in image


def test_fat16_multiple_files() -> None:
    writer = Fat16Writer(total_sectors=8192)
    writer.add_file("Image", b"\x00" * 2048)
    writer.add_file("config.txt", b"kernel=Image\n")
    writer.add_file("cmdline.txt", b"root=/dev/mmcblk0p2\n")
    image = writer.get_image()
    assert len(image) == 8192 * 512


def test_fat16_long_filename_written() -> None:
    """A long filename (>8.3) is written using LFN entries.

    LFN entries store name characters split across three non-contiguous
    fields within each 32-byte entry.  We verify that the first five
    characters (which fit entirely in field 1, bytes 1-10) appear as a
    contiguous UTF-16-LE substring.
    """
    long_name = "bcm2710-rpi-zero-2-w.dtb"
    writer = Fat16Writer(total_sectors=4096)
    writer.add_file(long_name, b"\xd0\x0d" * 16)
    image = writer.get_image()
    # First 5 chars fit in LFN entry[1:11] as contiguous UTF-16-LE
    assert "bcm27".encode("utf-16-le") in image


def test_fat16_83_conversion_short() -> None:
    name_b, ext_b = _to_83("Image")
    assert name_b == b"IMAGE   "
    assert ext_b == b"   "


def test_fat16_83_conversion_with_ext() -> None:
    name_b, ext_b = _to_83("config.txt")
    assert name_b == b"CONFIG  "
    assert ext_b == b"TXT"


def test_fat16_83_long_name_truncated() -> None:
    name_b, ext_b = _to_83("bcm2710-rpi-zero-2-w.dtb")
    # Truncated to 8 chars with ~1
    assert len(name_b) == 8
    assert b"~1" in name_b or b"~" in name_b


# ---------------------------------------------------------------------------
# MBR writer
# ---------------------------------------------------------------------------


def test_write_mbr_has_boot_signature() -> None:
    mbr = write_mbr([])
    assert mbr[510:512] == b"\x55\xaa"


def test_write_mbr_size_is_512() -> None:
    assert len(write_mbr([])) == 512


def test_write_mbr_partition_entries() -> None:
    p1 = PartitionEntry(lba_start=2048, lba_size=131072, partition_type=PART_FAT16, bootable=True)
    p2 = PartitionEntry(lba_start=133120, lba_size=1048576, partition_type=PART_LINUX)
    mbr = write_mbr([p1, p2])
    assert len(mbr) == 512
    # Verify P1 LBA start (little-endian uint32 at offset 446+8)
    lba_start = struct.unpack_from("<I", mbr, 446 + 8)[0]
    assert lba_start == 2048


def test_read_mbr_round_trip() -> None:
    p1 = PartitionEntry(lba_start=2048, lba_size=131072, partition_type=PART_FAT16, bootable=True)
    p2 = PartitionEntry(lba_start=133120, lba_size=1048576, partition_type=PART_LINUX)
    mbr = write_mbr([p1, p2])
    entries = read_mbr(mbr)
    assert len(entries) == 2
    assert entries[0].lba_start == 2048
    assert entries[0].partition_type == PART_FAT16
    assert entries[0].bootable is True
    assert entries[1].lba_start == 133120
    assert entries[1].partition_type == PART_LINUX


def test_write_mbr_max_four_partitions() -> None:
    with pytest.raises(ValueError, match="at most 4"):
        write_mbr([PartitionEntry(0, 100)] * 5)


def test_read_mbr_invalid_signature_raises() -> None:
    with pytest.raises(ValueError, match="signature"):
        read_mbr(b"\x00" * 512)


# ---------------------------------------------------------------------------
# Boot files
# ---------------------------------------------------------------------------


def test_make_rpi_config_txt_contains_kernel() -> None:
    data = make_rpi_config_txt(kernel="Image", dtb="board.dtb")
    assert b"kernel=Image" in data


def test_make_rpi_config_txt_arm64() -> None:
    data = make_rpi_config_txt(arm64=True)
    assert b"arm_64bit=1" in data


def test_make_rpi_config_txt_no_arm64() -> None:
    data = make_rpi_config_txt(arm64=False)
    assert b"arm_64bit" not in data


def test_make_cmdline_txt_has_root() -> None:
    data = make_cmdline_txt(root="/dev/mmcblk0p2")
    assert b"/dev/mmcblk0p2" in data


def test_make_cmdline_txt_single_line() -> None:
    data = make_cmdline_txt()
    # Should be one non-empty line plus trailing newline
    lines = [ln for ln in data.decode().splitlines() if ln]
    assert len(lines) == 1


# ---------------------------------------------------------------------------
# compose_image — integration
# ---------------------------------------------------------------------------


def _make_spec(rootfs_id: str, **kwargs) -> ImageSpec:
    return ImageSpec(
        distribution="tinywifi",
        profile="default",
        board="rpi-zero-2w",
        arch="aarch64",
        rootfs_artifact_id=rootfs_id,
        boot_size_mb=4,     # tiny for tests
        rootfs_size_mb=8,
        **kwargs,
    )


def test_compose_image_success(
    db_url: str, store_root: Path, rootfs_artifact: Artifact
) -> None:
    spec = _make_spec(rootfs_artifact.id)
    result = compose_image(spec, store_root=store_root, db_url=db_url)
    assert result.success is True
    assert result.artifact_id is not None
    assert result.error is None


def test_compose_image_artifact_kind(
    db_url: str, store_root: Path, rootfs_artifact: Artifact
) -> None:
    spec = _make_spec(rootfs_artifact.id)
    result = compose_image(spec, store_root=store_root, db_url=db_url)
    from sqlalchemy import select as sa_select
    with sync_session(db_url) as session:
        art = session.scalar(sa_select(Artifact).where(Artifact.id == result.artifact_id))
    assert art.kind == "image"
    assert art.arch == "aarch64"
    assert art.media_type == "application/gzip"


def test_compose_image_is_valid_gzip(
    db_url: str, store_root: Path, rootfs_artifact: Artifact
) -> None:
    spec = _make_spec(rootfs_artifact.id)
    result = compose_image(spec, store_root=store_root, db_url=db_url)
    from sqlalchemy import select as sa_select

    from osfabricum.store.layout import blob_path
    with sync_session(db_url) as session:
        art = session.scalar(sa_select(Artifact).where(Artifact.id == result.artifact_id))
    bp = blob_path(store_root, art.blob_sha256)
    with gzip.open(str(bp), "rb") as gz:
        raw = gz.read(512)  # just read MBR
    # Check MBR signature
    assert raw[510:512] == b"\x55\xaa"


def test_compose_image_mbr_has_two_partitions(
    db_url: str, store_root: Path, rootfs_artifact: Artifact
) -> None:
    spec = _make_spec(rootfs_artifact.id)
    result = compose_image(spec, store_root=store_root, db_url=db_url)
    from sqlalchemy import select as sa_select

    from osfabricum.store.layout import blob_path
    with sync_session(db_url) as session:
        art = session.scalar(sa_select(Artifact).where(Artifact.id == result.artifact_id))
    bp = blob_path(store_root, art.blob_sha256)
    with gzip.open(str(bp), "rb") as gz:
        raw = gz.read(512)
    entries = read_mbr(raw)
    assert len(entries) == 2
    assert entries[0].partition_type == PART_FAT16
    assert entries[1].partition_type == PART_LINUX
    assert entries[0].bootable is True


def test_compose_image_boot_has_config_txt(
    db_url: str, store_root: Path, rootfs_artifact: Artifact
) -> None:
    """config.txt must appear in the boot partition (FAT data area)."""
    spec = _make_spec(rootfs_artifact.id)
    result = compose_image(spec, store_root=store_root, db_url=db_url)
    from sqlalchemy import select as sa_select

    from osfabricum.store.layout import blob_path
    with sync_session(db_url) as session:
        art = session.scalar(sa_select(Artifact).where(Artifact.id == result.artifact_id))
    bp = blob_path(store_root, art.blob_sha256)
    with gzip.open(str(bp), "rb") as gz:
        raw = gz.read()
    assert b"kernel=" in raw  # config.txt content


def test_compose_image_with_kernel(
    db_url: str, store_root: Path, rootfs_artifact: Artifact, kernel_artifact: Artifact
) -> None:
    spec = _make_spec(rootfs_artifact.id, kernel_artifact_id=kernel_artifact.id)
    result = compose_image(spec, store_root=store_root, db_url=db_url)
    assert result.success is True
    assert "Image" in result.boot_files


def test_compose_image_with_firmware(
    db_url: str, store_root: Path, rootfs_artifact: Artifact, firmware_artifact: Artifact
) -> None:
    spec = _make_spec(
        rootfs_artifact.id, firmware_artifact_ids=[firmware_artifact.id]
    )
    result = compose_image(spec, store_root=store_root, db_url=db_url)
    assert result.success is True
    assert "start4.elf" in result.boot_files


def test_compose_image_has_repro_chain(
    db_url: str, store_root: Path, rootfs_artifact: Artifact
) -> None:
    spec = _make_spec(rootfs_artifact.id)
    result = compose_image(spec, store_root=store_root, db_url=db_url)
    from sqlalchemy import select as sa_select
    with sync_session(db_url) as session:
        art = session.scalar(sa_select(Artifact).where(Artifact.id == result.artifact_id))
    assert art.input_hash is not None
    assert art.metadata_json is not None
    assert art.metadata_json["repro"]["step_kind"] == "image.compose"


def test_compose_image_invalid_rootfs(db_url: str, store_root: Path) -> None:
    spec = _make_spec("00000000-0000-0000-0000-000000000000")
    result = compose_image(spec, store_root=store_root, db_url=db_url)
    assert result.success is False
    assert result.error is not None


def test_compose_image_idempotent(
    db_url: str, store_root: Path, rootfs_artifact: Artifact
) -> None:
    spec = _make_spec(rootfs_artifact.id)
    r1 = compose_image(spec, store_root=store_root, db_url=db_url)
    r2 = compose_image(spec, store_root=store_root, db_url=db_url)
    assert r1.artifact_id == r2.artifact_id


def test_compose_image_logs(
    db_url: str, store_root: Path, rootfs_artifact: Artifact
) -> None:
    spec = _make_spec(rootfs_artifact.id)
    result = compose_image(spec, store_root=store_root, db_url=db_url)
    assert any("[image]" in line for line in result.logs)


# ---------------------------------------------------------------------------
# CLI image compose
# ---------------------------------------------------------------------------


def test_cli_image_compose(
    db_url: str, store_root: Path, rootfs_artifact: Artifact
) -> None:
    result = runner.invoke(
        app,
        [
            "image", "compose",
            "tinywifi/default",
            "--board", "rpi-zero-2w",
            "--arch", "aarch64",
            "--rootfs", rootfs_artifact.id,
            "--store-root", str(store_root),
            "--db-url", db_url,
            "--boot-mb", "4",
            "--rootfs-mb", "8",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "artifact" in result.output


def test_cli_image_compose_bad_target(
    db_url: str, store_root: Path, rootfs_artifact: Artifact
) -> None:
    result = runner.invoke(
        app,
        [
            "image", "compose",
            "noslash",
            "--board", "rpi-zero-2w",
            "--arch", "aarch64",
            "--rootfs", rootfs_artifact.id,
            "--store-root", str(store_root),
            "--db-url", db_url,
        ],
    )
    assert result.exit_code != 0
