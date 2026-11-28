from datetime import datetime, timedelta
import sqlite3

from test_network_test_validation import VALID_TEST, post_test
import backend.main as main


def save_record(client, timestamp):
    response = post_test(
        client,
        {**VALID_TEST, "timestamp": timestamp},
    )
    assert response.status_code == 200
    return response


def test_delete_selected_history_records_only_removes_requested_ids(client):
    first = save_record(client, "2026-11-20T10:00:00Z").json()["id"]
    second = save_record(client, "2026-11-21T10:00:00Z").json()["id"]
    third = save_record(client, "2026-11-22T10:00:00Z").json()["id"]

    response = client.request(
        "DELETE", "/api/network-history", json={"ids": [first, third]}
    )

    assert response.status_code == 200
    assert response.json()["deleted_count"] == 2
    remaining = client.get("/api/network-history?range=all").json()
    assert [item["id"] for item in remaining] == [second]


def test_delete_all_requires_explicit_all_flag_and_clears_history(client):
    save_record(client, "2026-11-20T10:00:00Z")

    missing_confirmation = client.request("DELETE", "/api/network-history")
    assert missing_confirmation.status_code == 422
    assert client.get("/api/network-history?range=all").json()

    response = client.delete("/api/network-history?all=true")
    assert response.status_code == 200
    assert response.json()["deleted_count"] == 1
    assert client.get("/api/network-history?range=all").json() == []


def test_delete_rejects_invalid_or_unbounded_ids(client):
    for ids in ([], [0], [-1], [True], list(range(1, 502))):
        response = client.request(
            "DELETE", "/api/network-history", json={"ids": ids}
        )
        assert response.status_code == 422


def test_delete_reports_database_failure_without_exposing_details(client, monkeypatch):
    def fail_connection():
        raise sqlite3.OperationalError("private database path")

    monkeypatch.setattr(main, "get_connection", fail_connection)
    response = client.delete("/api/network-history?all=true")

    assert response.status_code == 500
    assert "private database path" not in response.text


def test_retention_uses_configured_days_and_deletes_only_one_bounded_batch(
    client, monkeypatch
):
    now = datetime.now().replace(microsecond=0)
    expired = (now - timedelta(days=400)).isoformat()
    recent = (now - timedelta(days=29)).isoformat()

    monkeypatch.setenv("NETWORK_HISTORY_RETENTION_DAYS", "3650")
    for _ in range(501):
        save_record(client, expired)
    recent_id = save_record(client, recent).json()["id"]

    monkeypatch.setenv("NETWORK_HISTORY_RETENTION_DAYS", "30")
    # Trigger one bounded cleanup pass with a fresh measurement.
    current_id = save_record(client, now.isoformat()).json()["id"]

    records = client.get("/api/network-history?range=all").json()
    assert len(records) == 3
    assert {record["id"] for record in records} == {501, recent_id, current_id}
