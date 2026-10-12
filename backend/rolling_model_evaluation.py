
"""
Smart Connectivity Analyser
Rolling Chronological Model Evaluation

Compares:
1. Previous-value baseline
2. Random Forest Regressor

Uses multiple chronological test windows.
Does not modify the database or production models.
"""

import json
import sqlite3
from pathlib import Path

import numpy as np
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score


BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "network_history.db"
RESULTS_PATH = Path(__file__).resolve().parent / "rolling_model_evaluation_results.json"

FEATURES = [
    "download_mbps",
    "upload_mbps",
    "ping_ms",
    "jitter_ms",
    "packet_loss",
    "connectivity_score",
]

SEQUENCE_LENGTH = 8
N_WINDOWS = 4
RANDOM_STATE = 42


def load_data():
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found: {DB_PATH}")

    with sqlite3.connect(DB_PATH) as connection:
        rows = connection.execute(
            f"""
            SELECT {", ".join(FEATURES)}
            FROM network_tests
            ORDER BY timestamp ASC
            """
        ).fetchall()

    records = []

    for row in rows:
        try:
            values = np.asarray(row, dtype=float)
        except (TypeError, ValueError):
            continue

        if np.isfinite(values).all():
            records.append(values)

    return np.asarray(records, dtype=float)


def metrics(actual, predicted):
    return {
        "mae": round(float(mean_absolute_error(actual, predicted)), 4),
        "rmse": round(float(np.sqrt(mean_squared_error(actual, predicted))), 4),
        "r2": round(float(r2_score(actual, predicted)), 4),
    }


def make_samples(data):
    score_index = FEATURES.index("connectivity_score")
    X, y, target_indices = [], [], []

    for index in range(SEQUENCE_LENGTH, len(data)):
        X.append(data[index - SEQUENCE_LENGTH:index].reshape(-1))
        y.append(data[index, score_index])
        target_indices.append(index)

    return (
        np.asarray(X),
        np.asarray(y),
        np.asarray(target_indices),
    )


def main():
    data = load_data()

    if len(data) < 40:
        raise ValueError(
            f"Only {len(data)} complete records found. "
            "Collect more records before rolling evaluation."
        )

    X, y, target_indices = make_samples(data)
    score_index = FEATURES.index("connectivity_score")

    # Four expanding chronological windows:
    # train on earlier records, evaluate on the next block.
    first_test = int(len(data) * 0.60)
    remaining = len(data) - first_test
    window_size = remaining // N_WINDOWS

    if window_size < 2:
        raise ValueError("Not enough records for four test windows.")

    window_results = []

    print("=" * 60)
    print("ROLLING CHRONOLOGICAL MODEL EVALUATION")
    print("=" * 60)
    print(f"Complete records: {len(data)}")
    print(f"Sequence length: {SEQUENCE_LENGTH}")
    print(f"Test windows: {N_WINDOWS}")
    print()

    for window in range(N_WINDOWS):
        test_start = first_test + window * window_size

        if window == N_WINDOWS - 1:
            test_end = len(data)
        else:
            test_end = test_start + window_size

        train_mask = target_indices < test_start
        test_mask = (
            (target_indices >= test_start)
            & (target_indices < test_end)
        )

        X_train, y_train = X[train_mask], y[train_mask]
        X_test, y_test = X[test_mask], y[test_mask]

        if len(X_train) == 0 or len(X_test) == 0:
            continue

        model = RandomForestRegressor(
            n_estimators=200,
            max_depth=8,
            min_samples_leaf=2,
            random_state=RANDOM_STATE,
            n_jobs=-1,
        )
        model.fit(X_train, y_train)
        rf_predictions = model.predict(X_test)

        # For every test target, predict using the immediately
        # preceding observed connectivity score.
        baseline_predictions = data[
            target_indices[test_mask] - 1, score_index
        ]

        baseline_metrics = metrics(y_test, baseline_predictions)
        rf_metrics = metrics(y_test, rf_predictions)

        window_results.append({
            "window": window + 1,
            "training_samples": int(len(X_train)),
            "test_samples": int(len(X_test)),
            "previous_value": baseline_metrics,
            "random_forest": rf_metrics,
        })

        print(
            f"Window {window + 1}: "
            f"train={len(X_train)}, test={len(X_test)}"
        )
        print(
            f"  Previous-value RMSE: {baseline_metrics['rmse']:.4f}"
        )
        print(
            f"  Random Forest RMSE:  {rf_metrics['rmse']:.4f}"
        )
        print()

    if not window_results:
        raise ValueError("No valid test windows were evaluated.")

    def average_metric(model_name, metric_name):
        return round(
            float(np.mean([
                item[model_name][metric_name]
                for item in window_results
            ])),
            4,
        )

    summary = {}

    for model_name in ("previous_value", "random_forest"):
        summary[model_name] = {
            metric_name: average_metric(model_name, metric_name)
            for metric_name in ("mae", "rmse", "r2")
        }

    output = {
        "evaluation": "Expanding-window chronological evaluation",
        "complete_records": int(len(data)),
        "sequence_length": SEQUENCE_LENGTH,
        "window_count": len(window_results),
        "windows": window_results,
        "mean_window_metrics": summary,
        "lower_mean_rmse_model": min(
            summary,
            key=lambda name: summary[name]["rmse"],
        ),
        "note": (
            "Each window trains on earlier records and tests on a later block. "
            "Within each test block, later predictions use the immediately "
            "preceding observed record. Results measure rolling one-step-ahead "
            "prediction, not long-range forecasting."
        ),
    }

    RESULTS_PATH.write_text(
        json.dumps(output, indent=2),
        encoding="utf-8",
    )

    print("=" * 60)
    print("MEAN WINDOW METRICS")
    print(json.dumps(summary, indent=2))
    print()
    print(f"Lower mean RMSE: {output['lower_mean_rmse_model']}")
    print(f"Results saved to: {RESULTS_PATH}")
    print("=" * 60)


if __name__ == "__main__":
    main()
