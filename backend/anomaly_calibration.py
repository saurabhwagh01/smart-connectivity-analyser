"""
Validation-based anomaly threshold calibration (issue #40).

The Transformer Autoencoder flags a record as anomalous when its
reconstruction error is above a threshold. Previously that threshold was
``mean + 2 * std`` of the reconstruction errors on the *same* records
the model was trained on. Training errors are optimistically small (the
model has fitted exactly those records), so they say little about how the
model behaves on new measurements.

This module holds the pure, dependency-light parts of the calibration
pipeline (NumPy only, no PyTorch), so they can be tested in isolation:

* ``chronological_split``: the earliest records train the model, the
  latest are held out for validation. Records are never shuffled, so no
  future measurement is used to train a model that is then judged on the
  past.
* Threshold strategies computed on **validation** reconstruction errors:

  ``percentile`` (default, q = 95)
      The q-th percentile of the validation errors (linear
      interpolation). It makes no assumption about the error
      distribution and, by construction, about (100 - q)% of normal
      validation records lie above it. That gives an interpretable
      expected false-alarm rate when the validation period is normal.
  ``mean_std`` (k = 2)
      ``mean + k * std``. This was the previous method. It is only well
      founded for roughly Gaussian errors. Reconstruction errors are
      non-negative and right-skewed, and a few large errors inflate both
      the mean and the standard deviation.
  ``mad`` (k = 3)
      ``median + k * 1.4826 * MAD``. A robust analogue of ``mean_std``:
      the median absolute deviation, scaled by 1.4826, estimates the
      standard deviation for Gaussian data but is barely moved by
      outliers already present in the validation period.

* ``error_statistics``, ``compare_strategies`` and ``threshold_stability``
  build the evaluation report.
* ``labelled_metrics``: precision, recall and F1 **only** when labels are
  provided. Without labels nothing is calculated (``None``), so no
  performance figure is ever invented.
* Calibration artifacts: the selected threshold is saved with the SHA-256
  of the model file and of the scaler it was computed with.
  ``load_calibration`` refuses the threshold if either no longer matches,
  so a retrained model or scaler can never be paired with a stale
  threshold.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np


CALIBRATION_SCHEMA_VERSION = 1
MODEL_NAME = "Transformer Autoencoder"

DEFAULT_VALIDATION_RATIO = 0.2
MIN_TRAINING_RECORDS = 40
MIN_VALIDATION_RECORDS = 10


class InsufficientDataError(ValueError):
    """Not enough records to train and validate separately."""


# ------------------------------------------------------------
# Configuration
# ------------------------------------------------------------

@dataclass(frozen=True)
class CalibrationConfig:
    """Adjustable calibration settings. They never change the model itself."""

    strategy: str = "percentile"
    params: dict = field(default_factory=lambda: {"q": 95.0})
    validation_ratio: float = DEFAULT_VALIDATION_RATIO
    min_training_records: int = MIN_TRAINING_RECORDS
    min_validation_records: int = MIN_VALIDATION_RECORDS
    seed: int = 42
    epochs: int = 100
    learning_rate: float = 0.001

    def to_dict(self):
        return asdict(self)


DEFAULT_COMPARISON = (
    ("percentile", {"q": 95.0}),
    ("percentile", {"q": 99.0}),
    ("mean_std", {"k": 2.0}),
    ("mean_std", {"k": 3.0}),
    ("mad", {"k": 3.0}),
)


# ------------------------------------------------------------
# Data separation
# ------------------------------------------------------------

def chronological_split(
    records,
    validation_ratio=DEFAULT_VALIDATION_RATIO,
    min_training_records=MIN_TRAINING_RECORDS,
    min_validation_records=MIN_VALIDATION_RECORDS,
):
    """Split chronologically ordered records into (training, validation).

    ``records`` must already be in chronological order (as returned by
    ``ai_engine.load_network_data``). The latest ``validation_ratio`` of
    them are held out. The two lists never share a record.
    """

    if not 0.0 < float(validation_ratio) < 1.0:
        raise ValueError("validation_ratio must be between 0 and 1.")

    records = list(records)
    total = len(records)
    validation_count = int(math.ceil(total * float(validation_ratio)))
    training_count = total - validation_count

    if (
        training_count < min_training_records
        or validation_count < min_validation_records
    ):
        raise InsufficientDataError(
            "Insufficient data for validation-based calibration: "
            f"{total} complete records give {training_count} training and "
            f"{validation_count} validation records; at least "
            f"{min_training_records} and {min_validation_records} are "
            "required."
        )

    return records[:training_count], records[training_count:]


# ------------------------------------------------------------
# Threshold strategies
# ------------------------------------------------------------

def _finite_errors(errors):
    values = np.asarray(list(errors), dtype=float).reshape(-1)
    if values.size == 0:
        raise ValueError("At least one reconstruction error is required.")
    if not np.isfinite(values).all():
        raise ValueError("Reconstruction errors must be finite.")
    if np.any(values < 0):
        raise ValueError("Reconstruction errors cannot be negative.")
    return values


def percentile_threshold(errors, q=95.0):
    q = float(q)
    if not 0.0 < q < 100.0:
        raise ValueError("Percentile q must be between 0 and 100.")
    return float(np.percentile(_finite_errors(errors), q))


def mean_std_threshold(errors, k=2.0):
    values = _finite_errors(errors)
    return float(values.mean() + float(k) * values.std())


def mad_threshold(errors, k=3.0):
    values = _finite_errors(errors)
    median = float(np.median(values))
    mad = float(np.median(np.abs(values - median)))
    return median + float(k) * 1.4826 * mad


THRESHOLD_STRATEGIES = {
    "percentile": percentile_threshold,
    "mean_std": mean_std_threshold,
    "mad": mad_threshold,
}


def calculate_threshold(errors, strategy="percentile", **params):
    try:
        function = THRESHOLD_STRATEGIES[strategy]
    except KeyError:
        raise ValueError(
            f"Unknown threshold strategy '{strategy}'. "
            f"Choose one of: {', '.join(sorted(THRESHOLD_STRATEGIES))}."
        ) from None
    threshold = function(errors, **params)
    if not math.isfinite(threshold):
        raise ValueError("Calculated threshold is not finite.")
    return threshold


def describe_strategy(strategy, params):
    details = ", ".join(f"{key}={value:g}" for key, value in sorted(params.items()))
    return f"{strategy}({details})" if details else strategy


# ------------------------------------------------------------
# Statistics and evaluation
# ------------------------------------------------------------

def error_statistics(errors):
    values = _finite_errors(errors)
    return {
        "count": int(values.size),
        "mean": float(values.mean()),
        "std": float(values.std()),
        "min": float(values.min()),
        "median": float(np.median(values)),
        "p90": float(np.percentile(values, 90)),
        "p95": float(np.percentile(values, 95)),
        "p99": float(np.percentile(values, 99)),
        "max": float(values.max()),
    }


def exceedance(errors, threshold):
    values = _finite_errors(errors)
    count = int(np.sum(values > threshold))
    return {
        "records_above_threshold": count,
        "percent_above_threshold": 100.0 * count / values.size,
    }


def labelled_metrics(errors, labels, threshold):
    """Precision, recall and F1 against labels (True = anomaly).

    Returns ``None`` when no labels are available; metrics are never
    estimated without ground truth. ``labels`` may contain ``None`` for
    unlabelled records, which are excluded.
    """

    if labels is None:
        return None

    values = _finite_errors(errors)
    labels = list(labels)
    if len(labels) != values.size:
        raise ValueError("labels must have one entry per error.")

    pairs = [
        (error > threshold, bool(label))
        for error, label in zip(values, labels)
        if label is not None
    ]
    if not pairs:
        return None

    tp = sum(1 for predicted, actual in pairs if predicted and actual)
    fp = sum(1 for predicted, actual in pairs if predicted and not actual)
    fn = sum(1 for predicted, actual in pairs if not predicted and actual)
    tn = sum(1 for predicted, actual in pairs if not predicted and not actual)

    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision is not None and recall is not None and precision + recall
        else None
    )

    return {
        "labelled_records": len(pairs),
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
        "true_negatives": tn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def compare_strategies(
    validation_errors,
    strategies=DEFAULT_COMPARISON,
    labels=None,
):
    """Evaluate each strategy on the same validation errors."""

    comparison = []
    for strategy, params in strategies:
        threshold = calculate_threshold(validation_errors, strategy, **params)
        comparison.append(
            {
                "strategy": strategy,
                "params": dict(params),
                "label": describe_strategy(strategy, params),
                "threshold": threshold,
                **exceedance(validation_errors, threshold),
                "labelled_metrics": labelled_metrics(
                    validation_errors, labels, threshold
                ),
                "stability": threshold_stability(
                    validation_errors, strategy, params
                ),
            }
        )
    return comparison


def threshold_stability(errors, strategy, params, folds=3, min_fold_size=5):
    """Compare the threshold across consecutive chronological validation folds.

    Large variation between folds means the threshold depends heavily on
    which period it was calibrated on. Returns ``None`` when there are
    too few errors for the requested folds.
    """

    values = _finite_errors(errors)
    if folds < 2 or values.size < folds * min_fold_size:
        return None

    thresholds = [
        calculate_threshold(chunk, strategy, **params)
        for chunk in np.array_split(values, folds)
    ]
    mean = float(np.mean(thresholds))
    return {
        "folds": folds,
        "thresholds": [float(value) for value in thresholds],
        "mean": mean,
        "std": float(np.std(thresholds)),
        "range": float(max(thresholds) - min(thresholds)),
        "coefficient_of_variation": (
            float(np.std(thresholds) / mean) if mean > 0 else None
        ),
    }


# ------------------------------------------------------------
# Artifacts
# ------------------------------------------------------------

def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def scaler_sha256(scaler):
    """Fingerprint of the values that define the scaler."""

    payload = {
        "features": list(scaler.get("features") or []),
        "mean": [float(value) for value in scaler["mean"]],
        "std": [float(value) for value in scaler["std"]],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def build_calibration(
    *,
    threshold,
    config,
    model_path,
    scaler,
    features,
    training_records,
    validation_records,
    validation_statistics,
    validation_exceedance,
    training_period=None,
    validation_period=None,
):
    return {
        "schema_version": CALIBRATION_SCHEMA_VERSION,
        "model": MODEL_NAME,
        "threshold": float(threshold),
        "strategy": config.strategy,
        "params": dict(config.params),
        "method": describe_strategy(config.strategy, config.params),
        "source": "validation",
        "features": list(features),
        "model_sha256": file_sha256(model_path),
        "scaler_sha256": scaler_sha256(scaler),
        "training_records": int(training_records),
        "validation_records": int(validation_records),
        "training_period": training_period,
        "validation_period": validation_period,
        "validation_statistics": validation_statistics,
        "validation_exceedance": validation_exceedance,
        "config": config.to_dict(),
        "created_at": datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
    }


def write_json_atomic(path, payload):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def load_calibration(path, model_path, scaler, features):
    """Return ``(calibration, None)`` if valid, else ``(None, reason)``."""

    path = Path(path)
    if not path.exists():
        return None, "No calibration file found."

    try:
        calibration = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return None, f"Calibration file could not be read: {error}"

    if not isinstance(calibration, dict):
        return None, "Calibration file is not a JSON object."
    if calibration.get("schema_version") != CALIBRATION_SCHEMA_VERSION:
        return None, "Calibration schema version is not supported."
    if calibration.get("model") != MODEL_NAME:
        return None, "Calibration belongs to a different model."
    if list(calibration.get("features") or []) != list(features):
        return None, "Calibration features do not match the model features."

    try:
        threshold = float(calibration.get("threshold"))
    except (TypeError, ValueError):
        return None, "Calibration threshold is missing or invalid."
    if not math.isfinite(threshold) or threshold < 0:
        return None, "Calibration threshold is not a finite, non-negative value."

    try:
        model_hash = file_sha256(model_path)
    except OSError as error:
        return None, f"Model file could not be read: {error}"
    if calibration.get("model_sha256") != model_hash:
        return None, (
            "Calibration was computed for a different model file; "
            "re-run backend/calibrate_anomaly.py."
        )
    if calibration.get("scaler_sha256") != scaler_sha256(scaler):
        return None, (
            "Calibration was computed with a different scaler; "
            "re-run backend/calibrate_anomaly.py."
        )

    calibration["threshold"] = threshold
    return calibration, None
