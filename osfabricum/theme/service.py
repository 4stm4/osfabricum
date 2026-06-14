"""Themes / Icons / Fonts Designer service (M43).

A ``ThemeProfile`` captures the full visual appearance stack for a distribution:
GTK/cursor/icon/sound themes, font assignments, DPI/scaling, and arbitrary
dconf/gsettings key overrides.

Key functions:

* :func:`create_theme_profile` — create a new theme profile.
* :func:`get_theme_profile` — full detail (packages + gsettings overrides).
* :func:`update_theme_profile` — change theme/font/scaling fields; clears cache.
* :func:`add_theme_package` — attach a theme/icon/font package to the profile.
* :func:`set_gsettings_override` — upsert an arbitrary gsettings key-value pair.
* :func:`render_theme_config` — generate a dconf lock-db override file and a
  GTK settings.ini; compute ``sha256:`` hash; store on the profile row.
* :func:`list_theme_asset_kinds` — enumerate the seeded asset kind lookup.
"""

from __future__ import annotations

import hashlib
from datetime import UTC
from datetime import datetime as _dt
from typing import Any

from sqlalchemy import select

from osfabricum.db.models import (
    GsettingsOverride,
    ThemeAssetKind,
    ThemePackage,
    ThemeProfile,
)
from osfabricum.db.seed_data import THEME_ASSET_KINDS
from osfabricum.db.session import sync_session

# ---------------------------------------------------------------------------
# Valid values
# ---------------------------------------------------------------------------

VALID_ASSET_KINDS: frozenset[str] = frozenset(name for name, *_ in THEME_ASSET_KINDS)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> _dt:
    return _dt.now(UTC).replace(tzinfo=None)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _profile_to_dict(p: ThemeProfile) -> dict[str, Any]:
    return {
        "id": p.id,
        "name": p.name,
        "distribution_id": p.distribution_id,
        "gtk_theme": p.gtk_theme,
        "icon_theme": p.icon_theme,
        "cursor_theme": p.cursor_theme,
        "sound_theme": p.sound_theme,
        "dark_mode": p.dark_mode,
        "font_default": p.font_default,
        "font_monospace": p.font_monospace,
        "font_document": p.font_document,
        "font_size": p.font_size,
        "cursor_size": p.cursor_size,
        "scaling_factor": p.scaling_factor,
        "rendered_gsettings": p.rendered_gsettings,
        "rendered_gtk_ini": p.rendered_gtk_ini,
        "content_hash": p.content_hash,
        "rendered_at": p.rendered_at.isoformat() if p.rendered_at else None,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


# ---------------------------------------------------------------------------
# Asset kinds (read-only seeded data)
# ---------------------------------------------------------------------------


def list_theme_asset_kinds(*, db_url: str | None = None) -> list[dict[str, Any]]:
    with sync_session(db_url) as s:
        return [
            {
                "name": k.name,
                "description": k.description,
                "display_order": k.display_order,
            }
            for k in s.scalars(
                select(ThemeAssetKind).order_by(ThemeAssetKind.display_order)
            ).all()
        ]


# ---------------------------------------------------------------------------
# Profile CRUD
# ---------------------------------------------------------------------------


def create_theme_profile(
    name: str,
    *,
    distribution_id: str | None = None,
    gtk_theme: str = "Adwaita",
    icon_theme: str = "Adwaita",
    cursor_theme: str = "Adwaita",
    sound_theme: str = "freedesktop",
    dark_mode: bool = False,
    font_default: str = "Sans",
    font_monospace: str = "Monospace",
    font_document: str = "Sans",
    font_size: int = 11,
    cursor_size: int = 24,
    scaling_factor: float = 1.0,
    db_url: str | None = None,
) -> dict[str, Any]:
    """Create a new theme profile."""
    now = _now()
    with sync_session(db_url) as s:
        existing = s.scalars(
            select(ThemeProfile).where(
                ThemeProfile.distribution_id == distribution_id,
                ThemeProfile.name == name,
            )
        ).first()
        if existing is not None:
            raise ValueError(f"theme profile already exists: {name!r}")
        p = ThemeProfile(
            name=name,
            distribution_id=distribution_id,
            gtk_theme=gtk_theme,
            icon_theme=icon_theme,
            cursor_theme=cursor_theme,
            sound_theme=sound_theme,
            dark_mode=dark_mode,
            font_default=font_default,
            font_monospace=font_monospace,
            font_document=font_document,
            font_size=font_size,
            cursor_size=cursor_size,
            scaling_factor=scaling_factor,
            created_at=now,
            updated_at=now,
        )
        s.add(p)
        s.commit()
        return _profile_to_dict(p)


def update_theme_profile(
    profile_id: str,
    *,
    gtk_theme: str | None = None,
    icon_theme: str | None = None,
    cursor_theme: str | None = None,
    sound_theme: str | None = None,
    dark_mode: bool | None = None,
    font_default: str | None = None,
    font_monospace: str | None = None,
    font_document: str | None = None,
    font_size: int | None = None,
    cursor_size: int | None = None,
    scaling_factor: float | None = None,
    db_url: str | None = None,
) -> dict[str, Any]:
    """Update theme fields; clears rendered cache."""
    with sync_session(db_url) as s:
        p = s.get(ThemeProfile, profile_id)
        if p is None:
            raise ValueError(f"theme profile not found: {profile_id!r}")
        if gtk_theme is not None:
            p.gtk_theme = gtk_theme
        if icon_theme is not None:
            p.icon_theme = icon_theme
        if cursor_theme is not None:
            p.cursor_theme = cursor_theme
        if sound_theme is not None:
            p.sound_theme = sound_theme
        if dark_mode is not None:
            p.dark_mode = dark_mode
        if font_default is not None:
            p.font_default = font_default
        if font_monospace is not None:
            p.font_monospace = font_monospace
        if font_document is not None:
            p.font_document = font_document
        if font_size is not None:
            p.font_size = font_size
        if cursor_size is not None:
            p.cursor_size = cursor_size
        if scaling_factor is not None:
            p.scaling_factor = scaling_factor
        p.rendered_gsettings = None
        p.rendered_gtk_ini = None
        p.content_hash = None
        p.rendered_at = None
        p.updated_at = _now()
        s.commit()
        return _profile_to_dict(p)


def list_theme_profiles(
    distribution_id: str | None = None,
    *,
    db_url: str | None = None,
) -> list[dict[str, Any]]:
    with sync_session(db_url) as s:
        q = select(ThemeProfile).order_by(ThemeProfile.name)
        if distribution_id is not None:
            q = q.where(ThemeProfile.distribution_id == distribution_id)
        return [_profile_to_dict(p) for p in s.scalars(q).all()]


def get_theme_profile(profile_id: str, *, db_url: str | None = None) -> dict[str, Any]:
    """Return full profile including theme packages and gsettings overrides."""
    with sync_session(db_url) as s:
        p = s.get(ThemeProfile, profile_id)
        if p is None:
            raise ValueError(f"theme profile not found: {profile_id!r}")
        result = _profile_to_dict(p)

        result["packages"] = [
            {
                "id": pkg.id,
                "asset_kind": pkg.asset_kind,
                "package_name": pkg.package_name,
                "version_constraint": pkg.version_constraint,
                "is_default": pkg.is_default,
            }
            for pkg in s.scalars(
                select(ThemePackage)
                .where(ThemePackage.profile_id == profile_id)
                .order_by(ThemePackage.asset_kind, ThemePackage.package_name)
            ).all()
        ]

        result["gsettings"] = [
            {
                "id": o.id,
                "schema": o.schema,
                "key": o.key,
                "value": o.value,
                "description": o.description,
            }
            for o in s.scalars(
                select(GsettingsOverride)
                .where(GsettingsOverride.profile_id == profile_id)
                .order_by(GsettingsOverride.schema, GsettingsOverride.key)
            ).all()
        ]
        return result


# ---------------------------------------------------------------------------
# Theme packages
# ---------------------------------------------------------------------------


def add_theme_package(
    profile_id: str,
    asset_kind: str,
    package_name: str,
    *,
    version_constraint: str | None = None,
    is_default: bool = False,
    db_url: str | None = None,
) -> dict[str, Any]:
    """Add a theme/icon/font package to a theme profile."""
    if asset_kind not in VALID_ASSET_KINDS:
        raise ValueError(
            f"unknown asset_kind {asset_kind!r}; "
            f"valid: {', '.join(sorted(VALID_ASSET_KINDS))}"
        )
    with sync_session(db_url) as s:
        if s.get(ThemeProfile, profile_id) is None:
            raise ValueError(f"theme profile not found: {profile_id!r}")
        existing = s.scalars(
            select(ThemePackage).where(
                ThemePackage.profile_id == profile_id,
                ThemePackage.asset_kind == asset_kind,
                ThemePackage.package_name == package_name,
            )
        ).first()
        if existing is not None:
            raise ValueError(
                f"package {package_name!r} ({asset_kind}) already in profile {profile_id!r}"
            )
        pkg = ThemePackage(
            profile_id=profile_id,
            asset_kind=asset_kind,
            package_name=package_name,
            version_constraint=version_constraint,
            is_default=is_default,
        )
        s.add(pkg)
        s.commit()
        return {
            "id": pkg.id,
            "profile_id": profile_id,
            "asset_kind": asset_kind,
            "package_name": package_name,
            "version_constraint": version_constraint,
            "is_default": is_default,
        }


# ---------------------------------------------------------------------------
# GSettings overrides
# ---------------------------------------------------------------------------


def set_gsettings_override(
    profile_id: str,
    schema: str,
    key: str,
    value: str,
    *,
    description: str | None = None,
    db_url: str | None = None,
) -> dict[str, Any]:
    """Upsert a dconf/gsettings key override for a theme profile."""
    with sync_session(db_url) as s:
        if s.get(ThemeProfile, profile_id) is None:
            raise ValueError(f"theme profile not found: {profile_id!r}")
        existing = s.scalars(
            select(GsettingsOverride).where(
                GsettingsOverride.profile_id == profile_id,
                GsettingsOverride.schema == schema,
                GsettingsOverride.key == key,
            )
        ).first()
        if existing is not None:
            existing.value = value
            if description is not None:
                existing.description = description
            s.commit()
            return {
                "id": existing.id,
                "profile_id": profile_id,
                "schema": schema,
                "key": key,
                "value": value,
                "description": existing.description,
            }
        o = GsettingsOverride(
            profile_id=profile_id,
            schema=schema,
            key=key,
            value=value,
            description=description,
        )
        s.add(o)
        s.commit()
        return {
            "id": o.id,
            "profile_id": profile_id,
            "schema": schema,
            "key": key,
            "value": value,
            "description": description,
        }


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

_GSETTINGS_HEADER = "# Generated by OSFabricum M43 — do not edit manually\n"

_GTK_INI_TEMPLATE = """\
# Generated by OSFabricum M43 — do not edit manually
[Settings]
gtk-theme-name={gtk_theme}
gtk-icon-theme-name={icon_theme}
gtk-cursor-theme-name={cursor_theme}
gtk-cursor-theme-size={cursor_size}
gtk-font-name={font_default} {font_size}
gtk-application-prefer-dark-theme={dark_mode}
"""


def _build_gsettings(p: ThemeProfile, overrides: list[GsettingsOverride]) -> str:
    # Core interface settings
    schema_groups: dict[str, list[tuple[str, str]]] = {}

    interface_kv = [
        ("gtk-theme", f"'{p.gtk_theme}'"),
        ("icon-theme", f"'{p.icon_theme}'"),
        ("cursor-theme", f"'{p.cursor_theme}'"),
        ("cursor-size", str(p.cursor_size)),
        ("font-name", f"'{p.font_default} {p.font_size}'"),
        ("monospace-font-name", f"'{p.font_monospace} {p.font_size}'"),
        ("document-font-name", f"'{p.font_document} {p.font_size}'"),
        ("text-scaling-factor", f"{p.scaling_factor:.2f}"),
        ("color-scheme", f"'{'prefer-dark' if p.dark_mode else 'default'}'"),
    ]
    schema_groups["org/gnome/desktop/interface"] = interface_kv

    if p.sound_theme != "freedesktop":
        schema_groups.setdefault("org/gnome/desktop/sound", []).append(
            ("theme-name", f"'{p.sound_theme}'")
        )

    # Extra overrides
    for o in overrides:
        schema_groups.setdefault(o.schema, []).append((o.key, o.value))

    lines = [_GSETTINGS_HEADER]
    for schema in sorted(schema_groups):
        lines.append(f"[{schema}]\n")
        for key, val in schema_groups[schema]:
            lines.append(f"{key}={val}\n")
        lines.append("\n")
    return "".join(lines)


def render_theme_config(
    profile_id: str, *, db_url: str | None = None
) -> dict[str, Any]:
    """Generate dconf override content and GTK settings.ini; store on profile row.

    Both outputs are concatenated for the deterministic sha256: hash.
    """
    with sync_session(db_url) as s:
        p = s.get(ThemeProfile, profile_id)
        if p is None:
            raise ValueError(f"theme profile not found: {profile_id!r}")

        overrides = s.scalars(
            select(GsettingsOverride)
            .where(GsettingsOverride.profile_id == profile_id)
            .order_by(GsettingsOverride.schema, GsettingsOverride.key)
        ).all()

        packages = s.scalars(
            select(ThemePackage).where(ThemePackage.profile_id == profile_id)
        ).all()

        gsettings = _build_gsettings(p, list(overrides))
        gtk_ini = _GTK_INI_TEMPLATE.format(
            gtk_theme=p.gtk_theme,
            icon_theme=p.icon_theme,
            cursor_theme=p.cursor_theme,
            cursor_size=p.cursor_size,
            font_default=p.font_default,
            font_size=p.font_size,
            dark_mode=str(p.dark_mode).lower(),
        )

        body = gsettings + "\n---\n" + gtk_ini
        content_hash = "sha256:" + _sha(body)
        now = _now()

        p.rendered_gsettings = gsettings
        p.rendered_gtk_ini = gtk_ini
        p.content_hash = content_hash
        p.rendered_at = now
        p.updated_at = now
        s.commit()

        return {
            "profile_id": profile_id,
            "rendered_gsettings": gsettings,
            "rendered_gtk_ini": gtk_ini,
            "content_hash": content_hash,
            "rendered_at": now.isoformat(),
            "package_count": len(packages),
            "gsettings_override_count": len(overrides),
        }
