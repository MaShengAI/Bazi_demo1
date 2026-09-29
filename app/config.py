from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class AnalysisQueueSettings:
    """Non-secret settings shared by the API process and worker."""

    model_id: str
    provider: str = "openai-compatible"
    prompt_version: str = "bazi-analysis-1.0.0"
    worker_poll_seconds: float = 2.0
    worker_lease_seconds: int = 600
    worker_concurrency: int = 4
    max_running_sections_per_job: int = 4
    max_attempts: int = 2
    retry_delays_seconds: tuple[int, ...] = (30, 60, 120)

    @classmethod
    def from_env(cls) -> AnalysisQueueSettings:
        return cls(
            model_id=os.getenv("BAZI_LLM_MODEL", "deepseek-chat").strip(),
            provider=os.getenv("BAZI_LLM_PROVIDER", "openai-compatible").strip(),
            prompt_version=os.getenv("BAZI_ANALYSIS_PROMPT_VERSION", "bazi-analysis-1.0.0").strip(),
            worker_poll_seconds=_float_env("BAZI_WORKER_POLL_SECONDS", 2.0, 0.1, 60.0),
            worker_lease_seconds=_int_env("BAZI_WORKER_LEASE_SECONDS", 600, 30, 3600),
            worker_concurrency=_int_env("BAZI_WORKER_CONCURRENCY", 4, 1, 32),
            max_running_sections_per_job=_int_env("BAZI_MAX_RUNNING_SECTIONS_PER_JOB", 4, 1, 8),
            max_attempts=_int_env("BAZI_ANALYSIS_MAX_ATTEMPTS", 2, 1, 10),
            retry_delays_seconds=_retry_delays_env(
                "BAZI_ANALYSIS_RETRY_DELAYS_SECONDS", (30, 60, 120)
            ),
        )


@dataclass(frozen=True)
class AuthSettings:
    """WeChat OAuth and server-side session settings.

    ``disabled`` keeps the existing anonymous deployment unchanged, ``mock`` is
    for local/test development, and ``live`` talks to the official WeChat OAuth
    endpoints. Secrets are read only by the API container.
    """

    mode: str = "disabled"
    app_id: str = ""
    app_secret: str = ""
    callback_url: str = ""
    oauth_scope: str = "snsapi_base"
    session_cookie_name: str = "bazi_session"
    session_ttl_seconds: int = 30 * 24 * 60 * 60
    oauth_state_ttl_seconds: int = 10 * 60
    cookie_secure: bool = True
    require_for_analysis: bool = False
    analysis_limit_per_24h: int = 0
    mock_openid: str = "local-wechat-user"

    @property
    def enabled(self) -> bool:
        return self.mode != "disabled"

    def validate_for_login(self) -> None:
        if self.mode == "disabled":
            raise ValueError("WeChat login is disabled")
        if not self.callback_url:
            raise ValueError("BAZI_WECHAT_OAUTH_CALLBACK_URL is required")
        if self.mode == "live" and (not self.app_id or not self.app_secret):
            raise ValueError("BAZI_WECHAT_APP_ID and BAZI_WECHAT_APP_SECRET are required")

    @classmethod
    def from_env(cls) -> AuthSettings:
        mode = os.getenv("BAZI_WECHAT_AUTH_MODE", "disabled").strip().lower()
        if mode not in {"disabled", "mock", "live"}:
            raise ValueError("BAZI_WECHAT_AUTH_MODE must be disabled, mock, or live")
        scope = os.getenv("BAZI_WECHAT_OAUTH_SCOPE", "snsapi_base").strip()
        if scope not in {"snsapi_base", "snsapi_userinfo"}:
            raise ValueError("BAZI_WECHAT_OAUTH_SCOPE must be snsapi_base or snsapi_userinfo")
        return cls(
            mode=mode,
            app_id=os.getenv("BAZI_WECHAT_APP_ID", "").strip(),
            app_secret=os.getenv("BAZI_WECHAT_APP_SECRET", "").strip(),
            callback_url=os.getenv("BAZI_WECHAT_OAUTH_CALLBACK_URL", "").strip(),
            oauth_scope=scope,
            session_cookie_name=os.getenv("BAZI_SESSION_COOKIE_NAME", "bazi_session").strip(),
            session_ttl_seconds=_int_env(
                "BAZI_SESSION_TTL_SECONDS", 30 * 24 * 60 * 60, 300, 365 * 24 * 60 * 60
            ),
            oauth_state_ttl_seconds=_int_env(
                "BAZI_WECHAT_OAUTH_STATE_TTL_SECONDS", 10 * 60, 60, 3600
            ),
            cookie_secure=_bool_env("BAZI_SESSION_COOKIE_SECURE", True),
            require_for_analysis=_bool_env("BAZI_AUTH_REQUIRED_FOR_ANALYSIS", False),
            analysis_limit_per_24h=_int_env("BAZI_USER_ANALYSIS_LIMIT_PER_24H", 0, 0, 1000),
            mock_openid=os.getenv("BAZI_WECHAT_MOCK_OPENID", "local-wechat-user").strip(),
        )


def _retry_delays_env(name: str, default: tuple[int, ...]) -> tuple[int, ...]:
    raw = os.getenv(name)
    if raw is None:
        return default
    if not raw.strip():
        return ()
    try:
        values = tuple(int(item.strip()) for item in raw.split(","))
    except ValueError as exc:
        raise ValueError(f"{name} must be comma-separated integers") from exc
    if not values or any(value < 1 or value > 86400 for value in values):
        raise ValueError(f"{name} values must be between 1 and 86400")
    if any(current <= previous for previous, current in zip(values, values[1:], strict=False)):
        raise ValueError(f"{name} values must be strictly increasing")
    return values


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


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean")
