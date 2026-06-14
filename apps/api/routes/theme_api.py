"""Themes / Icons / Fonts Designer API (M43).

    GET  /v1/theme-asset-kinds
    GET  /v1/theme-profiles
    POST /v1/theme-profiles
    GET  /v1/theme-profiles/{profile_id}
    PATCH /v1/theme-profiles/{profile_id}
    POST /v1/theme-profiles/{profile_id}/packages
    POST /v1/theme-profiles/{profile_id}/gsettings
    GET  /v1/theme-profiles/{profile_id}/gsettings
    POST /v1/theme-profiles/{profile_id}/render

Reads are public; mutations require auth (WriteAuthDep, G-24).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from osfabricum import theme as th
from osfabricum.security.auth_policy import WriteAuthDep

router = APIRouter(tags=["theme"])


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
    gtk_theme: str = "Adwaita"
    icon_theme: str = "Adwaita"
    cursor_theme: str = "Adwaita"
    sound_theme: str = "freedesktop"
    dark_mode: bool = False
    font_default: str = "Sans"
    font_monospace: str = "Monospace"
    font_document: str = "Sans"
    font_size: int = 11
    cursor_size: int = 24
    scaling_factor: float = 1.0


class UpdateProfileRequest(BaseModel):
    gtk_theme: str | None = None
    icon_theme: str | None = None
    cursor_theme: str | None = None
    sound_theme: str | None = None
    dark_mode: bool | None = None
    font_default: str | None = None
    font_monospace: str | None = None
    font_document: str | None = None
    font_size: int | None = None
    cursor_size: int | None = None
    scaling_factor: float | None = None


class AddPackageRequest(BaseModel):
    asset_kind: str
    package_name: str
    version_constraint: str | None = None
    is_default: bool = False


class SetGsettingsRequest(BaseModel):
    schema: str
    key: str
    value: str
    description: str | None = None


# ---------------------------------------------------------------------------
# Asset kinds (read-only)
# ---------------------------------------------------------------------------


@router.get("/v1/theme-asset-kinds")
def list_asset_kinds(req: Request) -> list[dict]:
    return th.list_theme_asset_kinds(db_url=_db(req))


# ---------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------


@router.get("/v1/theme-profiles")
def list_profiles(req: Request, distribution_id: str | None = None) -> list[dict]:
    return th.list_theme_profiles(distribution_id, db_url=_db(req))


@router.post("/v1/theme-profiles", status_code=201)
def create_profile(
    body: CreateProfileRequest, req: Request, _auth: WriteAuthDep
) -> dict:
    try:
        return th.create_theme_profile(
            body.name,
            distribution_id=body.distribution_id,
            gtk_theme=body.gtk_theme,
            icon_theme=body.icon_theme,
            cursor_theme=body.cursor_theme,
            sound_theme=body.sound_theme,
            dark_mode=body.dark_mode,
            font_default=body.font_default,
            font_monospace=body.font_monospace,
            font_document=body.font_document,
            font_size=body.font_size,
            cursor_size=body.cursor_size,
            scaling_factor=body.scaling_factor,
            db_url=_db(req),
        )
    except ValueError as exc:
        raise _guard(exc) from exc


@router.get("/v1/theme-profiles/{profile_id}")
def get_profile(profile_id: str, req: Request) -> dict:
    try:
        return th.get_theme_profile(profile_id, db_url=_db(req))
    except ValueError as exc:
        raise _guard(exc) from exc


@router.patch("/v1/theme-profiles/{profile_id}")
def update_profile(
    profile_id: str, body: UpdateProfileRequest, req: Request, _auth: WriteAuthDep
) -> dict:
    try:
        return th.update_theme_profile(
            profile_id,
            gtk_theme=body.gtk_theme,
            icon_theme=body.icon_theme,
            cursor_theme=body.cursor_theme,
            sound_theme=body.sound_theme,
            dark_mode=body.dark_mode,
            font_default=body.font_default,
            font_monospace=body.font_monospace,
            font_document=body.font_document,
            font_size=body.font_size,
            cursor_size=body.cursor_size,
            scaling_factor=body.scaling_factor,
            db_url=_db(req),
        )
    except ValueError as exc:
        raise _guard(exc) from exc


# ---------------------------------------------------------------------------
# Packages
# ---------------------------------------------------------------------------


@router.post("/v1/theme-profiles/{profile_id}/packages", status_code=201)
def add_package(
    profile_id: str, body: AddPackageRequest, req: Request, _auth: WriteAuthDep
) -> dict:
    try:
        return th.add_theme_package(
            profile_id,
            body.asset_kind,
            body.package_name,
            version_constraint=body.version_constraint,
            is_default=body.is_default,
            db_url=_db(req),
        )
    except ValueError as exc:
        raise _guard(exc) from exc


# ---------------------------------------------------------------------------
# GSettings overrides
# ---------------------------------------------------------------------------


@router.get("/v1/theme-profiles/{profile_id}/gsettings")
def get_gsettings(profile_id: str, req: Request) -> list[dict]:
    try:
        detail = th.get_theme_profile(profile_id, db_url=_db(req))
    except ValueError as exc:
        raise _guard(exc) from exc
    return detail["gsettings"]


@router.post("/v1/theme-profiles/{profile_id}/gsettings", status_code=201)
def set_gsettings(
    profile_id: str, body: SetGsettingsRequest, req: Request, _auth: WriteAuthDep
) -> dict:
    try:
        return th.set_gsettings_override(
            profile_id,
            body.schema,
            body.key,
            body.value,
            description=body.description,
            db_url=_db(req),
        )
    except ValueError as exc:
        raise _guard(exc) from exc


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


@router.post("/v1/theme-profiles/{profile_id}/render")
def render(profile_id: str, req: Request, _auth: WriteAuthDep) -> dict:
    try:
        return th.render_theme_config(profile_id, db_url=_db(req))
    except ValueError as exc:
        raise _guard(exc) from exc
