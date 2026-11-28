"""Validation-based anomaly threshold calibration (issue #40)."""

import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import anomaly_calibration as cal  # noqa: E402

torch = pytest.importorskip("torch")

import ai_engine  # noqa: E402
import backend.main as main  # noqa: E402
import calibrate_anomaly  # noqa: E402


FAST = dict(epochs=3, seed=7)


def make_records(count=60, seed=0):
    rng = np.random.default_rng(seed)
    records = []
    for index in range(count):
        records.append(
            {
                "timestamp": (
                    f"2026-11-{1 + index // 24:02d}T{index % 24:02d}:00:00.000Z"
                ),
                "values": [
                    float(40 + rng.normal(0, 3)),
                    float(10 + rng.normal(0, 1)),
                    float(20 + abs(rng.normal(0, 2))),
                    float(2 + abs(rng.normal(0, 0.5))),
                    float(abs(rng.normal(0, 0.5))),
                    float(70 + rng.normal(0, 4)),
                ],
            }
        )
    return records


@pytest.fixture
def records():
    return make_records()


@pytest.fixture
def artifact_paths(tmp_path):
    return {
        "model_path": tmp_path / "anomaly_autoencoder.pt",
        "scaler_path": tmp_path / "scaler.json",
        "calibration_path": tmp_path / "anomaly_calibration.json",
    }


def calibrate(records, paths=None, save=False, labels=None, **config):
    settings = {**FAST, **config}
    return ai_engine.calibrate_anomaly_model(
        cal.CalibrationConfig(**settings),
        data=records,
        labels=labels,
        save=save,
        **(paths or {}),
    )


# ------------------------------------------------------------
# Threshold strategies
# ------------------------------------------------------------

ERRORS = [0.01, 0.02, 0.02, 0.03, 0.04, 0.05, 0.06, 0.08, 0.10, 0.50]


def test_percentile_threshold_matches_linear_interpolation():
    assert cal.percentile_threshold(ERRORS, q=95) == pytest.approx(
        float(np.percentile(ERRORS, 95))
    )
    assert cal.percentile_threshold(ERRORS, q=50) == pytest.approx(0.045)


def test_mean_std_threshold():
    values = np.asarray(ERRORS)
    assert cal.mean_std_threshold(ERRORS, k=2) == pytest.approx(
        values.mean() + 2 * values.std()
    )


def test_mad_threshold_is_robust_to_one_outlier():
    median = float(np.median(ERRORS))
    mad = float(np.median(np.abs(np.asarray(ERRORS) - median)))
    assert cal.mad_threshold(ERRORS, k=3) == pytest.approx(
        median + 3 * 1.4826 * mad
    )
    # The single 0.50 outlier inflates mean/std far more than the MAD.
    assert cal.mad_threshold(ERRORS) < cal.mean_std_threshold(ERRORS, k=2)


def test_calculate_threshold_dispatch_and_errors():
    assert cal.calculate_threshold(ERRORS, "percentile", q=90) == pytest.approx(
        cal.percentile_threshold(ERRORS, 90)
    )
    with pytest.raises(ValueError, match="Unknown threshold strategy"):
        cal.calculate_threshold(ERRORS, "magic")
    with pytest.raises(ValueError, match="between 0 and 100"):
        cal.calculate_threshold(ERRORS, "percentile", q=100)


@pytest.mark.parametrize(
    "errors",
    [[], [0.1, math.nan], [0.1, math.inf], [0.1, -0.2]],
    ids=["empty", "nan", "inf", "negative"],
)
def test_invalid_errors_are_rejected(errors):
    with pytest.raises(ValueError):
        cal.percentile_threshold(errors)


def test_error_statistics_and_exceedance():
    stats = cal.error_statistics(ERRORS)
    assert stats["count"] == 10
    assert stats["max"] == 0.50
    assert stats["median"] == pytest.approx(0.045)
    above = cal.exceedance(ERRORS, 0.05)
    assert above == {
        "records_above_threshold": 4,
        "percent_above_threshold": 40.0,
    }


# ------------------------------------------------------------
# Chronological separation
# ------------------------------------------------------------

def test_split_is_chronological_and_disjoint(records):
    training, validation = cal.chronological_split(records, 0.2)

    assert len(training) == 48
    assert len(validation) == 12
    assert training + validation == records
    assert training[-1]["timestamp"] < validation[0]["timestamp"]
    assert not {r["timestamp"] for r in training} & {
        r["timestamp"] for r in validation
    }


def test_split_rejects_insufficient_data(records):
    with pytest.raises(cal.InsufficientDataError, match="at least 40"):
        cal.chronological_split(records[:45], 0.2)
    with pytest.raises(cal.InsufficientDataError):
        cal.chronological_split(records, 0.1, min_validation_records=10)


@pytest.mark.parametrize("ratio", [0, 1, -0.2, 1.5])
def test_split_rejects_invalid_ratio(records, ratio):
    with pytest.raises(ValueError):
        cal.chronological_split(records, ratio)


# ------------------------------------------------------------
# Labelled evaluation
# ------------------------------------------------------------

def test_no_labels_means_no_metrics():
    assert cal.labelled_metrics(ERRORS, None, 0.05) is None
    assert cal.labelled_metrics(ERRORS, [None] * 10, 0.05) is None


def test_labelled_metrics_counts():
    # Above 0.05: 0.06, 0.08, 0.10, 0.50.
    labels = [False] * 6 + [False, True, True, True]
    metrics = cal.labelled_metrics(ERRORS, labels, 0.05)

    assert metrics["true_positives"] == 3
    assert metrics["false_positives"] == 1
    assert metrics["false_negatives"] == 0
    assert metrics["true_negatives"] == 6
    assert metrics["precision"] == pytest.approx(0.75)
    assert metrics["recall"] == pytest.approx(1.0)
    assert metrics["f1"] == pytest.approx(2 * 0.75 / 1.75)


def test_labelled_metrics_skips_unlabelled_and_undefined_ratios():
    labels = [None] * 9 + [False]
    metrics = cal.labelled_metrics(ERRORS, labels, 1.0)

    assert metrics["labelled_records"] == 1
    assert metrics["precision"] is None  # nothing flagged
    assert metrics["recall"] is None  # no actual anomalies
    assert metrics["f1"] is None
    with pytest.raises(ValueError):
        cal.labelled_metrics(ERRORS, [True], 0.05)


def test_compare_strategies_is_reproducible():
    errors = list(np.random.default_rng(1).gamma(2.0, 0.01, size=30))
    first = cal.compare_strategies(errors)
    second = cal.compare_strategies(errors)

    assert first == second
    assert [row["label"] for row in first] == [
        "percentile(q=95)",
        "percentile(q=99)",
        "mean_std(k=2)",
        "mean_std(k=3)",
        "mad(k=3)",
    ]
    for row in first:
        assert row["labelled_metrics"] is None
        assert row["stability"]["folds"] == 3
        assert len(row["stability"]["thresholds"]) == 3


def test_stability_requires_enough_errors():
    assert cal.threshold_stability(ERRORS, "percentile", {"q": 95}) is None


# ------------------------------------------------------------
# Artifacts and consistency
# ------------------------------------------------------------

cal_features = list(ai_engine.FEATURES)

SCALER = {
    "features": cal_features,
    "mean": [1.0] * 6,
    "std": [2.0] * 6,
}


def write_calibration(tmp_path, overrides=None, threshold=0.04):
    model_path = tmp_path / "model.pt"
    model_path.write_bytes(b"model-bytes")
    calibration = cal.build_calibration(
        threshold=threshold,
        config=cal.CalibrationConfig(),
        model_path=model_path,
        scaler=SCALER,
        features=cal_features,
        training_records=48,
        validation_records=12,
        validation_statistics=cal.error_statistics(ERRORS),
        validation_exceedance=cal.exceedance(ERRORS, threshold),
    )
    calibration.update(overrides or {})
    path = tmp_path / "calibration.json"
    cal.write_json_atomic(path, calibration)
    return path, model_path


def test_valid_calibration_is_loaded(tmp_path):
    path, model_path = write_calibration(tmp_path)
    loaded, reason = cal.load_calibration(path, model_path, SCALER, cal_features)

    assert reason is None
    assert loaded["threshold"] == 0.04
    assert loaded["method"] == "percentile(q=95)"
    assert loaded["source"] == "validation"


def test_calibration_rejected_when_model_changes(tmp_path):
    path, model_path = write_calibration(tmp_path)
    model_path.write_bytes(b"retrained-model")

    loaded, reason = cal.load_calibration(path, model_path, SCALER, cal_features)
    assert loaded is None
    assert "different model file" in reason


def test_calibration_rejected_when_scaler_changes(tmp_path):
    path, model_path = write_calibration(tmp_path)
    other = {**SCALER, "mean": [1.5] * 6}

    loaded, reason = cal.load_calibration(path, model_path, other, cal_features)
    assert loaded is None
    assert "different scaler" in reason


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"features": ["ping_ms"]}, "features"),
        ({"schema_version": 99}, "schema"),
        ({"model": "Other"}, "different model"),
        ({"threshold": -1}, "non-negative"),
        ({"threshold": None}, "missing or invalid"),
    ],
)
def test_incompatible_calibration_is_rejected(tmp_path, overrides, message):
    path, model_path = write_calibration(tmp_path, overrides)
    loaded, reason = cal.load_calibration(path, model_path, SCALER, cal_features)
    assert loaded is None
    assert message in reason


def test_missing_or_corrupt_calibration(tmp_path):
    model_path = tmp_path / "model.pt"
    model_path.write_bytes(b"x")
    loaded, reason = cal.load_calibration(
        tmp_path / "none.json", model_path, SCALER, cal_features
    )
    assert loaded is None and "No calibration" in reason

    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    loaded, reason = cal.load_calibration(broken, model_path, SCALER, cal_features)
    assert loaded is None and "could not be read" in reason


# ------------------------------------------------------------
# Calibration pipeline (trains a small model)
# ------------------------------------------------------------

def test_model_is_trained_on_training_records_only(records, monkeypatch):
    seen = {}
    original = ai_engine.train_autoencoder

    def spy(training, scaler, **kwargs):
        seen["timestamps"] = [item["timestamp"] for item in training]
        seen["scaler"] = scaler
        return original(training, scaler, **kwargs)

    monkeypatch.setattr(ai_engine, "train_autoencoder", spy)
    report = calibrate(records)
    training, validation = cal.chronological_split(records, 0.2)

    assert report["success"] is True
    assert seen["timestamps"] == [item["timestamp"] for item in training]
    assert not set(seen["timestamps"]) & {item["timestamp"] for item in validation}
    # The scaler is fitted on training records only.
    assert seen["scaler"] == ai_engine.calculate_scaler(training)
    assert report["training_records"] == 48
    assert report["validation_records"] == 12
    assert report["training_period"]["end"] < report["validation_period"]["start"]


def test_threshold_comes_from_validation_errors(records, artifact_paths):
    report = calibrate(records, artifact_paths, save=True)
    _, validation = cal.chronological_split(records, 0.2)

    model = ai_engine.TransformerAutoencoder()
    model.load_state_dict(torch.load(artifact_paths["model_path"], weights_only=True))
    scaler = json.loads(artifact_paths["scaler_path"].read_text(encoding="utf-8"))
    errors = ai_engine.anomaly_reconstruction_errors(model, scaler, validation)

    assert report["selected"]["threshold"] == pytest.approx(
        float(np.percentile(errors, 95)), rel=1e-6
    )
    assert report["validation_error_statistics"]["count"] == 12
    assert report["selected"]["validation"]["records_above_threshold"] == 1


def test_calibration_is_reproducible(records):
    first = calibrate(records)
    second = calibrate(records)

    assert first["selected"]["threshold"] == second["selected"]["threshold"]
    assert first["comparison"] == second["comparison"]
    assert first["config"]["seed"] == 7


def test_configurable_strategy(records):
    report = calibrate(records, strategy="mad", params={"k": 2.5})

    assert report["selected"]["method"] == "mad(k=2.5)"
    labels = [row["label"] for row in report["comparison"]]
    assert "percentile(q=95)" in labels and "mean_std(k=2)" in labels


def test_unknown_strategy_fails_before_training(records, monkeypatch):
    monkeypatch.setattr(
        ai_engine,
        "train_autoencoder",
        lambda *args, **kwargs: pytest.fail("must not train"),
    )
    with pytest.raises(ValueError):
        calibrate(records, strategy="magic", params={})


def test_insufficient_data_returns_clear_message(records, artifact_paths):
    report = calibrate(records[:30], artifact_paths, save=True)

    assert report["success"] is False
    assert "Insufficient data" in report["message"]
    assert not artifact_paths["calibration_path"].exists()


def test_report_without_labels_has_no_metrics(records):
    report = calibrate(records)

    assert report["selected"]["labelled_metrics"] is None
    assert any("No labelled anomalies" in item for item in report["limitations"])
    assert report["saved"] is False


def test_report_with_labels_has_metrics(records):
    _, validation = cal.chronological_split(records, 0.2)
    labels = {item["timestamp"]: False for item in validation}
    labels[validation[-1]["timestamp"]] = True
    # A label on a training record must not be used.
    labels[records[0]["timestamp"]] = True

    metrics = calibrate(records, labels=labels)["selected"]["labelled_metrics"]

    assert metrics["labelled_records"] == 12
    assert metrics["true_positives"] + metrics["false_negatives"] == 1


def test_save_false_leaves_artifacts_untouched(records, artifact_paths):
    calibrate(records, artifact_paths)
    assert not any(path.exists() for path in artifact_paths.values())


def test_saved_artifacts_are_consistent(records, artifact_paths):
    report = calibrate(records, artifact_paths, save=True)
    scaler = json.loads(artifact_paths["scaler_path"].read_text(encoding="utf-8"))

    loaded, reason = cal.load_calibration(
        artifact_paths["calibration_path"],
        artifact_paths["model_path"],
        scaler,
        ai_engine.FEATURES,
    )
    assert reason is None
    assert loaded["threshold"] == pytest.approx(report["selected"]["threshold"])
    assert loaded["validation_records"] == 12
    assert report["saved"] is True


def test_train_anomaly_model_saves_calibrated_artifacts(
    records, artifact_paths, monkeypatch
):
    monkeypatch.setattr(ai_engine, "load_network_data", lambda: records)
    monkeypatch.setattr(ai_engine, "ANOMALY_MODEL_PATH", artifact_paths["model_path"])
    monkeypatch.setattr(ai_engine, "SCALER_PATH", artifact_paths["scaler_path"])
    monkeypatch.setattr(
        ai_engine, "CALIBRATION_PATH", artifact_paths["calibration_path"]
    )

    result = ai_engine.train_anomaly_model(epochs=2)

    assert result["success"] is True
    assert result["training_records"] == 48
    assert result["threshold_method"] == "percentile(q=95)"
    assert all(path.exists() for path in artifact_paths.values())


# ------------------------------------------------------------
# Serving
# ------------------------------------------------------------

@pytest.fixture
def isolated_main(monkeypatch, artifact_paths, records):
    for name in (
        "ai_anomaly_model",
        "ai_scaler",
        "ai_anomaly_threshold",
        "ai_anomaly_threshold_info",
        "AI_MODELS_READY",
        "AI_MODELS_MESSAGE",
    ):
        monkeypatch.setattr(main, name, getattr(main, name))
    monkeypatch.setattr(main, "AI_ANOMALY_MODEL_PATH", artifact_paths["model_path"])
    monkeypatch.setattr(main, "AI_SCALER_PATH", artifact_paths["scaler_path"])
    monkeypatch.setattr(main, "AI_CALIBRATION_PATH", artifact_paths["calibration_path"])
    monkeypatch.setattr(main, "load_network_data", lambda: records)
    return artifact_paths


def test_server_uses_calibrated_threshold(records, isolated_main):
    report = calibrate(records, isolated_main, save=True)

    ready, _ = main.load_ai_models()

    assert ready is True
    assert main.ai_anomaly_threshold == pytest.approx(report["selected"]["threshold"])
    assert main.ai_anomaly_threshold_info["source"] == "validation_calibration"
    assert main.ai_anomaly_threshold_info["method"] == "percentile(q=95)"


def test_server_ignores_mismatched_calibration(records, isolated_main):
    calibrate(records, isolated_main, save=True)
    scaler = json.loads(isolated_main["scaler_path"].read_text(encoding="utf-8"))
    scaler["mean"][0] += 1.0
    isolated_main["scaler_path"].write_text(json.dumps(scaler), encoding="utf-8")

    ready, _ = main.load_ai_models()

    assert ready is True
    assert main.ai_anomaly_threshold_info["source"] == "legacy_training_errors"
    assert "different scaler" in main.ai_anomaly_threshold_info["calibration_message"]


def test_server_without_calibration_keeps_legacy_threshold(records, isolated_main):
    calibrate(records, isolated_main, save=True)
    isolated_main["calibration_path"].unlink()

    ready, _ = main.load_ai_models()
    model = main.ai_anomaly_model
    scaler = main.ai_scaler
    errors = ai_engine.anomaly_reconstruction_errors(model, scaler, records)

    assert ready is True
    assert main.ai_anomaly_threshold == pytest.approx(
        main.legacy_training_threshold(errors), rel=1e-5
    )
    assert main.ai_anomaly_threshold_info["source"] == "legacy_training_errors"


def test_api_reports_threshold_source(client, records, isolated_main, monkeypatch):
    calibrate(records, isolated_main, save=True)
    ready, message = main.load_ai_models()
    monkeypatch.setattr(main, "AI_MODELS_READY", ready)
    monkeypatch.setattr(main, "AI_MODELS_MESSAGE", message)

    anomaly = client.get("/api/ai/anomaly").json()
    assert anomaly["threshold_source"] == "validation_calibration"
    assert anomaly["threshold_method"] == "percentile(q=95)"
    assert anomaly["threshold"] == round(main.ai_anomaly_threshold, 6)
    assert isinstance(anomaly["anomaly"], bool)

    status = client.get("/api/ai/status").json()["anomaly_model"]
    assert status["threshold_source"] == "validation_calibration"
    assert status["calibration"]["validation_records"] == 12


# ------------------------------------------------------------
# Command line
# ------------------------------------------------------------

def test_cli_writes_report_without_touching_models(
    records, tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(ai_engine, "load_network_data", lambda: records)
    report_path = tmp_path / "report.json"

    code = calibrate_anomaly.main(
        ["--epochs", "2", "--strategy", "mean_std", "--report", str(report_path)]
    )

    assert code == 0
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["selected"]["method"] == "mean_std(k=2)"
    assert report["saved"] is False
    assert "Artifacts not changed" in capsys.readouterr().out


def test_cli_reports_insufficient_data(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(ai_engine, "load_network_data", lambda: make_records(20))

    assert calibrate_anomaly.main(["--report", str(tmp_path / "r.json")]) == 1
    assert "Insufficient data" in capsys.readouterr().out


def test_cli_label_formats(tmp_path):
    as_object = tmp_path / "object.json"
    as_object.write_text(json.dumps({"2026-11-01T00:00:00Z": True}), encoding="utf-8")
    as_list = tmp_path / "list.json"
    as_list.write_text(
        json.dumps([{"timestamp": "2026-11-01T05:30:00+05:30", "anomaly": False}]),
        encoding="utf-8",
    )

    assert calibrate_anomaly.load_labels(as_object) == {
        "2026-11-01T00:00:00.000Z": True
    }
    assert calibrate_anomaly.load_labels(as_list) == {
        "2026-11-01T00:00:00.000Z": False
    }

    invalid = tmp_path / "invalid.json"
    invalid.write_text(json.dumps({"bad": "yes"}), encoding="utf-8")
    with pytest.raises(ValueError):
        calibrate_anomaly.load_labels(invalid)
