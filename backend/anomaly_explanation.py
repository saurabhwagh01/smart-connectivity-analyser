import math


ANOMALY_METRICS = (
    ("download_mbps", "Download speed", "Mbps"),
    ("upload_mbps", "Upload speed", "Mbps"),
    ("ping_ms", "Ping", "ms"),
    ("jitter_ms", "Jitter", "ms"),
    ("packet_loss", "Packet loss", "%"),
)


def build_anomaly_explanation(
    features,
    values,
    normalized_values,
    reconstructed_values,
    scaler,
):
    """Build per-network-metric reconstruction-error diagnostics.

    ``contribution_percent`` is the share of the sum of squared normalized
    reconstruction errors attributable to each available valid metric:
    error_i^2 / sum(error_j^2) * 100.  It is not a probability and does not
    prove that a metric caused the anomaly.
    """
    diagnostics = []

    if not isinstance(features, (list, tuple)):
        features = ()
    if not isinstance(scaler, dict):
        scaler = {}

    scaler_features = scaler.get("features")
    if not isinstance(scaler_features, (list, tuple)):
        scaler_features = ()
    if (
        tuple(features) != tuple(scaler_features)
        or len(features) == 0
    ):
        return {
            "normalization": "relative_squared_reconstruction_error_shares",
            "contribution_percent_note": (
                "Percentages are relative squared reconstruction-error shares "
                "among available valid metrics. They are not probabilities "
                "and do not prove anomaly causation."
            ),
            "metrics": [],
        }

    metric_metadata = {
        feature: (name, unit)
        for feature, name, unit in ANOMALY_METRICS
    }
    mean_values = scaler.get("mean")
    std_values = scaler.get("std")
    if not isinstance(mean_values, (list, tuple)) or not isinstance(
        std_values, (list, tuple)
    ):
        mean_values = ()
        std_values = ()

    for index, feature in enumerate(features):
        metadata = metric_metadata.get(feature)
        if metadata is None:
            continue
        name, unit = metadata

        if (
            index >= len(values)
            or index >= len(normalized_values)
            or index >= len(reconstructed_values)
            or index >= len(mean_values)
            or index >= len(std_values)
        ):
            continue

        try:
            observed = float(values[index])
            normalized = float(normalized_values[index])
            reconstructed = float(reconstructed_values[index])
            mean = float(mean_values[index])
            scale = float(std_values[index])
        except (TypeError, ValueError):
            continue

        if not all(
            math.isfinite(value)
            for value in (observed, normalized, reconstructed, mean, scale)
        ):
            continue

        if abs(scale) < 1e-8:
            scale = 1.0

        reconstructed_value = reconstructed * scale + mean
        normalized_error = abs(reconstructed - normalized)
        absolute_error = abs(reconstructed_value - observed)

        if not all(
            math.isfinite(value)
            for value in (
                reconstructed_value,
                normalized_error,
                absolute_error,
            )
        ):
            continue

        diagnostics.append(
            {
                "feature": feature,
                "name": name,
                "unit": unit,
                "observed_value": observed,
                "reconstructed_value": reconstructed_value,
                "absolute_error": absolute_error,
                "normalized_error": normalized_error,
                "_feature_index": index,
            }
        )

    squared_errors = [
        item["normalized_error"] ** 2
        for item in diagnostics
    ]
    total_squared_error = sum(squared_errors)

    for index, item in enumerate(diagnostics):
        item["contribution_percent"] = (
            squared_errors[index] / total_squared_error * 100
            if total_squared_error > 0
            else 0.0
        )

    diagnostics.sort(
        key=lambda item: (
            -item["contribution_percent"],
            item["_feature_index"],
        )
    )

    for rank, item in enumerate(diagnostics, start=1):
        item["rank"] = rank
        del item["_feature_index"]

    return {
        "normalization": "relative_squared_reconstruction_error_shares",
        "contribution_percent_note": (
            "Percentages are relative squared reconstruction-error shares "
            "among available valid metrics. They are not probabilities "
            "and do not prove anomaly causation."
        ),
        "metrics": diagnostics,
    }
