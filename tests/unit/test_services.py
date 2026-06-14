"""Unit tests for M46 — Service / Init / Device Manager Designer."""

from __future__ import annotations

import pytest

from osfabricum import services as svc
from osfabricum.db.models import Base
from osfabricum.db.seed_data import seed_init_system_kinds

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_url(tmp_path):
    url = f"sqlite:///{tmp_path}/test_services.db"
    from sqlalchemy import create_engine  # noqa: PLC0415

    engine = create_engine(url)
    Base.metadata.create_all(engine)

    from sqlalchemy.orm import Session  # noqa: PLC0415

    with Session(engine) as s:
        seed_init_system_kinds(s)
        s.commit()

    engine.dispose()
    return url


@pytest.fixture()
def profile(db_url):
    return svc.create_service_profile(
        "base-server", init_system="systemd", db_url=db_url
    )


@pytest.fixture()
def profile2(db_url):
    return svc.create_service_profile(
        "minimal", init_system="busybox-init", db_url=db_url
    )


# ---------------------------------------------------------------------------
# Init system kinds
# ---------------------------------------------------------------------------


def test_list_kinds_seeded(db_url):
    kinds = svc.list_init_system_kinds(db_url=db_url)
    assert len(kinds) == 7
    names = {k["name"] for k in kinds}
    for expected in ("systemd", "openrc", "s6", "runit", "busybox-init", "dinit", "shepherd"):
        assert expected in names


def test_kinds_ordered(db_url):
    kinds = svc.list_init_system_kinds(db_url=db_url)
    orders = [k["display_order"] for k in kinds]
    assert orders == sorted(orders)


def test_kinds_idempotent(db_url):
    from sqlalchemy import create_engine  # noqa: PLC0415
    from sqlalchemy.orm import Session  # noqa: PLC0415

    engine = create_engine(db_url)
    with Session(engine) as s:
        seed_init_system_kinds(s)
        s.commit()
    engine.dispose()

    kinds = svc.list_init_system_kinds(db_url=db_url)
    assert len(kinds) == 7


# ---------------------------------------------------------------------------
# Profile CRUD
# ---------------------------------------------------------------------------


def test_create_profile(profile):
    assert profile["name"] == "base-server"
    assert profile["init_system"] == "systemd"
    assert profile["content_hash"] is None


def test_list_profiles(db_url, profile, profile2):
    all_profiles = svc.list_service_profiles(db_url=db_url)
    assert len(all_profiles) == 2
    names = {p["name"] for p in all_profiles}
    assert "base-server" in names
    assert "minimal" in names


def test_get_profile_full(db_url, profile):
    p = svc.get_service_profile(profile["id"], db_url=db_url)
    assert p["entries"] == []
    assert p["device_rules"] == []
    assert p["unit_overrides"] == []


def test_update_profile(db_url, profile):
    updated = svc.update_service_profile(
        profile["id"],
        name="server-base-v2",
        init_system="openrc",
        db_url=db_url,
    )
    assert updated["name"] == "server-base-v2"
    assert updated["init_system"] == "openrc"
    assert updated["content_hash"] is None


def test_create_duplicate_raises(db_url, profile):
    with pytest.raises(ValueError, match="already exists"):
        svc.create_service_profile("base-server", db_url=db_url)


def test_get_not_found(db_url):
    with pytest.raises(ValueError, match="not found"):
        svc.get_service_profile("no-such-id", db_url=db_url)


def test_create_invalid_init_system(db_url):
    with pytest.raises(ValueError, match="unknown init system"):
        svc.create_service_profile("bad", init_system="upstart", db_url=db_url)


def test_update_invalid_init_system(db_url, profile):
    with pytest.raises(ValueError, match="unknown init system"):
        svc.update_service_profile(
            profile["id"], init_system="launchd", db_url=db_url
        )


# ---------------------------------------------------------------------------
# Service entries
# ---------------------------------------------------------------------------


def test_add_service_entry(db_url, profile):
    e = svc.add_service_entry(
        profile["id"],
        "sshd",
        exec_start="/usr/sbin/sshd -D",
        restart_policy="on-failure",
        db_url=db_url,
    )
    assert e["name"] == "sshd"
    assert e["unit_type"] == "service"
    assert e["restart_policy"] == "on-failure"
    assert e["exec_start"] == "/usr/sbin/sshd -D"
    assert e["is_enabled"] is True
    assert e["is_masked"] is False


def test_add_entry_default_values(db_url, profile):
    e = svc.add_service_entry(profile["id"], "nginx", db_url=db_url)
    assert e["unit_type"] == "service"
    assert e["restart_policy"] == "no"
    assert e["wanted_by"] == "multi-user.target"
    assert e["priority"] == 100


def test_add_socket_entry(db_url, profile):
    e = svc.add_service_entry(
        profile["id"],
        "myapp",
        unit_type="socket",
        exec_start="/run/myapp.sock",
        db_url=db_url,
    )
    assert e["unit_type"] == "socket"


def test_add_timer_entry(db_url, profile):
    e = svc.add_service_entry(
        profile["id"],
        "backup",
        unit_type="timer",
        exec_start="*-*-* 03:00:00",
        db_url=db_url,
    )
    assert e["unit_type"] == "timer"


def test_add_target_entry(db_url, profile):
    e = svc.add_service_entry(
        profile["id"], "my-network", unit_type="target", db_url=db_url
    )
    assert e["unit_type"] == "target"


def test_add_masked_entry(db_url, profile):
    e = svc.add_service_entry(
        profile["id"], "cups", is_enabled=False, is_masked=True, db_url=db_url
    )
    assert e["is_enabled"] is False
    assert e["is_masked"] is True


def test_add_entry_with_user_group(db_url, profile):
    e = svc.add_service_entry(
        profile["id"],
        "redis",
        exec_start="/usr/bin/redis-server",
        run_user="redis",
        run_group="redis",
        working_directory="/var/lib/redis",
        db_url=db_url,
    )
    assert e["run_user"] == "redis"
    assert e["run_group"] == "redis"
    assert e["working_directory"] == "/var/lib/redis"


def test_add_entry_with_environment(db_url, profile):
    e = svc.add_service_entry(
        profile["id"],
        "myapp",
        environment="PORT=8080\nLOG_LEVEL=info",
        db_url=db_url,
    )
    assert "PORT=8080" in e["environment"]


def test_add_entry_duplicate_raises(db_url, profile):
    svc.add_service_entry(profile["id"], "sshd", db_url=db_url)
    with pytest.raises(ValueError, match="already exists"):
        svc.add_service_entry(profile["id"], "sshd", db_url=db_url)


def test_add_entry_same_name_different_type_ok(db_url, profile):
    svc.add_service_entry(profile["id"], "myapp", unit_type="service", db_url=db_url)
    e = svc.add_service_entry(profile["id"], "myapp", unit_type="socket", db_url=db_url)
    assert e["unit_type"] == "socket"


def test_add_entry_invalid_unit_type(db_url, profile):
    with pytest.raises(ValueError, match="unknown unit type"):
        svc.add_service_entry(profile["id"], "bad", unit_type="mount", db_url=db_url)


def test_add_entry_invalid_restart(db_url, profile):
    with pytest.raises(ValueError, match="unknown restart policy"):
        svc.add_service_entry(
            profile["id"], "bad", restart_policy="on-success", db_url=db_url
        )


def test_add_entry_profile_not_found(db_url):
    with pytest.raises(ValueError, match="not found"):
        svc.add_service_entry("no-such", "sshd", db_url=db_url)


def test_entries_in_get_profile(db_url, profile):
    svc.add_service_entry(
        profile["id"], "sshd", exec_start="/usr/sbin/sshd -D", db_url=db_url
    )
    svc.add_service_entry(
        profile["id"], "nginx", priority=50, db_url=db_url
    )
    p = svc.get_service_profile(profile["id"], db_url=db_url)
    assert len(p["entries"]) == 2
    # sorted by priority then name
    assert p["entries"][0]["name"] == "nginx"  # priority 50 first


# ---------------------------------------------------------------------------
# Device rules
# ---------------------------------------------------------------------------


def test_add_device_rule(db_url, profile):
    dr = svc.add_device_rule(
        profile["id"],
        subsystem="block",
        kernel_pattern="sd*",
        udev_action="add",
        symlink="disk/by-id/my-disk",
        priority=90,
        db_url=db_url,
    )
    assert dr["subsystem"] == "block"
    assert dr["kernel_pattern"] == "sd*"
    assert dr["symlink"] == "disk/by-id/my-disk"
    assert dr["priority"] == 90


def test_add_device_rule_with_mode_owner(db_url, profile):
    dr = svc.add_device_rule(
        profile["id"],
        subsystem="usb",
        mode="0660",
        owner="root",
        group_name="plugdev",
        db_url=db_url,
    )
    assert dr["mode"] == "0660"
    assert dr["owner"] == "root"
    assert dr["group_name"] == "plugdev"


def test_add_device_rule_with_run_command(db_url, profile):
    dr = svc.add_device_rule(
        profile["id"],
        subsystem="net",
        run_command="/usr/bin/notify-interface %k",
        db_url=db_url,
    )
    assert "/usr/bin/notify-interface" in dr["run_command"]


def test_add_device_rule_invalid_action(db_url, profile):
    with pytest.raises(ValueError, match="unknown udev action"):
        svc.add_device_rule(
            profile["id"], udev_action="modify", db_url=db_url
        )


def test_add_device_rule_profile_not_found(db_url):
    with pytest.raises(ValueError, match="not found"):
        svc.add_device_rule("no-such", subsystem="block", db_url=db_url)


def test_multiple_device_rules(db_url, profile):
    svc.add_device_rule(profile["id"], subsystem="block", priority=90, db_url=db_url)
    svc.add_device_rule(profile["id"], subsystem="usb", priority=80, db_url=db_url)
    p = svc.get_service_profile(profile["id"], db_url=db_url)
    assert len(p["device_rules"]) == 2


# ---------------------------------------------------------------------------
# Unit overrides
# ---------------------------------------------------------------------------


def test_set_unit_override(db_url, profile):
    uo = svc.set_unit_override(
        profile["id"],
        "sshd.service",
        "TimeoutStartSec=30\nLimitNOFILE=65536",
        section="Service",
        db_url=db_url,
    )
    assert uo["unit_name"] == "sshd.service"
    assert uo["section"] == "Service"
    assert "TimeoutStartSec=30" in uo["override_content"]


def test_set_unit_override_upsert(db_url, profile):
    svc.set_unit_override(
        profile["id"], "nginx.service", "LimitNOFILE=65536", db_url=db_url
    )
    uo2 = svc.set_unit_override(
        profile["id"], "nginx.service", "LimitNOFILE=131072", db_url=db_url
    )
    assert "131072" in uo2["override_content"]
    p = svc.get_service_profile(profile["id"], db_url=db_url)
    assert len(p["unit_overrides"]) == 1


def test_set_unit_override_different_sections(db_url, profile):
    svc.set_unit_override(
        profile["id"], "sshd.service", "TimeoutSec=60", section="Service", db_url=db_url
    )
    svc.set_unit_override(
        profile["id"], "systemd-networkd.service", "ProtectHome=yes", section="Unit", db_url=db_url
    )
    p = svc.get_service_profile(profile["id"], db_url=db_url)
    assert len(p["unit_overrides"]) == 2


def test_set_unit_override_invalid_section(db_url, profile):
    with pytest.raises(ValueError, match="unknown section"):
        svc.set_unit_override(
            profile["id"], "sshd.service", "X=1", section="Invalid", db_url=db_url
        )


def test_set_unit_override_profile_not_found(db_url):
    with pytest.raises(ValueError, match="not found"):
        svc.set_unit_override("no-such", "sshd.service", "X=1", db_url=db_url)


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


def test_render_empty_profile(db_url, profile):
    result = svc.render_service_config(profile["id"], db_url=db_url)
    assert result["content_hash"].startswith("sha256:")
    assert result["entry_count"] == 0
    assert result["device_rule_count"] == 0
    assert result["override_count"] == 0
    assert "no service entries configured" in result["rendered_units"]
    assert "no device rules configured" in result["rendered_udev"]
    assert "no unit overrides configured" in result["rendered_overrides"]


def test_render_unit_file_content(db_url, profile):
    svc.add_service_entry(
        profile["id"],
        "sshd",
        exec_start="/usr/sbin/sshd -D",
        restart_policy="on-failure",
        wanted_by="multi-user.target",
        run_user="root",
        db_url=db_url,
    )
    result = svc.render_service_config(profile["id"], db_url=db_url)
    units = result["rendered_units"]
    assert "##-- /etc/systemd/system/sshd.service --##" in units
    assert "[Unit]" in units
    assert "[Service]" in units
    assert "ExecStart=/usr/sbin/sshd -D" in units
    assert "Restart=on-failure" in units
    assert "User=root" in units
    assert "[Install]" in units
    assert "WantedBy=multi-user.target" in units


def test_render_masked_entry(db_url, profile):
    svc.add_service_entry(
        profile["id"], "cups", is_masked=True, db_url=db_url
    )
    result = svc.render_service_config(profile["id"], db_url=db_url)
    assert "# MASKED" in result["rendered_units"]


def test_render_disabled_entry(db_url, profile):
    svc.add_service_entry(
        profile["id"], "telnet", is_enabled=False, db_url=db_url
    )
    result = svc.render_service_config(profile["id"], db_url=db_url)
    assert "# DISABLED" in result["rendered_units"]


def test_render_socket_unit(db_url, profile):
    svc.add_service_entry(
        profile["id"],
        "myapp",
        unit_type="socket",
        exec_start="/run/myapp.sock",
        db_url=db_url,
    )
    result = svc.render_service_config(profile["id"], db_url=db_url)
    assert "myapp.socket" in result["rendered_units"]
    assert "[Socket]" in result["rendered_units"]
    assert "ListenStream=/run/myapp.sock" in result["rendered_units"]


def test_render_timer_unit(db_url, profile):
    svc.add_service_entry(
        profile["id"],
        "backup",
        unit_type="timer",
        exec_start="*-*-* 03:00:00",
        db_url=db_url,
    )
    result = svc.render_service_config(profile["id"], db_url=db_url)
    assert "backup.timer" in result["rendered_units"]
    assert "[Timer]" in result["rendered_units"]
    assert "OnCalendar=*-*-* 03:00:00" in result["rendered_units"]
    assert "Persistent=true" in result["rendered_units"]


def test_render_entry_with_after_requires(db_url, profile):
    svc.add_service_entry(
        profile["id"],
        "mydb",
        after="network.target network-online.target",
        requires="network-online.target",
        db_url=db_url,
    )
    result = svc.render_service_config(profile["id"], db_url=db_url)
    assert "After=network.target network-online.target" in result["rendered_units"]
    assert "Requires=network-online.target" in result["rendered_units"]


def test_render_entry_environment(db_url, profile):
    svc.add_service_entry(
        profile["id"],
        "myapp",
        exec_start="/usr/bin/myapp",
        environment="PORT=8080\nLOG_LEVEL=debug",
        db_url=db_url,
    )
    result = svc.render_service_config(profile["id"], db_url=db_url)
    assert "Environment=PORT=8080" in result["rendered_units"]
    assert "Environment=LOG_LEVEL=debug" in result["rendered_units"]


def test_render_udev_rule(db_url, profile):
    svc.add_device_rule(
        profile["id"],
        subsystem="block",
        kernel_pattern="sd*",
        udev_action="add",
        symlink="disk/by-id/my-disk",
        mode="0660",
        group_name="disk",
        priority=90,
        db_url=db_url,
    )
    result = svc.render_service_config(profile["id"], db_url=db_url)
    udev = result["rendered_udev"]
    assert 'SUBSYSTEM=="block"' in udev
    assert 'KERNEL=="sd*"' in udev
    assert 'ACTION=="add"' in udev
    assert 'SYMLINK+="disk/by-id/my-disk"' in udev
    assert 'MODE="0660"' in udev
    assert 'GROUP="disk"' in udev


def test_render_udev_any_action_omitted(db_url, profile):
    svc.add_device_rule(
        profile["id"],
        subsystem="usb",
        udev_action="any",
        symlink="my-device",
        db_url=db_url,
    )
    result = svc.render_service_config(profile["id"], db_url=db_url)
    assert 'ACTION==' not in result["rendered_udev"]


def test_render_udev_priority_ordering(db_url, profile):
    svc.add_device_rule(
        profile["id"], subsystem="block", priority=90, db_url=db_url
    )
    svc.add_device_rule(
        profile["id"], subsystem="usb", priority=60, db_url=db_url
    )
    result = svc.render_service_config(profile["id"], db_url=db_url)
    udev = result["rendered_udev"]
    assert udev.index("priority 60") < udev.index("priority 90")


def test_render_unit_override(db_url, profile):
    svc.set_unit_override(
        profile["id"],
        "sshd.service",
        "TimeoutStartSec=30\nLimitNOFILE=65536",
        section="Service",
        db_url=db_url,
    )
    result = svc.render_service_config(profile["id"], db_url=db_url)
    overrides = result["rendered_overrides"]
    assert "sshd.service.d/override.conf" in overrides
    assert "[Service]" in overrides
    assert "TimeoutStartSec=30" in overrides


def test_render_deterministic(db_url, profile):
    svc.add_service_entry(
        profile["id"], "sshd", exec_start="/usr/sbin/sshd -D", db_url=db_url
    )
    r1 = svc.render_service_config(profile["id"], db_url=db_url)
    r2 = svc.render_service_config(profile["id"], db_url=db_url)
    assert r1["content_hash"] == r2["content_hash"]


def test_render_stored_on_profile(db_url, profile):
    svc.add_service_entry(
        profile["id"], "nginx", exec_start="/usr/sbin/nginx", db_url=db_url
    )
    result = svc.render_service_config(profile["id"], db_url=db_url)
    fetched = svc.get_service_profile(profile["id"], db_url=db_url)
    assert fetched["content_hash"] == result["content_hash"]
    assert fetched["rendered_units"] == result["rendered_units"]


def test_render_hash_changes_after_entry_add(db_url, profile):
    r1 = svc.render_service_config(profile["id"], db_url=db_url)
    svc.add_service_entry(
        profile["id"], "sshd", exec_start="/usr/sbin/sshd -D", db_url=db_url
    )
    r2 = svc.render_service_config(profile["id"], db_url=db_url)
    assert r1["content_hash"] != r2["content_hash"]


def test_render_multiple_entries_sorted(db_url, profile):
    svc.add_service_entry(
        profile["id"], "zebra", priority=200, db_url=db_url
    )
    svc.add_service_entry(
        profile["id"], "alpha", priority=100, db_url=db_url
    )
    result = svc.render_service_config(profile["id"], db_url=db_url)
    units = result["rendered_units"]
    assert units.index("alpha.service") < units.index("zebra.service")


def test_render_profile_not_found(db_url):
    with pytest.raises(ValueError, match="not found"):
        svc.render_service_config("no-such", db_url=db_url)
