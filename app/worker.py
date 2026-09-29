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

from sqlalchemy import exists, func, or_, select
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
    ANALYSIS_MAXIMUM_CHARS,
    ANALYSIS_MINIMUM_CHARS,
    ANALYSIS_SECTIONS,
    SYSTEM_PROMPT,
    _character_count,
    _normalize_content,
    build_section_prompt,
)

SECTION_BY_CODE = {section.code: section for section in ANALYSIS_SECTIONS}
logger = logging.getLogger("bazi.worker")


def utcnow() -> datetime:
    return datetime.now(UTC)


class AnalysisWorker:
    """Section-level leased queue worker; safe to run in multiple processes."""

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
        """Claim and process one section. Primarily useful for tests and one-shot operation."""
        self._touch_heartbeat()
        self.recover_expired_leases()
        claimed = self._claim_section()
        if claimed is None:
            return False
        job_id, section_id = claimed
        await self._process_section(job_id, section_id)
        return True

    async def run_forever(self) -> None:
        logger.info(
            "worker_started",
            extra={
                "worker_id": self.worker_id,
                "concurrency": self.settings.worker_concurrency,
            },
        )
        tasks = [
            asyncio.create_task(self._run_slot(slot), name=f"section-slot-{slot}")
            for slot in range(self.settings.worker_concurrency)
        ]
        try:
            await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            logger.info("worker_stopped", extra={"worker_id": self.worker_id})
            await self.provider.close()

    async def _run_slot(self, slot: int) -> None:
        while True:
            self._touch_heartbeat()
            if slot == 0:
                self.recover_expired_leases()
            claimed = self._claim_section()
            if claimed is None:
                await asyncio.sleep(self.settings.worker_poll_seconds)
                continue
            job_id, section_id = claimed
            await self._process_section(job_id, section_id)

    def _touch_heartbeat(self) -> None:
        self.heartbeat_file.parent.mkdir(parents=True, exist_ok=True)
        self.heartbeat_file.touch()

    def _eligible_job_ids(self, now: datetime) -> list[str]:
        due_section = exists().where(
            AnalysisSectionRecord.job_id == AnalysisJobRecord.id,
            AnalysisSectionRecord.status == "pending",
            AnalysisSectionRecord.next_attempt_at <= now,
        )
        running_count = (
            select(func.count(AnalysisSectionRecord.id))
            .where(
                AnalysisSectionRecord.job_id == AnalysisJobRecord.id,
                AnalysisSectionRecord.status == "running",
            )
            .correlate(AnalysisJobRecord)
            .scalar_subquery()
        )
        with self.database.session() as session:
            return list(
                session.scalars(
                    select(AnalysisJobRecord.id)
                    .where(
                        AnalysisJobRecord.cancel_requested.is_(False),
                        AnalysisJobRecord.model_id == self.settings.model_id,
                        AnalysisJobRecord.provider == self.settings.provider,
                        AnalysisJobRecord.prompt_version == self.settings.prompt_version,
                        due_section,
                        running_count < self.settings.max_running_sections_per_job,
                    )
                    # Give capacity to reports with fewer running sections first.
                    .order_by(running_count, AnalysisJobRecord.created_at, AnalysisJobRecord.id)
                    .limit(1000)
                ).all()
            )

    def _lock_job_statement(self, job_id: str):
        return (
            select(AnalysisJobRecord)
            .where(
                AnalysisJobRecord.id == job_id,
                AnalysisJobRecord.cancel_requested.is_(False),
                AnalysisJobRecord.model_id == self.settings.model_id,
                AnalysisJobRecord.provider == self.settings.provider,
                AnalysisJobRecord.prompt_version == self.settings.prompt_version,
            )
            .with_for_update(skip_locked=True)
        )

    def _claim_statement(self, now: datetime, job_id: str):
        return (
            select(AnalysisSectionRecord)
            .where(
                AnalysisSectionRecord.status == "pending",
                AnalysisSectionRecord.next_attempt_at <= now,
                AnalysisSectionRecord.job_id == job_id,
            )
            .order_by(
                AnalysisSectionRecord.position,
                AnalysisSectionRecord.next_attempt_at,
                AnalysisSectionRecord.created_at,
                AnalysisSectionRecord.id,
            )
            .limit(1)
            .with_for_update(skip_locked=True)
        )

    def _claim_section(self) -> tuple[str, str] | None:
        now = utcnow()
        for candidate_job_id in self._eligible_job_ids(now):
            with self.database.session() as session:
                # Lock one known primary key at a time. This avoids MySQL locking every
                # row examined by an ORDER BY ... LIMIT ... FOR UPDATE query.
                job = session.scalar(self._lock_job_statement(candidate_job_id))
                if job is None:
                    continue
                running_count = session.scalar(
                    select(func.count(AnalysisSectionRecord.id)).where(
                        AnalysisSectionRecord.job_id == job.id,
                        AnalysisSectionRecord.status == "running",
                    )
                )
                if (running_count or 0) >= self.settings.max_running_sections_per_job:
                    continue
                section = session.scalar(self._claim_statement(now, job.id))
                if section is None or job.cancel_requested:
                    continue
                section.status = "running"
                section.locked_by = self.worker_id
                section.locked_at = now
                section.lease_expires_at = now + timedelta(
                    seconds=self.settings.worker_lease_seconds
                )
                section.next_attempt_at = None
                section.error_code = None
                section.error = None
                job_id = section.job_id
                section_id = section.id
                job.status = "running"
                job.started_at = job.started_at or now
                job.finished_at = None
                session.commit()
            logger.info(
                "section_claimed",
                extra={
                    "worker_id": self.worker_id,
                    "job_id": job_id,
                    "section_id": section_id,
                },
            )
            return job_id, section_id
        return None

    def recover_expired_leases(self) -> int:
        now = utcnow()
        recovered_ids: list[str] = []
        affected_jobs: set[str] = set()
        with self.database.session() as session:
            sections = session.scalars(
                select(AnalysisSectionRecord)
                .where(
                    AnalysisSectionRecord.status == "running",
                    or_(
                        AnalysisSectionRecord.lease_expires_at.is_(None),
                        AnalysisSectionRecord.lease_expires_at < now,
                    ),
                )
                .with_for_update(skip_locked=True)
            ).all()
            for section in sections:
                recovered_ids.append(section.id)
                affected_jobs.add(section.job_id)
                section.status = "pending"
                section.error_code = "worker_lease_expired"
                section.error = "worker租约过期，板块已重新入队"
                section.locked_by = None
                section.locked_at = None
                section.lease_expires_at = None
                section.next_attempt_at = now
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
            session.commit()
        for job_id in affected_jobs:
            self._refresh_job_status(job_id)
        if recovered_ids:
            logger.warning(
                "expired_leases_recovered",
                extra={
                    "worker_id": self.worker_id,
                    "recovered_sections": len(recovered_ids),
                },
            )
        return len(recovered_ids)

    async def _process_section(self, job_id: str, section_id: str) -> None:
        length_hint = ""
        for local_attempt in range(1, self.settings.max_attempts + 1):
            prepared = self._prepare_call(job_id, section_id, length_hint)
            if prepared is None:
                self._refresh_job_status(job_id)
                return
            log_id, prompt = prepared
            started = time.perf_counter()
            try:
                completion = await self._call_provider_with_heartbeat(
                    section_id, SYSTEM_PROMPT, prompt
                )
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
                self._retry_or_fail_section(section_id, exc.code, str(exc))
                self._refresh_job_status(job_id)
                logger.warning(
                    "section_attempt_failed",
                    extra={
                        "worker_id": self.worker_id,
                        "job_id": job_id,
                        "section_id": section_id,
                        "error_code": exc.code,
                    },
                )
                return
            except Exception:
                latency_ms = round((time.perf_counter() - started) * 1000)
                error_code = "llm_unexpected_error"
                error = "模型调用发生未预期错误"
                self._finish_call(
                    log_id,
                    status="failed",
                    latency_ms=latency_ms,
                    error_code=error_code,
                    error=error,
                )
                self._retry_or_fail_section(section_id, error_code, error)
                self._refresh_job_status(job_id)
                logger.exception(
                    "section_attempt_unexpected_error",
                    extra={
                        "worker_id": self.worker_id,
                        "job_id": job_id,
                        "section_id": section_id,
                    },
                )
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
            self._refresh_job_status(job_id)
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
            if job is None or section is None:
                return None
            if job.cancel_requested:
                if section.status == "running" and section.locked_by == self.worker_id:
                    section.status = "cancelled"
                    section.finished_at = now
                    self._clear_section_lease(section)
                    session.commit()
                return None
            if section.status != "running" or section.locked_by != self.worker_id:
                return None
            spec = SECTION_BY_CODE[section.code]
            section.started_at = section.started_at or now
            section.attempt_count += 1
            section.retry_count = max(section.retry_count, section.attempt_count - 1)
            section.error_code = None
            section.error = None
            section.lease_expires_at = now + timedelta(seconds=self.settings.worker_lease_seconds)
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
        self, section_id: str, system_prompt: str, user_prompt: str
    ) -> LLMCompletion:
        task = asyncio.create_task(self._call_provider(system_prompt, user_prompt))
        interval = max(5.0, min(30.0, self.settings.worker_lease_seconds / 3))
        while True:
            done, _ = await asyncio.wait({task}, timeout=interval)
            if task in done:
                return await task
            self._renew_lease(section_id)

    def _renew_lease(self, section_id: str) -> None:
        self._touch_heartbeat()
        with self.database.session() as session:
            section = session.get(AnalysisSectionRecord, section_id)
            if (
                section is None
                or section.status != "running"
                or section.locked_by != self.worker_id
            ):
                return
            section.lease_expires_at = utcnow() + timedelta(
                seconds=self.settings.worker_lease_seconds
            )
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
            if log is None or log.status != "running":
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
            if (
                section is None
                or section.status != "running"
                or section.locked_by != self.worker_id
            ):
                return
            section.status = "completed"
            section.content = content
            section.char_count = char_count
            section.length_status = length_status
            section.failure_count = 0
            section.error_code = None
            section.error = None
            section.finished_at = utcnow()
            section.next_attempt_at = None
            self._clear_section_lease(section)
            session.commit()

    def _retry_or_fail_section(self, section_id: str, error_code: str, error: str) -> None:
        now = utcnow()
        with self.database.session() as session:
            section = session.scalar(
                select(AnalysisSectionRecord)
                .where(AnalysisSectionRecord.id == section_id)
                .with_for_update()
            )
            if (
                section is None
                or section.status != "running"
                or section.locked_by != self.worker_id
            ):
                return
            section.failure_count += 1
            section.error_code = error_code
            section.error = error
            self._clear_section_lease(section)
            if section.failure_count <= len(self.settings.retry_delays_seconds):
                delay = self.settings.retry_delays_seconds[section.failure_count - 1]
                section.status = "pending"
                section.next_attempt_at = now + timedelta(seconds=delay)
                section.finished_at = None
                logger.info(
                    "section_retry_scheduled",
                    extra={
                        "worker_id": self.worker_id,
                        "section_id": section.id,
                        "retry_in_seconds": delay,
                        "failure_count": section.failure_count,
                    },
                )
            else:
                section.status = "failed"
                section.next_attempt_at = None
                section.finished_at = now
            session.commit()

    @staticmethod
    def _clear_section_lease(section: AnalysisSectionRecord) -> None:
        section.locked_by = None
        section.locked_at = None
        section.lease_expires_at = None

    def _refresh_job_status(self, job_id: str) -> None:
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
            if job.cancel_requested:
                for section in job.sections:
                    if section.status == "pending":
                        section.status = "cancelled"
                        section.finished_at = now
                        section.next_attempt_at = None
                        self._clear_section_lease(section)

            states = [section.status for section in job.sections]
            has_active = any(state in {"pending", "running"} for state in states)
            if job.cancel_requested:
                job.status = "running" if "running" in states else "cancelled"
            elif states and all(state == "completed" for state in states):
                job.status = "completed"
            elif "running" in states:
                job.status = "running"
            elif "pending" in states:
                job.status = (
                    "partial"
                    if any(state in {"completed", "failed"} for state in states)
                    else "pending"
                )
            elif "completed" in states:
                job.status = "partial"
            elif "failed" in states:
                job.status = "failed"
            else:
                job.status = "cancelled"

            if job.status in {"completed", "failed", "cancelled"} or (
                job.status == "partial" and not has_active
            ):
                job.finished_at = now
            else:
                job.finished_at = None
            # Job-level lease columns remain for schema compatibility but are no longer used.
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
