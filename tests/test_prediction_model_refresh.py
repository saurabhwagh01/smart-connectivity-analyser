"""Prediction model refresh when new records arrive (issue #37)."""

import sqlite3
import sys
import threading
import time
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import backend.main as main  # noqa: E402
import final_predictor as fp  # noqa: E402


COLUMNS = (
    "timestamp, download_mbps, upload_mbps, ping_ms, jitter_ms,"
    " packet_loss, connectivity_score"
)


def make_database(tmp_path):
    path = tmp_path / "history.db"
    connection = sqlite3.connect(path)
    connection.execute(
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
    connection.commit()
    connection.close()
    return path


_counter = {"minute": 0}


def add_record(path, score=None, **overrides):
    """Insert one record with a unique, increasing timestamp."""

    _counter["minute"] += 1
    minute = _counter["minute"]
    values = {
        "timestamp": (
            f"2026-11-{1 + minute // 1440:02d}T"
            f"{(minute // 60) % 24:02d}:{minute % 60:02d}:00.000Z"
        ),
        "download_mbps": 40.0 + minute % 7,
        "upload_mbps": 10.0 + minute % 3,
        "ping_ms": 20.0 + minute % 5,
        "jitter_ms": 2.0 + minute % 2,
        "packet_loss": 0.0,
        "connectivity_score": 70.0 + minute % 11 if score is None else score,
    }
    values.update(overrides)
    connection = sqlite3.connect(path)
    connection.execute(
        f"INSERT INTO network_tests ({COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?)",
        tuple(values[name.strip()] for name in COLUMNS.split(",")),
    )
    connection.commit()
    connection.close()


def add_records(path, count):
    for _ in range(count):
        add_record(path)


def delete_newest(path, count):
    connection = sqlite3.connect(path)
    connection.execute(
        "DELETE FROM network_tests WHERE id IN "
        "(SELECT id FROM network_tests ORDER BY id DESC LIMIT ?)",
        (count,),
    )
    connection.commit()
    connection.close()


class FitCounter:
    """Wrap ``_fit`` to count training runs, optionally slowing them down."""

    def __init__(self, predictor, delay=0.0, error=None):
        self.calls = 0
        self.delay = delay
        self.error = error
        self._original = predictor._fit
        self._lock = threading.Lock()
        predictor._fit = self

    def __call__(self, data):
        with self._lock:
            self.calls += 1
        if self.delay:
            time.sleep(self.delay)
        if self.error is not None:
            raise self.error
        return self._original(data)


@pytest.fixture
def db(tmp_path):
    return make_database(tmp_path)


@pytest.fixture
def trained(db):
    add_records(db, 20)
    predictor = fp.FinalConnectivityPredictor(db_path=db)
    assert predictor.train() is True
    return predictor


# ------------------------------------------------------------
# Training-data version and invalidation
# ------------------------------------------------------------

def test_training_records_a_data_version(trained):
    assert trained.ready is True
    assert trained.data_version is not None
    assert trained.record_count == 20
    assert trained.training_samples == 20 - fp.SEQUENCE_LENGTH
    assert trained.stale is False
    assert trained.check_staleness() is False


def test_data_version_is_stable_and_content_based():
    data = [[1, 2, 3, 4, 0, 50]] * 3
    assert fp.training_data_version(data) == fp.training_data_version(data)
    changed = [[1, 2, 3, 4, 0, 50]] * 2 + [[1, 2, 3, 4, 0, 51]]
    assert fp.training_data_version(data) != fp.training_data_version(changed)
    assert fp.training_data_version(data) != fp.training_data_version(data[:2])


def test_new_complete_record_invalidates_model(db, trained):
    old_version = trained.data_version
    add_record(db)

    assert trained.check_staleness() is True
    assert trained.status()["stale"] is True
    assert trained.data_version == old_version


@pytest.mark.parametrize(
    "overrides",
    [
        {"ping_ms": None},
        {"connectivity_score": None},
        {"packet_loss": 150.0},
        {"download_mbps": -1.0},
        {"timestamp": "not-a-timestamp"},
    ],
    ids=["missing-ping", "missing-score", "invalid-loss", "negative", "bad-time"],
)
def test_incomplete_or_invalid_records_do_not_invalidate(db, trained, overrides):
    counter = FitCounter(trained)
    version = trained.data_version
    add_record(db, **overrides)

    assert trained.check_staleness() is False
    assert trained.refresh_if_stale() is False
    assert counter.calls == 0
    assert trained.data_version == version


# ------------------------------------------------------------
# Controlled retraining
# ------------------------------------------------------------

def test_refresh_does_nothing_when_data_unchanged(trained):
    counter = FitCounter(trained)
    model = trained.model

    assert trained.refresh_if_stale() is False
    assert trained.refresh_if_stale() is False
    assert counter.calls == 0
    assert trained.model is model


def test_refresh_retrains_on_new_records(db, trained):
    old_model = trained.model
    old_version = trained.data_version
    add_records(db, 3)

    assert trained.refresh_if_stale() is True
    assert trained.model is not old_model
    assert trained.data_version != old_version
    assert trained.record_count == 23
    assert trained.training_samples == 23 - fp.SEQUENCE_LENGTH
    assert trained.stale is False
    assert trained.last_refresh_error is None

    # A second call with no new data does not retrain again.
    assert trained.refresh_if_stale() is False


def test_refresh_uses_latest_data_for_prediction(db, trained):
    before = trained.predict()
    # A strong, consistent shift in the data the model is trained on.
    for _ in range(30):
        add_record(db, score=5.0)

    assert trained.refresh_if_stale() is True
    after = trained.predict()

    assert after < before
    assert 0.0 <= after <= 100.0


def test_concurrent_refreshes_train_only_once(db, trained):
    add_records(db, 2)
    counter = FitCounter(trained, delay=0.2)
    results = []
    start = threading.Barrier(8)

    def worker():
        start.wait()
        results.append(trained.refresh_if_stale())

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert counter.calls == 1
    assert results.count(True) == 1
    assert results.count(False) == 7
    assert trained.stale is False
    assert trained.record_count == 22


def test_prediction_during_refresh_uses_a_complete_model(db, trained):
    add_records(db, 2)
    FitCounter(trained, delay=0.3)
    refresher = threading.Thread(target=trained.refresh_if_stale)
    refresher.start()
    time.sleep(0.05)

    # The previous model keeps serving while the new one trains.
    assert 0.0 <= trained.predict() <= 100.0
    refresher.join(timeout=30)
    assert trained.record_count == 22


# ------------------------------------------------------------
# Failure handling and availability
# ------------------------------------------------------------

def test_failed_refresh_keeps_previous_model(db, trained):
    old_model = trained.model
    old_version = trained.data_version
    old_prediction = trained.predict()
    counter = FitCounter(trained, error=ValueError("boom"))
    add_record(db)

    assert trained.refresh_if_stale() is False
    assert counter.calls == 1
    assert trained.model is old_model
    assert trained.data_version == old_version
    assert trained.ready is True
    assert trained.stale is True
    assert "boom" in trained.last_refresh_error
    assert trained.record_count == 20
    # Still predicts with the last successfully trained model.
    assert isinstance(trained.predict(), float)
    assert old_prediction is not None


def test_failed_refresh_is_not_retried_until_data_changes(db, trained):
    counter = FitCounter(trained, error=ValueError("boom"))
    add_record(db)

    trained.refresh_if_stale()
    trained.refresh_if_stale()
    trained.refresh_if_stale()
    assert counter.calls == 1

    # New data: try again, and recover once training works.
    counter.error = None
    add_record(db)
    assert trained.refresh_if_stale() is True
    assert counter.calls == 2
    assert trained.stale is False
    assert trained.last_refresh_error is None
    assert trained.record_count == 22


def test_insufficient_records_at_start_then_enough(db):
    add_records(db, fp.SEQUENCE_LENGTH)
    predictor = fp.FinalConnectivityPredictor(db_path=db)

    assert predictor.train() is False
    assert predictor.ready is False
    assert "Need at least 9" in predictor.message
    with pytest.raises(RuntimeError):
        predictor.predict()

    add_record(db)
    assert predictor.refresh_if_stale() is True
    assert predictor.ready is True
    assert predictor.record_count == fp.SEQUENCE_LENGTH + 1


def test_insufficient_records_after_training_keeps_previous_model(db, trained):
    old_model = trained.model
    delete_newest(db, 20 - fp.SEQUENCE_LENGTH)

    assert trained.refresh_if_stale() is False
    assert trained.model is old_model
    assert trained.ready is True
    assert trained.stale is True
    assert "Need at least 9" in trained.last_refresh_error


def test_empty_or_missing_table(tmp_path):
    predictor = fp.FinalConnectivityPredictor(db_path=tmp_path / "none.db")
    assert predictor.train() is False
    assert predictor.refresh_if_stale() is False
    assert predictor.ready is False


# ------------------------------------------------------------
# API integration
# ------------------------------------------------------------

def post_record(client, score):
    response = client.post(
        "/api/network-test",
        json={
            "download_mbps": 50.0,
            "upload_mbps": 10.0,
            "ping_ms": 20.0,
            "jitter_ms": 2.0,
            "packet_loss": 0.0,
            "connectivity_score": score,
            "network_type": "wifi",
        },
    )
    assert response.status_code == 200


@pytest.fixture
def api_predictor(client, monkeypatch):
    predictor = fp.FinalConnectivityPredictor(db_path=main.DB_PATH)
    predictor.train()
    monkeypatch.setattr(main, "final_predictor", predictor)
    monkeypatch.setattr(main, "FINAL_PREDICTOR_READY", predictor.ready)
    return predictor


def test_api_becomes_ready_once_enough_records_arrive(client, api_predictor):
    assert client.get("/api/ai/prediction").status_code == 503

    for score in range(60, 60 + fp.SEQUENCE_LENGTH + 1):
        post_record(client, score)

    response = client.get("/api/ai/prediction")
    assert response.status_code == 200
    body = response.json()
    assert body["model_refreshed"] is True
    assert body["training_records"] == fp.SEQUENCE_LENGTH + 1
    assert body["model_status"]["stale"] is False


def test_api_refreshes_only_after_new_eligible_records(client, api_predictor):
    for score in range(60, 75):
        post_record(client, score)

    first = client.get("/api/ai/prediction").json()
    second = client.get("/api/ai/prediction").json()
    assert first["model_refreshed"] is True
    assert second["model_refreshed"] is False
    assert second["training_records"] == 15

    post_record(client, 80)
    status = client.get("/api/ai/status").json()["prediction_model"]
    assert status["loaded"] is True
    assert status["stale"] is True

    third = client.get("/api/ai/prediction").json()
    assert third["model_refreshed"] is True
    assert third["training_records"] == 16
    status = client.get("/api/ai/status").json()["prediction_model"]
    assert status["stale"] is False
    assert status["training_records"] == 16


def test_api_reports_failed_refresh_and_keeps_serving(client, api_predictor):
    for score in range(60, 75):
        post_record(client, score)
    assert client.get("/api/ai/prediction").status_code == 200

    FitCounter(api_predictor, error=ValueError("boom"))
    post_record(client, 90)

    response = client.get("/api/ai/prediction")
    assert response.status_code == 200
    body = response.json()
    assert body["model_refreshed"] is False
    assert body["training_records"] == 15
    assert body["model_status"]["stale"] is True
    assert "boom" in body["model_status"]["last_refresh_error"]


def test_api_status_without_refresh_support(client, monkeypatch):
    class LegacyPredictor:
        record_count = 10
        training_samples = 2

        def predict(self):
            return 75.0

    monkeypatch.setattr(main, "final_predictor", LegacyPredictor())
    monkeypatch.setattr(main, "FINAL_PREDICTOR_READY", True)

    assert client.get("/api/ai/status").json()["prediction_model"] == {
        "name": "HistGradientBoosting",
        "loaded": True,
    }
    body = client.get("/api/ai/prediction").json()
    assert body["predicted_connectivity_score"] == 75.0
    assert body["model_refreshed"] is False
