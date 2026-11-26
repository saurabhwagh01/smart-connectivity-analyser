/**
 * Metric Validation & Formatting Module
 *
 * Pure, side-effect-free helpers for validating and formatting
 * network performance metrics. Works in both browser (globals) and Node.js.
 */

(function (root) {
    "use strict";

    const METRIC_UNITS = Object.freeze({
    download: "Mbps",
    download_mbps: "Mbps",
    upload: "Mbps",
    upload_mbps: "Mbps",
    ping: "ms",
    ping_ms: "ms",
    jitter: "ms",
    jitter_ms: "ms",
    packetLoss: "%",
    packet_loss: "%"
});

function isValidMetric(value) {
    return (
        value !== null &&
        value !== undefined &&
        value !== "" &&
        typeof value !== "boolean" &&
        Number.isFinite(Number(value))
    );
}

function safeNumber(value, fallback = null) {
    return isValidMetric(value) ? Number(value) : fallback;
}

function firstValid(...values) {
    for (const value of values) {
        if (isValidMetric(value)) return Number(value);
    }
    return null;
}

function isValidMetricNumber(value) {
    if (
        value === null ||
        value === undefined ||
        value === "" ||
        typeof value === "boolean" ||
        typeof value === "object" ||
        (typeof value === "string" && value.trim() === "")
    ) {
        return false;
    }

    return Number.isFinite(Number(value));
}

function formatNumber(value, decimals = 1) {
    if (!isValidMetricNumber(value)) {
        return "--";
    }

    return Number(value).toFixed(decimals);
}

function formatMetric(value, unitOrDecimals = "", decimals = 1) {
    if (!isValidMetricNumber(value)) {
        return "Unavailable";
    }

    // Maintain compatibility with existing formatMetric(value, 2) calls.
    let unit = "";

    if (typeof unitOrDecimals === "number") {
        decimals = unitOrDecimals;
    } else {
        unit = unitOrDecimals || "";
    }

    const formatted = Number(value).toFixed(decimals);

    return unit ? `${formatted} ${unit}` : formatted;
}

function formatNetworkMetric(metricType, value, decimals = 1) {
    const unit = METRIC_UNITS[metricType] || "";

    return formatMetric(value, unit, decimals);
}

    if (typeof root !== "undefined") {
        root.METRIC_UNITS = METRIC_UNITS;
        root.isValidMetric = isValidMetric;
        root.safeNumber = safeNumber;
        root.firstValid = firstValid;
        root.isValidMetricNumber = isValidMetricNumber;
        root.formatNumber = formatNumber;
        root.formatMetric = formatMetric;
        root.formatNetworkMetric = formatNetworkMetric;
    }

    if (typeof module !== "undefined" && module.exports) {
        module.exports = {
            METRIC_UNITS,
            isValidMetric,
            safeNumber,
            firstValid,
            isValidMetricNumber,
            formatNumber,
            formatMetric,
            formatNetworkMetric
        };
    }
})(typeof globalThis !== "undefined" ? globalThis : this);
