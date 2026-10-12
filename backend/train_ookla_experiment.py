
"""
Smart Connectivity Analyser
Public Ookla Dataset Experiment

Target: average network latency (ms)
Models: training-mean baseline and Random Forest

This experiment does not modify production models or the database.
"""

import json
from pathlib import Path

import duckdb
import numpy as np
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

BASE_DIR = Path(__file__).resolve().parent.parent
CSV_PATH = BASE_DIR / "datasets" / "ookla_mobile_sample.csv"
RESULT_PATH = BASE_DIR / "backend" / "ookla_experiment_results.json"

SAMPLE_SIZE = 50_000
RANDOM_STATE = 42

FEATURES = [
    "download_mbps",
    "upload_mbps",
    "download_latency_ms",
    "upload_latency_ms",
    "tests",
    "devices",
]
TARGET = "latency_ms"


def main():
    if not CSV_PATH.exists():
        raise FileNotFoundError(f"Prepared CSV not found: {CSV_PATH}")

    con = duckdb.connect(":memory:")
    csv_path = str(CSV_PATH).replace("\\", "/").replace("'", "''")

    total_rows = con.execute(
        f"SELECT COUNT(*) FROM read_csv_auto('{csv_path}')"
    ).fetchone()[0]

    # Reproducible random sample, limited to reduce memory use.
    data = con.execute(
        f"""
        SELECT {", ".join(FEATURES)}, {TARGET}
        FROM read_csv_auto('{csv_path}')
        WHERE {TARGET} > 0
          AND download_mbps > 0
          AND upload_mbps > 0
          AND download_latency_ms > 0
          AND upload_latency_ms > 0
          AND tests > 0
          AND devices > 0
        USING SAMPLE reservoir({SAMPLE_SIZE} ROWS) REPEATABLE ({RANDOM_STATE})
        """
    ).fetchall()

    con.close()

    if len(data) < 100:
        raise ValueError(
            f"Only {len(data)} usable rows were sampled; at least 100 are required."
        )

    values = np.asarray(data, dtype=float)
    X = values[:, :len(FEATURES)]
    y = values[:, len(FEATURES)]

    # Hold out 20% of the sampled rows.
    # This is a random holdout, not a chronological forecast evaluation.
    rng = np.random.default_rng(RANDOM_STATE)
    indices = rng.permutation(len(y))
    split = int(len(y) * 0.8)

    train_idx = indices[:split]
    test_idx = indices[split:]

    X_train, X_test = X[train_idx], X[test_idx]
    y_train, y_test = y[train_idx], y[test_idx]

    # Baseline: predict the mean latency in the training sample.
    baseline_predictions = np.full(
        len(y_test), float(np.mean(y_train))
    )

    model = RandomForestRegressor(
        n_estimators=150,
        max_depth=16,
        min_samples_leaf=5,
        random_state=RANDOM_STATE,
        n_jobs=-1,
    )
    model.fit(X_train, y_train)
    rf_predictions = model.predict(X_test)

    def calculate_metrics(actual, predicted):
        return {
            "mae_ms": round(float(mean_absolute_error(actual, predicted)), 4),
            "rmse_ms": round(
                float(np.sqrt(mean_squared_error(actual, predicted))), 4
            ),
            "r2": round(float(r2_score(actual, predicted)), 4),
        }

    results = {
        "dataset": "Ookla aggregated mobile network data",
        "source_rows_in_csv": int(total_rows),
        "sample_rows": int(len(y)),
        "training_rows": int(len(train_idx)),
        "test_rows": int(len(test_idx)),
        "target": TARGET,
        "target_unit": "milliseconds",
        "features": FEATURES,
        "baseline": calculate_metrics(y_test, baseline_predictions),
        "random_forest": calculate_metrics(y_test, rf_predictions),
        "feature_importance": {
            name: round(float(value), 6)
            for name, value in zip(FEATURES, model.feature_importances_)
        },
        "note": (
            "Random 80/20 holdout on aggregated geographic records. "
            "This is an exploratory experiment, not a time-series forecast. "
            "Latency features may be closely related to the target, so "
            "performance should not be interpreted as proof of future prediction."
        ),
    }

    RESULT_PATH.write_text(
        json.dumps(results, indent=2),
        encoding="utf-8",
    )

    print("=" * 60)
    print("OOKLA LATENCY PREDICTION EXPERIMENT")
    print("=" * 60)
    print(f"Rows in prepared CSV: {total_rows}")
    print(f"Rows sampled: {len(y)}")
    print(f"Training rows: {len(train_idx)}")
    print(f"Test rows: {len(test_idx)}")
    print("\nTraining-mean baseline:", results["baseline"])
    print("Random Forest:", results["random_forest"])
    print("\nFeature importance:")
    for name, value in results["feature_importance"].items():
        print(f"  {name}: {value}")
    print(f"\nResults saved to: {RESULT_PATH}")
    print("Production database and models were not modified.")


if __name__ == "__main__":
    main()
