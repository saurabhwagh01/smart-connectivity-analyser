/**
 * Tests for the Run Test loading state (Issue #59).
 *
 * Verifies the complete testing lifecycle against a stubbed DOM and a
 * stubbed fetch, driving the real startNetworkTest() from js/script.js:
 *
 * 1. Previous results stay visible during a test and the loading state
 *    ("Testing network...") is shown — regression test for the snapshot
 *    order fixed after the PR #66 review: the previous-metrics snapshot
 *    must be taken BEFORE currentMetrics is reset, otherwise the
 *    snapshot would only preserve the null values and the dashboard
 *    would show "Unavailable" mid-test.
 * 2. New metrics are displayed only after successful completion.
 * 3. Multiple simultaneous test requests are prevented.
 * 4. An offline interruption restores the previous metrics and clears
 *    the loading state.
 * 5. A run that produces no measurements at all is reported as a
 *    failure and restores the previous metrics.
 *
 * No real network is used: fetch is stubbed, and the Cloudflare
 * Speedtest dynamic import fails (unsupported URL scheme in Node) and
 * is handled by the implementation as "no bandwidth result".
 */

const test = require("node:test");
const assert = require("node:assert/strict");

/* ─── Minimal DOM stub ──────────────────────────────────── */

function createElement() {
    const classes = new Set();
    const attributes = {};

    return {
        textContent: "",
        value: "",
        hidden: false,
        dataset: {},
        style: {},
        parentElement: null,
        classList: {
            add: (...names) => {
                names.forEach((name) => classes.add(name));
            },
            remove: (...names) => {
                names.forEach((name) => classes.delete(name));
            },
            toggle: (name, force) => {
                const shouldAdd =
                    force === undefined
                        ? !classes.has(name)
                        : Boolean(force);

                if (shouldAdd) {
                    classes.add(name);
                } else {
                    classes.delete(name);
                }

                return shouldAdd;
            },
            contains: (name) => classes.has(name),
        },
        setAttribute: (name, value) => {
            attributes[name] = String(value);
        },
        getAttribute: (name) =>
            name in attributes ? attributes[name] : null,
        addEventListener: () => {},
    };
}

const elements = {};

function el(id) {
    if (!elements[id]) {
        elements[id] = createElement();
    }

    return elements[id];
}

// The elements the dashboard reads/writes during a test run.
[
    "download",
    "upload",
    "ping",
    "jitter",
    "packetLoss",
    "score",
    "testMessage",
    "startTest",
    "startTestLabel",
    "status",
    "networkStatusDot",
    "metricsSubtitle",
    "networkType",
    "networkTypeDetail",
    "averageSpeed",
    "averagePing",
    "peakSpeed",
    "downtime",
    "sessionTime",
    "recommendation",
].forEach(el);

// Require AFTER the stub registry exists but BEFORE global.document is
// installed: at require time script.js only initialises the app when
// `document` is already defined, and initialisation needs a real browser
// (window, localStorage, timers). The stub is installed below so the
// exported functions can run against it in Node.
const { smartConnectivity: api } = require("../js/script.js");

global.document = {
    getElementById: (id) => elements[id] || null,
    readyState: "complete",
    addEventListener: () => {},
};

/* ─── Stubbed fetch ─────────────────────────────────────── */

const FIRST_METRICS = {
    download_mbps: 85.4,
    upload_mbps: 42.1,
    ping_ms: 14.5,
    jitter_ms: 1.8,
    packet_loss: 0.0,
};

const SECOND_METRICS = {
    download_mbps: 120,
    upload_mbps: 60,
    ping_ms: 10,
    jitter_ms: 1,
    packet_loss: 0.5,
};

const fetchCalls = [];
let backendBehaviour = "metrics"; // "metrics" | "pending" | "empty"
let backendMetrics = { ...FIRST_METRICS };
let backendDeferred = null;

function deferred() {
    let resolve;
    let reject;
    const promise = new Promise((res, rej) => {
        resolve = res;
        reject = rej;
    });

    return { promise, resolve, reject };
}

global.fetch = async (url) => {
    fetchCalls.push(String(url));

    if (String(url).includes("/network-quality")) {
        if (backendBehaviour === "pending") {
            return backendDeferred.promise;
        }

        if (backendBehaviour === "empty") {
            return { ok: true, json: async () => ({}) };
        }

        return { ok: true, json: async () => ({ ...backendMetrics }) };
    }

    if (String(url).includes("/network-test")) {
        return { ok: true, json: async () => ({}) };
    }

    if (String(url).includes("/ai/analyze")) {
        return { ok: false, status: 503, json: async () => ({}) };
    }

    // Latency probes and anything else: fail fast, no samples.
    throw new Error(`stubbed fetch failure for ${url}`);
};

function networkQualityCalls() {
    return fetchCalls.filter((url) => url.includes("/network-quality"))
        .length;
}

// Node 24 ships a getter-only global `navigator` (no setter), so
// `global.navigator = { onLine: false }` silently does nothing and the
// implementation keeps seeing the device as online. Tests that need to
// simulate offline must replace it with defineProperty and restore the
// original descriptor afterwards.
const originalNavigatorDescriptor = Object.getOwnPropertyDescriptor(
    globalThis,
    "navigator"
);

function setNavigatorOnline(onLine) {
    Object.defineProperty(globalThis, "navigator", {
        value: { onLine },
        configurable: true,
        writable: true,
    });
}

function restoreNavigator() {
    if (originalNavigatorDescriptor) {
        Object.defineProperty(
            globalThis,
            "navigator",
            originalNavigatorDescriptor
        );
    } else {
        delete globalThis.navigator;
    }
}

async function runSuccessfulTest(metrics = FIRST_METRICS) {
    backendBehaviour = "metrics";
    backendMetrics = { ...metrics };
    await api.startNetworkTest();
}

/* ─── Tests ─────────────────────────────────────────────── */

test("previous results stay visible during a test and new results appear only after success", async () => {
    await runSuccessfulTest(FIRST_METRICS);

    assert.equal(el("download").textContent, "85.4");
    assert.equal(el("upload").textContent, "42.1");
    assert.equal(el("ping").textContent, "14.5");
    assert.equal(el("testMessage").textContent, "Network test completed successfully.");

    // Start a second run whose backend response is held back, so the
    // test is in-flight while we inspect the dashboard.
    backendBehaviour = "pending";
    backendDeferred = deferred();

    const run = api.startNetworkTest();

    // The synchronous prefix of startNetworkTest has already run:
    // loading state on, previous results still displayed.
    assert.equal(el("testMessage").textContent, "Testing network...");
    assert.equal(el("download").textContent, "85.4");
    assert.equal(el("upload").textContent, "42.1");
    assert.equal(el("ping").textContent, "14.5");
    assert.notEqual(el("download").textContent, "Unavailable");
    assert.equal(el("status").textContent, "Testing");
    assert.equal(el("startTest").getAttribute("aria-busy"), "true");
    assert.equal(el("startTestLabel").textContent, "Testing...");

    backendDeferred.resolve({
        ok: true,
        json: async () => ({ ...SECOND_METRICS }),
    });
    await run;

    // Only now are the new measurements displayed.
    assert.equal(el("download").textContent, "120.0");
    assert.equal(el("upload").textContent, "60.0");
    assert.equal(el("ping").textContent, "10.0");
    assert.equal(el("testMessage").textContent, "Network test completed successfully.");
    assert.equal(el("startTest").getAttribute("aria-busy"), "false");
    assert.equal(el("startTestLabel").textContent, "Start Test");
});

test("multiple simultaneous test requests are prevented", async () => {
    await runSuccessfulTest(FIRST_METRICS);

    backendBehaviour = "pending";
    backendDeferred = deferred();

    const callsBefore = networkQualityCalls();
    const first = api.startNetworkTest();
    const second = api.startNetworkTest(); // ignored while a test runs

    await second;

    assert.equal(networkQualityCalls(), callsBefore + 1);
    assert.equal(el("testMessage").textContent, "Testing network...");

    backendDeferred.resolve({
        ok: true,
        json: async () => ({ ...SECOND_METRICS }),
    });
    await first;

    assert.equal(el("download").textContent, "120.0");
});

test("an offline interruption restores the previous metrics and clears the loading state", async () => {
    await runSuccessfulTest(FIRST_METRICS);

    backendBehaviour = "pending";
    backendDeferred = deferred();

    const run = api.startNetworkTest();

    assert.equal(el("download").textContent, "85.4");

    // Device goes offline mid-test; the backend then resolves.
    setNavigatorOnline(false);
    backendDeferred.resolve({
        ok: true,
        json: async () => ({ ...SECOND_METRICS }),
    });
    await run;

    // While offline the dashboard shows the Offline state, and the
    // loading state is cleared.
    assert.equal(el("download").textContent, "Unavailable");
    assert.equal(
        el("testMessage").textContent,
        "Your device is offline. Connect to a network first."
    );
    assert.equal(el("startTest").getAttribute("aria-busy"), "false");
    assert.equal(el("startTestLabel").textContent, "Start Test");

    // ...but the previous results were restored into state: back online,
    // they reappear without running a new test.
    restoreNavigator();
    api.updateDashboard();

    assert.equal(el("download").textContent, "85.4");
    assert.equal(api.getCurrentNetworkData().download, 85.4);
});

test("a run with no measurements at all is a failure and restores the previous metrics", async () => {
    await runSuccessfulTest(FIRST_METRICS);

    // Backend returns an empty object: no usable measurements.
    backendBehaviour = "empty";
    await api.startNetworkTest();

    assert.match(el("testMessage").textContent, /failed/i);
    assert.equal(el("download").textContent, "85.4");
    assert.equal(el("upload").textContent, "42.1");
    assert.equal(api.getCurrentNetworkData().download, 85.4);
    assert.equal(el("startTest").getAttribute("aria-busy"), "false");
    assert.equal(el("startTestLabel").textContent, "Start Test");
});
