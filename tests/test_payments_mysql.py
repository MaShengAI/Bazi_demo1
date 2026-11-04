"""Opt-in integration tests. Never point BAZI_TEST_MYSQL_URL at a real account DB."""

from __future__ import annotations

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from datetime import timedelta

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.engine import make_url

from app.commerce_models import CardLedger, CardWallet, PaymentOrder, WeeklyCoupon
from app.config import AuthSettings
from app.database import Database
from app.models import UserRecord, WechatIdentityRecord
from app.payment_config import PaymentSettings
from app.services.cards import PaymentError, debit_report, ensure_account, lock_user, now_utc
from app.services.payments import PaymentService, iso


@pytest.fixture
def mysql_account():
    url = os.getenv("BAZI_TEST_MYSQL_URL", "").strip()
    if not url:
        pytest.skip("BAZI_TEST_MYSQL_URL is not configured; financial concurrency needs MySQL")
    if not (make_url(url).database or "").endswith("_test"):
        pytest.fail("Payment integration tests require a database ending in _test")
    database = Database(url)
    user_id = str(uuid.uuid4())
    with database.session() as session:
        session.add(UserRecord(id=user_id, status="active"))
        session.flush()
        session.add(WechatIdentityRecord(user_id=user_id, app_id="mock-app-id", openid=user_id))
        lock_user(session, user_id)
        ensure_account(session, user_id, now_utc())
        session.commit()
    try:
        yield database, user_id
    finally:
        # Only remove records created for this isolated test user.
        with database.session() as session:
            for table in (CardLedger, PaymentOrder, WeeklyCoupon, CardWallet, WechatIdentityRecord):
                session.execute(delete(table).where(table.user_id == user_id))
            session.execute(delete(UserRecord).where(UserRecord.id == user_id))
            session.commit()
        database.dispose()


def test_mysql_simultaneous_debits_never_go_negative(mysql_account):
    database, user_id = mysql_account
    with database.session() as session:
        session.get(CardWallet, user_id).balance = 1
        session.commit()

    def attempt(_):
        with database.session() as session:
            try:
                debit_report(session, user_id, str(uuid.uuid4()))
                session.commit()
                return "charged"
            except PaymentError as exc:
                assert exc.code == "cards_required"
                return "insufficient"

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(attempt, range(8)))
    assert results.count("charged") == 1
    with database.session() as session:
        assert session.get(CardWallet, user_id).balance == 0
        assert (
            session.scalar(select(func.count(CardLedger.id)).where(CardLedger.user_id == user_id))
            == 1
        )


@pytest.mark.parametrize("same_request", [True, False])
def test_mysql_selected_coupon_race_reserves_exactly_once(mysql_account, same_request):
    database, user_id = mysql_account
    service = PaymentService(database, PaymentSettings(mode="mock"), AuthSettings(mode="mock"))
    selected_id = str(uuid.uuid4())
    with database.session() as session:
        session.add(WeeklyCoupon(id=selected_id, user_id=user_id, amount=8800,
                                expires_at=now_utc() + timedelta(days=10)))
        session.commit()
    shared_key, barrier = uuid.uuid4().hex, Barrier(8)

    def attempt(_):
        barrier.wait(timeout=20)
        try:
            return service.create(user_id, "single", True,
                                  shared_key if same_request else uuid.uuid4().hex,
                                  coupon_id=selected_id)
        except PaymentError as exc:
            assert exc.code == "order_pending"
            return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(attempt, range(8)))
    orders = [result for result in results if result is not None]
    assert len(orders) == (8 if same_request else 1)
    assert len({order["id"] for order in orders}) == 1
    assert all(order["coupon_id"] == selected_id and order["total_amount"] == 1 for order in orders)
    with database.session() as session:
        assert session.scalar(select(func.count(PaymentOrder.id)).where(PaymentOrder.user_id == user_id)) == 1
        assert session.get(WeeklyCoupon, selected_id).reserved_order_id == orders[0]["id"]
        other = session.scalars(select(WeeklyCoupon).where(WeeklyCoupon.user_id == user_id, WeeklyCoupon.id != selected_id)).one()
        assert other.reserved_order_id is None and other.redeemed_order_id is None


def test_mysql_duplicate_callbacks_and_weekly_issuance_are_atomic(mysql_account):
    database, user_id = mysql_account
    service = PaymentService(database, PaymentSettings(mode="mock"), AuthSettings(mode="mock"))
    order = service.create(user_id, "family", True, uuid.uuid4().hex)
    with database.session() as session:
        record = session.get(PaymentOrder, order["id"])
        event = {
            "appid": record.app_id,
            "mchid": record.mchid,
            "out_trade_no": record.id,
            "transaction_id": "wx-" + record.id,
            "trade_state": "SUCCESS",
            "payer": {"openid": record.payer_openid},
            "amount": {"total": record.total_amount, "currency": "CNY"},
            "success_time": iso(now_utc()),
        }
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: service.receive(event), range(8)))
    with database.session() as session:
        assert session.get(CardWallet, user_id).balance == 5
        assert (
            session.scalar(select(func.count(CardLedger.id)).where(CardLedger.user_id == user_id))
            == 1
        )
        assert (
            session.scalar(
                select(func.count(WeeklyCoupon.id)).where(WeeklyCoupon.user_id == user_id)
            )
            == 1
        )
