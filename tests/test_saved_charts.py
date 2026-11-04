from __future__ import annotations

import asyncio
from dataclasses import replace
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from sqlalchemy import func, select

from app.commerce_models import CardLedger
from app.config import AuthSettings
from app.integrations.wechat import WechatOAuthClient, WechatProfile
from app.main import app
from app.models import AnalysisJobRecord, AnalysisSectionRecord, ChartRecord
from tests import test_payments
from tests.test_payments import account, chart_payload, create

payment_app = test_payments.payment_app


def test_free_chart_persists_without_unlocking_or_debiting(payment_app):
    client, db, _ = payment_app
    payload = {**chart_payload(), "name": "免费命盘", "birth_calendar": "lunar"}
    before = account(client)
    response = client.post("/api/v1/charts", json=payload)
    assert response.status_code == 200, response.text
    assert "no-store" in response.headers["cache-control"]
    chart_id = response.json()["saved_chart_id"]
    assert response.json()["analysis_job_id"] is None
    assert client.post("/api/v1/charts", json=payload).json()["saved_chart_id"] == chart_id
    reports = client.get("/api/v1/me/reports").json()
    assert len(reports) == 1
    assert reports[0]["chart_id"] == chart_id
    assert reports[0]["job_id"] is None
    assert reports[0]["status"] == "locked"
    assert reports[0]["completed_sections"] == 0
    restored = client.get(f"/api/v1/charts/{chart_id}")
    assert "no-store" in restored.headers["cache-control"]
    assert restored.json()["request"]["birth_calendar"] == "lunar"
    assert restored.json()["chart"]["request"]["birth_calendar"] == "lunar"
    assert restored.json()["chart"]["pillars"] == response.json()["pillars"]
    assert "snapshot" not in restored.json()
    assert account(client)["balance"] == before["balance"] == 0
    with db.session() as session:
        assert session.scalar(select(func.count(ChartRecord.id))) == 1
        assert session.scalar(select(func.count(AnalysisJobRecord.id))) == 0
        assert session.scalar(select(func.count(AnalysisSectionRecord.id))) == 0
        assert session.scalar(select(func.count(CardLedger.id))) == 0


def test_unlock_reuses_free_chart_and_debits_only_once(payment_app):
    client, db, _ = payment_app
    chart_id = client.post("/api/v1/charts", json=chart_payload()).json()["saved_chart_id"]
    denied = client.post(f"/api/v1/charts/{chart_id}/analyses")
    assert denied.status_code == 402, denied.text
    assert client.get("/api/v1/me/reports").json()[0]["status"] == "locked"
    order = create(client).json()
    assert client.post(f"/api/v1/payments/orders/{order['id']}/mock-confirm").status_code == 200
    unlocked = client.post(f"/api/v1/charts/{chart_id}/analyses")
    assert unlocked.status_code == 202, unlocked.text
    job = unlocked.json()
    assert job["chart_id"] == chart_id
    assert job["deduplicated"] is False
    # Changing the configured model must not debit an already unlocked chart again.
    app.state.analysis_job_service.settings = replace(
        app.state.analysis_job_service.settings, model_id="different-test-model"
    )
    repeated = client.post(f"/api/v1/charts/{chart_id}/analyses").json()
    assert repeated["job_id"] == job["job_id"]
    assert repeated["deduplicated"] is True
    assert account(client)["balance"] == 0
    assert client.get(f"/api/v1/charts/{chart_id}").json()["job_id"] == job["job_id"]
    reports = client.get("/api/v1/me/reports").json()
    assert len(reports) == 1
    assert reports[0]["job_id"] == job["job_id"]
    assert (
        client.post("/api/v1/charts", json=chart_payload()).json()["analysis_job_id"]
        == job["job_id"]
    )
    assert len(client.get("/api/v1/me/analyses").json()) == 1  # Legacy history still works.
    with db.session() as session:
        assert session.scalar(select(func.count(ChartRecord.id))) == 1
        assert session.scalar(select(func.count(AnalysisJobRecord.id))) == 1
        assert session.scalar(select(func.count(AnalysisSectionRecord.id))) == 8
        assert session.scalar(select(func.count(CardLedger.id))) == 2  # Purchase + debit.


def test_free_chart_is_owned_and_expired_login_cannot_save_anonymous_chart(payment_app):
    client, db, _ = payment_app
    chart_id = client.post("/api/v1/charts", json=chart_payload()).json()["saved_chart_id"]
    cookie = app.state.auth_settings.session_cookie_name
    _, token = app.state.auth_service.login_wechat_user(WechatProfile(openid="another-owner"))
    client.cookies.set(cookie, token)
    assert client.get("/api/v1/me/reports").json() == []
    assert client.get(f"/api/v1/charts/{chart_id}").status_code == 404
    assert client.post(f"/api/v1/charts/{chart_id}/analyses").status_code == 404
    assert client.delete(f"/api/v1/charts/{chart_id}").status_code == 404
    other = client.post("/api/v1/charts", json=chart_payload()).json()["saved_chart_id"]
    assert other != chart_id
    assert client.delete(f"/api/v1/charts/{other}").status_code == 204
    assert client.get("/api/v1/me/reports").json() == []
    assert client.post(f"/api/v1/charts/{other}/analyses").status_code == 404
    client.cookies.clear()
    assert client.post("/api/v1/charts", json=chart_payload()).status_code == 401
    assert client.get(f"/api/v1/charts/{chart_id}").status_code == 401
    with db.session() as session:
        assert session.scalar(select(func.count(ChartRecord.id))) == 1
        assert session.scalar(select(func.count(CardLedger.id))) == 0


def test_automatic_authorize_uses_base_scope_and_manual_default_is_preserved(payment_app):
    client, _, _ = payment_app
    app.state.auth_settings = replace(
        app.state.auth_settings,
        mode="live",
        app_id="wx-test",
        app_secret="test-secret",
        oauth_scope="snsapi_userinfo",
    )
    for params, expected in (({"scope": "snsapi_base"}, "snsapi_base"), ({}, "snsapi_userinfo")):
        response = client.get("/api/v1/auth/wechat/start", params=params, follow_redirects=False)
        assert response.status_code == 302, response.text
        assert parse_qs(urlsplit(response.headers["location"]).query)["scope"] == [expected]
    assert client.get("/api/v1/auth/wechat/start?scope=invalid").status_code == 422


def test_silent_login_reuses_identity_and_keeps_existing_avatar_and_nickname(payment_app):
    client, _, _ = payment_app
    profile = WechatProfile(
        openid="profile-owner", nickname="已授权的昵称", avatar_url="https://avatar.test/owned"
    )
    user, _ = app.state.auth_service.login_wechat_user(profile)
    silent_user, token = app.state.auth_service.login_wechat_user(
        WechatProfile(openid="profile-owner")
    )
    assert silent_user.id == user.id
    assert silent_user.display_name == "已授权的昵称"
    assert silent_user.avatar_url == "https://avatar.test/owned"
    client.cookies.set(app.state.auth_settings.session_cookie_name, token)
    assert client.get("/api/v1/auth/me").json()["user"]["id"] == user.id


@pytest.mark.parametrize("scope,profile_calls", [("snsapi_base", 0), ("snsapi_userinfo", 1)])
def test_callback_uses_wechat_granted_scope_without_erasing_saved_profile(
    monkeypatch, scope, profile_calls
):
    calls = []
    original_client = httpx.AsyncClient

    def handler(request):
        calls.append(request.url.path)
        value = (
            {"openid": "test-openid", "access_token": "test-token", "scope": scope}
            if "access_token" in request.url.path
            else {
                "openid": "test-openid",
                "nickname": "授权昵称",
                "headimgurl": "https://avatar.test/a",
            }
        )
        return httpx.Response(200, json=value)

    monkeypatch.setattr(
        "app.integrations.wechat.httpx.AsyncClient",
        lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    settings = AuthSettings(
        mode="live",
        app_id="wx-test",
        app_secret="test-secret",
        callback_url="https://example.test/api/v1/auth/wechat/callback",
        oauth_scope="snsapi_userinfo",
    )
    profile = asyncio.run(WechatOAuthClient(settings).exchange_code("test-code"))
    assert profile.openid == "test-openid"
    assert calls.count("/sns/userinfo") == profile_calls
    assert profile.nickname == ("授权昵称" if profile_calls else None)
