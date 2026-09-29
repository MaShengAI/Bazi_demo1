import asyncio
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import selectinload

from app.config import AnalysisQueueSettings
from app.database import Base, Database
from app.integrations.llm import LLMCompletion, LLMProviderError
from app.main import app
from app.models import AnalysisJobRecord, AnalysisSectionRecord, LLMCallLogRecord
from app.services.analysis_service import ANALYSIS_SECTIONS
from app.worker import AnalysisWorker, utcnow


def chart_payload() -> dict[str, object]:
    return {
        "name": "待删除姓名",
        "gender": "male",
        "birth_local_datetime": "1988-07-10T12:30",
        "location_id": 3101,
    }


class FakeDetailedProvider:
    def __init__(self, fail_codes: set[str] | None = None):
        self.fail_codes = fail_codes or set()
        self.calls: list[str] = []
        self.closed = False

    @property
    def model_name(self) -> str:
        return "fake-model"

    async def complete_detailed(self, system_prompt: str, user_prompt: str) -> LLMCompletion:
        assert "不得声称能够确定预测" in system_prompt
        self.calls.append(user_prompt)
        for spec in ANALYSIS_SECTIONS:
            if f"本次板块：{spec.title}" in user_prompt and spec.code in self.fail_codes:
                raise LLMProviderError("fake_failure", "模拟模型失败")
        return LLMCompletion(
            content="分析内容" * 375,
            prompt_tokens=100,
            completion_tokens=500,
            total_tokens=600,
            request_id=f"req-{len(self.calls)}",
        )

    async def complete(self, system_prompt: str, user_prompt: str) -> str:
        return (await self.complete_detailed(system_prompt, user_prompt)).content

    async def close(self) -> None:
        self.closed = True


async def drain_worker(worker: AnalysisWorker, limit: int = 20) -> int:
    processed = 0
    while processed < limit and await worker.run_once():
        processed += 1
    return processed


@pytest.fixture
def persisted_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'analysis.sqlite3').as_posix()}"
    monkeypatch.setenv("BAZI_DATABASE_URL", database_url)
    monkeypatch.setenv("BAZI_LLM_MODEL", "fake-model")
    monkeypatch.setenv("BAZI_ANALYSIS_PROMPT_VERSION", "test-prompt-v1")
    bootstrap = Database(database_url)
    Base.metadata.create_all(bootstrap.engine)
    bootstrap.dispose()
    with TestClient(app) as client:
        yield client, app.state.database


def test_submit_is_202_persisted_and_deduplicated(persisted_app) -> None:
    client, _ = persisted_app
    first = client.post("/api/v1/analyses", json=chart_payload())
    second = client.post("/api/v1/analyses", json=chart_payload())

    assert first.status_code == 202
    assert first.json()["status"] == "pending"
    assert second.status_code == 202
    assert second.json()["job_id"] == first.json()["job_id"]
    assert second.json()["deduplicated"] is True

    status = client.get(f"/api/v1/analyses/{first.json()['job_id']}/status")
    result = client.get(f"/api/v1/analyses/{first.json()['job_id']}")
    assert status.status_code == 200
    assert status.json()["total_sections"] == 8
    assert len(result.json()["sections"]) == 8
    assert all(section["status"] == "pending" for section in result.json()["sections"])


def test_submit_schedules_sections_with_application_utc(persisted_app) -> None:
    client, database = persisted_app
    before = datetime.now(UTC)

    accepted = client.post("/api/v1/analyses", json=chart_payload()).json()

    with database.session() as session:
        sections = session.scalars(
            select(AnalysisSectionRecord).where(AnalysisSectionRecord.job_id == accepted["job_id"])
        ).all()
        assert len(sections) == 8
        for section in sections:
            assert section.next_attempt_at is not None
            scheduled_at = section.next_attempt_at
            if scheduled_at.tzinfo is None:
                scheduled_at = scheduled_at.replace(tzinfo=UTC)
            assert before <= scheduled_at <= datetime.now(UTC)


def test_worker_completes_and_logs_only_safe_metadata(persisted_app) -> None:
    client, database = persisted_app
    accepted = client.post("/api/v1/analyses", json=chart_payload()).json()
    provider = FakeDetailedProvider()
    worker = AnalysisWorker(
        database,
        provider,
        AnalysisQueueSettings(
            model_id="fake-model", prompt_version="test-prompt-v1", max_attempts=1
        ),
        worker_id="test-worker",
    )

    assert asyncio.run(drain_worker(worker)) == 8
    result = client.get(f"/api/v1/analyses/{accepted['job_id']}").json()
    assert result["status"] == "completed"
    assert result["completed_sections"] == 8
    assert all(section["char_count"] == 1500 for section in result["sections"])

    with database.session() as session:
        logs = session.scalars(select(LLMCallLogRecord)).all()
        assert len(logs) == 8
        assert all(log.latency_ms is not None for log in logs)
        assert all(log.total_tokens == 600 for log in logs)
        assert all(
            log.provider_request_id and log.provider_request_id.startswith("req-") for log in logs
        )
        serialized = " ".join(str(log.__dict__) for log in logs)
        assert "api_key" not in serialized.lower()
        assert "authorization" not in serialized.lower()


def test_partial_result_survives_and_failed_section_can_retry(persisted_app) -> None:
    client, database = persisted_app
    accepted = client.post("/api/v1/analyses", json=chart_payload()).json()
    first_worker = AnalysisWorker(
        database,
        FakeDetailedProvider({"wealth"}),
        AnalysisQueueSettings(
            model_id="fake-model",
            prompt_version="test-prompt-v1",
            max_attempts=1,
            retry_delays_seconds=(),
        ),
    )
    assert asyncio.run(drain_worker(first_worker)) == 8

    partial = client.get(f"/api/v1/analyses/{accepted['job_id']}").json()
    assert partial["status"] == "partial"
    wealth = next(section for section in partial["sections"] if section["code"] == "wealth")
    assert wealth["status"] == "failed"
    assert partial["completed_sections"] == 7

    retry = client.post(f"/api/v1/analyses/{accepted['job_id']}/sections/wealth/retry")
    assert retry.status_code == 202
    second_worker = AnalysisWorker(
        database,
        FakeDetailedProvider(),
        AnalysisQueueSettings(
            model_id="fake-model", prompt_version="test-prompt-v1", max_attempts=1
        ),
    )
    asyncio.run(second_worker.run_once())

    completed = client.get(f"/api/v1/analyses/{accepted['job_id']}").json()
    assert completed["status"] == "completed"
    retried = next(section for section in completed["sections"] if section["code"] == "wealth")
    assert retried["retry_count"] == 1
    assert all(section["content"] for section in completed["sections"])


def test_worker_recovers_expired_running_task(persisted_app) -> None:
    client, database = persisted_app
    accepted = client.post("/api/v1/analyses", json=chart_payload()).json()
    with database.session() as session:
        job = session.scalar(
            select(AnalysisJobRecord)
            .where(AnalysisJobRecord.id == accepted["job_id"])
            .options(selectinload(AnalysisJobRecord.sections))
        )
        assert job is not None
        section = job.sections[0]
        section.status = "running"
        section.locked_by = "dead-worker"
        section.locked_at = utcnow() - timedelta(minutes=10)
        section.lease_expires_at = utcnow() - timedelta(seconds=1)
        session.commit()

    worker = AnalysisWorker(
        database,
        FakeDetailedProvider(),
        AnalysisQueueSettings(
            model_id="fake-model", prompt_version="test-prompt-v1", max_attempts=1
        ),
    )
    assert worker.recover_expired_leases() == 1
    assert asyncio.run(drain_worker(worker)) == 8
    assert client.get(f"/api/v1/analyses/{accepted['job_id']}").json()["status"] == "completed"


def test_workers_claim_independent_sections_with_mysql_skip_locked(persisted_app) -> None:
    client, database = persisted_app
    client.post("/api/v1/analyses", json=chart_payload())
    settings = AnalysisQueueSettings(
        model_id="fake-model", prompt_version="test-prompt-v1", max_attempts=1
    )
    first = AnalysisWorker(database, FakeDetailedProvider(), settings, worker_id="worker-one")
    second = AnalysisWorker(database, FakeDetailedProvider(), settings, worker_id="worker-two")

    first_claim = first._claim_section()
    second_claim = second._claim_section()

    assert first_claim is not None
    assert second_claim is not None
    assert first_claim[1] != second_claim[1]
    with database.session() as session:
        running = session.scalars(
            select(AnalysisSectionRecord).where(AnalysisSectionRecord.status == "running")
        ).all()
        assert {section.locked_by for section in running} == {"worker-one", "worker-two"}
        assert all(section.locked_at and section.lease_expires_at for section in running)

    job_sql = str(first._claim_job_statement(utcnow()).compile(dialect=mysql.dialect()))
    section_sql = str(
        first._claim_statement(utcnow(), first_claim[0]).compile(dialect=mysql.dialect())
    )
    assert "FOR UPDATE SKIP LOCKED" in job_sql
    assert "FOR UPDATE SKIP LOCKED" in section_sql


def test_claims_are_fair_and_capped_at_four_sections_per_job(persisted_app) -> None:
    client, database = persisted_app
    job_ids = []
    for index in range(3):
        payload = chart_payload()
        payload["name"] = f"公平调度测试{index}"
        job_ids.append(client.post("/api/v1/analyses", json=payload).json()["job_id"])

    worker = AnalysisWorker(
        database,
        FakeDetailedProvider(),
        AnalysisQueueSettings(
            model_id="fake-model",
            prompt_version="test-prompt-v1",
            max_attempts=1,
            max_running_sections_per_job=4,
        ),
        worker_id="fair-worker",
    )
    claims = [worker._claim_section() for _ in range(12)]

    assert all(claim is not None for claim in claims)
    counts = Counter(claim[0] for claim in claims if claim is not None)
    assert counts == Counter({job_id: 4 for job_id in job_ids})
    assert worker._claim_section() is None


def test_provider_failures_use_30_60_120_second_queue_backoff(persisted_app) -> None:
    client, database = persisted_app
    accepted = client.post("/api/v1/analyses", json=chart_payload()).json()
    with database.session() as session:
        job = session.scalar(
            select(AnalysisJobRecord)
            .where(AnalysisJobRecord.id == accepted["job_id"])
            .options(selectinload(AnalysisJobRecord.sections))
        )
        assert job is not None
        for section in job.sections:
            if section.code != "personality":
                section.status = "cancelled"
        session.commit()

    worker = AnalysisWorker(
        database,
        FakeDetailedProvider({"personality"}),
        AnalysisQueueSettings(
            model_id="fake-model",
            prompt_version="test-prompt-v1",
            max_attempts=1,
            retry_delays_seconds=(30, 60, 120),
        ),
    )

    for failure_count, delay in enumerate((30, 60, 120), 1):
        before = utcnow()
        assert asyncio.run(worker.run_once()) is True
        with database.session() as session:
            section = session.scalar(
                select(AnalysisSectionRecord).where(
                    AnalysisSectionRecord.job_id == accepted["job_id"],
                    AnalysisSectionRecord.code == "personality",
                )
            )
            assert section is not None
            assert section.status == "pending"
            assert section.failure_count == failure_count
            assert section.next_attempt_at is not None
            scheduled_delay = (
                section.next_attempt_at - before.replace(tzinfo=None)
            ).total_seconds()
            assert delay - 1 <= scheduled_delay <= delay + 1
            section.next_attempt_at = utcnow() - timedelta(seconds=1)
            session.commit()

    assert asyncio.run(worker.run_once()) is True
    with database.session() as session:
        section = session.scalar(
            select(AnalysisSectionRecord).where(
                AnalysisSectionRecord.job_id == accepted["job_id"],
                AnalysisSectionRecord.code == "personality",
            )
        )
        assert section is not None
        assert section.status == "failed"
        assert section.failure_count == 4
        assert section.next_attempt_at is None
        assert section.locked_by is None
        assert section.lease_expires_at is None
        assert section.retry_count == 3


def test_cancel_and_delete_birth_data_with_cascade(persisted_app) -> None:
    client, database = persisted_app
    accepted = client.post("/api/v1/analyses", json=chart_payload()).json()
    cancelled = client.post(f"/api/v1/analyses/{accepted['job_id']}/cancel")
    assert cancelled.status_code == 202
    assert cancelled.json()["status"] == "cancelled"

    deleted = client.delete(f"/api/v1/charts/{accepted['chart_id']}")
    assert deleted.status_code == 204
    assert client.get(f"/api/v1/analyses/{accepted['job_id']}").status_code == 404
    with database.session() as session:
        assert session.scalar(select(AnalysisSectionRecord)) is None
        assert session.scalar(select(LLMCallLogRecord)) is None


def test_alembic_migration_creates_the_four_core_tables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'migration.sqlite3').as_posix()}"
    monkeypatch.setenv("BAZI_DATABASE_URL", database_url)
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    database = Database(database_url)
    try:
        tables = set(inspect(database.engine).get_table_names())
        section_columns = {
            column["name"] for column in inspect(database.engine).get_columns("analysis_sections")
        }
    finally:
        database.dispose()
    assert {"charts", "analysis_jobs", "analysis_sections", "llm_call_logs"} <= tables
    assert {
        "failure_count",
        "locked_at",
        "locked_by",
        "lease_expires_at",
        "next_attempt_at",
    } <= section_columns
