/* =========================================================
   SESSION STATISTICS TESTS
   Run with: node --test tests/session-statistics.test.js
   ========================================================= */

const { describe, test } = require("node:test");
const assert = require("node:assert/strict");

const {
    calculateSessionStatistics,
    isValidMetric
} = require("../js/connectivity-score.js");


describe("isValidMetric", () => {
    test("valid numbers and zero", () => {
        assert.equal(isValidMetric(0), true);
        assert.equal(isValidMetric(0.0), true);
        assert.equal(isValidMetric(15.4), true);
        assert.equal(isValidMetric("24.5"), true);
        assert.equal(isValidMetric("0"), true);
    });

    test("missing, null, or undefined values", () => {
        assert.equal(isValidMetric(null), false);
        assert.equal(isValidMetric(undefined), false);
    });

    test("invalid types and non-finite values", () => {
        assert.equal(isValidMetric(""), false);
        assert.equal(isValidMetric("   "), false);
        assert.equal(isValidMetric("not-a-number"), false);
        assert.equal(isValidMetric(true), false);
        assert.equal(isValidMetric(false), false);
        assert.equal(isValidMetric(NaN), false);
        assert.equal(isValidMetric(Infinity), false);
        assert.equal(isValidMetric(-Infinity), false);
        assert.equal(isValidMetric({}), false);
        assert.equal(isValidMetric([]), false);
    });
});


describe("calculateSessionStatistics", () => {
    test("empty session returns null for averages", () => {
        const stats = calculateSessionStatistics([]);
        assert.equal(stats.averageSpeed, null);
        assert.equal(stats.averagePing, null);
        assert.equal(stats.peakSpeed, null);
        assert.equal(stats.poorTestCount, 0);
    });

    test("missing ping values are not converted to 0", () => {
        const session = [
            { download_mbps: 45, ping_ms: null, connectivity_score: 80 }
        ];
        const stats = calculateSessionStatistics(session);

        assert.equal(stats.averagePing, null);
        assert.notEqual(stats.averagePing, 0);
    });

    test("session with all missing ping values returns null for averagePing", () => {
        const session = [
            { download_mbps: 50, ping_ms: null },
            { download_mbps: 60, ping_ms: undefined },
            { download_mbps: 70, ping_ms: "" }
        ];
        const stats = calculateSessionStatistics(session);

        assert.equal(stats.averagePing, null);
        assert.equal(stats.averageSpeed, 60);
        assert.equal(stats.peakSpeed, 70);
    });

    test("valid zero ping remains distinguishable from missing ping", () => {
        const sessionWithZero = [
            { download_mbps: 100, ping_ms: 0, connectivity_score: 95 }
        ];
        const sessionWithNull = [
            { download_mbps: 100, ping_ms: null, connectivity_score: 75 }
        ];

        const statsZero = calculateSessionStatistics(sessionWithZero);
        const statsNull = calculateSessionStatistics(sessionWithNull);

        assert.equal(statsZero.averagePing, 0);
        assert.equal(statsNull.averagePing, null);
        assert.notEqual(statsZero.averagePing, statsNull.averagePing);
    });

    test("average calculations exclude unavailable measurements", () => {
        const session = [
            { download_mbps: 100, ping_ms: 20 },
            { download_mbps: 50, ping_ms: null },
            { download_mbps: null, ping_ms: 40 }
        ];
        const stats = calculateSessionStatistics(session);

        // Ping average should be (20 + 40) / 2 = 30, NOT (20 + 0 + 40) / 3 = 20
        assert.equal(stats.averagePing, 30);

        // Speed average should be (100 + 50) / 2 = 75, NOT (100 + 50 + 0) / 3 = 50
        assert.equal(stats.averageSpeed, 75);
        assert.equal(stats.peakSpeed, 100);
    });

    test("valid zero values are included in average calculations", () => {
        const session = [
            { download_mbps: 0, ping_ms: 0 },
            { download_mbps: 100, ping_ms: 20 }
        ];
        const stats = calculateSessionStatistics(session);

        // (0 + 20) / 2 = 10
        assert.equal(stats.averagePing, 10);
        // (0 + 100) / 2 = 50
        assert.equal(stats.averageSpeed, 50);
        assert.equal(stats.peakSpeed, 100);
    });

    test("invalid and non-numeric metrics are excluded from calculations", () => {
        const session = [
            { download_mbps: "invalid", ping_ms: false },
            { download_mbps: 30, ping_ms: 15 },
            { download_mbps: null, ping_ms: NaN }
        ];
        const stats = calculateSessionStatistics(session);

        assert.equal(stats.averageSpeed, 30);
        assert.equal(stats.averagePing, 15);
        assert.equal(stats.peakSpeed, 30);
    });

    test("poor test count counts only low connectivity scores", () => {
        const session = [
            { connectivity_score: 25 },
            { connectivity_score: 80 },
            { connectivity_score: null },
            { connectivity_score: 15 }
        ];
        const stats = calculateSessionStatistics(session);

        assert.equal(stats.poorTestCount, 2);
    });
});

