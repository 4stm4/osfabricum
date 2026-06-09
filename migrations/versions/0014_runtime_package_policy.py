"""M38 — Runtime Package Policy: RuntimePackageBackend, RuntimePackagePolicy.

Also adds runtime_policy_id column to profiles.

Revision ID: 0014
Revises: 0013
Create Date: 2026-06-07
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

# Seeded backends: (name, description, config_template)
_BACKENDS = [
    ("none", "No package manager — immutable or build-time-only image", ""),
    (
        "osf-pkg",
        "OSFabricum native package manager",
        "# OSFabricum package feed\nfeed {feed_name} {feed_url}\nchannel {channel}\n",
    ),
    (
        "opkg",
        "opkg (OpenWRT-compatible lightweight package manager)",
        "src/gz {feed_name} {feed_url}\n",
    ),
    (
        "apk",
        "Alpine Package Keeper (apk) — used by Alpine and musl-based images",
        "{feed_url}\n",
    ),
    (
        "dpkg",
        "dpkg/apt-compatible package manager (Debian/Ubuntu style)",
        "deb {feed_url} {channel} main\n",
    ),
    (
        "rpm",
        "rpm/dnf-compatible package manager (Red Hat style)",
        "[{feed_name}]\nbaseurl={feed_url}\nenabled=1\ngpgcheck=1\n",
    ),
]


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    fresh = "runtime_package_backends" not in existing

    if fresh:
        op.create_table(
            "runtime_package_backends",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("name", sa.String(32), nullable=False, unique=True),
            sa.Column("description", sa.Text, nullable=False),
            sa.Column("config_template", sa.Text, nullable=False),
        )

        op.create_table(
            "runtime_package_policies",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("profile_id", sa.String(36), nullable=False, unique=True),
            sa.Column("policy", sa.String(32), nullable=False),
            sa.Column("backend_name", sa.String(32), nullable=False),
            sa.Column("feed_ids", sa.JSON, nullable=False),
            sa.Column("config_path", sa.String(256), nullable=False),
            sa.Column("rendered_config", sa.Text, nullable=True),
            sa.Column("rendered_at", sa.DateTime, nullable=True),
            sa.Column("created_at", sa.DateTime, nullable=False),
            sa.Column("updated_at", sa.DateTime, nullable=False),
        )
        op.create_index(
            "ix_runtime_package_policies_profile_id",
            "runtime_package_policies",
            ["profile_id"],
        )

    # Seed backends (idempotent)
    import uuid  # noqa: PLC0415

    bind = op.get_bind()
    _q = sa.text("SELECT name FROM runtime_package_backends")
    existing_names = {r[0] for r in bind.execute(_q)}
    for name, description, config_template in _BACKENDS:
        if name not in existing_names:
            bind.execute(
                sa.text(
                    "INSERT INTO runtime_package_backends"
                    " (id, name, description, config_template)"
                    " VALUES (:id, :name, :desc, :tpl)"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "name": name,
                    "desc": description,
                    "tpl": config_template,
                },
            )

    # Add runtime_policy_id to profiles (guarded)
    existing_cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("profiles")}
    if "runtime_policy_id" not in existing_cols:
        op.add_column("profiles", sa.Column("runtime_policy_id", sa.String(36), nullable=True))


def downgrade() -> None:
    existing_cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("profiles")}
    if "runtime_policy_id" in existing_cols:
        op.drop_column("profiles", "runtime_policy_id")

    op.drop_index("ix_runtime_package_policies_profile_id", "runtime_package_policies")
    op.drop_table("runtime_package_policies")
    op.drop_table("runtime_package_backends")
