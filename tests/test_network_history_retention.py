"""Network-history deletion and retention behavior (issue #79)."""

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

import backend.main as main
from test_network_test_validation import VALID_TEST, post_test


def save_record(client, timestamp):
    response = post_test(
        client,
        {**VALID_TEST, "timestamp": timestamp},
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def test_retention_defaults_to_keep_forever(client):
    response = client.get("/api/network-history/retention")

    assert response.status_code == 200
    assert response.json() == {
        "retention_days": None,
        "max_retention_days": 3650,
    }


def test_setting_retention_removes_expired_local_rows(client):
    now = datetime.now(timezone.utc)
    expired_id = save_record(
        client, (now - timedelta(days=45)).isoformat()
    )
    recent_id = save_record(
        client, (now - timedelta(days=10)).isoformat()
    )

    response = client.put(
        "/api/network-history/retention",
        json={"retention_days": 30},
    )

    assert response.status_code == 200
    assert response.json()["retention_days"] == 30
    assert response.json()["deleted_count"] == 1
    assert response.json()["cleanup_scheduled"] is False

    history = client.get("/api/network-history?range=all").json()
    assert [record["id"] for record in history] == [recent_id]
    assert expired_id not in [record["id"] for record in history]


def test_null_retention_disables_cleanup_and_keeps_existing_records(client):
    old_id = save_record(
        client, (datetime.now(timezone.utc) - timedelta(days=500)).isoformat()
    )

    response = client.put(
        "/api/network-history/retention",
        json={"retention_days": None},
    )

    assert response.status_code == 200
    assert response.json()["retention_days"] is None
    assert response.json()["deleted_count"] == 0
    history = client.get("/api/network-history?range=all").json()
    assert [record["id"] for record in history] == [old_id]


@pytest.mark.parametrize("days", [0, -1, 3651, 1.5, "invalid"])
def test_retention_days_must_be_within_supported_integer_range(client, days):
    response = client.put(
        "/api/network-history/retention",
        json={"retention_days": days},
    )

    assert response.status_code == 422


def test_expired_history_cleanup_is_bounded_and_preserves_unparseable_rows(
    client, monkeypatch
):
    monkeypatch.setattr(main, "HISTORY_RETENTION_BATCH_SIZE", 2)
    connection = main.get_connection()
    try:
        connection.execute(
            "UPDATE network_history_settings SET retention_days = 30 WHERE id = 1"
        )
        rows = [
            ("2020-01-01T00:00:00.000Z",),
            ("2020-01-02T00:00:00.000Z",),
            ("2020-01-03T00:00:00.000Z",),
            ("2099-01-01T00:00:00.000Z",),
            ("legacy-timestamp",),
        ]
        connection.executemany(
            "INSERT INTO network_tests (timestamp) VALUES (?)",
            rows,
        )
        connection.commit()

        first_deleted = main.delete_expired_history_batch(connection, 30)
        connection.commit()
        second_deleted = main.delete_expired_history_batch(connection, 30)
        connection.commit()

        remaining = connection.execute(
            "SELECT timestamp FROM network_tests ORDER BY id"
        ).fetchall()
    finally:
        connection.close()

    assert first_deleted == 2
    assert second_deleted == 1
    assert [row["timestamp"] for row in remaining] == [
        "2099-01-01T00:00:00.000Z",
        "legacy-timestamp",
    ]


def test_selected_delete_removes_only_requested_rows_and_reports_count(client):
    ids = [
        save_record(
            client, f"2026-11-2{index}T10:00:00.000Z"
        )
        for index in range(3)
    ]

    response = client.request(
        "DELETE",
        "/api/network-history/selected",
        json={"ids": [ids[0], ids[2], ids[0]]},
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "success",
        "deleted_count": 2,
        "message": "Deleted 2 selected local history record(s).",
    }
    remaining = client.get("/api/network-history?range=all").json()
    assert [record["id"] for record in remaining] == [ids[1]]


@pytest.mark.parametrize("ids", [[], [0], [-1], [True], ["1"]])
def test_selected_delete_rejects_empty_or_invalid_ids(client, ids):
    response = client.request(
        "DELETE",
        "/api/network-history/selected",
        json={"ids": ids},
    )

    assert response.status_code == 422


def test_selected_delete_returns_zero_when_ids_do_not_exist(client):
    response = client.request(
        "DELETE",
        "/api/network-history/selected",
        json={"ids": [987654321]},
    )

    assert response.status_code == 200
    assert response.json()["deleted_count"] == 0


def test_delete_all_reports_count_and_leaves_empty_history(client):
    save_record(client, "2026-11-20T10:00:00.000Z")
    save_record(client, "2026-11-21T10:00:00.000Z")

    response = client.delete("/api/network-history")

    assert response.status_code == 200
    assert response.json()["deleted_count"] == 2
    assert client.get("/api/network-history?range=all").json() == []


def test_selected_delete_database_failure_returns_safe_error(
    client, tmp_path, monkeypatch
):
    path = tmp_path / "history-without-table.db"
    sqlite3.connect(path).close()
    monkeypatch.setattr(main, "DB_PATH", path)

    response = client.request(
        "DELETE",
        "/api/network-history/selected",
        json={"ids": [1]},
    )

    assert response.status_code == 500
    assert response.json() == {"detail": main.HISTORY_DELETE_ERROR}
    assert "no such table" not in response.text.lower()


@pytest.mark.parametrize(
    "method,path,expected",
    [
        ("get", "/api/network-history/retention", main.HISTORY_RETENTION_READ_ERROR),
        ("put", "/api/network-history/retention", main.HISTORY_RETENTION_UPDATE_ERROR),
    ],
)
def test_retention_database_failures_return_safe_errors(
    client, tmp_path, monkeypatch, method, path, expected
):
    corrupt = tmp_path / "corrupt-history.db"
    corrupt.write_bytes(b"not an sqlite database")
    monkeypatch.setattr(main, "DB_PATH", corrupt)

    response = (
        client.put(path, json={"retention_days": 30})
        if method == "put"
        else client.get(path)
    )

    assert response.status_code == 500
    assert response.json() == {"detail": expected}
    assert "not a database" not in response.text.lower()



def test_large_retention_cleanup_uses_background_batches(client, monkeypatch):
    monkeypatch.setattr(main, "HISTORY_RETENTION_BATCH_SIZE", 2)
    now = datetime.now(timezone.utc)
    expired_ids = [
        save_record(client, (now - timedelta(days=days)).isoformat())
        for days in (60, 50, 40)
    ]
    recent_id = save_record(client, (now - timedelta(days=10)).isoformat())

    response = client.put(
        "/api/network-history/retention",
        json={"retention_days": 30},
    )

    assert response.status_code == 200
    assert response.json()["deleted_count"] == 2
    assert response.json()["cleanup_scheduled"] is True
    remaining_ids = [
        record["id"]
        for record in client.get("/api/network-history?range=all").json()
    ]
    assert remaining_ids == [recent_id]
    assert not set(expired_ids).intersection(remaining_ids)


def test_scheduled_retention_cleanup_logs_database_failures(
    client, tmp_path, monkeypatch, caplog
):
    corrupt = tmp_path / "corrupt-cleanup.db"
    corrupt.write_bytes(b"not an sqlite database")
    monkeypatch.setattr(main, "DB_PATH", corrupt)

    with caplog.at_level("ERROR", logger=main.logger.name):
        deleted_count = main.cleanup_expired_history()

    assert deleted_count == 0
    assert "scheduled network history retention cleanup failed" in caplog.text.lower()
