"""Multi-horizon connectivity forecasting and degradation risk scoring."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
import re
import statistics
from typing import Any

DEFAULT_HORIZONS: tuple[str, ...] = ("1h", "6h", "24h")
MAX_HORIZON_HOURS = 168
MAX_HORIZON_COUNT = 10
MIN_RECORDS_FOR_TREND = 3
MIN_WINDOWS_FOR_TREND = 2
TREND_DAMPING = 0.85
CONFIDENCE_Z = 1.645
HORIZON_PATTERN = re.compile(r"^\s*(\d+)\s*h\s*$", re.IGNORECASE)

FORECAST_METRICS: dict[str, dict[str, Any]] = {
    "download_mbps": {
        "min": 0.0,
        "max": None,
        "higher_is_better": True,
        "unit": "Mbps",
        "floor_std": 1.5,
    },
    "upload_mbps": {
        "min": 0.0,
        "max": None,
        "higher_is_better": True,
        "unit": "Mbps",
        "floor_std": 0.8,
    },
    "ping_ms": {
        "min": 0.0,
        "max": None,
        "higher_is_better": False,
        "unit": "ms",
        "floor_std": 2.5,
    },
    "jitter_ms": {
        "min": 0.0,
        "max": None,
        "higher_is_better": False,
        "unit": "ms",
        "floor_std": 1.0,
    },
    "packet_loss": {
        "min": 0.0,
        "max": 100.0,
        "higher_is_better": False,
        "unit": "%",
        "floor_std": 0.4,
    },
    "connectivity_score": {
        "min": 0.0,
        "max": 100.0,
        "higher_is_better": True,
        "unit": "/100",
        "floor_std": 3.0,
    },
}


def parse_horizons(horizons_param: str | None) -> list[tuple[str, int]]:
    """Parse and validate a comma-separated list of forecast horizons (e.g. '1h,6h,24h')."""
    if horizons_param is None:
        return [(h, int(h[:-1])) for h in DEFAULT_HORIZONS]

    raw_items = [item.strip() for item in horizons_param.split(",")]
    if not raw_items or any(item == "" for item in raw_items):
        raise ValueError(
            "horizons must be a comma-separated list of positive hour values (e.g. 1h,6h,24h)"
        )

    if len(raw_items) > MAX_HORIZON_COUNT:
        raise ValueError(
            f"At most {MAX_HORIZON_COUNT} horizons may be requested at once"
        )

    parsed: list[tuple[str, int]] = []
    seen_hours: set[int] = set()
    for item in raw_items:
        match = HORIZON_PATTERN.match(item)
        if not match:
            raise ValueError(
                f"Invalid horizon '{item}'. Expected format like '1h', '6h', or '24h'."
            )
        hours = int(match.group(1))
        if hours < 1 or hours > MAX_HORIZON_HOURS:
            raise ValueError(
                f"Horizon '{item}' must be between 1h and {MAX_HORIZON_HOURS}h."
            )
        if hours not in seen_hours:
            seen_hours.add(hours)
            parsed.append((f"{hours}h", hours))

    return parsed


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _clean_metric(value: Any, spec: dict[str, Any]) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(num):
        return None
    if num < spec["min"]:
        return None
    if spec["max"] is not None and num > spec["max"]:
        return None
    return num


def _clamp(value: float, spec: dict[str, Any]) -> float:
    bounded = max(spec["min"], value)
    if spec["max"] is not None:
        bounded = min(spec["max"], bounded)
    return bounded


def _normalize_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for row in records:
        ts = _parse_timestamp(row.get("timestamp"))
        if ts is None:
            continue
        metrics = {
            field: _clean_metric(row.get(field), spec)
            for field, spec in FORECAST_METRICS.items()
        }
        if all(val is None for val in metrics.values()):
            continue
        normalized.append({"timestamp": ts, "metrics": metrics})

    normalized.sort(key=lambda item: item["timestamp"])
    return normalized


def _aggregate_windows(
    records: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """Group chronologically sorted records into fixed rolling time buckets."""
    if not records:
        return [], 60

    span_seconds = (records[-1]["timestamp"] - records[0]["timestamp"]).total_seconds()
    bucket_minutes = 60 if span_seconds >= 7200 else 15
    bucket_seconds = bucket_minutes * 60

    buckets: dict[int, dict[str, Any]] = {}
    for rec in records:
        epoch = rec["timestamp"].timestamp()
        bucket_id = int(epoch // bucket_seconds)
        entry = buckets.get(bucket_id)
        if entry is None:
            bucket_ts = datetime.fromtimestamp(
                (bucket_id + 0.5) * bucket_seconds, tz=timezone.utc
            )
            entry = {
                "timestamp": bucket_ts,
                "count": 0,
                "values": {field: [] for field in FORECAST_METRICS},
            }
            buckets[bucket_id] = entry

        entry["count"] += 1
        for field, val in rec["metrics"].items():
            if val is not None:
                entry["values"][field].append(val)

    windows: list[dict[str, Any]] = []
    for bucket_id in sorted(buckets):
        entry = buckets[bucket_id]
        means = {
            field: (
                sum(vals) / len(vals) if vals else None
            )
            for field, vals in entry["values"].items()
        }
        windows.append(
            {
                "timestamp": entry["timestamp"],
                "count": entry["count"],
                "metrics": means,
            }
        )

    return windows, bucket_minutes


def _summarize_rolling_windows(records: list[dict[str, Any]]) -> dict[str, Any]:
    if not records:
        return {
            label: {"count": 0, **{field: None for field in FORECAST_METRICS}}
            for label in ("1h", "6h", "24h")
        }

    anchor = records[-1]["timestamp"]
    summary: dict[str, Any] = {}
    for hours in (1, 6, 24):
        cutoff = anchor - timedelta(hours=hours)
        subset = [rec for rec in records if rec["timestamp"] >= cutoff]
        entry: dict[str, Any] = {"count": len(subset)}
        for field in FORECAST_METRICS:
            vals = [
                rec["metrics"][field]
                for rec in subset
                if rec["metrics"][field] is not None
            ]
            entry[field] = round(sum(vals) / len(vals), 2) if vals else None
        summary[f"{hours}h"] = entry
    return summary


def _weighted_slope_and_residuals(
    points: list[tuple[float, float]],
) -> tuple[float, float, float]:
    """Return (ewma_level, slope_per_hour, residual_std) over (hour_offset, value)."""
    n = len(points)
    weights = [0.75 ** (n - 1 - i) for i in range(n)]
    w_sum = sum(weights)

    mean_x = sum(w * x for w, (x, _) in zip(weights, points)) / w_sum
    mean_y = sum(w * y for w, (_, y) in zip(weights, points)) / w_sum

    denom = sum(w * (x - mean_x) ** 2 for w, (x, _) in zip(weights, points))
    if denom <= 1e-9:
        slope = 0.0
    else:
        slope = sum(
            w * (x - mean_x) * (y - mean_y) for w, (x, y) in zip(weights, points)
        ) / denom

    # Exponentially weighted baseline level anchored at recent windows.
    level = points[0][1]
    alpha = 0.45
    for _, y in points[1:]:
        level = alpha * y + (1.0 - alpha) * level

    residuals = [y - (mean_y + slope * (x - mean_x)) for x, y in points]
    if len(residuals) >= 2:
        res_std = statistics.stdev(residuals)
    else:
        res_std = 0.0

    return level, slope, res_std


def _trend_direction(
    predicted: float,
    baseline: float,
    spec: dict[str, Any],
) -> str:
    delta = predicted - baseline
    tol = max(spec["floor_std"] * 0.5, abs(baseline) * 0.03)
    if abs(delta) <= tol:
        return "stable"
    if spec["higher_is_better"]:
        return "improving" if delta > 0 else "declining"
    return "improving" if delta < 0 else "worsening"


def _forecast_metric(
    windows: list[dict[str, Any]],
    hours_ahead: int,
    spec: dict[str, Any],
    field: str,
    use_fallback: bool,
) -> dict[str, Any]:
    series = [
        (w["timestamp"], w["metrics"][field])
        for w in windows
        if w["metrics"][field] is not None
    ]
    if not series:
        return {
            "predicted": None,
            "lower": None,
            "upper": None,
            "baseline": None,
            "unit": spec["unit"],
            "trend": "unavailable",
        }

    t0 = series[0][0]
    points = [((ts - t0).total_seconds() / 3600.0, val) for ts, val in series]
    latest_val = points[-1][1]

    if use_fallback or len(points) < MIN_WINDOWS_FOR_TREND:
        baseline = sum(v for _, v in points) / len(points)
        predicted = _clamp(latest_val, spec)
        sample_std = (
            statistics.stdev([v for _, v in points]) if len(points) >= 2 else 0.0
        )
        half_width = max(
            sample_std,
            spec["floor_std"],
            abs(predicted) * 0.12,
        ) * math.sqrt(1.0 + hours_ahead / 6.0)
        lower = _clamp(predicted - half_width, spec)
        upper = _clamp(predicted + half_width, spec)
        if lower > predicted:
            lower = predicted
        if upper < predicted:
            upper = predicted
        return {
            "predicted": round(predicted, 2),
            "lower": round(lower, 2),
            "upper": round(upper, 2),
            "baseline": round(baseline, 2),
            "unit": spec["unit"],
            "trend": "stable" if len(points) >= 2 else "insufficient_data",
        }

    level, slope, res_std = _weighted_slope_and_residuals(points)
    damped_steps = (1.0 - TREND_DAMPING ** hours_ahead) / (1.0 - TREND_DAMPING)
    predicted = _clamp(level + slope * damped_steps, spec)

    sigma = max(res_std, spec["floor_std"])
    half_width = CONFIDENCE_Z * sigma * math.sqrt(1.0 + 0.35 * hours_ahead)
    lower = _clamp(predicted - half_width, spec)
    upper = _clamp(predicted + half_width, spec)
    if lower > predicted:
        lower = predicted
    if upper < predicted:
        upper = predicted

    return {
        "predicted": round(predicted, 2),
        "lower": round(lower, 2),
        "upper": round(upper, 2),
        "baseline": round(level, 2),
        "unit": spec["unit"],
        "trend": _trend_direction(predicted, level, spec),
    }


def _score_degradation_risk(
    horizon_label: str,
    metrics: dict[str, dict[str, Any]],
    fallback_used: bool,
) -> tuple[float | None, str, list[str]]:
    if fallback_used:
        return (
            None,
            "Insufficient Data",
            [
                "Forecast uses sparse-history fallback; accuracy will improve as more tests are recorded."
            ],
        )

    score = 0.0
    reasons: list[str] = []

    conn = metrics.get("connectivity_score", {})
    pred_score = conn.get("predicted")
    base_score = conn.get("baseline")
    if pred_score is not None:
        if pred_score < 40:
            score += 45
            reasons.append(
                f"Connectivity score forecast is low ({pred_score:.1f}/100 at {horizon_label})."
            )
        elif pred_score < 60:
            score += 25
            reasons.append(
                f"Connectivity score forecast dips below optimal ({pred_score:.1f}/100 at {horizon_label})."
            )
        elif pred_score < 75:
            score += 10

        if base_score is not None:
            drop = base_score - pred_score
            if drop >= 15:
                score += 25
                reasons.append(
                    f"Connectivity score projected to decline by {drop:.1f} pts over {horizon_label}."
                )
            elif drop >= 7:
                score += 12
                reasons.append(
                    f"Connectivity score trending down by {drop:.1f} pts over {horizon_label}."
                )

    ping = metrics.get("ping_ms", {})
    pred_ping = ping.get("predicted")
    base_ping = ping.get("baseline")
    if pred_ping is not None:
        if pred_ping >= 150:
            score += 25
            reasons.append(
                f"High ping latency forecast ({pred_ping:.1f} ms at {horizon_label})."
            )
        elif pred_ping >= 80:
            score += 15
            reasons.append(
                f"Elevated ping latency forecast ({pred_ping:.1f} ms at {horizon_label})."
            )
        if base_ping is not None and pred_ping - base_ping >= 25:
            score += 10
            reasons.append(
                f"Ping latency trending up by {pred_ping - base_ping:.1f} ms."
            )

    loss = metrics.get("packet_loss", {})
    pred_loss = loss.get("predicted")
    if pred_loss is not None:
        if pred_loss >= 5.0:
            score += 30
            reasons.append(
                f"High packet loss forecast ({pred_loss:.2f}% at {horizon_label})."
            )
        elif pred_loss >= 2.0:
            score += 18
            reasons.append(
                f"Elevated packet loss forecast ({pred_loss:.2f}% at {horizon_label})."
            )
        elif pred_loss >= 0.8:
            score += 8

    jitter = metrics.get("jitter_ms", {})
    pred_jitter = jitter.get("predicted")
    if pred_jitter is not None:
        if pred_jitter >= 30:
            score += 15
            reasons.append(
                f"High jitter forecast ({pred_jitter:.1f} ms at {horizon_label})."
            )
        elif pred_jitter >= 15:
            score += 8

    dl = metrics.get("download_mbps", {})
    pred_dl = dl.get("predicted")
    base_dl = dl.get("baseline")
    if pred_dl is not None and base_dl is not None and base_dl > 0:
        rel_drop = (base_dl - pred_dl) / base_dl
        if rel_drop >= 0.35:
            score += 20
            reasons.append(
                f"Download speed projected to drop by {rel_drop * 100:.0f}% over {horizon_label}."
            )
        elif rel_drop >= 0.15:
            score += 10

    clamped = round(min(100.0, max(0.0, score)), 1)
    if clamped >= 65:
        level = "High"
    elif clamped >= 35:
        level = "Moderate"
    else:
        level = "Low"

    if not reasons:
        reasons.append("Projected connection metrics remain stable with low degradation risk.")

    return clamped, level, reasons


def generate_connectivity_forecast(
    records: list[dict[str, Any]],
    horizons: list[tuple[str, int]] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Generate multi-horizon connectivity forecasts and degradation risk scores."""
    selected_horizons = horizons or [(h, int(h[:-1])) for h in DEFAULT_HORIZONS]
    normalized = _normalize_records(records)
    windows, bucket_minutes = _aggregate_windows(normalized)
    rolling_summary = _summarize_rolling_windows(normalized)

    total_records = len(normalized)
    window_count = len(windows)
    sufficient_history = (
        total_records >= MIN_RECORDS_FOR_TREND
        and window_count >= MIN_WINDOWS_FOR_TREND
    )
    fallback_used = not sufficient_history
    method = "rolling_trend_damped" if sufficient_history else "sparse_fallback"

    generated_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    anchor_time = normalized[-1]["timestamp"] if normalized else generated_at

    if total_records == 0:
        empty_metrics = {
            field: {
                "predicted": None,
                "lower": None,
                "upper": None,
                "baseline": None,
                "unit": spec["unit"],
                "trend": "unavailable",
            }
            for field, spec in FORECAST_METRICS.items()
        }
        horizon_entries = [
            {
                "horizon": label,
                "hours_ahead": hours,
                "target_timestamp": (
                    generated_at + timedelta(hours=hours)
                ).isoformat(),
                "degradation_risk": {"score": None, "level": "Insufficient Data"},
                "metrics": empty_metrics,
            }
            for label, hours in selected_horizons
        ]
        return {
            "success": True,
            "generated_at": generated_at.isoformat(),
            "history_summary": {
                "total_records": 0,
                "window_count": 0,
                "bucket_minutes": bucket_minutes,
                "sufficient_history": False,
                "fallback_used": True,
                "method": "sparse_fallback",
                "rolling_windows": rolling_summary,
            },
            "degradation_risk": {
                "score": None,
                "level": "Insufficient Data",
                "reasons": [
                    "Not enough historical measurements yet to generate a trend forecast."
                ],
            },
            "horizons": horizon_entries,
        }

    horizon_entries: list[dict[str, Any]] = []
    worst_score = -1.0
    worst_level = "Low"
    all_reasons: list[str] = []

    for label, hours in selected_horizons:
        metrics = {
            field: _forecast_metric(windows, hours, spec, field, fallback_used)
            for field, spec in FORECAST_METRICS.items()
        }
        risk_score, risk_level, reasons = _score_degradation_risk(
            label, metrics, fallback_used
        )
        if risk_score is not None and risk_score > worst_score:
            worst_score = risk_score
            worst_level = risk_level
        for reason in reasons:
            if reason not in all_reasons:
                all_reasons.append(reason)

        horizon_entries.append(
            {
                "horizon": label,
                "hours_ahead": hours,
                "target_timestamp": (
                    anchor_time + timedelta(hours=hours)
                ).isoformat(),
                "degradation_risk": {
                    "score": risk_score,
                    "level": risk_level,
                },
                "metrics": metrics,
            }
        )

    if fallback_used:
        overall_risk = {
            "score": None,
            "level": "Insufficient Data",
            "reasons": all_reasons[:4],
        }
    else:
        overall_risk = {
            "score": round(max(0.0, worst_score), 1),
            "level": worst_level,
            "reasons": all_reasons[:4],
        }

    return {
        "success": True,
        "generated_at": generated_at.isoformat(),
        "history_summary": {
            "total_records": total_records,
            "window_count": window_count,
            "bucket_minutes": bucket_minutes,
            "sufficient_history": sufficient_history,
            "fallback_used": fallback_used,
            "method": method,
            "rolling_windows": rolling_summary,
        },
        "degradation_risk": overall_risk,
        "horizons": horizon_entries,
    }
