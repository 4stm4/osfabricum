"""M40 — Graphical Shell Designer.

Extends graphical_profiles with display-server/compositor/DM/render columns.
Creates: compositor_backends, display_manager_backends, graphical_components,
graphical_sessions.
Seeds 10 compositor backends and 6 display manager backends.

Revision ID: 0016
Revises: 0015
Create Date: 2026-06-10
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None

# New columns for graphical_profiles (name → type, nullable)
_NEW_COLS: list[tuple[str, sa.types.TypeEngine]] = [
    ("display_server", sa.String(32)),
    ("compositor", sa.String(64)),
    ("display_manager", sa.String(64)),
    ("session_manager", sa.String(64)),
    ("toolkit_default", sa.String(32)),
    ("rendered_session_config", sa.Text),
    ("content_hash", sa.String(128)),
    ("rendered_at", sa.DateTime),
    ("created_at", sa.DateTime),
    ("updated_at", sa.DateTime),
]


def upgrade() -> None:
    bind = op.get_bind()
    existing_tables = set(sa.inspect(bind).get_table_names())
    fresh = "compositor_backends" not in existing_tables

    # Extend graphical_profiles (per-column guard)
    existing_cols = {c["name"] for c in sa.inspect(bind).get_columns("graphical_profiles")}
    for col_name, col_type in _NEW_COLS:
        if col_name not in existing_cols:
            op.add_column(
                "graphical_profiles", sa.Column(col_name, col_type, nullable=True)
            )

    if not fresh:
        return  # tables already created by create_all (fresh install)

    op.create_table(
        "compositor_backends",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False, unique=True),
        sa.Column("description", sa.Text, nullable=False, default=""),
        sa.Column("protocol", sa.String(16), nullable=False, default="none"),
        sa.Column("package_name", sa.String(128), nullable=True),
        sa.Column("config_template", sa.Text, nullable=False, default=""),
    )
    op.create_index("ix_compositor_backends_name", "compositor_backends", ["name"])

    op.create_table(
        "display_manager_backends",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False, unique=True),
        sa.Column("description", sa.Text, nullable=False, default=""),
        sa.Column("package_name", sa.String(128), nullable=True),
        sa.Column("config_template", sa.Text, nullable=False, default=""),
    )
    op.create_index(
        "ix_display_manager_backends_name", "display_manager_backends", ["name"]
    )

    op.create_table(
        "graphical_components",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "graphical_profile_id",
            sa.String(36),
            sa.ForeignKey("graphical_profiles.id"),
            nullable=False,
        ),
        sa.Column("component_kind", sa.String(64), nullable=False),
        sa.Column("package_name", sa.String(128), nullable=False),
        sa.Column("version_constraint", sa.String(64), nullable=True),
        sa.Column("config_fragment", sa.JSON, nullable=True),
        sa.Column("is_required", sa.Boolean, nullable=False, default=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint(
            "graphical_profile_id",
            "component_kind",
            "package_name",
            name="uq_graphical_components_profile_kind_pkg",
        ),
    )
    op.create_index(
        "ix_graphical_components_profile_id",
        "graphical_components",
        ["graphical_profile_id"],
    )

    op.create_table(
        "graphical_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "graphical_profile_id",
            sa.String(36),
            sa.ForeignKey("graphical_profiles.id"),
            nullable=False,
        ),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("session_type", sa.String(16), nullable=False, default="wayland"),
        sa.Column("exec_cmd", sa.String(256), nullable=True),
        sa.Column("desktop_entry", sa.Text, nullable=True),
        sa.Column("is_default", sa.Boolean, nullable=False, default=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint(
            "graphical_profile_id",
            "name",
            name="uq_graphical_sessions_profile_name",
        ),
    )
    op.create_index(
        "ix_graphical_sessions_profile_id",
        "graphical_sessions",
        ["graphical_profile_id"],
    )

    # Seed compositor and display manager backends
    from osfabricum.db.seed_data import (  # noqa: PLC0415
        COMPOSITOR_BACKENDS,
        DISPLAY_MANAGER_BACKENDS,
    )

    now = sa.func.now()  # noqa: F841 — used implicitly via DB default

    compositor_table = sa.table(
        "compositor_backends",
        sa.column("id", sa.String),
        sa.column("name", sa.String),
        sa.column("description", sa.String),
        sa.column("protocol", sa.String),
        sa.column("package_name", sa.String),
        sa.column("config_template", sa.String),
    )
    dm_table = sa.table(
        "display_manager_backends",
        sa.column("id", sa.String),
        sa.column("name", sa.String),
        sa.column("description", sa.String),
        sa.column("package_name", sa.String),
        sa.column("config_template", sa.String),
    )

    import uuid  # noqa: PLC0415

    existing_compositors = {
        row[0]
        for row in bind.execute(
            sa.text("SELECT name FROM compositor_backends")
        ).fetchall()
    }
    for name, description, protocol, package_name, config_template in COMPOSITOR_BACKENDS:
        if name in existing_compositors:
            continue
        bind.execute(
            compositor_table.insert().values(
                id=str(uuid.uuid4()),
                name=name,
                description=description,
                protocol=protocol,
                package_name=package_name or None,
                config_template=config_template,
            )
        )

    existing_dms = {
        row[0]
        for row in bind.execute(
            sa.text("SELECT name FROM display_manager_backends")
        ).fetchall()
    }
    for name, description, package_name, config_template in DISPLAY_MANAGER_BACKENDS:
        if name in existing_dms:
            continue
        bind.execute(
            dm_table.insert().values(
                id=str(uuid.uuid4()),
                name=name,
                description=description,
                package_name=package_name or None,
                config_template=config_template,
            )
        )


def downgrade() -> None:
    for tbl in (
        "graphical_sessions",
        "graphical_components",
        "display_manager_backends",
        "compositor_backends",
    ):
        try:
            op.drop_table(tbl)
        except Exception:
            pass

    existing_cols = {
        c["name"]
        for c in sa.inspect(op.get_bind()).get_columns("graphical_profiles")
    }
    for col_name, _ in reversed(_NEW_COLS):
        if col_name in existing_cols:
            try:
                op.drop_column("graphical_profiles", col_name)
            except Exception:
                pass
