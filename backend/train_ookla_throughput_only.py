
import json
from pathlib import Path

import duckdb
import numpy as np
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import train_test_split


# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent

CSV_PATH = ROOT / "datasets" / "ookla_mobile_sample.csv"

OUTPUT_PATH = (
    ROOT / "backend" / "ookla_throughput_only_results.json"
)

RANDOM_STATE = 42
SAMPLE_SIZE = 50000

FEATURES = [
    "download_mbps",
    "upload_mbps",
    "tests",
    "devices",
]

TARGET = "latency_ms"


# --------------------------------------------------
# METRICS
# --------------------------------------------------

def calculate_metrics(actual, predicted):
    """Calculate regression evaluation metrics."""

    return {
        "mae_ms": round(
            float(mean_absolute_error(actual, predicted)), 4
        ),
        "rmse_ms": round(
            float(np.sqrt(mean_squared_error(actual, predicted))), 4
        ),
        "r2": round(float(r2_score(actual, predicted)), 4),
    }


# --------------------------------------------------
# MAIN EXPERIMENT
# --------------------------------------------------

def main():

    if not CSV_PATH.exists():
        raise FileNotFoundError(
            f"Dataset not found: {CSV_PATH}"
        )

    print("=" * 55)
    print("OOKLA THROUGHPUT-ONLY LATENCY EXPERIMENT")
    print("=" * 55)

    connection = duckdb.connect()

    try:
        total_rows = connection.execute(
            """
            SELECT COUNT(*)
            FROM read_csv_auto(?)
            """,
            [str(CSV_PATH)],
        ).fetchone()[0]

        # Filter records before sampling.
        # fetchall() avoids the pandas dependency.
        query = """
            SELECT
                download_mbps,
                upload_mbps,
                tests,
                devices,
                latency_ms
            FROM read_csv_auto(?)
            WHERE download_mbps > 0
              AND upload_mbps > 0
              AND latency_ms > 0
              AND tests > 0
              AND devices > 0
            USING SAMPLE reservoir(50000 ROWS)
            REPEATABLE (42)
        """

        rows = connection.execute(
            query,
            [str(CSV_PATH)],
        ).fetchall()

    finally:
        connection.close()

    if not rows:
        raise ValueError(
            "No valid records were found in the dataset."
        )

    # Convert the records into a NumPy array.
    data = np.asarray(rows, dtype=float)

    # First four columns are features; last is the target.
    X = data[:, :4]
    y = data[:, 4]

    print(f"Rows in prepared CSV: {total_rows}")
    print(f"Rows sampled: {len(rows)}")

    # --------------------------------------------------
    # TRAIN-TEST SPLIT
    # --------------------------------------------------

    X_train, X_test, y_train, y_test = train_test_split(
        X,
        y,
        test_size=0.20,
        random_state=RANDOM_STATE,
    )

    print(f"Training rows: {len(X_train)}")
    print(f"Test rows: {len(X_test)}")

    # --------------------------------------------------
    # BASELINE MODEL
    # --------------------------------------------------

    baseline_prediction = np.full(
        len(y_test),
        float(np.mean(y_train)),
    )

    baseline_metrics = calculate_metrics(
        y_test,
        baseline_prediction,
    )

    # --------------------------------------------------
    # RANDOM FOREST MODEL
    # --------------------------------------------------

    model = RandomForestRegressor(
        n_estimators=150,
        max_depth=16,
        min_samples_leaf=5,
        random_state=RANDOM_STATE,
        n_jobs=-1,
    )

    print("\nTraining Random Forest...")
    model.fit(X_train, y_train)

    predictions = model.predict(X_test)

    model_metrics = calculate_metrics(
        y_test,
        predictions,
    )

    # --------------------------------------------------
    # FEATURE IMPORTANCE
    # --------------------------------------------------

    feature_importance = {
        feature: round(float(importance), 6)
        for feature, importance in zip(
            FEATURES,
            model.feature_importances_,
        )
    }

    # --------------------------------------------------
    # SAVE RESULTS
    # --------------------------------------------------

    results = {
        "experiment": (
            "Ookla throughput-only latency prediction"
        ),
        "target": TARGET,
        "features": FEATURES,
        "dataset_rows": int(total_rows),
        "sample_rows": int(len(rows)),
        "training_rows": int(len(X_train)),
        "test_rows": int(len(X_test)),
        "baseline": baseline_metrics,
        "random_forest": model_metrics,
        "feature_importance": feature_importance,
        "limitations": [
            (
                "The dataset contains aggregated geographic tiles, "
                "not individual network sessions."
            ),
            (
                "Random train-test splitting does not establish "
                "generalization to new locations or time periods."
            ),
            (
                "R2 measures the variation explained on the test set."
            ),
            (
                "Feature importance is not evidence of causation."
            ),
            (
                "This experiment does not modify production models "
                "or the production database."
            ),
        ],
    }

    OUTPUT_PATH.write_text(
        json.dumps(results, indent=2),
        encoding="utf-8",
    )

    # --------------------------------------------------
    # DISPLAY RESULTS
    # --------------------------------------------------

    print("\n" + "=" * 45)
    print("TRAINING-MEAN BASELINE")
    print("=" * 45)
    print(f"MAE:  {baseline_metrics['mae_ms']} ms")
    print(f"RMSE: {baseline_metrics['rmse_ms']} ms")
    print(f"R2:   {baseline_metrics['r2']}")

    print("\n" + "=" * 45)
    print("RANDOM FOREST")
    print("=" * 45)
    print(f"MAE:  {model_metrics['mae_ms']} ms")
    print(f"RMSE: {model_metrics['rmse_ms']} ms")
    print(f"R2:   {model_metrics['r2']}")

    print("\nFEATURE IMPORTANCE")
    for feature, importance in feature_importance.items():
        print(f"{feature}: {importance}")

    print(f"\nResults saved to:\n{OUTPUT_PATH}")
    print("\nProduction database and models were not modified.")


if __name__ == "__main__":
    main()
