"""Tests for the Filesystem / Image Recipe Designer service (M34).

Exercises the estimator that makes image sizes *data* instead of the old
hardcoded ``boot_size_mb`` / ``rootfs_size_mb`` constants (G-06): fixed vs grow
partitions, size-policy alignment / reserve / free-space, A/B and rootfs
validation, and the deterministic plan hash. Also covers the recipe catalog.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from apps.api.app import create_app
from osfabricum import imagedesign as imd
from osfabricum.db.base import Base
from osfabricum.settings import Settings


@pytest.fixture
def db_url(tmp_path) -> Iterator[str]:
    url = f"sqlite:///{tmp_path / 'imd.db'}"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    engine.dispose()
    yield url


@pytest.fixture
def std(db_url: str) -> dict[str, str]:
    """A standard fixture set: ext4 + vfat profiles and an aligned size policy."""
    ext4 = imd.create_filesystem_profile("root-ext4", "ext4", db_url=db_url)
    vfat = imd.create_filesystem_profile("boot-vfat", "vfat", db_url=db_url)
    policy = imd.create_size_policy(
        "std", align_mb=4, reserve_mb=1, free_space_pct=0, min_free_mb=0, db_url=db_url
    )
    return {"ext4": ext4["id"], "vfat": vfat["id"], "policy": policy["id"]}


def _sd_recipe(db_url: str, ids: dict[str, str], *, rootfs_size: int | None = 200) -> str:
    """A boot(vfat, fixed 64) + rootfs(ext4, grow) recipe → recipe id."""
    layout = imd.create_partition_layout("sd", db_url=db_url)["id"]
    imd.add_partition(layout, "boot", "boot", filesystem_id=ids["vfat"], size_mb=64, db_url=db_url)
    imd.add_partition(
        layout,
        "rootfs",
        "rootfs",
        filesystem_id=ids["ext4"],
        size_mb=rootfs_size,
        grow=True,
        db_url=db_url,
    )
    return imd.create_recipe(
        "edge-sd",
        output_format="raw",
        partition_layout_id=layout,
        size_policy_id=ids["policy"],
        root_filesystem_id=ids["ext4"],
        db_url=db_url,
    )["id"]


# --- catalog ----------------------------------------------------------------


def test_unknown_filesystem_rejected(db_url: str) -> None:
    with pytest.raises(ValueError, match="unknown filesystem"):
        imd.create_filesystem_profile("weird", "zfs", db_url=db_url)


def test_duplicate_filesystem_rejected(db_url: str) -> None:
    imd.create_filesystem_profile("ext4-a", "ext4", db_url=db_url)
    with pytest.raises(ValueError, match="already exists"):
        imd.create_filesystem_profile("ext4-a", "ext4", db_url=db_url)


def test_size_policy_align_must_be_positive(db_url: str) -> None:
    with pytest.raises(ValueError, match="align_mb"):
        imd.create_size_policy("bad", align_mb=0, db_url=db_url)


def test_unknown_output_format_rejected(db_url: str, std: dict[str, str]) -> None:
    with pytest.raises(ValueError, match="unknown output format"):
        imd.create_recipe("x", output_format="floppy", db_url=db_url)


# --- estimator: sizing math -------------------------------------------------


def test_estimate_fixed_plus_grow_no_disk(db_url: str, std: dict[str, str]) -> None:
    recipe = _sd_recipe(db_url, std)
    est = imd.estimate_recipe(recipe, db_url=db_url)
    assert est["valid"] is True
    sizes = {p["name"]: p["size_mb"] for p in est["partitions"]}
    assert sizes == {"boot": 64, "rootfs": 200}  # free_pct=0 → grow base unchanged
    # total = 2*reserve + 64 + 200
    assert est["total_image_mb"] == 2 + 64 + 200


def test_estimate_free_space_pct_inflates_grow(db_url: str) -> None:
    ext4 = imd.create_filesystem_profile("e", "ext4", db_url=db_url)["id"]
    vfat = imd.create_filesystem_profile("b", "vfat", db_url=db_url)["id"]
    policy = imd.create_size_policy(
        "grow20", align_mb=4, reserve_mb=1, free_space_pct=20, min_free_mb=8, db_url=db_url
    )["id"]
    layout = imd.create_partition_layout("l", db_url=db_url)["id"]
    imd.add_partition(layout, "boot", "boot", filesystem_id=vfat, size_mb=64, db_url=db_url)
    imd.add_partition(
        layout, "rootfs", "rootfs", filesystem_id=ext4, size_mb=100, grow=True, db_url=db_url
    )
    recipe = imd.create_recipe(
        "r", partition_layout_id=layout, size_policy_id=policy, db_url=db_url
    )["id"]
    est = imd.estimate_recipe(recipe, db_url=db_url)
    # inflated = 100 + 100*20//100 + 8 = 128, aligned to 4 → 128
    sizes = {p["name"]: p["size_mb"] for p in est["partitions"]}
    assert sizes["rootfs"] == 128


def test_estimate_with_total_disk_grow_absorbs_remainder(db_url: str, std: dict[str, str]) -> None:
    recipe = _sd_recipe(db_url, std)
    est = imd.estimate_recipe(recipe, total_disk_mb=500, db_url=db_url)
    # usable = 500 - 64 - 2*1 = 434 → aligned up to 436
    sizes = {p["name"]: p["size_mb"] for p in est["partitions"]}
    assert sizes["rootfs"] == 436
    assert est["valid"] is True


def test_estimate_fixed_exceeds_disk_errors(db_url: str, std: dict[str, str]) -> None:
    recipe = _sd_recipe(db_url, std)
    est = imd.estimate_recipe(recipe, total_disk_mb=10, db_url=db_url)
    assert est["valid"] is False
    assert any("exceed total disk" in e for e in est["errors"])


def test_estimate_alignment_rounds_up(db_url: str) -> None:
    vfat = imd.create_filesystem_profile("b", "vfat", db_url=db_url)["id"]
    ext4 = imd.create_filesystem_profile("e", "ext4", db_url=db_url)["id"]
    policy = imd.create_size_policy("a16", align_mb=16, reserve_mb=1, db_url=db_url)["id"]
    layout = imd.create_partition_layout("l", db_url=db_url)["id"]
    imd.add_partition(layout, "boot", "boot", filesystem_id=vfat, size_mb=10, db_url=db_url)
    imd.add_partition(layout, "rootfs", "rootfs", filesystem_id=ext4, size_mb=100, db_url=db_url)
    recipe = imd.create_recipe(
        "r", partition_layout_id=layout, size_policy_id=policy, db_url=db_url
    )["id"]
    est = imd.estimate_recipe(recipe, db_url=db_url)
    sizes = {p["name"]: p["size_mb"] for p in est["partitions"]}
    assert sizes == {"boot": 16, "rootfs": 112}  # 10→16, 100→112 (multiples of 16)


def test_estimate_is_deterministic(db_url: str, std: dict[str, str]) -> None:
    recipe = _sd_recipe(db_url, std)
    a = imd.estimate_recipe(recipe, db_url=db_url)
    b = imd.estimate_recipe(recipe, db_url=db_url)
    assert a["plan_hash"] == b["plan_hash"]
    assert a["plan_hash"].startswith("sha256:")


# --- estimator: validation --------------------------------------------------


def test_estimate_requires_layout(db_url: str) -> None:
    recipe = imd.create_recipe("no-layout", db_url=db_url)["id"]
    with pytest.raises(ValueError, match="no partition layout"):
        imd.estimate_recipe(recipe, db_url=db_url)


def test_estimate_no_root_partition_errors(db_url: str, std: dict[str, str]) -> None:
    layout = imd.create_partition_layout("bootonly", db_url=db_url)["id"]
    imd.add_partition(layout, "boot", "boot", filesystem_id=std["vfat"], size_mb=64, db_url=db_url)
    recipe = imd.create_recipe("r", partition_layout_id=layout, db_url=db_url)["id"]
    est = imd.estimate_recipe(recipe, db_url=db_url)
    assert est["valid"] is False
    assert any("no root partition" in e for e in est["errors"])


def test_estimate_two_roots_errors(db_url: str, std: dict[str, str]) -> None:
    layout = imd.create_partition_layout("tworoot", db_url=db_url)["id"]
    imd.add_partition(layout, "r1", "rootfs", filesystem_id=std["ext4"], size_mb=100, db_url=db_url)
    imd.add_partition(layout, "r2", "rootfs", filesystem_id=std["ext4"], size_mb=100, db_url=db_url)
    recipe = imd.create_recipe("r", partition_layout_id=layout, db_url=db_url)["id"]
    est = imd.estimate_recipe(recipe, db_url=db_url)
    assert est["valid"] is False
    assert any("root partitions" in e for e in est["errors"])


def test_estimate_ab_pair_equal_is_valid(db_url: str, std: dict[str, str]) -> None:
    layout = imd.create_partition_layout("ab", db_url=db_url)["id"]
    imd.add_partition(layout, "boot", "boot", filesystem_id=std["vfat"], size_mb=64, db_url=db_url)
    imd.add_partition(
        layout, "slot_a", "ab_a", filesystem_id=std["ext4"], size_mb=200, db_url=db_url
    )
    imd.add_partition(
        layout, "slot_b", "ab_b", filesystem_id=std["ext4"], size_mb=200, db_url=db_url
    )
    recipe = imd.create_recipe(
        "ab", partition_layout_id=layout, size_policy_id=std["policy"], db_url=db_url
    )["id"]
    est = imd.estimate_recipe(recipe, db_url=db_url)
    assert est["valid"] is True


def test_estimate_ab_unequal_errors(db_url: str, std: dict[str, str]) -> None:
    layout = imd.create_partition_layout("ab", db_url=db_url)["id"]
    imd.add_partition(
        layout, "slot_a", "ab_a", filesystem_id=std["ext4"], size_mb=200, db_url=db_url
    )
    imd.add_partition(
        layout, "slot_b", "ab_b", filesystem_id=std["ext4"], size_mb=100, db_url=db_url
    )
    recipe = imd.create_recipe("ab", partition_layout_id=layout, db_url=db_url)["id"]
    est = imd.estimate_recipe(recipe, db_url=db_url)
    assert est["valid"] is False
    assert any("equal size" in e for e in est["errors"])


def test_estimate_ab_single_slot_errors(db_url: str, std: dict[str, str]) -> None:
    layout = imd.create_partition_layout("ab", db_url=db_url)["id"]
    imd.add_partition(
        layout, "slot_a", "ab_a", filesystem_id=std["ext4"], size_mb=200, db_url=db_url
    )
    recipe = imd.create_recipe("ab", partition_layout_id=layout, db_url=db_url)["id"]
    est = imd.estimate_recipe(recipe, db_url=db_url)
    assert est["valid"] is False
    assert any("both ab_a and ab_b" in e for e in est["errors"])


# --- resolve + multi-output -------------------------------------------------


def test_resolve_and_multi_output(db_url: str, std: dict[str, str]) -> None:
    recipe = _sd_recipe(db_url, std)
    imd.add_output(recipe, "qcow2", db_url=db_url)
    imd.add_output(recipe, "tarball", db_url=db_url)
    imd.add_mount(recipe, "tmpfs", "/tmp", "tmpfs", options="size=64M", db_url=db_url)

    resolved = imd.resolve_recipe(recipe, db_url=db_url)
    assert set(resolved["outputs"]) == {"raw", "qcow2", "tarball"}
    assert {p["role"] for p in resolved["partitions"]} == {"boot", "rootfs"}
    assert resolved["mounts"][0]["target"] == "/tmp"

    est = imd.estimate_recipe(recipe, db_url=db_url)
    assert set(est["outputs"]) == {"raw", "qcow2", "tarball"}


# --- HTTP API (thin wrapper, auth disabled) ---------------------------------


@pytest.fixture
def client(db_url: str) -> TestClient:
    settings = Settings()
    settings.database.url = db_url
    settings.auth.enabled = False
    return TestClient(create_app(settings))


def test_api_recipe_estimate_flow(client: TestClient, db_url: str, std: dict[str, str]) -> None:
    layout = client.post("/v1/partition-layouts", json={"name": "sd"}).json()
    layout_id = layout["id"]
    client.post(
        f"/v1/partition-layouts/{layout_id}/partitions",
        json={"name": "boot", "role": "boot", "filesystem_id": std["vfat"], "size_mb": 64},
    )
    client.post(
        f"/v1/partition-layouts/{layout_id}/partitions",
        json={
            "name": "rootfs",
            "role": "rootfs",
            "filesystem_id": std["ext4"],
            "size_mb": 200,
            "grow": True,
        },
    )
    recipe = client.post(
        "/v1/image-recipes",
        json={
            "name": "edge",
            "output_format": "raw",
            "partition_layout_id": layout_id,
            "size_policy_id": std["policy"],
        },
    ).json()
    est = client.post(f"/v1/image-recipes/{recipe['id']}/estimate", json={}).json()
    assert est["valid"] is True
    assert {p["name"] for p in est["partitions"]} == {"boot", "rootfs"}
    assert est["total_image_mb"] == 2 + 64 + 200
