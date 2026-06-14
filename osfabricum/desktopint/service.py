"""Desktop Integration Designer service (M42).

A ``DesktopIntegrationProfile`` is the full XDG/freedesktop.org integration
layer for a distribution: MIME type → .desktop file associations, XDG autostart
entries, and user directory path overrides.

Key functions:

* :func:`create_desktop_integration_profile` — create a new profile.
* :func:`get_desktop_integration_profile` — full detail (associations + autostart + dirs).
* :func:`add_mime_association` — bind a MIME type to a .desktop file.
* :func:`add_autostart_entry` — register an XDG autostart .desktop entry.
* :func:`set_user_dir` — override an XDG user directory path.
* :func:`render_desktop_integration` — generate ``mimeapps.list`` +
  ``user-dirs.defaults``, compute ``sha256:`` hash, store on profile row.
* :func:`list_mime_types` — enumerate seeded MIME type definitions.
"""

from __future__ import annotations

import hashlib
from datetime import UTC
from datetime import datetime as _dt
from typing import Any

from sqlalchemy import select

from osfabricum.db.models import (
    AutostartEntry,
    DesktopIntegrationProfile,
    MimeAssociation,
    MimeTypeDefinition,
    XdgUserDir,
)
from osfabricum.db.seed_data import (
    AUTOSTART_CONDITIONS,
    MIME_ASSOCIATION_TYPES,
    XDG_DIR_NAMES,
    XDG_USER_DIR_DEFAULTS,
)
from osfabricum.db.session import sync_session

# ---------------------------------------------------------------------------
# Valid values
# ---------------------------------------------------------------------------

VALID_ASSOCIATION_TYPES: frozenset[str] = frozenset(MIME_ASSOCIATION_TYPES)
VALID_CONDITIONS: frozenset[str] = frozenset(AUTOSTART_CONDITIONS)
VALID_XDG_DIRS: frozenset[str] = frozenset(XDG_DIR_NAMES)
DEFAULT_USER_DIRS: dict[str, str] = dict(XDG_USER_DIR_DEFAULTS)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> _dt:
    return _dt.now(UTC).replace(tzinfo=None)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _profile_to_dict(p: DesktopIntegrationProfile) -> dict[str, Any]:
    return {
        "id": p.id,
        "name": p.name,
        "distribution_id": p.distribution_id,
        "xdg_data_dirs": p.xdg_data_dirs,
        "xdg_config_dirs": p.xdg_config_dirs,
        "rendered_mimeapps": p.rendered_mimeapps,
        "rendered_user_dirs": p.rendered_user_dirs,
        "content_hash": p.content_hash,
        "rendered_at": p.rendered_at.isoformat() if p.rendered_at else None,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


def _autostart_desktop(name: str, exec_cmd: str, comment: str | None, condition: str) -> str:
    lines = [
        "[Desktop Entry]",
        "Type=Application",
        f"Name={name}",
        f"Exec={exec_cmd}",
        f"Comment={comment or ''}",
        "X-GNOME-Autostart-enabled=true",
    ]
    if condition == "wayland":
        lines.append("OnlyShowIn=Wayland;")
    elif condition == "x11":
        lines.append("OnlyShowIn=X11;")
    elif condition == "graphical":
        lines.append("OnlyShowIn=GNOME;KDE;XFCE;")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# MIME type reference (read-only seeded data)
# ---------------------------------------------------------------------------


def list_mime_types(*, db_url: str | None = None) -> list[dict[str, Any]]:
    with sync_session(db_url) as s:
        return [
            {
                "name": m.name,
                "description": m.description,
                "parent": m.parent,
                "icon": m.icon,
                "display_order": m.display_order,
            }
            for m in s.scalars(
                select(MimeTypeDefinition).order_by(MimeTypeDefinition.display_order)
            ).all()
        ]


# ---------------------------------------------------------------------------
# Profile CRUD
# ---------------------------------------------------------------------------


def create_desktop_integration_profile(
    name: str,
    *,
    distribution_id: str | None = None,
    xdg_data_dirs: list[str] | None = None,
    xdg_config_dirs: list[str] | None = None,
    db_url: str | None = None,
) -> dict[str, Any]:
    """Create a new desktop integration profile."""
    now = _now()
    with sync_session(db_url) as s:
        existing = s.scalars(
            select(DesktopIntegrationProfile).where(
                DesktopIntegrationProfile.distribution_id == distribution_id,
                DesktopIntegrationProfile.name == name,
            )
        ).first()
        if existing is not None:
            raise ValueError(f"desktop integration profile already exists: {name!r}")
        p = DesktopIntegrationProfile(
            name=name,
            distribution_id=distribution_id,
            xdg_data_dirs=xdg_data_dirs or [],
            xdg_config_dirs=xdg_config_dirs or [],
            created_at=now,
            updated_at=now,
        )
        s.add(p)
        s.commit()
        return _profile_to_dict(p)


def update_desktop_integration_profile(
    profile_id: str,
    *,
    xdg_data_dirs: list[str] | None = None,
    xdg_config_dirs: list[str] | None = None,
    db_url: str | None = None,
) -> dict[str, Any]:
    """Update XDG path lists; clears rendered cache."""
    with sync_session(db_url) as s:
        p = s.get(DesktopIntegrationProfile, profile_id)
        if p is None:
            raise ValueError(f"desktop integration profile not found: {profile_id!r}")
        if xdg_data_dirs is not None:
            p.xdg_data_dirs = xdg_data_dirs
        if xdg_config_dirs is not None:
            p.xdg_config_dirs = xdg_config_dirs
        p.rendered_mimeapps = None
        p.rendered_user_dirs = None
        p.content_hash = None
        p.rendered_at = None
        p.updated_at = _now()
        s.commit()
        return _profile_to_dict(p)


def list_desktop_integration_profiles(
    distribution_id: str | None = None,
    *,
    db_url: str | None = None,
) -> list[dict[str, Any]]:
    with sync_session(db_url) as s:
        q = select(DesktopIntegrationProfile).order_by(DesktopIntegrationProfile.name)
        if distribution_id is not None:
            q = q.where(DesktopIntegrationProfile.distribution_id == distribution_id)
        return [_profile_to_dict(p) for p in s.scalars(q).all()]


def get_desktop_integration_profile(
    profile_id: str, *, db_url: str | None = None
) -> dict[str, Any]:
    """Return full profile including associations, autostart entries, and user dirs."""
    with sync_session(db_url) as s:
        p = s.get(DesktopIntegrationProfile, profile_id)
        if p is None:
            raise ValueError(f"desktop integration profile not found: {profile_id!r}")
        result = _profile_to_dict(p)

        result["mime_associations"] = [
            {
                "id": a.id,
                "mime_type": a.mime_type,
                "desktop_file": a.desktop_file,
                "association_type": a.association_type,
                "priority": a.priority,
            }
            for a in s.scalars(
                select(MimeAssociation)
                .where(MimeAssociation.profile_id == profile_id)
                .order_by(MimeAssociation.mime_type, MimeAssociation.priority)
            ).all()
        ]

        result["autostart_entries"] = [
            {
                "id": e.id,
                "name": e.name,
                "exec_cmd": e.exec_cmd,
                "comment": e.comment,
                "condition": e.condition,
                "is_enabled": e.is_enabled,
                "desktop_entry": e.desktop_entry,
            }
            for e in s.scalars(
                select(AutostartEntry)
                .where(AutostartEntry.profile_id == profile_id)
                .order_by(AutostartEntry.name)
            ).all()
        ]

        result["user_dirs"] = [
            {
                "id": d.id,
                "dir_name": d.dir_name,
                "path": d.path,
            }
            for d in s.scalars(
                select(XdgUserDir)
                .where(XdgUserDir.profile_id == profile_id)
                .order_by(XdgUserDir.dir_name)
            ).all()
        ]
        return result


# ---------------------------------------------------------------------------
# MIME associations
# ---------------------------------------------------------------------------


def add_mime_association(
    profile_id: str,
    mime_type: str,
    desktop_file: str,
    *,
    association_type: str = "default",
    priority: int = 0,
    db_url: str | None = None,
) -> dict[str, Any]:
    """Bind a MIME type to a .desktop file in a desktop integration profile."""
    if association_type not in VALID_ASSOCIATION_TYPES:
        raise ValueError(
            f"unknown association_type {association_type!r}; "
            f"valid: {', '.join(sorted(VALID_ASSOCIATION_TYPES))}"
        )
    with sync_session(db_url) as s:
        if s.get(DesktopIntegrationProfile, profile_id) is None:
            raise ValueError(f"desktop integration profile not found: {profile_id!r}")
        existing = s.scalars(
            select(MimeAssociation).where(
                MimeAssociation.profile_id == profile_id,
                MimeAssociation.mime_type == mime_type,
                MimeAssociation.desktop_file == desktop_file,
            )
        ).first()
        if existing is not None:
            raise ValueError(
                f"association {mime_type!r} → {desktop_file!r} already exists "
                f"in profile {profile_id!r}"
            )
        a = MimeAssociation(
            profile_id=profile_id,
            mime_type=mime_type,
            desktop_file=desktop_file,
            association_type=association_type,
            priority=priority,
        )
        s.add(a)
        s.commit()
        return {
            "id": a.id,
            "profile_id": profile_id,
            "mime_type": mime_type,
            "desktop_file": desktop_file,
            "association_type": association_type,
            "priority": priority,
        }


# ---------------------------------------------------------------------------
# Autostart entries
# ---------------------------------------------------------------------------


def add_autostart_entry(
    profile_id: str,
    name: str,
    exec_cmd: str,
    *,
    comment: str | None = None,
    condition: str = "always",
    is_enabled: bool = True,
    db_url: str | None = None,
) -> dict[str, Any]:
    """Add an XDG autostart entry to a desktop integration profile."""
    if condition not in VALID_CONDITIONS:
        raise ValueError(
            f"unknown condition {condition!r}; "
            f"valid: {', '.join(sorted(VALID_CONDITIONS))}"
        )
    with sync_session(db_url) as s:
        if s.get(DesktopIntegrationProfile, profile_id) is None:
            raise ValueError(f"desktop integration profile not found: {profile_id!r}")
        existing = s.scalars(
            select(AutostartEntry).where(
                AutostartEntry.profile_id == profile_id,
                AutostartEntry.name == name,
            )
        ).first()
        if existing is not None:
            raise ValueError(
                f"autostart entry {name!r} already exists in profile {profile_id!r}"
            )
        desktop_entry = _autostart_desktop(name, exec_cmd, comment, condition)
        e = AutostartEntry(
            profile_id=profile_id,
            name=name,
            exec_cmd=exec_cmd,
            comment=comment,
            condition=condition,
            is_enabled=is_enabled,
            desktop_entry=desktop_entry,
        )
        s.add(e)
        s.commit()
        return {
            "id": e.id,
            "profile_id": profile_id,
            "name": name,
            "exec_cmd": exec_cmd,
            "condition": condition,
            "is_enabled": is_enabled,
            "desktop_entry": desktop_entry,
        }


# ---------------------------------------------------------------------------
# XDG user directories
# ---------------------------------------------------------------------------


def set_user_dir(
    profile_id: str,
    dir_name: str,
    path: str,
    *,
    db_url: str | None = None,
) -> dict[str, Any]:
    """Override an XDG user directory path (upsert by dir_name)."""
    if dir_name not in VALID_XDG_DIRS:
        raise ValueError(
            f"unknown XDG dir {dir_name!r}; "
            f"valid: {', '.join(sorted(VALID_XDG_DIRS))}"
        )
    with sync_session(db_url) as s:
        if s.get(DesktopIntegrationProfile, profile_id) is None:
            raise ValueError(f"desktop integration profile not found: {profile_id!r}")
        existing = s.scalars(
            select(XdgUserDir).where(
                XdgUserDir.profile_id == profile_id,
                XdgUserDir.dir_name == dir_name,
            )
        ).first()
        if existing is not None:
            existing.path = path
            s.commit()
            return {
                "id": existing.id,
                "profile_id": profile_id,
                "dir_name": dir_name,
                "path": path,
            }
        d = XdgUserDir(profile_id=profile_id, dir_name=dir_name, path=path)
        s.add(d)
        s.commit()
        return {"id": d.id, "profile_id": profile_id, "dir_name": dir_name, "path": path}


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

_MIMEAPPS_HEADER = "# Generated by OSFabricum M42 — do not edit manually\n"


def _build_mimeapps(associations: list[MimeAssociation]) -> str:
    default: dict[str, list[str]] = {}
    added: dict[str, list[str]] = {}
    removed: dict[str, list[str]] = {}

    for a in sorted(associations, key=lambda x: (x.mime_type, x.priority)):
        if a.association_type == "default":
            default.setdefault(a.mime_type, []).append(a.desktop_file)
        elif a.association_type == "added":
            added.setdefault(a.mime_type, []).append(a.desktop_file)
        elif a.association_type == "removed":
            removed.setdefault(a.mime_type, []).append(a.desktop_file)

    parts = [_MIMEAPPS_HEADER]
    if default:
        parts.append("[Default Applications]\n")
        for mime in sorted(default):
            parts.append(f"{mime}={';'.join(default[mime])};\n")
        parts.append("\n")
    if added:
        parts.append("[Added Associations]\n")
        for mime in sorted(added):
            parts.append(f"{mime}={';'.join(added[mime])};\n")
        parts.append("\n")
    if removed:
        parts.append("[Removed Associations]\n")
        for mime in sorted(removed):
            parts.append(f"{mime}={';'.join(removed[mime])};\n")
    return "".join(parts)


def _build_user_dirs(user_dirs: list[XdgUserDir]) -> str:
    dir_map = dict(DEFAULT_USER_DIRS)
    for d in user_dirs:
        dir_map[d.dir_name] = d.path
    lines = ["# Generated by OSFabricum M42 — do not edit manually\n"]
    for dir_name in (name for name, _ in XDG_USER_DIR_DEFAULTS):
        lines.append(f"{dir_name}={dir_map[dir_name]}\n")
    return "".join(lines)


def render_desktop_integration(
    profile_id: str, *, db_url: str | None = None
) -> dict[str, Any]:
    """Generate mimeapps.list and user-dirs.defaults; store on profile row.

    The body (both files concatenated) is hashed deterministically.
    """
    with sync_session(db_url) as s:
        p = s.get(DesktopIntegrationProfile, profile_id)
        if p is None:
            raise ValueError(f"desktop integration profile not found: {profile_id!r}")

        associations = s.scalars(
            select(MimeAssociation).where(MimeAssociation.profile_id == profile_id)
        ).all()
        user_dirs = s.scalars(
            select(XdgUserDir).where(XdgUserDir.profile_id == profile_id)
        ).all()

        mimeapps = _build_mimeapps(list(associations))
        user_dirs_text = _build_user_dirs(list(user_dirs))
        body = mimeapps + "\n---\n" + user_dirs_text
        content_hash = "sha256:" + _sha(body)
        now = _now()

        p.rendered_mimeapps = mimeapps
        p.rendered_user_dirs = user_dirs_text
        p.content_hash = content_hash
        p.rendered_at = now
        p.updated_at = now
        s.commit()

        return {
            "profile_id": profile_id,
            "rendered_mimeapps": mimeapps,
            "rendered_user_dirs": user_dirs_text,
            "content_hash": content_hash,
            "rendered_at": now.isoformat(),
            "association_count": len(associations),
            "autostart_count": s.scalars(
                select(AutostartEntry).where(AutostartEntry.profile_id == profile_id)
            ).all().__len__(),
            "user_dir_count": len(user_dirs),
        }
