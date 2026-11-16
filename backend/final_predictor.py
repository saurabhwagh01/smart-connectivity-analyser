"""
Final connectivity prediction model for Smart Connectivity Analyser.

Uses HistGradientBoostingRegressor with the same 8-record window
evaluated in ml_model_comparison.py.

The model is trained from all currently complete historical records
when the FastAPI application starts, and refreshed dynamically and safely
when new eligible measurements are saved.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path
from typing import Any

import numpy as np

if __package__:
    from .model_config import (
        build_production_prediction_model,
        constrain_connectivity_predictions,
        is_valid_measurement_row,
    )
else:  # Support importing final_predictor directly from backend/.
    from model_config import (
        build_production_prediction_model,
        constrain_connectivity_predictions,
        is_valid_measurement_row,
    )


logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "network_history.db"

FEATURES = [
    "download_mbps",
    "upload_mbps",
    "ping_ms",
    "jitter_ms",
    "packet_loss",
    "connectivity_score",
]

SEQUENCE_LENGTH = 8


class FinalConnectivityPredictor:
    """Train and serve the final connectivity-score prediction model with thread-safe refresh."""

    def __init__(self, db_path: Path | str | None = None):
        self._db_path = Path(db_path) if db_path is not None else DB_PATH
        self.model = None
        self.record_count = 0
        self.training_samples = 0
        self.ready = False
        self.message = "Model not trained."

        # Version tracking & synchronization
        self.dataset_revision = 0
        self.model_revision = 0
        self.last_refresh_error: str | None = None
        self.is_training = False
        self._lock = threading.Lock()

    @property
    def db_path(self) -> Path:
        # Dynamically follow module-level DB_PATH unless explicitly overridden
        return self._db_path if self._db_path != DB_PATH else DB_PATH

    @db_path.setter
    def db_path(self, path: Path | str) -> None:
        self._db_path = Path(path)

    @property
    def is_stale(self) -> bool:
        """Return True if eligible data has changed since the current model was trained."""
        return self.dataset_revision != self.model_revision

    def get_status_info(self) -> dict[str, Any]:
        """Return a structured breakdown of readiness, freshness, and training status."""
        with self._lock:
            # Determine high-level freshness status:
            # - 'training' if currently training
            # - 'failed' if last refresh failed and dataset is still stale
            # - 'fresh' if model is up-to-date with dataset revision
            # - 'stale' if new records arrived and model hasn't updated yet
            # - 'unavailable' if model has never been trained / not ready
            if self.is_training:
                freshness = "training"
            elif not self.ready:
                freshness = "unavailable"
            elif self.dataset_revision != self.model_revision:
                if self.last_refresh_error is not None:
                    freshness = "failed"
                else:
                    freshness = "stale"
            else:
                freshness = "fresh"

            return {
                "name": "HistGradientBoosting",
                "loaded": bool(self.ready and self.model is not None),
                "ready": bool(self.ready and self.model is not None),
                "stale": bool(self.dataset_revision != self.model_revision),
                "freshness": freshness,
                "is_training": bool(self.is_training),
                "dataset_revision": int(self.dataset_revision),
                "model_revision": int(self.model_revision),
                "training_records": int(self.record_count),
                "training_samples": int(self.training_samples),
                "last_refresh_error": self.last_refresh_error,
                "message": self.message,
            }

    def check_eligible_record(
        self,
        download_mbps: float | None,
        upload_mbps: float | None,
        ping_ms: float | None,
        jitter_ms: float | None,
        packet_loss: float | None,
        connectivity_score: float | None,
    ) -> bool:
        """Check if incoming measurement fields form a valid, eligible training row."""
        raw = [
            download_mbps,
            upload_mbps,
            ping_ms,
            jitter_ms,
            packet_loss,
            connectivity_score,
        ]
        if any(value is None for value in raw):
            return False
        try:
            values = [float(v) for v in raw]
        except (TypeError, ValueError, OverflowError):
            return False
        return is_valid_measurement_row(values)

    def invalidate(self) -> int:
        """Mark eligible dataset as modified, incrementing dataset_revision."""
        with self._lock:
            self.dataset_revision += 1
            logger.info(
                "Dataset revision advanced to %d (model revision: %d). Model marked stale.",
                self.dataset_revision,
                self.model_revision,
            )
            return self.dataset_revision

    def notify_record_saved(
        self,
        download_mbps: float | None,
        upload_mbps: float | None,
        ping_ms: float | None,
        jitter_ms: float | None,
        packet_loss: float | None,
        connectivity_score: float | None,
    ) -> bool:
        """
        Check if the newly committed record qualifies for model training.
        If it qualifies, invalidate the model by advancing the dataset revision.
        Returns True if the model was invalidated, False otherwise.
        """
        if self.check_eligible_record(
            download_mbps=download_mbps,
            upload_mbps=upload_mbps,
            ping_ms=ping_ms,
            jitter_ms=jitter_ms,
            packet_loss=packet_loss,
            connectivity_score=connectivity_score,
        ):
            self.invalidate()
            return True
        return False

    def notify_dataset_cleared(self) -> None:
        """Handle dataset deletion: increment dataset revision and clear model state."""
        with self._lock:
            self.dataset_revision += 1
            self.model = None
            self.model_revision = self.dataset_revision
            self.record_count = 0
            self.training_samples = 0
            self.ready = False
            self.last_refresh_error = None
            self.message = (
                f"Need at least {SEQUENCE_LENGTH + 1} "
                "complete records for prediction."
            )

    def _load_complete_data(self) -> np.ndarray:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row

        try:
            try:
                rows = connection.execute(
                    f"""
                    SELECT timestamp, {", ".join(FEATURES)}
                    FROM network_tests
                    ORDER BY timestamp ASC, id ASC
                    """
                ).fetchall()

            except sqlite3.OperationalError as error:
                if (
                    "no such table" in str(error).lower()
                    or "no such column" in str(error).lower()
                ):
                    return np.empty(
                        (0, len(FEATURES)),
                        dtype=float,
                    )
                raise

        finally:
            connection.close()

        data = []

        for row in rows:
            if row["timestamp"] is None:
                continue

            raw = [row[column] for column in FEATURES]

            if any(value is None for value in raw):
                continue

            try:
                values = [float(value) for value in raw]
            except (TypeError, ValueError, OverflowError):
                continue

            if not is_valid_measurement_row(values):
                continue

            data.append(values)

        return np.asarray(data, dtype=float).reshape(
            -1,
            len(FEATURES),
        )

    def _build_dataset(self, data: np.ndarray):
        score_index = FEATURES.index("connectivity_score")

        X = []
        y = []

        for index in range(SEQUENCE_LENGTH, len(data)):
            window = data[index - SEQUENCE_LENGTH:index]

            # Same 8-record × 6-feature representation used in
            # the validated classical-ML comparison.
            X.append(window.reshape(-1))
            y.append(data[index, score_index])

        return (
            np.asarray(X, dtype=float),
            np.asarray(y, dtype=float),
        )

    def train(self) -> bool:
        """
        Train or refresh the model synchronously if stale or uninitialized.
        Safely protects previously working models if training fails.
        Prevents concurrent duplicate training operations.
        """
        with self._lock:
            # If already fresh and ready, avoid unnecessary retraining
            if self.ready and self.model is not None and self.model_revision == self.dataset_revision:
                return True

            if self.is_training:
                # Retraining is already underway in another thread
                return self.ready

            self.is_training = True
            # Capture the target revision we are beginning to train for
            target_revision = self.dataset_revision

        candidate_model = None
        data = None
        X = None
        y = None
        train_success = False
        error_msg = None

        try:
            data = self._load_complete_data()
            record_count = len(data)

            if record_count <= SEQUENCE_LENGTH:
                error_msg = (
                    f"Need at least {SEQUENCE_LENGTH + 1} "
                    "complete records for prediction."
                )
                logger.warning("Insufficient training data: %s", error_msg)
                with self._lock:
                    self.is_training = False
                    self.record_count = record_count
                    self.last_refresh_error = error_msg
                    # If we don't have a previously working model, mark not ready
                    if self.model is None:
                        self.ready = False
                        self.training_samples = 0
                        self.message = error_msg
                    else:
                        # Keep previous model, but note stale/insufficient status
                        self.message = f"Refresh failed: {error_msg}. Using previous model."
                    return self.ready

            X, y = self._build_dataset(data)
            candidate_model = build_production_prediction_model()
            candidate_model.fit(X, y)
            train_success = True

        except Exception as exc:
            error_msg = f"Training failed: {exc}"
            logger.exception("Error during model training")
            with self._lock:
                self.is_training = False
                self.last_refresh_error = error_msg
                if self.model is None:
                    self.ready = False
                    self.message = error_msg
                else:
                    self.message = f"Refresh failed: {exc}. Using previous model."
                return self.ready

        # Training succeeded: safely publish the candidate model
        with self._lock:
            self.is_training = False
            self.model = candidate_model
            self.record_count = len(data) if data is not None else 0
            self.training_samples = len(X) if X is not None else 0
            self.ready = True
            self.last_refresh_error = None
            self.model_revision = target_revision
            self.message = "HistGradientBoosting model trained successfully."
            logger.info(
                "Candidate model published successfully for dataset revision %d.",
                target_revision,
            )
            return True

    def refresh_if_needed(self) -> bool:
        """
        Check if model needs retraining and trigger controlled refresh if so.
        Returns True if a model is ready (either freshly trained or working previous model).
        """
        needs_refresh = False
        with self._lock:
            if not self.ready or self.model is None or self.model_revision != self.dataset_revision:
                needs_refresh = True

        if needs_refresh:
            return self.train()
        return self.ready

    def predict(self) -> float:
        """
        Generate connectivity prediction for the latest 8-record window.
        Refreshes the model first if stale or not yet trained.
        """
        self.refresh_if_needed()

        if not self.ready or self.model is None:
            raise RuntimeError(self.message)

        data = self._load_complete_data()

        if len(data) < SEQUENCE_LENGTH:
            raise RuntimeError(
                f"At least {SEQUENCE_LENGTH} complete records "
                "are required."
            )

        latest_window = data[-SEQUENCE_LENGTH:]
        X = latest_window.reshape(1, -1)

        prediction = float(
            constrain_connectivity_predictions(self.model.predict(X))[0]
        )

        return prediction


final_predictor = FinalConnectivityPredictor()
FINAL_PREDICTOR_READY = final_predictor.train()
