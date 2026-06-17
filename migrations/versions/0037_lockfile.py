"""0037 — Manifest / Lockfile System (M62)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    existing_tables = sa.inspect(bind).get_table_names()
    if "lockfiles" in existing_tables:
        return

    op.create_table(
        "lockfiles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "distribution_id", sa.String(36),
            sa.ForeignKey("distributions.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column(
            "profile_id", sa.String(36),
            sa.ForeignKey("profiles.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column(
            "build_id", sa.String(36),
            sa.ForeignKey("builds.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("lock_version", sa.String(32), nullable=False, server_default="1"),
        sa.Column("rendered_lock", sa.Text, nullable=True),
        sa.Column("content_hash", sa.String(80), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )

    op.create_table(
        "lockfile_entries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "lockfile_id", sa.String(36),
            sa.ForeignKey("lockfiles.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("entry_kind", sa.String(32), nullable=False),
        sa.Column("entry_key", sa.String(256), nullable=False),
        sa.Column("version", sa.String(128), nullable=False, server_default=""),
        sa.Column("source_hash", sa.String(80), nullable=True),
        sa.Column("extra_json", sa.Text, nullable=True),
    )


def downgrade() -> None:
    op.drop_table("lockfile_entries")
    op.drop_table("lockfiles")
