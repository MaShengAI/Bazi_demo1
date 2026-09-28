"""move queue leases from jobs to sections

Revision ID: 20260928_0002
Revises: 20260804_0001
Create Date: 2026-09-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260928_0002"
down_revision: str | None = "20260804_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "analysis_sections",
        sa.Column("failure_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column("analysis_sections", sa.Column("locked_by", sa.String(128)))
    op.add_column("analysis_sections", sa.Column("locked_at", sa.DateTime(timezone=True)))
    op.add_column("analysis_sections", sa.Column("lease_expires_at", sa.DateTime(timezone=True)))
    op.add_column(
        "analysis_sections",
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_analysis_sections_queue",
        "analysis_sections",
        ["status", "position", "next_attempt_at", "created_at"],
    )
    op.create_index(
        "ix_analysis_sections_lease",
        "analysis_sections",
        ["status", "lease_expires_at"],
    )

    # A rolling upgrade can leave job-leased sections marked running. Requeue them once so the
    # new section-level workers can safely claim them; completed content is untouched.
    op.execute(
        sa.text(
            "UPDATE analysis_sections "
            "SET status = 'pending', error_code = 'queue_migrated', "
            "error = '任务队列升级，板块已重新入队' "
            "WHERE status = 'running'"
        )
    )
    op.execute(
        sa.text(
            "UPDATE analysis_jobs "
            "SET status = 'pending', locked_by = NULL, lease_expires_at = NULL "
            "WHERE status = 'running'"
        )
    )
    op.execute(
        sa.text(
            "UPDATE analysis_sections SET next_attempt_at = created_at WHERE status = 'pending'"
        )
    )
    op.execute(
        sa.text("UPDATE analysis_sections SET next_attempt_at = NULL WHERE status <> 'pending'")
    )


def downgrade() -> None:
    op.drop_index("ix_analysis_sections_lease", table_name="analysis_sections")
    op.drop_index("ix_analysis_sections_queue", table_name="analysis_sections")
    op.drop_column("analysis_sections", "next_attempt_at")
    op.drop_column("analysis_sections", "lease_expires_at")
    op.drop_column("analysis_sections", "locked_at")
    op.drop_column("analysis_sections", "locked_by")
    op.drop_column("analysis_sections", "failure_count")
