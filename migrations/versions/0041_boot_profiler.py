"""0041 — Boot / Performance Profiler (M66)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    existing_tables = sa.inspect(bind).get_table_names()
    if "boot_profiles" in existing_tables:
        return

    op.create_table(
        "boot_profiles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "build_id", sa.String(36),
            sa.ForeignKey("builds.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("capture_method", sa.String(16), nullable=False, server_default="qemu"),
        sa.Column("total_boot_ms", sa.Integer, nullable=True),
        sa.Column("rendered_timeline", sa.Text, nullable=True),
        sa.Column("summary_json", sa.Text, nullable=True),
        sa.Column("content_hash", sa.String(80), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )

    op.create_table(
        "boot_samples",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "boot_profile_id", sa.String(36),
            sa.ForeignKey("boot_profiles.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("event_kind", sa.String(32), nullable=False),
        sa.Column("event_name", sa.String(256), nullable=False),
        sa.Column("timestamp_ms", sa.Integer, nullable=False, server_default="0"),
        sa.Column("duration_ms", sa.Integer, nullable=True),
        sa.Column("is_critical_path", sa.Boolean, nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_table("boot_samples")
    op.drop_table("boot_profiles")
