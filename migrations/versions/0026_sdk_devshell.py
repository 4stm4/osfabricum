"""0026 — SDK / dev-shell export designer (M50)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.orm import Session

from osfabricum.db.seed_data import seed_sdk_export_kinds

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    existing_tables = sa.inspect(bind).get_table_names()
    if "sdk_export_kinds" in existing_tables:
        return

    op.create_table(
        "sdk_export_kinds",
        sa.Column("kind", sa.String(32), primary_key=True),
        sa.Column("label", sa.String(64), nullable=False, server_default=""),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("display_order", sa.Integer, nullable=False, server_default="0"),
    )

    op.create_table(
        "sdk_profiles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column(
            "distribution_id",
            sa.String(36),
            sa.ForeignKey("distributions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("export_format", sa.String(32), nullable=False, server_default="shell-env"),
        sa.Column("python_version", sa.String(16), nullable=False, server_default="3.11"),
        sa.Column("include_debug_symbols", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("rendered_setup_script", sa.Text, nullable=True),
        sa.Column("rendered_env_script", sa.Text, nullable=True),
        sa.Column("content_hash", sa.String(71), nullable=True),
        sa.Column("rendered_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("distribution_id", "name", name="uq_sdk_profiles_dist_name"),
    )

    op.create_table(
        "sdk_variables",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "profile_id",
            sa.String(36),
            sa.ForeignKey("sdk_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("value", sa.Text, nullable=False, server_default=""),
        sa.Column("description", sa.String(256), nullable=False, server_default=""),
        sa.Column("is_secret", sa.Boolean, nullable=False, server_default="0"),
        sa.UniqueConstraint("profile_id", "key", name="uq_sdk_variables_profile_key"),
    )

    with Session(bind) as s:
        seed_sdk_export_kinds(s)
        s.commit()


def downgrade() -> None:
    op.drop_table("sdk_variables")
    op.drop_table("sdk_profiles")
    op.drop_table("sdk_export_kinds")
