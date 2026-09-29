from __future__ import annotations

import logging
import re
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app import __version__
from app.api.routes import router
from app.config import AnalysisQueueSettings, AuthSettings
from app.database import Database
from app.domain.calendar.solar_terms import SolarTermDataError, SolarTermRepository
from app.domain.timezone.service import TimeNormalizationError
from app.observability import configure_logging, request_id_context
from app.repositories.locations import LocationRepository
from app.services.analysis_jobs import AnalysisJobError, AnalysisJobService
from app.services.analysis_service import AnalysisServiceError
from app.services.auth import AuthError, AuthService
from app.services.chart_service import ChartService, ChartServiceError

configure_logging()
logger = logging.getLogger("bazi.api")
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


class UTF8JSONResponse(JSONResponse):
    """显式声明UTF-8，兼容仍按响应charset解码JSON的Windows PowerShell 5.1。"""

    media_type = "application/json; charset=utf-8"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时初始化共享仓库，避免每个请求重复加载节气数据。"""
    locations = LocationRepository()
    terms = SolarTermRepository()
    app.state.locations = locations
    chart_service = ChartService(locations, terms)
    app.state.chart_service = chart_service
    database = Database.from_env()
    app.state.database = database
    auth_settings = AuthSettings.from_env()
    app.state.auth_settings = auth_settings
    app.state.auth_service = AuthService(database, auth_settings) if database is not None else None
    app.state.analysis_job_service = (
        AnalysisJobService(database, chart_service, AnalysisQueueSettings.from_env())
        if database is not None
        else None
    )
    try:
        yield
    finally:
        if database is not None:
            database.dispose()


app = FastAPI(
    title="确定性八字排盘 API",
    version=__version__,
    description="立春换年、节令换月、真太阳时23点换日的可审计排盘服务。",
    lifespan=lifespan,
    default_response_class=UTF8JSONResponse,
)
app.include_router(router)


@app.middleware("http")
async def request_context(request: Request, call_next):
    incoming = request.headers.get("X-Request-ID", "")
    request_id = incoming if _REQUEST_ID_PATTERN.fullmatch(incoming) else uuid.uuid4().hex
    token = request_id_context.set(request_id)
    started = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        response.headers["X-Request-ID"] = request_id
        return response
    except Exception:
        logger.exception(
            "request_failed",
            extra={"method": request.method, "path": request.url.path, "status_code": 500},
        )
        raise
    finally:
        logger.info(
            "request_completed",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status_code": status_code,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            },
        )
        request_id_context.reset(token)


def error_response(
    status: int, code: str, message: str, details: dict[str, object] | None = None
) -> UTF8JSONResponse:
    """统一错误响应外形，方便前端按 code 处理异常。"""
    return UTF8JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "details": details or {}}},
    )


@app.exception_handler(ChartServiceError)
async def chart_error(_: Request, exc: ChartServiceError) -> JSONResponse:
    # 地点不存在属于资源未找到，其余业务规则异常按不可处理实体返回。
    return error_response(
        404 if exc.code == "location_not_found" else 422, exc.code, str(exc), exc.details
    )


@app.exception_handler(AnalysisServiceError)
async def analysis_error(_: Request, exc: AnalysisServiceError) -> JSONResponse:
    unavailable_codes = {
        "analysis_not_configured",
        "llm_invalid_configuration",
        "llm_timeout",
        "llm_unavailable",
    }
    status = 503 if exc.code in unavailable_codes else 502
    return error_response(status, exc.code, str(exc), exc.details)


@app.exception_handler(AnalysisJobError)
async def analysis_job_error(_: Request, exc: AnalysisJobError) -> JSONResponse:
    return error_response(exc.status_code, exc.code, str(exc), exc.details)


@app.exception_handler(AuthError)
async def auth_error(_: Request, exc: AuthError) -> JSONResponse:
    return error_response(exc.status_code, exc.code, str(exc))


@app.exception_handler(TimeNormalizationError)
async def time_error(_: Request, exc: TimeNormalizationError) -> JSONResponse:
    return error_response(422, exc.code, str(exc), exc.details)


@app.exception_handler(SolarTermDataError)
async def term_error(_: Request, exc: SolarTermDataError) -> JSONResponse:
    return error_response(422, "solar_term_data_missing", str(exc))


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    # Pydantic 的上下文可能包含异常对象，转成字符串后才能安全序列化为 JSON。
    errors = exc.errors()
    for item in errors:
        item.pop("url", None)
        if "ctx" in item:
            item["ctx"] = {key: str(value) for key, value in item["ctx"].items()}
    details: dict[str, object] = {"errors": errors}
    messages = " ".join(str(item.get("msg", "")) for item in errors)
    code = "unsupported_date_range" if "between 1901" in messages else "invalid_birth_datetime"
    return error_response(422, code, "request validation failed", details)


@app.exception_handler(SQLAlchemyError)
async def database_error(_: Request, exc: SQLAlchemyError) -> JSONResponse:
    logger.warning("database_unavailable", extra={"error_type": type(exc).__name__})
    return error_response(
        503,
        "database_unavailable",
        "AI分析存储暂时不可用，普通排盘仍可正常使用",
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@app.get("/health/live")
def health_live() -> dict[str, str]:
    return {"status": "ok", "component": "api", "version": __version__}


@app.get("/health/ready")
def health_ready(request: Request) -> JSONResponse:
    database: Database | None = request.app.state.database
    if database is None:
        return UTF8JSONResponse(
            content={"status": "degraded", "api": "ok", "database": "not_configured"}
        )
    try:
        database.ping()
    except SQLAlchemyError:
        return UTF8JSONResponse(
            status_code=503,
            content={"status": "unavailable", "api": "ok", "database": "unavailable"},
        )
    return UTF8JSONResponse(content={"status": "ok", "api": "ok", "database": "ok"})
