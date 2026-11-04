from typing import Annotated, Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from app.api.admin import AdminDependency, same_origin
from app.api.routes import RequiredUserDependency
from app.services.cards import PaymentError
from app.services.reviews import ReviewService

router = APIRouter(tags=["reviews"])


def service(request: Request) -> ReviewService:
    if request.app.state.database is None:
        raise PaymentError(503, "reviews_unavailable", "评价服务暂未开放")
    return ReviewService(request.app.state.database)


Reviews = Annotated[ReviewService, Depends(service)]


class ReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    job_id: str = Field(min_length=36, max_length=36)
    rating: int = Field(ge=1, le=5)
    content: str = Field(min_length=2, max_length=2000)
    consent: bool
    consent_version: str = Field(max_length=32)


class ModerationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["approved", "hidden"]


@router.get("/api/v1/reviews")
def public(reviews: Reviews, page: int = Query(1, ge=1, le=100000)):
    return reviews.listing(page)


@router.get("/api/v1/reviews/mine")
def mine(user: RequiredUserDependency, reviews: Reviews):
    return reviews.eligible(user.id)


@router.post("/api/v1/reviews")
def submit(payload: ReviewInput, user: RequiredUserDependency, request: Request, reviews: Reviews):
    origin = request.headers.get("origin")
    expected = urlsplit(request.app.state.auth_settings.callback_url)
    if request.headers.get("sec-fetch-site") == "cross-site" or (
        origin
        and origin != f"{expected.scheme}://{expected.netloc}"
        and not (
            request.app.state.auth_settings.mode == "mock"
            and urlsplit(origin).hostname in {"localhost", "127.0.0.1", "testserver"}
        )
    ):
        raise PaymentError(403, "review_origin_invalid", "请从本站页面提交评价")
    return reviews.submit(user.id, **payload.model_dump())


@router.get("/api/v1/admin/reviews")
def listing(
    admin: AdminDependency,
    reviews: Reviews,
    status: Literal["", "pending", "approved", "hidden"] = "pending",
    page: int = Query(1, ge=1, le=100000),
):
    return reviews.listing(page, status, admin=True)


@router.post("/api/v1/admin/reviews/{review_id}/moderate")
def moderate(
    review_id: str,
    payload: ModerationInput,
    request: Request,
    admin: AdminDependency,
    reviews: Reviews,
):
    same_origin(request, admin)
    return reviews.moderate(review_id, payload.status, admin.settings.username)
