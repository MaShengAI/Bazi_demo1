from __future__ import annotations

import base64
import json
import re
import time
from dataclasses import replace

import httpx
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.integrations.wechat_pay import VerifiedProviderError, WechatPayClient
from app.payment_config import PaymentSettings
from app.services.cards import PaymentError


@pytest.fixture
def crypto_client(tmp_path):
    merchant = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    wechat = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_path, public_path = tmp_path / "merchant.pem", tmp_path / "wechat-public.pem"
    private_path.write_bytes(
        merchant.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    public_path.write_bytes(
        wechat.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    )
    settings = PaymentSettings(
        mode="live",
        mchid="test-mch",
        serial="test-serial",
        private_key_path=str(private_path),
        public_key_path=str(public_path),
        public_key_id="PUB_KEY_ID_TEST",
        api_v3_key="0" * 32,
    )
    return WechatPayClient(settings, "test-app"), merchant, wechat


def signed_headers(client, wechat, body, timestamp=None):
    stamp = timestamp or str(int(time.time()))
    nonce = "test-nonce"
    signature = wechat.sign(
        stamp.encode() + b"\n" + nonce.encode() + b"\n" + body + b"\n",
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    return httpx.Headers(
        {
            "Wechatpay-Timestamp": stamp,
            "Wechatpay-Nonce": nonce,
            "Wechatpay-Serial": client.settings.public_key_id,
            "Wechatpay-Signature": base64.b64encode(signature).decode(),
        }
    )


def notification_body(client, transaction=None):
    plaintext = json.dumps(
        transaction or {"out_trade_no": "test-order", "trade_state": "SUCCESS"}
    ).encode()
    nonce, associated = b"123456789012", b"transaction"
    ciphertext = AESGCM(client.settings.api_v3_key.encode()).encrypt(nonce, plaintext, associated)
    return json.dumps(
        {
            "event_type": "TRANSACTION.SUCCESS",
            "resource": {
                "original_type": "transaction",
                "algorithm": "AEAD_AES_256_GCM",
                "nonce": nonce.decode(),
                "associated_data": associated.decode(),
                "ciphertext": base64.b64encode(ciphertext).decode(),
            },
        }
    ).encode()


def test_signed_notification_decryption_and_tamper_rejection(crypto_client):
    client, _, wechat = crypto_client
    body = notification_body(client)
    headers = signed_headers(client, wechat, body)
    assert client.notification(headers, body)["out_trade_no"] == "test-order"
    with pytest.raises(PaymentError):
        client.notification(headers, body + b" ")
    client.settings = replace(client.settings, api_v3_key="1" * 32)
    with pytest.raises(PaymentError) as invalid:
        client.notification(headers, body)
    assert invalid.value.code == "payment_notification_invalid"


@pytest.mark.parametrize(
    "variant", ["unknown-key", "stale", "test-signature", "missing", "invalid-base64"]
)
def test_untrusted_signatures_rejected(crypto_client, variant):
    client, _, wechat = crypto_client
    body = b"{}"
    headers = signed_headers(
        client, wechat, body, str(int(time.time()) - 301) if variant == "stale" else None
    )
    if variant == "unknown-key":
        headers["Wechatpay-Serial"] = "PUB_KEY_ID_ATTACKER"
    elif variant == "test-signature":
        headers["Wechatpay-Signature"] = "WECHATPAY/SIGNTEST/not-valid"
    elif variant == "missing":
        del headers["Wechatpay-Nonce"]
    elif variant == "invalid-base64":
        headers["Wechatpay-Signature"] = "!!!"
    with pytest.raises(PaymentError):
        client.verify(headers, body)


def test_api_canonical_request_signature_and_response_validation(crypto_client, monkeypatch):
    client, merchant, wechat = crypto_client
    real_http_client = httpx.Client

    def handler(request):
        authorization = request.headers["Authorization"]
        fields = dict(re.findall(r'(\w+)="([^"]*)"', authorization))
        assert request.headers["Wechatpay-Serial"] == "PUB_KEY_ID_TEST"
        path = request.url.raw_path.decode()
        canonical = (
            f"{request.method}\n{path}\n{fields['timestamp']}\n{fields['nonce_str']}\n".encode()
            + request.content
            + b"\n"
        )
        merchant.public_key().verify(
            base64.b64decode(fields["signature"]), canonical, padding.PKCS1v15(), hashes.SHA256()
        )
        body = b'{"prepay_id":"verified-prepay"}'
        return httpx.Response(200, content=body, headers=signed_headers(client, wechat, body))

    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: real_http_client(transport=httpx.MockTransport(handler))
    )
    assert client.request("POST", "/v3/pay/transactions/jsapi", {"amount": {"total": 3800}}) == {
        "prepay_id": "verified-prepay"
    }
    assert client.request("GET", "/v3/pay/transactions/out-trade-no/test?mchid=test-mch")


def test_empty_close_response_still_requires_signature(crypto_client, monkeypatch):
    client, _, wechat = crypto_client
    real_http_client = httpx.Client
    valid = False

    def handler(request):
        return httpx.Response(204, headers=signed_headers(client, wechat, b"") if valid else {})

    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: real_http_client(transport=httpx.MockTransport(handler))
    )
    with pytest.raises(PaymentError):
        client.request(
            "POST", "/v3/pay/transactions/out-trade-no/test/close", {"mchid": "test-mch"}
        )
    valid = True
    assert (
        client.request(
            "POST", "/v3/pay/transactions/out-trade-no/test/close", {"mchid": "test-mch"}
        )
        == {}
    )


def test_unsigned_json_cannot_be_used_as_payment_result(crypto_client, monkeypatch):
    client, _, _ = crypto_client
    real_http_client = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: real_http_client(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(200, json={"trade_state": "SUCCESS"})
            )
        ),
    )
    with pytest.raises(PaymentError):
        client.request("GET", "/v3/pay/transactions/out-trade-no/test?mchid=test-mch")


def test_jsapi_signature_uses_merchant_key(crypto_client):
    client, merchant, _ = crypto_client
    params = client.jsapi_parameters("prepay-test")
    canonical = (
        f"{params['appId']}\n{params['timeStamp']}\n{params['nonceStr']}\n{params['package']}\n"
    )
    merchant.public_key().verify(
        base64.b64decode(params["paySign"]), canonical.encode(), padding.PKCS1v15(), hashes.SHA256()
    )
    assert params["signType"] == "RSA"


def test_malformed_encrypted_resource_fails(crypto_client):
    client, _, wechat = crypto_client
    body = b'{"event_type":"TRANSACTION.SUCCESS","resource":{"algorithm":"NOT_AES"}}'
    with pytest.raises(PaymentError):
        client.notification(signed_headers(client, wechat, body), body)


@pytest.mark.parametrize("state", ["SUCCESS", "CLOSED", "ABNORMAL"])
def test_refund_notifications_require_signed_decryption_and_matching_event(crypto_client, state):
    client, _, wechat = crypto_client
    plaintext = json.dumps({"out_refund_no": "refund-test", "refund_status": state}).encode()
    nonce = b"123456789012"
    encrypted = AESGCM(client.settings.api_v3_key.encode()).encrypt(nonce, plaintext, b"refund")
    envelope = {
        "event_type": "REFUND." + state,
        "resource": {
            "original_type": "refund",
            "algorithm": "AEAD_AES_256_GCM",
            "nonce": nonce.decode(),
            "associated_data": "refund",
            "ciphertext": base64.b64encode(encrypted).decode(),
        },
    }
    body = json.dumps(envelope).encode()
    headers = signed_headers(client, wechat, body)
    assert client.refund_notification(headers, body)["refund_status"] == state
    with pytest.raises(PaymentError):
        client.refund_notification(headers, body + b" ")
    with pytest.raises(PaymentError):
        client.notification(headers, body)  # Cannot send refunds to the payment-credit parser.
    envelope["event_type"] = "REFUND.CLOSED" if state != "CLOSED" else "REFUND.SUCCESS"
    mismatched = json.dumps(envelope).encode()
    with pytest.raises(PaymentError):
        client.refund_notification(signed_headers(client, wechat, mismatched), mismatched)


def test_verified_not_found_is_distinct_from_unsigned_or_other_404(crypto_client, monkeypatch):
    client, _, wechat = crypto_client
    real_client = httpx.Client
    trusted = True

    def handler(request):
        body = b'{"code":"RESOURCE_NOT_EXISTS","message":"fixture"}'
        return httpx.Response(
            404, content=body, headers=signed_headers(client, wechat, body) if trusted else {}
        )

    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: real_client(transport=httpx.MockTransport(handler))
    )
    with pytest.raises(VerifiedProviderError) as verified:
        client.request("GET", "/v3/refund/domestic/refunds/fixture")
    assert verified.value.http_status == 404
    assert verified.value.provider_code == "RESOURCE_NOT_EXISTS"
    trusted = False
    with pytest.raises(PaymentError) as untrusted:
        client.request("GET", "/v3/refund/domestic/refunds/fixture")
    assert untrusted.value.code == "payment_signature_invalid"
