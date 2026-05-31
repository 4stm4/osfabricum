"""Tests for M8: Build System / Recipes.

All tests use the ``custom`` driver with simple POSIX shell commands so that
no external build tool (make/cmake/cargo/…) is required.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from osfabricum.builder.drivers import DRIVERS
from osfabricum.builder.recipe import RecipeResult, compute_recipe_hash, run_recipe
from osfabricum.db.engine import make_sync_engine
from osfabricum.db.models import Base

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
def src_dir(tmp_path: Path) -> Path:
    d = tmp_path / "src"
    d.mkdir()
    return d


# ---------------------------------------------------------------------------
# compute_recipe_hash
# ---------------------------------------------------------------------------


def test_recipe_hash_is_deterministic() -> None:
    h1 = compute_recipe_hash("make", {"build": ["make"]}, {"CFLAGS": "-O2"}, "tc-1")
    h2 = compute_recipe_hash("make", {"build": ["make"]}, {"CFLAGS": "-O2"}, "tc-1")
    assert h1 == h2


def test_recipe_hash_is_64_char_hex() -> None:
    h = compute_recipe_hash("custom", None, None)
    assert len(h) == 64
    int(h, 16)  # must be valid hex — raises ValueError if not


def test_recipe_hash_changes_with_build_system() -> None:
    assert compute_recipe_hash("make", {}, {}) != compute_recipe_hash("cmake", {}, {})


def test_recipe_hash_changes_with_steps() -> None:
    h1 = compute_recipe_hash("custom", {"build": ["echo a"]}, {})
    h2 = compute_recipe_hash("custom", {"build": ["echo b"]}, {})
    assert h1 != h2


def test_recipe_hash_changes_with_env() -> None:
    h1 = compute_recipe_hash("custom", {}, {"CFLAGS": "-O2"})
    h2 = compute_recipe_hash("custom", {}, {"CFLAGS": "-O0"})
    assert h1 != h2


def test_recipe_hash_changes_with_toolchain() -> None:
    h1 = compute_recipe_hash("custom", {}, {}, "aarch64-tc")
    h2 = compute_recipe_hash("custom", {}, {}, "x86_64-tc")
    assert h1 != h2


def test_recipe_hash_none_steps_equals_empty_steps() -> None:
    assert compute_recipe_hash("custom", None, {}) == compute_recipe_hash("custom", {}, {})


# ---------------------------------------------------------------------------
# DRIVERS registry
# ---------------------------------------------------------------------------


def test_drivers_registry_has_all_expected_keys() -> None:
    expected = {"cargo", "make", "cmake", "meson", "autotools", "custom"}
    assert expected <= set(DRIVERS.keys())


def test_all_drivers_implement_four_phases() -> None:
    for cls in DRIVERS.values():
        inst = cls()
        for phase in ("prepare", "configure", "build", "install"):
            assert callable(getattr(inst, phase)), f"{cls.__name__}.{phase} not callable"


def test_make_driver_default_commands() -> None:
    from osfabricum.builder.drivers.make import MakeDriver

    d = MakeDriver()
    assert "configure" in d.default_configure_cmd
    assert "make" in d.default_build_cmd
    assert "DESTDIR" in d.default_install_cmd


def test_cmake_driver_default_commands() -> None:
    from osfabricum.builder.drivers.cmake import CMakeDriver

    d = CMakeDriver()
    assert "cmake" in d.default_configure_cmd
    assert "cmake" in d.default_build_cmd
    assert "DESTDIR" in d.default_install_cmd


def test_meson_driver_default_commands() -> None:
    from osfabricum.builder.drivers.meson import MesonDriver

    d = MesonDriver()
    assert "meson" in d.default_configure_cmd
    assert "ninja" in d.default_build_cmd
    assert "DESTDIR" in d.default_install_cmd


def test_autotools_driver_default_commands() -> None:
    from osfabricum.builder.drivers.autotools import AutotoolsDriver

    d = AutotoolsDriver()
    assert "autoreconf" in d.default_prepare_cmd
    assert "configure" in d.default_configure_cmd
    assert "DESTDIR" in d.default_install_cmd


def test_cargo_driver_default_commands() -> None:
    from osfabricum.builder.drivers.cargo import CargoDriver

    d = CargoDriver()
    assert "cargo" in d.default_build_cmd
    assert "DESTDIR" in d.default_install_cmd


# ---------------------------------------------------------------------------
# run_recipe — custom driver: basic success
# ---------------------------------------------------------------------------


def test_run_recipe_returns_recipe_result(
    src_dir: Path, store_root: Path, db_url: str
) -> None:
    result = run_recipe(
        build_system="custom",
        steps={"build": ["echo hi"]},
        src_dir=src_dir,
        store_root=store_root,
        db_url=db_url,
    )
    assert isinstance(result, RecipeResult)


def test_run_recipe_success_flag(src_dir: Path, store_root: Path, db_url: str) -> None:
    result = run_recipe(
        build_system="custom",
        steps={"build": ["echo ok"]},
        src_dir=src_dir,
        store_root=store_root,
        db_url=db_url,
    )
    assert result.success is True
    assert result.error is None
    assert result.artifact_id is not None


def test_run_recipe_logs_captured(src_dir: Path, store_root: Path, db_url: str) -> None:
    result = run_recipe(
        build_system="custom",
        steps={"build": ["echo hello-from-build"]},
        src_dir=src_dir,
        store_root=store_root,
        db_url=db_url,
    )
    assert result.success is True
    assert any("hello-from-build" in line for line in result.logs)


def test_run_recipe_recipe_hash_in_result(
    src_dir: Path, store_root: Path, db_url: str
) -> None:
    steps = {"build": ["echo hi"]}
    result = run_recipe(
        build_system="custom",
        steps=steps,
        src_dir=src_dir,
        store_root=store_root,
        db_url=db_url,
    )
    assert result.recipe_hash == compute_recipe_hash("custom", steps, None, None)


# ---------------------------------------------------------------------------
# Reproducibility guarantees
# ---------------------------------------------------------------------------


def test_source_date_epoch_always_zero(
    src_dir: Path, store_root: Path, db_url: str
) -> None:
    result = run_recipe(
        build_system="custom",
        steps={"build": ["sh -c 'echo epoch=${SOURCE_DATE_EPOCH}'"]},
        src_dir=src_dir,
        store_root=store_root,
        db_url=db_url,
    )
    assert result.success is True
    assert any("epoch=0" in line for line in result.logs)


def test_source_date_epoch_not_overridable(
    src_dir: Path, store_root: Path, db_url: str
) -> None:
    """Recipe env_extra must not override SOURCE_DATE_EPOCH."""
    result = run_recipe(
        build_system="custom",
        steps={"build": ["sh -c 'echo sde=${SOURCE_DATE_EPOCH}'"]},
        env_extra={"SOURCE_DATE_EPOCH": "9999"},
        src_dir=src_dir,
        store_root=store_root,
        db_url=db_url,
    )
    assert result.success is True
    assert any("sde=0" in line for line in result.logs)


def test_destdir_injected(src_dir: Path, store_root: Path, db_url: str) -> None:
    result = run_recipe(
        build_system="custom",
        steps={
            "install": [
                "mkdir -p ${DESTDIR}/usr/bin",
                "sh -c 'echo destdir=${DESTDIR}'",
            ]
        },
        src_dir=src_dir,
        store_root=store_root,
        db_url=db_url,
    )
    assert result.success is True
    assert any("destdir=/" in line for line in result.logs)


def test_destdir_not_overridable(src_dir: Path, store_root: Path, db_url: str) -> None:
    """Recipe env_extra must not override DESTDIR."""
    result = run_recipe(
        build_system="custom",
        steps={"install": ["sh -c 'echo dd=${DESTDIR}' && mkdir -p ${DESTDIR}"]},
        env_extra={"DESTDIR": "/absolutely-wrong"},
        src_dir=src_dir,
        store_root=store_root,
        db_url=db_url,
    )
    assert result.success is True
    # DESTDIR must be some temp path managed by run_recipe, not the injected wrong one
    assert not any("/absolutely-wrong" in line for line in result.logs)


def test_env_extra_reaches_subprocess(
    src_dir: Path, store_root: Path, db_url: str
) -> None:
    result = run_recipe(
        build_system="custom",
        steps={"build": ["sh -c 'echo MY_VAR=${MY_VAR}'"]},
        env_extra={"MY_VAR": "hello-custom-env"},
        src_dir=src_dir,
        store_root=store_root,
        db_url=db_url,
    )
    assert result.success is True
    assert any("hello-custom-env" in line for line in result.logs)


# ---------------------------------------------------------------------------
# Failure handling
# ---------------------------------------------------------------------------


def test_step_failure_sets_success_false(
    src_dir: Path, store_root: Path, db_url: str
) -> None:
    result = run_recipe(
        build_system="custom",
        steps={"build": ["false"]},
        src_dir=src_dir,
        store_root=store_root,
        db_url=db_url,
    )
    assert result.success is False
    assert result.error is not None


def test_failed_build_preserves_work_dir(
    src_dir: Path, store_root: Path, db_url: str
) -> None:
    result = run_recipe(
        build_system="custom",
        steps={"build": ["false"]},
        src_dir=src_dir,
        store_root=store_root,
        db_url=db_url,
    )
    assert result.success is False
    assert result.work_dir is not None
    assert result.work_dir.exists(), "work_dir must be preserved for inspection"


def test_successful_build_cleans_work_dir(
    src_dir: Path, store_root: Path, db_url: str
) -> None:
    result = run_recipe(
        build_system="custom",
        steps={"build": ["echo done"]},
        src_dir=src_dir,
        store_root=store_root,
        db_url=db_url,
    )
    assert result.success is True
    assert result.work_dir is None, "work_dir should be cleaned up on success"


def test_failed_build_no_artifact(
    src_dir: Path, store_root: Path, db_url: str
) -> None:
    result = run_recipe(
        build_system="custom",
        steps={"build": ["false"]},
        src_dir=src_dir,
        store_root=store_root,
        db_url=db_url,
    )
    assert result.artifact_id is None


def test_error_in_install_phase_caught(
    src_dir: Path, store_root: Path, db_url: str
) -> None:
    result = run_recipe(
        build_system="custom",
        steps={
            "build": ["echo building"],
            "install": ["false"],
        },
        src_dir=src_dir,
        store_root=store_root,
        db_url=db_url,
    )
    assert result.success is False
    # Logs from successful build phase are still captured
    assert any("building" in line for line in result.logs)


# ---------------------------------------------------------------------------
# Phase execution order
# ---------------------------------------------------------------------------


def test_phases_run_in_correct_order(
    src_dir: Path, store_root: Path, db_url: str, tmp_path: Path
) -> None:
    marker = tmp_path / "order.txt"
    result = run_recipe(
        build_system="custom",
        steps={
            "prepare": [f"echo prepare >> {marker}"],
            "configure": [f"echo configure >> {marker}"],
            "build": [f"echo build >> {marker}"],
            "install": [
                f"echo install >> {marker}",
                "mkdir -p ${DESTDIR}/usr",
            ],
        },
        src_dir=src_dir,
        store_root=store_root,
        db_url=db_url,
    )
    assert result.success is True
    lines = marker.read_text().strip().splitlines()
    assert lines == ["prepare", "configure", "build", "install"]


def test_missing_phase_is_silently_skipped(
    src_dir: Path, store_root: Path, db_url: str
) -> None:
    """A custom recipe with no configure/install steps must still succeed."""
    result = run_recipe(
        build_system="custom",
        steps={"build": ["echo build-only"]},
        src_dir=src_dir,
        store_root=store_root,
        db_url=db_url,
    )
    assert result.success is True


# ---------------------------------------------------------------------------
# Cache deduplication
# ---------------------------------------------------------------------------


def test_second_identical_recipe_is_cache_hit(
    src_dir: Path, store_root: Path, db_url: str
) -> None:
    steps = {"build": ["echo cached"]}
    kwargs = dict(
        build_system="custom",
        steps=steps,
        src_dir=src_dir,
        store_root=store_root,
        db_url=db_url,
    )
    r1 = run_recipe(**kwargs)
    assert r1.success is True
    assert r1.cache_hit is False

    r2 = run_recipe(**kwargs)
    assert r2.success is True
    assert r2.cache_hit is True
    assert r2.artifact_id == r1.artifact_id


def test_different_steps_bypass_cache(
    src_dir: Path, store_root: Path, db_url: str
) -> None:
    base = dict(src_dir=src_dir, store_root=store_root, db_url=db_url)
    r1 = run_recipe(build_system="custom", steps={"build": ["echo v1"]}, **base)
    r2 = run_recipe(build_system="custom", steps={"build": ["echo v2"]}, **base)
    assert r1.success is True
    assert r2.success is True
    assert r2.cache_hit is False
    assert r1.artifact_id != r2.artifact_id


def test_source_hash_in_cache_key(
    src_dir: Path, store_root: Path, db_url: str
) -> None:
    base = dict(
        build_system="custom",
        steps={"build": ["echo hi"]},
        src_dir=src_dir,
        store_root=store_root,
        db_url=db_url,
    )
    r1 = run_recipe(**base, source_hash="aabbcc")
    r2 = run_recipe(**base, source_hash="ddeeff")
    assert r1.success is True
    assert r2.success is True
    # Different source_hash → different artifact
    assert r1.artifact_id != r2.artifact_id


def test_unsupported_build_system_raises(
    src_dir: Path, store_root: Path, db_url: str
) -> None:
    with pytest.raises(ValueError, match="unsupported build_system"):
        run_recipe(
            build_system="NONEXISTENT",
            src_dir=src_dir,
            store_root=store_root,
            db_url=db_url,
        )
