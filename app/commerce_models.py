"""Immutable order prices and append-only card accounting (no cash balance)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models import new_id


class CardWallet(Base):
    __tablename__ = "card_wallets"
    __table_args__ = (CheckConstraint("balance >= 0", name="ck_wallet_nonnegative"),)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), primary_key=True)
    balance: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class WeeklyCoupon(Base):
    __tablename__ = "weekly_coupons"
    __table_args__ = (UniqueConstraint("user_id", "period_start", name="uq_coupon_user_week"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    # NULL for refund gifts, so they do not replace the weekly grant or its expiry.
    period_start: Mapped[datetime | None] = mapped_column(DateTime)
    # An immutable source key, like reserved_order_id; never reused on another refund.
    source_refund_id: Mapped[str | None] = mapped_column(String(32), unique=True)
    amount: Mapped[int] = mapped_column(
        Integer, nullable=False, default=5000, server_default="5000"
    )
    source_code_id: Mapped[str | None] = mapped_column(String(32), unique=True)
    # Immutable grant key, deliberately not a FK: deleting a report keeps its gift.
    source_review_id: Mapped[str | None] = mapped_column(String(36), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    reserved_order_id: Mapped[str | None] = mapped_column(String(32))
    redeemed_order_id: Mapped[str | None] = mapped_column(String(32))


class ReportReview(Base):
    __tablename__ = "report_reviews"
    __table_args__ = (
        CheckConstraint("rating BETWEEN 1 AND 5", name="ck_review_rating"),
        CheckConstraint("status IN ('pending','approved','hidden')", name="ck_review_status"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_jobs.id", ondelete="CASCADE"), unique=True
    )
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    public_profile: Mapped[dict] = mapped_column(JSON, nullable=False)
    consent_version: Mapped[str] = mapped_column(String(32), nullable=False)
    consent_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", index=True)
    moderated_at: Mapped[datetime | None] = mapped_column(DateTime)
    moderated_by: Mapped[str | None] = mapped_column(String(32))


class ReviewModeration(Base):
    __tablename__ = "review_moderation"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    review_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("report_reviews.id", ondelete="CASCADE"), index=True
    )
    operator: Mapped[str] = mapped_column(String(32), nullable=False)
    previous_status: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class RedemptionBatch(Base):
    __tablename__ = "redemption_batches"
    __table_args__ = (
        CheckConstraint("kind IN ('cards','coupon')", name="ck_redemption_kind"),
        CheckConstraint("value > 0 AND quantity > 0", name="ck_redemption_reward"),
    )
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    request_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    label: Mapped[str] = mapped_column(String(80), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    value: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    operator: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class RedemptionCode(Base):
    __tablename__ = "redemption_codes"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    batch_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("redemption_batches.id"), index=True
    )
    # Random 100-bit secret: plaintext is returned only at generation, never stored/logged.
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    suffix: Mapped[str] = mapped_column(String(4), nullable=False)
    redeemed_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    redeemed_at: Mapped[datetime | None] = mapped_column(DateTime)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime)
    disabled_by: Mapped[str | None] = mapped_column(String(32))
    # Retain the secret hash and grant reference after removal from the admin list.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    deleted_by: Mapped[str | None] = mapped_column(String(32))


class RedemptionAttempt(Base):
    __tablename__ = "redemption_attempts"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)


class PaymentOrder(Base):
    __tablename__ = "payment_orders"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_order_user_key"),
        CheckConstraint("status IN ('pending','paid','closed')", name="ck_payment_status"),
        CheckConstraint("total_amount > 0 AND cards > 0", name="ck_payment_positive"),
        CheckConstraint(
            "original_amount - discount_amount = total_amount", name="ck_payment_discount"
        ),
    )
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    product_code: Mapped[str] = mapped_column(String(32), nullable=False)
    product_name: Mapped[str] = mapped_column(String(127), nullable=False)
    cards: Mapped[int] = mapped_column(Integer, nullable=False)
    original_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    discount_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    total_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    coupon_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("weekly_coupons.id"))
    app_id: Mapped[str] = mapped_column(String(64), nullable=False)
    mchid: Mapped[str] = mapped_column(String(64), nullable=False)
    payer_openid: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    prepay_id: Mapped[str | None] = mapped_column(String(128))
    provider_started: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    transaction_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime)


class CardLedger(Base):
    __tablename__ = "card_ledger"
    __table_args__ = (CheckConstraint("delta != 0", name="ck_ledger_nonzero"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    event_key: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    delta: Mapped[int] = mapped_column(Integer, nullable=False)
    # No cascading job FK: deleting a report must never erase its charge or buy it back.
    order_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("payment_orders.id"))
    job_id: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class PaymentRefund(Base):
    __tablename__ = "payment_refunds"
    __table_args__ = (
        CheckConstraint("amount > 0 AND reclaim_cards >= 0", name="ck_refund_positive"),
        CheckConstraint(
            "status IN ('reserved','processing','success','closed','abnormal')",
            name="ck_refund_status",
        ),
    )
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    order_id: Mapped[str] = mapped_column(String(32), ForeignKey("payment_orders.id"), index=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    reclaim_cards: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(80), nullable=False)
    operator: Mapped[str] = mapped_column(String(64), nullable=False)
    notify_url: Mapped[str] = mapped_column(String(256), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    provider_refund_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    submit_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    last_submit_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    next_check_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    success_at: Mapped[datetime | None] = mapped_column(DateTime)


class RefundAudit(Base):
    __tablename__ = "refund_audit"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    refund_id: Mapped[str] = mapped_column(String(32), ForeignKey("payment_refunds.id"), index=True)
    event_key: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    event: Mapped[str] = mapped_column(String(32), nullable=False)
    actor: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
