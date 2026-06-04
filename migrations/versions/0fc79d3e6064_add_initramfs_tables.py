"""add_initramfs_tables

Revision ID: 0fc79d3e6064
Revises: b3470647df99
Create Date: 2026-06-04 09:11:03.000000

M32: Initramfs / Early Boot Designer

Creates tables for managing initramfs profiles, packages, scripts, hooks, and artifacts.
Supports: no initramfs, minimal, recovery, encrypted-root unlock, network boot,
debug shell, factory reset.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0fc79d3e6064"
down_revision = "b3470647df99"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Guard: already present (fresh install via create_all or previous run).
    if "initramfs_profiles" in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    # initramfs_profiles: defines initramfs configurations
    op.execute("""
        CREATE TABLE initramfs_profiles (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            profile_type TEXT NOT NULL,
            description TEXT,
            compression TEXT DEFAULT 'zstd',
            size_limit_mb INTEGER,
            include_modules BOOLEAN DEFAULT TRUE,
            include_firmware BOOLEAN DEFAULT FALSE,
            enable_debug_shell BOOLEAN DEFAULT FALSE,
            enable_network BOOLEAN DEFAULT FALSE,
            enable_encryption_unlock BOOLEAN DEFAULT FALSE,
            enable_factory_reset BOOLEAN DEFAULT FALSE,
            metadata_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.create_index("idx_initramfs_profiles_type", "initramfs_profiles", ["profile_type"])
    op.create_index("idx_initramfs_profiles_name", "initramfs_profiles", ["name"])

    # initramfs_packages: packages to include in initramfs
    op.execute("""
        CREATE TABLE initramfs_packages (
            id TEXT PRIMARY KEY,
            initramfs_profile_id TEXT NOT NULL,
            package_name TEXT NOT NULL,
            version_constraint TEXT,
            required BOOLEAN DEFAULT TRUE,
            priority INTEGER DEFAULT 100,
            metadata_json TEXT,
            FOREIGN KEY (initramfs_profile_id) REFERENCES initramfs_profiles(id) ON DELETE CASCADE
        )
    """)
    op.create_index(
        "idx_initramfs_packages_profile", "initramfs_packages", ["initramfs_profile_id"]
    )
    op.create_index("idx_initramfs_packages_name", "initramfs_packages", ["package_name"])

    # initramfs_scripts: init scripts and helpers
    op.execute("""
        CREATE TABLE initramfs_scripts (
            id TEXT PRIMARY KEY,
            initramfs_profile_id TEXT NOT NULL,
            script_name TEXT NOT NULL,
            script_type TEXT NOT NULL,
            content TEXT NOT NULL,
            execution_order INTEGER DEFAULT 50,
            required BOOLEAN DEFAULT TRUE,
            metadata_json TEXT,
            FOREIGN KEY (initramfs_profile_id) REFERENCES initramfs_profiles(id) ON DELETE CASCADE
        )
    """)
    op.create_index("idx_initramfs_scripts_profile", "initramfs_scripts", ["initramfs_profile_id"])
    op.create_index("idx_initramfs_scripts_type", "initramfs_scripts", ["script_type"])
    op.create_index("idx_initramfs_scripts_order", "initramfs_scripts", ["execution_order"])

    # initramfs_hooks: build-time hooks for customization
    op.execute("""
        CREATE TABLE initramfs_hooks (
            id TEXT PRIMARY KEY,
            initramfs_profile_id TEXT NOT NULL,
            hook_name TEXT NOT NULL,
            hook_stage TEXT NOT NULL,
            command TEXT NOT NULL,
            execution_order INTEGER DEFAULT 50,
            enabled BOOLEAN DEFAULT TRUE,
            metadata_json TEXT,
            FOREIGN KEY (initramfs_profile_id) REFERENCES initramfs_profiles(id) ON DELETE CASCADE
        )
    """)
    op.create_index("idx_initramfs_hooks_profile", "initramfs_hooks", ["initramfs_profile_id"])
    op.create_index("idx_initramfs_hooks_stage", "initramfs_hooks", ["hook_stage"])

    # initramfs_artifacts: built initramfs images
    op.execute("""
        CREATE TABLE initramfs_artifacts (
            id TEXT PRIMARY KEY,
            initramfs_profile_id TEXT NOT NULL,
            board_id TEXT,
            kernel_version TEXT,
            artifact_id TEXT,
            size_bytes INTEGER,
            compression TEXT,
            modules_manifest_json TEXT,
            build_hash TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            metadata_json TEXT,
            FOREIGN KEY (initramfs_profile_id) REFERENCES initramfs_profiles(id) ON DELETE CASCADE
        )
    """)
    op.create_index(
        "idx_initramfs_artifacts_profile", "initramfs_artifacts", ["initramfs_profile_id"]
    )
    op.create_index("idx_initramfs_artifacts_board", "initramfs_artifacts", ["board_id"])
    op.create_index("idx_initramfs_artifacts_hash", "initramfs_artifacts", ["build_hash"])


def downgrade() -> None:
    op.drop_table("initramfs_artifacts")
    op.drop_table("initramfs_hooks")
    op.drop_table("initramfs_scripts")
    op.drop_table("initramfs_packages")
    op.drop_table("initramfs_profiles")


# Made with Bob
