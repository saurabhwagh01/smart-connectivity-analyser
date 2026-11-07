import sqlite3
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

import backend.main as main

SAMPLE_RECORD = {
    "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
    "download_mbps": 45.5,
    "upload_mbps": 15.2,
    "ping_ms": 25.0,
    "jitter_ms": 4.1,
    "packet_loss": 0.0,
    "network_type": "Wi-Fi",
    "connectivity_score": 92.0,
    "latitude": 37.7749,
    "longitude": -122.4194,
}


# ============================================================
# SUCCESS SCENARIOS
# ============================================================


def test_get_network_history_returns_saved_records(client):
    """Verify saved network records are returned correctly with all expected fields."""
    save_response = client.post("/api/network-test", json=SAMPLE_RECORD)
    assert save_response.status_code == 200

    response = client.get("/api/network-history?range=monthly")
    assert response.status_code == 200

    records = response.json()
    assert isinstance(records, list)
    assert len(records) == 1

    record = records[0]
    assert record["id"] is not None
    assert record["timestamp"] == SAMPLE_RECORD["timestamp"]
    assert record["download_mbps"] == SAMPLE_RECORD["download_mbps"]
    assert record["upload_mbps"] == SAMPLE_RECORD["upload_mbps"]
    assert record["ping_ms"] == SAMPLE_RECORD["ping_ms"]
    assert record["jitter_ms"] == SAMPLE_RECORD["jitter_ms"]
    assert record["packet_loss"] == SAMPLE_RECORD["packet_loss"]
    assert record["network_type"] == SAMPLE_RECORD["network_type"]
    assert record["connectivity_score"] == SAMPLE_RECORD["connectivity_score"]
    assert record["latitude"] == SAMPLE_RECORD["latitude"]
    assert record["longitude"] == SAMPLE_RECORD["longitude"]


def test_get_network_history_preserves_null_fields(client):
    """Verify optional fields stored as null are retrieved correctly."""
    partial_record = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "download_mbps": 50.0,
        "upload_mbps": 10.0,
        "ping_ms": 20.0,
        "jitter_ms": None,
        "packet_loss": None,
        "network_type": "Ethernet",
        "connectivity_score": 85.0,
        "latitude": None,
        "longitude": None,
    }
    client.post("/api/network-test", json=partial_record)

    response = client.get("/api/network-history?range=monthly")
    assert response.status_code == 200

    records = response.json()
    assert len(records) == 1
    assert records[0]["jitter_ms"] is None
    assert records[0]["packet_loss"] is None
    assert records[0]["latitude"] is None
    assert records[0]["longitude"] is None


def test_get_network_history_multiple_records_sorted_by_timestamp(client):
    """Verify multiple records are returned in chronological order (ASC)."""
    t1 = (datetime.now() - timedelta(minutes=10)).isoformat()
    t2 = (datetime.now() - timedelta(minutes=5)).isoformat()
    t3 = datetime.now().isoformat()

    client.post("/api/network-test", json={**SAMPLE_RECORD, "timestamp": t2, "download_mbps": 20.0})
    client.post("/api/network-test", json={**SAMPLE_RECORD, "timestamp": t1, "download_mbps": 10.0})
    client.post("/api/network-test", json={**SAMPLE_RECORD, "timestamp": t3, "download_mbps": 30.0})

    response = client.get("/api/network-history?range=hourly")
    assert response.status_code == 200

    records = response.json()
    assert len(records) == 3
    assert [r["download_mbps"] for r in records] == [10.0, 20.0, 30.0]


@pytest.mark.parametrize("range_param", ["hourly", "daily", "weekly", "monthly", "recent", "10", "20"])
def test_get_network_history_supports_all_range_options(client, range_param):
    """Verify different range queries work without errors."""
    client.post("/api/network-test", json=SAMPLE_RECORD)

    response = client.get(f"/api/network-history?range={range_param}")
    assert response.status_code == 200
    assert isinstance(response.json(), list)
    assert len(response.json()) == 1


# ============================================================
# EMPTY HISTORY SCENARIOS
# ============================================================


def test_get_network_history_empty_database_returns_empty_list(client):
    """Verify an empty database returns [] with HTTP 200 and no server error."""
    response = client.get("/api/network-history")

    assert response.status_code == 200
    assert response.json() == []


def test_get_network_history_no_matching_records_for_range(client):
    """Verify empty result when records exist but fall outside the requested time window."""
    old_time = (datetime.now() - timedelta(days=2)).isoformat()
    client.post("/api/network-test", json={**SAMPLE_RECORD, "timestamp": old_time})

    # Hourly range only covers past 24 hours
    response = client.get("/api/network-history?range=hourly")
    assert response.status_code == 200
    assert response.json() == []

    # Monthly range covers past 365 days, so the record is found
    response_monthly = client.get("/api/network-history?range=monthly")
    assert response_monthly.status_code == 200
    assert len(response_monthly.json()) == 1


# ============================================================
# DATABASE FAILURE SCENARIOS
# ============================================================


def test_get_network_history_table_missing(client):
    """Verify a clean 500 error when the network_tests table is missing."""
    conn = main.get_connection()
    conn.execute("DROP TABLE network_tests")
    conn.commit()
    conn.close()

    response = client.get("/api/network-history")

    assert response.status_code == 500
    assert response.json() == {
        "detail": "Failed to load network history from database"
    }


def test_get_network_history_corrupt_database(client):
    """Verify a clean 500 error when the database file is corrupt."""
    with open(main.DB_PATH, "wb") as f:
        f.write(b"NOT A VALID SQLITE DATABASE FILE")

    response = client.get("/api/network-history")

    assert response.status_code == 500
    assert response.json() == {
        "detail": "Failed to load network history from database"
    }


def test_get_network_history_query_sqlite_error(client, monkeypatch):
    """Verify a clean 500 error when cursor.execute raises sqlite3.OperationalError."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.execute.side_effect = sqlite3.OperationalError("database is locked")
    mock_conn.cursor.return_value = mock_cursor
    monkeypatch.setattr(main, "get_connection", lambda: mock_conn)

    response = client.get("/api/network-history")

    assert response.status_code == 500
    assert response.json() == {
        "detail": "Failed to load network history from database"
    }


def test_get_network_history_connection_failure(client, monkeypatch):
    """Verify a clean 500 error when connecting to the database raises sqlite3.Error."""
    def mock_connect(*args, **kwargs):
        raise sqlite3.OperationalError("unable to open database file")

    monkeypatch.setattr(sqlite3, "connect", mock_connect)

    response = client.get("/api/network-history")

    assert response.status_code == 500
    assert response.json() == {
        "detail": "Failed to load network history from database"
    }
