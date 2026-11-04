from __future__ import annotations

from typing import Annotated, Literal
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from app.api.routes import RequiredUserDependency
from app.services.cards import PaymentError
from app.services.payments import PaymentService
from app.services.refunds import RefundService

router = APIRouter(prefix="/api/v1/payments")


def payment_service(request: Request) -> PaymentService:
    service = request.app.state.payment_service
    if service is None:
        raise PaymentError(503, "payments_disabled", "购买解读卡尚未开放")
    service.require_enabled()
    is_notification = request.url.path in {
        "/api/v1/payments/wechat/notify",
        "/api/v1/payments/wechat/refund-notify",
    }
    if request.method == "POST" and not is_notification:
        origin = request.headers.get("origin")
        expected = urlsplit(service.auth.callback_url)
        local_mock_origin = (
            service.settings.mode == "mock"
            and origin
            and urlsplit(origin).hostname in {"localhost", "127.0.0.1", "::1", "testserver"}
        )
        if request.headers.get("sec-fetch-site") == "cross-site" or (
            origin and origin != f"{expected.scheme}://{expected.netloc}" and not local_mock_origin
        ):
            raise PaymentError(403, "payment_origin_invalid", "请从本站页面发起支付操作")
    # Never expose a simulation that can grant cards on a public hostname.
    if service.settings.mode == "mock" and request.url.hostname not in {
        "localhost",
        "127.0.0.1",
        "testserver",
        "::1",
    }:
        raise PaymentError(403, "mock_local_only", "模拟支付仅可在本地测试")
    return service


Service = Annotated[PaymentService, Depends(payment_service)]


class OrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_code: Literal["single", "double", "family"]
    use_coupon: bool = True
    coupon_id: str | None = Field(
        default=None, min_length=1, max_length=36, pattern=r"^[A-Za-z0-9_-]+$"
    )
    idempotency_key: str = Field(min_length=16, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


@router.get("/account")
def account(service: Service, user: RequiredUserDependency) -> dict:
    return service.account(user.id)


@router.post("/orders", status_code=201)
def create_order(payload: OrderRequest, service: Service, user: RequiredUserDependency) -> dict:
    return service.create(
        user.id,
        payload.product_code,
        payload.use_coupon,
        payload.idempotency_key,
        coupon_id=payload.coupon_id,
    )


@router.post("/orders/{order_id}/prepay")
def prepay(order_id: str, service: Service, user: RequiredUserDependency) -> dict:
    return service.prepay(user.id, order_id)


@router.post("/orders/{order_id}/refresh")
def refresh(order_id: str, service: Service, user: RequiredUserDependency) -> dict:
    return service.refresh(user.id, order_id)


@router.post("/orders/{order_id}/close")
def close(order_id: str, service: Service, user: RequiredUserDependency) -> dict:
    return service.refresh(user.id, order_id, close=True)


@router.post("/orders/{order_id}/mock-confirm")
def mock_confirm(order_id: str, service: Service, user: RequiredUserDependency) -> dict:
    return service.mock_confirm(user.id, order_id)


@router.post("/wechat/notify")
async def notify(request: Request, service: Service) -> Response:
    if service.client is None:
        raise PaymentError(404, "not_found", "接口不存在")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 65536:
            raise PaymentError(413, "notification_too_large", "通知过大")
    transaction = await run_in_threadpool(
        service.client.notification, httpx.Headers(request.headers), bytes(body)
    )
    await run_in_threadpool(service.receive, transaction)
    return Response(status_code=204)


@router.post("/wechat/refund-notify")
async def refund_notify(request: Request, service: Service) -> Response:
    refunds = RefundService(service.database, service.settings, service.auth, service.client)
    refunds.require_enabled()
    if service.client is None:
        raise PaymentError(404, "not_found", "接口不存在")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 65536:
            raise PaymentError(413, "notification_too_large", "通知过大")
    result = await run_in_threadpool(
        service.client.refund_notification, httpx.Headers(request.headers), bytes(body)
    )
    await run_in_threadpool(refunds.receive, result, source="callback")
    return Response(status_code=204)
