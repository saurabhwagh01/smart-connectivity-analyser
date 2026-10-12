"""
Smart Connectivity Analyser
Feature-Engineered HistGradientBoosting Evaluation

Goal:
Improve connectivity-score prediction using recent temporal/network
features while keeping the same chronological 80/20 unseen test split.

This script ONLY evaluates the model.
It does not modify the database or existing AI model files.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score


BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "network_history.db"
RESULTS_PATH = Path(__file__).resolve().parent / "feature_engineered_results.json"

FEATURES = [
    "download_mbps",
    "upload_mbps",
    "ping_ms",
    "jitter_ms",
    "packet_loss",
    "connectivity_score",
]

SEQUENCE_LENGTH = 8
TEST_RATIO = 0.20
RANDOM_STATE = 42


def load_complete_data():
    """Load only complete, finite records in chronological order."""

    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found: {DB_PATH}")

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


def build_features(data):
    """
    Build temporal and network-quality features.

    For every target record, features are calculated only from the
    previous 8 records, so future information is never used.
    """

    score_index = FEATURES.index("connectivity_score")

    X = []
    y = []

    for i in range(SEQUENCE_LENGTH, len(data)):

        window = data[i - SEQUENCE_LENGTH:i]

        # Individual latest measurements.
        latest = window[-1]

        # Recent averages.
        mean_values = np.mean(window, axis=0)

        # Recent standard deviation / volatility.
        std_values = np.std(window, axis=0)

        # First-to-last change.
        change_values = window[-1] - window[0]

        # Last 3-record average.
        short_window = window[-3:]
        short_mean = np.mean(short_window, axis=0)

        # Last 3-record trend.
        short_change = short_window[-1] - short_window[0]

        # Recent score differences.
        score_series = window[:, score_index]
        score_diff = np.diff(score_series)

        if len(score_diff) > 0:
            score_change_mean = float(np.mean(score_diff))
            score_change_std = float(np.std(score_diff))
            score_last_change = float(score_diff[-1])
        else:
            score_change_mean = 0.0
            score_change_std = 0.0
            score_last_change = 0.0

        # Construct a compact engineered feature vector.
        features = np.concatenate([
            latest,
            mean_values,
            std_values,
            change_values,
            short_mean,
            short_change,
            [
                score_change_mean,
                score_change_std,
                score_last_change,
            ],
        ])

        X.append(features)
        y.append(data[i, score_index])

    return np.asarray(X, dtype=float), np.asarray(y, dtype=float)


def evaluate_model(data, split_index):
    """Train on historical targets and evaluate on unseen targets."""

    X, y = build_features(data)

    # Feature row j predicts original record SEQUENCE_LENGTH + j.
    target_indices = np.arange(
        SEQUENCE_LENGTH,
        len(data)
    )

    train_mask = target_indices < split_index
    test_mask = target_indices >= split_index

    X_train = X[train_mask]
    y_train = y[train_mask]

    X_test = X[test_mask]
    y_test = y[test_mask]

    model = HistGradientBoostingRegressor(
        max_iter=400,
        learning_rate=0.04,
        max_leaf_nodes=12,
        min_samples_leaf=4,
        l2_regularization=0.5,
        random_state=RANDOM_STATE,
    )

    model.fit(X_train, y_train)

    predictions = model.predict(X_test)

    mae = mean_absolute_error(y_test, predictions)
    rmse = np.sqrt(mean_squared_error(y_test, predictions))
    r2 = r2_score(y_test, predictions)

    return {
        "mae": float(mae),
        "rmse": float(rmse),
        "r2": float(r2),
        "training_samples": int(len(X_train)),
        "test_samples": int(len(X_test)),
        "feature_count": int(X.shape[1]),
    }


def main():
    print("=" * 60)
    print("SMART CONNECTIVITY ANALYSER")
    print("FEATURE-ENGINEERED MODEL EVALUATION")
    print("=" * 60)

    data = load_complete_data()

    split_index = int(
        len(data) * (1.0 - TEST_RATIO)
    )

    train_count = split_index
    test_count = len(data) - split_index

    print(f"Complete records: {len(data)}")
    print(f"Training records: {train_count}")
    print(f"Unseen test records: {test_count}")
    print()

    result = evaluate_model(
        data,
        split_index
    )

    print("FEATURE-ENGINEERED HISTGRADIENTBOOSTING")
    print("-" * 60)
    print(f"MAE:  {result['mae']:.4f}")
    print(f"RMSE: {result['rmse']:.4f}")
    print(f"R2:   {result['r2']:.4f}")
    print(f"Features: {result['feature_count']}")
    print()

    print("=" * 60)

    if result["r2"] >= 0:
        print("RESULT: R2 is non-negative.")
        print("The model is explaining useful variation in the test data.")
    else:
        print("RESULT: R2 is still negative.")
        print("The model improves error metrics but needs more data or tuning.")

    print("=" * 60)

    output = {
        "dataset": {
            "complete_records": len(data),
            "training_records": train_count,
            "unseen_test_records": test_count,
            "sequence_length": SEQUENCE_LENGTH,
            "test_ratio": TEST_RATIO,
        },
        "model": "HistGradientBoostingRegressor",
        "result": result,
    }

    RESULTS_PATH.write_text(
        json.dumps(output, indent=2),
        encoding="utf-8"
    )

    print()
    print(f"Results saved to: {RESULTS_PATH}")


if __name__ == "__main__":
    main()
