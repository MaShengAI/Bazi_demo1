"""Independent operator login and read-only report access. Disabled by default."""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import threading
import time
from collections import deque
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone, tzinfo
from datetime import time as daytime
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine, event, func, or_, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, joinedload, selectinload

from app.models import AnalysisJobRecord, AnalysisSectionRecord, ChartRecord

HASH_ITERATIONS = 600_000
ADMIN_PATH = "/api/v1/admin"
STATUSES = {"pending", "running", "partial", "completed", "failed", "cancelled"}


class AdminError(RuntimeError):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code = status, code


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    result = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, HASH_ITERATIONS)
    return f"pbkdf2_sha256${HASH_ITERATIONS}${salt.hex()}${result.hex()}"


def _hash_parts(encoded: str) -> tuple[int, bytes, bytes]:
    algorithm, iterations, salt, expected = encoded.split("$")
    if (
        algorithm != "pbkdf2_sha256"
        or int(iterations) != HASH_ITERATIONS
        or not re.fullmatch(r"[0-9a-f]{32}", salt)
        or not re.fullmatch(r"[0-9a-f]{64}", expected)
    ):
        raise ValueError("Invalid administrator password hash")
    return int(iterations), bytes.fromhex(salt), bytes.fromhex(expected)


@dataclass(frozen=True)
class AdminSettings:
    username: str
    password_hash: str
    database_url: str
    public_origin: str
    cookie_secure: bool = True
    session_seconds: int = 3600

    @property
    def cookie_name(self) -> str:
        return "__Secure-bazi_admin" if self.cookie_secure else "bazi_admin_local"

    def validate(self) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_.-]{3,32}", self.username):
            raise ValueError("Invalid administrator username")
        _hash_parts(self.password_hash)
        parsed = urlsplit(self.public_origin)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.path
            or parsed.query
            or parsed.fragment
            or parsed.username
            or not 300 <= self.session_seconds <= 3600
        ):
            raise ValueError("Invalid administrator origin/session configuration")
        url = make_url(self.database_url)
        if url.get_backend_name() not in {"mysql", "sqlite"}:
            raise ValueError("Unsupported administrator database")
        if url.get_backend_name() == "mysql" and (
            url.username != "bazi_admin_reader" or url.database != "bazi"
        ):
            raise ValueError("Use the dedicated administrator reader account")
        if not self.cookie_secure and (
            url.get_backend_name() != "sqlite"
            or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        ):
            raise ValueError("HTTP administrator cookies are for isolated local SQLite tests only")
        if self.cookie_secure and parsed.scheme != "https":
            raise ValueError("Production administrator access requires HTTPS")

    @classmethod
    def from_env(cls) -> AdminSettings | None:
        if os.getenv("BAZI_ADMIN_ENABLED", "false").lower() != "true":
            return None
        settings = cls(
            username=os.getenv("BAZI_ADMIN_USERNAME", ""),
            password_hash=os.getenv("BAZI_ADMIN_PASSWORD_HASH", ""),
            database_url=os.getenv("BAZI_ADMIN_DATABASE_URL", ""),
            public_origin=os.getenv("BAZI_ADMIN_PUBLIC_ORIGIN", "").rstrip("/"),
            cookie_secure=os.getenv("BAZI_ADMIN_COOKIE_SECURE", "true").lower() != "false",
        )
        settings.validate()
        return settings


class AdminReadDatabase:
    """No shared write engine/session; additionally reject every non-SELECT statement."""

    def __init__(self, url: str):
        options: dict = {"pool_pre_ping": True, "hide_parameters": True}
        if make_url(url).get_backend_name() == "sqlite":
            options["connect_args"] = {"check_same_thread": False}
        else:
            options["pool_recycle"] = 1800
        self.engine = create_engine(url, **options)

        @event.listens_for(self.engine, "connect")
        def readonly_connection(connection, _):
            cursor = connection.cursor()
            try:
                cursor.execute(
                    "PRAGMA query_only = ON"
                    if self.engine.dialect.name == "sqlite"
                    else "SET SESSION TRANSACTION READ ONLY"
                )
            finally:
                cursor.close()

        @event.listens_for(self.engine, "before_cursor_execute")
        def only_select(connection, cursor, statement, parameters, context, executemany):
            if not re.match(r"^\s*SELECT\b", statement, flags=re.I):
                raise RuntimeError("Administrator database accepts SELECT statements only")

    @contextmanager
    def session(self) -> Iterator[Session]:
        with Session(self.engine, autoflush=False) as session:
            yield session
            # No commit or flush; queries are rolled back on close.

    def dispose(self) -> None:
        self.engine.dispose()


def _timestamp(value: datetime | None, zone: tzinfo = UTC) -> str | None:
    if value is None:
        return None
    return (value if value.tzinfo else value.replace(tzinfo=zone)).astimezone(UTC).isoformat()


class AdminService:
    def __init__(self, settings: AdminSettings):
        settings.validate()
        self.settings = settings
        self.database = AdminReadDatabase(settings.database_url)
        self._sessions: dict[str, float] = {}
        self._failures: dict[str, deque[float]] = {}
        self._login_attempts: deque[float] = deque()
        self._lock = threading.RLock()

    @staticmethod
    def _token_hash(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def _prune(self, now: float) -> None:
        self._sessions = {key: expiry for key, expiry in self._sessions.items() if expiry > now}
        while self._login_attempts and self._login_attempts[0] <= now - 300:
            self._login_attempts.popleft()
        for key in list(self._failures):
            bucket = self._failures[key]
            while bucket and bucket[0] <= now - 900:
                bucket.popleft()
            if not bucket:
                del self._failures[key]

    def login(self, username: str, password: str, client: str) -> str:
        now = time.time()
        client = hashlib.sha256(client.encode()).hexdigest()
        with self._lock:
            self._prune(now)
            if len(self._login_attempts) >= 20 or len(self._failures.get(client, ())) >= 5:
                raise AdminError(429, "admin_login_limited", "登录尝试较多，请稍后再试。")
            self._login_attempts.append(now)
        iterations, salt, expected = _hash_parts(self.settings.password_hash)
        calculated = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
        valid = hmac.compare_digest(calculated, expected) & hmac.compare_digest(
            username.encode(), self.settings.username.encode()
        )
        with self._lock:
            if not valid:
                self._failures.setdefault(client, deque()).append(now)
                raise AdminError(401, "admin_login_invalid", "账号或密码不正确。")
            self._failures.pop(client, None)
            self._prune(time.time())
            if len(self._sessions) >= 20:
                del self._sessions[min(self._sessions, key=self._sessions.__getitem__)]
            token = secrets.token_urlsafe(32)
            self._sessions[self._token_hash(token)] = time.time() + self.settings.session_seconds
            return token

    def authenticated(self, token: str | None) -> bool:
        if not token or len(token) > 128:
            return False
        with self._lock:
            self._prune(time.time())
            return self._token_hash(token) in self._sessions

    def logout(self, token: str | None) -> None:
        if token and len(token) <= 128:
            with self._lock:
                self._sessions.pop(self._token_hash(token), None)

    def _created_zone(self, session: Session) -> tzinfo:
        # created_at uses DB CURRENT_TIMESTAMP; worker finish times use application UTC.
        if self.database.engine.dialect.name != "mysql":
            return UTC
        offset = int(
            session.scalar(
                text("SELECT TIMESTAMPDIFF(SECOND, UTC_TIMESTAMP(), CURRENT_TIMESTAMP())")
            )
            or 0
        )
        if not -50400 <= offset <= 50400:
            raise AdminError(503, "admin_timezone_unavailable", "暂时无法读取数据库时间设置。")
        return timezone(timedelta(seconds=offset))

    def reports(
        self,
        *,
        q: str = "",
        status: str = "",
        start: date | None = None,
        end: date | None = None,
        page: int = 1,
    ) -> dict:
        if (
            (status and status not in STATUSES)
            or (start and end and start > end)
            or (start and start.year < 2)
            or (end and end.year > 9998)
        ):
            raise AdminError(422, "admin_filter_invalid", "请检查状态或日期范围。")
        conditions = []
        if q:
            conditions.append(
                or_(
                    AnalysisJobRecord.id.contains(q, autoescape=True),
                    ChartRecord.request_json["name"].as_string().contains(q, autoescape=True),
                )
            )
        if status:
            conditions.append(AnalysisJobRecord.status == status)
        with self.database.session() as session:
            created_zone = self._created_zone(session)
            zone = ZoneInfo("Asia/Shanghai")
            if start:
                since = datetime.combine(start, daytime.min, zone).astimezone(created_zone)
                conditions.append(AnalysisJobRecord.created_at >= since.replace(tzinfo=None))
            if end:
                until = datetime.combine(end + timedelta(days=1), daytime.min, zone)
                conditions.append(
                    AnalysisJobRecord.created_at
                    < until.astimezone(created_zone).replace(tzinfo=None)
                )
            total = (
                session.scalar(
                    select(func.count(AnalysisJobRecord.id)).join(ChartRecord).where(*conditions)
                )
                or 0
            )
            rows = session.execute(
                select(
                    AnalysisJobRecord.id,
                    AnalysisJobRecord.chart_id,
                    AnalysisJobRecord.status,
                    AnalysisJobRecord.model_id,
                    AnalysisJobRecord.created_at,
                    ChartRecord.request_json,
                    ChartRecord.user_id,
                )
                .join(ChartRecord)
                .where(*conditions)
                .order_by(AnalysisJobRecord.created_at.desc(), AnalysisJobRecord.id.desc())
                .offset((page - 1) * 20)
                .limit(20)
            ).all()
            ids = [row.id for row in rows]
            counts: dict[str, list[str]] = {}
            if ids:
                for job_id, section_status in session.execute(
                    select(
                        AnalysisSectionRecord.job_id,
                        AnalysisSectionRecord.status,
                    ).where(AnalysisSectionRecord.job_id.in_(ids))
                ):
                    counts.setdefault(job_id, []).append(section_status)
            items = []
            for row in rows:
                states = counts.get(row.id, [])
                items.append(
                    {
                        "id": row.id,
                        "chart_id": row.chart_id,
                        "status": row.status,
                        "model": row.model_id,
                        "created_at": _timestamp(row.created_at, created_zone),
                        "name": row.request_json.get("name") or "未命名命盘",
                        "birth_local_datetime": row.request_json.get("birth_local_datetime"),
                        "gender": row.request_json.get("gender"),
                        "user_id": row.user_id,
                        "completed_sections": states.count("completed"),
                        "total_sections": len(states),
                    }
                )
        return {"items": items, "total": total, "page": page, "page_size": 20}

    def report(self, job_id: str) -> dict:
        with self.database.session() as session:
            created_zone = self._created_zone(session)
            job = session.scalar(
                select(AnalysisJobRecord)
                .where(AnalysisJobRecord.id == job_id)
                .options(
                    joinedload(AnalysisJobRecord.chart), selectinload(AnalysisJobRecord.sections)
                )
            )
            if job is None:
                raise AdminError(404, "admin_report_not_found", "报告不存在或已被删除。")
            return {
                "id": job.id,
                "chart_id": job.chart_id,
                "user_id": job.chart.user_id,
                "status": job.status,
                "model": job.model_id,
                "prompt_version": job.prompt_version,
                "created_at": _timestamp(job.created_at, created_zone),
                "finished_at": _timestamp(job.finished_at),
                "request": job.chart.request_json,
                "chart": job.chart.snapshot_json,
                "sections": [
                    {
                        "code": s.code,
                        "title": s.title,
                        "status": s.status,
                        "content": s.content,
                        "char_count": s.char_count,
                        "retry_count": s.retry_count,
                        "length_status": s.length_status,
                        "error": s.error,
                        "error_code": s.error_code,
                    }
                    for s in job.sections
                ],
            }
