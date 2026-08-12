from __future__ import annotations

import contextvars
import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any

request_id_context: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")

_SENSITIVE_KEY = re.compile(
    r"(?:^|[_-])(?:api[_-]?key|authorization|cookie|password|secret|token|access[_-]?token|"
    r"refresh[_-]?token|database[_-]?url)(?:$|[_-])",
    re.I,
)
_BEARER = re.compile(r"(?i)(bearer\s+)[^\s,;]+")
_DEEPSEEK_KEY = re.compile(r"(?i)\bsk-[A-Za-z0-9_-]{8,}\b")
_URL_PASSWORD = re.compile(r"(mysql(?:\+pymysql)?://[^:/\s]+:)[^@/\s]+(@)", re.I)
_STANDARD_LOG_FIELDS = set(logging.makeLogRecord({}).__dict__) | {
    "message",
    "asctime",
}


def redact(value: Any, *, key: str | None = None) -> Any:
    """Redact common credentials without ever serializing request bodies or prompts."""
    if key and _SENSITIVE_KEY.search(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(item_key): redact(item, key=str(item_key)) for item_key, item in value.items()}
    if isinstance(value, list | tuple):
        return [redact(item) for item in value]
    if not isinstance(value, str):
        return value
    value = _BEARER.sub(r"\1[REDACTED]", value)
    value = _DEEPSEEK_KEY.sub("[REDACTED]", value)
    return _URL_PASSWORD.sub(r"\1[REDACTED]\2", value)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
            "request_id": getattr(record, "request_id", request_id_context.get()),
        }
        for key, value in record.__dict__.items():
            if key in _STANDARD_LOG_FIELDS or key.startswith("_"):
                continue
            if key in {"args", "exc_info", "exc_text", "stack_info"}:
                continue
            payload[key] = redact(value, key=key)
        if record.exc_info:
            payload["exception"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)


class RequestContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = request_id_context.get()
        return True


def configure_logging(level: str | None = None) -> None:
    root = logging.getLogger()
    if getattr(root, "_bazi_json_configured", False):
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RequestContextFilter())
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel((level or "INFO").upper())
    root._bazi_json_configured = True  # type: ignore[attr-defined]
