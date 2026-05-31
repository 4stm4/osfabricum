"""Tests for M11: Firmware fetch, catalog import, and CLI commands."""

from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml
from sqlalchemy import select
from typer.testing import CliRunner

from apps.cli.main import app
from osfabricum.db.engine import make_sync_engine
from osfabricum.db.models import Architecture, Base, Board, FirmwareBlob
from osfabricum.db.session import sync_session
from osfabricum.firmware.fetch import fetch_firmware_blob

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
def arch_id(db_url: str) -> str:
    with sync_session(db_url) as session:
        arch = Architecture(name="aarch64")
        session.add(arch)
        session.commit()
        session.refresh(arch)
        return arch.id


@pytest.fixture()
def board_id(db_url: str, arch_id: str) -> str:
    with sync_session(db_url) as session:
        board = Board(
            name="rpi-zero-2w",
            arch_id=arch_id,
            boot_scheme="uboot",
            firmware_required=True,
        )
        session.add(board)
        session.commit()
        session.refresh(board)
        return board.id


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FAKE_FIRMWARE = b"\x00\x01\x02\x03" * 256  # 1 KB fake binary
_FAKE_SHA256 = hashlib.sha256(_FAKE_FIRMWARE).hexdigest()


def _mock_urlopen(data: bytes = _FAKE_FIRMWARE):
    """Return a context-manager mock that yields a file-like object."""
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=MagicMock(read=MagicMock(return_value=data)))
    cm.__exit__ = MagicMock(return_value=False)
    return cm


# ---------------------------------------------------------------------------
# fetch_firmware_blob
# ---------------------------------------------------------------------------


def test_fetch_firmware_blob_returns_row(
    tmp_path: Path, db_url: str, store_root: Path, board_id: str
) -> None:
    with patch("osfabricum.firmware.fetch.urllib.request.urlopen", return_value=_mock_urlopen()):
        fb = fetch_firmware_blob(
            url="http://example.com/start4.elf",
            filename="start4.elf",
            board_id=board_id,
            store_root=store_root,
            db_url=db_url,
        )
    assert fb.filename == "start4.elf"
    assert fb.board_id == board_id


def test_fetch_firmware_blob_creates_db_row(
    tmp_path: Path, db_url: str, store_root: Path, board_id: str
) -> None:
    with patch("osfabricum.firmware.fetch.urllib.request.urlopen", return_value=_mock_urlopen()):
        fetch_firmware_blob(
            url="http://example.com/start4.elf",
            filename="start4.elf",
            board_id=board_id,
            store_root=store_root,
            db_url=db_url,
        )
    with sync_session(db_url) as session:
        row = session.scalar(
            select(FirmwareBlob).where(
                FirmwareBlob.board_id == board_id,
                FirmwareBlob.filename == "start4.elf",
            )
        )
    assert row is not None
    assert row.artifact_id is not None


def test_fetch_firmware_blob_correct_hash_passes(
    tmp_path: Path, db_url: str, store_root: Path, board_id: str
) -> None:
    with patch("osfabricum.firmware.fetch.urllib.request.urlopen", return_value=_mock_urlopen()):
        fb = fetch_firmware_blob(
            url="http://example.com/start4.elf",
            filename="start4.elf",
            board_id=board_id,
            expected_sha256=_FAKE_SHA256,
            store_root=store_root,
            db_url=db_url,
        )
    assert fb.filename == "start4.elf"


def test_fetch_firmware_blob_hash_mismatch_raises(
    tmp_path: Path, db_url: str, store_root: Path, board_id: str
) -> None:
    with patch("osfabricum.firmware.fetch.urllib.request.urlopen", return_value=_mock_urlopen()):
        with pytest.raises(ValueError, match="SHA-256 mismatch"):
            fetch_firmware_blob(
                url="http://example.com/start4.elf",
                filename="start4.elf",
                board_id=board_id,
                expected_sha256="aaaa" * 16,  # wrong hash
                store_root=store_root,
                db_url=db_url,
            )


def test_fetch_firmware_blob_idempotent(
    tmp_path: Path, db_url: str, store_root: Path, board_id: str
) -> None:
    """Fetching the same blob twice does not create duplicate DB rows."""
    with patch("osfabricum.firmware.fetch.urllib.request.urlopen", return_value=_mock_urlopen()):
        fb1 = fetch_firmware_blob(
            url="http://example.com/start4.elf",
            filename="start4.elf",
            board_id=board_id,
            store_root=store_root,
            db_url=db_url,
        )
    with patch("osfabricum.firmware.fetch.urllib.request.urlopen", return_value=_mock_urlopen()):
        fb2 = fetch_firmware_blob(
            url="http://example.com/start4.elf",
            filename="start4.elf",
            board_id=board_id,
            store_root=store_root,
            db_url=db_url,
        )
    # Both return the same artifact (content-addressed, same store_key)
    assert fb1.artifact_id == fb2.artifact_id
    # Only one DB row should exist
    from sqlalchemy import select as sa_select

    with sync_session(db_url) as session:
        count = len(
            session.scalars(
                sa_select(FirmwareBlob).where(
                    FirmwareBlob.board_id == board_id,
                    FirmwareBlob.filename == "start4.elf",
                )
            ).all()
        )
    assert count == 1


def test_fetch_firmware_blob_placement(
    tmp_path: Path, db_url: str, store_root: Path, board_id: str
) -> None:
    with patch("osfabricum.firmware.fetch.urllib.request.urlopen", return_value=_mock_urlopen()):
        fb = fetch_firmware_blob(
            url="http://example.com/config.txt",
            filename="config.txt",
            board_id=board_id,
            placement="boot",
            store_root=store_root,
            db_url=db_url,
        )
    assert fb.placement == "boot"


# ---------------------------------------------------------------------------
# fetch_all_firmware
# ---------------------------------------------------------------------------


def test_fetch_all_firmware_skips_blobs_without_url(
    tmp_path: Path, db_url: str, store_root: Path, board_id: str
) -> None:
    """Blobs with no metadata_json['url'] are skipped."""
    with sync_session(db_url) as session:
        session.add(
            FirmwareBlob(
                board_id=board_id,
                filename="no-url.bin",
                placement="boot",
                required=False,
                metadata_json={},  # no url key
            )
        )
        session.commit()

    from osfabricum.firmware.fetch import fetch_all_firmware

    with patch("osfabricum.firmware.fetch.urllib.request.urlopen", return_value=_mock_urlopen()):
        results = fetch_all_firmware(
            board_name="rpi-zero-2w",
            store_root=store_root,
            db_url=db_url,
        )
    assert results == []


def test_fetch_all_firmware_fetches_url_blobs(
    tmp_path: Path, db_url: str, store_root: Path, board_id: str
) -> None:
    with sync_session(db_url) as session:
        session.add(
            FirmwareBlob(
                board_id=board_id,
                filename="start4.elf",
                placement="boot",
                required=True,
                metadata_json={"url": "http://example.com/start4.elf"},
            )
        )
        session.add(
            FirmwareBlob(
                board_id=board_id,
                filename="fixup4.dat",
                placement="boot",
                required=True,
                metadata_json={"url": "http://example.com/fixup4.dat"},
            )
        )
        session.commit()

    from osfabricum.firmware.fetch import fetch_all_firmware

    with patch("osfabricum.firmware.fetch.urllib.request.urlopen", return_value=_mock_urlopen()):
        results = fetch_all_firmware(
            board_name="rpi-zero-2w",
            store_root=store_root,
            db_url=db_url,
        )
    assert len(results) == 2


def test_fetch_all_firmware_unknown_board_raises(
    tmp_path: Path, db_url: str, store_root: Path
) -> None:
    from osfabricum.firmware.fetch import fetch_all_firmware

    with pytest.raises(ValueError, match="board not found"):
        fetch_all_firmware(
            board_name="nonexistent-board",
            store_root=store_root,
            db_url=db_url,
        )


# ---------------------------------------------------------------------------
# catalog import FirmwareList
# ---------------------------------------------------------------------------


def _make_firmware_yaml(path: Path, board_name: str) -> Path:
    data = {
        "apiVersion": "osfabricum/v1",
        "kind": "FirmwareList",
        "items": [
            {
                "board": board_name,
                "filename": "start4.elf",
                "placement": "boot",
                "required": True,
                "metadata": {"url": "http://example.com/start4.elf"},
            },
            {
                "board": board_name,
                "filename": "fixup4.dat",
                "placement": "boot",
                "required": True,
                "metadata": {"url": "http://example.com/fixup4.dat"},
            },
        ],
    }
    yaml_path = path / "firmware.yaml"
    yaml_path.write_text(yaml.dump(data))
    return yaml_path


def test_catalog_import_firmware_list(
    tmp_path: Path, db_url: str, board_id: str
) -> None:
    yaml_path = _make_firmware_yaml(tmp_path, "rpi-zero-2w")
    result = runner.invoke(
        app,
        ["catalog", "import", "--file", str(yaml_path), "--db-url", db_url],
    )
    assert result.exit_code == 0, result.output
    assert "2 firmware blob(s)" in result.output

    with sync_session(db_url) as session:
        rows = session.scalars(
            select(FirmwareBlob).where(FirmwareBlob.board_id == board_id)
        ).all()
    assert len(rows) == 2


def test_catalog_import_firmware_idempotent(
    tmp_path: Path, db_url: str, board_id: str
) -> None:
    """Importing the same file twice does not create duplicate rows."""
    yaml_path = _make_firmware_yaml(tmp_path, "rpi-zero-2w")
    for _ in range(2):
        result = runner.invoke(
            app,
            ["catalog", "import", "--file", str(yaml_path), "--db-url", db_url],
        )
        assert result.exit_code == 0, result.output

    with sync_session(db_url) as session:
        count = len(
            session.scalars(
                select(FirmwareBlob).where(FirmwareBlob.board_id == board_id)
            ).all()
        )
    assert count == 2


# ---------------------------------------------------------------------------
# firmware CLI commands
# ---------------------------------------------------------------------------


def test_firmware_list_command(
    tmp_path: Path, db_url: str, board_id: str
) -> None:
    with sync_session(db_url) as session:
        session.add(
            FirmwareBlob(
                board_id=board_id,
                filename="test.elf",
                placement="boot",
                required=True,
            )
        )
        session.commit()

    result = runner.invoke(app, ["firmware", "list", "--db-url", db_url])
    assert result.exit_code == 0, result.output
    assert "test.elf" in result.output


def test_firmware_list_with_board_filter(
    tmp_path: Path, db_url: str, board_id: str
) -> None:
    with sync_session(db_url) as session:
        session.add(
            FirmwareBlob(
                board_id=board_id,
                filename="filtered.elf",
                placement="boot",
                required=True,
            )
        )
        session.commit()

    result = runner.invoke(app, ["firmware", "list", "rpi-zero-2w", "--db-url", db_url])
    assert result.exit_code == 0, result.output
    assert "filtered.elf" in result.output


def test_firmware_list_unknown_board(tmp_path: Path, db_url: str) -> None:
    result = runner.invoke(app, ["firmware", "list", "no-such-board", "--db-url", db_url])
    assert result.exit_code != 0
