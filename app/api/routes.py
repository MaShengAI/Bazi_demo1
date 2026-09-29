from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import RedirectResponse

from app.config import AuthSettings
from app.integrations.wechat import WechatOAuthClient, WechatOAuthError
from app.repositories.locations import LocationRepository
from app.schemas.analysis import (
    AnalysisAccepted,
    AnalysisResultResponse,
    AnalysisStatusResponse,
)
from app.schemas.auth import AnalysisHistoryItem, AuthStateResponse, AuthUserResponse
from app.schemas.chart import ChartRequest
from app.services.analysis_jobs import AnalysisJobError, AnalysisJobService
from app.services.auth import AuthenticatedUser, AuthError, AuthService
from app.services.chart_service import ChartService

router = APIRouter(prefix="/api/v1")
logger = logging.getLogger("bazi.api.jobs")


def get_chart_service(request: Request) -> ChartService:
    """取得应用启动时创建的共享排盘服务。"""
    return request.app.state.chart_service


def get_location_repository(request: Request) -> LocationRepository:
    """通过依赖注入共享本地点位仓库。"""
    return request.app.state.locations


def get_analysis_job_service(request: Request) -> AnalysisJobService:
    """持久化接口需要数据库；本地排盘接口不使用此依赖。"""
    service = request.app.state.analysis_job_service
    if service is None:
        raise AnalysisJobError(
            503,
            "database_not_configured",
            "持久化分析服务尚未配置，请设置BAZI_DATABASE_URL并执行迁移",
        )
    return service


def get_auth_service(request: Request) -> AuthService:
    service = request.app.state.auth_service
    if service is None:
        raise AuthError(503, "database_not_configured", "微信登录需要先配置数据库")
    return service


def get_optional_user(request: Request) -> AuthenticatedUser | None:
    settings: AuthSettings = request.app.state.auth_settings
    if not settings.enabled:
        return None
    service = get_auth_service(request)
    return service.current_user(request.cookies.get(settings.session_cookie_name))


def require_current_user(request: Request) -> AuthenticatedUser:
    settings: AuthSettings = request.app.state.auth_settings
    if not settings.enabled:
        raise AuthError(503, "wechat_auth_disabled", "微信登录尚未启用")
    service = get_auth_service(request)
    return service.require_user(request.cookies.get(settings.session_cookie_name))


ChartServiceDependency = Annotated[ChartService, Depends(get_chart_service)]
LocationRepositoryDependency = Annotated[LocationRepository, Depends(get_location_repository)]
AnalysisJobServiceDependency = Annotated[AnalysisJobService, Depends(get_analysis_job_service)]
AuthServiceDependency = Annotated[AuthService, Depends(get_auth_service)]
OptionalUserDependency = Annotated[AuthenticatedUser | None, Depends(get_optional_user)]
RequiredUserDependency = Annotated[AuthenticatedUser, Depends(require_current_user)]


@router.post("/charts")
def create_chart(payload: ChartRequest, service: ChartServiceDependency) -> dict[str, object]:
    """执行完整排盘；路由层不直接参与历法计算。"""
    return service.calculate(payload)


@router.post(
    "/analyses",
    response_model=AnalysisAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_analysis(
    payload: ChartRequest,
    request: Request,
    service: AnalysisJobServiceDependency,
    current_user: OptionalUserDependency,
) -> AnalysisAccepted:
    """持久化命盘快照和八个待处理板块，不在API进程内调用模型。"""
    auth_settings: AuthSettings = request.app.state.auth_settings
    if auth_settings.require_for_analysis and current_user is None:
        raise AuthError(401, "authentication_required", "请先使用微信登录再生成AI分析")
    submission = service.submit(
        payload,
        user_id=current_user.id if current_user else None,
        analysis_limit_per_24h=auth_settings.analysis_limit_per_24h,
    )
    logger.info(
        "analysis_job_submitted",
        extra={
            "job_id": submission.job_id,
            "chart_id": submission.chart_id,
            "deduplicated": submission.deduplicated,
        },
    )
    return AnalysisAccepted(
        job_id=submission.job_id,
        chart_id=submission.chart_id,
        status=submission.status,  # type: ignore[arg-type]
        deduplicated=submission.deduplicated,
    )


@router.get("/analyses/{job_id}/status", response_model=AnalysisStatusResponse)
def analysis_status(
    job_id: str,
    service: AnalysisJobServiceDependency,
    current_user: OptionalUserDependency,
) -> AnalysisStatusResponse:
    return AnalysisStatusResponse.model_validate(
        service.status(job_id, actor_user_id=current_user.id if current_user else None)
    )


@router.get("/analyses/{job_id}", response_model=AnalysisResultResponse)
def analysis_result(
    job_id: str,
    service: AnalysisJobServiceDependency,
    current_user: OptionalUserDependency,
) -> AnalysisResultResponse:
    return AnalysisResultResponse.model_validate(
        service.result(job_id, actor_user_id=current_user.id if current_user else None)
    )


@router.post(
    "/analyses/{job_id}/sections/{section_code}/retry",
    response_model=AnalysisAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
def retry_analysis_section(
    job_id: str,
    section_code: str,
    service: AnalysisJobServiceDependency,
    current_user: OptionalUserDependency,
) -> AnalysisAccepted:
    submission = service.retry_section(
        job_id, section_code, actor_user_id=current_user.id if current_user else None
    )
    return AnalysisAccepted(
        job_id=submission.job_id,
        chart_id=submission.chart_id,
        status=submission.status,  # type: ignore[arg-type]
    )


@router.post(
    "/analyses/{job_id}/cancel",
    response_model=AnalysisStatusResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def cancel_analysis(
    job_id: str,
    service: AnalysisJobServiceDependency,
    current_user: OptionalUserDependency,
) -> AnalysisStatusResponse:
    return AnalysisStatusResponse.model_validate(
        service.cancel(job_id, actor_user_id=current_user.id if current_user else None)
    )


@router.delete("/analyses/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_analysis(
    job_id: str,
    service: AnalysisJobServiceDependency,
    current_user: OptionalUserDependency,
) -> Response:
    service.delete_job(job_id, actor_user_id=current_user.id if current_user else None)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/charts/{chart_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_persisted_chart(
    chart_id: str,
    service: AnalysisJobServiceDependency,
    current_user: OptionalUserDependency,
) -> Response:
    """删除出生信息、排盘快照以及其全部分析和调用日志。"""
    service.delete_chart(chart_id, actor_user_id=current_user.id if current_user else None)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/auth/wechat/start")
def start_wechat_login(
    request: Request,
    service: AuthServiceDependency,
    return_to: str = Query(default="/", max_length=500),
) -> RedirectResponse:
    settings: AuthSettings = request.app.state.auth_settings
    state = service.create_oauth_state(return_to)
    return RedirectResponse(WechatOAuthClient(settings).authorization_url(state), status_code=302)


@router.get("/auth/wechat/callback")
async def finish_wechat_login(
    request: Request,
    service: AuthServiceDependency,
    code: str = Query(min_length=1, max_length=1024),
    state: str = Query(min_length=1, max_length=1024),
) -> RedirectResponse:
    settings: AuthSettings = request.app.state.auth_settings
    return_to = service.consume_oauth_state(state)
    try:
        profile = await WechatOAuthClient(settings).exchange_code(code)
    except WechatOAuthError as exc:
        raise AuthError(502, exc.code, str(exc)) from exc
    _, raw_token = service.login_wechat_user(profile)
    response = RedirectResponse(return_to, status_code=302)
    response.set_cookie(
        settings.session_cookie_name,
        raw_token,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    return response


@router.get("/auth/me", response_model=AuthStateResponse)
def auth_state(request: Request, current_user: OptionalUserDependency) -> AuthStateResponse:
    settings: AuthSettings = request.app.state.auth_settings
    user = (
        AuthUserResponse(
            id=current_user.id,
            display_name=current_user.display_name,
            avatar_url=current_user.avatar_url,
        )
        if current_user
        else None
    )
    return AuthStateResponse(
        enabled=settings.enabled,
        authenticated=current_user is not None,
        require_for_analysis=settings.require_for_analysis,
        analysis_limit_per_24h=settings.analysis_limit_per_24h,
        user=user,
    )


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, service: AuthServiceDependency) -> Response:
    settings: AuthSettings = request.app.state.auth_settings
    service.logout(request.cookies.get(settings.session_cookie_name))
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(settings.session_cookie_name, path="/")
    return response


@router.get("/me/analyses", response_model=list[AnalysisHistoryItem])
def my_analyses(
    service: AnalysisJobServiceDependency,
    current_user: RequiredUserDependency,
    limit: int = Query(default=20, ge=1, le=100),
) -> list[AnalysisHistoryItem]:
    return [
        AnalysisHistoryItem.model_validate(item)
        for item in service.list_for_user(current_user.id, limit=limit)
    ]


@router.get("/locations/provinces")
def provinces(
    repository: LocationRepositoryDependency,
) -> list[dict[str, str]]:
    """返回产品支持的全部34个中国省级行政区。"""
    return repository.provinces()


@router.get("/locations/cities")
def cities(
    repository: LocationRepositoryDependency,
    province: str = Query(min_length=2, max_length=20),
) -> list[dict[str, object]]:
    """按省级行政区名称返回可测算城市及其 location_id。"""
    return repository.cities(province)
