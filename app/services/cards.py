from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.commerce_models import CardLedger, CardWallet, WeeklyCoupon
from app.models import UserRecord


class PaymentError(RuntimeError):
    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code


def now_utc() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def week_window(now: datetime) -> tuple[datetime, datetime]:
    """A coupon week starts Monday 08:00 Asia/Shanghai, not Monday midnight."""
    local = now.replace(tzinfo=UTC).astimezone(ZoneInfo("Asia/Shanghai"))
    start = (local - timedelta(days=local.weekday())).replace(
        hour=8, minute=0, second=0, microsecond=0
    )
    if local < start:
        start -= timedelta(days=7)
    return (
        start.astimezone(UTC).replace(tzinfo=None),
        (start + timedelta(days=7)).astimezone(UTC).replace(tzinfo=None),
    )


def lock_user(session: Session, user_id: str, *, allow_disabled: bool = False) -> None:
    # Serialize all coupon/order/wallet operations using an existing row on MySQL.
    user = session.scalar(select(UserRecord).where(UserRecord.id == user_id).with_for_update())
    if user is None or (user.status != "active" and not allow_disabled):
        raise PaymentError(403, "account_unavailable", "当前账户不可用")


def ensure_account(session: Session, user_id: str, now: datetime) -> WeeklyCoupon:
    """Caller holds the user lock. Never backfill expired coupons or stack weeks."""
    start, end = week_window(now)
    if session.get(CardWallet, user_id, with_for_update=True, populate_existing=True) is None:
        session.add(CardWallet(user_id=user_id, balance=0))
    coupon = session.scalar(
        select(WeeklyCoupon)
        .where(
            WeeklyCoupon.user_id == user_id,
            WeeklyCoupon.period_start == start,
            WeeklyCoupon.source_refund_id.is_(None),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if coupon is None:
        coupon = WeeklyCoupon(user_id=user_id, period_start=start, expires_at=end)
        session.add(coupon)
    session.flush()
    return coupon


def available_coupons(session: Session, user_id: str, now: datetime) -> list[WeeklyCoupon]:
    """Caller holds the user lock. Earliest expiry first; one voucher per order."""
    return list(
        session.scalars(
            select(WeeklyCoupon)
            .where(
                WeeklyCoupon.user_id == user_id,
                WeeklyCoupon.expires_at > now,
                WeeklyCoupon.redeemed_order_id.is_(None),
                WeeklyCoupon.reserved_order_id.is_(None),
            )
            .order_by(WeeklyCoupon.expires_at, WeeklyCoupon.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )


def debit_report(session: Session, user_id: str, job_id: str) -> None:
    lock_user(session, user_id)
    changed = session.execute(
        update(CardWallet)
        .where(CardWallet.user_id == user_id, CardWallet.balance > 0)
        .values(balance=CardWallet.balance - 1)
    ).rowcount
    if changed != 1:
        raise PaymentError(402, "cards_required", "解读卡不足，请先购买；基础排盘仍然免费")
    session.add(
        CardLedger(
            user_id=user_id,
            event_key=f"analysis:{job_id}",
            delta=-1,
            job_id=job_id,
            created_at=now_utc(),
        )
    )
