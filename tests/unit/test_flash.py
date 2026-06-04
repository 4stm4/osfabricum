"""Tests for M21: Flash Utility (device allowlist, image flash, verify)."""

from __future__ import annotations

import gzip
import hashlib
from pathlib import Path

import pytest
from typer.testing import CliRunner

from apps.cli.main import app
from osfabricum.db.engine import make_sync_engine
from osfabricum.db.models import Base
from osfabricum.flasher.device import (
    DENYLIST,
    FlashDevice,
    is_device_allowed,
)
from osfabricum.flasher.flash import (
    _decompress_if_gzip,
    flash_image_artifact,
    flash_image_bytes,
)
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
def image_artifact(db_url: str, store_root: Path):
    """Ingest a gzip-compressed fake image artifact."""
    raw_image = b"\x55\xaa" * 4096  # 8 KB fake disk image
    gz = gzip.compress(raw_image, mtime=0)
    art = ingest_blob(
        data=gz,
        store_root=store_root,
        store_key="images/tinywifi/test.img.gz",
        kind="image",
        name="tinywifi-default-rpi-zero-2w",
        arch="aarch64",
        media_type="application/gzip",
        db_url=db_url,
    )
    return art, raw_image


# ---------------------------------------------------------------------------
# device allowlist
# ---------------------------------------------------------------------------


def test_is_device_allowed_match() -> None:
    assert is_device_allowed("/dev/sdb", ["/dev/sdb"]) is True


def test_is_device_allowed_glob() -> None:
    assert is_device_allowed("/dev/sdb", ["/dev/sd*"]) is True
    assert is_device_allowed("/dev/mmcblk1", ["/dev/mmcblk*"]) is True


def test_is_device_allowed_empty_allowlist() -> None:
    assert is_device_allowed("/dev/sdb", []) is False


def test_is_device_allowed_no_match() -> None:
    assert is_device_allowed("/dev/sdb", ["/dev/mmcblk*"]) is False


def test_is_device_allowed_denylist_blocks_sda() -> None:
    # Even if explicitly allowed, /dev/sda is denied
    assert is_device_allowed("/dev/sda", ["/dev/sda"]) is False


def test_is_device_allowed_denylist_blocks_nvme() -> None:
    assert is_device_allowed("/dev/nvme0n1", ["/dev/*"]) is False


def test_is_device_allowed_denylist_blocks_emmc_boot() -> None:
    assert is_device_allowed("/dev/mmcblk0boot0", ["/dev/mmcblk*"]) is False


def test_denylist_nonempty() -> None:
    assert "/dev/sda" in DENYLIST


def test_flash_device_human_size() -> None:
    assert FlashDevice(path="/dev/sdb", size_bytes=1024).human_size() == "1.0KB"
    assert FlashDevice(path="/dev/sdb", size_bytes=None).human_size() == "?"
    assert FlashDevice(path="/dev/sdb", size_bytes=5 * 1024**3).human_size() == "5.0GB"


# ---------------------------------------------------------------------------
# _decompress_if_gzip
# ---------------------------------------------------------------------------


def test_decompress_gzip() -> None:
    raw = b"hello world" * 100
    gz = gzip.compress(raw)
    assert _decompress_if_gzip(gz) == raw


def test_decompress_passthrough_non_gzip() -> None:
    raw = b"not gzipped"
    assert _decompress_if_gzip(raw) == raw


# ---------------------------------------------------------------------------
# flash_image_bytes
# ---------------------------------------------------------------------------


def test_flash_bytes_refuses_unlisted_device(tmp_path: Path) -> None:
    dev = tmp_path / "device.img"
    result = flash_image_bytes(b"data", str(dev), allowlist=[])
    assert result.success is False
    assert "allowlist" in result.error
    assert not dev.exists()  # nothing written


def test_flash_bytes_dry_run(tmp_path: Path) -> None:
    dev = tmp_path / "device.img"
    result = flash_image_bytes(b"data" * 100, str(dev), allowlist=[str(dev)], dry_run=True)
    assert result.success is True
    assert result.dry_run is True
    assert result.bytes_written == 0
    assert not dev.exists()  # dry-run writes nothing


def test_flash_bytes_writes_and_verifies(tmp_path: Path) -> None:
    dev = tmp_path / "device.img"
    data = b"\xde\xad\xbe\xef" * 1000
    result = flash_image_bytes(data, str(dev), allowlist=[str(dev)], verify=True)
    assert result.success is True
    assert result.verified is True
    assert result.bytes_written == len(data)
    assert dev.read_bytes() == data


def test_flash_bytes_no_verify(tmp_path: Path) -> None:
    dev = tmp_path / "device.img"
    data = b"x" * 500
    result = flash_image_bytes(data, str(dev), allowlist=[str(dev)], verify=False)
    assert result.success is True
    assert result.verified is False  # verification skipped
    assert dev.read_bytes() == data


def test_flash_bytes_sha256_recorded(tmp_path: Path) -> None:
    dev = tmp_path / "device.img"
    data = b"payload" * 200
    result = flash_image_bytes(data, str(dev), allowlist=[str(dev)])
    assert result.image_sha256 == hashlib.sha256(data).hexdigest()


def test_flash_bytes_glob_allowlist(tmp_path: Path) -> None:
    dev = tmp_path / "sdcard.img"
    result = flash_image_bytes(b"data" * 10, str(dev), allowlist=[str(tmp_path / "*.img")])
    assert result.success is True


def test_flash_bytes_multiblock(tmp_path: Path) -> None:
    """Write data larger than a single block."""
    dev = tmp_path / "device.img"
    data = b"\x01\x02\x03\x04" * 100_000  # 400 KB
    result = flash_image_bytes(data, str(dev), allowlist=[str(dev)], block_size=4096)
    assert result.success is True
    assert result.verified is True
    assert dev.read_bytes() == data


# ---------------------------------------------------------------------------
# flash_image_artifact
# ---------------------------------------------------------------------------


def test_flash_artifact_decompresses_and_writes(
    tmp_path: Path, db_url: str, store_root: Path, image_artifact
) -> None:
    art, raw_image = image_artifact
    dev = tmp_path / "device.img"
    result = flash_image_artifact(
        art.id,
        str(dev),
        store_root=store_root,
        allowlist=[str(dev)],
        db_url=db_url,
    )
    assert result.success is True
    assert result.verified is True
    # Device holds the DECOMPRESSED image, not the gzip
    assert dev.read_bytes() == raw_image


def test_flash_artifact_dry_run(
    tmp_path: Path, db_url: str, store_root: Path, image_artifact
) -> None:
    art, _ = image_artifact
    dev = tmp_path / "device.img"
    result = flash_image_artifact(
        art.id,
        str(dev),
        store_root=store_root,
        allowlist=[str(dev)],
        dry_run=True,
        db_url=db_url,
    )
    assert result.success is True
    assert result.dry_run is True
    assert not dev.exists()


def test_flash_artifact_unlisted_device_refused(
    tmp_path: Path, db_url: str, store_root: Path, image_artifact
) -> None:
    art, _ = image_artifact
    dev = tmp_path / "device.img"
    result = flash_image_artifact(
        art.id,
        str(dev),
        store_root=store_root,
        allowlist=[],
        db_url=db_url,
    )
    assert result.success is False
    assert "allowlist" in result.error


def test_flash_artifact_not_found(tmp_path: Path, db_url: str, store_root: Path) -> None:
    dev = tmp_path / "device.img"
    result = flash_image_artifact(
        "00000000-0000-0000-0000-000000000000",
        str(dev),
        store_root=store_root,
        allowlist=[str(dev)],
        db_url=db_url,
    )
    assert result.success is False
    assert "not found" in result.error


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_flash_requires_allow(
    tmp_path: Path, db_url: str, store_root: Path, image_artifact
) -> None:
    art, _ = image_artifact
    dev = tmp_path / "device.img"
    result = runner.invoke(
        app,
        [
            "flash",
            "image",
            art.id,
            "--device",
            str(dev),
            "--store-root",
            str(store_root),
            "--db-url",
            db_url,
        ],
    )
    # No --allow → refused
    assert result.exit_code != 0
    assert "allow" in result.output.lower()


def test_cli_flash_dry_run(tmp_path: Path, db_url: str, store_root: Path, image_artifact) -> None:
    art, _ = image_artifact
    dev = tmp_path / "device.img"
    result = runner.invoke(
        app,
        [
            "flash",
            "image",
            art.id,
            "--device",
            str(dev),
            "--store-root",
            str(store_root),
            "--allow",
            str(dev),
            "--dry-run",
            "--db-url",
            db_url,
        ],
    )
    assert result.exit_code == 0, result.output
    assert "dry-run" in result.output.lower()
    assert not dev.exists()


def test_cli_flash_writes(tmp_path: Path, db_url: str, store_root: Path, image_artifact) -> None:
    art, raw_image = image_artifact
    dev = tmp_path / "device.img"
    result = runner.invoke(
        app,
        [
            "flash",
            "image",
            art.id,
            "--device",
            str(dev),
            "--store-root",
            str(store_root),
            "--allow",
            str(dev),
            "--db-url",
            db_url,
        ],
    )
    assert result.exit_code == 0, result.output
    assert dev.read_bytes() == raw_image


def test_cli_flash_verify_command(
    tmp_path: Path, db_url: str, store_root: Path, image_artifact
) -> None:
    art, raw_image = image_artifact
    dev = tmp_path / "device.img"
    # Pre-write the correct contents
    dev.write_bytes(raw_image)
    result = runner.invoke(
        app,
        [
            "flash",
            "verify",
            art.id,
            "--device",
            str(dev),
            "--store-root",
            str(store_root),
            "--db-url",
            db_url,
        ],
    )
    assert result.exit_code == 0, result.output
    assert "matches" in result.output


def test_cli_flash_verify_mismatch(
    tmp_path: Path, db_url: str, store_root: Path, image_artifact
) -> None:
    art, _ = image_artifact
    dev = tmp_path / "device.img"
    dev.write_bytes(b"wrong contents")
    result = runner.invoke(
        app,
        [
            "flash",
            "verify",
            art.id,
            "--device",
            str(dev),
            "--store-root",
            str(store_root),
            "--db-url",
            db_url,
        ],
    )
    assert result.exit_code != 0
    assert "mismatch" in result.output.lower()


def test_cli_flash_list_devices(tmp_path: Path) -> None:
    result = runner.invoke(app, ["flash", "list-devices"])
    # Should not crash regardless of platform
    assert result.exit_code == 0
