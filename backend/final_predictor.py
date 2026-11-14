
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

    def train(self):
        data = self._load_complete_data()
        self.record_count = len(data)

        if len(data) <= SEQUENCE_LENGTH:
            self.model = None
            self.training_samples = 0
            self.ready = False
            self.message = (
                f"Need at least {SEQUENCE_LENGTH + 1} "
                "complete records for prediction."
            )
            return False

        X, y = self._build_dataset(data)

        self.model = build_production_prediction_model()

        self.model.fit(X, y)

        self.training_samples = len(X)
        self.ready = True
        self.message = (
            "HistGradientBoosting model trained successfully."
        )

        return True

    def predict(self):
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
