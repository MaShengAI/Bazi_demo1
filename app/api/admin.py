from __future__ import annotations

import json
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from starlette.concurrency import run_in_threadpool

from app.admin import ADMIN_PATH, AdminError, AdminService

router = APIRouter(prefix=ADMIN_PATH, tags=["administrator"])


def service(request: Request) -> AdminService:
    value = getattr(request.app.state, "admin_service", None)
    if value is None:
        raise AdminError(503, "admin_unavailable", "管理后台尚未启用，请先完成服务器配置。")
    return value


def require_admin(request: Request) -> AdminService:
    value = service(request)
    if not value.authenticated(request.cookies.get(value.settings.cookie_name)):
        raise AdminError(401, "admin_auth_required", "请登录管理后台。")
    return value


def same_origin(request: Request, value: AdminService) -> None:
    if request.headers.get("origin") != value.settings.public_origin:
        raise AdminError(403, "admin_origin_rejected", "请求来源不正确，请从管理页面操作。")


@router.get("/session")
def session_state(request: Request) -> dict:
    value = service(request)
    authenticated = value.authenticated(request.cookies.get(value.settings.cookie_name))
    return {
        "authenticated": authenticated,
        "username": value.settings.username if authenticated else None,
    }


@router.post("/login")
async def login(request: Request, response: Response) -> dict:
    value = service(request)
    same_origin(request, value)
    if request.headers.get("content-type", "").split(";", 1)[0].lower() != "application/json":
        raise AdminError(415, "admin_json_required", "请使用管理页面登录。")
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > 4096:
            raise AdminError(413, "admin_login_too_large", "登录信息过长。")
        data.extend(chunk)
    try:
        body = json.loads(data)
        username, password = body["username"], body["password"]
        if not isinstance(username, str) or not isinstance(password, str):
            raise ValueError
        if len(username) > 128 or not 1 <= len(password) <= 256:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        # Do not let Pydantic echo a password in a validation error response.
        raise AdminError(401, "admin_login_invalid", "账号或密码不正确。") from None
    token = await run_in_threadpool(
        value.login,
        username,
        password,
        request.client.host if request.client else "unknown",
    )
    response.set_cookie(
        value.settings.cookie_name,
        token,
        max_age=value.settings.session_seconds,
        httponly=True,
        secure=value.settings.cookie_secure,
        samesite="strict",
        path=ADMIN_PATH,
    )
    return {"authenticated": True, "username": value.settings.username}


@router.post("/logout", status_code=204, response_class=Response, response_model=None)
def logout(request: Request, response: Response) -> None:
    value = service(request)
    same_origin(request, value)
    value.logout(request.cookies.get(value.settings.cookie_name))
    response.delete_cookie(
        value.settings.cookie_name,
        path=ADMIN_PATH,
        secure=value.settings.cookie_secure,
        httponly=True,
        samesite="strict",
    )


AdminDependency = Annotated[AdminService, Depends(require_admin)]


@router.get("/reports")
def reports(
    admin: AdminDependency,
    q: str = Query("", max_length=100),
    status: str = Query("", max_length=20),
    start: date | None = None,
    end: date | None = None,
    page: int = Query(1, ge=1, le=100_000),
) -> dict:
    return admin.reports(q=q.strip(), status=status, start=start, end=end, page=page)


@router.get("/reports/{job_id}")
def report(job_id: str, admin: AdminDependency) -> dict:
    if len(job_id) > 36:
        raise AdminError(404, "admin_report_not_found", "报告不存在或已被删除。")
    return admin.report(job_id)
