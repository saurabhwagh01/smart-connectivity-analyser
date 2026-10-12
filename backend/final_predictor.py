"""
Final connectivity prediction model for Smart Connectivity Analyser.

Uses HistGradientBoostingRegressor with the same 8-record window
evaluated in ml_model_comparison.py.

The model is trained from all currently complete historical records
when the FastAPI application starts. It does not modify the database.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor


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
RANDOM_STATE = 42


class FinalConnectivityPredictor:
    """Train and serve the final connectivity-score prediction model."""

    def __init__(self):
        self.model = None
        self.record_count = 0
        self.training_samples = 0
        self.ready = False
        self.message = "Model not trained."

    def _load_complete_data(self):
        connection = sqlite3.connect(DB_PATH)
        connection.row_factory = sqlite3.Row

        try:
            rows = connection.execute(
                f"""
                SELECT {", ".join(FEATURES)}
                FROM network_tests
                ORDER BY timestamp ASC
                """
            ).fetchall()
        finally:
            connection.close()

        data = []

        for row in rows:
            raw = [row[column] for column in FEATURES]

            if any(value is None for value in raw):
                continue

            try:
                values = [float(value) for value in raw]
            except (TypeError, ValueError):
                continue

            if not all(np.isfinite(values)):
                continue

            data.append(values)

        return np.asarray(data, dtype=float)

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

    def train(self):
        data = self._load_complete_data()
        self.record_count = len(data)

        if len(data) <= SEQUENCE_LENGTH:
            self.ready = False
            self.message = (
                f"Need at least {SEQUENCE_LENGTH + 1} "
                "complete records for prediction."
            )
            return False

        X, y = self._build_dataset(data)

        self.model = HistGradientBoostingRegressor(
            max_iter=300,
            learning_rate=0.05,
            max_leaf_nodes=15,
            l2_regularization=0.1,
            random_state=RANDOM_STATE,
        )

        self.model.fit(X, y)

        self.training_samples = len(X)
        self.ready = True
        self.message = "HistGradientBoosting model trained successfully."

        return True

    def predict(self):
        if not self.ready or self.model is None:
            raise RuntimeError(self.message)

        data = self._load_complete_data()

        if len(data) < SEQUENCE_LENGTH:
            raise RuntimeError(
                f"At least {SEQUENCE_LENGTH} complete records are required."
            )

        latest_window = data[-SEQUENCE_LENGTH:]
        X = latest_window.reshape(1, -1)

        prediction = float(self.model.predict(X)[0])

        prediction = max(
            0.0,
            min(100.0, prediction),
        )

        return prediction


final_predictor = FinalConnectivityPredictor()
FINAL_PREDICTOR_READY = final_predictor.train()
