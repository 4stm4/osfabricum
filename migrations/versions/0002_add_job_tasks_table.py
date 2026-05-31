"""Create pyjobkit job_tasks table (replaces the old custom jobs table).

Revision ID: 0002
Revises: 0001
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    # Guard: already created (fresh install via create_all or previous run)
    if sa.inspect(bind).has_table("job_tasks"):
        return
    from pyjobkit.backends.sql.schema import metadata as pjk_meta

    pjk_meta.create_all(bind, checkfirst=True)


def downgrade() -> None:
    op.drop_table("job_tasks")
