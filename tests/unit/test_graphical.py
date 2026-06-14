"""Unit tests for M40 — Graphical Shell Designer."""

from __future__ import annotations

import hashlib

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from osfabricum.db.models import Base
from osfabricum.db.seed_data import seed_compositor_backends, seed_display_manager_backends
from osfabricum.db.session import sync_session
import osfabricum.graphical as gr


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_url(tmp_path):
    url = f"sqlite:///{tmp_path}/test.db"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    engine.dispose()
    with sync_session(url) as s:
        seed_compositor_backends(s)
        seed_display_manager_backends(s)
        s.commit()
    return url


@pytest.fixture()
def profile_id(db_url):
    p = gr.create_graphical_profile(
        "gnome-wayland",
        display_server="wayland",
        compositor="mutter",
        display_manager="gdm",
        session_manager="systemd-user",
        toolkit_default="gtk4",
        db_url=db_url,
    )
    return p["id"]


# ---------------------------------------------------------------------------
# Seed data
# ---------------------------------------------------------------------------


def test_seed_compositor_backends(db_url):
    backends = gr.list_compositor_backends(db_url=db_url)
    names = {b["name"] for b in backends}
    assert "none" in names
    assert "mutter" in names
    assert "sway" in names
    assert "openbox" in names
    assert len(backends) == 10


def test_seed_compositor_backends_idempotent(db_url):
    with sync_session(db_url) as s:
        added = seed_compositor_backends(s)
        s.commit()
    assert added == 0


def test_seed_display_manager_backends(db_url):
    backends = gr.list_display_manager_backends(db_url=db_url)
    names = {b["name"] for b in backends}
    assert "none" in names
    assert "gdm" in names
    assert "lightdm" in names
    assert "sddm" in names
    assert "greetd" in names
    assert len(backends) == 6


def test_seed_dm_backends_idempotent(db_url):
    with sync_session(db_url) as s:
        added = seed_display_manager_backends(s)
        s.commit()
    assert added == 0


# ---------------------------------------------------------------------------
# Profile CRUD
# ---------------------------------------------------------------------------


def test_create_profile(db_url):
    p = gr.create_graphical_profile(
        "sway-minimal",
        display_server="wayland",
        compositor="sway",
        db_url=db_url,
    )
    assert p["name"] == "sway-minimal"
    assert p["display_server"] == "wayland"
    assert p["compositor"] == "sway"
    assert p["mode"] == "gui"
    assert p["id"] is not None


def test_create_headless_sets_mode(db_url):
    p = gr.create_graphical_profile("headless", display_server="none", db_url=db_url)
    assert p["mode"] == "no-gui"


def test_create_duplicate_rejected(db_url, profile_id):
    with pytest.raises(ValueError, match="already exists"):
        gr.create_graphical_profile("gnome-wayland", db_url=db_url)


def test_invalid_display_server(db_url):
    with pytest.raises(ValueError, match="unknown display_server"):
        gr.create_graphical_profile("bad", display_server="mir2", db_url=db_url)


def test_list_profiles(db_url, profile_id):
    gr.create_graphical_profile("second", db_url=db_url)
    profiles = gr.list_graphical_profiles(db_url=db_url)
    assert len(profiles) == 2
    names = {p["name"] for p in profiles}
    assert "gnome-wayland" in names
    assert "second" in names


def test_list_profiles_filter_by_dist(db_url):
    gr.create_graphical_profile("p1", distribution_id="dist-1", db_url=db_url)
    gr.create_graphical_profile("p2", distribution_id="dist-2", db_url=db_url)
    result = gr.list_graphical_profiles("dist-1", db_url=db_url)
    assert len(result) == 1
    assert result[0]["name"] == "p1"


def test_get_profile_not_found(db_url):
    with pytest.raises(ValueError, match="not found"):
        gr.get_graphical_profile("no-such-id", db_url=db_url)


def test_update_profile(db_url, profile_id):
    updated = gr.update_graphical_profile(
        profile_id, compositor="kwin", display_manager="sddm", db_url=db_url
    )
    assert updated["compositor"] == "kwin"
    assert updated["display_manager"] == "sddm"


def test_update_clears_rendered_cache(db_url, profile_id):
    gr.render_session_config(profile_id, db_url=db_url)
    p_before = gr.get_graphical_profile(profile_id, db_url=db_url)
    assert p_before["content_hash"] is not None

    gr.update_graphical_profile(profile_id, compositor="sway", db_url=db_url)
    p_after = gr.get_graphical_profile(profile_id, db_url=db_url)
    assert p_after["content_hash"] is None


# ---------------------------------------------------------------------------
# Components
# ---------------------------------------------------------------------------


def test_add_component(db_url, profile_id):
    result = gr.add_component(
        profile_id, "panel", "gnome-panel", version_constraint=">=42", db_url=db_url
    )
    assert result["component_kind"] == "panel"
    assert result["package_name"] == "gnome-panel"

    detail = gr.get_graphical_profile(profile_id, db_url=db_url)
    assert len(detail["components"]) == 1
    assert detail["components"][0]["version_constraint"] == ">=42"


def test_add_component_unknown_kind(db_url, profile_id):
    with pytest.raises(ValueError, match="unknown component_kind"):
        gr.add_component(profile_id, "not-a-kind", "pkg", db_url=db_url)


def test_add_component_profile_not_found(db_url):
    with pytest.raises(ValueError, match="not found"):
        gr.add_component("bad-id", "panel", "pkg", db_url=db_url)


def test_add_multiple_components(db_url, profile_id):
    gr.add_component(profile_id, "compositor", "mutter", db_url=db_url)
    gr.add_component(profile_id, "panel", "gnome-shell", db_url=db_url)
    gr.add_component(profile_id, "polkit-agent", "polkit-gnome", db_url=db_url)
    detail = gr.get_graphical_profile(profile_id, db_url=db_url)
    assert len(detail["components"]) == 3


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------


def test_add_session(db_url, profile_id):
    result = gr.add_session(
        profile_id, "GNOME", "wayland", exec_cmd="gnome-session", is_default=True, db_url=db_url
    )
    assert result["name"] == "GNOME"
    assert result["session_type"] == "wayland"
    assert result["is_default"] is True

    detail = gr.get_graphical_profile(profile_id, db_url=db_url)
    assert len(detail["sessions"]) == 1
    assert detail["sessions"][0]["desktop_entry"] is not None
    assert "[Desktop Entry]" in detail["sessions"][0]["desktop_entry"]
    assert "gnome-session" in detail["sessions"][0]["desktop_entry"]


def test_add_session_invalid_type(db_url, profile_id):
    with pytest.raises(ValueError, match="unknown session_type"):
        gr.add_session(profile_id, "Bad", "xorg2", db_url=db_url)


def test_add_session_duplicate_rejected(db_url, profile_id):
    gr.add_session(profile_id, "GNOME", "wayland", db_url=db_url)
    with pytest.raises(ValueError, match="already exists"):
        gr.add_session(profile_id, "GNOME", "wayland", db_url=db_url)


def test_update_session(db_url, profile_id):
    gr.add_session(profile_id, "GNOME", "wayland", exec_cmd="gnome-session", db_url=db_url)
    result = gr.update_session(
        profile_id, "GNOME", exec_cmd="gnome-session --new", is_default=True, db_url=db_url
    )
    assert result["exec_cmd"] == "gnome-session --new"
    assert result["is_default"] is True


def test_update_session_not_found(db_url, profile_id):
    with pytest.raises(ValueError, match="not found"):
        gr.update_session(profile_id, "NoSuchSession", db_url=db_url)


# ---------------------------------------------------------------------------
# render_session_config
# ---------------------------------------------------------------------------


def test_render_session_config_placeholder(db_url, profile_id):
    """No sessions → placeholder .desktop is generated."""
    result = gr.render_session_config(profile_id, db_url=db_url)
    assert "[Desktop Entry]" in result["rendered_session_config"]
    assert result["content_hash"].startswith("sha256:")


def test_render_session_config_with_session(db_url, profile_id):
    gr.add_session(
        profile_id, "GNOME", "wayland", exec_cmd="gnome-session", is_default=True, db_url=db_url
    )
    result = gr.render_session_config(profile_id, db_url=db_url)
    rendered = result["rendered_session_config"]
    assert "Name=GNOME" in rendered
    assert "gnome-session" in rendered
    assert result["content_hash"].startswith("sha256:")


def test_render_hash_matches_manual(db_url, profile_id):
    result = gr.render_session_config(profile_id, db_url=db_url)
    expected = "sha256:" + hashlib.sha256(
        result["rendered_session_config"].encode()
    ).hexdigest()
    assert result["content_hash"] == expected


def test_render_deterministic(db_url, profile_id):
    r1 = gr.render_session_config(profile_id, db_url=db_url)
    r2 = gr.render_session_config(profile_id, db_url=db_url)
    assert r1["content_hash"] == r2["content_hash"]


def test_render_stored_on_profile(db_url, profile_id):
    gr.render_session_config(profile_id, db_url=db_url)
    detail = gr.get_graphical_profile(profile_id, db_url=db_url)
    assert detail["rendered_session_config"] is not None
    assert detail["content_hash"] is not None
    assert detail["rendered_at"] is not None


def test_render_hash_changes_after_session_add(db_url, profile_id):
    r1 = gr.render_session_config(profile_id, db_url=db_url)
    gr.add_session(profile_id, "Sway", "wayland", exec_cmd="sway", is_default=True, db_url=db_url)
    r2 = gr.render_session_config(profile_id, db_url=db_url)
    assert r1["content_hash"] != r2["content_hash"]


def test_render_profile_not_found(db_url):
    with pytest.raises(ValueError, match="not found"):
        gr.render_session_config("bad-id", db_url=db_url)


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


def test_http_list_compositor_backends(client):
    r = client.get("/v1/compositor-backends")
    assert r.status_code == 200
    names = {b["name"] for b in r.json()}
    assert "none" in names
    assert "mutter" in names


def test_http_list_dm_backends(client):
    r = client.get("/v1/display-manager-backends")
    assert r.status_code == 200
    names = {b["name"] for b in r.json()}
    assert "gdm" in names
    assert "greetd" in names


def test_http_create_and_list(client):
    r = client.post("/v1/graphical-profiles", json={
        "name": "sway-session", "display_server": "wayland", "compositor": "sway"
    })
    assert r.status_code == 201
    pid = r.json()["id"]

    r2 = client.get("/v1/graphical-profiles")
    assert r2.status_code == 200
    ids = [p["id"] for p in r2.json()]
    assert pid in ids


def test_http_get_profile(client):
    r = client.post("/v1/graphical-profiles", json={"name": "detail-test"})
    pid = r.json()["id"]
    r2 = client.get(f"/v1/graphical-profiles/{pid}")
    assert r2.status_code == 200
    assert r2.json()["name"] == "detail-test"


def test_http_404(client):
    r = client.get("/v1/graphical-profiles/no-such-id")
    assert r.status_code == 404


def test_http_render_session_config(client):
    r = client.post("/v1/graphical-profiles", json={
        "name": "render-test", "display_server": "wayland", "compositor": "sway"
    })
    pid = r.json()["id"]
    client.post(f"/v1/graphical-profiles/{pid}/sessions", json={
        "name": "Sway", "session_type": "wayland", "exec_cmd": "sway", "is_default": True
    })
    r2 = client.post(f"/v1/graphical-profiles/{pid}/render-session-config")
    assert r2.status_code == 201
    body = r2.json()
    assert body["content_hash"].startswith("sha256:")
    assert "Name=Sway" in body["rendered_session_config"]


def test_http_add_component(client):
    r = client.post("/v1/graphical-profiles", json={"name": "comp-test"})
    pid = r.json()["id"]
    r2 = client.post(f"/v1/graphical-profiles/{pid}/components", json={
        "component_kind": "panel", "package_name": "xfce4-panel"
    })
    assert r2.status_code == 201
    r3 = client.get(f"/v1/graphical-profiles/{pid}")
    assert len(r3.json()["components"]) == 1
