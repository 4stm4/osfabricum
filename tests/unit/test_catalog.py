"""Tests for ``osfabricumctl catalog`` subcommands (M2)."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from typer.testing import CliRunner

from apps.cli.main import app
from osfabricum.db.engine import make_sync_engine
from osfabricum.db.models import Base

runner = CliRunner()


@pytest.fixture()
def db_path(tmp_path: Path) -> str:
    db_file = tmp_path / "test.db"
    url = f"sqlite:///{db_file}"
    engine = make_sync_engine(url)
    Base.metadata.create_all(engine)
    engine.dispose()
    return url


# ---------------------------------------------------------------------------
# catalog import — architectures
# ---------------------------------------------------------------------------


def test_import_architectures(db_path: str, tmp_path: Path) -> None:
    yaml_file = tmp_path / "archs.yaml"
    yaml_file.write_text(
        textwrap.dedent("""\
            apiVersion: osfabricum/v1
            kind: ArchitectureList
            items:
              - name: aarch64
              - name: x86_64
        """)
    )
    result = runner.invoke(
        app,
        ["catalog", "import", "--file", str(yaml_file), "--db-url", db_path],
    )
    assert result.exit_code == 0, result.output
    assert "2" in result.output


def test_import_architectures_idempotent(db_path: str, tmp_path: Path) -> None:
    yaml_file = tmp_path / "archs.yaml"
    yaml_file.write_text(
        textwrap.dedent("""\
            kind: ArchitectureList
            items:
              - name: aarch64
        """)
    )
    runner.invoke(app, ["catalog", "import", "--file", str(yaml_file), "--db-url", db_path])
    result = runner.invoke(
        app,
        ["catalog", "import", "--file", str(yaml_file), "--db-url", db_path],
    )
    assert result.exit_code == 0
    assert "0" in result.output


# ---------------------------------------------------------------------------
# catalog import — boards
# ---------------------------------------------------------------------------


def test_import_boards(db_path: str, tmp_path: Path) -> None:
    arch_file = tmp_path / "archs.yaml"
    arch_file.write_text(
        textwrap.dedent("""\
            kind: ArchitectureList
            items:
              - name: aarch64
              - name: x86_64
        """)
    )
    runner.invoke(app, ["catalog", "import", "--file", str(arch_file), "--db-url", db_path])

    board_file = tmp_path / "boards.yaml"
    board_file.write_text(
        textwrap.dedent("""\
            kind: BoardList
            items:
              - name: rpi-zero-2w
                arch: aarch64
                boot_scheme: rpi-firmware
                firmware_required: true
              - name: qemu-x86_64
                arch: x86_64
                boot_scheme: qemu
                firmware_required: false
        """)
    )
    result = runner.invoke(
        app,
        ["catalog", "import", "--file", str(board_file), "--db-url", db_path],
    )
    assert result.exit_code == 0, result.output
    assert "2" in result.output


def test_import_boards_missing_arch(db_path: str, tmp_path: Path) -> None:
    board_file = tmp_path / "boards.yaml"
    board_file.write_text(
        textwrap.dedent("""\
            kind: BoardList
            items:
              - name: my-board
                arch: missing-arch
                boot_scheme: unknown
        """)
    )
    result = runner.invoke(
        app,
        ["catalog", "import", "--file", str(board_file), "--db-url", db_path],
    )
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# catalog import — distributions
# ---------------------------------------------------------------------------


def test_import_distributions(db_path: str, tmp_path: Path) -> None:
    yaml_file = tmp_path / "dists.yaml"
    yaml_file.write_text(
        textwrap.dedent("""\
            kind: DistributionList
            items:
              - name: tinywifi
                description: Minimal Wi-Fi AP OS
                default_channel: dev
              - name: netos
                description: NetOS
                default_channel: stable
        """)
    )
    result = runner.invoke(
        app,
        ["catalog", "import", "--file", str(yaml_file), "--db-url", db_path],
    )
    assert result.exit_code == 0, result.output
    assert "2" in result.output


# ---------------------------------------------------------------------------
# catalog import — error cases
# ---------------------------------------------------------------------------


def test_import_file_not_found(db_path: str, tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["catalog", "import", "--file", str(tmp_path / "nope.yaml"), "--db-url", db_path],
    )
    assert result.exit_code != 0


def test_import_unknown_kind(db_path: str, tmp_path: Path) -> None:
    yaml_file = tmp_path / "unknown.yaml"
    yaml_file.write_text("kind: SomethingElse\nitems: []\n")
    result = runner.invoke(
        app,
        ["catalog", "import", "--file", str(yaml_file), "--db-url", db_path],
    )
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# catalog list
# ---------------------------------------------------------------------------


def _seed_all(db_path: str, tmp_path: Path) -> None:
    arch_file = tmp_path / "a.yaml"
    arch_file.write_text("kind: ArchitectureList\nitems:\n  - name: aarch64\n  - name: x86_64\n")
    runner.invoke(app, ["catalog", "import", "--file", str(arch_file), "--db-url", db_path])

    dist_file = tmp_path / "d.yaml"
    dist_file.write_text(
        "kind: DistributionList\nitems:\n"
        "  - name: tinywifi\n    description: AP OS\n    default_channel: dev\n"
    )
    runner.invoke(app, ["catalog", "import", "--file", str(dist_file), "--db-url", db_path])

    board_file = tmp_path / "b.yaml"
    board_file.write_text(
        "kind: BoardList\nitems:\n"
        "  - name: rpi-zero-2w\n    arch: aarch64\n"
        "    boot_scheme: rpi-firmware\n    firmware_required: true\n"
    )
    runner.invoke(app, ["catalog", "import", "--file", str(board_file), "--db-url", db_path])


def test_list_distributions(db_path: str, tmp_path: Path) -> None:
    _seed_all(db_path, tmp_path)
    result = runner.invoke(app, ["catalog", "list", "distributions", "--db-url", db_path])
    assert result.exit_code == 0, result.output
    assert "tinywifi" in result.output


def test_list_boards(db_path: str, tmp_path: Path) -> None:
    _seed_all(db_path, tmp_path)
    result = runner.invoke(app, ["catalog", "list", "boards", "--db-url", db_path])
    assert result.exit_code == 0, result.output
    assert "rpi-zero-2w" in result.output
    assert "aarch64" in result.output


def test_list_unknown(db_path: str, tmp_path: Path) -> None:
    result = runner.invoke(app, ["catalog", "list", "packages", "--db-url", db_path])
    assert result.exit_code != 0
