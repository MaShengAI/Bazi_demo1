"""Allow independent seven-day refund gifts while preserving all weekly coupons.

Revision ID: 20261101_0007
Revises: 20261101_0006
"""

import sqlalchemy as sa
from alembic import op

revision = "20261101_0007"
down_revision = "20261101_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # NULL period_start distinguishes gifts from the unique user/week grant.
    # MySQL/SQLite both permit multiple NULL values in the existing unique key.
    with op.batch_alter_table("weekly_coupons") as batch:
        batch.alter_column("period_start", existing_type=sa.DateTime(), nullable=True)
        batch.add_column(sa.Column("source_refund_id", sa.String(32), nullable=True))
        batch.create_unique_constraint("uq_coupon_source_refund", ["source_refund_id"])


def downgrade() -> None:
    raise RuntimeError("Coupon grants and redemption history must not be deleted by rollback")
