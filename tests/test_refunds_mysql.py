"""Opt-in MySQL row-lock tests; restricted *_test database, synthetic users only."""

from __future__ import annotations

import copy
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from mysql_target import require_financial_test_database
from sqlalchemy import delete, func, select

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
from app.models import UserRecord, WechatIdentityRecord
from app.payment_config import PaymentSettings
from app.services.cards import PaymentError, debit_report, ensure_account, lock_user, now_utc
from app.services.payments import PaymentService, iso
from app.services.refunds import RefundService


class Provider:
    def __init__(self, order):
        self.order = order
        self.posts = []
        self.payload = None
        self.state = "PROCESSING"
        self.uncertain = False

    def result(self):
        return {
            "out_refund_no": self.payload["out_refund_no"],
            "out_trade_no": self.order.id,
            "transaction_id": self.order.transaction_id,
            "refund_id": "wx" + self.payload["out_refund_no"][:28],
            "status": self.state,
            "success_time": iso(now_utc()),
            "amount": copy.deepcopy(self.payload["amount"]),
        }

    def request(self, method, path, payload=None):
        if "/pay/transactions/" in path:
            assert method == "GET"
            return {
                "appid": self.order.app_id,
                "mchid": self.order.mchid,
                "out_trade_no": self.order.id,
                "transaction_id": self.order.transaction_id,
                "trade_state": "SUCCESS",
                "payer": {"openid": self.order.payer_openid},
                "amount": {"total": self.order.total_amount, "currency": "CNY"},
            }
        if method == "POST":
            assert path == "/v3/refund/domestic/refunds"
            self.posts.append(copy.deepcopy(payload))
            self.payload = copy.deepcopy(payload)
            if self.uncertain:
                raise PaymentError(502, "payment_unavailable", "simulated lost response")
        return self.result()


@pytest.fixture
def isolated():
    url = os.getenv("BAZI_TEST_MYSQL_URL", "")
    if not url:
        pytest.skip("Requires a restricted MySQL *_test database")
    require_financial_test_database(url)
    database, uid = Database(url), str(uuid.uuid4())
    with database.session() as session:
        session.add(UserRecord(id=uid, status="active"))
        session.flush()
        session.add(WechatIdentityRecord(user_id=uid, app_id="mock-app-id", openid=uid))
        lock_user(session, uid)
        ensure_account(session, uid, now_utc())
        session.commit()
    payments = PaymentService(database, PaymentSettings(mode="mock"), AuthSettings(mode="mock"))
    order_id = payments.create(uid, "family", True, uuid.uuid4().hex)["id"]
    payments.mock_confirm(uid, order_id)
    with database.session() as s:
        order = s.get(PaymentOrder, order_id)
    provider = Provider(order)
    refunds = RefundService(
        database,
        PaymentSettings(mode="mock", refunds_enabled=True),
        AuthSettings(mode="mock"),
        provider,
    )
    try:
        yield database, uid, order, refunds, provider
    finally:
        with database.session() as session:
            ids = select(PaymentRefund.id).where(PaymentRefund.user_id == uid)
            session.execute(delete(RefundAudit).where(RefundAudit.refund_id.in_(ids)))
            for table in (
                PaymentRefund,
                CardLedger,
                PaymentOrder,
                WeeklyCoupon,
                CardWallet,
                WechatIdentityRecord,
            ):
                session.execute(delete(table).where(table.user_id == uid))
            session.execute(delete(UserRecord).where(UserRecord.id == uid))
            session.commit()
        database.dispose()


def assert_balance(db, uid, expected):
    with db.session() as s:
        assert s.get(CardWallet, uid).balance == expected
        assert (
            s.scalar(select(func.sum(CardLedger.delta)).where(CardLedger.user_id == uid))
            == expected
        )


def test_mysql_duplicate_submission_reserves_and_submits_once(isolated):
    db, uid, order, service, provider = isolated
    plan = service.preview(order.id, 17800, 0, "协商退款", "mysql-test")
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: service.submit(plan, plan["confirmation"]), range(8)))
    assert len({r["refund_id"] for r in results}) == 1 and len(provider.posts) == 1
    assert_balance(db, uid, 5)
    with db.session() as s:
        assert (
            s.scalar(select(func.count(PaymentRefund.id)).where(PaymentRefund.user_id == uid)) == 1
        )


def test_mysql_refund_and_report_debit_never_reclaim_cards(isolated):
    db, uid, order, service, provider = isolated
    plan = service.preview(order.id, 17800, 0, "协商退款", "mysql-test")
    barrier = threading.Barrier(2)

    def refund():
        barrier.wait()
        try:
            service.submit(plan, plan["confirmation"])
            return "refund"
        except PaymentError as exc:
            assert exc.code == "refund_plan_stale"
            return "refund_refused"

    def report():
        barrier.wait()
        with db.session() as s:
            debit_report(s, uid, str(uuid.uuid4()))
            s.commit()

    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = pool.submit(refund), pool.submit(report)
        result = a.result()
        b.result()
    assert_balance(db, uid, 4)
    assert len(provider.posts) == (1 if result == "refund" else 0)


def test_mysql_duplicate_closed_results_release_only_once(isolated):
    db, uid, order, service, provider = isolated
    plan = service.preview(order.id, 10000, 0, "协商退款", "mysql-test")
    service.submit(plan, plan["confirmation"])
    provider.state = "CLOSED"
    evidence = provider.result()
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: service.receive(evidence, source="query"), range(8)))
    assert_balance(db, uid, 5)
    with db.session() as s:
        assert (
            s.scalar(
                select(func.count(CardLedger.id)).where(
                    CardLedger.event_key == "refund-release:" + plan["refund_id"]
                )
            )
            == 0
        )


def test_mysql_unknown_request_keeps_hold_and_blocks_fresh_refund(isolated):
    db, uid, order, service, provider = isolated
    plan = service.preview(order.id, 10000, 0, "协商退款", "mysql-test")
    provider.uncertain = True
    with pytest.raises(PaymentError):
        service.submit(plan, plan["confirmation"])
    service.submit(plan, plan["confirmation"])
    assert len(provider.posts) == 1
    assert_balance(db, uid, 5)
    with pytest.raises(PaymentError) as error:
        service.preview(order.id, 100, 0, "协商退款", "mysql-test")
    assert error.value.code == "refund_in_progress"


@pytest.mark.parametrize("microsecond", [0, 750000])
def test_mysql_concurrent_success_creates_one_independent_gift(isolated, monkeypatch, microsecond):
    db, uid, order, service, provider = isolated
    plan = service.preview(order.id, 3800, 0, "人工审核通过", "mysql-test")
    service.submit(plan, plan["confirmation"])
    provider.state = "SUCCESS"
    evidence = provider.result()
    issued_at = now_utc().replace(microsecond=microsecond)
    monkeypatch.setattr("app.services.refunds.now_utc", lambda: issued_at)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: service.receive(evidence, source="query"), range(8)))
    assert_balance(db, uid, 5)
    with db.session() as s:
        gifts = list(
            s.scalars(
                select(WeeklyCoupon).where(WeeklyCoupon.source_refund_id == plan["refund_id"])
            )
        )
        assert len(gifts) == 1 and gifts[0].period_start is None
        # MySQL DATETIME(0) can round fractional seconds up. Compare with
        # the fixed issuance time, not a later wall clock sampled by the test.
        expected = issued_at + timedelta(days=7)
        first_second = expected.replace(microsecond=0)
        last_second = first_second + timedelta(seconds=bool(microsecond))
        assert first_second <= gifts[0].expires_at <= last_second
        assert s.get(PaymentRefund, plan["refund_id"]).status == "success"
    payments = PaymentService(db, PaymentSettings(mode="mock"), AuthSettings(mode="mock"))
    pending = payments.create(uid, "single", True, uuid.uuid4().hex)
    assert pending["total_amount"] == 3800
    payments.mock_confirm(uid, pending["id"])
    assert_balance(db, uid, 6)
    assert payments.account(uid)["coupons"] == []
