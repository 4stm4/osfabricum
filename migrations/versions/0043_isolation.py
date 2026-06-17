"""0043 — Build Isolation / Sandbox Policy (M68)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0043"
down_revision = "0042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    existing_tables = sa.inspect(bind).get_table_names()
    if "isolation_policies" in existing_tables:
        return

    op.create_table(
        "isolation_policies",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False, unique=True),
        sa.Column("label", sa.String(256), nullable=False, server_default=""),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("mode", sa.String(32), nullable=False, server_default="none"),
        sa.Column("network_allowed", sa.Boolean, nullable=False, server_default="1"),
        sa.Column("write_access", sa.String(16), nullable=False, server_default="build-dir"),
        sa.Column("cache_mode", sa.String(8), nullable=False, server_default="ro"),
        sa.Column("secret_access", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("privileged", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )

    op.create_table(
        "recipe_isolation_requirements",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("recipe_id", sa.String(36), nullable=True),
        sa.Column("required_mode", sa.String(32), nullable=False),
        sa.Column("reason", sa.Text, nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("recipe_isolation_requirements")
    op.drop_table("isolation_policies")
