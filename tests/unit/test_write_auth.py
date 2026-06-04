"""Tests for write operation authorization (G-24).

Verifies that:
- Write endpoints require authentication when auth is enabled
- Read endpoints remain public
- Token validation works correctly
- Auth can be disabled for development
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

if TYPE_CHECKING:
    from fastapi import FastAPI


@pytest.fixture
def app_with_auth(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    """Create an app instance with auth enabled."""
    monkeypatch.setenv("OSFABRICUM_API_TOKEN", "test-secret-token")
    
    from osfabricum.settings import Settings
    from apps.api.app import create_app
    
    settings = Settings()
    settings.auth.enabled = True
    settings.auth.token = "test-secret-token"
    
    return create_app(settings)


@pytest.fixture
def app_without_auth() -> FastAPI:
    """Create an app instance with auth disabled."""
    from osfabricum.settings import Settings
    from apps.api.app import create_app
    
    settings = Settings()
    settings.auth.enabled = False
    
    return create_app(settings)


def test_read_endpoints_public_when_auth_enabled(app_with_auth: FastAPI) -> None:
    """Read endpoints should remain accessible without auth."""
    client = TestClient(app_with_auth)
    
    # These should all work without authentication
    response = client.get("/v1/distributions")
    assert response.status_code in (200, 500)  # 500 if DB not ready, but not 401
    
    response = client.get("/v1/profiles")
    assert response.status_code in (200, 500)
    
    response = client.get("/v1/builds")
    assert response.status_code in (200, 500)


def test_write_endpoints_require_auth(app_with_auth: FastAPI) -> None:
    """Write endpoints should require authentication."""
    client = TestClient(app_with_auth)
    
    # POST without auth should fail with 401
    response = client.post(
        "/v1/distributions",
        json={"name": "test", "description": "test"},
    )
    assert response.status_code == 401
    assert "authentication required" in response.json()["detail"].lower()
    
    # PATCH without auth should fail
    response = client.patch(
        "/v1/distributions/test",
        json={"description": "updated"},
    )
    assert response.status_code == 401
    
    # DELETE without auth should fail
    response = client.delete("/v1/distributions/test")
    assert response.status_code == 401


def test_write_with_valid_token(app_with_auth: FastAPI) -> None:
    """Write endpoints should accept valid bearer token."""
    client = TestClient(app_with_auth)
    
    headers = {"Authorization": "Bearer test-secret-token"}
    
    # Should get past auth (may fail on business logic, but not 401/403)
    response = client.post(
        "/v1/distributions",
        json={"name": "test", "description": "test"},
        headers=headers,
    )
    assert response.status_code not in (401, 403)


def test_write_with_invalid_token(app_with_auth: FastAPI) -> None:
    """Write endpoints should reject invalid token."""
    client = TestClient(app_with_auth)
    
    headers = {"Authorization": "Bearer wrong-token"}
    
    response = client.post(
        "/v1/distributions",
        json={"name": "test", "description": "test"},
        headers=headers,
    )
    assert response.status_code == 403
    assert "invalid token" in response.json()["detail"].lower()


def test_write_without_auth_when_disabled(app_without_auth: FastAPI) -> None:
    """Write endpoints should work without auth when disabled."""
    client = TestClient(app_without_auth)
    
    # Should get past auth check (may fail on business logic)
    response = client.post(
        "/v1/distributions",
        json={"name": "test", "description": "test"},
    )
    assert response.status_code not in (401, 403)


def test_malformed_auth_header(app_with_auth: FastAPI) -> None:
    """Malformed Authorization header should be rejected."""
    client = TestClient(app_with_auth)
    
    # Missing "Bearer" prefix
    response = client.post(
        "/v1/distributions",
        json={"name": "test"},
        headers={"Authorization": "test-secret-token"},
    )
    assert response.status_code == 401
    
    # Empty token
    response = client.post(
        "/v1/distributions",
        json={"name": "test"},
        headers={"Authorization": "Bearer "},
    )
    assert response.status_code == 401


def test_all_write_endpoints_protected(app_with_auth: FastAPI) -> None:
    """Verify all write endpoints are protected."""
    client = TestClient(app_with_auth)
    
    write_endpoints = [
        ("POST", "/v1/distributions", {"name": "test"}),
        ("PATCH", "/v1/distributions/test", {"description": "test"}),
        ("DELETE", "/v1/distributions/test", None),
        ("POST", "/v1/profiles", {"distribution": "test", "name": "test"}),
        ("PATCH", "/v1/profiles/test/test", {"inputs": {}}),
        ("DELETE", "/v1/profiles/test/test", None),
        ("POST", "/v1/builds", {"distribution": "test", "profile": "test", "board": "test"}),
        ("POST", "/v1/plan", {"distribution": "test", "profile": "test", "board": "test"}),
        ("POST", "/v1/prefetch", {"distribution": "test", "profile": "test", "board": "test"}),
        ("POST", "/v1/drafts", {"distribution": "test", "profile": "test", "board": "test"}),
        ("PATCH", "/v1/drafts/test", {"inputs": {}}),
        ("DELETE", "/v1/drafts/test", None),
    ]
    
    for method, path, json_data in write_endpoints:
        if method == "POST":
            response = client.post(path, json=json_data)
        elif method == "PATCH":
            response = client.patch(path, json=json_data)
        elif method == "DELETE":
            response = client.delete(path)
        else:
            continue
        
        assert response.status_code == 401, f"{method} {path} should require auth"


def test_health_endpoints_always_public(app_with_auth: FastAPI) -> None:
    """Health/metrics endpoints should always be public."""
    client = TestClient(app_with_auth)
    
    # These should work without auth even when auth is enabled
    response = client.get("/healthz")
    assert response.status_code == 200
    
    response = client.get("/readyz")
    assert response.status_code == 200
    
    response = client.get("/metrics")
    assert response.status_code == 200

# Made with Bob
