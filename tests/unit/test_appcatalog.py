"""Unit tests for M41 — Application Catalog Designer."""

from __future__ import annotations

import pytest

from osfabricum import appcatalog as ac
from osfabricum.db.models import Base
from osfabricum.db.seed_data import seed_app_categories

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_url(tmp_path):
    url = f"sqlite:///{tmp_path}/test_appcatalog.db"
    from sqlalchemy import create_engine  # noqa: PLC0415

    engine = create_engine(url)
    Base.metadata.create_all(engine)

    from sqlalchemy.orm import Session  # noqa: PLC0415

    with Session(engine) as s:
        seed_app_categories(s)
        s.commit()

    engine.dispose()
    return url


@pytest.fixture()
def profile(db_url):
    return ac.create_catalog_profile(
        "Desktop Suite", distribution_id=None, db_url=db_url
    )


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------


def test_list_categories_seeded(db_url):
    cats = ac.list_app_categories(db_url=db_url)
    assert len(cats) == 11
    names = {c["name"] for c in cats}
    assert "productivity" in names
    assert "internet" in names
    assert "accessibility" in names


def test_categories_ordered(db_url):
    cats = ac.list_app_categories(db_url=db_url)
    orders = [c["display_order"] for c in cats]
    assert orders == sorted(orders)


# ---------------------------------------------------------------------------
# Profile CRUD
# ---------------------------------------------------------------------------


def test_create_catalog_profile(db_url):
    p = ac.create_catalog_profile("My Catalog", db_url=db_url)
    assert p["name"] == "My Catalog"
    assert p["distribution_id"] is None
    assert p["content_hash"] is None
    assert p["rendered_app_list"] is None
    assert p["id"]


def test_create_profile_with_description(db_url):
    p = ac.create_catalog_profile(
        "Described", description="A test catalog", db_url=db_url
    )
    assert p["description"] == "A test catalog"


def test_create_duplicate_profile_raises(db_url, profile):
    with pytest.raises(ValueError, match="already exists"):
        ac.create_catalog_profile("Desktop Suite", db_url=db_url)


def test_list_catalog_profiles(db_url, profile):
    ac.create_catalog_profile("Minimal", db_url=db_url)
    profiles = ac.list_catalog_profiles(db_url=db_url)
    names = {p["name"] for p in profiles}
    assert "Desktop Suite" in names
    assert "Minimal" in names


def test_get_catalog_profile_not_found(db_url):
    with pytest.raises(ValueError, match="not found"):
        ac.get_catalog_profile("nonexistent", db_url=db_url)


def test_update_catalog_profile(db_url, profile):
    updated = ac.update_catalog_profile(
        profile["id"], description="Updated desc", db_url=db_url
    )
    assert updated["description"] == "Updated desc"


def test_update_clears_cache(db_url, profile):
    # Add an app and render first
    ac.add_app(
        profile["id"], "firefox", "Firefox", "firefox",
        category_name="internet", db_url=db_url
    )
    rendered = ac.render_app_list(profile["id"], db_url=db_url)
    assert rendered["content_hash"]
    # Update should clear the cache
    updated = ac.update_catalog_profile(
        profile["id"], description="Changed", db_url=db_url
    )
    assert updated["content_hash"] is None
    assert updated["rendered_app_list"] is None


# ---------------------------------------------------------------------------
# Apps
# ---------------------------------------------------------------------------


def test_add_app_basic(db_url, profile):
    a = ac.add_app(
        profile["id"], "firefox", "Firefox Web Browser", "firefox",
        category_name="internet", db_url=db_url,
    )
    assert a["name"] == "firefox"
    assert a["package_name"] == "firefox"
    assert a["category_name"] == "internet"
    assert a["is_default_install"] is True
    assert a["is_optional"] is False


def test_add_app_optional(db_url, profile):
    a = ac.add_app(
        profile["id"], "vlc", "VLC", "vlc",
        category_name="multimedia",
        is_default_install=False,
        is_optional=True,
        db_url=db_url,
    )
    assert a["is_default_install"] is False
    assert a["is_optional"] is True


def test_add_app_with_tags(db_url, profile):
    a = ac.add_app(
        profile["id"], "gedit", "Text Editor", "gedit",
        category_name="productivity",
        tags=["editor", "text"],
        db_url=db_url,
    )
    assert "editor" in a["name"] or a["name"] == "gedit"


def test_add_duplicate_app_raises(db_url, profile):
    ac.add_app(profile["id"], "firefox", "Firefox", "firefox",
               category_name="internet", db_url=db_url)
    with pytest.raises(ValueError, match="already exists"):
        ac.add_app(profile["id"], "firefox", "Firefox2", "firefox2",
                   category_name="internet", db_url=db_url)


def test_add_app_invalid_category(db_url, profile):
    with pytest.raises(ValueError, match="unknown category"):
        ac.add_app(
            profile["id"], "foo", "Foo", "foo",
            category_name="nonexistent", db_url=db_url,
        )


def test_add_app_to_nonexistent_profile(db_url):
    with pytest.raises(ValueError, match="not found"):
        ac.add_app("bad-id", "foo", "Foo", "foo", db_url=db_url)


def test_get_profile_includes_apps(db_url, profile):
    ac.add_app(profile["id"], "firefox", "Firefox", "firefox",
               category_name="internet", db_url=db_url)
    ac.add_app(profile["id"], "gedit", "Gedit", "gedit",
               category_name="productivity", db_url=db_url)
    detail = ac.get_catalog_profile(profile["id"], db_url=db_url)
    app_names = {a["name"] for a in detail["apps"]}
    assert "firefox" in app_names
    assert "gedit" in app_names


# ---------------------------------------------------------------------------
# Groups
# ---------------------------------------------------------------------------


def test_add_group(db_url, profile):
    g = ac.add_group(
        profile["id"], "Core Apps",
        description="Essential applications",
        is_default=True,
        db_url=db_url,
    )
    assert g["name"] == "Core Apps"
    assert g["is_default"] is True


def test_add_duplicate_group_raises(db_url, profile):
    ac.add_group(profile["id"], "Core", db_url=db_url)
    with pytest.raises(ValueError, match="already exists"):
        ac.add_group(profile["id"], "Core", db_url=db_url)


def test_add_group_to_nonexistent_profile(db_url):
    with pytest.raises(ValueError, match="not found"):
        ac.add_group("bad-id", "Core", db_url=db_url)


def test_add_group_member(db_url, profile):
    ac.add_app(profile["id"], "firefox", "Firefox", "firefox",
               category_name="internet", db_url=db_url)
    ac.add_group(profile["id"], "Internet", db_url=db_url)
    m = ac.add_group_member(
        profile["id"], "Internet", "firefox", position=0, db_url=db_url
    )
    assert m["app_name"] == "firefox"
    assert m["group_name"] == "Internet"


def test_add_duplicate_member_raises(db_url, profile):
    ac.add_app(profile["id"], "firefox", "Firefox", "firefox",
               category_name="internet", db_url=db_url)
    ac.add_group(profile["id"], "Internet", db_url=db_url)
    ac.add_group_member(profile["id"], "Internet", "firefox", db_url=db_url)
    with pytest.raises(ValueError, match="already a member"):
        ac.add_group_member(profile["id"], "Internet", "firefox", db_url=db_url)


def test_add_member_nonexistent_group(db_url, profile):
    ac.add_app(profile["id"], "firefox", "Firefox", "firefox",
               category_name="internet", db_url=db_url)
    with pytest.raises(ValueError, match="not found"):
        ac.add_group_member(profile["id"], "NoGroup", "firefox", db_url=db_url)


def test_add_member_nonexistent_app(db_url, profile):
    ac.add_group(profile["id"], "Internet", db_url=db_url)
    with pytest.raises(ValueError, match="not found"):
        ac.add_group_member(profile["id"], "Internet", "noapp", db_url=db_url)


def test_get_profile_includes_groups(db_url, profile):
    ac.add_app(profile["id"], "firefox", "Firefox", "firefox",
               category_name="internet", db_url=db_url)
    ac.add_group(profile["id"], "Core", is_default=True, db_url=db_url)
    ac.add_group_member(profile["id"], "Core", "firefox", db_url=db_url)
    detail = ac.get_catalog_profile(profile["id"], db_url=db_url)
    assert len(detail["groups"]) == 1
    assert detail["groups"][0]["name"] == "Core"
    assert len(detail["groups"][0]["members"]) == 1
    assert detail["groups"][0]["members"][0]["app_name"] == "firefox"


# ---------------------------------------------------------------------------
# Default roles
# ---------------------------------------------------------------------------


def test_set_default_role(db_url, profile):
    r = ac.set_default_role(
        profile["id"], "web-browser", "firefox", "firefox", db_url=db_url
    )
    assert r["role"] == "web-browser"
    assert r["app_name"] == "firefox"
    assert r["package_name"] == "firefox"


def test_set_default_role_upsert(db_url, profile):
    ac.set_default_role(profile["id"], "web-browser", "firefox", "firefox", db_url=db_url)
    r2 = ac.set_default_role(
        profile["id"], "web-browser", "chromium", "chromium", db_url=db_url
    )
    assert r2["app_name"] == "chromium"
    detail = ac.get_catalog_profile(profile["id"], db_url=db_url)
    roles = {r["role"]: r["app_name"] for r in detail["default_roles"]}
    assert roles["web-browser"] == "chromium"


def test_set_invalid_role_raises(db_url, profile):
    with pytest.raises(ValueError, match="unknown role"):
        ac.set_default_role(
            profile["id"], "bad-role", "foo", "foo", db_url=db_url
        )


def test_set_role_nonexistent_profile(db_url):
    with pytest.raises(ValueError, match="not found"):
        ac.set_default_role("bad-id", "web-browser", "foo", "foo", db_url=db_url)


def test_get_profile_includes_roles(db_url, profile):
    ac.set_default_role(profile["id"], "web-browser", "firefox", "firefox", db_url=db_url)
    ac.set_default_role(profile["id"], "text-editor", "gedit", "gedit", db_url=db_url)
    detail = ac.get_catalog_profile(profile["id"], db_url=db_url)
    role_map = {r["role"]: r["app_name"] for r in detail["default_roles"]}
    assert role_map["web-browser"] == "firefox"
    assert role_map["text-editor"] == "gedit"


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


def _setup_full_catalog(profile_id: str, db_url: str) -> None:
    ac.add_app(profile_id, "firefox", "Firefox", "firefox",
               category_name="internet", tags=["web", "browser"], db_url=db_url)
    ac.add_app(profile_id, "gedit", "Text Editor", "gedit",
               category_name="productivity", is_optional=True, db_url=db_url)
    ac.add_group(profile_id, "Core", is_default=True, db_url=db_url)
    ac.add_group_member(profile_id, "Core", "firefox", position=0, db_url=db_url)
    ac.add_group_member(profile_id, "Core", "gedit", position=1, db_url=db_url)
    ac.set_default_role(profile_id, "web-browser", "firefox", "firefox", db_url=db_url)
    ac.set_default_role(profile_id, "text-editor", "gedit", "gedit", db_url=db_url)


def test_render_app_list_basic(db_url, profile):
    _setup_full_catalog(profile["id"], db_url)
    result = ac.render_app_list(profile["id"], db_url=db_url)
    assert result["content_hash"].startswith("sha256:")
    assert result["app_count"] == 2
    assert result["group_count"] == 1
    assert result["role_count"] == 2
    assert "[Catalog]" in result["rendered_app_list"]


def test_render_contains_app_section(db_url, profile):
    _setup_full_catalog(profile["id"], db_url)
    result = ac.render_app_list(profile["id"], db_url=db_url)
    manifest = result["rendered_app_list"]
    assert "[App:firefox]" in manifest
    assert "[App:gedit]" in manifest
    assert "Package=firefox" in manifest
    assert "Category=internet" in manifest


def test_render_contains_group_section(db_url, profile):
    _setup_full_catalog(profile["id"], db_url)
    result = ac.render_app_list(profile["id"], db_url=db_url)
    manifest = result["rendered_app_list"]
    assert "[Group:Core]" in manifest
    assert "firefox" in manifest


def test_render_contains_role_section(db_url, profile):
    _setup_full_catalog(profile["id"], db_url)
    result = ac.render_app_list(profile["id"], db_url=db_url)
    manifest = result["rendered_app_list"]
    assert "[Role:web-browser]" in manifest
    assert "[Role:text-editor]" in manifest


def test_render_deterministic(db_url, profile):
    _setup_full_catalog(profile["id"], db_url)
    r1 = ac.render_app_list(profile["id"], db_url=db_url)
    r2 = ac.render_app_list(profile["id"], db_url=db_url)
    # Body (minus GeneratedAt header) should be identical → same hash
    assert r1["content_hash"] == r2["content_hash"]


def test_render_stored_on_profile(db_url, profile):
    _setup_full_catalog(profile["id"], db_url)
    ac.render_app_list(profile["id"], db_url=db_url)
    detail = ac.get_catalog_profile(profile["id"], db_url=db_url)
    assert detail["content_hash"] is not None
    assert detail["rendered_at"] is not None
    assert "[Catalog]" in (detail["rendered_app_list"] or "")


def test_render_empty_catalog(db_url, profile):
    result = ac.render_app_list(profile["id"], db_url=db_url)
    assert result["app_count"] == 0
    assert result["group_count"] == 0
    assert result["role_count"] == 0
    assert result["content_hash"].startswith("sha256:")


def test_render_nonexistent_profile(db_url):
    with pytest.raises(ValueError, match="not found"):
        ac.render_app_list("bad-id", db_url=db_url)


# ---------------------------------------------------------------------------
# Valid roles / categories constants
# ---------------------------------------------------------------------------


def test_valid_roles_complete():
    expected = {
        "web-browser", "text-editor", "file-manager", "terminal",
        "email-client", "music-player", "video-player", "image-viewer",
        "pdf-viewer", "archive-manager", "calculator", "calendar",
        "contacts", "camera",
    }
    assert ac.VALID_ROLES == expected


def test_valid_categories_complete():
    expected = {
        "productivity", "internet", "multimedia", "graphics", "office",
        "development", "games", "utilities", "system", "education", "accessibility",
    }
    assert ac.VALID_CATEGORIES == expected
