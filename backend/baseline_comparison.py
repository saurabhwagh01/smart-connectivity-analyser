"""
Smart Internet Connectivity Analyser
Baseline Comparison

Compares simple forecasting baselines against the current
Transformer + TCN evaluation using the same chronological
80/20 holdout.

Run from project root:
    python backend/baseline_comparison.py
"""

from pathlib import Path
import sqlite3
import math
import json

import torch
import torch.nn as nn

from ai_engine import (
    FEATURES,
    SEQUENCE_LENGTH,
    ConnectivityPredictor,
)

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "network_history.db"
RESULT_PATH = BASE_DIR / "backend" / "baseline_comparison_results.json"

TRAIN_RATIO = 0.80
SEED = 42


def load_complete_data():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row

    try:
        rows = connection.execute(
            """
            SELECT timestamp, download_mbps, upload_mbps,
                   ping_ms, jitter_ms, packet_loss,
                   connectivity_score
            FROM network_tests
            ORDER BY timestamp ASC
            """
        ).fetchall()
    finally:
        connection.close()

    data = []

    for row in rows:
        values = []
        valid = True

        for feature in FEATURES:
            value = row[feature]

            if value is None:
                valid = False
                break

            try:
                value = float(value)
            except (TypeError, ValueError):
                valid = False
                break

            if not math.isfinite(value):
                valid = False
                break

            values.append(value)

        if valid:
            data.append(values)

    return data


def metrics(actuals, predictions):
    absolute_errors = [
        abs(a - p)
        for a, p in zip(actuals, predictions)
    ]

    squared_errors = [
        (a - p) ** 2
        for a, p in zip(actuals, predictions)
    ]

    mae = sum(absolute_errors) / len(actuals)
    rmse = math.sqrt(
        sum(squared_errors) / len(actuals)
    )

    mean_actual = sum(actuals) / len(actuals)

    ss_total = sum(
        (a - mean_actual) ** 2
        for a in actuals
    )

    ss_residual = sum(
        (a - p) ** 2
        for a, p in zip(actuals, predictions)
    )

    r2 = None

    if ss_total > 1e-12:
        r2 = 1 - (
            ss_residual / ss_total
        )

    return {
        "mae": round(mae, 4),
        "rmse": round(rmse, 4),
        "r2": None if r2 is None else round(r2, 4),
    }


def main():
    torch.manual_seed(SEED)

    data = load_complete_data()

    score_index = FEATURES.index(
        "connectivity_score"
    )

    train_count = int(
        len(data) * TRAIN_RATIO
    )

    train_data = data[:train_count]
    test_data = data[train_count:]

    actuals = [
        row[score_index]
        for row in test_data
    ]

    print("=" * 60)
    print("SMART CONNECTIVITY ANALYSER - BASELINE COMPARISON")
    print("=" * 60)

    print(f"Complete records: {len(data)}")
    print(f"Training records: {len(train_data)}")
    print(f"Unseen test records: {len(test_data)}")
    print()

    # ---------------------------------------------------------
    # Baseline 1: previous value
    # ---------------------------------------------------------
    previous_predictions = [
        data[train_count - 1][score_index]
    ]

    for index in range(
        train_count,
        len(data) - 1
    ):
        previous_predictions.append(
            data[index][score_index]
        )

    previous_predictions = previous_predictions[:len(actuals)]

    previous_metrics = metrics(
        actuals,
        previous_predictions
    )

    # ---------------------------------------------------------
    # Baseline 2: training mean
    # ---------------------------------------------------------
    train_scores = [
        row[score_index]
        for row in train_data
    ]

    mean_score = (
        sum(train_scores)
        / len(train_scores)
    )

    mean_predictions = [
        mean_score
        for _ in actuals
    ]

    mean_metrics = metrics(
        actuals,
        mean_predictions
    )

    print("BASELINE 1 — PREVIOUS VALUE")
    print("-" * 60)
    print(f"MAE:  {previous_metrics['mae']}")
    print(f"RMSE: {previous_metrics['rmse']}")
    print(f"R2:   {previous_metrics['r2']}")
    print()

    print("BASELINE 2 — TRAINING MEAN")
    print("-" * 60)
    print(f"Mean score: {mean_score:.4f}")
    print(f"MAE:  {mean_metrics['mae']}")
    print(f"RMSE: {mean_metrics['rmse']}")
    print(f"R2:   {mean_metrics['r2']}")
    print()

    # ---------------------------------------------------------
    # Train a temporary Transformer + TCN using the same
    # chronological 80% training portion.
    # ---------------------------------------------------------
    from evaluate_ai import (
        train_predictor,
        evaluate_predictor,
    )

    print("TRANSFORMER + TCN")
    print("-" * 60)

    # evaluate_ai.py expects records in the form:
    # {"values": [...]}
    train_records = [
        {"values": row}
        for row in train_data
    ]

    all_records = [
        {"values": row}
        for row in data
    ]

    model, scaler, training_loss = train_predictor(
        train_records
    )

    transformer_metrics = evaluate_predictor(
        model,
        scaler,
        all_records,
        train_count
    )

    print(
        f"MAE:  {transformer_metrics['mae']}"
    )
    print(
        f"RMSE: {transformer_metrics['rmse']}"
    )
    print(
        f"R2:   {transformer_metrics['r2']}"
    )

    # ---------------------------------------------------------
    # Determine the best model by RMSE.
    # ---------------------------------------------------------
    candidates = {
        "Previous Value": previous_metrics,
        "Training Mean": mean_metrics,
        "Transformer + TCN": transformer_metrics,
    }

    best_model = min(
        candidates,
        key=lambda name: candidates[name]["rmse"]
    )

    results = {
        "records": len(data),
        "training_records": len(train_data),
        "test_records": len(test_data),
        "models": {
            "Previous Value": previous_metrics,
            "Training Mean": mean_metrics,
            "Transformer + TCN": transformer_metrics,
        },
        "best_by_rmse": best_model,
        "transformer_training_loss": round(
            training_loss,
            6
        ),
    }

    RESULT_PATH.write_text(
        json.dumps(
            results,
            indent=2
        ),
        encoding="utf-8"
    )

    print()
    print("=" * 60)
    print(f"BEST BY RMSE: {best_model}")
    print("=" * 60)
    print(
        f"Results saved to: {RESULT_PATH}"
    )


if __name__ == "__main__":
    main()
