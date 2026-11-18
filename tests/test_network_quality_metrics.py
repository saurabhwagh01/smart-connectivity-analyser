import subprocess

import backend.main as main


def mock_ping(monkeypatch, output, returncode=0):
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=returncode,
            stdout=output,
            stderr="",
        )

    monkeypatch.setattr(main.subprocess, "run", fake_run)


def test_one_ping_returns_unavailable_jitter(client, monkeypatch):
    mock_ping(
        monkeypatch,
        "Reply from 1.1.1.1: bytes=32 time=20ms TTL=58\n",
    )

    response = client.get("/api/network-quality")

    assert response.status_code == 200
    assert response.json()["ping_ms"] == 20.0
    assert response.json()["jitter_ms"] is None


def test_multiple_pings_calculate_jitter(client, monkeypatch):
    mock_ping(
        monkeypatch,
        "Reply from 1.1.1.1: bytes=32 time=20ms TTL=58\n"
        "Reply from 1.1.1.1: bytes=32 time=30ms TTL=58\n",
    )

    response = client.get("/api/network-quality")

    assert response.status_code == 200
    assert response.json()["jitter_ms"] == 10.0


def test_real_zero_jitter_is_preserved(client, monkeypatch):
    mock_ping(
        monkeypatch,
        "Reply from 1.1.1.1: bytes=32 time=20ms TTL=58\n"
        "Reply from 1.1.1.1: bytes=32 time=20ms TTL=58\n",
    )

    response = client.get("/api/network-quality")

    assert response.status_code == 200
    assert response.json()["jitter_ms"] == 0.0


def test_unreachable_network_returns_null_metrics(client, monkeypatch):
    mock_ping(
        monkeypatch,
        "Request timed out.\n",
        returncode=1,
    )

    response = client.get("/api/network-quality")

    assert response.status_code == 200, response.text
    assert response.json()["ping_ms"] is None
    assert response.json()["jitter_ms"] is None