"""add WeChat users, sessions, OAuth states, and report ownership

Revision ID: 20260929_0004
Revises: 20260928_0003
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260929_0004"
down_revision: str | None = "20260928_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("display_name", sa.String(191), nullable=False),
        sa.Column("avatar_url", sa.String(1024)),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("status IN ('active','disabled')", name="ck_users_status"),
    )

    op.create_table(
        "wechat_identities",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("app_id", sa.String(64), nullable=False),
        sa.Column("openid", sa.String(128), nullable=False),
        sa.Column("unionid", sa.String(128)),
        sa.Column("profile_json", sa.JSON()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("app_id", "openid", name="uq_wechat_identities_app_openid"),
    )
    op.create_index("ix_wechat_identities_user_id", "wechat_identities", ["user_id"])
    op.create_index("ix_wechat_identities_unionid", "wechat_identities", ["unionid"])

    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("token_hash", name="uq_auth_sessions_token_hash"),
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
    op.create_index("ix_auth_sessions_expiry", "auth_sessions", ["expires_at", "revoked_at"])

    op.create_table(
        "oauth_states",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("state_hash", sa.String(64), nullable=False),
        sa.Column("return_to", sa.String(500), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("state_hash", name="uq_oauth_states_state_hash"),
    )
    op.create_index("ix_oauth_states_expiry", "oauth_states", ["expires_at"])

    with op.batch_alter_table("charts") as batch_op:
        batch_op.add_column(sa.Column("user_id", sa.String(36), nullable=True))
        batch_op.create_foreign_key(
            "fk_charts_user_id_users", "users", ["user_id"], ["id"], ondelete="SET NULL"
        )
        batch_op.create_index("ix_charts_user_id", ["user_id"])


def downgrade() -> None:
    with op.batch_alter_table("charts") as batch_op:
        batch_op.drop_index("ix_charts_user_id")
        batch_op.drop_constraint("fk_charts_user_id_users", type_="foreignkey")
        batch_op.drop_column("user_id")
    op.drop_table("oauth_states")
    op.drop_table("auth_sessions")
    op.drop_table("wechat_identities")
    op.drop_table("users")
