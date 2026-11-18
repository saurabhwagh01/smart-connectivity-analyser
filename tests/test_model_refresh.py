"""Tests for prediction-model invalidation and refresh (Issue #37)."""

import sqlite3
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import backend.main as main
from backend.final_predictor import (
    DB_PATH,
    FEATURES,
    SEQUENCE_LENGTH,
    FinalConnectivityPredictor,
)


def _insert_record(
    db_path: Path,
    download: float | None = 50.0,
    upload: float | None = 15.0,
    ping: float | None = 20.0,
    jitter: float | None = 5.0,
    loss: float | None = 0.0,
    score: float | None = 85.0,
    timestamp: str | None = "2026-11-16T12:00:00.000Z",
) -> None:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO network_tests (
            timestamp, download_mbps, upload_mbps, ping_ms, jitter_ms,
            packet_loss, network_type, connectivity_score, latitude, longitude
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (timestamp, download, upload, ping, jitter, loss, "Wi-Fi", score, 0.0, 0.0),
    )
    conn.commit()
    conn.close()


def _populate_records(db_path: Path, count: int) -> None:
    for i in range(count):
        _insert_record(
            db_path,
            download=50.0 + (i % 10),
            upload=15.0 + (i % 5),
            ping=20.0 + (i % 5),
            jitter=5.0,
            loss=0.0,
            score=80.0 + (i % 10),
            timestamp=f"2026-11-16T12:{i:02d}:00.000Z",
        )


@pytest.fixture
def test_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_refresh.db"
    monkeypatch.setattr(main, "DB_PATH", db_file)
    main.initialize_database()
    return db_file


# ----------------------------------------------------------------------
# Test 1: New eligible record invalidates the model
# ----------------------------------------------------------------------
def test_new_eligible_record_invalidates_the_model(test_db):
    predictor = FinalConnectivityPredictor(db_path=test_db)
    _populate_records(test_db, 10)
    assert predictor.train() is True
    initial_model_rev = predictor.model_revision
    initial_dataset_rev = predictor.dataset_revision
    assert initial_model_rev == initial_dataset_rev
    assert not predictor.is_stale

    # Insert an eligible measurement
    invalidated = predictor.notify_record_saved(
        download_mbps=45.0,
        upload_mbps=12.0,
        ping_ms=25.0,
        jitter_ms=4.0,
        packet_loss=0.0,
        connectivity_score=82.0,
    )
    assert invalidated is True
    assert predictor.dataset_revision > initial_dataset_rev
    assert predictor.is_stale
    status = predictor.get_status_info()
    assert status["stale"] is True
    assert status["freshness"] == "stale"


# ----------------------------------------------------------------------
# Test 2: Incomplete record does not invalidate the model
# ----------------------------------------------------------------------
def test_incomplete_record_does_not_invalidate_the_model(test_db):
    predictor = FinalConnectivityPredictor(db_path=test_db)
    _populate_records(test_db, 10)
    assert predictor.train() is True
    initial_dataset_rev = predictor.dataset_revision
    assert not predictor.is_stale

    # Missing download_mbps
    invalidated = predictor.notify_record_saved(
        download_mbps=None,
        upload_mbps=12.0,
        ping_ms=25.0,
        jitter_ms=4.0,
        packet_loss=0.0,
        connectivity_score=82.0,
    )
    assert invalidated is False
    assert predictor.dataset_revision == initial_dataset_rev
    assert not predictor.is_stale

    # Out of range / invalid connectivity score (> 100)
    invalidated = predictor.notify_record_saved(
        download_mbps=45.0,
        upload_mbps=12.0,
        ping_ms=25.0,
        jitter_ms=4.0,
        packet_loss=0.0,
        connectivity_score=150.0,
    )
    assert invalidated is False
    assert predictor.dataset_revision == initial_dataset_rev
    assert not predictor.is_stale

    # Negative ping
    invalidated = predictor.notify_record_saved(
        download_mbps=45.0,
        upload_mbps=12.0,
        ping_ms=-5.0,
        jitter_ms=4.0,
        packet_loss=0.0,
        connectivity_score=80.0,
    )
    assert invalidated is False
    assert predictor.dataset_revision == initial_dataset_rev
    assert not predictor.is_stale


# ----------------------------------------------------------------------
# Test 3: Successful model refresh
# ----------------------------------------------------------------------
def test_successful_model_refresh(test_db):
    predictor = FinalConnectivityPredictor(db_path=test_db)
    _populate_records(test_db, 10)
    assert predictor.train() is True
    old_model = predictor.model
    old_samples = predictor.training_samples

    # Add a new eligible record to DB and notify predictor
    _insert_record(test_db, download=60.0, upload=20.0, ping=15.0, jitter=2.0, loss=0.0, score=92.0)
    predictor.notify_record_saved(
        download_mbps=60.0,
        upload_mbps=20.0,
        ping_ms=15.0,
        jitter_ms=2.0,
        packet_loss=0.0,
        connectivity_score=92.0,
    )
    assert predictor.is_stale

    # Refresh
    refreshed = predictor.refresh_if_needed()
    assert refreshed is True
    assert not predictor.is_stale
    assert predictor.model_revision == predictor.dataset_revision
    assert predictor.training_samples == old_samples + 1
    assert predictor.model is not old_model
    status = predictor.get_status_info()
    assert status["freshness"] == "fresh"


# ----------------------------------------------------------------------
# Test 4: No unnecessary retraining
# ----------------------------------------------------------------------
def test_no_unnecessary_retraining(test_db):
    predictor = FinalConnectivityPredictor(db_path=test_db)
    _populate_records(test_db, 10)
    assert predictor.train() is True
    published_model = predictor.model

    with patch("backend.final_predictor.build_production_prediction_model") as mock_builder:
        # Multiple predictions on unchanged data
        score1 = predictor.predict()
        score2 = predictor.predict()
        assert isinstance(score1, float)
        assert isinstance(score2, float)
        # build_production_prediction_model should not be called again
        mock_builder.assert_not_called()

    assert predictor.model is published_model


# ----------------------------------------------------------------------
# Test 5: Failed retraining preserves the old model
# ----------------------------------------------------------------------
def test_failed_retraining_preserves_old_model(test_db):
    predictor = FinalConnectivityPredictor(db_path=test_db)
    _populate_records(test_db, 10)
    assert predictor.train() is True
    previous_model = predictor.model
    published_rev = predictor.model_revision

    # Advance dataset revision
    _insert_record(test_db, score=95.0)
    predictor.notify_record_saved(50.0, 15.0, 20.0, 5.0, 0.0, 95.0)
    assert predictor.is_stale

    # Force training to fail
    with patch("backend.final_predictor.build_production_prediction_model", side_effect=RuntimeError("Training failed unexpectedly")):
        refreshed = predictor.train()
        # The predictor remains functional with the previous model
        assert refreshed is True
        assert predictor.model is previous_model
        assert predictor.model_revision == published_rev
        assert predictor.last_refresh_error is not None
        assert "Training failed unexpectedly" in predictor.last_refresh_error

        # Freshness is accurately reported as failed or stale, not fresh
        status = predictor.get_status_info()
        assert status["freshness"] == "failed"
        assert status["stale"] is True

        # Prediction should still succeed using the previous model
        score = predictor.predict()
        assert isinstance(score, float)


# ----------------------------------------------------------------------
# Test 6: Concurrent refresh protection
# ----------------------------------------------------------------------
def test_concurrent_refresh_protection(test_db):
    predictor = FinalConnectivityPredictor(db_path=test_db)
    _populate_records(test_db, 10)
    predictor.invalidate()

    fit_call_count = 0
    import backend.final_predictor as fp_module
    original_builder = fp_module.build_production_prediction_model

    def wrapped_builder():
        model = original_builder()
        original_fit = model.fit

        def slow_fit(X, y):
            nonlocal fit_call_count
            fit_call_count += 1
            time.sleep(0.05)
            return original_fit(X, y)

        model.fit = slow_fit
        return model

    with patch("backend.final_predictor.build_production_prediction_model", side_effect=wrapped_builder):
        threads = []
        for _ in range(5):
            t = threading.Thread(target=predictor.train)
            threads.append(t)
            t.start()
        for t in threads:
            t.join()

    # Only one training operation should have run for this dataset revision
    assert fit_call_count == 1
    assert predictor.ready is True
    assert not predictor.is_stale


# ----------------------------------------------------------------------
# Test 7: Insufficient training data handling
# ----------------------------------------------------------------------
def test_insufficient_training_data_handling(test_db):
    predictor = FinalConnectivityPredictor(db_path=test_db)
    # Empty database
    assert predictor.train() is False
    assert predictor.ready is False
    assert predictor.model is None
    status = predictor.get_status_info()
    assert status["freshness"] == "unavailable"
    assert "Need at least 9" in status["message"]

    # Only 5 records (< 9 required for sequence length 8)
    _populate_records(test_db, 5)
    predictor.invalidate()
    assert predictor.train() is False
    assert predictor.ready is False
    assert predictor.model is None

    # Now add enough records to make it work
    _populate_records(test_db, 5)  # Total 10
    predictor.invalidate()
    assert predictor.train() is True
    assert predictor.ready is True
    assert predictor.model is not None


# ----------------------------------------------------------------------
# Test 8: Dataset changes during training
# ----------------------------------------------------------------------
def test_dataset_changes_during_training(test_db):
    predictor = FinalConnectivityPredictor(db_path=test_db)
    _populate_records(test_db, 10)
    predictor.invalidate()  # dataset_rev = 1

    import backend.final_predictor as fp_module
    original_builder = fp_module.build_production_prediction_model

    def builder_that_inserts_record():
        model = original_builder()
        original_fit = model.fit

        def fit_and_modify(X, y):
            # Simulate a new record arriving while fit is running
            _insert_record(test_db, score=99.0)
            predictor.notify_record_saved(50.0, 15.0, 20.0, 5.0, 0.0, 99.0)
            return original_fit(X, y)

        model.fit = fit_and_modify
        return model

    with patch("backend.final_predictor.build_production_prediction_model", side_effect=builder_that_inserts_record):
        trained = predictor.train()
        assert trained is False

    # The completed model was trained for rev 1, but new record pushed dataset to rev 2
    # The stale candidate was discarded, so model_revision has not advanced to rev 2
    assert predictor.model_revision < predictor.dataset_revision
    assert predictor.is_stale
    status = predictor.get_status_info()
    assert status["stale"] is True


# ----------------------------------------------------------------------
# Test 9: Prediction endpoint compatibility
# ----------------------------------------------------------------------
def test_prediction_endpoint_compatibility(client, monkeypatch):
    monkeypatch.setattr(main.final_predictor, "db_path", main.DB_PATH)
    main.final_predictor.notify_dataset_cleared()
    # With empty DB, 503 is returned
    resp = client.get("/api/ai/prediction")
    assert resp.status_code == 503

    # Save 10 valid tests via API
    for i in range(10):
        client.post(
            "/api/network-test",
            json={
                "download_mbps": 50.0 + i,
                "upload_mbps": 15.0,
                "ping_ms": 20.0,
                "jitter_ms": 5.0,
                "packet_loss": 0.0,
                "connectivity_score": 80.0 + i,
            },
        )

    # Prediction endpoint should now succeed and return all expected contract fields
    resp = client.get("/api/ai/prediction")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["model"] == "HistGradientBoosting"
    assert data["input_records"] == 8
    assert data["training_records"] >= 10
    assert data["training_samples"] >= 2
    assert "predicted_connectivity_score" in data
    assert 0 <= data["predicted_connectivity_score"] <= 100
    assert data["predicted_quality"] in ["Excellent", "Good", "Average", "Poor"]


# ----------------------------------------------------------------------
# Test 10: Status endpoint readiness
# ----------------------------------------------------------------------
def test_status_endpoint_readiness(client, monkeypatch):
    monkeypatch.setattr(main.final_predictor, "db_path", main.DB_PATH)
    # Clear predictor state for the empty test database
    main.final_predictor.notify_dataset_cleared()
    # Empty DB
    resp = client.get("/api/ai/status")
    assert resp.status_code == 200
    status = resp.json()
    assert status["prediction_model"]["name"] == "HistGradientBoosting"
    assert status["prediction_model"]["loaded"] is False
    assert status["prediction_model"]["freshness"] == "unavailable"

    # Add 10 records
    for i in range(10):
        client.post(
            "/api/network-test",
            json={
                "download_mbps": 55.0,
                "upload_mbps": 15.0,
                "ping_ms": 20.0,
                "jitter_ms": 5.0,
                "packet_loss": 0.0,
                "connectivity_score": 85.0,
            },
        )

    # Before prediction, model is stale because records were added
    resp = client.get("/api/ai/status")
    status = resp.json()
    assert status["prediction_model"]["stale"] is True

    # Call prediction, which triggers refresh
    pred_resp = client.get("/api/ai/prediction")
    assert pred_resp.status_code == 200

    # Status should now report fresh
    resp = client.get("/api/ai/status")
    status = resp.json()
    assert status["prediction_model"]["loaded"] is True
    assert status["prediction_model"]["ready"] is True
    assert status["prediction_model"]["stale"] is False
    assert status["prediction_model"]["freshness"] == "fresh"


# ----------------------------------------------------------------------
# Test 11: Explicit return value on successful model training
# ----------------------------------------------------------------------
def test_successful_training_returns_true(test_db):
    """
    Verify that when model training succeeds and candidate is published,
    train() explicitly returns True and model_revision matches dataset_revision.
    """
    predictor = FinalConnectivityPredictor(db_path=test_db)
    _populate_records(test_db, 10)
    predictor.invalidate()
    assert predictor.is_stale is True
    target_rev = predictor.dataset_revision

    result = predictor.train()
    assert result is True
    assert predictor.ready is True
    assert predictor.model is not None
    assert predictor.model_revision == target_rev
    assert predictor.dataset_revision == target_rev
    assert predictor.is_stale is False


# ----------------------------------------------------------------------
# Test 12: Dataset deletion during active training discards candidate
# ----------------------------------------------------------------------
def test_dataset_deletion_during_active_training(test_db):
    """
    Verify race condition where notify_dataset_cleared() is invoked while
    model training is in progress. The candidate trained on deleted records
    must be discarded, model_revision must not advance to target_revision,
    and train() must return False without overwriting cleared model state.
    """
    predictor = FinalConnectivityPredictor(db_path=test_db)
    _populate_records(test_db, 10)
    initial_train_result = predictor.train()
    assert initial_train_result is True
    published_model = predictor.model
    assert published_model is not None

    # Now add more records so model is marked stale for a new revision
    _populate_records(test_db, 2)
    predictor.invalidate()
    target_rev = predictor.dataset_revision

    training_started = threading.Event()
    dataset_cleared = threading.Event()

    import backend.final_predictor as fp_module
    original_builder = fp_module.build_production_prediction_model

    def builder_with_deletion_sync():
        model = original_builder()
        original_fit = model.fit

        def fit_and_wait(X, y):
            # Signal that candidate training has begun
            training_started.set()
            # Wait until dataset deletion has been triggered
            cleared_ok = dataset_cleared.wait(timeout=5.0)
            assert cleared_ok, "Timed out waiting for dataset to be cleared"
            return original_fit(X, y)

        model.fit = fit_and_wait
        return model

    train_result_container = []

    def run_training():
        res = predictor.train()
        train_result_container.append(res)

    worker_thread = threading.Thread(target=run_training)

    with patch("backend.final_predictor.build_production_prediction_model", side_effect=builder_with_deletion_sync):
        worker_thread.start()

        # Step 4: Wait until training has definitely started
        started_ok = training_started.wait(timeout=5.0)
        assert started_ok, "Timed out waiting for training to begin"

        # Step 5: Invoke notify_dataset_cleared() while training is active
        # Simulate clearing the database table as well
        with sqlite3.connect(test_db) as conn:
            conn.execute("DELETE FROM network_tests")
            conn.commit()

        predictor.notify_dataset_cleared()

        # Step 6: Confirm dataset revision has changed
        assert predictor.dataset_revision > target_rev
        cleared_rev = predictor.dataset_revision
        assert predictor.model is None
        assert predictor.ready is False

        # Step 7: Resume candidate training operation
        dataset_cleared.set()

        # Step 8: Wait for refresh completion
        worker_thread.join(timeout=10.0)
        assert not worker_thread.is_alive()

    # Assertions:
    # 1. The refresh operation returns an unsuccessful result
    assert len(train_result_container) == 1
    assert train_result_container[0] is False

    # 2. The stale candidate was not published and model remains cleared
    assert predictor.model is None
    assert predictor.ready is False

    # 3. model_revision is not advanced to the stale target revision
    assert predictor.model_revision != target_rev
    assert predictor.model_revision == cleared_rev

    # 4. Model is not reported as fresh
    status = predictor.get_status_info()
    assert status["freshness"] == "unavailable"

    # 5. The in-progress refresh lock/flag is released
    assert predictor.is_training is False

    # 6. A subsequent refresh can execute normally once new data arrives
    _populate_records(test_db, 10)
    predictor.invalidate()
    assert predictor.train() is True
    assert predictor.ready is True
    assert predictor.model is not None
