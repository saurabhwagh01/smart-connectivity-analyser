import asyncio
import json

import pytest
from fastapi import HTTPException

import backend.main as main


class ConnectedRequest:
    async def is_disconnected(self):
        return False


class DisconnectedRequest:
    async def is_disconnected(self):
        return True


def decode_events(chunks):
    events = []
    for chunk in chunks:
        if not chunk.startswith("event: "):
            continue
        name, payload = chunk.split("\n", 1)
        events.append((name.removeprefix("event: "), json.loads(payload.removeprefix("data: ").strip())))
    return events


def collect_stream(request, profile_id=None):
    async def collect():
        return [
            chunk async for chunk in main.diagnostic_progress_events(request, profile_id)
        ]

    return asyncio.run(collect())


def test_stream_emits_progress_and_preserves_the_existing_result(monkeypatch):
    expected = {
        "target": "1.1.1.1",
        "packets_sent": 4,
        "packets_received": 4,
        "packet_loss": 0.0,
        "ping_ms": 10.5,
        "jitter_ms": 1.0,
        "status": "excellent",
    }

    async def fake_measure(packet_count):
        assert packet_count == 4  # Quick profile's real configured packet count.
        return expected

    monkeypatch.setattr(main, "measure_ping_async", fake_measure)
    chunks = collect_stream(ConnectedRequest(), "quick")
    events = decode_events(chunks)

    assert events[0] == ("progress", {
        "stage": "ping",
        "status": "started",
        "completed": [],
    })
    assert events[1] == ("progress", {
        "stage": "ping",
        "status": "completed",
        "completed": ["ping"],
    })
    result = next(payload for name, payload in events if name == "result")
    assert result["profile"] == "quick"
    assert result["ping_ms"] == expected["ping_ms"]
    assert result["checks"]["ping"]["status"] == "ok"
    assert events[-1] == ("done", {"status": "completed"})


def test_stream_sends_a_failure_event_without_fabricating_a_result(monkeypatch):
    async def failed_measure(_packet_count):
        raise HTTPException(status_code=503, detail="Ping command unavailable.")

    monkeypatch.setattr(main, "measure_ping_async", failed_measure)
    events = decode_events(collect_stream(ConnectedRequest()))

    assert ("progress", {
        "stage": "ping",
        "status": "started",
        "completed": [],
    }) in events
    assert ("progress", {
        "stage": "ping",
        "status": "failed",
        "completed": [],
    }) in events
    assert ("failure", {
        "status_code": 503,
        "detail": "Ping command unavailable.",
    }) in events
    assert not any(name == "result" for name, _ in events)
    assert events[-1] == ("done", {"status": "failed"})


def test_disconnected_client_cancels_the_active_diagnostic(monkeypatch):
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def slow_measure(_packet_count):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    monkeypatch.setattr(main, "measure_ping_async", slow_measure)
    chunks = collect_stream(DisconnectedRequest())

    assert any("status" in chunk and "started" in chunk for chunk in chunks)
    assert started.is_set()
    assert cancelled.is_set()
    assert not any("event: result" in chunk for chunk in chunks)


def test_cancelling_async_ping_kills_and_reaps_the_child_process(monkeypatch):
    started = asyncio.Event()

    class FakeProcess:
        returncode = None

        async def communicate(self):
            started.set()
            await asyncio.Event().wait()

        def kill(self):
            self.returncode = -9

        async def wait(self):
            return self.returncode

    process = FakeProcess()

    async def fake_create_subprocess_exec(*_args, **_kwargs):
        return process

    monkeypatch.setattr(main, "build_ping_command", lambda *_args: ["ping", "1.1.1.1"])
    monkeypatch.setattr(main.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    async def run_and_cancel():
        task = asyncio.create_task(main.measure_ping_async(4))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run_and_cancel())
    assert process.returncode == -9


def test_stream_route_keeps_the_event_stream_content_type(client, monkeypatch):
    async def fake_measure(_packet_count):
        return {
            "target": "1.1.1.1",
            "packets_sent": 10,
            "packets_received": 10,
            "packet_loss": 0.0,
            "ping_ms": 12.0,
            "jitter_ms": 1.0,
            "status": "excellent",
        }

    monkeypatch.setattr(main, "measure_ping_async", fake_measure)
    response = client.get("/api/network-quality/stream")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: progress" in response.text
    assert "event: result" in response.text
    assert "event: done" in response.text


def test_stream_rejects_an_unknown_profile_before_opening(client):
    response = client.get("/api/network-quality/stream?profile=not-a-profile")

    assert response.status_code == 400
    assert "Unknown diagnostic profile" in response.json()["detail"]["error"]
