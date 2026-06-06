"""Tests for the Kernel / Driver Designer service (M33).

Exercises the resolver semantics that make Kconfig a typed dependency graph
rather than flat checkboxes (G-05): type validation, hidden-symbol rejection,
``select`` (forced on), ``imply`` (soft) and unmet ``depends on``. Also covers
the renderer's deterministic hashing and the driver-bundle catalog.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from apps.api.app import create_app
from osfabricum import kerneldesign as kd
from osfabricum.db.base import Base
from osfabricum.settings import Settings

# A small but representative Kconfig graph.
_SYMBOLS = [
    {"name": "MODULES", "type": "tristate", "prompt": "Loadable module support"},
    {"name": "NET", "type": "bool", "prompt": "Networking support"},
    {"name": "USB", "type": "bool", "prompt": "USB support"},
    {"name": "USB_STORAGE", "type": "tristate", "prompt": "USB Mass Storage", "depends": ["USB"]},
    {"name": "WIFI", "type": "bool", "prompt": "WiFi", "selects": ["NET"]},
    {"name": "DEBUG_INFO", "type": "bool", "prompt": None},  # hidden (no prompt)
    {"name": "FOO", "type": "bool", "prompt": "Foo", "implies": ["BAR"]},
    {"name": "BAR", "type": "bool", "prompt": "Bar"},
    {"name": "NR_CPUS", "type": "int", "prompt": "Maximum number of CPUs"},
]


@pytest.fixture
def db_url(tmp_path) -> Iterator[str]:
    """A file-backed SQLite URL with the schema created.

    The service opens its own engine per call via ``sync_session(db_url)``, so a
    shared in-memory DB will not do — each connection would see an empty schema.
    A temp file persists across the service's independent connections.
    """
    url = f"sqlite:///{tmp_path / 'kd.db'}"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    engine.dispose()
    yield url


@pytest.fixture
def index_id(db_url: str) -> str:
    result = kd.index_kconfig(
        kernel_id="k-test", arch="arm64", source_ref="v6.6", symbols=_SYMBOLS, db_url=db_url
    )
    assert result["symbol_count"] == len(_SYMBOLS)
    return result["index_id"]


# --- index + search ---------------------------------------------------------


def test_list_and_search(db_url: str, index_id: str) -> None:
    indexes = kd.list_indexes(db_url=db_url)
    assert len(indexes) == 1
    assert indexes[0]["id"] == index_id
    assert indexes[0]["symbol_count"] == len(_SYMBOLS)

    hits = {s["name"] for s in kd.search_options(index_id, "USB", db_url=db_url)}
    assert hits == {"USB", "USB_STORAGE"}

    hidden = kd.search_options(index_id, "DEBUG_INFO", db_url=db_url)
    assert hidden and hidden[0]["user_selectable"] is False


def test_get_option_reports_selected_by(db_url: str, index_id: str) -> None:
    net = kd.get_option(index_id, "NET", db_url=db_url)
    assert net["user_selectable"] is True
    assert "WIFI" in net["selected_by"]


def test_search_unknown_index_raises(db_url: str) -> None:
    with pytest.raises(ValueError, match="not found"):
        kd.search_options("no-such-index", "USB", db_url=db_url)


# --- resolver semantics (G-05) ----------------------------------------------


def test_resolve_unknown_symbol(db_url: str, index_id: str) -> None:
    r = kd.resolve_config(index_id, {"NOPE": "y"}, db_url=db_url)
    assert r["valid"] is False
    assert any("unknown symbol" in e for e in r["errors"])


def test_resolve_hidden_symbol_rejected(db_url: str, index_id: str) -> None:
    r = kd.resolve_config(index_id, {"DEBUG_INFO": "y"}, db_url=db_url)
    assert r["valid"] is False
    assert any("not user-selectable" in e for e in r["errors"])


def test_resolve_type_validation(db_url: str, index_id: str) -> None:
    # bool may not take 'm'
    assert kd.resolve_config(index_id, {"USB": "m"}, db_url=db_url)["valid"] is False
    # int must be digits
    assert kd.resolve_config(index_id, {"NR_CPUS": "lots"}, db_url=db_url)["valid"] is False
    # tristate accepts 'm'
    ok = kd.resolve_config(index_id, {"MODULES": "m"}, db_url=db_url)
    assert ok["valid"] is True
    assert ok["resolved"]["MODULES"] == "m"


def test_resolve_select_forces_target_on(db_url: str, index_id: str) -> None:
    r = kd.resolve_config(index_id, {"WIFI": "y"}, db_url=db_url)
    assert r["valid"] is True
    assert r["resolved"]["NET"] == "y"
    assert r["explain"]["NET"] == "selected by WIFI"


def test_resolve_depends_unmet_is_error(db_url: str, index_id: str) -> None:
    r = kd.resolve_config(index_id, {"USB_STORAGE": "y"}, db_url=db_url)
    assert r["valid"] is False
    assert any("depends on USB" in e for e in r["errors"])


def test_resolve_depends_met_is_valid(db_url: str, index_id: str) -> None:
    r = kd.resolve_config(index_id, {"USB": "y", "USB_STORAGE": "y"}, db_url=db_url)
    assert r["valid"] is True
    assert r["resolved"]["USB_STORAGE"] == "y"


def test_resolve_imply_is_soft(db_url: str, index_id: str) -> None:
    r = kd.resolve_config(index_id, {"FOO": "y"}, db_url=db_url)
    assert r["valid"] is True
    assert r["resolved"]["BAR"] == "y"
    assert r["explain"]["BAR"] == "implied by FOO"


# --- render + diff ----------------------------------------------------------


def test_render_is_deterministic_and_marks_not_set(db_url: str, index_id: str) -> None:
    resolved = {"USB": "y", "NET": "n", "MODULES": "m"}
    first = kd.render_config(index_id, resolved, db_url=db_url)
    second = kd.render_config(index_id, resolved, db_url=db_url)

    assert first["config_hash"] == second["config_hash"]
    assert first["config_hash"].startswith("sha256:")
    assert "CONFIG_USB=y" in first["content"]
    assert "CONFIG_MODULES=m" in first["content"]
    assert "# CONFIG_NET is not set" in first["content"]


def test_diff_config() -> None:
    a = "CONFIG_USB=y\n# CONFIG_NET is not set\n"
    b = 'CONFIG_USB=m\nCONFIG_NET=y\nCONFIG_NEW="x"\n'
    d = kd.diff_config(a, b)
    assert d["changed"]["CONFIG_USB"] == {"a": "y", "b": "m"}
    assert d["changed"]["CONFIG_NET"] == {"a": "n", "b": "y"}
    assert d["added"]["CONFIG_NEW"] == '"x"'


# --- driver bundles ---------------------------------------------------------


def test_driver_bundle_resolve(db_url: str) -> None:
    bundle = kd.create_driver_bundle("wifi-rpi", description="RPi WiFi", db_url=db_url)
    bid = bundle["id"]
    kd.add_bundle_option(bid, "CFG80211", "m", db_url=db_url)
    kd.add_bundle_module(bid, "brcmfmac", db_url=db_url)
    kd.add_bundle_firmware(bid, "brcm/brcmfmac43455-sdio.bin", db_url=db_url)
    kd.add_bundle_dt_overlay(bid, "disable-bt", db_url=db_url)

    resolved = kd.resolve_driver_bundle(bid, db_url=db_url)
    assert resolved["options"] == {"CFG80211": "m"}
    assert resolved["modules"] == ["brcmfmac"]
    assert resolved["firmware"] == ["brcm/brcmfmac43455-sdio.bin"]
    assert resolved["dt_overlays"] == ["disable-bt"]


def test_driver_bundle_rejects_bad_option_value(db_url: str) -> None:
    bundle = kd.create_driver_bundle("bad", db_url=db_url)
    with pytest.raises(ValueError, match="'y' or 'm'"):
        kd.add_bundle_option(bundle["id"], "USB", "n", db_url=db_url)


def test_driver_bundle_duplicate_name(db_url: str) -> None:
    kd.create_driver_bundle("dup", db_url=db_url)
    with pytest.raises(ValueError, match="already exists"):
        kd.create_driver_bundle("dup", db_url=db_url)


# --- external modules -------------------------------------------------------


def test_external_module_and_recipe(db_url: str) -> None:
    mod = kd.create_external_module(
        "rtl8812au", source_uri="https://example/rtl8812au.git", db_url=db_url
    )
    kd.add_external_module_recipe(
        mod["id"], kernel_id="k-test", build_system="kbuild", steps={"make": "all"}, db_url=db_url
    )
    listing = kd.list_external_modules(db_url=db_url)
    assert listing[0]["name"] == "rtl8812au"


# --- HTTP API (thin wrapper, auth disabled) ---------------------------------


@pytest.fixture
def client(db_url: str) -> TestClient:
    settings = Settings()
    settings.database.url = db_url
    settings.auth.enabled = False
    return TestClient(create_app(settings))


def test_api_index_resolve_render_flow(client: TestClient) -> None:
    created = client.post(
        "/v1/kconfig-indexes",
        json={"kernel_id": "k-http", "arch": "arm64", "symbols": _SYMBOLS},
    )
    assert created.status_code == 201
    index_id = created.json()["index_id"]

    listed = client.get("/v1/kconfig-indexes").json()
    assert any(i["id"] == index_id for i in listed)

    hits = client.get(f"/v1/kconfig-indexes/{index_id}/options", params={"q": "USB"}).json()
    assert {h["name"] for h in hits} == {"USB", "USB_STORAGE"}

    resolved = client.post(
        "/v1/kernel-configs/resolve",
        json={"index_id": index_id, "requested": {"WIFI": "y"}},
    ).json()
    assert resolved["valid"] is True
    assert resolved["resolved"]["NET"] == "y"

    rendered = client.post(
        "/v1/kernel-configs/render",
        json={"index_id": index_id, "resolved": resolved["resolved"]},
    ).json()
    assert "CONFIG_WIFI=y" in rendered["content"]
    assert rendered["config_hash"].startswith("sha256:")


def test_api_resolve_reports_dependency_error(client: TestClient) -> None:
    index_id = client.post(
        "/v1/kconfig-indexes",
        json={"kernel_id": "k-http", "arch": "arm64", "symbols": _SYMBOLS},
    ).json()["index_id"]

    r = client.post(
        "/v1/kernel-configs/resolve",
        json={"index_id": index_id, "requested": {"USB_STORAGE": "y"}},
    ).json()
    assert r["valid"] is False
    assert any("depends on USB" in e for e in r["errors"])


def test_api_diff_is_public(client: TestClient) -> None:
    resp = client.post(
        "/v1/kernel-configs/diff",
        json={"a": "CONFIG_USB=y\n", "b": "CONFIG_USB=m\n"},
    )
    assert resp.status_code == 200
    assert resp.json()["changed"]["CONFIG_USB"] == {"a": "y", "b": "m"}
