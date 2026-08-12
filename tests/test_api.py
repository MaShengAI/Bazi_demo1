from fastapi.testclient import TestClient

from app.main import app


def test_chart_api_returns_auditable_result() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/charts",
            json={
                "name": "测试用户",
                "gender": "male",
                "birth_local_datetime": "1988-07-10T12:30",
                "location_id": 3101,
            },
        )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/json; charset=utf-8"
    payload = response.json()
    assert payload["time_normalization"]["standard_local_time"] == "1988-07-10T11:30:00+08:00"
    assert [payload["pillars"][key]["pillar"] for key in ("year", "month", "day", "hour")] == [
        "戊辰",
        "己未",
        "丙寅",
        "甲午",
    ]
    assert payload["luck_direction"]["direction"] == "forward"
    assert payload["luck_start"]["reference_jie"] == "立秋"
    assert payload["major_luck_cycles"][-1]["end_age"] <= 100
    assert payload["ruleset_versions"]["shen_sha"] == "common-shensha-2.2.0"
    assert any(
        hit["code"] == "taiji"
        for pillar in payload["pillars"].values()
        for hit in pillar["shen_sha"]
    )
    luck_hits = [hit for cycle in payload["major_luck_cycles"] for hit in cycle["shen_sha"]]
    assert luck_hits
    assert all(len(hit["rule_id"]) == 6 and hit["rule_id"].startswith("SS-") for hit in luck_hits)
    assert payload["calculation_trace"]


def test_api_rejects_non_minute_input() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/charts",
            json={
                "gender": "male",
                "birth_local_datetime": "1988-07-10T12:30:20",
                "location_id": 3101,
            },
        )
    assert response.status_code == 422
    assert response.headers["content-type"] == "application/json; charset=utf-8"
    assert response.json()["error"]["code"] == "invalid_birth_datetime"


def test_api_returns_structured_ambiguous_time_error() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/charts",
            json={
                "gender": "female",
                "birth_local_datetime": "1946-09-30T23:00",
                "location_id": 8200,
            },
        )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "ambiguous_local_time"


def test_supported_birth_range_endpoints() -> None:
    with TestClient(app) as client:
        for value in ("1901-01-01T00:00", "2100-12-31T23:59"):
            response = client.post(
                "/api/v1/charts",
                json={
                    "gender": "male",
                    "birth_local_datetime": value,
                    "location_id": 3101,
                },
            )
            assert response.status_code == 200, response.text


def test_out_of_range_birth_is_structured_error() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/charts",
            json={
                "gender": "male",
                "birth_local_datetime": "1900-12-31T23:59",
                "location_id": 3101,
            },
        )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unsupported_date_range"


def test_legacy_geoname_field_is_no_longer_accepted() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/charts",
            json={
                "gender": "male",
                "birth_local_datetime": "2024-05-01T22:50",
                "location_geoname_id": 3101,
            },
        )
    assert response.status_code == 422


def test_location_api_only_exposes_provinces_and_cities() -> None:
    with TestClient(app) as client:
        provinces = client.get("/api/v1/locations/provinces").json()
        shanghai = client.get("/api/v1/locations/cities", params={"province": "上海市"}).json()
        removed_statuses = [
            client.get("/api/v1/locations/countries").status_code,
            client.get("/api/v1/locations/admin1", params={"country": "CN"}).status_code,
            client.get("/api/v1/locations/counties").status_code,
            client.get("/api/v1/locations/3101").status_code,
        ]
    assert len(provinces) == 34
    assert shanghai == [{"code": 3101, "name": "上海市", "longitude": 121.47, "latitude": 31.23}]
    assert removed_statuses == [404, 404, 404, 404]
