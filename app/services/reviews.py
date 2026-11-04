"""Report-owned reviews; consent and an independent gift commit atomically."""

import unicodedata
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from lunar_python import Solar
from sqlalchemy import func, select

from app.commerce_models import ReportReview, ReviewModeration, WeeklyCoupon
from app.database import Database
from app.models import AnalysisJobRecord, AnalysisSectionRecord, ChartRecord, UserRecord, new_id
from app.services.cards import PaymentError, lock_user, now_utc

CONSENT_VERSION = "review-public-v1"
AUTO_APPROVAL_OPERATOR = "system:rating"
FACES = ["😞", "😕", "🙂", "😊", "😄"]
ELEMENTS = dict(zip("甲乙丙丁戊己庚辛壬癸", "木木火火土土金金水水", strict=True))


def graphemes(value: str) -> list[str]:
    """Keep emoji ZWJ/modifier/flag/keycap and combining marks in one character."""
    result: list[str] = []
    regional = 0
    for char in value:
        code = ord(char)
        is_regional = 0x1F1E6 <= code <= 0x1F1FF
        extend = (
            unicodedata.category(char).startswith("M")
            or char == "\u200d"
            or 0x1F3FB <= code <= 0x1F3FF
            or 0xE0020 <= code <= 0xE007F
            or bool(result and result[-1].endswith("\u200d"))
            or (is_regional and regional % 2 == 1)
        )
        if result and extend:
            result[-1] += char
        else:
            result.append(char)
        regional = regional + 1 if is_regional else 0
    return result


def public_profile(user: UserRecord, chart: ChartRecord) -> dict:
    snapshot = chart.snapshot_json
    request = chart.request_json
    birth = datetime.fromisoformat(request["birth_local_datetime"])
    year = birth.year // 5 * 5
    day = snapshot["pillars"]["day"]["heavenly_stem"]
    avatar = user.avatar_url or ""
    parsed = urlsplit(avatar)
    # Never emit javascript/data URLs or credentials from a stored profile.
    if parsed.scheme != "https" or not parsed.hostname or parsed.username:
        avatar = ""
    return {
        "nickname": (graphemes(user.display_name.strip()) or ["微"])[0],
        "avatar_url": avatar or None,
        "gender": request["gender"],
        "cohort": f"{year % 100:02d}后",
        "day_master": day + ELEMENTS[day],
        "zodiac": Solar.fromYmd(birth.year, birth.month, birth.day).getLunar().getYearShengXiao(),
        "pillars": [snapshot["pillars"][key]["pillar"] for key in ("year", "month", "day", "hour")],
        "province": snapshot["location"]["province"],
    }


def packed(review: ReportReview, private: bool = False) -> dict:
    data = {
        "id": review.id,
        "profile": review.public_profile,
        "rating": review.rating,
        "face": FACES[review.rating - 1],
        "content": review.content,
        "created_at": review.created_at.isoformat() + "Z",
    }
    if private:
        data.update(job_id=review.job_id, status=review.status)
    return data


def complete(session, job: AnalysisJobRecord) -> bool:
    sections = session.scalars(
        select(AnalysisSectionRecord).where(AnalysisSectionRecord.job_id == job.id)
    ).all()
    return (
        job.status == "completed"
        and len(sections) == 8
        and all(
            section.status == "completed" and (section.content or "").strip()
            for section in sections
        )
    )


class ReviewService:
    def __init__(self, database: Database):
        self.database = database

    def eligible(self, user_id: str) -> dict:
        with self.database.session() as session:
            user = session.get(UserRecord, user_id)
            if user is None or user.status != "active":
                raise PaymentError(401, "login_required", "请先登录")
            jobs = session.scalars(
                select(AnalysisJobRecord)
                .join(ChartRecord)
                .where(ChartRecord.user_id == user_id, AnalysisJobRecord.status == "completed")
                .order_by(AnalysisJobRecord.created_at.desc())
            ).all()
            existing = {
                r.job_id: r
                for r in session.scalars(
                    select(ReportReview).where(ReportReview.user_id == user_id)
                ).all()
            }
            items = []
            for job in jobs:
                if complete(session, job):
                    chart = session.get(ChartRecord, job.chart_id)
                    items.append(
                        {
                            "job_id": job.id,
                            "name": chart.request_json.get("name") or "未署名",
                            "profile": public_profile(user, chart),
                            "review": packed(existing[job.id], True)
                            if job.id in existing
                            else None,
                        }
                    )
            return {"items": items, "consent_version": CONSENT_VERSION}

    def submit(
        self,
        user_id: str,
        job_id: str,
        rating: int,
        content: str,
        consent: bool,
        consent_version: str,
    ) -> dict:
        text = content.strip()
        if not consent or consent_version != CONSENT_VERSION:
            raise PaymentError(422, "consent_required", "请预览公开资料并确认已获得命主同意")
        if type(rating) is not int or not 1 <= rating <= 5 or not 2 <= len(graphemes(text)) <= 100:
            raise PaymentError(422, "review_invalid", "请选择1～5星，评价须为2～100字")
        with self.database.session() as session:
            # All account awards serialize on the same user row, including network retries.
            lock_user(session, user_id)
            user = session.get(UserRecord, user_id)
            previous = session.scalar(select(ReportReview).where(ReportReview.job_id == job_id))
            if previous:
                if previous.user_id != user_id:
                    raise PaymentError(404, "report_not_found", "未找到报告")
                if previous.rating != rating or previous.content != text:
                    raise PaymentError(409, "review_exists", "这份报告已经评价过了")
                return {"review": packed(previous, True), "gift_amount": 5000, "replayed": True}
            job = session.scalar(
                select(AnalysisJobRecord).where(AnalysisJobRecord.id == job_id).with_for_update()
            )
            chart = (
                session.scalar(
                    select(ChartRecord).where(ChartRecord.id == job.chart_id).with_for_update()
                )
                if job
                else None
            )
            if chart is None or chart.user_id != user_id:
                raise PaymentError(404, "report_not_found", "未找到报告")
            if not complete(session, job):
                raise PaymentError(409, "report_not_complete", "完整解读完成后才可评价")
            now = now_utc()
            auto_approved = rating >= 4
            review = ReportReview(
                id=new_id(),
                user_id=user_id,
                job_id=job_id,
                rating=rating,
                content=text,
                public_profile=public_profile(user, chart),
                consent_version=CONSENT_VERSION,
                consent_at=now,
                created_at=now,
                status="approved" if auto_approved else "pending",
                moderated_at=now if auto_approved else None,
                moderated_by=AUTO_APPROVAL_OPERATOR if auto_approved else None,
            )
            session.add(review)
            if auto_approved:
                # Keep the new review, approval audit and gift in one transaction.
                session.flush()
                session.add(
                    ReviewModeration(
                        review_id=review.id,
                        operator=AUTO_APPROVAL_OPERATOR,
                        previous_status="pending",
                        status="approved",
                        created_at=now,
                    )
                )
            session.add(
                WeeklyCoupon(
                    user_id=user_id,
                    period_start=None,
                    source_review_id=review.id,
                    amount=5000,
                    expires_at=now + timedelta(days=7),
                )
            )
            session.commit()
            return {"review": packed(review, True), "gift_amount": 5000, "replayed": False}

    def listing(self, page: int, status: str = "approved", admin: bool = False) -> dict:
        with self.database.session() as session:
            # Public query always restricts status, regardless of caller input.
            query = select(ReportReview).join(UserRecord).where(UserRecord.status == "active")
            if not admin or status:
                query = query.where(ReportReview.status == (status if admin else "approved"))
            total = session.scalar(select(func.count()).select_from(query.subquery()))
            rows = session.scalars(
                query.order_by(ReportReview.created_at.desc(), ReportReview.id.desc())
                .offset((page - 1) * 10)
                .limit(10)
            ).all()
            return {
                "items": [packed(r, admin) for r in rows],
                "page": page,
                "page_size": 10,
                "total": total,
            }

    def moderate(self, review_id: str, status: str, operator: str) -> dict:
        if status not in ("approved", "hidden"):
            raise PaymentError(422, "invalid_status", "无效的审核状态")
        with self.database.session() as session:
            review = session.scalar(
                select(ReportReview).where(ReportReview.id == review_id).with_for_update()
            )
            if review is None:
                raise PaymentError(404, "review_not_found", "未找到评价")
            if review.status != status:
                now = now_utc()
                session.add(
                    ReviewModeration(
                        review_id=review.id,
                        operator=operator,
                        previous_status=review.status,
                        status=status,
                        created_at=now,
                    )
                )
                review.status, review.moderated_at, review.moderated_by = status, now, operator
                session.commit()
            return packed(review, True)
