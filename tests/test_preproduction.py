import json
import logging

from fastapi.testclient import TestClient

from app.main import app
from app.observability import JsonFormatter, redact

CHART_REQUEST = {
    "name": "降级测试",
    "gender": "male",
    "birth_local_datetime": "1988-07-10T12:30",
    "location_id": 3101,
}


def test_request_id_is_returned_and_untrusted_value_is_replaced(monkeypatch) -> None:
    monkeypatch.delenv("BAZI_DATABASE_URL", raising=False)
    with TestClient(app) as client:
        accepted = client.get("/health/live", headers={"X-Request-ID": "wechat-test-123"})
        rejected = client.get("/health/live", headers={"X-Request-ID": "bad value\nsecret"})
    assert accepted.headers["X-Request-ID"] == "wechat-test-123"
    assert rejected.headers["X-Request-ID"] != "bad value\nsecret"
    assert len(rejected.headers["X-Request-ID"]) == 32


def test_readiness_reports_optional_database_without_breaking_liveness(monkeypatch) -> None:
    monkeypatch.delenv("BAZI_DATABASE_URL", raising=False)
    with TestClient(app) as client:
        assert client.get("/health/live").status_code == 200
        ready = client.get("/health/ready")
    assert ready.status_code == 200
    assert ready.json() == {
        "status": "degraded",
        "api": "ok",
        "database": "not_configured",
    }


def test_plain_chart_works_when_mysql_ai_and_worker_are_unavailable(monkeypatch) -> None:
    monkeypatch.setenv(
        "BAZI_DATABASE_URL",
        "mysql+pymysql://unused:unused@127.0.0.1:9/bazi?connect_timeout=1",
    )
    monkeypatch.delenv("BAZI_LLM_API_KEY", raising=False)
    with TestClient(app) as client:
        chart = client.post("/api/v1/charts", json=CHART_REQUEST)
        readiness = client.get("/health/ready")
        analysis = client.post("/api/v1/analyses", json=CHART_REQUEST)
    assert chart.status_code == 200, chart.text
    assert chart.json()["pillars"]["day"]["pillar"] == "丙寅"
    assert readiness.status_code == 503
    assert readiness.json()["database"] == "unavailable"
    assert analysis.status_code == 503
    assert analysis.json()["error"]["code"] == "database_unavailable"


def test_structured_log_redacts_credentials() -> None:
    assert redact("Bearer sk-1234567890abcdef") == "Bearer [REDACTED]"
    assert redact("mysql+pymysql://user:super-secret@mysql:3306/bazi") == (
        "mysql+pymysql://user:[REDACTED]@mysql:3306/bazi"
    )
    record = logging.LogRecord(
        "bazi.test",
        logging.INFO,
        __file__,
        1,
        "key sk-1234567890abcdef",
        (),
        None,
    )
    record.job_id = "job-123"
    record.authorization = "Bearer token-value"
    payload = json.loads(JsonFormatter().format(record))
    assert payload["job_id"] == "job-123"
    assert payload["authorization"] == "[REDACTED]"
    assert "sk-1234567890abcdef" not in json.dumps(payload)
