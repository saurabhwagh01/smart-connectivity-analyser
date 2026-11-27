"""Error handling for network history operations (issue #8)."""

import sqlite3

import pytest

import backend.main as main
from test_network_test_validation import VALID_TEST, post_test


def use_missing_table_database(tmp_path, monkeypatch):
    """Point the API at a valid SQLite file that has no network_tests table."""
    path = tmp_path / "no_table.db"
    sqlite3.connect(path).close()
    monkeypatch.setattr(main, "DB_PATH", path)


def use_corrupt_database(tmp_path, monkeypatch):
    """Point the API at a file that is not an SQLite database."""
    path = tmp_path / "corrupt.db"
    path.write_bytes(b"this is not an sqlite database" * 100)
    monkeypatch.setattr(main, "DB_PATH", path)


def use_unopenable_database(tmp_path, monkeypatch):
    """Point the API at a directory, which SQLite cannot open."""
    path = tmp_path / "is_a_directory"
    path.mkdir()
    monkeypatch.setattr(main, "DB_PATH", path)


BROKEN_DATABASES = [
    use_missing_table_database,
    use_corrupt_database,
    use_unopenable_database,
]


def assert_clean_error(response, expected_detail):
    assert response.status_code == 500
    body = response.json()
    assert body == {"detail": expected_detail}
    # Internal SQLite messages and file paths must not reach the client.
    lowered = body["detail"].lower()
    for leaked in ("sqlite", "no such table", "not a database", "unable to open"):
        assert leaked not in lowered


def test_empty_history_returns_empty_list(client):
    response = client.get("/api/network-history", params={"range": "all"})

    assert response.status_code == 200
    assert response.json() == []


def test_empty_history_paginated_returns_empty_page(client):
    response = client.get(
        "/api/network-history",
        params={"range": "all", "limit": 10},
    )

    assert response.status_code == 200
    assert response.json() == {
        "data": [],
        "pagination": {
            "limit": 10,
            "offset": 0,
            "total": 0,
            "has_more": False,
            "next_offset": None,
        },
    }


def test_saved_records_are_returned(client):
    saved = post_test(client, VALID_TEST)
    assert saved.status_code == 200

    response = client.get("/api/network-history", params={"range": "all"})

    assert response.status_code == 200
    records = response.json()
    assert [record["id"] for record in records] == [saved.json()["id"]]
    assert records[0]["connectivity_score"] == VALID_TEST["connectivity_score"]


@pytest.mark.parametrize("break_database", BROKEN_DATABASES)
@pytest.mark.parametrize("params", [{"range": "all"}, {"range": "all", "limit": 5}])
def test_history_read_failure_returns_clean_error(
    client, tmp_path, monkeypatch, break_database, params
):
    break_database(tmp_path, monkeypatch)

    response = client.get("/api/network-history", params=params)

    assert_clean_error(response, main.HISTORY_READ_ERROR)


@pytest.mark.parametrize("break_database", BROKEN_DATABASES)
def test_history_delete_failure_returns_clean_error(
    client, tmp_path, monkeypatch, break_database
):
    break_database(tmp_path, monkeypatch)

    response = client.delete("/api/network-history")

    assert_clean_error(response, main.HISTORY_DELETE_ERROR)


@pytest.mark.parametrize("break_database", BROKEN_DATABASES)
def test_save_failure_returns_clean_error(
    client, tmp_path, monkeypatch, break_database
):
    break_database(tmp_path, monkeypatch)

    response = post_test(client, VALID_TEST)

    assert_clean_error(response, main.HISTORY_SAVE_ERROR)


def test_delete_removes_saved_records(client):
    assert post_test(client, VALID_TEST).status_code == 200

    deleted = client.delete("/api/network-history")

    assert deleted.status_code == 200
    assert deleted.json() == {
        "status": "success",
        "message": "Network history deleted",
    }
    assert client.get("/api/network-history", params={"range": "all"}).json() == []


def test_database_errors_are_logged(client, tmp_path, monkeypatch, caplog):
    use_corrupt_database(tmp_path, monkeypatch)

    with caplog.at_level("ERROR", logger=main.logger.name):
        client.get("/api/network-history", params={"range": "all"})

    assert "network history" in caplog.text.lower()
