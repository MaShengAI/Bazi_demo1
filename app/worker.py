from __future__ import annotations

import asyncio
import logging
import os
import socket
import tempfile
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import exists, select
from sqlalchemy.orm import selectinload

from app.config import AnalysisQueueSettings
from app.database import Database
from app.integrations.llm import (
    LLMCompletion,
    LLMProvider,
    LLMProviderError,
    LLMSettings,
    OpenAICompatibleLLM,
)
from app.models import AnalysisJobRecord, AnalysisSectionRecord, LLMCallLogRecord
from app.observability import configure_logging
from app.services.analysis_service import (
    ANALYSIS_SECTIONS,
    SYSTEM_PROMPT,
    ANALYSIS_MINIMUM_CHARS,
    ANALYSIS_MAXIMUM_CHARS,
    _character_count,
    _normalize_content,
    build_section_prompt,
)

SECTION_BY_CODE = {section.code: section for section in ANALYSIS_SECTIONS}
logger = logging.getLogger("bazi.worker")


def utcnow() -> datetime:
    return datetime.now(UTC)


class AnalysisWorker:
    """Lease-based worker; safe to run as a process separate from FastAPI."""

    def __init__(
        self,
        database: Database,
        provider: LLMProvider,
        settings: AnalysisQueueSettings,
        *,
        worker_id: str | None = None,
    ):
        self.database = database
        self.provider = provider
        self.settings = settings
        self.worker_id = worker_id or f"{socket.gethostname()}-{uuid.uuid4().hex[:12]}"
        self.heartbeat_file = Path(
            os.getenv(
                "BAZI_WORKER_HEARTBEAT_FILE",
                str(Path(tempfile.gettempdir()) / "bazi-worker-heartbeat"),
            )
        )

    async def run_once(self) -> bool:
        self._touch_heartbeat()
        self.recover_expired_leases()
        job_id = self._claim_job()
        if job_id is None:
            return False
        await self._process_job(job_id)
        return True

    async def run_forever(self) -> None:
        logger.info("worker_started", extra={"worker_id": self.worker_id})
        try:
            while True:
                self._touch_heartbeat()
                worked = await self.run_once()
                if not worked:
                    await asyncio.sleep(self.settings.worker_poll_seconds)
        finally:
            logger.info("worker_stopped", extra={"worker_id": self.worker_id})
            await self.provider.close()

    def _touch_heartbeat(self) -> None:
        self.heartbeat_file.parent.mkdir(parents=True, exist_ok=True)
        self.heartbeat_file.touch()

    def recover_expired_leases(self) -> int:
        now = utcnow()
        recovered = 0
        with self.database.session() as session:
            jobs = session.scalars(
                select(AnalysisJobRecord)
                .where(
                    AnalysisJobRecord.status == "running",
                    AnalysisJobRecord.lease_expires_at.is_not(None),
                    AnalysisJobRecord.lease_expires_at < now,
                )
                .options(selectinload(AnalysisJobRecord.sections))
                .with_for_update(skip_locked=True)
            ).all()
            for job in jobs:
                recovered += 1
                for section in job.sections:
                    if section.status == "running":
                        section.status = "pending"
                        section.error_code = "worker_lease_expired"
                        section.error = "worker租约过期，板块已重新入队"
                        running_calls = session.scalars(
                            select(LLMCallLogRecord).where(
                                LLMCallLogRecord.section_id == section.id,
                                LLMCallLogRecord.status == "running",
                            )
                        ).all()
                        for call in running_calls:
                            call.status = "failed"
                            call.error_code = "worker_lease_expired"
                            call.error = "worker租约过期"
                            call.finished_at = now
                job.status = (
                    "partial"
                    if any(section.status == "completed" for section in job.sections)
                    else "pending"
                )
                job.locked_by = None
                job.lease_expires_at = None
            session.commit()
            if recovered:
                logger.warning(
                    "expired_leases_recovered",
                    extra={"worker_id": self.worker_id, "recovered_jobs": recovered},
                )
        return recovered

    def _claim_job(self) -> str | None:
        now = utcnow()
        pending_section = exists().where(
            AnalysisSectionRecord.job_id == AnalysisJobRecord.id,
            AnalysisSectionRecord.status == "pending",
        )
        with self.database.session() as session:
            job = session.scalar(
                select(AnalysisJobRecord)
                .where(
                    AnalysisJobRecord.status.in_(("pending", "partial")),
                    AnalysisJobRecord.cancel_requested.is_(False),
                    AnalysisJobRecord.model_id == self.settings.model_id,
                    AnalysisJobRecord.provider == self.settings.provider,
                    AnalysisJobRecord.prompt_version == self.settings.prompt_version,
                    pending_section,
                )
                .order_by(AnalysisJobRecord.created_at, AnalysisJobRecord.id)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if job is None:
                return None
            job.status = "running"
            job.locked_by = self.worker_id
            job.lease_expires_at = now + timedelta(seconds=self.settings.worker_lease_seconds)
            job.started_at = job.started_at or now
            session.commit()
            logger.info(
                "job_claimed",
                extra={"worker_id": self.worker_id, "job_id": job.id},
            )
            return job.id

    async def _process_job(self, job_id: str) -> None:
        logger.info("job_started", extra={"worker_id": self.worker_id, "job_id": job_id})
        with self.database.session() as session:
            job = session.scalar(
                select(AnalysisJobRecord)
                .where(AnalysisJobRecord.id == job_id)
                .options(selectinload(AnalysisJobRecord.sections))
            )
            section_ids = (
                [section.id for section in job.sections if section.status == "pending"]
                if job is not None
                else []
            )
        for section_id in section_ids:
            if self._is_cancel_requested(job_id):
                break
            await self._process_section(job_id, section_id)
        self._finish_job(job_id)
        logger.info("job_finished", extra={"worker_id": self.worker_id, "job_id": job_id})

    async def _process_section(self, job_id: str, section_id: str) -> None:
        length_hint = ""
        last_error: tuple[str, str] | None = None
        for local_attempt in range(1, self.settings.max_attempts + 1):
            prepared = self._prepare_call(job_id, section_id, length_hint)
            if prepared is None:
                return
            log_id, prompt = prepared
            started = time.perf_counter()
            try:
                completion = await self._call_provider_with_heartbeat(job_id, SYSTEM_PROMPT, prompt)
            except LLMProviderError as exc:
                latency_ms = round((time.perf_counter() - started) * 1000)
                request_id = exc.details.get("request_id")
                self._finish_call(
                    log_id,
                    status="failed",
                    latency_ms=latency_ms,
                    request_id=request_id if isinstance(request_id, str) else None,
                    error_code=exc.code,
                    error=str(exc),
                )
                last_error = (exc.code, str(exc))
                logger.warning(
                    "section_attempt_failed",
                    extra={
                        "worker_id": self.worker_id,
                        "job_id": job_id,
                        "section_id": section_id,
                        "attempt": local_attempt,
                        "error_code": exc.code,
                    },
                )
                if local_attempt < self.settings.max_attempts:
                    continue
                self._fail_section(section_id, *last_error)
                return
            except Exception:
                latency_ms = round((time.perf_counter() - started) * 1000)
                self._finish_call(
                    log_id,
                    status="failed",
                    latency_ms=latency_ms,
                    error_code="llm_unexpected_error",
                    error="模型调用发生未预期错误",
                )
                last_error = ("llm_unexpected_error", "模型调用发生未预期错误")
                logger.exception(
                    "section_attempt_unexpected_error",
                    extra={
                        "worker_id": self.worker_id,
                        "job_id": job_id,
                        "section_id": section_id,
                        "attempt": local_attempt,
                    },
                )
                if local_attempt < self.settings.max_attempts:
                    continue
                self._fail_section(section_id, *last_error)
                return

            latency_ms = round((time.perf_counter() - started) * 1000)
            content = _normalize_content(completion.content)
            char_count = _character_count(content)
            length_status = "ok"
            if char_count < ANALYSIS_MINIMUM_CHARS:
                length_status = "short"
            elif char_count > ANALYSIS_MAXIMUM_CHARS:
                length_status = "long"
            self._finish_call(
                log_id,
                status="completed",
                latency_ms=latency_ms,
                request_id=completion.request_id,
                prompt_tokens=completion.prompt_tokens,
                completion_tokens=completion.completion_tokens,
                total_tokens=completion.total_tokens,
            )
            if length_status != "ok" and local_attempt < self.settings.max_attempts:
                direction = "扩写" if length_status == "short" else "精简"
                length_hint = f"上次输出为{char_count}字符，请明显{direction}并重新完整作答。"
                continue
            self._complete_section(section_id, content, char_count, length_status)
            logger.info(
                "section_completed",
                extra={
                    "worker_id": self.worker_id,
                    "job_id": job_id,
                    "section_id": section_id,
                    "attempt": local_attempt,
                    "latency_ms": latency_ms,
                    "length_status": length_status,
                },
            )
            return

    def _prepare_call(
        self, job_id: str, section_id: str, length_hint: str
    ) -> tuple[str, str] | None:
        now = utcnow()
        with self.database.session() as session:
            job = session.get(AnalysisJobRecord, job_id)
            section = session.get(AnalysisSectionRecord, section_id)
            if (
                job is None
                or section is None
                or job.cancel_requested
                or section.status not in {"pending", "running"}
            ):
                return None
            spec = SECTION_BY_CODE[section.code]
            section.status = "running"
            section.started_at = section.started_at or now
            section.attempt_count += 1
            section.retry_count = max(0, section.attempt_count - 1)
            section.error_code = None
            section.error = None
            job.lease_expires_at = now + timedelta(seconds=self.settings.worker_lease_seconds)
            log = LLMCallLogRecord(
                section_id=section.id,
                request_hash=section.request_hash,
                provider=job.provider,
                model_id=job.model_id,
                attempt_no=section.attempt_count,
                status="running",
                started_at=now,
            )
            prompt = build_section_prompt(
                spec,
                job.chart.snapshot_json,
                length_hint=length_hint,
                analysis_date=job.created_at.date(),
            )
            session.add(log)
            session.commit()
            return log.id, prompt

    async def _call_provider(self, system_prompt: str, user_prompt: str) -> LLMCompletion:
        detailed = getattr(self.provider, "complete_detailed", None)
        if callable(detailed):
            result = await detailed(system_prompt, user_prompt)
            if isinstance(result, LLMCompletion):
                return result
        return LLMCompletion(content=await self.provider.complete(system_prompt, user_prompt))

    async def _call_provider_with_heartbeat(
        self, job_id: str, system_prompt: str, user_prompt: str
    ) -> LLMCompletion:
        task = asyncio.create_task(self._call_provider(system_prompt, user_prompt))
        interval = max(5.0, min(30.0, self.settings.worker_lease_seconds / 3))
        while True:
            done, _ = await asyncio.wait({task}, timeout=interval)
            if task in done:
                return await task
            self._renew_lease(job_id)

    def _renew_lease(self, job_id: str) -> None:
        self._touch_heartbeat()
        with self.database.session() as session:
            job = session.get(AnalysisJobRecord, job_id)
            if job is None or job.locked_by != self.worker_id:
                return
            job.lease_expires_at = utcnow() + timedelta(seconds=self.settings.worker_lease_seconds)
            session.commit()

    def _finish_call(
        self,
        log_id: str,
        *,
        status: str,
        latency_ms: int,
        request_id: str | None = None,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        total_tokens: int | None = None,
        error_code: str | None = None,
        error: str | None = None,
    ) -> None:
        with self.database.session() as session:
            log = session.get(LLMCallLogRecord, log_id)
            if log is None:
                return
            log.status = status
            log.latency_ms = latency_ms
            log.provider_request_id = request_id
            log.prompt_tokens = prompt_tokens
            log.completion_tokens = completion_tokens
            log.total_tokens = total_tokens
            log.error_code = error_code
            log.error = error
            log.finished_at = utcnow()
            session.commit()

    def _complete_section(
        self, section_id: str, content: str, char_count: int, length_status: str
    ) -> None:
        with self.database.session() as session:
            section = session.get(AnalysisSectionRecord, section_id)
            if section is None:
                return
            section.status = "completed"
            section.content = content
            section.char_count = char_count
            section.length_status = length_status
            section.error_code = None
            section.error = None
            section.finished_at = utcnow()
            session.commit()

    def _fail_section(self, section_id: str, error_code: str, error: str) -> None:
        with self.database.session() as session:
            section = session.get(AnalysisSectionRecord, section_id)
            if section is None:
                return
            section.status = "failed"
            section.error_code = error_code
            section.error = error
            section.finished_at = utcnow()
            session.commit()

    def _is_cancel_requested(self, job_id: str) -> bool:
        with self.database.session() as session:
            job = session.get(AnalysisJobRecord, job_id)
            return job is None or job.cancel_requested

    def _finish_job(self, job_id: str) -> None:
        now = utcnow()
        with self.database.session() as session:
            job = session.scalar(
                select(AnalysisJobRecord)
                .where(AnalysisJobRecord.id == job_id)
                .options(selectinload(AnalysisJobRecord.sections))
                .with_for_update()
            )
            if job is None:
                return
            states = [section.status for section in job.sections]
            if job.cancel_requested:
                for section in job.sections:
                    if section.status == "pending":
                        section.status = "cancelled"
                job.status = "cancelled"
            elif states and all(state == "completed" for state in states):
                job.status = "completed"
            elif any(state == "completed" for state in states):
                job.status = "partial"
            elif not any(state in {"pending", "running"} for state in states):
                job.status = "failed"
            else:
                job.status = "pending"
            if job.status in {"completed", "partial", "failed", "cancelled"}:
                job.finished_at = now
            job.locked_by = None
            job.lease_expires_at = None
            session.commit()


async def _run() -> None:
    database = Database.from_env()
    if database is None:
        raise SystemExit("BAZI_DATABASE_URL is required for the worker")
    llm_settings = LLMSettings.from_env()
    if llm_settings is None:
        raise SystemExit("BAZI_LLM_API_KEY is required for the worker")
    queue_settings = AnalysisQueueSettings.from_env()
    provider = OpenAICompatibleLLM(llm_settings)
    worker = AnalysisWorker(database, provider, queue_settings)
    try:
        await worker.run_forever()
    finally:
        database.dispose()


def main() -> None:
    configure_logging(os.getenv("BAZI_LOG_LEVEL", "INFO"))
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
