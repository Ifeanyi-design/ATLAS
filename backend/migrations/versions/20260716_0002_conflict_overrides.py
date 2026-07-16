"""add auditable conflict overrides"""

from alembic import op
import sqlalchemy as sa

revision = "20260716_0002"
down_revision = "20260715_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("conflict_events", sa.Column("status", sa.String(length=20), nullable=False, server_default="open"))
    op.add_column("conflict_events", sa.Column("override_reason", sa.Text(), nullable=True))
    op.add_column("conflict_events", sa.Column("overridden_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("conflict_events", "overridden_at")
    op.drop_column("conflict_events", "override_reason")
    op.drop_column("conflict_events", "status")
