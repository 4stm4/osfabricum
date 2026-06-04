"""API token authentication middleware (M14, refined for G-24).

Authorization model:

* **Read endpoints are public.** Browsing the catalog, plans, builds, etc. needs
  no credentials.
* **Write endpoints enforce auth per-endpoint** via ``WriteAuthDep``
  (``osfabricum.security.auth_policy``) — POST/PATCH/DELETE require a bearer
  token when ``AuthSettings.enabled`` is ``True``.
* **This middleware guards only admin/internal surfaces** (``/internal/*``) —
  e.g. the queue dashboard — so they are never world-readable.

Health/monitoring endpoints (``/healthz``, ``/readyz``, ``/metrics``) and the
static UI are always public.

The expected token is read from (in priority order):
1. ``OSFABRICUM_API_TOKEN`` environment variable
2. ``auth.token`` field in the TOML config file

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

#: Path prefixes that REQUIRE a bearer token when auth is enabled. Everything
#: else is public at the middleware level; write endpoints add their own
#: per-endpoint check (WriteAuthDep, G-24).
_PROTECTED_PREFIXES: tuple[str, ...] = ("/internal/",)


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
    """Starlette middleware that protects admin/internal endpoints.

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
        # Only admin/internal paths are guarded here; reads are public and
        # writes are guarded per-endpoint (WriteAuthDep).
        if not request.url.path.startswith(_PROTECTED_PREFIXES):
            return await call_next(request)  # type: ignore[operator]

        expected = _get_expected_token(self._settings)
        if expected is None:
            # Auth is enabled but no token configured → refuse protected requests
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
