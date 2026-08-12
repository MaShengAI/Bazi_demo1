from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status

from app.repositories.locations import LocationRepository
from app.schemas.analysis import (
    AnalysisAccepted,
    AnalysisResultResponse,
    AnalysisStatusResponse,
)
from app.schemas.chart import ChartRequest
from app.services.analysis_jobs import AnalysisJobError, AnalysisJobService
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


ChartServiceDependency = Annotated[ChartService, Depends(get_chart_service)]
LocationRepositoryDependency = Annotated[LocationRepository, Depends(get_location_repository)]
AnalysisJobServiceDependency = Annotated[AnalysisJobService, Depends(get_analysis_job_service)]


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
    payload: ChartRequest, service: AnalysisJobServiceDependency
) -> AnalysisAccepted:
    """持久化命盘快照和八个待处理板块，不在API进程内调用模型。"""
    submission = service.submit(payload)
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
def analysis_status(job_id: str, service: AnalysisJobServiceDependency) -> AnalysisStatusResponse:
    return AnalysisStatusResponse.model_validate(service.status(job_id))


@router.get("/analyses/{job_id}", response_model=AnalysisResultResponse)
def analysis_result(job_id: str, service: AnalysisJobServiceDependency) -> AnalysisResultResponse:
    return AnalysisResultResponse.model_validate(service.result(job_id))


@router.post(
    "/analyses/{job_id}/sections/{section_code}/retry",
    response_model=AnalysisAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
def retry_analysis_section(
    job_id: str, section_code: str, service: AnalysisJobServiceDependency
) -> AnalysisAccepted:
    submission = service.retry_section(job_id, section_code)
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
def cancel_analysis(job_id: str, service: AnalysisJobServiceDependency) -> AnalysisStatusResponse:
    return AnalysisStatusResponse.model_validate(service.cancel(job_id))


@router.delete("/analyses/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_analysis(job_id: str, service: AnalysisJobServiceDependency) -> Response:
    service.delete_job(job_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/charts/{chart_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_persisted_chart(chart_id: str, service: AnalysisJobServiceDependency) -> Response:
    """删除出生信息、排盘快照以及其全部分析和调用日志。"""
    service.delete_chart(chart_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
