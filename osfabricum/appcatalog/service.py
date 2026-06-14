"""Application Catalog Designer service (M41).

An ``AppCatalogProfile`` is the full definition of which applications a
distribution ships: their categories, groupings, and default role mappings
(e.g. web-browser → firefox).

Key functions:

* :func:`create_catalog_profile` — create a new catalog.
* :func:`get_catalog_profile` — full detail (apps + groups + roles).
* :func:`add_app` — add an application entry to a catalog.
* :func:`add_group` / :func:`add_group_member` — create named app groups.
* :func:`set_default_role` — bind a functional role to an app.
* :func:`render_app_list` — generate a deterministic INI manifest with
  ``sha256:`` content hash, stored on the profile row.
* :func:`list_app_categories` — enumerate the seeded categories.
"""

from __future__ import annotations

import hashlib
from datetime import UTC
from datetime import datetime as _dt
from typing import Any

from sqlalchemy import select

from osfabricum.db.models import (
    AppCatalogProfile,
    AppCategory,
    AppGroup,
    AppGroupMember,
    CatalogApp,
    DefaultAppRole,
)
from osfabricum.db.seed_data import APP_CATEGORIES, DEFAULT_APP_ROLES
from osfabricum.db.session import sync_session

# ---------------------------------------------------------------------------
# Valid values
# ---------------------------------------------------------------------------

VALID_CATEGORIES: frozenset[str] = frozenset(name for name, *_ in APP_CATEGORIES)
VALID_ROLES: frozenset[str] = frozenset(DEFAULT_APP_ROLES)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> _dt:
    return _dt.now(UTC).replace(tzinfo=None)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _profile_to_dict(p: AppCatalogProfile) -> dict[str, Any]:
    return {
        "id": p.id,
        "name": p.name,
        "distribution_id": p.distribution_id,
        "description": p.description,
        "rendered_app_list": p.rendered_app_list,
        "content_hash": p.content_hash,
        "rendered_at": p.rendered_at.isoformat() if p.rendered_at else None,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


# ---------------------------------------------------------------------------
# Categories (read-only seeded data)
# ---------------------------------------------------------------------------


def list_app_categories(*, db_url: str | None = None) -> list[dict[str, Any]]:
    with sync_session(db_url) as s:
        return [
            {
                "name": c.name,
                "description": c.description,
                "icon": c.icon,
                "display_order": c.display_order,
            }
            for c in s.scalars(
                select(AppCategory).order_by(AppCategory.display_order)
            ).all()
        ]


# ---------------------------------------------------------------------------
# Profile CRUD
# ---------------------------------------------------------------------------


def create_catalog_profile(
    name: str,
    *,
    distribution_id: str | None = None,
    description: str | None = None,
    db_url: str | None = None,
) -> dict[str, Any]:
    """Create a new application catalog profile."""
    now = _now()
    with sync_session(db_url) as s:
        existing = s.scalars(
            select(AppCatalogProfile).where(
                AppCatalogProfile.distribution_id == distribution_id,
                AppCatalogProfile.name == name,
            )
        ).first()
        if existing is not None:
            raise ValueError(f"app catalog profile already exists: {name!r}")
        p = AppCatalogProfile(
            name=name,
            distribution_id=distribution_id,
            description=description,
            created_at=now,
            updated_at=now,
        )
        s.add(p)
        s.commit()
        return _profile_to_dict(p)


def update_catalog_profile(
    profile_id: str,
    *,
    description: str | None = None,
    db_url: str | None = None,
) -> dict[str, Any]:
    """Update catalog metadata; clears rendered cache."""
    with sync_session(db_url) as s:
        p = s.get(AppCatalogProfile, profile_id)
        if p is None:
            raise ValueError(f"app catalog profile not found: {profile_id!r}")
        if description is not None:
            p.description = description
        p.rendered_app_list = None
        p.content_hash = None
        p.rendered_at = None
        p.updated_at = _now()
        s.commit()
        return _profile_to_dict(p)


def list_catalog_profiles(
    distribution_id: str | None = None,
    *,
    db_url: str | None = None,
) -> list[dict[str, Any]]:
    with sync_session(db_url) as s:
        q = select(AppCatalogProfile).order_by(AppCatalogProfile.name)
        if distribution_id is not None:
            q = q.where(AppCatalogProfile.distribution_id == distribution_id)
        return [_profile_to_dict(p) for p in s.scalars(q).all()]


def get_catalog_profile(
    profile_id: str, *, db_url: str | None = None
) -> dict[str, Any]:
    """Return full profile including apps, groups, and default roles."""
    with sync_session(db_url) as s:
        p = s.get(AppCatalogProfile, profile_id)
        if p is None:
            raise ValueError(f"app catalog profile not found: {profile_id!r}")
        result = _profile_to_dict(p)

        apps = s.scalars(
            select(CatalogApp).where(
                CatalogApp.catalog_profile_id == profile_id
            )
        ).all()
        result["apps"] = [
            {
                "id": a.id,
                "name": a.name,
                "display_name": a.display_name,
                "description": a.description,
                "category_name": a.category_name,
                "package_name": a.package_name,
                "version_constraint": a.version_constraint,
                "icon_name": a.icon_name,
                "is_default_install": a.is_default_install,
                "is_optional": a.is_optional,
                "tags": a.tags,
            }
            for a in apps
        ]

        groups = s.scalars(
            select(AppGroup).where(AppGroup.catalog_profile_id == profile_id)
        ).all()
        group_list = []
        for g in groups:
            members = s.scalars(
                select(AppGroupMember)
                .where(AppGroupMember.group_id == g.id)
                .order_by(AppGroupMember.position)
            ).all()
            app_ids = {a.id: a.name for a in apps}
            group_list.append(
                {
                    "id": g.id,
                    "name": g.name,
                    "description": g.description,
                    "is_default": g.is_default,
                    "members": [
                        {
                            "catalog_app_id": m.catalog_app_id,
                            "app_name": app_ids.get(m.catalog_app_id, ""),
                            "position": m.position,
                        }
                        for m in members
                    ],
                }
            )
        result["groups"] = group_list

        result["default_roles"] = [
            {
                "id": r.id,
                "role": r.role,
                "app_name": r.app_name,
                "package_name": r.package_name,
            }
            for r in s.scalars(
                select(DefaultAppRole).where(
                    DefaultAppRole.catalog_profile_id == profile_id
                )
            ).all()
        ]
        return result


# ---------------------------------------------------------------------------
# Apps
# ---------------------------------------------------------------------------


def add_app(
    profile_id: str,
    name: str,
    display_name: str,
    package_name: str,
    *,
    description: str | None = None,
    category_name: str = "utilities",
    version_constraint: str | None = None,
    icon_name: str | None = None,
    is_default_install: bool = True,
    is_optional: bool = False,
    tags: list[str] | None = None,
    db_url: str | None = None,
) -> dict[str, Any]:
    """Add an application to a catalog profile."""
    if category_name not in VALID_CATEGORIES:
        raise ValueError(
            f"unknown category {category_name!r}; "
            f"valid: {', '.join(sorted(VALID_CATEGORIES))}"
        )
    with sync_session(db_url) as s:
        if s.get(AppCatalogProfile, profile_id) is None:
            raise ValueError(f"app catalog profile not found: {profile_id!r}")
        existing = s.scalars(
            select(CatalogApp).where(
                CatalogApp.catalog_profile_id == profile_id,
                CatalogApp.name == name,
            )
        ).first()
        if existing is not None:
            raise ValueError(f"app {name!r} already exists in profile {profile_id!r}")
        a = CatalogApp(
            catalog_profile_id=profile_id,
            name=name,
            display_name=display_name,
            package_name=package_name,
            description=description,
            category_name=category_name,
            version_constraint=version_constraint,
            icon_name=icon_name,
            is_default_install=is_default_install,
            is_optional=is_optional,
            tags=tags or [],
            created_at=_now(),
        )
        s.add(a)
        s.commit()
        return {
            "id": a.id,
            "profile_id": profile_id,
            "name": name,
            "display_name": display_name,
            "package_name": package_name,
            "category_name": category_name,
            "is_default_install": is_default_install,
            "is_optional": is_optional,
        }


# ---------------------------------------------------------------------------
# Groups
# ---------------------------------------------------------------------------


def add_group(
    profile_id: str,
    name: str,
    *,
    description: str | None = None,
    is_default: bool = False,
    db_url: str | None = None,
) -> dict[str, Any]:
    """Add a named app group to a catalog profile."""
    with sync_session(db_url) as s:
        if s.get(AppCatalogProfile, profile_id) is None:
            raise ValueError(f"app catalog profile not found: {profile_id!r}")
        existing = s.scalars(
            select(AppGroup).where(
                AppGroup.catalog_profile_id == profile_id,
                AppGroup.name == name,
            )
        ).first()
        if existing is not None:
            raise ValueError(f"group {name!r} already exists in profile {profile_id!r}")
        g = AppGroup(
            catalog_profile_id=profile_id,
            name=name,
            description=description,
            is_default=is_default,
            created_at=_now(),
        )
        s.add(g)
        s.commit()
        return {
            "id": g.id,
            "profile_id": profile_id,
            "name": name,
            "description": description,
            "is_default": is_default,
        }


def add_group_member(
    profile_id: str,
    group_name: str,
    app_name: str,
    *,
    position: int = 0,
    db_url: str | None = None,
) -> dict[str, Any]:
    """Add an app to a group (by name)."""
    with sync_session(db_url) as s:
        g = s.scalars(
            select(AppGroup).where(
                AppGroup.catalog_profile_id == profile_id,
                AppGroup.name == group_name,
            )
        ).first()
        if g is None:
            raise ValueError(
                f"group {group_name!r} not found in profile {profile_id!r}"
            )
        a = s.scalars(
            select(CatalogApp).where(
                CatalogApp.catalog_profile_id == profile_id,
                CatalogApp.name == app_name,
            )
        ).first()
        if a is None:
            raise ValueError(f"app {app_name!r} not found in profile {profile_id!r}")
        existing = s.scalars(
            select(AppGroupMember).where(
                AppGroupMember.group_id == g.id,
                AppGroupMember.catalog_app_id == a.id,
            )
        ).first()
        if existing is not None:
            raise ValueError(
                f"app {app_name!r} is already a member of group {group_name!r}"
            )
        m = AppGroupMember(
            group_id=g.id,
            catalog_app_id=a.id,
            position=position,
        )
        s.add(m)
        s.commit()
        return {
            "group_id": g.id,
            "catalog_app_id": a.id,
            "app_name": app_name,
            "group_name": group_name,
            "position": position,
        }


# ---------------------------------------------------------------------------
# Default roles
# ---------------------------------------------------------------------------


def set_default_role(
    profile_id: str,
    role: str,
    app_name: str,
    package_name: str,
    *,
    db_url: str | None = None,
) -> dict[str, Any]:
    """Bind a functional role to an app (upsert by role)."""
    if role not in VALID_ROLES:
        raise ValueError(
            f"unknown role {role!r}; valid: {', '.join(sorted(VALID_ROLES))}"
        )
    with sync_session(db_url) as s:
        if s.get(AppCatalogProfile, profile_id) is None:
            raise ValueError(f"app catalog profile not found: {profile_id!r}")
        existing = s.scalars(
            select(DefaultAppRole).where(
                DefaultAppRole.catalog_profile_id == profile_id,
                DefaultAppRole.role == role,
            )
        ).first()
        if existing is not None:
            existing.app_name = app_name
            existing.package_name = package_name
            s.commit()
            return {
                "id": existing.id,
                "profile_id": profile_id,
                "role": role,
                "app_name": app_name,
                "package_name": package_name,
            }
        r = DefaultAppRole(
            catalog_profile_id=profile_id,
            role=role,
            app_name=app_name,
            package_name=package_name,
            created_at=_now(),
        )
        s.add(r)
        s.commit()
        return {
            "id": r.id,
            "profile_id": profile_id,
            "role": role,
            "app_name": app_name,
            "package_name": package_name,
        }


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

_CATALOG_HEADER = """\
[Catalog]
Name={name}
GeneratedAt={generated_at}
ContentHash={content_hash}
"""

_APP_SECTION = """\
[App:{name}]
DisplayName={display_name}
Category={category}
Package={package}
DefaultInstall={default_install}
Optional={optional}
Tags={tags}
"""

_GROUP_SECTION = """\
[Group:{name}]
Default={is_default}
Apps={apps}
"""

_ROLE_SECTION = """\
[Role:{role}]
App={app}
Package={package}
"""


def render_app_list(
    profile_id: str, *, db_url: str | None = None
) -> dict[str, Any]:
    """Generate a deterministic INI app-list manifest.

    The output is deterministic — same inputs → same text → same sha256: hash.
    The rendered text and hash are stored on the profile row.
    """
    with sync_session(db_url) as s:
        p = s.get(AppCatalogProfile, profile_id)
        if p is None:
            raise ValueError(f"app catalog profile not found: {profile_id!r}")

        apps = s.scalars(
            select(CatalogApp)
            .where(CatalogApp.catalog_profile_id == profile_id)
            .order_by(CatalogApp.name)
        ).all()
        groups = s.scalars(
            select(AppGroup)
            .where(AppGroup.catalog_profile_id == profile_id)
            .order_by(AppGroup.name)
        ).all()
        roles = s.scalars(
            select(DefaultAppRole)
            .where(DefaultAppRole.catalog_profile_id == profile_id)
            .order_by(DefaultAppRole.role)
        ).all()

        now = _now()
        placeholder_hash = "sha256:pending"
        body_parts: list[str] = []
        for a in apps:
            body_parts.append(
                _APP_SECTION.format(
                    name=a.name,
                    display_name=a.display_name,
                    category=a.category_name,
                    package=a.package_name,
                    default_install=str(a.is_default_install).lower(),
                    optional=str(a.is_optional).lower(),
                    tags=",".join(a.tags),
                )
            )

        app_id_to_name = {a.id: a.name for a in apps}
        for g in groups:
            members = s.scalars(
                select(AppGroupMember)
                .where(AppGroupMember.group_id == g.id)
                .order_by(AppGroupMember.position)
            ).all()
            member_names = ",".join(
                app_id_to_name.get(m.catalog_app_id, m.catalog_app_id)
                for m in members
            )
            body_parts.append(
                _GROUP_SECTION.format(
                    name=g.name,
                    is_default=str(g.is_default).lower(),
                    apps=member_names,
                )
            )

        for r in roles:
            body_parts.append(
                _ROLE_SECTION.format(
                    role=r.role,
                    app=r.app_name,
                    package=r.package_name,
                )
            )

        body = "".join(body_parts)
        content_hash = "sha256:" + _sha(body)
        header = _CATALOG_HEADER.format(
            name=p.name,
            generated_at=now.isoformat(),
            content_hash=content_hash,
        )
        rendered = header + body

        p.rendered_app_list = rendered
        p.content_hash = content_hash
        p.rendered_at = now
        p.updated_at = now
        s.commit()

        return {
            "profile_id": profile_id,
            "rendered_app_list": rendered,
            "content_hash": content_hash,
            "rendered_at": now.isoformat(),
            "app_count": len(apps),
            "group_count": len(groups),
            "role_count": len(roles),
        }
