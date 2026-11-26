const { describe, it } = require("node:test");
const assert = require("node:assert/strict");

const metrics = require("../js/metrics.js");
const networkStatus = require("../js/network-status.js");
const scriptExports = require("../js/script.js");

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

    describe("js/script.js backwards-compatible re-exports", () => {
        it("re-exports extracted module functions identically", () => {
            assert.strictEqual(scriptExports.formatMetric, metrics.formatMetric);
            assert.strictEqual(scriptExports.formatNetworkMetric, metrics.formatNetworkMetric);
            assert.strictEqual(scriptExports.resolveNetworkType, networkStatus.resolveNetworkType);
            assert.strictEqual(
                scriptExports.resolveDashboardDisplayState,
                networkStatus.resolveDashboardDisplayState
            );
        });
    });
});
