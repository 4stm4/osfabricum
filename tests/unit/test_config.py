"""Tests for M11: Config rendering, overlay, and first-boot tasks."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest
from sqlalchemy import select

from osfabricum.config.firstboot import install_first_boot_tasks
from osfabricum.config.overlay import apply_overlay, build_overlay
from osfabricum.config.renderer import render_template_str
from osfabricum.db.engine import make_sync_engine
from osfabricum.db.models import Architecture, Base, Board, Overlay
from osfabricum.db.session import sync_session

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
# render_template_str
# ---------------------------------------------------------------------------


def test_render_template_str_basic() -> None:
    result = render_template_str("Hello, ${name}!", {"name": "world"})
    assert result == b"Hello, world!"


def test_render_template_str_returns_bytes() -> None:
    out = render_template_str("val=$val", {"val": "42"})
    assert isinstance(out, bytes)


def test_render_template_str_non_str_coercion() -> None:
    out = render_template_str("n=$n", {"n": 123})  # type: ignore[dict-item]
    assert out == b"n=123"


def test_render_template_str_multiple_vars() -> None:
    tmpl = "HOSTNAME=${hostname}\nPORT=${port}"
    out = render_template_str(tmpl, {"hostname": "192.168.1.1", "port": "22"})
    assert b"HOSTNAME=192.168.1.1" in out
    assert b"PORT=22" in out


def test_render_template_str_missing_key_raises() -> None:
    with pytest.raises(KeyError):
        render_template_str("Hello ${missing}", {})


def test_render_template_str_unicode() -> None:
    out = render_template_str("Привет, ${name}!", {"name": "мир"})
    assert out == "Привет, мир!".encode()


def test_render_template_str_empty_template() -> None:
    assert render_template_str("", {}) == b""


def test_render_template_str_no_variables() -> None:
    out = render_template_str("static content", {})
    assert out == b"static content"


# ---------------------------------------------------------------------------
# install_first_boot_tasks
# ---------------------------------------------------------------------------


def test_install_first_boot_tasks_creates_scripts(tmp_path: Path) -> None:
    tasks = [
        {"name": "hostname", "script": "echo myhostname > /etc/hostname"},
        {"name": "resize-fs", "script": "resize2fs /dev/sda2"},
    ]
    written = install_first_boot_tasks(tasks=tasks, target_dir=tmp_path)
    assert len(written) == 2
    for p in written:
        assert p.exists()
        assert p.stat().st_size > 0


def test_install_first_boot_tasks_executable(tmp_path: Path) -> None:
    tasks = [{"name": "test", "script": "echo ok"}]
    (written,) = install_first_boot_tasks(tasks=tasks, target_dir=tmp_path)
    mode = written.stat().st_mode
    assert mode & stat.S_IXUSR, "script should be user-executable"
    assert mode & stat.S_IXGRP, "script should be group-executable"


def test_install_first_boot_tasks_ordering(tmp_path: Path) -> None:
    tasks = [
        {"name": "late", "script": "echo late", "order": 90},
        {"name": "early", "script": "echo early", "order": 10},
    ]
    written = install_first_boot_tasks(tasks=tasks, target_dir=tmp_path)
    filenames = [p.name for p in written]
    assert "10-early.sh" in filenames
    assert "90-late.sh" in filenames


def test_install_first_boot_tasks_default_order(tmp_path: Path) -> None:
    tasks = [{"name": "default-order", "script": "echo hi"}]
    (p,) = install_first_boot_tasks(tasks=tasks, target_dir=tmp_path)
    assert p.name == "50-default-order.sh"


def test_install_first_boot_tasks_description_in_script(tmp_path: Path) -> None:
    tasks = [{"name": "mything", "script": "echo x", "description": "My thing runs here"}]
    (p,) = install_first_boot_tasks(tasks=tasks, target_dir=tmp_path)
    content = p.read_text()
    assert "My thing runs here" in content


def test_install_first_boot_tasks_creates_directory(tmp_path: Path) -> None:
    rootfs = tmp_path / "rootfs"
    tasks = [{"name": "t", "script": "echo t"}]
    install_first_boot_tasks(tasks=tasks, target_dir=rootfs)
    assert (rootfs / "etc" / "osfab-firstboot.d").is_dir()


def test_install_first_boot_tasks_empty_list(tmp_path: Path) -> None:
    result = install_first_boot_tasks(tasks=[], target_dir=tmp_path)
    assert result == []


def test_install_first_boot_tasks_script_has_shebang(tmp_path: Path) -> None:
    tasks = [{"name": "check", "script": "echo check"}]
    (p,) = install_first_boot_tasks(tasks=tasks, target_dir=tmp_path)
    first_line = p.read_text().splitlines()[0]
    assert first_line == "#!/bin/sh"


# ---------------------------------------------------------------------------
# build_overlay / apply_overlay
# ---------------------------------------------------------------------------


def _make_overlay_src(tmp_path: Path) -> Path:
    """Create a small fake overlay source tree."""
    src = tmp_path / "overlay_src"
    (src / "etc").mkdir(parents=True)
    (src / "etc" / "motd").write_text("Welcome to OSFabricum\n")
    (src / "etc" / "hostname").write_text("osfab-device\n")
    return src


def test_build_overlay_creates_artifact(
    tmp_path: Path, db_url: str, store_root: Path
) -> None:
    src = _make_overlay_src(tmp_path)
    art = build_overlay(
        name="base-overlay",
        src_dir=src,
        store_root=store_root,
        db_url=db_url,
    )
    assert art.id is not None
    assert art.kind == "overlay"
    assert art.name == "base-overlay"


def test_build_overlay_upserts_db_row(
    tmp_path: Path, db_url: str, store_root: Path
) -> None:
    src = _make_overlay_src(tmp_path)
    build_overlay(name="test-overlay", src_dir=src, store_root=store_root, db_url=db_url)

    with sync_session(db_url) as session:
        row = session.scalar(select(Overlay).where(Overlay.name == "test-overlay"))
    assert row is not None
    assert row.artifact_id is not None


def test_build_overlay_second_call_updates_artifact(
    tmp_path: Path, db_url: str, store_root: Path
) -> None:
    src = _make_overlay_src(tmp_path)
    build_overlay(name="my-overlay", src_dir=src, store_root=store_root, db_url=db_url)

    # Modify source and rebuild
    (src / "etc" / "motd").write_text("Updated motd\n")
    art2 = build_overlay(name="my-overlay", src_dir=src, store_root=store_root, db_url=db_url)

    with sync_session(db_url) as session:
        row = session.scalar(select(Overlay).where(Overlay.name == "my-overlay"))
    assert row is not None
    assert row.artifact_id == art2.id


def test_build_overlay_without_db(tmp_path: Path, store_root: Path) -> None:
    """build_overlay without db_url should still return an Artifact."""
    src = _make_overlay_src(tmp_path)
    art = build_overlay(name="nodb-overlay", src_dir=src, store_root=store_root, db_url=None)
    assert art.id is not None


def test_apply_overlay_extracts_files(
    tmp_path: Path, db_url: str, store_root: Path
) -> None:
    src = _make_overlay_src(tmp_path)
    art = build_overlay(name="apply-test", src_dir=src, store_root=store_root, db_url=db_url)

    target = tmp_path / "rootfs"
    extracted = apply_overlay(
        artifact_id=art.id,
        target_dir=target,
        store_root=store_root,
        db_url=db_url,
    )
    assert len(extracted) > 0
    assert (target / "etc" / "motd").exists()
    assert (target / "etc" / "hostname").exists()


def test_apply_overlay_file_content(
    tmp_path: Path, db_url: str, store_root: Path
) -> None:
    src = _make_overlay_src(tmp_path)
    art = build_overlay(name="content-test", src_dir=src, store_root=store_root, db_url=db_url)
    target = tmp_path / "rootfs"
    apply_overlay(
        artifact_id=art.id,
        target_dir=target,
        store_root=store_root,
        db_url=db_url,
    )
    assert (target / "etc" / "motd").read_text() == "Welcome to OSFabricum\n"


def test_apply_overlay_creates_target_dir(
    tmp_path: Path, db_url: str, store_root: Path
) -> None:
    src = _make_overlay_src(tmp_path)
    art = build_overlay(name="mkdir-test", src_dir=src, store_root=store_root, db_url=db_url)

    target = tmp_path / "new" / "rootfs"
    assert not target.exists()
    apply_overlay(
        artifact_id=art.id,
        target_dir=target,
        store_root=store_root,
        db_url=db_url,
    )
    assert target.is_dir()


def test_apply_overlay_without_db_raises(tmp_path: Path, store_root: Path) -> None:
    with pytest.raises(ValueError, match="db_url is required"):
        apply_overlay(
            artifact_id="fake-id",
            target_dir=tmp_path / "root",
            store_root=store_root,
            db_url=None,
        )


def test_apply_overlay_missing_artifact_raises(
    tmp_path: Path, db_url: str, store_root: Path
) -> None:
    with pytest.raises(ValueError, match="artifact not found"):
        apply_overlay(
            artifact_id="00000000-0000-0000-0000-000000000000",
            target_dir=tmp_path / "root",
            store_root=store_root,
            db_url=db_url,
        )
