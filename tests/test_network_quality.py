import subprocess

import pytest

import backend.main as main
from backend.main import build_ping_command, parse_ping_output


# ------------------------------------------------------------
# Sample `ping` outputs from each operating system.
# Tests use saved text, so they never need a real network.
# ------------------------------------------------------------

WINDOWS_OUTPUT = """
Pinging 1.1.1.1 with 32 bytes of data:
Reply from 1.1.1.1: bytes=32 time=12ms TTL=57
Reply from 1.1.1.1: bytes=32 time=15ms TTL=57

Ping statistics for 1.1.1.1:
    Packets: Sent = 2, Received = 2, Lost = 0 (0% loss),
"""

LINUX_OUTPUT = """
PING 1.1.1.1 (1.1.1.1) 56(84) bytes of data.
64 bytes from 1.1.1.1: icmp_seq=1 ttl=57 time=12.4 ms
64 bytes from 1.1.1.1: icmp_seq=2 ttl=57 time=11.9 ms
64 bytes from 1.1.1.1: icmp_seq=3 ttl=57 time=13.1 ms

--- 1.1.1.1 ping statistics ---
4 packets transmitted, 3 received, 25% packet loss, time 3004ms
rtt min/avg/max/mdev = 11.9/12.4/13.1/0.5 ms
"""

MACOS_OUTPUT = """
PING 1.1.1.1 (1.1.1.1): 56 data bytes
64 bytes from 1.1.1.1: icmp_seq=0 ttl=57 time=12.345 ms
64 bytes from 1.1.1.1: icmp_seq=1 ttl=57 time=11.876 ms

--- 1.1.1.1 ping statistics ---
2 packets transmitted, 2 packets received, 0.0% packet loss
round-trip min/avg/max/stddev = 11.876/12.111/12.345/0.235 ms
"""


def test_parses_windows_output():
    ping_times, packet_loss = parse_ping_output(WINDOWS_OUTPUT)

    assert ping_times == [12.0, 15.0]
    assert packet_loss == 0.0


def test_parses_linux_output_with_decimal_times():
    ping_times, packet_loss = parse_ping_output(LINUX_OUTPUT)

    assert ping_times == [12.4, 11.9, 13.1]
    assert packet_loss == 25.0


def test_parses_macos_output_with_decimal_loss():
    ping_times, packet_loss = parse_ping_output(MACOS_OUTPUT)

    assert ping_times == [12.345, 11.876]
    assert packet_loss == 0.0


def test_ignores_linux_summary_time():
    # "time 3004ms" in the summary line is the total run time,
    # not a ping reply, so it must not be counted.
    ping_times, _ = parse_ping_output(LINUX_OUTPUT)

    assert 3004.0 not in ping_times


def test_returns_none_when_loss_line_is_missing():
    ping_times, packet_loss = parse_ping_output("")

    assert ping_times == []
    assert packet_loss is None


# ------------------------------------------------------------
# Ping command for each operating system
# ------------------------------------------------------------

def test_builds_windows_command():
    command = build_ping_command("1.1.1.1", 10, 2, "Windows")

    assert command == ["ping", "-n", "10", "-w", "2000", "1.1.1.1"]


def test_builds_linux_command():
    command = build_ping_command("1.1.1.1", 10, 2, "Linux")

    assert command == ["ping", "-c", "10", "-W", "2", "1.1.1.1"]


def test_builds_macos_command():
    command = build_ping_command("1.1.1.1", 10, 2, "Darwin")

    assert command == ["ping", "-c", "10", "-W", "2000", "1.1.1.1"]


# ------------------------------------------------------------
# /api/network-quality endpoint (ping is mocked, no network)
# ------------------------------------------------------------

def fake_ping(monkeypatch, stdout="", stderr="", error=None):
    """Replace subprocess.run so the endpoint never runs real ping."""

    def fake_run(command, **kwargs):
        if error is not None:
            raise error
        return subprocess.CompletedProcess(command, 0, stdout, stderr)

    monkeypatch.setattr(main.subprocess, "run", fake_run)


def test_endpoint_reports_linux_metrics(client, monkeypatch):
    # The bug from issue #43: this used to return
    # "unreachable" with 100% packet loss.
    fake_ping(monkeypatch, stdout=LINUX_OUTPUT)

    response = client.get("/api/network-quality")

    assert response.status_code == 200
    data = response.json()
    assert data["packets_received"] == 3
    assert data["packet_loss"] == 25.0
    assert data["ping_ms"] == 12.47
    assert data["status"] == "excellent"


def test_endpoint_reports_real_total_loss_as_unreachable(client, monkeypatch):
    # A real outage: ping ran and printed a summary with 100% loss.
    fake_ping(
        monkeypatch,
        stdout="10 packets transmitted, 0 received, 100% packet loss",
    )

    response = client.get("/api/network-quality")

    assert response.status_code == 200
    assert response.json()["status"] == "unreachable"
    assert response.json()["packet_loss"] == 100.0


def test_endpoint_returns_503_when_ping_is_missing(client, monkeypatch):
    fake_ping(monkeypatch, error=FileNotFoundError("ping"))

    response = client.get("/api/network-quality")

    assert response.status_code == 503
    assert "not available" in response.json()["detail"]


def test_endpoint_returns_503_when_ping_cannot_run(client, monkeypatch):
    fake_ping(monkeypatch, stderr="ping: socket: Operation not permitted")

    response = client.get("/api/network-quality")

    assert response.status_code == 503
    assert "Operation not permitted" in response.json()["detail"]
