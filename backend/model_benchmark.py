"""Reproducible, leakage-aware benchmark for connectivity-score prediction.

Run from the repository root:
    python backend/model_benchmark.py

The benchmark reads the local SQLite history database and writes aggregate
metrics only. It does not modify the database or production model files.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import time
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import TimeSeriesSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

if __package__:
    from .model_config import (
        CONNECTIVITY_SCORE_MAX,
        CONNECTIVITY_SCORE_MIN,
        PRODUCTION_HIST_GRADIENT_BOOSTING_PARAMS,
        build_production_prediction_model,
        constrain_connectivity_predictions,
        is_valid_measurement_row,
    )
else:  # Support running this file directly from the repository root.
    from model_config import (
        CONNECTIVITY_SCORE_MAX,
        CONNECTIVITY_SCORE_MIN,
        PRODUCTION_HIST_GRADIENT_BOOSTING_PARAMS,
        build_production_prediction_model,
        constrain_connectivity_predictions,
        is_valid_measurement_row,
    )


BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = BASE_DIR / "network_history.db"
DEFAULT_RESULTS_PATH = Path(__file__).resolve().parent / "model_benchmark_results.json"

FEATURE_COLUMNS = (
    "download_mbps",
    "upload_mbps",
    "ping_ms",
    "jitter_ms",
    "packet_loss",
    "connectivity_score",
)
TARGET_COLUMN = "connectivity_score"
SEQUENCE_LENGTH = 8
TEST_RATIO = 0.20
RANDOM_STATE = 42
MIN_TRAINING_SAMPLES_FOR_TUNING = 30


class BenchmarkDataError(ValueError):
    """Raised when the local history database cannot support evaluation."""


def load_complete_records(
    db_path: Path | str = DEFAULT_DB_PATH,
) -> tuple[list[dict[str, Any]], int]:
    """Load complete, finite, in-range records in deterministic time order.

    Returns (complete_records, total_rows_read). Incomplete, non-numeric,
    non-finite, or out-of-range measurements are excluded rather than
    silently imputed. The database ID breaks timestamp ties consistently.
    """

    path = Path(db_path)
    if not path.is_file():
        raise FileNotFoundError(f"Network history database not found: {path}")

    columns = ", ".join(("timestamp",) + FEATURE_COLUMNS)
    try:
        with sqlite3.connect(path) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                f"SELECT {columns} FROM network_tests ORDER BY timestamp ASC, id ASC"
            ).fetchall()
    except sqlite3.Error as exc:
        raise BenchmarkDataError(
            "Could not read network_tests from the SQLite database. "
            "Check that the database has the expected project schema."
        ) from exc

    records: list[dict[str, Any]] = []
    for row in rows:
        timestamp = row["timestamp"]
        raw_values = [row[column] for column in FEATURE_COLUMNS]
        if timestamp is None or any(value is None for value in raw_values):
            continue

        try:
            values = np.asarray([float(value) for value in raw_values], dtype=float)
        except (TypeError, ValueError, OverflowError):
            continue

        if not np.isfinite(values).all():
            continue

        # Apply the same measurement bounds used by the production pipeline.
        if not is_valid_measurement_row(values):
            continue

        records.append({"timestamp": str(timestamp), "values": values})

    return records, len(rows)


def build_supervised_samples(
    records: list[dict[str, Any]],
    sequence_length: int = SEQUENCE_LENGTH,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Build next-record targets from the immediately preceding observations."""

    if sequence_length < 1:
        raise ValueError("sequence_length must be at least 1")
    if len(records) <= sequence_length:
        raise BenchmarkDataError(
            f"Need at least {sequence_length + 1} complete records; "
            f"found {len(records)}."
        )

    values = np.vstack([record["values"] for record in records]).astype(float)
    target_index = FEATURE_COLUMNS.index(TARGET_COLUMN)

    features: list[np.ndarray] = []
    targets: list[float] = []
    target_indices: list[int] = []

    for index in range(sequence_length, len(values)):
        history = values[index - sequence_length:index]
        features.append(history.reshape(-1))
        targets.append(float(values[index, target_index]))
        target_indices.append(index)

    return (
        np.vstack(features),
        np.asarray(targets, dtype=float),
        np.asarray(target_indices, dtype=int),
    )


def build_engineered_features(records: list[dict[str, Any]]) -> np.ndarray:
    """Create causal temporal summaries for every next-record prediction.

    All features for target t are derived only from records before t.
    The feature layout mirrors the repository's previous feature-engineering
    experiment while keeping construction in one testable implementation.
    """

    values = np.vstack([record["values"] for record in records]).astype(float)
    target_index = FEATURE_COLUMNS.index(TARGET_COLUMN)
    engineered: list[np.ndarray] = []

    for index in range(SEQUENCE_LENGTH, len(values)):
        window = values[index - SEQUENCE_LENGTH:index]
        short_window = window[-3:]
        score_differences = np.diff(window[:, target_index])

        score_change_mean = float(np.mean(score_differences))
        score_change_std = float(np.std(score_differences))
        score_last_change = float(score_differences[-1])

        engineered.append(
            np.concatenate(
                [
                    window[-1],
                    np.mean(window, axis=0),
                    np.std(window, axis=0),
                    window[-1] - window[0],
                    np.mean(short_window, axis=0),
                    short_window[-1] - short_window[0],
                    np.asarray(
                        [score_change_mean, score_change_std, score_last_change],
                        dtype=float,
                    ),
                ]
            )
        )

    return np.vstack(engineered)


def chronological_split(
    record_count: int,
    target_indices: np.ndarray,
    test_ratio: float = TEST_RATIO,
) -> tuple[int, np.ndarray, np.ndarray]:
    """Split by target-record position, never by random row shuffling."""

    if not 0.0 < test_ratio < 1.0:
        raise ValueError("test_ratio must be between 0 and 1")

    split_index = int(record_count * (1.0 - test_ratio))
    train_mask = target_indices < split_index
    test_mask = target_indices >= split_index

    if not np.any(train_mask):
        raise BenchmarkDataError("The chronological training split has no samples.")
    if not np.any(test_mask):
        raise BenchmarkDataError("The chronological test split has no samples.")

    return split_index, train_mask, test_mask


def calculate_metrics(actual: np.ndarray, predicted: np.ndarray) -> dict[str, float | None]:
    """Return regression metrics; R² is undefined for a single/constant target."""

    y_true = np.asarray(actual, dtype=float)
    y_pred = np.asarray(predicted, dtype=float)
    if y_true.ndim != 1 or y_pred.ndim != 1 or len(y_true) != len(y_pred):
        raise ValueError("actual and predicted must be one-dimensional arrays of equal length")
    if len(y_true) == 0:
        raise ValueError("metrics require at least one test sample")
    if not np.isfinite(y_true).all() or not np.isfinite(y_pred).all():
        raise ValueError("metrics cannot be calculated from non-finite values")

    r2: float | None = None
    if len(y_true) >= 2 and float(np.var(y_true)) > 1e-12:
        r2 = float(r2_score(y_true, y_pred))

    return {
        "mae": float(mean_absolute_error(y_true, y_pred)),
        "rmse": float(np.sqrt(mean_squared_error(y_true, y_pred))),
        "r2": r2,
    }


def _engineered_model() -> HistGradientBoostingRegressor:
    return HistGradientBoostingRegressor(
        max_iter=400,
        learning_rate=0.04,
        max_leaf_nodes=12,
        min_samples_leaf=4,
        l2_regularization=0.5,
        random_state=RANDOM_STATE,
    )


def _current_model() -> HistGradientBoostingRegressor:
    """Build the exact HistGradientBoosting configuration used in production."""
    return build_production_prediction_model()


def tune_hist_gradient_boosting(
    features: np.ndarray,
    targets: np.ndarray,
) -> dict[str, Any]:
    """Tune HGB using chronological CV on training data only.

    Tuning is deliberately skipped for small datasets. The final test split is
    never passed to this function.
    """

    if len(targets) < MIN_TRAINING_SAMPLES_FOR_TUNING:
        return {
            "status": "skipped_insufficient_training_samples",
            "minimum_training_samples": MIN_TRAINING_SAMPLES_FOR_TUNING,
            "available_training_samples": int(len(targets)),
            "best_params": None,
        }

    splitter = TimeSeriesSplit(n_splits=3)
    configurations = [
        {
            "max_iter": iterations,
            "learning_rate": rate,
            "max_leaf_nodes": leaves,
            "min_samples_leaf": leaf_size,
        }
        for iterations in (100, 250)
        for rate in (0.03, 0.05)
        for leaves in (7, 15)
        for leaf_size in (2, 5)
    ]

    best_params: dict[str, int | float] | None = None
    best_mae = float("inf")

    for params in configurations:
        fold_errors: list[float] = []
        for train_indices, validation_indices in splitter.split(features):
            if len(train_indices) < 2 or len(validation_indices) == 0:
                continue
            model = HistGradientBoostingRegressor(
                **params,
                l2_regularization=0.1,
                random_state=RANDOM_STATE,
            )
            model.fit(features[train_indices], targets[train_indices])
            predictions = constrain_connectivity_predictions(
                model.predict(features[validation_indices])
            )
            fold_errors.append(
                float(mean_absolute_error(targets[validation_indices], predictions))
            )

        if fold_errors:
            mean_error = float(np.mean(fold_errors))
            if mean_error < best_mae:
                best_mae = mean_error
                best_params = dict(params)

    if best_params is None:
        return {
            "status": "skipped_no_valid_temporal_folds",
            "minimum_training_samples": MIN_TRAINING_SAMPLES_FOR_TUNING,
            "available_training_samples": int(len(targets)),
            "best_params": None,
        }

    return {
        "status": "completed",
        "validation": "3-fold expanding TimeSeriesSplit on training samples only",
        "best_validation_mae": best_mae,
        "best_params": best_params,
    }


def run_benchmark(
    db_path: Path | str = DEFAULT_DB_PATH,
    test_ratio: float = TEST_RATIO,
) -> dict[str, Any]:
    """Run all candidate models against the same chronological test targets."""

    records, total_rows = load_complete_records(db_path)
    X, y, target_indices = build_supervised_samples(records)
    engineered_X = build_engineered_features(records)
    split_index, train_mask, test_mask = chronological_split(
        len(records), target_indices, test_ratio
    )

    X_train, X_test = X[train_mask], X[test_mask]
    y_train, y_test = y[train_mask], y[test_mask]
    engineered_train, engineered_test = engineered_X[train_mask], engineered_X[test_mask]
    test_target_indices = target_indices[test_mask]

    # One-step-ahead persistence: at each test timestamp, the immediately
    # preceding observed connectivity score is available to the predictor.
    score_index = FEATURE_COLUMNS.index(TARGET_COLUMN)
    raw_values = np.vstack([record["values"] for record in records])
    previous_predictions = constrain_connectivity_predictions(
        raw_values[test_target_indices - 1, score_index]
    )
    mean_predictions = constrain_connectivity_predictions(
        np.full(len(y_test), float(np.mean(y_train)))
    )

    results: dict[str, Any] = {
        "previous_value": {
            **calculate_metrics(y_test, previous_predictions),
            "training_samples": int(len(y_train)),
            "test_samples": int(len(y_test)),
            "fit_seconds": 0.0,
        },
        "training_mean": {
            **calculate_metrics(y_test, mean_predictions),
            "training_samples": int(len(y_train)),
            "test_samples": int(len(y_test)),
            "fit_seconds": 0.0,
        },
    }

    candidates: list[tuple[str, Any, np.ndarray, np.ndarray]] = [
        (
            "linear_regression",
            Pipeline([("scaler", StandardScaler()), ("model", LinearRegression())]),
            X_train,
            X_test,
        ),
        (
            "random_forest",
            RandomForestRegressor(
                n_estimators=200,
                max_depth=8,
                min_samples_leaf=2,
                random_state=RANDOM_STATE,
                n_jobs=-1,
            ),
            X_train,
            X_test,
        ),
        ("hist_gradient_boosting_current", _current_model(), X_train, X_test),
        (
            "hist_gradient_boosting_engineered",
            _engineered_model(),
            engineered_train,
            engineered_test,
        ),
    ]

    for name, model, train_features, test_features in candidates:
        start = time.perf_counter()
        model.fit(train_features, y_train)
        predictions = constrain_connectivity_predictions(
            model.predict(test_features)
        )
        elapsed = time.perf_counter() - start
        results[name] = {
            **calculate_metrics(y_test, predictions),
            "training_samples": int(len(y_train)),
            "test_samples": int(len(y_test)),
            "fit_and_predict_seconds": float(elapsed),
        }
        if name == "hist_gradient_boosting_current":
            results[name]["matches_production_configuration"] = True

    tuning = tune_hist_gradient_boosting(X_train, y_train)
    if tuning.get("status") == "completed":
        tuned_model = HistGradientBoostingRegressor(
            **tuning["best_params"],
            l2_regularization=0.1,
            random_state=RANDOM_STATE,
        )
        start = time.perf_counter()
        tuned_model.fit(X_train, y_train)
        tuned_predictions = constrain_connectivity_predictions(
            tuned_model.predict(X_test)
        )
        elapsed = time.perf_counter() - start
        results["hist_gradient_boosting_tuned"] = {
            **calculate_metrics(y_test, tuned_predictions),
            "training_samples": int(len(y_train)),
            "test_samples": int(len(y_test)),
            "fit_and_predict_seconds": float(elapsed),
            "best_params": tuning["best_params"],
        }

    winner = min(results, key=lambda name: results[name]["rmse"])
    training_sample_count = int(np.sum(train_mask))
    low_data_warning = len(records) < 50 or training_sample_count < 30 or len(y_test) < 10

    return {
        "benchmark": "Connectivity score prediction",
        "protocol": {
            "evaluation": "chronological holdout with rolling one-step-ahead inputs",
            "test_ratio": test_ratio,
            "sequence_length": SEQUENCE_LENGTH,
            "target": "connectivity_score at the next record",
            "input_features": list(FEATURE_COLUMNS),
            "feature_rule": (
                "Each prediction uses only the immediately preceding eight "
                "complete records."
            ),
            "test_input_rule": (
                "Earlier observed records in the test period may be used as "
                "history for later one-step-ahead predictions."
            ),
            "preprocessing_rule": (
                "Incomplete, non-numeric, non-finite, and out-of-range records "
                "are excluded; no values are imputed."
            ),
            "record_order": "timestamp ascending, then SQLite record ID ascending",
            "prediction_bounds": [CONNECTIVITY_SCORE_MIN, CONNECTIVITY_SCORE_MAX],
            "production_model": {
                "name": "HistGradientBoostingRegressor",
                "parameters": PRODUCTION_HIST_GRADIENT_BOOSTING_PARAMS,
                "evaluation": (
                    "Evaluated with the same chronological holdout as all "
                    "baselines and candidates."
                ),
            },
            "shuffle": False,
            "random_state": RANDOM_STATE,
        },
        "dataset": {
            "database_name": Path(db_path).name,
            "total_rows": int(total_rows),
            "complete_records": int(len(records)),
            "excluded_records": int(total_rows - len(records)),
            "training_records_before_windowing": int(split_index),
            "test_records": int(len(records) - split_index),
            "training_samples": training_sample_count,
            "test_samples": int(len(y_test)),
        },
        "models": results,
        "best_by_rmse": winner,
        "tuning": tuning,
        "data_sufficiency": {
            "status": (
                "preliminary_small_sample"
                if low_data_warning
                else "adequate_for_initial_comparison"
            ),
            "warning": (
                "Results are preliminary: the dataset or held-out sample is small. "
                "Collect more real observations before making a "
                "model-selection or improvement claim."
                if low_data_warning
                else None
            ),
            "deep_learning_note": (
                "Transformer/TCN training is not included in this classical-model benchmark. "
                "The existing AI engine requires at least 50 complete records, and deep models "
                "should be evaluated only with a larger chronological training set."
            ),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database",
        type=Path,
        default=DEFAULT_DB_PATH,
        help="Path to the local network_history.db (default: repository root).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_RESULTS_PATH,
        help="Where to write aggregate benchmark results.",
    )
    parser.add_argument(
        "--test-ratio",
        type=float,
        default=TEST_RATIO,
        help="Chronological test fraction (default: 0.20).",
    )
    args = parser.parse_args()

    report = run_benchmark(args.database, args.test_ratio)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("=" * 68)
    print("SMART CONNECTIVITY ANALYSER — MODEL BENCHMARK")
    print("=" * 68)
    print(
        f"Complete records: {report['dataset']['complete_records']} "
        f"(excluded: {report['dataset']['excluded_records']})"
    )
    print(
        f"Training samples: {report['dataset']['training_samples']} | "
        f"Test samples: {report['dataset']['test_samples']}"
    )
    print()
    print(f"{'MODEL':42} {'MAE':>9} {'RMSE':>9} {'R²':>9}")
    print("-" * 72)
    for name, metrics in sorted(report["models"].items(), key=lambda item: item[1]["rmse"]):
        r2 = "N/A" if metrics["r2"] is None else f"{metrics['r2']:.4f}"
        print(f"{name:42} {metrics['mae']:9.4f} {metrics['rmse']:9.4f} {r2:>9}")

    print()
    print(f"Best by RMSE on this test split: {report['best_by_rmse']}")
    print(f"Tuning: {report['tuning']['status']}")
    if report["data_sufficiency"]["warning"]:
        print(f"WARNING: {report['data_sufficiency']['warning']}")
    print(f"Results saved to: {args.output}")


if __name__ == "__main__":
    main()
