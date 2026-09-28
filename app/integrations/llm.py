from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol

import httpx


class LLMProviderError(RuntimeError):
    """可安全转换为 API 错误、且不会泄露密钥或上游响应正文的异常。"""

    def __init__(self, code: str, message: str, details: dict[str, object] | None = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


@dataclass(frozen=True)
class LLMCompletion:
    content: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    request_id: str | None = None


@dataclass(frozen=True)
class LLMSettings:
    api_key: str
    base_url: str
    model: str
    timeout_seconds: float = 240.0
    max_output_tokens: int = 2600
    temperature: float = 0.35
    max_concurrency: int = 2

    @classmethod
    def from_env(cls) -> LLMSettings | None:
        """没有密钥时仅禁用分析接口；其他排盘接口仍可正常启动。"""
        api_key = os.getenv("BAZI_LLM_API_KEY", "").strip()
        if not api_key:
            return None
        return cls(
            api_key=api_key,
            base_url=os.getenv("BAZI_LLM_BASE_URL", "https://api.deepseek.com").strip(),
            model=os.getenv("BAZI_LLM_MODEL", "deepseek-chat").strip(),
            timeout_seconds=_float_env("BAZI_LLM_TIMEOUT_SECONDS", 240.0, 10.0, 600.0),
            max_output_tokens=_int_env("BAZI_LLM_MAX_OUTPUT_TOKENS", 2600, 1200, 65536),
            temperature=_float_env("BAZI_LLM_TEMPERATURE", 0.35, 0.0, 1.5),
            max_concurrency=_int_env("BAZI_LLM_MAX_CONCURRENCY", 2, 1, 8),
        )


def _int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name)
    try:
        value = default if raw is None else int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _float_env(name: str, default: float, minimum: float, maximum: float) -> float:
    raw = os.getenv(name)
    try:
        value = default if raw is None else float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


class LLMProvider(Protocol):
    @property
    def model_name(self) -> str: ...

    async def complete(self, system_prompt: str, user_prompt: str) -> str: ...

    async def close(self) -> None: ...


class OpenAICompatibleLLM:
    """兼容 DeepSeek、OpenAI 等 `/chat/completions` 协议的异步客户端。"""

    def __init__(self, settings: LLMSettings, client: httpx.AsyncClient | None = None):
        self.settings = settings
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=f"{settings.base_url.rstrip('/')}/",
            headers={"Content-Type": "application/json"},
            timeout=httpx.Timeout(settings.timeout_seconds),
        )

    @property
    def model_name(self) -> str:
        return self.settings.model

    async def complete(self, system_prompt: str, user_prompt: str) -> str:
        return (await self.complete_detailed(system_prompt, user_prompt)).content

    async def complete_detailed(self, system_prompt: str, user_prompt: str) -> LLMCompletion:
        try:
            authorization = f"Bearer {self.settings.api_key}"
            authorization.encode("ascii")
        except UnicodeEncodeError as exc:
            raise LLMProviderError(
                "llm_invalid_configuration",
                "BAZI_LLM_API_KEY包含非ASCII字符，请配置模型服务商提供的真实API密钥",
            ) from exc
        payload = {
            "model": self.settings.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "thinking": {"type": "enabled"},
            "reasoning_effort": "high",
            "max_tokens": self.settings.max_output_tokens,
            "stream": False,
        }
        try:
            response = await self._client.post(
                "chat/completions",
                json=payload,
                headers={"Authorization": authorization},
            )
        except httpx.TimeoutException as exc:
            raise LLMProviderError("llm_timeout", "AI模型响应超时") from exc
        except httpx.HTTPError as exc:
            raise LLMProviderError("llm_unavailable", "无法连接AI模型服务") from exc
        if response.is_error:
            raise LLMProviderError(
                "llm_http_error",
                "AI模型服务返回错误",
                {
                    "status_code": response.status_code,
                    "request_id": response.headers.get("x-request-id"),
                },
            )
        try:
            data = response.json()
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise LLMProviderError("llm_invalid_response", "AI模型返回格式无效") from exc
        if not isinstance(content, str) or not content.strip():
            raise LLMProviderError("llm_empty_response", "AI模型没有返回分析内容")
        usage = data.get("usage") if isinstance(data, dict) else None
        if not isinstance(usage, dict):
            usage = {}
        request_id = response.headers.get("x-request-id")
        if request_id is None and isinstance(data, dict) and isinstance(data.get("id"), str):
            request_id = data["id"]
        return LLMCompletion(
            content=content.strip(),
            prompt_tokens=_optional_int(usage.get("prompt_tokens")),
            completion_tokens=_optional_int(usage.get("completion_tokens")),
            total_tokens=_optional_int(usage.get("total_tokens")),
            request_id=request_id,
        )

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and value >= 0 else None
