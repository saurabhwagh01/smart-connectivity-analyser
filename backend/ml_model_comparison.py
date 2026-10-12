"""
Smart Connectivity Analyser
Classical ML Model Comparison

Uses the same chronological 80/20 split as the AI evaluation.

Models:
1. Previous Value baseline
2. Training Mean baseline
3. Linear Regression
4. Random Forest Regressor
5. HistGradientBoosting Regressor

The script:
- reads the root network_history.db
- skips incomplete/NULL records
- uses only complete finite records
- does not modify the database
- does not modify existing AI models
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


# ============================================================
# PATHS AND SETTINGS
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "network_history.db"
RESULTS_PATH = Path(__file__).resolve().parent / "ml_model_comparison_results.json"

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


# ============================================================
# LOAD DATA
# ============================================================

def load_complete_data() -> list[dict]:
    """
    Load complete finite records from SQLite in chronological order.

    Any record containing NULL or non-numeric values is skipped.
    This matches the data-cleaning approach used by the AI evaluation.
    """

    if not DB_PATH.exists():
        raise FileNotFoundError(
            f"Database not found: {DB_PATH}"
        )

    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row

    try:
        columns = ", ".join(FEATURES)

        rows = connection.execute(
            f"""
            SELECT {columns}
            FROM network_tests
            ORDER BY timestamp ASC
            """
        ).fetchall()

    finally:
        connection.close()

    data = []

    for row in rows:

        # Get raw values first so NULL can be detected safely.
        raw_values = [
            row[column]
            for column in FEATURES
        ]

        # Skip incomplete records.
        if any(value is None for value in raw_values):
            continue

        # Convert values to float safely.
        try:
            values = [
                float(value)
                for value in raw_values
            ]

        except (TypeError, ValueError):
            continue

        # Skip NaN or infinity.
        if not all(np.isfinite(values)):
            continue

        data.append({
            "values": values
        })

    return data


# ============================================================
# TRAIN / TEST SPLIT
# ============================================================

def split_data(data: list[dict]):
    """
    Chronological 80/20 split.

    No random shuffling is used because this is time-series data.
    """

    split_index = int(
        len(data) * (1.0 - TEST_RATIO)
    )

    if split_index <= SEQUENCE_LENGTH:
        raise ValueError(
            f"Not enough training records. "
            f"Need more than {SEQUENCE_LENGTH} records."
        )

    train_data = data[:split_index]
    test_data = data[split_index:]

    return train_data, test_data, split_index


# ============================================================
# METRICS
# ============================================================

def calculate_metrics(y_true, y_pred):
    """Calculate MAE, RMSE and R²."""

    y_true = np.asarray(
        y_true,
        dtype=float
    )

    y_pred = np.asarray(
        y_pred,
        dtype=float
    )

    return {
        "mae": float(
            mean_absolute_error(
                y_true,
                y_pred
            )
        ),

        "rmse": float(
            np.sqrt(
                mean_squared_error(
                    y_true,
                    y_pred
                )
            )
        ),

        "r2": float(
            r2_score(
                y_true,
                y_pred
            )
        ),
    }


# ============================================================
# CREATE SUPERVISED DATASET
# ============================================================

def build_tabular_dataset(data: list[dict]):
    """
    Convert time-series data into supervised samples.

    Each sample uses the previous 8 records.

    Input:
        8 records × 6 features

    Target:
        connectivity score of the next record
    """

    values = np.asarray(
        [
            item["values"]
            for item in data
        ],
        dtype=float
    )

    score_index = FEATURES.index(
        "connectivity_score"
    )

    X = []
    y = []

    for index in range(
        SEQUENCE_LENGTH,
        len(values)
    ):

        window = values[
            index - SEQUENCE_LENGTH:index
        ]

        # Flatten:
        # 8 records × 6 features
        # becomes 48 ML features.
        X.append(
            window.reshape(-1)
        )

        y.append(
            values[
                index,
                score_index
            ]
        )

    return (
        np.asarray(X, dtype=float),
        np.asarray(y, dtype=float)
    )


# ============================================================
# CLASSICAL ML MODEL EVALUATION
# ============================================================

def evaluate_tabular_model(
    model,
    all_data,
    split_index
):
    """
    Train on samples whose target is inside the training period.

    Test only on samples whose target occurs after the
    chronological train/test split.
    """

    X, y = build_tabular_dataset(
        all_data
    )

    # Each generated sample predicts:
    # original record index = SEQUENCE_LENGTH + row
    target_indices = np.arange(
        SEQUENCE_LENGTH,
        len(all_data)
    )

    train_mask = (
        target_indices < split_index
    )

    test_mask = (
        target_indices >= split_index
    )

    X_train = X[train_mask]
    y_train = y[train_mask]

    X_test = X[test_mask]
    y_test = y[test_mask]

    if len(X_train) == 0:
        raise ValueError(
            "No training samples were created."
        )

    if len(X_test) == 0:
        raise ValueError(
            "No test samples were created."
        )

    model.fit(
        X_train,
        y_train
    )

    predictions = model.predict(
        X_test
    )

    result = calculate_metrics(
        y_test,
        predictions
    )

    return (
        result,
        y_test,
        predictions
    )


# ============================================================
# PREVIOUS VALUE BASELINE
# ============================================================

def previous_value_baseline(
    data,
    split_index
):
    """
    Predict the next connectivity score using
    the immediately previous connectivity score.
    """

    score_index = FEATURES.index(
        "connectivity_score"
    )

    y_true = []
    y_pred = []

    for index in range(
        split_index,
        len(data)
    ):

        y_true.append(
            data[index]["values"][
                score_index
            ]
        )

        y_pred.append(
            data[index - 1]["values"][
                score_index
            ]
        )

    return calculate_metrics(
        y_true,
        y_pred
    )


# ============================================================
# TRAINING MEAN BASELINE
# ============================================================

def training_mean_baseline(
    data,
    split_index
):
    """
    Predict every test score using the mean
    connectivity score from the training data.
    """

    score_index = FEATURES.index(
        "connectivity_score"
    )

    train_scores = [
        row["values"][score_index]
        for row in data[:split_index]
    ]

    test_scores = [
        row["values"][score_index]
        for row in data[split_index:]
    ]

    mean_score = float(
        np.mean(train_scores)
    )

    predictions = [
        mean_score
        for _ in test_scores
    ]

    result = calculate_metrics(
        test_scores,
        predictions
    )

    result["mean_score"] = mean_score

    return result


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 60)
    print(
        "SMART CONNECTIVITY ANALYSER - "
        "ML MODEL COMPARISON"
    )
    print("=" * 60)

    # --------------------------------------------------------
    # Load data
    # --------------------------------------------------------

    data = load_complete_data()

    train_data, test_data, split_index = split_data(
        data
    )

    print(
        f"Complete records: {len(data)}"
    )

    print(
        f"Training records: {len(train_data)}"
    )

    print(
        f"Unseen test records: {len(test_data)}"
    )

    print()

    results = {}

    # --------------------------------------------------------
    # Baseline 1
    # --------------------------------------------------------

    print(
        "BASELINE 1 — PREVIOUS VALUE"
    )

    print("-" * 60)

    previous_result = previous_value_baseline(
        data,
        split_index
    )

    results["previous_value"] = previous_result

    print(
        f"MAE:  {previous_result['mae']:.4f}"
    )

    print(
        f"RMSE: {previous_result['rmse']:.4f}"
    )

    print(
        f"R2:   {previous_result['r2']:.4f}"
    )

    print()

    # --------------------------------------------------------
    # Baseline 2
    # --------------------------------------------------------

    print(
        "BASELINE 2 — TRAINING MEAN"
    )

    print("-" * 60)

    mean_result = training_mean_baseline(
        data,
        split_index
    )

    results["training_mean"] = mean_result

    print(
        f"Mean score: "
        f"{mean_result['mean_score']:.4f}"
    )

    print(
        f"MAE:  {mean_result['mae']:.4f}"
    )

    print(
        f"RMSE: {mean_result['rmse']:.4f}"
    )

    print(
        f"R2:   {mean_result['r2']:.4f}"
    )

    print()

    # --------------------------------------------------------
    # Classical ML models
    # --------------------------------------------------------

    models = {

        "linear_regression":
            Pipeline(
                [
                    (
                        "scaler",
                        StandardScaler()
                    ),
                    (
                        "model",
                        LinearRegression()
                    ),
                ]
            ),

        "random_forest":
            RandomForestRegressor(
                n_estimators=300,
                max_depth=8,
                min_samples_leaf=2,
                random_state=RANDOM_STATE,
                n_jobs=-1,
            ),

        "hist_gradient_boosting":
            HistGradientBoostingRegressor(
                max_iter=300,
                learning_rate=0.05,
                max_leaf_nodes=15,
                l2_regularization=0.1,
                random_state=RANDOM_STATE,
            ),
    }

    # --------------------------------------------------------
    # Run each model
    # --------------------------------------------------------

    for name, model in models.items():

        display_names = {
            "linear_regression":
                "LINEAR REGRESSION",

            "random_forest":
                "RANDOM FOREST",

            "hist_gradient_boosting":
                "HISTGRADIENTBOOSTING",
        }

        print(
            display_names[name]
        )

        print("-" * 60)

        result, _, _ = evaluate_tabular_model(
            model,
            data,
            split_index
        )

        results[name] = result

        print(
            f"MAE:  {result['mae']:.4f}"
        )

        print(
            f"RMSE: {result['rmse']:.4f}"
        )

        print(
            f"R2:   {result['r2']:.4f}"
        )

        print()

    # --------------------------------------------------------
    # Find best model
    # --------------------------------------------------------

    best_name = min(
        results,
        key=lambda name:
            results[name]["rmse"]
    )

    best_result = results[
        best_name
    ]

    print("=" * 60)

    print(
        f"BEST BY RMSE: {best_name}"
    )

    print(
        f"MAE: {best_result['mae']:.4f} | "
        f"RMSE: {best_result['rmse']:.4f} | "
        f"R2: {best_result['r2']:.4f}"
    )

    print("=" * 60)

    # --------------------------------------------------------
    # Save results
    # --------------------------------------------------------

    output = {

        "dataset": {

            "database": str(
                DB_PATH
            ),

            "complete_records":
                len(data),

            "training_records":
                len(train_data),

            "unseen_test_records":
                len(test_data),

            "test_ratio":
                TEST_RATIO,

            "sequence_length":
                SEQUENCE_LENGTH,

            "features":
                FEATURES,
        },

        "results":
            results,

        "best_by_rmse":
            best_name,
    }

    RESULTS_PATH.write_text(
        json.dumps(
            output,
            indent=2
        ),
        encoding="utf-8"
    )

    print()

    print(
        f"Results saved to: "
        f"{RESULTS_PATH}"
    )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()
