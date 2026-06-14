"""Unit tests for M49 — Update / OTA / Recovery Designer."""

from __future__ import annotations

import pytest

from osfabricum import updates as upd
from osfabricum.db.models import Base
from osfabricum.db.seed_data import seed_update_strategy_kinds


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_engine(tmp_path):
    from sqlalchemy import create_engine  # noqa: PLC0415

    url = f"sqlite:///{tmp_path}/test_updates.db"
    engine = create_engine(url)
    Base.metadata.create_all(engine)

    from sqlalchemy.orm import Session  # noqa: PLC0415

    with Session(engine) as s:
        seed_update_strategy_kinds(s)
        s.commit()

    return engine


@pytest.fixture()
def session(db_engine):
    from sqlalchemy.orm import Session  # noqa: PLC0415

    with Session(db_engine) as s:
        yield s


@pytest.fixture()
def profile(session):
    p = upd.create_update_profile(session, "default-ota")
    session.commit()
    return p


# ---------------------------------------------------------------------------
# Strategy kinds
# ---------------------------------------------------------------------------


def test_strategy_kinds_seeded(session):
    kinds = upd.list_update_strategy_kinds(session)
    assert len(kinds) == 6


def test_strategy_kinds_ordered(session):
    kinds = upd.list_update_strategy_kinds(session)
    orders = [k.display_order for k in kinds]
    assert orders == sorted(orders)


def test_strategy_kinds_values(session):
    kinds = {k.kind for k in upd.list_update_strategy_kinds(session)}
    assert kinds == {"full", "a-b", "delta", "recovery", "rollback", "manual"}


def test_strategy_kinds_have_labels(session):
    kinds = upd.list_update_strategy_kinds(session)
    for k in kinds:
        assert k.label
        assert k.description


def test_strategy_seed_idempotent(session):
    count = seed_update_strategy_kinds(session)
    assert count == 0


# ---------------------------------------------------------------------------
# Update profiles — CRUD
# ---------------------------------------------------------------------------


def test_create_profile_defaults(profile):
    assert profile.name == "default-ota"
    assert profile.strategy == "full"
    assert profile.signing_required is True
    assert profile.rollback_enabled is True
    assert profile.rollback_window_days == 30
    assert profile.verification_mode == "strict"
    assert profile.content_hash is None
    assert profile.max_delta_size_mb is None


def test_create_profile_all_options(session):
    p = upd.create_update_profile(
        session, "a-b-policy",
        strategy="a-b",
        signing_required=True,
        rollback_enabled=True,
        rollback_window_days=14,
        max_delta_size_mb=512,
        verification_mode="relaxed",
        description="A/B policy",
    )
    session.commit()
    assert p.strategy == "a-b"
    assert p.max_delta_size_mb == 512
    assert p.verification_mode == "relaxed"


def test_create_profile_invalid_strategy(session):
    with pytest.raises(ValueError, match="strategy"):
        upd.create_update_profile(session, "bad", strategy="teleport")


def test_create_profile_invalid_verification(session):
    with pytest.raises(ValueError, match="verification_mode"):
        upd.create_update_profile(session, "bad", verification_mode="paranoid")


def test_create_profile_duplicate(session, profile):
    with pytest.raises(ValueError, match="already exists"):
        upd.create_update_profile(session, "default-ota")


def test_list_profiles(session, profile):
    p2 = upd.create_update_profile(session, "second-ota")
    session.commit()
    names = [p.name for p in upd.list_update_profiles(session)]
    assert "default-ota" in names
    assert "second-ota" in names


def test_get_profile(session, profile):
    fetched = upd.get_update_profile(session, profile.id)
    assert fetched.id == profile.id


def test_get_profile_not_found(session):
    with pytest.raises(KeyError, match="not found"):
        upd.get_update_profile(session, "no-such-id")


def test_update_profile(session, profile):
    upd.update_update_profile(
        session, profile.id,
        strategy="a-b",
        rollback_window_days=7,
        signing_required=False,
    )
    session.commit()
    p = upd.get_update_profile(session, profile.id)
    assert p.strategy == "a-b"
    assert p.rollback_window_days == 7
    assert p.signing_required is False


def test_update_profile_clears_hash(session, profile):
    profile.content_hash = "sha256:abc"
    session.flush()
    upd.update_update_profile(session, profile.id, description="updated")
    session.commit()
    p = upd.get_update_profile(session, profile.id)
    assert p.content_hash is None


def test_update_profile_not_found(session):
    with pytest.raises(KeyError, match="not found"):
        upd.update_update_profile(session, "no-id", description="x")


def test_update_profile_invalid_strategy(session, profile):
    with pytest.raises(ValueError, match="strategy"):
        upd.update_update_profile(session, profile.id, strategy="warp")


def test_update_profile_all_strategies(session):
    for i, strat in enumerate(upd.VALID_STRATEGIES):
        p = upd.create_update_profile(session, f"strat-{i}", strategy=strat)
        assert p.strategy == strat


# ---------------------------------------------------------------------------
# Update channels
# ---------------------------------------------------------------------------


def test_add_channel(session, profile):
    ch = upd.add_update_channel(session, profile.id, "stable", priority=0)
    session.commit()
    assert ch.name == "stable"
    assert ch.is_default is False


def test_add_channel_with_url(session, profile):
    ch = upd.add_update_channel(
        session, profile.id, "nightly",
        priority=10, url="https://nightly.example.com",
        signing_key_id="key-nightly-01", is_default=False,
    )
    session.commit()
    assert ch.url == "https://nightly.example.com"
    assert ch.signing_key_id == "key-nightly-01"


def test_add_channel_upsert(session, profile):
    upd.add_update_channel(session, profile.id, "stable", priority=0)
    session.commit()
    upd.add_update_channel(
        session, profile.id, "stable", priority=5, url="https://new.example.com"
    )
    session.commit()
    channels = upd.list_update_channels(session, profile.id)
    assert len(channels) == 1
    assert channels[0].priority == 5
    assert channels[0].url == "https://new.example.com"


def test_add_channel_default(session, profile):
    ch = upd.add_update_channel(
        session, profile.id, "lts", priority=0, is_default=True
    )
    session.commit()
    assert ch.is_default is True


def test_list_channels_ordered(session, profile):
    for name, prio in (("c", 2), ("a", 0), ("b", 1)):
        upd.add_update_channel(session, profile.id, name, priority=prio)
    session.commit()
    channels = upd.list_update_channels(session, profile.id)
    priorities = [ch.priority for ch in channels]
    assert priorities == sorted(priorities)


def test_list_channels_not_found(session):
    with pytest.raises(KeyError, match="not found"):
        upd.list_update_channels(session, "no-id")


def test_add_channel_not_found_profile(session):
    with pytest.raises(KeyError, match="not found"):
        upd.add_update_channel(session, "no-id", "stable")


# ---------------------------------------------------------------------------
# Recovery targets
# ---------------------------------------------------------------------------


def test_add_recovery_target(session, profile):
    t = upd.add_recovery_target(session, profile.id, "minimal-recovery", "minimal")
    session.commit()
    assert t.name == "minimal-recovery"
    assert t.target_type == "minimal"
    assert t.is_default is False


def test_add_recovery_target_all_types(session, profile):
    for i, ttype in enumerate(upd.VALID_RECOVERY_TARGET_TYPES):
        t = upd.add_recovery_target(session, profile.id, f"target-{i}", ttype)
        assert t.target_type == ttype


def test_add_recovery_target_upsert(session, profile):
    upd.add_recovery_target(session, profile.id, "factory", "factory-reset")
    session.commit()
    upd.add_recovery_target(
        session, profile.id, "factory", "factory-reset",
        kernel_args="recovery=1", is_default=True
    )
    session.commit()
    targets = upd.list_recovery_targets(session, profile.id)
    assert len(targets) == 1
    assert targets[0].is_default is True
    assert targets[0].kernel_args == "recovery=1"


def test_add_recovery_target_with_kernel_args(session, profile):
    t = upd.add_recovery_target(
        session, profile.id, "emergency", "emergency-shell",
        kernel_args="console=ttyS0 emergency=1",
        initramfs_hint="/boot/initramfs-emergency.cpio.gz",
        priority=10,
    )
    session.commit()
    assert t.kernel_args == "console=ttyS0 emergency=1"
    assert t.initramfs_hint == "/boot/initramfs-emergency.cpio.gz"


def test_add_recovery_target_invalid_type(session, profile):
    with pytest.raises(ValueError, match="target_type"):
        upd.add_recovery_target(session, profile.id, "bad", "laser-beam")


def test_list_recovery_targets_ordered(session, profile):
    for name, prio in (("c", 2), ("a", 0), ("b", 1)):
        upd.add_recovery_target(session, profile.id, name, "minimal", priority=prio)
    session.commit()
    targets = upd.list_recovery_targets(session, profile.id)
    priorities = [t.priority for t in targets]
    assert priorities == sorted(priorities)


def test_list_recovery_targets_not_found(session):
    with pytest.raises(KeyError, match="not found"):
        upd.list_recovery_targets(session, "no-id")


def test_add_recovery_target_not_found_profile(session):
    with pytest.raises(KeyError, match="not found"):
        upd.add_recovery_target(session, "no-id", "t", "minimal")


# ---------------------------------------------------------------------------
# Update hooks
# ---------------------------------------------------------------------------


def test_add_hook(session, profile):
    h = upd.add_update_hook(
        session, profile.id, "pre-apply", "#!/bin/sh\necho pre"
    )
    session.commit()
    assert h.hook_point == "pre-apply"
    assert h.is_enabled is True
    assert "echo pre" in h.script_content


def test_add_hook_all_points(session, profile):
    for i, point in enumerate(upd.VALID_HOOK_POINTS):
        h = upd.add_update_hook(
            session, profile.id, point, f"#!/bin/sh\n# {point}", priority=i
        )
        assert h.hook_point == point


def test_add_hook_upsert(session, profile):
    upd.add_update_hook(session, profile.id, "post-apply", "#!/bin/sh\nv1", priority=0)
    session.commit()
    upd.add_update_hook(
        session, profile.id, "post-apply", "#!/bin/sh\nv2", priority=0
    )
    session.commit()
    hooks = upd.list_update_hooks(session, profile.id)
    assert len(hooks) == 1
    assert "v2" in hooks[0].script_content


def test_add_hook_disabled(session, profile):
    h = upd.add_update_hook(
        session, profile.id, "rollback", "#!/bin/sh\nrollback",
        is_enabled=False
    )
    session.commit()
    assert h.is_enabled is False


def test_add_hook_multiple_priorities(session, profile):
    for prio in (0, 1, 2):
        upd.add_update_hook(
            session, profile.id, "pre-download", f"# step {prio}", priority=prio
        )
    session.commit()
    hooks = upd.list_update_hooks(session, profile.id)
    assert len(hooks) == 3


def test_add_hook_invalid_point(session, profile):
    with pytest.raises(ValueError, match="hook_point"):
        upd.add_update_hook(session, profile.id, "pre-lunch", "#!/bin/sh")


def test_list_hooks_ordered(session, profile):
    upd.add_update_hook(session, profile.id, "post-reboot", "# r", priority=0)
    upd.add_update_hook(session, profile.id, "pre-apply", "# a", priority=0)
    upd.add_update_hook(session, profile.id, "post-apply", "# b", priority=0)
    session.commit()
    hooks = upd.list_update_hooks(session, profile.id)
    points = [h.hook_point for h in hooks]
    assert points == sorted(points)


def test_list_hooks_not_found(session):
    with pytest.raises(KeyError, match="not found"):
        upd.list_update_hooks(session, "no-id")


def test_add_hook_not_found_profile(session):
    with pytest.raises(KeyError, match="not found"):
        upd.add_update_hook(session, "no-id", "pre-apply", "#!/bin/sh")


# ---------------------------------------------------------------------------
# Render — update config
# ---------------------------------------------------------------------------


def test_render_empty(session, profile):
    p = upd.render_update_config(session, profile.id)
    assert p.content_hash is not None
    assert p.content_hash.startswith("sha256:")
    assert p.rendered_update_config is not None
    assert p.rendered_recovery_config is not None


def test_render_update_strategy_section(session, profile):
    p = upd.render_update_config(session, profile.id)
    assert "[strategy]" in p.rendered_update_config
    assert f"type = {profile.strategy}" in p.rendered_update_config
    assert "signing_required = true" in p.rendered_update_config
    assert "rollback_enabled = true" in p.rendered_update_config
    assert "verification_mode = strict" in p.rendered_update_config


def test_render_channels_section(session, profile):
    upd.add_update_channel(
        session, profile.id, "stable", priority=0,
        url="https://stable.example.com", is_default=True
    )
    upd.add_update_channel(session, profile.id, "nightly", priority=10)
    session.flush()
    p = upd.render_update_config(session, profile.id)
    assert "[channels]" in p.rendered_update_config
    assert "stable" in p.rendered_update_config
    assert "https://stable.example.com" in p.rendered_update_config
    assert "(default)" in p.rendered_update_config
    assert "nightly" in p.rendered_update_config


def test_render_channels_sorted_by_priority(session, profile):
    upd.add_update_channel(session, profile.id, "z-channel", priority=99)
    upd.add_update_channel(session, profile.id, "a-channel", priority=0)
    session.flush()
    p = upd.render_update_config(session, profile.id)
    a_pos = p.rendered_update_config.index("a-channel")
    z_pos = p.rendered_update_config.index("z-channel")
    assert a_pos < z_pos


def test_render_hooks_section(session, profile):
    upd.add_update_hook(
        session, profile.id, "pre-apply", "#!/bin/sh\necho applying"
    )
    session.flush()
    p = upd.render_update_config(session, profile.id)
    assert "[hooks]" in p.rendered_update_config
    assert "pre-apply" in p.rendered_update_config
    assert "echo applying" in p.rendered_update_config


def test_render_disabled_hooks_excluded(session, profile):
    upd.add_update_hook(
        session, profile.id, "post-apply", "#!/bin/sh\necho enabled"
    )
    upd.add_update_hook(
        session, profile.id, "pre-apply", "#!/bin/sh\necho disabled",
        is_enabled=False
    )
    session.flush()
    p = upd.render_update_config(session, profile.id)
    assert "echo enabled" in p.rendered_update_config
    assert "echo disabled" not in p.rendered_update_config


def test_render_max_delta_present(session):
    profile = upd.create_update_profile(
        session, "delta-policy", strategy="delta", max_delta_size_mb=256
    )
    session.flush()
    p = upd.render_update_config(session, profile.id)
    assert "max_delta_size_mb = 256" in p.rendered_update_config


# ---------------------------------------------------------------------------
# Render — recovery config
# ---------------------------------------------------------------------------


def test_render_recovery_header(session, profile):
    p = upd.render_update_config(session, profile.id)
    assert "Recovery Configuration" in p.rendered_recovery_config
    assert "[recovery]" in p.rendered_recovery_config


def test_render_recovery_targets(session, profile):
    upd.add_recovery_target(
        session, profile.id, "factory", "factory-reset",
        kernel_args="recovery=1", is_default=True
    )
    upd.add_recovery_target(session, profile.id, "shell", "emergency-shell")
    session.flush()
    p = upd.render_update_config(session, profile.id)
    assert "factory" in p.rendered_recovery_config
    assert "factory-reset" in p.rendered_recovery_config
    assert "recovery=1" in p.rendered_recovery_config
    assert "(DEFAULT)" in p.rendered_recovery_config
    assert "shell" in p.rendered_recovery_config


def test_render_recovery_sorted_by_priority(session, profile):
    upd.add_recovery_target(
        session, profile.id, "z-target", "minimal", priority=99
    )
    upd.add_recovery_target(
        session, profile.id, "a-target", "minimal", priority=0
    )
    session.flush()
    p = upd.render_update_config(session, profile.id)
    a_pos = p.rendered_recovery_config.index("a-target")
    z_pos = p.rendered_recovery_config.index("z-target")
    assert a_pos < z_pos


def test_render_recovery_no_targets_note(session, profile):
    p = upd.render_update_config(session, profile.id)
    assert "No recovery targets defined" in p.rendered_recovery_config


# ---------------------------------------------------------------------------
# Render — determinism and cache
# ---------------------------------------------------------------------------


def test_render_deterministic(session, profile):
    upd.add_update_channel(session, profile.id, "stable", priority=0)
    session.flush()
    p1 = upd.render_update_config(session, profile.id)
    h1 = p1.content_hash
    p2 = upd.render_update_config(session, profile.id)
    assert p2.content_hash == h1


def test_render_stored(session, profile):
    p = upd.render_update_config(session, profile.id)
    session.commit()
    fetched = upd.get_update_profile(session, profile.id)
    assert fetched.content_hash == p.content_hash
    assert fetched.rendered_update_config is not None


def test_render_hash_changes_on_new_channel(session, profile):
    p1 = upd.render_update_config(session, profile.id)
    h1 = p1.content_hash
    upd.add_update_channel(session, profile.id, "new-channel", priority=5)
    session.flush()
    p2 = upd.render_update_config(session, profile.id)
    assert p2.content_hash != h1


def test_render_hash_changes_on_new_target(session, profile):
    p1 = upd.render_update_config(session, profile.id)
    h1 = p1.content_hash
    upd.add_recovery_target(session, profile.id, "new-target", "minimal")
    session.flush()
    p2 = upd.render_update_config(session, profile.id)
    assert p2.content_hash != h1


def test_add_channel_clears_hash(session, profile):
    upd.render_update_config(session, profile.id)
    session.flush()
    upd.add_update_channel(session, profile.id, "extra", priority=99)
    session.flush()
    fetched = upd.get_update_profile(session, profile.id)
    assert fetched.content_hash is None


def test_add_hook_clears_hash(session, profile):
    upd.render_update_config(session, profile.id)
    session.flush()
    upd.add_update_hook(session, profile.id, "pre-apply", "#!/bin/sh\n# new")
    session.flush()
    fetched = upd.get_update_profile(session, profile.id)
    assert fetched.content_hash is None


def test_render_not_found(session):
    with pytest.raises(KeyError, match="not found"):
        upd.render_update_config(session, "no-such-id")
