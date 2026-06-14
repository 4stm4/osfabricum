"""Unit tests for M50 — SDK / dev-shell export designer."""

from __future__ import annotations

import pytest

from osfabricum import sdk
from osfabricum.db.models import Base
from osfabricum.db.seed_data import seed_sdk_export_kinds


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_engine(tmp_path):
    from sqlalchemy import create_engine

    url = f"sqlite:///{tmp_path}/test_sdk.db"
    engine = create_engine(url)
    Base.metadata.create_all(engine)

    from sqlalchemy.orm import Session

    with Session(engine) as s:
        seed_sdk_export_kinds(s)
        s.commit()

    return engine


@pytest.fixture()
def session(db_engine):
    from sqlalchemy.orm import Session

    with Session(db_engine) as s:
        yield s


@pytest.fixture()
def profile(session):
    p = sdk.create_sdk_profile(session, "default-sdk")
    session.commit()
    return p


# ---------------------------------------------------------------------------
# Export kinds
# ---------------------------------------------------------------------------


def test_export_kinds_seeded(session):
    kinds = sdk.list_sdk_export_kinds(session)
    assert len(kinds) == 5


def test_export_kinds_ordered(session):
    kinds = sdk.list_sdk_export_kinds(session)
    orders = [k.display_order for k in kinds]
    assert orders == sorted(orders)


def test_export_kinds_values(session):
    kinds = {k.kind for k in sdk.list_sdk_export_kinds(session)}
    assert kinds == {"pip", "conda", "nix", "shell-env", "docker"}


def test_export_kinds_have_labels(session):
    kinds = sdk.list_sdk_export_kinds(session)
    for k in kinds:
        assert k.label
        assert k.description


def test_export_kinds_seed_idempotent(session):
    count = seed_sdk_export_kinds(session)
    assert count == 0


# ---------------------------------------------------------------------------
# Profile CRUD
# ---------------------------------------------------------------------------


def test_create_profile_defaults(profile):
    assert profile.name == "default-sdk"
    assert profile.export_format == "shell-env"
    assert profile.python_version == "3.11"
    assert profile.include_debug_symbols is False
    assert profile.content_hash is None
    assert profile.distribution_id is None


def test_create_profile_all_formats(session):
    for i, fmt in enumerate(sdk.VALID_EXPORT_FORMATS):
        p = sdk.create_sdk_profile(session, f"fmt-{i}", export_format=fmt)
        assert p.export_format == fmt


def test_create_profile_invalid_format(session):
    with pytest.raises(ValueError, match="export_format"):
        sdk.create_sdk_profile(session, "bad", export_format="rpm")


def test_create_profile_duplicate(session, profile):
    with pytest.raises(ValueError, match="already exists"):
        sdk.create_sdk_profile(session, "default-sdk")


def test_create_profile_with_options(session):
    p = sdk.create_sdk_profile(
        session, "full-sdk",
        export_format="pip",
        python_version="3.12",
        include_debug_symbols=True,
        description="Full debug SDK",
    )
    session.commit()
    assert p.python_version == "3.12"
    assert p.include_debug_symbols is True
    assert p.description == "Full debug SDK"


def test_list_profiles(session, profile):
    sdk.create_sdk_profile(session, "second-sdk")
    session.commit()
    names = [p.name for p in sdk.list_sdk_profiles(session)]
    assert "default-sdk" in names
    assert "second-sdk" in names


def test_list_profiles_by_distribution(session):
    sdk.create_sdk_profile(session, "dist-sdk", distribution_id="dist-1")
    sdk.create_sdk_profile(session, "global-sdk")
    session.commit()
    dist_profiles = sdk.list_sdk_profiles(session, distribution_id="dist-1")
    assert len(dist_profiles) == 1
    assert dist_profiles[0].name == "dist-sdk"


def test_get_profile(session, profile):
    fetched = sdk.get_sdk_profile(session, profile.id)
    assert fetched.id == profile.id


def test_get_profile_not_found(session):
    with pytest.raises(KeyError, match="not found"):
        sdk.get_sdk_profile(session, "no-such-id")


def test_update_profile(session, profile):
    sdk.update_sdk_profile(
        session, profile.id,
        export_format="pip",
        python_version="3.12",
        include_debug_symbols=True,
    )
    session.commit()
    p = sdk.get_sdk_profile(session, profile.id)
    assert p.export_format == "pip"
    assert p.python_version == "3.12"
    assert p.include_debug_symbols is True


def test_update_profile_clears_hash(session, profile):
    profile.content_hash = "sha256:abc"
    session.flush()
    sdk.update_sdk_profile(session, profile.id, description="updated")
    session.commit()
    p = sdk.get_sdk_profile(session, profile.id)
    assert p.content_hash is None


def test_update_profile_not_found(session):
    with pytest.raises(KeyError, match="not found"):
        sdk.update_sdk_profile(session, "no-id", description="x")


def test_update_profile_invalid_format(session, profile):
    with pytest.raises(ValueError, match="export_format"):
        sdk.update_sdk_profile(session, profile.id, export_format="flatpak")


# ---------------------------------------------------------------------------
# SDK variables
# ---------------------------------------------------------------------------


def test_set_variable(session, profile):
    v = sdk.set_sdk_variable(session, profile.id, "ARCH", "arm64")
    session.commit()
    assert v.key == "ARCH"
    assert v.value == "arm64"
    assert v.is_secret is False


def test_set_variable_upsert(session, profile):
    sdk.set_sdk_variable(session, profile.id, "ARCH", "x86_64")
    session.commit()
    sdk.set_sdk_variable(session, profile.id, "ARCH", "arm64")
    session.commit()
    variables = sdk.list_sdk_variables(session, profile.id)
    assert len(variables) == 1
    assert variables[0].value == "arm64"


def test_set_variable_secret(session, profile):
    v = sdk.set_sdk_variable(
        session, profile.id, "API_TOKEN", "s3cr3t", is_secret=True
    )
    session.commit()
    assert v.is_secret is True


def test_set_variable_with_description(session, profile):
    v = sdk.set_sdk_variable(
        session, profile.id, "CROSS_COMPILE", "aarch64-linux-gnu-",
        description="Cross-compiler prefix"
    )
    session.commit()
    assert v.description == "Cross-compiler prefix"


def test_set_variable_clears_hash(session, profile):
    sdk.render_sdk_export(session, profile.id)
    session.flush()
    sdk.set_sdk_variable(session, profile.id, "NEW_VAR", "value")
    session.flush()
    p = sdk.get_sdk_profile(session, profile.id)
    assert p.content_hash is None


def test_list_variables_ordered(session, profile):
    for key in ("Z_VAR", "A_VAR", "M_VAR"):
        sdk.set_sdk_variable(session, profile.id, key, "val")
    session.commit()
    keys = [v.key for v in sdk.list_sdk_variables(session, profile.id)]
    assert keys == sorted(keys)


def test_list_variables_not_found(session):
    with pytest.raises(KeyError, match="not found"):
        sdk.list_sdk_variables(session, "no-id")


def test_set_variable_not_found_profile(session):
    with pytest.raises(KeyError, match="not found"):
        sdk.set_sdk_variable(session, "no-id", "K", "V")


# ---------------------------------------------------------------------------
# Render — basic
# ---------------------------------------------------------------------------


def test_render_returns_hash(session, profile):
    p = sdk.render_sdk_export(session, profile.id)
    assert p.content_hash is not None
    assert p.content_hash.startswith("sha256:")


def test_render_returns_scripts(session, profile):
    p = sdk.render_sdk_export(session, profile.id)
    assert p.rendered_setup_script is not None
    assert p.rendered_env_script is not None


def test_render_setup_has_shebang(session, profile):
    p = sdk.render_sdk_export(session, profile.id)
    assert p.rendered_setup_script.startswith("#!/usr/bin/env bash")


def test_render_env_has_shebang(session, profile):
    p = sdk.render_sdk_export(session, profile.id)
    assert p.rendered_env_script.startswith("#!/usr/bin/env bash")


def test_render_not_found(session):
    with pytest.raises(KeyError, match="not found"):
        sdk.render_sdk_export(session, "no-such-id")


# ---------------------------------------------------------------------------
# Render — format-specific content
# ---------------------------------------------------------------------------


def test_render_pip_format(session):
    p = sdk.create_sdk_profile(session, "pip-sdk", export_format="pip")
    session.flush()
    p = sdk.render_sdk_export(session, p.id)
    assert "venv" in p.rendered_setup_script
    assert "pip install" in p.rendered_setup_script


def test_render_conda_format(session):
    p = sdk.create_sdk_profile(session, "conda-sdk", export_format="conda")
    session.flush()
    p = sdk.render_sdk_export(session, p.id)
    assert "conda" in p.rendered_setup_script.lower()
    assert "environment.yml" in p.rendered_setup_script


def test_render_nix_format(session):
    p = sdk.create_sdk_profile(session, "nix-sdk", export_format="nix")
    session.flush()
    p = sdk.render_sdk_export(session, p.id)
    assert "nix" in p.rendered_setup_script.lower()


def test_render_shell_env_format(session, profile):
    p = sdk.render_sdk_export(session, profile.id)
    assert "Shell Environment" in p.rendered_setup_script


def test_render_docker_format(session):
    p = sdk.create_sdk_profile(session, "docker-sdk", export_format="docker")
    session.flush()
    p = sdk.render_sdk_export(session, p.id)
    assert "FROM python:" in p.rendered_setup_script


def test_render_docker_debug_symbols(session):
    p = sdk.create_sdk_profile(
        session, "docker-debug", export_format="docker", include_debug_symbols=True
    )
    session.flush()
    p = sdk.render_sdk_export(session, p.id)
    assert "python3-dbg" in p.rendered_setup_script


def test_render_pip_python_version(session):
    p = sdk.create_sdk_profile(
        session, "pip312", export_format="pip", python_version="3.12"
    )
    session.flush()
    p = sdk.render_sdk_export(session, p.id)
    assert "3.12" in p.rendered_setup_script


# ---------------------------------------------------------------------------
# Render — variables in output
# ---------------------------------------------------------------------------


def test_render_includes_variables(session, profile):
    sdk.set_sdk_variable(session, profile.id, "ARCH", "arm64")
    session.flush()
    p = sdk.render_sdk_export(session, profile.id)
    assert "ARCH" in p.rendered_setup_script
    assert "arm64" in p.rendered_setup_script


def test_render_env_exports_non_secret(session, profile):
    sdk.set_sdk_variable(session, profile.id, "CROSS_COMPILE", "aarch64-linux-gnu-")
    session.flush()
    p = sdk.render_sdk_export(session, profile.id)
    assert "export CROSS_COMPILE=" in p.rendered_env_script
    assert "aarch64-linux-gnu-" in p.rendered_env_script


def test_render_env_masks_secrets(session, profile):
    sdk.set_sdk_variable(session, profile.id, "TOKEN", "s3cr3t", is_secret=True)
    session.flush()
    p = sdk.render_sdk_export(session, profile.id)
    assert "s3cr3t" not in p.rendered_env_script
    assert "TOKEN" in p.rendered_env_script


def test_render_env_contains_profile_export(session, profile):
    p = sdk.render_sdk_export(session, profile.id)
    assert "OSF_SDK_PROFILE" in p.rendered_env_script
    assert "OSF_SDK_FORMAT" in p.rendered_env_script


# ---------------------------------------------------------------------------
# Render — determinism and caching
# ---------------------------------------------------------------------------


def test_render_deterministic(session, profile):
    p1 = sdk.render_sdk_export(session, profile.id)
    h1 = p1.content_hash
    p2 = sdk.render_sdk_export(session, profile.id)
    assert p2.content_hash == h1


def test_render_stored(session, profile):
    p = sdk.render_sdk_export(session, profile.id)
    session.commit()
    fetched = sdk.get_sdk_profile(session, profile.id)
    assert fetched.content_hash == p.content_hash


def test_render_hash_changes_on_new_variable(session, profile):
    p1 = sdk.render_sdk_export(session, profile.id)
    h1 = p1.content_hash
    sdk.set_sdk_variable(session, profile.id, "NEW_VAR", "new_val")
    session.flush()
    p2 = sdk.render_sdk_export(session, profile.id)
    assert p2.content_hash != h1


def test_render_hash_changes_on_format_update(session, profile):
    p1 = sdk.render_sdk_export(session, profile.id)
    h1 = p1.content_hash
    sdk.update_sdk_profile(session, profile.id, export_format="pip")
    session.flush()
    p2 = sdk.render_sdk_export(session, profile.id)
    assert p2.content_hash != h1
