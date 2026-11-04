"""Commerce is opt-in. Money is always integer CNY cents, never browser input."""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from app.config import AuthSettings


@dataclass(frozen=True)
class Product:
    code: str
    name: str
    cards: int
    price: int


@dataclass(frozen=True)
class PaymentSettings:
    mode: str = "disabled"
    accept_new_orders: bool = True
    allowed_user_ids: tuple[str, ...] = ()
    refunds_enabled: bool = False
    refund_notify_url: str = ""
    mchid: str = ""
    serial: str = ""
    private_key_path: str = ""
    public_key_id: str = ""
    public_key_path: str = ""
    api_v3_key: str = field(default="", repr=False)
    notify_url: str = ""
    single_price: int = 8800
    double_price: int = 15800
    family_price: int = 22800

    @property
    def enabled(self) -> bool:
        return self.mode != "disabled"

    def can_purchase(self, user_id: str) -> bool:
        """Restrict new purchases only; existing orders still need reconciliation."""
        return self.accept_new_orders and (
            not self.allowed_user_ids or user_id in self.allowed_user_ids
        )

    def validate_purchase_access(self) -> None:
        if len(set(self.allowed_user_ids)) != len(self.allowed_user_ids):
            raise ValueError("Duplicate payment access account")
        for user_id in self.allowed_user_ids:
            if str(uuid.UUID(user_id)) != user_id:
                raise ValueError("Payment access requires canonical account UUIDs")

    @property
    def products(self) -> tuple[Product, ...]:
        return (
            Product("single", "单次八字精批卡", 1, self.single_price),
            Product("double", "双人八字精批卡", 2, self.double_price),
            Product("family", "全家福八字精批卡", 5, self.family_price),
        )

    @classmethod
    def from_env(cls) -> PaymentSettings:
        def env(name: str) -> str:
            return os.getenv(f"BAZI_PAY_{name}", "").strip()

        settings = cls(
            mode=env("MODE") or "disabled",
            accept_new_orders=(env("ACCEPT_NEW_ORDERS") or "true").lower() == "true",
            allowed_user_ids=tuple(item.strip() for item in env("ALLOWED_USER_IDS").split(","))
            if env("ALLOWED_USER_IDS")
            else (),
            refunds_enabled=env("REFUNDS_ENABLED").lower() == "true",
            refund_notify_url=env("REFUND_NOTIFY_URL"),
            mchid=env("MCHID"),
            serial=env("SERIAL"),
            private_key_path=env("PRIVATE_KEY_PATH"),
            public_key_id=env("PUBLIC_KEY_ID"),
            public_key_path=env("PUBLIC_KEY_PATH"),
            api_v3_key=env("API_V3_KEY"),
            notify_url=env("NOTIFY_URL"),
            single_price=int(env("SINGLE_PRICE") or 8800),
            double_price=int(env("DOUBLE_PRICE") or 15800),
            family_price=int(env("FAMILY_PRICE") or 22800),
        )
        if settings.mode not in {"disabled", "mock", "live"}:
            raise ValueError("BAZI_PAY_MODE must be disabled, mock, or live")
        settings.validate_purchase_access()
        if any(not 5000 < p.price <= 10000000 for p in settings.products):
            raise ValueError("Product prices must exceed the 5000-cent coupon")
        return settings

    def validate(self, auth: AuthSettings) -> None:
        self.validate_purchase_access()
        if not self.enabled:
            return
        if self.mode == "mock":
            if auth.mode != "mock" or urlsplit(auth.callback_url).hostname not in {
                "localhost",
                "127.0.0.1",
                "testserver",
                "::1",
            }:
                raise ValueError("Mock payments require local mock authentication")
            return
        if auth.mode != "live" or not auth.app_id or not auth.cookie_secure:
            raise ValueError("Live payments require live WeChat login and secure cookies")
        if not all(
            (
                self.mchid,
                self.serial,
                self.private_key_path,
                self.public_key_id,
                self.public_key_path,
                self.notify_url,
            )
        ):
            raise ValueError("Missing WeChat Pay merchant configuration")
        parsed = urlsplit(self.notify_url)
        if parsed.scheme != "https" or parsed.query or parsed.fragment or not parsed.hostname:
            raise ValueError("WeChat Pay notify URL must be public HTTPS without query or fragment")
        if not self.public_key_id.startswith("PUB_KEY_ID_"):
            raise ValueError("This integration requires WeChat Pay public-key mode")
        if len(self.api_v3_key.encode()) != 32:
            raise ValueError("WeChat Pay API v3 key must contain exactly 32 bytes")
