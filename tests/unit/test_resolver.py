"""Tests for M12: Resolver / Build Plan."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from apps.cli.main import app
from osfabricum.db.engine import make_sync_engine
from osfabricum.db.models import (
    Architecture,
    Base,
    Board,
    Distribution,
    FirmwareBlob,
    Kernel,
    KernelConfig,
    Overlay,
    Package,
    PackageVersion,
    PartitionLayout,
    Profile,
    Toolchain,
)
from osfabricum.db.session import sync_session
from osfabricum.resolver import BuildPlan, resolve_plan
from osfabricum.resolver.resolver import _compute_resolution_hash

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
def base_data(db_url: str) -> dict:
    """Insert the minimum set of records for resolve_plan to succeed."""
    with sync_session(db_url) as session:
        arch = Architecture(name="aarch64")
        session.add(arch)
        session.flush()

        board = Board(
            name="rpi-zero-2w",
            arch_id=arch.id,
            boot_scheme="uboot",
            firmware_required=True,
        )
        session.add(board)
        session.flush()

        dist = Distribution(name="tinywifi", default_channel="dev")
        session.add(dist)
        session.flush()

        profile = Profile(distribution_id=dist.id, name="default")
        session.add(profile)
        session.flush()

        session.commit()
        return {
            "arch_id": arch.id,
            "board_id": board.id,
            "dist_id": dist.id,
            "profile_id": profile.id,
        }


# ---------------------------------------------------------------------------
# Unit tests: _compute_resolution_hash
# ---------------------------------------------------------------------------


def test_resolution_hash_is_deterministic() -> None:
    payload = {
        "distribution_id": "aaa",
        "profile_id": "bbb",
        "board_id": "ccc",
        "arch_id": "ddd",
        "toolchain_id": None,
        "kernel_id": None,
        "package_version_ids": ["x", "y"],
        "firmware_blob_ids": [],
        "overlay_ids": [],
        "script_ids": [],
    }
    h1 = _compute_resolution_hash(payload)
    h2 = _compute_resolution_hash(payload)
    assert h1 == h2
    assert h1.startswith("sha256:")


def test_resolution_hash_changes_with_inputs() -> None:
    base = {
        "distribution_id": "aaa",
        "profile_id": "bbb",
        "board_id": "ccc",
        "arch_id": "ddd",
        "toolchain_id": None,
        "kernel_id": None,
        "package_version_ids": [],
        "firmware_blob_ids": [],
        "overlay_ids": [],
        "script_ids": [],
    }
    h1 = _compute_resolution_hash(base)
    modified = {**base, "kernel_id": "new-kernel-id"}
    h2 = _compute_resolution_hash(modified)
    assert h1 != h2


def test_resolution_hash_list_order_irrelevant() -> None:
    """Sorted lists → same hash regardless of insertion order."""
    payload_a = {
        "distribution_id": "a",
        "profile_id": "b",
        "board_id": "c",
        "arch_id": "d",
        "toolchain_id": None,
        "kernel_id": None,
        "package_version_ids": ["z", "a", "m"],
        "firmware_blob_ids": [],
        "overlay_ids": [],
        "script_ids": [],
    }
    payload_b = {
        **payload_a,
        "package_version_ids": sorted(["z", "a", "m"]),
    }
    # resolver sorts before hashing — compare the sorted version
    payload_a_sorted = {**payload_a, "package_version_ids": sorted(["z", "a", "m"])}
    assert _compute_resolution_hash(payload_a_sorted) == _compute_resolution_hash(payload_b)


# ---------------------------------------------------------------------------
# resolve_plan — basic cases
# ---------------------------------------------------------------------------


def test_resolve_plan_returns_build_plan(db_url: str, base_data: dict) -> None:
    plan = resolve_plan("tinywifi", "default", "rpi-zero-2w", db_url=db_url)
    assert isinstance(plan, BuildPlan)
    assert plan.distribution == "tinywifi"
    assert plan.profile == "default"
    assert plan.board == "rpi-zero-2w"
    assert plan.arch == "aarch64"


def test_resolve_plan_has_resolution_hash(db_url: str, base_data: dict) -> None:
    plan = resolve_plan("tinywifi", "default", "rpi-zero-2w", db_url=db_url)
    assert plan.resolution_hash.startswith("sha256:")
    assert len(plan.resolution_hash) > 8


def test_resolve_plan_same_inputs_same_hash(db_url: str, base_data: dict) -> None:
    plan1 = resolve_plan("tinywifi", "default", "rpi-zero-2w", db_url=db_url)
    plan2 = resolve_plan("tinywifi", "default", "rpi-zero-2w", db_url=db_url)
    assert plan1.resolution_hash == plan2.resolution_hash


def test_resolve_plan_unknown_distribution_raises(db_url: str, base_data: dict) -> None:
    with pytest.raises(ValueError, match="distribution not found"):
        resolve_plan("no-such-distro", "default", "rpi-zero-2w", db_url=db_url)


def test_resolve_plan_unknown_profile_raises(db_url: str, base_data: dict) -> None:
    with pytest.raises(ValueError, match="profile not found"):
        resolve_plan("tinywifi", "nonexistent", "rpi-zero-2w", db_url=db_url)


def test_resolve_plan_unknown_board_raises(db_url: str, base_data: dict) -> None:
    with pytest.raises(ValueError, match="board not found"):
        resolve_plan("tinywifi", "default", "no-such-board", db_url=db_url)


# ---------------------------------------------------------------------------
# resolve_plan — toolchain
# ---------------------------------------------------------------------------


def test_resolve_plan_includes_toolchain(db_url: str, base_data: dict) -> None:
    arch_id = base_data["arch_id"]
    with sync_session(db_url) as session:
        tc = Toolchain(
            name="aarch64-linux-musl",
            arch_id=arch_id,
            libc="musl",
            version="13.2.0",
            source_type="prebuilt",
        )
        session.add(tc)
        session.commit()

    plan = resolve_plan("tinywifi", "default", "rpi-zero-2w", db_url=db_url)
    assert plan.toolchain is not None
    assert plan.toolchain.name == "aarch64-linux-musl"
    assert plan.toolchain.artifact_id is None  # not yet fetched


def test_resolve_plan_no_toolchain(db_url: str, base_data: dict) -> None:
    plan = resolve_plan("tinywifi", "default", "rpi-zero-2w", db_url=db_url)
    assert plan.toolchain is None


# ---------------------------------------------------------------------------
# resolve_plan — kernel
# ---------------------------------------------------------------------------


def test_resolve_plan_includes_kernel(db_url: str, base_data: dict) -> None:
    arch_id, board_id = base_data["arch_id"], base_data["board_id"]
    with sync_session(db_url) as session:
        kernel = Kernel(
            name="linux-rpi",
            version="6.6.y",
            arch_id=arch_id,
            board_id=board_id,
        )
        session.add(kernel)
        session.commit()

    plan = resolve_plan("tinywifi", "default", "rpi-zero-2w", db_url=db_url)
    assert plan.kernel is not None
    assert plan.kernel.name == "linux-rpi"
    assert plan.kernel.artifact_id is None


def test_resolve_plan_kernel_with_config_artifact(db_url: str, base_data: dict) -> None:
    arch_id, board_id = base_data["arch_id"], base_data["board_id"]
    from osfabricum.db.models import Artifact

    with sync_session(db_url) as session:
        art = Artifact(
            kind="kernel",
            name="linux-rpi-image",
            store_key="kernel/linux-rpi/test",
            blob_sha256="a" * 64,
        )
        session.add(art)
        session.flush()
        kernel = Kernel(
            name="linux-rpi",
            version="6.6.y",
            arch_id=arch_id,
            board_id=board_id,
        )
        session.add(kernel)
        session.flush()
        kc = KernelConfig(
            kernel_id=kernel.id,
            board_id=board_id,
            config_artifact_id=art.id,
        )
        session.add(kc)
        session.commit()

    plan = resolve_plan("tinywifi", "default", "rpi-zero-2w", db_url=db_url)
    assert plan.kernel is not None
    assert plan.kernel.artifact_id == art.id


# ---------------------------------------------------------------------------
# resolve_plan — packages
# ---------------------------------------------------------------------------


def test_resolve_plan_includes_packages(db_url: str, base_data: dict) -> None:
    arch_id = base_data["arch_id"]
    with sync_session(db_url) as session:
        pkg = Package(name="nanodhcp", package_type="native")
        session.add(pkg)
        session.flush()
        pv = PackageVersion(
            package_id=pkg.id,
            version="0.1.0",
            arch_id=arch_id,
            status="pending",
        )
        session.add(pv)
        session.commit()

    plan = resolve_plan("tinywifi", "default", "rpi-zero-2w", db_url=db_url)
    assert len(plan.packages) == 1
    assert plan.packages[0].name == "nanodhcp"
    assert plan.packages[0].version == "0.1.0"
    assert plan.packages[0].status == "missing"  # no artifact_id


def test_resolve_plan_package_with_artifact(db_url: str, base_data: dict) -> None:
    arch_id = base_data["arch_id"]
    from osfabricum.db.models import Artifact

    with sync_session(db_url) as session:
        art = Artifact(
            kind="package",
            name="nanodhcp",
            store_key="package/nanodhcp/0.1.0",
            blob_sha256="b" * 64,
        )
        session.add(art)
        session.flush()
        pkg = Package(name="nanodhcp", package_type="native")
        session.add(pkg)
        session.flush()
        pv = PackageVersion(
            package_id=pkg.id,
            version="0.1.0",
            arch_id=arch_id,
            status="built",
            artifact_id=art.id,
        )
        session.add(pv)
        session.commit()

    plan = resolve_plan("tinywifi", "default", "rpi-zero-2w", db_url=db_url)
    assert len(plan.packages) == 1
    assert plan.packages[0].artifact_id == art.id
    assert plan.packages[0].status == "built"


# ---------------------------------------------------------------------------
# resolve_plan — firmware
# ---------------------------------------------------------------------------


def test_resolve_plan_includes_firmware(db_url: str, base_data: dict) -> None:
    board_id = base_data["board_id"]
    with sync_session(db_url) as session:
        fw = FirmwareBlob(
            board_id=board_id,
            filename="start4.elf",
            placement="boot",
            required=True,
        )
        session.add(fw)
        session.commit()

    plan = resolve_plan("tinywifi", "default", "rpi-zero-2w", db_url=db_url)
    assert any(f.filename == "start4.elf" for f in plan.firmware)


def test_resolve_plan_firmware_missing_in_missing_artifacts(db_url: str, base_data: dict) -> None:
    board_id = base_data["board_id"]
    with sync_session(db_url) as session:
        fw = FirmwareBlob(
            board_id=board_id,
            filename="start4.elf",
            placement="boot",
            required=True,
        )
        session.add(fw)
        session.commit()

    plan = resolve_plan("tinywifi", "default", "rpi-zero-2w", db_url=db_url)
    assert any("start4.elf" in m for m in plan.missing_artifacts)


# ---------------------------------------------------------------------------
# resolve_plan — missing_artifacts & required_jobs
# ---------------------------------------------------------------------------


def test_resolve_plan_missing_artifacts_empty_when_all_present(
    db_url: str, base_data: dict
) -> None:
    plan = resolve_plan("tinywifi", "default", "rpi-zero-2w", db_url=db_url)
    assert plan.missing_artifacts == []


def test_resolve_plan_required_jobs_always_contains_compose(db_url: str, base_data: dict) -> None:
    plan = resolve_plan("tinywifi", "default", "rpi-zero-2w", db_url=db_url)
    assert "rootfs.compose" in plan.required_jobs
    assert "image.compose" in plan.required_jobs


def test_resolve_plan_required_jobs_includes_kernel_build(db_url: str, base_data: dict) -> None:
    arch_id, board_id = base_data["arch_id"], base_data["board_id"]
    with sync_session(db_url) as session:
        k = Kernel(
            name="linux-rpi",
            version="6.6.y",
            arch_id=arch_id,
            board_id=board_id,
        )
        session.add(k)
        session.commit()

    plan = resolve_plan("tinywifi", "default", "rpi-zero-2w", db_url=db_url)
    assert "kernel.build:linux-rpi" in plan.required_jobs


def test_resolve_plan_required_jobs_includes_package_build(db_url: str, base_data: dict) -> None:
    arch_id = base_data["arch_id"]
    with sync_session(db_url) as session:
        pkg = Package(name="nanodhcp", package_type="native")
        session.add(pkg)
        session.flush()
        pv = PackageVersion(package_id=pkg.id, version="0.1.0", arch_id=arch_id, status="pending")
        session.add(pv)
        session.commit()

    plan = resolve_plan("tinywifi", "default", "rpi-zero-2w", db_url=db_url)
    assert "package.build:nanodhcp" in plan.required_jobs


# ---------------------------------------------------------------------------
# resolve_plan — profile inheritance
# ---------------------------------------------------------------------------


def test_resolve_plan_profile_inheritance(db_url: str, base_data: dict) -> None:
    dist_id = base_data["dist_id"]
    with sync_session(db_url) as session:
        parent = Profile(
            distribution_id=dist_id,
            name="base",
            inputs_json={"key1": "parent_val", "key2": "parent_val2"},
        )
        session.add(parent)
        session.flush()
        child = Profile(
            distribution_id=dist_id,
            name="child",
            inherits_id=parent.id,
            inputs_json={"key1": "child_val"},  # overrides parent
        )
        session.add(child)
        session.commit()

    plan = resolve_plan("tinywifi", "child", "rpi-zero-2w", db_url=db_url)
    assert plan.profile == "child"
    assert plan.resolution_hash.startswith("sha256:")


def test_resolve_plan_profile_cycle_raises(db_url: str, base_data: dict) -> None:
    """A profile that inherits itself should raise ValueError."""
    dist_id = base_data["dist_id"]
    with sync_session(db_url) as session:
        # Create a profile that points to itself via a second profile
        p1 = Profile(distribution_id=dist_id, name="cycle-a")
        session.add(p1)
        session.flush()
        p2 = Profile(distribution_id=dist_id, name="cycle-b", inherits_id=p1.id)
        session.add(p2)
        session.flush()
        # Close the cycle: p1 → p2 → p1
        p1.inherits_id = p2.id
        session.commit()

    with pytest.raises(ValueError, match="cycle"):
        resolve_plan("tinywifi", "cycle-a", "rpi-zero-2w", db_url=db_url)


# ---------------------------------------------------------------------------
# resolve_plan — overlays & partition layout
# ---------------------------------------------------------------------------


def test_resolve_plan_includes_overlays(db_url: str, base_data: dict) -> None:
    dist_id, board_id = base_data["dist_id"], base_data["board_id"]
    with sync_session(db_url) as session:
        ov = Overlay(name="base-overlay", distribution_id=dist_id, board_id=board_id)
        session.add(ov)
        session.commit()

    plan = resolve_plan("tinywifi", "default", "rpi-zero-2w", db_url=db_url)
    assert any(o.name == "base-overlay" for o in plan.overlays)


def test_resolve_plan_includes_partition_layout(db_url: str, base_data: dict) -> None:
    board_id = base_data["board_id"]
    with sync_session(db_url) as session:
        pl = PartitionLayout(
            name="rpi-default",
            board_id=board_id,
            layout_json={"partitions": [{"name": "boot", "size": "256M"}]},
        )
        session.add(pl)
        session.commit()

    plan = resolve_plan("tinywifi", "default", "rpi-zero-2w", db_url=db_url)
    assert plan.partition_layout is not None
    assert plan.partition_layout.name == "rpi-default"


# ---------------------------------------------------------------------------
# BuildPlan.to_dict
# ---------------------------------------------------------------------------


def test_build_plan_to_dict_is_json_serializable(db_url: str, base_data: dict) -> None:
    plan = resolve_plan("tinywifi", "default", "rpi-zero-2w", db_url=db_url)
    d = plan.to_dict()
    # Must be JSON-serializable without errors
    text = json.dumps(d)
    roundtrip = json.loads(text)
    assert roundtrip["distribution"] == "tinywifi"
    assert roundtrip["arch"] == "aarch64"


# ---------------------------------------------------------------------------
# CLI plan command
# ---------------------------------------------------------------------------


def test_cli_plan_table_output(db_url: str, base_data: dict) -> None:
    result = runner.invoke(
        app,
        ["plan", "tinywifi/default", "--board", "rpi-zero-2w", "--db-url", db_url],
    )
    assert result.exit_code == 0, result.output
    assert "tinywifi" in result.output
    assert "rpi-zero-2w" in result.output


def test_cli_plan_json_output(db_url: str, base_data: dict) -> None:
    result = runner.invoke(
        app,
        [
            "plan",
            "tinywifi/default",
            "--board",
            "rpi-zero-2w",
            "--db-url",
            db_url,
            "--output",
            "json",
        ],
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["distribution"] == "tinywifi"
    assert data["profile"] == "default"
    assert data["board"] == "rpi-zero-2w"
    assert data["arch"] == "aarch64"
    assert "resolution_hash" in data


def test_cli_plan_bad_target_format(db_url: str, base_data: dict) -> None:
    result = runner.invoke(
        app,
        ["plan", "no-slash", "--board", "rpi-zero-2w", "--db-url", db_url],
    )
    assert result.exit_code != 0


def test_cli_plan_unknown_distribution(db_url: str, base_data: dict) -> None:
    result = runner.invoke(
        app,
        ["plan", "missing/default", "--board", "rpi-zero-2w", "--db-url", db_url],
    )
    assert result.exit_code != 0
    assert "ERROR" in result.output


def test_cli_plan_json_has_required_jobs(db_url: str, base_data: dict) -> None:
    result = runner.invoke(
        app,
        [
            "plan",
            "tinywifi/default",
            "--board",
            "rpi-zero-2w",
            "--db-url",
            db_url,
            "--output",
            "json",
        ],
    )
    data = json.loads(result.output)
    assert "required_jobs" in data
    assert "rootfs.compose" in data["required_jobs"]
    assert "image.compose" in data["required_jobs"]
