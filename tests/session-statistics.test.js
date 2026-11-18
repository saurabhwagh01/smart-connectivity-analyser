const { describe, it } = require("node:test");
const assert = require("node:assert/strict");

const {
    calculateSessionStatistics,
    resolveDashboardDisplayState
} = require("../js/script.js");

describe("Session statistics and unavailable metrics", () => {
    it("excludes unavailable and invalid values from statistics", () => {
        const result = calculateSessionStatistics([
            { download_mbps: 10, ping_ms: 20 },
            { download_mbps: null, ping_ms: null },
            { download_mbps: undefined, ping_ms: undefined },
            { download_mbps: "invalid", ping_ms: "invalid" },
            { download_mbps: "   ", ping_ms: "   " },
            { download_mbps: NaN, ping_ms: NaN },
            { download_mbps: false, ping_ms: true },
            { download_mbps: [], ping_ms: {} },
            { download_mbps: 0, ping_ms: 0 }
        ]);

        assert.equal(result.averageSpeed, 5);
        assert.equal(result.averagePing, 10);
        assert.equal(result.peakSpeed, 10);
    });

    it("returns null when all measurements are unavailable", () => {
        const result = calculateSessionStatistics([
            { download_mbps: null, ping_ms: null },
            { download_mbps: undefined, ping_ms: undefined },
            { download_mbps: "invalid", ping_ms: "invalid" },
            { download_mbps: "   ", ping_ms: "   " }
        ]);

        assert.deepEqual(result, {
            averageSpeed: null,
            averagePing: null,
            peakSpeed: null
        });
    });

    it("preserves genuine zero measurements", () => {
        const result = calculateSessionStatistics([
            { download_mbps: 0, ping_ms: 0 },
            { download_mbps: 0, ping_ms: 0 }
        ]);

        assert.deepEqual(result, {
            averageSpeed: 0,
            averagePing: 0,
            peakSpeed: 0
        });
    });

    it("supports legacy history field names", () => {
        const result = calculateSessionStatistics([
            { download: 12, ping: 8 },
            { downloadSpeed: 18, ping: 12 }
        ]);

        assert.equal(result.averageSpeed, 15);
        assert.equal(result.averagePing, 10);
        assert.equal(result.peakSpeed, 18);
    });

    it("handles an empty session", () => {
        assert.deepEqual(calculateSessionStatistics([]), {
            averageSpeed: null,
            averagePing: null,
            peakSpeed: null
        });
    });

    it("shows Unavailable for invalid dashboard metrics", () => {
        const invalidValues = [
            null,
            undefined,
            NaN,
            "",
            "   ",
            "invalid",
            false,
            [],
            {}
        ];

        const metricNames = [
            "download",
            "upload",
            "ping",
            "jitter",
            "packetLoss"
        ];

        for (const value of invalidValues) {
            const state = resolveDashboardDisplayState({
                download: value,
                upload: value,
                ping: value,
                jitter: value,
                packetLoss: value,
                score: 50
            });

            for (const metric of metricNames) {
                assert.equal(
                    state[metric],
                    "Unavailable",
                    `${metric} should be unavailable for ${String(value)}`
                );
            }
        }
    });

    it("continues displaying genuine zero for all five dashboard metrics", () => {
        const state = resolveDashboardDisplayState({
            download: 0,
            upload: 0,
            ping: 0,
            jitter: 0,
            packetLoss: 0,
            score: 0
        });

        for (const metric of [
            "download",
            "upload",
            "ping",
            "jitter",
            "packetLoss"
        ]) {
            assert.equal(state[metric], "0.0");
        }
    });
});
