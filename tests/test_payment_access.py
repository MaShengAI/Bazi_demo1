from __future__ import annotations

import uuid
from dataclasses import replace

import pytest
import test_payments
from sqlalchemy import func, select
from test_payments import account, create, transaction

from app.commerce_models import CardLedger, PaymentOrder, WeeklyCoupon
from app.config import AuthSettings
from app.payment_config import PaymentSettings
from app.services.cards import PaymentError

payment_app = test_payments.payment_app


def user_id(client):
    return client.get("/api/v1/auth/me").json()["user"]["id"]


def test_allowed_account_can_buy_and_credit_exactly_once(payment_app):
    client, database, service = payment_app
    uid = user_id(client)
    service.settings = replace(service.settings, allowed_user_ids=(uid,))
    assert account(client)["accept_new_orders"] is True
    created = create(client).json()
    assert created["total_amount"] == 3800 and created["cards"] == 1
    with database.session() as session:
        event = transaction(session.get(PaymentOrder, created["id"]))
    service.receive(event)
    service.receive(event)
    assert account(client)["balance"] == 1
    with database.session() as session:
        assert session.scalar(select(func.count(CardLedger.id))) == 1


def test_nonallowed_account_cannot_create_even_with_direct_request(payment_app):
    client, database, service = payment_app
    uid = user_id(client)
    service.settings = replace(service.settings, allowed_user_ids=(str(uuid.uuid4()),))
    response = create(client)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "purchases_paused"
    with pytest.raises(PaymentError):
        service.create(uid, "single", True, uuid.uuid4().hex)
    with database.session() as session:
        assert session.scalar(select(func.count(PaymentOrder.id))) == 0
        assert session.scalar(select(func.count(CardLedger.id))) == 0
        assert session.scalar(select(func.count(WeeklyCoupon.id))) == 1  # login only
        coupon = session.scalar(select(WeeklyCoupon))
        assert coupon.reserved_order_id is None and coupon.redeemed_order_id is None
    data = account(client)
    assert data["accept_new_orders"] is False
    assert "allowed_user_ids" not in data


def test_global_pause_wins_over_allowed_account(payment_app):
    client, _, service = payment_app
    service.settings = replace(service.settings, allowed_user_ids=(user_id(client),),
                               accept_new_orders=False)
    assert account(client)["accept_new_orders"] is False
    assert create(client).status_code == 503


def test_removing_account_does_not_block_existing_order_or_callback(payment_app):
    client, database, service = payment_app
    created = create(client).json()
    with database.session() as session:
        event = transaction(session.get(PaymentOrder, created["id"]))
    service.settings = replace(service.settings, allowed_user_ids=(str(uuid.uuid4()),),
                               accept_new_orders=False)
    assert client.post(f"/api/v1/payments/orders/{created['id']}/prepay").status_code == 200
    service.receive(event)
    service.receive(event)
    refreshed = client.post(f"/api/v1/payments/orders/{created['id']}/refresh")
    assert refreshed.json()["status"] == "paid"
    assert account(client)["balance"] == 1
    assert create(client).status_code == 503
    assert client.post(f"/api/v1/payments/orders/{created['id']}/close").json()["status"] == "paid"


def test_existing_unpaid_order_can_close_after_restriction(payment_app):
    client, _, service = payment_app
    created = create(client).json()
    service.settings = replace(service.settings, allowed_user_ids=(str(uuid.uuid4()),))
    closed = client.post(f"/api/v1/payments/orders/{created['id']}/close")
    assert closed.json()["status"] == "closed"
    assert account(client)["coupon"]["status"] == "available"


@pytest.mark.parametrize("raw", ["bad", "*", ",", str(uuid.uuid4()) + ",",
    "118A376D-C19B-4648-A121-F340A08F4347",
    "118a376d-c19b-4648-a121-f340a08f4347,118a376d-c19b-4648-a121-f340a08f4347"])
def test_invalid_access_configuration_fails_closed(monkeypatch, raw):
    monkeypatch.setenv("BAZI_PAY_ALLOWED_USER_IDS", raw)
    with pytest.raises(ValueError):
        PaymentSettings.from_env()


def test_access_configuration_and_pause(monkeypatch):
    uid = "118a376d-c19b-4648-a121-f340a08f4347"
    monkeypatch.setenv("BAZI_PAY_ALLOWED_USER_IDS", uid)
    settings = PaymentSettings.from_env()
    assert settings.allowed_user_ids == (uid,)
    assert settings.can_purchase(uid) and not settings.can_purchase(str(uuid.uuid4()))
    assert not replace(settings, accept_new_orders=False).can_purchase(uid)
    monkeypatch.delenv("BAZI_PAY_ALLOWED_USER_IDS")
    assert PaymentSettings.from_env().allowed_user_ids == ()
    with pytest.raises(ValueError):
        PaymentSettings(allowed_user_ids=("*",)).validate(AuthSettings())
