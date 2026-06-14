"""M45 — Network Designer.

Creates: network_interface_kinds, network_profiles, net_interfaces,
net_dns_entries, net_routes, net_firewall_rules.
Seeds 9 interface kinds.

Revision ID: 0021
Revises: 0020
Create Date: 2026-06-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    existing_tables = set(sa.inspect(bind).get_table_names())
    fresh = "network_interface_kinds" not in existing_tables

    if not fresh:
        return

    op.create_table(
        "network_interface_kinds",
        sa.Column("name", sa.String(32), primary_key=True),
        sa.Column("description", sa.Text, nullable=False, default=""),
        sa.Column("display_order", sa.Integer, nullable=False, default=0),
    )

    op.create_table(
        "network_profiles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column(
            "distribution_id",
            sa.String(36),
            sa.ForeignKey("distributions.id"),
            nullable=True,
        ),
        sa.Column("hostname", sa.String(253), nullable=False, default="localhost"),
        sa.Column("rendered_networkd", sa.Text, nullable=True),
        sa.Column("rendered_resolv_conf", sa.Text, nullable=True),
        sa.Column("rendered_hosts", sa.Text, nullable=True),
        sa.Column("content_hash", sa.String(128), nullable=True),
        sa.Column("rendered_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint(
            "distribution_id", "name", name="uq_network_profiles_dist_name"
        ),
    )
    op.create_index(
        "ix_network_profiles_distribution_id",
        "network_profiles",
        ["distribution_id"],
    )

    op.create_table(
        "net_interfaces",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "profile_id",
            sa.String(36),
            sa.ForeignKey("network_profiles.id"),
            nullable=False,
        ),
        sa.Column("name", sa.String(15), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False, default="ethernet"),
        sa.Column("description", sa.Text, nullable=False, default=""),
        sa.Column("mtu", sa.Integer, nullable=True),
        sa.Column("mac_address", sa.String(17), nullable=True),
        sa.Column("is_dhcp4", sa.Boolean, nullable=False, default=True),
        sa.Column("is_dhcp6", sa.Boolean, nullable=False, default=False),
        sa.Column("static_addresses", sa.Text, nullable=True),
        sa.Column("gateway4", sa.String(45), nullable=True),
        sa.Column("metric", sa.Integer, nullable=True),
        sa.Column("parent_name", sa.String(15), nullable=True),
        sa.Column("vlan_id", sa.Integer, nullable=True),
        sa.UniqueConstraint(
            "profile_id", "name", name="uq_net_interfaces_profile_name"
        ),
    )
    op.create_index("ix_net_interfaces_profile_id", "net_interfaces", ["profile_id"])

    op.create_table(
        "net_dns_entries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "profile_id",
            sa.String(36),
            sa.ForeignKey("network_profiles.id"),
            nullable=False,
        ),
        sa.Column("nameserver", sa.String(45), nullable=False),
        sa.Column("search_domain", sa.String(253), nullable=True),
        sa.Column("priority", sa.Integer, nullable=False, default=100),
        sa.UniqueConstraint(
            "profile_id", "nameserver", name="uq_net_dns_entries_profile_ns"
        ),
    )
    op.create_index(
        "ix_net_dns_entries_profile_id", "net_dns_entries", ["profile_id"]
    )

    op.create_table(
        "net_routes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "profile_id",
            sa.String(36),
            sa.ForeignKey("network_profiles.id"),
            nullable=False,
        ),
        sa.Column("destination", sa.String(49), nullable=False),
        sa.Column("gateway", sa.String(45), nullable=False),
        sa.Column("metric", sa.Integer, nullable=False, default=0),
        sa.Column("interface_name", sa.String(15), nullable=True),
        sa.Column("description", sa.Text, nullable=False, default=""),
        sa.UniqueConstraint(
            "profile_id", "destination", "gateway",
            name="uq_net_routes_profile_dest_gw",
        ),
    )
    op.create_index("ix_net_routes_profile_id", "net_routes", ["profile_id"])

    op.create_table(
        "net_firewall_rules",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "profile_id",
            sa.String(36),
            sa.ForeignKey("network_profiles.id"),
            nullable=False,
        ),
        sa.Column("chain", sa.String(16), nullable=False),
        sa.Column("protocol", sa.String(8), nullable=False, default="any"),
        sa.Column("source_cidr", sa.String(49), nullable=True),
        sa.Column("destination_cidr", sa.String(49), nullable=True),
        sa.Column("dport", sa.String(16), nullable=True),
        sa.Column("action", sa.String(8), nullable=False, default="ACCEPT"),
        sa.Column("priority", sa.Integer, nullable=False, default=100),
        sa.Column("comment", sa.String(128), nullable=True),
    )
    op.create_index(
        "ix_net_firewall_rules_profile_id", "net_firewall_rules", ["profile_id"]
    )

    # Seed interface kinds
    from osfabricum.db.seed_data import NETWORK_INTERFACE_KINDS  # noqa: PLC0415

    kind_table = sa.table(
        "network_interface_kinds",
        sa.column("name", sa.String),
        sa.column("description", sa.String),
        sa.column("display_order", sa.Integer),
    )
    existing = {
        row[0]
        for row in bind.execute(
            sa.text("SELECT name FROM network_interface_kinds")
        ).fetchall()
    }
    for name, description, display_order in NETWORK_INTERFACE_KINDS:
        if name in existing:
            continue
        bind.execute(
            kind_table.insert().values(
                name=name, description=description, display_order=display_order
            )
        )


def downgrade() -> None:
    for tbl in (
        "net_firewall_rules",
        "net_routes",
        "net_dns_entries",
        "net_interfaces",
        "network_profiles",
        "network_interface_kinds",
    ):
        try:
            op.drop_table(tbl)
        except Exception:
            pass
