"""Users / Groups / Credentials / Secrets Designer service (M44).

An ``OsUserProfile`` captures the complete set of OS user accounts, groups,
and build-time secret references for a distribution image.

Key functions:

* :func:`create_user_profile` — create a new user profile.
* :func:`get_user_profile` — full detail (groups, users, secrets).
* :func:`update_user_profile` — rename the profile; clears rendered cache.
* :func:`add_os_group` — declare an OS group (name, optional GID, is_system).
* :func:`add_os_user` — declare an OS user account.
* :func:`add_supplementary_group` — add a secondary group to a user.
* :func:`add_secret_variable` — register a named build-time secret reference.
* :func:`render_user_config` — generate /etc/passwd, /etc/group, and a secrets
  manifest; store sha256 content hash on the profile row.
* :func:`list_user_shell_kinds` — enumerate seeded shell paths.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC
from datetime import datetime as _dt
from typing import Any

from sqlalchemy import select

from osfabricum.db.models import (
    OsGroup,
    OsUser,
    OsUserProfile,
    SecretVariable,
    UserShellKind,
    UserSupplementaryGroup,
)
from osfabricum.db.seed_data import USER_SHELL_KINDS
from osfabricum.db.session import sync_session

# ---------------------------------------------------------------------------
# Valid values
# ---------------------------------------------------------------------------

VALID_SECRET_KINDS: frozenset[str] = frozenset(
    {"env-var", "file", "ssh-key", "api-key", "certificate", "gpg-key"}
)

VALID_SHELL_PATHS: frozenset[str] = frozenset(path for path, *_ in USER_SHELL_KINDS)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> _dt:
    return _dt.now(UTC).replace(tzinfo=None)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _profile_to_dict(p: OsUserProfile) -> dict[str, Any]:
    return {
        "id": p.id,
        "name": p.name,
        "distribution_id": p.distribution_id,
        "rendered_passwd": p.rendered_passwd,
        "rendered_group": p.rendered_group,
        "rendered_secrets_manifest": p.rendered_secrets_manifest,
        "content_hash": p.content_hash,
        "rendered_at": p.rendered_at.isoformat() if p.rendered_at else None,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


def _clear_cache(p: OsUserProfile) -> None:
    p.rendered_passwd = None
    p.rendered_group = None
    p.rendered_secrets_manifest = None
    p.content_hash = None
    p.rendered_at = None


# ---------------------------------------------------------------------------
# Shell kinds (seeded, read-only)
# ---------------------------------------------------------------------------


def list_user_shell_kinds(*, db_url: str | None = None) -> list[dict[str, Any]]:
    with sync_session(db_url) as s:
        return [
            {
                "path": k.path,
                "description": k.description,
                "display_order": k.display_order,
            }
            for k in s.scalars(
                select(UserShellKind).order_by(UserShellKind.display_order)
            ).all()
        ]


# ---------------------------------------------------------------------------
# Profile CRUD
# ---------------------------------------------------------------------------


def create_user_profile(
    name: str,
    *,
    distribution_id: str | None = None,
    db_url: str | None = None,
) -> dict[str, Any]:
    """Create a new OS user profile."""
    now = _now()
    with sync_session(db_url) as s:
        existing = s.scalars(
            select(OsUserProfile).where(
                OsUserProfile.distribution_id == distribution_id,
                OsUserProfile.name == name,
            )
        ).first()
        if existing is not None:
            raise ValueError(f"user profile already exists: {name!r}")
        p = OsUserProfile(
            name=name,
            distribution_id=distribution_id,
            created_at=now,
            updated_at=now,
        )
        s.add(p)
        s.commit()
        return _profile_to_dict(p)


def list_user_profiles(
    distribution_id: str | None = None,
    *,
    db_url: str | None = None,
) -> list[dict[str, Any]]:
    with sync_session(db_url) as s:
        q = select(OsUserProfile).order_by(OsUserProfile.name)
        if distribution_id is not None:
            q = q.where(OsUserProfile.distribution_id == distribution_id)
        return [_profile_to_dict(p) for p in s.scalars(q).all()]


def get_user_profile(
    profile_id: str, *, db_url: str | None = None
) -> dict[str, Any]:
    """Return full profile including groups, users (with supplementary groups), and secrets."""
    with sync_session(db_url) as s:
        p = s.get(OsUserProfile, profile_id)
        if p is None:
            raise ValueError(f"user profile not found: {profile_id!r}")
        result = _profile_to_dict(p)

        groups = s.scalars(
            select(OsGroup)
            .where(OsGroup.profile_id == profile_id)
            .order_by(OsGroup.is_system.desc(), OsGroup.gid.nulls_last(), OsGroup.name)
        ).all()
        result["groups"] = [
            {
                "id": g.id,
                "name": g.name,
                "gid": g.gid,
                "is_system": g.is_system,
                "description": g.description,
            }
            for g in groups
        ]

        users = s.scalars(
            select(OsUser)
            .where(OsUser.profile_id == profile_id)
            .order_by(OsUser.is_system.desc(), OsUser.uid.nulls_last(), OsUser.username)
        ).all()
        user_rows = []
        for u in users:
            supps = s.scalars(
                select(UserSupplementaryGroup)
                .where(UserSupplementaryGroup.user_id == u.id)
                .order_by(UserSupplementaryGroup.group_name)
            ).all()
            user_rows.append(
                {
                    "id": u.id,
                    "username": u.username,
                    "uid": u.uid,
                    "primary_group": u.primary_group,
                    "home_dir": u.home_dir,
                    "shell": u.shell,
                    "gecos": u.gecos,
                    "is_system": u.is_system,
                    "is_locked": u.is_locked,
                    "supplementary_groups": [sg.group_name for sg in supps],
                }
            )
        result["users"] = user_rows

        secrets = s.scalars(
            select(SecretVariable)
            .where(SecretVariable.profile_id == profile_id)
            .order_by(SecretVariable.name)
        ).all()
        result["secrets"] = [
            {
                "id": sv.id,
                "name": sv.name,
                "kind": sv.kind,
                "description": sv.description,
                "masked_value": sv.masked_value,
                "is_required": sv.is_required,
            }
            for sv in secrets
        ]
        return result


def update_user_profile(
    profile_id: str,
    *,
    name: str | None = None,
    db_url: str | None = None,
) -> dict[str, Any]:
    """Rename a user profile; clears rendered cache."""
    with sync_session(db_url) as s:
        p = s.get(OsUserProfile, profile_id)
        if p is None:
            raise ValueError(f"user profile not found: {profile_id!r}")
        if name is not None:
            p.name = name
        _clear_cache(p)
        p.updated_at = _now()
        s.commit()
        return _profile_to_dict(p)


# ---------------------------------------------------------------------------
# Groups
# ---------------------------------------------------------------------------


def add_os_group(
    profile_id: str,
    name: str,
    *,
    gid: int | None = None,
    is_system: bool = False,
    description: str = "",
    db_url: str | None = None,
) -> dict[str, Any]:
    """Add an OS group to a user profile."""
    with sync_session(db_url) as s:
        if s.get(OsUserProfile, profile_id) is None:
            raise ValueError(f"user profile not found: {profile_id!r}")
        existing = s.scalars(
            select(OsGroup).where(
                OsGroup.profile_id == profile_id, OsGroup.name == name
            )
        ).first()
        if existing is not None:
            raise ValueError(f"group {name!r} already exists in profile {profile_id!r}")
        g = OsGroup(
            profile_id=profile_id,
            name=name,
            gid=gid,
            is_system=is_system,
            description=description,
        )
        s.add(g)
        s.commit()
        return {
            "id": g.id,
            "profile_id": profile_id,
            "name": name,
            "gid": gid,
            "is_system": is_system,
            "description": description,
        }


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


def add_os_user(
    profile_id: str,
    username: str,
    *,
    uid: int | None = None,
    primary_group: str = "users",
    home_dir: str | None = None,
    shell: str = "/bin/bash",
    gecos: str = "",
    is_system: bool = False,
    is_locked: bool = False,
    password_hash: str | None = None,
    db_url: str | None = None,
) -> dict[str, Any]:
    """Add an OS user account to a user profile."""
    if home_dir is None:
        home_dir = f"/home/{username}"
    with sync_session(db_url) as s:
        if s.get(OsUserProfile, profile_id) is None:
            raise ValueError(f"user profile not found: {profile_id!r}")
        existing = s.scalars(
            select(OsUser).where(
                OsUser.profile_id == profile_id, OsUser.username == username
            )
        ).first()
        if existing is not None:
            raise ValueError(
                f"user {username!r} already exists in profile {profile_id!r}"
            )
        u = OsUser(
            profile_id=profile_id,
            username=username,
            uid=uid,
            primary_group=primary_group,
            home_dir=home_dir,
            shell=shell,
            gecos=gecos,
            is_system=is_system,
            is_locked=is_locked,
            password_hash=password_hash,
        )
        s.add(u)
        s.commit()
        return {
            "id": u.id,
            "profile_id": profile_id,
            "username": username,
            "uid": uid,
            "primary_group": primary_group,
            "home_dir": home_dir,
            "shell": shell,
            "gecos": gecos,
            "is_system": is_system,
            "is_locked": is_locked,
        }


def add_supplementary_group(
    user_id: str,
    group_name: str,
    *,
    db_url: str | None = None,
) -> dict[str, Any]:
    """Add a secondary group membership to an OS user."""
    with sync_session(db_url) as s:
        if s.get(OsUser, user_id) is None:
            raise ValueError(f"os user not found: {user_id!r}")
        existing = s.scalars(
            select(UserSupplementaryGroup).where(
                UserSupplementaryGroup.user_id == user_id,
                UserSupplementaryGroup.group_name == group_name,
            )
        ).first()
        if existing is not None:
            raise ValueError(
                f"user {user_id!r} is already a member of group {group_name!r}"
            )
        sg = UserSupplementaryGroup(user_id=user_id, group_name=group_name)
        s.add(sg)
        s.commit()
        return {"id": sg.id, "user_id": user_id, "group_name": group_name}


# ---------------------------------------------------------------------------
# Secrets
# ---------------------------------------------------------------------------


def add_secret_variable(
    profile_id: str,
    name: str,
    kind: str,
    *,
    description: str = "",
    masked_value: str | None = None,
    is_required: bool = True,
    db_url: str | None = None,
) -> dict[str, Any]:
    """Register a named build-time secret reference in a user profile."""
    if kind not in VALID_SECRET_KINDS:
        raise ValueError(
            f"unknown secret kind {kind!r}; "
            f"valid: {', '.join(sorted(VALID_SECRET_KINDS))}"
        )
    with sync_session(db_url) as s:
        if s.get(OsUserProfile, profile_id) is None:
            raise ValueError(f"user profile not found: {profile_id!r}")
        existing = s.scalars(
            select(SecretVariable).where(
                SecretVariable.profile_id == profile_id,
                SecretVariable.name == name,
            )
        ).first()
        if existing is not None:
            raise ValueError(
                f"secret {name!r} already exists in profile {profile_id!r}"
            )
        sv = SecretVariable(
            profile_id=profile_id,
            name=name,
            kind=kind,
            description=description,
            masked_value=masked_value,
            is_required=is_required,
        )
        s.add(sv)
        s.commit()
        return {
            "id": sv.id,
            "profile_id": profile_id,
            "name": name,
            "kind": kind,
            "description": description,
            "masked_value": masked_value,
            "is_required": is_required,
        }


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

_PASSWD_HEADER = "# /etc/passwd — generated by OSFabricum M44 — do not edit manually\n"
_GROUP_HEADER = "# /etc/group — generated by OSFabricum M44 — do not edit manually\n"


def _gid_for_group(name: str, groups: list[OsGroup]) -> str:
    for g in groups:
        if g.name == name:
            return str(g.gid) if g.gid is not None else "?"
    return "?"


def _build_passwd(users: list[OsUser], groups: list[OsGroup]) -> str:
    lines = [_PASSWD_HEADER]
    sorted_users = sorted(
        users,
        key=lambda u: (0 if u.is_system else 1, u.uid if u.uid is not None else 99999, u.username),
    )
    for u in sorted_users:
        uid = str(u.uid) if u.uid is not None else "?"
        gid = _gid_for_group(u.primary_group, groups)
        shell = "/usr/sbin/nologin" if u.is_locked else u.shell
        lines.append(f"{u.username}:x:{uid}:{gid}:{u.gecos}:{u.home_dir}:{shell}\n")
    return "".join(lines)


def _build_group(
    groups: list[OsGroup],
    memberships: dict[str, list[str]],
) -> str:
    """memberships: group_name → sorted list of usernames with it as supplementary."""
    lines = [_GROUP_HEADER]
    sorted_groups = sorted(
        groups,
        key=lambda g: (0 if g.is_system else 1, g.gid if g.gid is not None else 99999, g.name),
    )
    for g in sorted_groups:
        gid = str(g.gid) if g.gid is not None else "?"
        members = ",".join(sorted(memberships.get(g.name, [])))
        lines.append(f"{g.name}:x:{gid}:{members}\n")
    return "".join(lines)


def render_user_config(
    profile_id: str, *, db_url: str | None = None
) -> dict[str, Any]:
    """Generate /etc/passwd, /etc/group, secrets manifest; store on profile row.

    All three are concatenated for the deterministic sha256: hash.
    """
    with sync_session(db_url) as s:
        p = s.get(OsUserProfile, profile_id)
        if p is None:
            raise ValueError(f"user profile not found: {profile_id!r}")

        groups = s.scalars(
            select(OsGroup).where(OsGroup.profile_id == profile_id)
        ).all()

        users = s.scalars(
            select(OsUser).where(OsUser.profile_id == profile_id)
        ).all()

        # Build supplementary-group → [username] mapping
        group_members: dict[str, list[str]] = {}
        for u in users:
            supps = s.scalars(
                select(UserSupplementaryGroup).where(
                    UserSupplementaryGroup.user_id == u.id
                )
            ).all()
            for sg in supps:
                group_members.setdefault(sg.group_name, []).append(u.username)

        secrets = s.scalars(
            select(SecretVariable)
            .where(SecretVariable.profile_id == profile_id)
            .order_by(SecretVariable.name)
        ).all()

        passwd_text = _build_passwd(list(users), list(groups))
        group_text = _build_group(list(groups), group_members)
        secrets_manifest = json.dumps(
            [
                {
                    "name": sv.name,
                    "kind": sv.kind,
                    "description": sv.description,
                    "is_required": sv.is_required,
                    "masked_value": sv.masked_value,
                }
                for sv in secrets
            ],
            sort_keys=True,
            indent=2,
        )

        body = passwd_text + "\n---\n" + group_text + "\n---\n" + secrets_manifest
        content_hash = "sha256:" + _sha(body)
        now = _now()

        p.rendered_passwd = passwd_text
        p.rendered_group = group_text
        p.rendered_secrets_manifest = secrets_manifest
        p.content_hash = content_hash
        p.rendered_at = now
        p.updated_at = now
        s.commit()

        return {
            "profile_id": profile_id,
            "rendered_passwd": passwd_text,
            "rendered_group": group_text,
            "rendered_secrets_manifest": secrets_manifest,
            "content_hash": content_hash,
            "rendered_at": now.isoformat(),
            "user_count": len(users),
            "group_count": len(groups),
            "secret_count": len(secrets),
        }
