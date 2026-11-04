import uuid
from dataclasses import replace
from datetime import datetime, timedelta

import pytest
from sqlalchemy import event, func, select
from test_payments import NOW, account, create, payment_app  # noqa: F401 - shared pytest fixture

from app.commerce_models import CardLedger, CardWallet, RedemptionCode, WeeklyCoupon
from app.models import UserRecord
from app.services.cards import PaymentError
from app.services.redemptions import RedemptionService, code_digest, month_later


@pytest.fixture
def codes(payment_app, monkeypatch):  # noqa: F811 - pytest injects imported fixture
    client, db, payments = payment_app
    monkeypatch.setattr("app.services.redemptions.now_utc", lambda: NOW)
    service = RedemptionService(db)
    user_id = client.get("/api/v1/auth/me").json()["user"]["id"]
    return client, db, payments, service, user_id


def generate(service, kind="cards", value=2, quantity=1, key=None):
    return service.generate(
        kind=kind,
        value=value,
        quantity=quantity,
        label="测试赠礼",
        request_key=key or uuid.uuid4().hex,
        operator="owner",
    )


@pytest.mark.parametrize(
    "start,end",
    [
        ("2026-01-31T04:05:06", "2026-02-28T04:05:06"),
        ("2028-01-31T04:05:06", "2028-02-29T04:05:06"),
        ("2026-12-31T16:05:06", "2027-01-31T16:05:06"),  # Beijing Jan 1 -> Feb 1
    ],
)
def test_calendar_month_not_30_days(start, end):
    assert month_later(datetime.fromisoformat(start)) == datetime.fromisoformat(end)


def test_cards_once_even_when_purchases_paused_and_normalizes(codes):
    client, db, payments, service, user = codes
    payments.settings = replace(payments.settings, accept_new_orders=False)
    batch = generate(service)
    raw = batch["codes"][0]
    result = client.post("/api/v1/redemptions", json={"code": "  " + raw.lower() + "\n"})
    assert result.status_code == 200 and result.json()["value"] == 2
    again = client.post("/api/v1/redemptions", json={"code": raw})
    assert again.json()["already_redeemed"] is True
    assert account(client)["balance"] == 2
    with db.session() as s:
        assert s.scalar(select(func.count(CardLedger.id))) == 1
        stored = s.scalar(select(RedemptionCode))
        assert stored.code_hash == code_digest(raw) and raw not in stored.code_hash
        assert stored.redeemed_by == user


def test_other_account_cannot_reuse_or_read_receipt(codes):
    _, db, _, service, user = codes
    raw = generate(service)["codes"][0]
    service.redeem(user, raw)
    other = str(uuid.uuid4())
    with db.session() as s:
        s.add(UserRecord(id=other, status="active"))
        s.commit()
    with pytest.raises(PaymentError, match="兑换码"):
        service.redeem(other, raw)
    with db.session() as s:
        assert s.get(CardWallet, other) is None


def test_coupon_independent_seven_days_preserves_weekly_and_face_value(codes, monkeypatch):
    client, db, _, service, user = codes
    raw = generate(service, "coupon", 3000)["codes"][0]
    redeemed = NOW + timedelta(days=20, hours=7)
    monkeypatch.setattr("app.services.redemptions.now_utc", lambda: redeemed)
    result = service.redeem(user, raw)
    assert result["coupon_expires_at"].startswith((redeemed + timedelta(days=7)).isoformat())
    service.redeem(user, raw)
    with db.session() as s:
        coupons = list(s.scalars(select(WeeklyCoupon)))
        assert len(coupons) == 2
        gift = next(c for c in coupons if c.source_code_id)
        assert gift.amount == 3000 and gift.period_start is None
        assert gift.expires_at == redeemed + timedelta(days=7)
        assert s.scalar(select(func.count(CardLedger.id))) == 0
    monkeypatch.setattr("app.services.payments.now_utc", lambda: redeemed)
    current = account(client)
    assert any(c["amount"] == 3000 and c["source"] == "redemption" for c in current["coupons"])
    # Keep a single available voucher, then check authoritative order pricing.
    with db.session() as s:
        for c in s.scalars(select(WeeklyCoupon).where(WeeklyCoupon.source_code_id.is_(None))):
            c.expires_at = NOW
        s.commit()
    order = create(client).json()
    assert order["discount_amount"] == 3000 and order["total_amount"] == 5800


def test_coupon_larger_than_product_never_makes_negative_or_zero_order(codes):
    client, db, _, service, user = codes
    raw = generate(service, "coupon", 10000)["codes"][0]
    service.redeem(user, raw)
    with db.session() as s:
        for c in s.scalars(select(WeeklyCoupon).where(WeeklyCoupon.source_code_id.is_(None))):
            c.expires_at = NOW
        s.commit()
    order = create(client).json()
    assert order["total_amount"] == 1 and order["discount_amount"] == 8799


def test_expired_boundary_disabled_and_duplicate_batch(codes, monkeypatch):
    _, db, _, service, user = codes
    key = uuid.uuid4().hex
    batch = generate(service, quantity=2, key=key)
    with pytest.raises(PaymentError) as conflict:
        generate(service, key=key)
    assert conflict.value.code == "batch_already_created"
    with db.session() as s:
        code = s.scalar(
            select(RedemptionCode).where(RedemptionCode.code_hash == code_digest(batch["codes"][0]))
        )
        code_id = code.id
    service.disable(code_id, "owner")
    with pytest.raises(PaymentError):
        service.redeem(user, batch["codes"][0])
    monkeypatch.setattr("app.services.redemptions.now_utc", lambda: month_later(NOW))
    with pytest.raises(PaymentError):
        service.redeem(user, batch["codes"][1])
    assert service.listing(status="disabled")["total"] == 1
    assert service.listing(status="expired")["total"] == 1
    assert "code_hash" not in str(service.listing())


def test_storage_failure_rolls_back_claim_and_credit(codes):
    _, db, _, service, user = codes
    raw = generate(service)["codes"][0]

    def fail(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("INSERT INTO CARD_LEDGER"):
            raise RuntimeError("ledger unavailable")

    event.listen(db.engine, "before_cursor_execute", fail)
    try:
        with pytest.raises(RuntimeError):
            service.redeem(user, raw)
    finally:
        event.remove(db.engine, "before_cursor_execute", fail)
    with db.session() as s:
        assert s.scalar(select(RedemptionCode)).redeemed_by is None
        assert s.get(CardWallet, user).balance == 0
    assert service.redeem(user, raw)["already_redeemed"] is False


def test_rate_limit_invalid_codes_no_secret_in_error(codes):
    client, _, _, _, _ = codes
    for _ in range(5):
        assert (
            client.post("/api/v1/redemptions", json={"code": "invalid-secret"}).status_code == 400
        )
    assert client.post("/api/v1/redemptions", json={"code": "invalid-secret"}).status_code == 429
    oversized = client.post("/api/v1/redemptions", json={"code": "private-code" * 100})
    assert oversized.status_code == 422 and "private-code" not in oversized.text


def test_customer_cannot_access_admin_and_cross_site_rejected(codes):
    client, _, _, _, _ = codes
    assert client.get("/api/v1/admin/redemptions").status_code in {401, 503}
    res = client.post(
        "/api/v1/redemptions", headers={"Origin": "https://evil.example"}, json={"code": "X"}
    )
    assert res.status_code == 403
    client.post("/api/v1/auth/logout")
    assert client.post("/api/v1/redemptions", json={"code": "X"}).status_code == 401
