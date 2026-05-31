"""Tests for M10: Kernel Model (build, cache, worker handler, CLI, catalog import)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import select
from typer.testing import CliRunner

from apps.cli.main import app
from osfabricum.db.engine import make_sync_engine
from osfabricum.db.models import Architecture, Artifact, Base, Board, Kernel, KernelConfig
from osfabricum.db.session import sync_session
from osfabricum.kernel.build import KernelBuildResult, build_kernel
from osfabricum.kernel.handler import make_kernel_build_handler
from osfabricum.queue.backend import JobView

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


@pytest.fixture()
def kernel_id(db_url: str, arch_id: str) -> str:
    with sync_session(db_url) as session:
        kernel = Kernel(
            name="linux-rpi",
            version="6.6.y",
            arch_id=arch_id,
            source_uri="https://github.com/raspberrypi/linux",
            source_ref="stable_20240529",
            metadata_json={
                "tarball_url": "https://github.com/raspberrypi/linux/archive/stable_20240529.tar.gz",
                "defconfig": "bcm2711_defconfig",
                "image_path": "arch/arm64/boot/Image",
                "dtbs": ["arch/arm64/boot/dts/broadcom/bcm2710-rpi-zero-2-w.dtb"],
                "patches": [],
            },
        )
        session.add(kernel)
        session.commit()
        session.refresh(kernel)
        return kernel.id


@pytest.fixture()
def fake_src(tmp_path: Path) -> Path:
    """Fake kernel source tree with pre-built outputs."""
    src = tmp_path / "linux-src"
    src.mkdir()
    # Create the files that _compile_kernel would normally produce
    image_dir = src / "arch" / "arm64" / "boot"
    image_dir.mkdir(parents=True)
    (image_dir / "Image").write_bytes(b"\x7fELF fake kernel image aarch64")
    dtb_dir = image_dir / "dts" / "broadcom"
    dtb_dir.mkdir(parents=True)
    (dtb_dir / "bcm2710-rpi-zero-2-w.dtb").write_bytes(b"fake dtb blob")
    mod_dir = src / "_modules"
    mod_dir.mkdir()
    (mod_dir / "lib" / "modules" / "6.6.0").mkdir(parents=True)
    (mod_dir / "lib" / "modules" / "6.6.0" / "modules.dep").write_text("# fake\n")
    return src


def _fake_compile(
    *,
    src_dir: Path,
    arch: str,
    cross_compile: str,
    image_target: str,
    dtb_patterns: list[str],
    jobs: int,
    logs: list[str],
    toolchain_root: Path | None = None,
) -> tuple[Path, list[Path], Path]:
    """Mock _compile_kernel — returns pre-created fake outputs."""
    image_path = src_dir / "arch" / "arm64" / "boot" / "Image"
    dtb_paths = [
        src_dir / "arch" / "arm64" / "boot" / "dts" / "broadcom" / "bcm2710-rpi-zero-2-w.dtb"
    ]
    mod_dir = src_dir / "_modules"
    logs.append("fake: make Image modules")
    return image_path, dtb_paths, mod_dir


# ---------------------------------------------------------------------------
# KernelBuildResult dataclass
# ---------------------------------------------------------------------------


def test_kernel_build_result_defaults() -> None:
    r = KernelBuildResult(success=True, source_hash="a" * 64, config_hash="b" * 64)
    assert r.image_artifact_id is None
    assert r.modules_artifact_id is None
    assert r.dtb_artifact_ids == []
    assert r.cache_hit is False
    assert r.error is None
    assert r.logs == []


# ---------------------------------------------------------------------------
# build_kernel — success path
# ---------------------------------------------------------------------------


def test_build_kernel_success(
    kernel_id: str, store_root: Path, db_url: str, fake_src: Path
) -> None:
    with patch("osfabricum.kernel.build._compile_kernel", side_effect=_fake_compile):
        result = build_kernel(
            "linux-rpi",
            store_root=store_root,
            board_name="rpi-zero-2w",
            src_dir=fake_src,
            db_url=db_url,
        )
    assert result.success is True
    assert result.error is None
    assert result.image_artifact_id is not None
    assert result.modules_artifact_id is not None
    assert len(result.dtb_artifact_ids) == 1


def test_build_kernel_result_hashes(
    kernel_id: str, store_root: Path, db_url: str, fake_src: Path
) -> None:
    with patch("osfabricum.kernel.build._compile_kernel", side_effect=_fake_compile):
        result = build_kernel(
            "linux-rpi",
            store_root=store_root,
            src_dir=fake_src,
            db_url=db_url,
        )
    assert len(result.source_hash) == 64
    assert len(result.config_hash) == 64
    int(result.source_hash, 16)
    int(result.config_hash, 16)


def test_build_kernel_logs_captured(
    kernel_id: str, store_root: Path, db_url: str, fake_src: Path
) -> None:
    with patch("osfabricum.kernel.build._compile_kernel", side_effect=_fake_compile):
        result = build_kernel(
            "linux-rpi",
            store_root=store_root,
            src_dir=fake_src,
            db_url=db_url,
        )
    assert result.success is True
    assert any("fake" in line for line in result.logs)


def test_build_kernel_artifacts_have_correct_kinds(
    kernel_id: str, store_root: Path, db_url: str, fake_src: Path
) -> None:
    with patch("osfabricum.kernel.build._compile_kernel", side_effect=_fake_compile):
        result = build_kernel(
            "linux-rpi",
            store_root=store_root,
            board_name="rpi-zero-2w",
            src_dir=fake_src,
            db_url=db_url,
        )
    with sync_session(db_url) as session:
        image_art = session.scalar(
            select(Artifact).where(Artifact.id == result.image_artifact_id)
        )
        mod_art = session.scalar(
            select(Artifact).where(Artifact.id == result.modules_artifact_id)
        )
        dtb_art = session.scalar(
            select(Artifact).where(Artifact.id == result.dtb_artifact_ids[0])
        )
    assert image_art.kind == "kernel"
    assert mod_art.kind == "kernel-modules"
    assert dtb_art.kind == "dtb"


def test_build_kernel_image_has_correct_content(
    kernel_id: str, store_root: Path, db_url: str, fake_src: Path
) -> None:
    with patch("osfabricum.kernel.build._compile_kernel", side_effect=_fake_compile):
        result = build_kernel(
            "linux-rpi",
            store_root=store_root,
            src_dir=fake_src,
            db_url=db_url,
        )
    with sync_session(db_url) as session:
        art = session.scalar(select(Artifact).where(Artifact.id == result.image_artifact_id))
    # Verify blob exists in store
    from osfabricum.store.layout import blob_path

    bp = blob_path(store_root, art.blob_sha256)
    assert bp.exists()
    assert bp.read_bytes() == b"\x7fELF fake kernel image aarch64"


def test_build_kernel_updates_kernel_config(
    kernel_id: str, board_id: str, store_root: Path, db_url: str, fake_src: Path
) -> None:
    with patch("osfabricum.kernel.build._compile_kernel", side_effect=_fake_compile):
        build_kernel(
            "linux-rpi",
            store_root=store_root,
            board_name="rpi-zero-2w",
            src_dir=fake_src,
            db_url=db_url,
        )
    with sync_session(db_url) as session:
        kc = session.scalar(
            select(KernelConfig).where(
                KernelConfig.kernel_id == kernel_id,
                KernelConfig.board_id == board_id,
            )
        )
    assert kc is not None
    assert kc.config_artifact_id is not None


def test_build_kernel_by_id(
    kernel_id: str, store_root: Path, db_url: str, fake_src: Path
) -> None:
    with patch("osfabricum.kernel.build._compile_kernel", side_effect=_fake_compile):
        result = build_kernel(
            kernel_id,
            store_root=store_root,
            src_dir=fake_src,
            db_url=db_url,
        )
    assert result.success is True


def test_build_kernel_not_found(store_root: Path, db_url: str) -> None:
    with pytest.raises(ValueError, match="kernel not found"):
        build_kernel("NONEXISTENT", store_root=store_root, db_url=db_url)


# ---------------------------------------------------------------------------
# Failure handling
# ---------------------------------------------------------------------------


def test_build_kernel_compile_failure(
    kernel_id: str, store_root: Path, db_url: str, fake_src: Path
) -> None:
    def _fail_compile(**_kwargs: object) -> None:
        raise RuntimeError("make failed: no cross-compiler found")

    with patch("osfabricum.kernel.build._compile_kernel", side_effect=_fail_compile):
        result = build_kernel(
            "linux-rpi",
            store_root=store_root,
            src_dir=fake_src,
            db_url=db_url,
        )
    assert result.success is False
    assert result.error is not None
    assert "no cross-compiler" in result.error


def test_build_kernel_failure_preserves_work_dir(
    kernel_id: str, store_root: Path, db_url: str, fake_src: Path
) -> None:
    def _fail_compile(**_kwargs: object) -> None:
        raise RuntimeError("build exploded")

    with patch("osfabricum.kernel.build._compile_kernel", side_effect=_fail_compile):
        result = build_kernel(
            "linux-rpi",
            store_root=store_root,
            src_dir=fake_src,
            db_url=db_url,
        )
    assert result.success is False
    assert result.work_dir is not None
    assert result.work_dir.exists()


# ---------------------------------------------------------------------------
# Cache deduplication
# ---------------------------------------------------------------------------


def test_build_kernel_cache_hit(
    kernel_id: str, store_root: Path, db_url: str, fake_src: Path
) -> None:
    with patch("osfabricum.kernel.build._compile_kernel", side_effect=_fake_compile):
        r1 = build_kernel(
            "linux-rpi",
            store_root=store_root,
            src_dir=fake_src,
            db_url=db_url,
        )
    assert r1.success is True
    assert r1.cache_hit is False

    with patch("osfabricum.kernel.build._compile_kernel", side_effect=_fake_compile):
        r2 = build_kernel(
            "linux-rpi",
            store_root=store_root,
            src_dir=fake_src,
            db_url=db_url,
        )
    assert r2.success is True
    assert r2.cache_hit is True
    assert r2.image_artifact_id == r1.image_artifact_id


def test_build_kernel_different_config_bypasses_cache(
    kernel_id: str, store_root: Path, db_url: str, fake_src: Path
) -> None:
    with patch("osfabricum.kernel.build._compile_kernel", side_effect=_fake_compile):
        r1 = build_kernel(
            "linux-rpi",
            store_root=store_root,
            src_dir=fake_src,
            config_data=b"CONFIG_A=y\n",
            db_url=db_url,
        )
        r2 = build_kernel(
            "linux-rpi",
            store_root=store_root,
            src_dir=fake_src,
            config_data=b"CONFIG_B=y\n",
            db_url=db_url,
        )
    assert r1.success and r2.success
    assert r2.cache_hit is False
    assert r1.image_artifact_id != r2.image_artifact_id


def test_build_kernel_same_src_produces_cache_hit(
    kernel_id: str, store_root: Path, fake_src: Path, db_url: str
) -> None:
    """Two calls with identical src_dir + no config produce a cache hit on the second."""
    compile_calls = []

    def _count_compile(**kwargs: object) -> tuple:
        compile_calls.append(1)
        return _fake_compile(**kwargs)

    with patch("osfabricum.kernel.build._compile_kernel", side_effect=_count_compile):
        r1 = build_kernel("linux-rpi", store_root=store_root, src_dir=fake_src, db_url=db_url)
        r2 = build_kernel("linux-rpi", store_root=store_root, src_dir=fake_src, db_url=db_url)

    assert r1.success and r2.success
    assert len(compile_calls) == 1  # second call is a cache hit → no recompile
    assert r2.cache_hit is True


# ---------------------------------------------------------------------------
# Catalog import — KernelList
# ---------------------------------------------------------------------------


def test_catalog_import_kernel_list(
    tmp_path: Path, db_url: str, arch_id: str, board_id: str
) -> None:
    yaml_file = tmp_path / "kernels.yaml"
    yaml_file.write_text(
        "apiVersion: osfabricum/v1\n"
        "kind: KernelList\n"
        "items:\n"
        "  - name: linux-rpi\n"
        "    version: '6.6.y'\n"
        "    arch: aarch64\n"
        "    board: rpi-zero-2w\n"
        "    source_uri: https://github.com/raspberrypi/linux\n"
        "    source_ref: stable_20240529\n"
        "    metadata:\n"
        "      defconfig: bcm2711_defconfig\n"
    )
    result = runner.invoke(
        app,
        ["catalog", "import", "--file", str(yaml_file), "--db-url", db_url],
    )
    assert result.exit_code == 0, result.output
    assert "1 kernel" in result.output

    with sync_session(db_url) as session:
        kernel = session.scalar(select(Kernel).where(Kernel.name == "linux-rpi"))
    assert kernel is not None
    assert kernel.version == "6.6.y"


def test_catalog_import_kernel_creates_kernel_config(
    tmp_path: Path, db_url: str, arch_id: str, board_id: str
) -> None:
    yaml_file = tmp_path / "kernels.yaml"
    yaml_file.write_text(
        "apiVersion: osfabricum/v1\n"
        "kind: KernelList\n"
        "items:\n"
        "  - name: linux-rpi\n"
        "    version: '6.6.y'\n"
        "    arch: aarch64\n"
        "    board: rpi-zero-2w\n"
    )
    result = runner.invoke(
        app,
        ["catalog", "import", "--file", str(yaml_file), "--db-url", db_url],
    )
    assert result.exit_code == 0, result.output

    with sync_session(db_url) as session:
        kernel = session.scalar(select(Kernel).where(Kernel.name == "linux-rpi"))
        kc = session.scalar(
            select(KernelConfig).where(
                KernelConfig.kernel_id == kernel.id,
                KernelConfig.board_id == board_id,
            )
        )
    assert kc is not None


def test_catalog_import_kernel_idempotent(
    tmp_path: Path, db_url: str, arch_id: str, board_id: str
) -> None:
    yaml_file = tmp_path / "kernels.yaml"
    yaml_file.write_text(
        "apiVersion: osfabricum/v1\n"
        "kind: KernelList\n"
        "items:\n"
        "  - name: linux-rpi\n"
        "    version: '6.6.y'\n"
        "    arch: aarch64\n"
    )
    runner.invoke(app, ["catalog", "import", "--file", str(yaml_file), "--db-url", db_url])
    result = runner.invoke(
        app, ["catalog", "import", "--file", str(yaml_file), "--db-url", db_url]
    )
    assert result.exit_code == 0
    assert "0 kernel" in result.output

    with sync_session(db_url) as session:
        count = len(session.scalars(select(Kernel)).all())
    assert count == 1


# ---------------------------------------------------------------------------
# Worker handler
# ---------------------------------------------------------------------------


def test_kernel_handler_dispatches(
    kernel_id: str, store_root: Path, db_url: str, fake_src: Path
) -> None:
    handler = make_kernel_build_handler(store_root, db_url=db_url)
    job = JobView(
        id="job-1",
        kind="kernel.build",
        status="claimed",
        worker_hostname="host",
        attempt=1,
        max_attempts=3,
        payload={
            "kernel_id": "linux-rpi",
            "board_name": "rpi-zero-2w",
            "jobs": 1,
        },
    )
    # Patch build_kernel at the handler's import site so the handler uses the mock
    mock_result = KernelBuildResult(
        success=True,
        source_hash="a" * 64,
        config_hash="b" * 64,
        image_artifact_id="img-1",
        modules_artifact_id="mod-1",
        dtb_artifact_ids=["dtb-1"],
    )
    with patch("osfabricum.kernel.handler.build_kernel", return_value=mock_result):
        handler(job)  # must not raise


def test_kernel_handler_raises_on_missing_kernel_id(store_root: Path, db_url: str) -> None:
    handler = make_kernel_build_handler(store_root, db_url=db_url)
    job = JobView(
        id="job-2",
        kind="kernel.build",
        status="claimed",
        worker_hostname="host",
        attempt=1,
        max_attempts=3,
        payload={},
    )
    with pytest.raises(ValueError, match="missing 'kernel_id'"):
        handler(job)


# ---------------------------------------------------------------------------
# CLI — kernel list / show
# ---------------------------------------------------------------------------


def test_cli_kernel_list(db_url: str, kernel_id: str) -> None:
    result = runner.invoke(app, ["kernel", "list", "--db-url", db_url])
    assert result.exit_code == 0, result.output
    assert "linux-rpi" in result.output
    assert "6.6.y" in result.output


def test_cli_kernel_show(db_url: str, kernel_id: str) -> None:
    result = runner.invoke(app, ["kernel", "show", "linux-rpi", "--db-url", db_url])
    assert result.exit_code == 0, result.output
    assert "linux-rpi" in result.output
    assert "6.6.y" in result.output


def test_cli_kernel_show_not_found(db_url: str) -> None:
    result = runner.invoke(app, ["kernel", "show", "NONEXISTENT", "--db-url", db_url])
    assert result.exit_code != 0


def test_cli_kernel_build(
    db_url: str, kernel_id: str, store_root: Path, fake_src: Path
) -> None:
    with patch("osfabricum.kernel.build._compile_kernel", side_effect=_fake_compile):
        result = runner.invoke(
            app,
            [
                "kernel",
                "build",
                "linux-rpi",
                "--board",
                "rpi-zero-2w",
                "--store",
                str(store_root),
                "--src-dir",
                str(fake_src),
                "--db-url",
                db_url,
            ],
        )
    assert result.exit_code == 0, result.output
    assert "OK" in result.output
    assert "image:" in result.output


def test_cli_kernel_build_not_found(db_url: str, store_root: Path) -> None:
    result = runner.invoke(
        app,
        [
            "kernel",
            "build",
            "NONEXISTENT",
            "--store",
            str(store_root),
            "--db-url",
            db_url,
        ],
    )
    assert result.exit_code != 0
