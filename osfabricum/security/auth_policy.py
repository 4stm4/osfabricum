"""Authorization policies and dependencies for API endpoints (G-24).

This module provides FastAPI dependencies that enforce authorization on write
operations. Read operations remain public by default (catalog browsing), while
all create/update/delete operations require authentication.

Usage in route handlers::

    from osfabricum.security.auth_policy import require_write_auth

    @router.post("/v1/distributions", dependencies=[require_write_auth])
    def create_distribution(...):
        ...

When ``AuthSettings.enabled`` is ``False``, the dependency is a no-op.
When enabled, it validates the bearer token from the ``Authorization`` header.
"""

from __future__ import annotations

import hmac
import os
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

# HTTPBearer scheme for OpenAPI documentation
_bearer_scheme = HTTPBearer(auto_error=False)


def _get_expected_token(request: Request) -> str | None:
    """Extract the expected API token from settings or environment."""
    try:
        settings = request.app.state.settings
    except AttributeError:
        return None

    # Environment variable takes priority
    env_tok = os.environ.get("OSFABRICUM_API_TOKEN", "").strip()
    if env_tok:
        return env_tok

    # Fall back to settings
    try:
        tok = settings.auth.token
        if tok:
            return str(tok).strip()
    except AttributeError:
        pass

    return None


def _verify_write_auth(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)] = None,
) -> None:
    """Verify bearer token for write operations.

    Raises
    ------
    HTTPException
        401 if auth is enabled but no token provided.
        403 if token is invalid.
        500 if auth is enabled but server has no token configured.
    """
    # Check if auth is enabled
    try:
        settings = request.app.state.settings
        if not settings.auth.enabled:
            return  # Auth disabled, allow all
    except AttributeError:
        return  # No settings, allow (dev mode)

    # Auth is enabled, validate token
    expected = _get_expected_token(request)
    if expected is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="server misconfiguration: auth enabled but no token set",
        )

    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication required for write operations",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Constant-time comparison
    provided = credentials.credentials.strip()
    if not hmac.compare_digest(expected.encode(), provided.encode()):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="invalid token",
        )


# Dependency for write operations
require_write_auth = Depends(_verify_write_auth)

# Type alias for use in route signatures
WriteAuthDep = Annotated[None, require_write_auth]

# Made with Bob
