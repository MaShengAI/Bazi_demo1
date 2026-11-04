from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.commerce_models import CardLedger, CardWallet, PaymentOrder, WeeklyCoupon
from app.config import AuthSettings
from app.database import Database
from app.integrations.wechat_pay import WechatPayClient
from app.models import WechatIdentityRecord
from app.payment_config import PaymentSettings
from app.services.cards import PaymentError, available_coupons, ensure_account, lock_user, now_utc

logger = logging.getLogger("bazi.payments")


def iso(value: datetime) -> str:
    return value.replace(tzinfo=UTC).isoformat()


def coupon_json(coupon: WeeklyCoupon) -> dict[str, Any]:
    return {
        "id": coupon.id,
        "amount": coupon.amount,
        "expires_at": iso(coupon.expires_at),
        "source": "redemption" if coupon.source_code_id else ("refund" if coupon.source_refund_id else "weekly"),
        "status": "used"
        if coupon.redeemed_order_id
        else ("reserved" if coupon.reserved_order_id else "available"),
    }


def preferred_coupon(coupons: list[WeeklyCoupon], now: datetime) -> WeeklyCoupon | None:
    # Avoid a nearly-expired voucher blocking another valid voucher at checkout.
    return next((c for c in coupons if c.expires_at - now >= timedelta(minutes=2)), None)


def order_json(order: PaymentOrder) -> dict[str, Any]:
    return {
        "id": order.id,
        "product_code": order.product_code,
        "product_name": order.product_name,
        "cards": order.cards,
        "original_amount": order.original_amount,
        "discount_amount": order.discount_amount,
        "coupon_id": order.coupon_id,
        "total_amount": order.total_amount,
        "status": order.status,
        "created_at": iso(order.created_at),
        "expires_at": iso(order.expires_at),
    }


class PaymentService:
    def __init__(self, database: Database, settings: PaymentSettings, auth: AuthSettings):
        self.database, self.settings, self.auth = database, settings, auth
        self.client = WechatPayClient(settings, auth.app_id) if settings.mode == "live" else None

    def require_enabled(self) -> None:
        if not self.settings.enabled:
            raise PaymentError(503, "payments_disabled", "购买解读卡尚未开放")

    def account(self, user_id: str) -> dict[str, Any]:
        self.require_enabled()
        with self.database.session() as session:
            lock_user(session, user_id)
            now = now_utc()
            weekly = ensure_account(session, user_id, now)
            coupons = available_coupons(session, user_id, now)
            coupon = preferred_coupon(coupons, now) or (coupons[0] if coupons else weekly)
            wallet = session.get(CardWallet, user_id)
            orders = session.scalars(
                select(PaymentOrder)
                .where(PaymentOrder.user_id == user_id)
                .order_by(PaymentOrder.created_at.desc())
                .limit(20)
            ).all()
            result = {
                "accept_new_orders": self.settings.can_purchase(user_id),
                "balance": wallet.balance if wallet else 0,
                "mode": self.settings.mode,
                # Keep the original singular field for older cached clients.
                "coupon": coupon_json(coupon),
                "coupons": [coupon_json(c) for c in coupons],
                "products": [
                    {"code": p.code, "name": p.name, "cards": p.cards, "price": p.price}
                    for p in self.settings.products
                ],
                "orders": [order_json(order) for order in orders],
            }
            session.commit()
            return result

    def create(
        self, user_id: str, product_code: str, use_coupon: bool, idempotency_key: str,
        coupon_id: str | None = None,
    ) -> dict:
        self.require_enabled()
        if coupon_id is not None and not use_coupon:
            raise PaymentError(422, "invalid_coupon_selection", "不使用优惠券时不能指定优惠券")
        if not self.settings.can_purchase(user_id):
            raise PaymentError(503, "purchases_paused", "暂时停止新购，已有订单仍可支付或查单")
        product = next((p for p in self.settings.products if p.code == product_code), None)
        if product is None:
            raise PaymentError(422, "invalid_product", "商品不存在")
        with self.database.session() as session:
            lock_user(session, user_id)
            existing = session.scalar(
                select(PaymentOrder).where(
                    PaymentOrder.user_id == user_id, PaymentOrder.idempotency_key == idempotency_key
                )
            )
            if existing:
                if (existing.product_code != product_code or bool(existing.coupon_id) != use_coupon
                        or (coupon_id is not None and existing.coupon_id != coupon_id)):
                    raise PaymentError(409, "idempotency_conflict", "请勿使用同一请求创建不同订单")
                return order_json(existing)
            # One outstanding order prevents accidental double purchase on lost responses.
            pending = session.scalar(
                select(PaymentOrder).where(
                    PaymentOrder.user_id == user_id, PaymentOrder.status == "pending"
                )
            )
            if pending:
                raise PaymentError(409, "order_pending", "有待支付订单，请先继续支付、查单或关闭")
            now = now_utc()
            weekly = ensure_account(session, user_id, now)
            coupons = available_coupons(session, user_id, now) if use_coupon else []
            coupon = preferred_coupon(coupons, now) or (coupons[0] if coupons else weekly)
            if coupon_id is not None:
                # Never substitute a different voucher for an explicit selection.
                coupon = next((c for c in coupons if c.id == coupon_id), None)
                if coupon is None:
                    raise PaymentError(409, "coupon_unavailable", "所选优惠券已失效或被占用，请重新选择")
            identity = session.scalar(
                select(WechatIdentityRecord).where(
                    WechatIdentityRecord.user_id == user_id,
                    WechatIdentityRecord.app_id == (self.auth.app_id or "mock-app-id"),
                )
            )
            if identity is None or (identity.profile_json or {}).get("is_snapshotuser") in {1, "1"}:
                raise PaymentError(403, "payment_identity_required", "请使用正式微信账户重新登录")
            expires = now + timedelta(minutes=15)
            if use_coupon:
                if coupon.redeemed_order_id or coupon.reserved_order_id:
                    raise PaymentError(
                        409, "coupon_unavailable", "暂无可用优惠券或已被待支付订单占用"
                    )
                # WeChat adjusts time_expire shorter than a minute. Do not allow
                # an old coupon to leak beyond the exact weekly boundary.
                if coupon.expires_at - now < timedelta(minutes=2):
                    raise PaymentError(409, "coupon_expiring", "优惠券即将过期，请稍后重新选择")
                expires = min(expires, coupon.expires_at)
            order = PaymentOrder(
                id=uuid.uuid4().hex,
                user_id=user_id,
                idempotency_key=idempotency_key,
                product_code=product.code,
                product_name=product.name,
                cards=product.cards,
                original_amount=product.price,
                discount_amount=min(coupon.amount, product.price - 1) if use_coupon else 0,
                total_amount=product.price - (min(coupon.amount, product.price - 1) if use_coupon else 0),
                coupon_id=coupon.id if use_coupon else None,
                app_id=self.auth.app_id or "mock-app-id",
                mchid=self.settings.mchid or "mock-mch",
                payer_openid=identity.openid,
                status="pending",
                created_at=now,
                expires_at=expires,
            )
            if use_coupon:
                coupon.reserved_order_id = order.id
            session.add(order)
            session.commit()
            return order_json(order)

    @staticmethod
    def _owned(session: Session, user_id: str, order_id: str) -> PaymentOrder:
        lock_user(session, user_id)
        order = session.get(PaymentOrder, order_id, with_for_update=True, populate_existing=True)
        if order is None or order.user_id != user_id:
            raise PaymentError(404, "order_not_found", "订单不存在")
        return order

    def prepay(self, user_id: str, order_id: str) -> dict:
        self.require_enabled()
        with self.database.session() as session:
            order = self._owned(session, user_id, order_id)
            if order.status != "pending" or order.expires_at <= now_utc() + timedelta(minutes=1):
                raise PaymentError(409, "order_not_payable", "订单无法支付，请先查单或关闭后重建")
            if self.client is None:
                return {"mode": "mock", "parameters": None}
            if not order.prepay_id:
                # Persist uncertainty BEFORE network I/O. A lost response must
                # never release the coupon based only on local time.
                order.provider_started = True
                session.commit()
                order = self._owned(session, user_id, order_id)
                if order.status != "pending":
                    raise PaymentError(409, "order_not_payable", "订单状态已更新，请重新查单")
                payload = {
                    "appid": order.app_id,
                    "mchid": order.mchid,
                    "description": f"解读卡*{order.cards}张",
                    "out_trade_no": order.id,
                    "notify_url": self.settings.notify_url,
                    "time_expire": iso(order.expires_at),
                    "amount": {"total": order.total_amount, "currency": "CNY"},
                    "payer": {"openid": order.payer_openid},
                }
                result = self.client.request("POST", "/v3/pay/transactions/jsapi", payload)
                prepay_id = result.get("prepay_id")
                if not isinstance(prepay_id, str) or not 1 <= len(prepay_id) <= 128:
                    raise PaymentError(502, "payment_invalid_response", "缺少预支付标识")
                order.prepay_id = prepay_id
                session.commit()
            return {"mode": "live", "parameters": self.client.jsapi_parameters(order.prepay_id)}

    def refresh(self, user_id: str, order_id: str, *, close: bool = False) -> dict:
        self.require_enabled()
        with self.database.session() as session:
            order = self._owned(session, user_id, order_id)
            if order.status == "pending" and self.client and order.provider_started:
                path = f"/v3/pay/transactions/out-trade-no/{order.id}"
                transaction = self.client.request("GET", path + "?mchid=" + quote(order.mchid))
                self._validate(order, transaction, paid=False)
                if transaction.get("trade_state") == "SUCCESS":
                    self._credit(session, order, transaction)
                elif transaction.get("trade_state") in {"CLOSED", "REVOKED"}:
                    self._close(session, order)
                elif close:
                    self.client.request("POST", path + "/close", {"mchid": order.mchid})
                    self._close(session, order)
            elif order.status == "pending" and close:
                self._close(session, order)
            session.commit()
            return order_json(order)

    def reconcile(self) -> None:
        """Callback fallback; only the API has merchant keys, never AI workers."""
        if self.client is None:
            return
        after = ""
        while True:
            with self.database.session() as session:
                rows = session.execute(
                    select(PaymentOrder.id, PaymentOrder.user_id, PaymentOrder.expires_at)
                    .where(PaymentOrder.status == "pending", PaymentOrder.id > after)
                    .order_by(PaymentOrder.id)
                    .limit(50)
                ).all()
            if not rows:
                return
            for order_id, user_id, expiry in rows:
                try:
                    self.refresh(user_id, order_id, close=expiry <= now_utc())
                except Exception as exc:
                    logger.warning(
                        "payment_reconciliation_failed", extra={"error_type": type(exc).__name__}
                    )
            after = rows[-1][0]

    def mock_confirm(self, user_id: str, order_id: str) -> dict:
        if self.settings.mode != "mock":
            raise PaymentError(404, "not_found", "接口不存在")
        with self.database.session() as session:
            order = self._owned(session, user_id, order_id)
            if order.status != "paid" and (
                order.status != "pending" or order.expires_at <= now_utc()
            ):
                raise PaymentError(409, "order_not_payable", "测试订单已关闭或过期")
            self._credit(
                session,
                order,
                {
                    "appid": order.app_id,
                    "mchid": order.mchid,
                    "out_trade_no": order.id,
                    "transaction_id": f"mock-{order.id}",
                    "trade_state": "SUCCESS",
                    "payer": {"openid": order.payer_openid},
                    "amount": {"total": order.total_amount, "currency": "CNY"},
                    "success_time": iso(now_utc()),
                },
            )
            session.commit()
            return order_json(order)

    def receive(self, transaction: dict) -> None:
        order_id = transaction.get("out_trade_no")
        if not isinstance(order_id, str):
            raise PaymentError(400, "payment_invalid_transaction", "支付订单号无效")
        with self.database.session() as session:
            order = session.get(PaymentOrder, order_id)
            if order is None:
                raise PaymentError(400, "payment_unknown_order", "支付订单不存在")
            lock_user(session, order.user_id, allow_disabled=True)
            session.refresh(order, with_for_update=True)
            self._credit(session, order, transaction)
            session.commit()

    @staticmethod
    def _validate(order: PaymentOrder, transaction: dict, *, paid: bool) -> None:
        try:
            if (
                transaction["appid"] != order.app_id
                or transaction["mchid"] != order.mchid
                or transaction["out_trade_no"] != order.id
                or transaction["trade_state"]
                not in {
                    "SUCCESS",
                    "REFUND",
                    "NOTPAY",
                    "CLOSED",
                    "REVOKED",
                    "USERPAYING",
                    "PAYERROR",
                    "ACCEPT",
                }
            ):
                raise ValueError("Transaction mismatch")
            # The official query schema permits amount/payer to be absent on
            # unpaid orders. Never permit absence when granting paid cards.
            if paid:
                amount = transaction["amount"]
                if (
                    transaction["trade_state"] != "SUCCESS"
                    or transaction["payer"]["openid"] != order.payer_openid
                    or type(amount["total"]) is not int
                    or amount["total"] != order.total_amount
                    or amount["currency"] != "CNY"
                ):
                    raise ValueError("Paid transaction mismatch")
        except (KeyError, TypeError, ValueError) as exc:
            raise PaymentError(
                400, "payment_transaction_mismatch", "支付通知与本站订单不匹配"
            ) from exc

    def _credit(self, session: Session, order: PaymentOrder, transaction: dict) -> None:
        self._validate(order, transaction, paid=True)
        transaction_id = transaction.get("transaction_id")
        try:
            success_time = transaction.get("success_time")
            if not isinstance(success_time, str):
                raise ValueError("Missing success time")
            paid_at = datetime.fromisoformat(success_time.replace("Z", "+00:00"))
            if (
                not paid_at.tzinfo
                or not isinstance(transaction_id, str)
                or not 1 <= len(transaction_id) <= 64
            ):
                raise ValueError("Missing transaction identity")
        except (KeyError, TypeError, ValueError) as exc:
            raise PaymentError(400, "payment_invalid_transaction", "支付结果缺少交易标识") from exc
        if order.status == "paid":
            if order.transaction_id != transaction_id:
                raise PaymentError(409, "payment_duplicate_mismatch", "交易标识不一致")
            return
        # A delayed, verified success must be honored, even after local expiry.
        ensure_account(session, order.user_id, now_utc())
        wallet = session.get(
            CardWallet, order.user_id, with_for_update=True, populate_existing=True
        )
        assert wallet is not None
        wallet.balance += order.cards
        session.add(
            CardLedger(
                user_id=order.user_id,
                event_key=f"pay:{order.id}",
                delta=order.cards,
                order_id=order.id,
                created_at=now_utc(),
            )
        )
        order.status, order.transaction_id = "paid", transaction_id
        order.paid_at = paid_at.astimezone(UTC).replace(tzinfo=None)
        if order.coupon_id:
            coupon = session.get(
                WeeklyCoupon, order.coupon_id, with_for_update=True, populate_existing=True
            )
            if coupon is None or coupon.redeemed_order_id not in {None, order.id}:
                raise PaymentError(409, "coupon_conflict", "优惠券交易冲突，请人工核对")
            coupon.redeemed_order_id, coupon.reserved_order_id = order.id, None

    @staticmethod
    def _close(session: Session, order: PaymentOrder) -> None:
        order.status = "closed"
        if order.coupon_id:
            coupon = session.get(
                WeeklyCoupon, order.coupon_id, with_for_update=True, populate_existing=True
            )
            if coupon and coupon.reserved_order_id == order.id and not coupon.redeemed_order_id:
                coupon.reserved_order_id = None
