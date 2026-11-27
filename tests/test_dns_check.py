import socket
import threading
import time
import subprocess

from fastapi.testclient import TestClient

import backend.main as main
from backend.dns_check import check_dns, classify_dns_error

client = TestClient(main.app)

NOT_FOUND = socket.EAI_NONAME if hasattr(socket, "EAI_NONAME") else 11001
TRY_AGAIN = socket.EAI_AGAIN if hasattr(socket, "EAI_AGAIN") else 11002


def ok_resolver(host, port):
    return [("addr",)]


def gaierror_resolver(code):
    def _resolver(host, port):
        raise socket.gaierror(code, "details that must never be exposed")
    return _resolver


def test_success_reports_duration():
    result = check_dns(resolver=ok_resolver)
    assert result["status"] == "ok"
    assert result["failure_category"] is None
    assert result["duration_ms"] >= 0


def test_resolution_failure_is_not_found():
    result = check_dns(resolver=gaierror_resolver(NOT_FOUND))
    assert result["status"] == "failed"
    assert result["failure_category"] == "not_found"
    assert result["duration_ms"] is not None


def test_unavailable_resolver_is_its_own_category():
    result = check_dns(resolver=gaierror_resolver(TRY_AGAIN))
    assert result["status"] == "failed"
    assert result["failure_category"] == "resolver_unavailable"


def test_timeout_is_bounded_and_has_no_duration():
    release = threading.Event()
    finished = threading.Event()

    def slow(host, port):
        release.wait(timeout=1)
        finished.set()

    started = time.perf_counter()
    result = check_dns(resolver=slow, timeout_seconds=0.05)
    elapsed = time.perf_counter() - started
    release.set()

    assert result["status"] == "failed"
    assert result["failure_category"] == "timeout"
    assert result["duration_ms"] is None
    assert elapsed < 0.4  # returned without waiting for the slow lookup
    assert finished.wait(timeout=1)


def test_repeated_timeouts_cannot_grow_resolver_workers():
    release = threading.Event()
    finished = threading.Event()
    lock = threading.Lock()
    started = 0
    completed = 0

    def blocked_resolver(host, port):
        nonlocal started, completed
        with lock:
            started += 1
        release.wait(timeout=1)
        with lock:
            completed += 1
            if completed == 2:
                finished.set()
        return []

    first = check_dns(resolver=blocked_resolver, timeout_seconds=0.01)
    second = check_dns(resolver=blocked_resolver, timeout_seconds=0.01)
    third = check_dns(resolver=blocked_resolver, timeout_seconds=0.01)

    assert first["failure_category"] == "timeout"
    assert second["failure_category"] == "timeout"
    assert third["failure_category"] == "capacity_exhausted"
    with lock:
        assert started <= 2

    release.set()
    assert finished.wait(timeout=1)


def test_unexpected_error_is_unknown_and_never_raises():
    def broken(host, port):
        raise RuntimeError("secret internal detail")

    result = check_dns(resolver=broken)
    assert result["status"] == "failed"
    assert result["failure_category"] == "unknown"
    assert "secret" not in str(result)


def test_result_never_exposes_resolver_details():
    result = check_dns(resolver=gaierror_resolver(NOT_FOUND))
    assert "details that must never be exposed" not in str(result)
    assert set(result) == {
        "check", "hostname", "status", "duration_ms",
        "failure_category", "measured_at",
    }


def test_classify_non_dns_errors_as_unknown():
    assert classify_dns_error(OSError("x")) == "unknown"


def test_endpoint_returns_200_even_when_dns_fails(monkeypatch):
    monkeypatch.setattr(
        main,
        "check_dns",
        lambda: {"check": "dns", "status": "failed", "failure_category": "timeout"},
    )
    response = client.get("/api/dns-check")
    assert response.status_code == 200
    assert response.json()["status"] == "failed"


def test_endpoint_reports_success(monkeypatch):
    monkeypatch.setattr(
        main,
        "check_dns",
        lambda: {"check": "dns", "status": "ok", "duration_ms": 12.3},
    )
    body = client.get("/api/dns-check").json()
    assert body["status"] == "ok"


def test_dns_timeouts_do_not_affect_network_measurements(monkeypatch):
    monkeypatch.setattr(
        main,
        "check_dns",
        lambda: {
            "check": "dns",
            "status": "failed",
            "duration_ms": None,
            "failure_category": "timeout",
        },
    )
    ping_output = (
        "Reply from 1.1.1.1: bytes=32 time=12ms TTL=57\n"
        "10 packets: Sent = 10, Received = 10, Lost = 0 (0% loss)"
    )
    monkeypatch.setattr(
        main.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(
            command, 0, ping_output, ""
        ),
    )

    dns_response = client.get("/api/dns-check")
    quality_response = client.get("/api/network-quality")

    assert dns_response.status_code == 200
    assert dns_response.json()["failure_category"] == "timeout"
    assert quality_response.status_code == 200
    assert quality_response.json()["ping_ms"] == 12.0
    assert quality_response.json()["packet_loss"] == 0.0


def test_dns_failures_do_not_affect_network_measurements(monkeypatch):
    monkeypatch.setattr(
        main,
        "check_dns",
        lambda: {
            "check": "dns",
            "status": "failed",
            "duration_ms": 2.1,
            "failure_category": "resolver_unavailable",
        },
    )
    ping_output = (
        "Reply from 1.1.1.1: bytes=32 time=16ms TTL=57\n"
        "10 packets: Sent = 10, Received = 10, Lost = 0 (0% loss)"
    )
    monkeypatch.setattr(
        main.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(
            command, 0, ping_output, ""
        ),
    )

    dns_response = client.get("/api/dns-check")
    quality_response = client.get("/api/network-quality")

    assert dns_response.status_code == 200
    assert dns_response.json()["failure_category"] == "resolver_unavailable"
    assert quality_response.status_code == 200
    assert quality_response.json()["ping_ms"] == 16.0
    assert quality_response.json()["packet_loss"] == 0.0
