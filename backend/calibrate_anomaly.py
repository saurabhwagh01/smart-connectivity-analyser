"""
Smart Internet Connectivity Analyser
Anomaly threshold calibration (issue #40)

Trains the Transformer Autoencoder on the earliest complete records,
calibrates the anomaly threshold on the held-out latest records, compares
threshold strategies and writes a reproducible report.

Run from the project root:

    # Report only: existing model files are not touched.
    python backend/calibrate_anomaly.py

    # Report, and replace the served model, scaler and threshold together.
    python backend/calibrate_anomaly.py --save

    # Other strategies, split or labelled anomalies.
    python backend/calibrate_anomaly.py --strategy mad --k 3
    python backend/calibrate_anomaly.py --strategy percentile --q 99
    python backend/calibrate_anomaly.py --labels labels.json

``labels.json`` is optional. It maps record timestamps to true (anomaly)
or false (normal), either as an object or as a list of
``{"timestamp": ..., "anomaly": ...}`` items. Without labels, precision,
recall and F1 are not calculated.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__:
    from . import ai_engine
    from . import anomaly_calibration as calibration
    from .timestamps import to_canonical_utc
else:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import ai_engine
    import anomaly_calibration as calibration
    from timestamps import to_canonical_utc


def load_labels(path):
    """Read labels keyed by canonical UTC timestamp."""

    raw = json.loads(Path(path).read_text(encoding="utf-8"))

    if isinstance(raw, dict):
        items = raw.items()
    elif isinstance(raw, list):
        items = (
            (item.get("timestamp"), item.get("anomaly"))
            for item in raw
            if isinstance(item, dict)
        )
    else:
        raise ValueError("Labels must be a JSON object or list.")

    labels = {}
    for timestamp, label in items:
        canonical = to_canonical_utc(timestamp)
        if canonical is None or not isinstance(label, bool):
            raise ValueError(
                f"Invalid label entry: {timestamp!r} -> {label!r}. "
                "Use a valid timestamp and true/false."
            )
        labels[canonical] = label
    return labels


def build_config(args):
    if args.strategy == "percentile":
        params = {"q": args.q}
    else:
        params = {"k": args.k if args.k is not None else (
            2.0 if args.strategy == "mean_std" else 3.0
        )}

    return calibration.CalibrationConfig(
        strategy=args.strategy,
        params=params,
        validation_ratio=args.validation_ratio,
        seed=args.seed,
        epochs=args.epochs,
    )


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[1])
    parser.add_argument(
        "--strategy",
        choices=sorted(calibration.THRESHOLD_STRATEGIES),
        default="percentile",
    )
    parser.add_argument("--q", type=float, default=95.0,
                        help="Percentile for the percentile strategy.")
    parser.add_argument("--k", type=float, default=None,
                        help="Multiplier for mean_std (default 2) or mad (default 3).")
    parser.add_argument("--validation-ratio", type=float,
                        default=calibration.DEFAULT_VALIDATION_RATIO)
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--labels", type=Path, default=None)
    parser.add_argument("--report", type=Path,
                        default=ai_engine.CALIBRATION_REPORT_PATH)
    parser.add_argument("--save", action="store_true",
                        help="Replace the served model, scaler and calibration.")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    config = build_config(args)
    labels = load_labels(args.labels) if args.labels else None

    report = ai_engine.calibrate_anomaly_model(
        config,
        labels=labels,
        save=args.save,
    )

    if not report["success"]:
        print(report["message"])
        return 1

    calibration.write_json_atomic(args.report, report)

    selected = report["selected"]
    print("=" * 60)
    print("ANOMALY THRESHOLD CALIBRATION")
    print("=" * 60)
    print(f"Training records:   {report['training_records']}")
    print(f"Validation records: {report['validation_records']}")
    print(f"Selected method:    {selected['method']}")
    print(f"Threshold:          {selected['threshold']:.6f}")
    print(
        "Validation above:   "
        f"{selected['validation']['records_above_threshold']}"
        f"/{report['validation_records']} "
        f"({selected['validation']['percent_above_threshold']:.1f}%)"
    )
    print()
    print("Strategy comparison (validation errors):")
    for row in report["comparison"]:
        print(
            f"  {row['label']:<24} threshold={row['threshold']:.6f} "
            f"above={row['percent_above_threshold']:.1f}%"
        )
    print()
    print(f"Report: {args.report}")
    print(
        "Artifacts saved." if report["saved"]
        else "Artifacts not changed (use --save to apply)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
