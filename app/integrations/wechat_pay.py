"""WeChat Pay API v3, pinned public-key mode; no secrets in browser or logs."""

from __future__ import annotations

import base64
import json
import secrets
import time
from pathlib import Path
from typing import Any

import httpx
from cryptography.exceptions import InvalidSignature, InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.payment_config import PaymentSettings
from app.services.cards import PaymentError


class VerifiedProviderError(PaymentError):
    """Only constructed after authenticating the provider's exact response body."""

    def __init__(self, http_status: int, provider_code: str):
        super().__init__(502, "payment_rejected", "微信支付暂未接受操作，请查询或稍后重试")
        self.http_status, self.provider_code = http_status, provider_code


class WechatPayClient:
    def __init__(self, settings: PaymentSettings, app_id: str):
        self.settings = settings
        self.app_id = app_id
        private = serialization.load_pem_private_key(
            Path(settings.private_key_path).read_bytes(), password=None
        )
        public = serialization.load_pem_public_key(Path(settings.public_key_path).read_bytes())
        if not isinstance(private, rsa.RSAPrivateKey) or private.key_size < 2048:
            raise ValueError("Merchant key must be RSA 2048 or stronger")
        if not isinstance(public, rsa.RSAPublicKey) or public.key_size < 2048:
            raise ValueError("WeChat Pay public key must be RSA 2048 or stronger")
        self.private_key = private
        self.public_key = public

    def sign(self, message: bytes) -> str:
        return base64.b64encode(
            self.private_key.sign(message, padding.PKCS1v15(), hashes.SHA256())
        ).decode("ascii")

    def verify(self, headers: httpx.Headers, body: bytes) -> None:
        try:
            timestamp = headers["Wechatpay-Timestamp"]
            nonce = headers["Wechatpay-Nonce"]
            serial = headers["Wechatpay-Serial"]
            signature = headers["Wechatpay-Signature"]
            if serial != self.settings.public_key_id or abs(time.time() - int(timestamp)) > 300:
                raise ValueError("Untrusted key or stale message")
            if signature.startswith("WECHATPAY/SIGNTEST/"):
                raise ValueError("Signature test message")
            self.public_key.verify(
                base64.b64decode(signature, validate=True),
                timestamp.encode() + b"\n" + nonce.encode() + b"\n" + body + b"\n",
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
        except (KeyError, ValueError, InvalidSignature) as exc:
            raise PaymentError(400, "payment_signature_invalid", "微信支付签名校验失败") from exc

    def request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) if payload else ""
        timestamp, nonce = str(int(time.time())), secrets.token_hex(16)
        signature = self.sign(f"{method}\n{path}\n{timestamp}\n{nonce}\n{body}\n".encode())
        authorization = (
            f'WECHATPAY2-SHA256-RSA2048 mchid="{self.settings.mchid}",'
            f'nonce_str="{nonce}",timestamp="{timestamp}",'
            f'serial_no="{self.settings.serial}",signature="{signature}"'
        )
        try:
            with httpx.Client(
                timeout=httpx.Timeout(4.0), follow_redirects=False, trust_env=False
            ) as client:
                response = client.request(
                    method,
                    "https://api.mch.weixin.qq.com" + path,
                    content=body.encode(),
                    headers={
                        "Authorization": authorization,
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                        "Wechatpay-Serial": self.settings.public_key_id,
                        "User-Agent": "Bazi-WechatPay/1.0",
                    },
                )
        except httpx.HTTPError as exc:
            raise PaymentError(
                502, "payment_unavailable", "支付网络异常，请查询原订单，勿重复下单"
            ) from exc
        # Even HTTP 204 close-order responses require signature verification.
        self.verify(response.headers, response.content)
        if response.status_code == 204 and not response.content:
            return {}
        if response.status_code != 200:
            try:
                provider_code = response.json().get("code", "")
                if not isinstance(provider_code, str) or len(provider_code) > 64:
                    provider_code = ""
            except (ValueError, AttributeError):
                provider_code = ""
            raise VerifiedProviderError(response.status_code, provider_code)
        try:
            result = response.json()
            if not isinstance(result, dict):
                raise ValueError("Invalid payload")
            return result
        except ValueError as exc:
            raise PaymentError(502, "payment_invalid_response", "支付响应格式无效") from exc

    def jsapi_parameters(self, prepay_id: str) -> dict[str, str]:
        timestamp, nonce = str(int(time.time())), secrets.token_hex(16)
        package = f"prepay_id={prepay_id}"
        return {
            "appId": self.app_id,
            "timeStamp": timestamp,
            "nonceStr": nonce,
            "package": package,
            "signType": "RSA",
            "paySign": self.sign(f"{self.app_id}\n{timestamp}\n{nonce}\n{package}\n".encode()),
        }

    def notification(self, headers: httpx.Headers, body: bytes) -> dict:
        return self._notification(headers, body, "transaction", {"TRANSACTION.SUCCESS"})

    def refund_notification(self, headers: httpx.Headers, body: bytes) -> dict:
        result = self._notification(
            headers, body, "refund", {"REFUND.SUCCESS", "REFUND.CLOSED", "REFUND.ABNORMAL"}
        )
        # The signed event and the authenticated plaintext must describe the same state.
        if json.loads(body)["event_type"] != "REFUND." + str(result.get("refund_status")):
            raise PaymentError(400, "payment_notification_invalid", "退款通知状态不匹配")
        return result

    def _notification(
        self, headers: httpx.Headers, body: bytes, kind: str, events: set[str]
    ) -> dict:
        self.verify(headers, body)
        try:
            envelope = json.loads(body)
            resource = envelope["resource"]
            if (
                envelope["event_type"] not in events
                or resource["algorithm"] != "AEAD_AES_256_GCM"
                or resource["original_type"] != kind
            ):
                raise ValueError("Unexpected resource")
            plaintext = AESGCM(self.settings.api_v3_key.encode()).decrypt(
                resource["nonce"].encode(),
                base64.b64decode(resource["ciphertext"], validate=True),
                resource.get("associated_data", "").encode(),
            )
            transaction = json.loads(plaintext)
            if not isinstance(transaction, dict):
                raise ValueError("Invalid transaction")
            return transaction
        except (KeyError, TypeError, ValueError, InvalidTag) as exc:
            raise PaymentError(400, "payment_notification_invalid", "支付通知解密失败") from exc
