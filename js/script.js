/* =========================================================
   SMART CONNECTIVITY ANALYSER
   COMPLETE CORRECTED SCRIPT
   ========================================================= */

const API_BASE =
    typeof window !== "undefined" && window.API_BASE
        ? window.API_BASE
        : "http://127.0.0.1:8000/api";

const $ = (id) => typeof document === "undefined" ? null : document.getElementById(id);

let applicationInitialized = false;
let testInProgress = false;
let speedTest = null;
let speedTestTimeout = null;
let networkChart = null;
let forecastChart = null;
let latestForecastData = null;
let connectivityMap = null;
let userMarker = null;
let savedMarkers = [];
let sessionTimer = null;
let sessionStartTime = Date.now();
let lastTestTime = null;
let downtimeSeconds = 0;
let currentLocation = null;
let sessionTests = [];
let savedLocations = [];
let metricsRestoredFromHistory = false;
let offlineClearedMetrics = false;
let wasDeviceOffline = false;

let currentMetrics = {
    download: null,
    upload: null,
    ping: null,
    jitter: null,
    packetLoss: null,
    networkType: "Unknown",
    networkTypeDetail: "Connection type",
    score: 0
};

// ─── Metric Units (loaded from js/metrics.js) ──────────
const _metrics =
    typeof require === "function"
        ? require("./metrics.js")
        : {
            METRIC_UNITS: globalThis.METRIC_UNITS,
            isValidMetric: globalThis.isValidMetric,
            safeNumber: globalThis.safeNumber,
            firstValid: globalThis.firstValid,
            isValidMetricNumber: globalThis.isValidMetricNumber,
            formatNumber: globalThis.formatNumber,
            formatMetric: globalThis.formatMetric,
            formatNetworkMetric: globalThis.formatNetworkMetric
        };

var {
    METRIC_UNITS,
    isValidMetric,
    safeNumber,
    firstValid,
    isValidMetricNumber,
    formatNumber,
    formatMetric,
    formatNetworkMetric
} = _metrics;

const ANOMALY_METRIC_LABELS = Object.freeze({
    download_mbps: "Download speed",
    upload_mbps: "Upload speed",
    ping_ms: "Ping",
    jitter_ms: "Jitter",
    packet_loss: "Packet loss"
});

function setText(id, value) {
    const element = $(id);
    if (element) element.textContent = value;
}

function showToast(message) {
    const toast = $("toast");
    const toastMessage = $("toast-message");

    if (!toast) return;

    if (toastMessage) toastMessage.textContent = message;

    toast.classList.add("show");

    clearTimeout(showToast.timeout);

    showToast.timeout = setTimeout(() => {
        toast.classList.remove("show");
    }, 3000);
}

// ─── Format Metric ─────────────────────────────────────

// ─── Shared Connectivity Score (loaded from js/connectivity-score.js) ──
const sharedCalculateConnectivityScore =
    typeof calculateConnectivityScore !== "undefined"
        ? calculateConnectivityScore
        : require("./connectivity-score.js").calculateConnectivityScore;
/**
 * Mark the Start Test button as busy without using the `disabled`
 * attribute. A disabled button loses keyboard focus, which drops a
 * keyboard user back to the top of the page. Repeat clicks are already
 * ignored by the `testInProgress` check in startNetworkTest().
 */
function setStartButtonBusy(button, busy) {
    if (!button) return;

    button.setAttribute?.("aria-disabled", String(busy));
    button.setAttribute?.("aria-busy", String(busy));

    const label = $("startTestLabel");

    if (label) {
        label.textContent = busy ? "Testing..." : "Start Test";
    }
}

function setProgress(id, value) {
    const element = $(id);

    if (!element || !element.style) return;

    element.style.width =
        `${Math.max(0, Math.min(100, Number(value) || 0))}%`;
}

/* =========================================================
   INITIALIZATION
   ========================================================= */

if (typeof document !== "undefined") {
    if (document.readyState === "loading") {
        document.addEventListener(
            "DOMContentLoaded",
            initializeApplication,
            { once: true }
        );
    } else {
    initializeApplication();
}
}

async function initializeApplication() {
    if (applicationInitialized) return;

    applicationInitialized = true;
    wasDeviceOffline = isDeviceOffline();

    setupButtons();
    await loadDiagnosticProfiles();
    setupNetworkListeners();
    detectNetworkType();
    applyConnectivityStatusIndicator();

    initializeMap();
    initializeChart();
    loadSavedLocations();

    await loadNetworkHistory();

    updateDashboard();
    updateApplicationReadiness();
    updateAIAnalysis();
    updateAISectionsFromBackend();
    loadConnectivityForecast();
    updateNetworkRecommendation();

    startSessionTimer();

    console.log("Smart Connectivity Analyser initialized.");
}

/* =========================================================
   BUTTONS + NETWORK EVENTS
   ========================================================= */

function setupButtons() {
    $("startTest")?.addEventListener("click", startNetworkTest);

    $("exportCSV")?.addEventListener(
        "click",
        exportHistoryToCSV
    );

    $("deleteSelectedHistory")?.addEventListener("click", deleteSelectedHistory);
    $("deleteAllHistory")?.addEventListener("click", deleteAllHistory);

    $("historyRange")?.addEventListener("change", (event) => {
        loadNetworkHistory(event.target.value);
    });

    $("historyMetric")?.addEventListener("change", (event) => {
        applyHistoryMetricFilter(event.target.value);
    });

    // Apply history filters.
    $("applyHistoryFilters")?.addEventListener(
        "click",
        () => loadNetworkHistory()
    );

    // Reset history filters.
    $("resetHistoryFilters")?.addEventListener(
        "click",
        resetNetworkHistoryFilters
    );

    $("detectLocation")?.addEventListener(
        "click",
        detectLocation
    );

    $("saveLocation")?.addEventListener(
        "click",
        saveLocation
    );

    $("findBetterArea")?.addEventListener(
        "click",
        findBetterArea
    );

    $("forecastMetric")?.addEventListener("change", (event) => {
        if (latestForecastData) {
            updateForecastChart(latestForecastData, event.target.value);
        }
    });
}

const STATUS_INDICATOR_CLASSES = Object.freeze([
    "connected",
    "online",
    "disconnected",
    "offline",
    "testing",
    "excellent",
    "good",
    "fair",
    "poor"
]);

// ─── Network Status & Type Detection (loaded from js/network-status.js) ──
const _networkStatus =
    typeof require === "function"
        ? require("./network-status.js")
        : {
            getBrowserConnection: globalThis.getBrowserConnection,
            resolveNetworkType: globalThis.resolveNetworkType,
            isDeviceOffline: globalThis.isDeviceOffline,
            resolveConnectivityIndicator: globalThis.resolveConnectivityIndicator,
            resolveDashboardDisplayState: globalThis.resolveDashboardDisplayState
        };

var {
    getBrowserConnection,
    resolveNetworkType,
    isDeviceOffline,
    resolveConnectivityIndicator,
    resolveDashboardDisplayState
} = _networkStatus;

function clearLiveMetrics() {
    currentMetrics.download = null;
    currentMetrics.upload = null;
    currentMetrics.ping = null;
    currentMetrics.jitter = null;
    currentMetrics.packetLoss = null;
    currentMetrics.score = 0;
    metricsRestoredFromHistory = false;
    offlineClearedMetrics = true;
}

function applyConnectivityStatusIndicator(score = currentMetrics.score) {
    const indicator = resolveConnectivityIndicator(score, {
        isOffline: isDeviceOffline(),
        isTesting: testInProgress
    });

    if (typeof document === "undefined") {
        return indicator;
    }

    setText("status", indicator.status);

    const dot = typeof $ === "function" ? $("networkStatusDot") : null;
    if (dot) {
        dot.classList?.remove(...STATUS_INDICATOR_CLASSES);
        dot.classList?.add(indicator.dotClass);
        if (dot.dataset) {
            dot.dataset.status = indicator.status.toLowerCase();
        }
        dot.setAttribute?.("aria-label", `Connectivity status: ${indicator.status}`);
        dot.setAttribute?.("title", `Connectivity status: ${indicator.status}`);
    }

    const statusEl = typeof $ === "function" ? $("status") : null;
    if (statusEl) {
        statusEl.classList?.remove(...STATUS_INDICATOR_CLASSES);
        statusEl.classList?.add(indicator.dotClass);
    }

    return indicator;
}

function handleConnectivityTransition({ showToastNotification = false } = {}) {
    const network = detectNetworkType();
    const offline = network.type === "Offline" || isDeviceOffline();

    if (offline) {
        clearLiveMetrics();
        updateDashboard();
        updateApplicationReadiness();
        updateNetworkRecommendation();

        if (!testInProgress) {
            setText(
                "testMessage",
                "Your device is offline. Connect to a network first."
            );
        }

        if (showToastNotification && !wasDeviceOffline) {
            showToast("Internet connection lost.");
        }
    } else {
        if (wasDeviceOffline && !testInProgress) {
            setText(
                "testMessage",
                "Run a connectivity test to analyse your network."
            );
        }

        updateDashboard();
        updateApplicationReadiness();
        updateNetworkRecommendation();

        if (showToastNotification && wasDeviceOffline) {
            showToast("Internet connection restored.");
        }
    }

    wasDeviceOffline = offline;
}

function setupNetworkListeners() {
    window.addEventListener("online", () => {
        handleConnectivityTransition({ showToastNotification: true });
    });

    window.addEventListener("offline", () => {
        handleConnectivityTransition({ showToastNotification: true });
    });

    const connection = getBrowserConnection();

    if (connection && typeof connection.addEventListener === "function") {
        connection.addEventListener("change", () => {
            handleConnectivityTransition({ showToastNotification: true });
        });
    } else if (connection && "onchange" in connection) {
        connection.onchange = () => {
            handleConnectivityTransition({ showToastNotification: true });
        };
    }

    window.addEventListener("resize", () => {
        connectivityMap?.invalidateSize();
        networkChart?.resize();
        forecastChart?.resize();
    });

    setInterval(() => {
        if (isDeviceOffline()) {
            downtimeSeconds++;
        }

        updateSessionStatistics();
    }, 1000);
}

function updateNetworkStatus() {
    return applyConnectivityStatusIndicator(currentMetrics.score);
}

/**
 * Resolves reliable network type information from browser connection data.
 *
 * Distinguishes verified physical media (Wi-Fi, Cellular, Ethernet, Bluetooth, WiMAX)
 * from synthetic or unverified metrics. Avoids presenting an unverified cellular
 * generation (e.g. from effectiveType '3g'/'4g') as a confirmed hardware result.
 *
 * @param {Object|null|undefined} connection - navigator.connection object
 * @param {boolean} [isOnline=true] - Browser online status
 * @returns {{type: string, detail: string, isKnown: boolean, effectiveType: string|null}}
 */
// resolveNetworkType is loaded from js/network-status.js

function detectNetworkType() {
    const isOnline =
        typeof navigator !== "undefined" && typeof navigator.onLine === "boolean"
            ? navigator.onLine
            : true;

    const connection = getBrowserConnection();

    const result = resolveNetworkType(connection, isOnline);

    currentMetrics.networkType = result.type;
    currentMetrics.networkTypeDetail = result.detail;

    if (typeof document !== "undefined") {
        setText("networkType", result.type);
        setText("networkTypeDetail", result.detail);

        const networkTypeEl = typeof $ === "function" ? $("networkType") : null;
        if (networkTypeEl) {
            networkTypeEl.setAttribute("title", result.detail);
            networkTypeEl.dataset.known = String(result.isKnown);
        }
    }

    return result;
}

/* =========================================================
   MAP - OPENSTREETMAP
   ========================================================= */

function initializeMap() {
    const mapElement = $("connectivityMap");

    if (!mapElement) {
        console.warn("Map container not found.");
        return;
    }

    if (typeof L === "undefined") {
        console.error("Leaflet is not loaded.");

        setText(
            "locationResult",
            "The map could not load. Check your internet connection and refresh the page."
        );

        return;
    }

    if (connectivityMap) {
        setTimeout(() => {
            connectivityMap.invalidateSize(true);
        }, 150);

        return;
    }

    try {
        connectivityMap = L.map(mapElement, {
            zoomControl: true,
            scrollWheelZoom: true
        }).setView([19.0760, 72.8777], 12);

        const tileLayer = L.tileLayer(
            "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
            {
                minZoom: 1,
                maxZoom: 19,
                attribution:
                    '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
            }
        );

        tileLayer.on("tileerror", (event) => {
            console.warn("OpenStreetMap tile error:", event);

            setText(
                "locationResult",
                "Map tiles could not load. Check your connection."
            );
        });

        tileLayer.addTo(connectivityMap);

        connectivityMap.whenReady(() => {
            setTimeout(() => {
                connectivityMap?.invalidateSize(true);
            }, 250);
        });

        console.log("OpenStreetMap initialized.");

    } catch (error) {
        console.error("Map initialization failed:", error);

        setText(
            "locationResult",
            "The map could not be started. Refresh the page to try again."
        );
    }
}

function ensureMapReady() {
    if (!connectivityMap) {
        initializeMap();
    }

    if (connectivityMap) {
        setTimeout(() => {
            connectivityMap.invalidateSize(true);
        }, 100);
    }
}

/* =========================================================
   LOCATION
   ========================================================= */

function detectLocation() {
    if (!navigator.geolocation) {
        showToast("Geolocation is not supported.");

        setText(
            "locationResult",
            "Geolocation is not supported by this browser."
        );

        return;
    }

    setText(
        "locationResult",
        "Detecting your current location..."
    );

    navigator.geolocation.getCurrentPosition(
        (position) => {
            const latitude = position.coords.latitude;
            const longitude = position.coords.longitude;
            const accuracy = position.coords.accuracy;

            currentLocation = {
                latitude,
                longitude,
                accuracy,
                timestamp: position.timestamp
            };

            ensureMapReady();

            if (connectivityMap && typeof L !== "undefined") {
                const point = [latitude, longitude];

                connectivityMap.setView(point, 16);

                if (userMarker) {
                    userMarker.setLatLng(point);
                } else {
                    userMarker = L.marker(point).addTo(connectivityMap);
                }

                userMarker
                    .bindPopup("Your Current Location")
                    .openPopup();
            }

            setText(
                "locationResult",
                `Location detected: ${latitude.toFixed(5)}, ${longitude.toFixed(5)} (±${Math.round(accuracy)} m)`
            );

            showToast("Location detected successfully.");
        },

        (error) => {
            let message = "Unable to detect location.";

            if (error.code === 1) {
                message =
                    "Location permission denied. Allow location access in your browser.";
            } else if (error.code === 2) {
                message = "Location information is unavailable.";
            } else if (error.code === 3) {
                message = "Location request timed out. Try again.";
            }

            setText("locationResult", message);
            showToast(message);
        },

        {
            enableHighAccuracy: true,
            timeout: 20000,
            maximumAge: 0
        }
    );
}

function saveLocation() {
    let latitude;
    let longitude;

    if (currentLocation) {
        latitude = currentLocation.latitude;
        longitude = currentLocation.longitude;
    } else if (connectivityMap) {
        const center = connectivityMap.getCenter();

        latitude = center.lat;
        longitude = center.lng;
    } else {
        showToast("Detect your location first.");
        return;
    }

    const point = {
        latitude,
        longitude,
        score: currentMetrics.score,
        download: currentMetrics.download,
        upload: currentMetrics.upload,
        ping: currentMetrics.ping,
        timestamp: new Date().toISOString()
    };

    try {
        savedLocations.push(point);

        localStorage.setItem(
            "savedConnectivityLocations",
            JSON.stringify(savedLocations)
        );

        addSavedLocationToMap(point);

        setText("locationResult", "Network location saved.");

        showToast("Location saved successfully.");

    } catch (error) {
        console.error("Save location failed:", error);

        showToast("Unable to save location.");
    }
}

function loadSavedLocations() {
    try {
        const parsed = JSON.parse(
            localStorage.getItem("savedConnectivityLocations") || "[]"
        );

        savedLocations = Array.isArray(parsed) ? parsed : [];

        savedLocations.forEach(addSavedLocationToMap);

    } catch (error) {
        savedLocations = [];

        console.warn("Could not load saved locations:", error);
    }
}

function addSavedLocationToMap(point) {
    if (!connectivityMap || typeof L === "undefined") return;

    const lat = safeNumber(point.latitude);
    const lng = safeNumber(point.longitude);

    if (lat === null || lng === null) return;

    const marker = L.circleMarker([lat, lng], {
        radius: 7,
        weight: 2
    }).addTo(connectivityMap);

    marker.bindPopup(
        `Saved network point<br>Score: ${safeNumber(point.score, 0)}/100`
    );

    savedMarkers.push(marker);
}

function findBetterArea() {
    const result = $("navigationResult");

    if (!currentLocation) {
        if (result) {
            result.textContent = "Detect your current location first.";
        }

        showToast("Detect your current location first.");
        return;
    }

    const betterPoints = savedLocations
        .filter((point) =>
            safeNumber(point.score, -1) > currentMetrics.score &&
            isValidMetric(point.latitude) &&
            isValidMetric(point.longitude)
        )
        .sort((a, b) => Number(b.score) - Number(a.score));

    if (!betterPoints.length) {
        if (result) {
            result.textContent =
                "No saved location has a higher connectivity score yet.";
        }

        showToast("No better saved network point found.");
        return;
    }

    const target = betterPoints[0];

    const distance = calculateDistanceKm(
        currentLocation.latitude,
        currentLocation.longitude,
        Number(target.latitude),
        Number(target.longitude)
    );

    const direction = bearingToDirection(
        calculateBearing(
            currentLocation.latitude,
            currentLocation.longitude,
            Number(target.latitude),
            Number(target.longitude)
        )
    );

    if (result) {
        result.textContent =
            `Better saved area found. Score: ${target.score}/100. Distance: ${distance.toFixed(2)} km. Direction: ${direction}.`;
    }

    connectivityMap?.setView(
        [Number(target.latitude), Number(target.longitude)],
        15
    );
}

function calculateDistanceKm(lat1, lon1, lat2, lon2) {
    const toRad = (degrees) => degrees * Math.PI / 180;

    const dLat = toRad(lat2 - lat1);
    const dLon = toRad(lon2 - lon1);

    const a =
        Math.sin(dLat / 2) ** 2 +
        Math.cos(toRad(lat1)) *
        Math.cos(toRad(lat2)) *
        Math.sin(dLon / 2) ** 2;

    return 6371 * 2 *
        Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

function calculateBearing(lat1, lon1, lat2, lon2) {
    const toRad = (degrees) => degrees * Math.PI / 180;
    const toDeg = (radians) => radians * 180 / Math.PI;

    const phi1 = toRad(lat1);
    const phi2 = toRad(lat2);
    const lambda = toRad(lon2 - lon1);

    const y = Math.sin(lambda) * Math.cos(phi2);

    const x =
        Math.cos(phi1) * Math.sin(phi2) -
        Math.sin(phi1) * Math.cos(phi2) * Math.cos(lambda);

    return (toDeg(Math.atan2(y, x)) + 360) % 360;
}

function bearingToDirection(bearing) {
    const directions = [
        "North",
        "North-East",
        "East",
        "South-East",
        "South",
        "South-West",
        "West",
        "North-West"
    ];

    return directions[Math.round(bearing / 45) % 8];
}

/* =========================================================
   CHART.JS
   ========================================================= */

function initializeChart() {
    const canvas = $("networkChart");

    if (!canvas) {
        console.warn("Chart canvas #networkChart was not found.");
        return;
    }

    if (typeof Chart === "undefined") {
        console.error("Chart.js is not loaded.");

        setText(
            "testMessage",
            "The history chart could not load. Check your internet connection and refresh the page."
        );

        return;
    }

    if (networkChart) return;

    const context = canvas.getContext("2d");

    if (!context) return;

    networkChart = new Chart(context, {
        type: "line",

        data: {
            labels: [],

            datasets: [
                {
                    label: "Connectivity Score",
                    data: [],
                    borderColor: "#8b5cf6",
                    backgroundColor: "rgba(139, 92, 246, 0.15)",
                    borderWidth: 3,
                    fill: true,
                    tension: 0.35,
                    spanGaps: true,
                    yAxisID: "scoreAxis"
                },

                {
                    label: "Download Speed (Mbps)",
                    data: [],
                    borderColor: "#ec4899",
                    backgroundColor: "rgba(236, 72, 153, 0.10)",
                    borderWidth: 3,
                    fill: false,
                    tension: 0.35,
                    spanGaps: true,
                    yAxisID: "speedAxis"
                },

                {
                    label: "Upload Speed (Mbps)",
                    data: [],
                    borderColor: "#3b82f6",
                    backgroundColor: "rgba(59, 130, 246, 0.10)",
                    borderWidth: 3,
                    fill: false,
                    tension: 0.35,
                    spanGaps: true,
                    yAxisID: "speedAxis"
                },

                {
                    label: "Ping (ms)",
                    data: [],
                    borderColor: "#f59e0b",
                    backgroundColor: "rgba(245, 158, 11, 0.10)",
                    borderWidth: 3,
                    fill: false,
                    tension: 0.35,
                    spanGaps: true,
                    yAxisID: "latencyAxis"
                },

                {
                    label: "Jitter (ms)",
                    data: [],
                    borderColor: "#10b981",
                    backgroundColor: "rgba(16, 185, 129, 0.10)",
                    borderWidth: 3,
                    fill: false,
                    tension: 0.35,
                    spanGaps: true,
                    yAxisID: "latencyAxis"
                },

                {
                    label: "Packet Loss (%)",
                    data: [],
                    borderColor: "#ef4444",
                    backgroundColor: "rgba(239, 68, 68, 0.10)",
                    borderWidth: 3,
                    fill: false,
                    tension: 0.35,
                    spanGaps: true,
                    yAxisID: "scoreAxis"
                }
            ]
        },

        options: {
            responsive: true,
            maintainAspectRatio: false,

            interaction: {
                intersect: false,
                mode: "index"
            },

            plugins: {
                legend: {
                    display: true,
                    position: "bottom"
                },

                tooltip: {
                    enabled: true
                }
            },

            scales: {
                scoreAxis: {
                    type: "linear",
                    position: "left",
                    min: 0,
                    max: 100,

                    title: {
                        display: true,
                        text: "Score / Loss (%)"
                    }
                },

                speedAxis: {
                    type: "linear",
                    position: "right",
                    beginAtZero: true,

                    title: {
                        display: true,
                        text: "Speed (Mbps)"
                    },

                    grid: {
                        drawOnChartArea: false
                    }
                },

                latencyAxis: {
                    type: "linear",
                    position: "right",
                    beginAtZero: true,

                    title: {
                        display: false,
                        text: "Latency (ms)"
                    },

                    grid: {
                        drawOnChartArea: false
                    }
                }
            }
        }
    });

    console.log("Chart.js initialized.");
}

function applyHistoryMetricFilter(selectedMetric = "all") {
    if (!networkChart) return;

    const metricDatasetMap = {
        score: [0],
        download: [1],
        upload: [2],
        ping: [3],
        jitter: [4],
        packet_loss: [5]
    };

    const targetIndices = metricDatasetMap[selectedMetric];

    networkChart.data.datasets.forEach((dataset, idx) => {
        if (selectedMetric === "all") {
            dataset.hidden = false;
        } else {
            dataset.hidden = !targetIndices?.includes(idx);
        }
    });

    networkChart.update();
}

/* =========================================================
   HISTORY
   ========================================================= */

function normalizeHistoryItem(item = {}) {
    return {
        id: Number.isSafeInteger(Number(item.id)) ? Number(item.id) : null,
        timestamp:
            item.timestamp ||
            item.created_at ||
            item.time ||
            new Date().toISOString(),

        download_mbps: firstValid(
            item.download_mbps,
            item.download,
            item.downloadSpeed
        ),

        upload_mbps: firstValid(
            item.upload_mbps,
            item.upload,
            item.uploadSpeed
        ),

        ping: firstValid(item.ping_ms, item.ping),

        jitter: firstValid(item.jitter_ms, item.jitter),

        packet_loss: firstValid(
            item.packet_loss,
            item.packetLoss,
            item.packet_loss_percent
        ),

        connectivity_score: firstValid(
            item.connectivity_score,
            item.score
        )
    };
}
/* =========================================================
   NETWORK HISTORY FILTER HELPERS
   ========================================================= */

function validateHistoryFilterValues({
    startDate = "",
    endDate = "",
    minScore = "",
    maxScore = ""
} = {}) {

    const normalize = value =>
        String(value ?? "").trim();

    startDate = normalize(startDate);
    endDate = normalize(endDate);
    minScore = normalize(minScore);
    maxScore = normalize(maxScore);

    function isValidDate(value) {
        if (!value) return true;

        if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) {
            return false;
        }

        const parsed = new Date(
            `${value}T00:00:00.000Z`
        );

        return (
            !Number.isNaN(parsed.getTime()) &&
            parsed.toISOString().slice(0, 10) === value
        );
    }

    if (!isValidDate(startDate) || !isValidDate(endDate)) {
        return {
            valid: false,
            error: "Please enter valid dates."
        };
    }

    if (startDate && endDate && startDate > endDate) {
        return {
            valid: false,
            error: "Start date cannot be after end date."
        };
    }

    function parseScore(value, label) {
        if (value === "") {
            return {
                valid: true,
                value: null
            };
        }

        const score = Number(value);

        if (
            !Number.isFinite(score) ||
            score < 0 ||
            score > 100
        ) {
            return {
                valid: false,
                error: `${label} must be between 0 and 100.`
            };
        }

        return {
            valid: true,
            value: score
        };
    }

    const minimum = parseScore(minScore, "Minimum score");

    if (!minimum.valid) {
        return {
            valid: false,
            error: minimum.error
        };
    }

    const maximum = parseScore(maxScore, "Maximum score");

    if (!maximum.valid) {
        return {
            valid: false,
            error: maximum.error
        };
    }

    if (
        minimum.value !== null &&
        maximum.value !== null &&
        minimum.value > maximum.value
    ) {
        return {
            valid: false,
            error: "Minimum score cannot exceed maximum score."
        };
    }

    return {
        valid: true,
        filters: {
            startDate,
            endDate,
            minScore: minimum.value,
            maxScore: maximum.value
        }
    };
}


function setHistoryFilterMessage(message, isError = false) {
    const element = $("historyFilterMessage");

    if (!element) return;

    element.textContent = message;

    element.classList.toggle(
        "is-error",
        isError
    );
}


function resetNetworkHistoryFilters() {
    const filterIds = [
        "historyStartDate",
        "historyEndDate",
        "historyMinScore",
        "historyMaxScore"
    ];

    filterIds.forEach(id => {
        const element = $(id);

        if (element) {
            element.value = "";
        }
    });

    const rangeElement = $("historyRange");

    if (rangeElement) {
        rangeElement.value = "all";
    }

    setHistoryFilterMessage("");

    loadNetworkHistory("all");
}

async function loadNetworkHistory(range = null) {
    const selectedRange =
        range || $("historyRange")?.value || "recent";

    const validation = validateHistoryFilterValues({
        startDate: $("historyStartDate")?.value || "",
        endDate: $("historyEndDate")?.value || "",
        minScore: $("historyMinScore")?.value || "",
        maxScore: $("historyMaxScore")?.value || ""
    });

    if (!validation.valid) {
        setHistoryFilterMessage(validation.error, true);
        return;
    }

    const filters = validation.filters;
    const params = new URLSearchParams();

    params.set("range", selectedRange);

    if (filters.startDate) {
        params.set("start_date", filters.startDate);
    }

    if (filters.endDate) {
        params.set("end_date", filters.endDate);
    }

    if (filters.minScore !== null) {
        params.set("min_score", filters.minScore);
    }

    if (filters.maxScore !== null) {
        params.set("max_score", filters.maxScore);
    }

    const canvasContainer = $("historyChartContainer");
    const emptyState = $("historyEmptyState");
    const errorState = $("historyErrorState");

    try {
        setHistoryFilterMessage("Loading network history...");

        const response = await fetch(
            `${API_BASE}/network-history?${params.toString()}`,
            {
                method: "GET",
                cache: "no-store"
            }
        );

        if (!response.ok) {
            throw new Error(
                `History API returned ${response.status}`
            );
        }

        const result = await response.json();

        const data = Array.isArray(result)
            ? result
            : (
                result.history ||
                result.data ||
                result.results ||
                []
            );

        if (!Array.isArray(data)) {
            throw new Error("Unexpected network history format.");
        }

        if (errorState) errorState.hidden = true;

        sessionTests = data
            .map(normalizeHistoryItem)
            .filter((item) =>
                Number.isFinite(Date.parse(item.timestamp))
            );
        renderHistoryRecordSelection(sessionTests);

        if (sessionTests.length === 0) {
            updateHistoryChart([], "all");

            if (canvasContainer) {
                canvasContainer.hidden = true;
            }

            if (emptyState) {
                emptyState.hidden = false;
            }

            updateSessionStatistics();

            setHistoryFilterMessage("");

            return;
        }

        if (canvasContainer) {
            canvasContainer.hidden = false;
        }

        if (emptyState) {
            emptyState.hidden = true;
        }

        // The backend has already applied all selected filters.
        updateHistoryChart(sessionTests, "all");

        updateSessionStatistics();

        setHistoryFilterMessage(
            `Showing ${sessionTests.length} matching network record(s).`
        );

        // Preserve latest-measurement restoration only when online and not cleared by offline transition.
        const latest = sessionTests[sessionTests.length - 1];

        if (!isDeviceOffline() && !offlineClearedMetrics && latest) {
            let restored = false;

            if (
                currentMetrics.download === null &&
                latest.download_mbps !== null
            ) {
                currentMetrics.download = Number(
                    latest.download_mbps
                );
                restored = true;
            }

            if (
                currentMetrics.upload === null &&
                latest.upload_mbps !== null
            ) {
                currentMetrics.upload = Number(
                    latest.upload_mbps
                );
                restored = true;
            }

            if (restored) {
                metricsRestoredFromHistory = true;
            }
        }

    } catch (error) {
        console.warn(
            "Network history could not be loaded:",
            error.message
        );

        sessionTests = [];
        renderHistoryRecordSelection([]);

        updateHistoryChart([], "all");

        if (canvasContainer) {
            canvasContainer.hidden = true;
        }

        if (emptyState) {
            emptyState.hidden = true;
        }

        if (errorState) {
            errorState.hidden = false;
        }

        updateSessionStatistics();

        setHistoryFilterMessage("");
    }
}

function renderHistoryRecordSelection(items = sessionTests) {
    const list = $("historyRecordSelection");
    const deleteButton = $("deleteSelectedHistory");
    if (!list) return;

    list.replaceChildren();
    for (const item of items) {
        if (!Number.isSafeInteger(item.id) || item.id <= 0) continue;
        const entry = document.createElement("li");
        const label = document.createElement("label");
        const checkbox = document.createElement("input");
        const description = document.createElement("span");
        label.className = "flex items-center gap-2 rounded-lg p-2 text-xs hover:bg-white/70";
        checkbox.type = "checkbox";
        checkbox.dataset.historyId = String(item.id);
        description.textContent = `${new Date(item.timestamp).toLocaleString()} — score ${item.connectivity_score ?? "unavailable"}`;
        checkbox.addEventListener("change", () => {
            if (deleteButton) {
                deleteButton.disabled =
                    !list.querySelector("input[data-history-id]:checked");
            }
        });
        label.append(checkbox, description);
        entry.append(label);
        list.append(entry);
    }
    if (deleteButton) deleteButton.disabled = true;
}

async function deleteSelectedHistory() {
    const selectedIds = Array.from(
        $("historyRecordSelection")?.querySelectorAll("input[data-history-id]:checked") || []
    ).map((checkbox) => Number(checkbox.dataset.historyId));
    if (!selectedIds.length) return;
    if (!window.confirm(`Delete ${selectedIds.length} selected network history record(s)? This cannot be undone.`)) return;

    await deleteHistoryRequest("/network-history", { ids: selectedIds });
}

async function deleteAllHistory() {
    if (!window.confirm("Delete all saved network history? This cannot be undone.")) return;
    await deleteHistoryRequest("/network-history?all=true");
}

async function deleteHistoryRequest(path, body = undefined) {
    const message = $("historyDeleteMessage");
    if (message) message.textContent = "Deleting network history…";
    try {
        const response = await fetch(`${API_BASE}${path}`, {
            method: "DELETE",
            headers: body ? { "Content-Type": "application/json" } : undefined,
            body: body ? JSON.stringify(body) : undefined
        });
        const result = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error("The database could not delete the selected history.");
        }
        if (message) message.textContent = `Deleted ${result.deleted_count} network record(s).`;
        await loadNetworkHistory();
    } catch (error) {
        if (message) message.textContent = `History deletion failed: ${error.message}`;
    }
}

function updateHistoryChart(history = sessionTests, range = null) {
    if (!networkChart) initializeChart();

    if (!networkChart) return;

    const selectedRange =
        range || $("historyRange")?.value || "recent";

    const now = Date.now();

    const durations = {
        "1h": 60 * 60 * 1000,
        "24h": 24 * 60 * 60 * 1000,
        "7d": 7 * 24 * 60 * 60 * 1000
    };

    const filtered = history
        .map(normalizeHistoryItem)
        .filter((item) => {
            const time = Date.parse(item.timestamp);

            if (!Number.isFinite(time)) return false;

            if (selectedRange === "recent") return true;

            const duration = durations[selectedRange];

            return duration
                ? now - time <= duration && now - time >= 0
                : true;
        })
        .sort((a, b) =>
            Date.parse(a.timestamp) - Date.parse(b.timestamp)
        );

    networkChart.data.labels = filtered.map((item) =>
        new Date(item.timestamp).toLocaleString([], {
            month: "short",
            day: "numeric",
            hour: "2-digit",
            minute: "2-digit"
        })
    );

    networkChart.data.datasets[0].data =
        filtered.map((item) => item.connectivity_score);

    networkChart.data.datasets[1].data =
        filtered.map((item) => item.download_mbps);

    networkChart.data.datasets[2].data =
        filtered.map((item) => item.upload_mbps);

    networkChart.data.datasets[3].data =
        filtered.map((item) => item.ping ?? item.ping_ms);

    networkChart.data.datasets[4].data =
        filtered.map((item) => item.jitter ?? item.jitter_ms);

    networkChart.data.datasets[5].data =
        filtered.map((item) => item.packet_loss);

    const activeMetric = $("historyMetric")?.value || "all";
    if (activeMetric !== "all") {
        applyHistoryMetricFilter(activeMetric);
    } else {
        networkChart.update();
    }

    updateChartDescription(filtered);
}

/**
 * Keep the canvas aria-label in step with the plotted data, because
 * screen readers cannot read the pixels Chart.js draws.
 */
function updateChartDescription(items) {
    const canvas = $("networkChart");

    if (!canvas?.setAttribute) return;

    if (!items.length) {
        canvas.setAttribute(
            "aria-label",
            "Network history chart. No network history is available for the selected range."
        );
        return;
    }

    const latest = items[items.length - 1];
    const parts = [
        `Network history chart showing ${items.length} test${items.length === 1 ? "" : "s"}.`
    ];

    if (isValidMetric(latest.connectivity_score)) {
        parts.push(
            `Latest connectivity score: ${Math.round(Number(latest.connectivity_score))} out of 100.`
        );
    }

    if (isValidMetric(latest.download_mbps)) {
        parts.push(
            `Latest download speed: ${Number(latest.download_mbps).toFixed(1)} Mbps.`
        );
    }

    if (isValidMetric(latest.upload_mbps)) {
        parts.push(
            `Latest upload speed: ${Number(latest.upload_mbps).toFixed(1)} Mbps.`
        );
    }

    if (isValidMetric(latest.ping ?? latest.ping_ms)) {
        parts.push(
            `Latest ping: ${Math.round(Number(latest.ping ?? latest.ping_ms))} ms.`
        );
    }

    if (isValidMetric(latest.jitter ?? latest.jitter_ms)) {
        parts.push(
            `Latest jitter: ${Math.round(Number(latest.jitter ?? latest.jitter_ms))} ms.`
        );
    }

    if (isValidMetric(latest.packet_loss)) {
        parts.push(
            `Latest packet loss: ${Number(latest.packet_loss).toFixed(1)}%.`
        );
    }

    canvas.setAttribute("aria-label", parts.join(" "));
}

/* =========================================================
   NETWORK TEST
   ========================================================= */

function abortTestIfOffline() {
    if (!isDeviceOffline()) return false;

    clearLiveMetrics();
    detectNetworkType();
    updateDashboard();
    updateApplicationReadiness();
    updateNetworkRecommendation();
    showToast("Internet connection lost during test.");
    return true;
}

async function startNetworkTest() {
    if (testInProgress) return;

    if (isDeviceOffline()) {
        clearLiveMetrics();
        detectNetworkType();
        updateDashboard();
        updateApplicationReadiness();
        updateNetworkRecommendation();

        setText(
            "testMessage",
            "Your device is offline. Connect to a network first."
        );

        showToast("Your device is offline.");
        return;
    }

    testInProgress = true;
    metricsRestoredFromHistory = false;
    offlineClearedMetrics = false;

    const button = $("startTest");

    // NEW: profile selection (null = original standard test)
    const profile = getSelectedProfile();
    const runsBandwidth =
        !profile ||
        profile.checks.includes("download") ||
        profile.checks.includes("upload");
    let outcome = null;

    setStartButtonBusy(button, true);
    setProfileSelectorDisabled(true);
    renderProfileResultLoading(profile);

    setText(
        "testMessage",
        profile
            ? `Running ${profile.label} (about ${profile.estimated_seconds}s)...`
            : "Measuring download, upload, ping and jitter..."
    );
    setText("dnsStatus", "Checking DNS on the server...");

    currentMetrics = {
        download: null,
        upload: null,
        ping: null,
        jitter: null,
        packetLoss: null,
        networkType: currentMetrics.networkType,
        networkTypeDetail: currentMetrics.networkTypeDetail,
        score: 0
    };

    updateDashboard();

    try {
        void runBackendDnsCheck()
            .then((dnsResult) => {
                setText("dnsStatus", formatDnsStatus(dnsResult));
            })
            .catch(() => {
                setText("dnsStatus", formatDnsStatus(null));
            });

        const [backendResult, bandwidthResult, protocolResult] =
            await Promise.all([
                runBackendNetworkQualityTest(profile?.id ?? null),
                runsBandwidth
                    ? runCloudflareBandwidthTest()
                    : Promise.resolve(null),
                runNetworkProtocolTest()
            ]);



        if (abortTestIfOffline()) return;

        setText("protocolStatus", formatProtocolSummary(protocolResult));
        applyBackendMetrics(backendResult);
        applyBandwidthMetrics(bandwidthResult);

        // Browser-latency fallback only for the standard test.
        // Profiles must not silently swap in a different measurement.
        if (
            !profile &&
            (currentMetrics.ping === null ||
                currentMetrics.jitter === null)
        ) {
            const latency = await measureBrowserLatency();

            if (abortTestIfOffline()) return;

            if (currentMetrics.ping === null) {
                currentMetrics.ping = latency.ping;
            }

            if (currentMetrics.jitter === null) {
                currentMetrics.jitter = latency.jitter;
            }
        }

        if (abortTestIfOffline()) return;

        outcome = renderProfileResult(
            profile,
            backendResult,
            bandwidthResult
        );

        detectNetworkType();

        currentMetrics.score =
            sharedCalculateConnectivityScore(currentMetrics);

        lastTestTime = new Date().toISOString();

        updateDashboard();
        updateApplicationReadiness();
        updateAIAnalysis();
        updateNetworkRecommendation();

        await updateAISectionsFromBackend();

        const entry = {
            timestamp: lastTestTime,

            download_mbps: currentMetrics.download,
            upload_mbps: currentMetrics.upload,

            ping_ms: currentMetrics.ping,
            jitter_ms: currentMetrics.jitter,

            packet_loss: currentMetrics.packetLoss,

            connectivity_score: currentMetrics.score,

            network_type: currentMetrics.networkType,

            latitude: currentLocation?.latitude ?? null,
            longitude: currentLocation?.longitude ?? null
        };

        sessionTests.push(normalizeHistoryItem(entry));

        updateHistoryChart(sessionTests);
        updateSessionStatistics();

        // Do not save an empty record when every check failed.
        if (outcome?.state !== "error") {
            await saveNetworkTest(entry);
            await loadConnectivityForecast();
        }

        setText("testMessage", describeOutcome(profile, outcome));

        showToast(
            outcome?.state === "partial"
                ? "Test finished with some failed checks."
                : outcome?.state === "error"
                    ? "Diagnostic failed."
                    : "Network test completed."
        );

    } catch (error) {
        console.error("Network test failed:", error);

        setText(
            "testMessage",
            "Network test failed. Check that the backend server is running and you are connected to the internet, then try again."
        );

        showToast("Network test failed.");

    } finally {
        testInProgress = false;

        setStartButtonBusy(button, false);
        setProfileSelectorDisabled(false);

        if (profile && outcome === null) {
            renderProfileResultStopped();
        }

        if (isDeviceOffline()) {
            clearLiveMetrics();
            updateDashboard();
            updateApplicationReadiness();
            updateNetworkRecommendation();
        } else {
            updateNetworkStatus();
        }
    }
}
/* =========================================================
   DIAGNOSTIC PROFILES
   ========================================================= */

let diagnosticProfiles = [];
let selectedProfileId = null; // null = standard test (original behaviour)
let lastBackendError = null;

const CHECK_LABELS = {
    ping: "Latency (ping)",
    jitter: "Jitter",
    packet_loss: "Packet loss",
    download: "Download speed",
    upload: "Upload speed"
};

const CHECK_VALUES = {
    ping: ["ping_ms", "ms"],
    jitter: ["jitter_ms", "ms"],
    packet_loss: ["packet_loss", "%"]
};

async function readApiError(response) {
    try {
        const body = await response.json();
        const detail = body?.detail;
        if (typeof detail === "string") return detail;
        if (detail?.error) return detail.error;
    } catch (_) { /* fall through */ }
    return `Request failed (${response.status}).`;
}

async function loadDiagnosticProfiles(fetchProfiles = fetch) {
    try {
        const response = await fetchProfiles(`${API_BASE}/diagnostic-profiles`, { cache: "no-store" });
        if (!response.ok) throw new Error(`status ${response.status}`);
        const data = await response.json();
        diagnosticProfiles = Array.isArray(data.profiles) ? data.profiles : [];
    } catch (error) {
        console.warn("Diagnostic profiles unavailable:", error.message);
        diagnosticProfiles = [];
    }

    if (!diagnosticProfiles.some((p) => p.id === selectedProfileId)) {
        selectedProfileId = null;
    }
    renderProfileSelector();
    return diagnosticProfiles;
}

function getSelectedProfile() {
    return diagnosticProfiles.find((p) => p.id === selectedProfileId) ?? null;
}

function selectDiagnosticProfile(profileId) {
    selectedProfileId = diagnosticProfiles.some((profile) => profile.id === profileId)
        ? profileId
        : null;
    renderProfileSelector();
    return getSelectedProfile();
}

function renderProfileSelector() {
    const container = $("profileSelector");
    const note = $("profileNote");
    if (!container || typeof document === "undefined") return;

    container.replaceChildren();
    const choices = [
        { id: "", label: "Standard Test", description: "The original full network test." },
        ...diagnosticProfiles
    ];

    choices.forEach((profile) => {
        const label = document.createElement("label");
        label.className = "profile-card";
        const input = document.createElement("input");
        input.type = "radio";
        input.name = "diagnosticProfile";
        input.value = profile.id;
        input.checked = (profile.id || null) === selectedProfileId;
        input.addEventListener("change", () => {
            selectedProfileId = input.value || null;
        });
        const title = document.createElement("span");
        title.className = "profile-title";
        title.textContent = profile.label;
        const description = document.createElement("small");
        description.className = "profile-desc";
        description.textContent = profile.description || "";
        label.append(input, title, description);
        container.append(label);
    });
    if (note) note.hidden = diagnosticProfiles.length > 0;
}

/* Pure logic: no DOM. Builds per-check rows from THIS run only. */
function evaluateProfileResult(
    profile,
    backendResult,
    bandwidthResult,
    backendError = null
) {
    const backendChecks = backendResult?.checks ?? {};

    const rows = profile.checks.map((check) => {
        if (check === "download" || check === "upload") {
            const value = bandwidthResult?.[check];
            return isValidMetric(value)
                ? { check, status: "ok", detail: `${Number(value).toFixed(2)} Mbps` }
                : { check, status: "failed", detail: "Speed test unavailable or timed out." };
        }

        const info = backendChecks[check];

        if (!backendResult || !info) {
            return {
                check,
                status: "failed",
                detail: backendError || "The backend did not return this check."
            };
        }

        if (info.status === "ok") {
            const [key, unit] = CHECK_VALUES[check];
            const value = backendResult[key];
            if (!isValidMetric(value)) {
                return {
                    check,
                    status: "failed",
                    detail: "The backend marked this check successful without a valid measurement."
                };
            }
            return {
                check,
                status: "ok",
                detail: `${Number(value).toFixed(2)} ${unit}`
            };
        }

        return { check, status: "failed", detail: info.reason || "Check failed." };
    });

    const failed = rows.filter((row) => row.status === "failed");

    const state =
        failed.length === 0 ? "success"
        : failed.length === rows.length ? "error"
        : "partial";

    return {
        state,
        rows,
        failed: failed.map((row) => CHECK_LABELS[row.check] ?? row.check),
        measuredAt: backendResult?.measured_at ?? null
    };
}

function setProfileSelectorDisabled(disabled) {
    const container = $("profileSelector");
    if (container) container.disabled = disabled;
}

function showProfilePanel(state, build) {
    const panel = $("profileResult");
    if (!panel) return;
    panel.hidden = false;
    panel.dataset.state = state;
    panel.setAttribute("aria-busy", state === "loading" ? "true" : "false");
    panel.replaceChildren();
    build(panel);
}

function renderProfileResultLoading(profile) {
    const panel = $("profileResult");
    if (!profile) {
        if (panel) panel.hidden = true;
        return;
    }
    showProfilePanel("loading", (p) => {
        p.textContent = `Running ${profile.label}... please keep this tab open.`;
    });
}

function renderProfileResultStopped() {
    showProfilePanel("error", (p) => {
        p.textContent = "The test stopped before it finished. No fresh results to show.";
    });
}

function renderProfileResult(profile, backendResult, bandwidthResult) {
    if (!profile) return null;
    const evaluation = evaluateProfileResult(profile, backendResult, bandwidthResult, lastBackendError);

    showProfilePanel(evaluation.state, (panel) => {
        const heading = document.createElement("strong");
        heading.textContent = profile.label;

        const when = evaluation.measuredAt
            ? document.createElement("span")
            : null;
        if (when) {
            when.className = "profile-time";
            when.textContent = ` Measured at ${new Date(evaluation.measuredAt).toLocaleTimeString()}`;
        }

        const list = document.createElement("ul");
        evaluation.rows.forEach((row) => {
            const item = document.createElement("li");

            const badge = document.createElement("span");
            badge.className = "check-badge";
            badge.dataset.status = row.status;
            badge.textContent = row.status === "ok" ? "OK" : "Failed";

            const name = document.createElement("span");
            name.textContent = CHECK_LABELS[row.check] ?? row.check;

            const detail = document.createElement("span");
            detail.className = "profile-desc";
            detail.textContent = row.detail;

            item.append(badge, name, detail);
            list.append(item);
        });

        panel.append(heading, ...(when ? [when] : []), list);
    });

    return { state: evaluation.state, failed: evaluation.failed };
}

function describeOutcome(profile, outcome) {
    if (!profile || !outcome) return "Network test completed successfully.";
    if (outcome.state === "success") {
        return `${profile.label} completed. All checks succeeded.`;
    }
    if (outcome.state === "partial") {
        return `${profile.label} finished, but ${outcome.failed.length} check(s) failed: ${outcome.failed.join(", ")}.`;
    }
    return `${profile.label} failed. No check produced a result.`;
}
/* =========================================================
   BACKEND NETWORK QUALITY
   ========================================================= */

async function runBackendNetworkQualityTest(profileId = null) {
    lastBackendError = null;

    try {
        const query = profileId
            ? `?profile=${encodeURIComponent(profileId)}`
            : "";

        const response = await fetch(
            `${API_BASE}/network-quality${query}`,
            {
                method: "GET",
                cache: "no-store"
            }
        );

        if (!response.ok) {
            lastBackendError = await readApiError(response);
            throw new Error(
                `Network quality API returned ${response.status}`
            );
        }

        const data = await response.json();

        console.log("Backend network quality:", data);

        return data.metrics || data.data || data;

    } catch (error) {
        console.warn(
            "Backend network-quality endpoint unavailable:",
            error.message
        );

        lastBackendError = lastBackendError || error.message;

        return null;
    }
}

async function runBackendDnsCheck() {
    try {
        const response = await fetch(
            `${API_BASE}/dns-check`,
            { method: "GET", cache: "no-store" }
        );
        if (!response.ok) {
            throw new Error(`DNS check API returned ${response.status}`);
        }
        return await response.json();
    } catch (error) {
        console.warn("Backend DNS check unavailable:", error.message);
        return null;
    }
}

function formatDnsStatus(result) {
    if (!result || typeof result !== "object") {
        return "Server DNS: status unavailable.";
    }

    const duration = Number.isFinite(result.duration_ms)
        ? ` in ${result.duration_ms} ms`
        : "";

    if (result.status === "ok") {
        return `Server DNS: resolved${duration}.`;
    }

    const category = {
        not_found: "hostname not found",
        resolver_unavailable: "resolver unavailable",
        capacity_exhausted: "diagnostic capacity reached",
        timeout: "lookup timed out",
        unknown: "lookup failed"
    }[result.failure_category] || "lookup failed";

    return `Server DNS: ${category}${duration}.`;
} async function runNetworkProtocolTest() {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 5000);
    try {
        const response = await fetch(
            `${API_BASE}/network-protocols`,
            {
                method: "GET",
                cache: "no-store",
                signal: controller.signal
            }
        );

        if (!response.ok) {
            throw new Error(`Network protocol API returned ${response.status}`);
        }

        return await response.json();
    } catch (error) {
        console.warn("Network protocol endpoint unavailable:", error.message);
        return null;
    } finally {
        clearTimeout(timeout);
    }
}

function formatProtocolSummary(result) {
    if (!result || typeof result !== "object") {
        return "Server IPv4/IPv6 status is unavailable.";
    }

    const describe = (protocol, check) => {
        const label = protocol;
        if (!check || typeof check !== "object") {
            return `${label} status unknown`;
        }
        if (check.status === "available") {
            return `${label} connected`;
        }
        if (check.status === "unsupported") {
            return `${label} unsupported`;
        }
        const reason = {
            dns_failure: "DNS lookup failed",
            timeout: "connection timed out",
            connection_failure: "connection failed"
        }[check.reason] || "unavailable";
        return `${label} ${reason}`;
    };

    return `Server: ${describe("IPv4", result.ipv4)} · ${describe("IPv6", result.ipv6)}`;
}

function applyBackendMetrics(data) {
    if (!data || typeof data !== "object") return;

    currentMetrics.ping = firstValid(
        data.ping_ms,
        data.ping,
        currentMetrics.ping
    );

    currentMetrics.jitter = firstValid(
        data.jitter_ms,
        data.jitter,
        currentMetrics.jitter
    );

    currentMetrics.packetLoss = firstValid(
        data.packet_loss,
        data.packet_loss_percent,
        data.packetLoss,
        currentMetrics.packetLoss
    );

    currentMetrics.download = firstValid(
        data.download_mbps,
        data.download,
        data.downloadSpeed,
        currentMetrics.download
    );

    currentMetrics.upload = firstValid(
        data.upload_mbps,
        data.upload,
        data.uploadSpeed,
        currentMetrics.upload
    );

    currentMetrics.networkType =
        data.network_type ||
        data.networkType ||
        currentMetrics.networkType;
}

/* =========================================================
   CLOUDFLARE SPEED TEST
   ========================================================= */

async function runCloudflareBandwidthTest() {
    try {
        setText(
            "testMessage",
            "Measuring download and upload speed..."
        );

        const module = await import(
            "https://cdn.skypack.dev/@cloudflare/speedtest"
        );

        const SpeedTest = module.default;

        if (typeof SpeedTest !== "function") {
            throw new Error(
                "Cloudflare Speedtest module unavailable."
            );
        }

        const test = new SpeedTest({
            autoStart: false,

            measureDownloadLoadedLatency: false,
            measureUploadLoadedLatency: false,

            bandwidthFinishRequestDuration: 500,

            measurements: [
                {
                    type: "download",
                    bytes: 100000,
                    count: 2,
                    bypassMinDuration: true
                },
                {
                    type: "download",
                    bytes: 1000000,
                    count: 2,
                    bypassMinDuration: true
                },
                {
                    type: "upload",
                    bytes: 100000,
                    count: 2,
                    bypassMinDuration: true
                },
                {
                    type: "upload",
                    bytes: 1000000,
                    count: 2,
                    bypassMinDuration: true
                }
            ]
        });

        speedTest = test;

        return await new Promise((resolve) => {
            let completed = false;

            const finish = (result) => {
                if (completed) return;

                completed = true;

                clearTimeout(speedTestTimeout);

                resolve(result);
            };

            test.onResultsChange = ({ type } = {}) => {
                try {
                    if (isDeviceOffline()) return;

                    if (type === "download") {
                        const value =
                            test.results?.getDownloadBandwidth?.();

                        if (isValidMetric(value)) {
                            currentMetrics.download =
                                Number(value) / 1000000;

                            setText(
                                "download",
                                currentMetrics.download.toFixed(2)
                            );
                        }
                    }

                    if (type === "upload") {
                        const value =
                            test.results?.getUploadBandwidth?.();

                        if (isValidMetric(value)) {
                            currentMetrics.upload =
                                Number(value) / 1000000;

                            setText(
                                "upload",
                                currentMetrics.upload.toFixed(2)
                            );
                        }
                    }

                } catch (error) {
                    console.debug(
                        "Live bandwidth result not ready:",
                        error
                    );
                }
            };

            test.onFinish = (results) => {
                let download = null;
                let upload = null;

                try {
                    download = safeNumber(
                        results?.getDownloadBandwidth?.()
                    );

                    upload = safeNumber(
                        results?.getUploadBandwidth?.()
                    );

                } catch (error) {
                    console.warn(
                        "Could not read final speed results:",
                        error
                    );
                }

                finish({
                    download:
                        download === null ? null : download / 1000000,

                    upload:
                        upload === null ? null : upload / 1000000
                });
            };

            test.onError = (error) => {
                console.warn("Cloudflare speed test error:", error);

                finish({
                    download: null,
                    upload: null
                });
            };

            speedTestTimeout = setTimeout(() => {
                try {
                    test.pause?.();
                } catch (_) {}

                finish({
                    download: null,
                    upload: null
                });

            }, 90000);

            try {
                test.play();

            } catch (error) {
                console.error(
                    "Could not start Cloudflare test:",
                    error
                );

                finish({
                    download: null,
                    upload: null
                });
            }
        });

    } catch (error) {
        console.warn(
            "Cloudflare Speedtest unavailable:",
            error.message
        );

        return {
            download: null,
            upload: null
        };
    }
}

function applyBandwidthMetrics(result) {
    if (!result) return;

    if (
        currentMetrics.download === null &&
        isValidMetric(result.download)
    ) {
        currentMetrics.download = Number(result.download);
    }

    if (
        currentMetrics.upload === null &&
        isValidMetric(result.upload)
    ) {
        currentMetrics.upload = Number(result.upload);
    }
}

/* =========================================================
   BROWSER LATENCY
   ========================================================= */

async function measureBrowserLatency() {
    const samples = [];

    for (let i = 0; i < 4; i++) {
        const start = performance.now();

        try {
            await fetch(
                `https://www.cloudflare.com/cdn-cgi/trace?nocache=${Date.now()}-${i}`,
                {
                    cache: "no-store",
                    mode: "no-cors"
                }
            );

            samples.push(performance.now() - start);

        } catch (error) {
            console.debug("Latency sample failed:", error);
        }
    }

    if (!samples.length) {
        return {
            ping: null,
            jitter: null
        };
    }

    const average =
        samples.reduce((sum, value) => sum + value, 0) /
        samples.length;

    const deviations = samples.map(
        (value) => Math.abs(value - average)
    );

    const jitter =
        deviations.reduce((sum, value) => sum + value, 0) /
        deviations.length;

    return {
        ping: Number(average.toFixed(2)),
        jitter: Number(jitter.toFixed(2))
    };
}

/* =========================================================
   CONNECTIVITY SCORE
   ========================================================= */

function getConnectivityStatus(score) {
    return resolveConnectivityIndicator(score, {
        isOffline: isDeviceOffline()
    }).status;
}

/* =========================================================
   DASHBOARD
   ========================================================= */

function updateDashboard() {
    const offline = isDeviceOffline();

    if (offline) {
        currentMetrics.score = 0;
    } else {
        currentMetrics.score =
            sharedCalculateConnectivityScore(currentMetrics);
    }

    const display = resolveDashboardDisplayState(currentMetrics, {
        isOffline: offline,
        isTesting: testInProgress,
        isHistoryRestored: metricsRestoredFromHistory
    });

    setText("download", display.download);
    setText("upload", display.upload);
    setText("ping", display.ping);
    setText("jitter", display.jitter);
    setText("packetLoss", display.packetLoss);
    setText("metricsSubtitle", display.metricsSubtitle);

    const networkLabel = offline
        ? "Offline"
        : (currentMetrics.networkType || "Unknown");
    const networkDetail = offline
        ? (
            currentMetrics.networkType === "Offline" &&
            currentMetrics.networkTypeDetail
                ? currentMetrics.networkTypeDetail
                : "No internet connection"
          )
        : currentMetrics.networkTypeDetail;

    setText("networkType", networkLabel);

    if (networkDetail) {
        setText("networkTypeDetail", networkDetail);
    }

    setText("score", String(display.score));
    setProgress("scoreProgress", display.score);

    const scoreMeter = typeof $ === "function" ? $("scoreMeter") : null;
    scoreMeter?.setAttribute?.("aria-valuenow", String(display.score));

    applyConnectivityStatusIndicator(display.score);

    if (offline && !testInProgress) {
        setText(
            "testMessage",
            "Your device is offline. Connect to a network first."
        );
    }

    updateSessionStatistics();
}

/* =========================================================
   APPLICATION READINESS
   ========================================================= */

function updateApplicationReadiness() {
    const offline = isDeviceOffline();
    const download = offline ? null : safeNumber(currentMetrics.download);
    const upload = offline ? null : safeNumber(currentMetrics.upload);
    const ping = offline ? null : safeNumber(currentMetrics.ping);
    const jitter = offline ? null : safeNumber(currentMetrics.jitter);
    const loss = offline ? null : safeNumber(currentMetrics.packetLoss);

    const gaming = readinessScore(
        [
            download === null ? null : Math.min(25, download * 2.5),
            upload === null ? null : Math.min(15, upload * 3),
            ping === null ? null : Math.max(0, 35 - ping * 0.35),
            jitter === null ? null : Math.max(0, 15 - jitter * 0.75),
            loss === null ? null : Math.max(0, 10 - loss * 5)
        ],
        [25, 15, 35, 15, 10]
    );

    const video = readinessScore(
        [
            download === null ? null : Math.min(25, download * 5),
            upload === null ? null : Math.min(30, upload * 6),
            ping === null ? null : Math.max(0, 20 - ping * 0.08),
            jitter === null ? null : Math.max(0, 15 - jitter * 0.3),
            loss === null ? null : Math.max(0, 10 - loss * 3)
        ],
        [25, 30, 20, 15, 10]
    );

    const streaming = download === null
        ? null
        : download >= 25 ? 100
        : download >= 10 ? 85
        : download >= 5 ? 70
        : download >= 3 ? 55
        : download >= 1 ? 30
        : 10;

    const browsing = readinessScore(
        [
            download === null ? null : Math.min(55, download * 5.5),
            ping === null ? null : Math.max(0, 35 - ping * 0.12),
            loss === null ? null : Math.max(0, 10 - loss * 2)
        ],
        [55, 35, 10]
    );

    updateReadinessDisplay("gamingScore", "gamingProgress", gaming);

    updateReadinessDisplay(
        "videoCallScore",
        "videoCallProgress",
        video
    );

    updateReadinessDisplay(
        "streamingScore",
        "streamingProgress",
        streaming
    );

    updateReadinessDisplay(
        "browsingScore",
        "browsingProgress",
        browsing
    );
}

function readinessScore(parts, maxima) {
    let earned = 0;
    let available = 0;

    parts.forEach((value, index) => {
        if (value !== null && Number.isFinite(value)) {
            earned += value;
            available += maxima[index];
        }
    });

    if (!available) return null;

    return Math.round(
        Math.max(0, Math.min(100, earned / available * 100))
    );
}

function updateReadinessDisplay(textId, barId, value) {
    setText(
        textId,
        value === null ? "—" : `${value}%`
    );

    setProgress(barId, value === null ? 0 : value);

    // The bar's parent track carries role="progressbar".
    const track = $(barId)?.parentElement;

    if (track?.setAttribute) {
        track.setAttribute(
            "aria-valuenow",
            String(value === null ? 0 : value)
        );
        track.setAttribute(
            "aria-valuetext",
            value === null ? "Not available" : `${value}%`
        );
    }
}

/* =========================================================
   AI ANALYSIS
   ========================================================= */

function updateAIAnalysis() {
    const prediction = $("predictionResult");
    const anomaly = $("anomalyResult");

    if (sessionTests.length < 2) {
        if (prediction) {
            prediction.textContent =
                "Collect more network measurements to identify connectivity trends.";
        }

        if (anomaly) {
            anomaly.textContent =
                "Insufficient measurements for reliable anomaly analysis.";
        }

        return;
    }

    const recent = sessionTests.slice(-5);

    const speeds = recent
        .map((item) => safeNumber(item.download_mbps))
        .filter((value) => value !== null);

    const pings = recent
        .map((item) => safeNumber(item.ping))
        .filter((value) => value !== null);

    if (prediction) {
        if (speeds.length >= 2) {
            const first = speeds[0];
            const last = speeds[speeds.length - 1];

            prediction.textContent =
                last > first
                    ? "Recent download measurements show an improving trend."
                    : last < first
                    ? "Recent download measurements show a declining trend."
                    : "Download performance appears relatively stable.";
        } else {
            prediction.textContent =
                "More download measurements are required.";
        }
    }

    if (anomaly) {
        if (pings.length >= 2) {
            const average =
                pings.reduce((sum, value) => sum + value, 0) /
                pings.length;

            const latest = pings[pings.length - 1];

            anomaly.textContent =
                latest > average * 1.5
                    ? "Possible latency anomaly detected."
                    : "No significant latency anomaly detected.";
        } else {
            anomaly.textContent =
                "More latency measurements are required.";
        }
    }
}

function formatAnomalyMetric(metric) {
    if (!metric || !ANOMALY_METRIC_LABELS[metric.feature]) {
        return null;
    }

    const observed = safeNumber(metric.observed_value);
    const reconstructed = safeNumber(metric.reconstructed_value);
    const absoluteError = safeNumber(metric.absolute_error);
    const normalizedError = safeNumber(metric.normalized_error);
    const contribution = safeNumber(metric.contribution_percent);
    const rank = safeNumber(metric.rank);

    if (
        observed === null ||
        reconstructed === null ||
        absoluteError === null ||
        normalizedError === null ||
        contribution === null ||
        rank === null ||
        rank < 1 ||
        !Number.isInteger(rank) ||
        contribution < 0
    ) {
        return null;
    }

    const unit = METRIC_UNITS[metric.feature];
    return `Rank ${rank}: ${ANOMALY_METRIC_LABELS[metric.feature]} — observed ${formatMetric(observed, unit, 2)}, reconstructed ${formatMetric(reconstructed, unit, 2)} (error ${formatMetric(absoluteError, unit, 2)}; standardized error ${normalizedError.toFixed(2)}); ${contribution.toFixed(1)}% contribution.`;
}

function renderAnomalyExplanation(explanation) {
    const list = $("anomalyExplanation");
    if (!list) return;

    while (list.firstChild) {
        list.removeChild(list.firstChild);
    }

    const metrics = Array.isArray(explanation?.metrics)
        ? explanation.metrics
        : [];
    const lines = metrics
        .map(formatAnomalyMetric)
        .filter((line) => line !== null)
        .slice(0, 3);

    if (!lines.length) {
        list.hidden = true;
        return;
    }

    lines.forEach((line) => {
        const item = document.createElement("li");
        item.textContent = line;
        list.appendChild(item);
    });

    list.hidden = false;
}

async function updateAISectionsFromBackend() {
    try {
        const response = await fetch(
            `${API_BASE}/ai/analyze`,
            { cache: "no-store" }
        );

        if (!response.ok) {
            renderAnomalyExplanation(null);
            const prediction = $("predictionResult");
            if (prediction) {
                prediction.textContent =
                    "AI service is unavailable. Showing local analysis: " +
                    prediction.textContent;
            }
            return;
        }

        const result = await response.json();

        if (!result?.success) {
            renderAnomalyExplanation(null);
            const prediction = $("predictionResult");
            if (prediction) {
                prediction.textContent =
                    "AI analysis is unavailable. Showing local analysis: " +
                    prediction.textContent;
            }
            return;
        }

        const predictionData = result.prediction || {};
        const anomalyData = result.anomaly || {};
        renderAnomalyExplanation(anomalyData.explanation);

        if (
            predictionData.predicted_connectivity_score !== undefined
        ) {
            setText(
                "predictionResult",
                `Predicted connectivity score: ${Number(
                    predictionData.predicted_connectivity_score
                ).toFixed(2)}/100 (${predictionData.predicted_quality || "Unknown"}).`
            );
        }

        if (typeof anomalyData.anomaly === "boolean") {
            const error = safeNumber(
                anomalyData.reconstruction_error
            );

            const threshold = safeNumber(
                anomalyData.threshold
            );

            setText(
                "anomalyResult",
                anomalyData.anomaly
                    ? `Anomaly detected. Reconstruction error: ${error === null ? "Unavailable" : error.toFixed(6)}.`
                    : `No anomaly detected. Reconstruction error: ${error === null ? "Unavailable" : error.toFixed(6)}.`
            );
        }

    } catch (error) {
        renderAnomalyExplanation(null);
        const prediction = $("predictionResult");
        if (prediction) {
            prediction.textContent =
                "AI service is unavailable. Showing local analysis: " +
                prediction.textContent;
        }
        console.info(
            "Backend AI analysis unavailable:",
            error.message
        );
    }
}

/* =========================================================
   CONNECTIVITY FORECAST
   ========================================================= */

const FORECAST_METRIC_META = Object.freeze({
    connectivity_score: { label: "Connectivity Score", unit: "/100", decimals: 1 },
    download_mbps: { label: "Download Speed", unit: "Mbps", decimals: 1 },
    upload_mbps: { label: "Upload Speed", unit: "Mbps", decimals: 1 },
    ping_ms: { label: "Ping", unit: "ms", decimals: 1 },
    jitter_ms: { label: "Jitter", unit: "ms", decimals: 1 },
    packet_loss: { label: "Packet Loss", unit: "%", decimals: 2 }
});

function resolveForecastRiskMeta(level) {
    const normalized = typeof level === "string" ? level.trim().toLowerCase() : "";
    if (normalized === "high") {
        return {
            key: "high",
            label: "High Risk",
            iconClass: "fa-solid fa-triangle-exclamation"
        };
    }
    if (normalized === "moderate") {
        return {
            key: "moderate",
            label: "Moderate Risk",
            iconClass: "fa-solid fa-circle-exclamation"
        };
    }
    if (normalized === "low") {
        return {
            key: "low",
            label: "Low Risk",
            iconClass: "fa-solid fa-circle-check"
        };
    }
    if (
        normalized === "insufficient data" ||
        normalized === "insufficient_data" ||
        normalized === "insufficient"
    ) {
        return {
            key: "insufficient",
            label: "Insufficient Data",
            iconClass: "fa-solid fa-circle-info"
        };
    }
    return {
        key: "unavailable",
        label: "Pending Forecast",
        iconClass: "fa-solid fa-circle-info"
    };
}

function formatForecastRange(metricEntry, decimals = 1) {
    if (!metricEntry || typeof metricEntry !== "object") return "Unavailable";
    const predicted = safeNumber(metricEntry.predicted);
    const lower = safeNumber(metricEntry.lower);
    const upper = safeNumber(metricEntry.upper);
    const unit = metricEntry.unit || "";

    if (predicted === null) return "Unavailable";
    const mainText = formatMetric(predicted, unit, decimals);
    if (lower === null || upper === null) return mainText;
    return `${mainText} (${lower.toFixed(decimals)} – ${upper.toFixed(decimals)})`;
}

function normalizeForecastResponse(payload) {
    if (!payload || typeof payload !== "object" || !Array.isArray(payload.horizons)) {
        return null;
    }

    const horizons = payload.horizons.filter(
        (item) =>
            item &&
            typeof item.horizon === "string" &&
            item.metrics &&
            typeof item.metrics === "object"
    );

    if (horizons.length === 0) {
        return null;
    }

    return {
        success: Boolean(payload.success),
        generated_at: payload.generated_at || null,
        history_summary: payload.history_summary || {},
        degradation_risk: payload.degradation_risk || {
            level: "Insufficient Data",
            score: null,
            reasons: []
        },
        horizons
    };
}

function updateForecastRiskBadge(risk) {
    const badge = $("forecastRiskBadge");
    const icon = $("forecastRiskIcon");
    const text = $("forecastRiskText");
    if (!badge || !text) return;

    const meta = resolveForecastRiskMeta(risk?.level);
    badge.dataset.risk = meta.key;

    const score = safeNumber(risk?.score);
    text.textContent =
        score !== null &&
        meta.key !== "unavailable" &&
        meta.key !== "insufficient"
            ? `${meta.label} (${Math.round(score)}/100)`
            : meta.label;

    if (icon) {
        icon.className = meta.iconClass;
    }
}

function updateForecastChart(forecastData, metricKey = "connectivity_score") {
    const container = $("forecastChartContainer");
    const canvas = $("forecastChart");
    if (!container || !canvas) return;

    const normalized = normalizeForecastResponse(forecastData);
    if (!normalized) {
        container.hidden = true;
        return;
    }

    const meta = FORECAST_METRIC_META[metricKey] || FORECAST_METRIC_META.connectivity_score;
    const points = normalized.horizons.map((item) => item.metrics?.[metricKey] || {});
    const hasValues = points.some((m) => safeNumber(m.predicted) !== null);

    if (!hasValues) {
        container.hidden = true;
        return;
    }

    container.hidden = false;
    const baseline = safeNumber(points[0]?.baseline);
    const labels = baseline !== null
        ? ["Now", ...normalized.horizons.map((h) => `+${h.horizon}`)]
        : normalized.horizons.map((h) => `+${h.horizon}`);

    const predictedSeries = baseline !== null
        ? [baseline, ...points.map((m) => safeNumber(m.predicted))]
        : points.map((m) => safeNumber(m.predicted));

    const upperSeries = baseline !== null
        ? [baseline, ...points.map((m) => safeNumber(m.upper))]
        : points.map((m) => safeNumber(m.upper));

    const lowerSeries = baseline !== null
        ? [baseline, ...points.map((m) => safeNumber(m.lower))]
        : points.map((m) => safeNumber(m.lower));

    canvas.setAttribute(
        "aria-label",
        `${meta.label} forecast chart across ${normalized.horizons.map((h) => h.horizon).join(", ")} horizons.`
    );

    if (typeof Chart === "undefined") {
        return;
    }

    const context = canvas.getContext("2d");
    if (!context) return;

    if (forecastChart) {
        forecastChart.data.labels = labels;
        forecastChart.data.datasets[0].data = upperSeries;
        forecastChart.data.datasets[1].data = lowerSeries;
        forecastChart.data.datasets[2].label = `Predicted ${meta.label} (${meta.unit})`;
        forecastChart.data.datasets[2].data = predictedSeries;
        forecastChart.update();
        return;
    }

    forecastChart = new Chart(context, {
        type: "line",
        data: {
            labels,
            datasets: [
                {
                    label: "Upper Confidence Bound",
                    data: upperSeries,
                    borderColor: "rgba(139, 92, 246, 0.35)",
                    borderDash: [4, 4],
                    borderWidth: 1.5,
                    pointRadius: 0,
                    fill: false,
                    tension: 0.3
                },
                {
                    label: "Lower Confidence Bound",
                    data: lowerSeries,
                    borderColor: "rgba(139, 92, 246, 0.35)",
                    backgroundColor: "rgba(139, 92, 246, 0.14)",
                    borderDash: [4, 4],
                    borderWidth: 1.5,
                    pointRadius: 0,
                    fill: "-1",
                    tension: 0.3
                },
                {
                    label: `Predicted ${meta.label} (${meta.unit})`,
                    data: predictedSeries,
                    borderColor: "#7c3aed",
                    backgroundColor: "rgba(124, 58, 237, 0.15)",
                    borderWidth: 2.5,
                    pointRadius: 4,
                    pointHoverRadius: 6,
                    fill: false,
                    tension: 0.3
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: "index", intersect: false },
            plugins: {
                legend: { display: true }
            },
            scales: {
                y: {
                    beginAtZero: true
                }
            }
        }
    });
}

function renderForecastSection(payload, unavailableMessage = null) {
    const statusEl = $("forecastStatus");
    const horizonsEl = $("forecastHorizons");
    const reasonsEl = $("forecastRiskReasons");
    const chartContainer = $("forecastChartContainer");
    const normalized = normalizeForecastResponse(payload);

    if (!normalized) {
        latestForecastData = null;
        updateForecastRiskBadge(null);
        if (horizonsEl) {
            while (horizonsEl.firstChild) horizonsEl.removeChild(horizonsEl.firstChild);
        }
        if (reasonsEl) {
            while (reasonsEl.firstChild) reasonsEl.removeChild(reasonsEl.firstChild);
            reasonsEl.hidden = true;
        }
        if (chartContainer) chartContainer.hidden = true;
        if (statusEl) {
            statusEl.textContent =
                unavailableMessage ||
                "Connectivity forecast is currently unavailable.";
        }
        return;
    }

    const summary = normalized.history_summary || {};
    const totalRecords = safeNumber(summary.total_records, 0);
    const hasHistory = totalRecords > 0;
    const isFallback = !hasHistory || Boolean(summary.fallback_used) || summary.sufficient_history === false;

    latestForecastData = normalized;
    updateForecastRiskBadge(
        isFallback
            ? { level: "Insufficient Data", score: null }
            : normalized.degradation_risk
    );

    if (statusEl) {
        if (!hasHistory) {
            statusEl.textContent =
                "Not enough historical measurements yet. Run a connectivity test to start forecasting.";
        } else if (isFallback) {
            statusEl.textContent =
                `Sparse-history fallback active (${totalRecords} saved measurement${totalRecords === 1 ? "" : "s"}). Confidence ranges narrow as more tests accumulate.`;
        } else {
            statusEl.textContent =
                `Forecast computed from ${totalRecords} measurements across ${summary.window_count || 0} rolling time windows.`;
        }
    }

    if (horizonsEl) {
        while (horizonsEl.firstChild) horizonsEl.removeChild(horizonsEl.firstChild);

        if (hasHistory) {
            normalized.horizons.forEach((entry) => {
            const card = document.createElement("article");
            card.className = "forecast-horizon-card";

            const header = document.createElement("div");
            header.className = "forecast-horizon-header";

            const title = document.createElement("h3");
            title.className = "forecast-horizon-title";
            title.textContent = `+${entry.horizon} Horizon`;

            const riskLevel = isFallback
                ? "Insufficient Data"
                : (entry.degradation_risk?.level || "Insufficient Data");
            const riskMeta = resolveForecastRiskMeta(riskLevel);
            const miniBadge = document.createElement("span");
            miniBadge.className = "forecast-risk-badge";
            miniBadge.dataset.risk = riskMeta.key;
            const miniIcon = document.createElement("i");
            miniIcon.className = riskMeta.iconClass;
            miniIcon.setAttribute("aria-hidden", "true");
            const miniLabel = document.createElement("span");
            miniLabel.textContent = riskMeta.label;
            miniBadge.append(miniIcon, miniLabel);

            header.append(title, miniBadge);

            const scoreMetric = entry.metrics?.connectivity_score;
            const scoreEl = document.createElement("div");
            scoreEl.className = "forecast-horizon-score";
            const predScore = safeNumber(scoreMetric?.predicted);
            scoreEl.textContent =
                predScore !== null ? `${predScore.toFixed(1)} / 100` : "Unavailable";

            const rangeEl = document.createElement("p");
            rangeEl.className = "forecast-horizon-range";
            rangeEl.textContent =
                predScore !== null
                    ? `Range: ${formatForecastRange(scoreMetric, 1)}`
                    : "Collect more measurements to project score range";

            const list = document.createElement("dl");
            list.className = "forecast-horizon-metrics";

            const rows = [
                ["Download", entry.metrics?.download_mbps, 1],
                ["Upload", entry.metrics?.upload_mbps, 1],
                ["Ping", entry.metrics?.ping_ms, 1],
                ["Packet Loss", entry.metrics?.packet_loss, 2]
            ];

            rows.forEach(([label, metricVal, dec]) => {
                const dt = document.createElement("dt");
                dt.textContent = label;
                const dd = document.createElement("dd");
                const num = safeNumber(metricVal?.predicted);
                dd.textContent =
                    num !== null ? formatMetric(num, metricVal?.unit || "", dec) : "—";
                list.append(dt, dd);
            });

                card.append(header, scoreEl, rangeEl, list);
                horizonsEl.appendChild(card);
            });
        }
    }

    if (reasonsEl) {
        while (reasonsEl.firstChild) reasonsEl.removeChild(reasonsEl.firstChild);
        const reasons = Array.isArray(normalized.degradation_risk?.reasons)
            ? normalized.degradation_risk.reasons
            : [];
        if (reasons.length > 0) {
            reasons.forEach((reason) => {
                const li = document.createElement("li");
                li.textContent = `• ${reason}`;
                reasonsEl.appendChild(li);
            });
            reasonsEl.hidden = false;
        } else {
            reasonsEl.hidden = true;
        }
    }

    const selectedMetric = $("forecastMetric")?.value || "connectivity_score";
    updateForecastChart(normalized, selectedMetric);
}

async function loadConnectivityForecast(horizons = "1h,6h,24h") {
    try {
        const params = new URLSearchParams({ horizons });
        const response = await fetch(
            `${API_BASE}/predict/forecast?${params.toString()}`,
            { cache: "no-store" }
        );
        if (!response.ok) {
            renderForecastSection(
                null,
                "Forecast service is currently unavailable."
            );
            return null;
        }
        const payload = await response.json();
        renderForecastSection(payload);
        return payload;
    } catch (error) {
        console.info("Backend connectivity forecast unavailable:", error.message);
        renderForecastSection(
            null,
            "Forecast service is unavailable. Check backend connection."
        );
        return null;
    }
}

function updateNetworkRecommendation() {
    let recommendation =
        "Continue monitoring your connection.";

    if (isDeviceOffline()) {
        recommendation =
            "No active internet connection detected. Check Wi-Fi, mobile data, or airplane mode settings.";

    } else if (
        currentMetrics.ping !== null &&
        currentMetrics.ping > 100
    ) {
        recommendation =
            "High response latency detected. Try moving closer to your router or checking network congestion.";

    } else if (
        currentMetrics.download !== null &&
        currentMetrics.download < 10
    ) {
        recommendation =
            "Download speed is low. Check background downloads and router placement.";

    } else if (
        currentMetrics.packetLoss !== null &&
        currentMetrics.packetLoss > 2
    ) {
        recommendation =
            "Packet loss detected. Check your router, Wi-Fi signal and network connection.";

    } else if (currentMetrics.score >= 80) {
        recommendation =
            "Your measured network performance looks good.";
    }

    setText("recommendation", recommendation);
}

/* =========================================================
   SAVE NETWORK TEST
   ========================================================= */

async function saveNetworkTest(testData) {
    try {
        const response = await fetch(
            `${API_BASE}/network-test`,
            {
                method: "POST",

                headers: {
                    "Content-Type": "application/json"
                },

                body: JSON.stringify(testData)
            }
        );

        if (response.ok) {
            console.log("Network test saved to backend.");
            return;
        }

        console.warn(
            "POST /network-test returned:",
            response.status
        );

    } catch (error) {
        console.warn(
            "Could not save network test:",
            error.message
        );
    }
}

/* =========================================================
   CSV EXPORT
   ========================================================= */

function exportHistoryToCSV() {
    if (!sessionTests.length) {
        showToast("No network history available to export.");
        return;
    }

    const headers = [
        "Timestamp",
        "Download Mbps",
        "Upload Mbps",
        "Ping ms",
        "Jitter ms",
        "Packet Loss %",
        "Connectivity Score"
    ];

    const rows = sessionTests.map((raw) => {
        const item = normalizeHistoryItem(raw);

        return [
            item.timestamp,
            item.download_mbps ?? "",
            item.upload_mbps ?? "",
            item.ping ?? "",
            item.jitter ?? "",
            item.packet_loss ?? "",
            item.connectivity_score ?? ""
        ];
    });

    const csv = [headers, ...rows]
        .map((row) =>
            row.map((value) =>
                `"${String(value).replace(/"/g, '""')}"`
            ).join(",")
        )
        .join("\r\n");

    const blob = new Blob(
        ["\uFEFF" + csv],
        { type: "text/csv;charset=utf-8;" }
    );

    const url = URL.createObjectURL(blob);

    const link = document.createElement("a");

    link.href = url;

    link.download =
        `connectivity-history-${new Date().toISOString().slice(0, 10)}.csv`;

    document.body.appendChild(link);

    link.click();

    link.remove();

    URL.revokeObjectURL(url);

    showToast("CSV exported successfully.");
}

/* =========================================================
   SESSION TIMER
   ========================================================= */

function startSessionTimer() {
    if (sessionTimer) {
        clearInterval(sessionTimer);
    }

    const update = () => {
        const elapsed = Math.floor(
            (Date.now() - sessionStartTime) / 1000
        );

        const hours = Math.floor(elapsed / 3600);

        const minutes = Math.floor(
            (elapsed % 3600) / 60
        );

        const seconds = elapsed % 60;

        setText(
            "sessionTime",
            [hours, minutes, seconds]
                .map((value) =>
                    String(value).padStart(2, "0")
                )
                .join(":")
        );

        updateSessionStatistics();
    };

    update();

    sessionTimer = setInterval(update, 1000);
}

/* =========================================================
   SESSION STATISTICS
   ========================================================= */

function updateSessionStatistics() {
    const speeds = sessionTests
        .map((raw) =>
            safeNumber(
                normalizeHistoryItem(raw).download_mbps
            )
        )
        .filter((value) => value !== null);

    const pings = sessionTests
        .map((raw) =>
            safeNumber(
                normalizeHistoryItem(raw).ping
            )
        )
        .filter((value) => value !== null);

    const averageSpeed = speeds.length
        ? speeds.reduce((a, b) => a + b, 0) / speeds.length
        : null;

    const averagePing = pings.length
        ? pings.reduce((a, b) => a + b, 0) / pings.length
        : null;

    const peakSpeed = speeds.length
        ? Math.max(...speeds)
        : null;

    setText(
        "averageSpeed",
        averageSpeed === null
            ? "—"
            : `${averageSpeed.toFixed(2)} Mbps`
    );

    setText(
        "averagePing",
        averagePing === null
            ? "—"
            : `${averagePing.toFixed(2)} ms`
    );

    setText(
        "peakSpeed",
        peakSpeed === null
            ? "—"
            : `${peakSpeed.toFixed(2)} Mbps`
    );

    setText(
        "downtime",
        `${Math.floor(downtimeSeconds / 60)} min`
    );
}

/* =========================================================
   BACKEND HEALTH
   ========================================================= */

async function checkBackendHealth() {
    try {
        const response = await fetch(
            `${API_BASE}/health`,
            { cache: "no-store" }
        );

        if (!response.ok) return false;

        return true;

    } catch (error) {
        console.warn(
            "Backend health check failed:",
            error.message
        );

        return false;
    }
}

/* =========================================================
   PUBLIC API
   ========================================================= */

const smartConnectivity = {
    getCurrentNetworkData() {
        return {
            ...currentMetrics,
            location: currentLocation,
            history: sessionTests
        };
    },

    checkBackendHealth,
    loadNetworkHistory,
    detectLocation,
    saveLocation,
    findBetterArea,
    startNetworkTest,
    exportHistoryToCSV,
    validateHistoryFilterValues,
    calculateConnectivityScore: sharedCalculateConnectivityScore,
    getConnectivityStatus,
    resolveConnectivityIndicator,
    resolveDashboardDisplayState,
    isDeviceOffline,
    clearLiveMetrics,
    updateDashboard,
    updateNetworkStatus,
    resolveNetworkType,
    detectNetworkType,
    normalizeForecastResponse,
    resolveForecastRiskMeta,
    formatForecastRange,
    loadConnectivityForecast,
    renderForecastSection
};

/* ─── Browser Exports ───────────────────────────────── */

if (typeof window !== "undefined") {
    window.smartConnectivity = smartConnectivity;

    window.calculateConnectivityScore =
        sharedCalculateConnectivityScore;

    window.getConnectivityStatus =
        getConnectivityStatus;

    window.resolveConnectivityIndicator =
        resolveConnectivityIndicator;

    window.resolveDashboardDisplayState =
        resolveDashboardDisplayState;

    window.isDeviceOffline =
        isDeviceOffline;

    window.updateDashboard =
        updateDashboard;

    window.exportHistoryToCSV =
        exportHistoryToCSV;

    window.loadNetworkHistory =
        loadNetworkHistory;

    window.applyHistoryMetricFilter =
        applyHistoryMetricFilter;

    window.normalizeHistoryItem =
        normalizeHistoryItem;

    window.METRIC_UNITS = METRIC_UNITS;

    window.resolveNetworkType =
        resolveNetworkType;

    window.detectNetworkType =
        detectNetworkType;

    window.loadConnectivityForecast =
        loadConnectivityForecast;
}

/* ─── Node.js Exports for Tests ─────────────────────── */

if (typeof module !== "undefined" && module.exports) {
    module.exports = {
        METRIC_UNITS,
        isValidMetricNumber,
        formatNumber,
        formatMetric,
        formatNetworkMetric,
        validateHistoryFilterValues,
        evaluateProfileResult,
        loadDiagnosticProfiles,
        selectDiagnosticProfile,
        getSelectedProfile,
        describeOutcome,
        calculateConnectivityScore: sharedCalculateConnectivityScore,
        getConnectivityStatus,
        resolveConnectivityIndicator,
        ..._metrics,
        ..._networkStatus,
        resolveDashboardDisplayState,
        isDeviceOffline,
        clearLiveMetrics,
        applyConnectivityStatusIndicator,
        updateDashboard,
        updateNetworkStatus,
        handleConnectivityTransition,
        formatAnomalyMetric,
        loadNetworkHistory,
        normalizeHistoryItem,
        applyHistoryMetricFilter,
        smartConnectivity,
        resolveNetworkType,
        detectNetworkType,
        formatDnsStatus,
        normalizeForecastResponse,
        resolveForecastRiskMeta,
        formatForecastRange,
        loadConnectivityForecast,
        renderForecastSection,
        formatProtocolSummary,
        runNetworkProtocolTest
    };
}
/* =========================================================
   END OF SCRIPT
   ========================================================= */

