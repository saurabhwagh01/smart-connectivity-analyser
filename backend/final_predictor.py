
"""
Final connectivity prediction model for Smart Connectivity Analyser.

Uses HistGradientBoostingRegressor with the same 8-record window
evaluated in ml_model_comparison.py.

The model is trained from all currently complete historical records
when the FastAPI application starts. It does not modify the database.

Model refresh (issue #37):

* Every training run records a *training-data version*: a fingerprint
  of the eligible (complete, valid, chronologically ordered) records it
  was trained on. Incomplete or invalid records are not part of the
  fingerprint, so saving them does not make the model stale.
* ``refresh_if_stale()`` compares the trained version with the current
  database. It retrains only when the eligible data has changed, so
  predictions do not retrain on every request.
* Refreshes are serialized with a lock. A caller that waits for another
  refresh re-checks the version afterwards, so concurrent requests do
  not train the same data twice.
* A new model replaces the previous one only after it has trained
  successfully. If a refresh fails (or there are no longer enough
  records), the previous model stays in use and is reported as stale
  together with the refresh error.
"""

from __future__ import annotations

import hashlib
import sqlite3
import threading
from pathlib import Path

import numpy as np

if __package__:
    from .model_config import (
        build_production_prediction_model,
        constrain_connectivity_predictions,
        is_valid_measurement_row,
    )
    from .timestamps import canonical_sort_key, to_canonical_utc
else:  # Support importing final_predictor directly from backend/.
    from model_config import (
        build_production_prediction_model,
        constrain_connectivity_predictions,
        is_valid_measurement_row,
    )
    from timestamps import canonical_sort_key, to_canonical_utc


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


def training_data_version(data):
    """Return a stable fingerprint of the eligible training data."""

    array = np.ascontiguousarray(
        np.asarray(data, dtype=np.float64).reshape(-1, len(FEATURES))
    )
    digest = hashlib.sha256()
    digest.update(str(array.shape).encode("ascii"))
    digest.update(array.tobytes())
    return digest.hexdigest()


class FinalConnectivityPredictor:
    """Train and serve the final connectivity-score prediction model."""

    def __init__(self, db_path=None):
        self.db_path = db_path
        self.model = None
        self.record_count = 0
        self.training_samples = 0
        self.ready = False
        self.message = "Model not trained."
        # Version of the data the current model was trained on.
        self.data_version = None
        # Version of the eligible data last seen in the database.
        self.latest_data_version = None
        self.last_refresh_error = None
        self._refresh_lock = threading.Lock()

    @property
    def stale(self):
        """True when the database has eligible data the model has not used."""

        return (
            self.model is not None
            and self.latest_data_version is not None
            and self.latest_data_version != self.data_version
        )

    def _load_complete_data(self):
        connection = sqlite3.connect(self.db_path or DB_PATH)
        connection.row_factory = sqlite3.Row

        try:
            try:
                rows = connection.execute(
                    f"""
                    SELECT id, timestamp, {", ".join(FEATURES)}
                    FROM network_tests
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

        # Same chronological order as ai_engine.load_network_data():
        # real UTC instant, then id (issue #39).
        rows = sorted(
            rows,
            key=lambda row: canonical_sort_key(row["timestamp"], row["id"]),
        )

        data = []

        for row in rows:
            # Records that cannot be placed in time are skipped.
            if to_canonical_utc(row["timestamp"]) is None:
                continue

            raw = [row[column] for column in FEATURES]

            if any(value is None for value in raw):
                continue

            try:
                values = [float(value) for value in raw]
            except (TypeError, ValueError):
                continue

            if not is_valid_measurement_row(values):
                continue

            data.append(values)

        return np.asarray(data, dtype=float).reshape(
            -1,
            len(FEATURES),
        )

    def _build_dataset(self, data):
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

    def _fit(self, data):
        """Train a new model on ``data`` without touching current state."""

        X, y = self._build_dataset(data)
        model = build_production_prediction_model()
        model.fit(X, y)
        return model, len(X)

    def _refresh(self, data, version):
        """Retrain on ``data``. Caller must hold ``_refresh_lock``."""

        self.latest_data_version = version

        if len(data) <= SEQUENCE_LENGTH:
            message = (
                f"Need at least {SEQUENCE_LENGTH + 1} "
                "complete records for prediction."
            )
            self.last_refresh_error = message
            if self.model is None:
                self.ready = False
                self.message = message
            return False

        try:
            model, samples = self._fit(data)
        except Exception as error:  # Keep the previous model on failure.
            self.last_refresh_error = f"Model refresh failed: {error}"
            if self.model is None:
                self.ready = False
                self.message = self.last_refresh_error
            return False

        # Swap in the new model only after it trained successfully.
        self.model = model
        self.record_count = len(data)
        self.training_samples = samples
        self.data_version = version
        self.last_refresh_error = None
        self.ready = True
        self.message = "HistGradientBoosting model trained successfully."
        return True

    def train(self):
        """Train on the current data. Returns whether a model is ready."""

        with self._refresh_lock:
            data = self._load_complete_data()
            self._refresh(data, training_data_version(data))
            return self.ready

    def check_staleness(self):
        """Record the current data version without training. Returns stale."""

        self.latest_data_version = training_data_version(
            self._load_complete_data()
        )
        return self.stale

    def refresh_if_stale(self):
        """Retrain only if the eligible data changed since the last training.

        Returns True when this call trained a new model.
        """

        version = training_data_version(self._load_complete_data())

        if self.ready and version == self.data_version:
            self.latest_data_version = version
            return False

        with self._refresh_lock:
            # Another request may have refreshed while we waited for the
            # lock. Re-read so we train on the newest data exactly once.
            data = self._load_complete_data()
            version = training_data_version(data)

            if self.ready and version == self.data_version:
                self.latest_data_version = version
                return False

            if (
                version == self.latest_data_version
                and self.last_refresh_error is not None
            ):
                # This exact data already failed to train; don't retry
                # on every request until the data changes again.
                return False

            return self._refresh(data, version)

    def status(self):
        """Readiness details for the API."""

        return {
            "ready": self.ready,
            "stale": self.stale,
            "training_data_version": self.data_version,
            "latest_data_version": self.latest_data_version,
            "training_records": self.record_count,
            "training_samples": self.training_samples,
            "message": self.message,
            "last_refresh_error": self.last_refresh_error,
        }

    def predict(self):
        if not self.ready or self.model is None:
            raise RuntimeError(self.message)

        data = self._load_complete_data()

        if len(data) < SEQUENCE_LENGTH:
            raise RuntimeError(
                f"At least {SEQUENCE_LENGTH} complete records "
                "are required."
            )

        # Read the model once so a concurrent refresh cannot swap it
        # between checks.
        model = self.model
        latest_window = data[-SEQUENCE_LENGTH:]
        X = latest_window.reshape(1, -1)

        prediction = float(
            constrain_connectivity_predictions(model.predict(X))[0]
        )

        return prediction


final_predictor = FinalConnectivityPredictor()
FINAL_PREDICTOR_READY = final_predictor.train()
