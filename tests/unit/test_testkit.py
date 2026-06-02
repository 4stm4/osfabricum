"""Tests for M22: Test Runner (suites, QEMU harness, runner, CLI)."""

from __future__ import annotations

import gzip
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from apps.cli.main import app
from osfabricum.db.engine import make_sync_engine
from osfabricum.db.models import Base
from osfabricum.store.ingest import ingest_blob
from osfabricum.testkit.qemu import BootResult, QemuConfig, build_qemu_command
from osfabricum.testkit.runner import (
    evaluate_case,
    run_image_test,
    run_suite,
)
from osfabricum.testkit.suites import (
    BUILTIN_SUITES,
    TestCase,
    TestSuite,
    get_suite,
    list_suites,
)

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
    raw = b"\x55\xaa" * 2048
    gz = gzip.compress(raw, mtime=0)
    return ingest_blob(
        data=gz, store_root=store_root,
        store_key="images/x/test.img.gz", kind="image",
        name="tinywifi-default-rpi-zero-2w", arch="aarch64",
        media_type="application/gzip", db_url=db_url,
    )


_BOOT_OK = "[    0.0] Linux\n... Welcome to OSFabricum\nrpi login: "
_BOOT_PANIC = "[    0.0] Linux\nKernel panic - not syncing: VFS\n"


# ---------------------------------------------------------------------------
# suites
# ---------------------------------------------------------------------------


def test_builtin_suites_present() -> None:
    assert "smoke" in BUILTIN_SUITES
    assert "services" in BUILTIN_SUITES
    assert "network" in BUILTIN_SUITES


def test_get_suite_returns_suite() -> None:
    s = get_suite("smoke")
    assert isinstance(s, TestSuite)
    assert s.name == "smoke"
    assert len(s.cases) > 0


def test_get_suite_unknown_raises() -> None:
    with pytest.raises(KeyError, match="unknown test suite"):
        get_suite("does-not-exist")


def test_list_suites() -> None:
    suites = list_suites()
    assert len(suites) >= 3


def test_suite_to_dict() -> None:
    d = get_suite("smoke").to_dict()
    assert d["name"] == "smoke"
    assert isinstance(d["cases"], list)


# ---------------------------------------------------------------------------
# build_qemu_command
# ---------------------------------------------------------------------------


def test_build_qemu_command_aarch64(tmp_path: Path) -> None:
    cfg = QemuConfig(arch="aarch64", image_path=tmp_path / "img")
    cmd = build_qemu_command(cfg)
    assert cmd[0] == "qemu-system-aarch64"
    assert "-nographic" in cmd
    assert "virt" in cmd


def test_build_qemu_command_x86_64(tmp_path: Path) -> None:
    cfg = QemuConfig(arch="x86_64", image_path=tmp_path / "img")
    cmd = build_qemu_command(cfg)
    assert cmd[0] == "qemu-system-x86_64"


def test_build_qemu_command_readonly_disk(tmp_path: Path) -> None:
    cfg = QemuConfig(arch="aarch64", image_path=tmp_path / "img")
    cmd = build_qemu_command(cfg)
    drive_arg = next(a for a in cmd if a.startswith("file="))
    assert "readonly=on" in drive_arg


def test_build_qemu_command_with_kernel(tmp_path: Path) -> None:
    cfg = QemuConfig(
        arch="aarch64", image_path=tmp_path / "img",
        kernel_path=tmp_path / "Image", append="console=ttyAMA0",
    )
    cmd = build_qemu_command(cfg)
    assert "-kernel" in cmd
    assert "-append" in cmd


def test_build_qemu_command_with_dtb(tmp_path: Path) -> None:
    cfg = QemuConfig(
        arch="aarch64", image_path=tmp_path / "img", dtb_path=tmp_path / "b.dtb",
    )
    cmd = build_qemu_command(cfg)
    assert "-dtb" in cmd


# ---------------------------------------------------------------------------
# evaluate_case
# ---------------------------------------------------------------------------


def test_evaluate_boot_case_pass() -> None:
    case = TestCase(name="b", kind="boot", spec={"markers": ["login:"]})
    r = evaluate_case(case, _BOOT_OK, booted=True, executor=None)
    assert r.outcome == "pass"


def test_evaluate_boot_case_fail() -> None:
    case = TestCase(name="b", kind="boot", spec={"markers": ["NEVER"]})
    r = evaluate_case(case, "garbage output", booted=False, executor=None)
    assert r.outcome == "fail"


def test_evaluate_log_negate_pass() -> None:
    # "Kernel panic" absent → negate case passes
    case = TestCase(name="np", kind="log", spec={"pattern": "Kernel panic", "negate": True})
    r = evaluate_case(case, _BOOT_OK, booted=True, executor=None)
    assert r.outcome == "pass"


def test_evaluate_log_negate_fail() -> None:
    case = TestCase(name="np", kind="log", spec={"pattern": "Kernel panic", "negate": True})
    r = evaluate_case(case, _BOOT_PANIC, booted=False, executor=None)
    assert r.outcome == "fail"


def test_evaluate_log_present_pass() -> None:
    case = TestCase(name="w", kind="log", spec={"pattern": "Welcome to"})
    r = evaluate_case(case, _BOOT_OK, booted=True, executor=None)
    assert r.outcome == "pass"


def test_evaluate_service_case() -> None:
    transcript = "Starting nanodhcp...\n"
    case = TestCase(name="svc", kind="service", spec={"service": "nanodhcp"})
    r = evaluate_case(case, transcript, booted=True, executor=None)
    assert r.outcome == "pass"


def test_evaluate_command_skip_without_executor() -> None:
    case = TestCase(name="cmd", kind="command", spec={"command": "ip link"})
    r = evaluate_case(case, "", booted=True, executor=None)
    assert r.outcome == "skip"


def test_evaluate_command_pass_with_executor() -> None:
    case = TestCase(
        name="cmd", kind="command",
        spec={"command": "hostname", "expect_exit": 0, "expect_output": "rpi"},
    )
    r = evaluate_case(case, "", booted=True, executor=lambda c: (0, "rpi\n"))
    assert r.outcome == "pass"


def test_evaluate_command_fail_exit() -> None:
    case = TestCase(name="cmd", kind="command", spec={"command": "x", "expect_exit": 0})
    r = evaluate_case(case, "", booted=True, executor=lambda c: (1, ""))
    assert r.outcome == "fail"


def test_evaluate_command_fail_output() -> None:
    case = TestCase(
        name="cmd", kind="command",
        spec={"command": "x", "expect_exit": 0, "expect_output": "yes"},
    )
    r = evaluate_case(case, "", booted=True, executor=lambda c: (0, "no"))
    assert r.outcome == "fail"


def test_evaluate_unknown_kind_fails() -> None:
    case = TestCase(name="x", kind="weird", spec={})
    r = evaluate_case(case, "", booted=True, executor=None)
    assert r.outcome == "fail"


# ---------------------------------------------------------------------------
# run_suite (with pre-captured BootResult — no real QEMU)
# ---------------------------------------------------------------------------


def test_run_suite_smoke_pass(tmp_path: Path) -> None:
    cfg = QemuConfig(arch="aarch64", image_path=tmp_path / "img")
    boot = BootResult(booted=True, transcript=_BOOT_OK)
    result = run_suite(get_suite("smoke"), cfg, boot_result=boot)
    assert result.success is True
    assert result.booted is True
    assert result.failed == 0


def test_run_suite_smoke_fail_on_panic(tmp_path: Path) -> None:
    cfg = QemuConfig(arch="aarch64", image_path=tmp_path / "img")
    boot = BootResult(booted=False, transcript=_BOOT_PANIC)
    result = run_suite(get_suite("smoke"), cfg, boot_result=boot)
    assert result.success is False
    assert result.failed > 0


def test_run_suite_network_skips_without_executor(tmp_path: Path) -> None:
    cfg = QemuConfig(arch="aarch64", image_path=tmp_path / "img")
    boot = BootResult(booted=True, transcript=_BOOT_OK)
    result = run_suite(get_suite("network"), cfg, boot_result=boot)
    # command cases skipped → still counts as success (no failures)
    assert result.skipped == 2
    assert result.success is True


def test_run_suite_network_with_executor(tmp_path: Path) -> None:
    cfg = QemuConfig(arch="aarch64", image_path=tmp_path / "img")
    boot = BootResult(booted=True, transcript=_BOOT_OK)

    def ex(cmd: str) -> tuple[int, str]:
        if "ip link" in cmd:
            return 0, "1: lo: <LOOPBACK,UP>"
        return 0, "rpi-zero-2w"

    result = run_suite(get_suite("network"), cfg, executor=ex, boot_result=boot)
    assert result.passed == 2
    assert result.success is True


def test_run_suite_boot_error_propagates(tmp_path: Path) -> None:
    cfg = QemuConfig(arch="aarch64", image_path=tmp_path / "img")
    boot = BootResult(booted=False, transcript="", error="qemu not found")
    result = run_suite(get_suite("smoke"), cfg, boot_result=boot)
    assert result.success is False
    assert result.error == "qemu not found"


def test_run_suite_logs(tmp_path: Path) -> None:
    cfg = QemuConfig(arch="aarch64", image_path=tmp_path / "img")
    boot = BootResult(booted=True, transcript=_BOOT_OK)
    result = run_suite(get_suite("smoke"), cfg, boot_result=boot)
    assert any("[test]" in line for line in result.logs)


# ---------------------------------------------------------------------------
# run_image_test (patches _spawn_qemu so no real QEMU runs)
# ---------------------------------------------------------------------------


def test_run_image_test_success(
    db_url: str, store_root: Path, image_artifact
) -> None:
    with patch(
        "osfabricum.testkit.qemu._spawn_qemu",
        return_value=(0, _BOOT_OK, False),
    ):
        result = run_image_test(
            image_artifact.id, "smoke",
            store_root=store_root, db_url=db_url,
        )
    assert result.success is True
    assert result.booted is True


def test_run_image_test_boot_failure(
    db_url: str, store_root: Path, image_artifact
) -> None:
    with patch(
        "osfabricum.testkit.qemu._spawn_qemu",
        return_value=(None, _BOOT_PANIC, True),
    ):
        result = run_image_test(
            image_artifact.id, "smoke",
            store_root=store_root, db_url=db_url,
        )
    assert result.success is False


def test_run_image_test_artifact_not_found(
    db_url: str, store_root: Path
) -> None:
    result = run_image_test(
        "00000000-0000-0000-0000-000000000000", "smoke",
        store_root=store_root, db_url=db_url,
    )
    assert result.success is False
    assert "not found" in result.error


def test_run_image_test_qemu_missing(
    db_url: str, store_root: Path, image_artifact
) -> None:
    # _spawn_qemu returns the "binary not found" signature
    with patch(
        "osfabricum.testkit.qemu._spawn_qemu",
        return_value=(None, "", False),
    ):
        result = run_image_test(
            image_artifact.id, "smoke",
            store_root=store_root, db_url=db_url,
        )
    assert result.success is False
    assert "not found" in (result.error or "")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_test_list_suites() -> None:
    result = runner.invoke(app, ["test", "list-suites"])
    assert result.exit_code == 0, result.output
    assert "smoke" in result.output


def test_cli_test_run_success(
    db_url: str, store_root: Path, image_artifact
) -> None:
    with patch(
        "osfabricum.testkit.qemu._spawn_qemu",
        return_value=(0, _BOOT_OK, False),
    ):
        result = runner.invoke(
            app,
            [
                "test", "run", image_artifact.id,
                "--suite", "smoke",
                "--store-root", str(store_root),
                "--db-url", db_url,
            ],
        )
    assert result.exit_code == 0, result.output
    assert "passed" in result.output


def test_cli_test_run_unknown_suite(
    db_url: str, store_root: Path, image_artifact
) -> None:
    result = runner.invoke(
        app,
        [
            "test", "run", image_artifact.id,
            "--suite", "nonexistent",
            "--store-root", str(store_root),
            "--db-url", db_url,
        ],
    )
    assert result.exit_code != 0


def test_cli_test_run_boot_failure_exit_code(
    db_url: str, store_root: Path, image_artifact
) -> None:
    with patch(
        "osfabricum.testkit.qemu._spawn_qemu",
        return_value=(None, _BOOT_PANIC, True),
    ):
        result = runner.invoke(
            app,
            [
                "test", "run", image_artifact.id,
                "--suite", "smoke",
                "--store-root", str(store_root),
                "--db-url", db_url,
            ],
        )
    assert result.exit_code != 0
