"""New-review rating policy, atomic awards and administrator override precedence."""

# ruff: noqa: F811
from datetime import timedelta

import pytest
from sqlalchemy import event, func, select
from test_payments import payment_app  # noqa: F401
from test_reviews import payload, ready

from app.commerce_models import ReportReview, ReviewModeration, WeeklyCoupon
from app.services.reviews import AUTO_APPROVAL_OPERATOR, ReviewService


@pytest.mark.parametrize("rating", [1, 2, 3, 4, 5])
def test_new_rating_controls_publication_only_and_awards_once(payment_app, rating):
    client, db, _ = payment_app
    uid = client.get("/api/v1/auth/me").json()["user"]["id"]
    job = ready(db, uid)
    request = {**payload(job), "rating": rating}
    submitted = client.post("/api/v1/reviews", json=request)
    assert submitted.status_code == 200
    result = submitted.json()
    expected = "approved" if rating >= 4 else "pending"
    assert result["review"]["status"] == expected
    assert result["gift_amount"] == 5000 and not result["replayed"]
    rid = result["review"]["id"]
    public = client.get("/api/v1/reviews").json()
    assert public["total"] == (1 if rating >= 4 else 0)
    if rating >= 4:
        assert public["items"][0]["id"] == rid
        assert "status" not in public["items"][0]
    assert client.post("/api/v1/reviews", json=request).json()["replayed"]
    with db.session() as session:
        review = session.get(ReportReview, rid)
        assert review.moderated_by == (AUTO_APPROVAL_OPERATOR if rating >= 4 else None)
        assert (
            (review.moderated_at == review.created_at)
            if rating >= 4
            else review.moderated_at is None
        )
        audits = session.scalars(
            select(ReviewModeration).where(ReviewModeration.review_id == rid)
        ).all()
        assert len(audits) == (1 if rating >= 4 else 0)
        if audits:
            assert audits[0].previous_status == "pending"
            assert audits[0].status == "approved" and audits[0].operator == AUTO_APPROVAL_OPERATOR
        gifts = session.scalars(
            select(WeeklyCoupon).where(WeeklyCoupon.source_review_id == rid)
        ).all()
        assert len(gifts) == 1 and gifts[0].amount == 5000
        assert gifts[0].expires_at - review.created_at == timedelta(days=7)


@pytest.mark.parametrize("rating", [4, 5])
def test_manual_hide_wins_over_submission_replay(payment_app, rating):
    client, db, _ = payment_app
    uid = client.get("/api/v1/auth/me").json()["user"]["id"]
    request = {**payload(ready(db, uid)), "rating": rating}
    svc = ReviewService(db)
    rid = svc.submit(uid, **request)["review"]["id"]
    svc.moderate(rid, "hidden", "owner")
    replay = svc.submit(uid, **request)
    assert replay["replayed"] and replay["review"]["status"] == "hidden"
    assert svc.listing(1)["total"] == 0
    with db.session() as session:
        assert session.get(ReportReview, rid).moderated_by == "owner"
        assert (
            session.scalar(
                select(func.count())
                .select_from(ReviewModeration)
                .where(ReviewModeration.review_id == rid)
            )
            == 2
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(WeeklyCoupon)
                .where(WeeklyCoupon.source_review_id == rid)
            )
            == 1
        )
    svc.moderate(rid, "approved", "owner")
    assert svc.listing(1)["total"] == 1


def test_old_pending_high_rating_is_not_reapproved_by_retry(payment_app):
    client, db, _ = payment_app
    uid = client.get("/api/v1/auth/me").json()["user"]["id"]
    job = ready(db, uid)
    svc = ReviewService(db)
    rid = svc.submit(uid, **payload(job))["review"]["id"]
    with db.session() as session:
        session.get(ReportReview, rid).rating = 5
        session.commit()
    assert svc.submit(uid, **{**payload(job), "rating": 5})["review"]["status"] == "pending"
    assert svc.listing(1)["total"] == 0


@pytest.mark.parametrize("failing_model", [WeeklyCoupon, ReviewModeration])
def test_auto_approval_and_gift_rollback_together(payment_app, failing_model):
    client, db, _ = payment_app
    uid = client.get("/api/v1/auth/me").json()["user"]["id"]
    job = ready(db, uid)
    request = {**payload(job), "rating": 5}

    def fail(*_):
        raise RuntimeError("synthetic insert failure")

    event.listen(failing_model, "before_insert", fail)
    try:
        with pytest.raises(RuntimeError):
            ReviewService(db).submit(uid, **request)
    finally:
        event.remove(failing_model, "before_insert", fail)
    with db.session() as session:
        assert session.scalar(select(ReportReview).where(ReportReview.job_id == job)) is None
        assert session.scalar(select(func.count()).select_from(ReviewModeration)) == 0
        assert (
            session.scalar(
                select(func.count())
                .select_from(WeeklyCoupon)
                .where(WeeklyCoupon.source_review_id.is_not(None))
            )
            == 0
        )
    assert ReviewService(db).submit(uid, **request)["review"]["status"] == "approved"
