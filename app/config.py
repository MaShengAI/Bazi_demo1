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
    max_attempts: int = 2

    @classmethod
    def from_env(cls) -> AnalysisQueueSettings:
        return cls(
            model_id=os.getenv("BAZI_LLM_MODEL", "deepseek-chat").strip(),
            provider=os.getenv("BAZI_LLM_PROVIDER", "openai-compatible").strip(),
            prompt_version=os.getenv("BAZI_ANALYSIS_PROMPT_VERSION", "bazi-analysis-1.0.0").strip(),
            worker_poll_seconds=_float_env("BAZI_WORKER_POLL_SECONDS", 2.0, 0.1, 60.0),
            worker_lease_seconds=_int_env("BAZI_WORKER_LEASE_SECONDS", 600, 30, 3600),
            max_attempts=_int_env("BAZI_ANALYSIS_MAX_ATTEMPTS", 2, 1, 10),
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
