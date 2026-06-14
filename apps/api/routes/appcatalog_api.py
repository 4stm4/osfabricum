"""Application Catalog Designer API (M41).

    GET  /v1/app-categories
    GET  /v1/app-catalog-profiles
    POST /v1/app-catalog-profiles
    GET  /v1/app-catalog-profiles/{profile_id}
    PATCH /v1/app-catalog-profiles/{profile_id}
    POST /v1/app-catalog-profiles/{profile_id}/apps
    POST /v1/app-catalog-profiles/{profile_id}/groups
    POST /v1/app-catalog-profiles/{profile_id}/groups/{group_name}/members
    POST /v1/app-catalog-profiles/{profile_id}/default-roles
    POST /v1/app-catalog-profiles/{profile_id}/render

Reads are public; mutations require auth (WriteAuthDep, G-24).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from osfabricum import appcatalog as ac
from osfabricum.security.auth_policy import WriteAuthDep

router = APIRouter(tags=["appcatalog"])


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
    description: str | None = None


class UpdateProfileRequest(BaseModel):
    description: str | None = None


class AddAppRequest(BaseModel):
    name: str
    display_name: str
    package_name: str
    description: str | None = None
    category_name: str = "utilities"
    version_constraint: str | None = None
    icon_name: str | None = None
    is_default_install: bool = True
    is_optional: bool = False
    tags: list[str] = []


class AddGroupRequest(BaseModel):
    name: str
    description: str | None = None
    is_default: bool = False


class AddGroupMemberRequest(BaseModel):
    app_name: str
    position: int = 0


class SetDefaultRoleRequest(BaseModel):
    role: str
    app_name: str
    package_name: str


# ---------------------------------------------------------------------------
# Categories (read-only)
# ---------------------------------------------------------------------------


@router.get("/v1/app-categories")
def list_categories(req: Request) -> list[dict]:
    return ac.list_app_categories(db_url=_db(req))


# ---------------------------------------------------------------------------
# Profile endpoints
# ---------------------------------------------------------------------------


@router.get("/v1/app-catalog-profiles")
def list_profiles(req: Request, distribution_id: str | None = None) -> list[dict]:
    return ac.list_catalog_profiles(distribution_id, db_url=_db(req))


@router.post("/v1/app-catalog-profiles", status_code=201)
def create_profile(
    body: CreateProfileRequest, req: Request, _auth: WriteAuthDep
) -> dict:
    try:
        return ac.create_catalog_profile(
            body.name,
            distribution_id=body.distribution_id,
            description=body.description,
            db_url=_db(req),
        )
    except ValueError as exc:
        raise _guard(exc) from exc


@router.get("/v1/app-catalog-profiles/{profile_id}")
def get_profile(profile_id: str, req: Request) -> dict:
    try:
        return ac.get_catalog_profile(profile_id, db_url=_db(req))
    except ValueError as exc:
        raise _guard(exc) from exc


@router.patch("/v1/app-catalog-profiles/{profile_id}")
def update_profile(
    profile_id: str, body: UpdateProfileRequest, req: Request, _auth: WriteAuthDep
) -> dict:
    try:
        return ac.update_catalog_profile(
            profile_id,
            description=body.description,
            db_url=_db(req),
        )
    except ValueError as exc:
        raise _guard(exc) from exc


# ---------------------------------------------------------------------------
# Apps
# ---------------------------------------------------------------------------


@router.post("/v1/app-catalog-profiles/{profile_id}/apps", status_code=201)
def add_app(
    profile_id: str, body: AddAppRequest, req: Request, _auth: WriteAuthDep
) -> dict:
    try:
        return ac.add_app(
            profile_id,
            body.name,
            body.display_name,
            body.package_name,
            description=body.description,
            category_name=body.category_name,
            version_constraint=body.version_constraint,
            icon_name=body.icon_name,
            is_default_install=body.is_default_install,
            is_optional=body.is_optional,
            tags=body.tags,
            db_url=_db(req),
        )
    except ValueError as exc:
        raise _guard(exc) from exc


# ---------------------------------------------------------------------------
# Groups
# ---------------------------------------------------------------------------


@router.post("/v1/app-catalog-profiles/{profile_id}/groups", status_code=201)
def add_group(
    profile_id: str, body: AddGroupRequest, req: Request, _auth: WriteAuthDep
) -> dict:
    try:
        return ac.add_group(
            profile_id,
            body.name,
            description=body.description,
            is_default=body.is_default,
            db_url=_db(req),
        )
    except ValueError as exc:
        raise _guard(exc) from exc


@router.post(
    "/v1/app-catalog-profiles/{profile_id}/groups/{group_name}/members",
    status_code=201,
)
def add_group_member(
    profile_id: str,
    group_name: str,
    body: AddGroupMemberRequest,
    req: Request,
    _auth: WriteAuthDep,
) -> dict:
    try:
        return ac.add_group_member(
            profile_id,
            group_name,
            body.app_name,
            position=body.position,
            db_url=_db(req),
        )
    except ValueError as exc:
        raise _guard(exc) from exc


# ---------------------------------------------------------------------------
# Default roles
# ---------------------------------------------------------------------------


@router.post("/v1/app-catalog-profiles/{profile_id}/default-roles", status_code=201)
def set_default_role(
    profile_id: str, body: SetDefaultRoleRequest, req: Request, _auth: WriteAuthDep
) -> dict:
    try:
        return ac.set_default_role(
            profile_id,
            body.role,
            body.app_name,
            body.package_name,
            db_url=_db(req),
        )
    except ValueError as exc:
        raise _guard(exc) from exc


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


@router.post("/v1/app-catalog-profiles/{profile_id}/render")
def render(profile_id: str, req: Request, _auth: WriteAuthDep) -> dict:
    try:
        return ac.render_app_list(profile_id, db_url=_db(req))
    except ValueError as exc:
        raise _guard(exc) from exc
