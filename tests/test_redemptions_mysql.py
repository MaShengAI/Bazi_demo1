"""Opt-in MySQL row-lock tests: restricted test schema and synthetic users only."""

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pytest
from mysql_target import require_financial_test_database
from sqlalchemy import delete, func, select

from app.commerce_models import (
    CardLedger,
    CardWallet,
    RedemptionAttempt,
    RedemptionBatch,
    RedemptionCode,
    WeeklyCoupon,
)
from app.database import Database
from app.models import UserRecord
from app.services.cards import PaymentError
from app.services.redemptions import RedemptionService, code_digest


@pytest.fixture
def mysql_codes():
    url = os.getenv("BAZI_TEST_MYSQL_URL", "").strip()
    if not url:
        pytest.skip("BAZI_TEST_MYSQL_URL is not configured")
    require_financial_test_database(url)
    db = Database(url)
    users = [str(uuid.uuid4()) for _ in range(8)]
    keys = []
    with db.session() as s:
        s.add_all([UserRecord(id=u, status="active") for u in users])
        s.commit()
    service = RedemptionService(db)

    def generate(kind="cards", quantity=1):
        key = uuid.uuid4().hex
        keys.append(key)
        return service.generate(
            kind=kind,
            value=2 if kind == "cards" else 5000,
            quantity=quantity,
            label="isolated race fixture",
            request_key=key,
            operator="test",
        )

    try:
        yield db, service, users, generate, keys
    finally:
        # Delete only records created by this fixture; never clear whole tables.
        with db.session() as s:
            batches = select(RedemptionBatch.id).where(RedemptionBatch.request_key.in_(keys))
            for model in (CardLedger, CardWallet, WeeklyCoupon, RedemptionAttempt):
                s.execute(delete(model).where(model.user_id.in_(users)))
            s.execute(delete(RedemptionCode).where(RedemptionCode.batch_id.in_(batches)))
            s.execute(delete(RedemptionBatch).where(RedemptionBatch.request_key.in_(keys)))
            s.execute(delete(UserRecord).where(UserRecord.id.in_(users)))
            s.commit()
        db.dispose()


def race(function, values):
    barrier = Barrier(len(values))

    def run(value):
        barrier.wait(timeout=15)
        return function(value)

    with ThreadPoolExecutor(max_workers=len(values)) as pool:
        return list(pool.map(run, values))


@pytest.mark.parametrize("kind", ["cards", "coupon"])
def test_eight_accounts_race_one_code_grants_exactly_once(mysql_codes, kind):
    db, service, users, generate, _ = mysql_codes
    batch = generate(kind)

    def redeem(user):
        try:
            return service.redeem(user, batch["codes"][0])
        except PaymentError as exc:
            assert exc.code == "code_unavailable"
            return None

    results = race(redeem, users)
    assert sum(r is not None for r in results) == 1
    with db.session() as s:
        codes = s.scalars(
            select(RedemptionCode).where(RedemptionCode.batch_id == batch["batch"]["id"])
        ).all()
        assert len(codes) == 1 and codes[0].redeemed_by in users
        if kind == "cards":
            assert (
                s.scalar(select(func.count(CardLedger.id)).where(CardLedger.user_id.in_(users)))
                == 1
            )
            assert (
                s.scalar(select(func.sum(CardWallet.balance)).where(CardWallet.user_id.in_(users)))
                == 2
            )
        else:
            coupons = s.scalars(select(WeeklyCoupon).where(WeeklyCoupon.user_id.in_(users))).all()
            assert len(coupons) == 1 and coupons[0].amount == 5000
            assert coupons[0].source_code_id == codes[0].id
            assert coupons[0].expires_at - codes[0].redeemed_at == timedelta(days=7)
            assert coupons[0].period_start is None
            assert (
                s.scalar(select(func.count(CardLedger.id)).where(CardLedger.user_id.in_(users)))
                == 0
            )


@pytest.mark.parametrize("kind", ["cards", "coupon"])
def test_same_account_four_concurrent_retries_do_not_double_grant(mysql_codes, kind):
    db, service, users, generate, _ = mysql_codes
    batch = generate(kind)
    results = race(lambda _: service.redeem(users[0], batch["codes"][0]), list(range(4)))
    assert sorted(r["already_redeemed"] for r in results) == [False, True, True, True]
    with db.session() as s:
        if kind == "cards":
            assert s.get(CardWallet, users[0]).balance == 2
            assert (
                s.scalar(select(func.count(CardLedger.id)).where(CardLedger.user_id == users[0]))
                == 1
            )
        else:
            coupons = s.scalars(select(WeeklyCoupon).where(WeeklyCoupon.user_id == users[0])).all()
            assert len(coupons) == 1 and coupons[0].amount == 5000
            assert len({r["coupon_expires_at"] for r in results}) == 1


def test_four_different_codes_credit_same_wallet_without_lost_updates(mysql_codes):
    db, service, users, generate, _ = mysql_codes
    batch = generate(quantity=4)
    results = race(lambda code: service.redeem(users[0], code), batch["codes"])
    assert all(not r["already_redeemed"] for r in results)
    with db.session() as s:
        assert s.get(CardWallet, users[0]).balance == 8
        entries = s.scalars(select(CardLedger).where(CardLedger.user_id == users[0])).all()
        assert len(entries) == len({e.event_key for e in entries}) == 4
        assert sum(e.delta for e in entries) == 8


def test_disable_and_redeem_race_has_only_one_valid_winner(mysql_codes):
    db, service, users, generate, _ = mysql_codes
    batch = generate()
    with db.session() as s:
        code_id = s.scalar(
            select(RedemptionCode.id).where(
                RedemptionCode.code_hash == code_digest(batch["codes"][0])
            )
        )

    def operation(action):
        try:
            if action == "redeem":
                service.redeem(users[0], batch["codes"][0])
            else:
                service.disable(code_id, "test-admin")
            return action
        except PaymentError as exc:
            assert exc.code in {"code_unavailable", "code_not_unused"}
            return None

    result = race(operation, ["redeem", "disable"])
    assert sum(r is not None for r in result) == 1
    with db.session() as s:
        code = s.get(RedemptionCode, code_id)
        assert bool(code.disabled_at) != bool(code.redeemed_by)
        wallet = s.get(CardWallet, users[0])
        count = s.scalar(select(func.count(CardLedger.id)).where(CardLedger.user_id == users[0]))
        if code.redeemed_by:
            assert wallet.balance == 2 and count == 1
        else:
            assert wallet is None and count == 0 and code.disabled_by == "test-admin"


def test_duplicate_batch_requests_generate_only_one_batch(mysql_codes):
    db, service, _, _, keys = mysql_codes
    key = uuid.uuid4().hex
    keys.append(key)

    def generate(_):
        try:
            return service.generate(
                kind="cards",
                value=1,
                quantity=4,
                label="duplicate batch",
                request_key=key,
                operator="test",
            )
        except PaymentError as exc:
            assert exc.code in {"batch_conflict", "batch_already_created"}
            return None

    results = race(generate, list(range(4)))
    assert sum(r is not None for r in results) == 1
    with db.session() as s:
        batches = s.scalars(select(RedemptionBatch).where(RedemptionBatch.request_key == key)).all()
        assert len(batches) == 1
        assert (
            s.scalar(
                select(func.count(RedemptionCode.id)).where(
                    RedemptionCode.batch_id == batches[0].id
                )
            )
            == 4
        )
