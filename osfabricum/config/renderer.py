"""Config template rendering (M11).

Uses Python's built-in :mod:`string` module ``Template`` so there are no
extra dependencies.  Variables use the ``${variable}`` or ``$variable``
syntax.  All values must be strings (or convertible to strings).

``render_template_str``
    Low-level: render a template string directly with a values dict.

``render_config``
    High-level: look up a :class:`~osfabricum.db.models.ConfigTemplate` and
    the most-specific :class:`~osfabricum.db.models.ConfigValue` row
    (board wins over profile wins over distribution-wide), merge with any
    caller-supplied ``extra_values``, then render.
"""

from __future__ import annotations

import string
from pathlib import Path
from typing import Any

from sqlalchemy import select

from osfabricum.db.models import Artifact, Board, ConfigTemplate, ConfigValue, Profile
from osfabricum.db.session import sync_session


def render_template_str(template_text: str, values: dict[str, str]) -> bytes:
    """Render *template_text* with *values* and return UTF-8 bytes.

    Parameters
    ----------
    template_text:
        A :class:`string.Template`-compatible string.  Variables are
        written as ``$name`` or ``${name}``.
    values:
        Mapping of variable name → string value.  All values are
        coerced to :class:`str` before substitution.

    Returns
    -------
    bytes
        UTF-8-encoded rendered output.

    Raises
    ------
    KeyError
        If a required variable is missing from *values*.
    """
    tmpl = string.Template(template_text)
    rendered = tmpl.substitute({k: str(v) for k, v in values.items()})
    return rendered.encode("utf-8")


def render_config(
    *,
    template_name: str,
    board_name: str | None = None,
    profile_name: str | None = None,
    store_root: Path | None = None,
    db_url: str | None = None,
    extra_values: dict[str, str] | None = None,
) -> bytes:
    """Render a named config template using values from the database.

    Resolution order (most-specific wins):
    1. *extra_values* (caller-supplied, always wins)
    2. ``ConfigValue`` row matched by *board_name* (if given)
    3. ``ConfigValue`` row matched by *profile_name* (if given)
    4. Default values from ``ConfigTemplate.schema_json["defaults"]``

    Parameters
    ----------
    template_name:
        Name of the :class:`~osfabricum.db.models.ConfigTemplate` row.
    board_name:
        Board name to look up board-level ``ConfigValue``.
    profile_name:
        Profile name to look up profile-level ``ConfigValue``.
    store_root:
        Artifact store root, used to load the template blob from disk.
        When ``None`` the template text defaults to ``""`` unless already
        embedded in ``ConfigTemplate.schema_json["template"]``.
    db_url:
        SQLAlchemy database URL.
    extra_values:
        Additional substitution values that override everything else.

    Returns
    -------
    bytes
        UTF-8-encoded rendered output.
    """
    with sync_session(db_url) as session:
        tmpl_row: ConfigTemplate | None = session.scalar(
            select(ConfigTemplate).where(ConfigTemplate.name == template_name)
        )
        if tmpl_row is None:
            raise ValueError(f"config template not found: {template_name!r}")

        schema: dict[str, Any] = dict(tmpl_row.schema_json or {})

        # Template text: try embedded first, then artifact blob
        template_text: str = schema.get("template", "")
        has_artifact = tmpl_row.template_artifact_id is not None and store_root is not None
        if not template_text and has_artifact:
            art: Artifact | None = session.scalar(
                select(Artifact).where(Artifact.id == tmpl_row.template_artifact_id)
            )
            if art is not None:
                from osfabricum.store.layout import blob_path

                bp = blob_path(store_root, art.blob_sha256)
                if bp.exists():
                    template_text = bp.read_text("utf-8")

        merged: dict[str, str] = {k: str(v) for k, v in schema.get("defaults", {}).items()}

        # Profile-level values
        if profile_name is not None:
            profile_row: Profile | None = session.scalar(
                select(Profile).where(Profile.name == profile_name)
            )
            if profile_row is not None:
                cv_profile: ConfigValue | None = session.scalar(
                    select(ConfigValue).where(
                        ConfigValue.template_id == tmpl_row.id,
                        ConfigValue.profile_id == profile_row.id,
                        ConfigValue.board_id.is_(None),
                    )
                )
                if cv_profile is not None:
                    for k, v in (cv_profile.values_json or {}).items():
                        merged[k] = str(v)

        # Board-level values (most specific, overrides profile)
        if board_name is not None:
            board_row: Board | None = session.scalar(
                select(Board).where(Board.name == board_name)
            )
            if board_row is not None:
                cv_board: ConfigValue | None = session.scalar(
                    select(ConfigValue).where(
                        ConfigValue.template_id == tmpl_row.id,
                        ConfigValue.board_id == board_row.id,
                    )
                )
                if cv_board is not None:
                    for k, v in (cv_board.values_json or {}).items():
                        merged[k] = str(v)

    # Caller-supplied values win over everything
    if extra_values:
        merged.update({k: str(v) for k, v in extra_values.items()})

    return render_template_str(template_text, merged)
