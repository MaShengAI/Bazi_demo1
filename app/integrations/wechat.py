from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx

from app.config import AuthSettings

WECHAT_AUTHORIZE_URL = "https://open.weixin.qq.com/connect/oauth2/authorize"
WECHAT_TOKEN_URL = "https://api.weixin.qq.com/sns/oauth2/access_token"
WECHAT_USERINFO_URL = "https://api.weixin.qq.com/sns/userinfo"


class WechatOAuthError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class WechatProfile:
    openid: str
    unionid: str | None = None
    nickname: str | None = None
    avatar_url: str | None = None
    raw_profile: dict[str, Any] | None = None


class WechatOAuthClient:
    def __init__(self, settings: AuthSettings):
        self.settings = settings

    def authorization_url(self, state: str) -> str:
        self.settings.validate_for_login()
        if self.settings.mode == "mock":
            query = urlencode({"code": "mock-code", "state": state})
            return f"{self.settings.callback_url}?{query}"
        query = urlencode(
            {
                "appid": self.settings.app_id,
                "redirect_uri": self.settings.callback_url,
                "response_type": "code",
                "scope": self.settings.oauth_scope,
                "state": state,
            }
        )
        return f"{WECHAT_AUTHORIZE_URL}?{query}#wechat_redirect"

    async def exchange_code(self, code: str) -> WechatProfile:
        if self.settings.mode == "mock":
            return WechatProfile(
                openid=self.settings.mock_openid,
                nickname="测试微信用户",
                raw_profile={"source": "mock"},
            )
        self.settings.validate_for_login()
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                WECHAT_TOKEN_URL,
                params={
                    "appid": self.settings.app_id,
                    "secret": self.settings.app_secret,
                    "code": code,
                    "grant_type": "authorization_code",
                },
            )
            payload = self._json(response)
            self._raise_wechat_error(payload)
            openid = payload.get("openid")
            access_token = payload.get("access_token")
            if not isinstance(openid, str) or not openid:
                raise WechatOAuthError("wechat_invalid_response", "微信授权响应缺少openid")
            profile_payload: dict[str, Any] | None = None
            if self.settings.oauth_scope == "snsapi_userinfo":
                if not isinstance(access_token, str) or not access_token:
                    raise WechatOAuthError(
                        "wechat_invalid_response", "微信授权响应缺少access_token"
                    )
                profile_response = await client.get(
                    WECHAT_USERINFO_URL,
                    params={"access_token": access_token, "openid": openid, "lang": "zh_CN"},
                )
                profile_payload = self._json(profile_response)
                self._raise_wechat_error(profile_payload)
            source = profile_payload or payload
            return WechatProfile(
                openid=openid,
                unionid=_optional_string(source.get("unionid")),
                nickname=_optional_string(source.get("nickname")),
                avatar_url=_optional_string(source.get("headimgurl")),
                raw_profile=profile_payload,
            )

    @staticmethod
    def _json(response: httpx.Response) -> dict[str, Any]:
        try:
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise WechatOAuthError("wechat_unavailable", "微信授权服务暂时不可用") from exc
        if not isinstance(payload, dict):
            raise WechatOAuthError("wechat_invalid_response", "微信授权响应格式无效")
        return payload

    @staticmethod
    def _raise_wechat_error(payload: dict[str, Any]) -> None:
        if "errcode" not in payload or payload.get("errcode") in {0, "0"}:
            return
        code = str(payload.get("errcode"))
        message = str(payload.get("errmsg") or "微信授权失败")
        raise WechatOAuthError("wechat_oauth_rejected", f"微信授权失败（{code}）：{message}")


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
