from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload, selectinload

from app.config import AnalysisQueueSettings
from app.database import Database
from app.models import AnalysisJobRecord, AnalysisSectionRecord, ChartRecord
from app.schemas.chart import ChartRequest
from app.services.analysis_service import ANALYSIS_DISCLAIMER, ANALYSIS_SECTIONS
from app.services.cards import debit_report, lock_user
from app.services.chart_service import ChartService, with_annual_branch_stars


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
        *,
        require_cards: bool = False,
    ):
        self.database = database
        self.chart_service = chart_service
        self.settings = settings
        self.require_cards = require_cards

    def submit(
        self,
        request: ChartRequest,
        *,
        user_id: str | None = None,
        analysis_limit_per_24h: int = 0,
        chart_id: str | None = None,
    ) -> Submission:
        if self.require_cards and user_id is None:
            raise AnalysisJobError(401, "authentication_required", "请先登录再使用解读卡")
        if chart_id is not None:
            # Unlock the stored facts, not a recalculated or client-supplied chart.
            stored = self.saved_chart(chart_id, actor_user_id=user_id)
            request = ChartRequest.model_validate(stored["request"])
            chart = cast(dict[str, object], stored["snapshot"])
        else:
            chart = self.chart_service.calculate(request)
        # Keep display metadata outside immutable calculation snapshots and debit identity.
        cast(dict[str, Any], chart["request"]).pop("birth_calendar", None)
        rule_version = cast(dict[str, Any], chart["ruleset_versions"])
        snapshot_hash = canonical_hash(chart)
        hash_payload: dict[str, object] = {
            "chart_snapshot": chart,
            "model_id": self.settings.model_id,
            "prompt_version": self.settings.prompt_version,
            "rule_version": rule_version,
        }
        # Anonymous hashes retain the legacy format. Authenticated reports include
        # their owner so identical birth data never deduplicates across users.
        if user_id is not None:
            hash_payload["user_id"] = user_id
        request_hash = canonical_hash(hash_payload)
        with self.database.session() as session:
            # Lock BEFORE inserting the chart's user FK. Otherwise two MySQL
            # submissions can both hold a shared FK lock and deadlock on debit.
            if (self.require_cards or chart_id is not None) and user_id is not None:
                lock_user(session, user_id)
            chart_record = None
            if chart_id is not None:
                chart_record = session.get(ChartRecord, chart_id)
                if chart_record is None or chart_record.user_id != user_id or user_id is None:
                    raise AnalysisJobError(404, "chart_not_found", "命盘不存在或无权访问")
                if chart_record.jobs:
                    restored = max(chart_record.jobs, key=lambda job: (job.created_at, job.id))
                    return Submission(restored.id, chart_id, restored.status, True)
            existing = session.scalar(
                select(AnalysisJobRecord).where(AnalysisJobRecord.request_hash == request_hash)
            )
            if existing is not None:
                if request.birth_calendar:
                    existing.chart.request_json = {
                        **existing.chart.request_json,
                        "birth_calendar": request.birth_calendar,
                    }
                    session.commit()
                return Submission(existing.id, existing.chart_id, existing.status, True)

            if user_id is not None and analysis_limit_per_24h > 0:
                since = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=24)
                recent_count = session.scalar(
                    select(func.count(AnalysisJobRecord.id))
                    .join(ChartRecord, AnalysisJobRecord.chart_id == ChartRecord.id)
                    .where(
                        ChartRecord.user_id == user_id,
                        AnalysisJobRecord.created_at >= since,
                    )
                )
                if int(recent_count or 0) >= analysis_limit_per_24h:
                    raise AnalysisJobError(
                        429,
                        "daily_analysis_limit_reached",
                        "已达到最近24小时的AI分析次数上限",
                        {"limit": analysis_limit_per_24h},
                    )

            chart_record = chart_record or ChartRecord(
                user_id=user_id,
                request_json={
                    **request.model_dump(mode="json"),
                    **(
                        {"birth_calendar": request.birth_calendar} if request.birth_calendar else {}
                    ),
                },
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
            queued_at = datetime.now(UTC)
            for position, spec in enumerate(ANALYSIS_SECTIONS):
                job.sections.append(
                    AnalysisSectionRecord(
                        code=spec.code,
                        title=spec.title,
                        position=position,
                        status="pending",
                        next_attempt_at=queued_at,
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
                session.flush()
                if self.require_cards and user_id is not None:
                    debit_report(session, user_id, job.id)
                session.commit()
            except IntegrityError:
                session.rollback()
                existing = session.scalar(
                    select(AnalysisJobRecord).where(AnalysisJobRecord.request_hash == request_hash)
                )
                if existing is None:
                    raise
                if request.birth_calendar:
                    existing.chart.request_json = {
                        **existing.chart.request_json,
                        "birth_calendar": request.birth_calendar,
                    }
                    session.commit()
                return Submission(existing.id, existing.chart_id, existing.status, True)
            return Submission(job.id, chart_record.id, job.status, False)

    def save_chart(
        self, request: ChartRequest, snapshot: dict[str, object], *, user_id: str
    ) -> dict[str, object]:
        """Archive free chart facts only; never enqueue sections or debit cards."""
        chart = deepcopy(snapshot)
        cast(dict[str, Any], chart["request"]).pop("birth_calendar", None)
        snapshot_hash = canonical_hash(chart)
        with self.database.session() as session:
            lock_user(session, user_id)
            record = session.scalar(
                select(ChartRecord)
                .where(ChartRecord.user_id == user_id, ChartRecord.snapshot_hash == snapshot_hash)
                .order_by(ChartRecord.created_at.desc(), ChartRecord.id.desc())
                .limit(1)
            )
            if record is None:
                record = ChartRecord(
                    user_id=user_id,
                    request_json=request.model_dump(mode="json"),
                    snapshot_json=chart,
                    snapshot_hash=snapshot_hash,
                )
                session.add(record)
            if request.birth_calendar:
                record.request_json = {
                    **record.request_json,
                    "birth_calendar": request.birth_calendar,
                }
            session.flush()
            job = max(record.jobs, key=lambda job: (job.created_at, job.id), default=None)
            result: dict[str, object] = {
                "saved_chart_id": record.id,
                "analysis_job_id": job.id if job else None,
            }
            session.commit()
            return result

    def saved_chart(self, chart_id: str, *, actor_user_id: str | None) -> dict[str, object]:
        with self.database.session() as session:
            record = session.get(ChartRecord, chart_id)
            if record is None or actor_user_id is None or record.user_id != actor_user_id:
                raise AnalysisJobError(404, "chart_not_found", "命盘不存在或无权访问")
            snapshot = deepcopy(record.snapshot_json)
            calendar = record.request_json.get("birth_calendar")
            chart = {
                **snapshot,
                "request": {
                    **snapshot["request"],
                    **({"birth_calendar": calendar} if calendar in ("solar", "lunar") else {}),
                },
            }
            job = max(record.jobs, key=lambda job: (job.created_at, job.id), default=None)
            return {
                "chart_id": record.id,
                "job_id": job.id if job else None,
                "request": deepcopy(record.request_json),
                "chart": with_annual_branch_stars(chart),
                "snapshot": snapshot,
            }

    def list_reports_for_user(self, user_id: str, *, limit: int = 100) -> list[dict[str, object]]:
        with self.database.session() as session:
            charts = session.scalars(
                select(ChartRecord)
                .where(ChartRecord.user_id == user_id)
                .options(
                    selectinload(ChartRecord.jobs)
                    .selectinload(AnalysisJobRecord.sections)
                    .load_only(AnalysisSectionRecord.status)
                )
                .order_by(ChartRecord.created_at.desc(), ChartRecord.id.desc())
                .limit(limit)
            ).all()
            reports = []
            for chart in charts:
                job = max(chart.jobs, key=lambda job: (job.created_at, job.id), default=None)
                reports.append(
                    {
                        "chart_id": chart.id,
                        "job_id": job.id if job else None,
                        "status": job.status if job else "locked",
                        "name": chart.request_json.get("name"),
                        "birth_local_datetime": chart.request_json.get("birth_local_datetime"),
                        "pillars": [
                            chart.snapshot_json.get("pillars", {}).get(key, {}).get("pillar", "")
                            for key in ("year", "month", "day", "hour")
                        ],
                        "completed_sections": (
                            sum(s.status == "completed" for s in job.sections) if job else 0
                        ),
                        "total_sections": len(job.sections) if job else 0,
                        "created_at": chart.created_at,
                    }
                )
            return reports

    def status(self, job_id: str, *, actor_user_id: str | None = None) -> dict[str, object]:
        job = self._load_job(job_id, include_chart=True, actor_user_id=actor_user_id)
        return _serialize_status(job)

    def result(self, job_id: str, *, actor_user_id: str | None = None) -> dict[str, object]:
        job = self._load_job(job_id, include_chart=True, actor_user_id=actor_user_id)
        snapshot = job.chart.snapshot_json
        calendar = job.chart.request_json.get("birth_calendar")
        chart = {
            **snapshot,
            "request": {
                **snapshot["request"],
                **({"birth_calendar": calendar} if calendar in ("solar", "lunar") else {}),
            },
        }
        return {
            **_serialize_status(job),
            "chart": with_annual_branch_stars(chart),
            "sections": [_serialize_section(section) for section in job.sections],
            "disclaimer": ANALYSIS_DISCLAIMER,
        }

    def retry_section(
        self, job_id: str, code: str, *, actor_user_id: str | None = None
    ) -> Submission:
        with self.database.session() as session:
            job = session.scalar(
                select(AnalysisJobRecord)
                .where(AnalysisJobRecord.id == job_id)
                .options(
                    selectinload(AnalysisJobRecord.sections), joinedload(AnalysisJobRecord.chart)
                )
                .with_for_update()
            )
            if job is None:
                raise AnalysisJobError(404, "analysis_not_found", "分析任务不存在")
            _ensure_job_access(job, actor_user_id)
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

    def cancel(self, job_id: str, *, actor_user_id: str | None = None) -> dict[str, object]:
        with self.database.session() as session:
            job = session.scalar(
                select(AnalysisJobRecord)
                .where(AnalysisJobRecord.id == job_id)
                .options(
                    selectinload(AnalysisJobRecord.sections), joinedload(AnalysisJobRecord.chart)
                )
                .with_for_update()
            )
            if job is None:
                raise AnalysisJobError(404, "analysis_not_found", "分析任务不存在")
            _ensure_job_access(job, actor_user_id)
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

    def delete_job(self, job_id: str, *, actor_user_id: str | None = None) -> None:
        with self.database.session() as session:
            job = session.scalar(
                select(AnalysisJobRecord)
                .where(AnalysisJobRecord.id == job_id)
                .options(joinedload(AnalysisJobRecord.chart))
            )
            if job is None:
                raise AnalysisJobError(404, "analysis_not_found", "分析任务不存在")
            _ensure_job_access(job, actor_user_id)
            session.delete(job)
            session.commit()

    def delete_chart(self, chart_id: str, *, actor_user_id: str | None = None) -> None:
        with self.database.session() as session:
            chart = session.get(ChartRecord, chart_id)
            if chart is None:
                raise AnalysisJobError(404, "chart_not_found", "持久化命盘不存在")
            if chart.user_id is not None and chart.user_id != actor_user_id:
                raise AnalysisJobError(404, "chart_not_found", "持久化命盘不存在")
            session.delete(chart)
            session.commit()

    def list_for_user(self, user_id: str, *, limit: int = 20) -> list[dict[str, object]]:
        with self.database.session() as session:
            jobs = session.scalars(
                select(AnalysisJobRecord)
                .join(ChartRecord, AnalysisJobRecord.chart_id == ChartRecord.id)
                .where(ChartRecord.user_id == user_id)
                .options(
                    joinedload(AnalysisJobRecord.chart),
                    selectinload(AnalysisJobRecord.sections),
                )
                .order_by(AnalysisJobRecord.created_at.desc())
                .limit(limit)
            ).all()
            return [
                {
                    "job_id": job.id,
                    "chart_id": job.chart_id,
                    "status": job.status,
                    "name": job.chart.request_json.get("name"),
                    "birth_local_datetime": job.chart.request_json.get("birth_local_datetime"),
                    "pillars": [
                        job.chart.snapshot_json.get("pillars", {}).get(key, {}).get("pillar", "")
                        for key in ("year", "month", "day", "hour")
                    ],
                    "completed_sections": sum(
                        section.status == "completed" for section in job.sections
                    ),
                    "total_sections": len(job.sections),
                    "created_at": job.created_at,
                }
                for job in jobs
            ]

    def _load_job(
        self,
        job_id: str,
        *,
        include_chart: bool,
        actor_user_id: str | None = None,
    ) -> AnalysisJobRecord:
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
            _ensure_job_access(job, actor_user_id)
            # All requested relations are eagerly loaded before the session closes.
            return job


def _ensure_job_access(job: AnalysisJobRecord, actor_user_id: str | None) -> None:
    if job.chart.user_id is not None and job.chart.user_id != actor_user_id:
        # Do not reveal that another user's report exists.
        raise AnalysisJobError(404, "analysis_not_found", "分析任务不存在")


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
