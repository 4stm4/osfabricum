"""Desktop Integration Designer API (M42).

    GET  /v1/mime-types
    GET  /v1/desktop-integration-profiles
    POST /v1/desktop-integration-profiles
    GET  /v1/desktop-integration-profiles/{profile_id}
    PATCH /v1/desktop-integration-profiles/{profile_id}
    POST /v1/desktop-integration-profiles/{profile_id}/mime-associations
    POST /v1/desktop-integration-profiles/{profile_id}/autostart
    POST /v1/desktop-integration-profiles/{profile_id}/user-dirs
    POST /v1/desktop-integration-profiles/{profile_id}/render

Reads are public; mutations require auth (WriteAuthDep, G-24).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from osfabricum import desktopint as di
from osfabricum.security.auth_policy import WriteAuthDep

router = APIRouter(tags=["desktopint"])


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
    xdg_data_dirs: list[str] = []
    xdg_config_dirs: list[str] = []


class UpdateProfileRequest(BaseModel):
    xdg_data_dirs: list[str] | None = None
    xdg_config_dirs: list[str] | None = None


class AddMimeAssociationRequest(BaseModel):
    mime_type: str
    desktop_file: str
    association_type: str = "default"
    priority: int = 0


class AddAutostartRequest(BaseModel):
    name: str
    exec_cmd: str
    comment: str | None = None
    condition: str = "always"
    is_enabled: bool = True


class SetUserDirRequest(BaseModel):
    dir_name: str
    path: str


# ---------------------------------------------------------------------------
# MIME type reference (read-only)
# ---------------------------------------------------------------------------


@router.get("/v1/mime-types")
def list_mime_types(req: Request) -> list[dict]:
    return di.list_mime_types(db_url=_db(req))


# ---------------------------------------------------------------------------
# Profile endpoints
# ---------------------------------------------------------------------------


@router.get("/v1/desktop-integration-profiles")
def list_profiles(req: Request, distribution_id: str | None = None) -> list[dict]:
    return di.list_desktop_integration_profiles(distribution_id, db_url=_db(req))


@router.post("/v1/desktop-integration-profiles", status_code=201)
def create_profile(
    body: CreateProfileRequest, req: Request, _auth: WriteAuthDep
) -> dict:
    try:
        return di.create_desktop_integration_profile(
            body.name,
            distribution_id=body.distribution_id,
            xdg_data_dirs=body.xdg_data_dirs,
            xdg_config_dirs=body.xdg_config_dirs,
            db_url=_db(req),
        )
    except ValueError as exc:
        raise _guard(exc) from exc


@router.get("/v1/desktop-integration-profiles/{profile_id}")
def get_profile(profile_id: str, req: Request) -> dict:
    try:
        return di.get_desktop_integration_profile(profile_id, db_url=_db(req))
    except ValueError as exc:
        raise _guard(exc) from exc


@router.patch("/v1/desktop-integration-profiles/{profile_id}")
def update_profile(
    profile_id: str, body: UpdateProfileRequest, req: Request, _auth: WriteAuthDep
) -> dict:
    try:
        return di.update_desktop_integration_profile(
            profile_id,
            xdg_data_dirs=body.xdg_data_dirs,
            xdg_config_dirs=body.xdg_config_dirs,
            db_url=_db(req),
        )
    except ValueError as exc:
        raise _guard(exc) from exc


# ---------------------------------------------------------------------------
# MIME associations
# ---------------------------------------------------------------------------


@router.post(
    "/v1/desktop-integration-profiles/{profile_id}/mime-associations", status_code=201
)
def add_mime_association(
    profile_id: str, body: AddMimeAssociationRequest, req: Request, _auth: WriteAuthDep
) -> dict:
    try:
        return di.add_mime_association(
            profile_id,
            body.mime_type,
            body.desktop_file,
            association_type=body.association_type,
            priority=body.priority,
            db_url=_db(req),
        )
    except ValueError as exc:
        raise _guard(exc) from exc


# ---------------------------------------------------------------------------
# Autostart
# ---------------------------------------------------------------------------


@router.post(
    "/v1/desktop-integration-profiles/{profile_id}/autostart", status_code=201
)
def add_autostart(
    profile_id: str, body: AddAutostartRequest, req: Request, _auth: WriteAuthDep
) -> dict:
    try:
        return di.add_autostart_entry(
            profile_id,
            body.name,
            body.exec_cmd,
            comment=body.comment,
            condition=body.condition,
            is_enabled=body.is_enabled,
            db_url=_db(req),
        )
    except ValueError as exc:
        raise _guard(exc) from exc


# ---------------------------------------------------------------------------
# User directories
# ---------------------------------------------------------------------------


@router.post(
    "/v1/desktop-integration-profiles/{profile_id}/user-dirs", status_code=201
)
def set_user_dir(
    profile_id: str, body: SetUserDirRequest, req: Request, _auth: WriteAuthDep
) -> dict:
    try:
        return di.set_user_dir(
            profile_id, body.dir_name, body.path, db_url=_db(req)
        )
    except ValueError as exc:
        raise _guard(exc) from exc


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


@router.post("/v1/desktop-integration-profiles/{profile_id}/render")
def render(profile_id: str, req: Request, _auth: WriteAuthDep) -> dict:
    try:
        return di.render_desktop_integration(profile_id, db_url=_db(req))
    except ValueError as exc:
        raise _guard(exc) from exc
