import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.integrations.llm import LLMProviderError, LLMSettings, OpenAICompatibleLLM
from app.main import app
from app.schemas.chart import ChartRequest
from app.services.analysis_service import (
    ANALYSIS_SECTIONS,
    AnalysisService,
    build_model_context,
)


class FakeProvider:
    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.closed = False

    @property
    def model_name(self) -> str:
        return "fake-analysis-model"

    async def complete(self, system_prompt: str, user_prompt: str) -> str:
        assert "不得声称能够确定预测" in system_prompt
        self.prompts.append(user_prompt)
        return "分析内容" * 375

    async def close(self) -> None:
        self.closed = True


def chart_payload(name: str = "隐私姓名") -> dict[str, object]:
    return {
        "name": name,
        "gender": "male",
        "birth_local_datetime": "1988-07-10T12:30",
        "location_id": 3101,
    }


def test_analysis_catalog_contains_the_eight_requested_sections() -> None:
    assert [section.title for section in ANALYSIS_SECTIONS] == [
        "性格特点与行为模式",
        "恋爱情感与婚姻状况预测",
        "子女状况与关系预测",
        "学业发展分析与建议",
        "事业发展预测与建议",
        "财运状况与求财建议",
        "个人健康与灾厄状况预测",
        "大运流年与人生起伏运程",
    ]


def test_persisted_analysis_endpoint_is_optional_without_database(monkeypatch) -> None:
    monkeypatch.delenv("BAZI_DATABASE_URL", raising=False)
    with TestClient(app) as client:
        response = client.post("/api/v1/analyses", json=chart_payload())
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "database_not_configured"


def test_in_process_analysis_service_still_omits_name() -> None:
    provider = FakeProvider()
    with TestClient(app):
        service = AnalysisService(app.state.chart_service, provider, max_concurrency=8)
        result = asyncio.run(service.analyze(ChartRequest.model_validate(chart_payload())))
        asyncio.run(service.close())
    analysis = result["analysis"]
    assert analysis["model"] == "fake-analysis-model"
    assert len(analysis["sections"]) == 8
    assert all(section["char_count"] == 1500 for section in analysis["sections"])
    assert all(section["length_status"] == "ok" for section in analysis["sections"])
    assert analysis["warnings"] == []
    assert len(provider.prompts) == 8
    assert all("隐私姓名" not in prompt for prompt in provider.prompts)
    assert provider.closed


def test_model_context_omits_name_coordinates_and_calculation_trace(monkeypatch) -> None:
    monkeypatch.delenv("BAZI_LLM_API_KEY", raising=False)
    with TestClient(app):
        chart = app.state.chart_service.calculate(ChartRequest.model_validate(chart_payload()))
    context = build_model_context(chart, include_annual_years=False)
    serialized = json.dumps(context, ensure_ascii=False)
    assert "隐私姓名" not in serialized
    assert "longitude" not in serialized
    assert "latitude" not in serialized
    assert "calculation_trace" not in serialized
    assert "annual_years" not in serialized


def test_openai_compatible_client_uses_configured_model_and_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer secret-key"
        payload = json.loads(request.content)
        assert payload["model"] == "deepseek-v4-pro"
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "模型分析结果"}}]},
        )

    async def run() -> None:
        client = httpx.AsyncClient(
            base_url="https://example.test/v1/",
            transport=httpx.MockTransport(handler),
        )
        settings = LLMSettings(
            api_key="secret-key",
            base_url="https://example.test/v1",
            model="deepseek-v4-pro",
        )
        provider = OpenAICompatibleLLM(settings, client=client)
        assert await provider.complete("system", "user") == "模型分析结果"
        await client.aclose()

    asyncio.run(run())


def test_openai_compatible_client_rejects_non_ascii_placeholder_key() -> None:
    async def run() -> None:
        settings = LLMSettings(
            api_key="你的API密钥",
            base_url="https://example.test/v1",
            model="deepseek-chat",
        )
        provider = OpenAICompatibleLLM(settings)
        with pytest.raises(LLMProviderError) as captured:
            await provider.complete("system", "user")
        assert captured.value.code == "llm_invalid_configuration"
        await provider.close()

    asyncio.run(run())
