"""UTC timestamp normalization regression tests (issue #39)."""

import re
import sqlite3
from datetime import date, datetime, timedelta, timezone

import pytest

import backend.main as main
from backend.timestamps import (
    canonical_sort_key,
    current_utc_timestamp,
    parse_timestamp,
    to_canonical_utc,
    utc_day_start,
)

# main.py imports the AI modules from backend/ as top-level modules.
import ai_engine  # noqa: E402
import final_predictor  # noqa: E402


CANONICAL = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")

FEATURE_COLUMNS = [
    "download_mbps",
    "upload_mbps",
    "ping_ms",
    "jitter_ms",
    "packet_loss",
    "connectivity_score",
]


def local_naive_as_utc(naive_text):
    """Expected canonical value for a legacy naive (server-local) timestamp."""
    moment = datetime.fromisoformat(naive_text).astimezone(timezone.utc)
    return moment.replace(tzinfo=None).isoformat(timespec="milliseconds") + "Z"


def save(client, timestamp, score=80):
    payload = {"connectivity_score": score}
    if timestamp is not None:
        payload["timestamp"] = timestamp
    response = client.post("/api/network-test", json=payload)
    assert response.status_code == 200, response.text
    return response.json()["id"]


def history(client, **params):
    response = client.get("/api/network-history", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def insert_raw(timestamp, score=50, db_path=None):
    """Insert a row directly, as an older version of the app would have."""
    with sqlite3.connect(db_path or main.DB_PATH) as connection:
        cursor = connection.execute(
            f"""
            INSERT INTO network_tests (timestamp, {", ".join(FEATURE_COLUMNS)})
            VALUES (?, 10, 5, 20, 2, 0, ?)
            """,
            (timestamp, score),
        )
        return cursor.lastrowid


def stored_timestamps():
    with sqlite3.connect(main.DB_PATH) as connection:
        return [
            row[0]
            for row in connection.execute(
                "SELECT timestamp FROM network_tests ORDER BY id"
            )
        ]


# ------------------------------------------------------------
# Utility functions
# ------------------------------------------------------------

@pytest.mark.parametrize(
    "value",
    [
        "2026-11-02T04:30:00Z",
        "2026-11-02T04:30:00.000Z",
        "2026-11-02T04:30:00+00:00",
        "2026-11-02T10:00:00+05:30",
        "2026-11-01T23:30:00-05:00",
    ],
)
def test_aware_timestamps_normalize_to_the_same_utc_instant(value):
    assert to_canonical_utc(value) == "2026-11-02T04:30:00.000Z"


def test_canonical_form_keeps_milliseconds():
    assert to_canonical_utc("2026-11-02T04:30:00.123456Z") == "2026-11-02T04:30:00.123Z"


def test_naive_legacy_timestamp_uses_server_local_time():
    naive = "2026-11-02T10:00:00"

    assert to_canonical_utc(naive) == local_naive_as_utc(naive)


@pytest.mark.parametrize(
    "value",
    [None, "", "   ", "not a date", "2026-13-45T99:00:00", "yesterday", 12345],
)
def test_invalid_timestamps_return_none(value):
    assert parse_timestamp(value) is None
    assert to_canonical_utc(value) is None


def test_current_utc_timestamp_is_canonical_and_current():
    value = current_utc_timestamp()

    assert CANONICAL.match(value)
    moment = parse_timestamp(value)
    assert abs(datetime.now(timezone.utc) - moment) < timedelta(seconds=5)


def test_utc_day_start():
    assert utc_day_start(date(2026, 11, 2)) == "2026-11-02T00:00:00.000Z"


def test_canonical_strings_sort_chronologically():
    values = [
        "2026-11-02T10:00:00+05:30",  # 04:30Z
        "2026-11-01T23:00:00-05:00",  # 04:00Z
        "2026-11-02T05:00:00Z",
    ]
    canonical = [to_canonical_utc(value) for value in values]

    assert sorted(canonical) == [
        "2026-11-02T04:00:00.000Z",
        "2026-11-02T04:30:00.000Z",
        "2026-11-02T05:00:00.000Z",
    ]


def test_sort_key_orders_by_instant_then_id_and_puts_invalid_last():
    rows = [
        (3, "garbage"),
        (2, "2026-11-02T10:00:00+05:30"),  # same instant as id 1
        (1, "2026-11-02T04:30:00Z"),
        (4, "2026-11-01T00:00:00Z"),
    ]

    ordered = sorted(rows, key=lambda row: canonical_sort_key(row[1], row[0]))

    assert [row[0] for row in ordered] == [4, 1, 2, 3]


# ------------------------------------------------------------
# Storage
# ------------------------------------------------------------

def test_api_stores_offset_timestamps_as_canonical_utc(client):
    save(client, "2026-11-02T10:00:00+05:30")

    assert stored_timestamps() == ["2026-11-02T04:30:00.000Z"]


def test_api_keeps_browser_timestamps_unchanged(client):
    save(client, "2026-11-02T04:30:00.000Z")

    assert stored_timestamps() == ["2026-11-02T04:30:00.000Z"]


def test_backend_generated_timestamp_is_timezone_aware_utc(client):
    save(client, None)

    [stored] = stored_timestamps()
    assert CANONICAL.match(stored)
    assert abs(datetime.now(timezone.utc) - parse_timestamp(stored)) < timedelta(seconds=5)


def test_invalid_timestamp_is_still_rejected(client):
    response = client.post(
        "/api/network-test",
        json={"connectivity_score": 80, "timestamp": "not a date"},
    )

    assert response.status_code == 422


# ------------------------------------------------------------
# Range filtering
# ------------------------------------------------------------

def test_recent_ranges_include_records_from_every_timestamp_source(client):
    # The original bug: on a server that is not on UTC, browser (Z) and
    # offset timestamps were compared as text with local time and dropped.
    now = datetime.now(timezone.utc)
    browser = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    offset = now.astimezone(timezone(timedelta(hours=-5))).isoformat()
    legacy_naive = datetime.now().isoformat()

    for timestamp in (browser, offset):
        save(client, timestamp)
    insert_raw(legacy_naive)

    assert len(history(client, range="1h")) == 3


def test_recent_range_excludes_old_records_from_every_source(client):
    two_hours_ago = datetime.now(timezone.utc) - timedelta(hours=2)
    save(client, two_hours_ago.strftime("%Y-%m-%dT%H:%M:%S.000Z"))
    save(client, two_hours_ago.astimezone(timezone(timedelta(hours=5, minutes=30))).isoformat())
    insert_raw((datetime.now() - timedelta(hours=2)).isoformat())

    assert history(client, range="1h") == []
    assert len(history(client, range="24h")) == 3


def test_date_filter_uses_utc_day_across_offsets(client):
    # 23:30 on 1 Nov at UTC-5 is 04:30 on 2 Nov in UTC.
    save(client, "2026-11-01T23:30:00-05:00", score=61)
    # 01:00 on 2 Nov at UTC+5:30 is 19:30 on 1 Nov in UTC.
    save(client, "2026-11-02T01:00:00+05:30", score=62)

    nov_1 = history(client, start_date="2026-11-01", end_date="2026-11-01")
    nov_2 = history(client, start_date="2026-11-02", end_date="2026-11-02")

    assert [record["connectivity_score"] for record in nov_1] == [62]
    assert [record["connectivity_score"] for record in nov_2] == [61]


def test_date_filter_is_inclusive_at_utc_midnight_boundaries(client):
    save(client, "2026-11-01T23:59:59.999Z", score=1)
    save(client, "2026-11-02T00:00:00.000Z", score=2)
    save(client, "2026-11-02T23:59:59.999Z", score=3)
    save(client, "2026-11-03T00:00:00.000Z", score=4)

    records = history(client, start_date="2026-11-02", end_date="2026-11-02")

    assert [record["connectivity_score"] for record in records] == [2, 3]


def test_start_date_only_and_end_date_only(client):
    save(client, "2026-11-01T12:00:00Z", score=1)
    save(client, "2026-11-02T12:00:00Z", score=2)

    assert [r["connectivity_score"] for r in history(client, start_date="2026-11-02")] == [2]
    assert [r["connectivity_score"] for r in history(client, end_date="2026-11-01")] == [1]


# ------------------------------------------------------------
# Ordering
# ------------------------------------------------------------

def test_history_is_ordered_by_utc_instant_not_text(client):
    # As text, "2026-11-02T01..." sorts after "2026-11-01T23...", but it
    # is the earlier instant (19:30Z vs 04:30Z next day).
    later = save(client, "2026-11-01T23:30:00-05:00")
    earlier = save(client, "2026-11-02T01:00:00+05:30")

    records = history(client, range="all")

    assert [record["id"] for record in records] == [earlier, later]


def test_identical_instants_are_ordered_by_id(client):
    first = save(client, "2026-11-02T10:00:00+05:30")
    second = save(client, "2026-11-02T04:30:00.000Z")
    third = save(client, "2026-11-01T23:30:00-05:00")

    records = history(client, range="all")

    assert [record["id"] for record in records] == [first, second, third]


def test_pagination_follows_utc_order(client):
    ids = {
        "c": save(client, "2026-11-02T12:00:00Z"),
        "a": save(client, "2026-11-02T10:00:00+05:30"),   # 04:30Z
        "b": save(client, "2026-11-02T00:00:00-06:00"),   # 06:00Z
    }

    page_1 = history(client, range="all", limit=2, offset=0)
    page_2 = history(client, range="all", limit=2, offset=2)

    assert [r["id"] for r in page_1["data"] + page_2["data"]] == [
        ids["a"],
        ids["b"],
        ids["c"],
    ]
    assert page_1["pagination"]["total"] == 3


# ------------------------------------------------------------
# Legacy records (written before this change, never rewritten)
# ------------------------------------------------------------

def test_legacy_records_remain_accessible_and_unchanged(client):
    naive = "2026-11-02T10:00:00"
    offset = "2026-11-02T10:00:00+05:30"
    malformed = "not-a-timestamp"
    for value in (naive, offset, malformed):
        insert_raw(value)

    records = history(client, range="all")

    assert len(records) == 3
    returned = [record["timestamp"] for record in records]
    assert local_naive_as_utc(naive) in returned
    assert "2026-11-02T04:30:00.000Z" in returned
    # A malformed value cannot be placed in time: it is returned as stored,
    # after all valid records.
    assert returned[-1] == malformed
    # Reading never rewrites the database.
    assert stored_timestamps() == [naive, offset, malformed]


def test_malformed_legacy_records_are_excluded_from_time_filters(client):
    insert_raw("not-a-timestamp")
    save(client, "2026-11-02T12:00:00Z")

    assert len(history(client, range="all")) == 2
    assert len(history(client, start_date="2000-01-01")) == 1
    assert len(history(client, range="all", limit=10)["data"]) == 2


# ------------------------------------------------------------
# AI training-data loaders
# ------------------------------------------------------------

def make_ai_database(tmp_path):
    path = tmp_path / "ai.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            f"""
            CREATE TABLE network_tests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                {", ".join(f"{column} REAL" for column in FEATURE_COLUMNS)}
            )
            """
        )
    # The connectivity_score column is used as a marker of expected order.
    insert_raw("2026-11-01T23:30:00-05:00", score=40, db_path=path)  # 04:30Z, 2 Nov
    insert_raw("garbage", score=99, db_path=path)
    insert_raw("2026-11-02T01:00:00+05:30", score=10, db_path=path)  # 19:30Z, 1 Nov
    insert_raw("2026-11-02T04:30:00.000Z", score=50, db_path=path)   # same instant as 40
    insert_raw("2026-11-02T06:00:00Z", score=60, db_path=path)
    return path


def test_ai_engine_loader_uses_utc_order_and_skips_malformed(tmp_path, monkeypatch):
    monkeypatch.setattr(ai_engine, "DB_PATH", make_ai_database(tmp_path))

    data = ai_engine.load_network_data()

    scores = [row["values"][-1] for row in data]
    assert scores == [10, 40, 50, 60]
    assert all(CANONICAL.match(row["timestamp"]) for row in data)


def test_final_predictor_loader_uses_utc_order_and_skips_malformed(tmp_path, monkeypatch):
    monkeypatch.setattr(final_predictor, "DB_PATH", make_ai_database(tmp_path))

    data = final_predictor.FinalConnectivityPredictor()._load_complete_data()

    assert data[:, -1].tolist() == [10, 40, 50, 60]
