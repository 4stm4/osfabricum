from fastapi.testclient import TestClient

from apps.api.app import create_app


def _client() -> TestClient:
    return TestClient(create_app())


def test_healthz_ok() -> None:
    resp = _client().get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_readyz_ok() -> None:
    resp = _client().get("/readyz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_metrics_prometheus_text() -> None:
    resp = _client().get("/metrics")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    assert "osf_build_info" in resp.text
