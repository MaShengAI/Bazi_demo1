"""Add manual refunds and audit; preserve existing paid orders and card ledger.

Revision ID: 20261101_0006
Revises: 20261020_0005
"""

import sqlalchemy as sa
from alembic import op

revision = "20261101_0006"
down_revision = "20261020_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "payment_refunds",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("order_id", sa.String(32), sa.ForeignKey("payment_orders.id"), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("amount", sa.Integer, nullable=False),
        sa.Column("reclaim_cards", sa.Integer, nullable=False),
        sa.Column("reason", sa.String(80), nullable=False),
        sa.Column("operator", sa.String(64), nullable=False),
        sa.Column("notify_url", sa.String(256), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("provider_refund_id", sa.String(64), unique=True),
        sa.Column("submit_attempts", sa.Integer, nullable=False),
        sa.Column("last_submit_at", sa.DateTime, nullable=False),
        sa.Column("next_check_at", sa.DateTime, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.Column("success_at", sa.DateTime),
        sa.CheckConstraint("amount > 0 AND reclaim_cards >= 0", name="ck_refund_positive"),
        sa.CheckConstraint(
            "status IN ('reserved','processing','success','closed','abnormal')",
            name="ck_refund_status",
        ),
    )
    for name in ("user_id", "order_id", "next_check_at"):
        op.create_index(f"ix_payment_refunds_{name}", "payment_refunds", [name])
    op.create_table(
        "refund_audit",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("refund_id", sa.String(32), sa.ForeignKey("payment_refunds.id"), nullable=False),
        sa.Column("event_key", sa.String(100), nullable=False, unique=True),
        sa.Column("event", sa.String(32), nullable=False),
        sa.Column("actor", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_refund_audit_refund_id", "refund_audit", ["refund_id"])


def downgrade() -> None:
    raise RuntimeError("Financial refund/audit records must not be deleted by app rollback")
