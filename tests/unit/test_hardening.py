"""Unit tests for M47 — Security / Hardening Designer."""

from __future__ import annotations

import pytest

from osfabricum import hardening as hd
from osfabricum.db.models import Base
from osfabricum.db.seed_data import seed_security_mac_kinds

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_url(tmp_path):
    url = f"sqlite:///{tmp_path}/test_hardening.db"
    from sqlalchemy import create_engine  # noqa: PLC0415

    engine = create_engine(url)
    Base.metadata.create_all(engine)

    from sqlalchemy.orm import Session  # noqa: PLC0415

    with Session(engine) as s:
        seed_security_mac_kinds(s)
        s.commit()

    engine.dispose()
    return url


@pytest.fixture()
def profile(db_url):
    return hd.create_security_profile(
        "server-hardened", mac_policy="apparmor", db_url=db_url
    )


@pytest.fixture()
def profile2(db_url):
    return hd.create_security_profile(
        "minimal", mac_policy="none", db_url=db_url
    )


# ---------------------------------------------------------------------------
# MAC framework kinds
# ---------------------------------------------------------------------------


def test_list_mac_kinds_seeded(db_url):
    kinds = hd.list_mac_kinds(db_url=db_url)
    assert len(kinds) == 6
    names = {k["name"] for k in kinds}
    for expected in ("none", "apparmor", "selinux", "tomoyo", "smack", "landlock"):
        assert expected in names


def test_mac_kinds_ordered(db_url):
    kinds = hd.list_mac_kinds(db_url=db_url)
    orders = [k["display_order"] for k in kinds]
    assert orders == sorted(orders)


def test_mac_kinds_idempotent(db_url):
    from sqlalchemy import create_engine  # noqa: PLC0415
    from sqlalchemy.orm import Session  # noqa: PLC0415

    engine = create_engine(db_url)
    with Session(engine) as s:
        seed_security_mac_kinds(s)
        s.commit()
    engine.dispose()
    kinds = hd.list_mac_kinds(db_url=db_url)
    assert len(kinds) == 6


# ---------------------------------------------------------------------------
# Profile CRUD
# ---------------------------------------------------------------------------


def test_create_profile(profile):
    assert profile["name"] == "server-hardened"
    assert profile["mac_policy"] == "apparmor"
    assert profile["content_hash"] is None


def test_create_profile_defaults(db_url):
    p = hd.create_security_profile("baseline", db_url=db_url)
    assert p["mac_policy"] == "none"
    assert p["description"] == ""


def test_list_profiles(db_url, profile, profile2):
    all_profiles = hd.list_security_profiles(db_url=db_url)
    assert len(all_profiles) == 2
    names = {p["name"] for p in all_profiles}
    assert "server-hardened" in names
    assert "minimal" in names


def test_get_profile_full(db_url, profile):
    p = hd.get_security_profile(profile["id"], db_url=db_url)
    assert p["sysctl"] == []
    assert p["mac_rules"] == []
    assert p["pam_rules"] == []
    assert p["capabilities"] == []


def test_update_profile(db_url, profile):
    updated = hd.update_security_profile(
        profile["id"],
        name="server-hardened-v2",
        mac_policy="selinux",
        description="CIS hardened",
        db_url=db_url,
    )
    assert updated["name"] == "server-hardened-v2"
    assert updated["mac_policy"] == "selinux"
    assert updated["description"] == "CIS hardened"
    assert updated["content_hash"] is None


def test_create_duplicate_raises(db_url, profile):
    with pytest.raises(ValueError, match="already exists"):
        hd.create_security_profile("server-hardened", db_url=db_url)


def test_get_not_found(db_url):
    with pytest.raises(ValueError, match="not found"):
        hd.get_security_profile("no-such-id", db_url=db_url)


def test_create_invalid_mac_policy(db_url):
    with pytest.raises(ValueError, match="unknown MAC policy"):
        hd.create_security_profile("bad", mac_policy="grsecurity", db_url=db_url)


def test_update_invalid_mac_policy(db_url, profile):
    with pytest.raises(ValueError, match="unknown MAC policy"):
        hd.update_security_profile(
            profile["id"], mac_policy="seharden", db_url=db_url
        )


# ---------------------------------------------------------------------------
# Sysctl settings
# ---------------------------------------------------------------------------


def test_set_sysctl(db_url, profile):
    sc = hd.set_sysctl(
        profile["id"],
        "net.ipv4.ip_forward",
        "0",
        description="Disable IP forwarding",
        db_url=db_url,
    )
    assert sc["key"] == "net.ipv4.ip_forward"
    assert sc["value"] == "0"
    assert sc["description"] == "Disable IP forwarding"


def test_set_sysctl_upsert(db_url, profile):
    hd.set_sysctl(profile["id"], "kernel.randomize_va_space", "1", db_url=db_url)
    sc2 = hd.set_sysctl(
        profile["id"], "kernel.randomize_va_space", "2", db_url=db_url
    )
    assert sc2["value"] == "2"
    p = hd.get_security_profile(profile["id"], db_url=db_url)
    assert len(p["sysctl"]) == 1


def test_set_multiple_sysctl(db_url, profile):
    hd.set_sysctl(profile["id"], "net.ipv4.ip_forward", "0", db_url=db_url)
    hd.set_sysctl(profile["id"], "kernel.randomize_va_space", "2", db_url=db_url)
    hd.set_sysctl(profile["id"], "net.ipv4.conf.all.rp_filter", "1", db_url=db_url)
    p = hd.get_security_profile(profile["id"], db_url=db_url)
    assert len(p["sysctl"]) == 3


def test_sysctl_profile_not_found(db_url):
    with pytest.raises(ValueError, match="not found"):
        hd.set_sysctl("no-such", "net.ipv4.ip_forward", "0", db_url=db_url)


def test_sysctl_sorted_by_key(db_url, profile):
    hd.set_sysctl(profile["id"], "z.last", "1", db_url=db_url)
    hd.set_sysctl(profile["id"], "a.first", "1", db_url=db_url)
    p = hd.get_security_profile(profile["id"], db_url=db_url)
    keys = [sc["key"] for sc in p["sysctl"]]
    assert keys == sorted(keys)


# ---------------------------------------------------------------------------
# MAC rules
# ---------------------------------------------------------------------------


def test_add_mac_rule(db_url, profile):
    mr = hd.add_mac_rule(
        profile["id"],
        "/usr/sbin/nginx",
        "  /var/log/nginx/** w,\n  /etc/nginx/** r,\n",
        is_enforcing=True,
        priority=100,
        comment="nginx AppArmor profile",
        db_url=db_url,
    )
    assert mr["subject"] == "/usr/sbin/nginx"
    assert "nginx" in mr["rule_text"]
    assert mr["is_enforcing"] is True
    assert mr["priority"] == 100


def test_add_mac_rule_permissive(db_url, profile):
    mr = hd.add_mac_rule(
        profile["id"],
        "/usr/bin/myapp",
        "  /** r,\n",
        is_enforcing=False,
        db_url=db_url,
    )
    assert mr["is_enforcing"] is False


def test_add_multiple_mac_rules_same_subject(db_url, profile):
    hd.add_mac_rule(profile["id"], "/usr/sbin/nginx", "  /run/nginx.pid rw,\n", db_url=db_url)
    hd.add_mac_rule(profile["id"], "/usr/sbin/nginx", "  /var/www/** r,\n", db_url=db_url)
    p = hd.get_security_profile(profile["id"], db_url=db_url)
    assert len(p["mac_rules"]) == 2


def test_add_mac_rule_profile_not_found(db_url):
    with pytest.raises(ValueError, match="not found"):
        hd.add_mac_rule("no-such", "/bin/sh", "  /** r,\n", db_url=db_url)


def test_mac_rules_sorted_by_priority_then_subject(db_url, profile):
    hd.add_mac_rule(profile["id"], "/usr/sbin/sshd", "  r,\n", priority=200, db_url=db_url)
    hd.add_mac_rule(profile["id"], "/usr/sbin/nginx", "  r,\n", priority=100, db_url=db_url)
    p = hd.get_security_profile(profile["id"], db_url=db_url)
    assert p["mac_rules"][0]["subject"] == "/usr/sbin/nginx"


# ---------------------------------------------------------------------------
# PAM rules
# ---------------------------------------------------------------------------


def test_add_pam_rule(db_url, profile):
    pr = hd.add_pam_rule(
        profile["id"],
        "sshd",
        "auth",
        "required",
        "pam_unix.so",
        module_args="nullok",
        db_url=db_url,
    )
    assert pr["service"] == "sshd"
    assert pr["module_type"] == "auth"
    assert pr["control_flag"] == "required"
    assert pr["module_path"] == "pam_unix.so"
    assert pr["module_args"] == "nullok"


def test_add_pam_rule_all_types(db_url, profile):
    for mtype in ("auth", "account", "session", "password"):
        hd.add_pam_rule(
            profile["id"], "login", mtype, "required", "pam_unix.so", db_url=db_url
        )
    p = hd.get_security_profile(profile["id"], db_url=db_url)
    assert len(p["pam_rules"]) == 4


def test_add_pam_rule_all_flags(db_url, profile):
    pairs = [
        ("svc1", "required"), ("svc2", "requisite"),
        ("svc3", "sufficient"), ("svc4", "optional"),
        ("svc5", "include"), ("svc6", "substack"),
    ]
    for svc, flag in pairs:
        hd.add_pam_rule(profile["id"], svc, "auth", flag, "pam_unix.so", db_url=db_url)
    p = hd.get_security_profile(profile["id"], db_url=db_url)
    assert len(p["pam_rules"]) == 6


def test_add_pam_rule_duplicate_raises(db_url, profile):
    hd.add_pam_rule(profile["id"], "sshd", "auth", "required", "pam_unix.so", db_url=db_url)
    with pytest.raises(ValueError, match="already exists"):
        hd.add_pam_rule(profile["id"], "sshd", "auth", "required", "pam_unix.so", db_url=db_url)


def test_add_pam_rule_invalid_module_type(db_url, profile):
    with pytest.raises(ValueError, match="unknown module type"):
        hd.add_pam_rule(
            profile["id"], "sshd", "security", "required", "pam_unix.so", db_url=db_url
        )


def test_add_pam_rule_invalid_control_flag(db_url, profile):
    with pytest.raises(ValueError, match="unknown control flag"):
        hd.add_pam_rule(
            profile["id"], "sshd", "auth", "binding", "pam_unix.so", db_url=db_url
        )


def test_add_pam_rule_profile_not_found(db_url):
    with pytest.raises(ValueError, match="not found"):
        hd.add_pam_rule("no-such", "sshd", "auth", "required", "pam_unix.so", db_url=db_url)


def test_pam_rules_multiple_services(db_url, profile):
    hd.add_pam_rule(profile["id"], "sshd", "auth", "required", "pam_unix.so", db_url=db_url)
    hd.add_pam_rule(profile["id"], "sudo", "auth", "required", "pam_unix.so", db_url=db_url)
    hd.add_pam_rule(profile["id"], "login", "auth", "required", "pam_unix.so", db_url=db_url)
    p = hd.get_security_profile(profile["id"], db_url=db_url)
    assert len(p["pam_rules"]) == 3


# ---------------------------------------------------------------------------
# Capability grants
# ---------------------------------------------------------------------------


def test_set_capability_grant(db_url, profile):
    cg = hd.set_capability_grant(
        profile["id"],
        "/usr/bin/ping",
        add_caps="net_raw",
        drop_caps="all",
        no_new_privs=True,
        description="Ping needs net_raw",
        db_url=db_url,
    )
    assert cg["executable"] == "/usr/bin/ping"
    assert cg["add_caps"] == "net_raw"
    assert cg["drop_caps"] == "all"
    assert cg["no_new_privs"] is True


def test_set_capability_grant_upsert(db_url, profile):
    hd.set_capability_grant(
        profile["id"], "/usr/bin/ping", add_caps="net_raw", db_url=db_url
    )
    cg2 = hd.set_capability_grant(
        profile["id"], "/usr/bin/ping", add_caps="net_raw net_admin", db_url=db_url
    )
    assert cg2["add_caps"] == "net_raw net_admin"
    p = hd.get_security_profile(profile["id"], db_url=db_url)
    assert len(p["capabilities"]) == 1


def test_set_capability_grant_drop_only(db_url, profile):
    cg = hd.set_capability_grant(
        profile["id"], "/usr/sbin/nginx", drop_caps="all", db_url=db_url
    )
    assert cg["add_caps"] is None
    assert cg["drop_caps"] == "all"


def test_set_capability_grant_multiple(db_url, profile):
    hd.set_capability_grant(profile["id"], "/usr/bin/ping", add_caps="net_raw", db_url=db_url)
    hd.set_capability_grant(
        profile["id"], "/usr/sbin/nginx", drop_caps="all", db_url=db_url
    )
    p = hd.get_security_profile(profile["id"], db_url=db_url)
    assert len(p["capabilities"]) == 2


def test_set_capability_grant_profile_not_found(db_url):
    with pytest.raises(ValueError, match="not found"):
        hd.set_capability_grant("no-such", "/usr/bin/ping", db_url=db_url)


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


def test_render_empty_profile(db_url, profile):
    result = hd.render_security_config(profile["id"], db_url=db_url)
    assert result["content_hash"].startswith("sha256:")
    assert result["sysctl_count"] == 0
    assert result["mac_rule_count"] == 0
    assert result["pam_rule_count"] == 0
    assert result["capability_count"] == 0
    assert "no sysctl settings" in result["rendered_sysctl"]
    assert "no MAC rules" in result["rendered_mac_rules"]
    assert "no PAM rules" in result["rendered_pam_config"]
    assert "no capability grants" in result["rendered_capabilities"]


def test_render_sysctl_content(db_url, profile):
    hd.set_sysctl(
        profile["id"],
        "net.ipv4.ip_forward",
        "0",
        description="Disable IP forwarding",
        db_url=db_url,
    )
    hd.set_sysctl(profile["id"], "kernel.randomize_va_space", "2", db_url=db_url)
    result = hd.render_security_config(profile["id"], db_url=db_url)
    sysctl = result["rendered_sysctl"]
    assert "99-osfabricum.conf" in sysctl
    assert "net.ipv4.ip_forward = 0" in sysctl
    assert "kernel.randomize_va_space = 2" in sysctl
    assert "Disable IP forwarding" in sysctl


def test_render_sysctl_sorted(db_url, profile):
    hd.set_sysctl(profile["id"], "z.last", "1", db_url=db_url)
    hd.set_sysctl(profile["id"], "a.first", "1", db_url=db_url)
    result = hd.render_security_config(profile["id"], db_url=db_url)
    sysctl = result["rendered_sysctl"]
    assert sysctl.index("a.first") < sysctl.index("z.last")


def test_render_mac_rules_content(db_url, profile):
    hd.add_mac_rule(
        profile["id"],
        "/usr/sbin/nginx",
        "  /var/log/nginx/** w,\n",
        is_enforcing=True,
        db_url=db_url,
    )
    result = hd.render_security_config(profile["id"], db_url=db_url)
    mac = result["rendered_mac_rules"]
    assert "MAC policy: apparmor" in mac
    assert "/usr/sbin/nginx" in mac
    assert "(enforce)" in mac
    assert "/var/log/nginx/** w," in mac


def test_render_mac_rule_permissive_marker(db_url, profile):
    hd.add_mac_rule(
        profile["id"], "/usr/bin/test", "  /** r,\n", is_enforcing=False, db_url=db_url
    )
    result = hd.render_security_config(profile["id"], db_url=db_url)
    assert "(permissive)" in result["rendered_mac_rules"]


def test_render_pam_config_content(db_url, profile):
    hd.add_pam_rule(
        profile["id"], "sshd", "auth", "required", "pam_unix.so",
        module_args="nullok", db_url=db_url
    )
    hd.add_pam_rule(
        profile["id"], "sshd", "account", "required", "pam_unix.so", db_url=db_url
    )
    result = hd.render_security_config(profile["id"], db_url=db_url)
    pam = result["rendered_pam_config"]
    assert "/etc/pam.d/sshd" in pam
    assert "auth" in pam
    assert "pam_unix.so" in pam
    assert "nullok" in pam


def test_render_pam_type_order(db_url, profile):
    hd.add_pam_rule(
        profile["id"], "login", "session", "required", "pam_unix.so", db_url=db_url
    )
    hd.add_pam_rule(
        profile["id"], "login", "auth", "required", "pam_unix.so",
        module_args="try_first_pass", db_url=db_url
    )
    result = hd.render_security_config(profile["id"], db_url=db_url)
    pam = result["rendered_pam_config"]
    # auth must appear before session in the rendered output
    assert pam.index("auth") < pam.index("session")


def test_render_pam_multiple_services(db_url, profile):
    hd.add_pam_rule(
        profile["id"], "sshd", "auth", "required", "pam_unix.so", db_url=db_url
    )
    hd.add_pam_rule(
        profile["id"], "sudo", "auth", "required", "pam_unix.so", db_url=db_url
    )
    result = hd.render_security_config(profile["id"], db_url=db_url)
    pam = result["rendered_pam_config"]
    assert "/etc/pam.d/sshd" in pam
    assert "/etc/pam.d/sudo" in pam


def test_render_capabilities_content(db_url, profile):
    hd.set_capability_grant(
        profile["id"],
        "/usr/bin/ping",
        add_caps="net_raw",
        drop_caps="all",
        no_new_privs=True,
        description="ping needs net_raw only",
        db_url=db_url,
    )
    result = hd.render_security_config(profile["id"], db_url=db_url)
    caps = result["rendered_capabilities"]
    assert "/usr/bin/ping" in caps
    assert "add=net_raw" in caps
    assert "drop=all" in caps
    assert "no_new_privs=yes" in caps
    assert "ping needs net_raw only" in caps


def test_render_capabilities_sorted(db_url, profile):
    hd.set_capability_grant(
        profile["id"], "/usr/sbin/nginx", drop_caps="all", db_url=db_url
    )
    hd.set_capability_grant(
        profile["id"], "/usr/bin/ping", add_caps="net_raw", db_url=db_url
    )
    result = hd.render_security_config(profile["id"], db_url=db_url)
    caps = result["rendered_capabilities"]
    assert caps.index("/usr/bin/ping") < caps.index("/usr/sbin/nginx")


def test_render_deterministic(db_url, profile):
    hd.set_sysctl(profile["id"], "net.ipv4.ip_forward", "0", db_url=db_url)
    hd.add_mac_rule(profile["id"], "/usr/sbin/nginx", "  r,\n", db_url=db_url)
    r1 = hd.render_security_config(profile["id"], db_url=db_url)
    r2 = hd.render_security_config(profile["id"], db_url=db_url)
    assert r1["content_hash"] == r2["content_hash"]


def test_render_stored_on_profile(db_url, profile):
    hd.set_sysctl(profile["id"], "kernel.randomize_va_space", "2", db_url=db_url)
    result = hd.render_security_config(profile["id"], db_url=db_url)
    fetched = hd.get_security_profile(profile["id"], db_url=db_url)
    assert fetched["content_hash"] == result["content_hash"]
    assert fetched["rendered_sysctl"] == result["rendered_sysctl"]


def test_render_hash_changes_after_sysctl_add(db_url, profile):
    r1 = hd.render_security_config(profile["id"], db_url=db_url)
    hd.set_sysctl(profile["id"], "net.ipv4.ip_forward", "0", db_url=db_url)
    r2 = hd.render_security_config(profile["id"], db_url=db_url)
    assert r1["content_hash"] != r2["content_hash"]


def test_render_update_clears_cache(db_url, profile):
    hd.set_sysctl(profile["id"], "net.ipv4.ip_forward", "0", db_url=db_url)
    hd.render_security_config(profile["id"], db_url=db_url)
    fetched = hd.get_security_profile(profile["id"], db_url=db_url)
    assert fetched["content_hash"] is not None
    hd.update_security_profile(profile["id"], mac_policy="selinux", db_url=db_url)
    fetched2 = hd.get_security_profile(profile["id"], db_url=db_url)
    assert fetched2["content_hash"] is None


def test_render_profile_not_found(db_url):
    with pytest.raises(ValueError, match="not found"):
        hd.render_security_config("no-such", db_url=db_url)
