from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from app.config import AuthSettings
from app.database import Database
from app.integrations.wechat import WechatProfile
from app.models import (
    AuthSessionRecord,
    OAuthStateRecord,
    UserRecord,
    WechatIdentityRecord,
)


class AuthError(RuntimeError):
    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code


@dataclass(frozen=True)
class AuthenticatedUser:
    id: str
    display_name: str
    avatar_url: str | None


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def utcnow_naive() -> datetime:
    """MySQL DATETIME has no timezone; store and compare application UTC consistently."""
    return datetime.now(UTC).replace(tzinfo=None)


def safe_return_to(value: str | None) -> str:
    candidate = (value or "/").strip()
    parsed = urlsplit(candidate)
    if (
        not candidate.startswith("/")
        or candidate.startswith("//")
        or "\\" in candidate
        or parsed.scheme
        or parsed.netloc
        or len(candidate) > 500
    ):
        return "/"
    return candidate


class AuthService:
    def __init__(self, database: Database, settings: AuthSettings):
        self.database = database
        self.settings = settings

    def create_oauth_state(self, return_to: str | None) -> str:
        if not self.settings.enabled:
            raise AuthError(503, "wechat_auth_disabled", "微信登录尚未启用")
        try:
            self.settings.validate_for_login()
        except ValueError as exc:
            raise AuthError(503, "wechat_auth_not_configured", str(exc)) from exc
        raw_state = secrets.token_urlsafe(32)
        now = utcnow_naive()
        with self.database.session() as session:
            session.execute(delete(OAuthStateRecord).where(OAuthStateRecord.expires_at <= now))
            session.add(
                OAuthStateRecord(
                    state_hash=token_hash(raw_state),
                    return_to=safe_return_to(return_to),
                    expires_at=now + timedelta(seconds=self.settings.oauth_state_ttl_seconds),
                )
            )
            session.commit()
        return raw_state

    def consume_oauth_state(self, raw_state: str) -> str:
        if not raw_state:
            raise AuthError(400, "invalid_oauth_state", "微信登录状态无效，请重新登录")
        with self.database.session() as session:
            record = session.scalar(
                select(OAuthStateRecord)
                .where(OAuthStateRecord.state_hash == token_hash(raw_state))
                .with_for_update()
            )
            if record is None or record.expires_at <= utcnow_naive():
                if record is not None:
                    session.delete(record)
                    session.commit()
                raise AuthError(400, "invalid_oauth_state", "微信登录状态已失效，请重新登录")
            return_to = record.return_to
            session.delete(record)
            session.commit()
            return return_to

    def login_wechat_user(self, profile: WechatProfile) -> tuple[AuthenticatedUser, str]:
        app_id = self.settings.app_id or "mock-app-id"
        now = utcnow_naive()
        with self.database.session() as session:
            identity = session.scalar(
                select(WechatIdentityRecord)
                .where(
                    WechatIdentityRecord.app_id == app_id,
                    WechatIdentityRecord.openid == profile.openid,
                )
                .options(joinedload(WechatIdentityRecord.user))
            )
            if identity is None:
                user = UserRecord(
                    display_name=profile.nickname or "微信用户",
                    avatar_url=profile.avatar_url,
                    last_login_at=now,
                )
                identity = WechatIdentityRecord(
                    user=user,
                    app_id=app_id,
                    openid=profile.openid,
                    unionid=profile.unionid,
                    profile_json=profile.raw_profile,
                )
                session.add(identity)
                try:
                    session.flush()
                except IntegrityError:
                    session.rollback()
                    identity = session.scalar(
                        select(WechatIdentityRecord)
                        .where(
                            WechatIdentityRecord.app_id == app_id,
                            WechatIdentityRecord.openid == profile.openid,
                        )
                        .options(joinedload(WechatIdentityRecord.user))
                    )
                    if identity is None:
                        raise
                    user = identity.user
            else:
                user = identity.user
                if profile.nickname:
                    user.display_name = profile.nickname
                if profile.avatar_url:
                    user.avatar_url = profile.avatar_url
                if profile.unionid:
                    identity.unionid = profile.unionid
                if profile.raw_profile:
                    identity.profile_json = profile.raw_profile
                user.last_login_at = now
            if user.status != "active":
                raise AuthError(403, "user_disabled", "当前账号已停用")
            raw_token = secrets.token_urlsafe(48)
            session.add(
                AuthSessionRecord(
                    user=user,
                    token_hash=token_hash(raw_token),
                    expires_at=now + timedelta(seconds=self.settings.session_ttl_seconds),
                    last_seen_at=now,
                )
            )
            session.commit()
            return AuthenticatedUser(user.id, user.display_name, user.avatar_url), raw_token

    def current_user(self, raw_token: str | None) -> AuthenticatedUser | None:
        if not raw_token:
            return None
        now = utcnow_naive()
        with self.database.session() as session:
            record = session.scalar(
                select(AuthSessionRecord)
                .where(
                    AuthSessionRecord.token_hash == token_hash(raw_token),
                    AuthSessionRecord.revoked_at.is_(None),
                    AuthSessionRecord.expires_at > now,
                )
                .options(joinedload(AuthSessionRecord.user))
            )
            if record is None or record.user.status != "active":
                return None
            if record.last_seen_at < now - timedelta(hours=1):
                record.last_seen_at = now
                session.commit()
            user = record.user
            return AuthenticatedUser(user.id, user.display_name, user.avatar_url)

    def require_user(self, raw_token: str | None) -> AuthenticatedUser:
        user = self.current_user(raw_token)
        if user is None:
            raise AuthError(401, "authentication_required", "请先使用微信登录")
        return user

    def logout(self, raw_token: str | None) -> None:
        if not raw_token:
            return
        with self.database.session() as session:
            record = session.scalar(
                select(AuthSessionRecord).where(
                    AuthSessionRecord.token_hash == token_hash(raw_token)
                )
            )
            if record is not None and record.revoked_at is None:
                record.revoked_at = utcnow_naive()
                session.commit()
