
const { describe, it } = require("node:test");
const assert = require("node:assert/strict");

const { buildDiagnosticJSON } = require("../js/script.js");

describe("Diagnostic JSON Export", () => {
    it("exports a complete diagnostic with the correct schema", () => {
        const diagnostic = {
            download: 100,
            upload: 50,
            ping: 20,
            jitter: 5,
            packetLoss: 0,
            score: 95,
            networkType: "Wi-Fi",
            timestamp: "2026-11-27T06:00:00.000Z"
        };

        const report = buildDiagnosticJSON(
            diagnostic,
            "2026-11-27T06:10:00.000Z"
        );

        assert.equal(report.schema_version, "1.0.0");
        assert.equal(report.exported_at, "2026-11-27T06:10:00.000Z");
        assert.equal(report.diagnostic.status, "completed");
        assert.equal(report.diagnostic.result_status, "complete");

        assert.equal(report.metrics.download_mbps, 100);
        assert.equal(report.metrics.upload_mbps, 50);
        assert.equal(report.metrics.ping_ms, 20);
        assert.equal(report.metrics.jitter_ms, 5);
        assert.equal(report.metrics.packet_loss_percent, 0);
        assert.equal(report.metrics.connectivity_score, 95);
    });

    it("represents unavailable metrics as null in partial results", () => {
        const diagnostic = {
            download: 80,
            upload: null,
            ping: 25,
            jitter: null,
            packetLoss: null,
            score: 70,
            networkType: "Wi-Fi",
            timestamp: "2026-11-27T06:00:00.000Z"
        };

        const report = buildDiagnosticJSON(diagnostic);

        assert.equal(report.diagnostic.result_status, "partial");

        assert.equal(report.metrics.download_mbps, 80);
        assert.equal(report.metrics.upload_mbps, null);
        assert.equal(report.metrics.ping_ms, 25);
        assert.equal(report.metrics.jitter_ms, null);
        assert.equal(report.metrics.packet_loss_percent, null);
        assert.equal(report.metrics.connectivity_score, 70);
    });

    it("preserves zero values instead of treating them as unavailable", () => {
        const diagnostic = {
            download: 0,
            upload: 0,
            ping: 0,
            jitter: 0,
            packetLoss: 0,
            score: 0,
            networkType: "Ethernet",
            timestamp: "2026-11-27T06:00:00.000Z"
        };

        const report = buildDiagnosticJSON(diagnostic);

        assert.equal(report.diagnostic.result_status, "complete");

        for (const value of Object.values(report.metrics)) {
            assert.equal(value, 0);
        }
    });

    it("does not export sensitive location information", () => {
        const diagnostic = {
            download: 10,
            upload: 5,
            ping: 30,
            jitter: 2,
            packetLoss: 0,
            score: 80,
            networkType: "Wi-Fi",
            timestamp: "2026-11-27T06:00:00.000Z",
            latitude: 28.6139,
            longitude: 77.2090
        };

        const report = buildDiagnosticJSON(diagnostic);
        const exportedJSON = JSON.stringify(report);

        assert.equal("latitude" in report, false);
        assert.equal("longitude" in report, false);
        assert.equal(exportedJSON.includes("28.6139"), false);
        assert.equal(exportedJSON.includes("77.209"), false);
    });

    it("converts invalid metric values to null", () => {
        const diagnostic = {
            download: NaN,
            upload: Infinity,
            ping: "25.6",
            jitter: -Infinity,
            packetLoss: undefined,
            score: 85,
            networkType: "Wi-Fi",
            timestamp: "2026-11-27T06:00:00.000Z"
        };

        const report = buildDiagnosticJSON(diagnostic);

        assert.equal(report.metrics.download_mbps, null);
        assert.equal(report.metrics.upload_mbps, null);
        assert.equal(report.metrics.ping_ms, null);
        assert.equal(report.metrics.jitter_ms, null);
        assert.equal(report.metrics.packet_loss_percent, null);
        assert.equal(report.metrics.connectivity_score, 85);
    });
});
