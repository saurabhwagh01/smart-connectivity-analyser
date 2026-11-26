const { describe, it } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const metrics = require("../js/metrics.js");
const networkStatus = require("../js/network-status.js");
const scriptExports = require("../js/script.js");

function createBrowserSandbox() {
    const sandbox = {
        console,
        Math,
        Number,
        Object,
        String,
        Boolean,
        Array
    };
    sandbox.globalThis = sandbox;
    return vm.createContext(sandbox);
}

function loadBrowserScript(context, relativePath) {
    const fullPath = path.join(__dirname, "..", relativePath);
    const code = fs.readFileSync(fullPath, "utf8");
    vm.runInContext(code, context, { filename: relativePath });
}

describe("Modular Frontend Architecture", () => {
    describe("js/metrics.js standalone module", () => {
        it("validates and formats metrics independently of script.js", () => {
            assert.equal(metrics.isValidMetric(0), true);
            assert.equal(metrics.isValidMetric(null), false);
            assert.equal(metrics.safeNumber("42.5", 0), 42.5);
            assert.equal(metrics.firstValid(null, undefined, "12.3", 99), 12.3);
            assert.equal(metrics.formatNumber(12.345, 1), "12.3");
            assert.equal(metrics.formatMetric(null), "Unavailable");
            assert.equal(metrics.formatNetworkMetric("download", 50), "50.0 Mbps");
            assert.equal(metrics.formatNetworkMetric("packetLoss", 0), "0.0 %");
        });
    });

    describe("js/network-status.js standalone module", () => {
        it("resolves network types and offline state independently", () => {
            assert.deepEqual(networkStatus.resolveNetworkType(null, false), {
                type: "Offline",
                detail: "No internet connection",
                isKnown: true,
                effectiveType: null
            });

            assert.equal(networkStatus.isDeviceOffline(null, false), true);
            assert.equal(networkStatus.isDeviceOffline({ type: "wifi" }, true), false);
            assert.equal(
                networkStatus.resolveNetworkType({ type: "ethernet" }, true).type,
                "Ethernet"
            );
        });

        it("resolves connectivity indicator and dashboard display state", () => {
            const indicator = networkStatus.resolveConnectivityIndicator(85);
            assert.equal(indicator.status, "Excellent");
            assert.equal(indicator.dotClass, "excellent");

            const offlineState = networkStatus.resolveDashboardDisplayState(
                { download: 100 },
                { isOffline: true }
            );
            assert.equal(offlineState.download, "Unavailable");
            assert.equal(offlineState.score, 0);
            assert.equal(offlineState.indicator.status, "Offline");
        });
    });

    describe("Browser environment compatibility (no Node.js require)", () => {
        it("loads js/metrics.js and exposes METRIC_UNITS and helpers on globalThis", () => {
            const ctx = createBrowserSandbox();
            loadBrowserScript(ctx, "js/metrics.js");

            assert.equal(typeof ctx.globalThis.METRIC_UNITS, "object");
            assert.equal(ctx.globalThis.METRIC_UNITS.download, "Mbps");
            assert.equal(ctx.globalThis.formatMetric(null), "Unavailable");
            assert.equal(ctx.globalThis.formatNetworkMetric("ping", 25), "25.0 ms");
            assert.equal(ctx.globalThis.isValidMetric(0), true);
            assert.equal(ctx.globalThis.safeNumber("10.5", 0), 10.5);
            assert.equal(ctx.globalThis.firstValid(null, "7.2"), 7.2);
        });

        it("loads js/network-status.js in browser without require and resolves state", () => {
            const ctx = createBrowserSandbox();
            loadBrowserScript(ctx, "js/connectivity-score.js");
            loadBrowserScript(ctx, "js/metrics.js");
            loadBrowserScript(ctx, "js/network-status.js");

            assert.equal(typeof ctx.globalThis.resolveNetworkType, "function");
            assert.equal(
                ctx.globalThis.resolveNetworkType({ type: "wifi" }, true).type,
                "Wi-Fi"
            );
            assert.equal(ctx.globalThis.isDeviceOffline(null, false), true);

            const displayState = ctx.globalThis.resolveDashboardDisplayState(
                { download: 100, upload: 50, ping: 10, jitter: 2, packetLoss: 0 },
                { isOffline: false }
            );
            assert.equal(displayState.download, "100.0");
            assert.equal(displayState.indicator.status, "Excellent");
        });
    });

    describe("js/script.js backwards-compatible re-exports", () => {
        it("re-exports all extracted metrics helpers and constants identically", () => {
            const metricKeys = [
                "METRIC_UNITS",
                "isValidMetric",
                "safeNumber",
                "firstValid",
                "isValidMetricNumber",
                "formatNumber",
                "formatMetric",
                "formatNetworkMetric"
            ];
            for (const key of metricKeys) {
                assert.strictEqual(
                    scriptExports[key],
                    metrics[key],
                    `Expected script.js to re-export ${key}`
                );
            }
        });

        it("re-exports all extracted network-status helpers identically", () => {
            const networkKeys = [
                "getBrowserConnection",
                "resolveNetworkType",
                "isDeviceOffline",
                "resolveConnectivityIndicator",
                "resolveDashboardDisplayState"
            ];
            for (const key of networkKeys) {
                assert.strictEqual(
                    scriptExports[key],
                    networkStatus[key],
                    `Expected script.js to re-export ${key}`
                );
            }
        });
    });
});
