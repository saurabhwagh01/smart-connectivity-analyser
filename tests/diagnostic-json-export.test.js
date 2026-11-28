
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { describe, it } = require("node:test");
const assert = require("node:assert/strict");

const { buildDiagnosticJSON } = require("../js/script.js");

function createExportTestContext() {
    const downloads = [];
    const revokedUrls = [];

    const elements = {
        toast: {
            classList: {
                add() {},
                remove() {}
            }
        },
        "toast-message": {
            textContent: ""
        }
    };

    const document = {
        readyState: "loading",

        addEventListener() {},

        getElementById(id) {
            return elements[id] || null;
        },

        createElement(tag) {
            assert.equal(tag, "a");

            const link = {
                click() {
                    downloads.push({
                        href: this.href,
                        download: this.download
                    });
                },

                remove() {
                    this.removed = true;
                }
            };

            return link;
        },

        body: {
            appendChild(link) {
                link.appended = true;
            }
        }
    };

    const URLMock = {
        createObjectURL(blob) {
            const url = `blob:test-${downloads.length}`;
            downloads.push({ blob, url });
            return url;
        },

        revokeObjectURL(url) {
            revokedUrls.push(url);
        }
    };

    const sandbox = {
        console,
        document,
        URL: URLMock,
        Blob,
        setTimeout,
        clearTimeout,
        Math,
        Date
    };

    sandbox.globalThis = sandbox;

    const context = vm.createContext(sandbox);

    const scripts = [
        "../js/connectivity-score.js",
        "../js/metrics.js",
        "../js/network-status.js",
        "../js/script.js"
    ];

    for (const script of scripts) {
        const source = fs.readFileSync(
            path.join(__dirname, script),
            "utf8"
        );

        vm.runInContext(source, context, {
            filename: script
        });
    }

    return {
        context,
        downloads,
        revokedUrls,
        elements
    };
}

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

        assert.deepEqual(
            Object.keys(report).sort(),
            [
                "schema_version",
                "exported_at",
                "diagnostic",
                "measurement_metadata",
                "metrics"
            ].sort()
        );

        assert.equal(report.schema_version, "1.0.0");
        assert.equal(report.exported_at, "2026-11-27T06:10:00.000Z");

        assert.deepEqual(
            Object.keys(report.diagnostic).sort(),
            [
                "status",
                "result_status",
                "timestamp",
                "network_type"
            ].sort()
        );

        assert.equal(report.diagnostic.status, "completed");
        assert.equal(report.diagnostic.result_status, "complete");
        assert.equal(report.diagnostic.timestamp, diagnostic.timestamp);
        assert.equal(report.diagnostic.network_type, "Wi-Fi");

        assert.deepEqual(
            Object.keys(report.measurement_metadata).sort(),
            ["source", "units"].sort()
        );

        assert.equal(
            report.measurement_metadata.source,
            "Smart Connectivity Analyser"
        );

        assert.deepEqual(
            Object.keys(report.measurement_metadata.units).sort(),
            [
                "download_mbps",
                "upload_mbps",
                "ping_ms",
                "jitter_ms",
                "packet_loss_percent",
                "connectivity_score"
            ].sort()
        );

        assert.deepEqual(
            report.measurement_metadata.units,
            {
                download_mbps: "Mbps",
                upload_mbps: "Mbps",
                ping_ms: "ms",
                jitter_ms: "ms",
                packet_loss_percent: "%",
                connectivity_score: "score"
            }
        );

        assert.deepEqual(
            Object.keys(report.metrics).sort(),
            [
                "download_mbps",
                "upload_mbps",
                "ping_ms",
                "jitter_ms",
                "packet_loss_percent",
                "connectivity_score"
            ].sort()
        );

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

    it("accepts valid upper boundary values for packet loss and score", () => {
        const diagnostic = {
            download: 0,
            upload: 0,
            ping: 0,
            jitter: 0,
            packetLoss: 100,
            score: 100,
            networkType: "Wi-Fi",
            timestamp: "2026-11-27T06:00:00.000Z"
        };

        const report = buildDiagnosticJSON(diagnostic);

        assert.equal(report.metrics.packet_loss_percent, 100);
        assert.equal(report.metrics.connectivity_score, 100);
        assert.equal(report.diagnostic.result_status, "complete");
    });

    it("converts negative and out-of-range metric values to null", () => {
        const diagnostic = {
            download: -10,
            upload: -5,
            ping: -20,
            jitter: -2,
            packetLoss: 101,
            score: 150,
            networkType: "Wi-Fi",
            timestamp: "2026-11-27T06:00:00.000Z"
        };

        const report = buildDiagnosticJSON(diagnostic);

        for (const value of Object.values(report.metrics)) {
            assert.equal(value, null);
        }

        assert.equal(report.diagnostic.result_status, "partial");
    });

    it("converts non-finite and non-numeric metric values to null", () => {
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

    it("downloads a completed diagnostic as a JSON file", () => {
        const {
            context,
            downloads,
            revokedUrls
        } = createExportTestContext();

        vm.runInContext(`
            lastCompletedDiagnostic = {
                download: 100,
                upload: 50,
                ping: 20,
                jitter: 5,
                packetLoss: 0,
                score: 95,
                networkType: "Wi-Fi",
                timestamp: "2026-11-27T06:00:00.000Z"
            };
        `, context);

        context.exportDiagnosticToJSON();

        const blobEntry = downloads.find(entry => entry.blob);

        assert.ok(blobEntry, "Expected a JSON Blob to be created");

        assert.equal(
            blobEntry.blob.type,
            "application/json;charset=utf-8"
        );

        assert.equal(
            downloads.some(entry =>
                entry.download === "connectivity-diagnostic-2026-11-27.json"
            ),
            true
        );

        assert.deepEqual(revokedUrls, ["blob:test-0"]);
    });

    it("preserves the previous completed diagnostic when the next diagnostic fails", async () => {
        const {
            context,
            downloads
        } = createExportTestContext();

        const successfulMetrics = {
            download: 100,
            upload: 50,
            ping: 20,
            jitter: 5,
            packetLoss: 0,
            score: 95,
            networkType: "Wi-Fi"
        };

        const successfulTimestamp = "2026-11-27T06:00:00.000Z";

        const failedMetrics = {
            download: 0,
            upload: 0,
            ping: 0,
            jitter: 0,
            packetLoss: 100,
            score: 0,
            networkType: "Wi-Fi"
        };

        // Store the previous successful diagnostic.
        context.preserveLastCompletedDiagnostic(
            { state: "success" },
            successfulMetrics,
            successfulTimestamp
        );

        // A failed diagnostic must not overwrite the previous one.
        context.preserveLastCompletedDiagnostic(
            { state: "error" },
            failedMetrics,
            "2026-11-27T06:10:00.000Z"
        );

        // Export should still contain the previous successful diagnostic.
        context.exportDiagnosticToJSON();

        const blobEntry = downloads.find(entry => entry.blob);

        assert.ok(blobEntry, "Expected a JSON Blob to be created");

        const exportedReport = JSON.parse(await blobEntry.blob.text());

        assert.equal(
            exportedReport.diagnostic.timestamp,
            successfulTimestamp
        );

        assert.equal(exportedReport.metrics.download_mbps, 100);
        assert.equal(exportedReport.metrics.upload_mbps, 50);
        assert.equal(exportedReport.metrics.ping_ms, 20);
        assert.equal(exportedReport.metrics.jitter_ms, 5);
        assert.equal(exportedReport.metrics.connectivity_score, 95);
        assert.equal(exportedReport.metrics.packet_loss_percent, 0);
        assert.equal(exportedReport.diagnostic.network_type, "Wi-Fi");
    });

    it("does not export when no completed diagnostic exists", () => {
        const {
            context,
            downloads,
            elements
        } = createExportTestContext();

        context.exportDiagnosticToJSON();

        assert.equal(downloads.length, 0);

        assert.equal(
            elements["toast-message"].textContent,
            "No completed diagnostic available to export."
        );
    });

    it("handles JSON export failures gracefully", () => {
        const {
            context,
            downloads,
            elements
        } = createExportTestContext();

        vm.runInContext(`
            lastCompletedDiagnostic = {
                download: 100,
                upload: 50,
                ping: 20,
                jitter: 5,
                packetLoss: 0,
                score: 95,
                networkType: "Wi-Fi",
                timestamp: "2026-11-27T06:00:00.000Z"
            };
        `, context);

        context.URL.createObjectURL = () => {
            throw new Error("Simulated download failure");
        };

        assert.doesNotThrow(() => {
            context.exportDiagnosticToJSON();
        });

        assert.equal(downloads.length, 0);

        assert.equal(
            elements["toast-message"].textContent,
            "Could not export diagnostic JSON."
        );
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
});
