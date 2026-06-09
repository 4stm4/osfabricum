"""Runtime Package Policy API (M38).

    GET  /v1/runtime-package-backends
    GET  /v1/profiles/{distribution}/{name}/runtime-policy
    POST /v1/profiles/{distribution}/{name}/runtime-policy
    POST /v1/profiles/{distribution}/{name}/runtime-policy/render

Reads are public; mutations require auth (WriteAuthDep, G-24).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from osfabricum import packagepolicy as pp
from osfabricum import profile as profile_svc
from osfabricum.security.auth_policy import WriteAuthDep

router = APIRouter(tags=["package-policy"])


def _db(req: Request) -> str | None:
    try:
        return req.app.state.settings.database.url  # type: ignore[no-any-return]
    except AttributeError:
        return None


def _guard(exc: ValueError) -> HTTPException:
    return HTTPException(status_code=404 if "not found" in str(exc) else 400, detail=str(exc))


class PolicyRequest(BaseModel):
    policy: str
    backend_name: str = "none"
    feed_ids: list[str] = []
    config_path: str = "/etc/package-manager.conf"


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------


@router.get("/v1/runtime-package-backends")
def list_backends(request: Request) -> list[dict[str, Any]]:
    """List all seeded runtime package manager backends."""
    return pp.list_backends(db_url=_db(request))


# ---------------------------------------------------------------------------
# Per-profile policy
# ---------------------------------------------------------------------------


@router.get("/v1/profiles/{distribution}/{name}/runtime-policy")
def get_runtime_policy(distribution: str, name: str, request: Request) -> dict[str, Any]:
    """Get the runtime package policy for a profile."""
    try:
        p = profile_svc.get_profile(distribution, name, db_url=_db(request))
        return pp.get_policy(p["id"], db_url=_db(request))
    except ValueError as exc:
        raise _guard(exc) from exc


@router.post("/v1/profiles/{distribution}/{name}/runtime-policy", status_code=201)
def set_runtime_policy(
    distribution: str,
    name: str,
    body: PolicyRequest,
    request: Request,
    _auth: WriteAuthDep = None,
) -> dict[str, Any]:
    """Create or update the runtime package policy for a profile."""
    try:
        p = profile_svc.get_profile(distribution, name, db_url=_db(request))
        return pp.set_policy(
            p["id"],
            body.policy,
            body.backend_name,
            feed_ids=body.feed_ids,
            config_path=body.config_path,
            db_url=_db(request),
        )
    except ValueError as exc:
        raise _guard(exc) from exc


@router.post("/v1/profiles/{distribution}/{name}/runtime-policy/render", status_code=201)
def render_runtime_policy(
    distribution: str,
    name: str,
    request: Request,
    _auth: WriteAuthDep = None,
) -> dict[str, Any]:
    """Render the package-manager config for a profile's runtime policy."""
    try:
        p = profile_svc.get_profile(distribution, name, db_url=_db(request))
        return pp.render_policy(p["id"], db_url=_db(request))
    except ValueError as exc:
        raise _guard(exc) from exc
