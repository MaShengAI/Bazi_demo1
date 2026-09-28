"""store queue schedule timestamps in application UTC

Revision ID: 20260928_0003
Revises: 20260928_0002
Create Date: 2026-09-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260928_0003"
down_revision: str | None = "20260928_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "mysql":
        op.alter_column(
            "analysis_sections",
            "next_attempt_at",
            existing_type=sa.DateTime(timezone=True),
            server_default=None,
        )
        due_now = "UTC_TIMESTAMP()"
    else:
        due_now = "CURRENT_TIMESTAMP"

    # MySQL's NOW() follows the server time zone. Older pending rows may therefore appear
    # several hours in the future to UTC workers. Make them immediately claimable once.
    op.execute(
        sa.text(
            "UPDATE analysis_sections "
            f"SET next_attempt_at = {due_now} "
            "WHERE status = 'pending'"
        )
    )


def downgrade() -> None:
    if op.get_bind().dialect.name == "mysql":
        op.alter_column(
            "analysis_sections",
            "next_attempt_at",
            existing_type=sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        )
