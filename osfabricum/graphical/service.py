"""Graphical Shell Designer service (M40).

A ``GraphicalProfile`` is the full definition of what runs on screen:
which display protocol (X11 / Wayland), which compositor, which display
manager, which toolkit, and which session entries are presented at login.

Key functions:

* :func:`create_graphical_profile` — create a new graphical stack.
* :func:`get_graphical_profile` — full detail (components + sessions).
* :func:`add_component` — attach a package to the stack by *kind*.
* :func:`add_session` — register a ``/usr/share/wayland-sessions/*.desktop`` entry.
* :func:`render_session_config` — generate the ``.desktop`` file content,
  compute ``sha256:`` hash, store on profile row.
* :func:`list_compositor_backends` / :func:`list_display_manager_backends`
  — enumerate the seeded backends.
"""

from __future__ import annotations

import hashlib
from datetime import UTC
from datetime import datetime as _dt
from typing import Any

from sqlalchemy import select

from osfabricum.db.models import (
    CompositorBackend,
    DisplayManagerBackend,
    GraphicalComponent,
    GraphicalProfile,
    GraphicalSession,
)
from osfabricum.db.session import sync_session

# ---------------------------------------------------------------------------
# Valid values
# ---------------------------------------------------------------------------

DISPLAY_SERVERS = ("none", "x11", "wayland", "both")

SESSION_TYPES = ("x11", "wayland", "mir")

COMPONENT_KINDS = (
    "compositor",
    "window-manager",
    "desktop-shell",
    "panel",
    "bar",
    "notifications",
    "file-manager",
    "settings-daemon",
    "polkit-agent",
    "screen-locker",
    "screenshot",
    "media-portal",
    "input-method",
    "theme-engine",
    "app-launcher",
    "clipboard-manager",
    "toolkit",
    "icon-theme",
    "cursor-theme",
    "sound-theme",
    "font",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> _dt:
    return _dt.now(UTC).replace(tzinfo=None)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _profile_to_dict(p: GraphicalProfile) -> dict[str, Any]:
    return {
        "id": p.id,
        "name": p.name,
        "distribution_id": p.distribution_id,
        "mode": p.mode,
        "display_server": p.display_server,
        "compositor": p.compositor,
        "display_manager": p.display_manager,
        "session_manager": p.session_manager,
        "toolkit_default": p.toolkit_default,
        "rendered_session_config": p.rendered_session_config,
        "content_hash": p.content_hash,
        "rendered_at": p.rendered_at.isoformat() if p.rendered_at else None,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------


def list_compositor_backends(*, db_url: str | None = None) -> list[dict[str, Any]]:
    with sync_session(db_url) as s:
        return [
            {
                "name": b.name,
                "description": b.description,
                "protocol": b.protocol,
                "package_name": b.package_name,
            }
            for b in s.scalars(
                select(CompositorBackend).order_by(CompositorBackend.name)
            ).all()
        ]


def list_display_manager_backends(*, db_url: str | None = None) -> list[dict[str, Any]]:
    with sync_session(db_url) as s:
        return [
            {
                "name": b.name,
                "description": b.description,
                "package_name": b.package_name,
            }
            for b in s.scalars(
                select(DisplayManagerBackend).order_by(DisplayManagerBackend.name)
            ).all()
        ]


# ---------------------------------------------------------------------------
# Profile CRUD
# ---------------------------------------------------------------------------


def create_graphical_profile(
    name: str,
    *,
    distribution_id: str | None = None,
    display_server: str = "none",
    compositor: str | None = None,
    display_manager: str | None = None,
    session_manager: str | None = None,
    toolkit_default: str | None = None,
    db_url: str | None = None,
) -> dict[str, Any]:
    """Create a new graphical shell profile."""
    if display_server not in DISPLAY_SERVERS:
        raise ValueError(
            f"unknown display_server {display_server!r}; valid: {', '.join(DISPLAY_SERVERS)}"
        )
    now = _now()
    with sync_session(db_url) as s:
        existing = s.scalars(
            select(GraphicalProfile).where(
                GraphicalProfile.distribution_id == distribution_id,
                GraphicalProfile.name == name,
            )
        ).first()
        if existing is not None:
            raise ValueError(f"graphical profile already exists: {name!r}")

        # Derive mode from display_server
        mode = "no-gui" if display_server == "none" else "gui"

        p = GraphicalProfile(
            name=name,
            distribution_id=distribution_id,
            mode=mode,
            display_server=display_server,
            compositor=compositor,
            display_manager=display_manager,
            session_manager=session_manager,
            toolkit_default=toolkit_default,
            created_at=now,
            updated_at=now,
        )
        s.add(p)
        s.commit()
        return _profile_to_dict(p)


def update_graphical_profile(
    profile_id: str,
    *,
    display_server: str | None = None,
    compositor: str | None = None,
    display_manager: str | None = None,
    session_manager: str | None = None,
    toolkit_default: str | None = None,
    db_url: str | None = None,
) -> dict[str, Any]:
    """Update stack fields; clears rendered cache."""
    with sync_session(db_url) as s:
        p = s.get(GraphicalProfile, profile_id)
        if p is None:
            raise ValueError(f"graphical profile not found: {profile_id!r}")
        if display_server is not None:
            if display_server not in DISPLAY_SERVERS:
                raise ValueError(
                    f"unknown display_server {display_server!r}; "
                    f"valid: {', '.join(DISPLAY_SERVERS)}"
                )
            p.display_server = display_server
            p.mode = "no-gui" if display_server == "none" else "gui"
        if compositor is not None:
            p.compositor = compositor
        if display_manager is not None:
            p.display_manager = display_manager
        if session_manager is not None:
            p.session_manager = session_manager
        if toolkit_default is not None:
            p.toolkit_default = toolkit_default
        # Invalidate rendered cache
        p.rendered_session_config = None
        p.content_hash = None
        p.rendered_at = None
        p.updated_at = _now()
        s.commit()
        return _profile_to_dict(p)


def list_graphical_profiles(
    distribution_id: str | None = None,
    *,
    db_url: str | None = None,
) -> list[dict[str, Any]]:
    with sync_session(db_url) as s:
        q = select(GraphicalProfile).order_by(GraphicalProfile.name)
        if distribution_id is not None:
            q = q.where(GraphicalProfile.distribution_id == distribution_id)
        return [_profile_to_dict(p) for p in s.scalars(q).all()]


def get_graphical_profile(profile_id: str, *, db_url: str | None = None) -> dict[str, Any]:
    """Return full profile including components and sessions."""
    with sync_session(db_url) as s:
        p = s.get(GraphicalProfile, profile_id)
        if p is None:
            raise ValueError(f"graphical profile not found: {profile_id!r}")
        result = _profile_to_dict(p)
        result["components"] = [
            {
                "id": c.id,
                "component_kind": c.component_kind,
                "package_name": c.package_name,
                "version_constraint": c.version_constraint,
                "is_required": c.is_required,
                "config_fragment": c.config_fragment,
            }
            for c in s.scalars(
                select(GraphicalComponent).where(
                    GraphicalComponent.graphical_profile_id == profile_id
                )
            ).all()
        ]
        result["sessions"] = [
            {
                "id": sess.id,
                "name": sess.name,
                "session_type": sess.session_type,
                "exec_cmd": sess.exec_cmd,
                "is_default": sess.is_default,
                "desktop_entry": sess.desktop_entry,
            }
            for sess in s.scalars(
                select(GraphicalSession).where(
                    GraphicalSession.graphical_profile_id == profile_id
                )
            ).all()
        ]
        return result


# ---------------------------------------------------------------------------
# Components
# ---------------------------------------------------------------------------


def add_component(
    profile_id: str,
    component_kind: str,
    package_name: str,
    *,
    version_constraint: str | None = None,
    config_fragment: dict[str, Any] | None = None,
    is_required: bool = True,
    db_url: str | None = None,
) -> dict[str, Any]:
    """Add a component package to a graphical profile."""
    if component_kind not in COMPONENT_KINDS:
        raise ValueError(
            f"unknown component_kind {component_kind!r}; "
            f"valid: {', '.join(COMPONENT_KINDS)}"
        )
    with sync_session(db_url) as s:
        if s.get(GraphicalProfile, profile_id) is None:
            raise ValueError(f"graphical profile not found: {profile_id!r}")
        c = GraphicalComponent(
            graphical_profile_id=profile_id,
            component_kind=component_kind,
            package_name=package_name,
            version_constraint=version_constraint,
            config_fragment=config_fragment,
            is_required=is_required,
        )
        s.add(c)
        s.commit()
        return {
            "id": c.id,
            "profile_id": profile_id,
            "component_kind": component_kind,
            "package_name": package_name,
            "is_required": is_required,
        }


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

_SESSION_DESKTOP_TEMPLATE = """\
[Desktop Entry]
Name={name}
Comment={description}
Exec={exec_cmd}
TryExec={exec_base}
Type=Application
DesktopNames={desktop_names}
"""


def add_session(
    profile_id: str,
    name: str,
    session_type: str = "wayland",
    *,
    exec_cmd: str | None = None,
    is_default: bool = False,
    db_url: str | None = None,
) -> dict[str, Any]:
    """Add a selectable session entry to a graphical profile.

    The ``desktop_entry`` is auto-generated from the session name and exec_cmd.
    """
    if session_type not in SESSION_TYPES:
        raise ValueError(
            f"unknown session_type {session_type!r}; valid: {', '.join(SESSION_TYPES)}"
        )
    with sync_session(db_url) as s:
        p = s.get(GraphicalProfile, profile_id)
        if p is None:
            raise ValueError(f"graphical profile not found: {profile_id!r}")

        existing = s.scalars(
            select(GraphicalSession).where(
                GraphicalSession.graphical_profile_id == profile_id,
                GraphicalSession.name == name,
            )
        ).first()
        if existing is not None:
            raise ValueError(
                f"session {name!r} already exists on profile {profile_id!r}"
            )

        exec_base = (exec_cmd or "").split()[0] if exec_cmd else ""
        desktop_entry = _SESSION_DESKTOP_TEMPLATE.format(
            name=name,
            description=f"A {session_type} session ({p.compositor or 'generic'})",
            exec_cmd=exec_cmd or "",
            exec_base=exec_base,
            desktop_names=name.upper().replace(" ", "-"),
        )

        sess = GraphicalSession(
            graphical_profile_id=profile_id,
            name=name,
            session_type=session_type,
            exec_cmd=exec_cmd,
            desktop_entry=desktop_entry,
            is_default=is_default,
        )
        s.add(sess)
        s.commit()
        return {
            "id": sess.id,
            "profile_id": profile_id,
            "name": name,
            "session_type": session_type,
            "exec_cmd": exec_cmd,
            "is_default": is_default,
        }


def update_session(
    profile_id: str,
    session_name: str,
    *,
    exec_cmd: str | None = None,
    is_default: bool | None = None,
    db_url: str | None = None,
) -> dict[str, Any]:
    """Update a session entry."""
    with sync_session(db_url) as s:
        sess = s.scalars(
            select(GraphicalSession).where(
                GraphicalSession.graphical_profile_id == profile_id,
                GraphicalSession.name == session_name,
            )
        ).first()
        if sess is None:
            raise ValueError(
                f"session {session_name!r} not found on profile {profile_id!r}"
            )
        if exec_cmd is not None:
            sess.exec_cmd = exec_cmd
            exec_base = exec_cmd.split()[0] if exec_cmd else ""
            p = s.get(GraphicalProfile, profile_id)
            sess.desktop_entry = _SESSION_DESKTOP_TEMPLATE.format(
                name=sess.name,
                description=(
                    f"A {sess.session_type} session "
                    f"({p.compositor if p else 'generic'})"
                ),
                exec_cmd=exec_cmd,
                exec_base=exec_base,
                desktop_names=sess.name.upper().replace(" ", "-"),
            )
        if is_default is not None:
            sess.is_default = is_default
        s.commit()
        return {
            "id": sess.id,
            "profile_id": profile_id,
            "name": sess.name,
            "session_type": sess.session_type,
            "exec_cmd": sess.exec_cmd,
            "is_default": sess.is_default,
        }


# ---------------------------------------------------------------------------
# Render session config
# ---------------------------------------------------------------------------


def render_session_config(profile_id: str, *, db_url: str | None = None) -> dict[str, Any]:
    """Generate a ``.desktop`` session config for the profile's default session.

    The output is deterministic — same inputs → same text → same sha256: hash.
    If the profile has no sessions, a placeholder ``.desktop`` is generated.
    The rendered text is stored on the profile row alongside the content hash.
    """
    with sync_session(db_url) as s:
        p = s.get(GraphicalProfile, profile_id)
        if p is None:
            raise ValueError(f"graphical profile not found: {profile_id!r}")

        sessions = s.scalars(
            select(GraphicalSession).where(
                GraphicalSession.graphical_profile_id == profile_id
            )
        ).all()

        default_sess = next((sess for sess in sessions if sess.is_default), None)
        if default_sess is None and sessions:
            default_sess = sessions[0]

        if default_sess is not None:
            exec_base = (default_sess.exec_cmd or "").split()[0]
            desktop = _SESSION_DESKTOP_TEMPLATE.format(
                name=default_sess.name,
                description=(
                    f"A {default_sess.session_type} session "
                    f"({p.compositor or 'generic'})"
                ),
                exec_cmd=default_sess.exec_cmd or "",
                exec_base=exec_base,
                desktop_names=default_sess.name.upper().replace(" ", "-"),
            )
        else:
            # No sessions defined yet — placeholder
            desktop = _SESSION_DESKTOP_TEMPLATE.format(
                name=p.name,
                description=f"Graphical session for {p.name}",
                exec_cmd=p.compositor or "startx",
                exec_base=p.compositor or "startx",
                desktop_names=p.name.upper().replace(" ", "-"),
            )

        content_hash = "sha256:" + _sha(desktop)
        now = _now()
        p.rendered_session_config = desktop
        p.content_hash = content_hash
        p.rendered_at = now
        p.updated_at = now
        s.commit()

        return {
            "profile_id": profile_id,
            "rendered_session_config": desktop,
            "content_hash": content_hash,
            "rendered_at": now.isoformat(),
        }
