"""API token authentication middleware (M14).

When ``AuthSettings.enabled`` is ``True``, every non-health-check request
must carry a valid bearer token in the ``Authorization`` header.

The expected token is read from (in priority order):
1. ``OSFABRICUM_API_TOKEN`` environment variable
2. ``auth.token`` field in the TOML config file

Health/readiness endpoints (``/healthz``, ``/readyz``, ``/metrics``) are
always exempt so monitoring systems do not need credentials.

Usage (in :func:`~apps.api.app.create_app`)::

    if settings.auth.enabled:
        app.add_middleware(TokenAuthMiddleware, settings=settings)
"""

from __future__ import annotations

import hmac
import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

#: Paths that skip authentication regardless of the auth setting.
_PUBLIC_PATHS: frozenset[str] = frozenset(
    {"/healthz", "/readyz", "/metrics", "/docs", "/openapi.json", "/redoc"}
)


def _get_expected_token(settings: object) -> str | None:
    """Return the expected API token, or ``None`` if not configured."""
    # Environment variable takes priority
    env_tok = os.environ.get("OSFABRICUM_API_TOKEN", "").strip()
    if env_tok:
        return env_tok
    # Fall back to settings (if the AuthSettings model has a ``token`` field)
    tok = getattr(getattr(settings, "auth", None), "token", None)
    if tok:
        return str(tok).strip()
    return None


class TokenAuthMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that enforces bearer token authentication.

    Parameters
    ----------
    app:
        The ASGI application.
    settings:
        An :class:`~osfabricum.settings.Settings` instance.
    """

    def __init__(self, app: ASGIApp, *, settings: object) -> None:
        super().__init__(app)
        self._settings = settings

    async def dispatch(self, request: Request, call_next: object) -> Response:
        # Exempt public paths
        if request.url.path in _PUBLIC_PATHS:
            return await call_next(request)  # type: ignore[operator]

        expected = _get_expected_token(self._settings)
        if expected is None:
            # Auth is enabled but no token configured → refuse all requests
            return JSONResponse(
                {"detail": "server misconfiguration: auth enabled but no token set"},
                status_code=500,
            )

        auth_header = request.headers.get("Authorization", "")
        scheme, _, provided = auth_header.partition(" ")
        if scheme.lower() != "bearer" or not provided:
            return JSONResponse(
                {"detail": "authentication required"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Constant-time comparison
        if not hmac.compare_digest(expected.encode(), provided.strip().encode()):
            return JSONResponse(
                {"detail": "invalid token"},
                status_code=403,
            )

        return await call_next(request)  # type: ignore[operator]
