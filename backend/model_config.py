"""Shared production prediction-model configuration and output constraints."""

from __future__ import annotations

import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor


CONNECTIVITY_SCORE_MIN = 0.0
CONNECTIVITY_SCORE_MAX = 100.0
PACKET_LOSS_MAX = 100.0

# Keep the benchmark and deployed predictor on exactly the same configuration.
PRODUCTION_HIST_GRADIENT_BOOSTING_PARAMS: dict[str, int | float] = {
    "max_iter": 300,
    "learning_rate": 0.05,
    "max_leaf_nodes": 15,
    "l2_regularization": 0.1,
    "random_state": 42,
}


def build_production_prediction_model() -> HistGradientBoostingRegressor:
    """Create the HistGradientBoosting model used by the application."""

    return HistGradientBoostingRegressor(
        **PRODUCTION_HIST_GRADIENT_BOOSTING_PARAMS
    )


def is_valid_measurement_row(values: np.ndarray) -> bool:
    """Return whether a six-feature database row satisfies app input bounds."""

    try:
        row = np.asarray(values, dtype=float)
    except (TypeError, ValueError, OverflowError):
        return False
    if row.ndim != 1 or row.size != 6 or not np.isfinite(row).all():
        return False
    if np.any(row < 0.0):
        return False
    return bool(
        row[4] <= PACKET_LOSS_MAX
        and row[5] <= CONNECTIVITY_SCORE_MAX
    )


def constrain_connectivity_predictions(predictions: np.ndarray) -> np.ndarray:
    """Constrain predicted connectivity scores to the application's 0–100 scale."""

    values = np.asarray(predictions, dtype=float)
    if not np.isfinite(values).all():
        raise ValueError("predictions must contain only finite values")
    return np.clip(
        values,
        CONNECTIVITY_SCORE_MIN,
        CONNECTIVITY_SCORE_MAX,
    )
