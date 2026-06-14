"""Unit tests for M42 — Desktop Integration Designer."""

from __future__ import annotations

import pytest

from osfabricum import desktopint as di
from osfabricum.db.models import Base
from osfabricum.db.seed_data import seed_mime_type_definitions

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_url(tmp_path):
    url = f"sqlite:///{tmp_path}/test_desktopint.db"
    from sqlalchemy import create_engine  # noqa: PLC0415

    engine = create_engine(url)
    Base.metadata.create_all(engine)

    from sqlalchemy.orm import Session  # noqa: PLC0415

    with Session(engine) as s:
        seed_mime_type_definitions(s)
        s.commit()

    engine.dispose()
    return url


@pytest.fixture()
def profile(db_url):
    return di.create_desktop_integration_profile("GNOME Desktop", db_url=db_url)


# ---------------------------------------------------------------------------
# MIME type reference
# ---------------------------------------------------------------------------


def test_list_mime_types_seeded(db_url):
    types = di.list_mime_types(db_url=db_url)
    assert len(types) == 21
    names = {m["name"] for m in types}
    assert "text/html" in names
    assert "application/pdf" in names
    assert "inode/directory" in names


def test_mime_types_ordered(db_url):
    types = di.list_mime_types(db_url=db_url)
    orders = [m["display_order"] for m in types]
    assert orders == sorted(orders)


def test_mime_types_have_descriptions(db_url):
    types = di.list_mime_types(db_url=db_url)
    for m in types:
        assert m["description"]


# ---------------------------------------------------------------------------
# Profile CRUD
# ---------------------------------------------------------------------------


def test_create_profile(db_url):
    p = di.create_desktop_integration_profile("KDE Plasma", db_url=db_url)
    assert p["name"] == "KDE Plasma"
    assert p["distribution_id"] is None
    assert p["xdg_data_dirs"] == []
    assert p["xdg_config_dirs"] == []
    assert p["content_hash"] is None
    assert p["id"]


def test_create_profile_with_xdg_dirs(db_url):
    p = di.create_desktop_integration_profile(
        "Custom",
        xdg_data_dirs=["/usr/share", "/usr/local/share"],
        xdg_config_dirs=["/etc/xdg"],
        db_url=db_url,
    )
    assert p["xdg_data_dirs"] == ["/usr/share", "/usr/local/share"]
    assert p["xdg_config_dirs"] == ["/etc/xdg"]


def test_create_duplicate_profile_raises(db_url, profile):
    with pytest.raises(ValueError, match="already exists"):
        di.create_desktop_integration_profile("GNOME Desktop", db_url=db_url)


def test_list_profiles(db_url, profile):
    di.create_desktop_integration_profile("KDE Plasma", db_url=db_url)
    profiles = di.list_desktop_integration_profiles(db_url=db_url)
    names = {p["name"] for p in profiles}
    assert "GNOME Desktop" in names
    assert "KDE Plasma" in names


def test_get_profile_not_found(db_url):
    with pytest.raises(ValueError, match="not found"):
        di.get_desktop_integration_profile("no-such-id", db_url=db_url)


def test_update_profile_xdg_dirs(db_url, profile):
    updated = di.update_desktop_integration_profile(
        profile["id"],
        xdg_data_dirs=["/usr/share"],
        db_url=db_url,
    )
    assert updated["xdg_data_dirs"] == ["/usr/share"]


def test_update_clears_cache(db_url, profile):
    di.add_mime_association(
        profile["id"], "text/html", "firefox.desktop", db_url=db_url
    )
    di.render_desktop_integration(profile["id"], db_url=db_url)
    updated = di.update_desktop_integration_profile(
        profile["id"], xdg_data_dirs=["/usr/share"], db_url=db_url
    )
    assert updated["content_hash"] is None
    assert updated["rendered_mimeapps"] is None


# ---------------------------------------------------------------------------
# MIME associations
# ---------------------------------------------------------------------------


def test_add_mime_association(db_url, profile):
    a = di.add_mime_association(
        profile["id"], "text/html", "firefox.desktop", db_url=db_url
    )
    assert a["mime_type"] == "text/html"
    assert a["desktop_file"] == "firefox.desktop"
    assert a["association_type"] == "default"
    assert a["priority"] == 0


def test_add_mime_association_added_type(db_url, profile):
    a = di.add_mime_association(
        profile["id"],
        "text/html",
        "chromium.desktop",
        association_type="added",
        priority=1,
        db_url=db_url,
    )
    assert a["association_type"] == "added"
    assert a["priority"] == 1


def test_add_mime_association_removed_type(db_url, profile):
    a = di.add_mime_association(
        profile["id"],
        "image/jpeg",
        "eog.desktop",
        association_type="removed",
        db_url=db_url,
    )
    assert a["association_type"] == "removed"


def test_add_duplicate_mime_assoc_raises(db_url, profile):
    di.add_mime_association(
        profile["id"], "text/html", "firefox.desktop", db_url=db_url
    )
    with pytest.raises(ValueError, match="already exists"):
        di.add_mime_association(
            profile["id"], "text/html", "firefox.desktop", db_url=db_url
        )


def test_add_mime_assoc_invalid_type(db_url, profile):
    with pytest.raises(ValueError, match="unknown association_type"):
        di.add_mime_association(
            profile["id"],
            "text/html",
            "foo.desktop",
            association_type="bogus",
            db_url=db_url,
        )


def test_add_mime_assoc_nonexistent_profile(db_url):
    with pytest.raises(ValueError, match="not found"):
        di.add_mime_association("bad-id", "text/html", "foo.desktop", db_url=db_url)


def test_get_profile_includes_assocs(db_url, profile):
    di.add_mime_association(
        profile["id"], "text/html", "firefox.desktop", db_url=db_url
    )
    di.add_mime_association(
        profile["id"], "application/pdf", "evince.desktop", db_url=db_url
    )
    detail = di.get_desktop_integration_profile(profile["id"], db_url=db_url)
    mime_types = {a["mime_type"] for a in detail["mime_associations"]}
    assert "text/html" in mime_types
    assert "application/pdf" in mime_types


# ---------------------------------------------------------------------------
# Autostart entries
# ---------------------------------------------------------------------------


def test_add_autostart_entry(db_url, profile):
    e = di.add_autostart_entry(
        profile["id"], "nm-applet", "/usr/bin/nm-applet", db_url=db_url
    )
    assert e["name"] == "nm-applet"
    assert e["exec_cmd"] == "/usr/bin/nm-applet"
    assert e["condition"] == "always"
    assert e["is_enabled"] is True
    assert "[Desktop Entry]" in e["desktop_entry"]


def test_autostart_desktop_entry_generated(db_url, profile):
    e = di.add_autostart_entry(
        profile["id"],
        "update-notifier",
        "/usr/bin/update-notifier",
        comment="Update notifier",
        condition="graphical",
        db_url=db_url,
    )
    entry = e["desktop_entry"]
    assert "Name=update-notifier" in entry
    assert "Exec=/usr/bin/update-notifier" in entry
    assert "Comment=Update notifier" in entry


def test_autostart_wayland_condition(db_url, profile):
    e = di.add_autostart_entry(
        profile["id"], "waybar", "waybar", condition="wayland", db_url=db_url
    )
    assert "OnlyShowIn=Wayland;" in e["desktop_entry"]


def test_autostart_x11_condition(db_url, profile):
    e = di.add_autostart_entry(
        profile["id"], "tray-icon", "tray-icon", condition="x11", db_url=db_url
    )
    assert "OnlyShowIn=X11;" in e["desktop_entry"]


def test_add_duplicate_autostart_raises(db_url, profile):
    di.add_autostart_entry(
        profile["id"], "nm-applet", "/usr/bin/nm-applet", db_url=db_url
    )
    with pytest.raises(ValueError, match="already exists"):
        di.add_autostart_entry(
            profile["id"], "nm-applet", "/usr/bin/nm-applet", db_url=db_url
        )


def test_add_autostart_invalid_condition(db_url, profile):
    with pytest.raises(ValueError, match="unknown condition"):
        di.add_autostart_entry(
            profile["id"], "foo", "foo", condition="never", db_url=db_url
        )


def test_add_autostart_nonexistent_profile(db_url):
    with pytest.raises(ValueError, match="not found"):
        di.add_autostart_entry("bad-id", "foo", "foo", db_url=db_url)


def test_get_profile_includes_autostart(db_url, profile):
    di.add_autostart_entry(
        profile["id"], "nm-applet", "/usr/bin/nm-applet", db_url=db_url
    )
    detail = di.get_desktop_integration_profile(profile["id"], db_url=db_url)
    names = {e["name"] for e in detail["autostart_entries"]}
    assert "nm-applet" in names


# ---------------------------------------------------------------------------
# XDG user directories
# ---------------------------------------------------------------------------


def test_set_user_dir(db_url, profile):
    d = di.set_user_dir(profile["id"], "DOWNLOAD", "Downloads", db_url=db_url)
    assert d["dir_name"] == "DOWNLOAD"
    assert d["path"] == "Downloads"


def test_set_user_dir_upsert(db_url, profile):
    di.set_user_dir(profile["id"], "DOWNLOAD", "Downloads", db_url=db_url)
    d2 = di.set_user_dir(profile["id"], "DOWNLOAD", "Téléchargements", db_url=db_url)
    assert d2["path"] == "Téléchargements"
    detail = di.get_desktop_integration_profile(profile["id"], db_url=db_url)
    dirs = {d["dir_name"]: d["path"] for d in detail["user_dirs"]}
    assert dirs["DOWNLOAD"] == "Téléchargements"


def test_set_user_dir_invalid_name(db_url, profile):
    with pytest.raises(ValueError, match="unknown XDG dir"):
        di.set_user_dir(profile["id"], "INVALID", "/home", db_url=db_url)


def test_set_user_dir_nonexistent_profile(db_url):
    with pytest.raises(ValueError, match="not found"):
        di.set_user_dir("bad-id", "DOWNLOAD", "Downloads", db_url=db_url)


def test_get_profile_includes_user_dirs(db_url, profile):
    di.set_user_dir(profile["id"], "DOCUMENTS", "Documents", db_url=db_url)
    di.set_user_dir(profile["id"], "PICTURES", "Images", db_url=db_url)
    detail = di.get_desktop_integration_profile(profile["id"], db_url=db_url)
    dirs = {d["dir_name"]: d["path"] for d in detail["user_dirs"]}
    assert dirs["DOCUMENTS"] == "Documents"
    assert dirs["PICTURES"] == "Images"


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


def _setup_full_profile(profile_id: str, db_url: str) -> None:
    di.add_mime_association(
        profile_id, "text/html", "firefox.desktop", association_type="default", db_url=db_url
    )
    di.add_mime_association(
        profile_id, "text/html", "chromium.desktop", association_type="added", priority=1, db_url=db_url
    )
    di.add_mime_association(
        profile_id, "application/pdf", "evince.desktop", db_url=db_url
    )
    di.add_autostart_entry(
        profile_id, "nm-applet", "/usr/bin/nm-applet", condition="graphical", db_url=db_url
    )
    di.set_user_dir(profile_id, "DOWNLOAD", "Downloads", db_url=db_url)
    di.set_user_dir(profile_id, "DOCUMENTS", "Documents", db_url=db_url)


def test_render_basic(db_url, profile):
    _setup_full_profile(profile["id"], db_url)
    result = di.render_desktop_integration(profile["id"], db_url=db_url)
    assert result["content_hash"].startswith("sha256:")
    assert result["association_count"] == 3
    assert result["autostart_count"] == 1
    assert result["user_dir_count"] == 2


def test_render_mimeapps_default_section(db_url, profile):
    _setup_full_profile(profile["id"], db_url)
    result = di.render_desktop_integration(profile["id"], db_url=db_url)
    mimeapps = result["rendered_mimeapps"]
    assert "[Default Applications]" in mimeapps
    assert "text/html=firefox.desktop;" in mimeapps
    assert "application/pdf=evince.desktop;" in mimeapps


def test_render_mimeapps_added_section(db_url, profile):
    _setup_full_profile(profile["id"], db_url)
    result = di.render_desktop_integration(profile["id"], db_url=db_url)
    mimeapps = result["rendered_mimeapps"]
    assert "[Added Associations]" in mimeapps
    assert "chromium.desktop" in mimeapps


def test_render_user_dirs_defaults(db_url, profile):
    _setup_full_profile(profile["id"], db_url)
    result = di.render_desktop_integration(profile["id"], db_url=db_url)
    user_dirs = result["rendered_user_dirs"]
    assert "DOWNLOAD=Downloads" in user_dirs
    assert "DOCUMENTS=Documents" in user_dirs
    assert "MUSIC=Music" in user_dirs  # uses fallback default


def test_render_user_dirs_all_dirs_present(db_url, profile):
    result = di.render_desktop_integration(profile["id"], db_url=db_url)
    user_dirs = result["rendered_user_dirs"]
    for dir_name in ("DESKTOP", "DOWNLOAD", "DOCUMENTS", "MUSIC", "PICTURES", "VIDEOS", "TEMPLATES", "PUBLICSHARE"):
        assert dir_name + "=" in user_dirs


def test_render_deterministic(db_url, profile):
    _setup_full_profile(profile["id"], db_url)
    r1 = di.render_desktop_integration(profile["id"], db_url=db_url)
    r2 = di.render_desktop_integration(profile["id"], db_url=db_url)
    assert r1["content_hash"] == r2["content_hash"]


def test_render_stored_on_profile(db_url, profile):
    _setup_full_profile(profile["id"], db_url)
    di.render_desktop_integration(profile["id"], db_url=db_url)
    detail = di.get_desktop_integration_profile(profile["id"], db_url=db_url)
    assert detail["content_hash"] is not None
    assert detail["rendered_at"] is not None
    assert "[Default Applications]" in (detail["rendered_mimeapps"] or "")
    assert "DOWNLOAD=" in (detail["rendered_user_dirs"] or "")


def test_render_empty_profile(db_url, profile):
    result = di.render_desktop_integration(profile["id"], db_url=db_url)
    assert result["association_count"] == 0
    assert result["content_hash"].startswith("sha256:")
    assert "DOWNLOAD=" in result["rendered_user_dirs"]


def test_render_nonexistent_profile(db_url):
    with pytest.raises(ValueError, match="not found"):
        di.render_desktop_integration("bad-id", db_url=db_url)


def test_render_removed_section(db_url, profile):
    di.add_mime_association(
        profile["id"], "image/jpeg", "gimp.desktop",
        association_type="removed", db_url=db_url
    )
    result = di.render_desktop_integration(profile["id"], db_url=db_url)
    assert "[Removed Associations]" in result["rendered_mimeapps"]
    assert "image/jpeg=gimp.desktop;" in result["rendered_mimeapps"]


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


def test_valid_association_types():
    assert di.VALID_ASSOCIATION_TYPES == {"default", "added", "removed"}


def test_valid_conditions():
    assert di.VALID_CONDITIONS == {"always", "graphical", "wayland", "x11"}


def test_valid_xdg_dirs():
    expected = {
        "DESKTOP", "DOWNLOAD", "DOCUMENTS", "MUSIC",
        "PICTURES", "VIDEOS", "TEMPLATES", "PUBLICSHARE",
    }
    assert di.VALID_XDG_DIRS == expected


def test_default_user_dirs_complete():
    assert len(di.DEFAULT_USER_DIRS) == 8
    assert di.DEFAULT_USER_DIRS["DOWNLOAD"] == "Downloads"
    assert di.DEFAULT_USER_DIRS["PUBLICSHARE"] == "Public"
