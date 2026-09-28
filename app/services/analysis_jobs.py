from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload, selectinload

from app.config import AnalysisQueueSettings
from app.database import Database
from app.models import AnalysisJobRecord, AnalysisSectionRecord, ChartRecord
from app.schemas.chart import ChartRequest
from app.services.analysis_service import ANALYSIS_DISCLAIMER, ANALYSIS_SECTIONS
from app.services.chart_service import ChartService


class AnalysisJobError(RuntimeError):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, object] | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.details = details or {}


@dataclass(frozen=True)
class Submission:
    job_id: str
    chart_id: str
    status: str
    deduplicated: bool


def canonical_hash(value: object) -> str:
    serialized = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


class AnalysisJobService:
    def __init__(
        self,
        database: Database,
        chart_service: ChartService,
        settings: AnalysisQueueSettings,
    ):
        self.database = database
        self.chart_service = chart_service
        self.settings = settings

    def submit(self, request: ChartRequest) -> Submission:
        chart = self.chart_service.calculate(request)
        rule_version = cast(dict[str, Any], chart["ruleset_versions"])
        snapshot_hash = canonical_hash(chart)
        request_hash = canonical_hash(
            {
                "chart_snapshot": chart,
                "model_id": self.settings.model_id,
                "prompt_version": self.settings.prompt_version,
                "rule_version": rule_version,
            }
        )
        with self.database.session() as session:
            existing = session.scalar(
                select(AnalysisJobRecord).where(AnalysisJobRecord.request_hash == request_hash)
            )
            if existing is not None:
                return Submission(existing.id, existing.chart_id, existing.status, True)

            chart_record = ChartRecord(
                request_json=request.model_dump(mode="json"),
                snapshot_json=chart,
                snapshot_hash=snapshot_hash,
            )
            job = AnalysisJobRecord(
                chart=chart_record,
                status="pending",
                model_id=self.settings.model_id,
                provider=self.settings.provider,
                prompt_version=self.settings.prompt_version,
                rule_version=rule_version,
                request_hash=request_hash,
            )
            for position, spec in enumerate(ANALYSIS_SECTIONS):
                job.sections.append(
                    AnalysisSectionRecord(
                        code=spec.code,
                        title=spec.title,
                        position=position,
                        status="pending",
                        request_hash=canonical_hash(
                            {
                                "job_request_hash": request_hash,
                                "section": spec.code,
                                "prompt_version": self.settings.prompt_version,
                            }
                        ),
                    )
                )
            session.add(job)
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                existing = session.scalar(
                    select(AnalysisJobRecord).where(AnalysisJobRecord.request_hash == request_hash)
                )
                if existing is None:
                    raise
                return Submission(existing.id, existing.chart_id, existing.status, True)
            return Submission(job.id, chart_record.id, job.status, False)

    def status(self, job_id: str) -> dict[str, object]:
        job = self._load_job(job_id, include_chart=False)
        return _serialize_status(job)

    def result(self, job_id: str) -> dict[str, object]:
        job = self._load_job(job_id, include_chart=True)
        return {
            **_serialize_status(job),
            "chart": job.chart.snapshot_json,
            "sections": [_serialize_section(section) for section in job.sections],
            "disclaimer": ANALYSIS_DISCLAIMER,
        }

    def retry_section(self, job_id: str, code: str) -> Submission:
        with self.database.session() as session:
            job = session.scalar(
                select(AnalysisJobRecord)
                .where(AnalysisJobRecord.id == job_id)
                .options(selectinload(AnalysisJobRecord.sections))
                .with_for_update()
            )
            if job is None:
                raise AnalysisJobError(404, "analysis_not_found", "分析任务不存在")
            section = next((item for item in job.sections if item.code == code), None)
            if section is None:
                raise AnalysisJobError(404, "analysis_section_not_found", "分析板块不存在")
            if section.status not in {"failed", "cancelled"}:
                raise AnalysisJobError(
                    409,
                    "section_not_retryable",
                    "只有失败或已取消的板块可以单独重试",
                    {"status": section.status},
                )
            section.status = "pending"
            section.failure_count = 0
            section.error_code = None
            section.error = None
            section.locked_by = None
            section.locked_at = None
            section.lease_expires_at = None
            section.next_attempt_at = datetime.now(UTC)
            section.started_at = None
            section.finished_at = None
            job.cancel_requested = False
            job.error = None
            job.finished_at = None
            job.status = (
                "partial" if any(item.status == "completed" for item in job.sections) else "pending"
            )
            session.commit()
            return Submission(job.id, job.chart_id, job.status, False)

    def cancel(self, job_id: str) -> dict[str, object]:
        with self.database.session() as session:
            job = session.scalar(
                select(AnalysisJobRecord)
                .where(AnalysisJobRecord.id == job_id)
                .options(selectinload(AnalysisJobRecord.sections))
                .with_for_update()
            )
            if job is None:
                raise AnalysisJobError(404, "analysis_not_found", "分析任务不存在")
            if job.status in {"completed", "failed", "cancelled"}:
                raise AnalysisJobError(
                    409,
                    "analysis_not_cancellable",
                    "当前任务状态不允许取消",
                    {"status": job.status},
                )
            job.cancel_requested = True
            for section in job.sections:
                if section.status == "pending":
                    section.status = "cancelled"
                    section.locked_by = None
                    section.locked_at = None
                    section.lease_expires_at = None
                    section.next_attempt_at = None
            if not any(section.status == "running" for section in job.sections):
                job.status = "cancelled"
            session.commit()
            return _serialize_status(job)

    def delete_job(self, job_id: str) -> None:
        with self.database.session() as session:
            job = session.get(AnalysisJobRecord, job_id)
            if job is None:
                raise AnalysisJobError(404, "analysis_not_found", "分析任务不存在")
            session.delete(job)
            session.commit()

    def delete_chart(self, chart_id: str) -> None:
        with self.database.session() as session:
            chart = session.get(ChartRecord, chart_id)
            if chart is None:
                raise AnalysisJobError(404, "chart_not_found", "持久化命盘不存在")
            session.delete(chart)
            session.commit()

    def _load_job(self, job_id: str, *, include_chart: bool) -> AnalysisJobRecord:
        options: list[object] = [selectinload(AnalysisJobRecord.sections)]
        if include_chart:
            options.append(joinedload(AnalysisJobRecord.chart))
        with self.database.session() as session:
            statement = select(AnalysisJobRecord).where(AnalysisJobRecord.id == job_id)
            for option in options:
                statement = statement.options(option)  # type: ignore[arg-type]
            job = session.scalar(statement)
            if job is None:
                raise AnalysisJobError(404, "analysis_not_found", "分析任务不存在")
            # All requested relations are eagerly loaded before the session closes.
            return job


def _serialize_status(job: AnalysisJobRecord) -> dict[str, object]:
    return {
        "job_id": job.id,
        "chart_id": job.chart_id,
        "status": job.status,
        "model_id": job.model_id,
        "prompt_version": job.prompt_version,
        "request_hash": job.request_hash,
        "cancel_requested": job.cancel_requested,
        "completed_sections": sum(item.status == "completed" for item in job.sections),
        "failed_sections": sum(item.status == "failed" for item in job.sections),
        "total_sections": len(job.sections),
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
    }


def _serialize_section(section: AnalysisSectionRecord) -> dict[str, object]:
    return {
        "code": section.code,
        "title": section.title,
        "status": section.status,
        "content": section.content,
        "char_count": section.char_count,
        "length_status": section.length_status,
        "retry_count": section.retry_count,
        "error": section.error,
        "started_at": section.started_at,
        "finished_at": section.finished_at,
    }
