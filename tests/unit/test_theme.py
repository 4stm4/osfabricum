"""Unit tests for M43 — Themes / Icons / Fonts Designer."""

from __future__ import annotations

import pytest

from osfabricum import theme as th
from osfabricum.db.models import Base
from osfabricum.db.seed_data import seed_theme_asset_kinds

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_url(tmp_path):
    url = f"sqlite:///{tmp_path}/test_theme.db"
    from sqlalchemy import create_engine  # noqa: PLC0415

    engine = create_engine(url)
    Base.metadata.create_all(engine)

    from sqlalchemy.orm import Session  # noqa: PLC0415

    with Session(engine) as s:
        seed_theme_asset_kinds(s)
        s.commit()

    engine.dispose()
    return url


@pytest.fixture()
def profile(db_url):
    return th.create_theme_profile("GNOME Light", db_url=db_url)


@pytest.fixture()
def dark_profile(db_url):
    return th.create_theme_profile(
        "GNOME Dark",
        gtk_theme="Adwaita-dark",
        icon_theme="Papirus-Dark",
        dark_mode=True,
        font_default="Cantarell",
        font_monospace="Source Code Pro",
        font_size=12,
        db_url=db_url,
    )


# ---------------------------------------------------------------------------
# Asset kinds
# ---------------------------------------------------------------------------


def test_list_asset_kinds_seeded(db_url):
    kinds = th.list_theme_asset_kinds(db_url=db_url)
    assert len(kinds) == 6
    names = {k["name"] for k in kinds}
    assert "gtk-theme" in names
    assert "icon-theme" in names
    assert "cursor-theme" in names
    assert "sound-theme" in names
    assert "font-face" in names
    assert "wallpaper" in names


def test_asset_kinds_ordered(db_url):
    kinds = th.list_theme_asset_kinds(db_url=db_url)
    orders = [k["display_order"] for k in kinds]
    assert orders == sorted(orders)


# ---------------------------------------------------------------------------
# Profile CRUD
# ---------------------------------------------------------------------------


def test_create_profile_defaults(db_url):
    p = th.create_theme_profile("Default", db_url=db_url)
    assert p["gtk_theme"] == "Adwaita"
    assert p["icon_theme"] == "Adwaita"
    assert p["cursor_theme"] == "Adwaita"
    assert p["sound_theme"] == "freedesktop"
    assert p["dark_mode"] is False
    assert p["font_default"] == "Sans"
    assert p["font_monospace"] == "Monospace"
    assert p["font_document"] == "Sans"
    assert p["font_size"] == 11
    assert p["cursor_size"] == 24
    assert p["scaling_factor"] == 1.0
    assert p["content_hash"] is None
    assert p["id"]


def test_create_profile_custom(db_url, dark_profile):
    assert dark_profile["gtk_theme"] == "Adwaita-dark"
    assert dark_profile["icon_theme"] == "Papirus-Dark"
    assert dark_profile["dark_mode"] is True
    assert dark_profile["font_default"] == "Cantarell"
    assert dark_profile["font_monospace"] == "Source Code Pro"
    assert dark_profile["font_size"] == 12


def test_create_duplicate_raises(db_url, profile):
    with pytest.raises(ValueError, match="already exists"):
        th.create_theme_profile("GNOME Light", db_url=db_url)


def test_list_profiles(db_url, profile, dark_profile):
    profiles = th.list_theme_profiles(db_url=db_url)
    names = {p["name"] for p in profiles}
    assert "GNOME Light" in names
    assert "GNOME Dark" in names


def test_get_profile_not_found(db_url):
    with pytest.raises(ValueError, match="not found"):
        th.get_theme_profile("no-such", db_url=db_url)


def test_update_gtk_theme(db_url, profile):
    updated = th.update_theme_profile(
        profile["id"], gtk_theme="Breeze", db_url=db_url
    )
    assert updated["gtk_theme"] == "Breeze"
    assert updated["icon_theme"] == "Adwaita"  # unchanged


def test_update_dark_mode(db_url, profile):
    updated = th.update_theme_profile(
        profile["id"], dark_mode=True, db_url=db_url
    )
    assert updated["dark_mode"] is True


def test_update_font_fields(db_url, profile):
    updated = th.update_theme_profile(
        profile["id"],
        font_default="Cantarell",
        font_monospace="Fira Code",
        font_size=13,
        db_url=db_url,
    )
    assert updated["font_default"] == "Cantarell"
    assert updated["font_monospace"] == "Fira Code"
    assert updated["font_size"] == 13


def test_update_scaling(db_url, profile):
    updated = th.update_theme_profile(
        profile["id"], scaling_factor=2.0, db_url=db_url
    )
    assert updated["scaling_factor"] == 2.0


def test_update_clears_cache(db_url, profile):
    th.render_theme_config(profile["id"], db_url=db_url)
    updated = th.update_theme_profile(
        profile["id"], gtk_theme="Breeze", db_url=db_url
    )
    assert updated["content_hash"] is None
    assert updated["rendered_gsettings"] is None
    assert updated["rendered_gtk_ini"] is None


def test_update_nonexistent_raises(db_url):
    with pytest.raises(ValueError, match="not found"):
        th.update_theme_profile("bad-id", gtk_theme="X", db_url=db_url)


# ---------------------------------------------------------------------------
# Theme packages
# ---------------------------------------------------------------------------


def test_add_gtk_theme_package(db_url, profile):
    pkg = th.add_theme_package(
        profile["id"], "gtk-theme", "arc-theme", db_url=db_url
    )
    assert pkg["asset_kind"] == "gtk-theme"
    assert pkg["package_name"] == "arc-theme"
    assert pkg["is_default"] is False


def test_add_default_package(db_url, profile):
    pkg = th.add_theme_package(
        profile["id"], "icon-theme", "papirus-icon-theme",
        is_default=True, db_url=db_url
    )
    assert pkg["is_default"] is True


def test_add_package_with_version(db_url, profile):
    pkg = th.add_theme_package(
        profile["id"], "font-face", "fonts-cantarell",
        version_constraint=">=0.301", db_url=db_url
    )
    assert pkg["version_constraint"] == ">=0.301"


def test_add_package_all_kinds(db_url, profile):
    for kind in th.VALID_ASSET_KINDS:
        th.add_theme_package(
            profile["id"], kind, f"pkg-{kind}", db_url=db_url
        )
    detail = th.get_theme_profile(profile["id"], db_url=db_url)
    kinds_added = {p["asset_kind"] for p in detail["packages"]}
    assert kinds_added == th.VALID_ASSET_KINDS


def test_add_duplicate_package_raises(db_url, profile):
    th.add_theme_package(profile["id"], "gtk-theme", "arc-theme", db_url=db_url)
    with pytest.raises(ValueError, match="already in profile"):
        th.add_theme_package(profile["id"], "gtk-theme", "arc-theme", db_url=db_url)


def test_add_invalid_kind_raises(db_url, profile):
    with pytest.raises(ValueError, match="unknown asset_kind"):
        th.add_theme_package(profile["id"], "bad-kind", "foo", db_url=db_url)


def test_add_package_nonexistent_profile(db_url):
    with pytest.raises(ValueError, match="not found"):
        th.add_theme_package("bad-id", "gtk-theme", "foo", db_url=db_url)


def test_get_profile_includes_packages(db_url, profile):
    th.add_theme_package(profile["id"], "gtk-theme", "arc-theme", db_url=db_url)
    th.add_theme_package(profile["id"], "icon-theme", "papirus-icon-theme", db_url=db_url)
    detail = th.get_theme_profile(profile["id"], db_url=db_url)
    pkg_names = {p["package_name"] for p in detail["packages"]}
    assert "arc-theme" in pkg_names
    assert "papirus-icon-theme" in pkg_names


# ---------------------------------------------------------------------------
# GSettings overrides
# ---------------------------------------------------------------------------


def test_set_gsettings_override(db_url, profile):
    o = th.set_gsettings_override(
        profile["id"],
        "org/gnome/desktop/wm/preferences",
        "num-workspaces",
        "4",
        description="Number of virtual desktops",
        db_url=db_url,
    )
    assert o["schema"] == "org/gnome/desktop/wm/preferences"
    assert o["key"] == "num-workspaces"
    assert o["value"] == "4"
    assert o["description"] == "Number of virtual desktops"


def test_gsettings_upsert(db_url, profile):
    th.set_gsettings_override(
        profile["id"], "org/gnome/desktop/interface", "enable-animations", "true",
        db_url=db_url
    )
    o2 = th.set_gsettings_override(
        profile["id"], "org/gnome/desktop/interface", "enable-animations", "false",
        db_url=db_url
    )
    assert o2["value"] == "false"
    detail = th.get_theme_profile(profile["id"], db_url=db_url)
    vals = {o["key"]: o["value"] for o in detail["gsettings"]}
    assert vals["enable-animations"] == "false"


def test_gsettings_nonexistent_profile(db_url):
    with pytest.raises(ValueError, match="not found"):
        th.set_gsettings_override("bad-id", "org/foo", "bar", "baz", db_url=db_url)


def test_get_profile_includes_gsettings(db_url, profile):
    th.set_gsettings_override(
        profile["id"], "org/gnome/desktop/wm/preferences", "num-workspaces", "4",
        db_url=db_url
    )
    th.set_gsettings_override(
        profile["id"], "org/gnome/mutter", "dynamic-workspaces", "false",
        db_url=db_url
    )
    detail = th.get_theme_profile(profile["id"], db_url=db_url)
    assert len(detail["gsettings"]) == 2
    schemas = {o["schema"] for o in detail["gsettings"]}
    assert "org/gnome/desktop/wm/preferences" in schemas


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


def _setup_full_profile(profile_id: str, db_url: str) -> None:
    th.add_theme_package(profile_id, "gtk-theme", "arc-theme", db_url=db_url)
    th.add_theme_package(profile_id, "icon-theme", "papirus-icon-theme", db_url=db_url)
    th.add_theme_package(profile_id, "font-face", "fonts-cantarell", db_url=db_url)
    th.set_gsettings_override(
        profile_id, "org/gnome/desktop/wm/preferences", "num-workspaces", "4",
        db_url=db_url
    )
    th.set_gsettings_override(
        profile_id, "org/gnome/mutter", "dynamic-workspaces", "false",
        db_url=db_url
    )


def test_render_basic(db_url, profile):
    _setup_full_profile(profile["id"], db_url)
    result = th.render_theme_config(profile["id"], db_url=db_url)
    assert result["content_hash"].startswith("sha256:")
    assert result["package_count"] == 3
    assert result["gsettings_override_count"] == 2


def test_render_gsettings_interface_section(db_url, profile):
    result = th.render_theme_config(profile["id"], db_url=db_url)
    gs = result["rendered_gsettings"]
    assert "[org/gnome/desktop/interface]" in gs
    assert "gtk-theme='Adwaita'" in gs
    assert "icon-theme='Adwaita'" in gs
    assert "cursor-theme='Adwaita'" in gs
    assert "font-name='Sans 11'" in gs
    assert "monospace-font-name='Monospace 11'" in gs
    assert "text-scaling-factor=1.00" in gs
    assert "color-scheme='default'" in gs


def test_render_dark_mode_gsettings(db_url, dark_profile):
    result = th.render_theme_config(dark_profile["id"], db_url=db_url)
    gs = result["rendered_gsettings"]
    assert "color-scheme='prefer-dark'" in gs
    assert "gtk-theme='Adwaita-dark'" in gs


def test_render_extra_gsettings_sections(db_url, profile):
    _setup_full_profile(profile["id"], db_url)
    result = th.render_theme_config(profile["id"], db_url=db_url)
    gs = result["rendered_gsettings"]
    assert "[org/gnome/desktop/wm/preferences]" in gs
    assert "num-workspaces=4" in gs
    assert "[org/gnome/mutter]" in gs
    assert "dynamic-workspaces=false" in gs


def test_render_gtk_ini(db_url, profile):
    result = th.render_theme_config(profile["id"], db_url=db_url)
    ini = result["rendered_gtk_ini"]
    assert "[Settings]" in ini
    assert "gtk-theme-name=Adwaita" in ini
    assert "gtk-icon-theme-name=Adwaita" in ini
    assert "gtk-cursor-theme-name=Adwaita" in ini
    assert "gtk-cursor-theme-size=24" in ini
    assert "gtk-font-name=Sans 11" in ini
    assert "gtk-application-prefer-dark-theme=false" in ini


def test_render_gtk_ini_dark(db_url, dark_profile):
    result = th.render_theme_config(dark_profile["id"], db_url=db_url)
    ini = result["rendered_gtk_ini"]
    assert "gtk-application-prefer-dark-theme=true" in ini
    assert "gtk-theme-name=Adwaita-dark" in ini


def test_render_non_default_sound_theme(db_url):
    p = th.create_theme_profile(
        "Yaru", gtk_theme="Yaru", icon_theme="Yaru",
        sound_theme="Yaru", db_url=db_url
    )
    result = th.render_theme_config(p["id"], db_url=db_url)
    gs = result["rendered_gsettings"]
    assert "[org/gnome/desktop/sound]" in gs
    assert "theme-name='Yaru'" in gs


def test_render_sound_theme_omitted_when_freedesktop(db_url, profile):
    result = th.render_theme_config(profile["id"], db_url=db_url)
    assert "[org/gnome/desktop/sound]" not in result["rendered_gsettings"]


def test_render_deterministic(db_url, profile):
    _setup_full_profile(profile["id"], db_url)
    r1 = th.render_theme_config(profile["id"], db_url=db_url)
    r2 = th.render_theme_config(profile["id"], db_url=db_url)
    assert r1["content_hash"] == r2["content_hash"]


def test_render_stored_on_profile(db_url, profile):
    th.render_theme_config(profile["id"], db_url=db_url)
    detail = th.get_theme_profile(profile["id"], db_url=db_url)
    assert detail["content_hash"] is not None
    assert detail["rendered_at"] is not None
    assert "[org/gnome/desktop/interface]" in (detail["rendered_gsettings"] or "")
    assert "[Settings]" in (detail["rendered_gtk_ini"] or "")


def test_render_nonexistent_profile(db_url):
    with pytest.raises(ValueError, match="not found"):
        th.render_theme_config("bad-id", db_url=db_url)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


def test_valid_asset_kinds():
    expected = {"gtk-theme", "icon-theme", "cursor-theme", "sound-theme", "font-face", "wallpaper"}
    assert th.VALID_ASSET_KINDS == expected
