"""Remove terminal codes from admin lists while preserving grants and code hashes."""

import sqlalchemy as sa
from alembic import op

revision = "20261103_0010"
down_revision = "20261102_0009"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("redemption_codes", sa.Column("deleted_at", sa.DateTime(), nullable=True))
    op.add_column("redemption_codes", sa.Column("deleted_by", sa.String(32), nullable=True))
    op.create_index("ix_redemption_codes_deleted_at", "redemption_codes", ["deleted_at"])


def downgrade():
    if op.get_bind().scalar(
        sa.text("SELECT COUNT(*) FROM redemption_codes WHERE deleted_at IS NOT NULL")
    ):
        raise RuntimeError("Removed codes exist; preserve the removal audit.")
    op.drop_index("ix_redemption_codes_deleted_at", table_name="redemption_codes")
    op.drop_column("redemption_codes", "deleted_by")
    op.drop_column("redemption_codes", "deleted_at")
