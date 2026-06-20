"""0049 — add pid column to workers table.

Stores the OS process ID of local workers so the API can send SIGTERM
to stop them without shelling out to pgrep.
"""

from alembic import op
import sqlalchemy as sa

revision = "0049"
down_revision = "0048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("workers") as batch_op:
        batch_op.add_column(sa.Column("pid", sa.Integer, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("workers") as batch_op:
        batch_op.drop_column("pid")
