from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.admin import ADMIN_PATH, AdminReadDatabase, AdminSettings, _timestamp, hash_password
from app.database import Base, Database
from app.main import app
from app.models import AnalysisJobRecord, AnalysisSectionRecord, ChartRecord
from app.schemas.chart import ChartRequest

PASSWORD = "unit-test-admin-password-only"
ORIGIN = "https://admin.example.test"


@pytest.fixture
def admin_app(tmp_path: Path, monkeypatch):
    url = f"sqlite+pysqlite:///{(tmp_path / 'admin_test.sqlite3').as_posix()}"
    monkeypatch.setenv("BAZI_DATABASE_URL", url)
    monkeypatch.setenv("BAZI_ADMIN_ENABLED", "true")
    monkeypatch.setenv("BAZI_ADMIN_USERNAME", "owner")
    monkeypatch.setenv("BAZI_ADMIN_PASSWORD_HASH", hash_password(PASSWORD))
    monkeypatch.setenv("BAZI_ADMIN_DATABASE_URL", url)
    monkeypatch.setenv("BAZI_ADMIN_PUBLIC_ORIGIN", ORIGIN)
    monkeypatch.setenv("BAZI_ADMIN_COOKIE_SECURE", "true")
    monkeypatch.setenv("BAZI_WECHAT_AUTH_MODE", "disabled")
    monkeypatch.setenv("BAZI_PAY_MODE", "disabled")
    writer = Database(url)
    Base.metadata.create_all(writer.engine)
    with TestClient(app, base_url=ORIGIN) as client:
        ids = []
        with writer.session() as session:
            for index, name in enumerate(("示例甲", "示例%乙")):
                request = ChartRequest.model_validate(
                    {
                        "name": name,
                        "gender": "male",
                        "birth_local_datetime": "1988-07-10T12:30",
                        "location_id": 3101,
                    }
                )
                chart = ChartRecord(
                    request_json=request.model_dump(mode="json"),
                    snapshot_json=app.state.chart_service.calculate(request),
                    snapshot_hash=str(index),
                )
                job = AnalysisJobRecord(
                    chart=chart,
                    status="completed" if not index else "partial",
                    model_id="deepseek-flash",
                    provider="test",
                    prompt_version="test-v1",
                    rule_version={},
                    request_hash=str(index),
                    created_at=datetime(2026, 10, 26, 15 if not index else 16, 30),
                )
                job.sections = [
                    AnalysisSectionRecord(
                        code=f"test-{i}",
                        title=f"板块{i}",
                        position=i,
                        request_hash=f"{index}-{i}",
                        status="completed",
                        content=f"保存正文{index}-{i}",
                        char_count=1234,
                        length_status="short",
                        retry_count=1,
                    )
                    for i in range(8)
                ]
                session.add(job)
                session.flush()
                ids.append(job.id)
            session.commit()
        yield client, app.state.admin_service, writer, ids
    writer.dispose()


def login(client):
    return client.post(
        ADMIN_PATH + "/login",
        headers={"Origin": ORIGIN},
        json={
            "username": "owner",
            "password": PASSWORD,
        },
    )


def test_admin_auth_is_independent_and_unauthorized_requests_reveal_no_reports(admin_app):
    client, service, _, ids = admin_app
    client.cookies.set("bazi_session", "fake-customer-session")
    assert client.get(ADMIN_PATH + "/session").json() == {
        "authenticated": False,
        "username": None,
    }
    for path in ("/reports", f"/reports/{ids[0]}"):
        response = client.get(ADMIN_PATH + path)
        assert response.status_code == 401
        assert "保存正文" not in response.text
        assert "private, no-store" in response.headers["cache-control"]
    assert not service._sessions


def test_login_cookie_is_private_logout_revokes_and_no_customer_login_is_granted(admin_app):
    client, service, _, ids = admin_app
    response = login(client)
    assert response.status_code == 200
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=strict" in cookie
    assert f"Path={ADMIN_PATH}" in cookie
    token = client.cookies.get(service.settings.cookie_name)
    assert token not in service._sessions
    assert PASSWORD not in response.text
    assert client.get(ADMIN_PATH + f"/reports/{ids[0]}").status_code == 200
    assert client.get("/api/v1/auth/me").json()["authenticated"] is False
    assert client.post(ADMIN_PATH + "/logout", headers={"Origin": ORIGIN}).status_code == 204
    assert not service.authenticated(token)
    assert (
        client.get(
            ADMIN_PATH + "/reports",
            headers={
                "Cookie": f"{service.settings.cookie_name}={token}",
            },
        ).status_code
        == 401
    )


def test_login_csrf_bad_input_and_passwords_are_not_echoed(admin_app):
    client, _, _, _ = admin_app
    assert (
        client.post(
            ADMIN_PATH + "/login",
            json={
                "username": "owner",
                "password": PASSWORD,
            },
        ).status_code
        == 403
    )
    assert (
        client.post(
            ADMIN_PATH + "/login",
            headers={"Origin": "https://evil.test"},
            json={
                "username": "owner",
                "password": PASSWORD,
            },
        ).status_code
        == 403
    )
    for password in (None, [], {"value": "PASSWORD_SENTINEL"}, "PASSWORD_SENTINEL"):
        response = client.post(
            ADMIN_PATH + "/login",
            headers={"Origin": ORIGIN},
            json={
                "username": "owner",
                "password": password,
            },
        )
        assert response.status_code == 401
        assert "PASSWORD_SENTINEL" not in response.text
    huge = client.post(
        ADMIN_PATH + "/login",
        headers={"Origin": ORIGIN},
        json={
            "username": "owner",
            "password": "a" * 5000,
        },
    )
    assert huge.status_code == 413


def test_wrong_password_rate_limit_and_absolute_session_expiry(admin_app, monkeypatch):
    client, service, _, _ = admin_app
    for _ in range(5):
        assert (
            client.post(
                ADMIN_PATH + "/login",
                headers={"Origin": ORIGIN},
                json={
                    "username": "owner",
                    "password": "wrong",
                },
            ).status_code
            == 401
        )
    assert login(client).status_code == 429
    service._failures.clear()
    assert login(client).status_code == 200
    token = client.cookies.get(service.settings.cookie_name)
    service._sessions[service._token_hash(token)] = 0
    assert client.get(ADMIN_PATH + "/reports").status_code == 401


def test_reports_filters_beijing_dates_and_details_have_no_auth_or_payment_secrets(admin_app):
    client, _, _, ids = admin_app
    login(client)
    response = client.get(ADMIN_PATH + "/reports")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert data["items"][0]["id"] == ids[1]
    assert all(item["completed_sections"] == 8 for item in data["items"])
    assert all("content" not in item and "chart" not in item for item in data["items"])
    assert client.get(ADMIN_PATH + "/reports", params={"q": "示例甲"}).json()["total"] == 1
    assert client.get(ADMIN_PATH + "/reports", params={"q": "%"}).json()["total"] == 1
    assert client.get(ADMIN_PATH + "/reports", params={"q": "' OR 1=1 --"}).json()["total"] == 0
    assert client.get(ADMIN_PATH + "/reports", params={"status": "partial"}).json()["total"] == 1
    dates = client.get(ADMIN_PATH + "/reports", params={"start": "2026-10-26", "end": "2026-10-26"})
    assert [item["id"] for item in dates.json()["items"]] == [ids[0]]
    detail = client.get(ADMIN_PATH + f"/reports/{ids[0]}").json()
    assert len(detail["sections"]) == 8
    assert detail["sections"][0]["content"] == "保存正文0-0"
    assert detail["request"]["name"] == "示例甲"
    assert detail["created_at"].endswith("+00:00")
    for forbidden in ("openid", "token_hash", "password_hash", "prepay_id", "api_key"):
        assert forbidden not in str(detail).lower()
    assert client.get(ADMIN_PATH + "/reports/missing").status_code == 404
    assert (
        client.get(
            ADMIN_PATH + "/reports", params={"start": "2026-11-01", "end": "2026-10-01"}
        ).status_code
        == 422
    )


def test_admin_routes_and_database_are_actually_readonly(admin_app):
    client, service, writer, ids = admin_app
    login(client)
    for method in ("post", "patch", "put", "delete"):
        assert getattr(client, method)(ADMIN_PATH + f"/reports/{ids[0]}").status_code == 405
    with service.database.session() as session:
        with pytest.raises(RuntimeError, match="SELECT"):
            session.execute(text("DELETE FROM analysis_jobs"))
    with writer.session() as session:
        assert len(session.scalars(select(AnalysisJobRecord)).all()) == 2
    # Even bypassing the SQLAlchemy guard cannot write through SQLite query_only.
    connection = service.database.engine.raw_connection()
    try:
        with pytest.raises(Exception, match="readonly"):
            connection.cursor().execute("DELETE FROM analysis_jobs")
    finally:
        connection.close()


def test_admin_default_disabled_or_bad_configuration_does_not_break_customer_api(monkeypatch):
    monkeypatch.setenv("BAZI_ADMIN_ENABLED", "true")
    monkeypatch.setenv("BAZI_ADMIN_PASSWORD_HASH", "bad")
    with TestClient(app) as client:
        assert client.get(ADMIN_PATH + "/session").status_code == 503
        assert client.get("/health/live").status_code == 200
    monkeypatch.setenv("BAZI_ADMIN_ENABLED", "false")
    with TestClient(app) as client:
        assert client.get(ADMIN_PATH + "/reports").status_code == 503


def test_admin_cannot_reuse_the_application_database_account():
    settings = AdminSettings(
        username="owner",
        password_hash=hash_password(PASSWORD),
        database_url="mysql+pymysql://bazi:placeholder@mysql:3306/bazi",
        public_origin=ORIGIN,
    )
    with pytest.raises(ValueError, match="dedicated"):
        settings.validate()


def test_read_database_rejects_schema_changes(tmp_path):
    database = AdminReadDatabase(f"sqlite+pysqlite:///{tmp_path / 'readonly.sqlite3'}")
    try:
        with database.session() as session:
            with pytest.raises(RuntimeError, match="SELECT"):
                session.execute(text("CREATE TABLE should_not_exist (id INTEGER)"))
    finally:
        database.dispose()


def test_admin_report_pagination_and_invalid_date_limits(admin_app):
    client, _, writer, _ = admin_app
    with writer.session() as session:
        chart = session.scalar(select(ChartRecord))
        for i in range(21):
            session.add(
                AnalysisJobRecord(
                    chart=chart,
                    status="pending",
                    model_id="test",
                    provider="test",
                    prompt_version="test-v1",
                    rule_version={},
                    request_hash=f"page-{i}",
                )
            )
        session.commit()
    login(client)
    one = client.get(ADMIN_PATH + "/reports").json()
    two = client.get(ADMIN_PATH + "/reports", params={"page": 2}).json()
    assert one["total"] == 23 and len(one["items"]) == 20
    assert two["total"] == 23 and len(two["items"]) == 3
    assert not set(x["id"] for x in one["items"]) & set(x["id"] for x in two["items"])
    for params in ({"end": "9999-12-31"}, {"start": "0001-01-01"}, {"start": "bad"}):
        response = client.get(ADMIN_PATH + "/reports", params=params)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "admin_filter_invalid"


def test_bad_admin_database_url_does_not_stop_customer_service(monkeypatch):
    monkeypatch.setenv("BAZI_ADMIN_ENABLED", "true")
    monkeypatch.setenv("BAZI_ADMIN_USERNAME", "owner")
    monkeypatch.setenv("BAZI_ADMIN_PASSWORD_HASH", hash_password(PASSWORD))
    monkeypatch.setenv("BAZI_ADMIN_DATABASE_URL", "not-a-database-url")
    monkeypatch.setenv("BAZI_ADMIN_PUBLIC_ORIGIN", ORIGIN)
    with TestClient(app) as client:
        assert client.get("/health/live").status_code == 200
        assert client.get(ADMIN_PATH + "/session").status_code == 503


def test_mysql_local_creation_times_and_utc_finish_times_are_not_mixed(admin_app, monkeypatch):
    from zoneinfo import ZoneInfo

    client, service, writer, ids = admin_app
    zone = ZoneInfo("Asia/Shanghai")
    monkeypatch.setattr(service, "_created_zone", lambda session: zone)
    with writer.session() as session:
        session.get(AnalysisJobRecord, ids[0]).created_at = datetime(2026, 10, 26, 23, 30)
        session.get(AnalysisJobRecord, ids[0]).finished_at = datetime(2026, 10, 26, 15, 35)
        session.get(AnalysisJobRecord, ids[1]).created_at = datetime(2026, 10, 27, 0, 30)
        session.commit()
    login(client)
    rows = client.get(
        ADMIN_PATH + "/reports",
        params={
            "start": "2026-10-26",
            "end": "2026-10-26",
        },
    ).json()["items"]
    assert [row["id"] for row in rows] == [ids[0]]
    detail = client.get(ADMIN_PATH + f"/reports/{ids[0]}").json()
    assert detail["created_at"] == "2026-10-26T15:30:00+00:00"
    assert detail["finished_at"] == "2026-10-26T15:35:00+00:00"
    assert _timestamp(datetime(2026, 10, 26, 15, 35, tzinfo=UTC), zone) == detail["finished_at"]
