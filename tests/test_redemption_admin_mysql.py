"""Restricted test database only: bulk actions racing with redemption and each other."""

# ruff: noqa: F811
import pytest
from sqlalchemy import func, select
from test_redemptions_mysql import mysql_codes, race  # noqa: F401

from app.commerce_models import CardLedger, CardWallet, RedemptionCode
from app.services.cards import PaymentError


def batch_ids(db, batch):
    with db.session() as session:
        return list(
            session.scalars(
                select(RedemptionCode.id)
                .where(RedemptionCode.batch_id == batch["batch"]["id"])
                .order_by(RedemptionCode.id)
            )
        )


def test_bulk_disable_races_redemption_atomically(mysql_codes):
    db, service, users, generate, _ = mysql_codes
    batch = generate(quantity=3)
    selected = batch_ids(db, batch)

    def action(kind):
        try:
            return (
                service.bulk_disable(selected, "test")
                if kind == "disable"
                else service.redeem(users[0], batch["codes"][0])
            )
        except PaymentError as error:
            assert error.code in {"code_unavailable", "code_not_unused"}
            return None

    results = race(action, ["disable", "redeem"])
    assert sum(item is not None for item in results) == 1
    with db.session() as session:
        rows = session.scalars(select(RedemptionCode).where(RedemptionCode.id.in_(selected))).all()
        if results[0] is not None:
            assert all(row.disabled_at and not row.redeemed_by for row in rows)
        else:
            assert not any(row.disabled_at for row in rows)
            assert sum(bool(row.redeemed_by) for row in rows) == 1


def test_duplicate_bulk_removal_keeps_reward_receipt(mysql_codes):
    db, service, users, generate, _ = mysql_codes
    batch = generate()
    receipt = service.redeem(users[0], batch["codes"][0])
    selected = batch_ids(db, batch)
    results = race(lambda _: service.bulk_delete(selected, "test"), range(8))
    assert sum(result["changed"] for result in results) == 1
    assert service.redeem(users[0], batch["codes"][0])["already_redeemed"]
    with db.session() as session:
        assert session.get(CardWallet, users[0]).balance == receipt["value"]
        assert (
            session.scalar(
                select(func.count()).select_from(CardLedger).where(CardLedger.user_id == users[0])
            )
            == 1
        )
        assert session.get(RedemptionCode, selected[0]).deleted_at is not None


def test_mixed_removal_is_all_or_nothing(mysql_codes):
    db, service, _, generate, _ = mysql_codes
    batch = generate(quantity=3)
    selected = batch_ids(db, batch)
    service.bulk_disable(selected[:2], "test")
    with pytest.raises(PaymentError):
        service.bulk_delete(selected, "test")
    with db.session() as session:
        assert not any(session.get(RedemptionCode, item).deleted_at for item in selected)
    results = race(
        lambda ids: service.bulk_disable(ids, "test"), [selected, list(reversed(selected))]
    )
    assert sum(result["changed"] for result in results) == 1
    assert service.bulk_delete(selected, "test")["changed"] == 3
