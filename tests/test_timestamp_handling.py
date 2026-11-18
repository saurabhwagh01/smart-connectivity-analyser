"""Automated regression tests for centralized UTC timestamp handling and normalization.

Covers:
- UTC timestamps (browser-generated and backend-generated)
- Positive and negative timezone offsets normalized to the exact UTC instant
- Date range filtering across midnight and calendar boundaries
- Deterministic secondary ordering on identical timestamps (tie-breaking via record ID)
- Safe handling and documented interpretation of legacy naive timestamps
- Accessibility and non-destructive retrieval of existing historical database records
- Deterministic chronological ordering in AI training-data loaders
"""

import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

import backend.main as main
from backend.ai_engine import load_network_data
from backend.final_predictor import final_predictor
from backend.timestamp_utils import (
    get_current_utc_timestamp,
    get_utc_date_boundaries,
    is_canonical_utc,
    migrate_legacy_timestamps,
    parse_iso_timestamp,
    to_canonical_utc,
    to_utc_sql,
)
from test_network_test_validation import VALID_TEST, post_test


# ============================================================
# 1. UNIT TESTS: TIMESTAMP UTILITIES
# ============================================================

def test_is_canonical_utc():
    assert is_canonical_utc("2026-11-01T12:00:00.000Z") is True
    assert is_canonical_utc("2026-11-01T23:59:59.999Z") is True

    # Non-canonical formats:
    assert is_canonical_utc("2026-11-01T12:00:00Z") is False  # missing ms
    assert is_canonical_utc("2026-11-01T12:00:00") is False  # naive
    assert is_canonical_utc("2026-11-01T17:30:00+05:30") is False  # offset
    assert is_canonical_utc("2026-11-01T12:00:00.123456Z") is False  # microsecond
    assert is_canonical_utc("not-a-date") is False


def test_parse_iso_timestamp_utc_variants():
    # Browser standard (with milliseconds + Z)
    dt1 = parse_iso_timestamp("2026-11-01T12:00:00.000Z")
    assert dt1.tzinfo == timezone.utc
    assert dt1.year == 2026 and dt1.month == 11 and dt1.day == 1
    assert dt1.hour == 12 and dt1.minute == 0 and dt1.second == 0

    # UTC without milliseconds
    dt2 = parse_iso_timestamp("2026-11-01T12:00:00Z")
    assert dt2 == dt1

    # UTC with +00:00 offset
    dt3 = parse_iso_timestamp("2026-11-01T12:00:00+00:00")
    assert dt3 == dt1


def test_parse_iso_timestamp_positive_and_negative_offsets():
    # IST (+05:30): 17:30 local -> 12:00 UTC
    dt_ist = parse_iso_timestamp("2026-11-01T17:30:00+05:30")
    assert dt_ist == datetime(2026, 11, 1, 12, 0, 0, tzinfo=timezone.utc)

    # PST (-08:00): 04:00 local -> 12:00 UTC
    dt_pst = parse_iso_timestamp("2026-11-01T04:00:00-08:00")
    assert dt_pst == datetime(2026, 11, 1, 12, 0, 0, tzinfo=timezone.utc)

    # Kathmandu (+05:45): 17:45 local -> 12:00 UTC
    dt_npt = parse_iso_timestamp("2026-11-01T17:45:00+05:45")
    assert dt_npt == datetime(2026, 11, 1, 12, 0, 0, tzinfo=timezone.utc)

    # Check canonical string output
    assert to_canonical_utc("2026-11-01T17:30:00+05:30") == "2026-11-01T12:00:00.000Z"
    assert to_canonical_utc("2026-11-01T04:00:00-08:00") == "2026-11-01T12:00:00.000Z"


def test_legacy_naive_timestamp_interpretation():
    """Documented interpretation: Naive timestamps represent local system time where measured.

    Assuming UTC for naive timestamps would distort measurement times by the local timezone offset.
    When a specific timezone is supplied (e.g. during migration or configured default_tz),
    it is applied before conversion to UTC. When None, system local time is presumed.
    """
    tz_ist = timezone(timedelta(hours=5, minutes=30))
    tz_est = timezone(timedelta(hours=-5))

    naive_str = "2026-11-01T12:00:00"

    # In IST (+05:30), 12:00 local is 06:30 UTC
    canonical_ist = to_canonical_utc(naive_str, default_tz=tz_ist)
    assert canonical_ist == "2026-11-01T06:30:00.000Z"

    # In EST (-05:00), 12:00 local is 17:00 UTC
    canonical_est = to_canonical_utc(naive_str, default_tz=tz_est)
    assert canonical_est == "2026-11-01T17:00:00.000Z"

    # Default system conversion preserves instant relative to system local time
    dt_local = parse_iso_timestamp(naive_str)
    assert dt_local.tzinfo == timezone.utc


def test_get_current_utc_timestamp_is_canonical():
    ts = get_current_utc_timestamp()
    assert is_canonical_utc(ts)
    dt = parse_iso_timestamp(ts)
    now_utc = datetime.now(timezone.utc)
    # Ensure current timestamp is within a few seconds of now
    assert abs((now_utc - dt).total_seconds()) < 5


def test_get_utc_date_boundaries():
    start_b, end_b = get_utc_date_boundaries(date(2026, 11, 1), date(2026, 11, 5))
    assert start_b == "2026-11-01T00:00:00.000Z"
    assert end_b == "2026-11-06T00:00:00.000Z"

    # Partial boundaries
    start_only, _ = get_utc_date_boundaries(date(2026, 11, 1), None)
    assert start_only == "2026-11-01T00:00:00.000Z"

    _, end_only = get_utc_date_boundaries(None, date(2026, 11, 5))
    assert end_only == "2026-11-06T00:00:00.000Z"


def test_migrate_legacy_timestamps(tmp_path):
    db_file = tmp_path / "test_migration.db"
    with sqlite3.connect(db_file) as conn:
        conn.execute(
            """
            CREATE TABLE network_tests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                download_mbps REAL
            )
            """
        )
        conn.execute(
            "INSERT INTO network_tests (timestamp, download_mbps) VALUES (?, ?)",
            ("2026-11-01T12:00:00.000Z", 50.0),  # already canonical
        )
        conn.execute(
            "INSERT INTO network_tests (timestamp, download_mbps) VALUES (?, ?)",
            ("2026-11-01T17:30:00+05:30", 60.0),  # offset
        )
        conn.execute(
            "INSERT INTO network_tests (timestamp, download_mbps) VALUES (?, ?)",
            ("2026-11-01T12:00:00", 70.0),  # naive
        )
        conn.commit()

    tz_ist = timezone(timedelta(hours=5, minutes=30))

    # Test dry run
    dry_report = migrate_legacy_timestamps(db_file, dry_run=True, default_tz=tz_ist)
    assert dry_report["status"] == "success"
    assert dry_report["total_records"] == 3
    assert dry_report["migrated"] == 2  # 2 non-canonical records detected

    # Verify no database rows were actually changed during dry run
    with sqlite3.connect(db_file) as conn:
        rows = conn.execute("SELECT id, timestamp FROM network_tests ORDER BY id ASC").fetchall()
        assert rows[1][1] == "2026-11-01T17:30:00+05:30"
        assert rows[2][1] == "2026-11-01T12:00:00"

    # Test actual safe migration
    exec_report = migrate_legacy_timestamps(db_file, dry_run=False, default_tz=tz_ist)
    assert exec_report["status"] == "success"
    assert exec_report["migrated"] == 2

    # Verify database rows are now all canonical UTC
    with sqlite3.connect(db_file) as conn:
        rows = conn.execute("SELECT id, timestamp FROM network_tests ORDER BY id ASC").fetchall()
        assert rows[0][1] == "2026-11-01T12:00:00.000Z"
        assert rows[1][1] == "2026-11-01T12:00:00.000Z"
        assert rows[2][1] == "2026-11-01T06:30:00.000Z"


# ============================================================
# 2. INTEGRATION TESTS: API ENDPOINTS
# ============================================================

def test_api_stores_new_records_in_canonical_utc(client):
    # Post with timezone offset (+05:30)
    res_ist = post_test(
        client,
        {**VALID_TEST, "timestamp": "2026-11-01T17:30:00+05:30", "connectivity_score": 85},
    )
    assert res_ist.status_code == 200

    # Post with negative timezone offset (-08:00)
    res_pst = post_test(
        client,
        {**VALID_TEST, "timestamp": "2026-11-01T04:00:00-08:00", "connectivity_score": 90},
    )
    assert res_pst.status_code == 200

    # Post with omitted timestamp (backend-generated)
    res_backend = post_test(
        client,
        {**VALID_TEST, "timestamp": None, "connectivity_score": 95},
    )
    assert res_backend.status_code == 200

    # Inspect SQLite database directly to confirm stored format is canonical UTC
    with main.get_connection() as conn:
        rows = conn.execute(
            "SELECT id, timestamp, connectivity_score FROM network_tests ORDER BY id ASC"
        ).fetchall()

        # Both offset records are stored as the exact normalized UTC instant
        assert rows[0]["timestamp"] == "2026-11-01T12:00:00.000Z"
        assert rows[1]["timestamp"] == "2026-11-01T12:00:00.000Z"

        # Backend-generated timestamp is stored in canonical UTC format
        assert is_canonical_utc(rows[2]["timestamp"])


def test_api_date_filtering_across_timezone_offsets(client):
    """Network records with different offsets are correctly filtered according to their UTC calendar date."""
    # Record A: Nov 1 at 02:00 +05:30 -> UTC instant is Oct 31, 20:30:00 UTC
    post_test(
        client,
        {**VALID_TEST, "timestamp": "2026-11-01T02:00:00+05:30", "connectivity_score": 50},
    )

    # Record B: Oct 31 at 20:00 -05:00 -> UTC instant is Nov 1, 01:00:00 UTC
    post_test(
        client,
        {**VALID_TEST, "timestamp": "2026-10-31T20:00:00-05:00", "connectivity_score": 80},
    )

    # Filter for calendar day 2026-11-01 in UTC
    res = client.get(
        "/api/network-history",
        params={"start_date": "2026-11-01", "end_date": "2026-11-01"},
    )
    assert res.status_code == 200
    results = res.json()

    # Only Record B belongs to 2026-11-01 in UTC
    assert len(results) == 1
    assert results[0]["connectivity_score"] == 80
    assert results[0]["timestamp"] == "2026-11-01T01:00:00.000Z"

    # Filter for calendar day 2026-10-31 in UTC
    res_oct = client.get(
        "/api/network-history",
        params={"start_date": "2026-10-31", "end_date": "2026-10-31"},
    )
    assert res_oct.status_code == 200
    results_oct = res_oct.json()

    # Record A belongs to 2026-10-31 in UTC
    assert len(results_oct) == 1
    assert results_oct[0]["connectivity_score"] == 50
    assert results_oct[0]["timestamp"] == "2026-10-31T20:30:00.000Z"


def test_api_date_boundaries_across_midnight(client):
    """Inclusive calendar date boundaries properly separate records across midnight."""
    # 1 ms before midnight on Nov 1 UTC
    post_test(
        client,
        {**VALID_TEST, "timestamp": "2026-11-01T23:59:59.999Z", "connectivity_score": 70},
    )

    # Exact midnight at start of Nov 2 UTC
    post_test(
        client,
        {**VALID_TEST, "timestamp": "2026-11-02T00:00:00.000Z", "connectivity_score": 80},
    )

    # 1 ms after midnight on Nov 2 UTC
    post_test(
        client,
        {**VALID_TEST, "timestamp": "2026-11-02T00:00:00.001Z", "connectivity_score": 90},
    )

    # Filter for Nov 1 only
    res_nov1 = client.get(
        "/api/network-history",
        params={"start_date": "2026-11-01", "end_date": "2026-11-01"},
    )
    assert res_nov1.status_code == 200
    assert [r["connectivity_score"] for r in res_nov1.json()] == [70]

    # Filter for Nov 2 only
    res_nov2 = client.get(
        "/api/network-history",
        params={"start_date": "2026-11-02", "end_date": "2026-11-02"},
    )
    assert res_nov2.status_code == 200
    assert [r["connectivity_score"] for r in res_nov2.json()] == [80, 90]


def test_deterministic_ordering_for_identical_timestamps(client):
    """Records sharing identical timestamps are deterministically sorted by database record ID."""
    records = [
        ("2026-11-01T12:00:00.000Z", 60),
        ("2026-11-01T17:30:00+05:30", 70),  # Same instant (12:00:00.000Z)
        ("2026-11-01T04:00:00-08:00", 80),  # Same instant (12:00:00.000Z)
        ("2026-11-01T12:00:00.000Z", 90),  # Same instant (12:00:00.000Z)
    ]

    for ts, score in records:
        post_test(client, {**VALID_TEST, "timestamp": ts, "connectivity_score": score})

    res = client.get("/api/network-history", params={"range": "all"})
    assert res.status_code == 200

    results = res.json()
    assert len(results) == 4

    # Returned items must preserve ascending primary timestamp and ascending secondary ID
    ids = [r["id"] for r in results]
    assert ids == sorted(ids)
    assert [r["connectivity_score"] for r in results] == [60, 70, 80, 90]


def test_existing_legacy_records_remain_accessible(client):
    """Historical records stored in non-canonical or naive formats remain accessible without data loss."""
    with main.get_connection() as conn:
        # Directly insert historical records to bypass new record validation
        conn.execute(
            """
            INSERT INTO network_tests (
                timestamp, download_mbps, upload_mbps, ping_ms, jitter_ms, packet_loss,
                network_type, connectivity_score, latitude, longitude
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("2023-05-10T14:30:00", 45.0, 10.0, 25.0, 3.0, 0.0, "Wi-Fi", 77.0, None, None),
        )
        conn.execute(
            """
            INSERT INTO network_tests (
                timestamp, download_mbps, upload_mbps, ping_ms, jitter_ms, packet_loss,
                network_type, connectivity_score, latitude, longitude
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("2023-05-10T20:00:00+05:30", 55.0, 15.0, 20.0, 2.0, 0.0, "Wi-Fi", 88.0, None, None),
        )
        conn.commit()

    # Query all history
    res = client.get("/api/network-history", params={"range": "all"})
    assert res.status_code == 200
    results = res.json()

    assert len(results) == 2
    # Verify legacy records are accessible and their original stored string is preserved in API output
    assert results[0]["timestamp"] == "2023-05-10T14:30:00"
    assert results[1]["timestamp"] == "2023-05-10T20:00:00+05:30"
    assert results[0]["connectivity_score"] == 77.0
    assert results[1]["connectivity_score"] == 88.0


# ============================================================
# 3. AI DATA LOADERS: CONSISTENT CHRONOLOGICAL ORDERING
# ============================================================

def test_ai_data_loaders_use_consistent_chronological_ordering(tmp_path, monkeypatch):
    test_db = tmp_path / "ai_test_history.db"

    with sqlite3.connect(test_db) as conn:
        conn.execute(
            """
            CREATE TABLE network_tests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                download_mbps REAL,
                upload_mbps REAL,
                ping_ms REAL,
                jitter_ms REAL,
                packet_loss REAL,
                network_type TEXT,
                connectivity_score REAL,
                latitude REAL,
                longitude REAL
            )
            """
        )

        # Insert records intentionally out of chronological string order:
        # Record 1: 17:00 UTC (written with +05:30 as 22:30)
        # Record 2: 12:00 UTC (written in UTC)
        # Record 3: 12:00 UTC (written with -08:00 as 04:00) -> same instant as Record 2!
        # Record 4: 08:00 UTC (written in UTC)
        test_rows = [
            ("2026-11-01T22:30:00+05:30", 50.0, 10.0, 20.0, 2.0, 0.0, 75.0), # UTC: 17:00
            ("2026-11-01T12:00:00.000Z", 60.0, 12.0, 18.0, 2.0, 0.0, 80.0), # UTC: 12:00 (id 2)
            ("2026-11-01T04:00:00-08:00", 70.0, 14.0, 16.0, 1.5, 0.0, 85.0), # UTC: 12:00 (id 3)
            ("2026-11-01T08:00:00.000Z", 80.0, 16.0, 15.0, 1.0, 0.0, 90.0), # UTC: 08:00
        ]
        for ts, d, u, p, j, pl, s in test_rows:
            conn.execute(
                """
                INSERT INTO network_tests (
                    timestamp, download_mbps, upload_mbps, ping_ms, jitter_ms, packet_loss, connectivity_score
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (ts, d, u, p, j, pl, s),
            )
        conn.commit()

    import backend.ai_engine as ai_engine
    monkeypatch.setattr(ai_engine, "DB_PATH", test_db)

    # 1. Test ai_engine.load_network_data()
    data = load_network_data()
    assert len(data) == 4

    # Chronological sequence expected:
    # 1st: 08:00 UTC (Record 4, score 90)
    # 2nd: 12:00 UTC (Record 2, score 80, id 2)
    # 3rd: 12:00 UTC (Record 3, score 85, id 3 - tie-breaker by id!)
    # 4th: 17:00 UTC (Record 1, score 75)
    scores = [item["values"][-1] for item in data]
    assert scores == [90.0, 80.0, 85.0, 75.0]

    # 2. Test final_predictor._load_complete_data()
    import backend.final_predictor as fp_module
    monkeypatch.setattr(fp_module, "DB_PATH", test_db)
    fp_data = final_predictor._load_complete_data()
    assert len(fp_data) == 4
    fp_scores = [row[-1] for row in fp_data]
    assert fp_scores == [90.0, 80.0, 85.0, 75.0]
