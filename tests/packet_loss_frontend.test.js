const { describe, it } = require("node:test");
const assert = require("node:assert");

const {
    formatMetric,
    formatNetworkMetric,
    isValidMetricNumber,
    resolveDashboardDisplayState,
    applyBackendMetrics,
    currentMetrics,
    clearLiveMetrics,
} = require("../js/script.js");

describe("Phase 5C: Frontend Packet Loss Display Tests", () => {
    describe("formatMetric and formatNetworkMetric for packet loss", () => {
        it("displays 0% as '0.0 %' and never as 'Unavailable'", () => {
            const formatted = formatNetworkMetric("packetLoss", 0);
            assert.strictEqual(formatted, "0.0 %");

            const formattedUnderscore = formatNetworkMetric("packet_loss", 0.0);
            assert.strictEqual(formattedUnderscore, "0.0 %");

            const rawFormatted = formatMetric(0, "%");
            assert.strictEqual(rawFormatted, "0.0 %");
        });

        it("displays partial loss correctly (e.g. 10%, 25.5%, 50%)", () => {
            assert.strictEqual(formatNetworkMetric("packetLoss", 10), "10.0 %");
            assert.strictEqual(formatNetworkMetric("packetLoss", 25.5), "25.5 %");
            assert.strictEqual(formatNetworkMetric("packetLoss", 50), "50.0 %");
        });

        it("displays 100% loss correctly as '100.0 %'", () => {
            assert.strictEqual(formatNetworkMetric("packetLoss", 100), "100.0 %");
            assert.strictEqual(formatNetworkMetric("packet_loss", 100.0), "100.0 %");
        });

        it("displays 'Unavailable' only for null, undefined, empty, NaN, or malformed values", () => {
            assert.strictEqual(formatNetworkMetric("packetLoss", null), "Unavailable");
            assert.strictEqual(formatNetworkMetric("packetLoss", undefined), "Unavailable");
            assert.strictEqual(formatNetworkMetric("packetLoss", ""), "Unavailable");
            assert.strictEqual(formatNetworkMetric("packetLoss", "   "), "Unavailable");
            assert.strictEqual(formatNetworkMetric("packetLoss", NaN), "Unavailable");
            assert.strictEqual(formatNetworkMetric("packetLoss", "corrupted"), "Unavailable");
            assert.strictEqual(formatNetworkMetric("packetLoss", true), "Unavailable");
            assert.strictEqual(formatNetworkMetric("packetLoss", false), "Unavailable");
            assert.strictEqual(formatNetworkMetric("packetLoss", {}), "Unavailable");
        });
    });

    describe("resolveDashboardDisplayState with packet loss", () => {
        it("returns '0.0' for genuine 0% loss on dashboard", () => {
            const state = resolveDashboardDisplayState({
                download: 50.0,
                upload: 10.0,
                ping: 25.0,
                jitter: 3.0,
                packetLoss: 0,
                score: 95,
            });
            assert.strictEqual(state.packetLoss, "0.0");
        });

        it("returns '10.0' for 10% partial loss on dashboard", () => {
            const state = resolveDashboardDisplayState({
                download: 50.0,
                upload: 10.0,
                ping: 25.0,
                jitter: 3.0,
                packetLoss: 10,
                score: 80,
            });
            assert.strictEqual(state.packetLoss, "10.0");
        });

        it("returns '100.0' for 100% packet loss on dashboard", () => {
            const state = resolveDashboardDisplayState({
                download: null,
                upload: null,
                ping: null,
                jitter: null,
                packetLoss: 100,
                score: 0,
            });
            assert.strictEqual(state.packetLoss, "100.0");
        });

        it("returns 'Unavailable' when packet loss is null or undefined", () => {
            const state = resolveDashboardDisplayState({
                download: 50.0,
                upload: 10.0,
                ping: 25.0,
                jitter: 3.0,
                packetLoss: null,
                score: 80,
            });
            assert.strictEqual(state.packetLoss, "Unavailable");
        });
    });

    describe("applyBackendMetrics integration with backend response format", () => {
        it("correctly extracts packet_loss from backend response including 0.0", () => {
            const backendResponse = {
                target: "1.1.1.1",
                packets_sent: 10,
                packets_received: 10,
                packet_loss: 0.0,
                ping_ms: 32.5,
                jitter_ms: 4.1,
                status: "excellent",
            };

            applyBackendMetrics(backendResponse);
            assert.strictEqual(currentMetrics.packetLoss, 0.0);
            assert.strictEqual(currentMetrics.ping, 32.5);
            assert.strictEqual(currentMetrics.jitter, 4.1);
        });

        it("correctly extracts partial packet_loss from backend response", () => {
            const backendResponse = {
                target: "1.1.1.1",
                packets_sent: 10,
                packets_received: 9,
                packet_loss: 10.0,
                ping_ms: 35.0,
                jitter_ms: 5.0,
                status: "excellent",
            };

            applyBackendMetrics(backendResponse);
            assert.strictEqual(currentMetrics.packetLoss, 10.0);
        });

        it("correctly extracts 100% loss when unreachable", () => {
            const backendResponse = {
                target: "1.1.1.1",
                packets_sent: 10,
                packets_received: 0,
                packet_loss: 100.0,
                ping_ms: null,
                jitter_ms: null,
                status: "unreachable",
            };

            applyBackendMetrics(backendResponse);
            assert.strictEqual(currentMetrics.packetLoss, 100.0);
        });

        it("safely handles null / missing / error backend responses without stale values", () => {
            clearLiveMetrics();
            assert.strictEqual(currentMetrics.packetLoss, null);

            // Applying null / error data does not crash or corrupt
            applyBackendMetrics(null);
            assert.strictEqual(currentMetrics.packetLoss, null);

            applyBackendMetrics({});
            assert.strictEqual(currentMetrics.packetLoss, null);

            applyBackendMetrics({ error: "Backend network-quality failed" });
            assert.strictEqual(currentMetrics.packetLoss, null);
        });
    });
});
