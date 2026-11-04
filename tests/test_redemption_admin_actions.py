# ruff: noqa: F811
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import event, func, select
from test_payments import payment_app  # noqa: F401
from test_redemptions import codes, generate  # noqa: F401

from app.api.admin import require_admin
from app.commerce_models import CardLedger, CardWallet, RedemptionCode, WeeklyCoupon
from app.main import app
from app.services.cards import PaymentError
from app.services.redemptions import code_digest


def ids(service, batch):
    return [row["id"] for row in service.listing(batch_id=batch["batch"]["id"])["items"]]


def test_bulk_disable_is_atomic_and_repeat_safe(codes):
    _, db, _, service, user = codes
    batch = generate(service, quantity=3)
    selected = ids(service, batch)
    service.redeem(user, batch["codes"][0])
    with pytest.raises(PaymentError):
        service.bulk_disable(selected, "owner")
    assert service.listing(status="unused")["total"] == 2
    unused = [row["id"] for row in service.listing(status="unused")["items"]]
    assert service.bulk_disable(unused, "owner")["changed"] == 2
    assert service.bulk_disable(unused + unused, "other")["changed"] == 0
    with db.session() as s:
        assert all(s.get(RedemptionCode, cid).disabled_by == "owner" for cid in unused)
        assert s.get(CardWallet, user).balance == 2


def test_delete_only_terminal_codes_preserves_grants_and_retry_receipts(codes):
    _, db, _, service, user = codes
    cards = generate(service)
    coupon = generate(service, kind="coupon", value=8800)
    disabled = generate(service)
    service.redeem(user, cards["codes"][0])
    receipt = service.redeem(user, coupon["codes"][0])
    disabled_id = ids(service, disabled)[0]
    service.disable(disabled_id, "owner")
    selected = ids(service, cards) + ids(service, coupon) + [disabled_id]
    assert service.bulk_delete(selected, "owner")["changed"] == 3
    assert service.bulk_delete(selected, "other")["changed"] == 0
    assert service.listing()["total"] == 0
    assert service.redeem(user, cards["codes"][0])["already_redeemed"]
    assert (
        service.redeem(user, coupon["codes"][0])["coupon_expires_at"]
        == receipt["coupon_expires_at"]
    )
    with pytest.raises(PaymentError):
        service.redeem(user, disabled["codes"][0])
    with db.session() as s:
        assert s.get(CardWallet, user).balance == 2
        assert (
            s.scalar(select(func.count()).select_from(CardLedger).where(CardLedger.user_id == user))
            == 1
        )
        assert (
            s.scalar(select(WeeklyCoupon).where(WeeklyCoupon.source_code_id.in_(selected))).amount
            == 8800
        )
        assert all(s.get(RedemptionCode, cid).deleted_by == "owner" for cid in selected)
        assert (
            s.scalar(
                select(RedemptionCode).where(
                    RedemptionCode.code_hash == code_digest(cards["codes"][0])
                )
            )
            is not None
        )


def test_mixed_invalid_deletion_and_expired_codes_leave_all_rows_unchanged(codes, monkeypatch):
    _, db, _, service, _ = codes
    batch = generate(service, quantity=2)
    selected = ids(service, batch)
    service.disable(selected[0], "owner")
    with pytest.raises(PaymentError):
        service.bulk_delete(selected, "owner")
    assert service.listing()["total"] == 2
    with db.session() as s:
        code = s.get(RedemptionCode, selected[1])
        from app.commerce_models import RedemptionBatch

        expired = s.get(RedemptionBatch, code.batch_id).expires_at + timedelta(days=1)
    monkeypatch.setattr("app.services.redemptions.now_utc", lambda: expired)
    with pytest.raises(PaymentError):
        service.bulk_disable([selected[1]], "owner")
    with pytest.raises(PaymentError):
        service.bulk_delete([selected[1]], "owner")
    for values in ([], ["invalid"], ["f" * 32] * 1001):
        with pytest.raises(PaymentError):
            service.bulk_delete(values, "owner")


def test_deletion_write_failure_rolls_back(codes):
    _, db, _, service, _ = codes
    batch = generate(service, quantity=2)
    selected = ids(service, batch)
    service.bulk_disable(selected, "owner")

    def fail(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("UPDATE redemption_codes SET deleted_at"):
            raise RuntimeError("synthetic write failure")

    event.listen(db.engine, "before_cursor_execute", fail)
    try:
        with pytest.raises(RuntimeError):
            service.bulk_delete(selected, "owner")
    finally:
        event.remove(db.engine, "before_cursor_execute", fail)
    assert service.listing()["total"] == 2


def test_bulk_endpoints_enforce_admin_origin_and_input(codes):
    client, _, _, service, _ = codes
    batch = generate(service, quantity=2)
    selected = ids(service, batch)
    url = "/api/v1/admin/redemptions/bulk-disable"
    assert client.post(url, json={"code_ids": selected}).status_code in {401, 503}
    fake = SimpleNamespace(
        settings=SimpleNamespace(username="owner", public_origin="http://testserver")
    )
    app.dependency_overrides[require_admin] = lambda: fake
    try:
        assert (
            client.post(
                url, json={"code_ids": selected}, headers={"Origin": "https://evil.example"}
            ).status_code
            == 403
        )
        headers = {"Origin": "http://testserver"}
        assert client.post(url, json={"code_ids": []}, headers=headers).status_code == 422
        assert client.post(url, json={"code_ids": selected}, headers=headers).json()["changed"] == 2
        assert (
            client.post(
                "/api/v1/admin/redemptions/bulk-delete",
                json={"code_ids": selected},
                headers=headers,
            ).json()["changed"]
            == 2
        )
    finally:
        app.dependency_overrides.pop(require_admin)


def test_migration_retains_existing_codes_and_removal_audit(tmp_path, monkeypatch):
    from datetime import datetime

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import MetaData, Table, create_engine

    from app.database import Database
    from app.services.redemptions import RedemptionService

    url = f"sqlite+pysqlite:///{(tmp_path / 'admin-code-upgrade.sqlite3').as_posix()}"
    monkeypatch.setenv("BAZI_DATABASE_URL", url)
    config = Config("alembic.ini")
    command.upgrade(config, "20261102_0009")
    engine = create_engine(url)
    meta = MetaData()
    batches = Table("redemption_batches", meta, autoload_with=engine)
    records = Table("redemption_codes", meta, autoload_with=engine)
    code_id = "a" * 32
    now = datetime(2026, 11, 3)
    with engine.begin() as connection:
        connection.execute(
            batches.insert().values(
                id="b" * 32,
                request_key="c" * 32,
                label="已有批次",
                kind="cards",
                value=1,
                quantity=1,
                operator="owner",
                created_at=now,
                expires_at=now + timedelta(days=30),
            )
        )
        connection.execute(
            records.insert().values(
                id=code_id,
                batch_id="b" * 32,
                code_hash="d" * 64,
                suffix="ABCD",
                disabled_at=now,
                disabled_by="owner",
            )
        )
    engine.dispose()
    command.upgrade(config, "20261103_0010")
    database = Database(url)
    try:
        service = RedemptionService(database)
        assert service.listing()["total"] == 1
        assert service.bulk_delete([code_id], "owner")["changed"] == 1
        assert service.listing()["total"] == 0
        with database.session() as session:
            assert session.get(RedemptionCode, code_id).code_hash == "d" * 64
        with pytest.raises(RuntimeError, match="preserve the removal audit"):
            command.downgrade(config, "20261102_0009")
    finally:
        database.dispose()
