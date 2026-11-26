import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import backend.main as main
from backend.diagnostic_profiles import (
    PROFILES,
    Check,
    DiagnosticProfile,
    build_profile_result,
)

client = TestClient(main.app)

GOOD_PING = {
    "target": "1.1.1.1",
    "packets_sent": 10,
    "packets_received": 10,
    "packet_loss": 0.0,
    "ping_ms": 20.0,
    "min_ping_ms": 18.0,
    "max_ping_ms": 25.0,
    "jitter_ms": 2.0,
    "samples": [20.0] * 10,
    "status": "excellent",
}


@pytest.fixture
def fake_ping(monkeypatch):
    calls = []

    def _fake(packet_count=10):
        calls.append(packet_count)
        return dict(GOOD_PING, packets_sent=packet_count,
                    packets_received=packet_count)

    monkeypatch.setattr(main, "measure_ping", _fake)
    return calls


def test_no_profile_keeps_original_response(fake_ping):
    response = client.get("/api/network-quality")
    assert response.status_code == 200
    body = response.json()
    assert "profile" not in body and "checks" not in body
    assert body["jitter_ms"] == 2.0
    assert fake_ping == [10]


@pytest.mark.parametrize("profile_id", list(PROFILES))
def test_each_profile_runs_only_its_documented_checks(fake_ping, profile_id):
    profile = PROFILES[profile_id]
    body = client.get(
        "/api/network-quality", params={"profile": profile_id}
    ).json()

    assert body["profile"] == profile_id
    assert set(body["checks"]) == {c.value for c in profile.checks}
    assert fake_ping == [profile.packet_count]
    assert "measured_at" in body
    assert ("jitter_ms" in body) == (Check.JITTER in profile.checks)
    assert ("packet_loss" in body) == (Check.PACKET_LOSS in profile.checks)


def test_quick_has_no_jitter_and_detailed_marks_bandwidth_client_side(fake_ping):
    quick = client.get("/api/network-quality?profile=quick").json()
    assert "jitter_ms" not in quick

    detailed = client.get("/api/network-quality?profile=detailed").json()
    assert detailed["checks"]["download"]["status"] == "client_side"
    assert detailed["checks"]["upload"]["status"] == "client_side"


@pytest.mark.parametrize("bad", ["nope", "QUICK", "", "quick;drop"])
def test_unknown_profile_returns_400_with_valid_list(fake_ping, bad):
    response = client.get("/api/network-quality", params={"profile": bad})
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert set(detail["valid_profiles"]) == set(PROFILES)
    assert fake_ping == []  # nothing was measured


def test_profiles_endpoint_lists_all_profiles():
    body = client.get("/api/diagnostic-profiles").json()
    assert {p["id"] for p in body["profiles"]} == {"quick", "detailed", "stability"}


def test_partial_failure_when_single_reply_has_no_jitter():
    ping = dict(GOOD_PING, packets_received=1, jitter_ms=0.0)
    result = build_profile_result(PROFILES["stability"], ping)
    assert result["checks"]["jitter"]["status"] == "failed"
    assert result["jitter_ms"] is None
    assert result["result_status"] == "partial"


def test_unreachable_network_is_failed_not_fake_zero():
    ping = {
        "target": "1.1.1.1", "packets_sent": 10, "packets_received": 0,
        "packet_loss": 100.0, "ping_ms": None, "jitter_ms": None,
        "status": "unreachable",
    }
    result = build_profile_result(PROFILES["quick"], ping)
    assert result["ping_ms"] is None
    assert result["checks"]["ping"]["status"] == "failed"


def test_packet_loss_none_is_failed():
    ping = dict(GOOD_PING, packet_loss=None)
    result = build_profile_result(PROFILES["quick"], ping)

    assert result["packet_loss"] is None
    assert result["checks"]["packet_loss"]["status"] == "failed"
    assert "missing or invalid" in result["checks"]["packet_loss"]["reason"]


def test_missing_packet_loss_is_failed():
    ping = dict(GOOD_PING)
    del ping["packet_loss"]
    result = build_profile_result(PROFILES["quick"], ping)

    assert result["packet_loss"] is None
    assert result["checks"]["packet_loss"]["status"] == "failed"


def test_packet_loss_zero_is_a_valid_measurement():
    result = build_profile_result(PROFILES["quick"], dict(GOOD_PING, packet_loss=0))

    assert result["packet_loss"] == 0
    assert result["checks"]["packet_loss"]["status"] == "ok"


def test_profile_config_validation_rejects_bad_config():
    base = dict(id="x", label="X", description="d", estimated_seconds=1)
    with pytest.raises(ValidationError):  # jitter with 1 packet
        DiagnosticProfile(**base, checks=(Check.JITTER,), packet_count=1)
    with pytest.raises(ValidationError):  # duplicate checks
        DiagnosticProfile(**base, checks=(Check.PING, Check.PING), packet_count=4)
    with pytest.raises(ValidationError):  # only client-side checks
        DiagnosticProfile(**base, checks=(Check.DOWNLOAD,), packet_count=4)
    with pytest.raises(ValidationError):  # invalid id
        DiagnosticProfile(**{**base, "id": "Bad Id"}, checks=(Check.PING,), packet_count=4)