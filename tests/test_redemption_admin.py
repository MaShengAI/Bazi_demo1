import uuid
from dataclasses import replace

from test_admin import ORIGIN, admin_app, login  # noqa: F401 - shared pytest fixture


def test_admin_generation_origin_validation_listing_disable(admin_app):  # noqa: F811
    client, _, _, _ = admin_app
    from app.main import app

    app.state.payment_settings = replace(app.state.payment_settings, mode="mock")
    root = "/api/v1/admin/redemptions"
    payload = {
        "kind": "cards",
        "value": 5,
        "quantity": 3,
        "label": "赠礼",
        "request_key": uuid.uuid4().hex,
    }
    assert (
        client.post(root + "/batches", json=payload, headers={"Origin": ORIGIN}).status_code == 401
    )
    assert login(client).status_code == 200
    assert client.post(root + "/batches", json=payload).status_code == 403
    assert (
        client.post(
            root + "/batches", json={**payload, "value": 101}, headers={"Origin": ORIGIN}
        ).status_code
        == 422
    )
    response = client.post(root + "/batches", json=payload, headers={"Origin": ORIGIN})
    assert response.status_code == 201, response.text
    assert "no-store" in response.headers["cache-control"]
    assert len(response.json()["codes"]) == 3
    assert (
        client.post(root + "/batches", json=payload, headers={"Origin": ORIGIN}).status_code == 409
    )
    listing = client.get(root).json()
    assert listing["total"] == 3
    assert "code_hash" not in str(listing) and response.json()["codes"][0] not in str(listing)
    code_id = listing["items"][0]["id"]
    assert (
        client.post(
            root + f"/{code_id}/disable", headers={"Origin": "https://evil.example"}
        ).status_code
        == 403
    )
    assert client.post(root + f"/{code_id}/disable", headers={"Origin": ORIGIN}).status_code == 204
    disabled = client.get(root + "?status=disabled").json()
    assert disabled["total"] == 1 and disabled["items"][0]["disabled_by"] == "owner"
