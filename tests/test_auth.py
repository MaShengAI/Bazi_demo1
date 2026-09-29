from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import Base, Database
from app.integrations.wechat import WechatProfile
from app.main import app
from app.models import ChartRecord


def chart_payload(
    name: str = "微信登录测试", birth_local_datetime: str = "1992-08-18T09:30"
) -> dict[str, object]:
    return {
        "name": name,
        "gender": "female",
        "birth_local_datetime": birth_local_datetime,
        "location_id": 3101,
    }


@pytest.fixture
def auth_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'auth.sqlite3').as_posix()}"
    monkeypatch.setenv("BAZI_DATABASE_URL", database_url)
    monkeypatch.setenv("BAZI_LLM_MODEL", "fake-model")
    monkeypatch.setenv("BAZI_WECHAT_AUTH_MODE", "mock")
    monkeypatch.setenv(
        "BAZI_WECHAT_OAUTH_CALLBACK_URL",
        "http://testserver/api/v1/auth/wechat/callback",
    )
    monkeypatch.setenv("BAZI_SESSION_COOKIE_SECURE", "false")
    monkeypatch.setenv("BAZI_AUTH_REQUIRED_FOR_ANALYSIS", "true")
    monkeypatch.setenv("BAZI_USER_ANALYSIS_LIMIT_PER_24H", "2")
    bootstrap = Database(database_url)
    Base.metadata.create_all(bootstrap.engine)
    bootstrap.dispose()
    with TestClient(app) as client:
        yield client, app.state.database


def login(client: TestClient, return_to: str = "/#analysis") -> str:
    started = client.get(
        "/api/v1/auth/wechat/start",
        params={"return_to": return_to},
        follow_redirects=False,
    )
    assert started.status_code == 302
    callback_url = started.headers["location"]
    callback = client.get(callback_url, follow_redirects=False)
    assert callback.status_code == 302
    assert callback.headers["location"] == return_to
    assert "HttpOnly" in callback.headers["set-cookie"]
    return callback_url


def test_mock_wechat_login_session_and_logout(auth_app) -> None:
    client, _ = auth_app
    before = client.get("/api/v1/auth/me").json()
    assert before == {
        "enabled": True,
        "authenticated": False,
        "require_for_analysis": True,
        "analysis_limit_per_24h": 2,
        "user": None,
    }

    login(client)
    after = client.get("/api/v1/auth/me").json()
    assert after["authenticated"] is True
    assert after["user"]["display_name"] == "测试微信用户"

    logged_out = client.post("/api/v1/auth/logout")
    assert logged_out.status_code == 204
    assert client.get("/api/v1/auth/me").json()["authenticated"] is False


def test_oauth_state_is_one_time_and_return_url_is_local(auth_app) -> None:
    client, _ = auth_app
    started = client.get(
        "/api/v1/auth/wechat/start",
        params={"return_to": "https://evil.example/steal"},
        follow_redirects=False,
    )
    callback_url = started.headers["location"]
    callback = client.get(callback_url, follow_redirects=False)
    assert callback.headers["location"] == "/"

    replay = client.get(callback_url, follow_redirects=False)
    assert replay.status_code == 400
    assert replay.json()["error"]["code"] == "invalid_oauth_state"

    query = parse_qs(urlsplit(callback_url).query)
    assert query["state"][0]

    backslash = client.get(
        "/api/v1/auth/wechat/start",
        params={"return_to": "/\\evil.example"},
        follow_redirects=False,
    )
    sanitized = client.get(backslash.headers["location"], follow_redirects=False)
    assert sanitized.headers["location"] == "/"


def test_analysis_requires_login_and_is_owned_by_current_user(auth_app) -> None:
    client, database = auth_app
    rejected = client.post("/api/v1/analyses", json=chart_payload())
    assert rejected.status_code == 401
    assert rejected.json()["error"]["code"] == "authentication_required"

    login(client)
    accepted = client.post("/api/v1/analyses", json=chart_payload())
    assert accepted.status_code == 202
    job_id = accepted.json()["job_id"]

    history = client.get("/api/v1/me/analyses")
    assert history.status_code == 200
    assert history.json()[0]["job_id"] == job_id
    assert history.json()[0]["name"] == "微信登录测试"

    with database.session() as session:
        chart = session.scalar(select(ChartRecord))
        assert chart is not None
        assert chart.user_id is not None

    _, second_token = app.state.auth_service.login_wechat_user(
        WechatProfile(openid="different-openid", nickname="另一个用户")
    )
    client.cookies.set("bazi_session", second_token)
    hidden = client.get(f"/api/v1/analyses/{job_id}")
    assert hidden.status_code == 404


def test_authenticated_deduplication_is_scoped_to_user(auth_app) -> None:
    client, _ = auth_app
    login(client)
    first = client.post("/api/v1/analyses", json=chart_payload())
    duplicate = client.post("/api/v1/analyses", json=chart_payload())
    assert duplicate.json()["job_id"] == first.json()["job_id"]
    assert duplicate.json()["deduplicated"] is True

    _, second_token = app.state.auth_service.login_wechat_user(
        WechatProfile(openid="second-dedup-user")
    )
    client.cookies.set("bazi_session", second_token)
    separate = client.post("/api/v1/analyses", json=chart_payload())
    assert separate.status_code == 202
    assert separate.json()["job_id"] != first.json()["job_id"]
    assert separate.json()["deduplicated"] is False


def test_per_user_24_hour_limit_does_not_block_existing_deduplicated_report(auth_app) -> None:
    client, _ = auth_app
    login(client)
    first = client.post("/api/v1/analyses", json=chart_payload("第一份", "1992-08-18T09:30"))
    second = client.post("/api/v1/analyses", json=chart_payload("第二份", "1993-08-18T09:30"))
    assert first.status_code == second.status_code == 202

    duplicate = client.post("/api/v1/analyses", json=chart_payload("第一份", "1992-08-18T09:30"))
    assert duplicate.status_code == 202
    assert duplicate.json()["deduplicated"] is True

    limited = client.post("/api/v1/analyses", json=chart_payload("第三份", "1994-08-18T09:30"))
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "daily_analysis_limit_reached"
