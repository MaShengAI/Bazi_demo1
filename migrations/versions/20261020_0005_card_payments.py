"""Add card wallets, weekly coupons, payment orders and immutable ledger.

Revision ID: 20261020_0005
Revises: 20260929_0004
"""

import sqlalchemy as sa
from alembic import op

revision = "20261020_0005"
down_revision = "20260929_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "card_wallets",
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("balance", sa.Integer, nullable=False),
        sa.CheckConstraint("balance >= 0", name="ck_wallet_nonnegative"),
    )
    op.create_table(
        "weekly_coupons",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("period_start", sa.DateTime, nullable=False),
        sa.Column("expires_at", sa.DateTime, nullable=False),
        sa.Column("reserved_order_id", sa.String(32)),
        sa.Column("redeemed_order_id", sa.String(32)),
        sa.UniqueConstraint("user_id", "period_start", name="uq_coupon_user_week"),
    )
    op.create_index("ix_weekly_coupons_user_id", "weekly_coupons", ["user_id"])
    op.create_table(
        "payment_orders",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column("product_code", sa.String(32), nullable=False),
        sa.Column("product_name", sa.String(127), nullable=False),
        sa.Column("cards", sa.Integer, nullable=False),
        sa.Column("original_amount", sa.Integer, nullable=False),
        sa.Column("discount_amount", sa.Integer, nullable=False),
        sa.Column("total_amount", sa.Integer, nullable=False),
        sa.Column("coupon_id", sa.String(36), sa.ForeignKey("weekly_coupons.id")),
        sa.Column("app_id", sa.String(64), nullable=False),
        sa.Column("mchid", sa.String(64), nullable=False),
        sa.Column("payer_openid", sa.String(128), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("prepay_id", sa.String(128)),
        sa.Column("provider_started", sa.Boolean, nullable=False),
        sa.Column("transaction_id", sa.String(64), unique=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("expires_at", sa.DateTime, nullable=False),
        sa.Column("paid_at", sa.DateTime),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_order_user_key"),
        sa.CheckConstraint("status IN ('pending','paid','closed')", name="ck_payment_status"),
        sa.CheckConstraint("total_amount > 0 AND cards > 0", name="ck_payment_positive"),
        sa.CheckConstraint(
            "original_amount - discount_amount = total_amount", name="ck_payment_discount"
        ),
    )
    op.create_index("ix_payment_orders_user_id", "payment_orders", ["user_id"])
    op.create_table(
        "card_ledger",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("event_key", sa.String(100), nullable=False, unique=True),
        sa.Column("delta", sa.Integer, nullable=False),
        sa.Column("order_id", sa.String(32), sa.ForeignKey("payment_orders.id")),
        sa.Column("job_id", sa.String(36)),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.CheckConstraint("delta != 0", name="ck_ledger_nonzero"),
    )
    op.create_index("ix_card_ledger_user_id", "card_ledger", ["user_id"])


def downgrade() -> None:
    # Financial records must not disappear because an application is rolled back.
    raise RuntimeError(
        "Back up/reconcile financial records before an explicitly reviewed downgrade"
    )
