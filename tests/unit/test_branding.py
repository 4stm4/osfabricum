"""Unit tests for M39 — Branding / Identity Designer.

Tests are written against the service layer only (no HTTP); the HTTP flow is
tested separately at the end.
"""

from __future__ import annotations

import hashlib

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from osfabricum.db.models import Base
import osfabricum.branding as br


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_url(tmp_path):
    url = f"sqlite:///{tmp_path}/test.db"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    engine.dispose()
    return url


@pytest.fixture()
def profile_id(db_url):
    p = br.create_branding_profile(
        "test-brand",
        os_name="TestOS",
        os_id="testos",
        os_version="1.0",
        os_pretty_name="TestOS 1.0",
        os_home_url="https://testos.example.org",
        vendor_name="Test Corp",
        support_url="https://testos.example.org/support",
        bug_report_url="https://bugs.testos.example.org",
        db_url=db_url,
    )
    return p["id"]


# ---------------------------------------------------------------------------
# Profile CRUD
# ---------------------------------------------------------------------------


def test_create_profile(db_url):
    p = br.create_branding_profile(
        "brand-one", os_name="Distro", os_id="distro", os_version="2.0", db_url=db_url
    )
    assert p["name"] == "brand-one"
    assert p["os_name"] == "Distro"
    assert p["os_id"] == "distro"
    assert p["os_version"] == "2.0"
    assert p["id"] is not None


def test_duplicate_profile_rejected(db_url, profile_id):
    with pytest.raises(ValueError, match="already exists"):
        br.create_branding_profile("test-brand", db_url=db_url)


def test_list_profiles(db_url, profile_id):
    br.create_branding_profile("second-brand", db_url=db_url)
    profiles = br.list_branding_profiles(db_url=db_url)
    assert len(profiles) == 2
    names = {p["name"] for p in profiles}
    assert "test-brand" in names
    assert "second-brand" in names


def test_list_profiles_filter_by_dist(db_url):
    br.create_branding_profile("brand-a", distribution_id="dist-1", db_url=db_url)
    br.create_branding_profile("brand-b", distribution_id="dist-2", db_url=db_url)
    result = br.list_branding_profiles("dist-1", db_url=db_url)
    assert len(result) == 1
    assert result[0]["name"] == "brand-a"


def test_get_profile_not_found(db_url):
    with pytest.raises(ValueError, match="not found"):
        br.get_branding_profile("no-such-id", db_url=db_url)


def test_update_profile(db_url, profile_id):
    updated = br.update_branding_profile(
        profile_id, os_version="2.0", vendor_name="New Vendor", db_url=db_url
    )
    assert updated["os_version"] == "2.0"
    assert updated["vendor_name"] == "New Vendor"


def test_update_clears_rendered_cache(db_url, profile_id):
    # First render
    br.render_os_release(profile_id, db_url=db_url)
    p_before = br.get_branding_profile(profile_id, db_url=db_url)
    assert p_before["content_hash"] is not None

    # Update should clear
    br.update_branding_profile(profile_id, os_version="99.0", db_url=db_url)
    p_after = br.get_branding_profile(profile_id, db_url=db_url)
    assert p_after["content_hash"] is None
    assert p_after["rendered_os_release"] is None


# ---------------------------------------------------------------------------
# Assets
# ---------------------------------------------------------------------------


def test_add_asset(db_url, profile_id):
    asset = br.add_asset(
        profile_id,
        "main-logo",
        "logo",
        source_path="/assets/logo.svg",
        mime_type="image/svg+xml",
        width_px=256,
        height_px=256,
        db_url=db_url,
    )
    assert asset["name"] == "main-logo"
    assert asset["asset_kind"] == "logo"

    detail = br.get_branding_profile(profile_id, db_url=db_url)
    assert len(detail["assets"]) == 1
    assert detail["assets"][0]["mime_type"] == "image/svg+xml"


def test_add_asset_unknown_kind(db_url, profile_id):
    with pytest.raises(ValueError, match="unknown asset_kind"):
        br.add_asset(profile_id, "x", "not-a-kind", db_url=db_url)


def test_add_asset_profile_not_found(db_url):
    with pytest.raises(ValueError, match="not found"):
        br.add_asset("bad-id", "x", "logo", db_url=db_url)


# ---------------------------------------------------------------------------
# Targets
# ---------------------------------------------------------------------------


def test_set_target(db_url, profile_id):
    result = br.set_target(profile_id, "os-release", db_url=db_url)
    assert result["stage"] == "os-release"

    detail = br.get_branding_profile(profile_id, db_url=db_url)
    stages = {t["stage"] for t in detail["targets"]}
    assert "os-release" in stages


def test_set_target_upsert(db_url, profile_id):
    br.set_target(profile_id, "plymouth", asset_id="asset-1", db_url=db_url)
    br.set_target(profile_id, "plymouth", asset_id="asset-2", db_url=db_url)
    detail = br.get_branding_profile(profile_id, db_url=db_url)
    targets = [t for t in detail["targets"] if t["stage"] == "plymouth"]
    assert len(targets) == 1
    assert targets[0]["asset_id"] == "asset-2"


def test_set_target_unknown_stage(db_url, profile_id):
    with pytest.raises(ValueError, match="unknown stage"):
        br.set_target(profile_id, "not-a-stage", db_url=db_url)


# ---------------------------------------------------------------------------
# render_os_release
# ---------------------------------------------------------------------------


def test_render_os_release_default_template(db_url, profile_id):
    result = br.render_os_release(profile_id, db_url=db_url)
    rendered = result["rendered_os_release"]
    assert 'NAME="TestOS"' in rendered
    assert "ID=testos" in rendered
    assert 'VERSION="1.0"' in rendered
    assert 'PRETTY_NAME="TestOS 1.0"' in rendered
    assert 'HOME_URL="https://testos.example.org"' in rendered
    assert 'SUPPORT_URL=' in rendered
    assert 'BUG_REPORT_URL=' in rendered


def test_render_os_release_hash_format(db_url, profile_id):
    result = br.render_os_release(profile_id, db_url=db_url)
    assert result["content_hash"].startswith("sha256:")


def test_render_os_release_hash_matches_manual(db_url, profile_id):
    result = br.render_os_release(profile_id, db_url=db_url)
    expected = "sha256:" + hashlib.sha256(result["rendered_os_release"].encode()).hexdigest()
    assert result["content_hash"] == expected


def test_render_os_release_deterministic(db_url, profile_id):
    r1 = br.render_os_release(profile_id, db_url=db_url)
    r2 = br.render_os_release(profile_id, db_url=db_url)
    assert r1["content_hash"] == r2["content_hash"]


def test_render_os_release_stored_on_profile(db_url, profile_id):
    br.render_os_release(profile_id, db_url=db_url)
    detail = br.get_branding_profile(profile_id, db_url=db_url)
    assert detail["rendered_os_release"] is not None
    assert detail["content_hash"] is not None
    assert detail["rendered_at"] is not None


def test_render_os_release_hash_changes_after_update(db_url, profile_id):
    r1 = br.render_os_release(profile_id, db_url=db_url)
    br.update_branding_profile(profile_id, os_version="2.0", db_url=db_url)
    r2 = br.render_os_release(profile_id, db_url=db_url)
    assert r1["content_hash"] != r2["content_hash"]


def test_render_os_release_profile_not_found(db_url):
    with pytest.raises(ValueError, match="not found"):
        br.render_os_release("bad-id", db_url=db_url)


def test_render_os_release_custom_template(db_url, profile_id):
    br.set_os_release_template(
        profile_id, "MYOS={os_id}\nMYVER={os_version}\n", db_url=db_url
    )
    result = br.render_os_release(profile_id, db_url=db_url)
    assert "MYOS=testos" in result["rendered_os_release"]
    assert "MYVER=1.0" in result["rendered_os_release"]


# ---------------------------------------------------------------------------
# render_motd
# ---------------------------------------------------------------------------


def test_render_motd_default(db_url, profile_id):
    result = br.render_motd(profile_id, db_url=db_url)
    assert "TestOS" in result["rendered_motd"]


def test_render_motd_custom_template(db_url, profile_id):
    br.set_motd_template(
        profile_id, "Welcome to {os_name} v{os_version}!\n", db_url=db_url
    )
    result = br.render_motd(profile_id, db_url=db_url)
    assert "Welcome to TestOS v1.0!" in result["rendered_motd"]


def test_render_motd_stored_on_profile(db_url, profile_id):
    br.render_motd(profile_id, db_url=db_url)
    detail = br.get_branding_profile(profile_id, db_url=db_url)
    assert detail["rendered_motd"] is not None


# ---------------------------------------------------------------------------
# Boot splash / Login theme
# ---------------------------------------------------------------------------


def test_set_boot_splash(db_url, profile_id):
    result = br.set_boot_splash(profile_id, "spinner", package_name="plymouth-theme-spinner", db_url=db_url)
    assert result["theme_name"] == "spinner"
    detail = br.get_branding_profile(profile_id, db_url=db_url)
    assert detail["boot_splash"]["theme_name"] == "spinner"


def test_set_boot_splash_upsert(db_url, profile_id):
    br.set_boot_splash(profile_id, "spinner", db_url=db_url)
    br.set_boot_splash(profile_id, "bgrt", db_url=db_url)
    detail = br.get_branding_profile(profile_id, db_url=db_url)
    assert detail["boot_splash"]["theme_name"] == "bgrt"


def test_set_login_theme(db_url, profile_id):
    result = br.set_login_theme(profile_id, "my-theme", display_manager="lightdm", db_url=db_url)
    assert result["theme_name"] == "my-theme"
    detail = br.get_branding_profile(profile_id, db_url=db_url)
    assert detail["login_theme"]["display_manager"] == "lightdm"


# ---------------------------------------------------------------------------
# HTTP flow
# ---------------------------------------------------------------------------


@pytest.fixture()
def client(db_url):
    from osfabricum.settings import DatabaseSettings, Settings
    from apps.api.app import create_app

    settings = Settings(database=DatabaseSettings(url=db_url))
    test_app = create_app(settings=settings)
    return TestClient(test_app)


def test_http_create_and_list(client):
    r = client.post("/v1/branding-profiles", json={"name": "http-brand", "os_name": "HTTP OS", "os_id": "httpos", "os_version": "3.0"})
    assert r.status_code == 201
    pid = r.json()["id"]

    r2 = client.get("/v1/branding-profiles")
    assert r2.status_code == 200
    ids = [p["id"] for p in r2.json()]
    assert pid in ids


def test_http_get_profile(client):
    r = client.post("/v1/branding-profiles", json={"name": "detail-test", "os_name": "DetailOS"})
    pid = r.json()["id"]
    r2 = client.get(f"/v1/branding-profiles/{pid}")
    assert r2.status_code == 200
    assert r2.json()["os_name"] == "DetailOS"


def test_http_404(client):
    r = client.get("/v1/branding-profiles/no-such-id")
    assert r.status_code == 404


def test_http_render_os_release(client):
    r = client.post("/v1/branding-profiles", json={
        "name": "render-test", "os_name": "RenderOS", "os_id": "renderos", "os_version": "5.0"
    })
    pid = r.json()["id"]
    r2 = client.post(f"/v1/branding-profiles/{pid}/render-os-release")
    assert r2.status_code == 201
    body = r2.json()
    assert body["content_hash"].startswith("sha256:")
    assert "RenderOS" in body["rendered_os_release"]


def test_http_add_asset(client):
    r = client.post("/v1/branding-profiles", json={"name": "asset-test"})
    pid = r.json()["id"]
    r2 = client.post(f"/v1/branding-profiles/{pid}/assets", json={
        "name": "logo", "asset_kind": "logo", "source_path": "/logo.svg"
    })
    assert r2.status_code == 201

    r3 = client.get(f"/v1/branding-profiles/{pid}")
    assert len(r3.json()["assets"]) == 1
