# ruff: noqa: F811
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import func, select
from test_payments import payment_app  # noqa: F401

from app.commerce_models import ReportReview, ReviewModeration, WeeklyCoupon
from app.models import AnalysisJobRecord, AnalysisSectionRecord, ChartRecord, UserRecord
from app.services.cards import PaymentError
from app.services.reviews import CONSENT_VERSION, ReviewService, graphemes


def ready(database, user_id, year=1999):
    with database.session() as s:
        chart = ChartRecord(
            id=str(uuid.uuid4()),
            user_id=user_id,
            request_json={
                "name": "秘密姓名",
                "gender": "female",
                "birth_local_datetime": f"{year}-06-01T12:30",
            },
            snapshot_json={
                "pillars": {
                    k: {"heavenly_stem": "甲", "pillar": "甲子"}
                    for k in ("year", "month", "day", "hour")
                },
                "location": {"province": "湖北省", "city": "秘密城市"},
            },
            snapshot_hash=uuid.uuid4().hex,
        )
        s.add(chart)
        s.flush()
        job = AnalysisJobRecord(
            id=str(uuid.uuid4()),
            chart_id=chart.id,
            status="completed",
            model_id="fake",
            provider="fake",
            prompt_version="test",
            rule_version={},
            request_hash=uuid.uuid4().hex,
        )
        s.add(job)
        s.flush()
        for i in range(8):
            s.add(
                AnalysisSectionRecord(
                    job_id=job.id,
                    code=str(i),
                    title=str(i),
                    position=i,
                    status="completed",
                    content="示例正文",
                    request_hash=uuid.uuid4().hex,
                )
            )
        s.commit()
        return job.id


def payload(job, **kw):
    return dict(
        job_id=job,
        rating=1,
        content="真实感受",
        consent=True,
        consent_version=CONSENT_VERSION,
        **kw,
    )


def test_review_consent_privacy_gift_and_moderation(payment_app):
    client, db, _ = payment_app
    uid = client.get("/api/v1/auth/me").json()["user"]["id"]
    with db.session() as s:
        user = s.get(UserRecord, uid)
        user.display_name = "👩🏽‍💻秘密昵称"
        s.commit()
    job = ready(db, uid)
    options = client.get("/api/v1/reviews/mine").json()
    assert options["items"][0]["profile"]["nickname"] == "👩🏽‍💻"
    assert options["items"][0]["profile"]["cohort"] == "95后"
    assert (
        client.post("/api/v1/reviews", json={**payload(job), "consent": False}).status_code == 422
    )
    assert (
        client.post(
            "/api/v1/reviews", json=payload(job), headers={"Origin": "https://evil.example"}
        ).status_code
        == 403
    )
    first = client.post("/api/v1/reviews", json=payload(job))
    assert first.status_code == 200, first.text
    rid = first.json()["review"]["id"]
    assert first.json()["review"]["face"] == "😞"
    assert client.get("/api/v1/reviews").json()["total"] == 0
    assert client.post("/api/v1/reviews", json=payload(job)).json()["replayed"]
    assert client.post("/api/v1/reviews", json={**payload(job), "rating": 5}).status_code == 409
    svc = ReviewService(db)
    svc.moderate(rid, "approved", "owner")
    public = client.get("/api/v1/reviews")
    assert public.json()["total"] == 1
    assert "no-store" in public.headers["cache-control"]
    assert all(
        word not in public.text for word in ("秘密姓名", "秘密昵称", "秘密城市", "1999", uid, job)
    )
    svc.moderate(rid, "hidden", "owner")
    svc.moderate(rid, "hidden", "owner")
    assert svc.listing(1)["total"] == 0
    with db.session() as s:
        gift = s.scalar(select(WeeklyCoupon).where(WeeklyCoupon.source_review_id == rid))
        review = s.get(ReportReview, rid)
        assert gift.amount == 5000 and gift.expires_at - review.created_at == timedelta(days=7)
        assert (
            s.scalar(
                select(func.count())
                .select_from(WeeklyCoupon)
                .where(WeeklyCoupon.source_review_id == rid)
            )
            == 1
        )
        assert s.scalar(select(func.count()).select_from(ReviewModeration)) == 2


def test_review_boundaries_ownership_and_paging(payment_app):
    client, db, _ = payment_app
    uid = client.get("/api/v1/auth/me").json()["user"]["id"]
    svc = ReviewService(db)
    for rating in range(1, 6):
        job = ready(db, uid, 2000)
        assert svc.eligible(uid)["items"][0]["profile"]["cohort"] == "00后"
        for text in ("好", "好" * 101):
            with pytest.raises(PaymentError):
                svc.submit(uid, **{**payload(job), "content": text})
        result = svc.submit(uid, **{**payload(job), "rating": rating, "content": "好" * 100})
        svc.moderate(result["review"]["id"], "approved", "owner")
    for _ in range(7):
        result = svc.submit(uid, **payload(ready(db, uid)))
        svc.moderate(result["review"]["id"], "approved", "owner")
    assert len(svc.listing(1)["items"]) == 10 and len(svc.listing(2)["items"]) == 2
    assert len({i["id"] for p in (1, 2) for i in svc.listing(p)["items"]}) == 12
    with db.session() as s:
        other = UserRecord(id=str(uuid.uuid4()), display_name="另一个人", status="active")
        s.add(other)
        s.commit()
        oid = other.id
    with pytest.raises(PaymentError):
        svc.submit(oid, **payload(job))
    unfinished = ready(db, uid)
    with db.session() as s:
        s.get(AnalysisJobRecord, unfinished).status = "partial"
        s.commit()
    with pytest.raises(PaymentError):
        svc.submit(uid, **payload(unfinished))


@pytest.mark.parametrize("value", ["中文", "English", "👩🏽‍💻X", "🇨🇳X", "👍🏽X", "éX"])
def test_first_grapheme(value):
    assert len(graphemes(value)[0]) >= 1
    assert len(graphemes("👩🏽‍💻🇨🇳")) == 2


def test_real_chart_profile(payment_app):
    from app.services.reviews import public_profile

    client, db, _ = payment_app
    result = client.post(
        "/api/v1/charts",
        json={
            "name": "test",
            "gender": "male",
            "birth_local_datetime": "1990-01-01T12:00",
            "location_id": 3101,
        },
    )
    assert result.status_code == 200, result.text
    uid = client.get("/api/v1/auth/me").json()["user"]["id"]
    with db.session() as s:
        chart = s.scalar(select(ChartRecord).where(ChartRecord.user_id == uid))
        profile = public_profile(s.get(UserRecord, uid), chart)
        assert profile["province"] and profile["day_master"] and len(profile["pillars"]) == 4
