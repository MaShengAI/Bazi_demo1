"""Operator-approved refunds: retain cards, grant one seven-day gift on cash success."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import quote, urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.commerce_models import (
    CardLedger,
    CardWallet,
    PaymentOrder,
    PaymentRefund,
    RefundAudit,
    WeeklyCoupon,
)
from app.config import AuthSettings
from app.database import Database
from app.integrations.wechat_pay import VerifiedProviderError, WechatPayClient
from app.payment_config import PaymentSettings
from app.services.cards import PaymentError, lock_user, now_utc

logger = logging.getLogger("bazi.refunds")
TERMINAL = {"success", "closed"}
REFUND_POLICY = "keep_cards_and_gift_v1"


def digest(value: dict) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def amount_cents(value: str) -> int:
    """Do not silently round fractions or accept exponent/float money."""
    if not re.fullmatch(r"(?:0|[1-9]\d{0,6})(?:\.\d{1,2})?", value):
        raise ValueError("金额须为正数，最多两位小数")
    whole, _, fraction = value.partition(".")
    result = int(whole) * 100 + int(fraction.ljust(2, "0") or "0")
    if result <= 0:
        raise ValueError("金额必须大于 0")
    return result


def refund_json(row: PaymentRefund) -> dict:
    return {
        "refund_id": row.id,
        "order_id": row.order_id,
        "amount": row.amount,
        "reclaim_cards": row.reclaim_cards,
        "status": row.status,
        "provider_refund_id": row.provider_refund_id,
        "submit_attempts": row.submit_attempts,
        "cards_reserved": row.reclaim_cards > 0 and row.status != "closed",
        "operator": row.operator,
        "success_at": row.success_at.isoformat() if row.success_at else None,
    }


class RefundService:
    def __init__(
        self,
        database: Database,
        settings: PaymentSettings,
        auth: AuthSettings,
        client: WechatPayClient | None,
    ):
        self.database, self.settings, self.auth, self.client = database, settings, auth, client

    def require_enabled(self) -> None:
        if not self.settings.refunds_enabled or self.settings.mode not in {"mock", "live"}:
            raise PaymentError(503, "refunds_disabled", "人工退款功能尚未启用")
        if self.settings.mode == "live":
            self.settings.validate(self.auth)
            target, payment = (
                urlsplit(self.settings.refund_notify_url),
                urlsplit(self.settings.notify_url),
            )
            if (
                self.client is None
                or target.scheme != "https"
                or target.query
                or target.fragment
                or target.netloc != payment.netloc
                or target.username
                or target.password
                or target.path != "/api/v1/payments/wechat/refund-notify"
            ):
                raise PaymentError(503, "refund_config_invalid", "退款回调配置未通过核对")

    @staticmethod
    def _args(order_id, refund_id, amount, cards, reason, operator):
        if not re.fullmatch(r"[a-f0-9]{32}", order_id or "") or not re.fullmatch(
            r"[a-f0-9]{32}", refund_id or ""
        ):
            raise PaymentError(422, "refund_invalid_id", "订单号或退款单号格式不正确")
        if type(amount) is not int or amount <= 0 or type(cards) is not int or cards < 0:
            raise PaymentError(422, "refund_invalid_amount", "退款分数及回收张数必须为整数")
        if cards != 0:
            raise PaymentError(422, "refund_keeps_cards", "退款不回收解读卡，回收张数必须为0")
        if not isinstance(reason, str) or not reason.strip() or len(reason.encode()) > 80:
            raise PaymentError(422, "refund_invalid_reason", "退款原因必填且不能超过80字节")
        if not isinstance(operator, str) or not re.fullmatch(r"[A-Za-z0-9_.@-]{1,64}", operator):
            raise PaymentError(422, "refund_invalid_operator", "请填写管理员操作标识")

    def _order(self, session: Session, order_id: str, *, lock: bool = False) -> PaymentOrder:
        row = session.get(PaymentOrder, order_id)
        if row is None:
            raise PaymentError(404, "order_not_found", "订单不存在")
        if lock:
            lock_user(session, row.user_id, allow_disabled=True)
            session.refresh(row, with_for_update=True)
        if row.app_id != (self.auth.app_id or "mock-app-id") or row.mchid != (
            self.settings.mchid or "mock-mch"
        ):
            raise PaymentError(409, "refund_merchant_mismatch", "原订单商户或公众号不匹配")
        if row.status != "paid" or not row.transaction_id or row.paid_at is None:
            raise PaymentError(409, "refund_order_unpaid", "只可处理已确认支付的订单")
        return row

    @staticmethod
    def _audit(session: Session, row: PaymentRefund, event: str, actor: str, suffix=""):
        session.add(
            RefundAudit(
                refund_id=row.id,
                event_key=f"refund:{row.id}:{event}{suffix}",
                event=event,
                actor=actor,
                created_at=now_utc(),
            )
        )

    def _plan(
        self, session, order, refund_id, amount, cards, reason, operator, expires, locked=False
    ):
        if now_utc() - order.paid_at >= timedelta(days=365):
            raise PaymentError(409, "refund_order_expired", "原订单已超出接口退款期限")
        query = (
            select(PaymentRefund)
            .where(PaymentRefund.order_id == order.id)
            .order_by(PaymentRefund.id)
        )
        if locked:
            query = query.with_for_update().execution_options(populate_existing=True)
        rows = session.scalars(query).all()
        if any(r.status not in TERMINAL for r in rows):
            raise PaymentError(
                409, "refund_in_progress", "该订单已有未确认的退款，请先处理原退款单"
            )
        if len(rows) >= 50 or any(
            now_utc() - r.last_submit_at < timedelta(minutes=1) for r in rows
        ):
            raise PaymentError(409, "refund_frequency", "请稍后处理；单笔订单退款次数也有上限")
        held_amount = sum(r.amount for r in rows if r.status != "closed")
        held_cards = sum(r.reclaim_cards for r in rows if r.status != "closed")
        wallet = session.get(
            CardWallet, order.user_id, populate_existing=True, with_for_update=locked
        )
        balance = wallet.balance if wallet else 0
        ledger_query = select(CardLedger).where(CardLedger.user_id == order.user_id)
        if locked:
            ledger_query = ledger_query.with_for_update().execution_options(populate_existing=True)
        entries = session.scalars(ledger_query).all()
        if balance != sum(entry.delta for entry in entries):
            raise PaymentError(409, "refund_ledger_mismatch", "卡余额与账本不一致，请先核对")
        if amount > order.total_amount - held_amount:
            raise PaymentError(409, "refund_exceeds_paid", "累计退款不可超过订单实付金额")
        if cards > min(order.cards - held_cards, balance):
            raise PaymentError(
                409, "refund_cards_insufficient", "回收张数超过原订单张数或当前可用余额"
            )
        snapshot = {
            "transaction_id": order.transaction_id,
            "merchant": order.mchid,
            "balance": balance,
            "refunds": [refund_json(r) for r in rows],
            "ledger_entries": sorted(entry.id for entry in entries),
            "refund_notify_url": self.settings.refund_notify_url,
        }
        plan = {
            "policy": REFUND_POLICY,
            "gift_coupon_amount": 5000,
            "gift_coupon_valid_days": 7,
            "refund_id": refund_id,
            "order_id": order.id,
            "amount": amount,
            "reclaim_cards": cards,
            "reason": reason,
            "operator": operator,
            "paid_amount": order.total_amount,
            "remaining_refundable": order.total_amount - held_amount,
            "available_cards": balance,
            "balance_after_reservation": balance - cards,
            "snapshot": digest(snapshot),
            "expires_at": expires,
        }
        return dict(plan, confirmation=digest(plan))

    def preview(self, order_id: str, amount: int, cards: int, reason: str, operator: str) -> dict:
        """Local SELECTs only: never issue coupons, reserve cards or call WeChat."""
        self.require_enabled()
        refund_id = uuid.uuid4().hex
        self._args(order_id, refund_id, amount, cards, reason, operator)
        with self.database.session() as session:
            return self._plan(
                session,
                self._order(session, order_id),
                refund_id,
                amount,
                cards,
                reason,
                operator,
                (now_utc() + timedelta(minutes=10)).isoformat(),
            )

    @staticmethod
    def _verify_plan(plan: dict, confirmation: str) -> None:
        if not isinstance(plan, dict) or plan.get("confirmation") != confirmation:
            raise PaymentError(409, "refund_confirmation_required", "请核对预览并提供对应确认码")
        if digest({k: v for k, v in plan.items() if k != "confirmation"}) != confirmation:
            raise PaymentError(409, "refund_plan_changed", "预览文件已变化，请重新核对")
        if plan.get("policy") != REFUND_POLICY:
            raise PaymentError(409, "refund_policy_changed", "退款规则已更新，请重新预览")

    def submit(self, plan: dict, confirmation: str) -> dict:
        self.require_enabled()
        self._verify_plan(plan, confirmation)
        self._args(
            *(
                plan[k]
                for k in ("order_id", "refund_id", "amount", "reclaim_cards", "reason", "operator")
            )
        )
        with self.database.session() as session:
            existing = session.get(PaymentRefund, plan["refund_id"])
            if existing:
                self._same_request(existing, plan)
                # An ambiguous original request must never be resubmitted implicitly.
                return refund_json(existing)
            order = self._order(session, plan["order_id"])
            if self.client:
                result = self.client.request(
                    "GET",
                    "/v3/pay/transactions/out-trade-no/"
                    + order.id
                    + "?mchid="
                    + quote(order.mchid),
                )
                from app.services.payments import PaymentService

                # After a partial refund WeChat reports REFUND, while the
                # original payment identity/total must still match exactly.
                # This adaptation is refund-only; never grant paid cards from it.
                if result.get("trade_state") not in {"SUCCESS", "REFUND"}:
                    raise PaymentError(409, "refund_payment_state", "微信原支付状态不支持退款")
                PaymentService._validate(order, dict(result, trade_state="SUCCESS"), paid=True)
                if result.get("transaction_id") != order.transaction_id:
                    raise PaymentError(409, "refund_transaction_mismatch", "微信交易号不匹配")
        with self.database.session() as session:
            order = self._order(session, plan["order_id"], lock=True)
            # A concurrent duplicate may have reserved the cards during query I/O.
            existing = session.get(
                PaymentRefund, plan["refund_id"], populate_existing=True, with_for_update=True
            )
            if existing:
                self._same_request(existing, plan)
                return refund_json(existing)
            try:
                expiry = datetime.fromisoformat(plan["expires_at"])
                if expiry.tzinfo or expiry <= now_utc():
                    raise ValueError("Expired plan")
            except (ValueError, TypeError) as exc:
                raise PaymentError(409, "refund_plan_expired", "预览已过期，请重新核对") from exc
            current = self._plan(
                session,
                order,
                plan["refund_id"],
                plan["amount"],
                plan["reclaim_cards"],
                plan["reason"],
                plan["operator"],
                plan["expires_at"],
                locked=True,
            )
            if current != plan:
                raise PaymentError(409, "refund_plan_stale", "订单或余额已变化，请重新预览")
            now = now_utc()
            row = PaymentRefund(
                id=plan["refund_id"],
                order_id=order.id,
                user_id=order.user_id,
                amount=plan["amount"],
                reclaim_cards=plan["reclaim_cards"],
                reason=plan["reason"],
                operator=plan["operator"],
                notify_url=self.settings.refund_notify_url,
                status="reserved",
                submit_attempts=1,
                last_submit_at=now,
                next_check_at=now + timedelta(minutes=1),
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            session.flush()
            if row.reclaim_cards:
                wallet = session.get(CardWallet, order.user_id, with_for_update=True)
                if wallet is None:
                    raise PaymentError(409, "refund_wallet_missing", "卡账户缺失，请先核对")
                wallet.balance -= row.reclaim_cards
                session.add(
                    CardLedger(
                        user_id=row.user_id,
                        event_key=f"refund-hold:{row.id}",
                        delta=-row.reclaim_cards,
                        order_id=order.id,
                        created_at=now,
                    )
                )
            self._audit(session, row, "reserved", row.operator)
            self._audit(session, row, "submit", row.operator, ":1")
            session.commit()  # Persist intent/hold BEFORE any cash-moving POST.
        return self._send(plan["refund_id"])

    @staticmethod
    def _same_request(existing, plan):
        if any(
            getattr(existing, k) != plan[k]
            for k in ("order_id", "amount", "reclaim_cards", "reason", "operator")
        ):
            raise PaymentError(409, "refund_idempotency_conflict", "退款单号已用于其他操作")

    def _send(self, refund_id: str) -> dict:
        with self.database.session() as session:
            row = session.get(PaymentRefund, refund_id)
            if row is None:
                raise PaymentError(404, "refund_not_found", "退款单不存在")
            order = self._order(session, row.order_id)
            payload = {
                "out_trade_no": row.order_id,
                "out_refund_no": row.id,
                "reason": row.reason,
                "notify_url": row.notify_url,
                "amount": {"total": order.total_amount, "refund": row.amount, "currency": "CNY"},
            }
            local = refund_json(row)
        if not self.client:
            return local  # Isolated mock: a test must explicitly deliver a simulated result.
        response = self.client.request("POST", "/v3/refund/domestic/refunds", payload)
        self.receive(response, source="response")
        return self.status(refund_id)

    def status(self, refund_id: str) -> dict:
        self.require_enabled()
        with self.database.session() as session:
            row = session.get(PaymentRefund, refund_id)
            if row is None:
                raise PaymentError(404, "refund_not_found", "退款单不存在")
            return refund_json(row)

    def sync(self, refund_id: str) -> dict:
        self.require_enabled()
        current = self.status(refund_id)
        if current["status"] in TERMINAL or not self.client:
            return current
        result = self.client.request("GET", "/v3/refund/domestic/refunds/" + quote(refund_id))
        self.receive(result, source="query")
        return self.status(refund_id)

    def retry(self, refund_id: str, confirmation: str) -> dict:
        """Explicit recovery only: signed not-found + same original id and parameters."""
        self.require_enabled()
        if confirmation != f"RETRY:{refund_id}" or self.client is None:
            raise PaymentError(409, "refund_confirmation_required", "恢复操作需要原退款单确认码")
        try:
            return self.sync(refund_id)
        except VerifiedProviderError as exc:
            if exc.http_status != 404 or exc.provider_code != "RESOURCE_NOT_EXISTS":
                raise
        with self.database.session() as session:
            row = session.get(PaymentRefund, refund_id)
            if row is None:
                raise PaymentError(404, "refund_not_found", "退款单不存在")
            self._order(session, row.order_id, lock=True)
            session.refresh(row, with_for_update=True)
            if row.status != "reserved" or now_utc() - row.last_submit_at < timedelta(minutes=1):
                raise PaymentError(
                    409, "refund_retry_not_ready", "状态已变化或请求间隔不足，请先查单"
                )
            row.submit_attempts += 1
            row.last_submit_at = now_utc()
            row.next_check_at = now_utc() + timedelta(minutes=1)
            self._audit(session, row, "submit", row.operator, f":{row.submit_attempts}")
            session.commit()
        return self._send(refund_id)

    def receive(self, data: dict, *, source: str) -> None:
        """Caller supplies only signature-verified query/response/decrypted notification."""
        self.require_enabled()
        if source not in {"query", "response", "callback"}:
            raise ValueError("Invalid refund evidence source")
        refund_id = data.get("out_refund_no")
        if not isinstance(refund_id, str):
            raise PaymentError(400, "refund_invalid_result", "退款结果缺少单号")
        with self.database.session() as session:
            row = session.get(PaymentRefund, refund_id)
            if row is None:
                raise PaymentError(400, "refund_unknown", "退款单未在本站登记，请人工核对")
            order = self._order(session, row.order_id, lock=True)
            session.refresh(row, with_for_update=True)
            try:
                amount = data["amount"]
                status = data["refund_status" if source == "callback" else "status"].lower()
                wxid = data["refund_id"]
                if (
                    data["out_trade_no"] != order.id
                    or data["transaction_id"] != order.transaction_id
                    or (source == "callback" and data["mchid"] != order.mchid)
                    or ("mchid" in data and data["mchid"] != order.mchid)
                    or type(amount["total"]) is not int
                    or amount["total"] != order.total_amount
                    or type(amount["refund"]) is not int
                    or amount["refund"] != row.amount
                    or (source != "callback" and amount["currency"] != "CNY")
                    or ("currency" in amount and amount["currency"] != "CNY")
                    or status not in {"processing", "success", "closed", "abnormal"}
                    or not isinstance(wxid, str)
                    or not 1 <= len(wxid) <= 64
                    or (row.provider_refund_id and row.provider_refund_id != wxid)
                ):
                    raise ValueError("Refund mismatch")
                success_at = None
                if status == "success":
                    success_at = datetime.fromisoformat(data["success_time"].replace("Z", "+00:00"))
                    if success_at.tzinfo is None:
                        raise ValueError("Missing success timezone")
                    success_at = success_at.astimezone(UTC).replace(tzinfo=None)
            except (KeyError, TypeError, ValueError, AttributeError) as exc:
                raise PaymentError(
                    400, "refund_result_mismatch", "退款结果与登记信息不匹配"
                ) from exc
            if row.status in TERMINAL:
                if status in TERMINAL and status != row.status:
                    raise PaymentError(409, "refund_terminal_conflict", "退款终态冲突，请人工核对")
                return  # Duplicate or late PROCESSING cannot revert a terminal state.
            if row.status == "abnormal" and status == "processing":
                return  # Do not hide an abnormal state with an older poll response.
            if row.status != status:
                if status == "closed" and row.reclaim_cards:
                    wallet = session.get(CardWallet, row.user_id, with_for_update=True)
                    if wallet is None:
                        raise PaymentError(409, "refund_wallet_missing", "卡账户缺失，请先核对")
                    wallet.balance += row.reclaim_cards
                    session.add(
                        CardLedger(
                            user_id=row.user_id,
                            event_key=f"refund-release:{row.id}",
                            delta=row.reclaim_cards,
                            order_id=row.order_id,
                            created_at=now_utc(),
                        )
                    )
                self._audit(session, row, status, source)
            row.status, row.provider_refund_id = status, wxid
            row.updated_at, row.success_at = now_utc(), success_at
            if status == "success":
                # Same transaction as SUCCESS: duplicate callbacks/queries cannot
                # mint another gift or extend its original seven-day lifetime.
                issued_at = now_utc()
                session.add(
                    WeeklyCoupon(
                        user_id=row.user_id,
                        period_start=None,
                        source_refund_id=row.id,
                        expires_at=issued_at + timedelta(days=7),
                    )
                )
                self._audit(session, row, "gift_coupon", source)
            age = (now_utc() - row.created_at).total_seconds()
            delay = 60 if age < 300 else min(1800, 300 * (2 ** min(3, int(age // 900))))
            row.next_check_at = now_utc() + timedelta(seconds=delay)
            session.commit()  # Original coupons/orders/reports and available cards are retained.

    def reconcile(self) -> None:
        self.require_enabled()
        if self.client is None:
            return
        with self.database.session() as session:
            ids = list(
                session.scalars(
                    select(PaymentRefund.id)
                    .where(
                        PaymentRefund.status.not_in(TERMINAL),
                        PaymentRefund.next_check_at <= now_utc(),
                    )
                    .order_by(PaymentRefund.next_check_at)
                    .limit(50)
                )
            )
        for refund_id in ids:
            try:
                self.sync(refund_id)
            except Exception as exc:
                logger.warning(
                    "refund_reconciliation_failed", extra={"error_type": type(exc).__name__}
                )
                with self.database.session() as session:
                    row = session.get(PaymentRefund, refund_id)
                    if row is None:
                        continue
                    self._order(session, row.order_id, lock=True)
                    session.refresh(row, with_for_update=True)
                    if row.status not in TERMINAL:
                        row.next_check_at = now_utc() + timedelta(minutes=5)
                        session.commit()  # Keep the hold; never infer failed cash from a timeout.
