from __future__ import annotations

import base64
import copy
import json
import uuid
from dataclasses import replace
from datetime import timedelta

import pytest
import test_payments
import test_wechat_pay_crypto
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import func, select
from test_payments import NOW, account, create, transaction

from app.commerce_models import (
    CardLedger,
    CardWallet,
    PaymentOrder,
    PaymentRefund,
    RefundAudit,
)
from app.integrations.wechat_pay import VerifiedProviderError
from app.services.cards import PaymentError, debit_report
from app.services.refunds import RefundService, amount_cents, digest

payment_app = test_payments.payment_app
crypto_client = test_wechat_pay_crypto.crypto_client


class Provider:
    def __init__(self, order):
        self.order = order
        self.calls = []
        self.payload = None
        self.state = "PROCESSING"
        self.fail_post = False
        self.not_found = False
        self.on_post = None
        self.trade_state = "SUCCESS"

    def result(self):
        return {
            "out_refund_no": self.payload["out_refund_no"],
            "out_trade_no": self.order.id,
            "transaction_id": self.order.transaction_id,
            "refund_id": "wx-refund-001",
            "status": self.state,
            "success_time": "2026-10-20T12:00:00+08:00",
            "amount": copy.deepcopy(self.payload["amount"]),
        }

    def request(self, method, path, payload=None):
        self.calls.append((method, path, copy.deepcopy(payload)))
        if "/pay/transactions/" in path:
            assert method == "GET"
            result = transaction(self.order)
            result["transaction_id"] = self.order.transaction_id
            result["trade_state"] = self.trade_state
            return result
        if method == "POST":
            assert path == "/v3/refund/domestic/refunds"
            self.payload = copy.deepcopy(payload)
            if self.on_post:
                self.on_post()
            if self.fail_post:
                raise PaymentError(502, "payment_unavailable", "simulated lost response")
            return self.result()
        if self.not_found:
            raise VerifiedProviderError(404, "RESOURCE_NOT_EXISTS")
        return self.result()


@pytest.fixture
def paid(payment_app, monkeypatch):
    client, database, payments = payment_app
    monkeypatch.setattr("app.services.refunds.now_utc", lambda: NOW)
    order_id = create(client, "family").json()["id"]
    assert client.post(f"/api/v1/payments/orders/{order_id}/mock-confirm").status_code == 200
    with database.session() as session:
        order = session.get(PaymentOrder, order_id)
    provider = Provider(order)
    settings = replace(
        payments.settings,
        refunds_enabled=True,
        refund_notify_url="http://testserver/api/v1/payments/wechat/refund-notify",
    )
    refunds = RefundService(database, settings, payments.auth, provider)
    return client, database, payments, refunds, provider, order


def plan_for(paid, amount=10000, cards=0):
    return paid[3].preview(paid[5].id, amount, cards, "协商退款", "owner")


def balance(database, order):
    with database.session() as session:
        value = session.get(CardWallet, order.user_id).balance
        total = session.scalar(
            select(func.sum(CardLedger.delta)).where(CardLedger.user_id == order.user_id)
        )
        assert value == total
        return value


def test_preview_has_no_db_writes_or_merchant_calls(paid):
    _, db, _, service, provider, order = paid
    plan = plan_for(paid)
    assert plan["paid_amount"] == 17800 and plan["balance_after_reservation"] == 5
    assert plan["confirmation"] == digest({k: v for k, v in plan.items() if k != "confirmation"})
    assert not provider.calls and balance(db, order) == 5
    with db.session() as session:
        assert session.scalar(select(func.count(PaymentRefund.id))) == 0
        assert session.scalar(select(func.count(RefundAudit.id))) == 0
    with pytest.raises(PaymentError, match="确认码"):
        service.submit(plan, "wrong")
    assert not provider.calls


def test_partial_refund_keeps_cards_and_verified_success_is_idempotent(paid):
    client, db, payments, service, provider, order = paid
    plan = plan_for(paid)

    def during_cash_request():
        assert balance(db, order) == 5  # Hold committed before the provider sees a request.
        with db.session() as s:
            assert s.get(PaymentRefund, plan["refund_id"]).status == "reserved"

    provider.on_post = during_cash_request
    assert service.submit(plan, plan["confirmation"])["status"] == "processing"
    assert provider.payload["amount"] == {"total": 17800, "refund": 10000, "currency": "CNY"}
    assert "transaction_id" not in provider.payload  # Exactly one original order identifier.
    service.submit(plan, plan["confirmation"])
    assert len([c for c in provider.calls if c[0] == "POST"]) == 1
    provider.state = "SUCCESS"
    service.sync(plan["refund_id"])
    service.receive(provider.result(), source="query")
    service.receive(dict(provider.result(), status="PROCESSING"), source="response")
    assert service.status(plan["refund_id"])["status"] == "success"
    assert balance(db, order) == 5
    assert account(client)["coupon"]["status"] == "available"
    with db.session() as session:
        original = session.get(PaymentOrder, order.id)
        assert original.status == "paid" and original.total_amount == 17800
        assert (
            session.scalar(
                select(func.count(CardLedger.id)).where(
                    CardLedger.event_key == f"refund-hold:{plan['refund_id']}"
                )
            )
            == 0
        )
    repeated_payment = dict(transaction(order), transaction_id=order.transaction_id)
    payments.receive(repeated_payment)  # Late duplicate payment cannot buy cards back.
    assert balance(db, order) == 5


def test_closed_refund_does_not_change_cards(paid):
    _, db, _, service, provider, order = paid
    plan = plan_for(paid)
    service.submit(plan, plan["confirmation"])
    provider.state = "CLOSED"
    service.sync(plan["refund_id"])
    service.receive(provider.result(), source="query")
    assert balance(db, order) == 5
    with db.session() as s:
        assert (
            s.scalar(
                select(func.count(CardLedger.id)).where(
                    CardLedger.event_key == f"refund-release:{plan['refund_id']}"
                )
            )
            == 0
        )
    provider.state = "SUCCESS"
    with pytest.raises(PaymentError) as error:
        service.receive(provider.result(), source="query")
    assert error.value.code == "refund_terminal_conflict"


def test_unknown_and_abnormal_never_gift_until_verified_success(paid, monkeypatch):
    _, db, _, service, provider, order = paid
    plan = plan_for(paid)
    provider.fail_post = True
    with pytest.raises(PaymentError):
        service.submit(plan, plan["confirmation"])
    assert service.status(plan["refund_id"])["status"] == "reserved"
    assert balance(db, order) == 5
    service.submit(plan, plan["confirmation"])
    assert len([c for c in provider.calls if c[0] == "POST"]) == 1
    with pytest.raises(PaymentError) as second:
        plan_for(paid)
    assert second.value.code == "refund_in_progress"
    provider.not_found, provider.fail_post = True, False
    with pytest.raises(PaymentError) as too_soon:
        service.retry(plan["refund_id"], "RETRY:" + plan["refund_id"])
    assert too_soon.value.code == "refund_retry_not_ready"
    monkeypatch.setattr("app.services.refunds.now_utc", lambda: NOW + timedelta(minutes=2))
    original_payload = copy.deepcopy(provider.payload)
    service.retry(plan["refund_id"], "RETRY:" + plan["refund_id"])
    assert provider.payload == original_payload
    provider.not_found, provider.state = False, "ABNORMAL"
    service.sync(plan["refund_id"])
    assert balance(db, order) == 5
    service.receive(dict(provider.result(), status="PROCESSING"), source="query")
    assert service.status(plan["refund_id"])["status"] == "abnormal"
    provider.state = "SUCCESS"
    service.sync(plan["refund_id"])
    assert balance(db, order) == 5


@pytest.mark.parametrize(
    "field,value",
    [
        ("amount", 17801),
        ("amount", True),
        ("amount", 0),
        ("cards", 1),
        ("cards", 6),
        ("cards", -1),
        ("reason", "汉" * 27),
        ("operator", "bad operator"),
    ],
)
def test_invalid_manual_values_never_create_refund(paid, field, value):
    args = {
        "order_id": paid[5].id,
        "amount": 10000,
        "cards": 0,
        "reason": "协商退款",
        "operator": "owner",
    }
    args[field] = value
    with pytest.raises(PaymentError):
        paid[3].preview(**args)
    assert not paid[4].calls and balance(paid[1], paid[5]) == 5


def test_balance_change_and_plan_tampering_stop_before_cash(paid):
    _, db, _, service, provider, order = paid
    plan = plan_for(paid)
    modified = dict(plan, amount=100)
    with pytest.raises(PaymentError):
        service.submit(modified, plan["confirmation"])
    assert not provider.calls
    with db.session() as s:
        debit_report(s, order.user_id, str(uuid.uuid4()))
        s.commit()
    with pytest.raises(PaymentError) as error:
        service.submit(plan, plan["confirmation"])
    assert error.value.code == "refund_plan_stale"
    assert not any(c[0] == "POST" for c in provider.calls)
    assert balance(db, order) == 4


def test_refund_keeps_unused_cards_available_for_reports(paid):
    _, db, _, service, _, order = paid
    plan = plan_for(paid, amount=17800)
    service.submit(plan, plan["confirmation"])
    with db.session() as s:
        debit_report(s, order.user_id, str(uuid.uuid4()))
        s.commit()
    assert balance(db, order) == 4


def test_manual_refund_can_reclaim_zero_cards_after_used_service(paid):
    _, db, _, service, _, order = paid
    with db.session() as s:
        for _ in range(5):
            debit_report(s, order.user_id, str(uuid.uuid4()))
        s.commit()
    plan = plan_for(paid, amount=3800, cards=0)
    assert service.submit(plan, plan["confirmation"])["status"] == "processing"
    assert balance(db, order) == 0


@pytest.mark.parametrize(
    "change",
    ["amount", "total", "currency", "transaction", "merchant", "provider_id", "missing_time"],
)
def test_mismatched_result_does_not_release_or_confirm(paid, change):
    _, db, _, service, provider, order = paid
    plan = plan_for(paid)
    service.submit(plan, plan["confirmation"])
    data = provider.result()
    data["status"] = "SUCCESS"
    if change in {"amount", "total", "currency"}:
        data["amount"][{"amount": "refund", "total": "total", "currency": "currency"}[change]] = -1
    elif change == "transaction":
        data["transaction_id"] = "other-order"
    elif change == "merchant":
        data["mchid"] = "other-merchant"
    elif change == "provider_id":
        data["refund_id"] = "other-refund"
    else:
        del data["success_time"]
    with pytest.raises(PaymentError):
        service.receive(data, source="query")
    assert service.status(plan["refund_id"])["status"] == "processing"
    assert balance(db, order) == 5


def test_partial_totals_are_capped_and_each_approved_refund_gifts_once(paid, monkeypatch):
    client, db, _, service, provider, order = paid
    plan = plan_for(paid, amount=10000)
    provider.state = "SUCCESS"
    service.submit(plan, plan["confirmation"])
    monkeypatch.setattr("app.services.refunds.now_utc", lambda: NOW + timedelta(minutes=2))
    with pytest.raises(PaymentError):
        plan_for(paid, amount=7801, cards=0)
    with pytest.raises(PaymentError):
        plan_for(paid, amount=7800, cards=2)
    next_plan = plan_for(paid, amount=7800)
    provider.trade_state = "REFUND"  # Official original-order state after first refund.
    # Each provider refund ID is unique, just like the real API.
    original = provider.result
    provider.result = lambda: dict(original(), refund_id="wx-refund-002")
    service.submit(next_plan, next_plan["confirmation"])
    assert balance(db, order) == 5
    assert account(client)["coupon"]["status"] == "available"


def test_feature_off_and_unknown_callback_fail_closed(paid):
    client, db, _, service, provider, _ = paid
    assert client.post("/api/v1/payments/wechat/refund-notify", content=b"{}").status_code == 503
    service.settings = replace(service.settings, refunds_enabled=False)
    with pytest.raises(PaymentError):
        plan_for(paid)
    service.settings = replace(service.settings, refunds_enabled=True)
    with pytest.raises(PaymentError):
        service.receive({"out_refund_no": uuid.uuid4().hex}, source="callback")
    assert not provider.calls
    with db.session() as s:
        assert s.scalar(select(func.count(PaymentRefund.id))) == 0


def test_callback_without_currency_is_supported_and_keeps_reference_checks(paid):
    _, db, _, service, provider, order = paid
    plan = plan_for(paid)
    service.submit(plan, plan["confirmation"])
    data = dict(provider.result(), refund_status="SUCCESS", mchid=order.mchid)
    del data["status"]
    del data["amount"]["currency"]  # Official callback schema differs from query schema.
    service.receive(data, source="callback")
    service.receive(data, source="callback")
    assert balance(db, order) == 5
    assert service.status(plan["refund_id"])["status"] == "success"


def test_signed_http_refund_callback_is_no_store_and_idempotent(paid, crypto_client):
    client, db, payments, service, provider, order = paid
    plan = plan_for(paid)
    service.submit(plan, plan["confirmation"])
    crypto, _, signing_key = crypto_client
    payments.settings, payments.client = service.settings, crypto
    data = dict(provider.result(), refund_status="SUCCESS", mchid=order.mchid)
    del data["status"]
    del data["amount"]["currency"]
    nonce = b"123456789012"
    ciphertext = AESGCM(crypto.settings.api_v3_key.encode()).encrypt(
        nonce, json.dumps(data).encode(), b"refund"
    )
    body = json.dumps(
        {
            "event_type": "REFUND.SUCCESS",
            "resource": {
                "original_type": "refund",
                "algorithm": "AEAD_AES_256_GCM",
                "nonce": nonce.decode(),
                "associated_data": "refund",
                "ciphertext": base64.b64encode(ciphertext).decode(),
            },
        }
    ).encode()
    headers = test_wechat_pay_crypto.signed_headers(crypto, signing_key, body)
    path = "/api/v1/payments/wechat/refund-notify"
    assert client.post(path, content=body + b" ", headers=headers).status_code == 400
    assert service.status(plan["refund_id"])["status"] == "processing"
    for _ in range(2):
        response = client.post(path, content=body, headers=headers)
        assert response.status_code == 204
        assert "no-store" in response.headers["cache-control"]
    assert service.status(plan["refund_id"])["status"] == "success"
    assert balance(db, order) == 5


@pytest.mark.parametrize("state", ["NOTPAY", "CLOSED", "PAYERROR"])
def test_nonpaid_provider_state_cannot_start_refund(paid, state):
    _, db, _, service, provider, order = paid
    plan = plan_for(paid)
    provider.trade_state = state
    with pytest.raises(PaymentError) as error:
        service.submit(plan, plan["confirmation"])
    assert error.value.code == "refund_payment_state"
    assert not any(call[0] == "POST" for call in provider.calls)
    assert balance(db, order) == 5


@pytest.mark.parametrize("value,expected", [("38", 3800), ("0.01", 1), ("178.00", 17800)])
def test_money_has_no_float_rounding(value, expected):
    assert amount_cents(value) == expected


@pytest.mark.parametrize("value", ["0", "1.001", "1e2", "NaN", "-1", " 38", "01.00"])
def test_bad_money_is_rejected(value):
    with pytest.raises(ValueError):
        amount_cents(value)


def test_pending_and_expired_orders_refused_and_tampered_balance_detected(paid, monkeypatch):
    client, db, _, service, provider, order = paid
    unpaid = create(client, coupon=False).json()["id"]
    with pytest.raises(PaymentError) as error:
        service.preview(unpaid, 100, 0, "协商退款", "owner")
    assert error.value.code == "refund_order_unpaid"
    monkeypatch.setattr("app.services.refunds.now_utc", lambda: NOW + timedelta(days=366))
    with pytest.raises(PaymentError) as error:
        plan_for(paid)
    assert error.value.code == "refund_order_expired"
    monkeypatch.setattr("app.services.refunds.now_utc", lambda: NOW)
    with db.session() as s:
        s.get(CardWallet, order.user_id).balance = 1
        s.commit()
    with pytest.raises(PaymentError) as error:
        plan_for(paid, amount=100, cards=0)
    assert error.value.code == "refund_ledger_mismatch"
    assert not provider.calls


def test_expired_plan_and_wrong_payment_identity_never_send_cash(paid, monkeypatch):
    _, db, _, service, provider, order = paid
    plan = plan_for(paid)
    monkeypatch.setattr("app.services.refunds.now_utc", lambda: NOW + timedelta(minutes=11))
    with pytest.raises(PaymentError) as error:
        service.submit(plan, plan["confirmation"])
    assert error.value.code == "refund_plan_expired"
    assert balance(db, order) == 5
    assert not any(c[0] == "POST" for c in provider.calls)


def test_reconciler_queries_only_and_keeps_uncertain_intent(paid, monkeypatch):
    _, db, _, service, provider, order = paid
    plan = plan_for(paid)
    provider.fail_post = True
    with pytest.raises(PaymentError):
        service.submit(plan, plan["confirmation"])
    provider.not_found = True
    monkeypatch.setattr("app.services.refunds.now_utc", lambda: NOW + timedelta(minutes=2))
    service.reconcile()
    assert len([c for c in provider.calls if c[0] == "POST"]) == 1
    assert balance(db, order) == 5
    provider.not_found, provider.state = False, "SUCCESS"
    monkeypatch.setattr("app.services.refunds.now_utc", lambda: NOW + timedelta(minutes=8))
    service.reconcile()
    assert service.status(plan["refund_id"])["status"] == "success"


def test_refund_creation_is_not_a_public_or_readonly_admin_endpoint(paid):
    client = paid[0]
    for path in ("/api/v1/payments/refunds", "/api/v1/admin/refunds"):
        assert client.post(path, json={"amount": 100}).status_code in {404, 405}


def test_cli_nonroot_cannot_touch_database(monkeypatch):
    from app import refund_cli

    monkeypatch.setattr(refund_cli.sys, "platform", "linux")
    monkeypatch.setattr(refund_cli.os, "geteuid", lambda: 10001, raising=False)

    def no_db():
        raise AssertionError("Non-root CLI must not open a database")

    monkeypatch.setattr(refund_cli.Database, "from_env", no_db)
    assert refund_cli.main(["status", "--refund", "fixture"]) == 1


def test_refund_migration_preserves_old_orders_and_balances(tmp_path, monkeypatch):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import inspect

    from app.database import Database
    from app.models import UserRecord

    url = "sqlite+pysqlite:///" + (tmp_path / "migration.sqlite3").as_posix()
    monkeypatch.setenv("BAZI_DATABASE_URL", url)
    config = Config("alembic.ini")
    command.upgrade(config, "20261020_0005")
    db = Database(url)
    uid, oid = str(uuid.uuid4()), uuid.uuid4().hex
    with db.session() as s:
        s.add(UserRecord(id=uid, status="active"))
        s.flush()
        s.add(CardWallet(user_id=uid, balance=1))
        s.add(
            PaymentOrder(
                id=oid,
                user_id=uid,
                idempotency_key=uuid.uuid4().hex,
                product_code="single",
                product_name="历史订单",
                cards=1,
                original_amount=8800,
                discount_amount=5000,
                total_amount=3800,
                app_id="mock-app-id",
                mchid="mock-mch",
                payer_openid="fixture",
                status="paid",
                transaction_id="wx-old",
                created_at=NOW,
                expires_at=NOW,
                paid_at=NOW,
            )
        )
        s.flush()
        s.add(
            CardLedger(user_id=uid, event_key="pay:" + oid, delta=1, order_id=oid, created_at=NOW)
        )
        s.commit()
    command.upgrade(config, "20261101_0007")
    assert {"payment_refunds", "refund_audit"}.issubset(inspect(db.engine).get_table_names())
    with db.session() as s:
        assert s.get(CardWallet, uid).balance == 1
        assert s.get(PaymentOrder, oid).status == "paid"
        assert s.get(PaymentOrder, oid).total_amount == 3800
        assert s.scalar(select(func.count(CardLedger.id))) == 1
    db.dispose()
