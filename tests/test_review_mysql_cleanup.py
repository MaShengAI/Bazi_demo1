"""Exercise the actual MySQL test fixture's teardown with foreign keys enabled."""

import uuid

import pytest
import test_reviews_mysql as mysql_tests
from sqlalchemy import func, select, text
from test_reviews import payload, ready

from app.commerce_models import ReportReview, ReviewModeration, WeeklyCoupon
from app.database import Base, Database
from app.models import ChartRecord, UserRecord
from app.services.reviews import ReviewService


@pytest.mark.parametrize("reports", [1, 3])
def test_fixture_deletes_own_gifts_before_user_and_preserves_others(tmp_path, monkeypatch, reports):
    db = Database(f"sqlite+pysqlite:///{(tmp_path / 'cleanup.sqlite3').as_posix()}")
    Base.metadata.create_all(db.engine)
    with db.engine.connect() as connection:
        assert connection.scalar(text("PRAGMA foreign_keys")) == 1

    other = str(uuid.uuid4())
    with db.session() as session:
        session.add(UserRecord(id=other, display_name="保留的独立测试用户", status="active"))
        session.commit()
    service = ReviewService(db)
    other_job = ready(db, other)
    other_review = service.submit(other, **payload(other_job))["review"]["id"]
    service.moderate(other_review, "approved", "test")

    monkeypatch.setenv(
        "BAZI_TEST_MYSQL_URL",
        "mysql+pymysql://bazi_payment_tester:synthetic@bazi-preprod-mysql-1:3306/bazi_payment_test",
    )
    monkeypatch.setattr(mysql_tests, "Database", lambda _: db)
    fixture = mysql_tests.isolated.__wrapped__()
    fixture_db, uid = next(fixture)
    assert fixture_db is db and uid != other
    jobs = [ready(db, uid) for _ in range(reports)]
    review_ids = []
    for job in jobs:
        review_id = service.submit(uid, **payload(job))["review"]["id"]
        review_ids.append(review_id)
        service.moderate(review_id, "approved", "test")
    with pytest.raises(StopIteration):
        next(fixture)

    try:
        with db.session() as session:
            assert session.get(UserRecord, uid) is None
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(WeeklyCoupon)
                    .where(WeeklyCoupon.user_id == uid)
                )
                == 0
            )
            assert (
                session.scalar(
                    select(func.count()).select_from(ChartRecord).where(ChartRecord.user_id == uid)
                )
                == 0
            )
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(ReportReview)
                    .where(ReportReview.id.in_(review_ids))
                )
                == 0
            )
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(ReviewModeration)
                    .where(ReviewModeration.review_id.in_(review_ids))
                )
                == 0
            )
            assert session.get(UserRecord, other) is not None
            assert session.get(ReportReview, other_review).status == "approved"
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(WeeklyCoupon)
                    .where(WeeklyCoupon.user_id == other)
                )
                == 1
            )
    finally:
        db.dispose()
