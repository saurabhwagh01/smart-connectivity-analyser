"""
Smart Internet Connectivity Analyser
AI Evaluation Script

Runs a chronological 80/20 holdout evaluation without
overwriting the existing trained models.

Run from the project root:
    python backend/evaluate_ai.py
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
    TransformerAutoencoder,
)

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "network_history.db"
RESULT_PATH = BASE_DIR / "backend" / "ai_evaluation_results.json"

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
            data.append({
                "timestamp": row["timestamp"],
                "values": values
            })

    return data


def calculate_scaler(data):
    values = [item["values"] for item in data]
    means = []
    stds = []

    for index in range(len(FEATURES)):
        column = [row[index] for row in values]
        mean = sum(column) / len(column)

        variance = sum(
            (value - mean) ** 2 for value in column
        ) / len(column)

        std = math.sqrt(variance)

        if std < 1e-8:
            std = 1.0

        means.append(mean)
        stds.append(std)

    return {"mean": means, "std": stds}


def normalize(values, scaler):
    return [
        (value - scaler["mean"][i]) / scaler["std"][i]
        for i, value in enumerate(values)
    ]


def denormalize(value, scaler, feature_index):
    return (
        value * scaler["std"][feature_index]
        + scaler["mean"][feature_index]
    )


def create_sequences(data, scaler):
    normalized = [
        normalize(item["values"], scaler)
        for item in data
    ]

    sequences = []
    targets = []

    for i in range(len(normalized) - SEQUENCE_LENGTH):
        sequences.append(
            normalized[i:i + SEQUENCE_LENGTH]
        )
        targets.append(
            normalized[i + SEQUENCE_LENGTH][-1]
        )

    return sequences, targets


def train_predictor(train_data, epochs=100, learning_rate=0.001):
    scaler = calculate_scaler(train_data)

    sequences, targets = create_sequences(
        train_data, scaler
    )

    if len(sequences) < 10:
        raise RuntimeError(
            "Not enough training sequences."
        )

    x = torch.tensor(
        sequences, dtype=torch.float32
    )
    y = torch.tensor(
        targets, dtype=torch.float32
    )

    torch.manual_seed(SEED)

    model = ConnectivityPredictor()
    optimizer = torch.optim.Adam(
        model.parameters(),
        lr=learning_rate
    )
    loss_function = nn.MSELoss()

    model.train()
    final_loss = None

    for _ in range(epochs):
        optimizer.zero_grad()

        prediction = model(x)

        loss = loss_function(
            prediction, y
        )

        loss.backward()
        optimizer.step()

        final_loss = float(loss.item())

    return model, scaler, final_loss


def evaluate_predictor(
    model,
    scaler,
    all_data,
    train_count
):
    normalized = [
        normalize(item["values"], scaler)
        for item in all_data
    ]

    predictions = []
    actuals = []

    score_index = FEATURES.index(
        "connectivity_score"
    )

    model.eval()

    for i in range(
        len(normalized) - SEQUENCE_LENGTH
    ):
        target_index = i + SEQUENCE_LENGTH

        if target_index < train_count:
            continue

        sequence = torch.tensor(
            [normalized[i:i + SEQUENCE_LENGTH]],
            dtype=torch.float32
        )

        with torch.no_grad():
            prediction = model(
                sequence
            ).item()

        predicted_score = denormalize(
            prediction,
            scaler,
            score_index
        )

        actual_score = all_data[
            target_index
        ]["values"][score_index]

        predictions.append(
            predicted_score
        )
        actuals.append(
            actual_score
        )

    if not predictions:
        raise RuntimeError(
            "No unseen test sequences available."
        )

    absolute_errors = [
        abs(p - a)
        for p, a in zip(predictions, actuals)
    ]

    squared_errors = [
        (p - a) ** 2
        for p, a in zip(predictions, actuals)
    ]

    mae = (
        sum(absolute_errors)
        / len(absolute_errors)
    )

    rmse = math.sqrt(
        sum(squared_errors)
        / len(squared_errors)
    )

    actual_mean = (
        sum(actuals) / len(actuals)
    )

    ss_total = sum(
        (actual - actual_mean) ** 2
        for actual in actuals
    )

    ss_residual = sum(
        (actual - predicted) ** 2
        for actual, predicted
        in zip(actuals, predictions)
    )

    r2 = None

    if ss_total > 1e-12:
        r2 = 1 - (
            ss_residual / ss_total
        )

    return {
        "test_predictions": len(predictions),
        "mae": round(mae, 4),
        "rmse": round(rmse, 4),
        "r2": (
            None
            if r2 is None
            else round(r2, 4)
        )
    }


def train_anomaly_model(
    train_data,
    epochs=100,
    learning_rate=0.001
):
    scaler = calculate_scaler(train_data)

    normalized = [
        normalize(item["values"], scaler)
        for item in train_data
    ]

    inputs = torch.tensor(
        normalized,
        dtype=torch.float32
    ).unsqueeze(1)

    torch.manual_seed(SEED)

    model = TransformerAutoencoder()

    optimizer = torch.optim.Adam(
        model.parameters(),
        lr=learning_rate
    )

    loss_function = nn.MSELoss()

    model.train()

    for _ in range(epochs):
        optimizer.zero_grad()

        reconstructed = model(inputs)
        target = inputs[:, -1, :]

        loss = loss_function(
            reconstructed, target
        )

        loss.backward()
        optimizer.step()

    return model, scaler


def reconstruction_errors(
    model,
    scaler,
    data
):
    normalized = [
        normalize(item["values"], scaler)
        for item in data
    ]

    inputs = torch.tensor(
        normalized,
        dtype=torch.float32
    ).unsqueeze(1)

    model.eval()

    with torch.no_grad():
        reconstructed = model(inputs)

    target = inputs[:, -1, :]

    errors = torch.mean(
        (reconstructed - target) ** 2,
        dim=1
    )

    return [
        float(error)
        for error in errors
    ]


def main():
    torch.manual_seed(SEED)

    data = load_complete_data()

    print("=" * 60)
    print("SMART CONNECTIVITY ANALYSER - AI EVALUATION")
    print("=" * 60)

    print(f"Complete records: {len(data)}")

    train_count = int(
        len(data) * TRAIN_RATIO
    )

    train_data = data[:train_count]
    test_data = data[train_count:]

    print(f"Training records: {len(train_data)}")
    print(f"Unseen test records: {len(test_data)}")

    if len(train_data) <= SEQUENCE_LENGTH:
        raise RuntimeError(
            "Training portion is too small."
        )

    print()
    print("Training temporary Transformer + TCN...")

    predictor, predictor_scaler, final_loss = (
        train_predictor(train_data)
    )

    prediction_metrics = evaluate_predictor(
        predictor,
        predictor_scaler,
        data,
        train_count
    )

    prediction_metrics[
        "final_training_loss"
    ] = round(final_loss, 6)

    print()
    print("PREDICTION RESULTS")
    print("-" * 60)
    print(
        f"Test predictions: "
        f"{prediction_metrics['test_predictions']}"
    )
    print(
        f"MAE:  {prediction_metrics['mae']}"
    )
    print(
        f"RMSE: {prediction_metrics['rmse']}"
    )
    print(
        f"R2:   {prediction_metrics['r2']}"
    )

    print()
    print("Training temporary Transformer Autoencoder...")

    anomaly_model, anomaly_scaler = (
        train_anomaly_model(train_data)
    )

    train_errors = reconstruction_errors(
        anomaly_model,
        anomaly_scaler,
        train_data
    )

    test_errors = reconstruction_errors(
        anomaly_model,
        anomaly_scaler,
        test_data
    )

    sorted_errors = sorted(train_errors)

    threshold_index = int(
        0.95 * (len(sorted_errors) - 1)
    )

    threshold = sorted_errors[
        threshold_index
    ]

    anomaly_count = sum(
        error > threshold
        for error in test_errors
    )

    train_average = (
        sum(train_errors)
        / len(train_errors)
    )

    test_average = (
        sum(test_errors)
        / len(test_errors)
    )

    anomaly_rate = (
        100 * anomaly_count
        / len(test_errors)
    )

    anomaly_metrics = {
        "training_average_reconstruction_error":
            round(train_average, 6),
        "test_average_reconstruction_error":
            round(test_average, 6),
        "threshold_95_percentile":
            round(threshold, 6),
        "test_records_above_threshold":
            anomaly_count,
        "test_anomaly_rate_percent":
            round(anomaly_rate, 2)
    }

    print()
    print("ANOMALY RESULTS")
    print("-" * 60)
    print(
        f"Training average error: "
        f"{anomaly_metrics['training_average_reconstruction_error']}"
    )
    print(
        f"Test average error: "
        f"{anomaly_metrics['test_average_reconstruction_error']}"
    )
    print(
        f"95% threshold: "
        f"{anomaly_metrics['threshold_95_percentile']}"
    )
    print(
        f"Test records above threshold: "
        f"{anomaly_count}/{len(test_errors)}"
    )
    print(
        f"Test anomaly rate: "
        f"{anomaly_metrics['test_anomaly_rate_percent']}%"
    )

    results = {
        "evaluation_type":
            "Chronological 80/20 holdout",
        "total_complete_records":
            len(data),
        "training_records":
            len(train_data),
        "unseen_test_records":
            len(test_data),
        "prediction_model":
            "Transformer + TCN",
        "anomaly_model":
            "Transformer Autoencoder",
        "prediction":
            prediction_metrics,
        "anomaly":
            anomaly_metrics,
        "note":
            "Existing trained models were not overwritten. "
            "Anomaly precision, recall and F1 require "
            "labelled anomaly records and are not calculated."
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
    print("Evaluation completed.")
    print(
        f"Results saved to: {RESULT_PATH}"
    )
    print("=" * 60)


if __name__ == "__main__":
    main()
