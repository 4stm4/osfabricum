"""Unit tests for M44 — Users / Groups / Credentials / Secrets Designer."""

from __future__ import annotations

import json

import pytest

from osfabricum import users as us
from osfabricum.db.models import Base
from osfabricum.db.seed_data import seed_user_shell_kinds

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_url(tmp_path):
    url = f"sqlite:///{tmp_path}/test_users.db"
    from sqlalchemy import create_engine  # noqa: PLC0415

    engine = create_engine(url)
    Base.metadata.create_all(engine)

    from sqlalchemy.orm import Session  # noqa: PLC0415

    with Session(engine) as s:
        seed_user_shell_kinds(s)
        s.commit()

    engine.dispose()
    return url


@pytest.fixture()
def profile(db_url):
    return us.create_user_profile("Base", db_url=db_url)


@pytest.fixture()
def profile2(db_url):
    return us.create_user_profile("Server", db_url=db_url)


# ---------------------------------------------------------------------------
# Shell kinds
# ---------------------------------------------------------------------------


def test_list_shell_kinds_seeded(db_url):
    kinds = us.list_user_shell_kinds(db_url=db_url)
    assert len(kinds) == 7
    paths = {k["path"] for k in kinds}
    assert "/bin/bash" in paths
    assert "/usr/sbin/nologin" in paths
    assert "/bin/false" in paths
    assert "/bin/zsh" in paths
    assert "/bin/fish" in paths
    assert "/bin/sh" in paths
    assert "/bin/dash" in paths


def test_shell_kinds_ordered(db_url):
    kinds = us.list_user_shell_kinds(db_url=db_url)
    orders = [k["display_order"] for k in kinds]
    assert orders == sorted(orders)


# ---------------------------------------------------------------------------
# Profile CRUD
# ---------------------------------------------------------------------------


def test_create_profile(db_url, profile):
    assert profile["id"]
    assert profile["name"] == "Base"
    assert profile["distribution_id"] is None
    assert profile["content_hash"] is None


def test_create_profile_with_distribution(db_url):
    p = us.create_user_profile("Dist Users", distribution_id="dist-123", db_url=db_url)
    assert p["distribution_id"] == "dist-123"


def test_create_duplicate_raises(db_url, profile):
    with pytest.raises(ValueError, match="already exists"):
        us.create_user_profile("Base", db_url=db_url)


def test_create_same_name_different_dist(db_url, profile):
    p = us.create_user_profile("Base", distribution_id="other-dist", db_url=db_url)
    assert p["id"] != profile["id"]


def test_list_profiles(db_url, profile, profile2):
    profiles = us.list_user_profiles(db_url=db_url)
    names = {p["name"] for p in profiles}
    assert "Base" in names
    assert "Server" in names


def test_list_profiles_by_distribution(db_url):
    us.create_user_profile("P1", distribution_id="d1", db_url=db_url)
    us.create_user_profile("P2", distribution_id="d2", db_url=db_url)
    result = us.list_user_profiles("d1", db_url=db_url)
    assert len(result) == 1
    assert result[0]["name"] == "P1"


def test_get_profile_not_found(db_url):
    with pytest.raises(ValueError, match="not found"):
        us.get_user_profile("no-such", db_url=db_url)


def test_update_profile_name(db_url, profile):
    updated = us.update_user_profile(profile["id"], name="Renamed", db_url=db_url)
    assert updated["name"] == "Renamed"


def test_update_clears_cache(db_url, profile):
    # seed something and render
    us.add_os_group(profile["id"], "users", gid=100, db_url=db_url)
    us.render_user_config(profile["id"], db_url=db_url)
    updated = us.update_user_profile(profile["id"], name="New Name", db_url=db_url)
    assert updated["content_hash"] is None
    assert updated["rendered_passwd"] is None
    assert updated["rendered_group"] is None


def test_update_nonexistent_raises(db_url):
    with pytest.raises(ValueError, match="not found"):
        us.update_user_profile("bad-id", name="X", db_url=db_url)


# ---------------------------------------------------------------------------
# Groups
# ---------------------------------------------------------------------------


def test_add_group_defaults(db_url, profile):
    g = us.add_os_group(profile["id"], "users", db_url=db_url)
    assert g["name"] == "users"
    assert g["gid"] is None
    assert g["is_system"] is False
    assert g["description"] == ""


def test_add_group_with_gid(db_url, profile):
    g = us.add_os_group(profile["id"], "sudo", gid=27, db_url=db_url)
    assert g["gid"] == 27


def test_add_system_group(db_url, profile):
    g = us.add_os_group(profile["id"], "daemon", gid=1, is_system=True, db_url=db_url)
    assert g["is_system"] is True


def test_add_group_with_description(db_url, profile):
    g = us.add_os_group(
        profile["id"], "docker", description="Docker engine group", db_url=db_url
    )
    assert g["description"] == "Docker engine group"


def test_add_duplicate_group_raises(db_url, profile):
    us.add_os_group(profile["id"], "users", db_url=db_url)
    with pytest.raises(ValueError, match="already exists"):
        us.add_os_group(profile["id"], "users", db_url=db_url)


def test_add_group_nonexistent_profile(db_url):
    with pytest.raises(ValueError, match="not found"):
        us.add_os_group("bad-id", "users", db_url=db_url)


def test_get_profile_includes_groups(db_url, profile):
    us.add_os_group(profile["id"], "users", gid=100, db_url=db_url)
    us.add_os_group(profile["id"], "sudo", gid=27, db_url=db_url)
    detail = us.get_user_profile(profile["id"], db_url=db_url)
    names = {g["name"] for g in detail["groups"]}
    assert "users" in names
    assert "sudo" in names


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


def test_add_user_defaults(db_url, profile):
    u = us.add_os_user(profile["id"], "alice", db_url=db_url)
    assert u["username"] == "alice"
    assert u["uid"] is None
    assert u["primary_group"] == "users"
    assert u["home_dir"] == "/home/alice"
    assert u["shell"] == "/bin/bash"
    assert u["gecos"] == ""
    assert u["is_system"] is False
    assert u["is_locked"] is False


def test_add_user_custom(db_url, profile):
    u = us.add_os_user(
        profile["id"],
        "www-data",
        uid=33,
        primary_group="www-data",
        home_dir="/var/www",
        shell="/usr/sbin/nologin",
        gecos="www-data",
        is_system=True,
        is_locked=True,
        db_url=db_url,
    )
    assert u["uid"] == 33
    assert u["primary_group"] == "www-data"
    assert u["home_dir"] == "/var/www"
    assert u["shell"] == "/usr/sbin/nologin"
    assert u["is_system"] is True
    assert u["is_locked"] is True


def test_add_user_auto_home(db_url, profile):
    u = us.add_os_user(profile["id"], "bob", db_url=db_url)
    assert u["home_dir"] == "/home/bob"


def test_add_duplicate_user_raises(db_url, profile):
    us.add_os_user(profile["id"], "alice", db_url=db_url)
    with pytest.raises(ValueError, match="already exists"):
        us.add_os_user(profile["id"], "alice", db_url=db_url)


def test_add_user_nonexistent_profile(db_url):
    with pytest.raises(ValueError, match="not found"):
        us.add_os_user("bad-id", "alice", db_url=db_url)


def test_get_profile_includes_users(db_url, profile):
    us.add_os_user(profile["id"], "alice", uid=1001, db_url=db_url)
    us.add_os_user(profile["id"], "bob", uid=1002, db_url=db_url)
    detail = us.get_user_profile(profile["id"], db_url=db_url)
    names = {u["username"] for u in detail["users"]}
    assert "alice" in names
    assert "bob" in names


# ---------------------------------------------------------------------------
# Supplementary groups
# ---------------------------------------------------------------------------


def test_add_supplementary_group(db_url, profile):
    u = us.add_os_user(profile["id"], "alice", db_url=db_url)
    sg = us.add_supplementary_group(u["id"], "sudo", db_url=db_url)
    assert sg["user_id"] == u["id"]
    assert sg["group_name"] == "sudo"


def test_add_multiple_supplementary_groups(db_url, profile):
    u = us.add_os_user(profile["id"], "alice", db_url=db_url)
    us.add_supplementary_group(u["id"], "sudo", db_url=db_url)
    us.add_supplementary_group(u["id"], "docker", db_url=db_url)
    us.add_supplementary_group(u["id"], "plugdev", db_url=db_url)
    detail = us.get_user_profile(profile["id"], db_url=db_url)
    alice = next(x for x in detail["users"] if x["username"] == "alice")
    assert set(alice["supplementary_groups"]) == {"sudo", "docker", "plugdev"}


def test_add_duplicate_supplementary_raises(db_url, profile):
    u = us.add_os_user(profile["id"], "alice", db_url=db_url)
    us.add_supplementary_group(u["id"], "sudo", db_url=db_url)
    with pytest.raises(ValueError, match="already"):
        us.add_supplementary_group(u["id"], "sudo", db_url=db_url)


def test_add_supplementary_nonexistent_user(db_url):
    with pytest.raises(ValueError, match="not found"):
        us.add_supplementary_group("bad-id", "sudo", db_url=db_url)


# ---------------------------------------------------------------------------
# Secrets
# ---------------------------------------------------------------------------


def test_add_secret_env_var(db_url, profile):
    sv = us.add_secret_variable(
        profile["id"], "ROOT_PASSWORD", "env-var", db_url=db_url
    )
    assert sv["name"] == "ROOT_PASSWORD"
    assert sv["kind"] == "env-var"
    assert sv["is_required"] is True
    assert sv["masked_value"] is None


def test_add_secret_ssh_key(db_url, profile):
    sv = us.add_secret_variable(
        profile["id"],
        "SSH_HOST_KEY",
        "ssh-key",
        description="Host ED25519 key",
        masked_value="***",
        db_url=db_url,
    )
    assert sv["kind"] == "ssh-key"
    assert sv["description"] == "Host ED25519 key"
    assert sv["masked_value"] == "***"


def test_add_secret_optional(db_url, profile):
    sv = us.add_secret_variable(
        profile["id"], "OPTIONAL_TOKEN", "api-key", is_required=False, db_url=db_url
    )
    assert sv["is_required"] is False


def test_add_all_secret_kinds(db_url, profile):
    for kind in us.VALID_SECRET_KINDS:
        us.add_secret_variable(profile["id"], f"SECRET_{kind}", kind, db_url=db_url)
    detail = us.get_user_profile(profile["id"], db_url=db_url)
    assert len(detail["secrets"]) == len(us.VALID_SECRET_KINDS)


def test_add_secret_invalid_kind(db_url, profile):
    with pytest.raises(ValueError, match="unknown secret kind"):
        us.add_secret_variable(profile["id"], "X", "bad-kind", db_url=db_url)


def test_add_duplicate_secret_raises(db_url, profile):
    us.add_secret_variable(profile["id"], "MY_SECRET", "env-var", db_url=db_url)
    with pytest.raises(ValueError, match="already exists"):
        us.add_secret_variable(profile["id"], "MY_SECRET", "file", db_url=db_url)


def test_add_secret_nonexistent_profile(db_url):
    with pytest.raises(ValueError, match="not found"):
        us.add_secret_variable("bad-id", "X", "env-var", db_url=db_url)


def test_get_profile_includes_secrets(db_url, profile):
    us.add_secret_variable(profile["id"], "A", "env-var", db_url=db_url)
    us.add_secret_variable(profile["id"], "B", "ssh-key", db_url=db_url)
    detail = us.get_user_profile(profile["id"], db_url=db_url)
    names = {s["name"] for s in detail["secrets"]}
    assert {"A", "B"} <= names


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


def _setup_profile(profile_id: str, db_url: str) -> dict:
    us.add_os_group(profile_id, "users", gid=100, db_url=db_url)
    us.add_os_group(profile_id, "sudo", gid=27, is_system=True, db_url=db_url)
    us.add_os_group(profile_id, "docker", gid=999, db_url=db_url)
    alice = us.add_os_user(
        profile_id, "alice", uid=1001, primary_group="users", db_url=db_url
    )
    us.add_os_user(
        profile_id, "root", uid=0, primary_group="root",
        home_dir="/root", shell="/bin/bash", is_system=True, db_url=db_url
    )
    us.add_supplementary_group(alice["id"], "sudo", db_url=db_url)
    us.add_supplementary_group(alice["id"], "docker", db_url=db_url)
    us.add_secret_variable(profile_id, "ROOT_PASSWORD", "env-var", db_url=db_url)
    us.add_secret_variable(
        profile_id, "SSH_HOST_KEY", "ssh-key", is_required=True, db_url=db_url
    )
    return alice


def test_render_basic(db_url, profile):
    _setup_profile(profile["id"], db_url)
    result = us.render_user_config(profile["id"], db_url=db_url)
    assert result["content_hash"].startswith("sha256:")
    assert result["user_count"] == 2
    assert result["group_count"] == 3
    assert result["secret_count"] == 2


def test_render_passwd_format(db_url, profile):
    _setup_profile(profile["id"], db_url)
    result = us.render_user_config(profile["id"], db_url=db_url)
    passwd = result["rendered_passwd"]
    assert "alice:x:1001:100::/" in passwd or "alice:x:1001:100::/home/alice:/bin/bash" in passwd
    assert "root:x:0:" in passwd


def test_render_passwd_locked_user_shell(db_url, profile):
    us.add_os_group(profile["id"], "srv", db_url=db_url)
    us.add_os_user(
        profile["id"], "daemon", uid=2, primary_group="srv",
        home_dir="/usr/sbin", shell="/bin/bash", is_locked=True, db_url=db_url
    )
    result = us.render_user_config(profile["id"], db_url=db_url)
    passwd = result["rendered_passwd"]
    assert "daemon:x:2" in passwd
    assert "/usr/sbin/nologin" in passwd


def test_render_group_format(db_url, profile):
    _setup_profile(profile["id"], db_url)
    result = us.render_user_config(profile["id"], db_url=db_url)
    group = result["rendered_group"]
    assert "sudo:x:27:" in group
    assert "docker:x:999:" in group
    # alice is a supplementary member of sudo and docker
    assert "alice" in group


def test_render_group_members(db_url, profile):
    us.add_os_group(profile["id"], "devs", gid=2000, db_url=db_url)
    alice = us.add_os_user(profile["id"], "alice", uid=1001, primary_group="users", db_url=db_url)
    bob = us.add_os_user(profile["id"], "bob", uid=1002, primary_group="users", db_url=db_url)
    us.add_supplementary_group(alice["id"], "devs", db_url=db_url)
    us.add_supplementary_group(bob["id"], "devs", db_url=db_url)
    result = us.render_user_config(profile["id"], db_url=db_url)
    group = result["rendered_group"]
    devs_line = next(ln for ln in group.splitlines() if ln.startswith("devs:"))
    members = devs_line.split(":")[3]
    assert "alice" in members
    assert "bob" in members


def test_render_secrets_manifest_json(db_url, profile):
    _setup_profile(profile["id"], db_url)
    result = us.render_user_config(profile["id"], db_url=db_url)
    manifest = json.loads(result["rendered_secrets_manifest"])
    assert isinstance(manifest, list)
    names = {s["name"] for s in manifest}
    assert "ROOT_PASSWORD" in names
    assert "SSH_HOST_KEY" in names
    for entry in manifest:
        assert "kind" in entry
        assert "is_required" in entry


def test_render_deterministic(db_url, profile):
    _setup_profile(profile["id"], db_url)
    r1 = us.render_user_config(profile["id"], db_url=db_url)
    r2 = us.render_user_config(profile["id"], db_url=db_url)
    assert r1["content_hash"] == r2["content_hash"]


def test_render_stored_on_profile(db_url, profile):
    _setup_profile(profile["id"], db_url)
    us.render_user_config(profile["id"], db_url=db_url)
    detail = us.get_user_profile(profile["id"], db_url=db_url)
    assert detail["content_hash"] is not None
    assert detail["rendered_at"] is not None
    assert "/etc/passwd" in (detail["rendered_passwd"] or "")
    assert "/etc/group" in (detail["rendered_group"] or "")


def test_render_empty_profile(db_url, profile):
    result = us.render_user_config(profile["id"], db_url=db_url)
    assert result["user_count"] == 0
    assert result["group_count"] == 0
    assert result["content_hash"].startswith("sha256:")


def test_render_nonexistent_profile(db_url):
    with pytest.raises(ValueError, match="not found"):
        us.render_user_config("bad-id", db_url=db_url)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


def test_valid_secret_kinds():
    expected = {"env-var", "file", "ssh-key", "api-key", "certificate", "gpg-key"}
    assert us.VALID_SECRET_KINDS == expected


def test_valid_shell_paths():
    assert "/bin/bash" in us.VALID_SHELL_PATHS
    assert "/usr/sbin/nologin" in us.VALID_SHELL_PATHS
    assert len(us.VALID_SHELL_PATHS) == 7
