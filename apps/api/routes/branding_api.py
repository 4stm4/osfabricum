"""Branding / Identity Designer API (M39).

    GET    /v1/branding-profiles
    POST   /v1/branding-profiles
    GET    /v1/branding-profiles/{profile_id}
    PATCH  /v1/branding-profiles/{profile_id}
    POST   /v1/branding-profiles/{profile_id}/assets
    POST   /v1/branding-profiles/{profile_id}/targets/{stage}
    POST   /v1/branding-profiles/{profile_id}/render-os-release
    POST   /v1/branding-profiles/{profile_id}/render-motd
    POST   /v1/branding-profiles/{profile_id}/boot-splash
    POST   /v1/branding-profiles/{profile_id}/login-theme
    POST   /v1/branding-profiles/{profile_id}/wallpapers
    POST   /v1/branding-profiles/{profile_id}/os-release-template
    POST   /v1/branding-profiles/{profile_id}/motd-template

Reads are public; mutations require auth (WriteAuthDep, G-24).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from osfabricum import branding as br
from osfabricum.security.auth_policy import WriteAuthDep

router = APIRouter(tags=["branding"])


def _db(req: Request) -> str | None:
    try:
        return req.app.state.settings.database.url  # type: ignore[no-any-return]
    except AttributeError:
        return None


def _guard(exc: ValueError) -> HTTPException:
    return HTTPException(status_code=404 if "not found" in str(exc) else 400, detail=str(exc))


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------


class CreateProfileRequest(BaseModel):
    name: str
    distribution_id: str | None = None
    os_name: str | None = None
    os_id: str | None = None
    os_version: str | None = None
    os_pretty_name: str | None = None
    os_home_url: str | None = None
    vendor_name: str | None = None
    vendor_url: str | None = None
    support_url: str | None = None
    bug_report_url: str | None = None


class UpdateProfileRequest(BaseModel):
    os_name: str | None = None
    os_id: str | None = None
    os_version: str | None = None
    os_pretty_name: str | None = None
    os_home_url: str | None = None
    vendor_name: str | None = None
    vendor_url: str | None = None
    support_url: str | None = None
    bug_report_url: str | None = None


class AddAssetRequest(BaseModel):
    name: str
    asset_kind: str
    source_path: str | None = None
    mime_type: str | None = None
    width_px: int | None = None
    height_px: int | None = None


class SetTargetRequest(BaseModel):
    asset_id: str | None = None
    config: dict[str, Any] | None = None


class BootSplashRequest(BaseModel):
    theme_name: str = "spinner"
    package_name: str | None = None
    config: dict[str, Any] | None = None


class LoginThemeRequest(BaseModel):
    theme_name: str
    display_manager: str | None = None
    config: dict[str, Any] | None = None


class AddWallpaperRequest(BaseModel):
    name: str
    resolution: str | None = None
    asset_id: str | None = None
    is_default: bool = False


class TemplateRequest(BaseModel):
    template_text: str


# ---------------------------------------------------------------------------
# Profile CRUD
# ---------------------------------------------------------------------------


@router.get("/v1/branding-profiles")
def list_profiles(request: Request, distribution_id: str | None = None) -> list[dict[str, Any]]:
    """List all branding profiles, optionally filtered by distribution."""
    return br.list_branding_profiles(distribution_id, db_url=_db(request))


@router.post("/v1/branding-profiles", status_code=201)
def create_profile(
    body: CreateProfileRequest,
    request: Request,
    _auth: WriteAuthDep = None,
) -> dict[str, Any]:
    """Create a new branding profile."""
    try:
        return br.create_branding_profile(
            body.name,
            distribution_id=body.distribution_id,
            os_name=body.os_name,
            os_id=body.os_id,
            os_version=body.os_version,
            os_pretty_name=body.os_pretty_name,
            os_home_url=body.os_home_url,
            vendor_name=body.vendor_name,
            vendor_url=body.vendor_url,
            support_url=body.support_url,
            bug_report_url=body.bug_report_url,
            db_url=_db(request),
        )
    except ValueError as exc:
        raise _guard(exc) from exc


@router.get("/v1/branding-profiles/{profile_id}")
def get_profile(profile_id: str, request: Request) -> dict[str, Any]:
    """Return a full branding profile including assets, targets, and themes."""
    try:
        return br.get_branding_profile(profile_id, db_url=_db(request))
    except ValueError as exc:
        raise _guard(exc) from exc


@router.patch("/v1/branding-profiles/{profile_id}")
def update_profile(
    profile_id: str,
    body: UpdateProfileRequest,
    request: Request,
    _auth: WriteAuthDep = None,
) -> dict[str, Any]:
    """Update identity fields of a branding profile."""
    try:
        return br.update_branding_profile(
            profile_id,
            os_name=body.os_name,
            os_id=body.os_id,
            os_version=body.os_version,
            os_pretty_name=body.os_pretty_name,
            os_home_url=body.os_home_url,
            vendor_name=body.vendor_name,
            vendor_url=body.vendor_url,
            support_url=body.support_url,
            bug_report_url=body.bug_report_url,
            db_url=_db(request),
        )
    except ValueError as exc:
        raise _guard(exc) from exc


# ---------------------------------------------------------------------------
# Assets & Targets
# ---------------------------------------------------------------------------


@router.post("/v1/branding-profiles/{profile_id}/assets", status_code=201)
def add_asset(
    profile_id: str,
    body: AddAssetRequest,
    request: Request,
    _auth: WriteAuthDep = None,
) -> dict[str, Any]:
    """Attach a branding asset to a profile."""
    try:
        return br.add_asset(
            profile_id,
            body.name,
            body.asset_kind,
            source_path=body.source_path,
            mime_type=body.mime_type,
            width_px=body.width_px,
            height_px=body.height_px,
            db_url=_db(request),
        )
    except ValueError as exc:
        raise _guard(exc) from exc


@router.post("/v1/branding-profiles/{profile_id}/targets/{stage}", status_code=201)
def set_target(
    profile_id: str,
    stage: str,
    body: SetTargetRequest,
    request: Request,
    _auth: WriteAuthDep = None,
) -> dict[str, Any]:
    """Set the asset/config for a build stage."""
    try:
        return br.set_target(
            profile_id,
            stage,
            asset_id=body.asset_id,
            config_json=body.config,
            db_url=_db(request),
        )
    except ValueError as exc:
        raise _guard(exc) from exc


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


@router.post("/v1/branding-profiles/{profile_id}/render-os-release", status_code=201)
def render_os_release(
    profile_id: str,
    request: Request,
    _auth: WriteAuthDep = None,
) -> dict[str, Any]:
    """Generate /etc/os-release from profile identity fields."""
    try:
        return br.render_os_release(profile_id, db_url=_db(request))
    except ValueError as exc:
        raise _guard(exc) from exc


@router.post("/v1/branding-profiles/{profile_id}/render-motd", status_code=201)
def render_motd(
    profile_id: str,
    request: Request,
    _auth: WriteAuthDep = None,
) -> dict[str, Any]:
    """Render /etc/motd from template or default."""
    try:
        return br.render_motd(profile_id, db_url=_db(request))
    except ValueError as exc:
        raise _guard(exc) from exc


# ---------------------------------------------------------------------------
# Plymouth / Login / Wallpapers
# ---------------------------------------------------------------------------


@router.post("/v1/branding-profiles/{profile_id}/boot-splash", status_code=201)
def set_boot_splash(
    profile_id: str,
    body: BootSplashRequest,
    request: Request,
    _auth: WriteAuthDep = None,
) -> dict[str, Any]:
    """Set the Plymouth theme for a branding profile."""
    try:
        return br.set_boot_splash(
            profile_id,
            body.theme_name,
            package_name=body.package_name,
            config_json=body.config,
            db_url=_db(request),
        )
    except ValueError as exc:
        raise _guard(exc) from exc


@router.post("/v1/branding-profiles/{profile_id}/login-theme", status_code=201)
def set_login_theme(
    profile_id: str,
    body: LoginThemeRequest,
    request: Request,
    _auth: WriteAuthDep = None,
) -> dict[str, Any]:
    """Set the display-manager greeter theme."""
    try:
        return br.set_login_theme(
            profile_id,
            body.theme_name,
            display_manager=body.display_manager,
            config_json=body.config,
            db_url=_db(request),
        )
    except ValueError as exc:
        raise _guard(exc) from exc


@router.post("/v1/branding-profiles/{profile_id}/wallpapers", status_code=201)
def add_wallpaper(
    profile_id: str,
    body: AddWallpaperRequest,
    request: Request,
    _auth: WriteAuthDep = None,
) -> dict[str, Any]:
    """Add a wallpaper entry at a resolution."""
    try:
        return br.add_wallpaper(
            profile_id,
            body.name,
            resolution=body.resolution,
            asset_id=body.asset_id,
            is_default=body.is_default,
            db_url=_db(request),
        )
    except ValueError as exc:
        raise _guard(exc) from exc


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------


@router.post("/v1/branding-profiles/{profile_id}/os-release-template", status_code=201)
def set_os_release_template(
    profile_id: str,
    body: TemplateRequest,
    request: Request,
    _auth: WriteAuthDep = None,
) -> dict[str, Any]:
    """Set a custom /etc/os-release template."""
    try:
        return br.set_os_release_template(profile_id, body.template_text, db_url=_db(request))
    except ValueError as exc:
        raise _guard(exc) from exc


@router.post("/v1/branding-profiles/{profile_id}/motd-template", status_code=201)
def set_motd_template(
    profile_id: str,
    body: TemplateRequest,
    request: Request,
    _auth: WriteAuthDep = None,
) -> dict[str, Any]:
    """Set a custom /etc/motd template."""
    try:
        return br.set_motd_template(profile_id, body.template_text, db_url=_db(request))
    except ValueError as exc:
        raise _guard(exc) from exc
