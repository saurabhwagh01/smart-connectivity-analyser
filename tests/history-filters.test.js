
const { describe, test } = require("node:test");
const assert = require("node:assert/strict");

const {
    validateHistoryFilterValues,
    normalizeHistoryItem
} = require("../js/script.js");


describe("Network history filter validation", () => {

    test("accepts empty filters", () => {
        const result = validateHistoryFilterValues({});

        assert.equal(result.valid, true);
    });

    test("accepts a valid date range", () => {
        const result = validateHistoryFilterValues({
            startDate: "2026-11-01",
            endDate: "2026-11-05"
        });

        assert.equal(result.valid, true);
    });

    test("rejects reversed date ranges", () => {
        const result = validateHistoryFilterValues({
            startDate: "2026-11-05",
            endDate: "2026-11-01"
        });

        assert.equal(result.valid, false);
    });

    test("rejects invalid calendar dates", () => {
        const result = validateHistoryFilterValues({
            startDate: "2026-13-40"
        });

        assert.equal(result.valid, false);
    });

    test("accepts score boundaries", () => {
        const result = validateHistoryFilterValues({
            minScore: "0",
            maxScore: "100"
        });

        assert.equal(result.valid, true);
    });

    test("rejects scores outside the allowed range", () => {
        const result = validateHistoryFilterValues({
            minScore: "-5"
        });

        assert.equal(result.valid, false);
    });

    test("rejects non-numeric scores", () => {
        const result = validateHistoryFilterValues({
            maxScore: "excellent"
        });

        assert.equal(result.valid, false);
    });

    test("rejects minimum score greater than maximum score", () => {
        const result = validateHistoryFilterValues({
            minScore: "90",
            maxScore: "60"
        });

        assert.equal(result.valid, false);
    });

    test("accepts decimal scores", () => {
        const result = validateHistoryFilterValues({
            minScore: "65.5",
            maxScore: "89.9"
        });

        assert.equal(result.valid, true);
        assert.equal(result.filters.minScore, 65.5);
        assert.equal(result.filters.maxScore, 89.9);
    });

});

describe("Network history item normalization for graphs", () => {

    test("maps all 5 metrics plus connectivity score correctly", () => {
        const raw = {
            id: 42,
            network_type: "Wi-Fi",
            timestamp: "2026-11-20T10:00:00.000Z",
            download_mbps: 45.2,
            upload_mbps: 15.6,
            ping_ms: 22,
            jitter_ms: 3.4,
            packet_loss: 0.5,
            connectivity_score: 92
        };

        const item = normalizeHistoryItem(raw);

        assert.equal(item.id, 42);
        assert.equal(item.network_type, "Wi-Fi");
        assert.equal(item.timestamp, "2026-11-20T10:00:00.000Z");
        assert.equal(item.download_mbps, 45.2);
        assert.equal(item.upload_mbps, 15.6);
        assert.equal(item.ping, 22);
        assert.equal(item.jitter, 3.4);
        assert.equal(item.packet_loss, 0.5);
        assert.equal(item.connectivity_score, 92);
    });

    test("maps alternative property name aliases correctly", () => {
        const raw = {
            id: "9",
            created_at: "2026-11-20T12:00:00.000Z",
            downloadSpeed: 50.0,
            uploadSpeed: 20.0,
            ping: 18,
            jitter: 2.1,
            packetLoss: 0.0,
            score: 95
        };

        const item = normalizeHistoryItem(raw);

        assert.equal(item.id, 9);
        assert.equal(item.timestamp, "2026-11-20T12:00:00.000Z");
        assert.equal(item.download_mbps, 50.0);
        assert.equal(item.upload_mbps, 20.0);
        assert.equal(item.ping, 18);
        assert.equal(item.jitter, 2.1);
        assert.equal(item.packet_loss, 0.0);
        assert.equal(item.connectivity_score, 95);
    });

    test("handles null or missing metrics gracefully without throwing", () => {
        const item = normalizeHistoryItem({});

        assert.ok(item.timestamp);
        assert.equal(item.download_mbps, null);
        assert.equal(item.upload_mbps, null);
        assert.equal(item.ping, null);
        assert.equal(item.jitter, null);
        assert.equal(item.packet_loss, null);
        assert.equal(item.connectivity_score, null);
    });

});
