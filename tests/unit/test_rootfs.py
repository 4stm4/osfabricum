"""Tests for M15: Base RootFS Builder."""

from __future__ import annotations

import io
import tarfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

from apps.cli.main import app
from osfabricum.db.engine import make_sync_engine
from osfabricum.db.models import Artifact, Base
from osfabricum.db.session import sync_session
from osfabricum.rootfs.builder import (
    RootfsSpec,
    build_base_rootfs,
    create_rootfs_tree,
    pack_rootfs_deterministic,
    write_etc_files,
)
from osfabricum.rootfs.etcfiles import (
    make_fstab,
    make_group,
    make_hostname,
    make_hosts,
    make_os_release,
    make_passwd,
    make_profile,
    make_shells,
)
from osfabricum.rootfs.initsystem import setup_busybox_init, setup_init_system, setup_systemd_init
from osfabricum.rootfs.layout import BASE_DIRS, DIR_MODES

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
def spec() -> RootfsSpec:
    return RootfsSpec(
        arch="aarch64",
        distribution="tinywifi",
        profile="default",
        board="rpi-zero-2w",
        init_system="busybox",
        hostname="testhost",
    )


# ---------------------------------------------------------------------------
# layout
# ---------------------------------------------------------------------------


def test_base_dirs_contains_required_paths() -> None:
    for required in ["etc", "proc", "sys", "dev", "tmp", "bin", "usr/bin"]:
        assert required in BASE_DIRS, f"{required!r} missing from BASE_DIRS"


def test_dir_modes_tmp_is_sticky() -> None:
    assert DIR_MODES.get("tmp") == 0o1777
    assert DIR_MODES.get("var/tmp") == 0o1777


# ---------------------------------------------------------------------------
# etcfiles
# ---------------------------------------------------------------------------


def test_make_passwd_contains_root() -> None:
    data = make_passwd().decode()
    assert data.startswith("root:x:0:0:")


def test_make_passwd_contains_nobody() -> None:
    data = make_passwd().decode()
    assert "nobody" in data


def test_make_group_contains_root() -> None:
    assert b"root:x:0:" in make_group()


def test_make_hostname_ends_with_newline() -> None:
    assert make_hostname("myhost") == b"myhost\n"


def test_make_hosts_contains_hostname() -> None:
    data = make_hosts("myhost").decode()
    assert "myhost" in data
    assert "127.0.0.1" in data


def test_make_fstab_contains_proc() -> None:
    data = make_fstab().decode()
    assert "proc" in data


def test_make_profile_exports_path() -> None:
    data = make_profile().decode()
    assert "export PATH=" in data


def test_make_shells_contains_sh() -> None:
    assert b"/bin/sh\n" in make_shells()


def test_make_os_release_contains_distro() -> None:
    data = make_os_release("tinywifi").decode()
    assert "TINYWIFI" in data
    assert "ID=tinywifi" in data


def test_make_passwd_extra_user() -> None:
    data = make_passwd([{"name": "alice", "uid": 1000, "gid": 1000}]).decode()
    assert "alice:x:1000:1000:" in data


# ---------------------------------------------------------------------------
# initsystem — busybox
# ---------------------------------------------------------------------------


def test_setup_busybox_init_creates_inittab(tmp_path: Path) -> None:
    for d in ["etc/init.d"]:
        (tmp_path / d).mkdir(parents=True)
    written = setup_busybox_init(tmp_path)
    assert "etc/inittab" in written
    assert (tmp_path / "etc" / "inittab").exists()


def test_setup_busybox_init_rcs_is_executable(tmp_path: Path) -> None:
    for d in ["etc/init.d"]:
        (tmp_path / d).mkdir(parents=True)
    setup_busybox_init(tmp_path)
    rcs = tmp_path / "etc" / "init.d" / "rcS"
    assert rcs.stat().st_mode & 0o100  # user-executable


def test_setup_busybox_inittab_contains_sysinit(tmp_path: Path) -> None:
    (tmp_path / "etc" / "init.d").mkdir(parents=True)
    setup_busybox_init(tmp_path)
    content = (tmp_path / "etc" / "inittab").read_text()
    assert "sysinit" in content


def test_setup_busybox_rcs_contains_mount(tmp_path: Path) -> None:
    (tmp_path / "etc" / "init.d").mkdir(parents=True)
    setup_busybox_init(tmp_path)
    content = (tmp_path / "etc" / "init.d" / "rcS").read_text()
    assert "mount" in content


# ---------------------------------------------------------------------------
# initsystem — systemd
# ---------------------------------------------------------------------------


def test_setup_systemd_creates_multi_user_target(tmp_path: Path) -> None:
    written = setup_systemd_init(tmp_path)
    assert any("multi-user.target" in w for w in written)
    target = tmp_path / "usr" / "lib" / "systemd" / "system" / "multi-user.target"
    assert target.exists()


def test_setup_systemd_creates_default_symlink(tmp_path: Path) -> None:
    setup_systemd_init(tmp_path)
    default = tmp_path / "usr" / "lib" / "systemd" / "system" / "default.target"
    assert default.is_symlink()
    assert "multi-user" in str(default.readlink())


def test_setup_init_system_unknown_raises() -> None:
    with pytest.raises(ValueError, match="unknown init_system"):
        setup_init_system(Path("/tmp"), "unknown-init")


# ---------------------------------------------------------------------------
# create_rootfs_tree
# ---------------------------------------------------------------------------


def test_create_rootfs_tree_creates_all_base_dirs(tmp_path: Path, spec: RootfsSpec) -> None:
    created = create_rootfs_tree(tmp_path, spec)
    for d in BASE_DIRS:
        assert (tmp_path / d).is_dir(), f"missing: {d}"
    assert len(created) >= len(BASE_DIRS)


def test_create_rootfs_tree_tmp_is_sticky(tmp_path: Path, spec: RootfsSpec) -> None:
    create_rootfs_tree(tmp_path, spec)
    import stat

    mode = (tmp_path / "tmp").stat().st_mode
    assert mode & stat.S_ISVTX, "/tmp should have sticky bit"


def test_create_rootfs_tree_extra_dirs(tmp_path: Path, spec: RootfsSpec) -> None:
    spec.extra_dirs = ["usr/local/custom"]
    create_rootfs_tree(tmp_path, spec)
    assert (tmp_path / "usr" / "local" / "custom").is_dir()


# ---------------------------------------------------------------------------
# write_etc_files
# ---------------------------------------------------------------------------


def test_write_etc_files_creates_passwd(tmp_path: Path, spec: RootfsSpec) -> None:
    create_rootfs_tree(tmp_path, spec)
    write_etc_files(tmp_path, spec)
    assert (tmp_path / "etc" / "passwd").exists()


def test_write_etc_files_hostname_matches_spec(tmp_path: Path, spec: RootfsSpec) -> None:
    create_rootfs_tree(tmp_path, spec)
    write_etc_files(tmp_path, spec)
    hostname = (tmp_path / "etc" / "hostname").read_text().strip()
    assert hostname == spec.hostname


def test_write_etc_files_os_release_has_distro(tmp_path: Path, spec: RootfsSpec) -> None:
    create_rootfs_tree(tmp_path, spec)
    write_etc_files(tmp_path, spec)
    content = (tmp_path / "etc" / "os-release").read_text()
    assert spec.distribution.upper() in content


def test_write_etc_files_shadow_permissions(tmp_path: Path, spec: RootfsSpec) -> None:
    create_rootfs_tree(tmp_path, spec)
    write_etc_files(tmp_path, spec)
    shadow = tmp_path / "etc" / "shadow"
    assert shadow.stat().st_mode & 0o777 == 0o640


def test_write_etc_files_extra_etc(tmp_path: Path, spec: RootfsSpec) -> None:
    spec.extra_etc = {"etc/custom.conf": b"key=value\n"}
    create_rootfs_tree(tmp_path, spec)
    write_etc_files(tmp_path, spec)
    assert (tmp_path / "etc" / "custom.conf").read_bytes() == b"key=value\n"


# ---------------------------------------------------------------------------
# pack_rootfs_deterministic
# ---------------------------------------------------------------------------


def test_pack_rootfs_is_valid_tar(tmp_path: Path, spec: RootfsSpec) -> None:
    create_rootfs_tree(tmp_path, spec)
    write_etc_files(tmp_path, spec)
    archive = pack_rootfs_deterministic(tmp_path)
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
        names = tar.getnames()
    assert len(names) > 0


def test_pack_rootfs_contains_etc_passwd(tmp_path: Path, spec: RootfsSpec) -> None:
    create_rootfs_tree(tmp_path, spec)
    write_etc_files(tmp_path, spec)
    archive = pack_rootfs_deterministic(tmp_path)
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
        names = tar.getnames()
    assert "etc/passwd" in names


def test_pack_rootfs_all_mtimes_zero(tmp_path: Path, spec: RootfsSpec) -> None:
    """All tar entries must have mtime=0 for reproducibility."""
    create_rootfs_tree(tmp_path, spec)
    write_etc_files(tmp_path, spec)
    archive = pack_rootfs_deterministic(tmp_path)
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
        for member in tar.getmembers():
            assert member.mtime == 0, f"{member.name} has mtime={member.mtime}"


def test_pack_rootfs_all_uids_zero(tmp_path: Path, spec: RootfsSpec) -> None:
    """All tar entries must have uid=0 for reproducibility."""
    create_rootfs_tree(tmp_path, spec)
    write_etc_files(tmp_path, spec)
    archive = pack_rootfs_deterministic(tmp_path)
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
        for member in tar.getmembers():
            assert member.uid == 0, f"{member.name} has uid={member.uid}"


def test_pack_rootfs_deterministic_same_output(tmp_path: Path, spec: RootfsSpec) -> None:
    """Same inputs → byte-identical output."""
    create_rootfs_tree(tmp_path, spec)
    write_etc_files(tmp_path, spec)
    archive1 = pack_rootfs_deterministic(tmp_path)
    archive2 = pack_rootfs_deterministic(tmp_path)
    assert archive1 == archive2


# ---------------------------------------------------------------------------
# build_base_rootfs — integration
# ---------------------------------------------------------------------------


def test_build_base_rootfs_success(
    tmp_path: Path, db_url: str, store_root: Path, spec: RootfsSpec
) -> None:
    result = build_base_rootfs(spec, store_root=store_root, db_url=db_url)
    assert result.success is True
    assert result.artifact_id is not None
    assert result.error is None


def test_build_base_rootfs_artifact_kind(
    tmp_path: Path, db_url: str, store_root: Path, spec: RootfsSpec
) -> None:
    result = build_base_rootfs(spec, store_root=store_root, db_url=db_url)
    from sqlalchemy import select

    with sync_session(db_url) as session:
        art = session.scalar(select(Artifact).where(Artifact.id == result.artifact_id))
    assert art is not None
    assert art.kind == "rootfs-base"
    assert art.arch == "aarch64"


def test_build_base_rootfs_has_input_hash(
    tmp_path: Path, db_url: str, store_root: Path, spec: RootfsSpec
) -> None:
    result = build_base_rootfs(spec, store_root=store_root, db_url=db_url)
    from sqlalchemy import select

    with sync_session(db_url) as session:
        art = session.scalar(select(Artifact).where(Artifact.id == result.artifact_id))
    assert art.input_hash is not None
    assert len(art.input_hash) == 64


def test_build_base_rootfs_has_repro_record(
    tmp_path: Path, db_url: str, store_root: Path, spec: RootfsSpec
) -> None:
    result = build_base_rootfs(spec, store_root=store_root, db_url=db_url)
    from sqlalchemy import select

    with sync_session(db_url) as session:
        art = session.scalar(select(Artifact).where(Artifact.id == result.artifact_id))
    assert art.metadata_json is not None
    assert "repro" in art.metadata_json
    assert art.metadata_json["repro"]["step_kind"] == "rootfs.base"


def test_build_base_rootfs_idempotent(
    tmp_path: Path, db_url: str, store_root: Path, spec: RootfsSpec
) -> None:
    """Second call with same spec returns same artifact (cached by store_key)."""
    r1 = build_base_rootfs(spec, store_root=store_root, db_url=db_url)
    r2 = build_base_rootfs(spec, store_root=store_root, db_url=db_url)
    assert r1.artifact_id == r2.artifact_id


def test_build_base_rootfs_busybox_has_inittab(
    tmp_path: Path, db_url: str, store_root: Path, spec: RootfsSpec
) -> None:
    result = build_base_rootfs(spec, store_root=store_root, db_url=db_url)
    from sqlalchemy import select

    with sync_session(db_url) as session:
        art = session.scalar(select(Artifact).where(Artifact.id == result.artifact_id))
    from osfabricum.store.layout import blob_path

    bp = blob_path(store_root, art.blob_sha256)
    with tarfile.open(str(bp), mode="r:gz") as tar:
        names = tar.getnames()
    assert "etc/inittab" in names


def test_build_base_rootfs_systemd(tmp_path: Path, db_url: str, store_root: Path) -> None:
    spec = RootfsSpec(
        arch="x86_64",
        distribution="tinywifi",
        profile="default",
        board="qemu-x86_64",
        init_system="systemd",
    )
    result = build_base_rootfs(spec, store_root=store_root, db_url=db_url)
    assert result.success is True

    from sqlalchemy import select

    with sync_session(db_url) as session:
        art = session.scalar(select(Artifact).where(Artifact.id == result.artifact_id))
    from osfabricum.store.layout import blob_path

    bp = blob_path(store_root, art.blob_sha256)
    with tarfile.open(str(bp), mode="r:gz") as tar:
        names = tar.getnames()
    assert any("multi-user.target" in n for n in names)


def test_build_base_rootfs_logs(
    tmp_path: Path, db_url: str, store_root: Path, spec: RootfsSpec
) -> None:
    result = build_base_rootfs(spec, store_root=store_root, db_url=db_url)
    assert len(result.logs) > 0
    assert any("rootfs" in line for line in result.logs)


# ---------------------------------------------------------------------------
# CLI rootfs init
# ---------------------------------------------------------------------------


def test_cli_rootfs_init(tmp_path: Path, db_url: str, store_root: Path) -> None:
    result = runner.invoke(
        app,
        [
            "rootfs",
            "init",
            "tinywifi/default",
            "--board",
            "rpi-zero-2w",
            "--arch",
            "aarch64",
            "--store-root",
            str(store_root),
            "--db-url",
            db_url,
        ],
    )
    assert result.exit_code == 0, result.output
    assert "artifact" in result.output


def test_cli_rootfs_init_bad_target(tmp_path: Path, db_url: str, store_root: Path) -> None:
    result = runner.invoke(
        app,
        [
            "rootfs",
            "init",
            "no-slash",
            "--board",
            "rpi-zero-2w",
            "--arch",
            "aarch64",
            "--store-root",
            str(store_root),
            "--db-url",
            db_url,
        ],
    )
    assert result.exit_code != 0
