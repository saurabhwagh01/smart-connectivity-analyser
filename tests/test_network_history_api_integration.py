import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

import backend.main as main


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    """Fixture providing an isolated SQLite database path and initialized schema."""
    db_file = tmp_path / "test_history_integration.db"
    monkeypatch.setattr(main, "DB_PATH", db_file)
    main.initialize_database()
    return db_file


@pytest.fixture
def client_with_isolated_db(isolated_db):
    """TestClient backed by isolated_db."""
    with TestClient(main.app) as test_client:
        yield test_client


def insert_raw_history_record(db_path: Path, **kwargs):
    """Helper to insert controlled raw records directly into the SQLite database."""
    defaults = {
        "timestamp": datetime.now().isoformat(),
        "download_mbps": 50.0,
        "upload_mbps": 20.0,
        "ping_ms": 25.0,
        "jitter_ms": 3.0,
        "packet_loss": 0.1,
        "network_type": "WiFi",
        "connectivity_score": 88.0,
        "latitude": 37.7749,
        "longitude": -122.4194,
    }
    defaults.update(kwargs)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO network_tests (
            timestamp,
            download_mbps,
            upload_mbps,
            ping_ms,
            jitter_ms,
            packet_loss,
            network_type,
            connectivity_score,
            latitude,
            longitude
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            defaults["timestamp"],
            defaults["download_mbps"],
            defaults["upload_mbps"],
            defaults["ping_ms"],
            defaults["jitter_ms"],
            defaults["packet_loss"],
            defaults["network_type"],
            defaults["connectivity_score"],
            defaults["latitude"],
            defaults["longitude"],
        ),
    )
    conn.commit()
    conn.close()


# =========================================================================
# A. Historical Records Retrieval & Verification
# =========================================================================

def test_api_network_history_retrieves_sqlite_records_accurately(client_with_isolated_db, isolated_db):
    """Verify that multiple historical records in SQLite are accurately returned by /api/network-history."""
    base_time = datetime.now() - timedelta(hours=2)
    sample_records = [
        {
            "timestamp": (base_time + timedelta(minutes=10)).isoformat(),
            "download_mbps": 42.5,
            "upload_mbps": 12.0,
            "ping_ms": 30.5,
            "jitter_ms": 4.1,
            "packet_loss": 0.0,
            "network_type": "WiFi",
            "connectivity_score": 85.0,
        },
        {
            "timestamp": (base_time + timedelta(minutes=30)).isoformat(),
            "download_mbps": 95.2,
            "upload_mbps": 35.8,
            "ping_ms": 14.2,
            "jitter_ms": 1.8,
            "packet_loss": 0.2,
            "network_type": "Ethernet",
            "connectivity_score": 96.0,
        },
        {
            "timestamp": (base_time + timedelta(minutes=50)).isoformat(),
            "download_mbps": 18.0,
            "upload_mbps": 5.2,
            "ping_ms": 65.0,
            "jitter_ms": 8.5,
            "packet_loss": 1.5,
            "network_type": "Cellular",
            "connectivity_score": 62.0,
        },
    ]

    for rec in sample_records:
        insert_raw_history_record(isolated_db, **rec)

    response = client_with_isolated_db.get("/api/network-history?range=all")
    assert response.status_code == 200

    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 3

    # Verify chronological ordering by timestamp ASC
    returned_timestamps = [item["timestamp"] for item in data]
    assert returned_timestamps == sorted(returned_timestamps)

    # Verify all expected schema fields match SQLite values and frontend expectations
    expected_fields = {
        "id",
        "timestamp",
        "download_mbps",
        "upload_mbps",
        "ping_ms",
        "jitter_ms",
        "packet_loss",
        "network_type",
        "connectivity_score",
        "latitude",
        "longitude",
    }
    for item in data:
        assert expected_fields.issubset(item.keys())

    # Deep match values for the second record
    second = data[1]
    assert second["download_mbps"] == 95.2
    assert second["upload_mbps"] == 35.8
    assert second["ping_ms"] == 14.2
    assert second["jitter_ms"] == 1.8
    assert second["packet_loss"] == 0.2
    assert second["network_type"] == "Ethernet"
    assert second["connectivity_score"] == 96.0


# =========================================================================
# B. Empty Database Response
# =========================================================================

def test_api_network_history_empty_database_returns_empty_list(client_with_isolated_db):
    """Verify that an empty database returns HTTP 200 with an empty list."""
    response = client_with_isolated_db.get("/api/network-history?range=all")
    assert response.status_code == 200
    assert response.json() == []

    # Also test recent range on empty database
    response_recent = client_with_isolated_db.get("/api/network-history?range=recent")
    assert response_recent.status_code == 200
    assert response_recent.json() == []


# =========================================================================
# C. API Error Handling
# =========================================================================

def test_api_network_history_database_error_handling(client_with_isolated_db, monkeypatch):
    """Verify that a database query or connection error raises an appropriate HTTP 500 error."""
    def broken_connection():
        raise sqlite3.OperationalError("Simulated database failure (disk I/O error)")

    monkeypatch.setattr(main, "get_connection", broken_connection)

    with pytest.raises(sqlite3.OperationalError) as exc_info:
        client_with_isolated_db.get("/api/network-history?range=all")

    assert "Simulated database failure" in str(exc_info.value)


# =========================================================================
# D. Range and Date Filtering
# =========================================================================

def test_api_network_history_time_window_filtering(client_with_isolated_db, isolated_db):
    """Verify that the range parameter correctly filters records within recent vs 1h vs 24h."""
    now = datetime.now()
    # 1. 20 minutes ago (within 1h)
    insert_raw_history_record(isolated_db, timestamp=(now - timedelta(minutes=20)).isoformat(), download_mbps=80.0)
    # 2. 3 hours ago (outside 1h, within 24h)
    insert_raw_history_record(isolated_db, timestamp=(now - timedelta(hours=3)).isoformat(), download_mbps=60.0)
    # 3. 2 days ago (outside 24h, within 7d)
    insert_raw_history_record(isolated_db, timestamp=(now - timedelta(days=2)).isoformat(), download_mbps=40.0)

    # 1h filter
    res_1h = client_with_isolated_db.get("/api/network-history?range=1h")
    assert res_1h.status_code == 200
    assert len(res_1h.json()) == 1
    assert res_1h.json()[0]["download_mbps"] == 80.0

    # 24h filter
    res_24h = client_with_isolated_db.get("/api/network-history?range=24h")
    assert res_24h.status_code == 200
    assert len(res_24h.json()) == 2

    # all filter
    res_all = client_with_isolated_db.get("/api/network-history?range=all")
    assert res_all.status_code == 200
    assert len(res_all.json()) == 3
