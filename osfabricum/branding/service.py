"""Branding / Identity Designer service (M39).

Branding is a first-class subsystem — not "just a wallpaper".  Every field that
ends up in ``/etc/os-release``, every splash screen, login theme, wallpaper and
MOTD is a *record*, not a hard-coded string in a build script.

Key functions:

* :func:`create_branding_profile` / :func:`update_branding_profile` — CRUD.
* :func:`add_asset` — attach a logo/icon/wallpaper/splash/font asset.
* :func:`set_target` — map a build stage to an asset or config.
* :func:`render_os_release` — generate ``/etc/os-release`` from profile fields
  (deterministic sha256 hash, same pattern as ``plan_hash``).
* :func:`render_motd` — generate ``/etc/motd`` from the attached template.
* :func:`set_boot_splash` / :func:`set_login_theme` — Plymouth + DM config.
* :func:`set_wallpaper` — add wallpaper entry at a resolution.
"""

from __future__ import annotations

import hashlib
from datetime import UTC
from datetime import datetime as _dt
from typing import Any

from sqlalchemy import select

from osfabricum.db.models import (
    BootSplashTheme,
    BrandingAsset,
    BrandingProfile,
    BrandingTarget,
    LoginScreenTheme,
    MotdTemplate,
    OsReleaseTemplate,
    WallpaperSet,
)
from osfabricum.db.session import sync_session

ASSET_KINDS = (
    "logo",
    "icon",
    "favicon",
    "wallpaper",
    "splash",
    "login-bg",
    "font",
    "sound",
)

BRANDING_STAGES = (
    "bootloader",
    "plymouth",
    "initramfs",
    "login-screen",
    "desktop-session",
    "os-release",
    "motd",
    "about-dialog",
    "web-ui",
    "installer",
)


def _now() -> _dt:
    return _dt.now(UTC).replace(tzinfo=None)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _profile_to_dict(p: BrandingProfile) -> dict[str, Any]:
    return {
        "id": p.id,
        "name": p.name,
        "distribution_id": p.distribution_id,
        "os_name": p.os_name,
        "os_id": p.os_id,
        "os_version": p.os_version,
        "os_pretty_name": p.os_pretty_name,
        "os_home_url": p.os_home_url,
        "vendor_name": p.vendor_name,
        "vendor_url": p.vendor_url,
        "support_url": p.support_url,
        "bug_report_url": p.bug_report_url,
        "logo_asset_id": p.logo_asset_id,
        "icon_asset_id": p.icon_asset_id,
        "rendered_os_release": p.rendered_os_release,
        "rendered_motd": p.rendered_motd,
        "content_hash": p.content_hash,
        "rendered_at": p.rendered_at.isoformat() if p.rendered_at else None,
    }


# ---------------------------------------------------------------------------
# Profile CRUD
# ---------------------------------------------------------------------------


def create_branding_profile(
    name: str,
    *,
    distribution_id: str | None = None,
    os_name: str | None = None,
    os_id: str | None = None,
    os_version: str | None = None,
    os_pretty_name: str | None = None,
    os_home_url: str | None = None,
    vendor_name: str | None = None,
    vendor_url: str | None = None,
    support_url: str | None = None,
    bug_report_url: str | None = None,
    db_url: str | None = None,
) -> dict[str, Any]:
    """Create a new branding profile."""
    now = _now()
    with sync_session(db_url) as s:
        existing = s.scalars(
            select(BrandingProfile).where(
                BrandingProfile.distribution_id == distribution_id,
                BrandingProfile.name == name,
            )
        ).first()
        if existing is not None:
            raise ValueError(f"branding profile already exists: {name!r}")
        p = BrandingProfile(
            name=name,
            distribution_id=distribution_id,
            os_name=os_name,
            os_id=os_id,
            os_version=os_version,
            os_pretty_name=os_pretty_name or (f"{os_name} {os_version}" if os_name else None),
            os_home_url=os_home_url,
            vendor_name=vendor_name,
            vendor_url=vendor_url,
            support_url=support_url,
            bug_report_url=bug_report_url,
            created_at=now,
            updated_at=now,
        )
        s.add(p)
        s.commit()
        return _profile_to_dict(p)


def update_branding_profile(
    profile_id: str,
    *,
    os_name: str | None = None,
    os_id: str | None = None,
    os_version: str | None = None,
    os_pretty_name: str | None = None,
    os_home_url: str | None = None,
    vendor_name: str | None = None,
    vendor_url: str | None = None,
    support_url: str | None = None,
    bug_report_url: str | None = None,
    db_url: str | None = None,
) -> dict[str, Any]:
    """Update identity fields; clears rendered cache."""
    with sync_session(db_url) as s:
        p = s.get(BrandingProfile, profile_id)
        if p is None:
            raise ValueError(f"branding profile not found: {profile_id!r}")
        if os_name is not None:
            p.os_name = os_name
        if os_id is not None:
            p.os_id = os_id
        if os_version is not None:
            p.os_version = os_version
        if os_pretty_name is not None:
            p.os_pretty_name = os_pretty_name
        if os_home_url is not None:
            p.os_home_url = os_home_url
        if vendor_name is not None:
            p.vendor_name = vendor_name
        if vendor_url is not None:
            p.vendor_url = vendor_url
        if support_url is not None:
            p.support_url = support_url
        if bug_report_url is not None:
            p.bug_report_url = bug_report_url
        # Invalidate rendered cache
        p.rendered_os_release = None
        p.content_hash = None
        p.rendered_at = None
        p.updated_at = _now()
        s.commit()
        return _profile_to_dict(p)


def list_branding_profiles(
    distribution_id: str | None = None,
    *,
    db_url: str | None = None,
) -> list[dict[str, Any]]:
    with sync_session(db_url) as s:
        q = select(BrandingProfile).order_by(BrandingProfile.name)
        if distribution_id is not None:
            q = q.where(BrandingProfile.distribution_id == distribution_id)
        return [_profile_to_dict(p) for p in s.scalars(q).all()]


def get_branding_profile(profile_id: str, *, db_url: str | None = None) -> dict[str, Any]:
    """Return full profile including assets, targets, templates."""
    with sync_session(db_url) as s:
        p = s.get(BrandingProfile, profile_id)
        if p is None:
            raise ValueError(f"branding profile not found: {profile_id!r}")
        result = _profile_to_dict(p)

        result["assets"] = [
            {
                "id": a.id,
                "name": a.name,
                "asset_kind": a.asset_kind,
                "source_path": a.source_path,
                "mime_type": a.mime_type,
                "width_px": a.width_px,
                "height_px": a.height_px,
            }
            for a in s.scalars(
                select(BrandingAsset).where(BrandingAsset.branding_profile_id == profile_id)
            ).all()
        ]
        result["targets"] = [
            {"id": t.id, "stage": t.stage, "asset_id": t.asset_id, "config": t.config_json}
            for t in s.scalars(
                select(BrandingTarget).where(BrandingTarget.branding_profile_id == profile_id)
            ).all()
        ]
        splash = s.scalars(
            select(BootSplashTheme).where(BootSplashTheme.branding_profile_id == profile_id)
        ).first()
        result["boot_splash"] = (
            {"theme_name": splash.theme_name, "package_name": splash.package_name}
            if splash
            else None
        )
        login = s.scalars(
            select(LoginScreenTheme).where(LoginScreenTheme.branding_profile_id == profile_id)
        ).first()
        result["login_theme"] = (
            {"theme_name": login.theme_name, "display_manager": login.display_manager}
            if login
            else None
        )
        result["wallpapers"] = [
            {
                "id": w.id,
                "name": w.name,
                "resolution": w.resolution,
                "is_default": w.is_default,
                "asset_id": w.asset_id,
            }
            for w in s.scalars(
                select(WallpaperSet).where(WallpaperSet.branding_profile_id == profile_id)
            ).all()
        ]
        return result


# ---------------------------------------------------------------------------
# Assets & Targets
# ---------------------------------------------------------------------------


def add_asset(
    profile_id: str,
    name: str,
    asset_kind: str,
    *,
    source_path: str | None = None,
    mime_type: str | None = None,
    width_px: int | None = None,
    height_px: int | None = None,
    db_url: str | None = None,
) -> dict[str, Any]:
    """Attach a branding asset to a profile."""
    if asset_kind not in ASSET_KINDS:
        raise ValueError(f"unknown asset_kind {asset_kind!r}; valid: {', '.join(ASSET_KINDS)}")
    with sync_session(db_url) as s:
        if s.get(BrandingProfile, profile_id) is None:
            raise ValueError(f"branding profile not found: {profile_id!r}")
        asset = BrandingAsset(
            branding_profile_id=profile_id,
            name=name,
            asset_kind=asset_kind,
            source_path=source_path,
            mime_type=mime_type,
            width_px=width_px,
            height_px=height_px,
        )
        s.add(asset)
        s.commit()
        return {
            "id": asset.id,
            "branding_profile_id": profile_id,
            "name": name,
            "asset_kind": asset_kind,
        }


def set_target(
    profile_id: str,
    stage: str,
    *,
    asset_id: str | None = None,
    config_json: dict[str, Any] | None = None,
    db_url: str | None = None,
) -> dict[str, Any]:
    """Set (upsert) the asset/config for a build stage."""
    if stage not in BRANDING_STAGES:
        raise ValueError(f"unknown stage {stage!r}; valid: {', '.join(BRANDING_STAGES)}")
    with sync_session(db_url) as s:
        if s.get(BrandingProfile, profile_id) is None:
            raise ValueError(f"branding profile not found: {profile_id!r}")
        existing = s.scalars(
            select(BrandingTarget).where(
                BrandingTarget.branding_profile_id == profile_id,
                BrandingTarget.stage == stage,
            )
        ).first()
        if existing is not None:
            existing.asset_id = asset_id
            existing.config_json = config_json
        else:
            existing = BrandingTarget(
                branding_profile_id=profile_id,
                stage=stage,
                asset_id=asset_id,
                config_json=config_json,
            )
            s.add(existing)
        s.commit()
        return {"id": existing.id, "profile_id": profile_id, "stage": stage, "asset_id": asset_id}


# ---------------------------------------------------------------------------
# Render — os-release, motd
# ---------------------------------------------------------------------------

_OS_RELEASE_TEMPLATE = """\
NAME="{os_name}"
VERSION="{os_version}"
ID={os_id}
ID_LIKE=linux
PRETTY_NAME="{os_pretty_name}"
HOME_URL="{os_home_url}"
SUPPORT_URL="{support_url}"
BUG_REPORT_URL="{bug_report_url}"
"""


def render_os_release(profile_id: str, *, db_url: str | None = None) -> dict[str, Any]:
    """Generate ``/etc/os-release`` content from profile identity fields.

    The output is deterministic — same inputs always produce the same text.
    A ``sha256:`` content hash is stored alongside the rendered text, matching
    the ``plan_hash`` / ``index_hash`` convention used throughout OSFabricum.
    """
    with sync_session(db_url) as s:
        p = s.get(BrandingProfile, profile_id)
        if p is None:
            raise ValueError(f"branding profile not found: {profile_id!r}")

        # Check for a custom template first
        custom = s.scalars(
            select(OsReleaseTemplate).where(
                OsReleaseTemplate.branding_profile_id == profile_id
            )
        ).first()

        if custom is not None:
            rendered = custom.template_text.format(
                os_name=p.os_name or "",
                os_id=(p.os_id or "").lower().replace(" ", "-"),
                os_version=p.os_version or "",
                os_pretty_name=p.os_pretty_name or p.os_name or "",
                os_home_url=p.os_home_url or "",
                vendor_name=p.vendor_name or "",
                support_url=p.support_url or "",
                bug_report_url=p.bug_report_url or "",
            )
            custom.rendered_text = rendered
            custom.rendered_at = _now()
        else:
            rendered = _OS_RELEASE_TEMPLATE.format(
                os_name=p.os_name or "",
                os_id=(p.os_id or "").lower().replace(" ", "-"),
                os_version=p.os_version or "",
                os_pretty_name=p.os_pretty_name or p.os_name or "",
                os_home_url=p.os_home_url or "",
                support_url=p.support_url or "",
                bug_report_url=p.bug_report_url or "",
            )

        content_hash = "sha256:" + _sha(rendered)
        now = _now()
        p.rendered_os_release = rendered
        p.content_hash = content_hash
        p.rendered_at = now
        p.updated_at = now
        s.commit()

        return {
            "profile_id": profile_id,
            "rendered_os_release": rendered,
            "content_hash": content_hash,
            "rendered_at": now.isoformat(),
        }


def render_motd(profile_id: str, *, db_url: str | None = None) -> dict[str, Any]:
    """Render ``/etc/motd`` from the attached MotdTemplate (or a default).

    Default template: ``Welcome to {os_pretty_name}\\n``.
    """
    with sync_session(db_url) as s:
        p = s.get(BrandingProfile, profile_id)
        if p is None:
            raise ValueError(f"branding profile not found: {profile_id!r}")

        template_row = s.scalars(
            select(MotdTemplate).where(MotdTemplate.branding_profile_id == profile_id)
        ).first()

        if template_row is not None:
            rendered = template_row.template_text.format(
                os_name=p.os_name or "",
                os_pretty_name=p.os_pretty_name or p.os_name or "",
                os_version=p.os_version or "",
                vendor_name=p.vendor_name or "",
            )
            template_row.rendered_text = rendered
            template_row.rendered_at = _now()
        else:
            rendered = f"Welcome to {p.os_pretty_name or p.os_name or 'Linux'}\n"

        now = _now()
        p.rendered_motd = rendered
        p.updated_at = now
        s.commit()
        return {"profile_id": profile_id, "rendered_motd": rendered}


# ---------------------------------------------------------------------------
# Boot splash / login screen / wallpapers
# ---------------------------------------------------------------------------


def set_boot_splash(
    profile_id: str,
    theme_name: str,
    *,
    package_name: str | None = None,
    config_json: dict[str, Any] | None = None,
    db_url: str | None = None,
) -> dict[str, Any]:
    """Set (upsert) the Plymouth theme for a branding profile."""
    with sync_session(db_url) as s:
        if s.get(BrandingProfile, profile_id) is None:
            raise ValueError(f"branding profile not found: {profile_id!r}")
        existing = s.scalars(
            select(BootSplashTheme).where(BootSplashTheme.branding_profile_id == profile_id)
        ).first()
        if existing is not None:
            existing.theme_name = theme_name
            existing.package_name = package_name
            existing.config_json = config_json
        else:
            existing = BootSplashTheme(
                branding_profile_id=profile_id,
                theme_name=theme_name,
                package_name=package_name,
                config_json=config_json,
            )
            s.add(existing)
        s.commit()
        return {"id": existing.id, "profile_id": profile_id, "theme_name": theme_name}


def set_login_theme(
    profile_id: str,
    theme_name: str,
    *,
    display_manager: str | None = None,
    config_json: dict[str, Any] | None = None,
    db_url: str | None = None,
) -> dict[str, Any]:
    """Set (upsert) the display-manager login theme."""
    with sync_session(db_url) as s:
        if s.get(BrandingProfile, profile_id) is None:
            raise ValueError(f"branding profile not found: {profile_id!r}")
        existing = s.scalars(
            select(LoginScreenTheme).where(LoginScreenTheme.branding_profile_id == profile_id)
        ).first()
        if existing is not None:
            existing.theme_name = theme_name
            existing.display_manager = display_manager
            existing.config_json = config_json
        else:
            existing = LoginScreenTheme(
                branding_profile_id=profile_id,
                theme_name=theme_name,
                display_manager=display_manager,
                config_json=config_json,
            )
            s.add(existing)
        s.commit()
        return {"id": existing.id, "profile_id": profile_id, "theme_name": theme_name}


def add_wallpaper(
    profile_id: str,
    name: str,
    *,
    resolution: str | None = None,
    asset_id: str | None = None,
    is_default: bool = False,
    db_url: str | None = None,
) -> dict[str, Any]:
    """Add a wallpaper entry at a given resolution."""
    with sync_session(db_url) as s:
        if s.get(BrandingProfile, profile_id) is None:
            raise ValueError(f"branding profile not found: {profile_id!r}")
        wp = WallpaperSet(
            branding_profile_id=profile_id,
            name=name,
            resolution=resolution,
            asset_id=asset_id,
            is_default=is_default,
        )
        s.add(wp)
        s.commit()
        return {
            "id": wp.id,
            "profile_id": profile_id,
            "name": name,
            "resolution": resolution,
            "is_default": is_default,
        }


def set_os_release_template(
    profile_id: str,
    template_text: str,
    *,
    db_url: str | None = None,
) -> dict[str, Any]:
    """Set (upsert) a custom /etc/os-release template for a branding profile."""
    with sync_session(db_url) as s:
        if s.get(BrandingProfile, profile_id) is None:
            raise ValueError(f"branding profile not found: {profile_id!r}")
        existing = s.scalars(
            select(OsReleaseTemplate).where(
                OsReleaseTemplate.branding_profile_id == profile_id
            )
        ).first()
        if existing is not None:
            existing.template_text = template_text
            existing.rendered_text = None
            existing.rendered_at = None
        else:
            existing = OsReleaseTemplate(
                branding_profile_id=profile_id,
                template_text=template_text,
            )
            s.add(existing)
        s.commit()
        return {"id": existing.id, "profile_id": profile_id}


def set_motd_template(
    profile_id: str,
    template_text: str,
    *,
    db_url: str | None = None,
) -> dict[str, Any]:
    """Set (upsert) a custom /etc/motd template."""
    with sync_session(db_url) as s:
        if s.get(BrandingProfile, profile_id) is None:
            raise ValueError(f"branding profile not found: {profile_id!r}")
        existing = s.scalars(
            select(MotdTemplate).where(MotdTemplate.branding_profile_id == profile_id)
        ).first()
        if existing is not None:
            existing.template_text = template_text
            existing.rendered_text = None
            existing.rendered_at = None
        else:
            existing = MotdTemplate(
                branding_profile_id=profile_id,
                template_text=template_text,
            )
            s.add(existing)
        s.commit()
        return {"id": existing.id, "profile_id": profile_id}
