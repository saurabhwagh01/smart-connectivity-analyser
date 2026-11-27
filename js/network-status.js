/**
 * Network Status & Type Detection Module
 *
 * Pure helpers for resolving browser connection state, offline status,
 * connectivity indicator badges, and dashboard display state.
 * Works in both browser (globals) and Node.js.
 */

(function (root) {
    "use strict";

    const _metricsMod =
        typeof root.formatMetric !== "undefined"
            ? { formatMetric: root.formatMetric }
            : require("./metrics.js");

    const _scoreMod =
        typeof root.calculateConnectivityScore !== "undefined"
            ? { calculateConnectivityScore: root.calculateConnectivityScore }
            : require("./connectivity-score.js");

function getBrowserConnection() {
    if (typeof navigator === "undefined") return null;

    return (
        navigator.connection ||
        navigator.mozConnection ||
        navigator.webkitConnection ||
        null
    );
}

function resolveNetworkType(connection, isOnline = true) {
    if (!isOnline) {
        return {
            type: "Offline",
            detail: "No internet connection",
            isKnown: true,
            effectiveType: null
        };
    }

    if (!connection || typeof connection !== "object") {
        return {
            type: "Unknown",
            detail: "Network Information API not supported by browser",
            isKnown: false,
            effectiveType: null
        };
    }

    const rawType = typeof connection.type === "string"
        ? connection.type.toLowerCase().trim()
        : "";

    const rawEffectiveType = typeof connection.effectiveType === "string"
        ? connection.effectiveType.toLowerCase().trim()
        : null;

    if (rawType === "none") {
        return {
            type: "Offline",
            detail: "No active network connection",
            isKnown: true,
            effectiveType: null
        };
    }

    if (rawType === "wifi" || rawType === "wlan") {
        return {
            type: "Wi-Fi",
            detail: "Wi-Fi connection",
            isKnown: true,
            effectiveType: rawEffectiveType
        };
    }

    if (rawType === "cellular" || rawType === "mobile" || rawType.startsWith("cellular")) {
        const speedContext = rawEffectiveType
            ? `Cellular (~${rawEffectiveType.toUpperCase()} speed tier, generation unverified)`
            : "Cellular connection (generation unverified)";

        return {
            type: "Mobile",
            detail: speedContext,
            isKnown: true,
            effectiveType: rawEffectiveType
        };
    }

    if (rawType === "ethernet") {
        return {
            type: "Ethernet",
            detail: "Wired ethernet connection",
            isKnown: true,
            effectiveType: rawEffectiveType
        };
    }

    if (rawType === "bluetooth") {
        return {
            type: "Bluetooth",
            detail: "Bluetooth tethering connection",
            isKnown: true,
            effectiveType: rawEffectiveType
        };
    }

    if (rawType === "wimax") {
        return {
            type: "WiMAX",
            detail: "WiMAX wireless connection",
            isKnown: true,
            effectiveType: rawEffectiveType
        };
    }

    // When connection.type is missing, "other", "unknown", or unrecognized:
    // Do NOT treat effectiveType (e.g. "3g" or "4g") as confirmed network type.
    const speedTierNote = rawEffectiveType
        ? `Estimated ~${rawEffectiveType.toUpperCase()} speed tier (medium unverified)`
        : "Network type not reported by browser";

    return {
        type: "Unknown",
        detail: speedTierNote,
        isKnown: false,
        effectiveType: rawEffectiveType
    };
}

function isDeviceOffline(
    connection = getBrowserConnection(),
    isOnline = typeof navigator !== "undefined" && typeof navigator.onLine === "boolean"
        ? navigator.onLine
        : true
) {
    return resolveNetworkType(connection, isOnline).type === "Offline";
}

function resolveConnectivityIndicator(
    score,
    { isOffline = false, isTesting = false } = {}
) {
    if (isOffline) {
        return {
            status: "Offline",
            dotClass: "disconnected",
            score: 0
        };
    }

    const numericScore = Number.isFinite(Number(score))
        ? Math.max(0, Number(score))
        : 0;

    if (isTesting) {
        return {
            status: "Testing",
            dotClass: "testing",
            score: numericScore
        };
    }

    if (numericScore >= 80) {
        return { status: "Excellent", dotClass: "excellent", score: numericScore };
    }

    if (numericScore >= 60) {
        return { status: "Good", dotClass: "good", score: numericScore };
    }

    if (numericScore >= 40) {
        return { status: "Fair", dotClass: "fair", score: numericScore };
    }

    if (numericScore > 0) {
        return { status: "Poor", dotClass: "poor", score: numericScore };
    }

    return {
        status: "Online",
        dotClass: "connected",
        score: 0
    };
}

function resolveDashboardDisplayState(
    metrics = {},
    {
        isOffline = false,
        isTesting = false,
        isHistoryRestored = false
    } = {}
) {
    if (isOffline) {
        return {
            download: "Unavailable",
            upload: "Unavailable",
            ping: "Unavailable",
            jitter: "Unavailable",
            packetLoss: "Unavailable",
            score: 0,
            metricsSubtitle: "Offline — live measurements unavailable",
            indicator: resolveConnectivityIndicator(0, {
                isOffline: true,
                isTesting
            })
        };
    }

    const score = Number.isFinite(Number(metrics.score))
        ? Math.max(0, Number(metrics.score))
        : _scoreMod.calculateConnectivityScore(metrics);

    return {
        download: _metricsMod.formatMetric(metrics.download),
        upload: _metricsMod.formatMetric(metrics.upload),
        ping: _metricsMod.formatMetric(metrics.ping),
        jitter: _metricsMod.formatMetric(metrics.jitter),
        packetLoss: _metricsMod.formatMetric(metrics.packetLoss),
        score,
        metricsSubtitle: isHistoryRestored
            ? "Last recorded measurements (run a test for live metrics)"
            : "Live performance measurements",
        indicator: resolveConnectivityIndicator(score, {
            isOffline: false,
            isTesting
        })
    };
}

    if (typeof root !== "undefined") {
        root.getBrowserConnection = getBrowserConnection;
        root.resolveNetworkType = resolveNetworkType;
        root.isDeviceOffline = isDeviceOffline;
        root.resolveConnectivityIndicator = resolveConnectivityIndicator;
        root.resolveDashboardDisplayState = resolveDashboardDisplayState;
    }

    if (typeof module !== "undefined" && module.exports) {
        module.exports = {
            getBrowserConnection,
            resolveNetworkType,
            isDeviceOffline,
            resolveConnectivityIndicator,
            resolveDashboardDisplayState
        };
    }
})(typeof globalThis !== "undefined" ? globalThis : this);
