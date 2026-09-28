from __future__ import annotations

import os

import pytest
from sqlalchemy import delete, inspect
from sqlalchemy.engine import make_url

from app.config import AnalysisQueueSettings
from app.database import Database
from app.models import AnalysisJobRecord, AnalysisSectionRecord, ChartRecord
from app.services.analysis_jobs import canonical_hash
from app.services.analysis_service import ANALYSIS_SECTIONS
from app.worker import AnalysisWorker, utcnow


class UnusedProvider:
    @property
    def model_name(self) -> str:
        return "fake-model"

    async def complete(self, system_prompt: str, user_prompt: str) -> str:
        raise AssertionError("claim test must not call the model")

    async def close(self) -> None:
        pass


@pytest.fixture
def mysql_database():
    database_url = os.getenv("BAZI_TEST_MYSQL_URL", "").strip()
    if not database_url:
        pytest.skip("BAZI_TEST_MYSQL_URL is not configured")
    if not (make_url(database_url).database or "").endswith("_test"):
        pytest.fail("BAZI_TEST_MYSQL_URL must point to a database ending in _test")
    database = Database(database_url)
    with database.session() as session:
        session.execute(delete(ChartRecord))
        session.commit()
    try:
        yield database
    finally:
        with database.session() as session:
            session.execute(delete(ChartRecord))
            session.commit()
        database.dispose()


def test_mysql_schema_and_skip_locked_claim_different_sections(mysql_database: Database) -> None:
    schema = inspect(mysql_database.engine)
    columns = {column["name"] for column in schema.get_columns("analysis_sections")}
    indexes = {index["name"] for index in schema.get_indexes("analysis_sections")}
    assert {
        "failure_count",
        "locked_at",
        "locked_by",
        "lease_expires_at",
        "next_attempt_at",
    } <= columns
    assert {"ix_analysis_sections_queue", "ix_analysis_sections_lease"} <= indexes

    with mysql_database.session() as session:
        chart = ChartRecord(
            request_json={"test": True},
            snapshot_json={"test": True},
            snapshot_hash=canonical_hash("mysql-chart"),
        )
        job = AnalysisJobRecord(
            chart=chart,
            status="pending",
            model_id="fake-model",
            provider="openai-compatible",
            prompt_version="test-prompt-v1",
            rule_version={"test": "1"},
            request_hash=canonical_hash("mysql-job"),
        )
        for position, spec in enumerate(ANALYSIS_SECTIONS):
            job.sections.append(
                AnalysisSectionRecord(
                    code=spec.code,
                    title=spec.title,
                    position=position,
                    status="pending",
                    request_hash=canonical_hash(f"mysql-section-{spec.code}"),
                )
            )
        session.add(job)
        session.commit()

    settings = AnalysisQueueSettings(
        model_id="fake-model", prompt_version="test-prompt-v1", max_attempts=1
    )
    worker = AnalysisWorker(mysql_database, UnusedProvider(), settings)
    now = utcnow()
    statement = worker._claim_statement(now, worker._eligible_job_ids(now))
    first_session = mysql_database.session_factory()
    second_session = mysql_database.session_factory()
    try:
        first = first_session.scalar(statement)
        second = second_session.scalar(statement)
        assert first is not None
        assert second is not None
        assert first.id != second.id
    finally:
        first_session.rollback()
        second_session.rollback()
        first_session.close()
        second_session.close()
