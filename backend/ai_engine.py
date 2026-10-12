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

import torch
import torch.nn as nn


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
                timestamp,
                download_mbps,
                upload_mbps,
                ping_ms,
                jitter_ms,
                packet_loss,
                connectivity_score
            FROM network_tests
            ORDER BY timestamp ASC
            """
        ).fetchall()

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
                data.append(
                    {
                        "timestamp": row["timestamp"],
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


def normalize_values(values, scaler):

    return [
        (
            value - scaler["mean"][index]
        )
        / scaler["std"][index]
        for index, value in enumerate(values)
    ]


def denormalize_value(value, scaler, feature_index):

    return (
        value * scaler["std"][feature_index]
        + scaler["mean"][feature_index]
    )


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
# TRAIN ANOMALY MODEL
# ============================================================

def train_anomaly_model(
    epochs=100,
    learning_rate=0.001
):

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

    normalized = [
        normalize_values(
            item["values"],
            scaler
        )
        for item in data
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

        reconstructed = model(
            inputs
        )

        target = inputs[:, -1, :]

        loss = loss_function(
            reconstructed,
            target
        )

        loss.backward()

        optimizer.step()

        final_loss = float(
            loss.item()
        )

    torch.save(
        model.state_dict(),
        ANOMALY_MODEL_PATH
    )

    save_scaler(
        scaler
    )

    return {
        "success": True,
        "model": "Transformer Autoencoder",
        "records": len(data),
        "epochs": epochs,
        "final_loss": final_loss,
        "model_path": str(
            ANOMALY_MODEL_PATH
        ),
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