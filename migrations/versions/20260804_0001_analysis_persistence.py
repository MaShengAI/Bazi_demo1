"""create persisted analysis job tables

Revision ID: 20260804_0001
Revises:
Create Date: 2026-08-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20260804_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONTENT_TEXT = sa.Text().with_variant(mysql.LONGTEXT(), "mysql")


def upgrade() -> None:
    op.create_table(
        "charts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("request_json", sa.JSON(), nullable=False),
        sa.Column("snapshot_json", sa.JSON(), nullable=False),
        sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_charts_snapshot_hash", "charts", ["snapshot_hash"])

    op.create_table(
        "analysis_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "chart_id",
            sa.String(36),
            sa.ForeignKey("charts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("model_id", sa.String(191), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("prompt_version", sa.String(64), nullable=False),
        sa.Column("rule_version", sa.JSON(), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("cancel_requested", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("locked_by", sa.String(128)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('pending','running','partial','completed','failed','cancelled')",
            name="ck_analysis_jobs_status",
        ),
        sa.UniqueConstraint("request_hash", name="uq_analysis_jobs_request_hash"),
    )
    op.create_index("ix_analysis_jobs_chart_id", "analysis_jobs", ["chart_id"])
    op.create_index("ix_analysis_jobs_status", "analysis_jobs", ["status"])

    op.create_table(
        "analysis_sections",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "job_id",
            sa.String(36),
            sa.ForeignKey("analysis_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column("title", sa.String(191), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("content", CONTENT_TEXT),
        sa.Column("char_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("length_status", sa.String(16)),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("retry_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_code", sa.String(64)),
        sa.Column("error", sa.Text()),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('pending','running','completed','failed','cancelled')",
            name="ck_analysis_sections_status",
        ),
        sa.UniqueConstraint("job_id", "code", name="uq_analysis_sections_job_code"),
        sa.UniqueConstraint("request_hash", name="uq_analysis_sections_request_hash"),
    )
    op.create_index("ix_analysis_sections_job_id", "analysis_sections", ["job_id"])
    op.create_index("ix_analysis_sections_status", "analysis_sections", ["status"])

    op.create_table(
        "llm_call_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "section_id",
            sa.String(36),
            sa.ForeignKey("analysis_sections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("model_id", sa.String(191), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("latency_ms", sa.Integer()),
        sa.Column("prompt_tokens", sa.Integer()),
        sa.Column("completion_tokens", sa.Integer()),
        sa.Column("total_tokens", sa.Integer()),
        sa.Column("provider_request_id", sa.String(191)),
        sa.Column("error_code", sa.String(64)),
        sa.Column("error", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('running','completed','failed')", name="ck_llm_call_logs_status"
        ),
        sa.UniqueConstraint("section_id", "attempt_no", name="uq_llm_calls_section_attempt"),
    )
    op.create_index("ix_llm_call_logs_request_hash", "llm_call_logs", ["request_hash"])


def downgrade() -> None:
    op.drop_table("llm_call_logs")
    op.drop_table("analysis_sections")
    op.drop_table("analysis_jobs")
    op.drop_table("charts")
