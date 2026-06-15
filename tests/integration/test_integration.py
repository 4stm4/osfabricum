"""M52 — Integration tests covering multi-designer API flows via FastAPI TestClient."""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Health / root
# ---------------------------------------------------------------------------


def test_health_ok(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"


def test_root_redirect_or_ok(client):
    r = client.get("/", follow_redirects=True)
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# SDK Export Kinds (M50)
# ---------------------------------------------------------------------------


def test_sdk_export_kinds_seeded(client):
    r = client.get("/v1/sdk-export-kinds")
    assert r.status_code == 200
    kinds = r.json()
    assert len(kinds) == 5
    names = {k["kind"] for k in kinds}
    assert "pip" in names
    assert "shell-env" in names


def test_sdk_export_kinds_ordered(client):
    r = client.get("/v1/sdk-export-kinds")
    orders = [k["display_order"] for k in r.json()]
    assert orders == sorted(orders)


# ---------------------------------------------------------------------------
# SDK Profiles (M50)
# ---------------------------------------------------------------------------


def test_sdk_profile_create(client):
    r = client.post("/v1/sdk-profiles", json={"name": "integ-sdk-profile"})
    assert r.status_code == 200
    data = r.json()
    assert data["name"] == "integ-sdk-profile"
    assert data["id"]


def test_sdk_profile_list(client):
    client.post("/v1/sdk-profiles", json={"name": "sdk-list-test"})
    r = client.get("/v1/sdk-profiles")
    assert r.status_code == 200
    names = [p["name"] for p in r.json()]
    assert "sdk-list-test" in names


def test_sdk_profile_get_by_id(client):
    cr = client.post("/v1/sdk-profiles", json={"name": "sdk-get-test"})
    pid = cr.json()["id"]
    r = client.get(f"/v1/sdk-profiles/{pid}")
    assert r.status_code == 200
    assert r.json()["id"] == pid


def test_sdk_profile_not_found(client):
    r = client.get("/v1/sdk-profiles/no-such-id")
    assert r.status_code == 404


def test_sdk_profile_render(client):
    cr = client.post("/v1/sdk-profiles", json={"name": "sdk-render-test"})
    pid = cr.json()["id"]
    r = client.post(f"/v1/sdk-profiles/{pid}/render")
    assert r.status_code == 200
    data = r.json()
    assert data["content_hash"].startswith("sha256:")


def test_sdk_variable_set_and_list(client):
    cr = client.post("/v1/sdk-profiles", json={"name": "sdk-var-test"})
    pid = cr.json()["id"]
    client.put(f"/v1/sdk-profiles/{pid}/variables/MY_VAR",
               json={"value": "hello"})
    r = client.get(f"/v1/sdk-profiles/{pid}/variables")
    assert r.status_code == 200
    keys = [v["key"] for v in r.json()]
    assert "MY_VAR" in keys


# ---------------------------------------------------------------------------
# Cache Policy Kinds (M51)
# ---------------------------------------------------------------------------


def test_cache_policy_kinds_seeded(client):
    r = client.get("/v1/cache-policy-kinds")
    assert r.status_code == 200
    kinds = r.json()
    assert len(kinds) == 4
    names = {k["kind"] for k in kinds}
    assert "always" in names
    assert "offline-only" in names


# ---------------------------------------------------------------------------
# Mirror Profiles (M51)
# ---------------------------------------------------------------------------


def test_mirror_profile_create(client):
    r = client.post("/v1/mirror-profiles", json={"name": "integ-mirror"})
    assert r.status_code == 200
    data = r.json()
    assert data["name"] == "integ-mirror"


def test_mirror_profile_list(client):
    client.post("/v1/mirror-profiles", json={"name": "mirror-list-test"})
    r = client.get("/v1/mirror-profiles")
    assert r.status_code == 200
    names = [p["name"] for p in r.json()]
    assert "mirror-list-test" in names


def test_mirror_profile_render(client):
    cr = client.post("/v1/mirror-profiles", json={"name": "mirror-render-test"})
    pid = cr.json()["id"]
    r = client.post(f"/v1/mirror-profiles/{pid}/render")
    assert r.status_code == 200
    assert r.json()["content_hash"].startswith("sha256:")


def test_mirror_endpoint_add(client):
    cr = client.post("/v1/mirror-profiles", json={"name": "mirror-ep-test"})
    pid = cr.json()["id"]
    r = client.put(f"/v1/mirror-profiles/{pid}/endpoints",
                   json={"url": "https://mirror.example.com/packages"})
    assert r.status_code == 200
    assert r.json()["url"] == "https://mirror.example.com/packages"


def test_mirror_cache_rule_add(client):
    cr = client.post("/v1/mirror-profiles", json={"name": "mirror-cr-test"})
    pid = cr.json()["id"]
    r = client.put(f"/v1/mirror-profiles/{pid}/cache-rules",
                   json={"source_pattern": "*.deb", "cache_policy": "always"})
    assert r.status_code == 200
    assert r.json()["source_pattern"] == "*.deb"


# ---------------------------------------------------------------------------
# Probe Source Kinds (M53)
# ---------------------------------------------------------------------------


def test_probe_source_kinds_seeded(client):
    r = client.get("/v1/probe-source-kinds")
    assert r.status_code == 200
    kinds = r.json()
    assert len(kinds) == 5
    names = {k["kind"] for k in kinds}
    assert "manual" in names
    assert "lshw" in names


# ---------------------------------------------------------------------------
# Hardware Probes (M53)
# ---------------------------------------------------------------------------


def test_hardware_probe_import(client):
    r = client.post("/v1/hardware-probes", json={
        "name": "integ-rpi4",
        "probe_source": "manual",
        "probe_data": {"cpu_arch": "aarch64", "mem_mb": 4096},
    })
    assert r.status_code == 200
    data = r.json()
    assert data["name"] == "integ-rpi4"
    assert data["cpu_arch"] == "aarch64"
    assert data["content_hash"].startswith("sha256:")


def test_hardware_probe_list(client):
    client.post("/v1/hardware-probes", json={
        "name": "probe-list-test",
        "probe_data": {"cpu_arch": "x86_64"},
    })
    r = client.get("/v1/hardware-probes")
    assert r.status_code == 200
    names = [p["name"] for p in r.json()]
    assert "probe-list-test" in names


def test_hardware_probe_get(client):
    cr = client.post("/v1/hardware-probes", json={
        "name": "probe-get-test", "probe_data": {},
    })
    pid = cr.json()["id"]
    r = client.get(f"/v1/hardware-probes/{pid}")
    assert r.status_code == 200
    assert r.json()["id"] == pid


def test_hardware_probe_not_found(client):
    r = client.get("/v1/hardware-probes/bad-id")
    assert r.status_code == 404


def test_hardware_probe_delete(client):
    cr = client.post("/v1/hardware-probes", json={
        "name": "probe-delete-test", "probe_data": {},
    })
    pid = cr.json()["id"]
    dr = client.delete(f"/v1/hardware-probes/{pid}")
    assert dr.status_code == 200
    assert dr.json()["deleted"] == pid


def test_hardware_probe_invalid_source(client):
    r = client.post("/v1/hardware-probes", json={
        "name": "bad-source", "probe_source": "not-valid", "probe_data": {},
    })
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# Layer Kinds (M54)
# ---------------------------------------------------------------------------


def test_layer_kinds_seeded(client):
    r = client.get("/v1/layer-kinds")
    assert r.status_code == 200
    kinds = r.json()
    assert len(kinds) == 6
    names = {k["kind"] for k in kinds}
    assert "base" in names
    assert "debug" in names


# ---------------------------------------------------------------------------
# Layer Profiles (M54)
# ---------------------------------------------------------------------------


def test_layer_profile_create(client):
    r = client.post("/v1/layer-profiles", json={"name": "integ-layers"})
    assert r.status_code == 200
    data = r.json()
    assert data["name"] == "integ-layers"
    assert data["base_layer"] == "base"


def test_layer_profile_list(client):
    client.post("/v1/layer-profiles", json={"name": "layer-list-test"})
    r = client.get("/v1/layer-profiles")
    assert r.status_code == 200
    names = [p["name"] for p in r.json()]
    assert "layer-list-test" in names


def test_layer_profile_get(client):
    cr = client.post("/v1/layer-profiles", json={"name": "layer-get-test"})
    pid = cr.json()["id"]
    r = client.get(f"/v1/layer-profiles/{pid}")
    assert r.status_code == 200
    assert r.json()["id"] == pid


def test_layer_profile_not_found(client):
    r = client.get("/v1/layer-profiles/no-such-id")
    assert r.status_code == 404


def test_layer_entry_add(client):
    cr = client.post("/v1/layer-profiles", json={"name": "layer-entry-test"})
    pid = cr.json()["id"]
    r = client.put(f"/v1/layer-profiles/{pid}/entries", json={
        "name": "wifi-fw", "layer_kind": "bsp", "priority": 5,
    })
    assert r.status_code == 200
    assert r.json()["name"] == "wifi-fw"


def test_layer_entry_list(client):
    cr = client.post("/v1/layer-profiles", json={"name": "layer-elist-test"})
    pid = cr.json()["id"]
    client.put(f"/v1/layer-profiles/{pid}/entries", json={"name": "e1"})
    client.put(f"/v1/layer-profiles/{pid}/entries", json={"name": "e2"})
    r = client.get(f"/v1/layer-profiles/{pid}/entries")
    assert r.status_code == 200
    assert len(r.json()) == 2


def test_layer_manifest_render(client):
    cr = client.post("/v1/layer-profiles", json={"name": "layer-render-test"})
    pid = cr.json()["id"]
    client.put(f"/v1/layer-profiles/{pid}/entries", json={"name": "base-layer"})
    r = client.post(f"/v1/layer-profiles/{pid}/render")
    assert r.status_code == 200
    data = r.json()
    assert data["content_hash"].startswith("sha256:")
    assert "base-layer" in data["rendered_manifest"]


def test_layer_entry_invalid_kind(client):
    cr = client.post("/v1/layer-profiles", json={"name": "layer-bad-kind"})
    pid = cr.json()["id"]
    r = client.put(f"/v1/layer-profiles/{pid}/entries",
                   json={"name": "e1", "layer_kind": "nonexistent"})
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# Override Kinds (M55)
# ---------------------------------------------------------------------------


def test_override_kinds_seeded(client):
    r = client.get("/v1/override-kinds")
    assert r.status_code == 200
    kinds = r.json()
    assert len(kinds) == 6
    names = {k["kind"] for k in kinds}
    assert "set" in names
    assert "mask" in names


# ---------------------------------------------------------------------------
# Override Profiles (M55)
# ---------------------------------------------------------------------------


def test_override_profile_create(client):
    r = client.post("/v1/override-profiles", json={"name": "integ-overrides"})
    assert r.status_code == 200
    data = r.json()
    assert data["name"] == "integ-overrides"


def test_override_profile_list(client):
    client.post("/v1/override-profiles", json={"name": "ov-list-test"})
    r = client.get("/v1/override-profiles")
    assert r.status_code == 200
    names = [p["name"] for p in r.json()]
    assert "ov-list-test" in names


def test_override_profile_get(client):
    cr = client.post("/v1/override-profiles", json={"name": "ov-get-test"})
    pid = cr.json()["id"]
    r = client.get(f"/v1/override-profiles/{pid}")
    assert r.status_code == 200
    assert r.json()["id"] == pid


def test_override_profile_not_found(client):
    r = client.get("/v1/override-profiles/no-such-id")
    assert r.status_code == 404


def test_override_rule_add(client):
    cr = client.post("/v1/override-profiles", json={"name": "ov-rule-test"})
    pid = cr.json()["id"]
    r = client.put(f"/v1/override-profiles/{pid}/rules", json={
        "target_type": "sysctl",
        "target_key": "net.ipv4.ip_forward",
        "action": "set",
        "value": "1",
    })
    assert r.status_code == 200
    data = r.json()
    assert data["target_key"] == "net.ipv4.ip_forward"
    assert data["action"] == "set"


def test_override_rule_list(client):
    cr = client.post("/v1/override-profiles", json={"name": "ov-rlist-test"})
    pid = cr.json()["id"]
    client.put(f"/v1/override-profiles/{pid}/rules",
               json={"target_type": "sysctl", "target_key": "a"})
    client.put(f"/v1/override-profiles/{pid}/rules",
               json={"target_type": "package", "target_key": "b"})
    r = client.get(f"/v1/override-profiles/{pid}/rules")
    assert r.status_code == 200
    assert len(r.json()) == 2


def test_override_rule_filter_by_type(client):
    cr = client.post("/v1/override-profiles", json={"name": "ov-filter-test"})
    pid = cr.json()["id"]
    client.put(f"/v1/override-profiles/{pid}/rules",
               json={"target_type": "sysctl", "target_key": "s1"})
    client.put(f"/v1/override-profiles/{pid}/rules",
               json={"target_type": "package", "target_key": "p1"})
    r = client.get(f"/v1/override-profiles/{pid}/rules?target_type=sysctl")
    assert r.status_code == 200
    rules = r.json()
    assert len(rules) == 1
    assert rules[0]["target_type"] == "sysctl"


def test_override_policy_render(client):
    cr = client.post("/v1/override-profiles", json={"name": "ov-render-test"})
    pid = cr.json()["id"]
    client.put(f"/v1/override-profiles/{pid}/rules",
               json={"target_type": "service", "target_key": "bluetooth", "action": "mask"})
    r = client.post(f"/v1/override-profiles/{pid}/render")
    assert r.status_code == 200
    data = r.json()
    assert data["content_hash"].startswith("sha256:")
    assert "[service]" in data["rendered_override_policy"]
    assert "bluetooth" in data["rendered_override_policy"]


def test_override_rule_invalid_action(client):
    cr = client.post("/v1/override-profiles", json={"name": "ov-bad-action"})
    pid = cr.json()["id"]
    r = client.put(f"/v1/override-profiles/{pid}/rules",
                   json={"target_type": "sysctl", "target_key": "k", "action": "bad"})
    assert r.status_code == 400


def test_override_rule_invalid_target_type(client):
    cr = client.post("/v1/override-profiles", json={"name": "ov-bad-type"})
    pid = cr.json()["id"]
    r = client.put(f"/v1/override-profiles/{pid}/rules",
                   json={"target_type": "invalid", "target_key": "k"})
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# Cross-designer: full flow (M52 narrative test)
# ---------------------------------------------------------------------------


def test_full_designer_flow(client):
    """
    Create an SDK profile and a layer profile, render both, verify hashes.
    Simulates a realistic designer session spanning two M-features.
    """
    # SDK profile with a variable
    sr = client.post("/v1/sdk-profiles", json={"name": "cross-sdk"})
    assert sr.status_code == 200
    spid = sr.json()["id"]
    client.put(f"/v1/sdk-profiles/{spid}/variables/CC", json={"value": "aarch64-linux-gnu-gcc"})
    render_r = client.post(f"/v1/sdk-profiles/{spid}/render")
    assert render_r.status_code == 200
    sdk_hash = render_r.json()["content_hash"]
    assert sdk_hash.startswith("sha256:")

    # Layer profile with one entry
    lr = client.post("/v1/layer-profiles", json={"name": "cross-layer"})
    assert lr.status_code == 200
    lpid = lr.json()["id"]
    client.put(f"/v1/layer-profiles/{lpid}/entries",
               json={"name": "bsp-core", "layer_kind": "bsp", "priority": 1})
    layer_render = client.post(f"/v1/layer-profiles/{lpid}/render")
    assert layer_render.status_code == 200
    layer_hash = layer_render.json()["content_hash"]
    assert layer_hash.startswith("sha256:")

    # Hashes are distinct (different content)
    assert sdk_hash != layer_hash
