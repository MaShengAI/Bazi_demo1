from __future__ import annotations

import copy
import uuid
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.commerce_models import CardLedger, CardWallet, PaymentOrder, WeeklyCoupon
from app.config import AuthSettings
from app.coupon_scheduler import issue_current_week
from app.database import Base, Database
from app.integrations.wechat import WechatProfile
from app.main import app
from app.models import AnalysisJobRecord, UserRecord
from app.payment_config import PaymentSettings
from app.services.cards import PaymentError, week_window
from app.services.payments import iso

NOW = datetime(2026, 10, 20, 4)


@pytest.fixture
def payment_app(tmp_path, monkeypatch):
    url = f"sqlite+pysqlite:///{(tmp_path / 'payments.sqlite3').as_posix()}"
    monkeypatch.setenv("BAZI_DATABASE_URL", url)
    monkeypatch.setenv("BAZI_WECHAT_AUTH_MODE", "mock")
    monkeypatch.setenv(
        "BAZI_WECHAT_OAUTH_CALLBACK_URL", "http://testserver/api/v1/auth/wechat/callback"
    )
    monkeypatch.setenv("BAZI_SESSION_COOKIE_SECURE", "false")
    monkeypatch.setenv("BAZI_PAY_MODE", "mock")
    monkeypatch.setenv("BAZI_AUTH_REQUIRED_FOR_ANALYSIS", "false")
    monkeypatch.setattr("app.services.auth.utcnow_naive", lambda: NOW)
    monkeypatch.setattr("app.services.payments.now_utc", lambda: NOW)
    monkeypatch.setattr("app.coupon_scheduler.now_utc", lambda: NOW)
    bootstrap = Database(url)
    Base.metadata.create_all(bootstrap.engine)
    bootstrap.dispose()
    with TestClient(app) as client:
        started = client.get("/api/v1/auth/wechat/start", follow_redirects=False)
        client.get(started.headers["location"], follow_redirects=False)
        yield client, app.state.database, app.state.payment_service


def create(client, product="single", coupon=True, key=None):
    return client.post(
        "/api/v1/payments/orders",
        json={
            "product_code": product,
            "use_coupon": coupon,
            "idempotency_key": key or uuid.uuid4().hex,
        },
    )


def account(client):
    response = client.get("/api/v1/payments/account")
    assert response.status_code == 200, response.text
    assert "no-store" in response.headers["cache-control"]
    return response.json()


def test_explicit_coupon_controls_price_and_idempotency(payment_app):
    client, database, _ = payment_app
    default = account(client)["coupon"]
    with database.session() as session:
        user_id = session.get(WeeklyCoupon, default["id"]).user_id
        selected = WeeklyCoupon(id=str(uuid.uuid4()), user_id=user_id, amount=8800,
                                expires_at=NOW + timedelta(days=10))
        selected_id = selected.id
        session.add(selected)
        session.commit()
    assert account(client)["coupon"]["id"] == default["id"]
    payload = {"product_code": "single", "use_coupon": True,
               "coupon_id": selected_id, "idempotency_key": uuid.uuid4().hex}
    response = client.post("/api/v1/payments/orders", json=payload)
    assert response.status_code == 201, response.text
    order = response.json()
    assert (order["coupon_id"], order["discount_amount"], order["total_amount"]) == (selected_id, 8799, 1)
    assert client.post("/api/v1/payments/orders", json=payload).json()["id"] == order["id"]
    conflict = client.post("/api/v1/payments/orders", json={**payload, "coupon_id": default["id"]})
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "idempotency_conflict"
    # A pending order holds its selected voucher, without consuming another.
    assert [c["id"] for c in account(client)["coupons"]] == [default["id"]]
    client.post(f"/api/v1/payments/orders/{order['id']}/close")
    assert len(account(client)["coupons"]) == 2
    none = create(client, coupon=False).json()
    assert none["total_amount"] == 8800 and none["coupon_id"] is None


@pytest.mark.parametrize("invalid", ["foreign", "expired", "reserved", "used", "missing", "expiring"])
def test_explicit_unavailable_coupon_never_substitutes_weekly(payment_app, invalid):
    client, database, _ = payment_app
    default = account(client)["coupon"]
    selected_id = str(uuid.uuid4())
    with database.session() as session:
        user_id = session.get(WeeklyCoupon, default["id"]).user_id
        if invalid == "foreign":
            user_id = str(uuid.uuid4())
            session.add(UserRecord(id=user_id, status="active"))
            session.flush()
        if invalid != "missing":
            session.add(WeeklyCoupon(id=selected_id, user_id=user_id, amount=8800,
                expires_at=NOW + (timedelta(seconds=90) if invalid == "expiring" else
                                  timedelta(days=-1 if invalid == "expired" else 7)),
                reserved_order_id="held" if invalid == "reserved" else None,
                redeemed_order_id="paid" if invalid == "used" else None))
        session.commit()
    result = client.post("/api/v1/payments/orders", json={"product_code": "single",
        "use_coupon": True, "coupon_id": selected_id, "idempotency_key": uuid.uuid4().hex})
    assert result.status_code == 409, result.text
    assert result.json()["error"]["code"] == ("coupon_expiring" if invalid == "expiring" else "coupon_unavailable")
    with database.session() as session:
        assert session.scalar(select(func.count(PaymentOrder.id))) == 0
        assert session.get(WeeklyCoupon, default["id"]).reserved_order_id is None


def test_coupon_selection_request_validation(payment_app):
    client, _, _ = payment_app
    payload = {"product_code": "single", "use_coupon": False,
               "coupon_id": account(client)["coupon"]["id"], "idempotency_key": uuid.uuid4().hex}
    assert client.post("/api/v1/payments/orders", json=payload).status_code == 422
    for bad in ("", "x" * 37, "invalid/identifier"):
        assert client.post("/api/v1/payments/orders", json={**payload, "use_coupon": True, "coupon_id": bad}).status_code == 422


def transaction(order: PaymentOrder):
    return {
        "appid": order.app_id,
        "mchid": order.mchid,
        "out_trade_no": order.id,
        "transaction_id": "wx-" + order.id,
        "trade_state": "SUCCESS",
        "amount": {"total": order.total_amount, "currency": "CNY", "payer_total": 1},
        "payer": {"openid": order.payer_openid},
        "success_time": iso(NOW),
    }


def chart_payload(hour="09:30"):
    return {"gender": "female", "birth_local_datetime": f"1992-08-18T{hour}", "location_id": 3101}


@pytest.mark.parametrize(
    "before,start,end",
    [
        ("2026-10-18T23:59:59", "2026-10-12T00:00:00", "2026-10-19T00:00:00"),
        ("2026-10-19T00:00:00", "2026-10-19T00:00:00", "2026-10-26T00:00:00"),
        ("2026-10-25T23:59:59", "2026-10-19T00:00:00", "2026-10-26T00:00:00"),
    ],
)
def test_monday_0800_beijing_boundary(before, start, end):
    assert week_window(datetime.fromisoformat(before)) == (
        datetime.fromisoformat(start),
        datetime.fromisoformat(end),
    )


def test_new_user_immediate_coupon_weekly_idempotency_and_no_expiring_cards(
    payment_app, monkeypatch
):
    client, database, _ = payment_app
    with database.session() as session:
        assert session.scalar(select(func.count(WeeklyCoupon.id))) == 1  # Issued during login.
    assert account(client)["coupon"]["expires_at"] == "2026-10-26T00:00:00+00:00"
    issue_current_week(database)
    issue_current_week(database)
    order = create(client).json()
    client.post(f"/api/v1/payments/orders/{order['id']}/mock-confirm")
    next_week = datetime(2026, 10, 26)
    monkeypatch.setattr("app.services.payments.now_utc", lambda: next_week)
    monkeypatch.setattr("app.coupon_scheduler.now_utc", lambda: next_week)
    issue_current_week(database)
    result = account(client)
    assert result["balance"] == 1
    assert result["coupon"]["status"] == "available"
    assert result["coupon"]["expires_at"] == "2026-11-02T00:00:00+00:00"
    with database.session() as session:
        assert session.scalar(select(func.count(WeeklyCoupon.id))) == 2


@pytest.mark.parametrize(
    "product,cards,price,discounted",
    [
        ("single", 1, 8800, 3800),
        ("double", 2, 15800, 10800),
        ("family", 5, 22800, 17800),
    ],
)
def test_server_prices_discount_and_grant_once(payment_app, product, cards, price, discounted):
    client, database, _ = payment_app
    response = create(client, product)
    assert response.status_code == 201
    order = response.json()
    assert (order["cards"], order["original_amount"], order["total_amount"]) == (
        cards,
        price,
        discounted,
    )
    assert account(client)["balance"] == 0
    assert account(client)["coupon"]["status"] == "reserved"
    prepay = client.post(f"/api/v1/payments/orders/{order['id']}/prepay")
    assert prepay.json() == {"mode": "mock", "parameters": None}
    for _ in range(3):
        assert client.post(f"/api/v1/payments/orders/{order['id']}/mock-confirm").status_code == 200
    assert account(client)["balance"] == cards
    assert account(client)["coupon"]["status"] == "used"
    with database.session() as session:
        assert session.scalar(select(func.count(CardLedger.id))) == 1


def test_coupon_reuse_idempotency_and_price_tampering(payment_app):
    client, _, _ = payment_app
    key = uuid.uuid4().hex
    order = create(client, key=key).json()
    assert create(client, key=key).json()["id"] == order["id"]
    assert create(client, "family", key=key).status_code == 409
    assert create(client).status_code == 409
    forged = client.post(
        "/api/v1/payments/orders",
        json={
            "product_code": "family",
            "use_coupon": True,
            "idempotency_key": key,
            "total_amount": 1,
        },
    )
    assert forged.status_code == 422
    closed = client.post(f"/api/v1/payments/orders/{order['id']}/close")
    assert closed.json()["status"] == "closed"
    assert account(client)["coupon"]["status"] == "available"
    assert client.post(f"/api/v1/payments/orders/{order['id']}/mock-confirm").status_code == 409
    second = create(client, "family").json()
    client.post(f"/api/v1/payments/orders/{second['id']}/mock-confirm")
    assert create(client, coupon=True).status_code == 409
    assert create(client, coupon=False).json()["total_amount"] == 8800


def test_report_dedup_retry_and_insufficient_rollback(payment_app):
    client, database, _ = payment_app
    assert client.post("/api/v1/charts", json=chart_payload()).status_code == 200
    assert client.post("/api/v1/analyses", json=chart_payload()).status_code == 402
    with database.session() as session:
        assert session.scalar(select(func.count(AnalysisJobRecord.id))) == 0
    order = create(client).json()
    client.post(f"/api/v1/payments/orders/{order['id']}/mock-confirm")
    first = client.post("/api/v1/analyses", json=chart_payload())
    assert first.status_code == 202
    assert account(client)["balance"] == 0
    duplicate = client.post("/api/v1/analyses", json=chart_payload())
    assert duplicate.json()["deduplicated"] is True
    # Calendar changes only affect presentation, including for existing legacy reports.
    lunar = client.post("/api/v1/analyses", json={**chart_payload(), "birth_calendar": "lunar"})
    assert lunar.status_code == 202
    assert lunar.json()["job_id"] == first.json()["job_id"]
    assert lunar.json()["deduplicated"] is True
    restored = client.get(f"/api/v1/analyses/{lunar.json()['job_id']}")
    assert restored.json()["chart"]["request"]["birth_calendar"] == "lunar"
    assert account(client)["balance"] == 0
    solar = client.post("/api/v1/analyses", json={**chart_payload(), "birth_calendar": "solar"})
    assert solar.json()["job_id"] == first.json()["job_id"]
    restored = client.get(f"/api/v1/analyses/{solar.json()['job_id']}").json()
    assert restored["chart"]["request"]["birth_calendar"] == "solar"
    assert client.post("/api/v1/analyses", json=chart_payload("12:00")).status_code == 402
    job_id = first.json()["job_id"]
    client.post(f"/api/v1/analyses/{job_id}/cancel")
    with database.session() as session:
        job = session.get(AnalysisJobRecord, job_id)
        section_code = job.sections[0].code
    assert (
        client.post(f"/api/v1/analyses/{job_id}/sections/{section_code}/retry").status_code == 202
    )
    with database.session() as session:
        assert session.scalar(select(func.count(CardLedger.id))) == 2  # purchase + one debit
        assert session.scalar(select(func.count(AnalysisJobRecord.id))) == 1


def test_deleting_report_does_not_refund_or_erase_ledger(payment_app):
    client, database, _ = payment_app
    order = create(client).json()
    client.post(f"/api/v1/payments/orders/{order['id']}/mock-confirm")
    accepted = client.post("/api/v1/analyses", json=chart_payload()).json()
    client.post(f"/api/v1/analyses/{accepted['job_id']}/cancel")
    assert client.delete(f"/api/v1/analyses/{accepted['job_id']}").status_code == 204
    assert client.post("/api/v1/analyses", json=chart_payload()).status_code == 402
    with database.session() as session:
        assert session.scalar(select(func.count(CardLedger.id))) == 2


@pytest.mark.parametrize(
    "field,value",
    [
        ("appid", "foreign-app"),
        ("mchid", "foreign-merchant"),
        ("trade_state", "NOTPAY"),
        ("out_trade_no", "unknown-order"),
        ("payer", {"openid": "someone-else"}),
        ("amount", {"total": 1, "currency": "CNY"}),
        ("amount", {"total": 3800, "currency": "USD"}),
        ("amount", {"total": "3800", "currency": "CNY"}),
        ("transaction_id", ""),
        ("success_time", "invalid"),
    ],
)
def test_transaction_mismatch_never_credits(payment_app, field, value):
    client, database, service = payment_app
    created = create(client).json()
    with database.session() as session:
        event = transaction(session.get(PaymentOrder, created["id"]))
    event[field] = value
    with pytest.raises(PaymentError):
        service.receive(event)
    assert account(client)["balance"] == 0
    assert account(client)["coupon"]["status"] == "reserved"


def test_late_success_and_duplicate_notification(payment_app, monkeypatch):
    client, database, service = payment_app
    created = create(client).json()
    with database.session() as session:
        event = transaction(session.get(PaymentOrder, created["id"]))
    monkeypatch.setattr("app.services.payments.now_utc", lambda: NOW + timedelta(days=3))
    service.receive(event)
    service.receive(event)
    assert account(client)["balance"] == 1
    altered = copy.deepcopy(event)
    altered["transaction_id"] = "different-transaction"
    with pytest.raises(PaymentError):
        service.receive(altered)


def test_orders_private_and_login_required_even_if_legacy_flag_false(payment_app):
    client, _, service = payment_app
    created = create(client).json()
    other, _ = app.state.auth_service.login_wechat_user(WechatProfile(openid="other-user"))
    for operation in [service.prepay, service.refresh, service.mock_confirm]:
        with pytest.raises(PaymentError) as rejected:
            operation(other.id, created["id"])
        assert rejected.value.status_code == 404
    assert (
        client.post(
            f"/api/v1/payments/orders/{created['id']}/close",
            headers={"Origin": "https://evil.example"},
        ).status_code
        == 403
    )
    assert (
        client.get("/api/v1/payments/account", headers={"Host": "public.example"}).status_code
        == 403
    )
    client.cookies.clear()
    assert client.get("/api/v1/payments/account").status_code == 401
    assert client.post("/api/v1/analyses", json=chart_payload()).status_code == 401


def test_coupon_near_expiry_cannot_cross_boundary(payment_app, monkeypatch):
    client, _, _ = payment_app
    monkeypatch.setattr("app.services.payments.now_utc", lambda: datetime(2026, 10, 25, 23, 59))
    result = create(client)
    assert result.status_code == 409
    assert result.json()["error"]["code"] == "coupon_expiring"
    assert create(client, coupon=False).status_code == 201


def test_mock_and_live_configuration_fail_closed():
    with pytest.raises(ValueError):
        PaymentSettings(mode="mock").validate(AuthSettings())
    with pytest.raises(ValueError):
        PaymentSettings(mode="mock").validate(
            AuthSettings(mode="mock", callback_url="https://public.example/callback")
        )
    with pytest.raises(ValueError):
        PaymentSettings(mode="live").validate(AuthSettings(mode="live"))
    PaymentSettings().validate(AuthSettings())


def test_query_success_fallback_and_network_failure_keeps_coupon(payment_app):
    client, database, service = payment_app
    created = create(client).json()
    with database.session() as session:
        order = session.get(PaymentOrder, created["id"])
        order.provider_started = True
        session.commit()
        event = transaction(order)

    class QueryClient:
        broken = True

        def request(self, method, path, payload=None):
            assert method == "GET"
            if self.broken:
                raise PaymentError(502, "payment_unavailable", "network")
            return event

    fake = QueryClient()
    service.client = fake
    with pytest.raises(PaymentError):
        service.refresh(order.user_id, order.id, close=True)
    assert account(client)["coupon"]["status"] == "reserved"
    fake.broken = False
    service.refresh(order.user_id, order.id)
    assert account(client)["balance"] == 1
    service.settings = replace(service.settings, mode="live")
    with pytest.raises(PaymentError):
        service.mock_confirm(order.user_id, order.id)


def test_old_users_get_only_current_coupon_and_disabled_users_skipped(payment_app):
    client, database, _ = payment_app
    with database.session() as session:
        session.add_all(
            [
                UserRecord(id=str(uuid.uuid4()), status="active"),
                UserRecord(id=str(uuid.uuid4()), status="disabled"),
            ]
        )
        session.commit()
    assert issue_current_week(database) == 2
    with database.session() as session:
        assert session.scalar(select(func.count(WeeklyCoupon.id))) == 2
        assert session.scalar(select(func.count(CardWallet.user_id))) == 2


def test_defaults_disabled_without_changing_legacy_usage(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("BAZI_DATABASE_URL", raising=False)
    monkeypatch.delenv("BAZI_PAY_MODE", raising=False)
    monkeypatch.setenv("BAZI_WECHAT_AUTH_MODE", "disabled")
    with TestClient(app) as client:
        assert client.get("/api/v1/auth/me").json()["payments_enabled"] is False
        assert client.get("/api/v1/payments/account").status_code == 503
        assert client.post("/api/v1/charts", json=chart_payload()).status_code == 200


@pytest.mark.parametrize(
    ("product", "cards", "name", "amount"),
    [
        ("single", 1, "单次八字精批卡", 3800),
        ("double", 2, "双人八字精批卡", 10800),
        ("family", 5, "全家福八字精批卡", 17800),
    ],
)
def test_wechat_bill_description_uses_order_card_count(payment_app, product, cards, name, amount):
    client, database, service = payment_app
    created = create(client, product).json()
    assert created["product_name"] == name

    class FakeClient:
        calls = 0

        def request(self, method, path, payload=None):
            self.calls += 1
            assert (method, path) == ("POST", "/v3/pay/transactions/jsapi")
            assert payload["description"] == f"解读卡*{cards}张"
            assert payload["amount"] == {"total": amount, "currency": "CNY"}
            assert payload["out_trade_no"] == created["id"]
            return {"prepay_id": "test-bill-description"}

        def jsapi_parameters(self, prepay_id):
            return {"package": "prepay_id=" + prepay_id}

    fake = FakeClient()
    service.client = fake
    with database.session() as session:
        order = session.get(PaymentOrder, created["id"])
        user_id = order.user_id
    service.prepay(user_id, created["id"])
    service.prepay(user_id, created["id"])
    assert fake.calls == 1
    with database.session() as session:
        order = session.get(PaymentOrder, created["id"])
        assert order.product_name == name
        assert order.cards == cards
        assert order.total_amount == amount
    assert account(client)["balance"] == 0


def test_live_prepay_price_snapshot_cache_and_uncertain_failure(payment_app):
    client, database, service = payment_app
    created = create(client, "double").json()

    class FakeClient:
        broken = True
        calls = 0

        def request(self, method, path, payload=None):
            self.calls += 1
            assert payload["amount"] == {"total": 10800, "currency": "CNY"}
            assert payload["out_trade_no"] == created["id"]
            if self.broken:
                raise PaymentError(502, "payment_unavailable", "network")
            return {"prepay_id": "safe-prepay"}

        def jsapi_parameters(self, prepay_id):
            return {"package": "prepay_id=" + prepay_id}

    fake = FakeClient()
    service.client = fake
    with database.session() as session:
        user_id = session.get(PaymentOrder, created["id"]).user_id
    with pytest.raises(PaymentError):
        service.prepay(user_id, created["id"])
    with database.session() as session:
        assert session.get(PaymentOrder, created["id"]).provider_started is True
    assert account(client)["coupon"]["status"] == "reserved"
    fake.broken = False
    # Changing prices affects new orders only, not the original 108-yuan order.
    service.settings = replace(service.settings, double_price=16800)
    assert (
        service.prepay(user_id, created["id"])["parameters"]["package"] == "prepay_id=safe-prepay"
    )
    assert (
        service.prepay(user_id, created["id"])["parameters"]["package"] == "prepay_id=safe-prepay"
    )
    assert fake.calls == 2  # One failed attempt, one accepted attempt; cached thereafter.


def test_signed_close_result_releases_coupon_but_unconfirmed_does_not(payment_app):
    client, database, service = payment_app
    created = create(client).json()
    with database.session() as session:
        record = session.get(PaymentOrder, created["id"])
        record.provider_started = True
        session.commit()
        event = transaction(record)
        event["trade_state"] = "NOTPAY"

    class ClosingClient:
        calls = []

        def request(self, method, path, payload=None):
            self.calls.append(method)
            return event if method == "GET" else {}

    fake = ClosingClient()
    service.client = fake
    assert service.refresh(record.user_id, record.id)["status"] == "pending"
    assert account(client)["coupon"]["status"] == "reserved"
    assert service.refresh(record.user_id, record.id, close=True)["status"] == "closed"
    assert fake.calls == ["GET", "GET", "POST"]
    assert account(client)["coupon"]["status"] == "available"


def test_pausing_new_orders_keeps_existing_payment_and_cards_working(payment_app):
    client, _, service = payment_app
    created = create(client).json()
    service.settings = replace(service.settings, accept_new_orders=False)
    assert account(client)["accept_new_orders"] is False
    assert create(client).status_code == 503
    assert client.post(f"/api/v1/payments/orders/{created['id']}/mock-confirm").status_code == 200
    assert account(client)["balance"] == 1
    assert client.post("/api/v1/analyses", json=chart_payload()).status_code == 202


def test_query_of_unpaid_order_can_omit_optional_amount_fields(payment_app):
    client, database, service = payment_app
    created = create(client).json()
    with database.session() as session:
        record = session.get(PaymentOrder, created["id"])
        record.provider_started = True
        session.commit()
        query = {
            "appid": record.app_id,
            "mchid": record.mchid,
            "out_trade_no": record.id,
            "trade_state": "CLOSED",
        }

    class MinimalQueryClient:
        def request(self, method, path, payload=None):
            return query

    service.client = MinimalQueryClient()
    assert service.refresh(record.user_id, record.id)["status"] == "closed"
    assert account(client)["coupon"]["status"] == "available"
    assert account(client)["balance"] == 0


def test_sunday_registration_does_not_get_seven_days_from_signup(payment_app, monkeypatch):
    _, database, _ = payment_app
    monkeypatch.setattr("app.services.auth.utcnow_naive", lambda: datetime(2026, 10, 25, 15, 59))
    user, _ = app.state.auth_service.login_wechat_user(WechatProfile(openid="sunday-new-user"))
    with database.session() as session:
        coupon = session.scalar(select(WeeklyCoupon).where(WeeklyCoupon.user_id == user.id))
        assert coupon.expires_at == datetime(2026, 10, 26)


def test_financial_credit_is_not_lost_if_account_was_disabled(payment_app):
    client, database, service = payment_app
    created = create(client).json()
    with database.session() as session:
        record = session.get(PaymentOrder, created["id"])
        event = transaction(record)
        session.get(UserRecord, record.user_id).status = "disabled"
        session.commit()
    service.receive(event)
    with database.session() as session:
        assert session.get(CardWallet, record.user_id).balance == 1
