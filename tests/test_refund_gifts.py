"""Refund success, coupon issuance and checkout must agree atomically."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
import test_refunds
from sqlalchemy import event, select
from test_payments import NOW, account, create
from test_refunds import balance, plan_for

from app.commerce_models import PaymentOrder, PaymentRefund, WeeklyCoupon
from app.services.cards import PaymentError, debit_report

payment_app = test_refunds.payment_app
paid = test_refunds.paid


def gifts(db):
    with db.session() as session:
        return list(
            session.scalars(select(WeeklyCoupon).where(WeeklyCoupon.source_refund_id.is_not(None)))
        )


def test_success_gifts_once_from_issue_time_not_payment_or_week_boundary(paid, monkeypatch):
    client, db, _, service, provider, order = paid
    plan = plan_for(paid)
    assert plan["policy"] == "keep_cards_and_gift_v1"
    assert plan["gift_coupon_amount"] == 5000 and plan["gift_coupon_valid_days"] == 7
    assert not gifts(db)
    service.submit(plan, plan["confirmation"])
    assert not gifts(db)  # PROCESSING is not a successful cash refund.
    issued_at = NOW + timedelta(days=5, hours=23)
    monkeypatch.setattr("app.services.refunds.now_utc", lambda: issued_at)
    monkeypatch.setattr("app.services.payments.now_utc", lambda: issued_at)
    provider.state = "SUCCESS"
    service.sync(plan["refund_id"])
    gift = gifts(db)[0]
    assert gift.source_refund_id == plan["refund_id"] and gift.period_start is None
    assert gift.expires_at == issued_at + timedelta(days=7)
    assert balance(db, order) == 5
    with db.session() as s:
        original = s.get(PaymentOrder, order.id)
        assert s.get(WeeklyCoupon, original.coupon_id).redeemed_order_id == order.id
    later = issued_at + timedelta(days=2)
    monkeypatch.setattr("app.services.refunds.now_utc", lambda: later)
    service.receive(provider.result(), source="query")
    assert len(gifts(db)) == 1 and gifts(db)[0].expires_at == gift.expires_at
    # A new weekly grant and the independent seven-day gift coexist.
    monday = NOW + timedelta(days=6)
    monkeypatch.setattr("app.services.payments.now_utc", lambda: monday)
    current = account(client)
    assert len(current["coupons"]) == 2
    assert {c["source"] for c in current["coupons"]} == {"weekly", "refund"}


@pytest.mark.parametrize("state", ["PROCESSING", "CLOSED", "ABNORMAL"])
def test_nonsuccess_never_gifts_or_changes_cards(paid, state):
    _, db, _, service, provider, order = paid
    provider.state = state
    service.submit(plan := plan_for(paid), plan["confirmation"])
    service.receive(provider.result(), source="query")
    assert not gifts(db) and balance(db, order) == 5


def test_gift_failure_rolls_back_success_and_callback_retry_can_finish(paid):
    _, db, _, service, provider, order = paid
    plan = plan_for(paid)
    service.submit(plan, plan["confirmation"])
    provider.state = "SUCCESS"

    def fail_gift(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("INSERT INTO WEEKLY_COUPONS"):
            raise RuntimeError("simulated storage failure")

    event.listen(db.engine, "before_cursor_execute", fail_gift)
    try:
        with pytest.raises(RuntimeError, match="storage failure"):
            service.receive(provider.result(), source="query")
    finally:
        event.remove(db.engine, "before_cursor_execute", fail_gift)
    assert service.status(plan["refund_id"])["status"] == "processing"
    assert not gifts(db) and balance(db, order) == 5
    service.receive(provider.result(), source="query")
    assert service.status(plan["refund_id"])["status"] == "success" and len(gifts(db)) == 1


def test_used_cards_refund_gift_redeemed_once_and_can_be_released_by_order_close(paid):
    client, db, _, service, provider, order = paid
    with db.session() as s:
        for _ in range(5):
            debit_report(s, order.user_id, str(uuid.uuid4()))
        s.commit()
    provider.state = "SUCCESS"
    service.submit(plan := plan_for(paid), plan["confirmation"])
    assert balance(db, order) == 0 and len(account(client)["coupons"]) == 1
    gift = gifts(db)[0]
    pending = create(client).json()
    assert pending["discount_amount"] == 5000 and pending["total_amount"] == 3800
    with db.session() as s:
        assert s.get(PaymentOrder, pending["id"]).coupon_id == gift.id
    assert account(client)["coupons"] == []
    assert client.post(f"/api/v1/payments/orders/{pending['id']}/close").status_code == 200
    assert len(account(client)["coupons"]) == 1
    second = create(client).json()
    for _ in range(2):
        assert (
            client.post(f"/api/v1/payments/orders/{second['id']}/mock-confirm").status_code == 200
        )
    assert balance(db, order) == 1 and account(client)["coupons"] == []
    assert create(client).json()["error"]["code"] == "coupon_unavailable"


def test_expired_gift_excluded_and_near_expiry_does_not_block_weekly_coupon(paid, monkeypatch):
    client, db, _, service, provider, _ = paid
    provider.state = "SUCCESS"
    service.submit(plan := plan_for(paid), plan["confirmation"])
    gift = gifts(db)[0]
    nearly_expired = gift.expires_at - timedelta(seconds=30)
    monkeypatch.setattr("app.services.payments.now_utc", lambda: nearly_expired)
    current = account(client)
    assert len(current["coupons"]) == 2 and current["coupon"]["source"] == "weekly"
    pending = create(client).json()
    with db.session() as s:
        chosen = s.get(WeeklyCoupon, s.get(PaymentOrder, pending["id"]).coupon_id)
        assert chosen.source_refund_id is None
    assert client.post(f"/api/v1/payments/orders/{pending['id']}/close").status_code == 200
    monkeypatch.setattr("app.services.payments.now_utc", lambda: gift.expires_at)
    assert all(c["id"] != gift.id for c in account(client)["coupons"])


def test_old_preview_and_any_nonzero_reclaim_are_rejected(paid):
    _, _, _, service, provider, order = paid
    with pytest.raises(PaymentError) as exc:
        service.preview(order.id, 3800, 1, "协商退款", "owner")
    assert exc.value.code == "refund_keeps_cards"
    plan = plan_for(paid)
    del plan["policy"]
    from app.services.refunds import digest

    plan["confirmation"] = digest({k: v for k, v in plan.items() if k != "confirmation"})
    with pytest.raises(PaymentError) as exc:
        service.submit(plan, plan["confirmation"])
    assert exc.value.code == "refund_policy_changed" and not provider.calls


def test_gift_source_unique_and_multiple_gifts_do_not_replace_weekly(paid, monkeypatch):
    client, db, _, service, provider, order = paid
    provider.state = "SUCCESS"
    service.submit(plan := plan_for(paid, amount=100), plan["confirmation"])
    monkeypatch.setattr("app.services.refunds.now_utc", lambda: NOW + timedelta(minutes=2))
    original = provider.result
    provider.result = lambda: dict(original(), refund_id="wx-refund-second")
    service.submit(plan := plan_for(paid, amount=100), plan["confirmation"])
    assert len(gifts(db)) == 2 and balance(db, order) == 5
    assert len(account(client)["coupons"]) == 2
    assert account(client)["coupon"]["id"] == gifts(db)[0].id
    with db.session() as s:
        assert len(list(s.scalars(select(PaymentRefund)))) == 2
