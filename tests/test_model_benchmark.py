"""Tests for the reproducible connectivity model benchmark."""

import sqlite3

import numpy as np
import pytest

from backend import model_benchmark as benchmark
from backend.model_config import build_production_prediction_model


def _create_database(path, rows):
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE network_tests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                download_mbps REAL,
                upload_mbps REAL,
                ping_ms REAL,
                jitter_ms REAL,
                packet_loss REAL,
                connectivity_score REAL
            )
            """
        )
        connection.executemany(
            """
            INSERT INTO network_tests (
                timestamp, download_mbps, upload_mbps, ping_ms,
                jitter_ms, packet_loss, connectivity_score
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )


def _valid_rows(count):
    rows = []
    for index in range(count):
        rows.append(
            (
                f"2026-01-{(index // 24) + 1:02d}T{index % 24:02d}:00:00",
                50.0 + index,
                20.0 + index / 2,
                15.0 + index / 10,
                2.0 + index / 20,
                0.5,
                80.0 - index / 2,
            )
        )
    return rows


def test_load_complete_records_excludes_null_and_non_finite(tmp_path):
    database = tmp_path / "history.db"
    rows = _valid_rows(4)
    rows[1] = (rows[1][0], None, *rows[1][2:])
    rows[2] = (rows[2][0], float("nan"), *rows[2][2:])
    _create_database(database, rows)

    records, total = benchmark.load_complete_records(database)

    assert total == 4
    assert len(records) == 2
    assert records[0]["timestamp"] < records[1]["timestamp"]
    assert np.isfinite(records[0]["values"]).all()



def test_duplicate_timestamps_use_database_id_as_stable_tiebreaker(tmp_path):
    database = tmp_path / "history.db"
    rows = _valid_rows(3)
    rows[1] = (rows[0][0], *rows[1][1:])
    _create_database(database, rows)

    records, _ = benchmark.load_complete_records(database)

    assert [record["values"][0] for record in records] == [
        rows[0][1],
        rows[1][1],
        rows[2][1],
    ]

def test_build_supervised_samples_uses_previous_eight_records():
    rows = _valid_rows(12)
    records = [
        {"timestamp": row[0], "values": np.asarray(row[1:], dtype=float)}
        for row in rows
    ]

    X, y, target_indices = benchmark.build_supervised_samples(records)

    assert X.shape == (4, 8 * len(benchmark.FEATURE_COLUMNS))
    assert target_indices.tolist() == [8, 9, 10, 11]
    assert y.tolist() == [row[-1] for row in rows[8:]]
    # First sample contains rows 0..7 only; target row 8 is not an input.
    assert X[0, 0] == rows[0][1]
    assert X[0, -1] == rows[7][-1]


def test_engineered_features_are_based_only_on_prior_rows():
    rows = _valid_rows(11)
    records = [
        {"timestamp": row[0], "values": np.asarray(row[1:], dtype=float)}
        for row in rows
    ]
    original = benchmark.build_engineered_features(records)

    # Changing a target row cannot change that row's own features.
    changed = list(records)
    changed[8] = {
        "timestamp": records[8]["timestamp"],
        "values": records[8]["values"].copy(),
    }
    changed[8]["values"][-1] = -999.0
    updated = benchmark.build_engineered_features(changed)

    assert np.array_equal(original[0], updated[0])
    assert not np.array_equal(original[1], updated[1])


def test_chronological_split_keeps_later_targets_out_of_training():
    target_indices = np.arange(8, 22)

    split_index, train_mask, test_mask = benchmark.chronological_split(
        record_count=22,
        target_indices=target_indices,
    )

    assert split_index == 17
    assert target_indices[train_mask].tolist() == list(range(8, 17))
    assert target_indices[test_mask].tolist() == list(range(17, 22))
    assert target_indices[train_mask].max() < split_index


def test_metrics_calculate_mae_rmse_and_r2():
    metrics = benchmark.calculate_metrics(
        np.asarray([1.0, 2.0, 3.0]),
        np.asarray([1.0, 2.0, 2.0]),
    )

    assert metrics["mae"] == pytest.approx(1 / 3)
    assert metrics["rmse"] == pytest.approx(np.sqrt(1 / 3))
    assert metrics["r2"] == pytest.approx(0.5)


def test_metrics_reports_undefined_r2_for_single_test_value():
    metrics = benchmark.calculate_metrics(
        np.asarray([5.0]),
        np.asarray([4.0]),
    )

    assert metrics["mae"] == 1.0
    assert metrics["rmse"] == 1.0
    assert metrics["r2"] is None


def test_tuning_is_skipped_for_small_training_sets():
    result = benchmark.tune_hist_gradient_boosting(
        np.zeros((9, 4)),
        np.arange(9, dtype=float),
    )

    assert result["status"] == "skipped_insufficient_training_samples"
    assert result["best_params"] is None



def test_tuning_uses_temporal_cross_validation_with_enough_samples():
    features = np.arange(30 * 4, dtype=float).reshape(30, 4)
    targets = np.linspace(20.0, 80.0, 30)

    result = benchmark.tune_hist_gradient_boosting(features, targets)

    assert result["status"] == "completed"
    assert result["validation"] == (
        "3-fold expanding TimeSeriesSplit on training samples only"
    )
    assert result["best_params"] is not None
    assert result["best_validation_mae"] >= 0.0

def test_run_benchmark_compares_all_models_on_same_test_samples(tmp_path):
    database = tmp_path / "history.db"
    _create_database(database, _valid_rows(45))

    report = benchmark.run_benchmark(database)

    assert report["dataset"]["complete_records"] == 45
    assert report["dataset"]["test_samples"] == 9
    assert report["models"]
    assert all(
        result["test_samples"] == 9
        for result in report["models"].values()
    )
    assert report["best_by_rmse"] in report["models"]
    assert report["data_sufficiency"]["status"] == "preliminary_small_sample"


def test_run_benchmark_reports_production_model_and_score_bounds(tmp_path):
    database = tmp_path / "history.db"
    _create_database(database, _valid_rows(45))

    report = benchmark.run_benchmark(database)

    assert report["protocol"]["prediction_bounds"] == [0.0, 100.0]
    assert report["protocol"]["production_model"]["name"] == (
        "HistGradientBoostingRegressor"
    )
    assert report["models"]["hist_gradient_boosting_current"][
        "matches_production_configuration"
    ] is True

def test_run_benchmark_does_not_modify_database(tmp_path):
    database = tmp_path / "history.db"
    _create_database(database, _valid_rows(35))

    with sqlite3.connect(database) as connection:
        before = connection.execute("SELECT COUNT(*) FROM network_tests").fetchone()[0]

    benchmark.run_benchmark(database)

    with sqlite3.connect(database) as connection:
        after = connection.execute("SELECT COUNT(*) FROM network_tests").fetchone()[0]

    assert before == after == 35


def test_load_complete_records_excludes_out_of_range_measurements(tmp_path):
    database = tmp_path / "history.db"
    rows = _valid_rows(4)
    rows[1] = (rows[1][0], -1.0, *rows[1][2:])
    rows[2] = (rows[2][0], *rows[2][1:5], 101.0, rows[2][6])
    rows[3] = (rows[3][0], *rows[3][1:5], rows[3][5], 101.0)
    _create_database(database, rows)

    records, total = benchmark.load_complete_records(database)

    assert total == 4
    assert len(records) == 1
    assert records[0]["values"][0] >= 0.0


def test_current_model_matches_production_configuration():
    benchmark_model = benchmark._current_model()
    production_model = build_production_prediction_model()

    assert benchmark_model.get_params() == production_model.get_params()
    assert benchmark.PRODUCTION_HIST_GRADIENT_BOOSTING_PARAMS == {
        "max_iter": 300,
        "learning_rate": 0.05,
        "max_leaf_nodes": 15,
        "l2_regularization": 0.1,
        "random_state": 42,
    }


def test_prediction_constraints_keep_scores_within_application_range():
    predictions = benchmark.constrain_connectivity_predictions(
        np.asarray([-12.0, 45.0, 128.0])
    )

    assert predictions.tolist() == [0.0, 45.0, 100.0]



def test_measurement_validation_rejects_malformed_rows():
    assert not benchmark.is_valid_measurement_row(["not-a-number"])
    assert not benchmark.is_valid_measurement_row([1.0, 2.0])


def test_prediction_constraints_reject_non_finite_values():
    with pytest.raises(ValueError, match="finite values"):
        benchmark.constrain_connectivity_predictions(
            np.asarray([float("nan")])
        )

def test_negative_r2_is_valid_but_error_metrics_are_non_negative():
    metrics = benchmark.calculate_metrics(
        np.asarray([1.0, 2.0, 3.0]),
        np.asarray([10.0, 10.0, 10.0]),
    )

    assert metrics["r2"] < 0.0
    assert metrics["mae"] >= 0.0
    assert metrics["rmse"] >= 0.0


def test_missing_database_has_actionable_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="database not found"):
        benchmark.load_complete_records(tmp_path / "missing.db")


def test_insufficient_records_are_rejected():
    records = [
        {"timestamp": str(index), "values": np.zeros(6)}
        for index in range(benchmark.SEQUENCE_LENGTH)
    ]

    with pytest.raises(benchmark.BenchmarkDataError, match="Need at least"):
        benchmark.build_supervised_samples(records)
