from datetime import datetime, timezone

import pytest

# Payload shaped like the one js/script.js sends after a test,
# including its toISOString() timestamp format.
VALID_TEST = {
    "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
    "download_mbps": 54.2,
    "upload_mbps": 12.8,
    "ping_ms": 21,
    "jitter_ms": 3.5,
    "packet_loss": 0,
    "network_type": "Wi-Fi",
    "connectivity_score": 88,
    "latitude": 30.3165,
    "longitude": 78.0322,
}


def post_test(client, payload):
    return client.post("/api/network-test", json=payload)


def post_raw(client, body):
    return client.post(
        "/api/network-test",
        content=body,
        headers={"Content-Type": "application/json"},
    )


def error_fields(response):
    return [error["loc"][-1] for error in response.json()["detail"]]


# ============================================================
# VALID REQUESTS
# ============================================================

def test_valid_test_is_saved_and_returned_in_history(client):
    response = post_test(client, VALID_TEST)

    assert response.status_code == 200
    assert response.json()["status"] == "success"

    history = client.get("/api/network-history?range=monthly")

    assert history.status_code == 200
    saved = history.json()[0]
    for field, value in VALID_TEST.items():
        assert saved[field] == value


def test_missing_measurements_are_stored_as_null_not_zero(client):
    payload = {
        **VALID_TEST,
        "packet_loss": None,
        "jitter_ms": None,
        "latitude": None,
        "longitude": None,
    }

    response = post_test(client, payload)

    assert response.status_code == 200
    saved = client.get("/api/network-history?range=monthly").json()[0]
    assert saved["packet_loss"] is None
    assert saved["jitter_ms"] is None
    assert saved["latitude"] is None
    assert saved["longitude"] is None


def test_single_measurement_is_accepted(client):
    response = post_test(client, {"ping_ms": 18})

    assert response.status_code == 200


@pytest.mark.parametrize("timestamp", [None, ""])
def test_missing_timestamp_defaults_to_server_time(client, timestamp):
    response = post_test(client, {"ping_ms": 18, "timestamp": timestamp})

    assert response.status_code == 200
    saved = client.get("/api/network-history").json()[0]
    assert saved["timestamp"]


def test_boundary_values_are_accepted(client):
    payload = {
        "download_mbps": 0,
        "upload_mbps": 0,
        "ping_ms": 0,
        "jitter_ms": 0,
        "packet_loss": 100,
        "connectivity_score": 100,
        "latitude": -90,
        "longitude": 180,
    }

    response = post_test(client, payload)

    assert response.status_code == 200


def test_numeric_strings_are_still_accepted(client):
    response = post_test(client, {"download_mbps": "12.5"})

    assert response.status_code == 200


# ============================================================
# INVALID REQUESTS
# ============================================================

def test_record_without_any_measurement_is_rejected(client):
    response = post_test(client, {"network_type": "Wi-Fi"})

    assert response.status_code == 422
    assert "At least one network measurement" in response.text


def test_empty_object_is_rejected(client):
    response = post_test(client, {})

    assert response.status_code == 422


@pytest.mark.parametrize(
    "field, value",
    [
        ("download_mbps", -1),
        ("upload_mbps", -0.5),
        ("ping_ms", -10),
        ("jitter_ms", -2),
        ("packet_loss", -1),
        ("packet_loss", 100.1),
        ("connectivity_score", -1),
        ("connectivity_score", 150),
        ("latitude", 90.5),
        ("latitude", -91),
        ("longitude", 181),
        ("longitude", -180.5),
    ],
)
def test_out_of_range_values_are_rejected(client, field, value):
    payload = {**VALID_TEST, field: value}

    response = post_test(client, payload)

    assert response.status_code == 422
    assert field in error_fields(response)


@pytest.mark.parametrize(
    "field, value",
    [
        ("download_mbps", "fast"),
        ("ping_ms", [20]),
        ("packet_loss", {"value": 1}),
        ("connectivity_score", True),
        ("download_mbps", False),
    ],
)
def test_wrong_value_types_are_rejected(client, field, value):
    payload = {**VALID_TEST, field: value}

    response = post_test(client, payload)

    assert response.status_code == 422
    assert field in error_fields(response)


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_numbers_are_rejected(client, value):
    response = post_raw(client, f'{{"download_mbps": {value}}}')

    assert response.status_code == 422
    assert "download_mbps" in error_fields(response)


def test_non_finite_number_does_not_break_history(client):
    post_raw(client, '{"download_mbps": Infinity}')

    history = client.get("/api/network-history")

    assert history.status_code == 200
    assert history.json() == []


@pytest.mark.parametrize(
    "timestamp",
    ["not-a-date", "2026-13-01T10:00:00", "01/11/2026 10:00", "yesterday"],
)
def test_invalid_timestamp_is_rejected(client, timestamp):
    response = post_test(client, {**VALID_TEST, "timestamp": timestamp})

    assert response.status_code == 422
    assert "timestamp" in error_fields(response)


@pytest.mark.parametrize(
    "location",
    [
        {"latitude": 30.3, "longitude": None},
        {"latitude": None, "longitude": 78.0},
    ],
)
def test_partial_location_is_rejected(client, location):
    response = post_test(client, {**VALID_TEST, **location})

    assert response.status_code == 422
    assert "latitude and longitude" in response.text


def test_overlong_network_type_is_rejected(client):
    response = post_test(client, {**VALID_TEST, "network_type": "x" * 51})

    assert response.status_code == 422
    assert "network_type" in error_fields(response)


@pytest.mark.parametrize("body", ["", "not json", "[1, 2, 3]", "null"])
def test_malformed_body_is_rejected(client, body):
    response = post_raw(client, body)

    assert response.status_code == 422


def test_invalid_request_is_not_saved(client):
    post_test(client, {**VALID_TEST, "packet_loss": 250})

    history = client.get("/api/network-history?range=monthly")

    assert history.json() == []
