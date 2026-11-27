from fastapi.testclient import TestClient

import backend.main as main


def test_liveness_does_not_need_the_database(tmp_path, monkeypatch):
    missing_db = tmp_path / "missing.db"
    monkeypatch.setattr(main, "DB_PATH", missing_db)

    with TestClient(main.app) as client:
        response = client.get("/api/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "alive"}
    assert not missing_db.exists()


def test_readiness_is_ok_with_the_history_database(client):
    response = client.get("/api/health/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["checks"] == {"database": "ok"}
    assert set(body["optional"]) == {"ai_models"}
    assert body["optional"]["ai_models"] in {"available", "unavailable"}


def test_readiness_is_not_ok_when_database_is_missing(tmp_path, monkeypatch):
    missing_db = tmp_path / "missing.db"
    monkeypatch.setattr(main, "DB_PATH", missing_db)

    with TestClient(main.app) as client:
        response = client.get("/api/health/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["checks"] == {"database": "unavailable"}
    assert set(body["optional"]) == {"ai_models"}
    assert str(tmp_path) not in response.text
    assert "OperationalError" not in response.text
    assert not missing_db.exists()


def test_readiness_is_not_ok_when_table_is_missing(tmp_path, monkeypatch):
    empty_db = tmp_path / "empty.db"
    empty_db.touch()
    monkeypatch.setattr(main, "DB_PATH", empty_db)

    with TestClient(main.app) as client:
        response = client.get("/api/health/ready")

    assert response.status_code == 503
    assert response.json()["checks"] == {"database": "unavailable"}
    assert empty_db.stat().st_size == 0
