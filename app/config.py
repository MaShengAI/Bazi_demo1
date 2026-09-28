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
            max_attempts=_int_env("BAZI_ANALYSIS_MAX_ATTEMPTS", 2, 1, 10),
            retry_delays_seconds=_retry_delays_env(
                "BAZI_ANALYSIS_RETRY_DELAYS_SECONDS", (30, 60, 120)
            ),
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
