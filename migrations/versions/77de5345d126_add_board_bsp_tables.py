"""add_board_bsp_tables

Revision ID: 77de5345d126
Revises: 0008
Create Date: 2026-06-04 10:11:46.638645

M30 — Board/BSP Designer: Extend boards model with BSP depth.
Add tables for board revisions, SoC families, boot schemes, firmware,
device trees, flash methods, test methods, and probe profiles.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '77de5345d126'
down_revision: Union[str, Sequence[str], None] = '0008'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # SoC families (e.g., BCM2835, BCM2711, RK3588, i.MX8)
    op.create_table(
        'soc_families',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('name', sa.String(64), nullable=False, unique=True),
        sa.Column('vendor', sa.String(64), nullable=True),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('metadata_json', sa.JSON, nullable=True),
    )

    # Extend existing boot_schemes table (created in M25)
    # Add columns as nullable first, then fill defaults, then make NOT NULL
    op.add_column('boot_schemes', sa.Column('boot_type', sa.String(32), nullable=True))
    op.add_column('boot_schemes', sa.Column('requires_bootloader', sa.Boolean, nullable=True))
    op.add_column('boot_schemes', sa.Column('requires_firmware', sa.Boolean, nullable=True))
    
    # Fill default values for existing rows
    op.execute("UPDATE boot_schemes SET boot_type = 'direct' WHERE boot_type IS NULL")
    op.execute("UPDATE boot_schemes SET requires_bootloader = 0 WHERE requires_bootloader IS NULL")
    op.execute("UPDATE boot_schemes SET requires_firmware = 0 WHERE requires_firmware IS NULL")
    
    # Note: SQLite doesn't support ALTER COLUMN SET NOT NULL easily
    # The model enforces NOT NULL for new rows; existing rows are now filled

    # Board revisions (e.g., rpi-zero-2w-rev1.0, rpi-zero-2w-rev1.1)
    op.create_table(
        'board_revisions',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('board_id', sa.String(36), sa.ForeignKey('boards.id'), nullable=False),
        sa.Column('revision', sa.String(32), nullable=False),
        sa.Column('soc_family_id', sa.String(36), sa.ForeignKey('soc_families.id'), nullable=True),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('is_default', sa.Boolean, nullable=False, default=False),
        sa.Column('metadata_json', sa.JSON, nullable=True),
    )
    op.create_index('ix_board_revisions_board_id', 'board_revisions', ['board_id'])
    op.create_unique_constraint('uq_board_revision', 'board_revisions', ['board_id', 'revision'])

    # Board firmware blobs (e.g., start4.elf, fixup4.dat for RPi)
    op.create_table(
        'board_firmware',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('board_id', sa.String(36), sa.ForeignKey('boards.id'), nullable=False),
        sa.Column('board_revision_id', sa.String(36), sa.ForeignKey('board_revisions.id'), nullable=True),
        sa.Column('filename', sa.String(255), nullable=False),
        sa.Column('artifact_id', sa.String(36), sa.ForeignKey('artifacts.id'), nullable=True),
        sa.Column('source_uri', sa.String(512), nullable=True),
        sa.Column('source_ref', sa.String(128), nullable=True),
        sa.Column('expected_hash', sa.String(64), nullable=True),
        sa.Column('required', sa.Boolean, nullable=False, default=True),
        sa.Column('placement', sa.String(128), nullable=True),  # boot partition path
        sa.Column('metadata_json', sa.JSON, nullable=True),
    )
    op.create_index('ix_board_firmware_board_id', 'board_firmware', ['board_id'])

    # Board device trees (DTB/DTBO)
    op.create_table(
        'board_device_trees',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('board_id', sa.String(36), sa.ForeignKey('boards.id'), nullable=False),
        sa.Column('board_revision_id', sa.String(36), sa.ForeignKey('board_revisions.id'), nullable=True),
        sa.Column('filename', sa.String(255), nullable=False),
        sa.Column('dtb_type', sa.String(32), nullable=False),  # base, overlay
        sa.Column('artifact_id', sa.String(36), sa.ForeignKey('artifacts.id'), nullable=True),
        sa.Column('source_uri', sa.String(512), nullable=True),
        sa.Column('source_ref', sa.String(128), nullable=True),
        sa.Column('expected_hash', sa.String(64), nullable=True),
        sa.Column('required', sa.Boolean, nullable=False, default=True),
        sa.Column('placement', sa.String(128), nullable=True),
        sa.Column('metadata_json', sa.JSON, nullable=True),
    )
    op.create_index('ix_board_device_trees_board_id', 'board_device_trees', ['board_id'])

    # Board default kernels (per board/revision)
    op.create_table(
        'board_default_kernels',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('board_id', sa.String(36), sa.ForeignKey('boards.id'), nullable=False),
        sa.Column('board_revision_id', sa.String(36), sa.ForeignKey('board_revisions.id'), nullable=True),
        sa.Column('kernel_id', sa.String(36), sa.ForeignKey('kernels.id'), nullable=False),
        sa.Column('priority', sa.Integer, nullable=False, default=0),
        sa.Column('metadata_json', sa.JSON, nullable=True),
    )
    op.create_index('ix_board_default_kernels_board_id', 'board_default_kernels', ['board_id'])

    # Board default toolchains
    op.create_table(
        'board_default_toolchains',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('board_id', sa.String(36), sa.ForeignKey('boards.id'), nullable=False),
        sa.Column('board_revision_id', sa.String(36), sa.ForeignKey('board_revisions.id'), nullable=True),
        sa.Column('toolchain_id', sa.String(36), sa.ForeignKey('toolchains.id'), nullable=False),
        sa.Column('priority', sa.Integer, nullable=False, default=0),
        sa.Column('metadata_json', sa.JSON, nullable=True),
    )
    op.create_index('ix_board_default_toolchains_board_id', 'board_default_toolchains', ['board_id'])

    # Board supported partition layouts
    op.create_table(
        'board_supported_layouts',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('board_id', sa.String(36), sa.ForeignKey('boards.id'), nullable=False),
        sa.Column('board_revision_id', sa.String(36), sa.ForeignKey('board_revisions.id'), nullable=True),
        sa.Column('layout_id', sa.String(36), sa.ForeignKey('partition_layouts.id'), nullable=False),
        sa.Column('is_default', sa.Boolean, nullable=False, default=False),
        sa.Column('metadata_json', sa.JSON, nullable=True),
    )
    op.create_index('ix_board_supported_layouts_board_id', 'board_supported_layouts', ['board_id'])

    # Board flash methods (e.g., dd, rpiboot, fastboot, dfu, jtag)
    op.create_table(
        'board_flash_methods',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('board_id', sa.String(36), sa.ForeignKey('boards.id'), nullable=False),
        sa.Column('board_revision_id', sa.String(36), sa.ForeignKey('board_revisions.id'), nullable=True),
        sa.Column('method_name', sa.String(64), nullable=False),  # dd, rpiboot, fastboot, etc.
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('command_template', sa.Text, nullable=True),
        sa.Column('requires_tools', sa.JSON, nullable=True),  # ["rpiboot", "usbboot"]
        sa.Column('device_pattern', sa.String(255), nullable=True),  # /dev/sdX, /dev/mmcblkX
        sa.Column('is_default', sa.Boolean, nullable=False, default=False),
        sa.Column('metadata_json', sa.JSON, nullable=True),
    )
    op.create_index('ix_board_flash_methods_board_id', 'board_flash_methods', ['board_id'])

    # Board test methods (e.g., qemu, hardware, serial)
    op.create_table(
        'board_test_methods',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('board_id', sa.String(36), sa.ForeignKey('boards.id'), nullable=False),
        sa.Column('board_revision_id', sa.String(36), sa.ForeignKey('board_revisions.id'), nullable=True),
        sa.Column('method_name', sa.String(64), nullable=False),  # qemu, hardware, serial
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('test_command', sa.Text, nullable=True),
        sa.Column('requires_tools', sa.JSON, nullable=True),
        sa.Column('timeout_seconds', sa.Integer, nullable=True),
        sa.Column('is_default', sa.Boolean, nullable=False, default=False),
        sa.Column('metadata_json', sa.JSON, nullable=True),
    )
    op.create_index('ix_board_test_methods_board_id', 'board_test_methods', ['board_id'])

    # Board probe profiles (hardware detection/identification)
    op.create_table(
        'board_probe_profiles',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('board_id', sa.String(36), sa.ForeignKey('boards.id'), nullable=False),
        sa.Column('board_revision_id', sa.String(36), sa.ForeignKey('board_revisions.id'), nullable=True),
        sa.Column('probe_method', sa.String(64), nullable=False),  # cpuinfo, devicetree, dmi, usb
        sa.Column('match_pattern', sa.Text, nullable=True),
        sa.Column('match_fields', sa.JSON, nullable=True),  # {"model": "Raspberry Pi Zero 2 W"}
        sa.Column('confidence', sa.Integer, nullable=False, default=100),  # 0-100
        sa.Column('metadata_json', sa.JSON, nullable=True),
    )
    op.create_index('ix_board_probe_profiles_board_id', 'board_probe_profiles', ['board_id'])


def downgrade() -> None:
    op.drop_table('board_probe_profiles')
    op.drop_table('board_test_methods')
    op.drop_table('board_flash_methods')
    op.drop_table('board_supported_layouts')
    op.drop_table('board_default_toolchains')
    op.drop_table('board_default_kernels')
    op.drop_table('board_device_trees')
    op.drop_table('board_firmware')
    op.drop_table('board_revisions')
    # Revert boot_schemes extensions
    op.drop_column('boot_schemes', 'requires_firmware')
    op.drop_column('boot_schemes', 'requires_bootloader')
    op.drop_column('boot_schemes', 'boot_type')
    # Note: Column type change not reverted (SQLite limitation)
    op.drop_table('soc_families')

# Made with Bob
