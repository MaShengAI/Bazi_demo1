from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.api.admin import AdminDependency, same_origin
from app.api.payments import Service
from app.api.routes import RequiredUserDependency
from app.services.redemptions import RedemptionService

router = APIRouter(tags=["redemptions"])


def service(request: Request) -> RedemptionService:
    from app.services.cards import PaymentError

    if request.app.state.database is None or not request.app.state.payment_settings.enabled:
        raise PaymentError(503, "redemption_unavailable", "兑换功能尚未开放")
    return RedemptionService(request.app.state.database)


Redemptions = Annotated[RedemptionService, Depends(service)]


class RedeemInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=1, max_length=100)


class BatchInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["cards", "coupon"]
    value: int = Field(ge=1, le=100000)  # cards: units; coupon: integer CNY cents
    quantity: int = Field(ge=1, le=1000)
    label: str = Field(min_length=1, max_length=80)
    request_key: str = Field(min_length=16, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


@router.post("/api/v1/redemptions")
def redeem(
    payload: RedeemInput, user: RequiredUserDependency, payments: Service, redemptions: Redemptions
):
    # Service dependency enforces existing customer origin and mock-local protections.
    # The new-purchase flag intentionally does not control gift redemption.
    return redemptions.redeem(user.id, payload.code)


@router.get("/api/v1/admin/redemptions")
def listing(
    admin: AdminDependency,
    redemptions: Redemptions,
    batch_id: str = Query("", max_length=32),
    status: Literal["", "unused", "redeemed", "expired", "disabled"] = "",
    page: int = Query(1, ge=1, le=100000),
):
    return redemptions.listing(batch_id=batch_id, status=status, page=page)


@router.post("/api/v1/admin/redemptions/batches", status_code=201)
def generate(
    payload: BatchInput, request: Request, admin: AdminDependency, redemptions: Redemptions
):
    same_origin(request, admin)
    return redemptions.generate(**payload.model_dump(), operator=admin.settings.username)


@router.post("/api/v1/admin/redemptions/{code_id}/disable", status_code=204)
def disable(code_id: str, request: Request, admin: AdminDependency, redemptions: Redemptions):
    same_origin(request, admin)
    redemptions.disable(code_id, admin.settings.username)
    return Response(status_code=204)


class CodeSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    code_ids: list[str] = Field(min_length=1, max_length=1000)


@router.post("/api/v1/admin/redemptions/bulk-disable")
def bulk_disable(
    payload: CodeSelection, request: Request, admin: AdminDependency, redemptions: Redemptions
):
    same_origin(request, admin)
    return redemptions.bulk_disable(payload.code_ids, admin.settings.username)


@router.post("/api/v1/admin/redemptions/bulk-delete")
def bulk_delete(
    payload: CodeSelection, request: Request, admin: AdminDependency, redemptions: Redemptions
):
    same_origin(request, admin)
    return redemptions.bulk_delete(payload.code_ids, admin.settings.username)
