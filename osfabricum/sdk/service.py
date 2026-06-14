"""Business logic for M50 — SDK / dev-shell export designer."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import select

from osfabricum.db.models import SDKExportKind, SDKProfile, SDKVariable, _now, _uuid

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

VALID_EXPORT_FORMATS: frozenset[str] = frozenset(
    {"pip", "conda", "nix", "shell-env", "docker"}
)

# ---------------------------------------------------------------------------
# Export kinds
# ---------------------------------------------------------------------------


def list_sdk_export_kinds(session: "Session") -> list[SDKExportKind]:
    return list(
        session.scalars(
            select(SDKExportKind).order_by(SDKExportKind.display_order)
        ).all()
    )


# ---------------------------------------------------------------------------
# SDK profiles — CRUD
# ---------------------------------------------------------------------------


def create_sdk_profile(
    session: "Session",
    name: str,
    export_format: str = "shell-env",
    distribution_id: str | None = None,
    description: str = "",
    python_version: str = "3.11",
    include_debug_symbols: bool = False,
) -> SDKProfile:
    if export_format not in VALID_EXPORT_FORMATS:
        raise ValueError(
            f"Invalid export_format {export_format!r}. "
            f"Valid: {sorted(VALID_EXPORT_FORMATS)}"
        )
    existing = session.scalar(
        select(SDKProfile).where(
            SDKProfile.distribution_id == distribution_id,
            SDKProfile.name == name,
        )
    )
    if existing is not None:
        raise ValueError(
            f"SDK profile {name!r} already exists for distribution {distribution_id!r}"
        )
    now = _now()
    p = SDKProfile(
        id=_uuid(),
        name=name,
        distribution_id=distribution_id,
        description=description,
        export_format=export_format,
        python_version=python_version,
        include_debug_symbols=include_debug_symbols,
        created_at=now,
        updated_at=now,
    )
    session.add(p)
    session.flush()
    return p


def list_sdk_profiles(
    session: "Session",
    distribution_id: str | None = None,
) -> list[SDKProfile]:
    q = select(SDKProfile).order_by(SDKProfile.name)
    if distribution_id is not None:
        q = q.where(SDKProfile.distribution_id == distribution_id)
    return list(session.scalars(q).all())


def get_sdk_profile(session: "Session", profile_id: str) -> SDKProfile:
    p = session.get(SDKProfile, profile_id)
    if p is None:
        raise KeyError(f"SDK profile {profile_id!r} not found")
    return p


def update_sdk_profile(session: "Session", profile_id: str, **kwargs: object) -> SDKProfile:
    p = get_sdk_profile(session, profile_id)
    if "export_format" in kwargs and kwargs["export_format"] not in VALID_EXPORT_FORMATS:
        raise ValueError(
            f"Invalid export_format {kwargs['export_format']!r}. "
            f"Valid: {sorted(VALID_EXPORT_FORMATS)}"
        )
    for key, val in kwargs.items():
        setattr(p, key, val)
    p.updated_at = _now()
    _invalidate(session, profile_id)
    session.flush()
    return p


# ---------------------------------------------------------------------------
# SDK variables
# ---------------------------------------------------------------------------


def set_sdk_variable(
    session: "Session",
    profile_id: str,
    key: str,
    value: str,
    description: str = "",
    is_secret: bool = False,
) -> SDKVariable:
    get_sdk_profile(session, profile_id)
    existing = session.scalar(
        select(SDKVariable).where(
            SDKVariable.profile_id == profile_id,
            SDKVariable.key == key,
        )
    )
    if existing is not None:
        existing.value = value
        existing.description = description
        existing.is_secret = is_secret
        _invalidate(session, profile_id)
        session.flush()
        return existing
    var = SDKVariable(
        id=_uuid(),
        profile_id=profile_id,
        key=key,
        value=value,
        description=description,
        is_secret=is_secret,
    )
    session.add(var)
    _invalidate(session, profile_id)
    session.flush()
    return var


def list_sdk_variables(session: "Session", profile_id: str) -> list[SDKVariable]:
    get_sdk_profile(session, profile_id)
    return list(
        session.scalars(
            select(SDKVariable)
            .where(SDKVariable.profile_id == profile_id)
            .order_by(SDKVariable.key)
        ).all()
    )


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


def render_sdk_export(session: "Session", profile_id: str) -> SDKProfile:
    p = get_sdk_profile(session, profile_id)
    variables = list_sdk_variables(session, profile_id)

    setup = _render_setup_script(p, variables)
    env = _render_env_script(p, variables)

    combined = setup + "\n" + env
    content_hash = "sha256:" + hashlib.sha256(combined.encode()).hexdigest()

    p.rendered_setup_script = setup
    p.rendered_env_script = env
    p.content_hash = content_hash
    p.rendered_at = datetime.utcnow()
    session.flush()
    return p


def _render_setup_script(profile: SDKProfile, variables: list[SDKVariable]) -> str:
    lines: list[str] = [
        "#!/usr/bin/env bash",
        f"# OSFabricum SDK setup — {profile.name}",
        f"# export_format: {profile.export_format}",
        f"# python_version: {profile.python_version}",
        "",
    ]

    if profile.export_format == "pip":
        lines += [
            "# --- Pip / venv ---",
            f'python{profile.python_version} -m venv .venv',
            "source .venv/bin/activate",
            "",
            "# requirements.txt",
        ]
        if profile.include_debug_symbols:
            lines.append("# (debug symbols requested — install debug packages below)")
        lines += [
            "pip install --upgrade pip",
            "# pip install -r requirements.txt",
            "",
        ]

    elif profile.export_format == "conda":
        lines += [
            "# --- Conda ---",
            "# environment.yml",
            "# name: " + profile.name.lower().replace(" ", "-"),
            f"# python: {profile.python_version}",
            "conda env create -f environment.yml",
            f"conda activate {profile.name.lower().replace(' ', '-')}",
            "",
        ]

    elif profile.export_format == "nix":
        lines += [
            "# --- Nix Shell ---",
            "# shell.nix",
            "# { pkgs ? import <nixpkgs> {} }:",
            "# pkgs.mkShell {",
            "#   buildInputs = [ pkgs.python3 ];",
            "# }",
            "nix-shell shell.nix",
            "",
        ]

    elif profile.export_format == "shell-env":
        lines += [
            "# --- Shell Environment ---",
            "# Source this file: eval $(osfabricumctl sdk render <id> --env)",
        ]

    elif profile.export_format == "docker":
        lines += [
            "# --- Docker Dev Container ---",
            f"FROM python:{profile.python_version}-slim",
            "WORKDIR /workspace",
            "COPY requirements.txt .",
            "RUN pip install -r requirements.txt",
        ]
        if profile.include_debug_symbols:
            lines.append("RUN apt-get install -y python3-dbg")

    if variables:
        lines.append("")
        lines.append("[variables]")
        for v in variables:
            mask = "****" if v.is_secret else v.value
            comment = f"  # {v.description}" if v.description else ""
            lines.append(f"{v.key} = {mask}{comment}")

    return "\n".join(lines) + "\n"


def _render_env_script(profile: SDKProfile, variables: list[SDKVariable]) -> str:
    lines: list[str] = [
        "#!/usr/bin/env bash",
        f"# OSFabricum SDK env — {profile.name} (eval-able)",
        "",
    ]
    for v in variables:
        if not v.is_secret:
            safe = v.value.replace("'", "'\\''")
            lines.append(f"export {v.key}='{safe}'")
        else:
            lines.append(f"# {v.key} is a secret — set manually")
    lines.append("")
    lines.append(f"export OSF_SDK_PROFILE={profile.id!r}")
    lines.append(f"export OSF_SDK_FORMAT={profile.export_format!r}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _invalidate(session: "Session", profile_id: str) -> None:
    p = session.get(SDKProfile, profile_id)
    if p is not None:
        p.content_hash = None
        p.rendered_at = None
