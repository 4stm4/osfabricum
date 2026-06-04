"""add_boot_chain_tables

Revision ID: b3470647df99
Revises: 77de5345d126
Create Date: 2026-06-04 13:37:18.423688

M31: Boot Chain Designer

Creates 4 tables for boot chain management:
- boot_chains: Boot chain definitions
- boot_chain_templates: Template content for boot files
- boot_chain_files: Individual boot files to generate
- boot_chain_bindings: Board/profile bindings for boot chains
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b3470647df99"
down_revision: str | Sequence[str] | None = "77de5345d126"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Guard: already present (fresh install via create_all or previous run).
    if "boot_chains" in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    # boot_chains table
    op.create_table(
        "boot_chains",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "boot_scheme_id", sa.String(36), sa.ForeignKey("boot_schemes.id"), nullable=False
        ),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("metadata_json", sa.JSON, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_boot_chains_boot_scheme_id", "boot_chains", ["boot_scheme_id"])

    # boot_chain_templates table
    op.create_table(
        "boot_chain_templates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("boot_chain_id", sa.String(36), sa.ForeignKey("boot_chains.id"), nullable=False),
        sa.Column(
            "template_type", sa.String(64), nullable=False
        ),  # grub_cfg, uboot_env, config_txt, etc.
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("variables", sa.JSON, nullable=True),  # Available template variables
        sa.Column("metadata_json", sa.JSON, nullable=True),
    )
    op.create_index(
        "ix_boot_chain_templates_boot_chain_id", "boot_chain_templates", ["boot_chain_id"]
    )

    # boot_chain_files table
    op.create_table(
        "boot_chain_files",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("boot_chain_id", sa.String(36), sa.ForeignKey("boot_chains.id"), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("content_template", sa.Text, nullable=True),  # Template content or reference
        sa.Column(
            "template_id", sa.String(36), sa.ForeignKey("boot_chain_templates.id"), nullable=True
        ),
        sa.Column("placement", sa.String(255), nullable=False),  # /boot, /boot/efi, etc.
        sa.Column("required", sa.Boolean, nullable=False, default=True),
        sa.Column("permissions", sa.String(16), nullable=True),  # e.g., "0644"
        sa.Column("metadata_json", sa.JSON, nullable=True),
    )
    op.create_index("ix_boot_chain_files_boot_chain_id", "boot_chain_files", ["boot_chain_id"])

    # boot_chain_bindings table (which boards/profiles use which boot chains)
    op.create_table(
        "boot_chain_bindings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("boot_chain_id", sa.String(36), sa.ForeignKey("boot_chains.id"), nullable=False),
        sa.Column("board_id", sa.String(36), sa.ForeignKey("boards.id"), nullable=True),
        sa.Column("profile_id", sa.String(36), sa.ForeignKey("profiles.id"), nullable=True),
        sa.Column("is_default", sa.Boolean, nullable=False, default=False),
        sa.Column("priority", sa.Integer, nullable=False, default=100),  # For conflict resolution
        sa.Column("metadata_json", sa.JSON, nullable=True),
    )
    op.create_index(
        "ix_boot_chain_bindings_boot_chain_id", "boot_chain_bindings", ["boot_chain_id"]
    )
    op.create_index("ix_boot_chain_bindings_board_id", "boot_chain_bindings", ["board_id"])
    op.create_index("ix_boot_chain_bindings_profile_id", "boot_chain_bindings", ["profile_id"])


def downgrade() -> None:
    op.drop_table("boot_chain_bindings")
    op.drop_table("boot_chain_files")
    op.drop_table("boot_chain_templates")
    op.drop_table("boot_chains")


# Made with Bob
