"""
Smart Internet Connectivity Analyser
AI Engine

Models:
1. Transformer + TCN
   - Predicts future connectivity score

2. Transformer Autoencoder
   - Detects abnormal network conditions

Training uses REAL measurements stored in:
network_history.db
"""

from pathlib import Path
import sqlite3
import json
import math
import os

import torch
import torch.nn as nn

if __package__:
    from . import anomaly_calibration as calibration
    from .timestamps import canonical_sort_key, to_canonical_utc
else:  # Imported directly from backend/ (as main.py does).
    import anomaly_calibration as calibration
    from timestamps import canonical_sort_key, to_canonical_utc


# ============================================================
# PATHS
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent

DB_PATH = BASE_DIR / "network_history.db"

MODEL_DIR = BASE_DIR / "backend" / "models"
MODEL_DIR.mkdir(parents=True, exist_ok=True)

PREDICTION_MODEL_PATH = MODEL_DIR / "connectivity_predictor.pt"
ANOMALY_MODEL_PATH = MODEL_DIR / "anomaly_autoencoder.pt"
SCALER_PATH = MODEL_DIR / "scaler.json"
CALIBRATION_PATH = MODEL_DIR / "anomaly_calibration.json"
CALIBRATION_REPORT_PATH = BASE_DIR / "backend" / "anomaly_calibration_report.json"


# ============================================================
# CONFIGURATION
# ============================================================

FEATURES = [
    "download_mbps",
    "upload_mbps",
    "ping_ms",
    "jitter_ms",
    "packet_loss",
    "connectivity_score",
]

SEQUENCE_LENGTH = 8

MIN_TRAINING_RECORDS = 50


# ============================================================
# DATABASE
# ============================================================

def load_network_data():
    """
    Load real network measurements from SQLite.
    """

    if not DB_PATH.exists():
        return []

    connection = sqlite3.connect(DB_PATH)

    connection.row_factory = sqlite3.Row

    try:

        rows = connection.execute(
            """
            SELECT
                id,
                timestamp,
                download_mbps,
                upload_mbps,
                ping_ms,
                jitter_ms,
                packet_loss,
                connectivity_score
            FROM network_tests
            """
        ).fetchall()

        # Order by real UTC instant, then id (issue #39). Stored values
        # may use different formats, so text order is not chronological.
        rows = sorted(
            rows,
            key=lambda row: canonical_sort_key(row["timestamp"], row["id"]),
        )

        data = []

        for row in rows:

            timestamp = to_canonical_utc(row["timestamp"])

            # A record that cannot be placed in time cannot be used in a
            # chronological sequence.
            if timestamp is None:
                continue

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
                data.append(
                    {
                        "timestamp": timestamp,
                        "values": values,
                    }
                )

        return data

    finally:

        connection.close()


# ============================================================
# DATA STATUS
# ============================================================

def get_data_status():

    data = load_network_data()

    total_records = len(data)

    return {
        "records": total_records,
        "minimum_required": MIN_TRAINING_RECORDS,
        "enough_data": total_records >= MIN_TRAINING_RECORDS,
        "remaining": max(
            0,
            MIN_TRAINING_RECORDS - total_records
        ),
    }


# ============================================================
# NORMALIZATION
# ============================================================

def calculate_scaler(data):

    values = [
        item["values"]
        for item in data
    ]

    feature_count = len(FEATURES)

    means = []
    stds = []

    for index in range(feature_count):

        column = [
            row[index]
            for row in values
        ]

        mean = sum(column) / len(column)

        variance = sum(
            (value - mean) ** 2
            for value in column
        ) / len(column)

        std = math.sqrt(variance)

        if std < 1e-8:
            std = 1.0

        means.append(mean)
        stds.append(std)

    return {
        "features": FEATURES,
        "mean": means,
        "std": stds,
    }


def _scaler_mean_and_scale(scaler, feature_index):
    mean = float(scaler["mean"][feature_index])
    std = float(scaler["std"][feature_index])

    if not math.isfinite(mean) or not math.isfinite(std) or std < 0:
        raise ValueError(
            "Scaler means and standard deviations must be valid finite values."
        )

    return mean, std if abs(std) >= 1e-8 else 1.0


def normalize_values(values, scaler):
    normalized = []

    for index, value in enumerate(values):
        value = float(value)
        if not math.isfinite(value):
            raise ValueError("Values to normalize must be finite.")

        mean, scale = _scaler_mean_and_scale(scaler, index)
        normalized_value = (value - mean) / scale
        if not math.isfinite(normalized_value):
            raise ValueError("Normalized values must be finite.")

        normalized.append(normalized_value)

    return normalized


def denormalize_value(value, scaler, feature_index):
    mean, scale = _scaler_mean_and_scale(scaler, feature_index)
    return float(value) * scale + mean


# ============================================================
# SEQUENCE CREATION
# ============================================================

def create_prediction_sequences(data, scaler):

    normalized = [
        normalize_values(
            item["values"],
            scaler
        )
        for item in data
    ]

    sequences = []

    targets = []

    for index in range(
        SEQUENCE_LENGTH,
        len(normalized)
    ):

        sequence = normalized[
            index - SEQUENCE_LENGTH:index
        ]

        target = normalized[
            index
        ][5]

        sequences.append(sequence)

        targets.append(target)

    return sequences, targets


# ============================================================
# TCN BLOCK
# ============================================================

class TCNBlock(nn.Module):

    def __init__(
        self,
        input_channels,
        output_channels,
        kernel_size=3
    ):

        super().__init__()

        padding = kernel_size // 2

        self.conv = nn.Conv1d(
            input_channels,
            output_channels,
            kernel_size,
            padding=padding
        )

        self.norm = nn.BatchNorm1d(
            output_channels
        )

        self.activation = nn.ReLU()

    def forward(self, x):

        x = self.conv(x)

        x = self.norm(x)

        return self.activation(x)


# ============================================================
# TRANSFORMER + TCN PREDICTOR
# ============================================================

class ConnectivityPredictor(nn.Module):

    def __init__(
        self,
        feature_count=len(FEATURES),
        model_dimension=64,
        heads=4,
        layers=2
    ):

        super().__init__()

        self.input_projection = nn.Linear(
            feature_count,
            model_dimension
        )

        encoder_layer = nn.TransformerEncoderLayer(
            d_model=model_dimension,
            nhead=heads,
            dim_feedforward=128,
            dropout=0.1,
            batch_first=True,
            activation="gelu"
        )

        self.transformer = nn.TransformerEncoder(
            encoder_layer,
            num_layers=layers
        )

        self.tcn = TCNBlock(
            model_dimension,
            model_dimension
        )

        self.output = nn.Sequential(
            nn.Linear(
                model_dimension,
                32
            ),
            nn.ReLU(),
            nn.Linear(
                32,
                1
            )
        )

    def forward(self, x):

        # x:
        # [batch, sequence, features]

        x = self.input_projection(x)

        x = self.transformer(x)

        # TCN expects:
        # [batch, channels, sequence]

        x = x.transpose(1, 2)

        x = self.tcn(x)

        # Last time step

        x = x[:, :, -1]

        return self.output(x).squeeze(-1)


# ============================================================
# TRANSFORMER AUTOENCODER
# ============================================================

class TransformerAutoencoder(nn.Module):

    def __init__(
        self,
        feature_count=len(FEATURES),
        model_dimension=64,
        heads=4,
        layers=2
    ):

        super().__init__()

        self.input_projection = nn.Linear(
            feature_count,
            model_dimension
        )

        encoder_layer = nn.TransformerEncoderLayer(
            d_model=model_dimension,
            nhead=heads,
            dim_feedforward=128,
            dropout=0.1,
            batch_first=True,
            activation="gelu"
        )

        self.encoder = nn.TransformerEncoder(
            encoder_layer,
            num_layers=layers
        )

        self.decoder = nn.Sequential(
            nn.Linear(
                model_dimension,
                32
            ),
            nn.ReLU(),
            nn.Linear(
                32,
                feature_count
            )
        )

    def forward(self, x):

        x = self.input_projection(x)

        encoded = self.encoder(x)

        # Reconstruct the final observation

        encoded = encoded[:, -1, :]

        return self.decoder(encoded)


# ============================================================
# TRAINING DATA
# ============================================================

def prepare_training_data():

    data = load_network_data()

    if len(data) < MIN_TRAINING_RECORDS:

        return {
            "success": False,
            "message": (
                f"Insufficient training data. "
                f"{len(data)}/{MIN_TRAINING_RECORDS} "
                f"records available."
            ),
            "records": len(data),
            "minimum_required": MIN_TRAINING_RECORDS,
        }

    scaler = calculate_scaler(data)

    sequences, targets = create_prediction_sequences(
        data,
        scaler
    )

    if len(sequences) < 10:

        return {
            "success": False,
            "message": (
                "Not enough time-series sequences "
                "available for training."
            ),
            "records": len(data),
        }

    return {
        "success": True,
        "data": data,
        "scaler": scaler,
        "sequences": sequences,
        "targets": targets,
    }


# ============================================================
# SAVE SCALER
# ============================================================

def save_scaler(scaler):

    with open(
        SCALER_PATH,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            scaler,
            file,
            indent=2
        )


# ============================================================
# TRAIN PREDICTION MODEL
# ============================================================

def train_prediction_model(
    epochs=100,
    learning_rate=0.001
):

    prepared = prepare_training_data()

    if not prepared["success"]:

        return prepared

    sequences = torch.tensor(
        prepared["sequences"],
        dtype=torch.float32
    )

    targets = torch.tensor(
        prepared["targets"],
        dtype=torch.float32
    )

    model = ConnectivityPredictor()

    optimizer = torch.optim.Adam(
        model.parameters(),
        lr=learning_rate
    )

    loss_function = nn.MSELoss()

    model.train()

    final_loss = None

    for epoch in range(epochs):

        optimizer.zero_grad()

        predictions = model(
            sequences
        )

        loss = loss_function(
            predictions,
            targets
        )

        loss.backward()

        optimizer.step()

        final_loss = float(
            loss.item()
        )

    torch.save(
        model.state_dict(),
        PREDICTION_MODEL_PATH
    )

    save_scaler(
        prepared["scaler"]
    )

    return {
        "success": True,
        "model": "Transformer + TCN",
        "records": len(
            prepared["data"]
        ),
        "sequences": len(
            prepared["sequences"]
        ),
        "epochs": epochs,
        "final_loss": final_loss,
        "model_path": str(
            PREDICTION_MODEL_PATH
        ),
    }


# ============================================================
# TRAIN AND CALIBRATE ANOMALY MODEL (issue #40)
# ============================================================

def train_autoencoder(
    records,
    scaler,
    epochs=100,
    learning_rate=0.001,
    seed=42,
):
    """Train a Transformer Autoencoder on ``records`` only."""

    if seed is not None:
        torch.manual_seed(seed)

    normalized = [
        normalize_values(item["values"], scaler)
        for item in records
    ]

    inputs = torch.tensor(
        normalized,
        dtype=torch.float32
    ).unsqueeze(1)

    model = TransformerAutoencoder()

    optimizer = torch.optim.Adam(
        model.parameters(),
        lr=learning_rate
    )

    loss_function = nn.MSELoss()

    model.train()

    final_loss = None

    for epoch in range(epochs):

        optimizer.zero_grad()

        reconstructed = model(inputs)

        target = inputs[:, -1, :]

        loss = loss_function(reconstructed, target)

        loss.backward()

        optimizer.step()

        final_loss = float(loss.item())

    model.eval()

    return model, final_loss


def anomaly_reconstruction_errors(model, scaler, records):
    """Per-record mean squared reconstruction error, as the API computes it."""

    if not records:
        return []

    normalized = [
        normalize_values(item["values"], scaler)
        for item in records
    ]

    inputs = torch.tensor(
        normalized,
        dtype=torch.float32
    ).unsqueeze(1)

    model.eval()

    with torch.no_grad():
        reconstructed = model(inputs)

    target = inputs[:, -1, :]

    errors = torch.mean((reconstructed - target) ** 2, dim=1)

    return [float(error) for error in errors]


def _period(records):
    if not records:
        return None
    return {
        "start": records[0]["timestamp"],
        "end": records[-1]["timestamp"],
    }


def calibrate_anomaly_model(
    config=None,
    data=None,
    labels=None,
    save=False,
    model_path=None,
    scaler_path=None,
    calibration_path=None,
    strategies=calibration.DEFAULT_COMPARISON,
):
    """Train on the earliest records and calibrate on the held-out latest.

    ``labels`` optionally maps canonical UTC timestamps to True (anomaly)
    or False (normal). Labelled metrics are reported only for labelled
    validation records and are never estimated without labels.

    With ``save=True`` the model, its training-only scaler and the
    calibration are written together, so the served threshold always
    belongs to the served model and scaler.
    """

    config = config or calibration.CalibrationConfig()
    model_path = Path(model_path or ANOMALY_MODEL_PATH)
    scaler_path = Path(scaler_path or SCALER_PATH)
    calibration_path = Path(calibration_path or CALIBRATION_PATH)

    if data is None:
        data = load_network_data()

    # Reject an unknown strategy or bad parameters before training.
    calibration.calculate_threshold([0.0, 1.0], config.strategy, **config.params)

    try:
        training, validation = calibration.chronological_split(
            data,
            config.validation_ratio,
            config.min_training_records,
            config.min_validation_records,
        )
    except calibration.InsufficientDataError as error:
        return {
            "success": False,
            "message": str(error),
            "records": len(data),
        }

    # The scaler is fitted on training records only: validation stays unseen.
    scaler = calculate_scaler(training)

    model, final_loss = train_autoencoder(
        training,
        scaler,
        epochs=config.epochs,
        learning_rate=config.learning_rate,
        seed=config.seed,
    )

    training_errors = anomaly_reconstruction_errors(model, scaler, training)
    validation_errors = anomaly_reconstruction_errors(model, scaler, validation)

    threshold = calibration.calculate_threshold(
        validation_errors,
        config.strategy,
        **config.params,
    )

    validation_labels = None
    if labels:
        validation_labels = [
            labels.get(item["timestamp"]) for item in validation
        ]
        if all(label is None for label in validation_labels):
            validation_labels = None

    validation_statistics = calibration.error_statistics(validation_errors)
    validation_exceedance = calibration.exceedance(validation_errors, threshold)

    limitations = [
        "The threshold is calibrated on the most recent records, which are "
        "assumed to be mostly normal; anomalies in that period raise it.",
        "A percentile threshold flags about (100 - q)% of validation records "
        "by construction; that share is not a detection rate.",
        f"Only {len(validation)} validation records were available; "
        "thresholds from small samples are noisy (see stability).",
    ]
    if validation_labels is None:
        limitations.append(
            "No labelled anomalies were provided, so precision, recall and "
            "F1 were not calculated."
        )

    report = {
        "success": True,
        "model": calibration.MODEL_NAME,
        "evaluation_type": "Chronological train/validation split",
        "config": config.to_dict(),
        "total_complete_records": len(data),
        "training_records": len(training),
        "validation_records": len(validation),
        "training_period": _period(training),
        "validation_period": _period(validation),
        "final_training_loss": final_loss,
        "training_error_statistics": calibration.error_statistics(
            training_errors
        ),
        "validation_error_statistics": validation_statistics,
        "selected": {
            "strategy": config.strategy,
            "params": dict(config.params),
            "method": calibration.describe_strategy(
                config.strategy, config.params
            ),
            "threshold": threshold,
            "validation": validation_exceedance,
            "training": calibration.exceedance(training_errors, threshold),
            "labelled_metrics": calibration.labelled_metrics(
                validation_errors, validation_labels, threshold
            ),
        },
        "comparison": calibration.compare_strategies(
            validation_errors,
            strategies,
            validation_labels,
        ),
        "limitations": limitations,
        "saved": False,
    }

    if save:
        model_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_model = model_path.with_suffix(model_path.suffix + ".tmp")
        torch.save(model.state_dict(), temporary_model)
        os.replace(temporary_model, model_path)
        calibration.write_json_atomic(scaler_path, scaler)
        calibration.write_json_atomic(
            calibration_path,
            calibration.build_calibration(
                threshold=threshold,
                config=config,
                model_path=model_path,
                scaler=scaler,
                features=FEATURES,
                training_records=len(training),
                validation_records=len(validation),
                validation_statistics=validation_statistics,
                validation_exceedance=validation_exceedance,
                training_period=report["training_period"],
                validation_period=report["validation_period"],
            ),
        )
        report["saved"] = True
        report["artifacts"] = {
            "model": str(model_path),
            "scaler": str(scaler_path),
            "calibration": str(calibration_path),
        }

    return report


def train_anomaly_model(
    epochs=100,
    learning_rate=0.001
):
    """Train, calibrate and save the anomaly model with its threshold."""

    data = load_network_data()

    if len(data) < MIN_TRAINING_RECORDS:

        return {
            "success": False,
            "message": (
                f"Insufficient training data. "
                f"{len(data)}/{MIN_TRAINING_RECORDS} "
                f"records available."
            ),
            "records": len(data),
            "minimum_required": MIN_TRAINING_RECORDS,
        }

    report = calibrate_anomaly_model(
        calibration.CalibrationConfig(
            epochs=epochs,
            learning_rate=learning_rate,
        ),
        data=data,
        save=True,
    )

    if not report["success"]:
        return report

    return {
        "success": True,
        "model": "Transformer Autoencoder",
        "records": len(data),
        "training_records": report["training_records"],
        "validation_records": report["validation_records"],
        "epochs": epochs,
        "final_loss": report["final_training_loss"],
        "threshold": report["selected"]["threshold"],
        "threshold_method": report["selected"]["method"],
        "model_path": str(ANOMALY_MODEL_PATH),
        "calibration_path": str(CALIBRATION_PATH),
    }

# ============================================================
# COMPLETE TRAINING
# ============================================================

def train_all_models():

    status = get_data_status()

    if not status["enough_data"]:

        return {
            "success": False,
            "message": (
                f"AI training is not ready. "
                f"{status['records']}/"
                f"{status['minimum_required']} "
                f"records collected."
            ),
            "data_status": status,
        }

    prediction = train_prediction_model()

    anomaly = train_anomaly_model()

    return {
        "success": (
            prediction["success"]
            and anomaly["success"]
        ),
        "prediction": prediction,
        "anomaly": anomaly,
    }


# ============================================================
# COMMAND LINE TEST
# ============================================================

if __name__ == "__main__":

    print()
    print("=" * 60)
    print("SMART CONNECTIVITY ANALYSER - AI ENGINE")
    print("=" * 60)

    status = get_data_status()

    print(
        f"Records available: "
        f"{status['records']}"
    )

    print(
        f"Minimum required: "
        f"{status['minimum_required']}"
    )

    if not status["enough_data"]:

        print()
        print(
            "AI training is not started."
        )

        print(
            f"Collect {status['remaining']} "
            f"more real network records."
        )

    else:

        print()
        print(
            "Enough data available."
        )

        result = train_all_models()

        print(
            json.dumps(
                result,
                indent=2
            )
        )

    print("=" * 60)