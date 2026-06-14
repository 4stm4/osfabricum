"""Graphical Shell Designer API (M40).

    GET  /v1/compositor-backends
    GET  /v1/display-manager-backends
    GET  /v1/graphical-profiles
    POST /v1/graphical-profiles
    GET  /v1/graphical-profiles/{profile_id}
    PATCH /v1/graphical-profiles/{profile_id}
    POST /v1/graphical-profiles/{profile_id}/components
    POST /v1/graphical-profiles/{profile_id}/sessions
    PATCH /v1/graphical-profiles/{profile_id}/sessions/{session_name}
    POST /v1/graphical-profiles/{profile_id}/render-session-config

Reads are public; mutations require auth (WriteAuthDep, G-24).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from osfabricum import graphical as gr
from osfabricum.security.auth_policy import WriteAuthDep

router = APIRouter(tags=["graphical"])


def _db(req: Request) -> str | None:
    try:
        return req.app.state.settings.database.url  # type: ignore[no-any-return]
    except AttributeError:
        return None


def _guard(exc: ValueError) -> HTTPException:
    return HTTPException(
        status_code=404 if "not found" in str(exc) else 400, detail=str(exc)
    )


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------


class CreateProfileRequest(BaseModel):
    name: str
    distribution_id: str | None = None
    display_server: str = "none"
    compositor: str | None = None
    display_manager: str | None = None
    session_manager: str | None = None
    toolkit_default: str | None = None


class UpdateProfileRequest(BaseModel):
    display_server: str | None = None
    compositor: str | None = None
    display_manager: str | None = None
    session_manager: str | None = None
    toolkit_default: str | None = None


class AddComponentRequest(BaseModel):
    component_kind: str
    package_name: str
    version_constraint: str | None = None
    config_fragment: dict[str, Any] | None = None
    is_required: bool = True


class AddSessionRequest(BaseModel):
    name: str
    session_type: str = "wayland"
    exec_cmd: str | None = None
    is_default: bool = False


class UpdateSessionRequest(BaseModel):
    exec_cmd: str | None = None
    is_default: bool | None = None


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------


@router.get("/v1/compositor-backends")
def list_compositor_backends(request: Request) -> list[dict[str, Any]]:
    """List all seeded compositor backends."""
    return gr.list_compositor_backends(db_url=_db(request))


@router.get("/v1/display-manager-backends")
def list_display_manager_backends(request: Request) -> list[dict[str, Any]]:
    """List all seeded display manager backends."""
    return gr.list_display_manager_backends(db_url=_db(request))


# ---------------------------------------------------------------------------
# Profile CRUD
# ---------------------------------------------------------------------------


@router.get("/v1/graphical-profiles")
def list_profiles(
    request: Request, distribution_id: str | None = None
) -> list[dict[str, Any]]:
    """List graphical profiles, optionally filtered by distribution."""
    return gr.list_graphical_profiles(distribution_id, db_url=_db(request))


@router.post("/v1/graphical-profiles", status_code=201)
def create_profile(
    body: CreateProfileRequest,
    request: Request,
    _auth: WriteAuthDep = None,
) -> dict[str, Any]:
    """Create a new graphical shell profile."""
    try:
        return gr.create_graphical_profile(
            body.name,
            distribution_id=body.distribution_id,
            display_server=body.display_server,
            compositor=body.compositor,
            display_manager=body.display_manager,
            session_manager=body.session_manager,
            toolkit_default=body.toolkit_default,
            db_url=_db(request),
        )
    except ValueError as exc:
        raise _guard(exc) from exc


@router.get("/v1/graphical-profiles/{profile_id}")
def get_profile(profile_id: str, request: Request) -> dict[str, Any]:
    """Return a full graphical profile including components and sessions."""
    try:
        return gr.get_graphical_profile(profile_id, db_url=_db(request))
    except ValueError as exc:
        raise _guard(exc) from exc


@router.patch("/v1/graphical-profiles/{profile_id}")
def update_profile(
    profile_id: str,
    body: UpdateProfileRequest,
    request: Request,
    _auth: WriteAuthDep = None,
) -> dict[str, Any]:
    """Update stack fields of a graphical profile."""
    try:
        return gr.update_graphical_profile(
            profile_id,
            display_server=body.display_server,
            compositor=body.compositor,
            display_manager=body.display_manager,
            session_manager=body.session_manager,
            toolkit_default=body.toolkit_default,
            db_url=_db(request),
        )
    except ValueError as exc:
        raise _guard(exc) from exc


# ---------------------------------------------------------------------------
# Components & Sessions
# ---------------------------------------------------------------------------


@router.post("/v1/graphical-profiles/{profile_id}/components", status_code=201)
def add_component(
    profile_id: str,
    body: AddComponentRequest,
    request: Request,
    _auth: WriteAuthDep = None,
) -> dict[str, Any]:
    """Add a component package to a graphical profile."""
    try:
        return gr.add_component(
            profile_id,
            body.component_kind,
            body.package_name,
            version_constraint=body.version_constraint,
            config_fragment=body.config_fragment,
            is_required=body.is_required,
            db_url=_db(request),
        )
    except ValueError as exc:
        raise _guard(exc) from exc


@router.post("/v1/graphical-profiles/{profile_id}/sessions", status_code=201)
def add_session(
    profile_id: str,
    body: AddSessionRequest,
    request: Request,
    _auth: WriteAuthDep = None,
) -> dict[str, Any]:
    """Register a session entry for a graphical profile."""
    try:
        return gr.add_session(
            profile_id,
            body.name,
            body.session_type,
            exec_cmd=body.exec_cmd,
            is_default=body.is_default,
            db_url=_db(request),
        )
    except ValueError as exc:
        raise _guard(exc) from exc


@router.patch("/v1/graphical-profiles/{profile_id}/sessions/{session_name}")
def update_session(
    profile_id: str,
    session_name: str,
    body: UpdateSessionRequest,
    request: Request,
    _auth: WriteAuthDep = None,
) -> dict[str, Any]:
    """Update a session entry."""
    try:
        return gr.update_session(
            profile_id,
            session_name,
            exec_cmd=body.exec_cmd,
            is_default=body.is_default,
            db_url=_db(request),
        )
    except ValueError as exc:
        raise _guard(exc) from exc


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


@router.post("/v1/graphical-profiles/{profile_id}/render-session-config", status_code=201)
def render_session_config(
    profile_id: str,
    request: Request,
    _auth: WriteAuthDep = None,
) -> dict[str, Any]:
    """Generate the .desktop session config and store the sha256: content hash."""
    try:
        return gr.render_session_config(profile_id, db_url=_db(request))
    except ValueError as exc:
        raise _guard(exc) from exc
