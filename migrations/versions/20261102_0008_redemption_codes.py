"""Single-use redemption codes and independently valued coupons; preserve all grants."""

import sqlalchemy as sa
from alembic import op

revision = "20261102_0008"
down_revision = "20261101_0007"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("weekly_coupons") as batch:
        batch.add_column(sa.Column("amount", sa.Integer(), server_default="5000", nullable=False))
        batch.add_column(sa.Column("source_code_id", sa.String(32), nullable=True))
        batch.create_unique_constraint("uq_coupon_source_code", ["source_code_id"])
    op.create_table(
        "redemption_batches",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("request_key", sa.String(64), nullable=False, unique=True),
        sa.Column("label", sa.String(80), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("value", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("operator", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("kind IN ('cards','coupon')", name="ck_redemption_kind"),
        sa.CheckConstraint("value > 0 AND quantity > 0", name="ck_redemption_reward"),
    )
    op.create_table(
        "redemption_codes",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "batch_id", sa.String(32), sa.ForeignKey("redemption_batches.id"), nullable=False
        ),
        sa.Column("code_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("suffix", sa.String(4), nullable=False),
        sa.Column("redeemed_by", sa.String(36), sa.ForeignKey("users.id")),
        sa.Column("redeemed_at", sa.DateTime()),
        sa.Column("disabled_at", sa.DateTime()),
        sa.Column("disabled_by", sa.String(32)),
    )
    op.create_index("ix_redemption_codes_batch_id", "redemption_codes", ["batch_id"])
    op.create_index("ix_redemption_codes_redeemed_by", "redemption_codes", ["redeemed_by"])
    op.create_table(
        "redemption_attempts",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_redemption_attempts_user_id", "redemption_attempts", ["user_id"])
    op.create_index("ix_redemption_attempts_created_at", "redemption_attempts", ["created_at"])


def downgrade():
    raise RuntimeError("Do not delete redemption history or issued rewards during rollback")
