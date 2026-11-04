"""Run ONLY through the restricted server test harness; no merchant/model calls."""

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.engine import make_url
from test_reviews import payload, ready

from app.commerce_models import ReportReview, ReviewModeration, WeeklyCoupon
from app.database import Database
from app.models import ChartRecord, UserRecord
from app.services.reviews import ReviewService


@pytest.fixture
def isolated():
    url = os.environ.get("BAZI_TEST_MYSQL_URL", "")
    if not url:
        pytest.skip("Restricted independent MySQL test database required")
    parsed = make_url(url)
    assert parsed.database == "bazi_payment_test" and parsed.username == "bazi_payment_tester"
    assert parsed.host == "bazi-preprod-mysql-1" and parsed.port == 3306
    db = Database(url)
    uid = str(uuid.uuid4())
    with db.session() as session:
        session.add(UserRecord(id=uid, display_name="测试专用", status="active"))
        session.commit()
    try:
        yield db, uid
    finally:
        try:
            with db.session() as session:
                # Review gifts intentionally survive report deletion in the product.
                # Test teardown must explicitly remove this fixture user's coupons
                # before deleting their parent user; never clear the whole table.
                session.execute(delete(WeeklyCoupon).where(WeeklyCoupon.user_id == uid))
                session.execute(delete(ChartRecord).where(ChartRecord.user_id == uid))
                session.execute(delete(UserRecord).where(UserRecord.id == uid))
                session.commit()
        finally:
            db.dispose()


def race(calls):
    barrier = Barrier(len(calls))

    def run(call):
        barrier.wait(timeout=15)
        return call()

    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        return list(pool.map(run, calls))


@pytest.mark.parametrize("rating", [3, 4, 5])
def test_eight_duplicate_submissions_gift_once(isolated, rating):
    db, uid = isolated
    svc = ReviewService(db)
    job = ready(db, uid)
    request = {**payload(job), "rating": rating}
    results = race([lambda: svc.submit(uid, **request) for _ in range(8)])
    ids = {r["review"]["id"] for r in results}
    assert len(ids) == 1 and sum(not r["replayed"] for r in results) == 1
    rid = next(iter(ids))
    assert {result["review"]["status"] for result in results} == {
        "approved" if rating >= 4 else "pending"
    }
    with db.session() as s:
        assert (
            s.scalar(
                select(func.count()).select_from(ReportReview).where(ReportReview.job_id == job)
            )
            == 1
        )
        assert s.scalar(
            select(func.count())
            .select_from(ReviewModeration)
            .where(ReviewModeration.review_id == rid)
        ) == (1 if rating >= 4 else 0)
        assert (
            s.scalar(
                select(func.count())
                .select_from(WeeklyCoupon)
                .where(WeeklyCoupon.source_review_id == rid)
            )
            == 1
        )
    race([lambda: svc.moderate(rid, "approved", "test") for _ in range(8)])
    with db.session() as s:
        assert (
            s.scalar(
                select(func.count())
                .select_from(WeeklyCoupon)
                .where(WeeklyCoupon.source_review_id == rid)
            )
            == 1
        )
    race(
        [lambda: svc.submit(uid, **request) for _ in range(7)]
        + [lambda: svc.moderate(rid, "hidden", "owner")]
    )
    assert svc.submit(uid, **request)["review"]["status"] == "hidden"
    with db.session() as s:
        assert s.get(ReportReview, rid).moderated_by == "owner"
        assert (
            s.scalar(
                select(func.count())
                .select_from(ReviewModeration)
                .where(ReviewModeration.review_id == rid)
            )
            == 2
        )
        assert (
            s.scalar(
                select(func.count())
                .select_from(WeeklyCoupon)
                .where(WeeklyCoupon.source_review_id == rid)
            )
            == 1
        )


def test_independent_reports_each_gift_and_transaction_rollback(isolated):
    db, uid = isolated
    svc = ReviewService(db)
    jobs = [ready(db, uid) for _ in range(8)]
    results = race([lambda job=j: svc.submit(uid, **{**payload(job), "rating": 5}) for j in jobs])
    assert len({r["review"]["id"] for r in results}) == 8
    assert all(result["review"]["status"] == "approved" for result in results)
    with db.session() as s:
        assert (
            s.scalar(
                select(func.count()).select_from(WeeklyCoupon).where(WeeklyCoupon.user_id == uid)
            )
            == 8
        )
    # A failure during the gift insert must roll the review back too.
    from sqlalchemy import event

    def fail(*_):
        raise RuntimeError("synthetic gift insert failure")

    job = ready(db, uid)
    event.listen(WeeklyCoupon, "before_insert", fail)
    try:
        with pytest.raises(RuntimeError):
            svc.submit(uid, **{**payload(job), "rating": 5})
    finally:
        event.remove(WeeklyCoupon, "before_insert", fail)
    with db.session() as s:
        assert s.scalar(select(ReportReview).where(ReportReview.job_id == job)) is None
    assert not svc.submit(uid, **{**payload(job), "rating": 5})["replayed"]
