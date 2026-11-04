"""Moderated report reviews and exactly-once review gift coupons."""

import sqlalchemy as sa
from alembic import op

revision = "20261102_0009"
down_revision = "20261102_0008"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "report_reviews",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "job_id",
            sa.String(36),
            sa.ForeignKey("analysis_jobs.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("public_profile", sa.JSON(), nullable=False),
        sa.Column("consent_version", sa.String(32), nullable=False),
        sa.Column("consent_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("moderated_at", sa.DateTime()),
        sa.Column("moderated_by", sa.String(32)),
        sa.CheckConstraint("rating BETWEEN 1 AND 5", name="ck_review_rating"),
        sa.CheckConstraint("status IN ('pending','approved','hidden')", name="ck_review_status"),
    )
    for column in ("user_id", "created_at", "status"):
        op.create_index(f"ix_report_reviews_{column}", "report_reviews", [column])
    op.create_table(
        "review_moderation",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "review_id",
            sa.String(36),
            sa.ForeignKey("report_reviews.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("operator", sa.String(32), nullable=False),
        sa.Column("previous_status", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_review_moderation_review_id", "review_moderation", ["review_id"])
    with op.batch_alter_table("weekly_coupons") as batch:
        batch.add_column(sa.Column("source_review_id", sa.String(36)))
        batch.create_unique_constraint("uq_coupon_source_review", ["source_review_id"])


def downgrade():
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT COUNT(*) FROM report_reviews")).scalar():
        raise RuntimeError("Review data exists; preserve reviews and issued gifts.")
    with op.batch_alter_table("weekly_coupons") as batch:
        batch.drop_constraint("uq_coupon_source_review", type_="unique")
        batch.drop_column("source_review_id")
    op.drop_table("review_moderation")
    op.drop_table("report_reviews")
